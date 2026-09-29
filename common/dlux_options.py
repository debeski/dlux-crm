from dlux.options import register_app_settings

from common.i18n import lazy_t

from .crm_options import CRM_OPTIONS_NS, CrmOptionsForm, crm_sections


register_app_settings(
    namespace=CRM_OPTIONS_NS,
    title=lazy_t("options_crm", "CRM options"),
    description=lazy_t(
        "options_crm_desc",
        "Store-wide settings for the products list, the public shop and the till.",
    ),
    icon="bi-sliders",
    order=50,
    form_class=CrmOptionsForm,
    visible=lambda request: bool(crm_sections()),
)
