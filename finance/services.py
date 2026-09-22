"""
Currency conversion helpers — the single source of truth for USD <-> LYD math.

Reuse these everywhere instead of multiplying by a rate inline; it keeps rounding
consistent and means there is exactly one place that decides what "the current
rate" is.
"""
import logging
import re
import urllib.request
from decimal import Decimal, ROUND_HALF_UP

from django.core.cache import cache
from django.utils import timezone

from .models import ExchangeRate, current_rate_cache_key

logger = logging.getLogger(__name__)

# --- Official (CBL) rate scraping -------------------------------------------
# The Central Bank of Libya publishes daily official rates. We scrape the USD
# row server-side (CSP forbids a browser-side cross-origin fetch) and cache the
# result. A Celery Beat task refreshes it; the dashboard shows it next to the
# in-house custom rate.
# Cache TTL for scraped rates: None = persist indefinitely. The value is only
# ever replaced by the next *successful* scrape, so a prolonged outage of the
# source sites never wipes the last-known rate (Redis runs with appendonly, so it
# also survives a Redis restart). Staleness is visible via the shown source date.
RATE_CACHE_TTL = None

CBL_URL = "https://cbl.gov.ly/currency-exchange-rates/"
CBL_RATE_CACHE_KEYS = {
    ExchangeRate.CURRENCY_USD: "finance:cbl_official_usd_rate",
    ExchangeRate.CURRENCY_EUR: "finance:cbl_official_eur_rate",
}
CBL_RATE_CACHE_KEY = CBL_RATE_CACHE_KEYS[ExchangeRate.CURRENCY_USD]
_CBL_MARKERS = {
    ExchangeRate.CURRENCY_USD: "الدولار الأمريكي",
    ExchangeRate.CURRENCY_EUR: "اليورو",
}

# eanlibya.com publishes a single daily *black-market* (parallel) USD price with a
# trend arrow. Same server-side scrape + cache pattern as the CBL official rate.
EAN_URL = "https://www.eanlibya.com/exchangerate/"
EAN_RATE_CACHE_KEYS = {
    ExchangeRate.CURRENCY_USD: "finance:ean_black_market_usd_rate",
    ExchangeRate.CURRENCY_EUR: "finance:ean_black_market_eur_rate",
}
EAN_RATE_CACHE_KEY = EAN_RATE_CACHE_KEYS[ExchangeRate.CURRENCY_USD]
_EAN_MARKERS = {
    ExchangeRate.CURRENCY_USD: "الدولار",
    ExchangeRate.CURRENCY_EUR: "اليورو",
}

# Sensible fallback so the system is usable before an admin sets the first rate.
# Surfaced in the UI as "no rate set" — never silently relied upon for real sales.
DEFAULT_RATE = Decimal("6.00")

LYD_QUANT = Decimal("0.01")
USD_QUANT = Decimal("0.01")


def get_current_rate(currency=ExchangeRate.CURRENCY_USD):
    """Return the live currency->LYD rate (USD by default).

    Cached to keep product-list price computations from issuing one query per row.
    Returns ``DEFAULT_RATE`` if no rate has ever been configured.
    """
    currency = str(currency).upper()
    if currency not in dict(ExchangeRate.CURRENCY_CHOICES):
        raise ValueError(f"Unsupported currency: {currency}")
    cache_key = current_rate_cache_key(currency)
    cached = cache.get(cache_key)
    if cached is not None:
        return Decimal(cached)
    latest = (
        ExchangeRate.objects.filter(currency=currency)
        .order_by("-created_at")
        .values_list("rate", flat=True)
        .first()
    )
    rate = Decimal(latest) if latest is not None else DEFAULT_RATE
    cache.set(cache_key, rate, 60 * 60)
    return rate


def has_configured_rate(currency=ExchangeRate.CURRENCY_USD):
    """True once an admin has entered at least one real exchange rate."""
    currency = str(currency).upper()
    return ExchangeRate.objects.filter(currency=currency).exists()


