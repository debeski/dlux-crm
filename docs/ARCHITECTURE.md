# Sales CRM — Architecture

Sales CRM is a web-based sales system (منظومة مبيعات) built on **DjangoLux** (the pinned
version is in `requirements.txt`). It is a single Django/DLux project with a public catalog
surface and an authenticated staff workflow. DjangoLux provides users, permissions,
sidebar/titlebar/navbar UI, dynamic modals, audit trail, soft-delete, reports, backups and
notifications; this project adds the sales, catalog and finance domain plus the public
catalog projection.

## Apps & dependency layering

```
finance          (money foundation: exchange rates, cash deposits, expenses, staff accounts and ledger)
   ▲
catalog          (categories, products, services, purchasing, stock ledger) — uses finance for conversion
   ▲                       ▲                        ▲
sales                automotive               public_catalog
(customers,          (optional vehicle        (curated public listings
 invoices,            compatibility;           linked to catalog
 payments,            references Product,      Product / Service)
 deliveries, POS)     never changes stock
                      identity)
                           ▲
                      machinery
                      (optional machine compatibility; references Product, Service and
                       Category, with an optional link to automotive.VehicleModel)
```

Model-level dependencies run one way, from the upper apps down to `finance`. The stock
ledger references sales invoices by their string number (`StockMovement.reference`), not by
a foreign key, so `catalog` stays independent of `sales`. Where a lower app has to reach an
upper one it imports at call time inside the function: `catalog` forms, views and filters
reach the optional `automotive` and `machinery` extensions, and `finance.currency` reaches
`catalog` and `sales` models when the default currency changes.

App-level settings live in DjangoLux's app-settings store,
`SystemSettings.extra_config['app'][<namespace>]`, and per-user preferences in
`Profile.preferences['app'][<key>]`. These namespaces and keys use the prefix
`sales_crm.` (for example `sales_crm.pricing`, `sales_crm.point_of_sale`). Stores
installed under the product's earlier name held them as `switch_pos.*`; the data
migration `common/migrations/0001_sales_crm_settings_namespaces.py` moves both JSON
columns to the new keys (and back on reverse).

| Key | Owner | Holds |
| --- | --- | --- |
| `sales_crm.pricing` | `finance` | Default currency and the both-currencies flag |
| `sales_crm.optional_enhancements` | `automotive` | Machinery and Automotive switches, Automotive criteria and wording mode |
| `sales_crm.point_of_sale` | `sales` | Till switch, accepted methods, discount cap, receipt size |
| `sales_crm.public_catalog` | `public_catalog` | Public-site switch, shop identity, contact endpoints, shop and homepage live flags, featured limit |
| `sales_crm.public_homepage` | `public_catalog` | Homepage Builder configuration |
| `sales_crm.products_layout` | `catalog` | Shop-wide default Products layout; also the per-user preference key |
| `sales_crm.workspace_dashboard.v1` | `common` | Per-user Workspace dashboard layout (preference key) |
| `sales_crm.crm_options` | `common` | Id of the CRM options group (no stored value of its own) |

Four features are switchable: Automotive and Machinery (Optional enhancements), Point of
sale, and the Public site. While one is off, its routes answer 404 or redirect to the staff
entry, its sidebar entries are hidden (a `sidebar_exclude` switch on the views;
`common.context_processors.crm_context` also filters saved navigation for Automotive,
Machinery and the public builders), and `common.permission_visibility` keeps its
permissions out of the permission editors (the grants themselves are kept). Each switch
defaults to off, except the Public site, which defaults to on.

