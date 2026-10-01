"""
Opening stock — the one-time bulk intake. It's a **child of the stock ledger**
(no model of its own): submitting the grid creates/reuses products and posts
Stock In movements. Covers new-item creation, existing-item stock-add + reprice,
blank-row dropping, and zero-qty reprice-without-movement.
"""
import json
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from catalog.models import Category, Product, ProductVariant, StockMovement
from catalog.views import OpeningStockEditorView

User = get_user_model()
rf = RequestFactory()


def _perm(code):
    app_label, codename = code.split(".", 1)
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


class OpeningStockViewTests(TestCase):
    def setUp(self):
        self.mgr = User.objects.create_user("mgr", password="x")
        for c in ("catalog.add_product", "catalog.change_product", "catalog.add_stockmovement"):
            self.mgr.user_permissions.add(_perm(c))
        self.mgr = User.objects.get(pk=self.mgr.pk)

    def _post(self, rows):
        data = {
            "form-TOTAL_FORMS": str(len(rows)), "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
        }
        for i, r in enumerate(rows):
            for k, v in r.items():
                data[f"form-{i}-{k}"] = v
        req = rf.post("/catalog/stock-movements/opening-stock/", data)
        req.user = self.mgr
        req.session = {}
        req._messages = FallbackStorage(req)
        return OpeningStockEditorView.as_view()(req)

    def _get(self):
        req = rf.get("/catalog/stock-movements/opening-stock/")
        req.user = self.mgr
        req.session = {}
        req._messages = FallbackStorage(req)
        return OpeningStockEditorView.as_view()(req)

    def _row(self, **over):
        base = {
            "product": "", "name": "", "unit": "piece", "barcode": "",
            "color": "", "size": "",
            "cost_usd": "0.00", "markup_percent": "0.00", "price_usd": "0.00",
            "price_lyd_override": "", "quantity": "0.00",
        }
        base.update(over)
        return base

    def test_new_item_created_and_stock_posted(self):
        resp = self._post([self._row(name="Smart Lock", cost_usd="40.00", markup_percent="25.00", price_usd="50.00", quantity="12")])
        self.assertEqual(resp.status_code, 302)
        p = Product.objects.get(name="Smart Lock")
        self.assertEqual(p.stock_qty, Decimal("12.00"))
        self.assertEqual(p.cost_usd, Decimal("40.00"))
        self.assertTrue(p.track_stock)
        mv = StockMovement.objects.get(product=p)
        self.assertEqual(mv.movement_type, StockMovement.TYPE_IN)
        self.assertEqual(mv.quantity, Decimal("12.00"))
        self.assertEqual(mv.reference, "OPENING")

    def test_existing_item_opening_stock_keeps_distinct_color_variants(self):
        existing = Product.objects.create(name="Spare Key", cost_usd=Decimal("4.00"), price_usd=Decimal("6.00"))
        resp = self._post([
            self._row(product=str(existing.pk), name="Spare Key", color=Product.COLOR_ORANGE, size="13.56 MHz", quantity="2"),
            self._row(product=str(existing.pk), name="Spare Key", color=Product.COLOR_BLUE, size="13.56 MHz", quantity="3"),
        ])
        self.assertEqual(resp.status_code, 302)
        existing.refresh_from_db()
        self.assertEqual(existing.stock_qty, Decimal("5.00"))
        self.assertEqual(
            set(ProductVariant.objects.filter(product=existing).values_list("color", "stock_qty")),
            {(Product.COLOR_ORANGE, Decimal("2.00")), (Product.COLOR_BLUE, Decimal("3.00"))},
        )

    def test_existing_item_gets_stock_and_reprice(self):
        existing = Product.objects.create(name="Existing", cost_usd=Decimal("10.00"), price_usd=Decimal("12.00"))
        Product.objects.filter(pk=existing.pk).update(stock_qty=Decimal("3.00"))
        self._post([self._row(product=str(existing.pk), name="Existing", cost_usd="15.00", price_usd="20.00", quantity="7")])
        existing.refresh_from_db()
        self.assertEqual(existing.stock_qty, Decimal("10.00"))   # 3 + 7 added
        self.assertEqual(existing.cost_usd, Decimal("15.00"))    # price corrected
        self.assertEqual(existing.price_usd, Decimal("20.00"))
        self.assertEqual(Product.objects.filter(name="Existing").count(), 1)  # no duplicate

    def test_blank_row_dropped_and_zero_qty_makes_no_movement(self):
        resp = self._post([
            self._row(name="Repriced", cost_usd="9.00"),  # qty 0 → created, no movement
            self._row(),                                   # fully blank → dropped
        ])
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Product.objects.count(), 1)
        p = Product.objects.get(name="Repriced")
        self.assertEqual(p.cost_usd, Decimal("9.00"))
        self.assertEqual(p.stock_qty, Decimal("0.00"))
        self.assertFalse(StockMovement.objects.filter(product=p).exists())

    def test_deleted_row_is_skipped(self):
        self._post([self._row(name="Gone", quantity="5", DELETE="on")])
        self.assertFalse(Product.objects.filter(name="Gone").exists())

    def test_opening_stock_page_loads_row_scoped_price_sync(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        self.assertRegex(html, r"catalog/js/price_sync\.js\?v=[0-9a-f]{12}")
        self.assertIn('data-price-sync-row', html)
        self.assertIn('data-price-cost="1"', html)
        self.assertIn('data-price-lyd="1"', html)

    def test_existing_product_selection_payload_includes_all_autofill_fields(self):
        cat = Category.objects.create(name="Locks")
        existing = Product.objects.create(
            name="Existing Box",
            category=cat,
            unit=Product.UNIT_BOX,
            barcode="6290000000012",
            color=Product.COLOR_BLACK,
            size="Small / 12x8x3 cm",
            cost_usd=Decimal("42.00"),
            markup_percent=Decimal("30.00"),
            price_usd=Decimal("54.60"),
            price_lyd_override=Decimal("410.00"),
        )

        resp = self._get()
        html = resp.content.decode()
        match = re.search(r'<script id="product-map" type="application/json">(.*?)</script>', html)
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        row = payload[str(existing.pk)]

        self.assertEqual(row["cost"], 42.0)
        self.assertEqual(row["markup"], 30.0)
        self.assertEqual(row["price_usd"], 54.6)
        self.assertEqual(row["price_lyd"], 410.0)
        self.assertEqual(row["barcode"], "6290000000012")
        self.assertEqual(row["category"], str(cat.pk))
        self.assertEqual(row["unit"], Product.UNIT_BOX)
        self.assertEqual(row["color"], Product.COLOR_BLACK)
        self.assertEqual(row["size"], "Small / 12x8x3 cm")
        self.assertIn("dataset.userEdited", html)
