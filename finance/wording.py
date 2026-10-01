"""USD ↔ EUR wording, as a ``common.wording`` axis.

When the store prices in EUR, labels such as "Import Cost (USD)" or
«تكلفة الاستيراد (دولار)» read EUR / يورو. Strings that name a currency on
purpose — the currency choices, the pricing setting, the two-currency exchange
card — keep their source wording.
"""
import re

from common.wording import register_wording

from .currency import CURRENCY_USD, PRICING_CURRENCIES, stored_pricing_currency

_EN = (
    (r"\bUS Dollars\b", "Euros"),
    (r"\bUS Dollar\b", "Euro"),
    (r"\bUSD\b", "EUR"),
)
_AR = (
    ("الدولار الأمريكي", "اليورو"),
    ("بالدولار", "باليورو"),
    ("الدولار", "اليورو"),
    ("دولار", "يورو"),
)


def _rewrite(text, lang, mode):
    if lang == "ar":
        for old, new in _AR:
            text = text.replace(old, new)
        return text
    for pattern, new in _EN:
        text = re.sub(pattern, new, text)
    return text


register_wording(
    "pricing_currency",
    modes=PRICING_CURRENCIES,
    default=CURRENCY_USD,
    stored_mode=lambda settings: stored_pricing_currency(settings.extra_config),
    rewrite=_rewrite,
    skip_prefixes=("currency_", "pricing_", "rate_card_", "choice_"),
)
