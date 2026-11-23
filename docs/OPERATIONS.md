# Sales CRM — Operations and Setup

How the stack is built, started, configured and kept running. Business behaviour
is in [BUSINESS_RULES.md](BUSINESS_RULES.md), roles in
[PERMISSIONS.md](PERMISSIONS.md), code layout in
[ARCHITECTURE.md](ARCHITECTURE.md), releases in [RELEASING.md](RELEASING.md).
The files an operator receives (`compose.yml`, `.proxy/`, `relay/`, `start.sh`,
`start.ps1`, the settings template) and the upgrade procedure are described in
`deploy/README.md`, which ships as `README.md` in the deployment zip.

## The stack

`compose.yml` (project name `sales`, stack schema 5) runs one image,
`debeski/dlux-crm:sales` (override with `WEB_IMAGE`), in several roles:

| Service | Image | Role | Networks |
| --- | --- | --- | --- |
| `db` | `postgres:17` | Database (`postgres_data` volume). Its environment is only what PostgreSQL reads. | `internal` |
| `redis` | `redis:7` | Cache and Celery broker (`redis_data` volume, append-only file). | `internal` |
| `smtp-relay` | app image | Local SMTP relay (`python -m dlux.smtp_relay`). The app sends mail to it; only it reaches the upstream provider. | `egress`, `internal` |
| `web` | app image | Gunicorn on port 8000 (Django development server when `DEBUG_STATUS=True`). | `internal` |
| `worker` | app image | DjangoLux task worker (`manage.py dlux_worker`): queued tasks, `DLUX_TASK_SCHEDULE`, backups. Its `pre_start` steps run `dlux_reconcile` and `migrator`, so it applies the migrations before the application starts. | `internal` |
| `celery` | app image | The project's own Celery worker with Beat (`celery -A config worker -B`): the exchange-rate refresh. Runs no migrations. | `internal` |
| `caddy` | `caddy:latest` | Reverse proxy, automatic HTTPS, stored-file access check, maintenance page. | `frontend`, `internal` |
| `docker-socket-proxy` | `tecnativa/docker-socket-proxy:latest` | Least-privilege Docker API for Composer. | `docker_proxy` |
| `composer-executor` | `debeski/composer:latest` | Holds Docker authority; performs the updates the agent requests. | `docker_proxy` |
| `composer-agent` | `debeski/composer:latest` | Resident Composer: image-update requests from the app, the outbound relay, the maintenance page. No Docker authority. | `egress`, `docker_proxy` |

Networks: `frontend` (published ingress), `egress` (the only networks with
internet access, used by `smtp-relay` and `composer-agent`), `internal` (no
internet) and `docker_proxy` (no internet; the Docker API path). Volumes:
`postgres_data`, `redis_data`, `static`, `dlux_runtime` (release pointer, update
state, maintenance flag), `composer_agent_state`, `composer_exec_sock`,
`caddy_data` (certificates and ACME account; must persist) and `caddy_config`.
Bind mounts: `./media/`, `./logs/` and, for `web`, `./imports/` (read-only).

