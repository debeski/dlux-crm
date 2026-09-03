"""
Catalog domain models — everything Switch can put on an invoice.

Two sellable families:
  * ``Product``  — stock items (smart locks, spare parts, unrelated goods).
  * ``Service``  — labour offerings (installation, maintenance, warranty, delivery).

Pricing model (decided with the owner): **hybrid USD base + optional LYD override**.
A product's price is held in USD (cost + markup, the way Switch imports), and the
LYD selling price is derived live from the global black-market rate in ``finance``.
Any item may carry a manual ``price_lyd_override`` for ad-hoc / unrelated goods.

``catalog`` depends on ``finance`` only (for the rate). It must never import
``sales`` — the stock ledger references invoices by their string number instead.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.core.validators import MinValueValidator
from django.db import IntegrityError, models
from django.utils import timezone

from dlux.models import ManagedAssetField, ScopedModel

from finance.services import get_current_rate, usd_to_lyd

TWO_PLACES = Decimal("0.01")

PRODUCT_COLOR_SWATCHES = {
    "black": "#111111",
    "gray": "#808080",
    "white": "#ffffff",
    "red": "#dc3545",
    "blue": "#0d6efd",
    "green": "#198754",
    "yellow": "#ffc107",
    "orange": "#fd7e14",
    "purple": "#6f42c1",
    "pink": "#d63384",
    "brown": "#795548",
    "beige": "#d8c3a5",
    "navy": "#001f54",
    "gold": "#d4af37",
    "teal": "#20c997",
}


def product_color_hex(color):
    return PRODUCT_COLOR_SWATCHES.get(color or "", "transparent")


def product_color_label(color):
    from common.i18n import t

    if not color:
        return t("ui_no_color", "No color")
    return t(f"color_{color}", dict(Product.COLOR_CHOICES).get(color, color))


class ImageAssetMixin(models.Model):
    """A picture held in the dlux asset library, with the old file as a fallback.

    ``image_asset`` is the field of record; the plain ``image`` column stays
    readable until the backfill has adopted every file (see the
    ``adopt_image_assets`` command). Read through ``image_url`` rather than
    either field so a half-migrated database renders the same as a finished one.
    """

    class Meta:
        abstract = True

    @property
    def image_url(self):
        if self.image_asset_id and self.image_asset.url:
            return self.image_asset.url
        return self.image.url if self.image else ""

    @property
    def has_image(self):
        return bool(self.image_url)


def _image_detail_row(instance, label):
    """A dlux detail row rendering the instance's image as a thumbnail (HTML), or
    ``None`` when there's no image. Consumed by ``get_modal_context`` and rendered
    via the project's ``extra_detail_fields`` (is_html) override."""
    url = getattr(instance, "image_url", "")
    if not url:
        return None
    from django.utils.html import format_html

    return {
        "label": label,
        "is_html": True,
        "value": format_html(
            '<img src="{}" alt="" class="img-fluid rounded border" style="max-height:180px">',
            url,
        ),
    }


