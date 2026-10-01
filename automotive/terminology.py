"""Vehicle ↔ machine/equipment wording, as a ``common.wording`` axis.

Machine wording rewrites "vehicle"/"car" across the app when the store serves
heavy machinery. ``common.wording`` writes it into the translation override
layer and keeps it in step with the mode saved in Optional enhancements.
"""
import re

from common.wording import register_wording

from .settings import TERMINOLOGY_EQUIPMENT, TERMINOLOGY_VEHICLE

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


def _rewrite(text, lang, mode):
    if lang == "ar":
        for old, new in _AR:
            text = text.replace(old, new)
        return text
    for pattern, new in _EN:
        text = re.sub(pattern, new, text)
    return text


def _stored_mode(settings):
    from dlux.system.constants import SYSTEM_APP_CONFIG_NAMESPACE

    from .settings import OPTIONAL_ENHANCEMENTS_NS, normalize_optional_enhancements

    extra = settings.extra_config if isinstance(settings.extra_config, dict) else {}
    app_bag = extra.get(SYSTEM_APP_CONFIG_NAMESPACE)
    stored = app_bag.get(OPTIONAL_ENHANCEMENTS_NS) if isinstance(app_bag, dict) else None
    return normalize_optional_enhancements(stored)["automotive"]["terminology"]


register_wording(
    "terminology",
    modes=(TERMINOLOGY_VEHICLE, TERMINOLOGY_EQUIPMENT),
    default=TERMINOLOGY_VEHICLE,
    stored_mode=lambda settings: _stored_mode(settings),
    rewrite=_rewrite,
    examples={TERMINOLOGY_EQUIPMENT: _EXAMPLES},
    skip_prefixes=("optional_terminology",),
)
