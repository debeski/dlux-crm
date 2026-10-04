# Switch POS — Business Rules

## Currency

- Products keep their own **USD** or **EUR** pricing currency (`Product.currency`).
  Historical `cost_usd` / `price_usd` column names store amounts in that currency.
  Local selling prices use the corresponding live rate, or a manual LYD override.
- CRM options → Currency (`switch_pos.pricing`) offers **USD / EUR / BOTH** in one selector. USD/EUR set the default for new products and invoices. BOTH retains the previous default and
  allows
  buyers to choose either currency per purchase invoice. Existing purchase
  permissions apply; there is no additional currency-selection permission.
- In single-currency mode, currency controls are hidden in product/intake forms and the purchase header; purchases use the default currency. Posting an
  alternative currency is rejected. Existing products retain their recorded
  currency and can still be purchased with conversion.
- Purchase-line cost and selling-price inputs are in the **invoice currency**.
  The line's Product currency selects how these amounts are stored in the
  catalog; existing products default to their own currency, new products to
  the invoice currency. Cross-currency intake requires available rates for
  both currencies and converts via LYD, rounded to two decimals. The invoice
  retains its original foreign amounts and frozen rate.
- Changing the default does **not** reprice products. Service prices and draft
  sales documents still convert with confirmation and rates for both currencies;
  issued documents remain unchanged. Services use the default currency. For example, a EUR product costing €20 and selling at €30 retains these amounts after selecting USD-only; its LYD value continues using the EUR working rate. No parallel USD price is stored. Local alias spans the product-form row when its currency selector is hidden.
- Rate resolution uses the latest manual rate, then the cached scraped market rate, then cached CBL official rate. Celery refreshes external rates; missing manual entries do not block conversions when a scraped rate is available.
- USD and EUR exchange rates have independent append-only histories. The
  Workspace shows each working rate with its source plus scraped reference rates. The exchange-rate list includes a current USD/EUR summary (working/manual/market/CBL and collection timestamps) above manual rate history; collected rates do not create manual overrides. Sales Overview also shows rate references.
- Opening-stock rows/workbooks support Currency and Local Alias. Older sheets
  without these columns retain an existing product's currency or use the default
  for a new item. Costs and prices in each row are in its product currency.

## Pricing model — hybrid (per-product foreign currency + optional LYD override)

Decided with the owner. For each `Product`:

1. Cost is stored in the product's currency (`cost_usd`). A `markup_percent` (or an explicit
   `price_usd`) yields the **selling price** in the product's currency (`effective_price_usd`).
   `Product.save()` **persists** this derived `price_usd` when only cost + markup
   were entered, so the stored record (and its detail view) never shows 0.
2. The **LYD selling price** is derived live: `effective_price_usd × current_rate`.
   Changing a currency's rate updates products priced in that currency.
3. Any item may set a manual **`price_lyd_override`** — a fixed LYD price that
   bypasses conversion (for odd / unrelated goods Switch occasionally resells).
   Left blank, the item sells at the live rate (the default).

The create/edit form keeps these fields in step as you type (`catalog/js/price_sync.js`):
editing markup recomputes the foreign price, editing the foreign price recomputes the markup,
editing cost recomputes the foreign price (markup held) while the manual LYD override is
blank, and the live LYD price is shown as the manual-LYD field's **placeholder**.
Typing a value into that field turns it into a real fixed override (and back-fills
the foreign price + markup to match); while that override is present, changing the cost keeps the
LYD price fixed and recalculates the implied foreign price + markup from the new cost.
The detail view adds a computed **"Selling Price (LYD)"** row (via
`get_modal_context`) so it matches the list.

`Service` items follow the same override logic and may also be **"per job"**
(no fixed price — entered on the invoice).

## Local aliases

