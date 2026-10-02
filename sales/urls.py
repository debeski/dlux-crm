from django.urls import path
from django.views.generic import RedirectView

from .pos_settings import pos_enabled
from .pos_views import CheckoutView, LookupView, ReceiptView, TillView, VehicleProductsView
from .payment_resolution_views import InvoiceCancellationView, CustomerCreditUseView
from .views import (
    CustomerListView,
    DashboardView,
    DeliveryListView,
    FinancialReportView,
    InvoiceCancelView,
    InvoiceCreateView,
    InvoiceDetailView,
    InvoiceIssueView,
    InvoiceListView,
    InvoicePrintView,
    InvoiceUpdateView,
    PaymentCreateView,
    PaymentListView,
    PaymentReceiptView,
    SalesReportExportView,
    SalesReportView,
)

app_name = "sales"

# The XLSX download is a file response, not a page — hide it from the dlux
# auto-discovered sidebar (see discovery._is_candidate -> sidebar_exclude).
_report_export = SalesReportExportView.as_view()
_report_export.sidebar_exclude = True

# Bare /sales/ redirects to the sales overview (the app home). The invoice list lives
# at /sales/invoices/ so its sidebar URL doesn't prefix-match every other sales
# page (which made "Invoices" highlight on the overview, customers, etc.).
_sales_home = RedirectView.as_view(pattern_name="sales:dashboard", permanent=False)
_sales_home.sidebar_exclude = True

class _PosSidebarExclusion:
    def __bool__(self):
        return not pos_enabled()


_till = TillView.as_view()
_till.sidebar_group = "workspace"
_till.sidebar_icon = "bi-upc-scan"
_till.sidebar_permissions = ["sales.use_pos"]
_till.sidebar_exclude = _PosSidebarExclusion()
_pos_hidden = {}
for _name, _view in (
    ("lookup", LookupView), ("checkout", CheckoutView), ("receipt", ReceiptView), ("vehicle", VehicleProductsView),
):
    _pos_hidden[_name] = _view.as_view()
    _pos_hidden[_name].sidebar_exclude = True

urlpatterns = [
    path("pos/", _till, name="pos_till"),
    path("pos/lookup/", _pos_hidden["lookup"], name="pos_lookup"),
    path("pos/checkout/", _pos_hidden["checkout"], name="pos_checkout"),
    path("pos/receipt/<int:pk>/", _pos_hidden["receipt"], name="pos_receipt"),
    path("pos/vehicle/", _pos_hidden["vehicle"], name="pos_vehicle"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("", _sales_home, name="sales_home"),
    path("invoices/", InvoiceListView.as_view(), name="invoice_list"),
    path("new/", InvoiceCreateView.as_view(), name="invoice_create"),
    path("<int:pk>/", InvoiceDetailView.as_view(), name="invoice_detail"),
    path("<int:pk>/edit/", InvoiceUpdateView.as_view(), name="invoice_edit"),
    path("<int:pk>/issue/", InvoiceIssueView.as_view(), name="invoice_issue"),
    path("<int:pk>/cancel/", InvoiceCancellationView.as_view(), name="invoice_cancel"),
    path("<int:pk>/print/", InvoicePrintView.as_view(), name="invoice_print"),
    path("<int:pk>/credit/", CustomerCreditUseView.as_view(), name="credit_apply"),
    path("<int:pk>/pay/", PaymentCreateView.as_view(), name="payment_add"),
    path("customers/", CustomerListView.as_view(), name="customer_list"),
    path("deliveries/", DeliveryListView.as_view(), name="delivery_list"),
    path("payments/<int:pk>/receipt/", PaymentReceiptView.as_view(), name="payment_receipt"),
    path("payments/", PaymentListView.as_view(), name="payment_list"),
    path("report/", SalesReportView.as_view(), name="report"),
    path("report/export/", _report_export, name="report_export"),
    path("financial/", FinancialReportView.as_view(), name="financial_report"),
]
