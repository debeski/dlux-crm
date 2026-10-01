# Switch POS — Architecture

A web-based sales system (منظومة مبيعات), built on **DjangoLux (dlux 1.10.0)**.
It is a single Django/DLux project with a public catalog surface and an authenticated
staff workflow. DjangoLux provides users, permissions, sidebar/titlebar/navbar UI,
dynamic modals, audit trail, soft-delete, reports, backups and notifications — this
project adds the Switch sales/catalog/finance domain plus the public catalog projection.

## Apps & dependency layering

```
finance   (money foundation: exchange rate, cash deposits, expenses, staff accounts)
   ▲
catalog   (products, services, stock ledger) — uses finance for conversion
   ▲                         ▲
sales     (customers,       automotive (optional vehicle compatibility;
           invoices,        references Product, never changes stock identity)
           payments)

public_catalog (curated public listings linked to catalog Product/Service)
```

Lower layers **never** import higher ones. The stock ledger references invoices by
their string number (not a FK) so `catalog` stays independent of `sales`.

`automotive/` is an optional extension above `catalog`. Its make/model,
generation, engine, trim and fitment tables reference `catalog.Product`, but no
automotive fields exist on Product, ProductVariant, stock, purchasing or sales
tables. `SystemSettings.extra_config['app']['switch_pos.optional_enhancements']`
is the single shop-wide configuration source; the Automotive master switch
defaults off, and its criteria affect only extension UI/query behavior.
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
Heavy equipment reuses the same tables: `EquipmentType` groups models,
`VehicleEngine.vehicle_model` may be blank for a shared engine linked to many
models through `fitted_models`, and `ProductFitment.vehicle_model`/years may be
blank (engine-only rows, all years). `VehicleBrowser._expanded_rows()` repeats an
engine-only row once per fitted active model, so every later step counts and
filters it like a model row. `automotive.terminology` derives the machine
wording from the project's own strings and stores it in
`SystemSettings.translations_override`.

`sales.pos` holds the till's lookup and `complete_sale` service; it builds an
invoice with the editor's own pricing helper, then reuses `issue_invoice` and
`Payment`, so the till adds no parallel sales model — only `PosSale` (retry key,
cash given, change). Settings live in the `switch_pos.point_of_sale` app config
(`sales.pos_settings`, card in `sales/dlux_options.py`). Phase 1 keeps the cart
in the browser (localStorage) and sends it once at checkout; the till page,
lookup, checkout, receipt and vehicle panel are under `/staff/sales/pos/`.

`common/` is a plain Python package (not a Django app, no models). It holds
`ScopedListView`, `RibbonPageMixin` and the generic
`common/templates/common/scoped_list.html` so every simple list page stays a few
lines.

## Public/staff URL split

The split is owned by Django URLconf and DLux settings, not by Caddy path routing.
Caddy proxies `switchlibya.ly`/`www.switchlibya.ly` to Django; the optional legacy
`erp.switchlibya.ly` host redirects to `https://switchlibya.ly/staff/`.

- Public routes: `/`, `/shop/`, `/shop/items/<slug>/`,
  `/shop/items/<slug>/modal/`, and `/contact/modal/`.
- Staff routes: `/staff/`, `/staff/accounts/...`, `/staff/sys/...`,
  `/staff/workspace/`, `/staff/catalog/`, `/staff/sales/`, `/staff/finance/`,
  `/staff/automotive/` (when enabled), `/staff/shop-builder/`,
  `/staff/shop-builder/homepage/`, `/staff/app-modals/...`, and `/staff/admin/`.
- `dlux.urls` is mounted below `/staff/`, so `reverse("login")` resolves to
  `/staff/accounts/login/`; staff-only views still use normal Django auth
  (`LoginRequiredMixin`, permissions, and `LOGIN_URL = "login"`).
- DLux `SystemSettings.home_url` is `/staff/workspace/`, while public-root settings
  are enabled with public root URL `/`; logout lands on `/`.

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
update listings, reorder featured items, and flip global storefront settings. Those
write endpoints never mutate on GET: passive probes return 204 and direct browser
navigation redirects back to `/staff/shop-builder/`. They are marked
`sidebar_exclude=True` so only `public_catalog_staff:builder` is discoverable for
sidebar navigation. Global config lives in the DLux app-settings namespace
`switch_pos.public_catalog`: the builders own the live toggles and featured limit,
while the remaining DLux Options tile exposes only shop identity, contact endpoints,
and new-listing show-price/show-availability defaults. When `shop_enabled` is off
the public shop/detail/modal views return `coming_soon.html` with HTTP 503 — except
staff with `view_publiccataloglisting`, who may preview the storefront while offline
via `?preview=1`.

