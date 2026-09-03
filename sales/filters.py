import django_filters
from django.db.models import Q

from common.filters import DatedFilterSet

from .models import Customer, Delivery, Invoice, Payment


class InvoiceFilter(DatedFilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    #: The date a user means when they say "when" for an invoice.
    date_field = "invoice_date"

    # Ribbon layout: keyword + status + the year jump in the ribbon's own row,
    # the date range inside the advanced panel. Read by
    # `ScopedListView.ribbon_primary`. The range fields are named for the
    # `_gte`/`_lte` suffix convention `set_field_attrs` labels From/To from.
    advanced_config = {
        "fields": [
            {"name": "keyword", "placeholder_key": "search_placeholder"},
            "status",
            "year",
        ],
        "advanced_fields": [["date_gte", "date_lte"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = Invoice
        fields = ["keyword", "status"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(number__icontains=value)
            | Q(customer_name__icontains=value)
            | Q(customer__name__icontains=value)
            | Q(customer_phone__icontains=value)
        )


class CustomerFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}],
        "advanced_fields": [["is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = Customer
        fields = ["keyword", "is_active"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(name__icontains=value) | Q(phone__icontains=value))


class PaymentFilter(DatedFilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    #: A DateTimeField, so `_lookup` adds the `__date` transform — without it a
    #: payment taken at 14:00 falls outside `date_lte` set to that same day.
    date_field = "paid_at"

    advanced_config = {
        "fields": [
            {"name": "keyword", "placeholder_key": "search_placeholder"}, "year",
        ],
        "advanced_fields": [["method"], ["date_gte", "date_lte"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = Payment
        fields = ["keyword", "method"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(receipt_number__icontains=value)
            | Q(invoice__number__icontains=value)
            | Q(notes__icontains=value)
        )


class DeliveryFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [
            {"name": "keyword", "placeholder_key": "search_placeholder"},
            "status",
        ],
        "advanced_fields": [["scheduled_date"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = Delivery
        fields = ["keyword", "status", "scheduled_date"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(recipient__icontains=value)
            | Q(address__icontains=value)
            | Q(phone__icontains=value)
            | Q(invoice__number__icontains=value)
        )
