"""Public homepage (landing page) configuration.

Stored in the DLux app-settings store under its own namespace, exactly like the
public catalog / products-layout settings. The homepage builder writes here; the
public landing view reads a resolved config + an ordered list of enabled sections.

Text fields in ``LOCALIZED_KEYS`` are stored per-language (``{lang_code: value}``)
so the builder can edit each discovered DLux language and the public page renders
the visitor's language (falling back to the default language, then any value).
"""
from dlux.options import write_app_system_config
from dlux.utils import get_app_system_config, get_system_config

HOMEPAGE_NS = "switch_pos.public_homepage"

# Order matters: this is the default section order on a fresh install.
SECTION_KEYS = ("featured", "categories", "services", "story", "contact")

SECTION_VARIANTS = {
    "featured": ("grid", "rail"),
    "categories": ("tiles", "chips"),
    "services": ("grid", "rail"),
    "story": ("split", "banner"),
    "contact": ("band", "compact"),
}

DEFAULT_SECTIONS = [
    {"key": "featured", "enabled": True, "variant": "grid"},
    {"key": "categories", "enabled": False, "variant": "tiles"},
    {"key": "services", "enabled": False, "variant": "grid"},
    {"key": "story", "enabled": False, "variant": "split"},
    {"key": "contact", "enabled": True, "variant": "band"},
]

HERO_MEDIA_MODES = ("featured", "logo", "custom", "gradient")
STYLE_PRESETS = ("signature", "showroom", "precision", "editorial")
HERO_LAYOUTS = ("poster", "center", "mosaic", "compact")
HERO_HEIGHTS = ("balanced", "immersive", "compact")
HERO_FOCUS = ("center", "top", "bottom", "left", "right")
NAV_TREATMENTS = ("glass", "solid", "quiet")
CARD_TREATMENTS = ("showcase", "spec", "minimal")
SECTION_DENSITIES = ("comfortable", "compact")
BACKGROUND_TREATMENTS = ("clean", "grid", "diagonal", "linework")
MOTION_LEVELS = ("subtle", "none", "lively")

CHOICE_FIELDS = {
    "hero_media": HERO_MEDIA_MODES,
    "style_preset": STYLE_PRESETS,
    "hero_layout": HERO_LAYOUTS,
    "hero_height": HERO_HEIGHTS,
    "hero_focus": HERO_FOCUS,
    "nav_treatment": NAV_TREATMENTS,
    "card_treatment": CARD_TREATMENTS,
    "section_density": SECTION_DENSITIES,
    "background_treatment": BACKGROUND_TREATMENTS,
    "motion_level": MOTION_LEVELS,
}

# Text fields stored as {lang_code: value} dicts.
LOCALIZED_KEYS = (
    "hero_kicker", "hero_title", "hero_subtitle", "hero_primary_label", "story_body",
    "featured_kicker", "featured_heading",
    "categories_kicker", "categories_heading",
    "services_kicker", "services_heading",
    "story_kicker", "story_heading",
    "contact_kicker", "contact_heading",
)

HOMEPAGE_DEFAULTS = {
    # Hero (localized text default seeds go to the default language on first read)
    "hero_kicker": "",
    "hero_title": "",            # blank -> shop_title
    "hero_subtitle": "",         # blank -> shop_subtitle
    "hero_primary_label": "Shop",
    "hero_primary_url": "",      # blank -> public shop (not localized)
    "hero_show_contact": True,
    "hero_media": "featured",    # featured | logo | custom | gradient
    "hero_image": "",            # media url when hero_media == custom
    "hero_overlay": 55,          # 0-100 scrim strength
    "show_stats": True,
    # Visual studio
    "style_preset": "signature",
    "hero_layout": "poster",
    "hero_height": "balanced",
    "hero_focus": "center",
    "nav_treatment": "glass",
    "card_treatment": "showcase",
    "section_density": "comfortable",
    "background_treatment": "clean",
    "motion_level": "subtle",
    # Site accents (blank -> theme default)
    "accent": "",
    "accent_secondary": "",
    # Per-section copy (localized)
    "featured_kicker": "Featured catalog",
    "featured_heading": "Ready for customer viewing",
    "categories_kicker": "Categories",
    "categories_heading": "Browse by category",
    "services_kicker": "What we do",
    "services_heading": "Services we provide",
    "story_kicker": "Who we are",
    "story_heading": "About us",
    "story_body": "",
    "story_image": "",           # not localized
    "contact_kicker": "Contact",
    "contact_heading": "Get in touch",
    # Ordered, toggleable sections
    "sections": DEFAULT_SECTIONS,
}

_BOOL_KEYS = ("hero_show_contact", "show_stats")


def get_public_languages():
    """Return (``[(code, label), ...]``, default_code) from DLux system config."""
    cfg = get_system_config()
    langs = cfg.get("languages") or {}
    codes = list(langs.keys()) or ["en"]
    default = str(cfg.get("default_language") or codes[0])
    if default not in codes:
        default = codes[0]
    return [(code, (langs.get(code) or {}).get("name", code.upper())) for code in codes], default


def _lang_codes():
    langs, default = get_public_languages()
    return [code for code, _label in langs], default


def _normalize_localized(value, codes, default):
    if isinstance(value, dict):
        return {code: str(value.get(code, "") or "") for code in codes}
    out = {code: "" for code in codes}
    out[default] = str(value or "")
    return out


def localize(value, lang, default):
    if isinstance(value, dict):
        return value.get(lang) or value.get(default) or next((v for v in value.values() if v), "")
    return value or ""


