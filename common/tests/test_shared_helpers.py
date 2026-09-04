"""Cover the shared helpers ported from the gov edition."""
from datetime import date, timedelta
from unittest import mock
from decimal import Decimal

import django_filters
from django import forms
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category
from common.filters import DatedFilterSet, year_choices
from common.formatting import format_money, format_quantity
from common.forms import translate_help_text
from sales.models import Customer, Invoice

User = get_user_model()
rf = RequestFactory()


class FormatQuantityTests(TestCase):
    def test_whole_numbers_lose_their_trailing_zeros(self):
        for value in (Decimal("4.00"), Decimal("4.0"), Decimal("4"), 4, 4.0):
            self.assertEqual(format_quantity(value), "4", msg=repr(value))

    def test_a_decimal_and_the_equivalent_float_render_identically(self):
        # The SQLite-vs-Postgres aggregate difference this helper exists for:
        # `f"{value:g}"` renders Decimal("4.00") as "4.00" and the float as "4".
        self.assertEqual(format_quantity(Decimal("4.00")), format_quantity(4.0))

    def test_fractional_quantities_keep_their_significant_digits(self):
        self.assertEqual(format_quantity(Decimal("4.50")), "4.5")
        self.assertEqual(format_quantity(Decimal("0.125")), "0.125")

    def test_large_quantities_never_go_scientific(self):
        self.assertEqual(format_quantity(Decimal("12500000")), "12500000")

    def test_unparseable_values_are_returned_as_given(self):
        self.assertEqual(format_quantity("n/a"), "n/a")


class FormatMoneyTests(TestCase):
    def test_two_decimals_with_thousands_grouping(self):
        self.assertEqual(format_money(Decimal("1234.5")), "1,234.50")

    def test_rounds_half_up(self):
        self.assertEqual(format_money(Decimal("0.125")), "0.13")

    def test_empty_reads_as_zero(self):
        self.assertEqual(format_money(None), "0.00")

    def test_matches_the_dashboard_helper_it_replaced(self):
        from common.views import _money

        self.assertEqual(_money(Decimal("98765.4")), "98,765.40")


class HelpTextTranslationTests(TestCase):
    """dlux ships generic `help_<field>` keys written for its own user forms."""

    def test_dlux_account_wording_does_not_leak_onto_a_project_model(self):
        class CategoryForm(forms.ModelForm):
            class Meta:
                model = Category
                fields = ["name", "is_active"]

        form = CategoryForm()
        translate_help_text(form)
        # dlux's help_is_active reads "Unselect this instead of deleting
        # accounts." — true of a user account, nonsense on a product category.
        self.assertNotIn(
            "deleting accounts", (form.fields["is_active"].help_text or "")
        )

    def test_a_model_specific_key_still_applies(self):
        from catalog.models import Product

        class ProductForm(forms.ModelForm):
            class Meta:
                model = Product
                fields = ["name", "sku"]

        form = ProductForm()
        translate_help_text(form)
        self.assertEqual(
            form.fields["sku"].help_text, "Leave blank to auto-generate."
        )


class InvoiceDateFilter(DatedFilterSet):
    date_field = "invoice_date"

    class Meta:
        model = Invoice
        fields = []


class InvoiceCreatedFilter(DatedFilterSet):
    date_field = "created_at"

    class Meta:
        model = Invoice
        fields = []


