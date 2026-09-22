"""
Finance domain models.

This app is the monetary foundation of the system. Everything that needs to
convert between USD (how Switch imports & thinks about cost) and LYD (how Switch
sells locally) reuses the single global black-market exchange rate defined here.

Layering: ``finance`` has no dependency on ``catalog`` or ``sales`` — they depend
on it. Keep it that way.
"""
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone
from django.urls import reverse

from dlux.models import ScopedModel

# Cache key retained for the live USD->LYD rate; EUR uses its own keyed value.
CURRENT_RATE_CACHE_KEY = "finance:current_usd_lyd_rate"
CURRENT_RATE_CACHE_TTL = 60 * 60  # 1h; bounded by explicit invalidation on save.


def current_rate_cache_key(currency):
    currency = str(currency).upper()
    return CURRENT_RATE_CACHE_KEY if currency == "USD" else f"finance:current_{currency.lower()}_lyd_rate"


class ExchangeRate(ScopedModel):
    """Append-only history of USD/EUR -> LYD conversion rates.

    The newest row is the *live* rate used everywhere prices are computed. Past
    rows are never edited, so the system keeps a full audit trail of how the
    black-market rate moved over time (``created_at`` / ``created_by`` come from
    ``ScopedModel``). Invoices freeze their own copy of the rate, so editing or
    adding a rate here never rewrites historical invoice totals.
    """

    SOURCE_BLACK_MARKET = "black_market"
    SOURCE_OFFICIAL = "official"
    SOURCE_CUSTOM = "custom"
    SOURCE_CHOICES = (
        (SOURCE_BLACK_MARKET, "Black Market"),
        (SOURCE_OFFICIAL, "Official"),
        (SOURCE_CUSTOM, "Custom"),
    )

    CURRENCY_USD = "USD"
    CURRENCY_EUR = "EUR"
    CURRENCY_CHOICES = (
        (CURRENCY_USD, "US Dollar (USD)"),
        (CURRENCY_EUR, "Euro (EUR)"),
    )

    currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default=CURRENCY_USD,
        db_index=True,
        verbose_name="Currency",
    )

    rate = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
        verbose_name="LYD per 1 unit",
        help_text="How many Libyan Dinars equal one unit of the selected currency.",
    )
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_BLACK_MARKET,
        verbose_name="Source",
    )
    note = models.CharField(max_length=255, blank=True, verbose_name="Note")

    class Meta:
        verbose_name = "Exchange Rate"
        verbose_name_plural = "Exchange Rates"
        ordering = ["-created_at"]
        permissions = [("manage_exchangerate", "Can set the global exchange rate")]

    def __str__(self):
        return f"1 {self.currency} = {self.rate} LYD"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # The newest row is authoritative; refresh the cached live rate.
        if not self.deleted_at:
            cache.set(current_rate_cache_key(self.currency), self.rate, CURRENT_RATE_CACHE_TTL)


