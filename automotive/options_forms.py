from django import forms
from django.db import OperationalError, ProgrammingError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, HTML, Layout, Row
from dlux.forms import build_settings_toggle_field

from common.i18n import lazy_t, t
from common.settings_forms import dependent_block, lock_dependents

from .settings import (
    REQUIRED_AUTOMOTIVE_CRITERIA,
    TERMINOLOGY_EQUIPMENT,
    TERMINOLOGY_VEHICLE,
    normalize_optional_enhancements,
)


CRITERION_FIELDS = {
    "equipment_type": "criterion_equipment_type",
    "generation_chassis": "criterion_generation_chassis",
    "fuel_type": "criterion_fuel_type",
    "trim": "criterion_trim",
    "position": "criterion_position",
}


class OptionalEnhancementsSettingsForm(forms.Form):
    machinery_enabled = forms.BooleanField(required=False, label=lazy_t("optional_machinery_enabled", "Machinery compatibility"), help_text=lazy_t("machine_flow", "Machine type → Manufacturer → Model → Category → Parts or services"))
    automotive_enabled = forms.BooleanField(
        required=False,
        label=lazy_t("optional_automotive_enabled", "Automotive compatibility"),
        help_text=lazy_t(
            "optional_automotive_enabled_help",
            "Adds vehicle compatibility screens and queries without changing Product or stock records.",
        ),
    )
    terminology = forms.ChoiceField(
        required=False,
        choices=(
            (TERMINOLOGY_VEHICLE, lazy_t("optional_terminology_vehicle", "Vehicles (cars, trucks)")),
            (TERMINOLOGY_EQUIPMENT, lazy_t("optional_terminology_equipment", "Machines & equipment")),
        ),
        label=lazy_t("optional_terminology", "What the store serves"),
        help_text=lazy_t(
            "optional_terminology_help",
            "Changes the wording across the compatibility screens; data stays the same.",
        ),
    )
    criterion_equipment_type = forms.BooleanField(
        required=False,
        label=lazy_t("optional_criterion_equipment_type", "Machine type"),
        help_text=lazy_t(
            "optional_criterion_equipment_type_help",
            "Group models by type, such as excavator, loader, or generator.",
        ),
    )

    criterion_generation_chassis = forms.BooleanField(
        required=False,
        label=lazy_t("optional_criterion_generation", "Chassis / generation"),
        help_text=lazy_t("optional_criterion_generation_help", "Distinguish platform and chassis generations."),
    )

    criterion_fuel_type = forms.BooleanField(
        required=False,
        label=lazy_t("optional_criterion_fuel", "Fuel type"),
        help_text=lazy_t("optional_criterion_fuel_help", "Show gasoline, diesel, hybrid, electric, LPG, or other fuel."),
    )
    criterion_trim = forms.BooleanField(
        required=False,
        label=lazy_t("optional_criterion_trim", "Trim"),
        help_text=lazy_t("optional_criterion_trim_help", "Use trim level when compatibility differs."),
    )

    criterion_position = forms.BooleanField(
        required=False,
        label=lazy_t("optional_criterion_position", "Part position"),
        help_text=lazy_t("optional_criterion_position_help", "Use front, rear, left, and right positions."),
    )

    def __init__(self, *args, current_value=None, **kwargs):
        kwargs.pop("request", None)
        kwargs.pop("namespace", None)
        kwargs.pop("settings_definition", None)
        self.current_config = normalize_optional_enhancements(current_value)
        automotive = self.current_config["automotive"]
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("machinery_enabled", self.current_config["machinery"]["enabled"])
        initial.setdefault("automotive_enabled", automotive["enabled"])
        initial.setdefault("terminology", automotive["terminology"])
        for criterion, field_name in CRITERION_FIELDS.items():
            initial.setdefault(field_name, automotive["criteria"][criterion])
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.fields["terminology"].widget = forms.HiddenInput()
        self.fields["terminology"].disabled = True
        self.initial["terminology"] = TERMINOLOGY_VEHICLE
        lock_dependents(self, "automotive_enabled", list(CRITERION_FIELDS.values()))

        self.helper = FormHelper()
        self.helper.form_tag = False
        criterion_toggles = [
            build_settings_toggle_field(self, field_name, css_class="col-12 col-lg-6")
            for field_name in CRITERION_FIELDS.values()
        ]
        from django.urls import reverse
        from django.utils.html import format_html

        def manage_action(pack, enabled, label, hint):
            tag = "a" if enabled else "span"
            destination = format_html("href='{}'", reverse(f"{pack}:hub")) if enabled else "role='link'"
            return format_html(
                "<div class='mt-3'><{tag} class='btn btn-sm btn-outline-primary rounded-pill{disabled}' {destination} "
                "aria-disabled='{aria}' data-{pack}-manage data-persisted-enabled='{persisted}'>"
                "<i class='bi bi-sliders me-1'></i>{label}</{tag}>"
                "<div class='small text-muted mt-2' data-{pack}-manage-hint hidden>{hint}</div></div>",
                tag=tag, disabled="" if enabled else " disabled", destination=destination,
                aria="false" if enabled else "true", pack=pack, persisted="true" if enabled else "false",
                label=label, hint=hint,
            )

        manage_vehicle_data = manage_action("automotive", automotive["enabled"], t("ui_manage_vehicle_data", "Manage vehicle data"), t("ui_save_vehicle_settings_first", "Save these settings before managing vehicle data."))
        manage_machinery = manage_action("machinery", self.current_config["machinery"]["enabled"], t("machine_manage", "Manage machinery"), t("machine_save_settings_first", "Save these settings before managing machinery."))
        self.helper.layout = Layout(
            Div(
                Row(
                    build_settings_toggle_field(self, "machinery_enabled", css_class="col-12"),
                    dependent_block(
                        self, "machinery_enabled",
                        Div(
                            HTML(manage_machinery),
                            css_id="machinery-criteria-fields",
                        ),
                        css_class="col-12 mb-3",
                    ),
                    build_settings_toggle_field(self, "automotive_enabled", css_class="col-12"),
                    css_class="g-3",
                ),
                dependent_block(
                    self, "automotive_enabled",
                    Row(Div("terminology", css_class="col-12 col-lg-6"), css_class="g-3 mt-1"),
                    Div(
                        HTML(
                            f"<h6 class='fw-semibold mb-1'>{t('optional_automotive_criteria', 'Vehicle criteria')}</h6>"
                            f"<p class='small text-muted mb-3'>{t('optional_automotive_criteria_help', 'Make, model, year, engine and transmission are always available. Choose the optional criteria this store uses.')}</p>"
                        ),
                        Row(*criterion_toggles, css_class="g-3"),
                        HTML(manage_vehicle_data),
                        css_id="automotive-criteria-fields",
                        css_class="mt-3",
                    ),
                ),
                css_id="optional-enhancements-form",
            )
        )

    def _criterion_usage_count(self, criterion):
        from django.db.models import Q

        from .models import ProductFitment

        filters = {
            "equipment_type": Q(pk__in=[]),
            "model_year": Q(year_from__isnull=False),
            "generation_chassis": Q(generation__isnull=False),
            "engine": Q(engine__isnull=False),
            "fuel_type": Q(engine__fuel_type__gt=""),
            "trim": Q(trim__isnull=False),
            "transmission": ~Q(transmission=""),
            "position": ~Q(position=""),
        }
        try:
            return ProductFitment.objects.filter(filters[criterion]).count()
        except (OperationalError, ProgrammingError):
            return 0

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("automotive_enabled"):
            return cleaned

        current_criteria = self.current_config["automotive"]["criteria"]
        for criterion, field_name in CRITERION_FIELDS.items():
            if current_criteria[criterion] and not cleaned.get(field_name):
                count = self._criterion_usage_count(criterion)
                if count:
                    self.add_error(
                        field_name,
                        t(
                            "optional_criterion_in_use",
                            "Cannot disable this criterion while {count} fitment(s) use it. Normalize those values first.",
                        ).format(count=count),
                    )
        return cleaned

    def to_app_config(self, current_value=None):
        criteria = {
            criterion: bool(self.cleaned_data.get(field_name))
            for criterion, field_name in CRITERION_FIELDS.items()
        }
        criteria.update({criterion: True for criterion in REQUIRED_AUTOMOTIVE_CRITERIA})
        terminology = TERMINOLOGY_VEHICLE
        # The wording follows on save of the settings row (terminology.sync_terminology).
        return {
            "machinery": {"enabled": bool(self.cleaned_data.get("machinery_enabled"))},
            "automotive": {
                "enabled": bool(self.cleaned_data.get("automotive_enabled")),
                "terminology": terminology,
                "criteria": criteria,
            },
        }
