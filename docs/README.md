# Sales CRM — Documentation

Project documentation for the Sales CRM (منظومة مبيعات):

- [ARCHITECTURE.md](ARCHITECTURE.md) — apps, layering, DjangoLux patterns, URL structure, money and security baseline
- [BUSINESS_RULES.md](BUSINESS_RULES.md) — currency and pricing, invoices, payments, catalog, stock, purchasing, POS, finance, public shop
- [PERMISSIONS.md](PERMISSIONS.md) — roles, `seed_roles`, custom permissions, per-employee visibility
- [OPERATIONS.md](OPERATIONS.md) — the container stack, settings, HTTPS, first-run checklist, key URLs, scheduled work, updating, local development, commands
- [RELEASING.md](RELEASING.md) — tag-driven Docker image releases for `debeski/dlux-crm:sales`, the deployment bundle, CI
- [AUTOMOTIVE_FITMENT.md](AUTOMOTIVE_FITMENT.md) — the optional vehicle and machinery compatibility modules
- [CLIENT_CATEGORIZATION.md](CLIENT_CATEGORIZATION.md) — machinery categories and compatibility vocabulary
- [QA_WORKFLOWS.md](QA_WORKFLOWS.md) — manual QA workflows

See also the root [README.md](../README.md), [CHANGELOG.md](../CHANGELOG.md), `VERSION` and
[deploy/README.md](../deploy/README.md) (the deployment bundle's README).

## Conventions

- Project defaults live in `DLUX_CONFIG` in `config/settings.py`; DjangoLux is wired by `dlux_settings(globals())`.
- Business models extend `ScopedModel` (DjangoLux audit and store-scope behaviour).
- Each app keeps `translations.py`, `forms.py`, `filters.py`, `tables.py`, `views.py` and `urls.py` under the conventional names so DjangoLux discovery finds them.
- `config/celery.py` is the Celery entrypoint; app tasks live in app-local `tasks.py`.
- `/health/` is the health endpoint.
- Secrets live in `.secrets/.env`; `compose.yml` keeps the standard inline-environment pattern and never reads that file into services directly.
- Useful commands: `python manage.py dlux_check`, `python manage.py dlux_setup`; with Docker `./start.sh -d`.
