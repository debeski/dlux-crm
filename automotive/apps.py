from django.apps import AppConfig


class AutomotiveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "automotive"
    verbose_name = "Automotive Compatibility"

    def ready(self):
        from . import terminology  # noqa: F401  registers the vehicle/machine wording axis
