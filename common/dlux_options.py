from dlux.options import register_app_settings_group

from common.i18n import lazy_t

# The store-wide settings of catalog, public_catalog and sales are sections of
# this one tile (register_app_settings(group=CRM_OPTIONS_GROUP)); each still
# saves its own namespace.
CRM_OPTIONS_GROUP = "switch_pos.crm_options"

register_app_settings_group(
    id=CRM_OPTIONS_GROUP,
    title=lazy_t("options_crm", "CRM options"),
    description=lazy_t(
        "options_crm_desc",
        "Store-wide settings for the products list, the public shop and the till.",
    ),
    icon="bi-sliders",
    order=50,
)
