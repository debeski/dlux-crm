# Sales CRM — Roles and Permissions

Access is decided in four layers. DjangoLux supplies users, groups and model
permissions. The project adds row ownership on top of them, and DjangoLux store
scopes and the optional-feature switches narrow access further. Business
behaviour is in [BUSINESS_RULES.md](BUSINESS_RULES.md), code layout in
[ARCHITECTURE.md](ARCHITECTURE.md).

1. **Model permissions**: may the user open this kind of record or run this
   action? Django's `view_`, `add_`, `change_`, `delete_` permissions plus the
   custom permissions listed below. Every page, action endpoint, ribbon button
   and row-menu entry is gated on them, and sidebar entries are discovered from
   the same permissions (any one of them shows the entry).
2. **Row ownership**: which records of that kind? A user sees a record they own;
   a `view_all_<model>` permission lifts the filter.
3. **Store scope**: when DjangoLux scopes are enabled, which store's records?
4. **Feature switches**: the point of sale, vehicles, machinery and the public
   site are optional and each is unavailable while it is off.

A signed-out request to a staff page is redirected to `/staff/accounts/login/`.
A signed-in user who lacks the model permission receives 403. A user who holds
the permission but does not own the record receives 404 on its direct URL
(invoice pages, receipts, staff accounts, stored files and the modal lookups).
The CRM's own views never test `is_staff`; DjangoLux's user-directory screens do.

## Roles

| Role | Who | Group | Sees and does |
| --- | --- | --- | --- |
| **Admin / owner** (المسؤول) | The store owner | Django superuser, no group | Everything, in every scope. |
| **Sales Manager** | Back-office and dispatch | `Sales Manager` | Every user's invoices, customers, payments, deliveries, deposits, expenses and staff accounts. Reassigns salespeople and couriers, cancels invoices, runs the sales and financial reports, manages the catalog, purchases, stock movements, stock takes, valuation and opening stock, sets exchange rates, confirms deposits, posts expenses, keeps staff ledgers, uses the till without a discount cap, maintains vehicle and machine reference data. |
| **Sales Representative** (مندوب المبيعات) | Counter or field seller | `Sales Representative` | Own invoices, customers and payments only. Creates and edits own drafts, issues them, records payments, applies customer credit, uses the till, looks up products, services, vehicles and machines read-only, records cash deposits, sees own staff account and ledger. |
| **Delivery Courier** | Driver | `Delivery Courier` | Only the deliveries assigned to them, whose status and notes they update (not the invoice, recipient, phone, address or date). Records cash deposits and sees own staff account and ledger. No access to invoices, customers, catalog or reports. |

A user may belong to several groups; their permissions add up.

**Superuser.** An active superuser passes every permission check and needs no
group and no seeded permission. Ownership filters (`user_can_view_all`) and scope
filters are bypassed, the settings tiles below are theirs alone, and only they can
review soft-deleted rows when that DjangoLux setting is on. A superuser is still
bound by the feature switches (a disabled till or vehicle browser answers 404)
and by the rules in the data model: only draft invoices are editable, payments
on a cancelled invoice and payment settlements are immutable, and a stock
movement cannot be deleted by anyone (`StockMovement.delete` raises
`IntegrityError`; a movement is undone by a compensating one).

## Seeding the groups

```bash
python manage.py seed_roles
```

`sales/management/commands/seed_roles.py` creates the three groups if they are
missing and sets each group's permissions to exactly the lists in that file:
Sales Manager 117, Sales Representative 28, Delivery Courier 6. Setting replaces
the group's permissions, so a grant added by hand to one of these groups is
removed by the next run. A codename that does not exist is reported as
`missing permission` and skipped, so run it after migrations. The command does
not create users, does not assign anyone to a group and creates no DjangoLux
`GroupProfile`; the groups work as plain presets. Nothing runs it automatically:
neither the container entrypoint nor a migration calls it. The machinery
migration `machinery.0002_separate_legacy_machines` appends the machinery grants
to existing `Sales Manager` and `Sales Representative` groups without touching
their other grants.

## Permission matrix

Generated from `seed_roles.py`. V view, A add, C change, D delete, ✓ held,
— not held. Entries marked (own) show only owned records, because the group
holds no `view_all_*` permission for that model; where the cell says view all the
group sees every user's rows.

