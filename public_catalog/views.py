from django.db.models import Q
from django.http import Http404, JsonResponse
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.generic import DetailView, TemplateView

from dlux.translations import get_current_language_code, get_strings
from dlux.utils import build_config_groups, get_system_config

from common.identity import store_name

from .forms import PublicContactForm
from .homepage import get_homepage_config, resolve_homepage, resolve_sections
from .models import PublicCatalogListing, PublicContactMessage
from .settings import contact_links, get_public_catalog_config

HOMEPAGE_PREVIEW_PERM = "public_catalog.view_publiccataloglisting"
PUBLIC_PREVIEW_LANG_ATTR = "_public_preview_language"


def _public_listings():
    listings = list(PublicCatalogListing.objects.published())
    return [
        listing
        for listing in listings
        if listing.show_when_unavailable or listing.is_available_for_public
    ]


def _listing_counts(listings):
    return {
        "total": len(listings),
        "products": sum(1 for listing in listings if listing.source_kind == "product"),
        "services": sum(1 for listing in listings if listing.source_kind == "service"),
    }


def _is_staff_preview(request):
    """Authed staff can preview the storefront (even when it is offline) via
    ?preview=1 — used by the homepage builder's live preview iframe."""
    return (
        request.GET.get("preview") == "1"
        and request.user.is_authenticated
        and request.user.has_perm(HOMEPAGE_PREVIEW_PERM)
    )


def _public_language_catalog():
    cfg = get_system_config()
    languages = cfg.get("localization", {}).get("languages") or cfg.get("languages", {}) or {}
    return cfg, languages


def _requested_public_language(request):
    raw = (request.GET.get("lang") or "").strip().lower().replace("_", "-")
    if not raw:
        return "", None, {}
    cfg, languages = _public_language_catalog()
    if raw in languages:
        return raw, cfg, languages
    base = raw.split("-", 1)[0]
    if base in languages:
        return base, cfg, languages
    return "", cfg, languages


def _apply_public_language(request):
    """Honor public ``?lang=<code>`` without leaking builder-preview choices.

    Normal public clicks persist in the session as before. Staff preview iframes
    share the authenticated staff session, so their requested edit language stays
    request-local and is applied by the landing context instead.
    """
    lang, _cfg, _languages = _requested_public_language(request)
    if not lang or not hasattr(request, "session"):
        return
    if _is_staff_preview(request):
        setattr(request, PUBLIC_PREVIEW_LANG_ATTR, lang)
        return
    request.session["lang"] = lang
    request.session["dlux_force_language_preview"] = True


def _public_language_context(lang, cfg=None, languages=None):
    cfg = cfg or get_system_config()
    languages = languages or cfg.get("localization", {}).get("languages") or cfg.get("languages", {}) or {}
    lang_config = languages.get(lang) if isinstance(languages, dict) else {}
    if not isinstance(lang_config, dict):
        lang_config = {"name": str(lang_config or lang).upper()}
    current_dir = lang_config.get("dir") or ("rtl" if lang.startswith(("ar", "fa", "he", "ur")) else "ltr")
    app_config = dict(cfg)
    app_config.update(build_config_groups(app_config, lang))
    overrides = cfg.get("localization", {}).get("translations", cfg.get("translations", None))
    return {
        "APP_CONFIG": app_config,
        "CURRENT_LANG": lang,
        "CURRENT_DIR": current_dir,
        "LANGUAGES": languages,
        "LANG_CONFIG": {**lang_config, "dir": current_dir},
        "DLUX_STRINGS": get_strings(lang, overrides=overrides),
    }


class _StorefrontGateMixin:
    # Which config flag gates this surface: shop views use "shop_enabled",
    # the landing overrides to "homepage_enabled" — so each can be toggled alone.
    gate_key = "shop_enabled"

    def dispatch(self, request, *args, **kwargs):
        _apply_public_language(request)
        cfg = get_public_catalog_config()
        if not cfg.get(self.gate_key, True) and not _is_staff_preview(request):
            return render(
                request,
                "public_catalog/coming_soon.html",
                {"public_config": cfg, "public_bare": True},
                status=503,
            )
        return super().dispatch(request, *args, **kwargs)


