from dlux.options import register_app_settings

from common.dlux_options import CRM_OPTIONS_GROUP
from common.i18n import lazy_t

from .pos_options_forms import PointOfSaleSettingsForm
from .pos_settings import POS_DEFAULTS, POS_NS


register_app_settings(
    namespace=POS_NS,
    group=CRM_OPTIONS_GROUP,
    title=lazy_t("pos_settings_title", "Point of sale"),
    description=lazy_t(
        "pos_settings_desc",
        "Quick walk-in sales from a till screen, a wall display, or a phone.",
    ),
    order=30,
    form_class=PointOfSaleSettingsForm,
    defaults=POS_DEFAULTS,
)
