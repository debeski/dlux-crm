from decimal import Decimal

from django import forms

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Layout, Row
from dlux.forms import build_settings_toggle_field
from dlux.widgets import DluxChoiceSelectorWidget

from common.i18n import lazy_t, t

from .currency import (
    CURRENCY_EUR,
    CURRENCY_USD,
    PRICING_CURRENCIES,
    conversion_factor,
    normalize_pricing_config,
    priced_catalog_counts,
)
from .services import get_current_rate, has_configured_rate

CURRENCY_ICONS = {CURRENCY_USD: "bi-currency-dollar", CURRENCY_EUR: "bi-currency-euro"}


class PricingSettingsForm(forms.Form):
    currency = forms.ChoiceField(
        choices=(
            (CURRENCY_USD, lazy_t("currency_usd", "US Dollar (USD)")),
            (CURRENCY_EUR, lazy_t("currency_eur", "Euro (EUR)")),
            ("BOTH", lazy_t("currency_both", "Both (USD / EUR)")),
        ),
        label=lazy_t("pricing_currency", "Pricing currency"),
        help_text=lazy_t(
            "pricing_currency_help",
            "Default for new products and invoices. Products retain their own currencies.",
        ),
    )
    convert_prices = forms.BooleanField(
        required=False,
        label=lazy_t("pricing_convert_confirm", "Convert service prices and draft sales invoices when switching"),
    )

    def __init__(self, *args, current_value=None, **kwargs):
        kwargs.pop("request", None)
        kwargs.pop("namespace", None)
        kwargs.pop("settings_definition", None)
        self.current = normalize_pricing_config(current_value)["currency"]
        initial = dict(kwargs.pop("initial", {}) or {})
        initial["currency"] = "BOTH" if normalize_pricing_config(current_value)["both_active"] else self.current
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.counts = priced_catalog_counts()
        self.fields["currency"].widget = DluxChoiceSelectorWidget(
            variant="toggle", option_meta={code: {"icon": icon} for code, icon in CURRENCY_ICONS.items()},
        )
        self.fields["currency"].widget.choices = self.fields["currency"].choices
        self.fields["convert_prices"].help_text = self._preview()

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(Div("currency", css_class="col-12"), css_class="g-3"),
            Row(build_settings_toggle_field(self, "convert_prices", css_class="col-12"), css_class="g-3 mt-1"),
        )

    def _other(self):
        return next(code for code in PRICING_CURRENCIES if code != self.current)

    def _preview(self):
        other = self._other()
        if not (has_configured_rate(self.current) and has_configured_rate(other)):
            return t(
                "pricing_convert_needs_rates",
                "Set both a USD and a EUR exchange rate before switching, so prices can be converted.",
            )
        factor = conversion_factor(self.current, other).quantize(Decimal("0.0001"))
        return t(
            "pricing_convert_preview",
            "Switching keeps product currencies and converts {services} services: 1 {current} = {factor} {other} "
            "at your rates (1 {current} = {current_rate} LYD, 1 {other} = {other_rate} LYD). "
            "Selling prices in LYD stay the same.",
        ).format(
            products=self.counts["products"], services=self.counts["services"], current=self.current,
            other=other, factor=factor, current_rate=get_current_rate(self.current),
            other_rate=get_current_rate(other),
        )

    def clean(self):
        cleaned = super().clean()
        new = cleaned.get("currency")
        if not new or new == "BOTH" or new == self.current:
            return cleaned
        if not (has_configured_rate(self.current) and has_configured_rate(new)):
            self.add_error("currency", t(
                "pricing_convert_needs_rates",
                "Set both a USD and a EUR exchange rate before switching, so prices can be converted.",
            ))
        elif (self.counts["products"] or self.counts["services"]) and not cleaned.get("convert_prices"):
            self.add_error("convert_prices", t(
                "pricing_convert_required",
                "Tick this to confirm converting the catalog prices to the new currency.",
            ))
        return cleaned

    def to_app_config(self, current_value=None):
        # Conversion happens on save of the settings row (currency.convert_on_switch).
        selected = self.cleaned_data["currency"]
        return {"currency": self.current if selected == "BOTH" else selected, "both_active": selected == "BOTH"}
