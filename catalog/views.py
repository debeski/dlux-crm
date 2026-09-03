import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import format_html
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import DetailView, TemplateView

from django.urls import reverse

from dlux.translations import get_current_language_code, get_strings
from dlux.utils import log_user_action

from common.editors import sync_party
from common.views import RibbonPageMixin, ScopedListView
from finance.services import get_current_rate, usd_to_lyd

from .filters import (
    CategoryFilter, ProductFilter, PurchaseInvoiceFilter, ServiceFilter, StockMovementFilter,
    StockTakeFilter, SupplierFilter,
)
from .forms import OpeningStockLineFormSet, PurchaseInvoiceForm, PurchaseInvoiceLineFormSet
from .models import (
    Category, Product, ProductVariant, PurchaseInvoice, PurchaseInvoiceLine, Service, StockMovement,
    StockTake, StockTakeLine, Supplier,
    product_color_hex,
)
from .product_layouts import (
    PRODUCTS_LAYOUT_GRID, PRODUCTS_LAYOUT_LIGHT, PRODUCTS_LAYOUT_NS, PRODUCTS_LAYOUTS,
    get_products_layout,
)
from .tables import (
    CategoryTable, ProductLightTable, ProductTable, PurchaseInvoiceTable, ServiceTable,
    StockMovementTable, StockTakeTable, SupplierTable,
)


def _variant_payload(variant):
    return {
        "id": variant.pk,
        "color": variant.color or "",
        "color_label": variant.color_label,
        "color_hex": product_color_hex(variant.color),
        "size": variant.size or "",
        "stock_qty": float(variant.stock_qty or 0),
        "label": variant.display_label,
    }


def _product_autofill_map_json():
    """JSON {pk: {cost, markup, price_usd, price_lyd, category, unit, barcode, ...}}
    used by both Opening Stock and Purchase Invoice grids."""
    data = {}
    for p in Product.objects.prefetch_related("variants"):
        variants = list(p.variants.all().order_by("color", "size", "pk"))
        default_variant = variants[0] if len(variants) == 1 else None
        fallback_color = (p.color or "") if not variants else ""
        fallback_size = (p.size or "") if not variants else ""
        data[str(p.pk)] = {
            "cost": float(p.cost_usd or 0),
            "markup": float(p.markup_percent or 0),
            "price_usd": float(p.price_usd or 0),
            "price_lyd": float(p.price_lyd_override) if p.price_lyd_override is not None else "",
            "category": str(p.category_id or ""),
            "unit": p.unit,
            "barcode": p.barcode,
            "color": (default_variant.color if default_variant else fallback_color),
            "size": (default_variant.size if default_variant else fallback_size),
            "variants": [_variant_payload(v) for v in variants],
        }
    return json.dumps(data)


def _save_product_from_intake_line(cd):
    """Create or reuse a product from an inbound stock row, then apply the row's
    pricing fields to it. The typed product name is also a no-JS fallback match."""
    name = (cd.get("name") or "").strip()
    pid = cd.get("product")
    product = Product.objects.filter(pk=pid).first() if pid else None
    if product is None and name:
        product = Product.objects.filter(name__iexact=name).first()
    if product is None:
        product = Product(name=name)
    product.name = name or product.name
    product.category = cd.get("category")
    product.unit = cd.get("unit") or product.unit
    if cd.get("barcode"):
        product.barcode = cd["barcode"]
    if product.pk is None:
        product.color = cd.get("color") or None
        product.size = cd.get("size") or None
    product.cost_usd = cd.get("cost_usd") or Decimal("0")
    product.markup_percent = cd.get("markup_percent") or Decimal("0")
    product.price_usd = cd.get("price_usd") or Decimal("0")
    product.price_lyd_override = cd.get("price_lyd_override")
    product.track_stock = True
    product.save()
    return product


def _variant_from_intake_line(product, cd):
    return ProductVariant.get_or_create_for(product, cd.get("color"), cd.get("size"))