`automotive/` is an optional extension above `catalog`. Its make/model,
generation, engine, trim and fitment tables reference `catalog.Product`, but no
automotive fields exist on Product, ProductVariant, stock, purchasing or sales
tables. `sales_crm.optional_enhancements` is the single shop-wide configuration source
for both extensions; the Automotive criteria affect only extension UI/query behavior, and
model year, engine and transmission are always on.
When enabled, `/staff/automotive/` is the reference-data hub and the Product
Item card is the reverse-lookup and fitment-maintenance entry point. Lookup
lists reuse `ScopedListView` and DjangoLux modals; Product fitments use a custom
inline formset because several vehicle ranges must be reviewed and saved as one
unit. The generic `/staff/app-modals/...` routes also enforce the enhancement
and criterion switches, so a hidden screen cannot be reached by guessing a URL.
`automotive.browser.VehicleBrowser` serves the runtime-gated
`/staff/automotive/browse/` path. It applies scope/soft-delete policy once,
aggregates distinct Product counts, then progressively narrows an in-memory set
of fitment rows so selecting a qualifier still includes blank broad/all rows.
Only the final Product query carries live category, stock and price data; result
size therefore does not create per-card compatibility queries. Query parameters
are the browser state, making Back, refresh and shared vehicle paths deterministic.
`automotive.fits` is the quick-entry layer: vehicle search, chip parsing and
validation (through `ProductFitment.clean`), additive/replace application, and
part-number sync. `automotive.product_form.AutomotiveProductExtension` grafts the
*Fits vehicles*, part brand and part-number fields onto `catalog.ProductForm`
without touching the Product model: it is attached in `ProductForm.__init__`
only while automotive is on, validates in `clean()`, and saves in `_save_m2m()`,
which DjangoLux's modal save calls after the Product row exists. `PartProfile`
(one-to-one) and `ProductPartNumber` (many, with an indexed normalized column)
are the extension tables. The picker is one widget
(`automotive/widgets/fits_picker.html` + `automotive/js/fits_picker.js`) reused
by the Product modal, the bulk *Assign vehicles* modal, purchase-invoice lines and
the browser's *Find a vehicle* jump; it loads its own static and re-binds on
`dlux:modal-content-loaded`.
Heavy equipment can reuse the same tables: `EquipmentType` groups models,
`VehicleEngine.vehicle_model` may be blank for a shared engine linked to many
models through `fitted_models`, and `ProductFitment.vehicle_model`/years may be
blank (engine-only rows, all years). `VehicleBrowser._expanded_rows()` repeats an
engine-only row once per fitted active model, so every later step counts and
filters it like a model row. `automotive.terminology` registers the vehicle ↔ machine
wording axis, derived from the project's own strings (see *Store wording*).
Vehicle models that a `machinery.MachineModel` links to through `legacy_vehicle_model`
are left out of the vehicle lists, pickers, filters and browser.

`sales.pos` holds the till's lookup and `complete_sale` service; it builds an
invoice with the editor's own pricing helper (`_apply_item_price`), then reuses
`issue_invoice` and `Payment`, so the till adds no parallel sales model — only
`PosSale` (retry key, till name, cash tendered, change). Settings live in the
`sales_crm.point_of_sale` app config (`sales.pos_settings`; form in
`sales/pos_options_forms.py`, registered in `sales/dlux_options.py` as a section of
the CRM options tile). While the till is off its routes answer 404; it needs
`sales.use_pos` plus the invoice-add, invoice-issue and payment-add permissions, and a
discount over the configured cap needs `sales.pos_unlimited_discount`. The cart stays in
the browser (localStorage, per user) and is sent once at checkout; the till page,
lookup, checkout, receipt and vehicle panel (Automotive only) are under `/staff/sales/pos/`.

`common/` is a Django app with no models. Its `ready()` registers the row-ownership
filter for the dynamic-modal lookup, the permission-editor visibility and the wording
signals. It holds `ScopedListView`, `RibbonPageMixin`, the generic
`common/templates/common/scoped_list.html`, form/table/filter helpers, the translation
and wording layer, protected stored-file serving, the CRM options group, the `asset`
template tag and the Workspace dashboard, so every simple list page stays a few lines.

## Public/staff URL split

The split is owned by Django URLconf and DLux settings, not by Caddy path routing.
Caddy proxies the hosts in `CADDY_SITE_ADDRESS` (set in `.secrets/.env`; the
`compose.yml` default `:80` serves plain HTTP on any host) to Django; the optional
legacy host in `CADDY_ERP_ADDRESS` redirects to `CADDY_PRIMARY_URL/staff/`.

- Public routes: `/`, `/shop/`, `/shop/items/<slug>/`,
  `/shop/items/<slug>/modal/`, `/contact/modal/`, and the `/health/` probe.
