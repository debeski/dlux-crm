from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finance"
    verbose_name = "Finance"

    def ready(self):
        from django.db.models.signals import pre_save

        from . import wording  # noqa: F401  registers the USD/EUR wording axis
        from .currency import convert_on_switch

        pre_save.connect(convert_on_switch, sender="dlux.SystemSettings", dispatch_uid="finance_convert_on_switch")
