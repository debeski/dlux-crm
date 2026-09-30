import json

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.urls import reverse

from dlux.utils import set_field_attrs
from dlux.widgets import DluxMultipleChoiceSelectorWidget

from common.forms import build_grid_helper, translate_choice_fields, translate_help_text
from common.i18n import t
from common.views import scope_filtered_queryset

from .models import (
    EquipmentType,
    ProductFitment,
    VehicleEngine,
    VehicleGeneration,
    VehicleMake,
    VehicleModel,
    VehicleTrim,
)
from .settings import get_automotive_config


def _selected_id(form, field_name):
    if form.is_bound:
        value = form.data.get(form.add_prefix(field_name))
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    value = getattr(form.instance, f"{field_name}_id", None)
    if value:
        return value
    initial = form.initial.get(field_name)
    return getattr(initial, "pk", initial)


def _for_user(queryset, user):
    return scope_filtered_queryset(queryset, user) if user is not None else queryset


class AutomotiveModelForm(forms.ModelForm):
    refresh_parent = True

    def __init__(self, *args, request=None, user=None, **kwargs):
        self.request = request
        self.user = user or getattr(request, "user", None)
        super().__init__(*args, **kwargs)

    def finish(self, layout):
        set_field_attrs(self)
        translate_choice_fields(self, self.request)
        translate_help_text(self, self.request)
        build_grid_helper(self, layout)