class Category(ScopedModel):
    """Grouping for products (e.g. Smart Locks, Spare Parts, Accessories)."""
    is_section = True
    name = models.CharField(max_length=120, verbose_name="Name")
    description = models.TextField(blank=True, verbose_name="Description")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Supplier(ScopedModel):
    """A stock supplier. Purchase invoices snapshot these fields so old
    documents remain readable even if the supplier record changes later."""

    name = models.CharField(max_length=200, verbose_name="Name")
    phone = models.CharField(max_length=40, blank=True, db_index=True, verbose_name="Phone")
    address = models.CharField(max_length=255, blank=True, verbose_name="Address")
    notes = models.TextField(blank=True, verbose_name="Notes")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Supplier"
        verbose_name_plural = "Suppliers"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(ImageAssetMixin, ScopedModel):
    """A stock item. Priced in USD; sold in LYD via the live rate."""

    COLOR_BLACK = "black"
    COLOR_GRAY = "gray"
    COLOR_WHITE = "white"
    COLOR_RED = "red"
    COLOR_BLUE = "blue"
    COLOR_GREEN = "green"
    COLOR_YELLOW = "yellow"
    COLOR_ORANGE = "orange"
    COLOR_PURPLE = "purple"
    COLOR_PINK = "pink"
    COLOR_BROWN = "brown"
    COLOR_BEIGE = "beige"
    COLOR_NAVY = "navy"
    COLOR_GOLD = "gold"
    COLOR_TEAL = "teal"
    COLOR_CHOICES = (
        (COLOR_BLACK, "Black"),
        (COLOR_GRAY, "Gray"),
        (COLOR_WHITE, "White"),
        (COLOR_RED, "Red"),
        (COLOR_BLUE, "Blue"),
        (COLOR_GREEN, "Green"),
        (COLOR_YELLOW, "Yellow"),
        (COLOR_ORANGE, "Orange"),
        (COLOR_PURPLE, "Purple"),
        (COLOR_PINK, "Pink"),
        (COLOR_BROWN, "Brown"),
        (COLOR_BEIGE, "Beige"),
        (COLOR_NAVY, "Navy"),
        (COLOR_GOLD, "Gold"),
        (COLOR_TEAL, "Teal"),
    )

    UNIT_PIECE = "piece"
    UNIT_BOX = "box"
    UNIT_SET = "set"
    UNIT_PAIR = "pair"
    UNIT_METER = "meter"
    UNIT_KG = "kg"
    UNIT_CHOICES = (
        (UNIT_PIECE, "Piece"),
        (UNIT_BOX, "Box"),
        (UNIT_SET, "Set"),
        (UNIT_PAIR, "Pair"),
        (UNIT_METER, "Meter"),
        (UNIT_KG, "Kg"),
    )

    sku = models.CharField(max_length=40, unique=True, blank=True, verbose_name="SKU")
    name = models.CharField(max_length=200, verbose_name="Name")
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.PROTECT,
        related_name="products", verbose_name="Category",
    )
    description = models.TextField(blank=True, verbose_name="Description")
    barcode = models.CharField(max_length=64, blank=True, db_index=True, verbose_name="Barcode")
    #: Superseded by `image_asset`; kept readable until the backfill has
    #: adopted every stored file. Read `image_url`, never either field.
    image = models.ImageField(upload_to="catalog/products/", blank=True, verbose_name="Image")
    image_asset = ManagedAssetField(kind="image", verbose_name="Image")
    unit = models.CharField(max_length=12, choices=UNIT_CHOICES, default=UNIT_PIECE, verbose_name="Unit")
    color = models.CharField(
        max_length=16, choices=COLOR_CHOICES, null=True, blank=True, verbose_name="Color",
    )
    size = models.CharField(max_length=120, null=True, blank=True, verbose_name="Size / Spec")

    # --- Pricing (USD base) ---
    cost_usd = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Import Cost (USD)",
    )
    markup_percent = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Markup %",
        help_text="Profit added on top of the import cost. Changing it recalculates the USD selling price.",
    )
    price_usd = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Selling Price (USD)",
        help_text="Auto-filled from cost + markup; edit it directly and the markup follows.",
    )
    price_lyd_override = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Manual LYD Price",
        help_text="Leave blank to sell at the live rate; enter a value to fix the LYD price for this item.",
    )

    # --- Stock ---
    track_stock = models.BooleanField(default=True, verbose_name="Track Stock")
    stock_qty = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="Stock Qty",
    )
    reorder_level = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="Reorder Level",
    )

    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ["name"]
        indexes = [models.Index(fields=["name"], name="catalog_product_name_idx")]

    def __str__(self):
        return f"{self.name} ({self.sku})" if self.sku else self.name

    def save(self, *args, **kwargs):
        # Persist the derived USD selling price so detail views and every
        # downstream read see a real number instead of 0 when the user only
        # entered cost + markup (the form JS normally fills this, but this keeps
        # the record consistent even for API/import/no-JS saves).
        if not self.price_usd or self.price_usd <= 0:
            derived = self.effective_price_usd
            if derived and derived > 0:
                self.price_usd = derived
        super().save(*args, **kwargs)
        if not self.sku:
            # SKU needs the pk, so assign on the next pass without re-running audit.
            self.sku = f"P{self.pk:05d}"
            super().save(update_fields=["sku"])

    def get_unit_display(self):
        """Translated unit label (dlux's generic detail view calls this directly,
        and Django's auto version would return the untranslated English choice)."""
        from common.i18n import t
        return t(f"unit_{self.unit}", dict(self.UNIT_CHOICES).get(self.unit, self.unit))

    def get_color_display(self):
        """Translated color label for dlux detail/list rendering."""
        if not self.color:
            return ""
        return product_color_label(self.color)

    def stock_variants(self, include_zero=False):
        qs = self.variants.all().order_by("color", "size", "pk")
        if not include_zero:
            qs = qs.filter(stock_qty__gt=0)
        return qs

    def variant_summary_html(self, include_zero=False):
        from django.utils.html import format_html
        from django.utils.safestring import mark_safe

        variants = list(self.stock_variants(include_zero=include_zero))
        if not variants:
            return "—"
        parts = []
        for variant in variants:
            color = variant.color or ""
            bg = product_color_hex(color)
            border = "#111111" if color == self.COLOR_WHITE else (bg if color else "var(--bs-border-color,#adb5bd)")
            title = variant.display_label
            parts.append(format_html(
                '<span class="d-inline-flex align-items-center gap-1 me-2 mb-1" title="{}">'
                '<span style="display:inline-block;width:.95rem;height:.95rem;border-radius:999px;'
                'border:2px solid {};background:{};box-shadow:inset 0 0 0 1px rgba(255,255,255,.45);"></span>'
                '<span class="small">{} × {}</span>'
                '</span>',
                f"{title}: {variant.stock_qty:g}",
                border,
                bg,
                title,
                f"{variant.stock_qty:g}",
            ))
        return mark_safe("".join(str(part) for part in parts))

    @property
    def effective_price_usd(self):
        """USD selling price: explicit ``price_usd`` if set, else cost + markup."""
        if self.price_usd and self.price_usd > 0:
            return self.price_usd
        base = (self.cost_usd or Decimal("0")) * (Decimal("1") + (self.markup_percent or Decimal("0")) / Decimal("100"))
        return base.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    def selling_price_lyd(self, rate=None):
        """The LYD price shown to customers: manual override wins, else converted."""
        if self.price_lyd_override is not None:
            return self.price_lyd_override
        return usd_to_lyd(self.effective_price_usd, rate)

    def get_modal_context(self):
        """Extra rows for the dlux generic detail view. Surfaces the *effective*
        LYD selling price (live-converted unless a manual override is set) so the
        detail card matches the product list, whose price column is also derived."""
        from common.i18n import t
        price = self.selling_price_lyd()
        rows = [
            {
                "label": t("label_product_selling_price_lyd", "Selling Price (LYD)"),
                "value": f"{price:,.2f}" if price is not None else "—",
            }
        ]
        if self.stock_variants().exists():
            rows.append({
                "label": t("label_product_available_variants", "Available variants"),
                "is_html": True,
                "value": self.variant_summary_html(),
            })
        else:
            if self.color:
                rows.append({
                    "label": t("label_product_color", "Color"),
                    "value": self.get_color_display(),
                })
            if self.size:
                rows.append({
                    "label": t("label_product_size", "Size"),
                    "value": self.size,
                })
        image_row = _image_detail_row(self, t("label_product_image", "Image"))
        if image_row:
            rows.insert(0, image_row)
        return {"extra_detail_fields": rows}

    @property
    def is_low_stock(self):
        return self.track_stock and self.stock_qty <= self.reorder_level