def _homepage_category_tiles(listings):
    tiles = {}
    for listing in listings:
        if listing.source_kind != "product":
            continue
        category = listing.product.category if listing.product_id else None
        if category is None:
            continue
        entry = tiles.setdefault(category.pk, {"name": category.name, "count": 0})
        entry["count"] += 1
    return sorted(tiles.values(), key=lambda t: (-t["count"], t["name"]))


class PublicLandingView(_StorefrontGateMixin, TemplateView):
    template_name = "public_catalog/landing.html"
    gate_key = "homepage_enabled"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cfg = get_public_catalog_config()
        # The homepage renders in the visitor's active language. Staff preview
        # iframes can request an edit language without mutating the staff session.
        active_lang = (
            getattr(self.request, PUBLIC_PREVIEW_LANG_ATTR, None)
            or get_current_language_code(self.request)
        )
        home = resolve_homepage(lang=active_lang)
        limit = cfg.get("featured_limit") or 4
        listings = _public_listings()
        featured = [listing for listing in listings if listing.is_featured][:limit]
        hero_listing = (featured or listings[:1] or [None])[0]
        services = [listing for listing in listings if listing.source_kind == "service"]

        if home.get("hero_media") == "featured":
            hero_slides = [l.image_url for l in featured if l.image_url]
            if not hero_slides and hero_listing and hero_listing.image_url:
                hero_slides = [hero_listing.image_url]
        elif home.get("hero_media") == "custom" and home.get("hero_image"):
            hero_slides = [home["hero_image"]]
        else:
            hero_slides = []

        hero_layout = home.get("hero_layout") or "poster"
        if hero_layout == "mosaic" and len(hero_slides) < 2:
            hero_layout = "poster"

        ctx.update({
            "public_config": cfg,
            "homepage_config": home,
            "homepage_sections": [s for s in resolve_sections(home) if s["enabled"]],
            "public_accent": home.get("accent"),
            "public_accent_secondary": home.get("accent_secondary"),
            "public_shell_classes": (
                f"public-style--{home.get('style_preset') or 'signature'} "
                f"public-bg--{home.get('background_treatment') or 'clean'} "
                f"public-nav--{home.get('nav_treatment') or 'glass'} "
                f"public-cardstyle--{home.get('card_treatment') or 'showcase'} "
                f"public-density--{home.get('section_density') or 'comfortable'} "
                f"public-motion--{home.get('motion_level') or 'subtle'}"
            ),
            "hero_layout": hero_layout,
            "hero_listing": hero_listing,
            "hero_slides": hero_slides,
            "featured_listings": featured or listings[:limit],
            "service_listings": services[:8],
            "category_tiles": _homepage_category_tiles(listings)[:8],
            "listing_counts": _listing_counts(listings),
            "contact_links": contact_links(),
        })
        ctx.update(_public_language_context(active_lang))
        return ctx


class PublicShopView(_StorefrontGateMixin, TemplateView):
    template_name = "public_catalog/shop.html"

    def _filtered_listings(self):
        qs = PublicCatalogListing.objects.published()
        kind = (self.request.GET.get("kind") or "").strip()
        if kind == "products":
            qs = qs.filter(product__isnull=False)
        elif kind == "services":
            qs = qs.filter(service__isnull=False)
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(public_title__icontains=q)
                | Q(public_summary__icontains=q)
                | Q(public_body__icontains=q)
                | Q(product__name__icontains=q)
                | Q(product__description__icontains=q)
                | Q(product__category__name__icontains=q)
                | Q(service__name__icontains=q)
                | Q(service__description__icontains=q)
            )
        return [
            listing
            for listing in qs
            if listing.show_when_unavailable or listing.is_available_for_public
        ]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        listings = self._filtered_listings()
        all_listings = _public_listings()
        ctx.update({
            "public_config": get_public_catalog_config(),
            "listings": listings,
            "listing_counts": _listing_counts(all_listings),
            "filtered_count": len(listings),
            "contact_links": contact_links(),
            "q": self.request.GET.get("q", ""),
            "kind": self.request.GET.get("kind", ""),
        })
        return ctx


