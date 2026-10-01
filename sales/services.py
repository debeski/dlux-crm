"""
Invoice lifecycle operations that touch more than one row/app.

Kept out of the model so the cross-app side effects (stock ledger, rate snapshot)
are explicit and wrapped in a single transaction.
"""
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from catalog.models import StockMovement
from finance.models import ExchangeRate

from .models import Invoice


def _item_variant(item):
    if item.variant_id:
        return item.variant
    if not item.product_id:
        return None
    color = item.color or ""
    size = item.size or ""
    matches = list(item.product.variants.filter(color=color, size=size))
    return matches[0] if len(matches) == 1 else None


@transaction.atomic
def issue_invoice(invoice, user):
    """Move a draft invoice to *issued*: snapshot the rate record and draw down
    stock for every product line. Idempotent — only acts on drafts."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != Invoice.STATUS_DRAFT:
        return invoice
    if not invoice.items.exists():
        raise ValidationError(_("Cannot issue an invoice with no items."))

    # Stock guard: aggregate demand per stock bucket. Variant-aware lines are
    # checked against their own color/size bucket; legacy/no-variant lines still
    # fall back to the aggregate product quantity.
    needs = defaultdict(lambda: Decimal("0"))
    stock_refs = {}
    for item in invoice.items.select_related("product", "variant"):
        if item.kind == item.KIND_PRODUCT and item.product_id and item.product.track_stock:
            variant = _item_variant(item)
            key = ("variant", variant.pk) if variant else ("product", item.product_id)
            needs[key] += item.quantity
            stock_refs[key] = variant or item.product

    shortages = []
    for key, qty in needs.items():
        ref = stock_refs[key]
        have = ref.stock_qty
        if have < qty:
            if key[0] == "variant":
                name = f"{ref.product.name} — {ref.display_label}"
            else:
                name = ref.name
            shortages.append(
                _("%(name)s (need %(need)s, have %(have)s)")
                % {"name": name, "need": qty, "have": have}
            )
    if shortages:
        raise ValidationError(_("Insufficient stock to issue: ") + "; ".join(shortages))

    invoice.exchange_rate_obj = ExchangeRate.objects.filter(currency=invoice.currency).order_by("-created_at").first()

    for item in invoice.items.select_related("product", "variant"):
        if item.kind == item.KIND_PRODUCT and item.product_id and item.product.track_stock:
            variant = _item_variant(item)
            StockMovement.objects.create(
                product=item.product,
                variant=variant,
                movement_type=StockMovement.TYPE_OUT,
                quantity=item.quantity,
                reason=_("Sold on invoice %(no)s") % {"no": invoice.number},
                reference=invoice.number,
            )

    invoice.status = Invoice.STATUS_ISSUED
    invoice.issued_at = timezone.now()
    invoice.save(update_fields=["status", "issued_at", "exchange_rate_obj", "updated_at"])
    invoice.recalc_payments()
    return invoice


@transaction.atomic
def cancel_invoice(invoice, user):
    """Cancel an invoice and restore any stock it had drawn down."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == Invoice.STATUS_CANCELLED:
        return invoice

    was_issued = invoice.status in (
        Invoice.STATUS_ISSUED, Invoice.STATUS_PARTIAL, Invoice.STATUS_PAID,
    )
    if was_issued:
        for item in invoice.items.select_related("product", "variant"):
            if item.kind == item.KIND_PRODUCT and item.product_id and item.product.track_stock:
                variant = _item_variant(item)
                StockMovement.objects.create(
                    product=item.product,
                    variant=variant,
                    movement_type=StockMovement.TYPE_IN,
                    quantity=item.quantity,
                    reason=_("Cancelled invoice %(no)s") % {"no": invoice.number},
                    reference=invoice.number,
                )

    invoice.status = Invoice.STATUS_CANCELLED
    invoice.save(update_fields=["status", "updated_at"])
    return invoice
