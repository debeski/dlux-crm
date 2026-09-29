"""Vehicle ↔ machine/equipment wording for the compatibility screens.

The words are applied as DLux translation overrides (the same layer an admin
edits in System Settings), so every screen — including DLux's own model labels
and breadcrumbs — follows the store's choice on the next request. Only keys
whose override is absent or still equal to the generated wording are touched,
so an admin's hand-written override always survives a switch.
"""
import re

from .settings import TERMINOLOGY_EQUIPMENT

_EN = (
    (r"\bAutomotive\b", "Equipment"),
    (r"\bautomotive\b", "equipment"),
    (r"\bVehicles\b", "Machines"),
    (r"\bvehicles\b", "machines"),
    (r"\bVehicle\b", "Machine"),
    (r"\bvehicle\b", "machine"),
    (r"\bCars\b", "Machines"),
    (r"\bcars\b", "machines"),
    (r"\bCar\b", "Machine"),
    (r"\bcar\b", "machine"),
)
# Both nouns are feminine, so agreement in the surrounding text still holds.
_AR = (
    ("المركبات", "الآليات"),
    ("مركبات", "آليات"),
    ("المركبة", "الآلية"),
    ("مركبة", "آلية"),
    ("السيارات", "الآليات"),
    ("سيارات", "آليات"),
    ("السيارة", "الآلية"),
    ("سيارة", "آلية"),
)


# Examples a word swap cannot turn into machines.
_EXAMPLES = {
    "en": {
        "fits_search_placeholder": "Type a machine: 320d, pc200-8, perkins 1104…",
        "vehicle_jump_placeholder": "320d, pc200-8, excavator, perkins 1104…",
        "hub_makes_help": "Caterpillar, Komatsu, JCB, and other manufacturers.",
        "hub_models_help": "320D, PC200-8, 3CX, and the make each belongs to.",
        "hub_engines_help": "Engines per machine, or shared engines such as a Perkins 1104 fitted to many.",
    },
    "ar": {
        "fits_search_placeholder": "اكتب الآلية: 320d أو pc200-8 أو perkins 1104…",
        "vehicle_jump_placeholder": "320d أو pc200-8 أو حفار أو perkins 1104…",
        "hub_makes_help": "كاتربيلر وكوماتسو وجي سي بي وغيرها من الشركات.",
        "hub_models_help": "320D و PC200-8 و 3CX والشركة التابعة لكل طراز.",
        "hub_engines_help": "محركات كل آلية، أو محركات مشتركة مثل بيركنز 1104 المركّب على آليات كثيرة.",
    },
}


def _to_equipment(text, lang):
    if lang == "ar":
        for old, new in _AR:
            text = text.replace(old, new)
        return text
    for pattern, new in _EN:
        text = re.sub(pattern, new, text)
    return text


def _source_strings():
    from automotive.translations import DLUX_STRINGS as automotive
    from catalog.translations import DLUX_STRINGS as catalog
    from common.translations import DLUX_STRINGS as common
    from sales.translations import DLUX_STRINGS as sales

    merged = {}
    for bundle in (common, catalog, sales, automotive):
        for lang, strings in bundle.items():
            merged.setdefault(lang, {}).update(strings)
    return merged


def equipment_overrides():
    """{lang: {key: machine wording}} for every string the switch rewrites."""
    overrides = {}
    for lang, strings in _source_strings().items():
        for key, value in strings.items():
            if not isinstance(value, str) or key.startswith("optional_terminology"):
                continue
            changed = _EXAMPLES.get(lang, {}).get(key) or _to_equipment(value, lang)
            if changed != value:
                overrides.setdefault(lang, {})[key] = changed
    return overrides


def apply_terminology(mode):
    """Write or withdraw the machine wording in the translation override layer."""
    from dlux.models import SystemSettings

    settings = SystemSettings.load()
    current = settings.translations_override if isinstance(settings.translations_override, dict) else {}
    overrides = {lang: dict(values) for lang, values in current.items() if isinstance(values, dict)}
    changed = False
    for lang, values in equipment_overrides().items():
        bucket = overrides.setdefault(lang, {})
        for key, wording in values.items():
            if mode == TERMINOLOGY_EQUIPMENT:
                if key not in bucket:
                    bucket[key] = wording
                    changed = True
            elif bucket.get(key) == wording:
                del bucket[key]
                changed = True
    if changed:
        settings.translations_override = {lang: values for lang, values in overrides.items() if values}
        settings.save()
    return changed
