try:
    from dlux.options import register_app_settings
except ImportError:  # pragma: no cover - guarded for older development runtimes
    register_app_settings = None

from common.i18n import lazy_t

from .options_forms import OptionalEnhancementsSettingsForm
from .settings import OPTIONAL_ENHANCEMENTS_DEFAULTS, OPTIONAL_ENHANCEMENTS_NS


if register_app_settings is not None:
    register_app_settings(
        namespace=OPTIONAL_ENHANCEMENTS_NS,
        title=lazy_t("options_optional_enhancements", "Optional enhancements"),
        description=lazy_t(
            "options_optional_enhancements_desc",
            "Enable store-specific CRM experiences without changing the generic product and stock model.",
        ),
        icon="bi-magic",
        order=70,
        form_class=OptionalEnhancementsSettingsForm,
        defaults=OPTIONAL_ENHANCEMENTS_DEFAULTS,
    )