| Capability | Sales Manager | Sales Representative | Delivery Courier |
| --- | --- | --- | --- |
| **Sales** | | | |
| Invoices | V A C D, view all | V A C (own) | — |
| Issue invoice (`issue_invoice`) | ✓ | ✓ | — |
| Cancel invoice (`cancel_invoice`) | ✓ | — | — |
| Reassign salesperson (`assign_salesperson`) | ✓ | — | — |
| Payments | V A C, view all | V A (own) | — |
| Customers | V A C D, view all | V A C (own) | — |
| Deliveries | V A C D, view all | — | V C (own) |
| Assign deliveries (`assign_delivery`) | ✓ | — | — |
| Sales report and XLSX export | ✓ | — | — |
| Financial report | ✓ | — | — |
| Till (`use_pos`) | ✓ | ✓ | — |
| Till discount above the cap (`pos_unlimited_discount`) | ✓ | — | — |
| POS sale records (`view_possale`) | V | — | — |
| **Catalog and inventory** | | | |
| Products | V A C | V | — |
| Services | V A C | V | — |
| Categories | V A C | — | — |
| Suppliers | V A C | — | — |
| Purchase invoices | V A C | — | — |
| Stock movements | V A | — | — |
| Stock takes | V A C | — | — |
| Apply a stock take (`apply_stocktake`) | ✓ | — | — |
| Inventory valuation (`view_inventory_valuation`) | ✓ | — | — |
| Opening stock | ✓ (through Products A C and Stock movements A) | — | — |
| **Finance** | | | |
| Exchange rates | V A C | — | — |
| Cash deposits | V A C, view all, confirm | V A (own) | V A (own) |
| Expense categories | V A C D | — | — |
| Expenses | V A C D, view all, post | — | — |
| Staff accounts | V A C D, view all | V (own) | V (own) |
| Staff ledger entries | V A C D, view all, resolve | V (own) | V (own) |
| **Optional features** | | | |
| Vehicle lookups (equipment types, makes, models, generations, engines, trims) | V A C | V | — |
| Product fitments, part numbers | V A C D | V | — |
| Part profiles | V A C | V | — |
| Machine types, manufacturers, machine models | V A C | V | — |
| **Not seeded** | | | |
| Public site builders (`public_catalog.*`) | — | — | — |
| DjangoLux administration (`dlux.*`) | — | — | — |

The public-site builders and DjangoLux's user, group, scope, report and backup
screens are reached by superusers, or by users the superuser grants those
permissions to by hand.

## Custom permissions

| Permission | Meaning |
| --- | --- |
| `sales.issue_invoice` | Issue (finalize) a draft invoice; draws stock down. Also part of the till set. |
| `sales.cancel_invoice` | Cancel an invoice, restore its stock and settle its payments; also resolves the unresolved payments of a cancelled invoice. |
| `sales.view_sales_report` | Sales report and its XLSX export, limited to the invoices the viewer may see. |
| `sales.view_financial_report` | The whole-store fiscal-year P&L. Not ownership-filtered. |
| `sales.view_all_invoice`, `view_all_customer`, `view_all_payment`, `view_all_delivery` | See every user's rows of that model instead of only owned ones. |
| `sales.assign_salesperson` | The Salesperson picker on the invoice editor. Without it the field is absent and the invoice belongs to its creator. |
| `sales.assign_delivery` | The Assigned-to courier picker on the delivery form. |
| `sales.use_pos` | Open the till. The till also needs `add_invoice`, `issue_invoice` and `add_payment`. |
| `sales.pos_unlimited_discount` | Give a till discount above the configured cap. |
| `catalog.apply_stocktake` | Post an open stock take's adjustments as stock movements. |
| `catalog.view_inventory_valuation` | The Inventory Valuation report. |
| `finance.confirm_cashdeposit` | Confirm or reject a cash deposit (ايداع نقدي). |
| `finance.view_all_cashdeposit`, `view_all_expense`, `view_all_staffaccount`, `view_all_staffledgerentry` | See every user's rows of that model. |
| `finance.post_expense` | Post or void an expense. |
| `finance.resolve_staffledgerentry` | Confirm, dispute or void any staff ledger entry, not only entries on one's own account. |
| `finance.manage_exchangerate` | Defined on `ExchangeRate`. No view, form or role checks it; rates are changed with `finance.add_exchangerate` and `change_exchangerate`. |

