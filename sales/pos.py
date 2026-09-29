"""Point-of-sale lookups and checkout on top of the regular invoice flow.

A till sale is an ordinary walk-in invoice that is issued (stock out) and paid
in one transaction, so reports, the stock ledger and cash deposits see it like
any other sale. ``PosSale`` carries the idempotency key and the cash change.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from catalog.models import Product, ProductBarcode
from common.i18n import t
from common.views import scope_filtered_queryset
from finance.services import get_current_rate, quantize_lyd

from .models import Invoice, InvoiceItem, Payment, PosSale
from .pos_settings import enabled_methods
from .services import issue_invoice

LOOKUP_LIMIT = 20
POPULAR_LIMIT = 12
POPULAR_DAYS = 90


def _decimal(value, default=None):
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(t("pos_bad_number", "A number in the sale could not be read."))


def _products(user):
    return scope_filtered_queryset(Product.objects.filter(is_active=True), user)


def _part_number_products(query, products):
    try:
        from automotive.models import ProductPartNumber, normalize_part_number
    except ImportError:  # pragma: no cover - automotive is optional
        return products.none()
    normalized = normalize_part_number(query)
    if len(normalized) < 3:
        return products.none()
    ids = ProductPartNumber.objects.filter(normalized=normalized).values("product_id")
    return products.filter(pk__in=ids)


def _item(product, variant=None, rate=None):
    variants = list(product.variants.all()) if variant is None else []
    return {
        "product": product.pk,
        "variant": variant.pk if variant else None,
        "name": product.name if variant is None else f"{product.name} — {variant.display_label}",
        "sku": product.sku,
        "barcode": product.barcode,
        "price": str(product.selling_price_lyd(rate) or Decimal("0.00")),
        "stock": float(variant.stock_qty if variant else product.stock_qty),
        "track_stock": product.track_stock,
        "unit": product.get_unit_display(),
        "image": product.image_url or "",
        "variants": [
            {"id": item.pk, "label": item.display_label, "stock": float(item.stock_qty)}
            for item in variants
        ] if len(variants) > 1 else [],
    }


def lookup(query, *, user):
    """``{"exact": bool, "items": [...]}`` for a scanned code or typed text.

    A code that names one product — an extra barcode, the product barcode, the
    SKU, or a part number — is an exact hit the till adds straight to the cart.
    """
    text = (query or "").strip()
    if not text:
        return {"exact": False, "items": []}
    rate = get_current_rate()
    products = _products(user).prefetch_related("variants")

    extra = (
        ProductBarcode.objects.filter(code=text, product__in=products)
        .select_related("product", "variant").first()
    )
    if extra is not None:
        return {"exact": True, "items": [_item(extra.product, extra.variant, rate)]}

    exact = list(products.filter(Q(barcode=text) | Q(sku__iexact=text))[:2])
    if not exact:
        exact = list(_part_number_products(text, products)[:2])
    if len(exact) == 1:
        return {"exact": True, "items": [_item(exact[0], None, rate)]}

    matches = products.filter(
        Q(name__icontains=text) | Q(sku__icontains=text) | Q(barcode__icontains=text)
        | Q(pk__in=_part_number_products(text, products).values("pk"))
    ).order_by("name")[:LOOKUP_LIMIT]
    return {"exact": False, "items": [_item(product, None, rate) for product in matches]}


def popular(*, user):
    """The till's opening grid: best sellers of the last 90 days, topped up
    with the newest items so a fresh store is not empty. Only items that can
    be sold now; out-of-stock ones are still found by search."""
    rate = get_current_rate()
    products = _products(user).filter(Q(track_stock=False) | Q(stock_qty__gt=0)).prefetch_related("variants")
    sold = Invoice.objects.filter(
        status__in=(Invoice.STATUS_ISSUED, Invoice.STATUS_PARTIAL, Invoice.STATUS_PAID),
        issued_at__gte=timezone.now() - timedelta(days=POPULAR_DAYS),
    )
    ranked = [
        row["product"] for row in
        InvoiceItem.objects.filter(invoice__in=sold, product__in=products)
        .values("product").annotate(sold=Sum("quantity")).order_by("-sold")[:POPULAR_LIMIT]
    ]
    chosen = products.in_bulk(ranked)
    items = [chosen[pk] for pk in ranked if pk in chosen]
    if len(items) < POPULAR_LIMIT:
        items += list(products.exclude(pk__in=ranked).order_by("-created_at")[:POPULAR_LIMIT - len(items)])
    return {"exact": False, "popular": True, "items": [_item(product, None, rate) for product in items]}


def _sale_result(sale):
    invoice = sale.invoice
    return {
        "ok": True,
        "invoice": invoice.pk,
        "number": invoice.number,
        "total": str(invoice.total_lyd),
        "change": str(sale.change_lyd),
    }


@transaction.atomic
def complete_sale(*, user, data, config):
    """Create, issue and pay one walk-in invoice from a till cart."""
    from .views import _apply_item_price

    key = str(data.get("key") or "").strip()[:64]
    if not key:
        raise ValidationError(t("pos_missing_key", "The sale could not be identified. Try again."))
    existing = PosSale.all_objects.select_related("invoice").filter(key=key).first()
    if existing is not None:
        return _sale_result(existing)

    lines = data.get("lines") if isinstance(data.get("lines"), list) else []
    if not lines:
        raise ValidationError(t("pos_empty_cart", "Add at least one item."))

    rate = get_current_rate()
    products = _products(user)
    invoice = Invoice(
        customer_name=str(data.get("customer_name") or "").strip()[:200],
        customer_phone=str(data.get("customer_phone") or "").strip()[:40],
        exchange_rate=rate,
        notes=t("pos_invoice_note", "Point of sale"),
    )
    invoice.save()

    list_total = Decimal("0.00")
    for line in lines:
        product = products.filter(pk=line.get("product")).first() if isinstance(line, dict) else None
        if product is None:
            raise ValidationError(t("pos_unknown_item", "An item in the cart is no longer available."))
        quantity = _decimal(line.get("qty"))
        if quantity is None or quantity <= 0:
            raise ValidationError(t("pos_bad_quantity", "Quantities must be more than zero."))
        list_price = product.selling_price_lyd(rate) or Decimal("0.00")
        price = _decimal(line.get("price"), list_price)
        if price < 0:
            raise ValidationError(t("pos_bad_price", "Prices cannot be negative."))
        variant = product.variants.filter(pk=line.get("variant")).first() if line.get("variant") else None
        item = InvoiceItem(
            invoice=invoice, product=product, variant=variant,
            quantity=quantity, unit_price_lyd=quantize_lyd(price),
        )
        _apply_item_price(item, invoice)
        item.save()
        list_total += list_price * quantity

    invoice.discount_percent = Decimal("0.00")
    invoice.discount_amount = quantize_lyd(max(_decimal(data.get("discount"), Decimal("0")), Decimal("0")))
    invoice.recalc_totals()

    cap = Decimal(config["max_discount_percent"])
    given = list_total - invoice.total_lyd
    if (
        list_total > 0 and given > 0
        and not user.has_perm("sales.pos_unlimited_discount")
        and given * 100 / list_total > cap
    ):
        raise ValidationError(
            t("pos_discount_over_cap", "Discount is over your {cap}% limit.").format(cap=f"{cap:g}")
        )

    issue_invoice(invoice, user)
    invoice.refresh_from_db()

    allowed = set(enabled_methods(config))
    payments = data.get("payments") if isinstance(data.get("payments"), list) else []
    remaining = invoice.total_lyd
    cash_given = Decimal("0.00")
    applied = []
    # Non-cash covers exact amounts first; cash takes the rest and makes change.
    for entry in sorted(payments, key=lambda entry: entry.get("method") == Payment.METHOD_CASH):
        method = entry.get("method") if isinstance(entry, dict) else None
        if method not in allowed:
            raise ValidationError(t("pos_bad_method", "That payment method is not accepted at the till."))
        amount = quantize_lyd(_decimal(entry.get("amount"), Decimal("0")))
        if amount <= 0:
            continue
        if method == Payment.METHOD_CASH:
            cash_given += amount
        elif amount > remaining:
            raise ValidationError(t("pos_card_over_total", "A card or transfer amount is more than what is left to pay."))
        take = min(amount, remaining)
        if take > 0:
            applied.append((method, take))
            remaining -= take
    if remaining > 0:
        raise ValidationError(t("pos_underpaid", "The payment does not cover the total."))

    for method, amount in applied:
        Payment.objects.create(invoice=invoice, amount=amount, method=method)
    cash_applied = sum((amount for method, amount in applied if method == Payment.METHOD_CASH), Decimal("0.00"))
    sale = PosSale.objects.create(
        key=key,
        invoice=invoice,
        till=str(data.get("till") or "").strip()[:60],
        tendered_lyd=cash_given or None,
        change_lyd=quantize_lyd(cash_given - cash_applied),
    )
    return _sale_result(sale)