- Staff routes: `/staff/`, `/staff/accounts/...`, `/staff/sys/...`,
  `/staff/workspace/`, `/staff/catalog/`, `/staff/sales/`, `/staff/finance/`,
  `/staff/automotive/` and `/staff/machinery/` (when enabled), `/staff/shop-builder/`,
  `/staff/shop-builder/homepage/`, `/staff/files/...` and `/staff/app-modals/...`.
  There is no Django admin site.
- `dlux.urls` is mounted below `/staff/`, so `reverse("login")` resolves to
  `/staff/accounts/login/`; staff-only views still use normal Django auth
  (`LoginRequiredMixin`, permissions, and `LOGIN_URL = "login"`).
- `DLUX_CONFIG` in `config/settings.py` sets `home_url` to `/staff/workspace/` and enables
  the public root at `/`; logout lands on `/`. `/staff/` itself redirects a signed-in user
  to the Workspace dashboard and a signed-out one to the login page.

`public_catalog.PublicCatalogListing` links exactly one internal `Product` or
`Service` to a public slug and public copy. Public pages read from those linked
records for safe price/availability display, but they do not expose SKU, barcode,
cost, markup, exact stock counts, internal modal URLs, or staff navigation chrome.
The public item modal returns the standard DLux dynamic-modal JSON shape
(`{"html": ...}`) without rendering the full internal DLux base/config payload.
The storefront UI is project-owned (`public_catalog/templates/public_catalog/*`
and `public_catalog/css/public_catalog.css`): it reuses Bootstrap/DLux variables
for theme fit, but does not extend the staff shell or emit staff navigation.
The landing, shop, contact modal, and `/staff/` entry callbacks set
`sidebar_exclude=True` so DLux sidebar discovery does not offer public pages or
the staff redirect as internal navigation items.

Staff curate the storefront from `/staff/shop-builder/` (`public_catalog.staff_views`,
mounted via `public_catalog.staff_urls`), not Django admin. The builder lists every
active `Product`/`Service` — backed by its real `PublicCatalogListing` or an unsaved
transient one — and its `POST`-only AJAX endpoints (`toggle-publish`, `update-listing`,
`reorder`, `settings`, gated by `public_catalog.change_publiccataloglisting`) create/
update listings, reorder them, and flip global storefront settings. Those
write endpoints never mutate on GET: passive probes return 204 and direct browser
navigation redirects back to `/staff/shop-builder/`. They are marked
`sidebar_exclude=True` so only the two builder pages (`public_catalog_staff:builder` and
`public_catalog_staff:homepage_builder`) are discoverable for sidebar navigation. Global
config lives in the DLux app-settings namespace `sales_crm.public_catalog`: the builders
own the live toggles (the shop toggle in the shop builder, the homepage toggle in the
Homepage Builder), and the `settings` endpoint also accepts the featured limit (default 4),
which has no UI control. The *Public catalog* section of the CRM options tile exposes the
Public site master switch, shop identity, contact endpoints, and the show-price/
show-availability defaults applied to listings the builder creates. While the Public site is
off, the builders and their endpoints are unavailable and the public pages redirect to the
staff entry. When `shop_enabled` is off the public shop and item-detail views return
`coming_soon.html` with HTTP 503 (the item modal answers 404) — except staff with
`view_publiccataloglisting`, who may preview the storefront while offline via `?preview=1`.