class ProductVariant(models.Model):
    """Stock-bearing color/size bucket for a Product.

    Product.color/size remain as legacy descriptive fields, but every new stock
    movement that knows a color/size should point at one of these rows so
    orange and blue stock are tracked independently while Product.stock_qty keeps
    the aggregate total.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants", verbose_name="Product")
    color = models.CharField(
        max_length=16, choices=Product.COLOR_CHOICES, blank=True, default="", verbose_name="Color"
    )
    size = models.CharField(max_length=120, blank=True, default="", verbose_name="Size / Spec")
    stock_qty = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="Stock Qty")

    class Meta:
        verbose_name = "Product Variant"
        verbose_name_plural = "Product Variants"
        default_permissions = ()
        ordering = ["product__name", "color", "size"]
        constraints = [
            models.UniqueConstraint(fields=["product", "color", "size"], name="uniq_product_variant_color_size"),
        ]
        indexes = [
            models.Index(fields=["product", "color", "size"], name="catalog_variant_lookup_idx"),
        ]

    def __str__(self):
        return f"{self.product} — {self.display_label}"

    @staticmethod
    def normalize_color(color):
        return (color or "").strip()

    @staticmethod
    def normalize_size(size):
        return (size or "").strip()

    @classmethod
    def get_or_create_for(cls, product, color=None, size=None):
        return cls.objects.get_or_create(
            product=product,
            color=cls.normalize_color(color),
            size=cls.normalize_size(size),
        )[0]

    @property
    def color_label(self):
        return product_color_label(self.color) if self.color else ""

    @property
    def display_label(self):
        from common.i18n import t

        parts = []
        if self.color:
            parts.append(self.color_label)
        else:
            parts.append(t("ui_no_color", "No color"))
        if self.size:
            parts.append(self.size)
        return " / ".join(parts)


class Service(ImageAssetMixin, ScopedModel):
    """A labour / after-sale offering. Priced in USD, LYD, or quoted per job."""

    TYPE_INSTALLATION = "installation"
    TYPE_MAINTENANCE = "maintenance"
    TYPE_WARRANTY = "warranty"
    TYPE_DELIVERY = "delivery"
    TYPE_OTHER = "other"
    TYPE_CHOICES = (
        (TYPE_INSTALLATION, "Installation"),
        (TYPE_MAINTENANCE, "Maintenance"),
        (TYPE_WARRANTY, "Warranty / After-sale"),
        (TYPE_DELIVERY, "Delivery"),
        (TYPE_OTHER, "Other"),
    )

    name = models.CharField(max_length=200, verbose_name="Name")
    service_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_INSTALLATION, db_index=True,
        verbose_name="Service Type",
    )
    description = models.TextField(blank=True, verbose_name="Description")
    image = models.ImageField(upload_to="catalog/services/", blank=True, verbose_name="Image")
    image_asset = ManagedAssetField(kind="image", verbose_name="Image")
    price_usd = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Price (USD)",
    )
    price_lyd_override = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Manual LYD Price",
    )
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Service"
        verbose_name_plural = "Services"
        ordering = ["service_type", "name"]

    def __str__(self):
        return self.name

    def get_service_type_display(self):
        """Translated service-type label (dlux's generic detail view calls this)."""
        from common.i18n import t
        return t(f"svctype_{self.service_type}", dict(self.TYPE_CHOICES).get(self.service_type, self.service_type))

    def selling_price_lyd(self, rate=None):
        """Override wins; else convert USD; else ``None`` meaning "quote per job"."""
        if self.price_lyd_override is not None:
            return self.price_lyd_override
        if self.price_usd is not None:
            return usd_to_lyd(self.price_usd, rate)
        return None

    def get_modal_context(self):
        """Effective LYD selling price for the dlux generic detail view (or the
        "Per job" marker when the service is quoted per job)."""
        from common.i18n import t
        price = self.selling_price_lyd()
        rows = [
            {
                "label": t("label_service_selling_price_lyd", "Selling Price (LYD)"),
                "value": f"{price:,.2f}" if price is not None else t("ui_per_job", "Per job"),
            }
        ]
        image_row = _image_detail_row(self, t("label_service_image", "Image"))
        if image_row:
            rows.insert(0, image_row)
        return {"extra_detail_fields": rows}


class PurchaseInvoice(ScopedModel):
    """Inbound stock invoice. Saving a completed purchase invoice creates
    ``StockMovement`` rows for each line; the invoice is the procurement document
    and the movements are the stock ledger audit trail."""

    STATUS_POSTED = "posted"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_POSTED, "Posted"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    number = models.CharField(max_length=20, unique=True, blank=True, verbose_name="Purchase Invoice No.")
    supplier = models.ForeignKey(
        Supplier, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="purchase_invoices", verbose_name="Supplier",
    )
    supplier_name = models.CharField(max_length=200, blank=True, verbose_name="Supplier Name")
    supplier_phone = models.CharField(max_length=40, blank=True, verbose_name="Supplier Phone")
    supplier_address = models.CharField(max_length=255, blank=True, verbose_name="Supplier Address")
    invoice_date = models.DateField(default=timezone.localdate, verbose_name="Invoice Date")
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_POSTED, db_index=True,
        verbose_name="Status",
    )
    exchange_rate = models.DecimalField(
        max_digits=12, decimal_places=4, verbose_name="Exchange Rate (LYD/USD)"
    )
    attachment = models.FileField(
        upload_to="purchase_invoices/", blank=True, verbose_name="Attachment"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    total_usd = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"), editable=False,
        verbose_name="Total (USD)",
    )
    total_lyd = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"), editable=False,
        verbose_name="Total (LYD)",
    )
    posted_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Posted At")

    class Meta:
        verbose_name = "Purchase Invoice"
        verbose_name_plural = "Purchase Invoices"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="catalog_pin_status_idx"),
            models.Index(fields=["-invoice_date"], name="catalog_pin_date_idx"),
        ]

    def __str__(self):
        return self.number or f"(purchase #{self.pk})"

    def save(self, *args, **kwargs):
        if self.exchange_rate is None:
            self.exchange_rate = get_current_rate()
        if self.status == self.STATUS_POSTED and self.posted_at is None:
            self.posted_at = timezone.now()
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"PINV-{self.pk:06d}"
            super().save(update_fields=["number"])

    @property
    def display_supplier(self):
        if self.supplier_id:
            return self.supplier.name
        return self.supplier_name or "—"

    @property
    def status_label(self):
        from common.i18n import t
        return t(f"purchase_status_{self.status}", self.get_status_display())

    def recalc_totals(self, commit=True):
        total_usd = sum((line.line_total_usd for line in self.lines.all()), Decimal("0.00"))
        self.total_usd = total_usd.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        self.total_lyd = usd_to_lyd(self.total_usd, self.exchange_rate)
        if commit:
            self.save(update_fields=["total_usd", "total_lyd", "updated_at"])


