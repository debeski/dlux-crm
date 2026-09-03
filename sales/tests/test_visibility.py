"""
Row-level (per-employee) visibility tests — the heart of the multi-user model.

A rep sees only their own invoices/customers; a manager holding view_all_* sees
everyone's; a courier sees only deliveries assigned to them. Covers the helper
(common.access.apply_ownership), the list-view + detail choke points, and the
dynamic-modal object lookup patch.

Views are driven with RequestFactory rather than the test Client on purpose: the
Client runs dlux's full middleware stack, which (until the system is marked
"configured") logs a non-superuser out — unrelated to what we're asserting here.
RequestFactory exercises the view's own get_queryset / permission logic directly.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.http import Http404
from django.test import RequestFactory, TestCase

from common.access import apply_ownership
from sales.models import Customer, Delivery, Invoice, Payment
from sales.views import (
    DashboardView,
    DeliveryListView,
    InvoiceDetailView,
    InvoiceListView,
    PaymentReceiptView,
)

User = get_user_model()
rf = RequestFactory()


def _perm(code):
    app_label, codename = code.split(".", 1)
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def _get(view, user, path="/", **kwargs):
    req = rf.get(path)
    req.user = user
    return view.as_view()(req, **kwargs)


class OwnershipHelperTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("rep_a", password="x")
        self.b = User.objects.create_user("rep_b", password="x")
        self.inv_a = Invoice.objects.create(exchange_rate=Decimal("6.5"), created_by=self.a, salesperson=self.a)
        # created by B, but A is the assigned salesperson -> A owns it too.
        self.inv_ab = Invoice.objects.create(exchange_rate=Decimal("6.5"), created_by=self.b, salesperson=self.a)
        self.inv_b = Invoice.objects.create(exchange_rate=Decimal("6.5"), created_by=self.b, salesperson=self.b)

    def test_rep_sees_own_and_assigned_only(self):
        seen = set(apply_ownership(Invoice.objects.all(), self.a).values_list("pk", flat=True))
        self.assertEqual(seen, {self.inv_a.pk, self.inv_ab.pk})

    def test_view_all_sees_everything(self):
        self.b.user_permissions.add(_perm("sales.view_all_invoice"))
        b = User.objects.get(pk=self.b.pk)  # reset perm cache
        seen = set(apply_ownership(Invoice.objects.all(), b).values_list("pk", flat=True))
        self.assertEqual(seen, {self.inv_a.pk, self.inv_ab.pk, self.inv_b.pk})

    def test_superuser_bypasses(self):
        su = User.objects.create_superuser("boss", "b@b.co", "x")
        self.assertEqual(apply_ownership(Invoice.objects.all(), su).count(), 3)

    def test_private_customer_hidden_from_stranger(self):
        Customer.objects.create(name="A's client", created_by=self.a)
        self.assertEqual(apply_ownership(Customer.objects.all(), self.b).count(), 0)
        self.assertEqual(apply_ownership(Customer.objects.all(), self.a).count(), 1)


class InvoiceListVisibilityTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("rep_a", password="x")
        self.a.user_permissions.add(_perm("sales.view_invoice"))
        self.b = User.objects.create_user("rep_b", password="x")
        Invoice.objects.create(number="INV-A", exchange_rate=Decimal("6.5"), created_by=self.a, salesperson=self.a)
        Invoice.objects.create(number="INV-B", exchange_rate=Decimal("6.5"), created_by=self.b, salesperson=self.b)

    def test_rep_list_hides_other_reps_invoices(self):
        resp = _get(InvoiceListView, self.a, "/sales/invoices/")
        self.assertEqual(resp.status_code, 200)
        numbers = {i.number for i in resp.context_data["table"].data}
        self.assertEqual(numbers, {"INV-A"})

    def test_manager_list_shows_all(self):
        self.a.user_permissions.add(_perm("sales.view_all_invoice"))
        resp = _get(InvoiceListView, User.objects.get(pk=self.a.pk), "/sales/invoices/")
        numbers = {i.number for i in resp.context_data["table"].data}
        self.assertEqual(numbers, {"INV-A", "INV-B"})

    def test_rep_cannot_open_other_reps_invoice_detail(self):
        other = Invoice.objects.get(number="INV-B")
        with self.assertRaises(Http404):
            _get(InvoiceDetailView, self.a, f"/sales/{other.pk}/", pk=other.pk)


class PaymentReceiptVisibilityTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("rep_a", password="x")
        self.a.user_permissions.add(_perm("sales.view_payment"))
        self.b = User.objects.create_user("rep_b", password="x")
        self.b.user_permissions.add(_perm("sales.view_payment"))
        self.invoice = Invoice.objects.create(
            number="INV-A",
            exchange_rate=Decimal("6.5"),
            created_by=self.a,
            salesperson=self.a,
        )
        self.payment = Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("50.00"),
            created_by=self.a,
        )

    def test_rep_can_print_own_payment_receipt(self):
        resp = _get(
            PaymentReceiptView,
            self.a,
            f"/sales/payments/{self.payment.pk}/receipt/",
            pk=self.payment.pk,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context_data["payment"], self.payment)

    def test_rep_cannot_print_other_reps_payment_receipt(self):
        with self.assertRaises(Http404):
            _get(
                PaymentReceiptView,
                self.b,
                f"/sales/payments/{self.payment.pk}/receipt/",
                pk=self.payment.pk,
            )


class ModalOwnershipPatchTests(TestCase):
    """The dynamic-modal edit/view/delete lookup must exclude rows a rep doesn't
    own, so guessing an id can't open another rep's private record.

    `common.apps` registers `apply_ownership` with dlux's modal queryset registry
    at app-init; dlux runs it inside `_scope_filtered_modal_queryset`, which is
    the single choke point all three edit/view/delete call sites resolve through."""

    def setUp(self):
        self.a = User.objects.create_user("rep_a", password="x")
        self.b = User.objects.create_user("rep_b", password="x")
        self.cust_b = Customer.objects.create(name="B's client", created_by=self.b)

    def test_ownership_filter_is_registered_at_app_init(self):
        from dlux.access import get_modal_queryset_filters

        from common.access import apply_ownership

        self.assertIn(apply_ownership, get_modal_queryset_filters())

    def test_modal_queryset_excludes_foreign_record(self):
        from dlux.views import sections

        qs_a = sections._scope_filtered_modal_queryset(Customer, self.a)
        qs_b = sections._scope_filtered_modal_queryset(Customer, self.b)
        self.assertNotIn(self.cust_b, list(qs_a))
        self.assertIn(self.cust_b, list(qs_b))


class DeliveryVisibilityTests(TestCase):
    def setUp(self):
        self.courier = User.objects.create_user("courier", password="x")
        self.courier.user_permissions.add(_perm("sales.view_delivery"))
        self.other = User.objects.create_user("courier2", password="x")
        self.mine = Delivery.objects.create(address="123 St", assigned_to=self.courier, created_by=self.other)
        self.theirs = Delivery.objects.create(address="456 St", assigned_to=self.other, created_by=self.other)

    def test_courier_sees_only_assigned(self):
        resp = _get(DeliveryListView, self.courier, "/sales/deliveries/")
        self.assertEqual(resp.status_code, 200)
        pks = {d.pk for d in resp.context_data["table"].data}
        self.assertEqual(pks, {self.mine.pk})

    def test_assigning_courier_advances_status(self):
        d = Delivery.objects.create(address="9 Rd", assigned_to=self.courier)
        self.assertEqual(d.status, Delivery.STATUS_ASSIGNED)

    def test_delivery_snapshots_invoice_address(self):
        inv = Invoice.objects.create(
            exchange_rate=Decimal("6.5"), customer_name="Buyer",
            customer_phone="0910", customer_address="Old City",
        )
        d = Delivery.objects.create(invoice=inv, assigned_to=self.courier)
        self.assertEqual((d.recipient, d.phone, d.address), ("Buyer", "0910", "Old City"))


class DashboardRoleTests(TestCase):
    def _ctx(self, user):
        req = rf.get("/sales/dashboard/")
        req.user = user
        view = DashboardView()
        view.request, view.args, view.kwargs = req, (), {}
        return view.get_context_data()

    def test_courier_dashboard_hides_sales(self):
        courier = User.objects.create_user("courier", password="x")
        courier.user_permissions.add(_perm("sales.view_delivery"))
        ctx = self._ctx(User.objects.get(pk=courier.pk))
        self.assertFalse(ctx["can_view_sales"])
        self.assertTrue(ctx["can_view_deliveries"])
        self.assertFalse(ctx["is_sales_manager"])

    def test_rep_dashboard_shows_own_sales_only(self):
        rep = User.objects.create_user("rep", password="x")
        rep.user_permissions.add(_perm("sales.view_invoice"))
        other = User.objects.create_user("rep2", password="x")
        Invoice.objects.create(exchange_rate=Decimal("6.5"), total_lyd=Decimal("100"),
                               status=Invoice.STATUS_ISSUED, created_by=rep, salesperson=rep)
        Invoice.objects.create(exchange_rate=Decimal("6.5"), total_lyd=Decimal("500"),
                               status=Invoice.STATUS_ISSUED, created_by=other, salesperson=other)
        ctx = self._ctx(User.objects.get(pk=rep.pk))
        self.assertTrue(ctx["can_view_sales"])
        self.assertFalse(ctx["is_sales_manager"])
        self.assertEqual(ctx["sales_month"], Decimal("100"))  # not the other rep's 500

    def test_manager_flag_when_view_all(self):
        mgr = User.objects.create_user("mgr", password="x")
        mgr.user_permissions.add(_perm("sales.view_invoice"))
        mgr.user_permissions.add(_perm("sales.view_all_invoice"))
        ctx = self._ctx(User.objects.get(pk=mgr.pk))
        self.assertTrue(ctx["is_sales_manager"])


class SalespersonDefaultTests(TestCase):
    def test_invoice_defaults_salesperson_to_current_user(self):
        from dlux import middleware as dlux_mw

        rep = User.objects.create_user("rep", password="x")
        dlux_mw._thread_locals.user = rep
        try:
            inv = Invoice.objects.create(exchange_rate=Decimal("6.5"), customer_name="Walk-in")
        finally:
            del dlux_mw._thread_locals.user
        self.assertEqual(inv.salesperson_id, rep.pk)
        self.assertEqual(inv.created_by_id, rep.pk)
