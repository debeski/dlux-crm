"""
Sales domain models — invoices and the money around them.

``sales`` sits at the top of the dependency stack: it may use ``catalog``
(Product / Service) and ``finance`` (the rate). Nothing depends on ``sales``.

Money rule of the house: every invoice **freezes** the USD→LYD rate it was
created with (``exchange_rate``) and every line **freezes** its own
``unit_price_lyd``. Later rate changes never rewrite a past invoice's totals.
"""
from decimal import Decimal, ROUND_HALF_UP
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from dlux.models import ScopedModel

from finance.currency import CURRENCY_CHOICES, pricing_currency
from finance.services import get_current_rate, quantize_lyd

TWO_PLACES = Decimal("0.01")


class Customer(ScopedModel):
    """A buyer. Optional on an invoice — walk-in sales just type a name.

    Customers are **private to the rep who created them** (row-level visibility):
    a sales rep sees only their own customer book, while a manager holding
    ``view_all_customer`` sees everyone's. See ``common.access``.
    """

    #: Row-ownership lookups consumed by common.access.apply_ownership.
    OWNER_FIELDS = ("created_by",)

    name = models.CharField(max_length=200, verbose_name="Name")
    phone = models.CharField(max_length=40, blank=True, db_index=True, verbose_name="Phone")
    address = models.CharField(max_length=255, blank=True, verbose_name="Address")
    notes = models.TextField(blank=True, verbose_name="Notes")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Customer"
        verbose_name_plural = "Customers"
        ordering = ["name"]
        permissions = [("view_all_customer", "Can view all customers (not just own)")]

    @property
    def credit_balance(self):
        return sum((entry.available_amount for entry in PaymentResolution.objects.filter(customer=self, action="credit")), Decimal("0.00"))

    def __str__(self):
        return self.name


