import functools
import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from catalog.models import Product, Service
from common.views import RibbonPageMixin

from .models import PublicCatalogListing
from .settings import PUBLIC_CATALOG_NS, get_public_catalog_config, set_public_catalog_config

EDIT_PERM = "public_catalog.change_publiccataloglisting"


def mutation_endpoint(view):
    """Write-only builder endpoint.

    POST mutates with permission. Direct browser navigation returns to the builder
    page; passive GET/HEAD probes stay silent and never mutate.
    """

    @login_required
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method not in ("POST", "PUT", "PATCH"):
            if request.method == "GET" and _is_navigation_get(request):
                return redirect("public_catalog_staff:builder")
            return HttpResponse(status=204)
        if not request.user.has_perm(EDIT_PERM):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def _is_navigation_get(request):
    fetch_mode = request.headers.get("Sec-Fetch-Mode", "")
    accept = request.headers.get("Accept", "")
    return fetch_mode == "navigate" or "text/html" in accept


TEXT_FIELDS = ("public_title", "public_summary", "public_body", "installation_notes", "warranty_notes")
BOOL_FIELDS = ("is_featured", "show_price", "show_availability", "show_when_unavailable")


def _builder_items():
    products = list(
        Product.objects.filter(is_active=True, deleted_at__isnull=True)
        .select_related("category")
        .prefetch_related("variants")
        .order_by("name")
    )
    services = list(
        Service.objects.filter(is_active=True, deleted_at__isnull=True).order_by("service_type", "name")
    )
    listings_p = {l.product_id: l for l in PublicCatalogListing.objects.filter(product__in=products)}
    listings_s = {l.service_id: l for l in PublicCatalogListing.objects.filter(service__in=services)}

    items = []
    for product in products:
        items.append(listings_p.get(product.pk) or PublicCatalogListing(product=product))
    for service in services:
        items.append(listings_s.get(service.pk) or PublicCatalogListing(service=service))

    items.sort(key=lambda l: (
        0 if (l.pk and l.is_published) else 1,
        l.sort_order if l.pk else 100,
        (l.display_title or "").lower(),
    ))
    return items


def _counts(items):
    published = [i for i in items if i.pk and i.is_published]
    return {
        "total": len(items),
        "published": len(published),
        "featured": sum(1 for i in published if i.is_featured),
        "available": sum(1 for i in published if i.is_available_for_public),
    }


def _listing_json(listing):
    price = listing.price_lyd
    return {
        "id": listing.pk,
        "kind": listing.source_kind,
        "source_id": listing.product_id or listing.service_id,
        "is_published": listing.is_published,
        "is_featured": listing.is_featured,
        "show_price": listing.show_price,
        "show_availability": listing.show_availability,
        "show_when_unavailable": listing.show_when_unavailable,
        "sort_order": listing.sort_order,
        "public_title": listing.public_title,
        "display_title": listing.display_title,
        "public_summary": listing.public_summary,
        "public_body": listing.public_body,
        "installation_notes": listing.installation_notes,
        "warranty_notes": listing.warranty_notes,
        "image_url": listing.image_url,
        "public_url": listing.get_absolute_url() if listing.pk else "",
        "availability_code": listing.availability_code,
        "availability_label": listing.availability_label,
        "price_lyd": float(price) if price is not None else None,
    }


def _resolve_listing(request, *, create):
    listing_id = request.POST.get("listing_id")
    if listing_id:
        try:
            return PublicCatalogListing.objects.get(pk=listing_id), False
        except PublicCatalogListing.DoesNotExist:
            raise Http404("listing not found")

    kind = request.POST.get("kind")
    source_id = request.POST.get("id")
    if kind == "product":
        existing = PublicCatalogListing.objects.filter(product_id=source_id).first()
    elif kind == "service":
        existing = PublicCatalogListing.objects.filter(service_id=source_id).first()
    else:
        raise Http404("invalid source")
    if existing:
        return existing, False
    if not create:
        raise Http404("listing not found")

    if kind == "product":
        source = Product.objects.filter(pk=source_id, is_active=True, deleted_at__isnull=True).first()
        listing = PublicCatalogListing(product=source) if source else None
    else:
        source = Service.objects.filter(pk=source_id, is_active=True, deleted_at__isnull=True).first()
        listing = PublicCatalogListing(service=source) if source else None
    if listing is None:
        raise Http404("source not found")

    cfg = get_public_catalog_config()
    listing.show_price = cfg["show_price"]
    listing.show_availability = cfg["show_availability"]
    return listing, True


