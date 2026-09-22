# Switch POS — Business Rules

## Currency

- Switch imports from China and thinks in **USD**; it sells locally in **LYD**.
- LYD prices follow the **black-market** USD rate (higher than the official rate),
  which the admin sets globally.
- Manual USD and EUR rates live in `finance.ExchangeRate` as separate
  **append-only histories**; the newest row for each currency is its live rate.
  Existing catalog cost, pricing and invoice conversion remain USD-based. EUR is
  available as a reference/manual conversion currency and does not silently
  reinterpret any stored USD amount.
- The dashboard also shows cached official and black-market USD and EUR rates
  scraped from CBL and EANLibya. Scraped rates are references only; invoices
  freeze the manually maintained USD rate.

## Pricing model — hybrid (USD base + optional LYD override)

Decided with the owner. For each `Product`:

1. Cost is stored in USD (`cost_usd`). A `markup_percent` (or an explicit
   `price_usd`) yields the **USD selling price** (`effective_price_usd`).
   `Product.save()` **persists** this derived `price_usd` when only cost + markup
   were entered, so the stored record (and its detail view) never shows 0.
2. The **LYD selling price** is derived live: `effective_price_usd × current_rate`.
   Change the rate once and every product's LYD price updates everywhere.
3. Any item may set a manual **`price_lyd_override`** — a fixed LYD price that
   bypasses conversion (for odd / unrelated goods Switch occasionally resells).
   Left blank, the item sells at the live rate (the default).

The create/edit form keeps these fields in step as you type (`catalog/js/price_sync.js`):
editing markup recomputes the USD price, editing the USD price recomputes the markup,
editing cost recomputes the USD price (markup held) while the manual LYD override is
blank, and the live LYD price is shown as the manual-LYD field's **placeholder**.
Typing a value into that field turns it into a real fixed override (and back-fills
USD + markup to match); while that override is present, changing the cost keeps the
LYD price fixed and recalculates the implied USD price + markup from the new cost.
The detail view adds a computed **"Selling Price (LYD)"** row (via
`get_modal_context`) so it matches the list.

`Service` items follow the same override logic and may also be **"per job"**
(no fixed price — entered on the invoice).

## Frozen rate per invoice

When an invoice is created it captures the current rate into `Invoice.exchange_rate`,
and every line stores its own frozen `unit_price_lyd`. **Later rate changes never
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
  via reversing `StockMovement` IN rows.
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
   category, unit, barcode, optional color and size/spec, import cost (USD),
   markup %, selling price (USD), optional manual LYD price, and **quantity in
   storage**. Purchase shop and date are intentionally omitted (irrelevant for an
   opening balance).
   Pricing cells use the same row-scoped live sync as the Product form: markup,
   USD selling price, cost, and manual LYD override stay consistent inside that
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
   barcode, import cost, markup, USD selling price, and manual LYD price. If the
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
override when set, else the USD price at the live rate), and its expected
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
