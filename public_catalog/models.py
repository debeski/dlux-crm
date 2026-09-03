from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.text import slugify

from dlux.managers import ScopedManager
from dlux.models import ManagedAssetField, ScopedModel

from catalog.models import Product, Service, product_color_hex


class PublicCatalogListingQuerySet(models.QuerySet):
    def published(self):
        return (
            self.filter(is_published=True)
            .filter(
                Q(product__isnull=False, product__is_active=True, product__deleted_at__isnull=True)
                | Q(service__isnull=False, service__is_active=True, service__deleted_at__isnull=True)
            )
            .select_related("product", "product__category", "service")
            .prefetch_related("product__variants")
        )


class PublicCatalogListingManager(ScopedManager.from_queryset(PublicCatalogListingQuerySet)):
    pass


class PublicCatalogListing(ScopedModel):
    """Curated public listing linked to an internal Product or Service."""

    product = models.ForeignKey(
        Product, null=True, blank=True, on_delete=models.PROTECT, related_name="public_listings"
    )
    service = models.ForeignKey(
        Service, null=True, blank=True, on_delete=models.PROTECT, related_name="public_listings"
    )
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    public_title = models.CharField(max_length=220, blank=True)
    public_summary = models.CharField(max_length=280, blank=True)
    public_body = models.TextField(blank=True)
    image_override = models.ImageField(upload_to="public_catalog/listings/", blank=True)
    #: Reads the catalog pools as well as its own: this field exists to show a
    #: *different shot of the same item*, so the product and service photos are
    #: exactly what an operator wants to choose between. Uploads still land in
    #: this listing's own namespace and never back into the catalog's.
    image_override_asset = ManagedAssetField(
        kind="image",
        reads=["catalog.product", "catalog.service"],
        verbose_name="Public image",
    )
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=100)
    show_price = models.BooleanField(default=True)
    show_availability = models.BooleanField(default=True)
    show_when_unavailable = models.BooleanField(default=True)
    installation_notes = models.TextField(blank=True)
    warranty_notes = models.TextField(blank=True)
    seo_title = models.CharField(max_length=220, blank=True)
    seo_description = models.CharField(max_length=300, blank=True)

    objects = PublicCatalogListingManager()

    class Meta:
        verbose_name = "Public Catalog Listing"
        verbose_name_plural = "Public Catalog Listings"
        ordering = ["sort_order", "public_title", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(product__isnull=False) & Q(service__isnull=True))
                    | (Q(product__isnull=True) & Q(service__isnull=False))
                ),
                name="public_listing_one_source",
            ),
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(product__isnull=False),
                name="uniq_public_listing_product",
            ),
            models.UniqueConstraint(
                fields=["service"],
                condition=Q(service__isnull=False),
                name="uniq_public_listing_service",
            ),
        ]

    def __str__(self):
        return self.display_title

    def clean(self):
        super().clean()
        if bool(self.product_id) == bool(self.service_id):
            raise ValidationError("Choose exactly one Product or one Service.")

    @property
    def source(self):
        return self.product or self.service

    @property
    def source_kind(self):
        return "product" if self.product_id else "service"

    @property
    def display_title(self):
        source = self.source
        return self.public_title or (source.name if source is not None else "")

    @property
    def display_summary(self):
        source = self.source
        return self.public_summary or (source.description if source is not None else "")

    @property
    def display_body(self):
        return self.public_body or self.display_summary

    @property
    def source_label(self):
        if self.product_id:
            return self.product.category.name if self.product.category_id else "Product"
        if self.service_id:
            return self.service.get_service_type_display()
        return ""

    @property
    def image_url(self):
        """The override if there is one, otherwise whatever the source shows.

        Each step prefers the asset library and falls back to the old column, so
        a half-backfilled database renders the same as a finished one.
        """
        if self.image_override_asset_id and self.image_override_asset.url:
            return self.image_override_asset.url
        if self.image_override:
            return self.image_override.url
        return getattr(self.source, "image_url", "") or ""

    def public_price_lyd(self, rate=None):
        if not self.show_price:
            return None
        source = self.source
        if source is None:
            return None
        return source.selling_price_lyd(rate)

    @property
    def price_lyd(self):
        return self.public_price_lyd()

    @property
    def availability_code(self):
        if self.service_id:
            return "by_appointment"
        product = self.product
        if product is None:
            return "unavailable"
        if not product.track_stock:
            return "available_to_order"
        qty = product.stock_qty or Decimal("0")
        if qty <= 0:
            return "unavailable"
        threshold = product.reorder_level if product.reorder_level > 0 else Decimal("3")
        if qty <= threshold:
            return "limited"
        return "available"

    @property
    def availability_label(self):
        labels = {
            "available": "Available",
            "limited": "Limited availability",
            "available_to_order": "Available to order",
            "by_appointment": "By appointment",
            "unavailable": "Currently unavailable",
        }
        return labels.get(self.availability_code, "Contact us")

    @property
    def is_available_for_public(self):
        return self.availability_code != "unavailable"

    @property
    def public_variants(self):
        if not self.product_id:
            return []
        variants = self.product.stock_variants()
        items = []
        for variant in variants:
            items.append({
                "label": variant.display_label,
                "color": variant.color or "",
                "color_label": variant.color_label,
                "color_hex": product_color_hex(variant.color),
                "size": variant.size or "",
            })
        return items

    def get_absolute_url(self):
        return reverse("public_catalog:item_detail", args=[self.slug])

    def save(self, *args, **kwargs):
        if not self.slug:
            source = self.source
            source_name = self.display_title or (source.name if source is not None else "listing")
            source_id = self.product_id or self.service_id or "new"
            base = slugify(source_name, allow_unicode=False) or "listing"
            self.slug = f"{self.source_kind}-{source_id}-{base}"[:160].strip("-")
        super().save(*args, **kwargs)


class PublicContactMessage(ScopedModel):
    """Idempotent public contact submission from the storefront."""

    STATUS_RECEIVED = "received"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = (
        (STATUS_RECEIVED, "Received"),
        (STATUS_SENT, "Email sent"),
        (STATUS_FAILED, "Email failed"),
        (STATUS_SKIPPED, "Skipped"),
    )

    idempotency_key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=160)
    email = models.EmailField()
    phone = models.CharField(max_length=60, blank=True)
    subject = models.CharField(max_length=180, blank=True)
    message = models.TextField()
    source_path = models.CharField(max_length=300, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    email_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RECEIVED)
    email_recipient = models.EmailField(blank=True)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_error = models.TextField(blank=True)

    class Meta:
        verbose_name = "Public Contact Message"
        verbose_name_plural = "Public Contact Messages"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"], name="pub_contact_created_idx"),
            models.Index(fields=["email_status", "created_at"], name="pub_contact_status_idx"),
        ]

    def __str__(self):
        return f"{self.name} <{self.email}>"