Every project model carries Django's four standard permissions except
`InvoiceItem`, `PaymentResolution`, `CustomerCreditUse`, `OpeningStockDraft`,
`ProductVariant`, `PurchaseInvoiceLine` and `StockTakeLine`, which are managed
through a parent record, a service or a draft flow and have none.

## Row ownership

Each owned model declares `OWNER_FIELDS`. A user sees a row when they are a
superuser, hold the model's `view_all_<model>` permission, or match one of the
owner fields (`common/access.py`).

| Model | Owner fields | See-all permission |
| --- | --- | --- |
| `Invoice` | `salesperson`, `created_by` | `sales.view_all_invoice` |
| `Customer` | `created_by` | `sales.view_all_customer` |
| `Payment` | `created_by`, `invoice.salesperson` | `sales.view_all_payment` |
| `Delivery` | `assigned_to`, `created_by` | `sales.view_all_delivery` |
| `CashDeposit` | `created_by` | `finance.view_all_cashdeposit` |
| `Expense` | `paid_by`, `created_by` | `finance.view_all_expense` |
| `StaffAccount` | `user` | `finance.view_all_staffaccount` |
| `StaffLedgerEntry` | `account.user`, `created_by` | `finance.view_all_staffledgerentry` |
| `PaymentResolution`, `CustomerCreditUse` | through the invoice's `salesperson` and `created_by` | none defined |

The filter is applied at read boundaries, not in a model manager: scoped list
pages, the dynamic-modal view, edit and delete lookup (registered with
`dlux.access.register_modal_queryset_filter` in `CommonConfig.ready()`), invoice
detail, print, edit, issue, payment and cancellation endpoints, payment receipts,
the till receipt, the sales report and its export, Sales Overview, the Workspace
tiles, staff account pages, expense review and stored files.

- An invoice belongs to its salesperson and to its creator. The salesperson
  defaults to the user who creates it and changes only through
  `assign_salesperson`.
- A payment belongs to whoever recorded it and to the invoice's salesperson.
  The invoice page lists all of its payments whoever recorded them.
- Customers are private to their creator. Two users can each keep a customer
  with the same name; typing a name in the invoice editor matches or creates a
  customer only inside the user's own book.
- A delivery is visible to its assignee and its creator.
- `PaymentResolution` and `CustomerCreditUse` are written only by the
  cancellation and credit services and are shown through the owning invoice's
  page; no `view_all_` permission exists for them.
- Models without owner fields are shared and gated only by model permissions:
  products, services, categories, suppliers, purchase invoices, stock movements,
  stock takes, exchange rates, expense categories, POS sale records, vehicle and
  machine data and the public site.
