import json
from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product, ProductVariant, Service
from finance.models import ExchangeRate
from sales.models import Invoice, InvoiceItem, Payment
from sales.services import cancel_invoice, issue_invoice

from ..urls import app_name


class InvoiceFormLayoutTests(TestCase):
    """The invoice header form gets the same multi-column grid as modal forms;
    the items formset is untouched. Rendered via the {% crispy %} tag."""

    def test_header_grid_keeps_hidden_customer_and_all_fields(self):
        from crispy_forms.utils import render_crispy_form

        from sales.forms import InvoiceForm

        form = InvoiceForm(user=None)  # a rep: no salesperson picker
        self.assertTrue(getattr(form, "helper", None) and form.helper.layout)
        html = render_crispy_form(form)
        self.assertIn('class="row', html)
        self.assertIn("col-md-6", html)
        self.assertIn('name="customer"', html)  # hidden FK still emitted
        for f in ("customer_name", "customer_phone", "customer_address",
                  "invoice_date", "discount_percent", "discount_amount", "notes"):
            self.assertIn(f'name="{f}"', html, f"header field {f} missing")

    def test_missing_line_quantity_renders_visible_invalid_cell(self):
        from django.contrib.auth import get_user_model
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.test import RequestFactory

        from sales.views import InvoiceCreateView

        ExchangeRate.objects.create(rate=Decimal("6.50"))
        user = get_user_model().objects.create_superuser("invoiceadmin", "i@example.com", "x")
        product = Product.objects.create(name="Spare Key", cost_usd=Decimal("4.00"), price_usd=Decimal("6.00"))
        data = {
            "salesperson": "",
            "customer": "",
            "customer_name": "Walk-in",
            "customer_phone": "",
            "customer_address": "",
            "invoice_date": "2026-07-11",
            "discount_percent": "0.00",
            "discount_amount": "0.00",
            "notes": "",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-id": "",
            "items-0-kind": "product",
            "items-0-product": str(product.pk),
            "items-0-service": "",
            "items-0-description": "",
            "items-0-variant": "",
            "items-0-color": "",
            "items-0-size": "",
            "items-0-unit_price_lyd": "10.00",
            "items-0-quantity": "",
        }
        request = RequestFactory().post(reverse("sales:invoice_create"), data)
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = user
        request._messages = FallbackStorage(request)
        response = InvoiceCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('name="items-0-quantity"', html)
        self.assertIn("errorlist", html)


class SalesConfigScaffoldTests(SimpleTestCase):
    def test_urls_namespace_matches_app_name(self):
        self.assertEqual(app_name, "sales")


