# Switch POS — Operations & Setup

## Production-style run (Postgres + Redis, via Docker)

The dlux scaffold ships Docker assets. Bring up the stack:

```bash
./start.sh -d                                  # composer orchestrator (DEV mode → app on http://localhost:90)
# or directly:
docker compose --env-file .secrets/.env -f compose.yml -f compose.dev.yml up
```

`./start.sh -d` runs the `debeski/composer` image, which decrypts `.secrets`,
builds the `web`/`celery`/`smtp-relay` images from the `Dockerfile`, starts the
stack (db, redis, caddy, web, celery, smtp-relay, pgadmin, db-backup) and runs the
`migrator` post-start task. In DEV mode the app is served at **http://localhost:90**.

## Production deploy with a domain + automatic HTTPS

The edge is a **Caddy** reverse proxy (`.proxy/Caddyfile`, `caddy` service). Caddy
obtains and renews Let's Encrypt certificates automatically on boot — there is
no certbot step, no bootstrap command, and no manual reload. A plain
`./start.sh` is the entire TLS workflow.

Caddy serves the canonical public/staff Django app and can redirect the old ERP
hostname. It does **not** split `/shop/` vs `/staff/`; Django URLconf and DLux
public-root/auth settings own that split.

| Hostname(s)                              | Served by            | Env var             |
|------------------------------------------|----------------------|---------------------|
| `switchlibya.ly` `www.switchlibya.ly`    | Django/DLux app (`/`, `/shop/`, `/staff/...`) | `CADDY_SITE_ADDRESS` |
| `erp.switchlibya.ly`                     | permanent redirect to `CADDY_PRIMARY_URL/staff/` | `CADDY_ERP_ADDRESS` |

Each hostname gets its **own** auto-provisioned Let's Encrypt cert. Session and
CSRF cookies follow `BASE_URL`; with `BASE_URL=https://switchlibya.ly`, staff and
public paths share the canonical domain.

1. Point **A/AAAA records** at the VPS public IP for **all three** names:
   `@`/apex, `www`, and optionally `erp` for legacy bookmarks. Open **inbound TCP
   80 and 443** on the host firewall — Caddy needs both for the ACME challenge
   and to serve traffic. (A name that doesn't resolve yet just fails its own cert
   and retries; it does not affect the other site.)
2. In `.secrets/.env` set:
   ```ini
   CADDY_SITE_ADDRESS=switchlibya.ly www.switchlibya.ly
   CADDY_ERP_ADDRESS=erp.switchlibya.ly
   CADDY_PRIMARY_URL=https://switchlibya.ly
   ALLOWED_HOSTS=switchlibya.ly,www.switchlibya.ly,erp.switchlibya.ly,web,localhost,127.0.0.1,caddy
   ALLOWED_URLS=https://switchlibya.ly,https://www.switchlibya.ly
   BASE_URL=https://switchlibya.ly
   ```
   > **Migrating from the older split:** the static `./portfolio` host is no
   > longer the public site. Apex/www now proxy to Django; `erp.switchlibya.ly`
   > is only a redirect to `/staff/`.

   No ACME email is required — Caddy issues and auto-renews certs without one. To
   receive Let's Encrypt expiry notices, add a real address to the `.proxy/Caddyfile`
   global block (`{ email you@your-domain.tld }`); the domain must contain a dot.
3. Bring the stack up in production (no `-d`):
   ```bash
   ./start.sh
   ```
   On first boot Caddy issues a cert per hostname (watch `docker compose logs
   caddy`); each site is live on HTTPS with HTTP→HTTPS redirect. Certs persist in
   the `caddy_data` volume and auto-renew.

Override the published ports with `HTTP_PORT` / `HTTPS_PORT` (default `80`/`443`)
and the upload cap with `CADDY_MAX_SIZE` (default `10MB`) if needed.

Then migrate, seed roles, and create the owner:

```bash
python manage.py migrate
python manage.py seed_roles
python manage.py createsuperuser
```

On first visit the system runs the DjangoLux **setup wizard** (system name, logo,
language, theme). Health endpoint: `/health/`.

## First-run checklist

1. Complete the setup wizard (set the Arabic/English system name + logo — these
   brand the printed sales invoice, payment receipt, and purchase invoice).