Products/parts and vehicle/machine models have an optional `alias` field for
local Libyan names, alongside the official name. Aliases are editable in the
existing product/model forms and purchase/opening-stock intake for products.
Product lists, sales picker, till, direct parts search, vehicle suggestions and
model lists search aliases. Intake suggestions retain the original product ID
and official name; an ambiguous alias is not automatically matched. Aliases are
separate from barcodes and OEM/cross-reference numbers.

## Frozen rate per invoice

When an invoice is created it records the pricing currency in `Invoice.currency`
and captures that currency's current rate into `Invoice.exchange_rate`, and every
line stores its own frozen `unit_price_lyd`. Product costs are frozen in
`unit_cost_lyd` at six decimal places using the product currency's rate; financial
reports use this snapshot so mixed-currency COGS survives subsequent rate and
product edits. Legacy lines retain their existing foreign-cost/rate fallback. Purchase invoices do the same
(`PurchaseInvoice.currency`); invoice pages and printouts show the document's own
currency, not the store's current one. **Later rate changes never
rewrite a past invoice's totals.** This is correct accounting and matches the owner's
expectation that an issued invoice is final.

## Invoice lifecycle

```
draft ──issue──▶ issued ──payment──▶ partial ──payment──▶ paid
  │                  │
  └───── (edit) ─────┘ (only drafts are editable)
issued/partial/paid ──cancel──▶ cancelled  (stock restored)
```

- **Draft**: editable; no stock impact.
- **Issue** (`issue_invoice`): snapshots the rate record and **draws down stock**
  (a `StockMovement` OUT per product line). Requires at least one item. **Blocked**
  if any tracked product or selected color/size variant would go negative —
  demand is summed per product for legacy/no-variant lines and per `ProductVariant`
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
  still owed to the customer and a **Resolve payments** action, including for
  invoices cancelled before this feature. The migration creates no historical
  refunds or credits automatically; staff must record the actual disposition.
- **Customer credit**: available LYD credit appears in the customer list and on
  eligible issued/partially paid invoices. **Apply customer credit** chooses an
  original receipt and an amount up to both its available credit and the target
  invoice balance. It creates a non-cash `CustomerCreditUse`, advances payment
  status, and contributes to `amount_paid`; it creates no new cash receipt or
  deposit. Request UUIDs prevent duplicate application, and customer/invoice
  locks serialize credit use against cancellation and other credit requests.
- **Cancelling credit-paid invoices**: previous credit allocations remain as
  history but no longer consume their source credit; they become available to
  the same customer again. Only actual cash/card/bank/cheque receipts on the
  cancelled invoice enter its new refund/credit settlement. Repeated cancellation
  neither restores stock nor resolves a receipt twice.
- **Financial reporting**: original receipts stay in gross collected cash;
  refunds are separate outflows dated by `resolved_at`, and net collected is
  gross receipts minus refunds. Available customer credit and unresolved
  cancellation payments are current customer liabilities, separate from
  revenue/expenses. Sales-report Paid includes cash and applied customer credit.
  Cancellation never rewrites a previously linked cash deposit.
- **History protection**: `PaymentResolution` and `CustomerCreditUse` are
  append-only records. Cancelled invoice receipts cannot be edited/deleted or
  receive new payments through the payment service. Refund recording does not
  initiate a bank/card transfer; return the money first, then record it.
- **Draft line removal**: retain each formset index and submit its `DELETE`
  checkbox, including newly added lines. Deleted line inputs are disabled
  except for `id`/`DELETE`; validation redisplay keeps deleted lines hidden.
- In the invoice and payment lists, row actions live in the standard **DjangoLux
  context menu** (right-click, long-press, or double-click primary action). The
  invoice number / receipt number columns are display values, not hidden action
  triggers. Print actions from those menus open in a new browser tab so the
  current workflow is not replaced.

## Payment receipts (إيصال قبض)