- Not ownership-filtered by design: the financial report, the product and
  service picker of the invoice editor (it lists every active product and
  service in the user's scope and needs only `add_invoice` or `change_invoice`).
- Writes follow the same ownership as reads: an invoice can be bound only to a
  customer the user may see (a posted customer id outside the user's book is
  rejected), a payment only to a pending deposit the user may see, and a delivery
  only to a visible invoice.
- Product cost and markup show on the product card only to holders of
  `catalog.change_product` (who edit them anyway). DjangoLux's generic record
  modal, reachable by a hand-typed URL, still lists every stored field; it has no
  hook for hiding one.

## Store scope

DjangoLux scopes are off by default. While they are on, every record carries a
scope, a record created by a user takes that user's profile scope, and a
non-superuser sees only their own scope's rows. The project's scoped lists and
Workspace tiles return nothing to a non-superuser who has no scope.
Opening-stock drafts are kept per scope (one global draft while scopes are off),
and a non-superuser without a scope cannot use opening stock. Ownership
filtering then applies inside the scope. The financial report is whole-store
within the viewer's scope.

## Feature switches and settings

The settings below are tiles in System settings that only superusers see.

| Feature | Stored under | Default | Effect while off |
| --- | --- | --- | --- |
| Point of sale | `sales_crm.point_of_sale` | off | The till and its endpoints answer 404. |
| Vehicles (automotive) | `sales_crm.optional_enhancements` | off | Vehicle pages, endpoints and modals answer 404. |
| Machinery | `sales_crm.optional_enhancements` | off | Machinery pages, endpoints and modals answer 404. |
| Public site | `sales_crm.public_catalog` | on | Public pages redirect to the staff entry, the builders redirect, and builder writes answer 404. |

While a feature is off its permissions (`automotive`, `machinery`,
`public_catalog`, and `use_pos`, `pos_unlimited_discount` and the `PosSale` model
permissions) are hidden from the group and user permission editors. Hiding is
display only: saving a group or user keeps the hidden grants, so they show,
unchanged, whenever the feature is on (`common/permission_visibility.py`).

The pricing currency (`sales_crm.pricing`) and the shop-wide default Products
layout (`sales_crm.products_layout`) are settings of the same superuser tiles
and do not change who can see what. Each user's own Products layout is a card
for holders of `catalog.view_product`. Choosing the purchase-invoice currency
needs only `catalog.add_purchaseinvoice`; there is no separate currency
permission.

## Workspace and Sales Overview

`/staff/workspace/` is open to every signed-in user, and its sidebar entry shows
for a user holding any permission that can produce a tile or quick action. The
server builds the tiles from permissions and ownership; a user's layout never adds
one. Tiles need the matching view permission: invoices (`sales.view_invoice`),
cash collected (`view_payment`), customers (`view_customer`), deliveries
(`view_delivery`), products and low stock (`catalog.view_product`), valuation,
purchases, suppliers, stock movements and stock takes (their `view_` permissions),
cash deposits, expenses and the staff account (`finance.view_` permissions).
The exchange-rate tile shows for holders of `finance.view_exchangerate`,
`sales.view_invoice` or `catalog.view_product`, and links to the rates page only
with `view_exchangerate`. The Point of Sale tile needs the till on and the four
till permissions; the vehicle and machine browser tiles need their feature on and
their view permissions. A quick action needs the permissions of its target: the
add permissions for creating screens, the report permissions for the reports.

Tile order, hidden state and size are stored per user in the DjangoLux app
preferences `sales_crm.workspace_dashboard.v1` (`Profile.preferences`), with
`localStorage` as a fallback. They are presentation only.

`/staff/sales/dashboard/` (Sales Overview) needs sign-in only. Its figures cover
the invoices, deposits and deliveries the viewer may see; its sections show per
`view_invoice`, `view_delivery` and `catalog.view_product`, and its Reports,
Financial and invoice-creation buttons need their own permissions.

## Action rules

**Invoices.** Creating needs `add_invoice` and editing `change_invoice`. Editing,
issuing, paying, printing and cancelling act only on invoices the user may see,
and only drafts can be edited. Issuing needs `issue_invoice` and is POST-only.
Recording a payment needs `add_payment`, is POST-only, and is refused on draft
and cancelled invoices. Printing needs `view_invoice`. A payment receipt
(`/staff/sales/payments/<id>/receipt/`) needs `view_payment` and passes the
payment ownership filter.

**Cancellation and customer credit.** `/staff/sales/<id>/cancel/` opens the
settlement modal on GET and writes only on POST. It needs `cancel_invoice` and a
visible invoice. A payment is refunded (a method is required), left to resolve
later, or kept as customer credit, which needs the invoice's linked customer.
`/staff/sales/<id>/credit/` applies credit and needs `add_payment` and a visible
target invoice. The credit must belong to the target's customer, and both that
customer and the source invoice must be visible to the user; a forged source id
is rejected. Only issued or partially paid invoices accept credit, and a request
key makes a repeated submit apply once.

**Point of sale.** The till, product lookup, checkout and receipt need
`use_pos`, `add_invoice`, `issue_invoice` and `add_payment`, and the till
switched on. A till sale is an invoice owned by the seller, issued and paid in
one step. A discount above `max_discount_percent` (default 10) is refused unless
the seller holds `pos_unlimited_discount`. The till's add-product shortcut shows
with `catalog.add_product`. A receipt opens only for an invoice the user may see.
The till's *By vehicle* panel and its vehicle search show, and answer, only for a
user who also holds the vehicle browser's permissions (`automotive.view_vehiclemake`,
`view_vehiclemodel`, `view_productfitment` and `catalog.view_product`).

**Inventory.** Product, service, category and supplier changes use their model
permissions. A purchase invoice needs `add_purchaseinvoice`, `add_product`,
`change_product` and `add_stockmovement` together, creates or updates the
products it lists and posts stock-in movements; it can create a supplier by name
without `add_supplier`. Viewing or printing one needs `view_purchaseinvoice`.
Opening-stock draft save and resume, workbook check, template download and
finalization all need `add_product`, `change_product` and `add_stockmovement`.
Drafts are kept per store scope and `OpeningStockDraft` has no permissions of
its own. Manual stock movements need `add_stockmovement`; no seeded role can
change or delete one. A stock take is created with `add_stocktake`, viewed with
`view_stocktake` and applied with `apply_stocktake`.

