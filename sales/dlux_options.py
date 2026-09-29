try:
    from dlux.options import register_app_settings
except ImportError:  # pragma: no cover - guarded for older development runtimes
    register_app_settings = None

from common.i18n import lazy_t

from .pos_options_forms import PointOfSaleSettingsForm
from .pos_settings import POS_DEFAULTS, POS_NS


if register_app_settings is not None:
    register_app_settings(
        namespace=POS_NS,
        title=lazy_t("pos_settings_title", "Point of sale"),
        description=lazy_t(
            "pos_settings_desc",
            "Quick walk-in sales from a till screen, a wall display, or a phone.",
        ),
        icon="bi-upc-scan",
        order=75,
        form_class=PointOfSaleSettingsForm,
        defaults=POS_DEFAULTS,
    )