The **public landing page** is composed from the Homepage Builder
(`/staff/shop-builder/homepage/`), a live-preview-iframe editor whose config lives in
its own app-settings namespace `switch_pos.public_homepage` (`public_catalog/homepage.py`:
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
public header `?lang=` clicks still persist in the visitor session. Its `homepage_save`
endpoint shares the same POST-only `mutation_endpoint` + `sidebar_exclude` treatment
as the catalog builder. The Homepage Builder is the only UI surface for homepage
copy, sections, visual style, and the homepage live toggle; its config still persists
under `SystemSettings.extra_config['app']['switch_pos.public_homepage']` for backups
and settings exports. If `shop_enabled` is off while `homepage_enabled` remains on,
homepage listing cards may still appear as public teasers, but they do not render
item-detail links or the Quick view item-modal button.

Storefront text is localized like the staff UI: templates read `DLUX_STRINGS.public_*`
keys from `public_catalog/translations.py` (with the English text as the template
default), code-keyed labels such as availability and product/service kind resolve
through `listing.availability_key` / `listing.source_kind_key` and dlux's `get_item`
filter, and `contact_links()` / `PublicContactForm` use `common.i18n.t`. Homepage
copy fields that still equal their English `HOMEPAGE_DEFAULTS` seed resolve to the
visitor-language `hp_seed_<field>` string in `resolve_homepage()`; anything edited in
the Homepage Builder is shown as saved.

`PublicContactMessage` is the first public write path. Contact form posts carry a
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
- The list page's "Add" button and the `DluxTable` row context menu open those modals.

`Product.stock_qty` and `ProductVariant.stock_qty` are running balances, applied once per movement by
`StockMovement.save()` — the ledger is the source of truth and the column is a cache of it. Anything that writes
movements in bulk therefore leaves the balance stale, which is why `catalog/stock_balance.py` rebuilds it from the
live ledger and runs on dlux's `data_reset_finished` signal. Call `rebuild_stock_balances()` after any other bulk
write to that table.

Images are held in the **dlux asset library**, never as a plain `ImageField`. `Product.image_asset`,
`Service.image_asset` and `PublicCatalogListing.image_override_asset` are `ManagedAssetField`s namespaced after
their own model, so one model's photos stay out of another's picker; the listing override also `reads` the catalog
pools because it exists to show a different shot of the same item. Always read `image_url`, never the field: the
old columns stay populated until `adopt_image_assets --apply` has adopted every stored file.

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
otherwise builds the ribbon before a subclass has added anything.

A `.btn-group` inside the ribbon's action area needs
`common/css/ribbon_actions.css` (already on `ScopedListView.base_styles`): the
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
are hidden inputs the picker fills; the server save path (`_apply_item_price` +
the per-variant issue/cancel stock guard) is unchanged.

Naming convention is load-bearing: `<Model>Form`, `<Model>Table`, `<Model>Filter`
let dlux discovery wire modals, tables and filters automatically.

## Per-user Products layout (table / grid / light)

The Products page renders three ways. The effective layout resolves
**per-user override → global admin default → `table`**, in
`catalog/product_layouts.py::get_products_layout(request)`:

- **Per-user override** — `Profile.preferences['app']['switch_pos.products_layout']`
  (a scalar; same app-preference store as the workspace dashboard).
- **Global admin default** — a superuser setting saved to
  `SystemSettings.extra_config['app']['switch_pos.products_layout']['default_layout']`,
  edited in the *Products layout* section of the **CRM options** tile (see
  below) and read via `dlux.utils.get_app_system_config`.

`ProductListView` branches on the resolved value:

- **table** — the full `ProductTable`.
- **light** — a minimal `ProductLightTable` (name · price · stock · active); the
  rest stays in the record's dlux detail modal (`Product.get_modal_context`).
- **grid** — `catalog/product_grid.html`, a store-style card grid (image, price,
  stock, in-stock colour/size variants) whose Expand action opens the same dlux
  detail modal the table rows use (`scoped_modal_manager … ?action=view`). Reuses
  the table's filtered + paginated rows and the themed `.dlux-table-shell` surface.

Per-user switching has two surfaces sharing one component
(`catalog/_products_layout_toggle.html`) and one script
(`catalog/js/products_layout.js`, persists through the reversed
`update_app_preference` URL, e.g. `/staff/sys/api/preferences/app/<namespace>/`,
then reloads only after a successful save): an inline header toggle and a
`/staff/sys/options` card registered with `dlux.options.register_card`
(`catalog/dlux_options.py`, gated on `catalog.view_product`). The global default
is the *Products layout* section of the **CRM options** tile. The shared
`templates/common/scoped_list.html` exposes a `{% block list_body %}` so alternate
layouts can replace the table body while keeping the header, filter and modal-CRUD
wiring.

### CRM options tile

The store-wide settings are one **CRM options** tile on the Options page — a
DjangoLux settings group (dlux ≥ 1.10.0). `common/dlux_options.py` registers
it with `register_app_settings_group(id=CRM_OPTIONS_GROUP)`
(`switch_pos.crm_options`, order 50), and each app registers its settings with
`register_app_settings(..., group=CRM_OPTIONS_GROUP)`: *Products layout*
(`catalog`), *Public catalog* (`public_catalog`) and *Point of sale* (`sales`).
DjangoLux draws them as sections of one modal under its own section headings,
validates them together and saves every namespace in **one** write of the
settings row, so readers such as `get_pos_config()` are unchanged. The same
registrations appear as sections of the first-run setup wizard's *Project
settings* step. *Optional enhancements* (store types) stay a separate tile.

A settings form's `to_app_config()` must only *return* its value: the setup
wizard saves the whole settings row once, so anything a form saves on its own
is overwritten. Side effects that must follow a saved value hang off the row's
`post_save` instead — the store wording does
(`common.wording.sync_wording`).

Settings that depend on a master toggle follow dlux's rule that a disabled
master locks its dependents rather than hiding them: `common/settings_forms.py`
wraps them in `dependent_block(form, master, …)` (greyed, with dlux's
`settings_dependent_disabled` tooltip) and `lock_dependents()` disables the
fields server-side while the master is off, so a save keeps their stored
values. `common/js/dependent_settings.js` (loaded from
`templates/dlux/includes/custom_scripts.html`) follows the toggle live.

## Static assets

Project CSS and JS are linked with `{% load asset_tags %}{% asset 'app/css/file.css' %}`,
which appends a short hash of the file's contents. Caddy serves `/static/` as
`immutable` for a year, so the URL must change whenever the file does; hand-written
`?v=` stamps were forgotten, and `{% dlux_static %}` only changes with the DjangoLux
release. Keep `dlux_static` for DjangoLux's own files.

## Money & currency

`finance/services.py` is the **single source of conversion math**:

- `get_current_rate(currency=None)` — the live currency→LYD rate (newest
  matching `ExchangeRate` row, cached independently for USD and EUR); without a
  currency it is the store's **pricing currency** (`finance.currency`).
- `usd_to_lyd()` / `lyd_to_usd()` / `eur_to_lyd()` / `quantize_lyd()` —
  conversions with consistent 2-dp rounding. The `usd` names are historic: like
  the `*_usd` columns they mean the pricing currency.
- `rate_overview()` — both currencies' store, CBL and EAN rates with their
  ages, for the Workspace exchange card and the Sales Overview.

`finance/currency.py` holds the pricing currency (`switch_pos.pricing`, a CRM
options section) and the switch: `convert_on_switch` on `SystemSettings`
`pre_save` converts catalog prices and draft sales invoices inside a
transaction before the new currency is written, so the tile, the setup wizard and
configuration imports all convert, and a failed conversion keeps the old
currency. `Invoice.currency` / `PurchaseInvoice.currency` default to the pricing
currency (existing rows were migrated as USD).

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

## Security baseline

- Every domain model extends `dlux.models.ScopedModel`: created/updated/deleted
  audit fields, soft-delete (`delete()` never hard-deletes), and optional scope
  isolation.
- Every view is `LoginRequiredMixin` + `PermissionRequiredMixin` with
  `raise_exception=True`; lifecycle actions (issue/cancel/confirm) are POST-only
  and permission-gated.
- Project security settings (CSP, CSRF/session cookies, HSTS) come from the dlux
  project scaffold in `config/settings.py`.
