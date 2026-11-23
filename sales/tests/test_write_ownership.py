"""Writes respect row ownership, not only reads.

A rep binds an invoice only to a customer in their own book, a payment only to a
pending cash-deposit batch they may see, a courier changes only the status and
notes of a delivery, and a deposit is confirmed only by someone who may see it,
once.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from finance.models import CashDeposit
from finance.views import CashDepositReviewView
from sales.forms import DeliveryForm, InvoiceForm, PaymentForm, attachable_deposits
from sales.models import Customer, Delivery, Invoice

User = get_user_model()
rf = RequestFactory()


def _perm(code):
    app_label, codename = code.split(".", 1)
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def _user(name, *perms):
    user = User.objects.create_user(name, password="x")
    user.user_permissions.add(*(_perm(code) for code in perms))
    return User.objects.get(pk=user.pk)


def _invoice_data(**overrides):
    data = {"customer_name": "Walk-in", "invoice_date": "2026-11-23", "discount_percent": "0", "discount_amount": "0"}
    data.update(overrides)
    return data


class InvoiceCustomerOwnershipTests(TestCase):
    def setUp(self):
        self.rep_a = _user("rep_a", "sales.add_invoice")
        self.rep_b = _user("rep_b", "sales.add_invoice")
        self.own = Customer.objects.create(name="A client", phone="111", created_by=self.rep_a)
        self.foreign = Customer.objects.create(name="B client", phone="222", address="B street", created_by=self.rep_b)

    def test_a_rep_cannot_bind_another_reps_customer(self):
        form = InvoiceForm(_invoice_data(customer=self.foreign.pk, customer_name="B client"), user=self.rep_a)
        self.assertFalse(form.is_valid())
        self.assertIn("customer", form.errors)

    def test_a_rep_binds_their_own_customer(self):
        form = InvoiceForm(_invoice_data(customer=self.own.pk, customer_name="A client"), user=self.rep_a)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["customer"], self.own)

    def test_view_all_may_bind_any_customer(self):
        manager = _user("manager", "sales.add_invoice", "sales.view_all_customer")
        form = InvoiceForm(_invoice_data(customer=self.foreign.pk, customer_name="B client"), user=manager)
        self.assertTrue(form.is_valid(), form.errors)


class PaymentDepositOwnershipTests(TestCase):
    def setUp(self):
        self.rep_a = _user("rep_a", "sales.add_payment")
        self.rep_b = _user("rep_b", "sales.add_payment")
        self.own = CashDeposit.objects.create(amount=Decimal("0"), reference="A-1", created_by=self.rep_a)
        self.own_confirmed = CashDeposit.objects.create(
            amount=Decimal("0"), reference="A-2", created_by=self.rep_a, status=CashDeposit.STATUS_CONFIRMED,
        )
        self.foreign = CashDeposit.objects.create(amount=Decimal("0"), reference="B-1", created_by=self.rep_b)

    def test_only_own_pending_batches_are_attachable(self):
        self.assertEqual(list(attachable_deposits(self.rep_a)), [self.own])

    def test_a_posted_foreign_or_settled_batch_is_rejected(self):
        for deposit in (self.foreign, self.own_confirmed):
            with self.subTest(deposit=deposit.reference):
                form = PaymentForm({"amount": "10", "method": "cash", "deposit": deposit.pk}, user=self.rep_a)
                self.assertFalse(form.is_valid())
                self.assertIn("deposit", form.errors)

    def test_an_own_pending_batch_is_accepted(self):
        form = PaymentForm({"amount": "10", "method": "cash", "deposit": self.own.pk}, user=self.rep_a)
        self.assertTrue(form.is_valid(), form.errors)

    def test_view_all_reaches_every_pending_batch(self):
        manager = _user("manager", "sales.add_payment", "finance.view_all_cashdeposit")
        self.assertEqual(set(attachable_deposits(manager)), {self.own, self.foreign})


class CashDepositReviewTests(TestCase):
    def setUp(self):
        self.courier = _user("courier")
        self.deposit = CashDeposit.objects.create(amount=Decimal("50"), reference="C-1", created_by=self.courier)

    def _post(self, user, decision="confirm"):
        request = rf.post("/")
        request.user = user
        request.session = {}
        request._messages = FallbackStorage(request)
        return CashDepositReviewView.as_view()(request, pk=self.deposit.pk, decision=decision)

    def test_a_reviewer_without_view_all_cannot_reach_someone_elses_deposit(self):
        from django.http import Http404

        reviewer = _user("reviewer", "finance.confirm_cashdeposit")
        with self.assertRaises(Http404):
            self._post(reviewer)
        self.deposit.refresh_from_db()
        self.assertEqual(self.deposit.status, CashDeposit.STATUS_PENDING)

    def test_a_decided_deposit_is_not_decided_again(self):
        manager = _user("manager", "finance.confirm_cashdeposit", "finance.view_all_cashdeposit")
        self._post(manager, "confirm")
        self._post(manager, "reject")
        self.deposit.refresh_from_db()
        self.assertEqual(self.deposit.status, CashDeposit.STATUS_CONFIRMED)


class CourierDeliveryEditTests(TestCase):
    def setUp(self):
        self.courier = _user("courier", "sales.view_delivery", "sales.change_delivery")
        self.delivery = Delivery.objects.create(
            assigned_to=self.courier, recipient="Mona", phone="0911", address="Old street",
        )

    def _data(self, **overrides):
        data = {
            "recipient": "Someone else", "phone": "0000", "address": "New street",
            "status": Delivery.STATUS_DELIVERED, "scheduled_date": "", "notes": "left at door",
        }
        data.update(overrides)
        return data

    def test_a_courier_changes_status_and_notes_only(self):
        form = DeliveryForm(self._data(), instance=self.delivery, user=self.courier)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual((saved.recipient, saved.phone, saved.address), ("Mona", "0911", "Old street"))
        self.assertEqual(saved.notes, "left at door")

    def test_a_dispatcher_may_change_the_destination(self):
        dispatcher = _user("dispatcher", "sales.change_delivery", "sales.assign_delivery")
        form = DeliveryForm(self._data(), instance=self.delivery, user=dispatcher)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().address, "New street")

    def test_only_visible_invoices_can_be_linked(self):
        rep = _user("rep", "sales.add_delivery")
        other = _user("other")
        own = Invoice.objects.create(exchange_rate=Decimal("6.5"), created_by=rep, salesperson=rep)
        foreign = Invoice.objects.create(exchange_rate=Decimal("6.5"), created_by=other, salesperson=other)
        form = DeliveryForm(user=rep)
        self.assertIn(own, form.fields["invoice"].queryset)
        self.assertNotIn(foreign, form.fields["invoice"].queryset)


class InvoiceDeletionTests(TestCase):
    def test_only_a_draft_invoice_can_be_deleted(self):
        from django.core.exceptions import ValidationError

        draft = Invoice.objects.create(exchange_rate=Decimal("6.5"))
        issued = Invoice.objects.create(exchange_rate=Decimal("6.5"), status=Invoice.STATUS_ISSUED)
        with self.assertRaises(ValidationError):
            issued.delete()
        issued.refresh_from_db()
        self.assertIsNone(issued.deleted_at)
        draft.delete()
        self.assertFalse(Invoice.objects.filter(pk=draft.pk).exists())
