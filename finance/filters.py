import django_filters
from django.db.models import Q

from common.filters import DatedFilterSet

from .models import CashDeposit, ExchangeRate, Expense, ExpenseCategory, StaffAccount, StaffLedgerEntry


class ExchangeRateFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}],
        "advanced_fields": [["source"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = ExchangeRate
        fields = ["keyword", "source"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(note__icontains=value) | Q(source__icontains=value))


class CashDepositFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [
            {"name": "keyword", "placeholder_key": "search_placeholder"},
            "method",
        ],
        "advanced_fields": [["status"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = CashDeposit
        fields = ["keyword", "method", "status"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(reference__icontains=value) | Q(notes__icontains=value))


class ExpenseCategoryFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}],
        "advanced_fields": [["is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = ExpenseCategory
        fields = ["keyword", "is_active"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(name__icontains=value) | Q(description__icontains=value))


class ExpenseFilter(DatedFilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    #: The date a user means when they say "when" for an expense.
    date_field = "expense_date"

    advanced_config = {
        "fields": [
            {"name": "keyword", "placeholder_key": "search_placeholder"},
            "category", "year",
        ],
        "advanced_fields": [["method", "status"], ["paid_by"], ["date_gte", "date_lte"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = Expense
        fields = ["keyword", "category", "method", "status", "paid_by"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(reference__icontains=value)
            | Q(notes__icontains=value)
            | Q(category__name__icontains=value)
        )


class StaffAccountFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}],
        "advanced_fields": [["is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = StaffAccount
        fields = ["keyword", "is_active"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(user__username__icontains=value)
            | Q(user__first_name__icontains=value)
            | Q(user__last_name__icontains=value)
            | Q(notes__icontains=value)
        )


class StaffLedgerEntryFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}, "account"],
        "advanced_fields": [["entry_type", "status"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = StaffLedgerEntry
        fields = ["keyword", "account", "entry_type", "status"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(reference__icontains=value)
            | Q(notes__icontains=value)
            | Q(account__user__username__icontains=value)
            | Q(account__user__first_name__icontains=value)
            | Q(account__user__last_name__icontains=value)
        )