The **public landing page** is composed from the Homepage Builder
(`/staff/shop-builder/homepage/`), a live-preview-iframe editor whose config lives in
its own app-settings namespace `sales_crm.public_homepage` (`public_catalog/homepage.py`:
hero copy/CTA/background mode/overlay, primary and secondary accent colours, visual
style preset, hero layout/height/focus, nav/card/density/background/motion treatments,
and an ordered, toggleable list of sections — featured, categories, services, story,
contact). Section config preserves a per-section `variant` (`grid`/`rail`,
`tiles`/`chips`, `split`/`banner`, `band`/`compact`) alongside `key` and `enabled`.
The `style_preset` is a broad art direction that changes page-level geometry,
typography, spacing, and surface treatment (`signature` brand stroke, `showroom`
image-forward display, `precision` flat technical surfaces, `editorial` text-led
serif rhythm); narrower controls such as `card_treatment` and
`background_treatment` then tune individual systems inside that direction. The
`grid` background is CSS-only sparse connected circuit linework, with missing
borders and light theme-aware opacity; `linework` uses stacked thin-angle CSS
gradients to create a denser drawn-rule field without external assets.
`PublicLandingView` and `landing.html` are fully driven by that config; the accents
inject `--public-accent` and `--public-accent-2` CSS variables into `public_base.html`,
and the rest emits class hooks consumed by `public_catalog.css`. The builder preview
uses `?preview=1&lang=<code>` with a request-local language override: it renders the
iframe's homepage content, direction, strings, and language-aware `APP_CONFIG` in the
edited language without writing to the staff user's display-language session; normal
public header `?lang=` clicks persist in the visitor session. Its `homepage_save`
endpoint shares the same POST-only `mutation_endpoint` + `sidebar_exclude` treatment
as the catalog builder. The Homepage Builder is the only UI surface for homepage
copy, sections, visual style, and the homepage live toggle; its config persists
under `SystemSettings.extra_config['app']['sales_crm.public_homepage']` for backups
and settings exports. If `shop_enabled` is off while `homepage_enabled` remains on,
homepage listing cards may appear as public teasers, but they do not render
item-detail links or the Quick view item-modal button.

Storefront text is localized like the staff UI: templates read `DLUX_STRINGS.public_*`
keys from `public_catalog/translations.py` (with the English text as the template
default), code-keyed labels such as availability and product/service kind resolve
through `listing.availability_key` / `listing.source_kind_key` and dlux's `get_item`
filter, and `contact_links()` / `PublicContactForm` use `common.i18n.t`. Homepage
copy fields that equal their English `HOMEPAGE_DEFAULTS` seed resolve to the
visitor-language `hp_seed_<field>` string in `resolve_homepage()`; anything edited in
the Homepage Builder is shown as saved.

`PublicContactMessage` is the public write path. Contact form posts carry a
stable hidden idempotency key enforced by a database unique constraint; repeated
submits with the same key return success without creating a second row or sending
a second email. Email delivery uses the public catalog contact recipient when
configured, falling back to Django's default sender address, and records
`received`/`sent`/`failed`/`skipped` status on the saved row.

## How a screen is built (the dlux pattern)

For **simple models** (products, services, categories, rates, deposits, customers):

- One `ScopedListView` subclass per model (sets `model`, `table_class`,
  `filterset_class`, `permission_required`).
- Create / edit / view / delete are handled by the DjangoLux **dynamic modal
  manager** (`modal_manager`), which auto-resolves `<Model>Form` from the app's
  `forms.py`. No per-model create/update/delete views or templates needed.
- Every form built on `common.forms.build_grid_helper()` opts into DjangoLux's
  unsaved-changes prompt (`form.dlux_unsaved_guard = True`). A custom modal
  fragment with its own `<form>` adds `data-dlux-unsaved-guard` to that tag.
- The list page's "Add" button and the `DluxTable` row context menu open those modals.

`Product.stock_qty` and `ProductVariant.stock_qty` are running balances, applied once per movement by
`StockMovement.save()` — the ledger is the source of truth and the column is a cache of it. The ledger is
append-only: `StockMovement.delete()` raises, and a movement is undone by posting a compensating one. Anything
that writes movements in bulk leaves the balance stale, which is why `catalog/stock_balance.py` rebuilds it from the
live ledger and runs on dlux's `data_reset_finished` signal. Call `rebuild_stock_balances()` after any other bulk
write to that table.

Images are held in the **dlux asset library**. `Product.image_asset`,
`Service.image_asset` and `PublicCatalogListing.image_override_asset` are `ManagedAssetField`s namespaced after
their own model, so one model's photos stay out of another's picker; the listing override also `reads` the catalog
pools because it exists to show a different shot of the same item. The plain `image` / `image_override` columns
remain readable fallbacks until `manage.py adopt_image_assets --apply` has adopted every stored file, so always
read `image_url`, never either field.

Every staff page carries the **dlux ribbon** — its title, description, filters
and actions. A list gets it from `ScopedListView`; a page with no model, table or
FilterSet (the reports, the sales overview, both public-site builders) gets it
from `common.views.RibbonPageMixin` and renders it with `{% dlux_ribbon %}`.
Both resolve the heading from `page_title_key` / `page_subtitle_key` against
`DLUX_STRINGS`, so a page's strings are named the same wherever they live, and
both build their buttons by overriding `get_ribbon_action_specs()`. An action
whose markup needs the page's own context (the homepage builder's live toggle,
language switch and save status) is raw `html` and the view calls
`refresh_ribbon(ctx)` at the end of `get_context_data`, because `RibbonMixin`
otherwise builds the ribbon ahead of anything a subclass adds to the context.