2. **Finance → Exchange Rates → Add**: enter the current black-market USD→LYD rate.
   The Workspace dashboard warns until this is done.
3. **Catalog → Categories / Products / Services**: add what you sell. For products,
   enter `cost_usd` + `markup_percent` (or a direct `price_usd`). Product variants
   are stock-bearing `ProductVariant` buckets (`color` + free-form `size` / spec):
   set them during Opening Stock, Purchase Invoice intake, or variant-aware manual
   Stock Movements. Product list/detail screens show available color swatches with
   quantities.
   - **Bulk shortcut for first setup:** **Catalog → Stock Movements → Opening
     Stock (bulk)** loads everything already on the shelf in one grid — one row
     per item, each a new or existing product, with the quantity currently in
     storage. Rows can also set optional color and size/spec. Submit to create
     the items and post the opening stock in one go (the result appears as Stock
     In movements). It can only be applied once;
     afterward the button becomes a view-only Opening Stock record. See
     BUSINESS_RULES → *Opening stock*.
   - **Normal stock purchases after launch:** use **Catalog → Purchase Invoices**
     or **Catalog → Stock Movements → Add Stock**. This records supplier details,
     creates/reuses products, can set product color and size/spec at intake,
     accepts the supplier invoice scan/photo/PDF, and posts Stock In movements
     per line.
4. Build the storefront from **Shop Builder** (`/staff/shop-builder/`): flip the
   **Publish** switch on any live Product/Service to add it to the public shop,
   **Feature** the best (drives the landing hero/strip, drag the grip to reorder),
   and **Customize** each listing (customer-safe public title/summary/body,
   optional image override, installation/warranty notes, and per-listing show
   price/availability). The **Storefront live** switch and the builder settings
   endpoint drive shop availability and featured count; the DLux **Shop settings**
   modal is limited to shop title/subtitle, contact endpoints, and new-listing
   price/availability defaults in `switch_pos.public_catalog`. Turning the storefront
   off serves a coming-soon page (HTTP 503).
   Public pages show availability bands, not exact stock counts. The full-screen
   contact modal posts to `/contact/modal/`, saves a `PublicContactMessage` with an
   idempotency key, and emails the configured contact recipient when SMTP is valid.
   Design the landing page itself from **Homepage Builder**
   (`/staff/shop-builder/homepage/`): edit the hero (kicker/title/subtitle, primary
   button, background mode — featured/logo/custom/gradient — and overlay), toggle and
   reorder sections (featured, categories, services, story, contact) with per-section
   copy, and pick an accent colour — all with a **live preview** that also works while
   the storefront is offline (`?preview=1`). Changes autosave.
5. Create staff users and add them to one seeded role (`seed_roles` creates Sales
   Manager, Sales Representative, and Delivery Courier). For delivery people,
   technicians, or anyone carrying advances/loans/service payouts, create a
   **Finance → Staff Accounts** row so their ledger and confirmations have a home.
6. **Sales → New Invoice**: type or pick a customer in the single search box —
   existing customers autofill phone/address, and a new name is saved as a
   customer for next time. Add product / service lines (prices auto-fill); product
   lines expose available color swatches and size/spec choices from live variant
   stock. Save Draft → **Issue** draws down the selected variant bucket → record
   payments.
   **Print / Export** produces a clean printable invoice (Save as PDF from the
   browser dialog).

## Key URLs

| Path | Page |
|------|------|
| `/` | Public landing page |
| `/shop/` | Public catalog |
| `/shop/items/<slug>/` | Public item page |
| `/contact/modal/` | Public contact dynamic modal endpoint |
| `/staff/` | Staff entry redirect |
| `/staff/accounts/login/` | Staff login |
| `/staff/workspace/` | Workspace dashboard (DLux Home URL) |
| `/staff/sales/dashboard/` | Sales Overview |
| `/staff/sales/invoices/` | Invoices |
| `/staff/sales/new/` | New invoice editor |
| `/staff/catalog/` | Products & stock |
| `/staff/shop-builder/` | Public Catalog Builder (curate the public shop) |
| `/staff/shop-builder/homepage/` | Public Homepage Builder (design the landing page, live preview) |
| `/staff/catalog/services/` | Services |
| `/staff/catalog/suppliers/` | Supplier list |
| `/staff/catalog/purchase-invoices/` | Purchase invoices / inbound stock invoices |
| `/staff/catalog/stock-movements/` | Stock ledger (+ Opening Stock / Add Stock buttons) |
| `/staff/finance/rates/` | Exchange rates |
| `/staff/finance/deposits/` | Cash deposits |
| `/staff/finance/expenses/` | Operating expenses |
| `/staff/finance/staff-accounts/` | Staff accounts / user credit |
| `/staff/finance/staff-ledger/` | Staff ledger entries |
| `/staff/sales/report/` | Sales report (XLSX export from here; owner-only) |
| `/staff/sales/financial/` | Fiscal-year financial report with expenses/net profit |

