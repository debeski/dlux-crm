from django.apps import AppConfig


class CommonConfig(AppConfig):
    """Project-shared app with NO models — exists so DjangoLux discovers
    ``common/translations.py`` (shared UI strings, table headers, choice labels)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "common"
    verbose_name = "Common"

    def ready(self):
        # Enforce per-employee row ownership on the dlux dynamic-modal
        # edit/view/delete object lookup (see common.access). Registered rather
        # than patched, and registered here rather than on the first request:
        # `dlux.access` imports nothing, so this costs no startup query — the
        # reason the old monkey-patch had to wait for `request_started` was that
        # importing `dlux.views` triggered section discovery.
        from dlux.access import register_modal_queryset_filter

        from .access import apply_ownership

        register_modal_queryset_filter(apply_ownership)

        # Store wording (machine vs vehicle, EUR vs USD) follows every save of the
        # settings row and every migrate; apps register their axes in their own ready().
        from django.db.models.signals import post_migrate, post_save

        from .wording import refresh_wording, sync_wording

        post_save.connect(sync_wording, sender="dlux.SystemSettings", dispatch_uid="common_sync_wording")
        post_migrate.connect(refresh_wording, sender=self, dispatch_uid="common_refresh_wording")
