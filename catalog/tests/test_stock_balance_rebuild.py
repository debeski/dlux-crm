"""A data reset must not leave stock standing on products whose ledger is gone.

The reported symptom: the admin reset everything except the assets, the invoices
disappeared, and the products still claimed the quantities those invoices had put
on them. ``Product.stock_qty`` is a running total applied by
``StockMovement.save()``, and a reset writes in bulk — no ``save()``, no delta,
so the number stayed behind.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from dlux.admin_actions.data_reset import RESET_MODE_PERMANENT, execute_reset
from dlux.middleware import _thread_locals

from catalog.models import Category, Product, ProductVariant, StockMovement
from catalog.stock_balance import rebuild_stock_balances

User = get_user_model()


class StockBalanceRebuildTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("root", "r@x.com", "pw12345!")
        _thread_locals.user = self.su
        self.category = Category.objects.create(name="Tools")
        self.product = Product.objects.create(
            name="Widget", category=self.category, track_stock=True,
            cost_usd=Decimal("1.00"), price_usd=Decimal("2.00"),
        )

    def tearDown(self):
        _thread_locals.user = None

    def _move(self, kind, qty, variant=None):
        return StockMovement.objects.create(
            product=self.product, variant=variant, movement_type=kind, quantity=Decimal(qty),
        )

    def _stock(self):
        self.product.refresh_from_db()
        return self.product.stock_qty

    def test_soft_reset_of_the_ledger_zeroes_the_balance(self):
        self._move(StockMovement.TYPE_IN, "10")
        self._move(StockMovement.TYPE_OUT, "4")
        self.assertEqual(self._stock(), Decimal("6.00"))

        execute_reset(self.su, ["catalog.stockmovement"])

        # The rows are recoverable, but nothing live backs the balance any more.
        self.assertEqual(self._stock(), Decimal("0.00"))
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(StockMovement.all_objects.count(), 2)

    def test_permanent_reset_zeroes_the_balance_and_empties_the_bin(self):
        self._move(StockMovement.TYPE_IN, "5")
        execute_reset(self.su, ["catalog.stockmovement"])          # bin gets 1 row
        self._move(StockMovement.TYPE_IN, "7")
        self.assertEqual(self._stock(), Decimal("7.00"))

        execute_reset(self.su, ["catalog.stockmovement"], mode=RESET_MODE_PERMANENT)

        self.assertEqual(self._stock(), Decimal("0.00"))
        self.assertEqual(StockMovement.all_objects.count(), 0)

    def test_a_reset_that_misses_the_ledger_leaves_the_balance_alone(self):
        self._move(StockMovement.TYPE_IN, "3")
        execute_reset(self.su, ["dlux.activitylog"])
        self.assertEqual(self._stock(), Decimal("3.00"))

    def test_rebuild_restores_a_balance_that_drifted(self):
        self._move(StockMovement.TYPE_IN, "8")
        self._move(StockMovement.TYPE_ADJUST, "-3")
        Product.all_objects.filter(pk=self.product.pk).update(stock_qty=Decimal("999.00"))

        products, _variants = rebuild_stock_balances()

        self.assertEqual(products, 1)
        self.assertEqual(self._stock(), Decimal("5.00"))

    def test_variant_balances_are_rebuilt_too(self):
        variant = ProductVariant.objects.create(product=self.product, color="Red")
        self._move(StockMovement.TYPE_IN, "6", variant=variant)
        self._move(StockMovement.TYPE_OUT, "2", variant=variant)
        variant.refresh_from_db()
        self.assertEqual(variant.stock_qty, Decimal("4.00"))

        execute_reset(self.su, ["catalog.stockmovement"])

        variant.refresh_from_db()
        self.assertEqual(variant.stock_qty, Decimal("0.00"))
        self.assertEqual(self._stock(), Decimal("0.00"))

    def test_untracked_products_are_left_alone(self):
        untracked = Product.objects.create(
            name="Service item", category=self.category, track_stock=False,
            cost_usd=Decimal("1.00"), price_usd=Decimal("2.00"), stock_qty=Decimal("42.00"),
        )
        rebuild_stock_balances()
        untracked.refresh_from_db()
        self.assertEqual(untracked.stock_qty, Decimal("42.00"))
