from dlux.options import register_app_settings

from common.dlux_options import CRM_OPTIONS_GROUP
from common.i18n import lazy_t

from .options_forms import PublicCatalogSettingsForm
from .settings import PUBLIC_CATALOG_DEFAULTS, PUBLIC_CATALOG_NS


register_app_settings(
    namespace=PUBLIC_CATALOG_NS,
    group=CRM_OPTIONS_GROUP,
    title=lazy_t("options_public_catalog", "Public catalog"),
    description=lazy_t(
        "options_public_catalog_desc",
        "Public shop identity, contact endpoints, and new-listing defaults.",
    ),
    order=20,
    form_class=PublicCatalogSettingsForm,
    defaults=PUBLIC_CATALOG_DEFAULTS,
)