class PurchaseInvoiceLine(models.Model):
    """One product bought on a purchase invoice. Product/pricing fields are
    snapshotted from the intake row so the purchase document remains historical."""

    invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="purchase_invoice_lines", verbose_name="Product"
    )
    variant = models.ForeignKey(
        ProductVariant, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="purchase_invoice_lines", verbose_name="Variant",
    )
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="purchase_invoice_lines", verbose_name="Category",
    )
    description = models.CharField(max_length=200, verbose_name="Description")
    unit = models.CharField(max_length=12, choices=Product.UNIT_CHOICES, default=Product.UNIT_PIECE, verbose_name="Unit")
    barcode = models.CharField(max_length=64, blank=True, verbose_name="Barcode")
    color = models.CharField(
        max_length=16, choices=Product.COLOR_CHOICES, null=True, blank=True, verbose_name="Color",
    )
    size = models.CharField(max_length=120, null=True, blank=True, verbose_name="Size / Spec")
    cost_usd = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Import Cost (USD)",
    )
    markup_percent = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Markup %",
    )
    price_usd = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Selling Price (USD)",
    )
    price_lyd_override = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Manual LYD Price",
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Quantity",
    )

    class Meta:
        verbose_name = "Purchase Invoice Line"
        verbose_name_plural = "Purchase Invoice Lines"
        default_permissions = ()
        ordering = ["id"]

    def __str__(self):
        return f"{self.description} × {self.quantity:g}"

    @property
    def line_total_usd(self):
        return ((self.quantity or Decimal("0")) * (self.cost_usd or Decimal("0"))).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )

    @property
    def line_total_lyd(self):
        return usd_to_lyd(self.line_total_usd, self.invoice.exchange_rate)

    @property
    def unit_label(self):
        from common.i18n import t
        return t(f"unit_{self.unit}", dict(Product.UNIT_CHOICES).get(self.unit, self.unit))

    @property
    def color_label(self):
        from common.i18n import t
        if not self.color:
            return ""
        return t(f"color_{self.color}", dict(Product.COLOR_CHOICES).get(self.color, self.color))


