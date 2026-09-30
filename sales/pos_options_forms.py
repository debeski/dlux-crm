from decimal import Decimal

from django import forms

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Layout, Row
from dlux.forms import build_settings_toggle_field

from common.i18n import lazy_t
from common.settings_forms import dependent_block, lock_dependents

from .pos_settings import POS_METHODS, normalize_pos_config

METHOD_FIELDS = {method: f"method_{method}" for method in POS_METHODS}


class PointOfSaleSettingsForm(forms.Form):
    pos_enabled = forms.BooleanField(
        required=False,
        label=lazy_t("pos_settings_enabled", "Point of sale"),
        help_text=lazy_t(
            "pos_settings_enabled_help",
            "A full-screen till for quick walk-in sales with barcode scanning. Off by default.",
        ),
    )
    method_cash = forms.BooleanField(required=False, label=lazy_t("method_cash", "Cash"))
    method_card = forms.BooleanField(required=False, label=lazy_t("method_card", "Card"))
    method_bank_transfer = forms.BooleanField(required=False, label=lazy_t("method_bank_transfer", "Bank Transfer"))
    max_discount_percent = forms.DecimalField(
        min_value=Decimal("0"), max_value=Decimal("100"), decimal_places=2,
        label=lazy_t("pos_settings_max_discount", "Seller discount limit (%)"),
        help_text=lazy_t(
            "pos_settings_max_discount_help",
            "The most a seller may take off a sale. Managers with the unlimited-discount permission are not limited.",
        ),
    )
    receipt_size = forms.ChoiceField(
        choices=(
            ("none", lazy_t("pos_receipt_none", "No receipt")),
            ("58", lazy_t("pos_receipt_58", "Thermal 58 mm")),
            ("80", lazy_t("pos_receipt_80", "Thermal 80 mm")),
            ("a4", lazy_t("pos_receipt_a4", "A4 page")),
        ),
        label=lazy_t("pos_settings_receipt", "Receipt"),
    )
    def __init__(self, *args, current_value=None, **kwargs):
        kwargs.pop("request", None)
        kwargs.pop("namespace", None)
        kwargs.pop("settings_definition", None)
        config = normalize_pos_config(current_value)
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("pos_enabled", config["enabled"])
        initial.setdefault("max_discount_percent", config["max_discount_percent"])
        initial.setdefault("receipt_size", config["receipt_size"])
        for method, field_name in METHOD_FIELDS.items():
            initial.setdefault(field_name, config["methods"][method])
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        lock_dependents(self, "pos_enabled", [*METHOD_FIELDS.values(), "max_discount_percent", "receipt_size"])

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(build_settings_toggle_field(self, "pos_enabled", css_class="col-12"), css_class="g-3"),
            dependent_block(
                self, "pos_enabled",
                Row(
                    *[build_settings_toggle_field(self, name, css_class="col-12 col-lg-4") for name in METHOD_FIELDS.values()],
                    css_class="g-3 mt-1",
                ),
                Row(
                    Div("max_discount_percent", css_class="col-12 col-lg-6"),
                    Div("receipt_size", css_class="col-12 col-lg-6"),
                    css_class="g-3 mt-1",
                ),
            ),
        )

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(name) for name in METHOD_FIELDS.values()):
            cleaned["method_cash"] = True
        return cleaned

    def to_app_config(self, current_value=None):
        data = self.cleaned_data
        return normalize_pos_config({
            "enabled": bool(data.get("pos_enabled")),
            "methods": {method: bool(data.get(name)) for method, name in METHOD_FIELDS.items()},
            "max_discount_percent": str(data.get("max_discount_percent") or "0"),
            "receipt_size": data.get("receipt_size") or "80",
        })
