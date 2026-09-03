import django_tables2 as tables
from dlux.tables import DluxTable
from django.urls import reverse

from common.i18n import t
from common.tables import ModalRowActionsMixin

from .models import CashDeposit, ExchangeRate, Expense, ExpenseCategory, StaffAccount, StaffLedgerEntry


class ExchangeRateTable(ModalRowActionsMixin, DluxTable):
    class Meta(DluxTable.Meta):
        model = ExchangeRate
        fields = ("rate", "source", "note", "created_by", "created_at")
        dlux_actions = True

    def render_source(self, record):
        return t(f"source_{record.source}", record.get_source_display())


class CashDepositTable(ModalRowActionsMixin, DluxTable):
    class Meta(DluxTable.Meta):
        model = CashDeposit
        fields = ("amount", "method", "deposited_at", "status", "created_by", "created_at")
        dlux_actions = True

    def render_method(self, record):
        return t(f"method_{record.method}", record.get_method_display())

    def render_status(self, record):
        return t(f"status_{record.status}", record.get_status_display())


class ExpenseCategoryTable(ModalRowActionsMixin, DluxTable):
    class Meta(DluxTable.Meta):
        model = ExpenseCategory
        fields = ("name", "is_active", "created_at")
        dlux_actions = True


class ExpenseTable(ModalRowActionsMixin, DluxTable):
    class Meta(DluxTable.Meta):
        model = Expense
        fields = ("category", "amount_lyd", "expense_date", "method", "status", "paid_by", "created_at")
        dlux_actions = True

    def render_method(self, record):
        return t(f"method_{record.method}", record.get_method_display())

    def render_status(self, record):
        return t(f"status_{record.status}", record.get_status_display())


class StaffAccountTable(DluxTable):
    balance = tables.Column(empty_values=(), verbose_name="Balance (LYD)", orderable=False)
    pending = tables.Column(empty_values=(), verbose_name="Pending", orderable=False)

    class Meta(DluxTable.Meta):
        model = StaffAccount
        fields = ("user", "balance", "pending", "is_active", "created_at")
        dlux_actions = True

    def get_dlux_base_actions(self, record):
        return [
            {
                "label": "ui_view",
                "icon": "bi bi-eye",
                "type": "url",
                "url": reverse("finance:staff_account_detail", args=[record.pk]),
                "dblclick": True,
                "permissions": ["finance.view_staffaccount"],
            },
        ]

    def render_balance(self, record):
        return f"{record.balance_lyd:,.2f}"

    def render_pending(self, record):
        return record.pending_count


class StaffLedgerEntryTable(ModalRowActionsMixin, DluxTable):
    class Meta(DluxTable.Meta):
        model = StaffLedgerEntry
        fields = ("account", "entry_type", "amount_lyd", "signed_amount", "entry_date", "status", "created_by", "created_at")
        dlux_actions = True

    def render_entry_type(self, record):
        return t(f"staff_entry_type_{record.entry_type}", record.get_entry_type_display())

    def render_status(self, record):
        return t(f"staff_entry_status_{record.status}", record.get_status_display())

    def render_signed_amount(self, record):
        return f"{record.signed_amount:,.2f}"
