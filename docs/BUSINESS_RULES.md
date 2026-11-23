# Sales CRM — Business Rules

## Currency

- Products keep their own **USD** or **EUR** pricing currency (`Product.currency`).
  The `cost_usd` / `price_usd` column names store amounts in that currency.
  Local selling prices use the corresponding live rate, or a manual LYD override.
- CRM options → Default currency (`sales_crm.pricing`) offers **USD / EUR / BOTH** in one selector. USD or EUR sets the default currency for products, invoices, purchase invoices and services. BOTH keeps the current default and
  allows buyers to choose either currency per purchase invoice. Existing purchase
  permissions apply (`catalog.add_purchaseinvoice`); there is no additional currency-selection permission.
- In single-currency mode, currency controls are hidden in product/intake forms and the purchase header; purchases use the default currency. Posting an
  alternative currency is rejected. Existing products keep their recorded
  currency and can be purchased with conversion.
- Purchase-line cost and selling-price inputs are in the **invoice currency**.
  The line's Product currency selects how these amounts are stored in the
  catalog; existing products default to their own currency, created products to
  the invoice currency. Cross-currency intake requires available rates for
  both currencies and converts via LYD, rounded to two decimals. The invoice
  keeps its original foreign amounts and frozen rate.
- Changing the default does **not** reprice products. It converts service prices and
  draft sales invoices at the current rates: rates for both currencies must be available, and a
  confirmation is required when services carry prices. Issued documents keep their own currency and
  amounts. Services use the default currency. For example, a EUR product costing €20 and selling at €30 keeps these amounts after selecting USD-only; its LYD value continues using the EUR working rate. No parallel USD price is stored. The local alias field spans the product-form row when its currency selector is hidden.
- A currency's working rate is its latest manual rate, else the cached scraped market rate, else the cached CBL official rate. When none exists a placeholder rate of 6.00 applies and the Workspace shows a *Rate Needed* warning. Celery refreshes both external rates every three hours; a missing manual entry does not block conversions while a collected rate is available.
- USD and EUR exchange rates (`ExchangeRate`) have independent histories; the newest row is the manual rate in use.
  The Workspace shows each working rate with its source plus the scraped reference rates. The exchange-rate list includes a current USD/EUR summary (working/manual/market/CBL and collection timestamps) above the manual rate history; collected rates do not create manual overrides. Sales Overview also shows rate references.
- Opening-stock rows/workbooks support Currency and Local Alias. Sheets
  without these columns keep an existing product's currency or use the default
  for a created item. Costs and prices in each row are in its product currency.

## Pricing model — hybrid (per-product foreign currency + optional LYD override)

For each `Product`:

1. Cost is stored in the product's currency (`cost_usd`). A `markup_percent` (or an explicit
   `price_usd`) yields the **selling price** in the product's currency (`effective_price_usd`).
   `Product.save()` **persists** this derived `price_usd` when only cost + markup
   were entered, so the stored record (and its detail view) never shows 0.
2. The **LYD selling price** is derived live: `effective_price_usd × current_rate`.
   Changing a currency's rate updates products priced in that currency.
3. Any item may set a manual **`price_lyd_override`** — a fixed LYD price that
   bypasses conversion (for odd / unrelated goods the store occasionally resells).
   Left blank, the item sells at the live rate (the default).

The create/edit form keeps these fields in step as you type (`catalog/js/price_sync.js`):
editing markup recomputes the foreign price, editing the foreign price recomputes the markup,
editing cost recomputes the foreign price (markup held) while the manual LYD override is
blank, and the live LYD price is shown as the manual-LYD field's **placeholder**.
Typing a value into that field turns it into a real fixed override (and back-fills
the foreign price + markup to match); while that override is present, changing the cost keeps the
LYD price fixed and recalculates the implied foreign price + markup from the edited cost.
The detail view adds a computed **"Selling Price (LYD)"** row (via
`get_modal_context`) so it matches the list.

`Service` items follow the same override logic and may also be **"per job"**
(no fixed price — entered on the invoice).

## Local aliases

Products/parts and vehicle/machine models have an optional `alias` field for
local Libyan names, alongside the official name. Aliases are editable in the
product/model forms and in purchase/opening-stock intake for products.
Product lists, sales picker, till, direct parts search, vehicle suggestions and
model lists search aliases. Intake suggestions keep the original product ID
and official name; an ambiguous alias is not automatically matched. Aliases are
separate from barcodes and OEM/cross-reference numbers.

## Frozen rate per invoice

When an invoice is created it records the pricing currency in `Invoice.currency`
and captures that currency's current rate into `Invoice.exchange_rate`, and every
line stores its own frozen `unit_price_lyd`. Product costs are frozen in
`unit_cost_lyd` at six decimal places using the product currency's rate; financial
reports use this snapshot so mixed-currency COGS survives subsequent rate and
product edits. Purchase invoices do the same
(`PurchaseInvoice.currency`); invoice pages and printouts show the document's own
currency, not the store's default. **Rate changes never
rewrite a past invoice's totals.** An issued invoice is final.

## Invoice lifecycle

```
draft ──issue──▶ issued ──payment──▶ partial ──payment──▶ paid
draft / issued / partial / paid ──cancel──▶ cancelled
```

