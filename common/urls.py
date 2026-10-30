from django.urls import path

from .views import StoredFileView, WorkspaceDashboardView

app_name = "common"

_workspace_dashboard = WorkspaceDashboardView.as_view()
_workspace_dashboard.sidebar_group = "workspace"
_workspace_dashboard.sidebar_icon = "bi-grid-1x2"
_workspace_dashboard.sidebar_permissions = [
    "sales.add_invoice",
    "sales.view_invoice",
    "sales.view_customer",
    "sales.view_delivery",
    "sales.view_payment",
    "sales.view_sales_report",
    "sales.view_financial_report",
    "catalog.add_purchaseinvoice",
    "catalog.add_stocktake",
    "catalog.view_product",
    "catalog.view_purchaseinvoice",
    "catalog.view_supplier",
    "catalog.view_inventory_valuation",
    "catalog.view_stockmovement",
    "catalog.view_stocktake",
    "finance.add_exchangerate",
    "finance.view_exchangerate",
    "finance.view_cashdeposit",
    "finance.view_expense",
    "finance.view_staffaccount",
    "finance.view_staffledgerentry",
]

urlpatterns = [
    path("workspace/", _workspace_dashboard, name="workspace_dashboard"),
    path(
        "files/<str:app_label>/<str:model_name>/<int:pk>/<str:field_name>/",
        StoredFileView.as_view(),
        name="stored_file",
    ),
]