A `.btn-group` inside the ribbon's action area needs
`common/css/ribbon_actions.css` (on `ScopedListView.base_styles`): the
panel skin pills every action button individually, which breaks a segmented
control into loose half-pills.

For the **invoice** (a multi-line document) we use custom full-page views
(`InvoiceCreateView` / `InvoiceUpdateView`) with a Django inline formset, plus
detail/issue/cancel/print/payment endpoints. The line editor is a POS-style
**catalog picker + cart**: `_catalog_map` serialises in-stock products (with
their in-stock `ProductVariant`s) and services (image or `service_type` icon);
`invoice_editor.js` renders a filterable tile grid where a colour/size variant is
picked *at add-time* and dropped into a cart list (`_invoice_cart_row.html`) with
editable price/qty. The formset fields (`product/service/variant/color/size/kind`)
are hidden inputs the picker fills; the server save path is `_apply_item_price`
plus the per-variant stock guard in `issue_invoice` and the stock restoration in
`cancel_invoice`.

Naming convention is load-bearing: `<Model>Form`, `<Model>Table`, `<Model>Filter`
let dlux discovery wire modals, tables and filters automatically.

## Per-user Products layout (table / grid / light)

The Products page renders three ways. The effective layout resolves
**per-user override → global admin default → `table`**, in
`catalog/product_layouts.py::get_products_layout(request)`:

- **Per-user override** — `Profile.preferences['app']['sales_crm.products_layout']`
  (a scalar; same app-preference store as the Workspace dashboard).
- **Global admin default** — a superuser setting saved to
  `SystemSettings.extra_config['app']['sales_crm.products_layout']['default_layout']`,
  edited in the *Products layout* section of the **CRM options** tile (see
  below) and read via `dlux.utils.get_app_system_config`.

`ProductListView` branches on the resolved value:

- **table** — the full `ProductTable`.
- **light** — a minimal `ProductLightTable` (name · price · stock · active); the
  rest stays on the Product *Item card* (`catalog:product_card`).
- **grid** — `catalog/product_grid.html`, a store-style card grid (image, price,
  stock, in-stock colour/size variants) whose *Details* button opens the same Item
  card modal the table rows use. Reuses the table's filtered + paginated rows and
  the themed `.dlux-table-shell` surface.

Per-user switching has two surfaces sharing one component
(`catalog/_products_layout_toggle.html`) and one script
(`catalog/js/products_layout.js`, persists through the reversed
`update_app_preference` URL, e.g. `/staff/sys/api/preferences/app/<namespace>/`,
then reloads only after a successful save): an inline header toggle and a
`/staff/sys/options` card registered with `dlux.options.register_card`
(`catalog/dlux_options.py`, gated on `catalog.view_product`). The global default
is the *Products layout* section of the **CRM options** tile.
`common/scoped_list.html` extends DjangoLux's `dlux/list_page.html` and adds a
`scoped_before_ribbon` slot; the grid layout replaces the inherited
`{% block list_body %}` while keeping the header, filter and modal-CRUD wiring.

### CRM options tile

The store-wide settings are one **CRM options** tile on the Options page — a
DjangoLux settings group. `common/dlux_options.py` registers
it with `register_app_settings_group(id=CRM_OPTIONS_GROUP)`
(`sales_crm.crm_options`, order 50), and each app registers its settings with
`register_app_settings(..., group=CRM_OPTIONS_GROUP)`: *Pricing currency*
(`finance`, order 5), *Products layout* (`catalog`, 10), *Public catalog*
(`public_catalog`, 20) and *Point of sale* (`sales`, 30).
DjangoLux draws them as sections of one modal under its own section headings,
validates them together and saves every namespace in **one** write of the
settings row, so readers such as `get_pos_config()` read their own namespace
directly. The same registrations appear as sections of the first-run setup
wizard's *Project settings* step. *Optional enhancements*
(`automotive/dlux_options.py`, order 70) is a separate tile.

