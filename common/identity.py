from dlux.utils import get_system_config


def store_name():
    """The store's own display name from DLux identity settings."""
    identity = get_system_config().get("identity") or {}
    return str(identity.get("display_name") or "").strip()
