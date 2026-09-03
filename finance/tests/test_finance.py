from unittest import mock
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TestCase

from common.forms import translate_choice_fields

from ..urls import app_name
from .. import services
from ..models import StaffAccount, StaffLedgerEntry
from ..translations import DLUX_STRINGS as FINANCE_STRINGS

User = get_user_model()


class ChoiceTranslationTests(SimpleTestCase):
    """common.forms.translate_choice_fields localizes dropdown option labels."""

    def test_translates_options_keeps_single_placeholder(self):
        class F(forms.Form):
            method = forms.ChoiceField(
                choices=[("", "Method"), ("cash", "x"), ("cheque", "y")]
            )

        form = F()
        translate_choice_fields(form)
        rendered = list(form.fields["method"].widget.choices)
        # First-choice placeholder label is preserved, not duplicated.
        self.assertEqual(rendered[0], ("", "Method"))
        self.assertEqual([v for v, _ in rendered].count(""), 1)
        # Values untouched; labels resolved from the choice_<value> keys.
        self.assertEqual([v for v, _ in rendered], ["", "cash", "cheque"])
        self.assertEqual(dict(rendered)["cash"], "Cash")
        self.assertEqual(dict(rendered)["cheque"], "Cheque")


class FinanceConfigScaffoldTests(SimpleTestCase):
    def test_urls_namespace_matches_app_name(self):
        self.assertEqual(app_name, "finance")

    def test_finance_translations_keep_english_arabic_key_parity(self):
        self.assertEqual(set(FINANCE_STRINGS["en"]), set(FINANCE_STRINGS["ar"]))


class StaffLedgerTests(TestCase):
    def setUp(self):
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        self.manager = User.objects.create_user("manager", password="x")
        self.staff = User.objects.create_user("staff", password="x")
        # dlux only delivers a notification to a recipient who could open the
        # object it points at (`_recipient_can_view_event`), so the staff user
        # needs the same view permission `seed_roles` grants the Rep and Courier
        # groups. Row-scoping still limits them to their own entries.
        self.staff.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="finance",
                codename="view_staffledgerentry",
            )
        )
        self.staff = User.objects.get(pk=self.staff.pk)
        self.account = StaffAccount.for_user(self.staff)

    def test_balance_counts_posted_signed_entries_only(self):
        earned = StaffLedgerEntry.objects.create(
            account=self.account,
            entry_type=StaffLedgerEntry.TYPE_SERVICE_EARNED,
            amount_lyd=Decimal("100.00"),
            requires_user_confirmation=False,
            created_by=self.manager,
        )
        advance = StaffLedgerEntry.objects.create(
            account=self.account,
            entry_type=StaffLedgerEntry.TYPE_ADVANCE,
            amount_lyd=Decimal("40.00"),
            created_by=self.manager,
        )

        earned.refresh_from_db()
        advance.refresh_from_db()
        self.assertEqual(earned.status, StaffLedgerEntry.STATUS_POSTED)
        self.assertEqual(earned.signed_amount, Decimal("100.00"))
        self.assertEqual(advance.status, StaffLedgerEntry.STATUS_PENDING_USER)
        self.assertEqual(advance.signed_amount, Decimal("-40.00"))
        self.assertEqual(self.account.balance_lyd, Decimal("100.00"))

        advance.confirm(self.staff)
        self.assertEqual(self.account.balance_lyd, Decimal("60.00"))

    def test_balance_matrix_for_all_signed_entry_types_and_statuses(self):
        posted_rows = [
            (StaffLedgerEntry.TYPE_SERVICE_EARNED, Decimal("100.10")),
            (StaffLedgerEntry.TYPE_REIMBURSEMENT, Decimal("25.25")),
            (StaffLedgerEntry.TYPE_RECEIVE_FROM_STAFF, Decimal("14.65")),
            (StaffLedgerEntry.TYPE_ADJUSTMENT, Decimal("10.00")),
            (StaffLedgerEntry.TYPE_ADVANCE, Decimal("20.05")),
            (StaffLedgerEntry.TYPE_LOAN, Decimal("30.10")),
            (StaffLedgerEntry.TYPE_CASH_CHECKOUT, Decimal("40.15")),
            (StaffLedgerEntry.TYPE_ITEM_CHECKOUT, Decimal("50.20")),
            (StaffLedgerEntry.TYPE_PAY_STAFF, Decimal("60.25")),
        ]
        for entry_type, amount in posted_rows:
            StaffLedgerEntry.objects.create(
                account=self.account,
                entry_type=entry_type,
                amount_lyd=amount,
                requires_user_confirmation=False,
                created_by=self.manager,
            )
        StaffLedgerEntry.objects.create(
            account=self.account,
            entry_type=StaffLedgerEntry.TYPE_ADVANCE,
            amount_lyd=Decimal("999.99"),
            created_by=self.manager,
        )
        disputed = StaffLedgerEntry.objects.create(
            account=self.account,
            entry_type=StaffLedgerEntry.TYPE_SERVICE_EARNED,
            amount_lyd=Decimal("777.77"),
            requires_user_confirmation=False,
            created_by=self.manager,
        )
        disputed.dispute(self.staff)
        void = StaffLedgerEntry.objects.create(
            account=self.account,
            entry_type=StaffLedgerEntry.TYPE_REIMBURSEMENT,
            amount_lyd=Decimal("333.33"),
            requires_user_confirmation=False,
            created_by=self.manager,
        )
        void.void(self.manager)

        self.assertEqual(self.account.balance_lyd, Decimal("-50.75"))
        self.assertEqual(self.account.pending_count, 1)

    def test_pending_entry_notifies_the_staff_user(self):
        from dlux.models import DluxNotificationState

        entry = StaffLedgerEntry.objects.create(
            account=self.account,
            entry_type=StaffLedgerEntry.TYPE_LOAN,
            amount_lyd=Decimal("25.00"),
            created_by=self.manager,
        )

        entry.refresh_from_db()
        self.assertIsNotNone(entry.notified_at)
        self.assertTrue(
            DluxNotificationState.objects.filter(
                user=self.staff,
                notification__source="finance",
                notification__action="confirm_staff_entry",
            ).exists()
        )


