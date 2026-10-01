"""The store's pricing currency: the foreign currency catalog prices are kept in.

USD (the default, so existing stores are unchanged) or EUR, chosen in the
*Pricing currency* section of CRM options. Every amount stored in a ``*_usd``
column is in this currency — the columns keep their historic names — and
``finance.services`` converts with this currency's rate unless told otherwise.
Sales and purchase invoices record the currency they were made in, so a switch
never rewrites a document. Switching re-expresses catalog prices in the new
currency (``convert_catalog_prices``) so LYD prices stay put.
"""
from decimal import ROUND_HALF_UP, Decimal

PRICING_NS = "switch_pos.pricing"
CURRENCY_USD = "USD"
CURRENCY_EUR = "EUR"
PRICING_CURRENCIES = (CURRENCY_USD, CURRENCY_EUR)
PRICING_DEFAULTS = {"currency": CURRENCY_USD}
CURRENCY_CHOICES = ((CURRENCY_USD, "USD"), (CURRENCY_EUR, "EUR"))

MONEY = Decimal("0.01")


def normalize_pricing_config(value):
    source = value if isinstance(value, dict) else {}
    currency = str(source.get("currency") or "").upper()
    return {"currency": currency if currency in PRICING_CURRENCIES else CURRENCY_USD}


def get_pricing_config():
    from dlux.utils import get_app_system_config

    return normalize_pricing_config(get_app_system_config(PRICING_NS, PRICING_DEFAULTS))


def pricing_currency():
    return get_pricing_config()["currency"]


def stored_pricing_currency(extra_config):
    """The pricing currency held in a SystemSettings ``extra_config`` value."""
    from dlux.system.constants import SYSTEM_APP_CONFIG_NAMESPACE

    extra = extra_config if isinstance(extra_config, dict) else {}
    app_bag = extra.get(SYSTEM_APP_CONFIG_NAMESPACE)
    stored = app_bag.get(PRICING_NS) if isinstance(app_bag, dict) else None
    return normalize_pricing_config(stored)["currency"]


def conversion_factor(from_currency, to_currency):
    """How many ``to_currency`` units one ``from_currency`` unit is worth, via LYD."""
    from .services import get_current_rate

    if from_currency == to_currency:
        return Decimal("1")
    return get_current_rate(from_currency) / get_current_rate(to_currency)


def priced_catalog_counts():
    from django.db.models import Q

    from catalog.models import Product, Service

    return {
        "products": Product.objects.filter(Q(cost_usd__gt=0) | Q(price_usd__gt=0)).count(),
        "services": Service.objects.filter(price_usd__isnull=False).count(),
    }


def convert_catalog_prices(from_currency, to_currency):
    """Re-express every product and service price in ``to_currency``.

    Cost and selling price scale by the cross rate, so a product's LYD price is
    unchanged; markup is a ratio and stays. Manual LYD overrides are already in
    LYD. Soft-deleted rows convert too, so restoring one never brings back an
    amount in the old currency. Returns the number of rows changed.
    """
    from catalog.models import Product, Service

    factor = conversion_factor(from_currency, to_currency)
    if factor == 1:
        return 0

    def scaled(value):
        return None if value is None else (value * factor).quantize(MONEY, rounding=ROUND_HALF_UP)

    products = list(Product.all_objects.only("pk", "cost_usd", "price_usd"))
    for product in products:
        product.cost_usd = scaled(product.cost_usd)
        product.price_usd = scaled(product.price_usd)
    Product.all_objects.bulk_update(products, ["cost_usd", "price_usd"], batch_size=500)

    services = list(Service.all_objects.only("pk", "price_usd"))
    for service in services:
        service.price_usd = scaled(service.price_usd)
    Service.all_objects.bulk_update(services, ["price_usd"], batch_size=500)
    return len(products) + len(services) + convert_draft_invoices(from_currency, to_currency, factor)


def convert_draft_invoices(from_currency, to_currency, factor):
    """Move unissued sales invoices to the new currency with the catalog.

    A draft is re-priced from the catalog while it is edited, so it must speak the
    catalog's currency. Its LYD figures are frozen per line and do not change;
    the rate becomes the new currency's live rate. Issued invoices keep theirs.
    """
    from sales.models import Invoice, InvoiceItem

    from .services import get_current_rate

    drafts = Invoice.all_objects.filter(status=Invoice.STATUS_DRAFT, currency=from_currency)
    items = list(InvoiceItem.objects.filter(invoice__in=drafts).only("pk", "unit_price_usd", "unit_cost_usd"))
    for item in items:
        for field in ("unit_price_usd", "unit_cost_usd"):
            value = getattr(item, field)
            if value is not None:
                setattr(item, field, (value * factor).quantize(MONEY, rounding=ROUND_HALF_UP))
    InvoiceItem.objects.bulk_update(items, ["unit_price_usd", "unit_cost_usd"], batch_size=500)
    return drafts.update(currency=to_currency, exchange_rate=get_current_rate(to_currency))


def convert_on_switch(sender, instance, **kwargs):
    """pre_save of SystemSettings: convert catalog prices when the currency changes.

    Runs on any save of the settings row — the CRM options tile, the setup
    wizard, a configuration import — and before the row is written, so a failed
    conversion leaves the old currency in place rather than prices in the wrong
    one.
    """
    from django.db import transaction

    if instance.pk is None:
        return
    previous = sender.objects.filter(pk=instance.pk).values_list("extra_config", flat=True).first()
    if previous is None:
        return
    old, new = stored_pricing_currency(previous), stored_pricing_currency(instance.extra_config)
    if old != new:
        with transaction.atomic():
            convert_catalog_prices(old, new)
