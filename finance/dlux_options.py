from dlux.options import register_app_settings

from common.dlux_options import CRM_OPTIONS_GROUP
from common.i18n import lazy_t

from .currency import PRICING_DEFAULTS, PRICING_NS
from .pricing_options_forms import PricingSettingsForm


register_app_settings(
    namespace=PRICING_NS,
    group=CRM_OPTIONS_GROUP,
    title=lazy_t("pricing_settings_title", "Pricing currency"),
    description=lazy_t(
        "pricing_settings_desc",
        "USD or EUR for costs and prices across the system; amounts in LYD are unaffected.",
    ),
    order=5,
    form_class=PricingSettingsForm,
    defaults=PRICING_DEFAULTS,
)