Only drafts are editable. Cancelling an invoice that had drawn stock restores it.

- **Totals**: a line total is unit price × quantity, rounded half-up to two decimals. A percentage
  discount, when set, replaces the fixed discount amount; the discount never exceeds the subtotal.
- **Draft**: editable; no stock impact.
- **Issue** (`issue_invoice`): links the latest manual rate record of the invoice currency (when one exists) and **draws down stock**
  (a `StockMovement` OUT per product line). Requires at least one item. **Blocked**
  if any tracked product or selected color/size variant would go negative —
  demand is summed per product for no-variant lines and per `ProductVariant`
  for variant lines; the issue is refused (nothing changes) with shortages named.
- **Payments**: each `Payment` updates `amount_paid` and advances status
  (`issued → partial → paid`). Payments link optionally to a `CashDeposit`.
- **Cancel** (`cancel_invoice`): if the invoice had drawn stock, it is **restored**
  via reversing `StockMovement` IN rows. Cancelled invoices have zero balance
  due and are excluded from sales revenue/outstanding aggregates. Original
  totals and payment receipts remain as history. Cancellation opens a payment
  settlement dialog with three choices: **Refund payments** (record money already
  returned, with cash/card/bank/cheque method and optional notes), **Customer
  credit** (requires a linked customer), or **Resolve later** (default). Each
  original receipt can be resolved exactly once; a partially paid invoice can
  only refund/credit the money actually received, not its unpaid balance.
- **Unresolved cancellation payments**: the cancelled invoice shows the amount
  still owed to the customer and a **Resolve payments** action. Staff record the
  actual disposition; nothing is refunded or credited automatically.
- **Customer credit**: available LYD credit appears in the customer list and on
  eligible issued/partially paid invoices. **Apply customer credit** (`sales.add_payment`) chooses an
  original receipt and an amount up to both its available credit and the target
  invoice balance. It creates a non-cash `CustomerCreditUse`, advances payment
  status, and contributes to `amount_paid`; it creates no cash receipt or
  deposit. Request UUIDs prevent duplicate application, and customer/invoice
  locks serialize credit use against cancellation and other credit requests.
- **Cancelling credit-paid invoices**: credit allocations stay as
  history but do not consume their source credit; the credit is available to
  the same customer again. Only actual cash/card/bank/cheque receipts on the
  cancelled invoice enter its refund/credit settlement. Repeated cancellation
  neither restores stock nor resolves a receipt twice.
- **Financial reporting**: original receipts stay in gross collected cash;
  refunds are separate outflows dated by `resolved_at`, and net collected is
  gross receipts minus refunds. Available customer credit and unresolved
  cancellation payments are current customer liabilities, separate from
  revenue/expenses. Sales-report Paid includes cash and applied customer credit.
  Cancellation never rewrites a linked cash deposit.
- **History protection**: `PaymentResolution` and `CustomerCreditUse` are
  append-only records. Cancelled invoice receipts cannot be edited/deleted or
  receive payments through the payment service. Refund recording does not
  initiate a bank/card transfer; return the money first, then record it.
- **Draft line removal**: removing a line, including one added in the same editing session, removes it on
  save. Each removed line keeps its formset index and submits its `DELETE`
  checkbox; its inputs are disabled except for `id`/`DELETE`, and a validation redisplay keeps removed lines hidden.
- In the invoice and payment lists, row actions live in the standard **DjangoLux
  context menu** (right-click, long-press, or double-click primary action). The
  invoice number / receipt number columns are display values, not hidden action
  triggers. Print actions from those menus open in a new browser tab so the
  current workflow is not replaced.

## Payment receipts (إيصال قبض)

Every recorded `Payment` has its own durable receipt number
(`Payment.receipt_number`, generated as `RCT-000001`). Staff can print the receipt from
the row context menu in the invoice's payments table or the standalone payments
list at `/staff/sales/payments/<id>/receipt/`; receipt print actions open in a new tab.

The receipt uses the same official logo from DjangoLux System Settings as the
printed invoice. It shows the customer/invoice, amount collected, method,
payment time, receiving user, optional cash-deposit reference, amount already paid
at that receipt, and the invoice balance **after this specific receipt**. It is
gated by `sales.view_payment` and the same `Payment` row ownership rules as the
payments list, so a rep cannot open another rep's receipt by guessing the URL.

## Catalog images

Products and Services carry an optional photo (`image_asset`, read through `image_url`). It's shown as a thumbnail
in the catalog lists and enlarged in the item's detail card. On a phone the upload
field offers the camera or the gallery. Purely descriptive — it never affects
pricing, stock or invoices.

## Products list layout

Each user chooses a **Table**, **Grid** or **Light** layout for the Products list (per-user preference `sales_crm.products_layout`).
CRM options → Products layout sets the store-wide default (Table); a user's own choice overrides it.

## Public catalog

