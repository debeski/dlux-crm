import django_filters
from django.db.models import Q
from .models import MachineType, Manufacturer, MachineModel


class ReferenceFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="")
    advanced_config = {"fields": [{"name": "keyword", "placeholder_key": "search_placeholder"}], "advanced_fields": [["is_active"]]}

    def filter_keyword(self, queryset, name, value):
        condition = Q(name__icontains=value)
        if self._meta.model is MachineModel:
            condition |= Q(alias__icontains=value) | Q(manufacturer__name__icontains=value)
        return queryset.filter(condition)


class MachineTypeFilter(ReferenceFilter):
    class Meta:
        model = MachineType
        fields = ["keyword", "is_active"]


class ManufacturerFilter(ReferenceFilter):
    class Meta:
        model = Manufacturer
        fields = ["keyword", "is_active"]


class MachineModelFilter(ReferenceFilter):
    class Meta:
        model = MachineModel
        fields = ["keyword", "is_active"]
