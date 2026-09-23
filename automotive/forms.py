from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory

from dlux.utils import set_field_attrs

from common.forms import build_grid_helper, translate_choice_fields, translate_help_text
from common.i18n import t
from common.views import scope_filtered_queryset

from .models import (
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
        fields = ["make", "name", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["make"].queryset = _for_user(
            VehicleMake.objects.filter(is_active=True), self.user,
        ).order_by("name")
        self.finish([("make", "name"), ("is_active",)])


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
            "vehicle_model", "generation", "display_name", "engine_code",
            "displacement", "fuel_type", "is_active",
        ]

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
        self.finish([first_row, ("display_name", "engine_code"), spec_row, ("is_active",)])


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
        trims = _for_user(
            VehicleTrim.objects.filter(is_active=True), self.user,
        ).select_related("vehicle_model", "generation")
        if model_id:
            generations = generations.filter(vehicle_model_id=model_id)
            engines = engines.filter(vehicle_model_id=model_id)
            trims = trims.filter(vehicle_model_id=model_id)
            if generation_id:
                engines = engines.filter(Q(generation_id=generation_id) | Q(generation__isnull=True))
                trims = trims.filter(Q(generation_id=generation_id) | Q(generation__isnull=True))
            else:
                engines = engines.filter(generation__isnull=True)
                trims = trims.filter(generation__isnull=True)
        else:
            generations = generations.none()
            engines = engines.none()
            trims = trims.none()
        self.fields["generation"].queryset = generations
        self.fields["engine"].queryset = engines
        self.fields["trim"].queryset = trims

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
                if max(left.get("year_from"), right.get("year_from")) <= min(
                    left.get("year_to"), right.get("year_to")
                ):
                    overlaps = True
        if overlaps and not self.confirm_overlaps:
            raise ValidationError(t(
                "fitment_overlap_error",
                "Some matching compatibility rows overlap. Consolidate their years or confirm the overlap and save again.",
            ))


ProductFitmentFormSet = inlineformset_factory(
    parent_model=ProductFitment._meta.get_field("product").remote_field.model,
    model=ProductFitment,
    form=ProductFitmentForm,
    formset=BaseProductFitmentFormSet,
    fields=ProductFitmentForm.Meta.fields,
    extra=1,
    can_delete=True,
)
