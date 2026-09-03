import django_tables2 as tables
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from dlux.tables import DluxTable

from common.i18n import t
from common.tables import ModalRowActionsMixin

from django.urls import reverse

from .models import Category, Product, PurchaseInvoice, Service, StockMovement, StockTake, Supplier

_STOCKTAKE_BADGE = {
    "open": "bg-warning text-dark",
    "applied": "bg-success",
    "cancelled": "bg-secondary",
}


def _render_thumb(url):
    """A small square thumbnail for a list row, or a neutral placeholder icon.

    Takes the resolved URL rather than a file field: the picture may live in the
    asset library or, until the backfill has run, still in the old column.
    """
    if url:
        return format_html(
            '<img src="{}" alt="" class="rounded border" '
            'style="width:38px;height:38px;object-fit:cover">',
            url,
        )
    # Static markup (no interpolation) — mark_safe, since Django 6's format_html
    # requires a placeholder arg.
    return mark_safe('<span class="text-muted"><i class="bi bi-image"></i></span>')


def _fmt_lyd(value):
    if value is None:
        return "—"
    return f"{value:,.2f}"


class CategoryTable(ModalRowActionsMixin, DluxTable):
    class Meta(DluxTable.Meta):
        model = Category
        fields = ("name", "is_active", "created_at")
        dlux_actions = True


class SupplierTable(ModalRowActionsMixin, DluxTable):
    class Meta(DluxTable.Meta):
        model = Supplier
        fields = ("name", "phone", "address", "is_active", "created_at")
        dlux_actions = True


class ProductTable(ModalRowActionsMixin, DluxTable):
    image = tables.Column(verbose_name="", orderable=False)
    price_lyd = tables.Column(
        empty_values=(), verbose_name="Price (LYD)", orderable=False
    )
    stock_qty = tables.Column(verbose_name="Stock")

    class Meta(DluxTable.Meta):
        model = Product
        fields = (
            "image", "name", "sku", "barcode", "category", "unit", "color", "size",
            "stock_qty", "price_lyd", "is_active",
        )
        dlux_actions = True

    def render_image(self, record):
        return _render_thumb(record.image_url)

    def render_price_lyd(self, record):
        return _fmt_lyd(record.selling_price_lyd())

    def render_unit(self, record):
        return t(f"unit_{record.unit}", record.get_unit_display())

    def render_color(self, record):
        summary = record.variant_summary_html()
        if summary != "—":
            return summary
        return record.get_color_display() if record.color else "—"

    def render_size(self, record):
        sizes = [
            v.size for v in record.stock_variants()
            if v.size
        ]
        if sizes:
            unique = list(dict.fromkeys(sizes))
            return ", ".join(unique)
        return record.size or "—"

    def render_stock_qty(self, record):
        if not record.track_stock:
            # Django 6.0's format_html requires a placeholder arg; pass the dash.
            return format_html('<span class="text-muted">{}</span>', "—")
        if record.is_low_stock:
            return format_html('<span class="text-danger fw-semibold">{}</span>', f"{record.stock_qty:g}")
        return f"{record.stock_qty:g}"


class ProductLightTable(ModalRowActionsMixin, DluxTable):
    """Minimal Products table for the "light" layout — name, price, stock and
    active only. Everything else (image, sku, barcode, category, unit, variants)
    stays in the record's detail modal (`Product.get_modal_context`), for a
    clutter-free list. Row actions still open that detail/edit modal."""

    price_lyd = tables.Column(
        empty_values=(), verbose_name="Price (LYD)", orderable=False
    )
    stock_qty = tables.Column(verbose_name="Stock")

    class Meta(DluxTable.Meta):
        model = Product
        fields = ("name", "price_lyd", "stock_qty", "is_active")
        dlux_actions = True

    def render_price_lyd(self, record):
        return _fmt_lyd(record.selling_price_lyd())

    def render_stock_qty(self, record):
        if not record.track_stock:
            return format_html('<span class="text-muted">{}</span>', "—")
        if record.is_low_stock:
            return format_html('<span class="text-danger fw-semibold">{}</span>', f"{record.stock_qty:g}")
        return f"{record.stock_qty:g}"