## Scheduled tasks (Celery Beat)

The `celery` service runs both a worker and Beat (see `compose.yml`). Scheduled
jobs are declared in `config/celery.py` under `app.conf.beat_schedule`:

| Task | Schedule | Purpose |
|------|----------|---------|
| `finance.tasks.refresh_market_rates` | every 3h | Scrapes two USD→LYD reference rates and caches them (**no expiry** — replaced only by a later successful scrape): the **official** rate from [cbl.gov.ly](https://cbl.gov.ly/currency-exchange-rates/) (`finance:cbl_official_usd_rate`) and the **black-market** rate + trend from [eanlibya.com](https://www.eanlibya.com/exchangerate/) (`finance:ean_black_market_usd_rate`). |

The **Workspace dashboard** shows both reference rates next to the in-house
*custom* rate when the viewer has a rate, sales, or catalog permission.
Each scrape is server-side (the CSP `connect-src` blocks a browser cross-origin
fetch) and independent — if one site is down its last cached value is kept while
the other still updates. This is display-only — invoices always freeze the custom
`ExchangeRate`, never a scraped rate.

**Networking**: `web` and the rest of the stack sit on the isolated
`internal` network (`internal: true`, no egress). The scrape therefore
runs in the **celery** service, which is additionally attached to the egress bridge
`egress`; the web tier reads the scraped rates **cache-only** from Redis
(it never makes an outbound call). A `worker_ready` signal warms the cache on
celery boot so values appear without waiting for the first 3-hourly Beat run.
Applying the network change needs a recreate (`./start.sh -d`), not just a restart.

The full topology is a **3+1 network model**:

| Network | Type | Members | Purpose |
| --- | --- | --- | --- |
| `frontend` | bridge | `caddy` | Published ingress; bridge so the host reaches the app and Caddy reaches Let's Encrypt/ACME. |
| `egress` | bridge | `smtp-relay`, `dlux-updater`, `celery`, `composer-updater` | The only services with outbound internet (Gmail, PyPI, rate scrapes, Docker Hub). |
| `internal` | `internal: true` | `db`, `redis`, `web`, `caddy`, `celery`, `pgadmin`, `db-backup` | No-internet inter-service traffic. |
| `docker_proxy` | `internal: true` | `composer-updater`, `docker-socket-proxy` | Isolated Docker API path (see below). |

## Composer-as-updater (image-level updates)

The stack ships two services that let an operator (or dlux's in-app UI) roll the
deployment onto a newer published image without any host shell access:

- **`composer-updater`** (`debeski/composer:latest`, deployed at v1.1.11 or newer,
  `command: watch`) — a resident
  process that watches `/opt/dlux-runtime/state/image-update-request.json` on the
  shared `dlux_runtime` volume. On a request it runs `composer -u` against the
  host daemon (pull → **version gate** → recreate → health → `post_start` migrator)
  and atomically writes terminal `deploy-status.json` and a token-matched request
  acknowledgement even if the child Composer process exits unexpectedly. Runtime
  Compose overrides are created in a writable system temporary directory, not the
  host-owned project mount. It talks to the daemon over TCP via the socket proxy
  (`DOCKER_HOST=tcp://docker-socket-proxy:2375`), never the raw socket. The service
  uses `:latest`, but `COMPOSER_EXCLUDE_SERVICES` prevents it and its socket proxy
  from recreating themselves mid-update. It mounts the project at its host path
  (`${PWD}:${PWD}`) — **so the stack must be started from its root directory** for
  the `./media`/`./logs` bind mounts to resolve.
- **`docker-socket-proxy`** (tecnativa) — a least-privilege Docker API gateway that
  mounts `/var/run/docker.sock:ro` and exposes only the surface Compose needs
  (containers/images/networks/volumes/exec/POST/info/ping/version). Everything else
  (build, auth, secrets, swarm) stays denied.

**Version gate**: the image is built with `--build-arg DLUX_BAKED_VERSION=<ver>`
(CI reads the pinned `django-lux[updater]==` from `requirements.txt`) which is
stamped as `LABEL org.dlux_crm.dlux_baked_version`. The updater
(`COMPOSER_VERSION_LABEL=org.dlux_crm.dlux_baked_version`) refuses to recreate
onto an image whose baked version is older than the deployment's active runtime
version (`/opt/dlux-runtime/state/active.json`).

**Project release metadata**: tagged CI validates root `release-manifest.json`
against `VERSION` and stamps its compact schema-1 JSON into
`LABEL org.dlux.project.release-manifest` on both the smoke-tested and published
images. Composer reads that explicit label through
`COMPOSER_RELEASE_MANIFEST_LABEL` and publishes the project version, summary,
highlights, and HTTPS release URL to the DjangoLux application-image review.

The pinned DjangoLux v1.4.9 image worker treats only a token-matched Composer
acknowledgement or fresh terminal status as authoritative. A failed acknowledgement
immediately terminalizes the image update and lowers maintenance; if neither a
fresh phase nor acknowledgement appears within 120 seconds, the worker fails the
handoff instead of leaving the site behind Caddy's 503 page for the full deployment
timeout. The HTTPS maintenance page then probes same-origin `/` and reloads the
operator's original path once Caddy can route to the recovered application.

## CI / Docker image

Two workflows (tag-driven model — full details in [RELEASING.md](RELEASING.md)):

- **`.github/workflows/ci.yml`** — on push/PR to `main`: Django checks + tests
  (`config.settings_dev_sqlite`) and a Docker build + runtime smoke test (no push).
- **`.github/workflows/release.yml`** — on a `v*` tag: verifies the tag, `VERSION`,
  and project release manifest agree,
  smoke-tests, pushes multi-arch `debeski/dlux-crm:sales-<ver>` + `:sales`, and creates a
  GitHub Release from the `CHANGELOG.md` section.

Required repository **Secrets**: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (token must
be a *Secret*, not a *Variable*). Deploy the published image with
`WEB_IMAGE=debeski/dlux-crm:sales ./start.sh -d`.

Set **System Settings → Home URL** to `/staff/workspace/` to make the
project-wide Workspace dashboard the staff landing page. Keep
`/staff/sales/dashboard/` for the sales-only overview when a sales-centric screen
is useful.

## Local development without Postgres/Redis

A dev-only settings overlay runs everything on SQLite + local-memory cache:

```bash
python manage.py migrate       --settings=config.settings_dev_sqlite
python manage.py seed_roles     --settings=config.settings_dev_sqlite
python manage.py runserver      --settings=config.settings_dev_sqlite
```

`config/settings_dev_sqlite.py` is **not for production** — it only overrides the
database/cache so checks, migrations and smoke tests run on a laptop.

## Rich demo dataset

For local demos, screenshots, and business-logic smoke testing, run:

```bash
python manage.py seed_demo --settings=config.settings_dev_sqlite
python manage.py seed_demo --reset --settings=config.settings_dev_sqlite  # rebuild demo rows
```

`seed_demo` now creates a cross-module operating dataset: five demo users
(`demo_manager`, two sales reps, a courier, and a technician; password
`demo12345`), five exchange-rate history rows, four suppliers, eight categories,
24 products with barcode/color/size variant buckets and stock-ledger opening
balances, 11 services, 12 customers, four posted purchase invoices with linked
variant stock-in movements, 18 sales invoices across every status, linked cash/bank deposit
batches, 10 deliveries, posted/draft/void expenses, staff-ledger rows, and both
open and applied stock takes. Reference rows are idempotent; operational documents are
created only when no invoices exist, unless `--reset` is used.

## Migrations

App migrations are committed under `finance/`, `catalog/`, `sales/` `migrations/`.
After changing a model: `python manage.py makemigrations && python manage.py migrate`.
Always update `docs/` and `CHANGELOG.md` in the same change.