class PublicCatalogBuilderView(RibbonPageMixin, LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = "public_catalog/shop_builder.html"
    permission_required = "public_catalog.view_publiccataloglisting"
    ribbon_title_icon = "bi bi-shop-window"
    page_title_key = "builder_title"
    page_subtitle_key = "builder_subtitle"

    def get_ribbon_action_specs(self):
        strings = self.get_page_strings()
        settings_label = strings.get("builder_settings", "Shop settings")
        return [
            {
                "url": reverse("public_catalog:shop"),
                "label": strings.get("builder_open_shop", "View live shop"),
                "icon": "bi bi-box-arrow-up-right",
                "css_class": "btn btn-outline-secondary rounded-pill",
                "attrs": {"target": "_blank", "rel": "noopener"},
            },
            {
                "label": settings_label,
                "icon": "bi bi-sliders",
                "css_class": "btn btn-primary rounded-pill",
                "attrs": {
                    "data-dynamic-modal": reverse("dlux_app_settings_modal", args=[PUBLIC_CATALOG_NS]),
                    "data-modal-title": settings_label,
                },
            },
        ]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        items = _builder_items()
        ctx.update({
            "builder_items": items,
            "public_config": get_public_catalog_config(),
            "public_settings_ns": PUBLIC_CATALOG_NS,
            "builder_counts": _counts(items),
            "can_edit": self.request.user.has_perm(EDIT_PERM),
        })
        return ctx


@mutation_endpoint
def builder_toggle_publish(request):
    listing, created = _resolve_listing(request, create=True)
    listing.is_published = True if created else not listing.is_published
    if not listing.is_published:
        listing.is_featured = False
    listing.save()
    return JsonResponse({"ok": True, "listing": _listing_json(listing)})


@mutation_endpoint
def builder_update_listing(request):
    listing, _created = _resolve_listing(request, create=True)

    for field in TEXT_FIELDS:
        if field in request.POST:
            setattr(listing, field, (request.POST.get(field) or "").strip())
    for field in BOOL_FIELDS:
        if field in request.POST:
            setattr(listing, field, request.POST.get(field) in ("1", "true", "on", "True"))
    if "sort_order" in request.POST:
        try:
            listing.sort_order = max(0, int(request.POST.get("sort_order") or 0))
        except (TypeError, ValueError):
            pass
    if request.POST.get("clear_image") in ("1", "true", "on"):
        # Clear both: the old column may still hold a file the backfill has not
        # adopted yet, and leaving it would make the override reappear.
        listing.image_override = ""
        listing.image_override_asset = None
    if "image_override" in request.FILES:
        # The builder posts the file with the rest of the row rather than through
        # a picker, so register it here — into this listing's own namespace, the
        # one its asset field declares.
        from dlux.assets import create_managed_asset

        field = PublicCatalogListing._meta.get_field("image_override_asset")
        asset, _created = create_managed_asset(
            request.FILES["image_override"],
            kind="image",
            namespace=field.namespace,
            user=request.user,
        )
        listing.image_override_asset = asset
        listing.image_override = ""
    if listing.is_featured and not listing.is_published:
        listing.is_featured = False

    listing.save()
    return JsonResponse({"ok": True, "listing": _listing_json(listing)})


@mutation_endpoint
def builder_reorder(request):
    try:
        order = json.loads(request.body.decode() or "[]")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    ids = [int(pk) for pk in order if str(pk).isdigit()]
    listings = {l.pk: l for l in PublicCatalogListing.objects.filter(pk__in=ids)}
    for index, pk in enumerate(ids):
        listing = listings.get(pk)
        if listing and listing.sort_order != index:
            listing.sort_order = index
            listing.save(update_fields=["sort_order"])
    return JsonResponse({"ok": True})


@mutation_endpoint
def builder_settings(request):
    patch = {}
    for flag in ("homepage_enabled", "shop_enabled"):
        if flag in request.POST:
            patch[flag] = request.POST.get(flag) in ("1", "true", "on", "True")
    if "featured_limit" in request.POST:
        try:
            patch["featured_limit"] = max(0, int(request.POST.get("featured_limit") or 0))
        except (TypeError, ValueError):
            pass
    cfg = set_public_catalog_config(patch, request=request)
    return JsonResponse({"ok": True, "config": {
        "homepage_enabled": cfg["homepage_enabled"],
        "shop_enabled": cfg["shop_enabled"],
        "featured_limit": cfg["featured_limit"],
    }})


# --------------------------------------------------------------------------- #
# Public homepage (landing page) builder
# --------------------------------------------------------------------------- #
def _save_homepage_image(uploaded, prefix):
    import os
    from uuid import uuid4

    from django.core.files.storage import default_storage

    ext = os.path.splitext(uploaded.name)[1].lower() or ".png"
    name = f"public_homepage/{prefix}-{uuid4().hex}{ext}"
    saved = default_storage.save(name, uploaded)
    return default_storage.url(saved)


class PublicHomepageBuilderView(RibbonPageMixin, LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = "public_catalog/homepage_builder.html"
    permission_required = "public_catalog.view_publiccataloglisting"
    ribbon_title_icon = "bi bi-easel2"
    page_title_key = "hp_builder_title"
    page_subtitle_key = "hp_builder_sub"

    def get_ribbon_action_specs(self):
        """The live toggle, the editing-language switch, the save status and the
        link to the site — one block of raw markup rather than four actions.

        They are stateful controls the builder's JS binds to and its stylesheet
        lays out as a group, and they read the page's own context, so they move
        into the ribbon whole. See `refresh_ribbon`.
        """
        from django.template.loader import render_to_string

        context = self.ribbon_page_context
        if context is None:
            return []
        return [{
            "html": render_to_string(
                "public_catalog/_homepage_builder_actions.html",
                context,
                request=self.request,
            ),
        }]

    def get_context_data(self, **kwargs):
        from common.i18n import t
        from dlux.translations import get_current_language_code
        from .homepage import (
            builder_sections, get_homepage_config, get_public_languages,
        )

        ctx = super().get_context_data(**kwargs)
        cfg = get_homepage_config()
        languages, default_lang = get_public_languages()
        active = ctx.get("CURRENT_LANG") or get_current_language_code(self.request) or default_lang
        codes = [c for c, _l in languages]
        def choices(items):
            return [
                {"value": value, "icon": icon, "label": t(label_key, fallback)}
                for value, icon, label_key, fallback in items
            ]

        ctx.update({
            "homepage_config": cfg,
            "public_config": get_public_catalog_config(),
            "homepage_sections": builder_sections(cfg),
            "homepage_languages": languages,
            "homepage_default_lang": default_lang,
            "homepage_active_lang": active if active in codes else default_lang,
            "hero_media_choices": [
                ("featured", t("hp_media_featured", "Featured image")),
                ("logo", t("hp_media_logo", "Logo")),
                ("custom", t("hp_media_custom", "Custom image")),
                ("gradient", t("hp_media_gradient", "Gradient")),
            ],
            "style_preset_choices": choices([
                ("signature", "bi-stars", "hp_style_signature", "Signature"),
                ("showroom", "bi-shop-window", "hp_style_showroom", "Showroom"),
                ("precision", "bi-rulers", "hp_style_precision", "Precision"),
                ("editorial", "bi-layout-text-window-reverse", "hp_style_editorial", "Editorial"),
            ]),
            "hero_layout_choices": choices([
                ("poster", "bi-window-fullscreen", "hp_hero_layout_poster", "Poster"),
                ("center", "bi-align-center", "hp_hero_layout_center", "Center"),
                ("mosaic", "bi-grid-3x3-gap", "hp_hero_layout_mosaic", "Mosaic"),
                ("compact", "bi-window", "hp_hero_layout_compact", "Compact"),
            ]),
            "hero_height_choices": choices([
                ("balanced", "bi-aspect-ratio", "hp_hero_height_balanced", "Balanced"),
                ("immersive", "bi-arrows-fullscreen", "hp_hero_height_immersive", "Immersive"),
                ("compact", "bi-arrows-collapse", "hp_hero_height_compact", "Compact"),
            ]),
            "hero_focus_choices": choices([
                ("center", "bi-bullseye", "hp_focus_center", "Center"),
                ("top", "bi-arrow-up", "hp_focus_top", "Top"),
                ("bottom", "bi-arrow-down", "hp_focus_bottom", "Bottom"),
                ("left", "bi-arrow-left", "hp_focus_left", "Left"),
                ("right", "bi-arrow-right", "hp_focus_right", "Right"),
            ]),
            "nav_treatment_choices": choices([
                ("glass", "bi-back", "hp_nav_glass", "Glass"),
                ("solid", "bi-square-fill", "hp_nav_solid", "Solid"),
                ("quiet", "bi-border-width", "hp_nav_quiet", "Quiet"),
            ]),
            "card_treatment_choices": choices([
                ("showcase", "bi-card-image", "hp_card_showcase", "Showcase"),
                ("spec", "bi-list-check", "hp_card_spec", "Spec"),
                ("minimal", "bi-dash-square", "hp_card_minimal", "Minimal"),
            ]),
            "section_density_choices": choices([
                ("comfortable", "bi-layout-three-columns", "hp_density_comfortable", "Comfortable"),
                ("compact", "bi-distribute-vertical", "hp_density_compact", "Compact"),
            ]),
            "background_treatment_choices": choices([
                ("clean", "bi-circle", "hp_bg_clean", "Clean"),
                ("grid", "bi-grid", "hp_bg_grid", "Grid"),
                ("diagonal", "bi-slash-lg", "hp_bg_diagonal", "Diagonal"),
                ("linework", "bi-bezier2", "hp_bg_linework", "Linework"),
            ]),
            "motion_level_choices": choices([
                ("subtle", "bi-wind", "hp_motion_subtle", "Subtle"),
                ("none", "bi-pause-circle", "hp_motion_none", "None"),
                ("lively", "bi-lightning-charge", "hp_motion_lively", "Lively"),
            ]),
            "accent_presets": ["#345b86", "#0ea5e9", "#16a34a", "#dc2626", "#9333ea", "#f59e0b", "#0f172a"],
            "accent_secondary_presets": ["#14b8a6", "#f97316", "#84cc16", "#e11d48", "#8b5cf6", "#64748b", "#111827"],
            "can_edit": self.request.user.has_perm(EDIT_PERM),
        })
        return self.refresh_ribbon(ctx)


@mutation_endpoint
def homepage_save(request):
    from .homepage import (
        HOMEPAGE_DEFAULTS, LOCALIZED_KEYS, set_homepage_config, get_public_languages,
    )

    post = request.POST
    patch = {}
    codes = [c for c, _l in get_public_languages()[0]]
    for key, default in HOMEPAGE_DEFAULTS.items():
        if key in ("sections", "hero_image", "story_image"):
            continue
        if key in LOCALIZED_KEYS:
            present = {code: (post.get(f"{key}__{code}") or "").strip()
                       for code in codes if f"{key}__{code}" in post}
            if present:
                patch[key] = present
        elif key in ("hero_show_contact", "show_stats"):
            if key in post:
                patch[key] = post.get(key) in ("1", "true", "on", "True")
        elif key == "hero_overlay":
            if key in post:
                patch[key] = post.get(key)
        elif isinstance(default, str):
            if key in post:
                patch[key] = (post.get(key) or "").strip()

    if "hero_image" in request.FILES:
        patch["hero_image"] = _save_homepage_image(request.FILES["hero_image"], "hero")
    elif post.get("clear_hero_image") in ("1", "true", "on"):
        patch["hero_image"] = ""
    if "story_image" in request.FILES:
        patch["story_image"] = _save_homepage_image(request.FILES["story_image"], "story")
    elif post.get("clear_story_image") in ("1", "true", "on"):
        patch["story_image"] = ""

    if "sections" in post:
        try:
            patch["sections"] = json.loads(post.get("sections") or "[]")
        except ValueError:
            pass

    cfg = set_homepage_config(patch, request=request)
    return JsonResponse({"ok": True, "config": cfg})