class PricingAndInvoiceTests(TestCase):
    def setUp(self):
        ExchangeRate.objects.create(rate=Decimal("6.50"))
        self.cat = Category.objects.create(name="Locks")
        self.product = Product.objects.create(
            name="Lock X1", category=self.cat,
            cost_usd=Decimal("40"), markup_percent=Decimal("25"),
            color=Product.COLOR_BLUE, size="Matte / 120x80 mm",
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            color=Product.COLOR_BLUE,
            size="Matte / 120x80 mm",
            stock_qty=Decimal("10.00"),
        )
        self.service = Service.objects.create(
            name="Install", service_type="installation", price_usd=Decimal("20"),
        )

    def test_hybrid_pricing(self):
        # 40 USD + 25% = 50 USD -> * 6.50 = 325 LYD
        self.assertEqual(self.product.effective_price_usd, Decimal("50.00"))
        self.assertEqual(self.product.selling_price_lyd(), Decimal("325.00"))
        # Manual LYD override wins over conversion
        self.product.price_lyd_override = Decimal("400.00")
        self.assertEqual(self.product.selling_price_lyd(), Decimal("400.00"))

    def test_invoice_editor_product_map_includes_variant_metadata(self):
        from sales.views import InvoiceCreateView

        payload = json.loads(InvoiceCreateView()._catalog_map(Decimal("6.50")))
        row = next(p for p in payload["products"] if p["id"] == self.product.pk)

        self.assertEqual(row["price"], 325.0)
        self.assertEqual(row["name"], self.product.name)
        variant = row["variants"][0]
        self.assertEqual(variant["id"], self.variant.pk)
        self.assertEqual(variant["color"], Product.COLOR_BLUE)
        self.assertEqual(variant["color_label"], "Blue")
        self.assertEqual(variant["size"], "Matte / 120x80 mm")
        self.assertEqual(variant["stock_qty"], 10.0)

    def test_product_line_snapshots_variant_metadata(self):
        from sales.views import _apply_item_price

        inv = Invoice.objects.create(customer_name="Walk-in", exchange_rate=Decimal("6.50"))
        item = InvoiceItem(
            invoice=inv, product=self.product, description="",
            unit_price_lyd=Decimal("325"), quantity=Decimal("1"),
        )
        _apply_item_price(item, inv)

        self.assertEqual(item.kind, InvoiceItem.KIND_PRODUCT)
        self.assertEqual(item.variant_id, self.variant.pk)
        self.assertEqual(item.color, Product.COLOR_BLUE)
        self.assertEqual(item.size, "Matte / 120x80 mm")

    def test_service_per_job_when_unpriced(self):
        svc = Service.objects.create(name="Custom job", service_type="other")
        self.assertIsNone(svc.selling_price_lyd())

    def test_auto_sku_and_invoice_number(self):
        self.assertTrue(self.product.sku.startswith("P"))
        inv = Invoice.objects.create(customer_name="Walk-in")
        self.assertTrue(inv.number.startswith("INV-"))
        self.assertEqual(inv.exchange_rate, Decimal("6.5000"))

    def test_issue_deducts_stock_and_freezes_total(self):
        from catalog.models import StockMovement
        StockMovement.objects.create(product=self.product, movement_type="in", quantity=Decimal("10"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, Decimal("10.00"))

        inv = Invoice.objects.create(customer_name="Walk-in")
        InvoiceItem.objects.create(
            invoice=inv, product=self.product, description="Lock X1",
            unit_price_lyd=Decimal("325"), quantity=Decimal("2"),
        )
        inv.recalc_totals()
        self.assertEqual(inv.total_lyd, Decimal("650.00"))

        issue_invoice(inv, None)
        inv.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(inv.status, Invoice.STATUS_ISSUED)
        self.assertEqual(self.product.stock_qty, Decimal("8.00"))

        # A later rate change must NOT alter this issued invoice's total.
        ExchangeRate.objects.create(rate=Decimal("9.99"))
        inv.refresh_from_db()
        self.assertEqual(inv.total_lyd, Decimal("650.00"))
        self.assertEqual(inv.exchange_rate, Decimal("6.5000"))

    def test_payment_status_transitions(self):
        inv = Invoice.objects.create(customer_name="Walk-in")
        InvoiceItem.objects.create(
            invoice=inv, service=self.service, kind="service", description="Install",
            unit_price_lyd=Decimal("130"), quantity=Decimal("1"),
        )
        inv.recalc_totals()
        issue_invoice(inv, None)

        Payment.objects.create(invoice=inv, amount=Decimal("50"))
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.STATUS_PARTIAL)
        self.assertEqual(inv.balance_due, Decimal("80.00"))

        Payment.objects.create(invoice=inv, amount=Decimal("80"))
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.STATUS_PAID)
        self.assertEqual(inv.balance_due, Decimal("0.00"))

    def test_issue_blocks_on_insufficient_stock(self):
        from django.core.exceptions import ValidationError
        from catalog.models import StockMovement
        StockMovement.objects.create(product=self.product, movement_type="in", quantity=Decimal("1"))
        inv = Invoice.objects.create(customer_name="Walk-in")
        InvoiceItem.objects.create(
            invoice=inv, product=self.product, description="Lock X1",
            unit_price_lyd=Decimal("325"), quantity=Decimal("3"),
        )
        inv.recalc_totals()
        with self.assertRaises(ValidationError):
            issue_invoice(inv, None)
        inv.refresh_from_db(); self.product.refresh_from_db()
        # Nothing changed: still a draft, stock untouched.
        self.assertEqual(inv.status, Invoice.STATUS_DRAFT)
        self.assertEqual(self.product.stock_qty, Decimal("1.00"))

    def test_issue_checks_stock_per_color_size_variant(self):
        from django.core.exceptions import ValidationError
        from catalog.models import StockMovement

        product = Product.objects.create(name="Spare Key", cost_usd=Decimal("4.00"), price_usd=Decimal("6.00"))
        orange = ProductVariant.get_or_create_for(product, Product.COLOR_ORANGE, "13.56 MHz")
        blue = ProductVariant.get_or_create_for(product, Product.COLOR_BLUE, "13.56 MHz")
        StockMovement.objects.create(product=product, variant=orange, movement_type="in", quantity=Decimal("1.00"))
        StockMovement.objects.create(product=product, variant=blue, movement_type="in", quantity=Decimal("10.00"))

        inv = Invoice.objects.create(customer_name="Variant Buyer")
        InvoiceItem.objects.create(
            invoice=inv,
            product=product,
            variant=orange,
            color=Product.COLOR_ORANGE,
            size="13.56 MHz",
            description="Spare Key Orange",
            unit_price_lyd=Decimal("40.00"),
            quantity=Decimal("2.00"),
        )
        inv.recalc_totals()

        with self.assertRaises(ValidationError):
            issue_invoice(inv, None)
        inv.refresh_from_db()
        product.refresh_from_db()
        orange.refresh_from_db()
        blue.refresh_from_db()
        self.assertEqual(inv.status, Invoice.STATUS_DRAFT)
        self.assertEqual(product.stock_qty, Decimal("11.00"))
        self.assertEqual(orange.stock_qty, Decimal("1.00"))
        self.assertEqual(blue.stock_qty, Decimal("10.00"))

        inv.items.update(quantity=Decimal("1.00"))
        issue_invoice(inv, None)
        product.refresh_from_db()
        orange.refresh_from_db()
        blue.refresh_from_db()
        self.assertEqual(product.stock_qty, Decimal("10.00"))
        self.assertEqual(orange.stock_qty, Decimal("0.00"))
        self.assertEqual(blue.stock_qty, Decimal("10.00"))

        cancel_invoice(inv, None)
        product.refresh_from_db()
        orange.refresh_from_db()
        blue.refresh_from_db()
        self.assertEqual(product.stock_qty, Decimal("11.00"))
        self.assertEqual(orange.stock_qty, Decimal("1.00"))
        self.assertEqual(blue.stock_qty, Decimal("10.00"))

    def test_sales_report_aggregates(self):
        from sales.reports import build_sales_report, build_sales_report_xlsx, default_window
        from catalog.models import StockMovement
        StockMovement.objects.create(product=self.product, movement_type="in", quantity=Decimal("10"))
        inv = Invoice.objects.create(customer_name="Acme")
        InvoiceItem.objects.create(
            invoice=inv, product=self.product, description="Lock X1",
            unit_price_lyd=Decimal("325"), quantity=Decimal("2"),
        )
        inv.recalc_totals()
        issue_invoice(inv, None)
        Payment.objects.create(invoice=inv, amount=Decimal("300"))

        df, dt = default_window()
        report = build_sales_report(df, dt)
        self.assertEqual(report["invoice_count"], 1)
        self.assertEqual(report["total_sales"], Decimal("650.00"))
        self.assertEqual(report["outstanding"], Decimal("350.00"))
        self.assertEqual(report["by_product"][0]["description"], "Lock X1")
        # XLSX builds and is a non-empty zip (xlsx magic bytes "PK").
        content = build_sales_report_xlsx(report)
        self.assertTrue(content.startswith(b"PK"))

    def test_cancel_restores_stock(self):
        from catalog.models import StockMovement
        StockMovement.objects.create(product=self.product, movement_type="in", quantity=Decimal("5"))
        inv = Invoice.objects.create(customer_name="Walk-in")
        InvoiceItem.objects.create(
            invoice=inv, product=self.product, description="Lock X1",
            unit_price_lyd=Decimal("325"), quantity=Decimal("3"),
        )
        inv.recalc_totals()
        issue_invoice(inv, None)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, Decimal("2.00"))

        cancel_invoice(inv, None)
        inv.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(inv.status, Invoice.STATUS_CANCELLED)
        self.assertEqual(self.product.stock_qty, Decimal("5.00"))