class ServiceTable(ModalRowActionsMixin, DluxTable):
    image = tables.Column(verbose_name="", orderable=False)
    price_lyd = tables.Column(empty_values=(), verbose_name="Price (LYD)", orderable=False)

    class Meta(DluxTable.Meta):
        model = Service
        fields = ("image", "name", "service_type", "price_lyd", "is_active")
        dlux_actions = True

    def render_image(self, record):
        return _render_thumb(record.image_url)

    def render_price_lyd(self, record):
        price = record.selling_price_lyd()
        return _fmt_lyd(price) if price is not None else t("ui_per_job", "Per job")

    def render_service_type(self, record):
        return t(f"svctype_{record.service_type}", record.get_service_type_display())


class StockMovementTable(ModalRowActionsMixin, DluxTable):
    # The ledger is append-only — see StockMovement.delete(). A movement is
    # undone by cancelling its source document, which posts a compensating row.
    row_delete_action = False

    class Meta(DluxTable.Meta):
        model = StockMovement
        fields = ("product", "variant", "movement_type", "quantity", "reference", "created_by", "created_at")
        dlux_actions = True

    def render_movement_type(self, record):
        return t(f"mtype_{record.movement_type}", record.get_movement_type_display())

    def render_variant(self, record):
        return record.variant.display_label if record.variant_id else "—"


class PurchaseInvoiceTable(DluxTable):
    number = tables.Column(verbose_name="Purchase Invoice No.")
    supplier = tables.Column(empty_values=(), verbose_name="Supplier", orderable=False)
    status = tables.Column(verbose_name="Status")
    total_usd = tables.Column(verbose_name="Total (USD)")
    total_lyd = tables.Column(verbose_name="Total (LYD)")

    class Meta(DluxTable.Meta):
        model = PurchaseInvoice
        fields = ("number", "supplier", "invoice_date", "status", "total_usd", "total_lyd", "created_by", "created_at")
        dlux_actions = True

    def get_dlux_base_actions(self, record):
        return [
            {
                "label": "ui_view_purchase_invoice",
                "icon": "bi bi-eye",
                "type": "url",
                "url": reverse("catalog:purchase_invoice_detail", args=[record.pk]),
                "dblclick": True,
                "permissions": ["catalog.view_purchaseinvoice"],
            },
            {
                "label": "ui_print_export",
                "icon": "bi bi-printer",
                "type": "url",
                "url": reverse("catalog:purchase_invoice_print", args=[record.pk]),
                "target": "_blank",
                "permissions": ["catalog.view_purchaseinvoice"],
            },
        ]

    def render_number(self, record):
        return record.number or "—"

    def render_supplier(self, record):
        return record.display_supplier

    def render_status(self, record):
        return format_html(
            '<span class="badge rounded-pill {}">{}</span>',
            "bg-success" if record.status == PurchaseInvoice.STATUS_POSTED else "bg-secondary",
            t(f"purchase_status_{record.status}", record.get_status_display()),
        )

    def render_total_usd(self, record):
        return f"{record.total_usd:,.2f}"

    def render_total_lyd(self, record):
        return f"{record.total_lyd:,.2f}"


class StockTakeTable(DluxTable):
    number = tables.Column(verbose_name="Count No.")
    status = tables.Column(verbose_name="Status")

    class Meta(DluxTable.Meta):
        model = StockTake
        fields = ("number", "count_date", "status", "created_by", "created_at")
        dlux_actions = False  # full-page count/detail flow, not modal CRUD

    def render_number(self, record):
        return format_html(
            '<a href="{}" class="fw-semibold text-decoration-none">{}</a>',
            reverse("catalog:stock_take_detail", args=[record.pk]),
            record.number or "—",
        )

    def render_status(self, record):
        return format_html(
            '<span class="badge rounded-pill {}">{}</span>',
            _STOCKTAKE_BADGE.get(record.status, "bg-secondary"),
            t(f"stocktake_status_{record.status}", record.get_status_display()),
        )
