from django import forms
from django.db import OperationalError, ProgrammingError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, HTML, Layout, Row
from dlux.forms import build_settings_toggle_field

from common.i18n import lazy_t, t

from .settings import AUTOMOTIVE_CRITERIA, normalize_optional_enhancements


CRITERION_FIELDS = {
    "generation_chassis": "criterion_generation_chassis",
    "engine": "criterion_engine",
    "fuel_type": "criterion_fuel_type",
    "trim": "criterion_trim",
    "transmission": "criterion_transmission",
    "position": "criterion_position",
}


class OptionalEnhancementsSettingsForm(forms.Form):
    automotive_enabled = forms.BooleanField(
        required=False,
        label=lazy_t("optional_automotive_enabled", "Automotive compatibility"),
        help_text=lazy_t(
            "optional_automotive_enabled_help",
            "Adds vehicle compatibility screens and queries without changing Product or stock records.",
        ),
    )
    criterion_generation_chassis = forms.BooleanField(
        required=False,
        label=lazy_t("optional_criterion_generation", "Chassis / generation"),
        help_text=lazy_t("optional_criterion_generation_help", "Distinguish platform and chassis generations."),
    )
    criterion_engine = forms.BooleanField(
        required=False,
        label=lazy_t("optional_criterion_engine", "Engine"),
        help_text=lazy_t("optional_criterion_engine_help", "Use engine code and displacement when matching parts."),
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
    criterion_transmission = forms.BooleanField(
        required=False,
        label=lazy_t("optional_criterion_transmission", "Transmission"),
        help_text=lazy_t("optional_criterion_transmission_help", "Distinguish automatic, manual, CVT, and DCT."),
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
        initial.setdefault("automotive_enabled", automotive["enabled"])
        for criterion, field_name in CRITERION_FIELDS.items():
            initial.setdefault(field_name, automotive["criteria"][criterion])
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_tag = False
        criterion_toggles = [
            build_settings_toggle_field(self, field_name, css_class="col-12 col-lg-6")
            for field_name in CRITERION_FIELDS.values()
        ]
        if automotive["enabled"]:
            manage_vehicle_data = (
                "<a class='btn btn-sm btn-outline-primary rounded-pill' "
                "href='/staff/automotive/' data-automotive-manage data-persisted-enabled='true'>"
                f"<i class='bi bi-sliders me-1'></i>{t('ui_manage_vehicle_data', 'Manage vehicle data')}"
                "</a>"
            )
        else:
            manage_vehicle_data = (
                "<span class='btn btn-sm btn-outline-primary rounded-pill disabled' role='link' "
                "aria-disabled='true' data-automotive-manage data-persisted-enabled='false'>"
                f"<i class='bi bi-sliders me-1'></i>{t('ui_manage_vehicle_data', 'Manage vehicle data')}"
                "</span>"
            )
        self.helper.layout = Layout(
            Div(
                Row(
                    build_settings_toggle_field(self, "automotive_enabled", css_class="col-12"),
                    css_class="g-3",
                ),
                Div(
                    HTML(
                        f"<h6 class='fw-semibold mb-1'>{t('optional_automotive_criteria', 'Vehicle criteria')}</h6>"
                        f"<p class='small text-muted mb-3'>{t('optional_automotive_criteria_help', 'Make, model, and year are always available. Choose the extra criteria this store uses.')}</p>"
                    ),
                    Row(*criterion_toggles, css_class="g-3"),
                    HTML(
                        "<div class='border rounded bg-light p-3 mt-3' data-automotive-workflow-preview "
                        f"data-core-label='{t('optional_preview_core', 'Make → Model → Year')}' "
                        f"data-end-label='{t('optional_preview_end', 'Category → Products')}'>"
                        f"<div class='small text-muted mb-1'>{t('optional_preview_title', 'Staff browsing path')}</div>"
                        "<div class='fw-semibold' data-automotive-workflow-output></div>"
                        "</div>"
                    ),
                    HTML(
                        "<div class='mt-3'>"
                        f"{manage_vehicle_data}"
                        "<div class='small text-muted mt-2' data-automotive-manage-hint hidden>"
                        f"{t('ui_save_vehicle_settings_first', 'Save these settings before managing vehicle data.')}"
                        "</div></div>"
                    ),
                    css_id="automotive-criteria-fields",
                    css_class="mt-3",
                ),
                css_id="optional-enhancements-form",
            )
        )

    def _criterion_usage_count(self, criterion):
        from django.db.models import Q

        from .models import ProductFitment

        filters = {
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
        if cleaned.get("criterion_fuel_type"):
            cleaned["criterion_engine"] = True
        if not cleaned.get("automotive_enabled"):
            return cleaned

        current_criteria = self.current_config["automotive"]["criteria"]
        for criterion in AUTOMOTIVE_CRITERIA:
            field_name = CRITERION_FIELDS[criterion]
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
        if criteria["fuel_type"]:
            criteria["engine"] = True
        return {
            "automotive": {
                "enabled": bool(self.cleaned_data.get("automotive_enabled")),
                "criteria": criteria,
            },
        }