**Public site switch.** System settings → CRM options → Public catalog starts with a
*Public site* toggle (`sales_crm.public_catalog.enabled`, default on;
`public_catalog.options_forms.PublicCatalogSettingsForm`). Off makes the install
staff-only: `/`, `/shop/` and item pages redirect to `/staff/` (`staff_entry`), the item
and contact modals return 404, both builders redirect to the staff home with a notice and
their POST endpoints return 404, the builders leave the sidebar
(`common.context_processors.crm_context`), and the `public_catalog` permission cards are
hidden (grants kept). The section's other fields are greyed out and keep their values;
the builders' homepage/shop live flags and featured limit are preserved, so switching
back on restores the site as it was. While the public site is on, the homepage and the shop each have a
live flag; a surface that is not live answers with a coming-soon page (HTTP 503), and staff holding
`public_catalog.view_publiccataloglisting` can preview it with `?preview=1`.

The public catalog is a curated read-only projection of internal catalog records.
`public_catalog.PublicCatalogListing` links exactly one active Product or one active
Service to a public slug, title, summary/body, optional public image override,
installation notes, warranty notes, and publish flags.

Public pages (`/`, `/shop/`, `/shop/items/<slug>/`, and the item modal endpoint)
may show public title/copy, customer-facing image, LYD selling price, broad
availability labels (`Available`, `Limited availability`, `Available to order`,
`By appointment`, `Currently unavailable`), and color/size option labels. A service is
*By appointment*; a product that does not track stock is *Available to order*; a
tracked product is *Currently unavailable* at zero stock, *Limited availability* at or
below its reorder level (3 when the reorder level is 0), otherwise *Available*. Each listing
decides whether it shows its price, its availability and whether it stays visible while unavailable.
Pages render
through the public storefront templates and dynamic quick-view modal. They
must not show SKU, barcode, import cost, markup, exact product/variant stock
counts, staff modal URLs, or internal staff chrome.

The public contact modal (`/contact/modal/`) is allowed to write
`PublicContactMessage` rows. Each browser attempt carries a stable idempotency
key, enforced by a database unique constraint, so retries create one message and
send at most one email. The saved message remains the source of truth even if the
SMTP side effect fails; staff can inspect `email_status` and `email_error` in
admin. Reservation, purchase, checkout, and payment capture paths must
follow the same rule: database-backed idempotency first, Celery/Redis only for
retryable side effects, races, or throttling support.

## Product variant attributes

Products can have stock-bearing `ProductVariant` buckets identified by `color`
and `size`. `color` is limited to the 15-color palette exposed in stock-intake
rows (black, gray, white, red, blue, green, yellow, orange, purple, pink, brown,
beige, navy, gold, teal). `size` is a free-form **Size / Spec** field for actual
size, capacity, measurements, model-specific descriptors, or whatever the product
requires.

`Product.stock_qty` is the aggregate total. `ProductVariant.stock_qty`
tracks the available quantity for a specific color/size bucket, so the same
product can hold orange and blue stock at the same time without either
overwriting the other. Pricing, cost, valuation, permissions, and low-stock rules
stay product-level. Opening Stock and Purchase Invoices create or top up
variants; a manual Stock Movement can target an existing variant; Product create/edit stays focused on identity and
pricing. Product list/detail views show available variant swatches with
quantities. Purchase invoice lines and sales invoice item lines snapshot the
variant values used at intake/sale time, so catalog edits do not rewrite
issued or posted documents.

## Inventory

- `Product.stock_qty` is **only** changed through `StockMovement` (the ledger is
  authoritative); it is not editable on the product form. Use Opening Stock once
  for first adoption, Purchase Invoices for normal inbound stock, and manual
  Stock Movements only for one-off corrections/adjustments.
- The ledger is append-only: a movement cannot be deleted. It is undone by a compensating
  movement (cancelling an invoice posts Stock In rows) or corrected by an Adjustment.
- Movements are applied atomically (`F()` expression) on insert. When a movement
  has a `variant`, both `Product.stock_qty` and `ProductVariant.stock_qty` move
  by the same signed quantity. Movement types are Stock In, Stock Out and Adjustment (a signed quantity).
- Low stock = `track_stock and stock_qty ≤ reorder_level` (shown on the Workspace dashboard).

## Workspace dashboard

The staff landing page is `/staff/workspace/`. It is not a separate accounting
source; it is a live operating surface over the same domain records. Tiles are
created server-side only when the user has the matching permission, and the
queries use the same dlux scope filtering plus project row ownership as the list
views. A sales rep therefore sees their own sales/payment/customer tiles, a
courier sees only assigned delivery work, and a manager/superuser sees the whole
store.

The optional enhancements add to it only while they are on and the user can use
them: the **till** puts *Open the till* first in Quick Actions and a *Point of
Sale* tile with today's till sales (total and count of `PosSale` invoices the
user may see); **automotive** adds *Browse by vehicle* to Quick Actions and a
tile with the number of vehicle models the browser offers (active, of an active
make, not moved to machinery) and of active products fitted to at least one. Independent **machinery** adds its own browsing action and a machine-model tile
with type → manufacturer → model → nested categories, without changing vehicle wording.

Users may hide, reorder, and resize tiles. Those layout preferences are stored
per user in DjangoLux's reserved app-preferences namespace:
`Profile.preferences["app"]["sales_crm.workspace_dashboard.v1"]`. Browser
`localStorage` is used only as a fallback. Layout preferences do not grant access to hidden data, change business
records, or affect another user's layout. The `/staff/sales/dashboard/`
page is available as **Sales Overview** for a sales-centric screen.

## Opening stock (one-time bulk intake / رصيد افتتاحي)

