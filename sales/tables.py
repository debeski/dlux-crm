import django_tables2 as tables
from django.urls import reverse
from django.utils.html import format_html

from dlux.tables import DluxTable

from common.i18n import t
from common.tables import ModalRowActionsMixin

from .models import Customer, Delivery, Invoice, Payment

_STATUS_BADGE = {
    "draft": "bg-secondary",
    "issued": "bg-info text-dark",
    "partial": "bg-warning text-dark",
    "paid": "bg-success",
    "cancelled": "bg-danger",
}

_DELIVERY_BADGE = {
    "pending": "bg-secondary",
    "assigned": "bg-info text-dark",
    "out": "bg-warning text-dark",
    "delivered": "bg-success",
    "failed": "bg-danger",
    "cancelled": "bg-dark",
}


def _user_label(user):
    if user is None:
        return "—"
    return (user.get_full_name() or user.get_username()) if hasattr(user, "get_username") else str(user)


class InvoiceTable(DluxTable):
    number = tables.Column(verbose_name="Invoice No.")
    customer = tables.Column(empty_values=(), verbose_name="Customer", orderable=False)
    salesperson = tables.Column(verbose_name="Salesperson")
    status = tables.Column(verbose_name="Status")
    total_lyd = tables.Column(verbose_name="Total (LYD)")
    balance = tables.Column(empty_values=(), verbose_name="Balance (LYD)", orderable=False)

    class Meta(DluxTable.Meta):
        model = Invoice
        fields = ("number", "customer", "salesperson", "invoice_date", "status", "total_lyd", "balance")
        dlux_actions = True

    def render_salesperson(self, record):
        return _user_label(record.salesperson)

    def render_number(self, record):
        return record.number or "—"

    def get_dlux_base_actions(self, record):
        actions = [
            {
                "label": "ui_view_invoice",
                "icon": "bi bi-eye",
                "type": "url",
                "url": reverse("sales:invoice_detail", args=[record.pk]),
                "dblclick": True,
                "permissions": ["sales.view_invoice"],
            },
            {
                "label": "ui_print_export",
                "icon": "bi bi-printer",
                "type": "url",
                "url": reverse("sales:invoice_print", args=[record.pk]),
                "target": "_blank",
                "permissions": ["sales.view_invoice"],
            },
        ]
        if record.is_editable:
            actions.extend(
                [
                    {"type": "divider"},
                    {
                        "label": "ui_edit_invoice",
                        "icon": "bi bi-pencil",
                        "type": "url",
                        "url": reverse("sales:invoice_edit", args=[record.pk]),
                        "permissions": ["sales.change_invoice"],
                    },
                    {
                        "label": "ui_issue",
                        "icon": "bi bi-check2-circle",
                        "type": "form",
                        "url": reverse("sales:invoice_issue", args=[record.pk]),
                        "permissions": ["sales.issue_invoice"],
                    },
                ]
            )
        if record.status != Invoice.STATUS_CANCELLED:
            if not record.is_editable:
                actions.append({"type": "divider"})
            actions.append(
                {
                    "label": "ui_cancel",
                    "icon": "bi bi-x-circle",
                    "type": "form",
                    "url": reverse("sales:invoice_cancel", args=[record.pk]),
                    "confirm": t("ui_cancel_confirm", "Cancel this invoice? Stock will be restored."),
                    "textClass": "text-danger",
                    "permissions": ["sales.cancel_invoice"],
                }
            )
        return actions

    def render_customer(self, record):
        return record.display_customer

    def render_status(self, record):
        return format_html(
            '<span class="badge rounded-pill {}">{}</span>',
            _STATUS_BADGE.get(record.status, "bg-secondary"),
            t(f"status_{record.status}", record.get_status_display()),
        )

    def render_total_lyd(self, record):
        return f"{record.total_lyd:,.2f}"

    def render_balance(self, record):
        bal = record.balance_due
        css = "text-danger fw-semibold" if bal > 0 else "text-success"
        return format_html('<span class="{}">{}</span>', css, f"{bal:,.2f}")


class CustomerTable(ModalRowActionsMixin, DluxTable):
    class Meta(DluxTable.Meta):
        model = Customer
        fields = ("name", "phone", "address", "is_active", "created_at")
        dlux_actions = True


class PaymentTable(DluxTable):
    receipt_number = tables.Column(verbose_name="Receipt No.")
    invoice = tables.Column(verbose_name="Invoice")
    amount = tables.Column(verbose_name="Amount (LYD)")

    class Meta(DluxTable.Meta):
        model = Payment
        fields = ("receipt_number", "invoice", "amount", "method", "paid_at", "created_by")
        dlux_actions = True

    def render_receipt_number(self, record):
        return record.receipt_number or "—"

    def render_invoice(self, record):
        return record.invoice.number

    def render_amount(self, record):
        return f"{record.amount:,.2f}"

    def render_method(self, record):
        return t(f"method_{record.method}", record.get_method_display())

    def get_dlux_base_actions(self, record):
        return [
            {
                "label": "ui_view_invoice",
                "icon": "bi bi-receipt",
                "type": "url",
                "url": reverse("sales:invoice_detail", args=[record.invoice_id]),
                "dblclick": True,
                "permissions": ["sales.view_invoice"],
            },
            {
                "label": "ui_print_receipt",
                "icon": "bi bi-printer",
                "type": "url",
                "url": reverse("sales:payment_receipt", args=[record.pk]),
                "target": "_blank",
                "dblclick": True,
                "permissions": ["sales.view_payment"],
            },
        ]


class DeliveryTable(ModalRowActionsMixin, DluxTable):
    recipient = tables.Column(verbose_name="Recipient")
    status = tables.Column(verbose_name="Status")
    assigned_to = tables.Column(verbose_name="Assigned To")

    class Meta(DluxTable.Meta):
        model = Delivery
        fields = ("recipient", "address", "status", "assigned_to", "scheduled_date", "created_at")
        dlux_actions = True

    def render_status(self, record):
        return format_html(
            '<span class="badge rounded-pill {}">{}</span>',
            _DELIVERY_BADGE.get(record.status, "bg-secondary"),
            t(f"delivery_status_{record.status}", record.get_status_display()),
        )

    def render_assigned_to(self, record):
        return _user_label(record.assigned_to)