class DatedFilterSetTests(TestCase):
    def setUp(self):
        self.old = Invoice.objects.create(customer_name="Old")
        Invoice.objects.filter(pk=self.old.pk).update(invoice_date=date(2024, 3, 4))
        self.new = Invoice.objects.create(customer_name="New")
        Invoice.objects.filter(pk=self.new.pk).update(invoice_date=date(2026, 5, 6))

    def _qs(self):
        return Invoice.objects.all()

    def test_year_choices_are_newest_first_and_only_years_with_rows(self):
        self.assertEqual(
            year_choices(self._qs(), "invoice_date"), [("2026", "2026"), ("2024", "2024")]
        )

    def test_year_choices_come_from_the_queryset_not_the_whole_table(self):
        # The visible set is what a rep may see; a year behind rows they cannot
        # open must not appear in their dropdown.
        visible = Invoice.objects.filter(pk=self.new.pk)
        self.assertEqual(year_choices(visible, "invoice_date"), [("2026", "2026")])

    def test_the_year_dropdown_is_populated_from_the_bound_queryset(self):
        fs = InvoiceDateFilter({}, queryset=Invoice.objects.filter(pk=self.old.pk))
        self.assertEqual(
            [c for c in fs.form.fields["year"].choices if c[0]], [("2024", "2024")]
        )

    def test_year_narrows_to_that_year(self):
        fs = InvoiceDateFilter({"year": "2026"}, queryset=self._qs())
        self.assertEqual(list(fs.qs), [self.new])

    def test_date_range_is_inclusive_on_both_ends(self):
        fs = InvoiceDateFilter(
            {"date_gte": "2026-05-06", "date_lte": "2026-05-06"}, queryset=self._qs()
        )
        self.assertEqual(list(fs.qs), [self.new])

    def test_a_datetime_field_compares_by_date_not_by_instant(self):
        # created_at is a DateTimeField: without the `__date` transform, a row
        # created at 14:00 today is excluded by `date_lte=today`.
        #
        # localtime() and not .date(): `__date` is evaluated in the active
        # timezone, so between 22:00 UTC and midnight the stored UTC date is
        # already yesterday in Africa/Tripoli and this asserted the wrong day.
        today = timezone.localtime(self.new.created_at).date()
        fs = InvoiceCreatedFilter({"date_lte": today.isoformat()}, queryset=self._qs())
        self.assertIn(self.new, list(fs.qs))

    def test_an_empty_value_leaves_the_queryset_alone(self):
        fs = InvoiceDateFilter({"year": "", "date_gte": ""}, queryset=self._qs())
        self.assertEqual(fs.qs.count(), 2)