Every recorded `Payment` has its own durable receipt number
(`Payment.receipt_number`, generated as `RCT-000001` style and backfilled for
existing payments by migration `sales/0005`). Staff can print the receipt from
the row context menu in the invoice's payments table or the standalone payments
list at `/staff/sales/payments/<id>/receipt/`; receipt print actions open in a new tab.

The receipt uses the same official logo from DjangoLux System Settings as the
printed invoice. It shows the customer/invoice, amount collected, method,
payment time, receiving user, optional cash-deposit reference, amount paid before
this receipt, and the invoice balance **after this specific receipt**. It is
gated by `sales.view_payment` and the same `Payment` row ownership rules as the
payments list, so a rep cannot open another rep's receipt by guessing the URL.

## Catalog images

Products and Services carry an optional photo (`image`). It's shown as a thumbnail
in the catalog lists and enlarged in the item's detail card. On a phone the upload
field offers the camera or the gallery. Purely descriptive — it never affects
pricing, stock or invoices.

## Public catalog

The public catalog is a curated read-only projection of internal catalog records.
`public_catalog.PublicCatalogListing` links exactly one active Product or one active
Service to a public slug, title, summary/body, optional public image override,
installation notes, warranty notes, and publish flags.

Public pages (`/`, `/shop/`, `/shop/items/<slug>/`, and the item modal endpoint)
may show public title/copy, customer-facing image, LYD selling price, broad
availability labels (`Available`, `Limited availability`, `Available to order`,
`By appointment`, `Currently unavailable`), and color/size option labels. They
render through the public storefront templates and dynamic quick-view modal. They
must not show SKU, barcode, import cost, markup, exact product/variant stock
counts, staff modal URLs, or internal staff chrome.

The public contact modal (`/contact/modal/`) is allowed to write
`PublicContactMessage` rows. Each browser attempt carries a stable idempotency
key, enforced by a database unique constraint, so retries create one message and
send at most one email. The saved message remains the source of truth even if the
SMTP side effect fails; staff can inspect `email_status` and `email_error` in
admin. Future reservation, purchase, checkout, and payment capture paths must
follow the same rule: database-backed idempotency first, Celery/Redis only for
retryable side effects, races, or throttling support.

## Product variant attributes

Products can have stock-bearing `ProductVariant` buckets identified by `color`
and `size`. `color` is limited to the 15-color palette exposed in stock-intake
rows (black, gray, white, red, blue, green, yellow, orange, purple, pink, brown,
beige, navy, gold, teal). `size` is a free-form **Size / Spec** field for actual
size, capacity, measurements, model-specific descriptors, or whatever the product
requires.

`Product.stock_qty` remains the aggregate total. `ProductVariant.stock_qty`
tracks the available quantity for a specific color/size bucket, so the same
product can hold orange and blue stock at the same time without either
overwriting the other. Pricing, cost, valuation, permissions, and low-stock rules
remain product-level unless a future rule explicitly changes them. Staff create
or top up variants while posting Opening Stock, Purchase Invoices, or variant
aware manual Stock Movements; Product create/edit stays focused on identity and
pricing. Product list/detail views show available variant swatches with
quantities. Purchase invoice lines and sales invoice item lines snapshot the
variant values used at intake/sale time, so later catalog changes do not rewrite
old documents.

## Inventory

- `Product.stock_qty` is **only** changed through `StockMovement` (the ledger is
  authoritative); it is not editable on the product form. Use Opening Stock once
  for first adoption, Purchase Invoices for normal inbound stock, and manual
  Stock Movements only for one-off corrections/adjustments.
- Movements are applied atomically (`F()` expression) on insert. When a movement
  has a `variant`, both `Product.stock_qty` and `ProductVariant.stock_qty` move
  by the same signed quantity.
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
tile with the number of vehicle models and of active products fitted
to at least one. Independent **machinery** adds its own browsing action/model tile
with type → manufacturer → model → nested categories, without changing vehicle wording.