class PublicItemDetailView(_StorefrontGateMixin, DetailView):
    model = PublicCatalogListing
    slug_field = "slug"
    slug_url_kwarg = "slug"
    template_name = "public_catalog/item_detail.html"
    context_object_name = "listing"

    def get_queryset(self):
        return PublicCatalogListing.objects.published()

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if not obj.show_when_unavailable and not obj.is_available_for_public:
            raise Http404("Listing is unavailable.")
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            "public_config": get_public_catalog_config(),
            "contact_links": contact_links(self.object),
        })
        return ctx


def public_item_modal(request, slug):
    if not get_public_catalog_config().get("shop_enabled", True):
        raise Http404("Storefront is offline.")
    listing = get_object_or_404(PublicCatalogListing.objects.published(), slug=slug)
    if not listing.show_when_unavailable and not listing.is_available_for_public:
        raise Http404("Listing is unavailable.")
    html = render_to_string(
        "public_catalog/_item_modal.html",
        {
            "listing": listing,
            "public_config": get_public_catalog_config(),
            "contact_links": contact_links(listing),
        },
        request=request,
    )
    return JsonResponse({"html": html})


def _contact_recipient():
    cfg = get_public_catalog_config()
    return str(cfg.get("contact_email") or settings.DEFAULT_FROM_EMAIL or "").strip()


def _render_contact_modal(request, form=None, sent=False):
    html = render_to_string(
        "public_catalog/_contact_modal.html",
        {
            "form": form or PublicContactForm(source_path=request.GET.get("next") or request.META.get("HTTP_REFERER", "")),
            "sent": sent,
            "public_config": get_public_catalog_config(),
        },
        request=request,
    )
    return JsonResponse({"html": html})


def _send_contact_email(message):
    recipient = _contact_recipient()
    if not recipient:
        message.email_status = PublicContactMessage.STATUS_SKIPPED
        message.email_error = "No public catalog contact email or DEFAULT_FROM_EMAIL configured."
        message.save(update_fields=["email_status", "email_error", "updated_at"])
        return

    subject = message.subject or f"Public catalog contact from {message.name}"
    body = "\n".join([
        f"Name: {message.name}",
        f"Email: {message.email}",
        f"Phone: {message.phone or '-'}",
        f"Source: {message.source_path or '-'}",
        "",
        message.message,
    ])
    try:
        send_mail(
            subject=f"[{store_name() or 'Public catalog'}] {subject}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
    except Exception as exc:
        message.email_status = PublicContactMessage.STATUS_FAILED
        message.email_recipient = recipient
        message.email_error = str(exc)[:2000]
        message.save(update_fields=["email_status", "email_recipient", "email_error", "updated_at"])
        return

    message.email_status = PublicContactMessage.STATUS_SENT
    message.email_recipient = recipient
    message.email_sent_at = timezone.now()
    message.email_error = ""
    message.save(update_fields=["email_status", "email_recipient", "email_sent_at", "email_error", "updated_at"])


def public_contact_modal(request):
    if request.method == "GET":
        sent = bool(request.session.pop("public_contact_sent", False))
        return _render_contact_modal(request, sent=sent)
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method."}, status=405)

    form = PublicContactForm(request.POST)
    if not form.is_valid():
        return _render_contact_modal(request, form=form)

    if form.cleaned_data.get("company"):
        request.session["public_contact_sent"] = True
        return JsonResponse({"success": True})

    key = form.cleaned_data["idempotency_key"]
    defaults = {
        "name": form.cleaned_data["name"],
        "email": form.cleaned_data["email"],
        "phone": form.cleaned_data.get("phone", ""),
        "subject": form.cleaned_data.get("subject", ""),
        "message": form.cleaned_data["message"],
        "source_path": form.cleaned_data.get("source_path", ""),
        "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:300],
    }
    created = False
    try:
        with transaction.atomic():
            message, created = PublicContactMessage.objects.get_or_create(
                idempotency_key=key,
                defaults=defaults,
            )
    except IntegrityError:
        message = PublicContactMessage.objects.get(idempotency_key=key)

    if created:
        _send_contact_email(message)

    request.session["public_contact_sent"] = True
    return JsonResponse({"success": True})