class ScopedListAccessTests(TestCase):
    """An expired session is a login problem, not a permissions problem."""

    def setUp(self):
        from dlux.models import SystemSettings

        # dlux bounces every staff request to the login screen until the system
        # is marked configured, which would mask the distinction under test.
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])

    def test_anonymous_visitor_is_sent_to_the_login_page(self):
        resp = self.client.get(reverse("sales:customer_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])

    def test_signed_in_user_without_the_permission_still_gets_403(self):
        user = User.objects.create_user("nobody", password="x")
        self.client.force_login(user)
        resp = self.client.get(reverse("sales:customer_list"))
        self.assertEqual(resp.status_code, 403)


class ModalRowActionsTests(TestCase):
    """Row menus open a dlux modal directly, not via the record-event fallback."""

    def setUp(self):
        self.user = User.objects.create_superuser("rows", "r@o.w", "x")
        self.customer = Customer.objects.create(name="Row Co")

    def _actions(self, table_class, record):
        from django.contrib.auth.models import AnonymousUser

        table = table_class([])
        request = rf.get("/")
        request.user = self.user
        table.request = request
        base = [{"label": "Delete", "event": "dlux:record:delete"}]
        return table.get_dlux_row_actions(record, base)

    def test_view_and_edit_dispatch_the_dynamic_modal_event(self):
        from sales.tables import CustomerTable

        actions = self._actions(CustomerTable, self.customer)
        events = [a.get("event") for a in actions if a.get("event")]
        self.assertIn("dlux:dynamic_modal:open", events)
        # The generic record events are what dlux falls back to; only delete
        # should still ride on one.
        self.assertNotIn("dlux:record:view", events)
        self.assertNotIn("dlux:record:edit", events)

    def test_view_is_the_double_click_action_and_carries_the_view_flag(self):
        from sales.tables import CustomerTable

        view = self._actions(CustomerTable, self.customer)[0]
        self.assertTrue(view.get("dblclick"))
        self.assertIn("?action=view", view["data"]["url"])

    def test_edit_is_gated_on_the_models_change_permission(self):
        from sales.tables import CustomerTable

        edit = next(
            a for a in self._actions(CustomerTable, self.customer)
            if a.get("data") and "action=view" not in a["data"]["url"]
        )
        self.assertEqual(edit["permissions"], ["sales.change_customer"])

    def test_delete_is_kept_from_the_base_actions(self):
        from sales.tables import CustomerTable

        actions = self._actions(CustomerTable, self.customer)
        self.assertIn("dlux:record:delete", [a.get("event") for a in actions])

    def test_the_sections_manager_page_keeps_its_own_row_actions(self):
        from sales.tables import CustomerTable

        table = CustomerTable([])
        request = rf.get("/")
        request.user = self.user
        request.resolver_match = type("M", (), {"url_name": "manage_sections"})()
        table.request = request
        base = [{"label": "Edit", "event": "dlux:record:edit"}]
        # That page edits in its own expanding form; a modal would talk over it.
        self.assertEqual(table.get_dlux_row_actions(self.customer, base), base)


class DocumentEditorAuditTests(TestCase):
    """A new document logs CREATE, an edited one logs UPDATE.

    Asserted against the editor's own `log_user_action` call rather than the
    ActivityLog table: dlux writes its own rows for scoped-model CRUD, and
    `recalc_totals()` adds another, so the table cannot say which entry the
    editor wrote.
    """

    def setUp(self):
        from django.contrib.auth.models import Permission
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        self.user = User.objects.create_user("editor", password="x")
        self.user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="sales",
                codename__in=["add_invoice", "change_invoice", "view_invoice"],
            )
        )
        self.client.force_login(self.user)

    def _post(self, url, **extra):
        data = {
            "customer_name": "Ledger Buyer",
            "customer_phone": "",
            "customer_address": "",
            "invoice_date": "2026-09-02",
            "discount_percent": "0",
            "discount_amount": "0",
            "notes": "",
            "items-TOTAL_FORMS": "0",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
        }
        data.update(extra)
        with mock.patch("common.editors.log_user_action") as logged:
            response = self.client.post(url, data)
        actions = [call.args[1] for call in logged.call_args_list]
        return response, actions

    def test_creating_an_invoice_logs_create_not_update(self):
        response, actions = self._post(reverse("sales:invoice_create"))
        self.assertEqual(response.status_code, 302)
        # The old editor read `invoice.pk` after save(), so this was "UPDATE"
        # for every invoice ever created.
        self.assertEqual(actions, ["CREATE"])

    def test_editing_an_invoice_logs_update(self):
        self._post(reverse("sales:invoice_create"))
        invoice = Invoice.objects.get(customer_name="Ledger Buyer")
        _, actions = self._post(reverse("sales:invoice_edit", args=[invoice.pk]))
        self.assertEqual(actions, ["UPDATE"])