def usd_to_lyd(amount_usd, rate=None):
    """Convert a USD amount to LYD, rounded to 2 dp. ``None`` -> ``None``."""
    if amount_usd is None:
        return None
    rate = get_current_rate() if rate is None else Decimal(rate)
    return (Decimal(amount_usd) * rate).quantize(LYD_QUANT, rounding=ROUND_HALF_UP)


def lyd_to_usd(amount_lyd, rate=None):
    """Convert an LYD amount back to USD, rounded to 2 dp. ``None`` -> ``None``."""
    if amount_lyd is None:
        return None
    rate = get_current_rate() if rate is None else Decimal(rate)
    if rate == 0:
        return None
    return (Decimal(amount_lyd) / rate).quantize(USD_QUANT, rounding=ROUND_HALF_UP)


def eur_to_lyd(amount_eur, rate=None):
    """Convert a EUR amount to LYD, rounded to 2 dp. ``None`` -> ``None``."""
    if amount_eur is None:
        return None
    rate = get_current_rate(ExchangeRate.CURRENCY_EUR) if rate is None else Decimal(rate)
    return (Decimal(amount_eur) * rate).quantize(LYD_QUANT, rounding=ROUND_HALF_UP)


def quantize_lyd(amount):
    """Normalise an arbitrary Decimal to 2-dp LYD money."""
    return Decimal(amount or 0).quantize(LYD_QUANT, rounding=ROUND_HALF_UP)


def _cbl_number(row_html, label):
    """Pull the number that follows an Arabic label (e.g. ``المتوسط: </span>6.4117``).

    The label and its value sit in separate elements, so allow a short run of
    non-digit characters (markup, colon, spaces) between them.
    """
    match = re.search(re.escape(label) + r"[^0-9]{0,40}([0-9]+(?:\.[0-9]+)?)", row_html)
    return match.group(1) if match else None