Users may hide, reorder, and resize tiles. Those layout preferences are stored
per user in DjangoLux's reserved app-preferences namespace:
`Profile.preferences["app"]["switch_pos.workspace_dashboard.v1"]`. Browser
`localStorage` is kept only as a fallback and one-time migration source for older
layouts. Layout preferences do not grant access to hidden data, change business
records, or affect another user's layout. The older `/staff/sales/dashboard/`
page remains available as **Sales Overview** for a sales-centric screen.

## Opening stock (one-time bulk intake / رصيد افتتاحي)

For **first adoption**: load everything already on the shelf in one pass, rather
than adding each product and then reconstructing history invoice-by-invoice. An
**opening balance** is *what is physically in storage now* — already net of
anything sold before go-live — so there's nothing to reconcile. Past sales are
simply not re-entered; real invoices start drawing down stock from launch on.

This is **not a document of its own** — it's a *child of the stock ledger*: a
one-time bulk way to post Stock In movements. A **trigger button on the Stock
Movements page** (gated by `add_product` + `add_stockmovement`) opens a full-page
grid (`/staff/catalog/stock-movements/opening-stock/`) where an admin enters many items
at once, one per row:

1. Each row is either a **new** item (type a name) or an **existing** one (pick
   it from the datalist — product details and pricing autofill). Fields: name,
   category, unit, barcode, optional color and size/spec, import cost and
   markup %, selling price (both in the pricing currency; headers read USD or EUR), optional manual LYD price, and **quantity in
   storage**. Purchase shop and date are intentionally omitted (irrelevant for an
   opening balance).
   Pricing cells use the same row-scoped live sync as the Product form: markup,
   foreign selling price, cost, and manual LYD override stay consistent inside that
   row without changing any neighbouring row. Selecting an existing product
   overwrites untouched row defaults (`0.00`, default unit) with that product's
   current values, but preserves fields the user already edited by hand.
2. **Import Excel** accepts an `.xlsx` workbook with `Name` and `Quantity in
   Storage` required, plus the same optional category, unit, barcode, variant
   and price columns as the grid. File selection only validates and stages the
   data: the modal shows creates versus existing-product updates, changed
   fields, duplicates, unknown categories and identity conflicts. No stock is
   written until the user reviews the diff and presses **Finalize import**.
3. **Submitting** manually or finalizing a verified workbook runs one
   transaction: each row create-or-reuses its `Product`, corrects its pricing
   when the admin edited those cells, and posts one **Stock In** `StockMovement`
   for the stored quantity (`reason="Opening balance"`, `reference="OPENING"`).
   The row's color/size creates or reuses a matching `ProductVariant`, and the
   movement points at that variant. Stock still flows only through the ledger. A
   zero-quantity row reprices its product without posting a movement; blank rows
   are dropped.
4. It can only be applied once. After `reference="OPENING"` movements exist, the
   Stock Movements page switches the action to a read-only Opening Stock record
   at `/staff/catalog/stock-movements/opening-stock/view/`; the posted movements remain
   the authoritative audit trail.

## Purchase invoices / inbound stock invoices

For stock bought **after** launch, use **Catalog → Purchase Invoices** (or the
**Add Stock** button on Stock Movements). A purchase invoice is the robust
inbound-stock document that Opening Stock was never meant to be:

1. Header fields capture the supplier and invoice metadata. The supplier name is
   a search-and-add combobox like customer entry on sales invoices: choosing an
   existing supplier autofills phone/address, while a new name creates a
   `Supplier` record and snapshots supplier name/phone/address onto the invoice.
2. The line grid reuses the Opening Stock product behavior. Each row is a new or
   existing `Product`; selecting an existing item autofills category, unit,
   barcode, import cost, markup, foreign selling price, and manual LYD price. If the
   product has exactly one variant, its color/size may autofill; if it has
   several, color/size stay explicit so the buyer can choose the correct bucket.
   Edits to cost/markup/USD/manual-LYD use the same row-scoped price-sync rules
   as the Product form.
