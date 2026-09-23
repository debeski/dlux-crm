# Switch POS — Roles & Permissions

DjangoLux provides the user/group/permission system (model-level). On top of it
this project adds **row-level visibility**: the same view permission shows a rep
only their own records but a manager the whole store. See
[`common/access.py`](../common/access.py) and [ARCHITECTURE.md](ARCHITECTURE.md).

## Two layers

1. **Model-level (Django/dlux)** — *can this user touch invoices at all?* Enforced
   by `PermissionRequiredMixin` on every view (`raise_exception=True` → 403). Also
   drives the auto-discovered sidebar: no `view_delivery` → no "Deliveries" entry.
   The project-wide `/staff/workspace/` dashboard is discoverable when the user has at
   least one permission that can produce a workspace tile or quick action.
2. **Row-level (this project)** — *which invoices?* Each owned model declares an
   `OWNER_FIELDS` tuple and gains a `view_all_<model>` permission. A user sees a
   row if they are a **superuser**, hold **`view_all_<model>`**, or **own** it
   (they match one of `OWNER_FIELDS`). A model without `OWNER_FIELDS` (product
   catalog, exchange rates) is shared — never row-filtered.

| Model | Owned by (`OWNER_FIELDS`) | "See everyone's" permission |
|-------|---------------------------|-----------------------------|
| `Invoice` | `salesperson`, `created_by` | `sales.view_all_invoice` |
| `Customer` | `created_by` | `sales.view_all_customer` |
| `Payment` | `created_by`, `invoice.salesperson` | `sales.view_all_payment` |
| `Delivery` | `assigned_to`, `created_by` | `sales.view_all_delivery` |
| `finance.CashDeposit` | `created_by` | `finance.view_all_cashdeposit` |
| `finance.Expense` | `paid_by`, `created_by` | `finance.view_all_expense` |
| `finance.StaffAccount` | `user` | `finance.view_all_staffaccount` |
| `finance.StaffLedgerEntry` | `account.user`, `created_by` | `finance.view_all_staffledgerentry` |

Payment receipt printing (`/staff/sales/payments/<id>/receipt/`) uses the same
`sales.view_payment` permission and `Payment` ownership row filter as the
payments list.

## Roles

| Role | Who | Group | Visibility |
|------|-----|-------|------------|
| **Admin / Owner** | المسؤول | Django **superuser** | Everything |
| **Sales Manager** | مدير المبيعات | **"Sales Manager"** | All reps' invoices/customers/payments/deliveries/expenses/staff accounts (holds every relevant `view_all_*`), assigns salespeople & couriers, runs reports, manages catalog + rate, confirms deposits, posts expenses, resolves staff ledger |
| **Sales Representative** | مندوب المبيعات | **"Sales Representative"** | **Own** invoices/customers/payments only (no `view_all_*`); sees own staff account/ledger |
| **Delivery Courier** | مندوب التوصيل | **"Delivery Courier"** | **Only deliveries assigned to them**; records cash collected and sees own staff account/ledger. No access to invoices, reports, or sales-figure tiles |

An invoice's `salesperson` defaults to whoever creates it; only a Manager
(`assign_salesperson`) can reassign it. Same for a delivery's `assigned_to`
(`assign_delivery`).

## Seed the groups

```bash
python manage.py seed_roles
```

Idempotent — safe to re-run after adding models/permissions. Creates/refreshes
**Sales Manager**, **Sales Representative**, and **Delivery Courier** with the
permission sets in [`sales/management/commands/seed_roles.py`](../sales/management/commands/seed_roles.py).

## Custom permissions defined by the project

| Permission | Model | Meaning |
|------------|-------|---------|
| `sales.issue_invoice` | Invoice | Finalize a draft (draws down stock) |
| `sales.cancel_invoice` | Invoice | Cancel an invoice (restores stock) |
| `sales.view_sales_report` | Invoice | View sales reports + XLSX export |
| `sales.view_financial_report` | Invoice | View the whole-store fiscal-year P&L (not row-scoped) |
| `sales.view_all_invoice` | Invoice | See every rep's invoices, not just own |
| `sales.assign_salesperson` | Invoice | Reassign an invoice's salesperson |
| `sales.view_all_customer` | Customer | See every rep's customers |
| `sales.view_all_payment` | Payment | See every rep's payments |
| `sales.view_all_delivery` | Delivery | See all deliveries, not just assigned |
| `sales.assign_delivery` | Delivery | Assign deliveries to couriers |
| `finance.confirm_cashdeposit` | CashDeposit | Confirm / reject deposits |
| `finance.view_all_cashdeposit` | CashDeposit | See every staffer's deposits |
| `finance.post_expense` | Expense | Post / void expenses |
| `finance.view_all_expense` | Expense | See every staffer's expenses |
| `finance.view_all_staffaccount` | StaffAccount | See every user's staff account |
| `finance.resolve_staffledgerentry` | StaffLedgerEntry | Confirm/void/resolve staff ledger entries |
| `finance.view_all_staffledgerentry` | StaffLedgerEntry | See every user's staff ledger entries |
| `catalog.view_supplier` / `add_supplier` / `change_supplier` | Supplier | Manage the supplier list used by purchase invoices |
| `catalog.view_purchaseinvoice` / `add_purchaseinvoice` / `change_purchaseinvoice` | PurchaseInvoice | View and post inbound stock invoices |
| `catalog.apply_stocktake` | StockTake | Post the adjustments from a physical count |
| `catalog.view_inventory_valuation` | StockTake | View the inventory valuation report |
| `automotive.view_*` | Automotive lookups + ProductFitment | Browse vehicle compatibility; granted read-only to Sales Representatives |
| `automotive.add_*` / `change_*` | Automotive lookups + ProductFitment | Maintain compatibility; granted to Sales Managers |
| `automotive.delete_productfitment` | ProductFitment | Remove an incorrect Product/vehicle relationship in the multi-row editor; granted to Sales Managers |

The one-time **Opening Stock** bulk intake has no permission of its own — it
reuses `catalog.add_product` + `catalog.change_product` + `catalog.add_stockmovement`
(it creates/reuses products and posts Stock In movements). Purchase invoices are
separate documents gated by `catalog.add_purchaseinvoice` plus product/stock
permissions because they create or update products and post stock-in movements.

Inventory features (suppliers, purchase invoices, stock movements, stock takes,
opening stock, valuation) are **not row-scoped** —
they're shared management data gated purely by these permissions; the Sales Manager
group holds them, reps/couriers don't.

Automotive records are also shared catalog data. The optional feature switch
controls whether their UI/query experience is active; it never grants access.
Sales Representatives receive view permissions for vehicle lookups and fitments,
Sales Managers receive view/add/change permissions plus delete permission for
ProductFitment, and Delivery Couriers receive none. Managers are intentionally
not granted delete permissions for vehicle reference data: obsolete makes,
models, generations, engines and trims are deactivated. Fitment removal is an
explicit correction from the Product compatibility editor.

Standard `view/add/change/delete` permissions exist for every model. Reports and
the Workspace/Sales Overview sales figures are additionally row-scoped by the
viewer. Workspace tile order, hidden state, and size are stored per user in
DjangoLux app preferences under `switch_pos.workspace_dashboard.v1`, with
`localStorage` retained only as a fallback/migration layer; this is presentation
only and never bypasses server-side permission or ownership checks.

## Assigning a user

1. Create the user (DjangoLux user management UI or admin).
2. Add them to **exactly one** of the three groups.
3. Keep the owner as a superuser.

Because reps/couriers lack the `view_all_*` permissions, they automatically see
only their own rows — no per-user configuration needed.
