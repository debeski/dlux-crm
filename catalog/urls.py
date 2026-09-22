from django.urls import path

from .views import (
    CategoryListView,
    InventoryValuationView,
    OpeningStockDetailView,
    OpeningStockEditorView,  # one-time bulk intake (posts Stock In movements)
    OpeningStockImportFinalizeView,
    OpeningStockImportPreviewView,
    ProductCardView,
    ProductListView,
    PurchaseInvoiceCreateView,
    PurchaseInvoiceDetailView,
    PurchaseInvoiceListView,
    PurchaseInvoicePrintView,
    ServiceListView,
    StockMovementListView,
    StockTakeApplyView,
    StockTakeCreateView,
    StockTakeDetailView,
    StockTakeListView,
    SupplierListView,
)

app_name = "catalog"

# The count-create and per-take routes shouldn't appear as their own sidebar
# entries (only the Stock Takes list should).
_stock_take_create = StockTakeCreateView.as_view()
_stock_take_create.sidebar_exclude = True
_stock_take_detail = StockTakeDetailView.as_view()
_stock_take_detail.sidebar_exclude = True
_stock_take_apply = StockTakeApplyView.as_view()
_stock_take_apply.sidebar_exclude = True

# One-time opening-stock intake: a single editor reached via a trigger on the
# Stock Movements page (not a sidebar entry of its own).
_opening_stock = OpeningStockEditorView.as_view()
_opening_stock.sidebar_exclude = True
_opening_stock_detail = OpeningStockDetailView.as_view()
_opening_stock_detail.sidebar_exclude = True
_opening_stock_import_preview = OpeningStockImportPreviewView.as_view()
_opening_stock_import_preview.sidebar_exclude = True
_opening_stock_import_finalize = OpeningStockImportFinalizeView.as_view()
_opening_stock_import_finalize.sidebar_exclude = True

_purchase_invoice_create = PurchaseInvoiceCreateView.as_view()
_purchase_invoice_create.sidebar_exclude = True
_purchase_invoice_detail = PurchaseInvoiceDetailView.as_view()
_purchase_invoice_detail.sidebar_exclude = True
_purchase_invoice_print = PurchaseInvoicePrintView.as_view()
_purchase_invoice_print.sidebar_exclude = True

_product_card = ProductCardView.as_view()
_product_card.sidebar_exclude = True

urlpatterns = [
    path("", ProductListView.as_view(), name="product_list"),
    path("products/<int:pk>/card/", _product_card, name="product_card"),
    path("categories/", CategoryListView.as_view(), name="category_list"),
    path("suppliers/", SupplierListView.as_view(), name="supplier_list"),
    path("services/", ServiceListView.as_view(), name="service_list"),
    path("purchase-invoices/", PurchaseInvoiceListView.as_view(), name="purchase_invoice_list"),
    path("purchase-invoices/new/", _purchase_invoice_create, name="purchase_invoice_create"),
    path("purchase-invoices/<int:pk>/", _purchase_invoice_detail, name="purchase_invoice_detail"),
    path("purchase-invoices/<int:pk>/print/", _purchase_invoice_print, name="purchase_invoice_print"),
    path("stock-movements/", StockMovementListView.as_view(), name="stock_movement_list"),
    path("stock-movements/opening-stock/", _opening_stock, name="opening_stock"),
    path(
        "stock-movements/opening-stock/import/preview/",
        _opening_stock_import_preview,
        name="opening_stock_import_preview",
    ),
    path(
        "stock-movements/opening-stock/import/finalize/",
        _opening_stock_import_finalize,
        name="opening_stock_import_finalize",
    ),
    path("stock-movements/opening-stock/view/", _opening_stock_detail, name="opening_stock_detail"),
    path("stock-takes/", StockTakeListView.as_view(), name="stock_take_list"),
    path("stock-takes/new/", _stock_take_create, name="stock_take_create"),
    path("stock-takes/<int:pk>/", _stock_take_detail, name="stock_take_detail"),
    path("stock-takes/<int:pk>/apply/", _stock_take_apply, name="stock_take_apply"),
    path("valuation/", InventoryValuationView.as_view(), name="inventory_valuation"),
]