class Invoice(ScopedModel):
    STATUS_DRAFT = "draft"
    STATUS_ISSUED = "issued"
    STATUS_PARTIAL = "partial"
    STATUS_PAID = "paid"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_ISSUED, "Issued"),
        (STATUS_PARTIAL, "Partially Paid"),
        (STATUS_PAID, "Paid"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    #: Row-ownership lookups consumed by common.access.apply_ownership. An
    #: invoice belongs to its assigned salesperson (falls back to whoever
    #: created it); managers hold ``view_all_invoice`` to see every rep's sales.
    OWNER_FIELDS = ("salesperson", "created_by")

    number = models.CharField(max_length=20, unique=True, blank=True, verbose_name="Invoice No.")
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="invoices_as_salesperson", verbose_name="Salesperson",
    )
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="invoices", verbose_name="Customer",
    )
    # Snapshot fields so historical invoices stay intact even if the customer
    # record is edited or removed later (walk-ins set these directly).
    customer_name = models.CharField(max_length=200, blank=True, verbose_name="Customer Name")
    customer_phone = models.CharField(max_length=40, blank=True, verbose_name="Customer Phone")
    customer_address = models.CharField(max_length=255, blank=True, verbose_name="Customer Address")

    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True,
        verbose_name="Status",
    )
    invoice_date = models.DateField(default=timezone.localdate, verbose_name="Invoice Date")

    # The pricing currency (USD/EUR) this invoice was made in, and its frozen rate.
    currency = models.CharField(
        max_length=3, choices=CURRENCY_CHOICES, default=pricing_currency, verbose_name="Currency",
    )
    exchange_rate = models.DecimalField(
        max_digits=12, decimal_places=4, verbose_name="Exchange Rate (LYD per unit)"
    )
    exchange_rate_obj = models.ForeignKey(
        "finance.ExchangeRate", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="invoices", editable=False, verbose_name="Rate Record",
    )

    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Discount %",
    )
    discount_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Discount (LYD)",
    )

    subtotal_lyd = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), editable=False, verbose_name="Subtotal (LYD)")
    total_lyd = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), editable=False, verbose_name="Total (LYD)")
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), editable=False, verbose_name="Amount Paid (LYD)")

    notes = models.TextField(blank=True, verbose_name="Notes")
    issued_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Issued At")

    class Meta:
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="sales_inv_status_idx"),
            models.Index(fields=["-invoice_date"], name="sales_inv_date_idx"),
        ]
        permissions = [
            ("issue_invoice", "Can issue (finalize) invoices"),
            ("cancel_invoice", "Can cancel invoices"),
            ("view_sales_report", "Can view sales reports"),
            ("view_all_invoice", "Can view all invoices (not just own)"),
            ("assign_salesperson", "Can assign an invoice's salesperson"),
            ("view_financial_report", "Can view the financial (fiscal-year) report"),
        ]

    def __str__(self):
        return self.number or f"(draft #{self.pk})"

    def save(self, *args, **kwargs):
        if self.exchange_rate is None:
            self.exchange_rate = get_current_rate()
        # Default the salesperson to the acting user on first save (a manager may
        # override it explicitly in the editor). Kept in sync with ScopedModel's
        # created_by so ownership works even for API/import creates with no form.
        if self.salesperson_id is None and self.pk is None:
            from dlux.middleware import get_current_user

            user = get_current_user()
            if user is not None and getattr(user, "is_authenticated", False):
                self.salesperson = user
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"INV-{self.pk:06d}"
            super().save(update_fields=["number"])

    # --- Derived display helpers ---
    @property
    def balance_due(self):
        if self.status == self.STATUS_CANCELLED:
            return Decimal("0.00")
        return quantize_lyd(self.total_lyd - self.amount_paid)

    @property
    def cash_received(self):
        return sum((p.amount for p in self.payments.all()), Decimal("0.00"))

    @property
    def cancellation_pending(self):
        if self.status != self.STATUS_CANCELLED:
            return Decimal("0.00")
        return sum((p.amount for p in self.payments.filter(resolution__isnull=True)), Decimal("0.00"))

    @property
    def credit_applied(self):
        return sum((entry.amount for entry in self.credit_uses.all()), Decimal("0.00"))

    @property
    def display_customer(self):
        if self.customer_id:
            return self.customer.name
        if self.customer_name:
            return self.customer_name
        from common.i18n import t
        return t("ui_walk_in", "Walk-in")

    @property
    def is_editable(self):
        """Only drafts may have their lines / header changed."""
        return self.status == self.STATUS_DRAFT

    @property
    def status_label(self):
        """Localized status label for the active request language."""
        from common.i18n import t
        return t(f"status_{self.status}", self.get_status_display())

    # --- Money recalculation ---
    def recalc_totals(self, commit=True):
        subtotal = sum((i.line_total_lyd for i in self.items.all()), Decimal("0.00"))
        if self.discount_percent and self.discount_percent > 0:
            discount = (subtotal * self.discount_percent / Decimal("100"))
        else:
            discount = self.discount_amount or Decimal("0.00")
        discount = min(discount, subtotal)
        self.subtotal_lyd = quantize_lyd(subtotal)
        self.discount_amount = quantize_lyd(discount)
        self.total_lyd = quantize_lyd(subtotal - discount)
        if commit:
            self.save(update_fields=["subtotal_lyd", "discount_amount", "total_lyd", "updated_at"])

    def recalc_payments(self, commit=True):
        # Read the persisted status first: this may be called from Payment.save()
        # holding an invoice instance whose in-memory status is stale (e.g. issued
        # elsewhere in the same request). Trusting it would clobber the real status.
        db_status = type(self).all_objects.filter(pk=self.pk).values_list("status", flat=True).first()
        if db_status is not None:
            self.status = db_status
        paid = sum((p.amount for p in self.payments.all()), Decimal("0.00"))
        self.amount_paid = quantize_lyd(paid + self.credit_applied)
        # Status only advances for live (non-draft, non-cancelled) invoices.
        if self.status in (self.STATUS_ISSUED, self.STATUS_PARTIAL, self.STATUS_PAID):
            if self.total_lyd > 0 and self.amount_paid >= self.total_lyd:
                self.status = self.STATUS_PAID
            elif self.amount_paid > 0:
                self.status = self.STATUS_PARTIAL
            else:
                self.status = self.STATUS_ISSUED
        if commit:
            self.save(update_fields=["amount_paid", "status", "updated_at"])


