# Sales CRM — Machinery Categorization

Machinery compatibility is an optional enhancement, switched on in System Settings
→ **Optional enhancements** → **Machinery compatibility**. It is independent of
vehicle compatibility, which keeps its own switch and its own year, chassis/generation,
engine, trim, fuel, transmission and position criteria. Machinery has none of those
qualifiers, and enabling it does not change vehicle wording. Settings,
permissions and URLs of both enhancements are in [AUTOMOTIVE_FITMENT.md](AUTOMOTIVE_FITMENT.md).

The flow is **Machine type → Manufacturer → Model → Category branch → Parts or services**.

## Machine records

`machinery.MachineType`, `Manufacturer` and `MachineModel` are scoped records with an
Active flag. A machine model needs only a machine type; manufacturer, model name,
local alias and category branches are optional. A label is the filled details joined
by ` / ` (for example `Concrete pump & mixer / CIFA / F8`). At most one machine exists
per machine type, manufacturer and model name (case-insensitive), blank details
included. Machines without a manufacturer appear directly under their type in the
browser and stay searchable and assignable. Reference lists offer View and Edit on
each row; a record is switched inactive instead of deleted.

Products and services can fit several machine models. The link is a plain
many-to-many relation: it carries no engine, trim or year data and does not
duplicate a product, SKU, stock ledger or price. A vehicle model that a machine
references through `legacy_vehicle_model` is hidden from vehicle screens.

Compatibility is edited with the **Compatible machines** picker in the Product and
Service modals, under the record's own add or change permission plus
`machinery.view_machinemodel`; the Service form shows its Category selector only
while machinery is on. Purchase-invoice and opening-stock rows carry the same picker
in a separate row under the item fields; posting or finalizing adds links to the
created or reused product and never clears existing ones. **Assign machines** on the Products ribbon
opens `/staff/machinery/assign/`, an additive modal that needs `catalog.view_product`,
`catalog.change_product` and `machinery.view_machinemodel`; it lists only active
machines and writes an audit entry per product.

## Categories

`catalog.Category.parent` makes a reusable tree. Choice labels and the category list
show full paths (`Hydraulic / Pump / Piston`). Category forms reject cycles and a
parent from another scope, and the parent selector of a saved category excludes the
category and its descendants. Selecting a parent in the Products category filter or
the machine browser includes its descendants.

`Category.is_service` marks service-only categories. Product and intake forms do not
offer them and product validation rejects them; the browser offers only service entry
inside such a branch. A category that already holds stock items cannot be switched to
service-only.

Opening-stock workbook category cells accept a name or a full path such as
`Hydraulic / Pump / Piston` (separator `/`). A name that matches more than one
category is rejected as ambiguous, and an unknown category is a blocking error.

## Browsing machinery

- **Machines Hub** (`/staff/machinery/`): cards for Browse machinery, Machine types,
  Manufacturers, Machine models, Category branches, Parts and Services, each shown
  only to users who hold its view permission. The hub has a ribbon description.
- **Browse machinery** (`/staff/machinery/browse/`, needs view on machine types,
  manufacturers and machine models). The path is in the query: `type`,
  `manufacturer`, `model`, `category`; `q` searches parts by name, alias, SKU or
  barcode, extra barcodes included (services by name). The type step lists
  manufacturers and manufacturer-less models; the model step lists models with their
  local aliases; then category branches narrow the result.
- **Find a machine** jump search (`/staff/machinery/models/search/?q=`): two or more
  characters, every word must match a model name, alias, manufacturer or machine
  type, up to 20 results.
- Only active vocabulary and compatible active items in the user's scope are shown.
  For a selected model the browser offers its assigned branches with their
  descendants, plus the branches (with their ancestors) of its compatible items, so
  branches appear even when no part is stocked. Parts need `catalog.view_product` and
  services `catalog.view_service`.
- With a model selected, **Add part** and **Add service** open the catalog modals with
  the category and machine preselected, for users who may add them.
- Parts open the product card. A service shows its price, or **Per job** when it has
  none, a service badge and no stock badge.
- The pages reuse the vehicle browser's hub and product partials, stylesheets,
  jump-search widget, breadcrumbs, choice grid and item cards. Both browse search
  forms opt out of assisted entry.

Product and service detail modals and the product card list the compatible machines
while machinery is on and the user holds `machinery.view_machinemodel`. Subject to
permissions, the Products ribbon shows **Browse machinery** when only machinery is on
and **Assign machines** whenever it is on; with both enhancements on it offers only
**Assign vehicles** and **Assign machines**.

Switching machinery off hides its fields and navigation and answers its direct
browser, list and modal routes with HTTP 404; stored compatibility stays intact.
Saved sidebar entries pointing into a switched-off enhancement are hidden at render
time by the project `crm_context` wrapper around the DLux context, empty groups are
removed, and the saved order and labels return when it is switched on.

## Settings card

The Optional enhancements card always renders the machinery block and its **Manage
machinery** action, built like the vehicle block (same dependent-settings component,
Manage-button builder and live event handler). Switching machinery off greys the
block at once and switching it on restores its controls. Each Manage action stays
disabled until the enabled state is saved, then follows the toggle on the open form.
Vehicle year, engine and transmission are always on; only machine type,
chassis/generation, fuel type, trim and part position have switches.

## Seeded vocabulary

`python manage.py seed_machine_categories` (or `--scope ID` for one store scope;
without it the records are global) is atomic and idempotent. A duplicate of a seeded
category name under the same parent stops it without a partial seed.

- Machine type **Concrete pump & mixer**, manufacturer **CIFA**, models **F8**, **F9**,
  **HPG** and **ZOOM**.
- F8 category branches: Hydraulic, Control, S-valve, Hopper, Seal kit.
- Hydraulic: Pump, Motor, Valve, Accumulator, Instruments, Repair.
- Pump: Gear, Piston, Vane, Charge, Tandem, Spare part.
- Hydraulic / Repair is a service-only category holding the maintenance service
  **Repair**, linked to F8 and quoted per job until the store sets a price.

The command creates no products, stock, prices or compatible parts. F9, HPG and ZOOM
have no category branches or fitments; branches are assigned in the machine model modal
and parts with Assign machines or the Product modal.

## Roles

`seed_roles` gives the Sales Representative view on machine types, manufacturers and
machine models, and the Sales Manager view, add and change on them.
