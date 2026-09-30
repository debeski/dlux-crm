import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from catalog.models import Product, ProductBarcode, ProductVariant, StockMovement
from finance.models import ExchangeRate
from sales.models import Invoice, PosSale
from sales.pos_settings import POS_DEFAULTS


User = get_user_model()


def pos_on(**overrides):
    return patch("dlux.utils.get_app_system_config", side_effect=lambda namespace, default=None: (
        {**POS_DEFAULTS, "enabled": True, **overrides} if namespace == "switch_pos.point_of_sale" else default
    ))


class PosTestCase(TestCase):
    def setUp(self):
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        ExchangeRate.objects.create(rate=Decimal("6.50"))
        self.admin = User.objects.create_superuser("pos-admin", "pos@example.com", "x")
        self.client.force_login(self.admin)
        self.filter = Product.objects.create(
            name="Oil Filter", barcode="6290000000011", price_lyd_override=Decimal("50.00"), track_stock=True,
        )
        self.stock_in(self.filter, 5)

    def stock_in(self, product, qty, variant=None):
        StockMovement.objects.create(
            product=product, variant=variant or ProductVariant.get_or_create_for(product, None, None),
            movement_type=StockMovement.TYPE_IN, quantity=qty, reason="test",
        )

    def lookup(self, query):
        with pos_on():
            return self.client.get(reverse("sales:pos_lookup"), {"q": query}).json()

    def checkout(self, body, client=None, **config):
        with pos_on(**config):
            return (client or self.client).post(
                reverse("sales:pos_checkout"), json.dumps(body), content_type="application/json",
            )

    def sale(self, **extra):
        body = {
            "key": "sale-1",
            "lines": [{"product": self.filter.pk, "qty": 2}],
            "payments": [{"method": "cash", "amount": "100"}],
        }
        body.update(extra)
        return body


class PosAccessTests(PosTestCase):
    def test_till_is_hidden_while_disabled(self):
        self.assertEqual(self.client.get(reverse("sales:pos_till")).status_code, 404)
        with pos_on():
            self.assertEqual(self.client.get(reverse("sales:pos_till")).status_code, 200)

    def test_seller_without_pos_permission_is_refused(self):
        seller = User.objects.create_user("no-pos", password="x")
        self.client.force_login(seller)
        with pos_on():
            self.assertEqual(self.client.get(reverse("sales:pos_till")).status_code, 403)


class PosLookupTests(PosTestCase):
    def test_primary_barcode_and_sku_are_exact_hits(self):
        self.assertTrue(self.lookup("6290000000011")["exact"])
        self.assertTrue(self.lookup(self.filter.sku)["exact"])

    def test_extra_barcode_resolves_its_variant(self):
        variant = ProductVariant.objects.create(product=self.filter, color="", size="Large")
        ProductVariant.objects.create(product=self.filter, color="", size="Small")
        ProductBarcode.objects.create(product=self.filter, variant=variant, code="SUPPLIER-77")
        data = self.lookup("SUPPLIER-77")
        self.assertTrue(data["exact"])
        self.assertEqual(data["items"][0]["variant"], variant.pk)

    def test_part_number_is_an_exact_hit_and_text_lists_matches(self):
        from automotive.models import ProductPartNumber

        ProductPartNumber.objects.create(product=self.filter, kind="oem", number="90915-YZZE1")
        self.assertTrue(self.lookup("90915yzze1")["exact"])
        Product.objects.create(name="Oil Filter Wrench")
        data = self.lookup("oil filter")
        self.assertFalse(data["exact"])
        self.assertEqual(len(data["items"]), 2)


class PosPopularTests(PosTestCase):
    def popular(self):
        with pos_on():
            return self.client.get(reverse("sales:pos_lookup"), {"popular": "1"}).json()["items"]

    def test_best_sellers_lead_and_new_items_fill_the_rest(self):
        grease = Product.objects.create(name="Grease", price_lyd_override=Decimal("5.00"), track_stock=True)
        self.stock_in(grease, 10)
        Product.objects.create(name="Newest Hose", track_stock=False)
        self.assertEqual(self.popular()[0]["name"], "Newest Hose")
        self.checkout(self.sale(lines=[{"product": grease.pk, "qty": 3}], payments=[
            {"method": "cash", "amount": "15"},
        ]))
        names = [item["name"] for item in self.popular()]
        self.assertEqual(names[0], "Grease")
        self.assertEqual(sorted(names), ["Grease", "Newest Hose", "Oil Filter"])

    def test_out_of_stock_items_stay_off_the_grid(self):
        Product.objects.create(name="Turbo", track_stock=True)
        self.assertNotIn("Turbo", [item["name"] for item in self.popular()])
        self.assertIn("Turbo", [item["name"] for item in self.lookup("turbo")["items"]])


