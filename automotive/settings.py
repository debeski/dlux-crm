from copy import deepcopy


OPTIONAL_ENHANCEMENTS_NS = "switch_pos.optional_enhancements"

AUTOMOTIVE_CRITERIA = (
    "generation_chassis",
    "engine",
    "fuel_type",
    "trim",
    "transmission",
    "position",
)

OPTIONAL_ENHANCEMENTS_DEFAULTS = {
    "automotive": {
        "enabled": False,
        "criteria": {criterion: True for criterion in AUTOMOTIVE_CRITERIA},
    },
}


def normalize_optional_enhancements(value):
    normalized = deepcopy(OPTIONAL_ENHANCEMENTS_DEFAULTS)
    source = value if isinstance(value, dict) else {}
    automotive = source.get("automotive")
    automotive = automotive if isinstance(automotive, dict) else {}
    criteria = automotive.get("criteria")
    criteria = criteria if isinstance(criteria, dict) else {}

    normalized_automotive = normalized["automotive"]
    normalized_automotive["enabled"] = automotive.get("enabled") is True
    for criterion in AUTOMOTIVE_CRITERIA:
        if criterion in criteria:
            normalized_automotive["criteria"][criterion] = criteria[criterion] is True

    # Fuel is an engine attribute. A malformed direct JSON write must not leave
    # the application with fuel filtering enabled while engines are unavailable.
    if normalized_automotive["criteria"]["fuel_type"]:
        normalized_automotive["criteria"]["engine"] = True
    return normalized


def get_optional_enhancements_config():
    try:
        from dlux.utils import get_app_system_config

        value = get_app_system_config(
            OPTIONAL_ENHANCEMENTS_NS,
            OPTIONAL_ENHANCEMENTS_DEFAULTS,
        )
    except Exception:
        value = OPTIONAL_ENHANCEMENTS_DEFAULTS
    return normalize_optional_enhancements(value)


def get_automotive_config():
    return get_optional_enhancements_config()["automotive"]


def automotive_enabled():
    return get_automotive_config()["enabled"]


def automotive_criterion_enabled(criterion):
    if criterion not in AUTOMOTIVE_CRITERIA:
        return False
    config = get_automotive_config()
    return config["enabled"] and config["criteria"][criterion]
