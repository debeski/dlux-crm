"""Automotive fields grafted onto the catalog Product modal form.

Product stays generic: the part brand, part numbers and vehicle chips are
saved into automotive tables after the Product row itself is saved.
"""
from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse

from common.i18n import t

from .fits import (
    apply_chips,
    chip_label,
    dump_chips,
    parse_chips,
    part_identity_initial,
    product_chips,
    save_part_identity,
    split_part_numbers,
)
from .forms import FitsField, FitsPickerWidget
from .models import VehicleGeneration, VehicleModel
from .settings import get_automotive_config

FITMENT_PERMS = (
    "automotive.view_productfitment",
    "automotive.add_productfitment",
    "automotive.change_productfitment",
    "automotive.delete_productfitment",
)
FITS_FIELD = "automotive_fits"
PART_FIELDS = ("part_brand", "oem_numbers", "cross_references")


def _integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def prefill_chip(params, user):
    """One chip from `fit_model` / `fit_generation` / `fit_year` query params."""
    from common.views import scope_filtered_queryset

    model_id = _integer(params.get("fit_model"))
    if not model_id:
        return None
    vehicle_model = scope_filtered_queryset(
        VehicleModel.objects.filter(is_active=True).select_related("make"), user,
    ).filter(pk=model_id).first()
    if vehicle_model is None:
        return None
    generation = None
    generation_id = _integer(params.get("fit_generation"))
    if generation_id:
        generation = scope_filtered_queryset(
            VehicleGeneration.objects.filter(is_active=True, vehicle_model=vehicle_model), user,
        ).filter(pk=generation_id).first()
    year = _integer(params.get("fit_year"))
    if generation is not None:
        span = (generation.year_from, generation.year_to)
    elif year:
        span = (year, year)
    else:
        return None
    return {
        "vehicle_model": vehicle_model.pk,
        "generation": generation.pk if generation else None,
        "year_from": span[0],
        "year_to": span[1],
        "label": chip_label(vehicle_model, *span, generation),
    }


def line_fits_enabled(user):
    return bool(get_automotive_config()["enabled"] and user and user.has_perms(FITMENT_PERMS))


def attach_line_fits(form, user):
    """Give an intake grid row a collapsed Fits picker; rows are additive."""
    if not line_fits_enabled(user):
        return False
    form.fields["fits"] = FitsField(
        label=t("ui_fits_vehicles", "Fits vehicles"),
        widget=FitsPickerWidget(),
    )
    return True


def clean_line_fits(form, cleaned_data, user):
    try:
        _kept, cleaned_data["fit_rows"] = parse_chips(
            cleaned_data.get("fits"), user=user, criteria=get_automotive_config()["criteria"],
        )
    except ValidationError as error:
        form.add_error("fits", error)


class AutomotiveProductExtension:
    """Adds part identity and quick vehicle chips to a Product form."""

    def __init__(self, form, request, config):
        self.form = form
        self.user = getattr(request, "user", None)
        self.config = config
        self.criteria = config["criteria"]
        self.can_fit = bool(self.user and self.user.has_perms(FITMENT_PERMS))
        self._kept, self._rows = set(), []

        instance = form.instance if form.instance.pk else None
        initial = part_identity_initial(instance)
        form.fields["part_brand"] = forms.CharField(
            required=False, max_length=120, label=t("label_part_brand", "Part brand"),
            initial=initial["part_brand"],
        )
        form.fields["oem_numbers"] = forms.CharField(
            required=False, label=t("label_oem_numbers", "OEM numbers"),
            initial=initial["oem_numbers"],
            help_text=t("help_part_numbers", "Separate several numbers with commas."),
        )
        form.fields["cross_references"] = forms.CharField(
            required=False, label=t("label_cross_references", "Cross-reference numbers"),
            initial=initial["cross_references"],
            help_text=t("help_part_numbers", "Separate several numbers with commas."),
        )
        if self.can_fit:
            editor_url = reverse("automotive:product_fitments", args=[instance.pk]) if instance else ""
            if instance:
                chips = product_chips(instance, self.criteria)
            else:
                chip = prefill_chip(getattr(request, "GET", {}), self.user)
                chips = [chip] if chip else []
            form.fields[FITS_FIELD] = FitsField(
                label=t("ui_fits_vehicles", "Fits vehicles"),
                initial=dump_chips(chips),
                widget=FitsPickerWidget(editor_url=editor_url, suggest_name=instance is None),
            )

    @classmethod
    def attach(cls, form, request):
        config = get_automotive_config()
        if not config["enabled"]:
            return None
        return cls(form, request, config)

    def layout(self, rows):
        """Parts-first order: fits right after name/category, then identity."""
        extra = [(FITS_FIELD,)] if self.can_fit else []
        extra += [("part_brand", "oem_numbers"), ("cross_references",)]
        anchor = next((i for i, row in enumerate(rows) if "category" in row), 0)
        return rows[:anchor + 1] + extra + rows[anchor + 1:]

    def clean(self, cleaned_data):
        for field in ("oem_numbers", "cross_references"):
            try:
                cleaned_data[field] = split_part_numbers(cleaned_data.get(field))
            except ValidationError as error:
                self.form.add_error(field, error)
        if not self.can_fit:
            return
        instance = self.form.instance
        existing = (
            set(instance.automotive_fitments.values_list("pk", flat=True)) if instance.pk else set()
        )
        try:
            self._kept, self._rows = parse_chips(
                cleaned_data.get(FITS_FIELD), user=self.user, criteria=self.criteria,
                existing_ids=existing,
            )
        except ValidationError as error:
            self.form.add_error(FITS_FIELD, error)

    def save(self, product):
        data = self.form.cleaned_data
        save_part_identity(
            product,
            brand=(data.get("part_brand") or "").strip(),
            oem_numbers=data.get("oem_numbers") or [],
            cross_references=data.get("cross_references") or [],
        )
        if self.can_fit:
            apply_chips(product, self._kept, self._rows, replace=True)
