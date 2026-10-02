from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.urls import reverse
from django.utils import timezone

from sales.models import Invoice, InvoiceItem, Payment
from sales.reports import build_sales_report
from sales.services import cancel_invoice


class InvoiceRegressionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("invoicefix", "fix@example.com", "x")

    def post_editor(self, url, data, invoice=None):
        from sales.views import InvoiceCreateView, InvoiceUpdateView

        request = RequestFactory().post(url, data)
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = self.user
        request._messages = FallbackStorage(request)
        view = InvoiceUpdateView if invoice else InvoiceCreateView
        return view.as_view()(request, **({"pk": invoice.pk} if invoice else {}))

    def test_removed_new_line_between_retained_lines_saves(self):
        data = {
            "invoice_date": timezone.localdate().isoformat(),
            "discount_percent": "0", "discount_amount": "0",
            "items-TOTAL_FORMS": "3", "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
            "items-1-DELETE": "on",
        }
        for index in (0, 2):
            data.update({
                f"items-{index}-kind": "custom",
                f"items-{index}-description": f"Keep {index}",
                f"items-{index}-quantity": "1",
                f"items-{index}-unit_price_lyd": "10",
            })
        response = self.post_editor(reverse("sales:invoice_create"), data)
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get()
        self.assertEqual(list(invoice.items.order_by("pk").values_list("description", flat=True)), ["Keep 0", "Keep 2"])
        self.assertEqual(invoice.total_lyd, Decimal("20.00"))

    def test_removed_existing_line_saves_and_stays_hidden_on_invalid_post(self):
        invoice = Invoice.objects.create(customer_name="Buyer")
        item = InvoiceItem.objects.create(invoice=invoice, kind="custom", description="Remove", quantity=1, unit_price_lyd=10)
        data = {
            "invoice_date": "invalid", "discount_percent": "0", "discount_amount": "0",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "1",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
            "items-0-id": str(item.pk), "items-0-DELETE": "on",
        }
        url = reverse("sales:invoice_edit", args=[invoice.pk])
        response = self.post_editor(url, data, invoice)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="cart-row d-none"')
        data["invoice_date"] = timezone.localdate().isoformat()
        self.assertEqual(self.post_editor(url, data, invoice).status_code, 302)
        invoice.refresh_from_db()
        self.assertFalse(invoice.items.exists())
        self.assertEqual(invoice.total_lyd, Decimal("0.00"))

    def test_cancel_clears_debt_excludes_sales_and_preserves_receipts(self):
        for paid in (Decimal("0"), Decimal("30"), Decimal("100")):
            with self.subTest(paid=paid):
                invoice = Invoice.objects.create(customer_name="Buyer", status="issued", total_lyd=100)
                if paid:
                    Payment.objects.create(invoice=invoice, amount=paid)
                cancel_invoice(invoice, self.user)
                invoice.refresh_from_db()
                self.assertEqual(invoice.balance_due, Decimal("0.00"))
                self.assertEqual(invoice.total_lyd, Decimal("100.00"))
                self.assertEqual(invoice.amount_paid, paid)
                cancel_invoice(invoice, self.user)
                report = build_sales_report(timezone.localdate(), timezone.localdate())
                self.assertEqual(report["total_sales"], Decimal("0.00"))
                self.assertEqual(report["outstanding"], Decimal("0.00"))