3. Submitting the invoice runs one transaction: it saves a `PurchaseInvoice` +
   `PurchaseInvoiceLine` snapshots, creates or updates the products, and posts
   one Stock In `StockMovement` per line with `reference=<purchase invoice no.>`
   and `purchase_invoice` linked. The line's color/size creates or reuses the
   matching `ProductVariant`; the purchase line and movement both point to it and
   snapshot the visible color/size alongside cost/pricing. This keeps
   `Product.stock_qty` ledger-driven while giving staff an invoice-like document
   to view/print later.
4. Purchase invoices may carry the scan/photo/PDF attachment of the supplier's
   paper invoice (`PurchaseInvoice.attachment`, upload path
   `purchase_invoices/`). This is record-only and never affects totals or stock.

The product create/reuse operation in step 3 is the same intake helper used by
Opening Stock. Typing a new item name on a purchase invoice therefore creates
the missing Product and its selected color/size variant before the purchase line
and Stock In movement are posted.

## Product item card

Product View and row double-click open an operational item card instead of the
generic field dump. It shows identity/image, on-hand quantity, cost and selling
prices, reorder level, every color/size balance, and the 30 newest stock-ledger
movements. Editing still uses the standard scoped modal.

## Optional enhancements and automotive fitment

Store-specific behavior must extend the generic product catalog rather than add
industry fields to it. The first extension is Automotive Compatibility, configured
by a superuser from the **Optional enhancements** System Settings card.

- The master switch defaults off. Missing configuration is treated as off, so an
  upgraded store sees no new navigation, forms, or query behavior.
- Make/model/year is the automotive core. Chassis/generation, engine, fuel type,
  trim, transmission and position are separately configurable criteria.
- Fuel type depends on Engine. Configuration normalization always enables Engine
  when Fuel Type is enabled.
- Disabling the whole enhancement hides it without deleting fitment data.
  Disabling one criterion is rejected while any fitment uses that constraint;
  otherwise a hidden engine/chassis value could create unsafe false-positive matches.
- `VehicleMake`, `VehicleModel`, `VehicleGeneration`, `VehicleEngine`,
  `VehicleTrim` and `ProductFitment` are scoped extension records. A fitment links
  one Product to one model and inclusive year range plus optional criteria.
- Product, ProductVariant, stock balances, purchase lines and sales lines receive
  no automotive columns. One compatible SKU always retains one stock balance and
  one purchase/sales history regardless of how many vehicles it fits.
- The vehicle-data hub manages makes, models and only the qualifier dimensions
  enabled by the store. Reference values are deactivated rather than deleted.
- The settings modal stages changes until Save. **Manage vehicle data** is
  disabled when Automotive Compatibility is not yet persistently enabled, so
  checking an unsaved switch cannot lead to a feature-gated 404.
- The automotive hub and **Browse by Vehicle** are the only routes exposed to the
  sidebar builder, and only while the persisted enhancement switch is on. Turning
  the enhancement off removes them from discovery and rendering even if they were
  previously saved in the sidebar; the individual make/model/generation/engine/trim
  routes remain internal hub destinations. To open the browser after login, set
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
- Browser results include active Products for active makes/models, mark low and
  out-of-stock items, and open the existing Product Item card. Out-of-stock items
  are currently shown by default; the retailer pilot must confirm whether that
  should become a user-controlled or store-wide filter.
- Direct browser search accepts Product name, SKU, barcode, OEM/cross-reference
  number or part brand without requiring a vehicle path. The XLSX fitment intake
  remains a later plan phase.
- **Quick Fits entry.** The Product add/edit modal carries a *Fits vehicles*
  search-and-tag picker right after name/category. Typing `camry 2014`, a chassis
  code (`xv50`) or an engine (`hilux 2.8`) suggests model-year, generation and
  engine matches; a typed year or `2010-2012` range becomes the row's years, a
  generation brings its own span. A model with no generations needs a typed year.
  Tags for existing rows are kept untouched (their engine/position/notes are
  edited in the full editor, linked as *Advanced*); removing a tag retires that
  row, new tags create rows. Exact duplicates collapse; overlap confirmation stays
  a rule of the full editor only.