For **first adoption**: load everything already on the shelf in one pass, rather
than adding each product and then reconstructing history invoice-by-invoice. An
**opening balance** is *what is physically in storage* — already net of
earlier sales — so there's nothing to reconcile. Past sales are
not re-entered; real invoices draw down stock from launch on.

Opening stock is a one-time bulk intake attached to the stock ledger. Its
work-in-progress is stored in `OpeningStockDraft`, one shared
draft per store scope (one global draft when scopes are off). Authorized intake
staff can save unfinished rows and resume them later; no product, pricing or
stock mutation occurs while saving a draft. A **trigger button on the Stock
Movements page** (gated by `add_product` + `change_product` + `add_stockmovement`) opens a full-page
grid (`/staff/catalog/stock-movements/opening-stock/`) where an admin enters many items
at once, one per row:

1. Each row is either a **created** item (type a name) or an **existing** one (pick
   it from the datalist — product details and pricing autofill). Fields: name,
   local alias, product currency (shown when both currencies are active),
   category, unit, barcode, optional color and size/spec, import cost and
   markup %, selling price (both in the row's product currency; column headers read USD or EUR
   following the store's pricing currency), optional manual LYD price, compatible machines (when Machinery is on), and **quantity in
   storage**. No supplier or date is captured (irrelevant for an
   opening balance). LYD previews use each row's selected product currency.
   Pricing cells use the same row-scoped live sync as the Product form: markup,
   foreign selling price, cost, and manual LYD override stay consistent inside that
   row without changing any neighbouring row. Selecting an existing product
   overwrites untouched row defaults (`0.00`, default unit) with that product's
   current values, but preserves fields the user already edited by hand.
2. **Import Excel** accepts an `.xlsx` workbook (up to 2 MB, at most 1000 data rows) with `Name` and `Quantity in
   Storage` required, plus the same optional alias, currency, category, unit, barcode, color, size
   and price columns as the grid. **Download template**
   (`catalog:opening_stock_import_template`, same permissions as the intake)
   returns a workbook built by `catalog.opening_stock_template.build_template()`:
   an `Opening Stock` sheet with the accepted headers (required ones highlighted,
   a note on each), Unit/Color/Category/Currency drop-downs fed by a hidden
   `Lists` sheet, non-negative number checks, a text-formatted Barcode column,
   and an `Instructions` sheet in the user's language. Currency appears only when
   both currencies are active. The modal shows the same per-column guide
   (`column_guide()`). The importer reads the `Opening Stock` sheet when present,
   otherwise the active sheet; a row without a name is a blocking conflict, and
   blank formatted rows do not count toward the 1000-row limit. A category cell
   accepts a full path such as `Hydraulic / Pump / Piston`; an ambiguous bare name is a
   conflict. Selecting a file
   sends no request: press **Check workbook** to preview creates versus updates,
   changed fields and conflicts. **Add rows to editor** appends the verified
   rows to the editable grid without creating products or stock. Add another
   workbook or more manual rows as needed. Import previews are not saved drafts;
   press **Save draft** to persist the combined work.
3. **Save draft** returns to Stock Movements, where **Resume opening stock
   draft** reopens the saved rows. Incomplete rows may be saved. A revision check
   returns HTTP 409 on a stale save/finalization and preserves the submitted
   entries on screen. Reconcile them against the saved draft in another
   tab; the server never overwrites it silently.
4. **Finalize opening stock** validates the whole grid and runs one locked
   transaction: each row create-or-reuses its `Product`, corrects its pricing
   when the admin edited those cells, and posts one **Stock In** `StockMovement`
   for the stored quantity (`reason="Opening balance"`, `reference="OPENING"`).
   The row's color/size creates or reuses a matching `ProductVariant`, and the
   movement points at that variant. Stock flows only through the ledger. A
   zero-quantity row reprices its product without posting a movement; blank rows
   are dropped. Drafts are capped at 1,000 rows / 2 MB;
   `DATA_UPLOAD_MAX_NUMBER_FIELDS=25000` accommodates the full form grid.
5. It can only be finalized once, including intakes containing only zero-quantity
   rows. A finalized draft or existing `reference="OPENING"` movements locks the
   editor. Duplicate item/color/size rows and inconsistent details/prices for one
   item across rows must be resolved before finalizing. The `/import/finalize/`
   endpoint returns HTTP 410 and cannot post inventory; imports reach stock only through the editor. The
   Stock Movements page switches the action to a read-only Opening Stock record
   at `/staff/catalog/stock-movements/opening-stock/view/`; the posted movements remain
   the authoritative audit trail.

### Starting opening stock over with Permanent Data Reset

For an initial setup without subsequent sales/purchases, take a backup, then use
DjangoLux Data Reset in **Permanent** mode and select **Stock Movements** plus
**Opening Stock Drafts**. This clears the ledger and saved finalization state,
recalculates product/variant stock to zero when no movements remain, and reopens
opening-stock entry. Both selections are needed. The reset applies across all
scopes and clears all selected stock movements, not just opening balances.

Products, their current prices/details, and zero-stock variants remain. If the
catalog should also be emptied, run a second Permanent reset selecting **Products**
after clearing the movements and drafts; variants cascade with their products.
Other documents referencing products can block that deletion, so this procedure is
for a clean initial setup. No product/pricing snapshot is
restored. A soft reset of drafts is unsupported: trashed drafts keep
the unique scope key and prevent creation of a replacement draft. Use Permanent
mode for this procedure.

## Purchase invoices / inbound stock invoices

For stock bought **after** launch, use **Catalog → Purchase Invoices** (or the
**Add Stock** button on Stock Movements). A purchase invoice is the robust
inbound-stock document that Opening Stock was never meant to be. Creating one needs
`add_purchaseinvoice`, `add_product`, `change_product` and `add_stockmovement`.

1. Header fields capture the supplier and invoice metadata. The supplier name is
   a search-and-add combobox like customer entry on sales invoices: choosing an
   existing supplier autofills phone/address, while a typed name creates a
   `Supplier` record and snapshots supplier name/phone/address onto the invoice.
2. The line grid reuses the Opening Stock product behavior. Each row is a created or
   existing `Product`; selecting an existing item autofills category, unit,
   barcode, import cost, markup, foreign selling price, and manual LYD price. If the
   product has exactly one variant, its color/size may autofill; if it has
   several, color/size stay explicit so the buyer can choose the correct bucket.
   Edits to cost/markup/foreign price/manual LYD use the same row-scoped price-sync rules
   as the Product form; LYD previews use the invoice currency.
3. Submitting the invoice runs one transaction: it saves a `PurchaseInvoice` +
   `PurchaseInvoiceLine` snapshots, creates or updates the products, and posts
   one Stock In `StockMovement` per line with `reference=<purchase invoice no.>`
   and `purchase_invoice` linked. The line's color/size creates or reuses the
   matching `ProductVariant`; the purchase line and movement both point to it and
   snapshot the visible color/size alongside cost/pricing. This keeps
   `Product.stock_qty` ledger-driven while giving staff an invoice-like document
   to view/print.
4. Purchase invoices may carry the scan/photo/PDF attachment of the supplier's
   paper invoice (`PurchaseInvoice.attachment`, upload path
   `purchase_invoices/`). This is record-only and never affects totals or stock.

The product create/reuse operation in step 3 is the same intake helper used by
Opening Stock. Typing a missing item name on a purchase invoice therefore creates
the Product and its selected color/size variant before the purchase line
and Stock In movement are posted.

## Product item card

Product View and row double-click open an operational item card instead of the
generic field dump. It shows identity/image, on-hand quantity, cost and selling
prices, reorder level, every color/size balance, and the 30 most recent stock-ledger
movements. Editing uses the standard scoped modal.

## Optional enhancements: automotive fitment

Store-specific behavior extends the generic product catalog rather than adding
industry fields to it. Two enhancements exist, each with its own switch in the
**Optional enhancements** System Settings card, which only a superuser can save:
Automotive Compatibility (this section) and Machinery (see *Client machinery categories*).

- The master switch defaults off. Missing configuration is treated as off.
- Make, model, year, engine and transmission are always available once the enhancement is on.
  Machine type, chassis/generation, fuel type, trim and part position are separately configurable criteria.
- Fuel type is an optional attribute of engines; the engine criterion itself is always on.
- Disabling the whole enhancement hides it without deleting fitment data.
  Disabling one criterion is rejected while any fitment uses that constraint;
  otherwise a hidden chassis, trim or position value could create unsafe false-positive matches.
- `EquipmentType`, `VehicleMake`, `VehicleModel`, `VehicleGeneration`, `VehicleEngine`,
  `VehicleTrim` and `ProductFitment` are scoped extension records. A fitment links
  one Product to one model (or to a shared engine alone) with an optional inclusive year range plus optional criteria.
- Product, ProductVariant, stock balances, purchase lines and sales lines receive
  no automotive columns. One compatible SKU always keeps one stock balance and
  one purchase/sales history regardless of how many vehicles it fits.
- The vehicle-data hub (`/staff/automotive/`) manages makes, models and only the qualifier dimensions
  enabled by the store. Reference values are deactivated rather than deleted.
- The settings modal stages changes until Save. **Manage vehicle data** is
  disabled when Automotive Compatibility is not yet persistently enabled, so
  checking an unsaved switch cannot lead to a feature-gated 404.
- The automotive hub and **Browse by Vehicle** (like the machinery hub and browser) are the only routes of these
  enhancements exposed to the sidebar builder, and only while the persisted enhancement switch is on. Turning
  the enhancement off removes them from discovery and rendering even if they were
  saved in the sidebar; the individual make/model/generation/engine/trim
  routes are internal hub destinations. To open the browser after login, set
  DjangoLux's Home (store-wide, or per user when allowed) to
  `/staff/automotive/browse/`; enabling automotive does not change where anyone
  lands.
- The Product Item card shows its compatible vehicles using enabled criteria
  only. Managers edit several ranges in one save; exact duplicates are rejected
  and matching overlapping ranges require explicit confirmation.
- Product keyword search includes enabled make/model/chassis/engine/fuel/trim
  text while automotive is on. It returns each Product once and does not alter
  stock, purchasing or sales history.
- The guided Vehicle Browser follows Make → Model → Year and then shows only
  enabled qualifiers that can meaningfully narrow the current result. Blank
  generation/engine/trim/transmission/position values mean broad/all and remain
  compatible when a specific qualifier is selected. Counts and results are by
  distinct Product/SKU, never by fitment-row count or stock units.
- Browser results (up to 100 products) include active Products for active makes/models, mark low and
  out-of-stock items, and open the existing Product Item card. Out-of-stock items
  are shown.
- Direct browser search accepts Product name, alias, SKU, barcode, OEM/cross-reference
  number or part brand without requiring a vehicle path.
- **Quick Fits entry.** The Product add/edit modal carries a *Fits vehicles*
  search-and-tag picker right after name/category. Typing `camry 2014`, a chassis
  code (`xv50`) or an engine (`hilux 2.8`) suggests model-year, generation and
  engine matches; a typed year or `2010-2012` range becomes the row's years, a
  generation brings its own span. A model tagged without a year fits all years.
  Tags for existing rows are kept untouched (their engine/position/notes are
  edited in the full editor, linked as *Advanced*); removing a tag retires that
  row, added tags create rows. Exact duplicates collapse; overlap confirmation is
  a rule of the full editor only.
- **Same cars as…** copies another product's compatibility as tags,
  including its engine/trim/transmission/position values.
- **Assign vehicles** (Products ribbon) adds the same tags to several products in
  one save. It is additive: existing compatibility is never removed.
- **Purchase invoice lines** carry a collapsed *Fits vehicles* picker; on posting,
  its tags are added to the created or reused Product (additive, same transaction
  as the stock-in).
- **Vehicle-first add.** The browser's *Find a vehicle* search reaches any active
  make/model/year, including one no product fits yet, and its results offer *Add
  part for this vehicle*, opening the Product modal with that vehicle tagged.
  The name is suggested as `<category> – <vehicle>` when left blank.
- **Part identity** lives beside the Product: `PartProfile` holds the part brand,
  `ProductPartNumber` holds OEM and cross-reference numbers. Numbers are
  comma-separated in the form and matched by an uppercase alphanumeric form, so
  `04465-33450` and `0446533450` are the same number. Product keyword search
  matches them (3+ significant characters).
- The Products list adds **Vehicle** and **Vehicle year** filters while automotive
  is on; both must match the *same* fitment row.
- **Machine type** (excavator, loader, generator…) is an optional criterion on
  each vehicle model. With it on, the browser shows types as chips over the make grid; choosing a
  type narrows the makes and models to that type, and untyped models stay reachable while no type is chosen.
- **Shared engines.** An engine with no model is shared: it has a manufacturer
  (Perkins, Cat, Cummins…) and a list of fitted models. A part tagged to a
  shared engine alone fits every machine that engine is fitted to — it appears
  in the browser, the Vehicle filter and search for each of them. A part tagged
  to a model *and* a shared engine is valid only when that engine is fitted to
  the model.
- **Years are optional.** A fitment with no years fits all years. The
  year step is skipped for a model whose fitments have no years.

## Permission editor and optional features

While Vehicles (automotive), Machinery, the Point of Sale or the public site is switched off, its
permissions leave DjangoLux's group and user permission editors
(`common.permission_visibility.hidden_feature_permissions`, registered in
`CommonConfig.ready()` through `dlux.access.register_permission_visibility_filter`).
POS covers `use_pos`, `pos_unlimited_discount` and the `PosSale` model permissions.
Hiding is display-only: saving a group or user keeps the hidden grants, so switching
the feature back on shows them exactly as they were.

## Point of sale (نقطة البيع)

An optional till for quick walk-in sales, switched on in the *Point of sale*
section of the **CRM options** settings tile (off by default). Using the till needs
`sales.use_pos`, `sales.add_invoice`, `sales.issue_invoice` and `sales.add_payment`.

- A till sale is an ordinary walk-in invoice: created, issued (stock out, with
  the usual shortage check) and paid in one transaction. Reports, the stock
  ledger and cash deposits treat it like any other sale. A shortage or any
  refusal rolls the whole sale back.
- Every sale carries a till-generated key (`PosSale.key`); resubmitting the same
  key returns the same invoice, so a double tap or a dropped connection cannot
  sell twice.
- Payment: cash, card (the store's own card machine) and bank transfer, as
  enabled in settings (cash stays on when none is selected), and split across them. Non-cash amounts may not exceed
  what is left to pay; cash covers the rest and the change is recorded on the
  `PosSale` (with the cash given) and printed on the receipt.
  The payment dialog opens with the total in the chosen method. Amounts the
  cashier types stay as typed; what is left to pay flows into the chosen method
  or else cash, never into another card or transfer field. Quick-amount buttons
  fill the field last focused (cash: the amount due and round-ups; card or
  transfer: the amount due).
- Discounts: a lowered line price and a sale discount both count. Their total,
  against the list price, may not exceed the seller limit (settings, default
  10%) unless the user holds `sales.pos_unlimited_discount`.
- Scanning: the always-focused box resolves an extra barcode (per product or
  per variant), the product barcode, the SKU or a normalized part number as an
  exact hit and adds it; anything else searches names, aliases, SKUs, barcodes and part numbers. Keys a
  hardware scanner types while focus is elsewhere are routed to the box. An
  unknown code offers **Add a new item with this barcode**; after saving, the
  till adds it to the still-open cart.
- Before any search the till shows the **Most sold** grid: the 12 best sellers of the
  last 90 days, topped up with the most recently created items, leaving out tracked items
  with no stock (search still finds them). Search hits open in a dropdown
  over it; clicking elsewhere folds the dropdown and focusing the box reopens
  it. Picking a vehicle fills the grid with what fits it until **Back to most
  sold**.
- Camera scanning uses the browser's built-in barcode reader where available
  and otherwise the bundled ZXing reader (`sales/static/sales/pos/vendor/`,
  Apache-2.0, loaded on first use, e.g. iPhone Safari). Either needs a secure
  page (localhost or HTTPS).
- Receipts: none, thermal 58 mm / 80 mm (default), or A4 (settings), printed from the
  browser.
- Where users land after login is DjangoLux's Home setting (store-wide, or per
  user when allowed); set it to `/staff/sales/pos/` for a counter that opens on
  the till. Enabling the till does not change where anyone lands.
- **Extra barcodes** (`catalog.ProductBarcode`) are edited in the product form
  whether or not the till is on; a code already used by another item is refused.

## Sales invoice variant selection

When adding a product line on a sales invoice, the editor reads the selected
product's in-stock `ProductVariant` rows. Available colors are shown as swatches
and sizes/specs are shown in the size selector with quantities. Saving the draft
stores `InvoiceItem.variant` plus `InvoiceItem.color` and `InvoiceItem.size`
snapshots. Issuing the invoice draws down that exact variant bucket; blue stock
cannot cover an orange shortage for the same product. Services and custom lines
keep variant/color/size blank.

## Stock take (physical inventory count / جرد)

The **annual (or periodic) inventory count**. You count what's physically on the
shelves and reconcile it against what the system thinks you have:

1. Start a count (`StockTake`) — it snapshots the current system quantity for
   every active stock-tracked product and gives you a sheet to enter the counted
   quantity (blank = not counted). A product with colour/size buckets has one row
   per bucket, plus a row *Outside colour/size* when its total holds stock outside
   them; a product without buckets has one row. Opens in `open` status.
2. The count's page shows a **variance report**: system vs counted, the signed
   variance, and the LYD value of each discrepancy (variance × unit cost).
3. **Apply** it (needs `apply_stocktake`) — the system posts one **Adjustment**
   `StockMovement` per real discrepancy on a tracked product, so `stock_qty`
   becomes the counted figure, and the take locks as `applied` (can't re-apply).
   Each row's adjustment moves its own bucket and the product total together, so
   the buckets the invoices check follow the count.
   Adjustments flow through the same append-only ledger as every other stock
   change, so the correction is fully auditable.

Apply promptly after counting: the adjustment is `counted − system-snapshot`, so
a sale between the snapshot and applying would skew it.

## Inventory valuation

A read-only report of **what the stock on hand is worth at the live rates** — for each
active stock-tracked product, `stock_qty` × `cost_usd` in the product's currency, converted to LYD at
that currency's live rate and summed, with totals per currency. This is the closing-stock figure
the fiscal-year financial report uses. Gated by `view_inventory_valuation`.

The same page answers **what the stock would bring in if it all sold**: each
item's sale value is `stock_qty` × `Product.selling_price_lyd` (the manual LYD
override when set, else the foreign price at the live rate), and its expected
profit is sale value − cost value in LYD. The totals add a margin, profit as a
percentage of sale value. These are today's shelf prices, not a forecast:
invoice discounts and rate changes are not applied.

## Fiscal year & the financial report

A **fiscal year** here is the calendar year (Jan 1 – Dec 31), which is the norm
in Libya. The **financial report** (`/staff/sales/financial/`, gated by
`sales.view_financial_report`) is a whole-store owner P&L for a chosen year — it is
never per-rep. The year picker runs from the year of the first invoice to the current year. It reports:

- **Period figures** (for the selected year): **revenue** (issued/partial/paid
  invoices), **cost of goods**, **gross profit** + margin, **posted operating
  expenses**, **net profit**, and **cash collected** (payments received in the year),
  with the refunds and net collected figures described under Invoice lifecycle.
- **Current snapshots** (point-in-time, labelled *current*): **outstanding
  receivables**, **inventory value**, available customer credit and unresolved
  cancellation payments.

**COGS is exact**: each invoice line freezes the product's unit cost at the time
of sale (`InvoiceItem.unit_cost_lyd`, with the foreign `unit_cost_usd` beside it), just like it freezes the selling price and
rate — so a cost change after the sale never rewrites a past invoice's profit. COGS =
Σ(quantity × frozen LYD unit cost). A line without a frozen LYD cost uses its frozen
foreign cost × the invoice's frozen rate, and the product's current cost when it has neither.

**Sales report** (`/staff/sales/report/`, gated by `sales.view_sales_report`) covers
issued, partial and paid invoices by invoice date for a chosen window (default: month to date).
It is row-scoped like the invoice list: a rep reports on their own sales, a manager on the
whole store. The Excel export (`/staff/sales/report/export/`) writes record text as text, so
a value starting with `=` is never evaluated as a formula.

## Purchase invoice attachment

Customer-facing sales invoices do **not** carry scan/PDF attachments. The
supporting scan/photo/PDF belongs to the inbound **Purchase Invoice** because it
represents the supplier document used to add stock. It is captured with the rich
file field (drag-drop, phone camera, or desktop scanner) and shown as a link on
the purchase invoice page.

The attachment, like an expense receipt, opens only for a signed-in user who may
view that record (`catalog.view_purchaseinvoice`; for receipts `finance.view_expense`
plus ownership unless `view_all_expense`). The app serves it at
`/staff/files/...`; the proxy refuses its `/media/` path.

## Cash deposits (ايداع نقدي)

Technicians and delivery reps **record** the cash they collected (`pending`); an
admin **confirms** or **rejects** it. Invoice payments may reference the deposit
that carried their cash so the books reconcile: typing an unused deposit reference on a
payment creates a pending deposit, and a deposit with linked payments takes its amount from their sum.
A staffer sees only the deposits they recorded; a manager (`view_all_cashdeposit`) sees all.

## Expenses

Generic operating costs live in `finance.Expense`, grouped optionally by
`ExpenseCategory`. Only posted expenses are subtracted in the
financial report; an expense saved from the form is posted, a draft is record-in-progress, and void expenses stay
auditable but inert. Each expense stores amount in LYD, date, payment method,
optional payer, reference, notes, and an optional receipt/photo/PDF attachment
using the same dlux archive/scanner widget used elsewhere. Expenses are owned by
`paid_by` or `created_by`; managers hold `view_all_expense` and `post_expense`.

## Staff accounts and credit

Each relevant user may have one `finance.StaffAccount` for advances, loans, cash
or item check-outs, reimbursements, service/commission earnings, and payments to
or from the user. The account balance is derived from posted
`StaffLedgerEntry` rows only:

- Positive balance means the company owes the user.
- Negative balance means the user owes the company.
- Pending rows do not affect balance until confirmed.
- Disputed and void rows remain visible for audit but do not affect balance.

Managers create ledger entries. By default entries require user confirmation:
dlux creates a persistent notification for the staff user and the row appears on
their staff-account page with Confirm/Dispute actions. A manager with
`resolve_staffledgerentry` can confirm, dispute or void entries. This keeps staff credit
visible and confirmable without turning services, deliveries, loans, and cash
hand-offs into separate complex subsystems.

## Who sees what (per-employee visibility)

The system is multi-user: each record is owned, and staff see only their own work
unless they hold the matching `view_all_<model>` permission. Full rules in
[PERMISSIONS.md](PERMISSIONS.md). In business terms:

- A **sales rep** sees only **their own** invoices, customers and payments. Their
  customer book is private (two reps can each keep a "Mr. Ali" without collision).
  Their Workspace/Sales Overview figures and reports cover **only their own sales**.
- An invoice belongs to its **salesperson** (defaults to whoever created it). Only
  a user holding `assign_salesperson` (a **manager**) can reassign it to another rep.
- A **manager** sees and reports on the **whole store**, and assigns work.
- The **owner** is a superuser and sees everything.

## Deliveries

A **delivery** is a courier job — optionally linked to an invoice, with a
recipient/address snapshot so it stays intact if the invoice changes. Lifecycle:
`pending → assigned → out → delivered` (or `failed` / `cancelled`). It
auto-advances to *assigned* the moment a courier is set, and stamps the delivery
time on *delivered*. A **courier sees only the jobs assigned to them** and never
the sales side of the business; a **dispatcher/manager** (`view_all_delivery` +
`assign_delivery`) sees the whole board and assigns couriers.

### Concurrent invoice issuance

Issuing locks the invoice, then affected products in primary-key order and their variants in primary-key order. It checks fresh locked balances against all demand for each product and each variant before writing any stock-out movement. Two invoices competing for the last unit result in one successful issue and one insufficient-stock rejection. Combined variant and unassigned lines also share the product stock limit.

## Client machinery categories

Machinery has an independent enhancement toggle (Optional enhancements → Machinery compatibility); the vehicle screens keep vehicle wording. Machine records are `machinery.MachineType`, `Manufacturer` and `MachineModel`. Adding a machine requires only machine type; manufacturer and model name are optional, and machines without them remain browsable and assignable. The browser follows machine type → manufacturer → model → nested categories. Parts and services can fit several machine models while retaining one item and stock/pricing history; **Assign machines** (Products ribbon) adds machines to several products additively. Categories form a tree (`Category.parent`); a category marked `is_service` holds services only, is refused for products, and cannot be set on a category that already contains stock items. Model category branches provide the client drill-down; parent category filters include descendants. Repair is a service-only category containing a quoted-per-job maintenance service, with no stock quantity. Full-path workbook categories disambiguate repeated leaf names.

`python manage.py seed_machine_categories` (optional `--scope ID`) is idempotent. It adds the Concrete pump & mixer type, the CIFA manufacturer with models F8, F9, HPG and ZOOM, and category branches for F8 only (Hydraulic, Control, S-valve, Hopper, Seal kit; under Hydraulic: Pump, Motor, Valve, Accumulator, Instruments, Repair; under Pump: Gear, Piston, Vane, Charge, Tandem, Spare part). It creates no products, prices, stock or compatibility. See [CLIENT_CATEGORIZATION.md](CLIENT_CATEGORIZATION.md).
