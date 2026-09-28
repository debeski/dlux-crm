from urllib.parse import quote

from dlux.options import write_app_system_config
from dlux.utils import get_app_system_config

from common.identity import store_name

PUBLIC_CATALOG_NS = "switch_pos.public_catalog"

PUBLIC_CATALOG_DEFAULTS = {
    "shop_title": "",          # blank -> the store's system name
    "shop_subtitle": "",
    "contact_phone": "",
    "contact_whatsapp": "",
    "contact_email": "",
    "show_price": True,
    "show_availability": True,
    "homepage_enabled": True,
    "shop_enabled": True,
    "featured_limit": 4,
}


def get_public_catalog_config(*, resolve_names=True):
    stored = get_app_system_config(PUBLIC_CATALOG_NS, {}) or {}
    if not isinstance(stored, dict):
        stored = {}
    cfg = {**PUBLIC_CATALOG_DEFAULTS, **stored}
    # Migrate the old single storefront flag to the split homepage/shop flags.
    if "storefront_enabled" in stored and "homepage_enabled" not in stored and "shop_enabled" not in stored:
        legacy = bool(stored.get("storefront_enabled"))
        cfg["homepage_enabled"] = legacy
        cfg["shop_enabled"] = legacy
    cfg["show_price"] = bool(cfg.get("show_price"))
    cfg["show_availability"] = bool(cfg.get("show_availability"))
    cfg["homepage_enabled"] = bool(cfg.get("homepage_enabled"))
    cfg["shop_enabled"] = bool(cfg.get("shop_enabled"))
    try:
        cfg["featured_limit"] = max(0, int(cfg.get("featured_limit") or 0))
    except (TypeError, ValueError):
        cfg["featured_limit"] = PUBLIC_CATALOG_DEFAULTS["featured_limit"]
    if resolve_names and not str(cfg.get("shop_title") or "").strip():
        cfg["shop_title"] = store_name()
    return cfg


def set_public_catalog_config(patch, *, request=None):
    cfg = get_public_catalog_config(resolve_names=False)
    cfg.update({k: v for k, v in patch.items() if k in PUBLIC_CATALOG_DEFAULTS})
    write_app_system_config(PUBLIC_CATALOG_NS, cfg, request=request)
    return cfg


def contact_links(listing=None):
    cfg = get_public_catalog_config()
    title = listing.display_title if listing is not None else cfg["shop_title"]
    message = quote(f"Hello, I am interested in {title}.")
    links = []
    phone = str(cfg.get("contact_phone") or "").strip()
    whatsapp = str(cfg.get("contact_whatsapp") or "").strip()
    email = str(cfg.get("contact_email") or "").strip()
    if whatsapp:
        normalized = "".join(ch for ch in whatsapp if ch.isdigit())
        if normalized:
            links.append({
                "label": "WhatsApp",
                "icon": "bi-whatsapp",
                "url": f"https://wa.me/{normalized}?text={message}",
                "kind": "whatsapp",
            })
    if phone:
        links.append({
            "label": "Call",
            "icon": "bi-telephone",
            "url": f"tel:{phone}",
            "kind": "phone",
        })
    if email:
        links.append({
            "label": "Email",
            "icon": "bi-envelope",
            "url": f"mailto:{email}?subject={quote(title)}",
            "kind": "email",
        })
    return links