class InvoiceItem(models.Model):
    """A single line on an invoice. Prices are snapshots frozen at line creation.

    A line is a Product, a Service, or a free-text "custom" line (for the
    occasional unrelated goods Switch resells). ``description`` is always stored
    so the printed invoice never changes if the source product is later renamed.
    """

    KIND_PRODUCT = "product"
    KIND_SERVICE = "service"
    KIND_CUSTOM = "custom"
    KIND_CHOICES = (
        (KIND_PRODUCT, "Product"),
        (KIND_SERVICE, "Service"),
        (KIND_CUSTOM, "Custom"),
    )

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=KIND_PRODUCT, verbose_name="Kind")
    product = models.ForeignKey(
        "catalog.Product", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="invoice_items", verbose_name="Product",
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="invoice_items", verbose_name="Variant",
    )
    service = models.ForeignKey(
        "catalog.Service", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="invoice_items", verbose_name="Service",
    )
    description = models.CharField(max_length=255, verbose_name="Description")
    color = models.CharField(max_length=16, null=True, blank=True, verbose_name="Color")
    size = models.CharField(max_length=120, null=True, blank=True, verbose_name="Size / Spec")
    unit_price_lyd = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Unit Price (LYD)")
    unit_price_usd = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Unit Price (USD)")
    # Frozen unit *cost* (USD) at time of sale, for exact COGS in the financial
    # report. Product lines only; NULL for services/custom or legacy lines.
    unit_cost_usd = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, editable=False, verbose_name="Unit Cost (USD)")
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.01"))], verbose_name="Quantity",
    )
    line_total_lyd = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), editable=False, verbose_name="Line Total (LYD)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Invoice Item"
        verbose_name_plural = "Invoice Items"
        default_permissions = ()  # managed through the parent Invoice
        ordering = ["pk"]

    def __str__(self):
        return f"{self.description} × {self.quantity}"

    @property
    def kind_label(self):
        from common.i18n import t
        return t(f"kind_{self.kind}", self.get_kind_display())

    @property
    def color_label(self):
        from common.i18n import t
        if not self.color:
            return ""
        try:
            from catalog.models import Product
            fallback = dict(Product.COLOR_CHOICES).get(self.color, self.color)
        except Exception:
            fallback = self.color
        return t(f"color_{self.color}", fallback)

    def clean(self):
        if self.kind == self.KIND_PRODUCT and not self.product_id:
            raise ValidationError({"product": "Select a product for a product line."})
        if self.kind == self.KIND_SERVICE and not self.service_id:
            raise ValidationError({"service": "Select a service for a service line."})
        if self.variant_id and self.product_id and self.variant.product_id != self.product_id:
            raise ValidationError({"variant": "Variant must belong to the selected product."})

    def save(self, *args, **kwargs):
        # Snapshot a description from the source if the user left it blank.
        if not self.description:
            if self.product_id:
                self.description = self.product.name
            elif self.service_id:
                self.description = self.service.name
        # Freeze the product's unit cost on first save (fallback for any path
        # that doesn't set it explicitly — the editor sets it via _apply_item_price).
        if self.product_id and self.unit_cost_usd is None:
            self.unit_cost_usd = self.product.cost_usd
        self.line_total_lyd = (Decimal(self.unit_price_lyd) * Decimal(self.quantity)).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        super().save(*args, **kwargs)