class CashDeposit(ScopedModel):
    """A cash hand-over recorded by a staff member (ايداع نقدي).

    Technicians and delivery reps record the money they collected; an admin then
    confirms it. Payments on invoices may optionally point at the deposit that
    carried their cash, so the books reconcile.

    Row-level visibility: a staff member sees only the deposits they recorded;
    an admin holding ``view_all_cashdeposit`` (typically paired with
    ``confirm_cashdeposit``) sees and reconciles everyone's. See ``common.access``.
    """

    #: Row-ownership lookups consumed by common.access.apply_ownership.
    OWNER_FIELDS = ("created_by",)

    METHOD_CASH = "cash"
    METHOD_BANK = "bank_transfer"
    METHOD_CHEQUE = "cheque"
    METHOD_CHOICES = (
        (METHOD_CASH, "Cash"),
        (METHOD_BANK, "Bank Transfer"),
        (METHOD_CHEQUE, "Cheque"),
    )

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_REJECTED, "Rejected"),
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Amount (LYD)",
    )
    method = models.CharField(
        max_length=20, choices=METHOD_CHOICES, default=METHOD_CASH, verbose_name="Method"
    )
    reference = models.CharField(max_length=120, blank=True, verbose_name="Reference")
    deposited_at = models.DateField(default=timezone.localdate, verbose_name="Deposit Date")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
        verbose_name="Status",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="confirmed_cash_deposits",
        on_delete=models.SET_NULL,
        editable=False,
        verbose_name="Confirmed By",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Confirmed At")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Cash Deposit"
        verbose_name_plural = "Cash Deposits"
        ordering = ["-deposited_at", "-created_at"]
        permissions = [
            ("confirm_cashdeposit", "Can confirm or reject cash deposits"),
            ("view_all_cashdeposit", "Can view all cash deposits (not just own)"),
        ]

    def __str__(self):
        return f"{self.amount} LYD ({self.get_status_display()})"

    def recalc_amount(self, commit=True):
        """Batch total = sum of the invoice Payments linked to this deposit.

        Called from ``Payment.save()/delete()`` so a deposit that acts as a
        payment batch always reflects the cash it carries. Standalone deposits
        (no linked payments) keep their manually-entered amount — this is never
        called for them.
        """
        total = self.payments.aggregate(t=models.Sum("amount"))["t"] or Decimal("0.00")
        self.amount = total
        if commit:
            self.save(update_fields=["amount", "updated_at"])

    def confirm(self, actor):
        self.status = self.STATUS_CONFIRMED
        self.confirmed_by = actor
        self.confirmed_at = timezone.now()
        self.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])

    def reject(self, actor):
        self.status = self.STATUS_REJECTED
        self.confirmed_by = actor
        self.confirmed_at = timezone.now()
        self.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])


class ExpenseCategory(ScopedModel):
    name = models.CharField(max_length=120, verbose_name="Name")
    description = models.TextField(blank=True, verbose_name="Description")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Expense Category"
        verbose_name_plural = "Expense Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Expense(ScopedModel):
    """A posted operating cost. Kept in finance so P&L can subtract it without
    making catalog/sales responsible for generic business expenses."""

    OWNER_FIELDS = ("paid_by", "created_by")

    METHOD_CASH = "cash"
    METHOD_BANK = "bank_transfer"
    METHOD_CHEQUE = "cheque"
    METHOD_OTHER = "other"
    METHOD_CHOICES = (
        (METHOD_CASH, "Cash"),
        (METHOD_BANK, "Bank Transfer"),
        (METHOD_CHEQUE, "Cheque"),
        (METHOD_OTHER, "Other"),
    )

    STATUS_DRAFT = "draft"
    STATUS_POSTED = "posted"
    STATUS_VOID = "void"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_POSTED, "Posted"),
        (STATUS_VOID, "Void"),
    )

    category = models.ForeignKey(
        ExpenseCategory, null=True, blank=True, on_delete=models.PROTECT,
        related_name="expenses", verbose_name="Category",
    )
    amount_lyd = models.DecimalField(
        max_digits=14, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))], verbose_name="Amount (LYD)",
    )
    expense_date = models.DateField(default=timezone.localdate, verbose_name="Expense Date")
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_CASH, verbose_name="Method")
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="paid_expenses", verbose_name="Paid By",
    )
    reference = models.CharField(max_length=120, blank=True, verbose_name="Reference")
    attachment = models.FileField(upload_to="finance/expenses/", blank=True, verbose_name="Receipt / Attachment")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_POSTED, db_index=True, verbose_name="Status")
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="posted_expenses", editable=False, verbose_name="Posted By",
    )
    posted_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Posted At")
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="voided_expenses", editable=False, verbose_name="Voided By",
    )
    voided_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Voided At")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Expense"
        verbose_name_plural = "Expenses"
        ordering = ["-expense_date", "-created_at"]
        permissions = [
            ("post_expense", "Can post or void expenses"),
            ("view_all_expense", "Can view all expenses (not just own)"),
        ]

    def __str__(self):
        label = self.category.name if self.category_id else "Expense"
        return f"{label} — {self.amount_lyd} LYD"

    def save(self, *args, **kwargs):
        if self.status == self.STATUS_POSTED and self.posted_at is None:
            self.posted_at = timezone.now()
        super().save(*args, **kwargs)

    def post(self, actor):
        self.status = self.STATUS_POSTED
        self.posted_by = actor
        self.posted_at = timezone.now()
        self.save(update_fields=["status", "posted_by", "posted_at", "updated_at"])

    def void(self, actor):
        self.status = self.STATUS_VOID
        self.voided_by = actor
        self.voided_at = timezone.now()
        self.save(update_fields=["status", "voided_by", "voided_at", "updated_at"])