- **Same cars as…** copies another product's compatibility as new tags,
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
- **Heavy machinery and equipment.** A store can choose *Machines & equipment*
  wording (Optional enhancements → What the store serves). The switch writes
  machine wording (آلية/آليات, "Machine") as DLux translation overrides and
  withdraws only the overrides it wrote, so an admin's own wording survives.
- **Machine type** (excavator, loader, generator…) is an optional criterion on
  each model. The browser shows types as chips over the make grid; untyped
  models stay reachable without a type.
- **Shared engines.** An engine with no model is shared: it has a manufacturer
  (Perkins, Cat, Cummins…) and a list of fitted models. A part tagged to a
  shared engine alone fits every machine that engine is fitted to — it appears
  in the browser, the Vehicle filter and search for each of them. A part tagged
  to a model *and* a shared engine is valid only when that engine is fitted to
  the model.
- **Years are optional.** A fitment with no years fits all years. Turning the
  *Model year* criterion off hides year inputs and the browser's year step, and
  is refused while any fitment still carries years. With the criterion on, the
  year step is skipped for a model whose fitments have no years.

## Point of sale (نقطة البيع)

An optional till for quick walk-in sales, switched on in the *Point of sale*
section of the **CRM options** settings tile (off by default).

- A till sale is an ordinary walk-in invoice: created, issued (stock out, with
  the usual shortage check) and paid in one transaction. Reports, the stock
  ledger and cash deposits treat it like any other sale. A shortage or any
  refusal rolls the whole sale back.
- Every sale carries a till-generated key (`PosSale.key`); resubmitting the same
  key returns the same invoice, so a double tap or a dropped connection cannot
  sell twice.