class Payment(ScopedModel):
    """A payment received against an invoice. Maintains the invoice's paid total.

    Visible on the standalone payments list to whoever recorded it *or* the
    salesperson of its invoice — so a rep sees payments a cashier keyed against
    their sale. Managers holding ``view_all_payment`` see all.
    """

    #: Row-ownership lookups consumed by common.access.apply_ownership.
    OWNER_FIELDS = ("created_by", "invoice__salesperson")

    METHOD_CASH = "cash"
    METHOD_CARD = "card"
    METHOD_BANK = "bank_transfer"
    METHOD_CHEQUE = "cheque"
    METHOD_CHOICES = (
        (METHOD_CASH, "Cash"),
        (METHOD_CARD, "Card"),
        (METHOD_BANK, "Bank Transfer"),
        (METHOD_CHEQUE, "Cheque"),
    )

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments", verbose_name="Invoice")
    receipt_number = models.CharField(max_length=20, unique=True, blank=True, verbose_name="Receipt No.")
    amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))], verbose_name="Amount (LYD)",
    )
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_CASH, verbose_name="Method")
    paid_at = models.DateTimeField(default=timezone.now, verbose_name="Paid At")
    deposit = models.ForeignKey(
        "finance.CashDeposit", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="payments", verbose_name="Linked Cash Deposit",
    )
    notes = models.CharField(max_length=255, blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        ordering = ["-paid_at"]
        permissions = [("view_all_payment", "Can view all payments (not just own)")]

    def __str__(self):
        return f"{self.receipt_number or 'Receipt'} — {self.amount} LYD on {self.invoice_id}"

    @property
    def method_label(self):
        from common.i18n import t
        return t(f"method_{self.method}", self.get_method_display())

    @transaction.atomic
    def save(self, *args, **kwargs):
        from .services import _lock_customer

        _lock_customer(self.invoice)
        locked_invoice = Invoice.objects.select_for_update().get(pk=self.invoice_id)
        prior = type(self).all_objects.filter(pk=self.pk).select_related("invoice").first() if self.pk else None
        if locked_invoice.status == Invoice.STATUS_CANCELLED or (prior and prior.invoice.status == Invoice.STATUS_CANCELLED):
            raise ValidationError(_("Payments on cancelled invoices cannot be changed. Resolve them with a refund or customer credit."))
        # Track a prior deposit link so a reassigned payment recomputes both batches.
        using = kwargs.get("using")
        prev_deposit_id = None
        if self.pk:
            prev_deposit_id = (
                type(self).all_objects.filter(pk=self.pk)
                .values_list("deposit_id", flat=True).first()
            )
        super().save(*args, **kwargs)
        if not self.receipt_number:
            self.receipt_number = f"RCT-{self.pk:06d}"
            super().save(update_fields=["receipt_number"], using=using)
        self.invoice.recalc_payments()
        self._recalc_linked_deposits(prev_deposit_id)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        from .services import _lock_customer

        _lock_customer(self.invoice)
        locked_invoice = Invoice.objects.select_for_update().get(pk=self.invoice_id)
        if locked_invoice.status == Invoice.STATUS_CANCELLED or PaymentResolution.objects.filter(payment=self).exists():
            raise ValidationError(_("Payments on cancelled invoices must be kept as history."))
        invoice = self.invoice
        deposit = self.deposit
        super().delete(*args, **kwargs)
        invoice.recalc_payments()
        if deposit is not None:
            deposit.recalc_amount()

    def _recalc_linked_deposits(self, prev_deposit_id=None):
        from finance.models import CashDeposit

        ids = {i for i in (self.deposit_id, prev_deposit_id) if i}
        for deposit in CashDeposit.objects.filter(pk__in=ids):
            deposit.recalc_amount()


class PaymentResolution(ScopedModel):
    """One final disposition per original cash receipt; written by lifecycle services."""

    OWNER_FIELDS = ("payment__invoice__salesperson", "payment__invoice__created_by")
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="resolution")
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.PROTECT, related_name="payment_resolutions")
    action = models.CharField(max_length=10, choices=(("refund", "Refund"), ("credit", "Customer credit")))
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=20, choices=Payment.METHOD_CHOICES, blank=True)
    resolved_at = models.DateTimeField(default=timezone.now)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="sales_resolution_positive"),
            models.CheckConstraint(condition=models.Q(action="refund", method__in=["cash", "card", "bank_transfer", "cheque"]) | models.Q(action="credit", customer__isnull=False, method=""), name="sales_resolution_disposition"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(_("Payment settlements are immutable."))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Payment settlements must be kept as history."))

    @property
    def available_amount(self):
        if self.action != "credit":
            return Decimal("0.00")
        used = self.uses.exclude(invoice__status=Invoice.STATUS_CANCELLED).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
        return quantize_lyd(self.amount - used)

    def __str__(self):
        return f"{self.payment.receipt_number} — {self.amount} LYD"


class CustomerCreditUse(ScopedModel):
    """A non-cash payment allocation; cancelled target invoices release it."""

    OWNER_FIELDS = ("invoice__salesperson", "invoice__created_by")
    credit = models.ForeignKey(PaymentResolution, on_delete=models.PROTECT, related_name="uses")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="credit_uses")
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    request_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    applied_at = models.DateTimeField(default=timezone.now)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="sales_credit_use_positive")]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(_("Credit allocations are immutable."))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Credit allocations must be kept as history."))


