from common.crm_options import register_crm_section
from common.i18n import lazy_t

from .pos_options_forms import PointOfSaleSettingsForm
from .pos_settings import POS_DEFAULTS, POS_NS


register_crm_section(
    key="point_of_sale",
    namespace=POS_NS,
    title=lazy_t("pos_settings_title", "Point of sale"),
    description=lazy_t(
        "pos_settings_desc",
        "Quick walk-in sales from a till screen, a wall display, or a phone.",
    ),
    order=30,
    form_class=PointOfSaleSettingsForm,
    defaults=POS_DEFAULTS,
)
