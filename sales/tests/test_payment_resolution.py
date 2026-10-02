import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.http import Http404
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Product, StockMovement
from sales.models import Customer, CustomerCreditUse, Invoice, InvoiceItem, Payment, PaymentResolution
from sales.payment_resolution_views import CustomerCreditUseView, InvoiceCancellationView, visible_credits
from sales.reports import build_financial_report, build_sales_report
from sales.services import apply_customer_credit, cancel_invoice, issue_invoice


class PaymentResolutionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("moneyadmin", "money@example.com", "x")
        self.customer = Customer.objects.create(name="Buyer", created_by=self.user)
        self.factory = RequestFactory()

    def invoice(self, customer=True, total="100", paid="30"):
        invoice = Invoice.objects.create(customer=self.customer if customer else None, status="issued", total_lyd=Decimal(total), salesperson=self.user)
        if Decimal(paid):
            Payment.objects.create(invoice=invoice, amount=Decimal(paid), created_by=self.user)
        invoice.refresh_from_db()
        return invoice

    def credit(self, paid="30"):
        source = self.invoice(paid=paid)
        cancel_invoice(source, self.user, payment_action="credit")
        return PaymentResolution.objects.get(payment__invoice=source)

    def apply(self, invoice, credit, amount, key=None):
        return apply_customer_credit(invoice, credit, Decimal(amount), key or uuid.uuid4(), self.user)

    def request(self, view, invoice, data=None, user=None):
        url = reverse("sales:invoice_cancel" if view == InvoiceCancellationView else "sales:credit_apply", args=[invoice.pk])
        request = self.factory.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest") if data is None else self.factory.post(url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = user or self.user
        return view.as_view()(request, pk=invoice.pk)

    def test_refund_each_receipt_once_and_preserve_deposit(self):
        from finance.models import CashDeposit
        invoice = self.invoice()
        deposit = CashDeposit.objects.create(reference="Cash batch", amount=0)
        Payment.objects.create(invoice=invoice, amount=20, deposit=deposit)
        cancel_invoice(invoice, self.user, payment_action="refund", refund_method="bank_transfer", notes="Returned")
        cancel_invoice(invoice, self.user, payment_action="refund", refund_method="bank_transfer")
        self.assertEqual(PaymentResolution.objects.count(), 2)
        self.assertEqual(sum(r.amount for r in PaymentResolution.objects.all()), Decimal("50"))
        self.assertEqual(invoice.payments.count(), 2)
        deposit.refresh_from_db()
        self.assertEqual(deposit.amount, Decimal("20"))
        entry = PaymentResolution.objects.first()
        self.assertEqual(entry.method, "bank_transfer")
        self.assertEqual(entry.notes, "Returned")
        invoice.refresh_from_db()
        self.assertEqual(invoice.balance_due, Decimal("0"))

    def test_walkin_refund_and_reject_walkin_credit_atomically(self):
        invoice = self.invoice(customer=False)
        with self.assertRaises(ValidationError):
            cancel_invoice(invoice, self.user, payment_action="credit")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "partial")
        self.assertFalse(PaymentResolution.objects.exists())
        cancel_invoice(invoice, self.user, payment_action="refund", refund_method="cash")
        self.assertEqual(PaymentResolution.objects.get().action, "refund")

    def test_later_can_be_resolved_on_previously_cancelled_invoice(self):
        invoice = self.invoice()
        cancel_invoice(invoice, self.user)
        invoice.refresh_from_db()
        self.assertEqual(invoice.cancellation_pending, Decimal("30"))
        cancel_invoice(invoice, self.user, payment_action="credit")
        self.assertEqual(invoice.cancellation_pending, Decimal("0"))
        self.assertEqual(self.customer.credit_balance, Decimal("30"))

    def test_unpaid_cancellation_creates_no_settlement(self):
        invoice = self.invoice(paid="0")
        cancel_invoice(invoice, self.user, payment_action="refund", refund_method="cash")
        self.assertFalse(PaymentResolution.objects.exists())

    def test_credit_use_pays_invoice_without_recording_cash(self):
        credit = self.credit(paid="100")
        target = self.invoice(paid="0")
        key = uuid.uuid4()
        first = self.apply(target, credit, "100", key)
        self.assertEqual(self.apply(target, credit, "100", key).pk, first.pk)
        target.refresh_from_db()
        self.assertEqual(target.status, "paid")
        self.assertEqual(target.amount_paid, Decimal("100"))
        self.assertFalse(target.payments.exists())
        self.assertEqual(self.customer.credit_balance, Decimal("0"))
        self.assertEqual(CustomerCreditUse.objects.count(), 1)
        report = build_sales_report(timezone.localdate(), timezone.localdate())
        self.assertEqual(report["outstanding"], Decimal("0"))
        self.assertEqual(report["total_sales"], Decimal("100"))

    def test_partial_credit_and_limits(self):
        credit = self.credit()
        target = self.invoice(paid="0")
        self.apply(target, credit, "20")
        target.refresh_from_db()
        self.assertEqual(target.status, "partial")
        self.assertEqual(target.balance_due, Decimal("80"))
        self.assertEqual(credit.available_amount, Decimal("10"))
        for amount in ("11", "0", "-1", "1.001"):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.apply(target, credit, amount)
        self.assertEqual(CustomerCreditUse.objects.count(), 1)

    def test_credit_cannot_exceed_invoice_balance_or_change_replay(self):
        credit = self.credit()
        target = self.invoice(total="10", paid="0")
        with self.assertRaises(ValidationError):
            self.apply(target, credit, "11")
        key = uuid.uuid4()
        self.apply(target, credit, "5", key)
        with self.assertRaises(ValidationError):
            self.apply(target, credit, "6", key)

    def test_cancellation_releases_used_credit_and_refunds_only_new_cash(self):
        credit = self.credit()
        target = self.invoice(paid="10")
        self.apply(target, credit, "20")
        cancel_invoice(target, self.user, payment_action="refund", refund_method="cash")
        self.assertEqual(credit.available_amount, Decimal("30"))
        self.assertEqual(PaymentResolution.objects.get(payment__invoice=target).amount, Decimal("10"))
        cancel_invoice(target, self.user, payment_action="credit")
        self.assertEqual(self.customer.credit_balance, Decimal("30"))
        next_invoice = self.invoice(paid="0")
        self.apply(next_invoice, credit, "30")
        self.assertEqual(self.customer.credit_balance, Decimal("0"))

    def test_reject_other_customer_draft_cancelled_and_refund_credit(self):
        credit = self.credit()
        other = Customer.objects.create(name="Other")
        target = self.invoice(paid="0")
        target.customer = other
        target.save()
        with self.assertRaises(ValidationError):
            self.apply(target, credit, "1")
        target.customer = self.customer
        for status in ("draft", "cancelled", "paid"):
            target.status = status
            target.save()
            with self.assertRaises(ValidationError):
                self.apply(target, credit, "1")

    def test_financial_report_refunds_and_credit_are_not_revenue_or_new_cash(self):
        credit = self.credit()
        refund_invoice = self.invoice(paid="20")
        cancel_invoice(refund_invoice, self.user, payment_action="refund", refund_method="cash")
        pending_invoice = self.invoice(paid="15")
        cancel_invoice(pending_invoice, self.user)
        target = self.invoice(paid="0")
        self.apply(target, credit, "10")
        report = build_financial_report(timezone.localdate(), timezone.localdate())
        self.assertEqual(report["cash_collected"], Decimal("65"))
        self.assertEqual(report["refunds"], Decimal("20"))
        self.assertEqual(report["net_collected"], Decimal("45"))
        self.assertEqual(report["customer_credit"], Decimal("20"))
        self.assertEqual(report["pending_refunds"], Decimal("15"))
        self.assertEqual(report["revenue"], Decimal("100"))
        self.assertEqual(report["receivables"], Decimal("90"))

    def test_resolution_and_receipts_are_immutable(self):
        credit = self.credit()
        with self.assertRaises(ValidationError):
            credit.save()
        with self.assertRaises(ValidationError):
            credit.delete()
        with self.assertRaises(ValidationError):
            credit.payment.save()
        with self.assertRaises(ValidationError):
            credit.payment.delete()

    def test_modal_validates_method_and_resolves_later(self):
        invoice = self.invoice()
        self.assertEqual(self.request(InvoiceCancellationView, invoice).status_code, 200)
        response = self.request(InvoiceCancellationView, invoice, {"payment_action": "refund"})
        self.assertIn(b'"success": false', response.content)
        self.assertFalse(PaymentResolution.objects.exists())
        response = self.request(InvoiceCancellationView, invoice, {"payment_action": "later"})
        self.assertIn(b'"success": true', response.content)
        invoice.refresh_from_db()
        response = self.request(InvoiceCancellationView, invoice, {"payment_action": "refund", "refund_method": "card"})
        self.assertIn(b'"success": true', response.content)
        self.assertEqual(invoice.cancellation_pending, Decimal("0"))

    def test_credit_modal_applies_and_replays(self):
        credit = self.credit()
        target = self.invoice(paid="0")
        data = {"credit": credit.pk, "amount": "10", "request_key": str(uuid.uuid4())}
        response = self.request(CustomerCreditUseView, target, data)
        self.assertIn(b'"success": true', response.content)
        response = self.request(CustomerCreditUseView, target, data)
        self.assertIn(b'"success": true', response.content)
        self.assertEqual(CustomerCreditUse.objects.count(), 1)

    def test_permission_and_ownership_enforced(self):
        invoice = self.invoice()
        user = get_user_model().objects.create_user("otherrep", password="x")
        with self.assertRaises(Exception) as error:
            self.request(InvoiceCancellationView, invoice, {}, user)
        from django.core.exceptions import PermissionDenied
        self.assertIsInstance(error.exception, PermissionDenied)
        user.user_permissions.add(Permission.objects.get(codename="cancel_invoice"))
        user = get_user_model().objects.get(pk=user.pk)
        with self.assertRaises(Http404):
            self.request(InvoiceCancellationView, invoice, {"payment_action": "later"}, user)
        credit = self.credit()
        self.assertFalse(visible_credits(invoice, user).exists())
        own_invoice = Invoice.objects.create(customer=self.customer, salesperson=user, status="issued", total_lyd=10)
        user.user_permissions.add(Permission.objects.get(codename="add_payment"))
        user = get_user_model().objects.get(pk=user.pk)
        response = self.request(CustomerCreditUseView, own_invoice, {"credit": credit.pk, "amount": "1", "request_key": str(uuid.uuid4())}, user)
        self.assertIn(b'"success": false', response.content)

    def test_stock_restored_only_once_with_later_resolution(self):
        product = Product.objects.create(name="Tracked", cost_usd=1, track_stock=True)
        StockMovement.objects.create(product=product, movement_type="in", quantity=3)
        invoice = Invoice.objects.create(customer=self.customer)
        InvoiceItem.objects.create(invoice=invoice, product=product, quantity=2, unit_price_lyd=10)
        invoice.recalc_totals()
        issue_invoice(invoice, self.user)
        Payment.objects.create(invoice=invoice, amount=10)
        cancel_invoice(invoice, self.user)
        cancel_invoice(invoice, self.user, payment_action="credit")
        product.refresh_from_db()
        self.assertEqual(product.stock_qty, Decimal("3"))
        self.assertEqual(StockMovement.objects.filter(product=product, movement_type="in").count(), 2)
