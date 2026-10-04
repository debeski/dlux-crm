from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, local
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from catalog.models import Product, ProductVariant, PurchaseInvoice, StockMovement
from catalog.tests import test_product_currencies as currency_helpers
from finance.models import ExchangeRate
from sales.models import Customer, Invoice, InvoiceItem, Payment, PaymentResolution
from sales.reports import build_financial_report
from sales.services import apply_customer_credit, cancel_invoice, issue_invoice
from sales.views import _apply_item_price


class CounterDayWorkflowTests(TestCase):
    setUp = currency_helpers.ProductCurrencyTests.setUp
    _row = currency_helpers.ProductCurrencyTests._row
    _post_data = currency_helpers.ProductCurrencyTests._post_data
    _post = currency_helpers.ProductCurrencyTests._post
    _post_purchase = currency_helpers.ProductCurrencyTests._post_purchase

    def sale(self, customer, products, discount=0):
        invoice = Invoice.objects.create(customer=customer, currency="USD", exchange_rate=7, discount_percent=discount)
        for product, quantity in products:
            item = InvoiceItem(invoice=invoice, product=product, quantity=quantity)
            _apply_item_price(item, invoice)
            item.save()
        invoice.recalc_totals()
        return issue_invoice(invoice, self.user)

    def test_purchase_sale_credit_reuse_rate_change_and_report_reconcile(self):
        for name, currency, cost, price, qty in [("Day EUR pump", "EUR", "20", "30", "6"), ("Day USD filter", "USD", "10", "15", "3")]:
            response = self._post_purchase([self._row(name=name, currency=currency, cost_usd=cost, price_usd=price, quantity=qty)], currency=currency)
            self.assertEqual(response.status_code, 302)
        pump = Product.objects.get(name="Day EUR pump")
        filter_part = Product.objects.get(name="Day USD filter")
        self.assertEqual(PurchaseInvoice.objects.get(currency="EUR").total_lyd, Decimal("960"))
        customer = Customer.objects.create(name="Day buyer")
        first = self.sale(customer, [(pump, 2)], discount=10)
        self.assertEqual(first.total_lyd, Decimal("432"))
        Payment.objects.create(invoice=first, amount=100)
        cancel_invoice(first, self.user, payment_action="credit")
        pump.refresh_from_db()
        self.assertEqual(pump.stock_qty, Decimal("6"))
        credit = PaymentResolution.objects.get(payment__invoice=first)
        second = self.sale(customer, [(pump, 1), (filter_part, 1)])
        self.assertEqual(second.total_lyd, Decimal("345"))
        apply_customer_credit(second, credit, Decimal("100"), uuid4(), self.user)
        Payment.objects.create(invoice=second, amount=245)
        second.refresh_from_db()
        self.assertEqual((second.status, second.balance_due, customer.credit_balance), ("paid", Decimal("0"), Decimal("0")))
        ExchangeRate.objects.create(currency="EUR", rate=10)
        report = build_financial_report(timezone.localdate(), timezone.localdate())
        self.assertEqual(report["revenue"], Decimal("345"))
        self.assertEqual(report["cogs"], Decimal("230"))
        self.assertEqual(report["cash_collected"], Decimal("345"))
        pump.refresh_from_db()
        filter_part.refresh_from_db()
        self.assertEqual((pump.stock_qty, filter_part.stock_qty), (Decimal("5"), Decimal("2")))


    def test_variant_and_unassigned_lines_share_the_product_stock_limit(self):
        product = Product.objects.create(name="Shared stock", cost_usd=10, price_usd=15)
        variant = ProductVariant.objects.create(product=product, color=Product.COLOR_BLUE)
        StockMovement.objects.create(product=product, variant=variant, movement_type="in", quantity=1)
        invoice = Invoice.objects.create(exchange_rate=7)
        for selected_variant in (variant, None):
            InvoiceItem.objects.create(invoice=invoice, product=product, variant=selected_variant, quantity=1, unit_price_lyd=105)
        with self.assertRaises(ValidationError):
            issue_invoice(invoice, self.user)
        product.refresh_from_db()
        self.assertEqual(product.stock_qty, Decimal("1"))
        self.assertFalse(StockMovement.objects.filter(product=product, movement_type="out").exists())


@skipUnlessDBFeature("has_select_for_update")
class LastItemConcurrencyTests(TransactionTestCase):
    def test_two_invoices_cannot_sell_the_last_unit(self):
        import sales.services as services
        product = Product.objects.create(name="Last unit", cost_usd=10, price_usd=15)
        StockMovement.objects.create(product=product, movement_type="in", quantity=1)
        invoices = []
        for _ in range(2):
            invoice = Invoice.objects.create(exchange_rate=7)
            InvoiceItem.objects.create(invoice=invoice, product=product, quantity=1, unit_price_lyd=105)
            invoices.append(invoice)
        barrier = Barrier(2)
        state = local()
        original = services._item_variant

        def rendezvous(item):
            if not getattr(state, "checked", False):
                state.checked = True
                barrier.wait(timeout=10)
            return original(item)

        def sell(invoice):
            close_old_connections()
            try:
                issue_invoice(invoice, None)
                return "sold"
            except ValidationError:
                return "rejected"
            finally:
                connection.close()

        with patch("sales.services._item_variant", side_effect=rendezvous), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(sell, invoices))
        self.assertEqual(sorted(results), ["rejected", "sold"])
        product.refresh_from_db()
        self.assertEqual(product.stock_qty, Decimal("0"))
        self.assertEqual(StockMovement.objects.filter(movement_type="out").count(), 1)