The app image runs on the DjangoLux version pinned in `requirements.txt` and
carries these labels: `org.dlux_crm.dlux_baked_version` (the baked DjangoLux
version, used by Composer's version gate), `org.dlux.project.release-manifest`
(the project's `release-manifest.json`, shown in the in-app update review) and
`org.dlux.stack-schema`.

## Starting the stack

```bash
./start.sh -d             # development: compose.dev.yml on top, http://localhost:84
./start.sh -d --build     # rebuild the local image after a dependency or Dockerfile change
./start.sh                # production: the published image, HTTPS on the configured domain
```

`start.sh` (Windows: `start.ps1`) runs the `debeski/composer` deployer, which
reads `.secrets/.env`, starts the stack, waits for health and reports. The
resident services use the `agent run` and `executor run` command form. Other
commands: `check`, `check --fix`, `update`, `update self`, `restart <service>`,
`log -n 200 <service>`, `stop`. `./start.sh check` must exit 0; its
`front-proxy` line is a warning until `DLUX_FRONT_PROXY` is set. Never pass `-v`
or `-p` to `stop`: they delete the database and the other volumes.

The development override builds the image from the working tree, bind-mounts
every project app (`automotive`, `machinery`, `catalog`, `common`, `config`,
`finance`, `public_catalog`, `sales`) into `web`, `worker` and `celery` for live
source changes, and serves plain HTTP on host port 84. `worker` and `celery` keep
the runtime volume read-write, because the rate refresh reaches the internet
through the Composer agent's relay.

Health: `/health/` (Caddy also answers `/_edge-alive` itself and `/health` with
`ok` during maintenance, for a front proxy's probe).

## Settings

Operator settings live in `.secrets/.env` (template: `deploy/env.template`).
Compose reads them; nothing in `compose.yml` needs editing for a normal install.

| Variable | Meaning |
| --- | --- |
| `DJANGO_SECRET_KEY`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Secrets. Never change `POSTGRES_PASSWORD` after the first start. |
| `POSTGRES_DB` | Database name; default `sales_db`. A server whose database has another name keeps that name here. |
| `ADMIN_PASS` | Password of the `admin` account created on the first start. |
| `BASE_URL`, `ALLOWED_URLS`, `ALLOWED_HOSTS` | Public address, trusted origins and hostnames (cookies and CSRF follow `BASE_URL`). |
| `CADDY_SITE_ADDRESS` | Hostname(s), space-separated, served by the app; each gets its own Let's Encrypt certificate. `:80` serves plain HTTP. |
| `CADDY_PRIMARY_URL`, `CADDY_ERP_ADDRESS` | Canonical URL; optional legacy hostname that redirects to `CADDY_PRIMARY_URL/staff/`. |
| `HTTP_PORT`, `HTTPS_PORT`, `CADDY_MAX_SIZE` | Published ports (80, 443) and the upload size cap (`10MB`). |
| `DLUX_FRONT_PROXY` | Proxy or TLS terminator in front of Caddy. Unset trusts every private address, a space-separated list trusts only those, empty trusts none. |
| `DEFAULT_FROM_EMAIL`, `SMTP_RELAY_*` | Fallback mail settings (normally configured in System Settings). |
| `WEB_IMAGE` | Application image; default `debeski/dlux-crm:sales`. |
| `DLUX_UPDATE_CHECK_INTERVAL` | Seconds between update checks (default 86400). |
| `DEBUG_STATUS` | `True` only in development. |
| `COMPOSER_CONTROL_URL`, `COMPOSER_ENROLLMENT_TOKEN` | Optional: control-plane URL and one-use enrolment token for the Composer agent. Leave unset otherwise. |

`config.json` is imported once on the first start. It is a settings snapshot
(system name, theme, language, security and layout defaults); change settings
afterwards in System Settings and Options.

## Domain and automatic HTTPS

Caddy (`.proxy/Caddyfile`) obtains and renews certificates for every hostname in
`CADDY_SITE_ADDRESS` on its own: no certbot, no reload. A plain `./start.sh` is
the whole TLS workflow.

1. Point the A/AAAA records of every hostname (and `CADDY_ERP_ADDRESS`, if used)
   at the server and open inbound TCP 80 and 443.
2. Set `BASE_URL`, `ALLOWED_URLS`, `ALLOWED_HOSTS`, `CADDY_SITE_ADDRESS` and
   `CADDY_PRIMARY_URL` in `.secrets/.env`.
3. `./start.sh`. Certificates persist in `caddy_data`.

The Django URLconf, not Caddy, splits the public site from `/staff/`. Caddy
compresses responses, caps request bodies at `CADDY_MAX_SIZE`, serves `/static/`
with a one-year immutable cache and sends everything else to `web`. It reads
`.proxy/Caddyfile` only when it starts: after editing it, run
`./start.sh restart caddy`. To receive Let's Encrypt expiry notices, add
`{ email you@your-domain.tld }` to the global block (the domain must contain a dot).

### Stored files

`/media/` is served by Caddy after DjangoLux's access check
(`/staff/sys/files/media-access/`):

- public without sign-in: `/media/public/`, `/media/dlux/branding/`,
  `/media/dlux/assets/image/` and `/media/dlux/assets/font/` (storefront images,
  branding, fonts);
- every other stored file (purchase-invoice and expense attachments, receipts)
  only to a signed-in user who may view its document; signed out the answer is `403`;
- `/media/dlux_backups/` is never served (`404`).

`./start.sh check` reports the `stored-files` check; a Caddy still running an old
Caddyfile shows there.

### Maintenance page

During an image update Composer publishes a progress page on the `dlux_runtime`
volume and Caddy serves it (HTTP 503) while `web` is recreated; the page returns
the visitor to the URL they were on once the application answers again. Caddy
serves `/_update/status.json` and `/_update/log.txt` even then.

## First-run checklist

1. Sign in at `BASE_URL/staff/` as `admin` with `ADMIN_PASS` and complete the
   DjangoLux setup wizard (`/staff/sys/setup/`: Arabic/English system name, logo,
   language, theme). The name and logo brand printed invoices, receipts and
   purchase invoices.
2. Create the permission groups: `docker compose exec web python manage.py seed_roles` (from the deployment folder)
   (Sales Manager, Sales Representative, Delivery Courier; see
   [PERMISSIONS.md](PERMISSIONS.md)). Create staff users and add each to one group.
3. Options (`/staff/sys/options/`): turn on what the store uses: the *CRM options*
   tile (pricing currency, products layout, public catalog, point of sale) and
   *Optional enhancements* (Automotive Compatibility, Machinery).
4. **Finance → Exchange Rates**: enter the current USD→LYD rate. The Workspace
   dashboard warns until a rate exists.
5. **Catalog**: categories, products, services, suppliers. **Opening Stock
   (bulk)** loads the stock already on the shelf in one grid (once);
   **Purchase Invoices** and **Add Stock** record later intake.
6. **Shop Builder** (`/staff/shop-builder/`) publishes and features listings for
   the public shop; **Homepage Builder** (`/staff/shop-builder/homepage/`)
   designs the landing page with a live preview.
7. For delivery staff, technicians or anyone carrying advances or payouts, add a
   **Finance → Staff Accounts** row.
8. **Sales → New Invoice**: pick or type a customer, add product and service
   lines, save the draft, issue it, record payments.

Business rules behind these steps are in [BUSINESS_RULES.md](BUSINESS_RULES.md).

## Key URLs

| Path | Page |
| --- | --- |
| `/` | Public landing page |
| `/shop/`, `/shop/items/<slug>/` | Public catalog, public item page |
| `/contact/modal/` | Public contact modal endpoint |
| `/health/` | Health check |
| `/staff/` | Staff entry (redirects to the Workspace dashboard when signed in) |
| `/staff/accounts/login/` | Staff login |
| `/staff/workspace/` | Workspace dashboard |
| `/staff/sys/setup/`, `/staff/sys/options/` | Setup wizard, Options |
| `/staff/sales/dashboard/` | Sales overview |
| `/staff/sales/invoices/`, `/staff/sales/new/` | Invoices, new invoice |
| `/staff/sales/pos/` | Point-of-sale till (when enabled) |
| `/staff/sales/customers/`, `/staff/sales/deliveries/`, `/staff/sales/payments/` | Customers, deliveries, payments |
| `/staff/sales/report/` | Sales report (Excel export) |
| `/staff/sales/financial/` | Fiscal-year financial report |
| `/staff/catalog/` | Products and stock |
| `/staff/catalog/services/`, `/suppliers/`, `/categories/` | Services, suppliers, categories |
| `/staff/catalog/purchase-invoices/` | Purchase invoices |
| `/staff/catalog/stock-movements/` | Stock ledger (Opening Stock, Add Stock) |
| `/staff/catalog/stock-takes/`, `/valuation/` | Stock takes, inventory valuation |
| `/staff/finance/rates/` | Exchange rates |
| `/staff/finance/deposits/`, `/expenses/` | Cash deposits, expenses |
| `/staff/finance/staff-accounts/`, `/staff-ledger/` | Staff accounts, staff ledger |
| `/staff/automotive/`, `/staff/automotive/browse/` | Vehicle data hub, vehicle browser (when enabled) |
| `/staff/machinery/`, `/staff/machinery/browse/` | Machinery hub, machinery browser (when enabled) |
| `/staff/shop-builder/`, `/staff/shop-builder/homepage/` | Public Catalog Builder, Homepage Builder |

The landing page after sign-in is DjangoLux's Home setting (System Settings); set
it to `/staff/sales/pos/` or `/staff/automotive/browse/` to open the till or the
vehicle browser.

## Point-of-sale hardware

- **Barcode scanners**: any USB or Bluetooth scanner that types like a keyboard
  works with the till; no driver.
- **Receipt printers**: choose the paper width in the Point of sale settings and
  print from the browser; set the printer's margins to none.
- **Phone camera scanning** needs a secure page (`localhost` or HTTPS).

## Scheduled work

- **`worker`** runs DjangoLux's own tasks and `DLUX_TASK_SCHEDULE`, and the
  system backups taken from Options > Backups.
- **`celery`** (worker plus Beat, `config/celery.py`) runs one project task:
  `finance.tasks.refresh_market_rates`, every 3 hours and once when the worker
  starts. It scrapes the USD and EUR reference rates from
  [cbl.gov.ly](https://cbl.gov.ly/currency-exchange-rates/) (official) and
  [eanlibya.com](https://www.eanlibya.com/exchangerate/) (black market) and caches
  them in Redis without expiry; a later successful scrape replaces them, and one
  site being down keeps its last value. `web` reads the cache and never makes an
  outbound call. The Workspace dashboard shows both sources next to the in-house
  rate for users with a rate, sales or catalog permission. The figures are
  display-only: invoices freeze the in-house `ExchangeRate`.

`celery` has no internet access of its own. The two page fetches are declared in
`relay/operations.json` (hash-locked in `relay/operations.lock`) and go through the
Composer agent's relay over the shared runtime volume. If the log shows
`RelayError: timeout ... The agent did not answer in time`, the agent was busy
(it checks packages when it starts, which takes minutes on a slow connection):
wait, then `./start.sh restart celery` runs the refresh again; otherwise the next
run comes within 3 hours and the last known rates stay in use.

## Updating

Back up first (Options > Backups, and the `media/` folder), then either:

- **In the app**: Options > Updates and maintenance shows a new application image
  when one is published; install it there. This updates the application image
  only, not `compose.yml`, `.proxy/Caddyfile` or `relay/`.
- **From the deployment folder**: `./start.sh update` refreshes the Composer
  deployer, pulls the images and recreates the services; migrations run on start.

A release that changes the stack files (`compose.yml`, `.proxy/Caddyfile`,
`relay/`, the wrappers) needs those files copied over before `./start.sh`; the
order is in `deploy/README.md`. Composer's version gate refuses to recreate onto
an image whose baked DjangoLux version is older than the running one
(`org.dlux_crm.dlux_baked_version`, `--force` overrides). `./start.sh check --fix`
repairs stack-file drift and keeps the replaced files under `.xclude/`.

## Local development

With Docker: `./start.sh -d` (above). Without Postgres and Redis, a SQLite
and local-memory-cache overlay runs the app, checks and tests on a laptop. It is
not for production:

```bash
python manage.py migrate   --settings=config.settings_dev_sqlite
python manage.py seed_roles --settings=config.settings_dev_sqlite
python manage.py runserver  --settings=config.settings_dev_sqlite
python manage.py test finance catalog sales common public_catalog automotive machinery tests \
    --settings=config.settings_dev_sqlite
```

## Management commands

| Command | Purpose |
| --- | --- |
| `seed_roles` | Create or refresh the permission groups (Sales Manager, Sales Representative, Delivery Courier). |
| `seed_demo [--reset]` | Demo dataset for local testing and screenshots: rates, suppliers, catalog with variants and stock, customers, purchase invoices, stock takes, expenses, staff ledger, deliveries and invoices in every status, plus demo users (`demo_manager`, two representatives, a courier, a technician; password `demo12345`). Reference rows are idempotent; documents are created only when no invoices exist. `--reset` wipes the demo tables first. Never run it on a real store. |
| `seed_machine_categories [--scope ID]` | Add the CIFA concrete-pump vocabulary (machine type, manufacturer, the F8, F9, HPG and ZOOM models, their category branches and services) without changing existing products, prices or compatibility; global, or for one scope. |
| `adopt_image_assets [--apply]` | Move stored product, service and listing images into the DjangoLux asset library (dry run unless `--apply`). |
| `migrator` | Bring a deployment up to date: migrations, `collectstatic`, then first-launch setup (run by `worker`'s `pre_start`). |

## Migrations

App migrations are committed under each app's `migrations/`. After changing a
model: `python manage.py makemigrations && python manage.py migrate`, and update
`docs/` and `CHANGELOG.md` in the same change.
