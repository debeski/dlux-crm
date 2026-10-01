from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from dlux.models import SystemSettings
from dlux.options import app_settings_form_prefix

from catalog.models import Product, Service
from finance.currency import PRICING_NS, pricing_currency
from finance.models import ExchangeRate
from finance.services import get_current_rate, rate_overview
from sales.models import Invoice, InvoiceItem


User = get_user_model()
PREFIX = app_settings_form_prefix(PRICING_NS)


class PricingCurrencyTests(TestCase):
    def setUp(self):
        import common.dlux_options  # noqa: F401
        import finance.dlux_options  # noqa: F401

        # Saved settings and live rates are cached; a rollback does not reach the cache.
        cache.clear()
        self.addCleanup(cache.clear)
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        ExchangeRate.objects.create(currency="USD", rate=Decimal("9.5000"))
        ExchangeRate.objects.create(currency="EUR", rate=Decimal("10.0000"))
        self.admin = User.objects.create_superuser("pricing-admin", "pricing@example.com", "x")
        self.client.force_login(self.admin)
        self.url = reverse("dlux_app_settings_group_modal", args=["switch_pos.crm_options"])
        self.filter = Product.objects.create(name="Oil Filter", cost_usd=Decimal("100.00"), markup_percent=Decimal("50"))
        self.fitting = Service.objects.create(name="Fitting", price_usd=Decimal("20.00"))

    def switch(self, currency, convert=True):
        data = {f"{PREFIX}-currency": currency}
        if convert:
            data[f"{PREFIX}-convert_prices"] = "on"
        response = self.client.post(self.url, data)
        cache.clear()
        return response.json()

    def test_usd_is_the_default_and_drives_the_live_rate(self):
        self.assertEqual(pricing_currency(), "USD")
        self.assertEqual(get_current_rate(), Decimal("9.5000"))

    def test_switching_converts_catalog_prices_and_keeps_lyd_prices(self):
        lyd_before = self.filter.selling_price_lyd()
        self.assertTrue(self.switch("EUR").get("success"))
        self.assertEqual(pricing_currency(), "EUR")
        self.assertEqual(get_current_rate(), Decimal("10.0000"))
        self.filter.refresh_from_db()
        self.fitting.refresh_from_db()
        self.assertEqual((self.filter.cost_usd, self.filter.price_usd), (Decimal("95.00"), Decimal("142.50")))
        self.assertEqual(self.fitting.price_usd, Decimal("19.00"))
        self.assertEqual(self.filter.selling_price_lyd(), lyd_before)

        self.assertTrue(self.switch("USD").get("success"))
        self.filter.refresh_from_db()
        self.assertEqual((self.filter.cost_usd, self.filter.price_usd), (Decimal("100.00"), Decimal("150.00")))

    def test_drafts_follow_the_switch_and_issued_invoices_keep_their_currency(self):
        draft = Invoice.objects.create(customer_name="Draft", exchange_rate=Decimal("9.5000"))
        InvoiceItem.objects.create(
            invoice=draft, product=self.filter, quantity=1, unit_price_lyd=Decimal("1425.00"),
            unit_price_usd=Decimal("150.00"), unit_cost_usd=Decimal("100.00"),
        )
        issued = Invoice.objects.create(customer_name="Issued", exchange_rate=Decimal("9.5000"), status=Invoice.STATUS_ISSUED)
        self.assertEqual((draft.currency, issued.currency), ("USD", "USD"))

        self.switch("EUR")
        draft.refresh_from_db()
        issued.refresh_from_db()
        self.assertEqual((draft.currency, draft.exchange_rate), ("EUR", Decimal("10.0000")))
        item = draft.items.get()
        self.assertEqual((item.unit_price_usd, item.unit_cost_usd, item.unit_price_lyd), (Decimal("142.50"), Decimal("95.00"), Decimal("1425.00")))
        self.assertEqual((issued.currency, issued.exchange_rate), ("USD", Decimal("9.5000")))

        fresh = Invoice.objects.create(customer_name="New", exchange_rate=get_current_rate())
        self.assertEqual((fresh.currency, fresh.exchange_rate), ("EUR", Decimal("10.0000")))

    def test_switch_needs_both_rates_and_a_confirmation(self):
        ExchangeRate.objects.filter(currency="EUR").delete()
        ExchangeRate.all_objects.filter(currency="EUR").delete()
        cache.clear()
        self.assertNotIn("success", self.switch("EUR"))
        ExchangeRate.objects.create(currency="EUR", rate=Decimal("10.0000"))
        cache.clear()
        self.assertNotIn("success", self.switch("EUR", convert=False))
        self.assertEqual(pricing_currency(), "USD")
        self.filter.refresh_from_db()
        self.assertEqual(self.filter.cost_usd, Decimal("100.00"))

    def test_labels_follow_the_currency_and_keep_currency_names(self):
        self.switch("EUR")
        overrides = SystemSettings.objects.get(pk=SystemSettings.load().pk).translations_override
        self.assertEqual(overrides["en"]["label_product_cost_usd"], "Import Cost (EUR)")
        self.assertEqual(overrides["ar"]["label_product_cost_usd"], "تكلفة الاستيراد (يورو)")
        self.assertNotIn("currency_usd", overrides["en"])

        self.switch("USD")
        overrides = SystemSettings.objects.get(pk=SystemSettings.load().pk).translations_override or {}
        self.assertNotIn("label_product_cost_usd", overrides.get("en", {}))

    def test_rate_overview_lists_both_currencies_and_marks_the_pricing_one(self):
        rows = {row["code"]: row for row in rate_overview()}
        self.assertEqual((rows["USD"]["store"], rows["EUR"]["store"]), (Decimal("9.5000"), Decimal("10.0000")))
        self.assertTrue(rows["USD"]["is_pricing"])
        self.switch("EUR")
        self.assertTrue({row["code"]: row for row in rate_overview()}["EUR"]["is_pricing"])

    def test_opening_stock_headers_follow_the_currency(self):
        from catalog.opening_stock_import import _HEADER_ALIASES, import_columns

        self.assertIn("Cost (USD)", [label for _key, label, _required in import_columns()])
        self.switch("EUR")
        self.assertIn("Cost (EUR)", [label for _key, label, _required in import_columns()])
        self.assertEqual(_HEADER_ALIASES["cost (eur)"], "cost_usd")

    def test_workspace_exchange_card_shows_both_currencies(self):
        html = self.client.get(reverse("common:workspace_dashboard")).content.decode()
        board = html[html.find('class="rate-board"'):]
        self.assertIn("USD", board[:3000])
        self.assertIn("EUR", board[:3000])
        self.assertIn("9.5", board[:3000])