**Cash deposits.** Any holder of `add_cashdeposit` records a deposit; a deposit
is pending until a holder of `confirm_cashdeposit` confirms or rejects it
(POST-only), and a decided deposit cannot be decided again. The reviewer reaches
only deposits they may see (`view_all_cashdeposit` for other users'). The deposit
form cannot set status or confirmation. A payment joins a deposit only while it
is pending and only one the user may see: a typed reference is matched among
those, and an unknown reference creates a new pending deposit owned by the user.

**Expenses.** Expenses are saved as posted. `post_expense` gates the post and
void endpoint, which also passes the expense ownership filter. Only posted
expenses reduce profit in the financial report.

**Staff accounts.** Holders of `add_staffaccount` and `add_staffledgerentry`
(the Sales Manager group) create one account per user and its entries. An entry
that requires user confirmation (the default) waits as pending, notifies the
account's user, and affects the balance only once posted. The account's user
can confirm or dispute a pending entry; a holder of `resolve_staffledgerentry`
can confirm or dispute any pending entry and can void entries. Disputed and
void entries stay visible and do not affect the balance. Representatives and
couriers see only their own account and entries.

**Vehicles and machinery.** Browsing vehicles needs `automotive.view_vehiclemake`,
`view_vehiclemodel`, `view_productfitment` and `catalog.view_product`; browsing
machinery needs the three `machinery.view_` permissions; the machine browser lists
products only with `catalog.view_product` and services only with
`catalog.view_service`. The Fits-vehicles picker (Product modal, Assign vehicles,
purchase lines, Add part for this vehicle) renders and saves only for users who
hold all four `ProductFitment` permissions; a posted value from anyone else is
ignored. The multi-row fitment editor needs the same four. `ProductFitment` has no
generic modal. While vehicles are on, part brand and part numbers are Product
form fields that follow the product's add and change permissions. The
machine-compatibility field and detail rows show only with machinery on and
`machinery.view_machinemodel`; assigning machines in bulk needs
`catalog.view_product`, `catalog.change_product` and
`machinery.view_machinemodel`. The Sales Manager group holds no delete
permission on vehicle and machine lookup data (makes, models, generations,
engines, trims, equipment types, machine types, manufacturers); only fitments and
part numbers can be deleted.

**Public site.** The shop and homepage builders need
`public_catalog.view_publiccataloglisting`, which also lets a signed-in user
preview a homepage or shop that is switched off (`?preview=1`) while the public
site itself is on. Every builder write needs
`public_catalog.change_publiccataloglisting`.

**Stored files.** Purchase-invoice and expense attachments are served at
`/staff/files/<app>/<model>/<pk>/<field>/` to a signed-in user holding the
record's `view_` permission, within scope and ownership (another user's expense
receipt answers 404). No other model field is reachable there. Product, service
and listing images are public (`DLUX_PUBLIC_MEDIA`). The paperwork folders are
app-only (`DLUX_APP_ONLY_MEDIA`): the `/media/` access check refuses them for
everyone, signed in or not. Any other stored file under `/media/` needs a
signed-in user.

## DjangoLux administration

Users, group presets, scopes, reports, the activity log, backups and audit
columns belong to DjangoLux and have their own permissions. `seed_roles` grants
none of them, and a superuser holds them all.

| Permission | Meaning |
| --- | --- |
| `dlux.manage_staff` | Manage staff users. |
| `dlux.manage_groups` | Manage permission groups (DjangoLux group presets) and assign users to them. |
| `dlux.manage_scopes` | Manage scopes and all users (the Global Staff tier). |
| `dlux.view_reports` | The general reports overview (staff users only). |
| `dlux.view_activitylog` | The activity log. |
| `dlux.download_backup` | Download a backup (staff users only). |
| `dlux.view_audit_fields` | Created-by and updated-by columns, when the audit-fields setting is on. |

DjangoLux's user-management screens require staff status, and a superuser's
account can be managed only by that superuser.

## Assigning a user

1. Run `seed_roles` so the groups exist.
2. Create the user in DjangoLux user management, which a superuser (or a staff
   user granted DjangoLux's own management permissions) operates.
3. Add the user to the group for their job. The owner is a superuser.

Because representatives and couriers hold no `view_all_*` permission they see
only their own rows, with no per-user configuration.
