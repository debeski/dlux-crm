# Catalog

Products, services, suppliers, purchasing and the stock ledger.

| Module | Contents |
| --- | --- |
| `models.py` | `Category`, `Supplier`, `Product`, `ProductVariant`, `ProductBarcode`, `Service`, `PurchaseInvoice`, `PurchaseInvoiceLine`, `StockMovement`, `StockTake`, `StockTakeLine`, `OpeningStockDraft`. |
| `stock_balance.py` | Rebuilding stock balances from the ledger. |
| `opening_stock.py`, `opening_stock_import.py`, `opening_stock_template.py` | Persistent opening-stock drafts, validation and staging of rows from an Excel workbook, and the downloadable template. |
| `product_layouts.py`, `dlux_options.py` | The per-user Products list layout and its Options registration. |
| `forms.py`, `filters.py`, `tables.py`, `views.py`, `urls.py` | Forms, list filters, tables, views and routes (mounted at `/staff/catalog/`). |
| `translations.py` | App strings for DjangoLux. |

Rules are in [docs/BUSINESS_RULES.md](../docs/BUSINESS_RULES.md).