- Payment: cash, card (the store's own card machine) and bank transfer, as
  enabled in settings, and split across them. Non-cash amounts may not exceed
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
  exact hit and adds it; anything else searches names and part numbers. Keys a
  hardware scanner types while focus is elsewhere are routed to the box. An
  unknown code offers **Add a new item with this barcode**; after saving, the
  till adds it to the still-open cart.
- Before any search the till shows the **Most sold** grid: best sellers of the
  last 90 days, topped up with the newest items, leaving out tracked items
  with no stock (search still finds them). Search hits open in a dropdown
  over it; clicking elsewhere folds the dropdown and focusing the box reopens
  it. Picking a vehicle fills the grid with what fits it until **Back to most
  sold**.
- Camera scanning uses the browser's built-in barcode reader where available
  and otherwise the bundled ZXing reader (`sales/static/sales/pos/vendor/`,
  Apache-2.0, loaded on first use, e.g. iPhone Safari). Either needs a secure
  page (localhost or HTTPS).
- Receipts: none, thermal 58 mm / 80 mm, or A4 (settings), printed from the
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
   quantity per item (blank = not counted). Opens in `open` status.
2. The count's page shows a **variance report**: system vs counted, the signed
   variance, and the LYD value of each discrepancy (variance × unit cost).
3. **Apply** it (needs `apply_stocktake`) — the system posts one **Adjustment**
   `StockMovement` per real discrepancy on a tracked product, so `stock_qty`
   becomes the counted figure, and the take locks as `applied` (can't re-apply).
   Adjustments flow through the same append-only ledger as every other stock
   change, so the correction is fully auditable.

Apply promptly after counting: the adjustment is `counted − system-snapshot`, so
a sale between the snapshot and applying would skew it.

## Inventory valuation

A read-only report of **what the stock on hand is worth right now** —
Σ(`stock_qty` × `cost_usd`), shown in USD and converted to LYD at the live rate.
This is the closing-stock figure the fiscal-year financial report uses. Gated
by `view_inventory_valuation`.

The same page answers **what the stock would bring in if it all sold**: each
item's sale value is `stock_qty` × `Product.selling_price_lyd` (the manual LYD
override when set, else the foreign price at the live rate), and its expected
profit is sale value − cost value in LYD. The totals add a margin, profit as a
percentage of sale value. These are today's shelf prices, not a forecast:
invoice discounts and future rate moves are not applied.

## Fiscal year & the financial report

A **fiscal year** here is the calendar year (Jan 1 – Dec 31), which is the norm
in Libya. The **financial report** (`/staff/sales/financial/`, gated by
`view_financial_report`) is a whole-store owner P&L for a chosen year — it is
never per-rep. It reports:

- **Period figures** (for the selected year): **revenue** (issued/partial/paid
  invoices), **cost of goods**, **gross profit** + margin, **posted operating
  expenses**, **net profit**, and **cash collected** (payments received in the year).
- **Current snapshots** (point-in-time, labelled *current*): **outstanding
  receivables** and **inventory value**.

**COGS is exact**: each invoice line freezes the product's unit cost at the time
of sale (`InvoiceItem.unit_cost_usd`), just like it freezes the selling price and
rate — so a later cost change never rewrites a past invoice's profit. COGS =
Σ(quantity × frozen unit cost × the invoice's frozen rate). Lines created before
cost-freezing was added fall back to the product's current cost.

## Purchase invoice attachment

Customer-facing sales invoices do **not** carry scan/PDF attachments. The
supporting scan/photo/PDF belongs to the inbound **Purchase Invoice** because it
represents the supplier document used to add stock. It is captured with the rich
file field (drag-drop, phone camera, or desktop scanner) and shown as a link on
the purchase invoice page.

## Cash deposits (ايداع نقدي)

Technicians and delivery reps **record** the cash they collected (`pending`); an
admin **confirms** or **rejects** it. Invoice payments may reference the deposit
that carried their cash so the books reconcile. A staffer sees only the deposits
they recorded; a manager (`view_all_cashdeposit`) sees all.

## Expenses

Generic operating costs live in `finance.Expense`, grouped optionally by
`ExpenseCategory`. Posted expenses are the only ones subtracted from the
financial report; draft expenses are record-in-progress, and void expenses stay
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
`resolve_staffledgerentry` can resolve or void entries. This keeps staff credit
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
  a **manager** can reassign it to another rep.
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

Issuing locks the invoice, then affected products in primary-key order and their variants in primary-key order. It checks fresh locked balances against all demand for each product and each variant before writing any stock-out movement. Two invoices competing for the last unit result in one successful issue and one insufficient-stock rejection. Combined variant and unassigned lines also share the product stock limit. Opening-stock LYD previews use each row’s selected product currency; purchase previews use the invoice currency.

## Client machinery categories

Machinery has an independent enhancement toggle. Parts and services can fit several machine models while retaining one item and stock/pricing history. Model category branches provide the client drill-down; parent category filters include descendants. Repair is a service-only category containing a quoted-per-job maintenance service, with no stock quantity. ZOOM belongs under CIFA as the customer instructed. Only F8 receives the illustrated branches. Full-path workbook categories disambiguate repeated leaf names. See [CLIENT_CATEGORIZATION.md](CLIENT_CATEGORIZATION.md).

## Independent machinery

MachineType, Manufacturer and MachineModel use `machinery.view_*` lookup permissions (Sales Representatives), plus `add_*`/`change_*` for Sales Managers. Product/service compatibility uses existing catalog add/change permissions and `machinery.view_machinemodel`; purchase rows retain the current purchase/product/stock permissions. There is no separate currency or compatibility-edit grant. The legacy migration appends new role permissions without resetting other grants. Disabled machinery blocks its CRUD/browser routes. Choices and detail rows are scoped; products and services require their respective view permissions in the browser.