def _opening_stock_used():
    return StockMovement.objects.filter(reference="OPENING").exists()


class CategoryListView(ScopedListView):
    model = Category
    permission_required = "catalog.view_category"
    table_class = CategoryTable
    filterset_class = CategoryFilter
    page_title_key = "page_categories"
    page_subtitle_key = "page_categories_sub"


class SupplierListView(ScopedListView):
    model = Supplier
    permission_required = "catalog.view_supplier"
    table_class = SupplierTable
    filterset_class = SupplierFilter
    page_title_key = "page_suppliers"
    page_subtitle_key = "page_suppliers_sub"


class ProductListView(ScopedListView):
    model = Product
    permission_required = "catalog.view_product"
    table_class = ProductTable
    filterset_class = ProductFilter
    page_title_key = "page_products"
    page_subtitle_key = "page_products_sub"
    # Live sync of the cost/markup/USD/LYD price fields in the create-edit modal,
    # plus the per-user layout switcher (table / grid / light).
    extra_scripts = ("catalog/js/price_sync.js", "catalog/js/products_layout.js")

    def get_layout(self):
        return get_products_layout(self.request)

    def get_table_class(self):
        # "light" swaps to the minimal columns table; "table"/"grid" keep the full one.
        if self.get_layout() == PRODUCTS_LAYOUT_LIGHT:
            return ProductLightTable
        return ProductTable

    def get_template_names(self):
        if self.get_layout() == PRODUCTS_LAYOUT_GRID:
            return ["catalog/product_grid.html"]
        # Table and Light are the shared list page; only the columns differ.
        return [self.template_name]

    def get_ribbon_action_specs(self):
        """The table/grid/light switch, ahead of the Add button.

        Raw `html` rather than three ribbon buttons: the control is one
        `btn-group` whose pressed state and app-preference wiring live in the
        partial, and splitting it into separate actions would lose both. The
        layout is a per-user dlux app preference, not a query key, so it needs
        no `ribbon_preserve_keys` entry.
        """
        from django.template.loader import render_to_string

        toggle = render_to_string(
            "catalog/_products_layout_toggle.html",
            {
                "products_layout": self.get_layout(),
                "products_layout_ns": PRODUCTS_LAYOUT_NS,
                "products_layouts": PRODUCTS_LAYOUTS,
            },
            request=self.request,
        )
        return [{"html": toggle}] + list(super().get_ribbon_action_specs())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["products_layout"] = self.get_layout()
        ctx["products_layout_ns"] = PRODUCTS_LAYOUT_NS
        ctx["products_layouts"] = PRODUCTS_LAYOUTS
        return ctx


class ServiceListView(ScopedListView):
    model = Service
    permission_required = "catalog.view_service"
    table_class = ServiceTable
    filterset_class = ServiceFilter
    page_title_key = "page_services"
    page_subtitle_key = "page_services_sub"
    extra_scripts = ("catalog/js/price_sync.js",)


