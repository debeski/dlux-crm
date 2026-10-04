from datetime import date
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase

from dlux.models import SystemSettings

from automotive.filters import VehicleModelFilter
from automotive.fits import search_vehicles
from automotive.models import VehicleMake, VehicleModel
from automotive.settings import OPTIONAL_ENHANCEMENTS_DEFAULTS
from catalog.filters import ProductFilter
from catalog.forms import PurchaseInvoiceForm
from catalog.models import Product, PurchaseInvoice, StockMovement
from catalog.tests import test_purchase_invoices as purchase_helpers
from finance.currency import PRICING_NS, active_currencies
from finance.models import ExchangeRate
from sales.models import Invoice, InvoiceItem
from sales.pos import lookup
from sales.reports import build_financial_report
from sales.views import _apply_item_price


class ProductCurrencyTests(TestCase):
    _row = purchase_helpers.PurchaseInvoiceTests._row
    _post_data = purchase_helpers.PurchaseInvoiceTests._post_data
    _post = purchase_helpers.PurchaseInvoiceTests._post

    def _post_purchase(self, rows, **header):
        return self._post(self._post_data(rows, **header))

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.extra_config = {**(settings.extra_config or {}), "app": {
            **((settings.extra_config or {}).get("app") or {}),
            PRICING_NS: {"currency": "USD", "both_active": True},
        }}
        settings.save()
        cache.clear()
        ExchangeRate.objects.create(currency="USD", rate=Decimal("7"))
        ExchangeRate.objects.create(currency="EUR", rate=Decimal("8"))
        self.user = get_user_model().objects.create_user("buyer")
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="catalog", codename__in=(
                "add_purchaseinvoice", "add_product", "change_product", "add_stockmovement", "view_product",
            ),
        ))
        self.usd = Product.objects.create(name="USD part", alias="فلتر محلي", currency="USD", cost_usd=100, price_usd=120, stock_qty=2)
        self.eur = Product.objects.create(name="EUR part", alias="Local pump", currency="EUR", cost_usd=100, price_usd=120, stock_qty=3)

    def test_buyer_uses_existing_permission_and_both_rates(self):
        self.assertEqual(active_currencies(), ("USD", "EUR"))
        form = PurchaseInvoiceForm(user=self.user)
        self.assertFalse(form.fields["currency"].disabled)
        self.assertEqual(dict(form.fields["currency"].choices), {"USD": "USD", "EUR": "EUR"})
        self.assertFalse(Permission.objects.filter(codename="choose_purchase_currency").exists())

    def test_eur_purchase_preserves_invoice_and_existing_usd_product(self):
        response = self._post_purchase([self._row(
            product=self.usd.pk, name=self.usd.name, currency="USD", cost_usd="100", price_usd="120", quantity="2",
        )], currency="EUR")
        self.assertEqual(response.status_code, 302)
        invoice = PurchaseInvoice.objects.get()
        self.usd.refresh_from_db()
        self.assertEqual((invoice.currency, invoice.exchange_rate, invoice.total_usd, invoice.total_lyd),
                         ("EUR", Decimal("8"), Decimal("200"), Decimal("1600")))
        self.assertEqual(invoice.lines.get().cost_usd, Decimal("100"))
        self.assertEqual((self.usd.currency, self.usd.cost_usd, self.usd.price_usd, self.usd.stock_qty),
                         ("USD", Decimal("114.29"), Decimal("137.14"), Decimal("4")))
        self.assertEqual(StockMovement.objects.count(), 1)
        ExchangeRate.objects.create(currency="EUR", rate=10)
        invoice.refresh_from_db()
        self.assertEqual(invoice.total_lyd, Decimal("1600"))

    def test_new_purchase_product_defaults_to_invoice_currency_and_keeps_alias(self):
        response = self._post_purchase([self._row(name="New machine part", alias="اسم محلي", cost_usd="100", price_usd="120", quantity="1")], currency="EUR")
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name="New machine part")
        self.assertEqual((product.currency, product.alias, product.cost_usd), ("EUR", "اسم محلي", Decimal("100")))

    def test_single_currency_mode_rejects_posted_alternative_without_writes(self):
        settings = SystemSettings.load()
        settings.extra_config["app"][PRICING_NS]["both_active"] = False
        settings.save()
        cache.clear()
        response = self._post_purchase([self._row(name="Forged", cost_usd="100", quantity="1")], currency="EUR")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PurchaseInvoice.objects.exists())
        self.assertFalse(Product.objects.filter(name="Forged").exists())

    def test_purchase_permission_required(self):
        from django.core.exceptions import PermissionDenied
        self.user = get_user_model().objects.create_user("unauthorized")
        with self.assertRaises(PermissionDenied):
            self._post_purchase([self._row(name="Forbidden", cost_usd="1", quantity="1")], currency="EUR")
        self.assertFalse(PurchaseInvoice.objects.exists())

    def test_missing_cross_rate_rejects_purchase_atomically(self):
        ExchangeRate.all_objects.filter(currency="EUR").update(deleted_at=date.today())
        cache.clear()
        response = self._post_purchase([self._row(name="No rate", cost_usd="100", quantity="1")], currency="EUR")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PurchaseInvoice.objects.exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_prices_till_and_stock_valuation_use_product_currency(self):
        self.assertEqual(self.usd.selling_price_lyd(), Decimal("840"))
        self.assertEqual(self.eur.selling_price_lyd(), Decimal("960"))
        self.assertEqual(lookup("Local pump", user=self.user)["items"][0]["price"], "960.00")
        report = build_financial_report(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(report["inventory_value"], Decimal("3800"))

    def test_mixed_sale_cost_freezes_in_lyd_and_survives_rate_and_currency_edits(self):
        invoice = Invoice.objects.create(currency="USD", exchange_rate=7, status=Invoice.STATUS_ISSUED, invoice_date=date(2026, 10, 3))
        for product in (self.usd, self.eur):
            item = InvoiceItem(invoice=invoice, product=product, quantity=1)
            _apply_item_price(item, invoice)
            item.save()
        self.assertEqual(list(invoice.items.order_by("pk").values_list("unit_price_lyd", flat=True)), [Decimal("840"), Decimal("960")])
        self.assertEqual(list(invoice.items.order_by("pk").values_list("unit_cost_lyd", flat=True)), [Decimal("700"), Decimal("800")])
        ExchangeRate.objects.create(currency="EUR", rate=10)
        Product.objects.filter(pk=self.eur.pk).update(cost_usd=999, currency="USD")
        report = build_financial_report(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(report["cogs"], Decimal("1500"))

    def test_product_and_machine_alias_search(self):
        self.assertEqual(list(ProductFilter({"keyword": "فلتر محلي"}, queryset=Product.objects.all()).qs), [self.usd])
        make = VehicleMake.objects.create(name="Caterpillar")
        machine = VehicleModel.objects.create(make=make, name="320", alias="حفار كبير")
        self.assertEqual(list(VehicleModelFilter({"keyword": "حفار"}, queryset=VehicleModel.objects.all()).qs), [machine])
        admin = get_user_model().objects.create_superuser("alias-admin", "alias@example.com", "x")
        matches = search_vehicles("حفار كبير", user=admin, criteria=OPTIONAL_ENHANCEMENTS_DEFAULTS["automotive"]["criteria"])
        self.assertEqual(len(matches), 1)

    def test_currency_backfill_preserves_existing_eur_store_amounts(self):
        settings = SystemSettings.load()
        extra = settings.extra_config
        extra["app"][PRICING_NS]["currency"] = "EUR"
        SystemSettings.objects.filter(pk=settings.pk).update(extra_config=extra, language_config={
            **settings.language_config, "translations_override": {
                "en": {"label_product_cost_usd": "Import Cost (EUR)", "label_product_price_usd": "Custom price"},
            },
        })
        migration = import_module("catalog.migrations.0010_alter_purchaseinvoice_options_product_alias_and_more")
        historical_apps = MigrationExecutor(connection).loader.project_state([("catalog", "0010_alter_purchaseinvoice_options_product_alias_and_more")]).apps
        migration.backfill_currency(historical_apps, SimpleNamespace(connection=connection))
        self.usd.refresh_from_db()
        self.assertEqual((self.usd.currency, self.usd.cost_usd), ("EUR", Decimal("100")))
        settings.refresh_from_db()
        self.assertEqual(settings.translations_override["en"], {"label_product_price_usd": "Custom price"})

    def test_alias_in_picker_json_cannot_close_the_script_element(self):
        import json
        from catalog.views import _product_autofill_map_json
        from sales.views import _InvoiceEditorView

        alias = '</script><script>alert("alias")</script>'
        self.usd.alias = alias
        self.usd.save()
        payload = _product_autofill_map_json()
        self.assertNotIn("</script>", payload)
        self.assertEqual(json.loads(payload)[str(self.usd.pk)]["alias"], alias)
        sales_payload = _InvoiceEditorView()._catalog_map(Decimal("7"))
        self.assertNotIn("</script>", sales_payload)
        products = {p["id"]: p for p in json.loads(sales_payload)["products"]}
        self.assertEqual(products[self.usd.pk]["alias"], alias)

    def test_opening_stock_row_carries_currency_specific_preview_rates(self):
        import json
        from catalog.forms import OpeningStockLineForm, PurchaseInvoiceLineForm
        form = OpeningStockLineForm()
        attrs = form.fields["currency"].widget.attrs
        self.assertEqual(attrs.get("data-product-currency"), "1")
        self.assertEqual(json.loads(attrs["data-currency-rates"]), {"USD": "7", "EUR": "8"})
        self.assertNotIn("data-product-currency", PurchaseInvoiceLineForm(invoice_currency="EUR").fields["currency"].widget.attrs)
