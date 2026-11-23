# Finance

Exchange rates, pricing currency, cash deposits, expenses and staff accounts.

| Module | Contents |
| --- | --- |
| `models.py` | `ExchangeRate`, `CashDeposit`, `ExpenseCategory`, `Expense`, `StaffAccount`, `StaffLedgerEntry`. |
| `currency.py`, `wording.py`, `pricing_options_forms.py` | The default document and service currency, the active purchase currencies, USD/EUR wording, and the *Pricing currency* settings (`sales_crm.pricing`). |
| `services.py` | Pricing-currency to LYD conversion, and the reference-rate scrapes (CBL and EAN) that go through the Composer relay. |
| `tasks.py` | `finance.tasks.refresh_market_rates`, the Celery task scheduled in `config/celery.py`. |
| `forms.py`, `filters.py`, `tables.py`, `views.py`, `urls.py` | Forms, list filters, tables, views and routes (mounted at `/staff/finance/`). |
| `dlux_options.py` | Options-page registration. |
| `translations.py` | App strings for DjangoLux. |

Rules are in [docs/BUSINESS_RULES.md](../docs/BUSINESS_RULES.md).