def _clamp_overlay(value):
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return HOMEPAGE_DEFAULTS["hero_overlay"]


def normalize_sections(stored):
    """Return a clean [{key, enabled}] list: stored order first (deduped, known
    keys only), then any newly-added default sections appended."""
    defaults = {section["key"]: section for section in DEFAULT_SECTIONS}
    result, seen = [], set()
    if isinstance(stored, list):
        for item in stored:
            key = item.get("key") if isinstance(item, dict) else None
            if key in SECTION_KEYS and key not in seen:
                variant = item.get("variant") if isinstance(item, dict) else None
                if variant not in SECTION_VARIANTS[key]:
                    variant = defaults[key]["variant"]
                result.append({
                    "key": key,
                    "enabled": bool(item.get("enabled", True)),
                    "variant": variant,
                })
                seen.add(key)
    for default in DEFAULT_SECTIONS:
        if default["key"] not in seen:
            result.append(dict(default))
            seen.add(default["key"])
    return result


def _sanitize_hex(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if not value.startswith("#"):
        value = "#" + value
    body = value[1:]
    if len(body) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in body):
        return value.lower()
    return ""


def get_homepage_config():
    stored = get_app_system_config(HOMEPAGE_NS, {}) or {}
    if not isinstance(stored, dict):
        stored = {}
    cfg = {**HOMEPAGE_DEFAULTS, **stored}
    codes, default = _lang_codes()
    for key in LOCALIZED_KEYS:
        cfg[key] = _normalize_localized(cfg.get(key), codes, default)
    for key in _BOOL_KEYS:
        cfg[key] = bool(cfg.get(key))
    cfg["hero_overlay"] = _clamp_overlay(cfg.get("hero_overlay"))
    for key, choices in CHOICE_FIELDS.items():
        if cfg.get(key) not in choices:
            cfg[key] = HOMEPAGE_DEFAULTS[key]
    cfg["accent"] = _sanitize_hex(cfg.get("accent"))
    cfg["accent_secondary"] = _sanitize_hex(cfg.get("accent_secondary"))
    cfg["sections"] = normalize_sections(cfg.get("sections"))
    return cfg


def set_homepage_config(patch, *, request=None):
    cfg = get_homepage_config()
    codes, default = _lang_codes()
    for key, value in patch.items():
        if key not in HOMEPAGE_DEFAULTS:
            continue
        if key in LOCALIZED_KEYS:
            cfg[key] = _normalize_localized(value, codes, default)
        elif key == "sections":
            cfg[key] = normalize_sections(value)
        elif key in _BOOL_KEYS:
            cfg[key] = bool(value)
        elif key == "hero_overlay":
            cfg[key] = _clamp_overlay(value)
        elif key in ("accent", "accent_secondary"):
            cfg[key] = _sanitize_hex(value)
        elif key in CHOICE_FIELDS:
            cfg[key] = value if value in CHOICE_FIELDS[key] else HOMEPAGE_DEFAULTS[key]
        else:
            cfg[key] = value
    write_app_system_config(HOMEPAGE_NS, cfg, request=request)
    return cfg


def resolve_homepage(cfg=None, lang=None):
    """Flatten localized fields to plain strings for the given language, for the
    public landing template."""
    cfg = cfg or get_homepage_config()
    _codes, default = _lang_codes()
    lang = lang or default
    flat = dict(cfg)
    for key in LOCALIZED_KEYS:
        flat[key] = localize(cfg.get(key), lang, default)
    return flat


def resolve_sections(flat_cfg=None):
    """Ordered sections with resolved (already-flattened) copy, for the landing.
    Pass the output of ``resolve_homepage`` so kicker/heading are plain strings."""
    from common.i18n import t

    flat_cfg = flat_cfg if flat_cfg is not None else resolve_homepage()
    resolved = []
    for section in flat_cfg["sections"]:
        key = section["key"]
        resolved.append({
            "key": key,
            "label": t(f"hp_section_{key}", key.capitalize()),
            "enabled": bool(section.get("enabled")),
            "variant": section.get("variant") or DEFAULT_SECTIONS[SECTION_KEYS.index(key)]["variant"],
            "kicker": flat_cfg.get(f"{key}_kicker", ""),
            "heading": flat_cfg.get(f"{key}_heading", ""),
        })
    return resolved


def builder_sections(cfg=None):
    """Ordered sections with RAW per-language dicts, for the builder editor."""
    from common.i18n import t

    cfg = cfg or get_homepage_config()
    out = []
    variant_labels = {
        "grid": t("hp_variant_grid", "Grid"),
        "rail": t("hp_variant_rail", "Rail"),
        "tiles": t("hp_variant_tiles", "Tiles"),
        "chips": t("hp_variant_chips", "Chips"),
        "split": t("hp_variant_split", "Split"),
        "banner": t("hp_variant_banner", "Banner"),
        "band": t("hp_variant_band", "Band"),
        "compact": t("hp_variant_compact", "Compact"),
    }
    for section in cfg["sections"]:
        key = section["key"]
        out.append({
            "key": key,
            "label": t(f"hp_section_{key}", key.capitalize()),
            "enabled": bool(section.get("enabled")),
            "variant": section.get("variant") or DEFAULT_SECTIONS[SECTION_KEYS.index(key)]["variant"],
            "variants": [
                {"value": variant, "label": variant_labels.get(variant, variant.capitalize())}
                for variant in SECTION_VARIANTS[key]
            ],
            "kicker": cfg.get(f"{key}_kicker", {}),
            "heading": cfg.get(f"{key}_heading", {}),
        })
    return out
