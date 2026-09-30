from django.apps import AppConfig


class AutomotiveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "automotive"
    verbose_name = "Automotive Compatibility"

    def ready(self):
        from django.db.models.signals import post_migrate, post_save

        from .terminology import refresh_terminology, sync_terminology

        post_migrate.connect(refresh_terminology, sender=self, dispatch_uid="automotive_refresh_terminology")
        post_save.connect(sync_terminology, sender="dlux.SystemSettings", dispatch_uid="automotive_sync_terminology")
