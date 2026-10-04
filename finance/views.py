from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import DetailView

from dlux.utils import log_user_action

from common.access import apply_ownership
from common.views import ScopedListView

from .filters import (
    CashDepositFilter, ExchangeRateFilter, ExpenseCategoryFilter, ExpenseFilter,
    StaffAccountFilter, StaffLedgerEntryFilter,
)
from .models import (
    CashDeposit, ExchangeRate, Expense, ExpenseCategory, StaffAccount, StaffLedgerEntry,
)
from .tables import (
    CashDepositTable, ExchangeRateTable, ExpenseCategoryTable, ExpenseTable,
    StaffAccountTable, StaffLedgerEntryTable,
)


class ExchangeRateListView(ScopedListView):
    model = ExchangeRate
    permission_required = "finance.view_exchangerate"
    table_class = ExchangeRateTable
    filterset_class = ExchangeRateFilter
    template_name = "finance/exchange_rate_list.html"

    def get_context_data(self, **kwargs):
        from .services import rate_overview

        context = super().get_context_data(**kwargs)
        context["rate_overview"] = rate_overview()
        return context

    page_title_key = "page_exchange_rates"
    page_subtitle_key = "page_exchange_rates_sub"


class CashDepositListView(ScopedListView):
    model = CashDeposit
    permission_required = "finance.view_cashdeposit"
    table_class = CashDepositTable
    filterset_class = CashDepositFilter
    page_title_key = "page_cash_deposits"
    page_subtitle_key = "page_cash_deposits_sub"


class CashDepositReviewView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Confirm or reject a pending cash deposit (privileged action)."""

    permission_required = "finance.confirm_cashdeposit"
    raise_exception = True

    def post(self, request, pk, decision):
        deposit = get_object_or_404(CashDeposit, pk=pk)
        if decision == "confirm":
            deposit.confirm(request.user)
            log_user_action(request, "CONFIRM", instance=deposit)
            messages.success(request, _("Cash deposit confirmed."))
        elif decision == "reject":
            deposit.reject(request.user)
            log_user_action(request, "REJECT", instance=deposit)
            messages.warning(request, _("Cash deposit rejected."))
        return redirect("finance:cash_deposit_list")


class ExpenseCategoryListView(ScopedListView):
    model = ExpenseCategory
    permission_required = "finance.view_expensecategory"
    table_class = ExpenseCategoryTable
    filterset_class = ExpenseCategoryFilter
    page_title_key = "page_expense_categories"
    page_subtitle_key = "page_expense_categories_sub"


class ExpenseListView(ScopedListView):
    model = Expense
    permission_required = "finance.view_expense"
    table_class = ExpenseTable
    filterset_class = ExpenseFilter
    page_title_key = "page_expenses"
    page_subtitle_key = "page_expenses_sub"


class ExpenseReviewView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "finance.post_expense"
    raise_exception = True

    def post(self, request, pk, decision):
        expense = get_object_or_404(apply_ownership(Expense.objects.all(), request.user), pk=pk)
        if decision == "post":
            expense.post(request.user)
            log_user_action(request, "POST", instance=expense)
            messages.success(request, _("Expense posted."))
        elif decision == "void":
            expense.void(request.user)
            log_user_action(request, "VOID", instance=expense)
            messages.warning(request, _("Expense voided."))
        return redirect("finance:expense_list")


class StaffAccountListView(ScopedListView):
    model = StaffAccount
    permission_required = "finance.view_staffaccount"
    table_class = StaffAccountTable
    filterset_class = StaffAccountFilter
    page_title_key = "page_staff_accounts"
    page_subtitle_key = "page_staff_accounts_sub"


class StaffAccountDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = StaffAccount
    permission_required = "finance.view_staffaccount"
    raise_exception = True
    template_name = "finance/staff_account_detail.html"
    context_object_name = "account"

    def get_queryset(self):
        qs = StaffAccount.objects.select_related("user")
        return apply_ownership(qs, self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["entries"] = self.object.entries.select_related("created_by", "confirmed_by", "disputed_by").all()[:100]
        ctx["balance"] = self.object.balance_lyd
        return ctx


class StaffLedgerEntryListView(ScopedListView):
    model = StaffLedgerEntry
    permission_required = "finance.view_staffledgerentry"
    table_class = StaffLedgerEntryTable
    filterset_class = StaffLedgerEntryFilter
    page_title_key = "page_staff_ledger_entries"
    page_subtitle_key = "page_staff_ledger_entries_sub"


class StaffLedgerEntryActionView(LoginRequiredMixin, View):
    raise_exception = True

    def _entry(self, request, pk):
        qs = StaffLedgerEntry.objects.select_related("account", "account__user")
        entry = get_object_or_404(qs, pk=pk)
        is_owner = entry.account.user_id == request.user.pk
        can_resolve = request.user.has_perm("finance.resolve_staffledgerentry")
        if not (is_owner or can_resolve):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        return entry, is_owner, can_resolve

    def post(self, request, pk, action):
        entry, is_owner, can_resolve = self._entry(request, pk)
        if action == "confirm" and (is_owner or can_resolve):
            if entry.status == StaffLedgerEntry.STATUS_PENDING_USER:
                entry.confirm(request.user)
                log_user_action(request, "CONFIRM", instance=entry)
                messages.success(request, _("Staff account entry confirmed."))
        elif action == "dispute" and (is_owner or can_resolve):
            if entry.status == StaffLedgerEntry.STATUS_PENDING_USER:
                entry.dispute(request.user)
                log_user_action(request, "DISPUTE", instance=entry)
                messages.warning(request, _("Staff account entry disputed."))
        elif action == "void" and can_resolve:
            entry.void(request.user)
            log_user_action(request, "VOID", instance=entry)
            messages.warning(request, _("Staff account entry voided."))
        return redirect("finance:staff_account_detail", pk=entry.account_id)