def fetch_cbl_rate(currency=ExchangeRate.CURRENCY_USD, timeout=15):
    """Scrape cbl.gov.ly for an official USD/EUR→LYD rate.

    Returns a dict ``{"average","sell","buy","date","fetched_at"}`` (rates as
    strings) or ``None`` if the page is unreachable or its structure changed.
    Never raises — callers treat ``None`` as "official rate unavailable".
    """
    try:
        req = urllib.request.Request(CBL_URL, headers={"User-Agent": "Mozilla/5.0 (switch-pos)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception:
        logger.warning("CBL official-rate fetch failed", exc_info=True)
        return None

    currency = str(currency).upper()
    marker = _CBL_MARKERS.get(currency)
    if marker is None:
        raise ValueError(f"Unsupported currency: {currency}")
    row = None
    for match in re.finditer(r"<tr>(.*?)</tr>", html, re.S):
        if marker in match.group(1):
            row = match.group(1)
            break
    if row is None:
        logger.warning("CBL %s row not found — page structure may have changed", currency)
        return None

    average = _cbl_number(row, "المتوسط")
    if average is None:
        logger.warning("CBL %s average not parseable", currency)
        return None
    date_match = re.search(r"([0-9]{4}-[0-9]{2}-[0-9]{2})", row)
    return {
        "average": average,
        "sell": _cbl_number(row, "بيع"),
        "buy": _cbl_number(row, "شراء"),
        "date": date_match.group(1) if date_match else None,
        "fetched_at": timezone.now().isoformat(timespec="minutes"),
    }


def fetch_cbl_usd_rate(timeout=15):
    return fetch_cbl_rate(ExchangeRate.CURRENCY_USD, timeout=timeout)


def fetch_cbl_eur_rate(timeout=15):
    return fetch_cbl_rate(ExchangeRate.CURRENCY_EUR, timeout=timeout)


def refresh_cbl_rate_cache(currency=ExchangeRate.CURRENCY_USD):
    """Fetch the CBL rate and cache it. Returns the dict (or None on failure).
    On failure the previous cached value is left untouched."""
    currency = str(currency).upper()
    data = fetch_cbl_rate(currency)
    if data:
        cache.set(CBL_RATE_CACHE_KEYS[currency], data, RATE_CACHE_TTL)
    return data


def get_cbl_official_rate(refresh_if_missing=True, timeout=8, currency=ExchangeRate.CURRENCY_USD):
    """Last-known official CBL USD/EUR→LYD info dict, or ``None``.

    On a cold cache (``refresh_if_missing``) do a single short synchronous fetch
    so the dashboard shows a value even before the Beat task has run; subsequent
    reads are served from cache. The short timeout keeps a cold dashboard load
    from hanging if CBL is slow.
    """
    currency = str(currency).upper()
    data = cache.get(CBL_RATE_CACHE_KEYS[currency])
    if data is None and refresh_if_missing:
        data = fetch_cbl_rate(currency, timeout=timeout)
        if data:
            cache.set(CBL_RATE_CACHE_KEYS[currency], data, RATE_CACHE_TTL)
    return data


def fetch_ean_rate(currency=ExchangeRate.CURRENCY_USD, timeout=15):
    """Scrape eanlibya.com for a black-market USD/EUR→LYD price.

    Returns ``{"rate","trend","fetched_at"}`` (rate as a string, trend one of
    ``"up"``/``"down"``/``None``) or ``None`` if unreachable or unparseable.
    Never raises.
    """
    try:
        req = urllib.request.Request(EAN_URL, headers={"User-Agent": "Mozilla/5.0 (switch-pos)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception:
        logger.warning("EAN black-market rate fetch failed", exc_info=True)
        return None

    currency = str(currency).upper()
    marker = _EAN_MARKERS.get(currency)
    if marker is None:
        raise ValueError(f"Unsupported currency: {currency}")
    for match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        row = match.group(1)
        # Match the row whose currency cell exactly names the requested currency.
        if not re.search(r'class="column-2"[^>]*>\s*' + re.escape(marker) + r"\s*<", row):
            continue
        # Require a decimal so the "2" in the fa-2x icon class isn't picked up.
        price = re.search(r"([0-9]+\.[0-9]+)", row)
        if not price:
            continue
        trend = None
        if "arrow-alt-circle-down" in row:
            trend = "down"
        elif "arrow-alt-circle-up" in row:
            trend = "up"
        return {
            "rate": price.group(1),
            "trend": trend,
            "fetched_at": timezone.now().isoformat(timespec="minutes"),
        }
    logger.warning("EAN %s row not found — page structure may have changed", currency)
    return None


def fetch_ean_usd_rate(timeout=15):
    return fetch_ean_rate(ExchangeRate.CURRENCY_USD, timeout=timeout)


def fetch_ean_eur_rate(timeout=15):
    return fetch_ean_rate(ExchangeRate.CURRENCY_EUR, timeout=timeout)


def refresh_ean_rate_cache(currency=ExchangeRate.CURRENCY_USD):
    """Fetch the EAN black-market rate and cache it (previous value kept on failure)."""
    currency = str(currency).upper()
    data = fetch_ean_rate(currency)
    if data:
        cache.set(EAN_RATE_CACHE_KEYS[currency], data, RATE_CACHE_TTL)
    return data


def get_ean_black_market_rate(refresh_if_missing=True, timeout=8, currency=ExchangeRate.CURRENCY_USD):
    """Last-known black-market USD/EUR→LYD info dict, or ``None``."""
    currency = str(currency).upper()
    data = cache.get(EAN_RATE_CACHE_KEYS[currency])
    if data is None and refresh_if_missing:
        data = fetch_ean_rate(currency, timeout=timeout)
        if data:
            cache.set(EAN_RATE_CACHE_KEYS[currency], data, RATE_CACHE_TTL)
    return data
