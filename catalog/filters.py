import django_filters
from django.db.models import Q

from .models import Category, Product, PurchaseInvoice, Service, StockMovement, StockTake, Supplier


class CategoryFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}],
        "advanced_fields": [["is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = Category
        fields = ["keyword", "is_active"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(name__icontains=value) | Q(description__icontains=value))


class SupplierFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}],
        "advanced_fields": [["is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = Supplier
        fields = ["keyword", "is_active"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(phone__icontains=value) | Q(address__icontains=value)
        )


class ProductFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [
            {"name": "keyword", "placeholder_key": "search_placeholder"},
            "category",
        ],
        "advanced_fields": [["unit", "color"], ["is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = Product
        fields = ["keyword", "category", "unit", "color", "is_active"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        query = (
            Q(name__icontains=value) | Q(sku__icontains=value) | Q(barcode__icontains=value)
            | Q(size__icontains=value)
        )
        from automotive.settings import get_automotive_config

        automotive = get_automotive_config()
        if automotive["enabled"]:
            criteria = automotive["criteria"]
            query |= (
                Q(automotive_fitments__vehicle_model__make__name__icontains=value)
                | Q(automotive_fitments__vehicle_model__name__icontains=value)
            )
            if criteria["generation_chassis"]:
                query |= (
                    Q(automotive_fitments__generation__name__icontains=value)
                    | Q(automotive_fitments__generation__chassis_code__icontains=value)
                )
            if criteria["engine"]:
                query |= (
                    Q(automotive_fitments__engine__display_name__icontains=value)
                    | Q(automotive_fitments__engine__engine_code__icontains=value)
                )
            if criteria["fuel_type"]:
                query |= Q(automotive_fitments__engine__fuel_type__icontains=value)
            if criteria["trim"]:
                query |= Q(automotive_fitments__trim__name__icontains=value)
        return queryset.filter(query).distinct()


class ServiceFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [
            {"name": "keyword", "placeholder_key": "search_placeholder"},
            "service_type",
        ],
        "advanced_fields": [["is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = Service
        fields = ["keyword", "service_type", "is_active"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(name__icontains=value) | Q(description__icontains=value))


class StockMovementFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [
            {"name": "keyword", "placeholder_key": "search_placeholder"},
            "product",
        ],
        "advanced_fields": [["movement_type"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = StockMovement
        fields = ["keyword", "product", "movement_type"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(reference__icontains=value) | Q(reason__icontains=value))


class PurchaseInvoiceFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [
            {"name": "keyword", "placeholder_key": "search_placeholder"},
            "status",
        ],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = PurchaseInvoice
        fields = ["keyword", "status"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(number__icontains=value)
            | Q(supplier_name__icontains=value)
            | Q(supplier__name__icontains=value)
            | Q(notes__icontains=value)
        )


class StockTakeFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [
            {"name": "keyword", "placeholder_key": "search_placeholder"},
            "status",
        ],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = StockTake
        fields = ["keyword", "status"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(number__icontains=value) | Q(notes__icontains=value))