class StaffAccount(ScopedModel):
    """A per-user running account. Balance is derived from posted ledger rows:
    positive means the company owes the user; negative means the user owes the
    company."""

    OWNER_FIELDS = ("user",)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="finance_staff_account", verbose_name="User",
    )
    is_active = models.BooleanField(default=True, verbose_name="Active")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Staff Account"
        verbose_name_plural = "Staff Accounts"
        ordering = ["user__username"]
        permissions = [("view_all_staffaccount", "Can view all staff accounts")]

    def __str__(self):
        return getattr(self.user, "get_full_name", lambda: "")() or self.user.get_username()

    @classmethod
    def for_user(cls, user):
        account, _created = cls.objects.get_or_create(user=user)
        return account

    @property
    def balance_lyd(self):
        return self.entries.filter(status=StaffLedgerEntry.STATUS_POSTED).aggregate(
            total=Sum("signed_amount")
        )["total"] or Decimal("0.00")

    @property
    def pending_count(self):
        return self.entries.filter(status=StaffLedgerEntry.STATUS_PENDING_USER).count()


class StaffLedgerEntry(ScopedModel):
    """Append-only staff-account row. Posted rows affect balance; pending rows
    wait for the staff member's confirmation."""

    OWNER_FIELDS = ("account__user", "created_by")

    TYPE_SERVICE_EARNED = "service_earned"
    TYPE_REIMBURSEMENT = "reimbursement"
    TYPE_ADVANCE = "advance"
    TYPE_LOAN = "loan"
    TYPE_CASH_CHECKOUT = "cash_checkout"
    TYPE_ITEM_CHECKOUT = "item_checkout"
    TYPE_PAY_STAFF = "pay_staff"
    TYPE_RECEIVE_FROM_STAFF = "receive_from_staff"
    TYPE_ADJUSTMENT = "adjustment"
    ENTRY_TYPE_CHOICES = (
        (TYPE_SERVICE_EARNED, "Service / commission earned"),
        (TYPE_REIMBURSEMENT, "Reimbursement due"),
        (TYPE_ADVANCE, "Advance given"),
        (TYPE_LOAN, "Loan given"),
        (TYPE_CASH_CHECKOUT, "Cash checked out"),
        (TYPE_ITEM_CHECKOUT, "Item checked out"),
        (TYPE_PAY_STAFF, "Payment to staff"),
        (TYPE_RECEIVE_FROM_STAFF, "Payment from staff"),
        (TYPE_ADJUSTMENT, "Manual adjustment"),
    )

    STATUS_PENDING_USER = "pending_user"
    STATUS_POSTED = "posted"
    STATUS_DISPUTED = "disputed"
    STATUS_VOID = "void"
    STATUS_CHOICES = (
        (STATUS_PENDING_USER, "Pending user confirmation"),
        (STATUS_POSTED, "Posted"),
        (STATUS_DISPUTED, "Disputed"),
        (STATUS_VOID, "Void"),
    )

    POSITIVE_TYPES = {TYPE_SERVICE_EARNED, TYPE_REIMBURSEMENT, TYPE_RECEIVE_FROM_STAFF, TYPE_ADJUSTMENT}
    NEGATIVE_TYPES = {TYPE_ADVANCE, TYPE_LOAN, TYPE_CASH_CHECKOUT, TYPE_ITEM_CHECKOUT, TYPE_PAY_STAFF}

    account = models.ForeignKey(
        StaffAccount, on_delete=models.PROTECT,
        related_name="entries", verbose_name="Staff Account",
    )
    entry_type = models.CharField(max_length=32, choices=ENTRY_TYPE_CHOICES, verbose_name="Type")
    amount_lyd = models.DecimalField(
        max_digits=14, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))], verbose_name="Amount (LYD)",
    )
    signed_amount = models.DecimalField(max_digits=14, decimal_places=2, editable=False, verbose_name="Signed Amount")
    entry_date = models.DateField(default=timezone.localdate, verbose_name="Date")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING_USER,
        db_index=True, verbose_name="Status",
    )
    reference = models.CharField(max_length=140, blank=True, verbose_name="Reference")
    notes = models.TextField(blank=True, verbose_name="Notes")
    requires_user_confirmation = models.BooleanField(default=True, verbose_name="Require User Confirmation")
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="confirmed_staff_entries", editable=False, verbose_name="Confirmed By",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Confirmed At")
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="posted_staff_entries", editable=False, verbose_name="Posted By",
    )
    posted_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Posted At")
    disputed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="disputed_staff_entries", editable=False, verbose_name="Disputed By",
    )
    disputed_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Disputed At")
    notified_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Notified At")

    class Meta:
        verbose_name = "Staff Ledger Entry"
        verbose_name_plural = "Staff Ledger Entries"
        ordering = ["-entry_date", "-created_at"]
        permissions = [
            ("resolve_staffledgerentry", "Can post, void, or resolve staff ledger entries"),
            ("view_all_staffledgerentry", "Can view all staff ledger entries"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_lyd__gt=0),
                name="finance_staffentry_amount_positive",
            ),
        ]

    def __str__(self):
        return f"{self.account} — {self.amount_lyd} LYD"

    def _signed(self):
        sign = Decimal("1") if self.entry_type in self.POSITIVE_TYPES else Decimal("-1")
        return (self.amount_lyd or Decimal("0.00")) * sign

    def save(self, *args, **kwargs):
        self.signed_amount = self._signed()
        if not self.requires_user_confirmation and self.status == self.STATUS_PENDING_USER:
            self.status = self.STATUS_POSTED
            self.posted_at = self.posted_at or timezone.now()
            self.posted_by = self.posted_by or self.created_by
        super().save(*args, **kwargs)
        self._notify_pending_user()

    @property
    def entry_type_key(self):
        return f"staff_entry_type_{self.entry_type}"

    @property
    def status_key(self):
        return f"staff_entry_status_{self.status}"

    @property
    def status_label(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    def _notify_pending_user(self):
        if self.status != self.STATUS_PENDING_USER or self.notified_at or not self.account_id:
            return
        user = self.account.user
        if not getattr(user, "is_active", False):
            return
        try:
            from dlux.notifications import notify
            notify.warning(
                f"Staff account entry needs your confirmation: {self.amount_lyd} LYD",
                title="Staff account confirmation",
                category="staff_account",
                source="finance",
                action="confirm_staff_entry",
                obj=self,
                recipients=[user],
                persist=True,
                target_url=reverse("finance:staff_account_detail", args=[self.account_id]),
                metadata={"entry_id": self.pk},
            )
        except Exception:
            return
        self.notified_at = timezone.now()
        StaffLedgerEntry.objects.filter(pk=self.pk).update(notified_at=self.notified_at)

    def confirm(self, actor):
        self.status = self.STATUS_POSTED
        self.confirmed_by = actor
        self.confirmed_at = timezone.now()
        self.posted_by = actor
        self.posted_at = self.confirmed_at
        self.save(update_fields=[
            "status", "confirmed_by", "confirmed_at", "posted_by", "posted_at",
            "signed_amount", "updated_at",
        ])

    def dispute(self, actor):
        self.status = self.STATUS_DISPUTED
        self.disputed_by = actor
        self.disputed_at = timezone.now()
        self.save(update_fields=["status", "disputed_by", "disputed_at", "signed_amount", "updated_at"])

    def void(self, actor):
        self.status = self.STATUS_VOID
        self.posted_by = actor
        self.posted_at = timezone.now()
        self.save(update_fields=["status", "posted_by", "posted_at", "signed_amount", "updated_at"])
