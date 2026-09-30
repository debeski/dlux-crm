from dlux.options import register_app_settings

from common.dlux_options import CRM_OPTIONS_GROUP
from common.i18n import lazy_t

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
    fields=[
        {"name": "shop_title", "type": "char", "label": lazy_t("public_catalog_shop_title", "Shop title"), "default": PUBLIC_CATALOG_DEFAULTS["shop_title"]},
        {"name": "shop_subtitle", "type": "text", "label": lazy_t("public_catalog_shop_subtitle", "Shop subtitle"), "default": PUBLIC_CATALOG_DEFAULTS["shop_subtitle"]},
        {"name": "contact_phone", "type": "char", "label": lazy_t("public_catalog_contact_phone", "Contact phone"), "default": ""},
        {"name": "contact_whatsapp", "type": "char", "label": lazy_t("public_catalog_contact_whatsapp", "WhatsApp number"), "default": ""},
        {"name": "contact_email", "type": "char", "label": lazy_t("public_catalog_contact_email", "Contact email"), "default": ""},
        {"name": "show_price", "type": "boolean", "label": lazy_t("public_catalog_show_price", "Show prices by default"), "default": True},
        {"name": "show_availability", "type": "boolean", "label": lazy_t("public_catalog_show_availability", "Show availability by default"), "default": True},
    ],
    defaults=PUBLIC_CATALOG_DEFAULTS,
)
