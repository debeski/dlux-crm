"""The stock ledger is append-only: movements are compensated, never removed."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import RequestFactory, TestCase

from catalog.models import Category, Product, StockMovement
from catalog.tables import StockMovementTable

User = get_user_model()
rf = RequestFactory()


class StockLedgerAppendOnlyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("ledger", "l@e.d", "x")
        category = Category.objects.create(name="Locks")
        self.product = Product.objects.create(
            name="Lock X1", category=category, track_stock=True,
        )
        self.movement = StockMovement.objects.create(
            product=self.product,
            movement_type=StockMovement.TYPE_IN,
            quantity=Decimal("10"),
        )

    def test_the_movement_moved_the_stock(self):
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, Decimal("10"))

    def test_deleting_a_movement_is_refused(self):
        with self.assertRaises(IntegrityError):
            self.movement.delete()

    def test_a_refused_delete_leaves_the_ledger_and_the_balance_intact(self):
        with self.assertRaises(IntegrityError):
            self.movement.delete()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, Decimal("10"))
        self.assertTrue(StockMovement.objects.filter(pk=self.movement.pk).exists())

    def test_the_row_menu_offers_no_delete(self):
        table = StockMovementTable([])
        request = rf.get("/")
        request.user = self.user
        table.request = request
        base = [{"label": "Delete", "event": "dlux:record:delete"}]
        actions = table.get_dlux_row_actions(self.movement, base)
        self.assertNotIn("dlux:record:delete", [a.get("event") for a in actions])

    def test_a_compensating_movement_is_how_stock_comes_back(self):
        StockMovement.objects.create(
            product=self.product,
            movement_type=StockMovement.TYPE_OUT,
            quantity=Decimal("4"),
            reason="Correction",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, Decimal("6"))
        # Both rows stand: the ledger is the history, not just the balance.
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_no_seeded_role_can_delete_a_movement(self):
        from pathlib import Path

        seed = Path("sales/management/commands/seed_roles.py").read_text()
        self.assertNotIn("catalog.delete_stockmovement", seed)