class StockMovement(ScopedModel):
    """Append-style inventory ledger. Every change to ``Product.stock_qty`` is a row.

    Sales invoices stay decoupled via the string ``reference``. Purchase invoices
    live in this app and also keep a nullable FK for easy drill-down from stock-in
    movements.
    """

    TYPE_IN = "in"
    TYPE_OUT = "out"
    TYPE_ADJUST = "adjustment"
    TYPE_CHOICES = (
        (TYPE_IN, "Stock In"),
        (TYPE_OUT, "Stock Out"),
        (TYPE_ADJUST, "Adjustment"),
    )

    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="movements", verbose_name="Product"
    )
    variant = models.ForeignKey(
        ProductVariant, null=True, blank=True, on_delete=models.PROTECT,
        related_name="movements", verbose_name="Variant",
    )
    movement_type = models.CharField(
        max_length=12, choices=TYPE_CHOICES, default=TYPE_IN, verbose_name="Type"
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="Quantity",
        help_text="A positive amount for Stock In / Stock Out; a signed (+/-) amount for an Adjustment.",
    )
    reason = models.CharField(max_length=200, blank=True, verbose_name="Reason")
    reference = models.CharField(max_length=64, blank=True, db_index=True, verbose_name="Reference")
    purchase_invoice = models.ForeignKey(
        PurchaseInvoice, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="stock_movements", verbose_name="Purchase Invoice",
    )

    class Meta:
        verbose_name = "Stock Movement"
        verbose_name_plural = "Stock Movements"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["product", "-created_at"], name="catalog_move_prod_idx")]

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.quantity} × {self.product_id}"

    def delete(self, *args, **kwargs):
        """The ledger is append-only: a movement is never removed.

        ``save()`` applies its delta to ``Product.stock_qty`` on insert only, so
        deleting the row would drop the ledger entry and leave the stock figure
        it moved standing — the balance would silently drift from its history.

        A movement is undone by posting a compensating one, which is what
        ``sales.services.cancel_invoice`` does: it writes a Stock In for every
        line the cancelled invoice drew down, and leaves the original Stock Out
        in place as the record of what happened. Corrections go the same way,
        as an Adjustment.

        Nothing in the project deletes a movement, and no seeded role holds
        ``catalog.delete_stockmovement``; this closes the remaining paths — the
        admin, a shell, and a superuser's row menu.
        """
        raise IntegrityError(
            "Stock movements are an append-only ledger and cannot be deleted. "
            "Post a compensating movement (or cancel the source document) instead."
        )

    def get_movement_type_display(self):
        """Translated movement-type label (dlux's generic detail view calls this)."""
        from common.i18n import t
        return t(f"mtype_{self.movement_type}", dict(self.TYPE_CHOICES).get(self.movement_type, self.movement_type))

    @property
    def signed_quantity(self):
        if self.movement_type == self.TYPE_OUT:
            return -abs(self.quantity)
        if self.movement_type == self.TYPE_IN:
            return abs(self.quantity)
        return self.quantity  # adjustment: caller supplies the sign

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if self.variant_id:
            if self.product_id is None:
                self.product = self.variant.product
            elif self.variant.product_id != self.product_id:
                from django.core.exceptions import ValidationError

                raise ValidationError("Stock movement variant must belong to the selected product.")
        super().save(*args, **kwargs)
        # Apply the delta to the product on first insert only (ledger is append-only).
        if is_new and self.product.track_stock:
            Product.objects.filter(pk=self.product_id).update(
                stock_qty=models.F("stock_qty") + self.signed_quantity
            )
            if self.variant_id:
                ProductVariant.objects.filter(pk=self.variant_id).update(
                    stock_qty=models.F("stock_qty") + self.signed_quantity
                )


