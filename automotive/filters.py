import django_filters
from django.db.models import Q

from .models import (
    VehicleEngine,
    VehicleGeneration,
    VehicleMake,
    VehicleModel,
    VehicleTrim,
)


class VehicleMakeFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}],
        "advanced_fields": [["is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = VehicleMake
        fields = ["keyword", "is_active"]

    def filter_keyword(self, queryset, name, value):
        return queryset.filter(name__icontains=value) if value else queryset


class VehicleModelFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}, "make"],
        "advanced_fields": [["is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = VehicleModel
        fields = ["keyword", "make", "is_active"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(name__icontains=value) | Q(make__name__icontains=value))


class VehicleGenerationFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}, "vehicle_model"],
        "advanced_fields": [["is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = VehicleGeneration
        fields = ["keyword", "vehicle_model", "is_active"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value)
            | Q(chassis_code__icontains=value)
            | Q(vehicle_model__name__icontains=value)
            | Q(vehicle_model__make__name__icontains=value)
        )


class VehicleEngineFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}, "vehicle_model"],
        "advanced_fields": [["fuel_type", "is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = VehicleEngine
        fields = ["keyword", "vehicle_model", "fuel_type", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .settings import get_automotive_config

        if not get_automotive_config()["criteria"]["fuel_type"]:
            self.filters.pop("fuel_type", None)

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(display_name__icontains=value)
            | Q(engine_code__icontains=value)
            | Q(vehicle_model__name__icontains=value)
            | Q(vehicle_model__make__name__icontains=value)
        )


class VehicleTrimFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")

    advanced_config = {
        "fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}, "vehicle_model"],
        "advanced_fields": [["is_active"]],
        "clear_preserve_keys": ["sort", "page"],
    }

    class Meta:
        model = VehicleTrim
        fields = ["keyword", "vehicle_model", "is_active"]

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value)
            | Q(vehicle_model__name__icontains=value)
            | Q(vehicle_model__make__name__icontains=value)
        )
