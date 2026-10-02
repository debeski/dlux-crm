import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, skipUnlessDBFeature

from sales.models import Customer, CustomerCreditUse, Invoice, Payment, PaymentResolution
from sales.services import apply_customer_credit, cancel_invoice


@skipUnlessDBFeature("has_select_for_update")
class CreditConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name="Concurrent customer")
        self.source = Invoice.objects.create(customer=self.customer, status="issued", total_lyd=100)
        Payment.objects.create(invoice=self.source, amount=30)

    def concurrently(self, tasks):
        barrier = Barrier(2)

        def run(task):
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                task()
                return "ok"
            except ValidationError:
                return "rejected"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, tasks))

    def test_simultaneous_refund_requests_resolve_receipt_once(self):
        def refund():
            cancel_invoice(self.source, None, payment_action="refund", refund_method="cash")

        self.assertEqual(self.concurrently([refund, refund]), ["ok", "ok"])
        self.assertEqual(PaymentResolution.objects.count(), 1)

    def test_competing_credit_payments_cannot_overdraw(self):
        cancel_invoice(self.source, None, payment_action="credit")
        credit = PaymentResolution.objects.get()
        first = Invoice.objects.create(customer=self.customer, status="issued", total_lyd=100)
        second = Invoice.objects.create(customer=self.customer, status="issued", total_lyd=100)
        results = self.concurrently([
            lambda: apply_customer_credit(first, credit, Decimal("20"), uuid.uuid4(), None),
            lambda: apply_customer_credit(second, credit, Decimal("20"), uuid.uuid4(), None),
        ])
        self.assertEqual(sorted(results), ["ok", "rejected"])
        self.assertEqual(CustomerCreditUse.objects.count(), 1)
        self.assertEqual(credit.available_amount, Decimal("10"))

    def test_duplicate_credit_request_is_applied_once(self):
        cancel_invoice(self.source, None, payment_action="credit")
        credit = PaymentResolution.objects.get()
        target = Invoice.objects.create(customer=self.customer, status="issued", total_lyd=100)
        key = uuid.uuid4()

        def apply():
            apply_customer_credit(target, credit, Decimal("20"), key, None)

        self.assertEqual(self.concurrently([apply, apply]), ["ok", "ok"])
        self.assertEqual(CustomerCreditUse.objects.count(), 1)
        target.refresh_from_db()
        self.assertEqual(target.amount_paid, Decimal("20"))