class StockTake(ScopedModel):
    """A physical inventory count (جرد). You snapshot the system quantity per
    product, enter what you actually counted on the shelf, then **apply** the
    take — which posts an Adjustment ``StockMovement`` for every discrepancy so
    ``stock_qty`` matches reality. The variance list is the audit trail.

    Inventory is a management concern (not per-rep), so this is gated purely by
    permissions and is not row-scoped — no ``OWNER_FIELDS``.
    """

    STATUS_OPEN = "open"
    STATUS_APPLIED = "applied"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_OPEN, "Open"),
        (STATUS_APPLIED, "Applied"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    number = models.CharField(max_length=20, unique=True, blank=True, verbose_name="Count No.")
    count_date = models.DateField(default=timezone.localdate, verbose_name="Count Date")
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True, verbose_name="Status",
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    applied_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Applied At")

    class Meta:
        verbose_name = "Stock Take"
        verbose_name_plural = "Stock Takes"
        ordering = ["-created_at"]
        permissions = [
            ("apply_stocktake", "Can apply a stock take (post adjustments)"),
            ("view_inventory_valuation", "Can view the inventory valuation report"),
        ]

    def __str__(self):
        return self.number or f"(count #{self.pk})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"ST-{self.pk:06d}"
            super().save(update_fields=["number"])

    @property
    def status_label(self):
        from common.i18n import t
        return t(f"stocktake_status_{self.status}", self.get_status_display())

    @property
    def is_open(self):
        return self.status == self.STATUS_OPEN

    @property
    def discrepancy_lines(self):
        """Counted lines whose count differs from the system snapshot."""
        return [ln for ln in self.lines.all() if ln.variance not in (None, Decimal("0.00"), 0)]

    @property
    def counted_count(self):
        return sum(1 for ln in self.lines.all() if ln.counted_qty is not None)

    @property
    def total_variance_value_lyd(self):
        rate = get_current_rate()
        return sum((ln.variance_value_lyd(rate) for ln in self.discrepancy_lines), Decimal("0.00"))

    def apply(self, actor=None):
        """Post an Adjustment movement for every counted discrepancy, bringing
        ``stock_qty`` to the counted figure, then lock the take as applied."""
        from django.core.exceptions import ValidationError
        from django.db import transaction

        if self.status != self.STATUS_OPEN:
            raise ValidationError("Only an open stock take can be applied.")
        with transaction.atomic():
            for line in self.lines.select_related("product"):
                variance = line.variance
                if variance in (None, Decimal("0.00"), 0):
                    continue
                if not line.product.track_stock:
                    continue
                StockMovement.objects.create(
                    product=line.product,
                    movement_type=StockMovement.TYPE_ADJUST,
                    quantity=variance,  # signed delta counted − system
                    reason=f"Stock take {self.number}",
                    reference=self.number,
                )
            self.status = self.STATUS_APPLIED
            self.applied_at = timezone.now()
            self.save(update_fields=["status", "applied_at", "updated_at"])


class StockTakeLine(models.Model):
    """One product counted within a StockTake. ``system_qty`` is the snapshot
    taken when the line was created; ``counted_qty`` is the physical count
    (``None`` = not counted). Managed through the parent take."""

    stock_take = models.ForeignKey(StockTake, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_take_lines", verbose_name="Product")
    system_qty = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="System Qty")
    counted_qty = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Counted Qty",
    )

    class Meta:
        verbose_name = "Stock Take Line"
        verbose_name_plural = "Stock Take Lines"
        default_permissions = ()  # managed through the parent StockTake
        ordering = ["product__name"]
        constraints = [
            models.UniqueConstraint(fields=["stock_take", "product"], name="uniq_stocktake_product"),
        ]

    def __str__(self):
        return f"{self.product.name}: {self.counted_qty}/{self.system_qty}"

    @property
    def variance(self):
        """Counted − system (signed), or ``None`` if not yet counted."""
        if self.counted_qty is None:
            return None
        return self.counted_qty - self.system_qty

    def variance_value_lyd(self, rate=None):
        """LYD value of the discrepancy (variance × unit cost). 0 if uncounted."""
        v = self.variance
        if v is None:
            return Decimal("0.00")
        return usd_to_lyd(v * (self.product.cost_usd or Decimal("0")), rate)