class CustomerComboboxSyncTests(TestCase):
    """_InvoiceEditorView._sync_customer binds/creates the Customer for the typed
    name and persists contact info so it autofills on re-entry."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        # A superuser bypasses row-ownership, so these tests exercise the
        # bind/create logic itself (not the private-customer filtering).
        self.actor = get_user_model().objects.create_superuser("comboadmin", "a@a.co", "x")

    def _sync(self, **kwargs):
        from sales.views import InvoiceCreateView
        inv = Invoice(exchange_rate=Decimal("6.50"), **kwargs)
        InvoiceCreateView().sync_counterparty(inv, self.actor)
        return inv

    def test_new_name_creates_and_persists_customer(self):
        from sales.models import Customer
        inv = self._sync(customer_name="New Buyer", customer_phone="0910", customer_address="Old City")
        self.assertIsNotNone(inv.customer_id)
        cust = Customer.objects.get(name="New Buyer")
        self.assertEqual((cust.phone, cust.address), ("0910", "Old City"))

    def test_existing_name_reused_and_backfills_snapshot(self):
        from sales.models import Customer
        existing = Customer.objects.create(name="Acme", phone="0999")
        inv = self._sync(customer_name="acme", customer_phone="", customer_address="")
        self.assertEqual(inv.customer_id, existing.pk)  # matched case-insensitively
        self.assertEqual(inv.customer_phone, "0999")  # snapshot backfilled from record
        self.assertEqual(Customer.objects.filter(name__iexact="acme").count(), 1)  # no duplicate

    def test_unnamed_walk_in_creates_no_customer(self):
        from sales.models import Customer
        inv = self._sync(customer_name="")
        self.assertIsNone(inv.customer_id)
        self.assertEqual(Customer.objects.count(), 0)


class PaymentFormTests(TestCase):
    def test_quick_pay_validates_without_paid_at(self):
        # The inline quick-pay form submits only amount/method/deposit; paid_at
        # must not be required (it defaults to now on save).
        from sales.forms import PaymentForm

        form = PaymentForm({"amount": "50", "method": "cash", "deposit": ""})
        self.assertTrue(form.is_valid(), form.errors)

        inv = Invoice.objects.create(customer_name="X", status=Invoice.STATUS_ISSUED)
        payment = form.save(commit=False)
        payment.invoice = inv
        payment.save()
        self.assertIsNotNone(payment.paid_at)  # model default applied
        self.assertRegex(payment.receipt_number, r"^RCT-\d{6}$")
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, Decimal("50.00"))

    def test_payment_receipt_numbers_are_unique(self):
        inv = Invoice.objects.create(customer_name="X", status=Invoice.STATUS_ISSUED)
        p1 = Payment.objects.create(invoice=inv, amount=Decimal("10"), method="cash")
        p2 = Payment.objects.create(invoice=inv, amount=Decimal("15"), method="cash")
        self.assertNotEqual(p1.receipt_number, p2.receipt_number)
        self.assertTrue(p1.receipt_number.startswith("RCT-"))


class PaymentReceiptViewTests(TestCase):
    def test_receipt_view_renders_payment_and_balance_after_that_receipt(self):
        from django.contrib.auth import get_user_model
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.test import RequestFactory

        from sales.views import PaymentReceiptView

        def attach_session(request):
            SessionMiddleware(lambda req: None).process_request(request)
            request.session.save()
            return request

        user = get_user_model().objects.create_superuser("receipt_admin", "r@example.com", "x")
        inv = Invoice.objects.create(
            customer_name="Buyer", status=Invoice.STATUS_ISSUED, total_lyd=Decimal("100.00")
        )
        first = Payment.objects.create(
            invoice=inv,
            amount=Decimal("30.00"),
            method="cash",
            paid_at=timezone.now() - timedelta(hours=1),
        )
        second = Payment.objects.create(
            invoice=inv,
            amount=Decimal("20.00"),
            method="bank_transfer",
            paid_at=timezone.now(),
        )

        rf = RequestFactory()
        req = attach_session(rf.get(f"/sales/payments/{first.pk}/receipt/"))
        req.user = user
        resp = PaymentReceiptView.as_view()(req, pk=first.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context_data["paid_before_receipt"], Decimal("0.00"))
        self.assertEqual(resp.context_data["balance_after_receipt"], Decimal("70.00"))
        resp.render()
        html = resp.content.decode()
        self.assertIn("Payment Receipt", html)
        self.assertIn(first.receipt_number, html)

        req = attach_session(rf.get(f"/sales/payments/{second.pk}/receipt/"))
        req.user = user
        resp = PaymentReceiptView.as_view()(req, pk=second.pk)
        self.assertEqual(resp.context_data["paid_before_receipt"], Decimal("30.00"))
        self.assertEqual(resp.context_data["balance_after_receipt"], Decimal("50.00"))

    def test_invoice_and_receipt_prints_use_system_logo_url(self):
        from dlux.translations import get_strings

        logo_url = "/media/dlux/branding/official-logo.png"
        app_config = {
            "identity": {"display_name": "Switch"},
            "logo_url": logo_url,
        }
        strings = get_strings("en")
        inv = Invoice.objects.create(
            customer_name="Buyer",
            status=Invoice.STATUS_ISSUED,
            total_lyd=Decimal("100.00"),
        )
        payment = Payment.objects.create(invoice=inv, amount=Decimal("40.00"), method="cash")

        invoice_html = render_to_string(
            "sales/invoice_print.html",
            {
                "APP_CONFIG": app_config,
                "DLUX_STRINGS": strings,
                "invoice": inv,
                "items": [],
                "payments": [payment],
                "doc_lang": "en",
                "is_rtl": False,
            },
        )
        receipt_html = render_to_string(
            "sales/payment_receipt.html",
            {
                "APP_CONFIG": app_config,
                "DLUX_STRINGS": strings,
                "invoice": inv,
                "payment": payment,
                "paid_before_receipt": Decimal("0.00"),
                "balance_after_receipt": Decimal("60.00"),
                "doc_lang": "en",
                "is_rtl": False,
            },
        )

        self.assertIn(f'src="{logo_url}"', invoice_html)
        self.assertIn(f'src="{logo_url}"', receipt_html)


class SalesContextMenuTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory

        self.user = get_user_model().objects.create_superuser("menu_admin", "m@example.com", "x")
        self.rf = RequestFactory()

    def _request(self, path="/"):
        from django.contrib.sessions.middleware import SessionMiddleware

        request = self.rf.get(path)
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = self.user
        return request

    def _row_actions(self, table, record):
        return json.loads(table.row_attrs["data-dlux-actions"](record))

    def test_invoice_table_uses_dlux_context_menu_for_full_page_actions(self):
        from sales.tables import InvoiceTable

        invoice = Invoice.objects.create(customer_name="Buyer", status=Invoice.STATUS_DRAFT)
        table = InvoiceTable([invoice], request=self._request("/sales/invoices/"))

        self.assertEqual(table.render_number(invoice), invoice.number)
        actions = self._row_actions(table, invoice)
        urls = {action.get("url") for action in actions}
        form_urls = {action.get("url") for action in actions if action.get("type") == "form"}
        print_action = next(action for action in actions if action.get("url") == reverse("sales:invoice_print", args=[invoice.pk]))

        self.assertIn(reverse("sales:invoice_detail", args=[invoice.pk]), urls)
        self.assertIn(reverse("sales:invoice_print", args=[invoice.pk]), urls)
        self.assertIn(reverse("sales:invoice_edit", args=[invoice.pk]), urls)
        self.assertIn(reverse("sales:invoice_issue", args=[invoice.pk]), form_urls)
        self.assertIn(reverse("sales:invoice_cancel", args=[invoice.pk]), form_urls)
        self.assertEqual(print_action["target"], "_blank")
        self.assertTrue(actions[0]["dblclick"])

    def test_invoice_list_exposes_hidden_csrf_for_context_menu_form_actions(self):
        from sales.views import InvoiceListView

        Invoice.objects.create(customer_name="Buyer", status=Invoice.STATUS_DRAFT)
        request = self._request(reverse("sales:invoice_list"))
        response = InvoiceListView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        response.render()
        html = response.content.decode()

        self.assertIn('name="csrfmiddlewaretoken"', html)
        self.assertIn("data-dlux-row-action-csrf", html)

    def test_payment_table_uses_dlux_context_menu_for_invoice_and_receipt(self):
        from sales.tables import PaymentTable

        invoice = Invoice.objects.create(
            customer_name="Buyer",
            status=Invoice.STATUS_ISSUED,
            total_lyd=Decimal("100.00"),
        )
        payment = Payment.objects.create(invoice=invoice, amount=Decimal("40.00"), method="cash")
        table = PaymentTable([payment], request=self._request("/sales/payments/"))

        self.assertEqual(table.render_receipt_number(payment), payment.receipt_number)
        self.assertEqual(table.render_invoice(payment), invoice.number)
        actions = self._row_actions(table, payment)
        urls = {action.get("url") for action in actions}
        receipt_action = next(action for action in actions if action.get("url") == reverse("sales:payment_receipt", args=[payment.pk]))

        self.assertIn(reverse("sales:invoice_detail", args=[invoice.pk]), urls)
        self.assertIn(reverse("sales:payment_receipt", args=[payment.pk]), urls)
        self.assertEqual(receipt_action["target"], "_blank")
        self.assertTrue(actions[0]["dblclick"])

    def test_invoice_detail_payment_rows_offer_receipt_context_action(self):
        from sales.views import InvoiceDetailView

        invoice = Invoice.objects.create(
            customer_name="Buyer",
            status=Invoice.STATUS_ISSUED,
            total_lyd=Decimal("100.00"),
        )
        payment = Payment.objects.create(invoice=invoice, amount=Decimal("40.00"), method="cash")
        receipt_url = reverse("sales:payment_receipt", args=[payment.pk])

        request = self._request(reverse("sales:invoice_detail", args=[invoice.pk]))
        response = InvoiceDetailView.as_view()(request, pk=invoice.pk)
        self.assertEqual(response.status_code, 200)
        response.render()
        html = response.content.decode()

        self.assertIn('data-dlux-context="true"', html)
        self.assertIn(receipt_url, html)
        self.assertIn('"label":"Print Receipt"', html)
        self.assertIn('"target":"_blank"', html)
        self.assertNotIn(f'<a href="{receipt_url}"', html)


class DepositBatchTests(TestCase):
    def setUp(self):
        ExchangeRate.objects.create(rate=Decimal("6.50"))
        self.inv = Invoice.objects.create(
            customer_name="X", status=Invoice.STATUS_ISSUED, total_lyd=Decimal("1000")
        )

    def test_deposit_amount_autosums_linked_payments(self):
        from finance.models import CashDeposit

        dep = CashDeposit.objects.create(reference="B", amount=Decimal("0.00"))
        Payment.objects.create(invoice=self.inv, amount=Decimal("320"), deposit=dep)
        dep.refresh_from_db()
        self.assertEqual(dep.amount, Decimal("320.00"))

        Payment.objects.create(invoice=self.inv, amount=Decimal("100"), deposit=dep)
        dep.refresh_from_db()
        self.assertEqual(dep.amount, Decimal("420.00"))  # grows

        dep.payments.order_by("-pk").first().delete()
        dep.refresh_from_db()
        self.assertEqual(dep.amount, Decimal("320.00"))  # shrinks

    def test_reassigning_a_payment_recomputes_both_batches(self):
        from finance.models import CashDeposit

        a = CashDeposit.objects.create(reference="A", amount=Decimal("0.00"))
        b = CashDeposit.objects.create(reference="B", amount=Decimal("0.00"))
        p = Payment.objects.create(invoice=self.inv, amount=Decimal("200"), deposit=a)
        a.refresh_from_db(); self.assertEqual(a.amount, Decimal("200.00"))

        p.deposit = b
        p.save()
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(a.amount, Decimal("0.00"))    # old batch emptied
        self.assertEqual(b.amount, Decimal("200.00"))  # new batch carries it

    def test_sync_deposit_creates_then_reuses_by_reference(self):
        from django.test import RequestFactory
        from django.contrib.auth import get_user_model
        from finance.models import CashDeposit
        from sales.views import PaymentCreateView

        req = RequestFactory().post("/")
        req.user = get_user_model().objects.create(username="u1")
        view = PaymentCreateView()

        p1 = Payment(invoice=self.inv, amount=Decimal("50"), method="cash")
        view._sync_deposit(req, p1, "Shift-1")
        self.assertIsNotNone(p1.deposit_id)
        self.assertEqual(p1.deposit.reference, "Shift-1")

        p2 = Payment(invoice=self.inv, amount=Decimal("10"), method="cash")
        view._sync_deposit(req, p2, "shift-1")  # case-insensitive match
        self.assertEqual(p2.deposit_id, p1.deposit_id)
        self.assertEqual(CashDeposit.objects.filter(reference__iexact="shift-1").count(), 1)

        p3 = Payment(invoice=self.inv, amount=Decimal("10"), method="cash")
        view._sync_deposit(req, p3, "")  # blank -> no batch
        self.assertIsNone(p3.deposit_id)


class SeedDemoCommandTests(TestCase):
    def test_seed_demo_spread_idempotent_and_reset(self):
        from django.core.management import call_command
        from catalog.models import Product, PurchaseInvoice, StockTake, Supplier
        from finance.models import CashDeposit, Expense, StaffLedgerEntry
        from sales.models import Delivery

        call_command("seed_demo", verbosity=0)
        self.assertEqual(Product.objects.count(), 24)
        self.assertEqual(Supplier.objects.count(), 4)
        self.assertEqual(PurchaseInvoice.objects.count(), 4)
        self.assertEqual(Delivery.objects.count(), 10)
        self.assertEqual(Expense.objects.count(), 5)
        self.assertEqual(StaffLedgerEntry.objects.count(), 7)
        self.assertEqual(StockTake.objects.count(), 2)
        self.assertEqual(CashDeposit.objects.count(), 3)
        self.assertTrue(Product.objects.filter(barcode="6291041500213").exists())
        self.assertTrue(ProductVariant.objects.filter(color=Product.COLOR_GOLD, size__icontains="ANSI").exists())
        for status in ("paid", "partial", "issued", "cancelled", "draft"):
            self.assertTrue(
                Invoice.objects.filter(status=status).exists(),
                f"expected a {status} invoice",
            )
        self.assertTrue(Payment.objects.exists())
        self.assertTrue(Payment.objects.filter(deposit__reference="DEP-SHIFT-001").exists())

        # Re-running does not pile up duplicate invoices.
        count = Invoice.objects.count()
        call_command("seed_demo", verbosity=0)
        self.assertEqual(Invoice.objects.count(), count)
        self.assertEqual(PurchaseInvoice.objects.count(), 4)

        # --reset wipes then rebuilds to the same shape.
        call_command("seed_demo", "--reset", verbosity=0)
        self.assertEqual(Invoice.objects.count(), count)
        self.assertEqual(Product.objects.count(), 24)
        self.assertEqual(PurchaseInvoice.objects.count(), 4)


class InvoicePickerTests(TestCase):
    """POS-style catalog picker + cart on the sales invoice editor."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        ExchangeRate.objects.create(rate=Decimal("6.50"))
        self.cat = Category.objects.create(name="Locks")
        self.product = Product.objects.create(
            name="Lock X1", category=self.cat, cost_usd=Decimal("40"), markup_percent=Decimal("25"),
        )
        self.variant = ProductVariant.objects.create(
            product=self.product, color=Product.COLOR_BLUE, size="XL", stock_qty=Decimal("10.00"),
        )
        # Out-of-stock, stock-tracked, no variants -> must be excluded from the picker.
        self.oos = Product.objects.create(name="Sold Out", cost_usd=Decimal("5"), track_stock=True)
        self.service = Service.objects.create(
            name="Install", service_type="installation", price_usd=Decimal("20"),
        )
        self.user = get_user_model().objects.create_superuser("picker", "p@example.com", "x")

    def _req(self, method, url, data=None):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.test import RequestFactory

        rf = RequestFactory()
        request = getattr(rf, method)(url, data or {})
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = self.user
        request._messages = FallbackStorage(request)
        return request

    def test_catalog_map_filters_stock_and_carries_service_icons(self):
        from sales.views import InvoiceCreateView

        payload = json.loads(InvoiceCreateView()._catalog_map(Decimal("6.50")))
        ids = [p["id"] for p in payload["products"]]
        self.assertIn(self.product.pk, ids)
        self.assertNotIn(self.oos.pk, ids)  # out of stock, filtered out

        svc = payload["services"][0]
        self.assertEqual(svc["id"], self.service.pk)
        self.assertEqual(svc["icon"], "bi-wrench")
        self.assertTrue(svc["type_label"])

    def test_create_view_renders_picker(self):
        from sales.views import InvoiceCreateView

        resp = InvoiceCreateView.as_view()(self._req("get", reverse("sales:invoice_create")))
        html = resp.content.decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("data-invoice-catalog", html)
        self.assertIn("data-picker-grid", html)
        self.assertIn('id="catalog-map"', html)
        self.assertIn("invoice_editor.js", html)
        self.assertNotIn('id="items-table"', html)  # old wide table gone

    def _mgmt(self, rows):
        data = {
            "salesperson": "", "customer": "", "customer_name": "Walk-in",
            "customer_phone": "", "customer_address": "", "invoice_date": "2026-07-11",
            "discount_percent": "0.00", "discount_amount": "0.00", "notes": "",
            "items-TOTAL_FORMS": str(len(rows)), "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
        }
        for i, row in enumerate(rows):
            for k, v in row.items():
                data[f"items-{i}-{k}"] = v
        return data

    def test_create_saves_product_variant_line(self):
        from sales.views import InvoiceCreateView

        data = self._mgmt([{
            "id": "", "kind": "product", "product": str(self.product.pk), "service": "",
            "variant": str(self.variant.pk), "color": Product.COLOR_BLUE, "size": "XL",
            "description": "Lock X1", "unit_price_lyd": "325.00", "quantity": "2",
        }])
        resp = InvoiceCreateView.as_view()(self._req("post", reverse("sales:invoice_create"), data))
        self.assertEqual(resp.status_code, 302)
        item = InvoiceItem.objects.get()
        self.assertEqual(item.kind, InvoiceItem.KIND_PRODUCT)
        self.assertEqual(item.variant_id, self.variant.pk)
        self.assertEqual(item.line_total_lyd, Decimal("650.00"))

    def test_create_saves_service_line(self):
        from sales.views import InvoiceCreateView

        data = self._mgmt([{
            "id": "", "kind": "service", "product": "", "service": str(self.service.pk),
            "variant": "", "color": "", "size": "", "description": "Install",
            "unit_price_lyd": "", "quantity": "1",
        }])
        resp = InvoiceCreateView.as_view()(self._req("post", reverse("sales:invoice_create"), data))
        self.assertEqual(resp.status_code, 302)
        item = InvoiceItem.objects.get()
        self.assertEqual(item.kind, InvoiceItem.KIND_SERVICE)
        self.assertEqual(item.service_id, self.service.pk)
