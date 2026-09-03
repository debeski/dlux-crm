from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "catalog"
    verbose_name = "Catalog"

    def ready(self):
        # A dlux data reset clears rows in bulk, so no save() runs and the stock
        # balances carried on Product/ProductVariant keep the quantities their
        # deleted movements had put there. Rebuild them from what survives.
        from dlux.admin_actions.data_reset import data_reset_finished

        from .stock_balance import on_data_reset_finished

        data_reset_finished.connect(on_data_reset_finished, dispatch_uid="catalog.rebuild_stock_balances")
