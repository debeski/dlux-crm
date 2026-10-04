from automotive.settings import get_optional_enhancements_config


def machinery_enabled():
    return get_optional_enhancements_config()["machinery"]["enabled"]