class StockMovementListView(ScopedListView):
    model = StockMovement
    permission_required = "catalog.view_stockmovement"
    table_class = StockMovementTable
    filterset_class = StockMovementFilter
    page_title_key = "page_stock_movements"
    page_subtitle_key = "page_stock_movements_sub"
    extra_scripts = ("catalog/js/stock_movement.js",)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["opening_stock_used"] = _opening_stock_used()
        return ctx

    def get_ribbon_action_specs(self):
        """Opening Stock, Add Stock, and the manual movement modal.

        Each button needs *every* permission it lists, not any of them — adding a
        movement by hand also creates the product it moves — so the checks are
        made here rather than handed to the ribbon's any-of `permissions` gate.
        """
        strings = get_strings(get_current_language_code(self.request))
        user = self.request.user
        actions = []
        if user.has_perm("catalog.add_product") and user.has_perm("catalog.add_stockmovement"):
            if _opening_stock_used():
                actions.append({
                    "url": reverse("catalog:opening_stock_detail"),
                    "label": strings.get("ui_view_opening_stock", "View Opening Stock"),
                    "icon": "bi bi-eye",
                    "css_class": "btn btn-outline-primary rounded-pill",
                })
            else:
                actions.append({
                    "url": reverse("catalog:opening_stock"),
                    "label": strings.get("ui_new_opening_stock", "Opening Stock (bulk)"),
                    "icon": "bi bi-box-seam",
                    "css_class": "btn btn-primary rounded-pill",
                })
        if (
            user.has_perm("catalog.add_purchaseinvoice")
            and user.has_perm("catalog.add_product")
            and user.has_perm("catalog.add_stockmovement")
        ):
            actions.append({
                "url": reverse("catalog:purchase_invoice_create"),
                "label": strings.get("ui_add_stock", "Add Stock"),
                "icon": "bi bi-plus-lg",
                "css_class": "btn btn-success rounded-pill",
            })
        label = strings.get("ui_manual_stock_movement", "Manual Movement")
        if self.allow_add and user.has_perm("catalog.add_stockmovement"):
            actions.append({
                "label": label,
                "icon": "bi bi-sliders",
                "css_class": "btn btn-outline-secondary rounded-pill",
                "attrs": {
                    "data-dynamic-modal": self.get_add_modal_url(),
                    "data-modal-title": label,
                },
            })
        # Deliberately not calling super(): the manual-movement button above IS
        # this list's Add, with its own label and a secondary style.
        return actions


class PurchaseInvoiceListView(ScopedListView):
    model = PurchaseInvoice
    permission_required = "catalog.view_purchaseinvoice"
    table_class = PurchaseInvoiceTable
    filterset_class = PurchaseInvoiceFilter
    page_title_key = "page_purchase_invoices"
    page_subtitle_key = "page_purchase_invoices_sub"
    allow_add = False  # created through the full-page editor, not a modal

    def get_ribbon_action_specs(self):
        user = self.request.user
        if not (
            user.has_perm("catalog.add_purchaseinvoice")
            and user.has_perm("catalog.add_product")
            and user.has_perm("catalog.add_stockmovement")
        ):
            return []
        strings = get_strings(get_current_language_code(self.request))
        return [{
            "url": reverse("catalog:purchase_invoice_create"),
            "label": strings.get("ui_new_purchase_invoice", "New Purchase Invoice"),
            "icon": "bi bi-plus-lg",
            "css_class": "btn btn-primary rounded-pill",
        }]


# --------------------------------------------------------------------------- #
# Stock take (physical inventory count) + inventory valuation
# --------------------------------------------------------------------------- #
def _parse_qty(raw):
    """Blank -> None (uncounted); a valid number -> Decimal; junk -> None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


class StockTakeListView(ScopedListView):
    model = StockTake
    permission_required = "catalog.view_stocktake"
    table_class = StockTakeTable
    filterset_class = StockTakeFilter
    page_title_key = "page_stock_takes"
    page_subtitle_key = "page_stock_takes_sub"
    allow_add = False  # created via the full-page count flow, not a modal

    def get_ribbon_action_specs(self):
        strings = get_strings(get_current_language_code(self.request))
        actions = []
        if self.request.user.has_perm("catalog.view_inventory_valuation"):
            actions.append({
                "url": reverse("catalog:inventory_valuation"),
                "label": strings.get("page_inventory_valuation", "Valuation"),
                "icon": "bi bi-cash-coin",
                "css_class": "btn btn-outline-secondary rounded-pill",
            })
        if self.request.user.has_perm("catalog.add_stocktake"):
            actions.append({
                "url": reverse("catalog:stock_take_create"),
                "label": strings.get("ui_new_stock_take", "New Count"),
                "icon": "bi bi-plus-lg",
                "css_class": "btn btn-primary rounded-pill",
            })
        return actions


class StockTakeCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Full-page count sheet: every active tracked product with an input for the
    physical count. Submitting snapshots the system quantity and creates the take
    (status = open); adjustments are posted later from the detail page."""

    permission_required = "catalog.add_stocktake"
    raise_exception = True
    template_name = "catalog/stock_take_form.html"

    def _products(self):
        return Product.objects.filter(is_active=True, track_stock=True).order_by("name")

    def get(self, request):
        return render(request, self.template_name, {"products": self._products()})

    def post(self, request):
        products = list(self._products())
        with transaction.atomic():
            take = StockTake(notes=request.POST.get("notes", ""))  # count_date defaults to today
            take.save()
            for p in products:
                StockTakeLine.objects.create(
                    stock_take=take,
                    product=p,
                    system_qty=p.stock_qty,
                    counted_qty=_parse_qty(request.POST.get(f"count_{p.pk}")),
                )
            log_user_action(request, "CREATE", instance=take)
        messages.success(request, _("Stock take %(no)s saved.") % {"no": take.number})
        return redirect("catalog:stock_take_detail", pk=take.pk)


class StockTakeDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = StockTake
    permission_required = "catalog.view_stocktake"
    raise_exception = True
    template_name = "catalog/stock_take_detail.html"
    context_object_name = "take"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        take = self.object
        rate = get_current_rate()
        lines = list(take.lines.select_related("product"))
        for ln in lines:
            ln.variance_lyd = ln.variance_value_lyd(rate)
        ctx["lines"] = lines
        ctx["discrepancy_count"] = len(take.discrepancy_lines)
        ctx["total_variance_lyd"] = take.total_variance_value_lyd
        ctx["can_apply"] = take.is_open and self.request.user.has_perm("catalog.apply_stocktake")
        return ctx


class StockTakeApplyView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "catalog.apply_stocktake"
    raise_exception = True

    def post(self, request, pk):
        take = get_object_or_404(StockTake, pk=pk)
        try:
            take.apply(request.user)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("catalog:stock_take_detail", pk=pk)
        log_user_action(request, "UPDATE", instance=take)
        messages.success(request, _("Stock take %(no)s applied. Stock adjusted.") % {"no": take.number})
        return redirect("catalog:stock_take_detail", pk=pk)


class InventoryValuationView(RibbonPageMixin, LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """What the stock on hand is worth right now: Σ(stock_qty × unit cost)."""

    permission_required = "catalog.view_inventory_valuation"
    raise_exception = True
    template_name = "catalog/inventory_valuation.html"
    page_title_key = "page_inventory_valuation"
    page_subtitle_key = "page_inventory_valuation_sub"

    def get_rate(self):
        # Memoized: the ribbon chip and the figures below it must quote the
        # same rate, and it is one lookup either way.
        if not hasattr(self, "_rate"):
            self._rate = get_current_rate()
        return self._rate

    def get_ribbon_action_specs(self):
        """The live USD → LYD rate every figure on the page is priced at."""
        strings = self.get_page_strings()
        return [{
            "html": format_html(
                '<span class="badge rounded-pill text-bg-light border">'
                '<i class="bi bi-currency-exchange me-1"></i>{}: 1 USD = {} LYD</span>',
                strings.get("ui_rate", "Rate"),
                self.get_rate(),
            ),
        }]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rate = self.get_rate()
        rows = []
        total_usd = Decimal("0.00")
        for p in Product.objects.filter(is_active=True, track_stock=True).order_by("name"):
            value_usd = (p.stock_qty or Decimal("0")) * (p.cost_usd or Decimal("0"))
            total_usd += value_usd
            rows.append({
                "product": p,
                "stock_qty": p.stock_qty,
                "cost_usd": p.cost_usd,
                "value_usd": value_usd,
                "value_lyd": usd_to_lyd(value_usd, rate),
            })
        ctx["rows"] = rows
        ctx["total_usd"] = total_usd
        ctx["total_lyd"] = usd_to_lyd(total_usd, rate)
        ctx["rate"] = rate
        ctx["item_count"] = len(rows)
        return ctx


# --------------------------------------------------------------------------- #
# Opening stock (one-time "ground zero" inventory intake)
# --------------------------------------------------------------------------- #
class OpeningStockEditorView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """One-time bulk intake for first setup — a **child of the stock ledger**, not
    a document of its own. Reached from a trigger on the Stock Movements page: fill
    the grid, confirm, and each row create-or-reuses its ``Product`` and posts a
    Stock In ``StockMovement`` (``reason="Opening balance"``, ``reference="OPENING"``)
    in a single transaction. The movements are the record; there is no list/detail.
    """

    permission_required = ("catalog.add_product", "catalog.change_product", "catalog.add_stockmovement")
    raise_exception = True
    template_name = "catalog/opening_stock_form.html"

    def _product_map(self):
        return _product_autofill_map_json()

    def _context(self, formset):
        return {
            "formset": formset,
            "current_rate": get_current_rate(),
            "product_map_json": self._product_map(),
            "products": Product.objects.order_by("name"),
        }

    @staticmethod
    def _apply_line(cd):
        """Create-or-reuse the product for a grid row (correcting its pricing from
        the row's figures — the admin may reprice an existing item), then post a
        Stock In movement for the storage quantity. A zero-qty row still (re)prices
        the product without a movement."""
        product = _save_product_from_intake_line(cd)
        qty = cd.get("quantity") or Decimal("0")
        if qty > 0:
            variant = _variant_from_intake_line(product, cd)
            StockMovement.objects.create(
                product=product,
                variant=variant,
                movement_type=StockMovement.TYPE_IN,
                quantity=qty,
                reason="Opening balance",
                reference="OPENING",
            )

    def get(self, request):
        if _opening_stock_used():
            messages.info(request, _("Opening stock has already been applied."))
            return redirect("catalog:opening_stock_detail")
        return render(request, self.template_name, self._context(OpeningStockLineFormSet()))

    def post(self, request):
        if _opening_stock_used():
            messages.error(request, _("Opening stock can only be applied once."))
            return redirect("catalog:opening_stock_detail")
        formset = OpeningStockLineFormSet(request.POST)
        if formset.is_valid():
            kept = 0
            with transaction.atomic():
                for form in formset:
                    cd = form.cleaned_data
                    if not cd or cd.get("DELETE"):
                        continue
                    if not (cd.get("name") or "").strip():
                        continue  # blank row the user added but never filled
                    self._apply_line(cd)
                    kept += 1
                log_user_action(
                    request, "CREATE", model_name="Opening Stock",
                    details=f"Opening stock intake: {kept} item(s)",
                )
            if kept:
                messages.success(
                    request,
                    _("Opening stock applied — %(n)s item(s) loaded into storage.") % {"n": kept},
                )
            else:
                messages.warning(request, _("No items were entered."))
            return redirect("catalog:stock_movement_list")
        return render(request, self.template_name, self._context(formset))


class OpeningStockDetailView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """View-only opening stock record. The stock movements are still the source
    of truth; this page groups the `OPENING` rows into an invoice-like view."""

    permission_required = "catalog.view_stockmovement"
    raise_exception = True
    template_name = "catalog/opening_stock_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        movements = list(
            StockMovement.objects.filter(reference="OPENING")
            .select_related("product", "variant", "created_by")
            .order_by("created_at", "pk")
        )
        ctx["movements"] = movements
        ctx["total_qty"] = sum((m.quantity for m in movements), Decimal("0.00"))
        ctx["created_at"] = movements[0].created_at if movements else None
        ctx["created_by"] = movements[0].created_by if movements else None
        return ctx


class PurchaseInvoiceCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = (
        "catalog.add_purchaseinvoice",
        "catalog.add_product",
        "catalog.change_product",
        "catalog.add_stockmovement",
    )
    raise_exception = True
    template_name = "catalog/purchase_invoice_form.html"

    def _context(self, form, formset):
        return {
            "form": form,
            "formset": formset,
            "current_rate": get_current_rate(),
            "product_map_json": _product_autofill_map_json(),
            "products": Product.objects.order_by("name"),
            "suppliers": Supplier.objects.filter(is_active=True).order_by("name"),
        }

    def _sync_supplier(self, invoice):
        # Suppliers are shared reference data, so no ownership narrowing here.
        sync_party(invoice, prefix="supplier", party_model=Supplier)

    def _kept_forms(self, formset):
        kept = []
        for form in formset:
            cd = form.cleaned_data
            if not cd or cd.get("DELETE"):
                continue
            if not (cd.get("name") or "").strip():
                continue
            kept.append(cd)
        return kept

    def _save(self, request, form, formset):
        kept = self._kept_forms(formset)
        if not kept:
            return None
        with transaction.atomic():
            invoice = form.save(commit=False)
            if invoice.exchange_rate is None:
                invoice.exchange_rate = get_current_rate()
            invoice.status = PurchaseInvoice.STATUS_POSTED
            self._sync_supplier(invoice)
            invoice.save()
            for cd in kept:
                product = _save_product_from_intake_line(cd)
                variant = _variant_from_intake_line(product, cd)
                qty = cd.get("quantity") or Decimal("0")
                PurchaseInvoiceLine.objects.create(
                    invoice=invoice,
                    product=product,
                    variant=variant,
                    category=product.category,
                    description=product.name,
                    unit=product.unit,
                    barcode=product.barcode,
                    color=variant.color or None,
                    size=variant.size or None,
                    cost_usd=product.cost_usd,
                    markup_percent=product.markup_percent,
                    price_usd=product.price_usd,
                    price_lyd_override=product.price_lyd_override,
                    quantity=qty,
                )
                StockMovement.objects.create(
                    product=product,
                    variant=variant,
                    movement_type=StockMovement.TYPE_IN,
                    quantity=qty,
                    reason=f"Purchase invoice {invoice.number}",
                    reference=invoice.number,
                    purchase_invoice=invoice,
                )
            invoice.recalc_totals()
            log_user_action(request, "CREATE", instance=invoice)
        return invoice

    def get(self, request):
        form = PurchaseInvoiceForm()
        formset = PurchaseInvoiceLineFormSet(initial=[{}])
        return render(request, self.template_name, self._context(form, formset))

    def post(self, request):
        form = PurchaseInvoiceForm(request.POST, request.FILES)
        formset = PurchaseInvoiceLineFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            invoice = self._save(request, form, formset)
            if invoice is None:
                messages.error(request, _("Enter at least one purchased item."))
                return render(request, self.template_name, self._context(form, formset))
            messages.success(request, _("Purchase invoice %(no)s posted. Stock updated.") % {"no": invoice.number})
            return redirect("catalog:purchase_invoice_detail", pk=invoice.pk)
        return render(request, self.template_name, self._context(form, formset))


class PurchaseInvoiceDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = PurchaseInvoice
    permission_required = "catalog.view_purchaseinvoice"
    raise_exception = True
    template_name = "catalog/purchase_invoice_detail.html"
    context_object_name = "invoice"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["lines"] = self.object.lines.select_related("product", "variant", "category")
        ctx["movements"] = self.object.stock_movements.select_related("product", "variant").order_by("created_at", "pk")
        return ctx


class PurchaseInvoicePrintView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = PurchaseInvoice
    permission_required = "catalog.view_purchaseinvoice"
    raise_exception = True
    template_name = "catalog/purchase_invoice_print.html"
    context_object_name = "invoice"

    def get_context_data(self, **kwargs):
        from dlux.translations import get_current_language_code

        ctx = super().get_context_data(**kwargs)
        ctx["lines"] = self.object.lines.select_related("product", "variant", "category")
        lang = get_current_language_code(self.request)
        ctx["doc_lang"] = lang
        ctx["is_rtl"] = lang.startswith("ar")
        return ctx