class EquipmentTypeForm(AutomotiveModelForm):
    class Meta:
        model = EquipmentType
        fields = ["name", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.finish([("name", "is_active")])


class VehicleMakeForm(AutomotiveModelForm):
    class Meta:
        model = VehicleMake
        fields = ["name", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.finish([("name", "is_active")])


class VehicleModelForm(AutomotiveModelForm):
    class Meta:
        model = VehicleModel
        fields = ["make", "equipment_type", "name", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["make"].queryset = _for_user(
            VehicleMake.objects.filter(is_active=True), self.user,
        ).order_by("name")
        if get_automotive_config()["criteria"].get("equipment_type"):
            self.fields["equipment_type"].queryset = _for_user(
                EquipmentType.objects.filter(is_active=True), self.user,
            ).order_by("name")
        else:
            self.fields.pop("equipment_type")
        self.finish([("make", "equipment_type"), ("name", "is_active")])


class VehicleGenerationForm(AutomotiveModelForm):
    class Meta:
        model = VehicleGeneration
        fields = ["vehicle_model", "name", "chassis_code", "year_from", "year_to", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle_model"].queryset = _for_user(
            VehicleModel.objects.filter(is_active=True, make__is_active=True), self.user,
        ).select_related("make").order_by("make__name", "name")
        self.finish([
            ("vehicle_model", "name"),
            ("chassis_code", "is_active"),
            ("year_from", "year_to"),
        ])


class VehicleEngineForm(AutomotiveModelForm):
    class Meta:
        model = VehicleEngine
        fields = [
            "vehicle_model", "generation", "manufacturer", "display_name", "engine_code",
            "displacement", "fuel_type", "fitted_models", "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        criteria = get_automotive_config()["criteria"]
        model_id = _selected_id(self, "vehicle_model")
        live_models = _for_user(
            VehicleModel.objects.filter(is_active=True, make__is_active=True), self.user,
        ).select_related("make").order_by("make__name", "name")
        self.fields["vehicle_model"].queryset = live_models
        self.fields["vehicle_model"].help_text = t(
            "help_engine_vehicle_model",
            "Leave blank for a shared engine used by several machines, then list them below.",
        )
        self.fields["fitted_models"].queryset = live_models
        self.fields["fitted_models"].widget = DluxMultipleChoiceSelectorWidget(
            variant="searchable-list", searchable=True,
            search_placeholder=t("ui_search_models", "Search models"),
        )
        self.fields["fitted_models"].widget.choices = self.fields["fitted_models"].choices
        generations = _for_user(VehicleGeneration.objects.filter(is_active=True), self.user).select_related(
            "vehicle_model", "vehicle_model__make",
        )
        if model_id:
            generations = generations.filter(vehicle_model_id=model_id)
        else:
            generations = generations.none()
        self.fields["generation"].queryset = generations
        self.fields["vehicle_model"].widget.attrs["data-automotive-parent"] = "vehicle-model"
        self.fields["generation"].widget.attrs["data-automotive-child"] = "generation"
        if not criteria["generation_chassis"]:
            self.fields.pop("generation")
        if not criteria["fuel_type"]:
            self.fields.pop("fuel_type")
        first_row = ("vehicle_model", "generation") if criteria["generation_chassis"] else ("vehicle_model",)
        spec_row = ("displacement", "fuel_type") if criteria["fuel_type"] else ("displacement",)
        self.finish([
            first_row, ("manufacturer", "display_name"), ("engine_code",), spec_row,
            ("fitted_models",), ("is_active",),
        ])

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("vehicle_model"):
            cleaned_data["fitted_models"] = VehicleModel.objects.none()
        return cleaned_data


class VehicleTrimForm(AutomotiveModelForm):
    class Meta:
        model = VehicleTrim
        fields = ["vehicle_model", "generation", "name", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        criteria = get_automotive_config()["criteria"]
        model_id = _selected_id(self, "vehicle_model")
        self.fields["vehicle_model"].queryset = _for_user(
            VehicleModel.objects.filter(is_active=True, make__is_active=True), self.user,
        ).select_related("make").order_by("make__name", "name")
        generations = _for_user(VehicleGeneration.objects.filter(is_active=True), self.user).select_related(
            "vehicle_model", "vehicle_model__make",
        )
        self.fields["generation"].queryset = (
            generations.filter(vehicle_model_id=model_id) if model_id else generations.none()
        )
        self.fields["vehicle_model"].widget.attrs["data-automotive-parent"] = "vehicle-model"
        self.fields["generation"].widget.attrs["data-automotive-child"] = "generation"
        if not criteria["generation_chassis"]:
            self.fields.pop("generation")
        vehicle_row = ("vehicle_model", "generation") if criteria["generation_chassis"] else ("vehicle_model",)
        self.finish([vehicle_row, ("name", "is_active")])


class ProductFitmentForm(AutomotiveModelForm):
    class Meta:
        model = ProductFitment
        fields = [
            "vehicle_model", "year_from", "year_to", "generation", "engine",
            "trim", "transmission", "position", "notes",
        ]

    def __init__(self, *args, criteria=None, **kwargs):
        self.criteria = criteria or {}
        super().__init__(*args, **kwargs)
        model_id = _selected_id(self, "vehicle_model")
        generation_id = _selected_id(self, "generation")
        models = _for_user(
            VehicleModel.objects.filter(is_active=True, make__is_active=True), self.user,
        ).select_related("make")
        self.fields["vehicle_model"].queryset = models.order_by("make__name", "name")

        generations = _for_user(
            VehicleGeneration.objects.filter(is_active=True), self.user,
        ).select_related("vehicle_model")
        engines = _for_user(
            VehicleEngine.objects.filter(is_active=True), self.user,
        ).select_related("vehicle_model", "generation")
        shared_engines = engines.filter(vehicle_model__isnull=True)
        trims = _for_user(
            VehicleTrim.objects.filter(is_active=True), self.user,
        ).select_related("vehicle_model", "generation")
        if model_id:
            generations = generations.filter(vehicle_model_id=model_id)
            own = engines.filter(vehicle_model_id=model_id)
            trims = trims.filter(vehicle_model_id=model_id)
            if generation_id:
                own = own.filter(Q(generation_id=generation_id) | Q(generation__isnull=True))
                trims = trims.filter(Q(generation_id=generation_id) | Q(generation__isnull=True))
            else:
                own = own.filter(generation__isnull=True)
                trims = trims.filter(generation__isnull=True)
            engines = engines.filter(
                Q(pk__in=own.values("pk")) | Q(pk__in=shared_engines.filter(fitted_models=model_id).values("pk"))
            )
        else:
            generations = generations.none()
            engines = shared_engines
            trims = trims.none()
        self.fields["generation"].queryset = generations
        self.fields["engine"].queryset = engines
        self.fields["trim"].queryset = trims

        if not self.criteria.get("model_year", True):
            self.fields.pop("year_from", None)
            self.fields.pop("year_to", None)
        criterion_fields = {
            "generation_chassis": "generation",
            "engine": "engine",
            "trim": "trim",
            "transmission": "transmission",
            "position": "position",
        }
        for criterion, field_name in criterion_fields.items():
            if not self.criteria.get(criterion, False):
                self.fields.pop(field_name, None)

        for field_name in ("vehicle_model", "generation", "engine", "trim"):
            if field_name in self.fields:
                self.fields[field_name].widget.attrs[f"data-fitment-{field_name.replace('_', '-')}"] = "1"
        self.finish([])


def _spans_overlap(left, right):
    """Blank years mean all years, so they overlap any range."""
    if left.get("year_from") is None or right.get("year_from") is None:
        return True
    return max(left["year_from"], right["year_from"]) <= min(left["year_to"], right["year_to"])


class BaseProductFitmentFormSet(BaseInlineFormSet):
    def __init__(self, *args, criteria=None, confirm_overlaps=False, request=None, user=None, **kwargs):
        self.criteria = criteria or {}
        self.confirm_overlaps = confirm_overlaps
        self.request = request
        self.user = user
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs.update({"criteria": self.criteria, "request": self.request, "user": self.user})
        return kwargs

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active = [
            form.cleaned_data
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        overlaps = False
        for index, left in enumerate(active):
            for right in active[index + 1:]:
                if left.get("vehicle_model") != right.get("vehicle_model"):
                    continue
                identity_fields = ("generation", "engine", "trim", "transmission", "position")
                if any(left.get(field) != right.get(field) for field in identity_fields):
                    continue
                same_years = (
                    left.get("year_from") == right.get("year_from")
                    and left.get("year_to") == right.get("year_to")
                )
                if same_years:
                    raise ValidationError(t(
                        "fitment_duplicate_error",
                        "The same vehicle compatibility row is entered more than once.",
                    ))
                if _spans_overlap(left, right):
                    overlaps = True
        if overlaps and not self.confirm_overlaps:
            raise ValidationError(t(
                "fitment_overlap_error",
                "Some matching compatibility rows overlap. Consolidate their years or confirm the overlap and save again.",
            ))


class FitsPickerWidget(forms.Widget):
    """Search-and-chip vehicle picker posting its chips as one JSON value."""

    template_name = "automotive/widgets/fits_picker.html"

    def __init__(self, attrs=None, *, editor_url="", allow_copy=True, suggest_name=False):
        super().__init__(attrs)
        self.editor_url = editor_url
        self.allow_copy = allow_copy
        self.suggest_name = suggest_name

    def format_value(self, value):
        if value in (None, ""):
            return "[]"
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"].update({
            "search_url": reverse("automotive:vehicle_search"),
            "copy_url": reverse("automotive:fits_source"),
            "editor_url": self.editor_url,
            "allow_copy": self.allow_copy,
            "suggest_name": self.suggest_name,
            "strings": {
                "placeholder": t("fits_search_placeholder", "Type a vehicle: camry 2014, xv50, hilux 2.8…"),
                "empty": t("fits_no_vehicles", "No vehicles yet — search above to add one."),
                "no_results": t("fits_no_results", "No matching vehicle."),
                "remove": t("ui_remove", "Remove"),
                "copy": t("fits_copy_from", "Same cars as…"),
                "copy_placeholder": t("fits_copy_placeholder", "Search a product that already has vehicles"),
                "copy_empty": t("fits_copy_empty", "No product with vehicles matches."),
                "added": t("fits_added", "Added"),
                "advanced": t("fits_advanced", "Advanced: engine, position, notes"),
                "vehicles": t("ui_fits_vehicles", "Fits vehicles"),
            },
        })
        return context


class FitsField(forms.CharField):
    widget = FitsPickerWidget

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("strip", False)
        super().__init__(*args, **kwargs)


class BulkFitmentForm(forms.Form):
    """Same vehicles for many products; existing rows are never removed."""

    products = forms.ModelMultipleChoiceField(queryset=None)
    fits = FitsField()

    def __init__(self, *args, request=None, user=None, **kwargs):
        self.request = request
        self.user = user
        super().__init__(*args, **kwargs)
        from catalog.models import Product

        self.fit_rows = []
        self.fields["products"].queryset = _for_user(
            Product.objects.filter(is_active=True), user,
        ).order_by("name")
        self.fields["products"].label = t("fits_bulk_products", "Products")
        self.fields["products"].help_text = t(
            "fits_bulk_products_help", "Choose every product that fits the same vehicles.",
        )
        self.fields["products"].widget = DluxMultipleChoiceSelectorWidget(
            variant="searchable-list",
            searchable=True,
            search_placeholder=t("fits_bulk_products_search", "Search products"),
        )
        self.fields["products"].widget.choices = self.fields["products"].choices
        self.fields["fits"].label = t("ui_fits_vehicles", "Fits vehicles")
        self.fields["fits"].widget = FitsPickerWidget()
        set_field_attrs(self)
        build_grid_helper(self, [("products",), ("fits",)])

    def clean(self):
        cleaned_data = super().clean()
        from .fits import parse_chips

        try:
            _kept, self.fit_rows = parse_chips(
                cleaned_data.get("fits"), user=self.user,
                criteria=get_automotive_config()["criteria"],
            )
        except ValidationError as error:
            self.add_error("fits", error)
            return cleaned_data
        if not self.fit_rows:
            self.add_error("fits", t("fits_bulk_need_vehicle", "Add at least one vehicle."))
        return cleaned_data


ProductFitmentFormSet = inlineformset_factory(
    parent_model=ProductFitment._meta.get_field("product").remote_field.model,
    model=ProductFitment,
    form=ProductFitmentForm,
    formset=BaseProductFitmentFormSet,
    fields=ProductFitmentForm.Meta.fields,
    extra=1,
    can_delete=True,
)