A settings form's `to_app_config()` must only *return* its value: the setup
wizard saves the whole settings row once, so anything a form saves on its own
is overwritten. Side effects that must follow a saved value hang off the row's
signals instead — the store wording does (`common.wording.sync_wording` on
`post_save`) and so does the default-currency conversion
(`finance.currency.convert_on_switch` on `pre_save`).

Settings that depend on a master toggle follow dlux's rule that a disabled
master locks its dependents rather than hiding them: `common/settings_forms.py`
wraps them in `dependent_block(form, master, …)` (greyed, with dlux's
`settings_dependent_disabled` tooltip) and `lock_dependents()` disables the
fields server-side while the master is off, so a save keeps their stored
values. `common/js/dependent_settings.js` (loaded from
`common/templates/dlux/includes/custom_scripts.html`) follows the toggle live.

## Workspace dashboard

`common.views.WorkspaceDashboardView` (`/staff/workspace/`, `common:workspace_dashboard`)
needs only a login: the server decides which tiles exist from the user's permissions and
ownership scope (invoices, stock, finance, the exchange card built from `rate_overview()`,
and quick actions that include the till and the vehicle and machinery browsers while those
are enabled). Order, hidden state and size are saved per user in the app-preference
namespace `sales_crm.workspace_dashboard.v1` through `update_app_preference`, with
`localStorage` as the fallback (`common/js/workspace_dashboard.js`).

## Static assets

Project CSS and JS are linked with `{% load asset_tags %}{% asset 'app/css/file.css' %}`,
which appends a short hash of the file's contents. Caddy serves `/static/` as
`immutable` for a year, so the URL must change whenever the file does; hand-written
`?v=` stamps are forgotten, and `{% dlux_static %}` only changes with the DjangoLux
release. Keep `dlux_static` for DjangoLux's own files.

## Money & currency

`finance/services.py` is the **single source of conversion math**:

- `get_current_rate(currency=None)` — the live currency→LYD rate: the newest
  `ExchangeRate` row for the currency (cached for an hour, independently for USD and
  EUR), else the cached market (EAN) quote, then the official (CBL) quote, then a fixed
  fallback; without a currency it is the store's **default currency** (`pricing_currency()`).
- `usd_to_lyd()` / `lyd_to_usd()` / `eur_to_lyd()` / `quantize_lyd()` —
  conversions with consistent 2-dp rounding. The `usd` names are kept: like
  the `*_usd` columns they mean the associated record's foreign currency.
- `rate_overview()` — both currencies' store, CBL and EAN rates with their
  ages, for the Workspace exchange card, the Sales Overview and the Exchange Rates page.

`finance/currency.py` holds the default currency and `both_active` flag under
`sales_crm.pricing`. Products store their own `currency`; `Product.pricing_rate()` and
`selling_price_lyd()` resolve the product's rate. Purchase headers expose active
currencies under the `catalog.add_purchaseinvoice` permission, rejecting
inactive or unauthorized posted choices. Intake converts invoice-currency amounts
into the target product currency; line snapshots remain in the invoice currency.
`Product.alias`, `MachineModel.alias` and `VehicleModel.alias` hold local names.

`finance.currency.convert_on_switch` (a `pre_save` on `SystemSettings`, connected in
`finance/apps.py`) re-expresses services and draft sales invoices inside a
transaction when the default currency changes, ahead of the settings write. Product
currencies and prices are unchanged. `Invoice.currency` and `PurchaseInvoice.currency`
default to the store currency; issued documents retain their snapshots.
`InvoiceItem.unit_cost_lyd` is a six-decimal product-currency cost snapshot used for
COGS: financial reports prefer it and fall back to cost × invoice rate for lines without
it. Stock valuation and workspace aggregates convert each product independently;
foreign totals are shown separately by currency rather than adding USD and EUR amounts
together.

### Store wording

`common/wording.py` writes store-dependent words into the DjangoLux translation
override layer: apps register *axes* (`automotive.terminology`: vehicle ↔
machine; `finance.wording`: USD ↔ EUR) and the engine generates all axes
together on every `SystemSettings` save and after `migrate`. An override is
treated as ours when it matches what some combination of modes generates;
anything else is an admin's own and is left alone. Keys that name a currency on
purpose (`currency_*`, `pricing_*`, `rate_card_*`, `choice_*`) keep their
wording.