# A trimmed sample of the CBL currency table (USD row, as served) so the scraper
# is exercised without a live network call.
_CBL_SAMPLE = """
<table id="currency-table">
<tr><th>التاريخ</th><th>العملة</th></tr>
<tr>
  <td><span class="uk-text-bold">التاريخ: </span>2026-07-02</td>
  <td><span class="uk-text-bold">العملة: </span>الدولار الأمريكي</td>
  <td><span class="uk-text-bold">المتوسط: </span>6.4117&nbspد.ل</td>
  <td><span class="uk-text-bold">بيع: </span>6.4277&nbspد.ل</td>
  <td><span class="uk-text-bold">شراء: </span>6.3956&nbspد.ل</td>
</tr>
<tr>
  <td><span>العملة: </span>الدولار الكندي</td>
  <td><span>المتوسط: </span>4.5118&nbspد.ل</td>
</tr>
</table>
"""


class CblRateScraperTests(SimpleTestCase):
    def test_parses_usd_row(self):
        fake = mock.Mock()
        fake.read.return_value = _CBL_SAMPLE.encode("utf-8")
        fake.__enter__ = lambda s: s
        fake.__exit__ = lambda *a: False
        with mock.patch("urllib.request.urlopen", return_value=fake):
            data = services.fetch_cbl_usd_rate()
        self.assertIsNotNone(data)
        # Must pick the American-dollar row, not the Canadian one below it.
        self.assertEqual(data["average"], "6.4117")
        self.assertEqual(data["sell"], "6.4277")
        self.assertEqual(data["buy"], "6.3956")
        self.assertEqual(data["date"], "2026-07-02")

    def test_returns_none_on_network_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            self.assertIsNone(services.fetch_cbl_usd_rate())


# A trimmed sample of the eanlibya table: the dollar row (with a "down" trend
# arrow whose `fa-2x` class must not be mistaken for the rate) plus a euro row.
_EAN_SAMPLE = """
<table>
<tr><th class="column-1"></th><th class="column-2">العملة</th><th class="column-3">السعر</th></tr>
<tr>
  <td class="column-1"><img alt="الدولار"></td>
  <td class="column-2">الدولار</td>
  <td class="column-3"><i class="far fa-arrow-alt-circle-down fa-2x" style="color:red"></i> 8.50</td>
</tr>
<tr>
  <td class="column-1"><img alt="اليورو"></td>
  <td class="column-2">اليورو</td>
  <td class="column-3"><i class="far fa-arrow-alt-circle-up fa-2x" style="color:green"></i> 9.71</td>
</tr>
</table>
"""


class EanRateScraperTests(SimpleTestCase):
    def test_parses_dollar_row(self):
        fake = mock.Mock()
        fake.read.return_value = _EAN_SAMPLE.encode("utf-8")
        fake.__enter__ = lambda s: s
        fake.__exit__ = lambda *a: False
        with mock.patch("urllib.request.urlopen", return_value=fake):
            data = services.fetch_ean_usd_rate()
        self.assertIsNotNone(data)
        self.assertEqual(data["rate"], "8.50")  # not "2" from fa-2x, not the euro 9.71
        self.assertEqual(data["trend"], "down")

    def test_returns_none_on_network_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            self.assertIsNone(services.fetch_ean_usd_rate())
