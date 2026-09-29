import json
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, TemplateView

from common.i18n import t
from common.views import RibbonPageMixin
from finance.services import get_current_rate

from .pos import complete_sale, lookup, popular
from .pos_settings import enabled_methods, get_pos_config
from .views import _visible_invoices

POS_PERMS = ("sales.use_pos", "sales.add_invoice", "sales.issue_invoice", "sales.add_payment")


class PosEnabledMixin(LoginRequiredMixin, PermissionRequiredMixin):
    permission_required = POS_PERMS
    raise_exception = True

    def dispatch(self, request, *args, **kwargs):
        self.pos_config = get_pos_config()
        if not self.pos_config["enabled"]:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _automotive_on():
    try:
        from automotive.settings import get_automotive_config
    except ImportError:  # pragma: no cover
        return False
    return get_automotive_config()["enabled"]


class TillView(PosEnabledMixin, RibbonPageMixin, TemplateView):
    template_name = "sales/pos/till.html"
    page_title_key = "pos_till_title"
    page_subtitle_key = "pos_till_subtitle"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config = self.pos_config
        user = self.request.user
        context.update({
            "pos_config": config,
            "pos_methods": enabled_methods(config),
            "pos_setup": json.dumps({
                "lookup": reverse("sales:pos_lookup"),
                "checkout": reverse("sales:pos_checkout"),
                "receipt": reverse("sales:pos_receipt", args=[0]),
                "vehicle": reverse("sales:pos_vehicle") if _automotive_on() else "",
                "vehicleSearch": reverse("automotive:vehicle_search") if _automotive_on() else "",
                "addProduct": reverse("scoped_modal_manager", args=["catalog", "product", "new"])
                if user.has_perm("catalog.add_product") else "",
                "receiptSize": config["receipt_size"],
                "maxDiscount": config["max_discount_percent"],
                "unlimitedDiscount": user.has_perm("sales.pos_unlimited_discount"),
                "methods": enabled_methods(config),
                "till": f"{user.get_username()}",
                "rate": str(get_current_rate() or ""),
                "strings": {
                    "added": t("pos_added", "Added"),
                    "not_found": t("pos_not_found", "Nothing matches"),
                    "network": t("pos_network", "Connection problem — try again."),
                    "failed": t("pos_failed", "The sale could not be completed."),
                    "low_stock": t("pos_low_stock", "Not enough stock"),
                    "in_stock": t("pos_in_stock", "In stock"),
                    "out_of_stock": t("ui_out_of_stock", "Out of stock"),
                    "remove": t("ui_remove", "Remove"),
                    "edit_price": t("pos_edit_price", "Change price"),
                    "price_prompt": t("pos_price_prompt", "Unit price (LYD). Leave empty to restore the list price."),
                    "discount_prompt": t("pos_discount_prompt", "Discount — an amount, or a percent like 5%"),
                    "limit": t("pos_limit", "limit"),
                    "clear_confirm": t("pos_clear_confirm", "Clear this sale?"),
                    "card_over": t("pos_card_over_total", "A card or transfer amount is more than what is left to pay."),
                    "camera_hint": t("pos_camera_hint", "Point the camera at a barcode."),
                    "camera_denied": t("pos_camera_denied", "The camera could not be opened."),
                    "add_unknown_title": t("pos_add_unknown_title", "New item"),
                    "items": t("ui_products_count", "products"),
                },
            }),
        })
        return context


class LookupView(PosEnabledMixin, View):
    def get(self, request):
        if request.GET.get("popular"):
            return JsonResponse(popular(user=request.user))
        return JsonResponse(lookup(request.GET.get("q", ""), user=request.user))


class CheckoutView(PosEnabledMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"ok": False, "error": "bad request"}, status=400)
        try:
            result = complete_sale(user=request.user, data=data, config=self.pos_config)
        except ValidationError as error:
            return JsonResponse({"ok": False, "error": " ".join(error.messages)}, status=400)
        result["receipt"] = reverse("sales:pos_receipt", args=[result["invoice"]])
        return JsonResponse(result)


class ReceiptView(PosEnabledMixin, DetailView):
    template_name = "sales/pos/receipt.html"
    context_object_name = "invoice"

    def get_queryset(self):
        return _visible_invoices(self.request.user).select_related("pos_sale")

    def get_context_data(self, **kwargs):
        from dlux.translations import get_current_language_code

        context = super().get_context_data(**kwargs)
        size = self.request.GET.get("size") or self.pos_config["receipt_size"]
        lang = get_current_language_code(self.request)
        context.update({
            "items": self.object.items.all(),
            "payments": self.object.payments.all(),
            "sale": getattr(self.object, "pos_sale", None),
            "size": size if size in ("58", "80", "a4") else "80",
            "is_rtl": lang.startswith("ar"),
            "doc_lang": lang,
        })
        return context


class VehicleProductsView(PosEnabledMixin, View):
    """Products that fit one machine, for the till's "Find by vehicle" panel."""

    def get(self, request):
        if not _automotive_on():
            raise Http404
        from automotive.browser import VehicleBrowser
        from automotive.settings import get_automotive_config

        params = QueryDict(mutable=True)
        for key in ("make", "model", "year", "generation", "engine", "type", "any_year"):
            if request.GET.get(key):
                params[key] = request.GET[key]
        request.GET = params
        context = VehicleBrowser(request, get_automotive_config()).build()
        rate = get_current_rate()
        items = [
            {
                "product": product.pk,
                "name": product.name,
                "sku": product.sku,
                "price": str(product.selling_price_lyd(rate) or Decimal("0.00")),
                "stock": float(product.stock_qty),
                "track_stock": product.track_stock,
                "category": str(product.category or ""),
            }
            for product in context.get("products", [])
        ]
        crumbs = [crumb["label"] for crumb in context.get("breadcrumbs", [])]
        return JsonResponse({"items": items, "path": crumbs, "complete": bool(context.get("show_results"))})