Reuse these everywhere instead of multiplying by a rate inline.

See [BUSINESS_RULES.md](BUSINESS_RULES.md) for pricing and the frozen-rate rule, and
[PERMISSIONS.md](PERMISSIONS.md) for the role model.

## Runtime topology and background tasks

`compose.yml` (project `sales`, stack contract `DLUX_STACK_SCHEMA` 5) runs one
application image in several roles; [OPERATIONS.md](OPERATIONS.md) has the service table
and the procedures.

- **`web`** serves Django on port 8000 (gunicorn; the development server when
  `DEBUG_STATUS=True`) behind `caddy`. It applies no migrations: `entrypoint.sh` waits
  until `migrate --check` passes.
- **`worker`** runs DjangoLux's task worker (`manage.py dlux_worker`: queued tasks,
  `DLUX_TASK_SCHEDULE`, backups) and applies the migrations through its `pre_start` steps
  (`dlux_reconcile`, then `migrator`), with `DLUX_BOOT_GATE=apply` covering a restart that
  skips `pre_start`.
- **`celery`** runs the project's only Celery task, `finance.tasks.refresh_market_rates`
  (`celery -A config worker -B`; `config/celery.py`). Beat runs it every 3 hours and the
  `worker_ready` signal runs it once at start. It refreshes the CBL (official) and EAN
  (market) quotes for USD and EUR into the Redis cache without expiry: a later successful
  scrape replaces a value and a failing site keeps its last one. `celery` has no internet
  access, so the page fetches go through the Composer agent's relay
  (`relay/operations.json`: `finance.cbl_rates_page`, `finance.ean_rates_page`); `web`
  only reads the cache. The service stays until the task moves to `dlux.taskrunner`
  (`compose.yml` notes that Celery leaves DjangoLux in 1.17).
- **`db`** (PostgreSQL) and **`redis`**: Redis database 1 holds the Django cache and the
  sessions (`SESSION_ENGINE` is cache-backed), 2 the Celery broker and 3 the Celery result
  backend; it runs with an append-only file.
- **`caddy`** is the only published ingress (`frontend` network): TLS, `/static/`, the
  `/media/` access check, the maintenance page and the proxy to `web`.
- **`smtp-relay`** (`python -m dlux.smtp_relay`) receives the app's mail on port 1025
  (`EMAIL_HOST`); it and `composer-agent` are the only services on the `egress` network.
- **`composer-agent`** (image-update requests, the outbound relay, the maintenance page)
  has no Docker authority: it reaches the Docker API only through `docker-socket-proxy`
  (read-only, no POST) on the `docker_proxy` network, and `composer-executor` alone has
  write access to the Docker socket and performs the updates.

`internal` and `docker_proxy` have no internet access; no service sits on both `frontend`
and `egress`. Volumes are `postgres_data`, `redis_data`, `static`, `dlux_runtime`,
`composer_agent_state`, `composer_exec_sock`, `caddy_data` and `caddy_config`, plus the
`./media/`, `./logs/` and `./imports/` bind mounts.

## Security baseline

- Every domain record extends `dlux.models.ScopedModel`: created/updated/deleted
  audit fields, soft-delete (`delete()` never hard-deletes), and optional scope
  isolation. Line and child tables (`InvoiceItem`, `PurchaseInvoiceLine`,
  `ProductVariant`, `StockTakeLine`) are plain models owned by a scoped parent.
  `StockMovement`, `PaymentResolution` and `CustomerCreditUse` refuse deletion outright.
- Staff views require a login. List pages (`ScopedListView`) send an anonymous visitor
  to the login page and answer a signed-in user without the permission with 403; other
  views combine `PermissionRequiredMixin` with `raise_exception = True`. The Workspace
  dashboard needs only a login and builds its tiles from the user's permissions. Lifecycle
  actions (issue, deposit and expense review, staff-ledger actions) accept POST only and
  are permission-gated; cancellation and credit application show their form on GET and
  change state only on POST.
- Row visibility: a model with `OWNER_FIELDS` is filtered by `common.access.apply_ownership`
  at the read boundaries (lists, the dynamic-modal lookup, invoice detail and reports), so an
  employee sees only their own records unless they hold the model's `view_all_<model>`
  permission.