class Delivery(ScopedModel):
    """A delivery job — the courier-facing side of a sale.

    A delivery employee sees **only the jobs assigned to them** (row-level
    visibility): they never touch the invoice list, sales figures or other
    reps' work. A dispatcher/manager holding ``view_all_delivery`` sees the whole
    board and assigns couriers via ``assign_delivery``.

    Linking to an ``Invoice`` is optional (ad-hoc drop-offs exist); the recipient
    address is snapshotted so the job stays self-contained if the invoice/customer
    changes later.
    """

    #: Row-ownership lookups consumed by common.access.apply_ownership.
    OWNER_FIELDS = ("assigned_to", "created_by")

    STATUS_PENDING = "pending"       # created, not yet assigned/scheduled
    STATUS_ASSIGNED = "assigned"     # a courier is responsible
    STATUS_OUT = "out"               # out for delivery
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"         # attempted, could not deliver
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_ASSIGNED, "Assigned"),
        (STATUS_OUT, "Out for Delivery"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    )
    OPEN_STATUSES = (STATUS_PENDING, STATUS_ASSIGNED, STATUS_OUT)

    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="deliveries", verbose_name="Invoice",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="deliveries", verbose_name="Assigned To",
    )
    recipient = models.CharField(max_length=200, blank=True, verbose_name="Recipient")
    phone = models.CharField(max_length=40, blank=True, verbose_name="Phone")
    address = models.CharField(max_length=255, verbose_name="Address")
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
        verbose_name="Status",
    )
    scheduled_date = models.DateField(null=True, blank=True, verbose_name="Scheduled Date")
    delivered_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Delivered At")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Delivery"
        verbose_name_plural = "Deliveries"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="sales_deliv_status_idx"),
            models.Index(fields=["assigned_to", "status"], name="sales_deliv_assignee_idx"),
        ]
        permissions = [
            ("view_all_delivery", "Can view all deliveries (not just assigned)"),
            ("assign_delivery", "Can assign deliveries to couriers"),
        ]

    def __str__(self):
        label = self.recipient or (self.invoice.display_customer if self.invoice_id else "")
        return f"{label} — {self.get_status_display()}".strip(" —")

    @property
    def status_label(self):
        from common.i18n import t
        return t(f"delivery_status_{self.status}", self.get_status_display())

    def save(self, *args, **kwargs):
        # Snapshot recipient/address/phone from the linked invoice on first save
        # so the courier's card is self-contained. Auto-advance pending→assigned
        # when a courier is set, and stamp the delivery time when it lands.
        if self.invoice_id:
            if not self.recipient:
                self.recipient = self.invoice.display_customer
            if not self.phone:
                self.phone = self.invoice.customer_phone
            if not self.address:
                self.address = self.invoice.customer_address
        if self.status == self.STATUS_PENDING and self.assigned_to_id:
            self.status = self.STATUS_ASSIGNED
        if self.status == self.STATUS_DELIVERED and self.delivered_at is None:
            self.delivered_at = timezone.now()
        super().save(*args, **kwargs)


class PosSale(ScopedModel):
    """One completed till sale: the invoice it became, keyed for safe retries.

    The till sends a fresh ``key`` per sale; a repeated submit (double tap,
    flaky Wi-Fi) finds this row and returns the same invoice instead of
    selling twice.
    """

    key = models.CharField(max_length=64, unique=True, verbose_name="Idempotency Key")
    invoice = models.OneToOneField(Invoice, on_delete=models.PROTECT, related_name="pos_sale", verbose_name="Invoice")
    till = models.CharField(max_length=60, blank=True, verbose_name="Till")
    tendered_lyd = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Cash Tendered (LYD)",
    )
    change_lyd = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"), verbose_name="Change (LYD)",
    )

    class Meta:
        verbose_name = "POS Sale"
        verbose_name_plural = "POS Sales"
        ordering = ["-created_at"]
        permissions = [
            ("use_pos", "Can sell from the point-of-sale till"),
            ("pos_unlimited_discount", "Can give any discount at the till"),
        ]

    def __str__(self):
        return f"{self.invoice} ({self.till or 'till'})"
