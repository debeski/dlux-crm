# Sales

Customers, invoices, payments, deliveries, the point-of-sale till and sales reports.

| Module | Contents |
| --- | --- |
| `models.py` | `Customer`, `Invoice`, `InvoiceItem`, `Payment`, `PaymentResolution`, `CustomerCreditUse`, `Delivery`, `PosSale`. |
| `services.py` | Invoice lifecycle operations that touch more than one row or app (issue, cancel with refund or credit, apply customer credit). |
| `pos.py`, `pos_views.py`, `pos_settings.py`, `pos_options_forms.py` | Till lookups and checkout on top of the regular invoice flow, its views, and the *Point of sale* settings (`switch_pos.point_of_sale`). |
| `payment_resolution_forms.py`, `payment_resolution_views.py` | Refund or customer credit for payments on cancelled invoices. |
| `reports.py` | Sales report aggregates and the Excel export. |
| `forms.py`, `filters.py`, `tables.py`, `views.py`, `urls.py` | Forms, list filters, tables, views and routes (mounted at `/staff/sales/`). |
| `dlux_options.py` | Options-page registration of the Point of sale settings. |
| `translations.py` | App strings for DjangoLux. |
| `management/commands/` | `seed_roles` (permission groups) and `seed_demo` (demo data). |

Rules are in [docs/BUSINESS_RULES.md](../docs/BUSINESS_RULES.md), roles in
[docs/PERMISSIONS.md](../docs/PERMISSIONS.md).