class SyncPartyTests(TestCase):
    """One helper binds a document to its party, both directions."""

    def _invoice(self, **kwargs):
        return Invoice(
            customer_name=kwargs.get("name", ""),
            customer_phone=kwargs.get("phone", ""),
            customer_address=kwargs.get("address", ""),
        )

    def _sync(self, invoice, queryset=None):
        from common.editors import sync_party

        sync_party(
            invoice, prefix="customer", party_model=Customer, queryset=queryset,
        )
        return invoice

    def test_a_new_name_creates_a_reusable_party(self):
        invoice = self._sync(self._invoice(name="Brand New", phone="0910"))
        self.assertIsNotNone(invoice.customer)
        self.assertEqual(invoice.customer.name, "Brand New")
        # Saved for reuse, not left living only on the document.
        self.assertTrue(Customer.objects.filter(name="Brand New").exists())

    def test_an_existing_name_is_reused_case_insensitively(self):
        existing = Customer.objects.create(name="Acme")
        invoice = self._sync(self._invoice(name="acme"))
        self.assertEqual(invoice.customer, existing)
        self.assertEqual(Customer.objects.filter(name__iexact="acme").count(), 1)

    def test_the_document_snapshot_is_filled_from_the_party(self):
        Customer.objects.create(name="Acme", phone="0921", address="Tripoli")
        invoice = self._sync(self._invoice(name="Acme"))
        self.assertEqual(invoice.customer_phone, "0921")
        self.assertEqual(invoice.customer_address, "Tripoli")

    def test_typed_details_backfill_the_partys_blanks(self):
        existing = Customer.objects.create(name="Acme")
        self._sync(self._invoice(name="Acme", phone="0930", address="Benghazi"))
        existing.refresh_from_db()
        self.assertEqual((existing.phone, existing.address), ("0930", "Benghazi"))

    def test_an_existing_party_value_is_never_clobbered(self):
        existing = Customer.objects.create(name="Acme", phone="0921")
        self._sync(self._invoice(name="Acme", phone="0999"))
        existing.refresh_from_db()
        self.assertEqual(existing.phone, "0921")

    def test_a_nameless_walk_in_binds_nothing(self):
        invoice = self._sync(self._invoice())
        self.assertIsNone(invoice.customer)
        self.assertEqual(Customer.objects.count(), 0)

    def test_the_queryset_scopes_which_parties_can_be_matched(self):
        other_rep = User.objects.create_user("other", password="x")
        Customer.objects.create(name="Acme", created_by=other_rep)
        # Matching only within an empty book creates a fresh record instead of
        # binding to one this user cannot see.
        invoice = self._sync(self._invoice(name="Acme"), queryset=Customer.objects.none())
        self.assertEqual(Customer.objects.filter(name="Acme").count(), 2)
        self.assertNotEqual(invoice.customer.created_by, other_rep)

    def test_it_works_the_same_for_suppliers(self):
        from catalog.models import PurchaseInvoice, Supplier
        from common.editors import sync_party

        purchase = PurchaseInvoice(supplier_name="Widget Co", supplier_phone="0940")
        sync_party(purchase, prefix="supplier", party_model=Supplier)
        self.assertEqual(purchase.supplier.name, "Widget Co")
        self.assertEqual(Supplier.objects.get(name="Widget Co").phone, "0940")


class AdoptedDatedFiltersTests(TestCase):
    """The three lists that gained a year jump and a date range."""

    def test_invoice_filter_exposes_year_and_the_renamed_range(self):
        from sales.filters import InvoiceFilter

        fields = InvoiceFilter({}, queryset=Invoice.objects.all()).form.fields
        self.assertIn("year", fields)
        self.assertIn("date_gte", fields)
        self.assertIn("date_lte", fields)
        # Renamed deliberately: `set_field_attrs` keys its From/To labels off
        # the `_gte`/`_lte` suffixes. Old bookmarked URLs lose their filter.
        self.assertNotIn("date_from", fields)

    def test_the_year_jump_sits_in_the_ribbons_own_row(self):
        from sales.views import InvoiceListView

        view = InvoiceListView()
        request = rf.get("/")
        request.user = User.objects.create_superuser("dates", "d@t.e", "x")
        view.request, view.args, view.kwargs = request, (), {}
        self.assertIn("year", view.ribbon_primary)
        self.assertIn("date_gte", view.ribbon_advanced)

    def test_a_datetime_dated_list_compares_by_calendar_day(self):
        from sales.filters import PaymentFilter
        from sales.models import Payment

        # paid_at is a DateTimeField; without the `__date` transform a payment
        # taken at 14:00 falls outside date_lte set to that same day.
        self.assertEqual(PaymentFilter.date_field, "paid_at")
        fs = PaymentFilter({}, queryset=Payment.objects.all())
        self.assertEqual(fs._lookup("lte"), "paid_at__date__lte")

    def test_expense_dates_need_no_transform(self):
        from finance.filters import ExpenseFilter
        from finance.models import Expense

        fs = ExpenseFilter({}, queryset=Expense.objects.all())
        self.assertEqual(fs._lookup("gte"), "expense_date__gte")
