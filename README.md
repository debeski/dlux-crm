# Sales CRM

dlux-crm **Sales Edition**: a sales, stock and finance system (منظومة مبيعات) for
a retail or trading business, built on [DjangoLux](https://pypi.org/project/django-lux/).
Staff work in Arabic or English (right-to-left supported); customers see an
optional public shop and landing page. The Docker image is
`debeski/dlux-crm:sales`; the Government edition ships from its own repository as
`debeski/dlux-crm:gov`.

## What it does

- **Sales**: customers, invoices (draft, issued, partially paid, paid, cancelled),
  payments and receipts, customer credit, refunds, deliveries, a point-of-sale
  till, a sales report with Excel export and a fiscal-year financial report.
- **Catalog and stock**: categories, products with colour/size variants and
  barcodes, services, suppliers, purchase invoices with attachments, a stock
  ledger, opening-stock import, stock takes and inventory valuation.
- **Finance**: USD/EUR pricing with a frozen exchange rate per invoice, reference
  rates refreshed from the Central Bank of Libya and EAN, cash deposits, expenses,
  staff accounts and a staff ledger.
- **Public site**: a curated shop and landing page with a live-preview builder, and
  a contact form.
- **Optional enhancements**: automotive vehicle compatibility and machinery
  compatibility for parts and services.
- **Roles**: Sales Manager, Sales Representative and Delivery Courier groups with
  per-employee visibility.

## Repository layout

| Path | Contents |
| --- | --- |
| `sales/`, `catalog/`, `finance/` | Core apps: invoices and POS; products, stock and purchasing; rates, deposits, expenses and staff accounts. |
| `automotive/`, `machinery/` | Optional vehicle and machinery compatibility. |
| `public_catalog/` | Public shop, landing page and their staff builders. |
| `common/` | Shared helpers, the Workspace dashboard and CRM options. |
| `config/` | Django settings, URLs, Celery. |
| `compose.yml`, `compose.dev.yml`, `Dockerfile`, `entrypoint.sh`, `.proxy/`, `relay/` | The container stack. |
| `deploy/` | Deployment bundle README and settings template (`scripts/build_deploy_zip.sh` builds the zip). |
| `docs/` | Project documentation. |

## Run it

Development (Docker, plain HTTP on <http://localhost:84>):

```bash
mkdir -p .secrets && cp deploy/env.template .secrets/.env   # fill in every CHANGE_ME
./start.sh -d
```

Without Docker, on SQLite:

```bash
pip install -r requirements.txt
python manage.py migrate    --settings=config.settings_dev_sqlite
python manage.py seed_roles --settings=config.settings_dev_sqlite
python manage.py runserver  --settings=config.settings_dev_sqlite
```

Tests:

```bash
python manage.py test finance catalog sales common public_catalog automotive machinery tests \
    --settings=config.settings_dev_sqlite
```

A server install uses the deployment zip and its `README.md` (also
`deploy/README.md`); setup, URLs and commands are in
[docs/OPERATIONS.md](docs/OPERATIONS.md).

## Documentation

See [docs/README.md](docs/README.md). Release history: [CHANGELOG.md](CHANGELOG.md).
Open work and project state: [tracker.md](tracker.md).
