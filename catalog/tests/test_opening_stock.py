"""Opening-stock drafts, explicit finalization, inventory effects and concurrent writes."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

import json
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from catalog.models import Category, OpeningStockDraft, Product, ProductVariant, StockMovement
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

    def _post(self, rows, action="finalize", revision=0):
        data = {
            "form-TOTAL_FORMS": str(len(rows)), "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
            "action": action, "revision": str(revision),
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
        self.assertRegex(html, r"catalog/js/opening_stock\.js\?v=[0-9a-f]{12}")

    def test_save_draft_preserves_partial_rows_without_writing_inventory(self):
        existing = Product.objects.create(name="Unchanged", cost_usd=10, price_usd=15)
        response = self._post([
            self._row(name="Half entered", quantity=""),
            self._row(product=existing.pk, name=existing.name, cost_usd="20", quantity="8"),
            self._row(name="Removed", quantity="2", DELETE="on"),
        ], action="save_draft")
        self.assertEqual(response.status_code, 302)
        draft = OpeningStockDraft.objects.get()
        self.assertEqual(draft.revision, 1)
        self.assertEqual([row["name"] for row in draft.rows], ["Half entered", "Unchanged"])
        self.assertIsNone(draft.finalized_at)
        self.assertFalse(StockMovement.objects.exists())
        existing.refresh_from_db()
        self.assertEqual(existing.cost_usd, Decimal("10"))
        self.assertEqual(Product.objects.count(), 1)
        response = self._get()
        self.assertContains(response, 'value="Half entered"')
        self.assertContains(response, 'name="revision" value="1"')
        self.assertContains(response, 'value="8"')

    def test_partial_pricing_and_large_drafts_survive_save_and_resume(self):
        rows = [self._row(name=f"Row {index}", quantity="1") for index in range(100)]
        rows[0] = self._row(cost_usd="12", markup_percent="25", name="")
        response = self._post(rows, action="save_draft")
        self.assertEqual(response.status_code, 302)
        draft = OpeningStockDraft.objects.get()
        self.assertEqual(len(draft.rows), 100)
        self.assertEqual(draft.rows[0]["cost_usd"], "12")
        response = self._get()
        self.assertContains(response, 'data-preserve-values="true"', count=100)
        self.assertFalse(Product.objects.exists())

    def test_resume_update_and_finalize_draft_once(self):
        self._post([self._row(name="Original", quantity="2")], action="save_draft")
        self._post([self._row(name="Original", quantity="3"), self._row(name="More", quantity="4")], action="save_draft", revision=1)
        self.assertFalse(Product.objects.exists())
        response = self._post([self._row(name="Original", quantity="3"), self._row(name="More", quantity="4")], revision=2)
        self.assertEqual(response.status_code, 302)
        draft = OpeningStockDraft.objects.get()
        self.assertIsNotNone(draft.finalized_at)
        self.assertEqual(draft.rows, [])
        self.assertEqual(StockMovement.objects.count(), 2)
        self._post([self._row(name="Duplicate", quantity="3")], revision=2)
        self.assertFalse(Product.objects.filter(name="Duplicate").exists())
        self.assertEqual(StockMovement.objects.count(), 2)
        self.assertEqual(self._get().status_code, 302)

    def test_stale_save_and_finalize_keep_newer_draft(self):
        self._post([self._row(name="Newer", quantity="2")], action="save_draft")
        for action in ("save_draft", "finalize"):
            response = self._post([self._row(name="Old tab", quantity="6")], action=action)
            self.assertEqual(response.status_code, 409)
            self.assertContains(response, 'value="Old tab"', status_code=409)
            self.assertEqual(OpeningStockDraft.objects.get().rows[0]["name"], "Newer")
            self.assertFalse(Product.objects.exists())

    def test_incomplete_row_can_be_saved_but_not_silently_finalized(self):
        rows = [self._row(name="Ready", quantity="2"), self._row(quantity="5")]
        self.assertEqual(self._post(rows, action="save_draft").status_code, 302)
        response = self._post(rows, revision=1)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.exists())
        self.assertIsNone(OpeningStockDraft.objects.get().finalized_at)
        self.assertContains(response, "Enter an item name")

    def test_zero_quantity_finalization_is_still_one_time(self):
        self._post([self._row(name="No quantity", cost_usd="9")])
        self.assertFalse(StockMovement.objects.exists())
        self.assertIsNotNone(OpeningStockDraft.objects.get().finalized_at)
        self.assertEqual(self._get().status_code, 302)
        self._post([self._row(name="Second opening", quantity="8")])
        self.assertFalse(Product.objects.filter(name="Second opening").exists())

    def test_failed_finalization_rolls_back_inventory_and_keeps_saved_draft(self):
        from unittest.mock import patch
        rows = [self._row(name="Kept", quantity="3")]
        self._post(rows, action="save_draft")
        original = OpeningStockEditorView._apply_line
        def fail_after_write(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("simulated stock failure")
        with patch.object(OpeningStockEditorView, "_apply_line", side_effect=fail_after_write):
            with self.assertRaises(RuntimeError):
                self._post(rows, revision=1)
        self.assertFalse(Product.objects.exists())
        draft = OpeningStockDraft.objects.get()
        self.assertEqual(draft.rows[0]["name"], "Kept")
        self.assertEqual(draft.revision, 1)
        self.assertIsNone(draft.finalized_at)

    def test_combined_grid_rejects_duplicates_and_conflicting_variant_prices(self):
        for second in (self._row(name="Same", quantity="4"), self._row(name="Same", color="blue", quantity="4", price_usd="20")):
            response = self._post([self._row(name="Same", quantity="2"), second])
            self.assertEqual(response.status_code, 200)
            self.assertFalse(Product.objects.exists())

    def test_draft_and_finalize_require_all_intake_permissions(self):
        from django.core.exceptions import PermissionDenied
        self.mgr.user_permissions.remove(_perm("catalog.change_product"))
        self.mgr = User.objects.get(pk=self.mgr.pk)
        for action in ("save_draft", "finalize"):
            with self.assertRaises(PermissionDenied):
                self._post([self._row(name="Denied", quantity="1")], action=action)
        self.assertFalse(OpeningStockDraft.objects.exists())

    def test_drafts_are_separate_per_scope_and_foreign_products_rejected(self):
        from unittest.mock import patch
        from dlux.models import Scope
        left = Scope.objects.create(name="Left store")
        right = Scope.objects.create(name="Right store")
        self.mgr.scope = left
        foreign = Product.objects.create(name="Foreign", scope=right)
        with patch("dlux.utils.is_scope_enabled", return_value=True), patch("catalog.opening_stock.is_scope_enabled", return_value=True):
            self._post([self._row(name="Left draft", quantity="2")], action="save_draft")
            self.mgr.scope = right
            self.assertNotContains(self._get(), 'value="Left draft"')
            self._post([self._row(name="Right draft", quantity="3")], action="save_draft")
            self.assertEqual(OpeningStockDraft.objects.count(), 2)
            self.mgr.scope = left
            response = self._post([self._row(product=foreign.pk, name="Foreign", quantity="2")], revision=1)
            self.assertEqual(response.status_code, 200)
            foreign.refresh_from_db()
            self.assertEqual(foreign.stock_qty, 0)
            self.assertFalse(StockMovement.objects.exists())


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class OpeningStockConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("opening-concurrency", "qa@example.invalid", "x")
        OpeningStockDraft.objects.create()

    def concurrent_posts(self, action):
        from catalog.opening_stock import locked_draft
        barrier = Barrier(2)
        def lock_together(user):
            barrier.wait(timeout=15)
            return locked_draft(user)
        def submit(index):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                data = {"action": action, "revision": 0, "form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 0,
                        "form-0-name": f"Concurrent item {index}", "form-0-unit": "piece", "form-0-quantity": "2"}
                req = rf.post("/", data)
                req.user, req.session = user, {}
                req._messages = FallbackStorage(req)
                return OpeningStockEditorView.as_view()(req).status_code
            finally:
                connection.close()
        with patch("catalog.views.locked_draft", side_effect=lock_together):
            with ThreadPoolExecutor(max_workers=2) as workers:
                return sorted(workers.map(submit, (1, 2)))

    def test_simultaneous_finalizations_post_only_once(self):
        self.assertEqual(self.concurrent_posts("finalize"), [302, 302])
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertIsNotNone(OpeningStockDraft.objects.get().finalized_at)

    def test_simultaneous_saves_preserve_the_winning_revision(self):
        self.assertEqual(self.concurrent_posts("save_draft"), [302, 409])
        self.assertFalse(Product.objects.exists())
        draft = OpeningStockDraft.objects.get()
        self.assertEqual(draft.revision, 1)
        self.assertEqual(len(draft.rows), 1)
