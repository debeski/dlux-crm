from django.contrib import admin

from .models import Category, Product, ProductVariant, PurchaseInvoice, PurchaseInvoiceLine, Service, StockMovement, Supplier


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    search_fields = ("name",)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "is_active")
    search_fields = ("name", "phone")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "category", "color", "size", "cost_usd", "price_usd", "stock_qty", "is_active")
    list_filter = ("category", "unit", "color", "is_active", "track_stock")
    search_fields = ("name", "alias", "sku", "barcode", "size")
    readonly_fields = ("stock_qty",)


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("product", "color", "size", "stock_qty")
    list_filter = ("color",)
    search_fields = ("product__name", "product__sku", "size")
    readonly_fields = ("stock_qty",)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "service_type", "price_usd", "price_lyd_override", "is_active")
    list_filter = ("service_type", "is_active")
    search_fields = ("name",)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("product", "variant", "movement_type", "quantity", "reference", "purchase_invoice", "created_at")
    list_filter = ("movement_type",)
    search_fields = ("product__name", "reference", "purchase_invoice__number")


class PurchaseInvoiceLineInline(admin.TabularInline):
    model = PurchaseInvoiceLine
    extra = 0


@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "display_supplier", "invoice_date", "status", "total_usd", "total_lyd")
    list_filter = ("status", "invoice_date")
    search_fields = ("number", "supplier_name", "supplier__name")
    readonly_fields = ("number", "total_usd", "total_lyd", "posted_at")
    inlines = [PurchaseInvoiceLineInline]
