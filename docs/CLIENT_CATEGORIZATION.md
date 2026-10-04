# Machinery categorization — client diagram

Source: `sales_edition/catagories.pdf`. Accepted customer interpretation: Repair is a billable service; ZOOM is a model under CIFA. Only F8 is expanded in the paper.

## Machinery workflow

The independent Machinery enhancement uses **Machine type → Manufacturer → Model → Category branch → Parts or services**. Enable it from Optional enhancements. Vehicle compatibility has its own toggle and retains its year, generation, engine, trim, fuel, transmission and position criteria. Machinery has none of those qualifiers, and enabling it does not rewrite vehicle labels.

`machinery.MachineType`, `Manufacturer` and `MachineModel` are scoped records. A model has an optional local alias and optional category branches. Products and services can fit multiple models; the compatibility relation does not duplicate a product, SKU, stock ledger or price. Compatibility is edited from the existing product/service modals, under those records' existing create/change permissions and the machine-model lookup permission. Purchase/opening-stock rows can add compatible machines under the existing intake permissions. Intake adds compatibility without clearing previous links.

`catalog.Category.parent` creates a reusable tree. `Category.is_service` marks service-only leaves; Repair is seeded with it, stock forms reject it, and that browser branch offers only service entry. A category containing existing stock items cannot be switched to service-only. Existing categories remain root nodes. Category forms reject cycles and scope mismatches, and their parent selector excludes the current node and its descendants. Choice labels and the category list show full paths. Selecting a parent in the product filter or machine browser includes its descendants. Opening-stock workbook categories accept full paths such as `Hydraulic / Pump / Piston`; ambiguous bare leaf names are rejected.

The browser shows only active scoped vocabulary and compatible active items. Category branches assigned to a model can appear before any parts have been stocked. Parts and services require their respective catalog view permissions. Adding an item from a branch preselects its category and compatible machine. Product cards and product/service detail modals show compatible machines when the enhancement and lookup permission are enabled. Disabling Machinery hides its fields/navigation and rejects its direct CRUD/browser routes; stored compatibility remains intact.

## Client vocabulary

Run `python manage.py seed_machine_categories` (or `--scope ID` for a scoped store). The command is atomic and idempotent; ambiguous existing categories stop it without a partial seed.

- Concrete pump & mixer → CIFA → F8 / F9 / HPG / ZOOM.
- F8 category branches: Hydraulic / Control / S-valve / Hopper / Seal kit.
- Hydraulic: Pump / Motor / Valve / Accumulator / Instruments / Repair.
- Pump: Gear / Piston / Vane / Charge / Tandem / Spare part.
- Hydraulic / Repair contains a maintenance service named Repair, quoted per job until the store sets a price. It does not create stock.

No real products, stock quantities, prices or compatible parts are invented. F9, HPG and ZOOM have no assumed category branches or fitments. Assign shared branches or actual parts explicitly when their compatibility is known.

## Migration and local deployment

`catalog.0011` adds the category hierarchy and service category; `catalog.0012` adds the service-only category flag. `machinery.0001` creates machinery vocabulary and compatibility; `machinery.0002` copies legacy equipment-type models, aliases and compatible products, preserving the original automotive rows. In a store formerly configured with equipment wording, all old models are copied, the machinery toggle inherits the previous enabled value, and vehicle compatibility is turned off with vehicle wording restored. Model-based and shared-engine compatibility become simple machine-model links. Original engine/trim/year data is retained for recovery but is not used by the machine flow.

The migration adds machine lookup permissions to existing Sales Representatives and lookup/create/change permissions to Sales Managers, without replacing their other grants. `seed_roles` includes the same permissions for future setup.

Development compose mounts `./machinery` into web and Celery alongside the existing feature apps. Use the project `./start.sh` wrapper to rebuild/recreate the stack after adding the app, then seed the client vocabulary in the intended scope. Back up the database before migration.

Saved sidebar entries also obey enhancement switches at render time via the project `crm_context` wrapper around DLux context. Disabled vehicle/machinery entries and empty groups are hidden without removing their saved order or labels; re-enabling restores the configured links.

Machinery uses the vehicle hub and browser components: shared hub/product partials, existing automotive stylesheets, the same jump-search widget, breadcrumbs, choice grid and responsive item cards. The scoped `machinery:model_search` endpoint returns active model/type/manufacturer paths and aliases for that picker. Parts open the operational product card; Repair uses the matching card surface with service/per-job pricing and no stock badge. Reference modals use the existing form-grid helper.

Vehicles Hub and Machines Hub use translated navigation titles; Machines Hub includes its ribbon description. Both browse search forms opt out of assisted entry. Products show Browse + Assign for a single active enhancement and only Assign vehicles + Assign machines when both are active, subject to permissions. `machinery:bulk_assign` is an additive scoped modal using the shared vehicle template and DLux searchable selectors. It requires `catalog.view_product`, `catalog.change_product` and `machinery.view_machinemodel`; existing links remain, inactive/cross-scope choices are rejected, and updates are audited. Disabled machine links use the same saved/cached sidebar guard as vehicles.

The Optional enhancements settings form always renders the machinery settings block and Manage action. It uses the same dependent-settings component, Manage-button builder and live event handler as vehicles: switching off greys the block immediately; switching on restores its controls immediately. Both Manage actions require first-time activation to be saved, then react instantly to toggles on the open form. The client diagram’s machine steps remain required. Vehicle year, engine and transmission are always enabled; only machine type, chassis/generation, fuel type, trim and part position have optional switches. Normalization restores those required criteria for legacy configurations that disabled them. The settings form omits both Staff browsing path cards and separates Manage machinery from the automotive card with bottom spacing.