class PosCheckoutTests(PosTestCase):
    def test_sale_issues_and_pays_one_invoice_with_change(self):
        response = self.checkout(self.sale(payments=[
            {"method": "card", "amount": "40"}, {"method": "cash", "amount": "100"},
        ]))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data["total"], data["change"]), ("100.00", "40.00"))
        invoice = Invoice.objects.get(pk=data["invoice"])
        self.assertEqual(invoice.status, Invoice.STATUS_PAID)
        self.assertEqual(
            sorted(invoice.payments.values_list("method", "amount")),
            [("card", Decimal("40.00")), ("cash", Decimal("60.00"))],
        )
        self.filter.refresh_from_db()
        self.assertEqual(self.filter.stock_qty, Decimal("3.00"))

    def test_retrying_the_same_key_never_sells_twice(self):
        first = self.checkout(self.sale()).json()
        second = self.checkout(self.sale()).json()
        self.assertEqual(first["invoice"], second["invoice"])
        self.assertEqual(PosSale.objects.count(), 1)
        self.filter.refresh_from_db()
        self.assertEqual(self.filter.stock_qty, Decimal("3.00"))

    def test_underpaid_and_oversized_card_payments_are_refused(self):
        self.assertEqual(self.checkout(self.sale(payments=[{"method": "cash", "amount": "50"}])).status_code, 400)
        over = self.checkout(self.sale(payments=[{"method": "card", "amount": "150"}]))
        self.assertEqual(over.status_code, 400)
        self.assertFalse(PosSale.objects.exists())

    def test_disabled_method_is_refused(self):
        response = self.checkout(
            self.sale(payments=[{"method": "card", "amount": "100"}]),
            methods={"cash": True, "card": False, "bank_transfer": True},
        )
        self.assertEqual(response.status_code, 400)

    def test_stock_shortage_rolls_the_whole_sale_back(self):
        response = self.checkout(self.sale(lines=[{"product": self.filter.pk, "qty": 9}], payments=[
            {"method": "cash", "amount": "450"},
        ]))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(PosSale.objects.exists())

    def test_discount_cap_limits_sellers_but_not_unlimited_users(self):
        seller = User.objects.create_user("seller", password="x")
        seller.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="sales",
            codename__in=["use_pos", "add_invoice", "issue_invoice", "add_payment"],
        ))
        from django.test import Client

        client = Client()
        client.force_login(seller)
        # A lowered line price counts toward the discount just like a sale discount.
        over = self.sale(lines=[{"product": self.filter.pk, "qty": 2, "price": "40"}], payments=[
            {"method": "cash", "amount": "80"},
        ])
        self.assertEqual(self.checkout(over, client=client, max_discount_percent="10").status_code, 400)
        within = self.sale(key="sale-2", discount="10", payments=[{"method": "cash", "amount": "90"}])
        self.assertEqual(self.checkout(within, client=client, max_discount_percent="10").status_code, 200)
        self.assertEqual(self.checkout({**over, "key": "sale-3"}, max_discount_percent="10").status_code, 200)


class ExtraBarcodeFormTests(PosTestCase):
    def modal(self, pk="new"):
        return reverse("scoped_modal_manager", args=["catalog", "product", pk])

    def payload(self, **extra):
        data = {
            "name": "Air Filter", "unit": Product.UNIT_PIECE, "cost_usd": "1", "markup_percent": "0",
            "price_usd": "1", "reorder_level": "0", "track_stock": "on", "is_active": "on",
        }
        data.update(extra)
        return data

    def test_extra_barcodes_save_and_clash_with_other_items(self):
        response = self.client.post(self.modal(), self.payload(extra_barcodes="111, 222"))
        self.assertTrue(response.json()["success"])
        product = Product.objects.get(name="Air Filter")
        self.assertEqual(sorted(product.extra_barcodes.values_list("code", flat=True)), ["111", "222"])
        clash = self.client.post(self.modal(), self.payload(name="Other", extra_barcodes="6290000000011"))
        self.assertFalse(clash.json()["success"])

    def test_scanned_code_prefills_a_new_item(self):
        html = self.client.get(self.modal(), {"barcode": "4006381333931"}).json()["html"]
        self.assertIn('value="4006381333931"', html)