- `config/settings.py` sets the Content-Security-Policy (`csp.middleware.CSPMiddleware`),
  CSRF and session cookies (secure when `BASE_URL` is https, `SameSite=Lax`, cache-backed
  sessions of one week) and HSTS outside DEBUG.
- Stored paperwork (`PurchaseInvoice.attachment`, `Expense.attachment`) uses
  `common.files.ProtectedFileField`: its `.url` is `common:stored_file`
  (`/staff/files/<app>/<model>/<pk>/<field>/`), which checks login, the record's
  `view_<model>` permission, scope and `OWNER_FIELDS` ownership, then answers with
  DjangoLux's `serve_file` (byte ranges, revalidation). Their folders are
  `DLUX_APP_ONLY_MEDIA`, so the `/media/` access check refuses them to everyone.
- Stored files are private by default: Caddy serves a `/media/` file outside the public
  folders only when `forward_auth` at `/staff/sys/files/media-access/` approves it. Branding, managed images and fonts, and `media/public/` are served to anyone;
  `DLUX_PUBLIC_MEDIA` keeps product, service and listing images public for the storefront;
  other stored files need a signed-in user, and `/media/dlux_backups/*` answers 404.
  `config/urls.py` also answers `/sys/files/media-access/` for Composer's generated fix.

## Cancellation payments and customer credit

`sales.PaymentResolution` records one immutable refund or customer-credit
allocation per original `Payment` (OneToOne/PROTECT), with amount, method,
customer, timestamp, actor, and optional notes. An unresolved cancellation is
represented by cancelled-invoice receipts without a resolution.

`sales.CustomerCreditUse` links a credit resolution to a later invoice with a
positive LYD amount and a unique request UUID. `Invoice.recalc_payments()` adds
cash receipts and credit allocations, while credit availability excludes uses
whose target invoice is cancelled. This releases credit without creating
cash or altering original receipts. Services lock the Customer first, then the
invoice/source credit; receipt creation/deletion takes matching locks so a
payment cannot be appended to a concurrently cancelled invoice.

Cancellation and credit application use the Dlux dynamic-modal protocol, with
full-page fallbacks, in `sales/payment_resolution_views.py`. Read boundaries
scope target invoices, customers, and source invoices by ownership. Credit
allocations are separate from `Payment`, preventing reuse from double-counting
cash/deposits. Financial-report refund outflows use settlement dates, while
credit and pending-refund liabilities are current snapshots.

## Rate and report pages

The exchange-rate overview extends the scoped DLux list and renders its current-rate summary as two compact USD/EUR `dlux_card` control surfaces using the DLux control-panel stylesheet and theme variables. The scoped-list `scoped_before_ribbon` extension slot places this summary above the ribbon without copying the DLux list shell. The cards share a desktop row and stack on mobile, with working-rate/source badges and manual/market/CBL quotes.

Sales Overview and Exchange Rates share `finance/includes/currency_wall.html`, using the same working-rate source, reference quotes, timestamps and responsive DLux cards. Exchange Rates places them above its ribbon; Sales Overview embeds them in its summary-card row with flexible columns that fill available space and stack on narrow screens.

Sales Report date filters use `data-dlux-entry-clipboard="false"` to opt out of the DLux assisted-entry clipboard bar.

Inventory Valuation, Sales Overview, Sales Report and Financial Report use the standard `dlux-list-page` wrapper inside the already padded DLux shell; avoid nested `container-fluid py-4` padding.

## Independent machinery enhancement

`machinery` references catalog products and services through compatibility many-to-many fields on `MachineModel` (`products`, `services`, plus `categories` for category branches), alongside the `automotive` app. Its type/manufacturer/model vocabulary (`MachineType`, `Manufacturer`, `MachineModel`) has no vehicle qualifiers; `MachineModel.legacy_vehicle_model` optionally links a machine to an `automotive.VehicleModel`. The machinery switch lives in `sales_crm.optional_enhancements`, and its routes answer 404 while it is off. `catalog.Category.parent` provides nested part branches; service-only leaves use `is_service`, and `Service.category` places Repair in the same browser tree. See [client diagram implementation](CLIENT_CATEGORIZATION.md).
