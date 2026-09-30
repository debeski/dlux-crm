from copy import deepcopy
from decimal import Decimal, InvalidOperation


POS_NS = "switch_pos.point_of_sale"

POS_METHODS = ("cash", "card", "bank_transfer")
RECEIPT_SIZES = ("none", "58", "80", "a4")

POS_DEFAULTS = {
    "enabled": False,
    "methods": {method: True for method in POS_METHODS},
    "max_discount_percent": "10",
    "receipt_size": "80",
}


def normalize_pos_config(value):
    config = deepcopy(POS_DEFAULTS)
    source = value if isinstance(value, dict) else {}
    config["enabled"] = source.get("enabled") is True
    methods = source.get("methods") if isinstance(source.get("methods"), dict) else {}
    for method in POS_METHODS:
        if method in methods:
            config["methods"][method] = methods[method] is True
    if not any(config["methods"].values()):
        config["methods"]["cash"] = True
    if source.get("receipt_size") in RECEIPT_SIZES:
        config["receipt_size"] = source["receipt_size"]
    try:
        cap = Decimal(str(source.get("max_discount_percent", POS_DEFAULTS["max_discount_percent"])))
    except (InvalidOperation, ValueError):
        cap = Decimal(POS_DEFAULTS["max_discount_percent"])
    config["max_discount_percent"] = str(min(max(cap, Decimal("0")), Decimal("100")))
    return config


def get_pos_config():
    try:
        from dlux.utils import get_app_system_config

        value = get_app_system_config(POS_NS, POS_DEFAULTS)
    except Exception:
        value = POS_DEFAULTS
    return normalize_pos_config(value)


def pos_enabled():
    return get_pos_config()["enabled"]


def enabled_methods(config=None):
    config = config or get_pos_config()
    return [method for method in POS_METHODS if config["methods"][method]]
