"""Rebuilding stock balances from the ledger.

``Product.stock_qty`` (and the per-variant column beside it) is a running total:
``StockMovement.save()`` applies each movement's delta once, on insert, and
nothing recomputes it afterwards. That is right for the hot path — a sale must
not re-sum a product's whole history — but it means the figure only stays true
while every movement behind it is still there.

A data reset writes in bulk. ``QuerySet.update()`` and ``QuerySet.delete()`` run
no ``save()``, so clearing the ledger left every product still claiming the stock
those movements had put on it: invoices gone, quantities standing.

So the balance is rebuilt from what survives, which is the ledger's own
definition of the number: the sum of the live movements' signed quantities.
"""
from decimal import Decimal

from django.db import models

ZERO = Decimal("0.00")


def _signed_quantity_expression(model):
    """The SQL twin of ``StockMovement.signed_quantity``.

    In / Out carry an unsigned amount and take their sign from the type; an
    adjustment is signed by whoever posted it.
    """
    absolute = models.Func(models.F("quantity"), function="ABS")
    return models.Case(
        models.When(movement_type=model.TYPE_IN, then=absolute),
        models.When(movement_type=model.TYPE_OUT, then=-absolute),
        default=models.F("quantity"),
        output_field=models.DecimalField(max_digits=12, decimal_places=2),
    )


def _live_movements(model):
    """Every scope's still-live ledger rows.

    ``all_objects`` rather than the scoped manager: a rebuild is system-wide, and
    a balance narrowed to one scope would be wrong for every other one.
    """
    return model.all_objects.filter(deleted_at__isnull=True)


def rebuild_stock_balances():
    """Recompute every tracked balance from the live ledger.

    Returns ``(products_updated, variants_updated)``. Only stock-tracked products
    are touched, matching the write path — an untracked product's column is not a
    balance and is left as it is.
    """
    from .models import Product, ProductVariant, StockMovement

    signed = _signed_quantity_expression(StockMovement)
    movements = _live_movements(StockMovement)

    by_product = {
        row["product_id"]: row["total"] or ZERO
        for row in movements.values("product_id").annotate(total=models.Sum(signed))
    }
    by_variant = {
        row["variant_id"]: row["total"] or ZERO
        for row in movements.exclude(variant_id=None).values("variant_id").annotate(total=models.Sum(signed))
    }

    products = []
    for product in Product.all_objects.filter(track_stock=True).only("pk", "stock_qty"):
        total = by_product.get(product.pk, ZERO)
        if product.stock_qty != total:
            product.stock_qty = total
            products.append(product)
    if products:
        Product.all_objects.bulk_update(products, ["stock_qty"], batch_size=500)

    variants = []
    for variant in ProductVariant.objects.filter(product__track_stock=True).only("pk", "stock_qty"):
        total = by_variant.get(variant.pk, ZERO)
        if variant.stock_qty != total:
            variant.stock_qty = total
            variants.append(variant)
    if variants:
        ProductVariant.objects.bulk_update(variants, ["stock_qty"], batch_size=500)

    return len(products), len(variants)


#: Clearing any of these changes what the ledger says, so the balances built from
#: it are stale until they are rebuilt. Purchase invoices and stock takes are in
#: the list because their movements carry their reference: a reset that takes the
#: documents and their movements together must not leave the total behind.
LEDGER_MODEL_KEYS = frozenset({
    "catalog.stockmovement",
    "catalog.product",
    "catalog.productvariant",
    "catalog.purchaseinvoice",
    "catalog.stocktake",
})


def on_data_reset_finished(sender, **kwargs):
    """Rebuild balances after a dlux data reset that touched the ledger."""
    selected = {str(key).strip().lower() for key in (kwargs.get("models") or ())}
    if not selected & LEDGER_MODEL_KEYS:
        return
    products, variants = rebuild_stock_balances()
    if products or variants:
        import logging

        logging.getLogger(__name__).info(
            "Data reset: rebuilt %s product and %s variant stock balance(s) from the ledger.",
            products, variants,
        )
