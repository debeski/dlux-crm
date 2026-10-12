from django import forms

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Layout, Row
from dlux.forms import build_settings_toggle_field

from common.i18n import lazy_t
from common.settings_forms import dependent_block, lock_dependents

from .settings import PUBLIC_CATALOG_DEFAULTS

TEXT_FIELDS = ("shop_title", "shop_subtitle", "contact_phone", "contact_whatsapp", "contact_email")
TOGGLE_FIELDS = ("show_price", "show_availability")


class PublicCatalogSettingsForm(forms.Form):
    public_enabled = forms.BooleanField(
        required=False,
        label=lazy_t("public_catalog_enabled", "Public site"),
        help_text=lazy_t(
            "public_catalog_enabled_help",
            "The public homepage and shop, and their builders. Turn off for a staff-only "
            "install: the site address then opens the staff sign-in.",
        ),
    )
    shop_title = forms.CharField(required=False, label=lazy_t("public_catalog_shop_title", "Shop title"))
    shop_subtitle = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}),
        label=lazy_t("public_catalog_shop_subtitle", "Shop subtitle"),
    )
    contact_phone = forms.CharField(required=False, label=lazy_t("public_catalog_contact_phone", "Contact phone"))
    contact_whatsapp = forms.CharField(required=False, label=lazy_t("public_catalog_contact_whatsapp", "WhatsApp number"))
    contact_email = forms.CharField(required=False, label=lazy_t("public_catalog_contact_email", "Contact email"))
    show_price = forms.BooleanField(required=False, label=lazy_t("public_catalog_show_price", "Show prices by default"))
    show_availability = forms.BooleanField(
        required=False, label=lazy_t("public_catalog_show_availability", "Show availability by default"),
    )

    def __init__(self, *args, current_value=None, **kwargs):
        kwargs.pop("request", None)
        kwargs.pop("namespace", None)
        kwargs.pop("settings_definition", None)
        config = {**PUBLIC_CATALOG_DEFAULTS, **(current_value if isinstance(current_value, dict) else {})}
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("public_enabled", bool(config["enabled"]))
        for name in (*TEXT_FIELDS, *TOGGLE_FIELDS):
            initial.setdefault(name, config[name])
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        lock_dependents(self, "public_enabled", [*TEXT_FIELDS, *TOGGLE_FIELDS])

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(build_settings_toggle_field(self, "public_enabled", css_class="col-12"), css_class="g-3"),
            dependent_block(
                self, "public_enabled",
                Row(
                    Div("shop_title", css_class="col-12 col-lg-6"),
                    Div("contact_email", css_class="col-12 col-lg-6"),
                    css_class="g-3 mt-1",
                ),
                Row(Div("shop_subtitle", css_class="col-12"), css_class="g-3"),
                Row(
                    Div("contact_phone", css_class="col-12 col-lg-6"),
                    Div("contact_whatsapp", css_class="col-12 col-lg-6"),
                    css_class="g-3",
                ),
                Row(
                    *[build_settings_toggle_field(self, name, css_class="col-12 col-lg-6") for name in TOGGLE_FIELDS],
                    css_class="g-3 mt-1",
                ),
            ),
        )

    def to_app_config(self, current_value=None):
        # Keep what the builders store in this namespace (homepage/shop live flags, featured limit).
        config = {**PUBLIC_CATALOG_DEFAULTS, **(current_value if isinstance(current_value, dict) else {})}
        data = self.cleaned_data
        config["enabled"] = bool(data.get("public_enabled"))
        for name in TEXT_FIELDS:
            config[name] = (data.get(name) or "").strip()
        for name in TOGGLE_FIELDS:
            config[name] = bool(data.get(name))
        return config
