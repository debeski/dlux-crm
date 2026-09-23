# Automotive Fitment Module — Phased Delivery Plan

> Implementation status (2026-09-23): Phases 1–3 are implemented for v0.8.0.
> The optional settings card, extension schema, role permissions, vehicle lookup
> managers, multi-row Product fitment editor, Product-card reverse lookup and
> compatibility keyword search, and guided vehicle browser are complete. Phase 0
> retailer data collection and Phase 4 workbook import/pilot work remain open.

## Objective

Add vehicle compatibility to Switch POS without turning the shared `Product`
model into a car-parts-only model. A product remains one SKU, one stock balance,
and one purchasing/sales history. Separate fitment records answer which vehicles
that product fits.

The retailer-facing experience should still feel hierarchical:

```text
Make → Model → Year → Category → Compatible products
```

That hierarchy is a filtered query, not a duplicated product/category tree.

## Decisions That Apply to Every Phase

- Product categories continue to answer **what the item is**. Vehicle fitment
  answers **what the item fits**.
- A product may have many fitments, and one vehicle may have many products.
- A compatible product is never copied per make, model, or year. Selling it from
  any vehicle path changes the same stock bucket.
- Compatibility uses inclusive year ranges (`year_from`, `year_to`), not one row
  per calendar year.
- Automotive is the first entry in a shop-wide **Optional Enhancements** settings
  card. The master switch is off by default, so an upgrade does not change any
  existing installation's navigation, forms, searches, or daily workflow.
- When automotive is enabled, make/model/year form its core. The admin can enable
  or disable chassis/generation, engine, fuel type, trim, transmission, and part
  position independently from the same card.
- The first release's extension schema can support every listed criterion, but
  each store sees and queries only the criteria its admin enables. Criteria are
  structured dimensions, not fragments embedded in a product name or note.
- Turning off the complete automotive enhancement hides its UI and queries but
  preserves extension data so it can be restored by turning the switch back on.
- No automotive column, flag, or nullable field is added to `Product`,
  `ProductVariant`, stock, or invoice tables. The generic asset/catalog database
  contract remains unchanged; optional fitment tables only reference Product.
- Normal catalog search, invoices, purchases, stock movements, and variants must
  continue to work when the automotive feature is disabled.
- All new staff UI, validation messages, and exported/imported labels require
  English and Arabic support, including RTL verification.

## Delivery Boundaries

| Milestone | Included phases | Result |
|---|---|---|
| Architecture approved | Phase 0 | Vocabulary, sample data, and scope agreed with retailer |
| Technical foundation | Phase 1 | Off-by-default enhancement card, domain model, and permissions |
| Usable fitment MVP | Phases 2–3 | Manage fitments and browse vehicle → products in the UI |
| Retailer launch candidate | Phase 4 | Bulk migration, audit, pilot, and operational documentation |
| Automotive v2 | Phase 5 | Refined matching, data-quality tooling, and faster counter workflows |
| Catalog intelligence | Phase 6 | Part-number, cross-reference, VIN, or external-data capabilities |

Phases 0–4 are the recommended first commercial delivery and include the full
configurable criterion set. Phases 5–6 should not block the first retailer launch.

## Optional Enhancements Pattern

The settings experience is designed to support other store-specific CRM
enhancements later without turning the core catalog into a collection of nullable
industry fields.

```text
Optional Enhancements
└── Automotive Compatibility                 [Off by default]
    ├── Chassis / Generation                 [On/Off]
    ├── Engine                               [On/Off]
    ├── Fuel Type                            [On/Off]
    ├── Trim                                 [On/Off]
    ├── Transmission                         [On/Off]
    └── Part Position                        [On/Off]
```

For now, only Automotive Compatibility is registered. A future vertical feature
can register another entry and its own settings, extension tables, UI, and query
service while leaving Product and existing stores alone. Build only the small
registry/configuration seam needed now; do not build a speculative plugin system.

---

## Phase 0 — Retailer Discovery and Data Contract

### Goal

Turn the meeting example into an agreed compatibility vocabulary before schema
or UI work begins.

### Work

1. Collect a representative sample of 50–100 stocked parts covering:
   - parts fitting one model and one year range;
   - parts fitting several models or makes;
   - parts that differ by engine, chassis, trim, or axle position;
   - products with existing SKU, barcode, OEM number, and supplier number;
   - products with color/size variants, if the retailer uses them.
2. Confirm what employees know when serving a customer:
   - make/model/year only;
   - chassis/platform code;
   - engine size or engine code;
   - VIN;
   - OEM or aftermarket part number.
3. Agree display terminology in English and Arabic for make, model, year range,
   compatibility, and “fits vehicles.”
4. Define canonical representations for chassis/generation, engine code and
   displacement, trim, transmission, and position. Blank qualifier values must
   have one agreed meaning: “applies to all values at this level.”
5. Select the initial criterion switches for this retailer. The current car-parts
   profile starts with every confirmed automotive criterion enabled, while other
   stores may use a smaller subset.
6. Decide whether current flat `Category` values are sufficient for launch.
   Nested product categories are a separate catalog project and are not required
   for correct vehicle fitment.
7. Map the retailer's existing spreadsheet columns to the proposed data contract.

### Deliverables

- An anonymized sample inventory workbook.
- Approved bilingual terms.
- A list of fields required for launch versus fields merely requested “someday.”
- Controlled values and matching rules for engine, chassis/generation, trim,
  transmission, and position, including how “all” compatibility is represented.
- The saved Optional Enhancements profile for the retailer.

### Exit gate

Every sample row can be represented without encoding compatibility in product
names or categories. The retailer has resolved ambiguous spellings such as
`1.8`, `1.8L`, and `1800cc`, and can identify the source columns for every
criterion enabled for its launch profile.

---

## Phase 1 — Optional Automotive Foundation

### Goal

Introduce the domain safely without changing generic catalog behavior.

### Proposed app and models

Create a separate `automotive` Django app. Its business records follow the
project's `ScopedModel` conventions and existing audit behavior.

```text
VehicleMake
  name
  is_active

VehicleModel
  make → VehicleMake
  name
  is_active

VehicleGeneration
  vehicle_model → VehicleModel
  name
  chassis_code
  year_from
  year_to
  is_active

VehicleEngine
  vehicle_model → VehicleModel
  generation → VehicleGeneration (optional when shared across generations)
  engine_code
  display_name
  displacement
  fuel_type
  is_active

VehicleTrim
  vehicle_model → VehicleModel
  generation → VehicleGeneration (optional when shared across generations)
  name
  is_active

ProductFitment
  product → catalog.Product
  vehicle_model → VehicleModel
  year_from
  year_to
  generation → VehicleGeneration (optional means all matching generations)
  engine → VehicleEngine (optional means all matching engines)
  trim → VehicleTrim (optional means all matching trims)
  transmission (controlled choice; blank means all)
  position (controlled choice)
  notes (optional, operational notes only)
```

Keeping `vehicle_model` on the fitment makes the base query direct; model-level
validation must ensure any selected generation, engine, and trim belong to that
model and agree with one another. If Phase 0 data shows that the retailer already
has a stable “vehicle configuration” identifier, replace the three optional
qualifier links with a normalized `VehicleConfiguration` lookup rather than
duplicating that identifier's meaning.

### Integrity rules

- Make names are unique within the applicable store scope, case-insensitively.
- Model names are unique per make within scope.
- `year_from <= year_to` is enforced at model/form and database levels.
- Fitment years must fall within the selected generation's supported range when
  a generation is specified.
- Engine, generation, and trim selections must belong to the selected model and
  must describe a consistent configuration.
- Years must be plausible, using an agreed lower bound and a small future-year
  allowance rather than accepting arbitrary integers.
- Exact duplicate product/model/year-range/qualifier/position fitments are rejected.
- Deactivation is preferred to deletion when a make/model is no longer used.
- Fitments use `PROTECT` where lookup removal would erase business meaning and
  `CASCADE` only where removal is explicitly safe, such as deleting a product.
- Add indexes for product reverse lookup, model/year compatibility, and the
  qualifier joins exercised by the browser.

### Optional Enhancements settings card

Register one admin-only settings step/card backed by DjangoLux
`SystemSettings.extra_config`, with a structure such as:

```text
app.switch_pos.optional_enhancements
  automotive
    enabled: false
    criteria
      generation_chassis: true
      engine: true
      fuel_type: true
      trim: true
      transmission: true
      position: true
```

The missing-key fallback for `automotive.enabled` is always `false`. This is the
release-compatibility guarantee: applying migrations or upgrading code does not
activate anything for a running instance. The criterion defaults form the
recommended profile shown when an admin elects to enable automotive; the admin
may deselect criteria before saving.

The card must:

- explain that this is an optional presentation/search enhancement and does not
  convert Product into an automotive asset;
- reveal criterion switches only when the automotive master switch is selected;
- show a preview of the staff navigation and search steps that will appear;
- persist one shop-wide configuration, not a per-user preference;
- require app-admin/superuser authority to change configuration;
- link to fitment data management after the enhancement is enabled;
- expose the same configuration if a future first-run setup wizard adds an
  Optional Enhancements step, rather than maintaining a second source of truth.

The feature helper is the sole reader of this JSON and returns validated defaults.
Templates, views, forms, imports, and query services must not inspect raw settings
independently.

The setting controls navigation and UI exposure. Server-side permissions remain
authoritative; a feature switch is never an authorization mechanism.

### Criterion toggle semantics

- A disabled criterion is absent from create/edit forms, the Vehicle Browser,
  Product card fitment labels, search query construction, and spreadsheet
  templates. Its database column/table still exists as part of the optional app.
- Enabling a criterion does not invent data. Existing broad/all fitments remain
  broad until an authorized user enriches them manually or through import.
- Disabling the complete automotive enhancement is always allowed because all
  compatibility UI and results disappear together; stored data is untouched.
- Disabling one criterion after nonblank values exist needs an impact check. The
  card shows the number of affected fitments and blocks the change until those
  values are explicitly normalized to broad/all or otherwise resolved. Silently
  ignoring engine/chassis constraints could return unsafe false-positive parts.
- Criterion dependencies are validated on save. In the initial model, Fuel Type
  requires Engine; the card explains and automatically selects the dependency
  rather than permitting an incoherent configuration.
- Re-enabling the enhancement or an unused criterion restores its UI without a
  schema migration or deployment.

### Permissions

Add normal view/add/change permissions for makes, models, and fitments.

- Admin/Owner: full management.
- Sales Manager: full management and import.
- Sales Representative: browse compatibility and view product fitments.
- Delivery Courier: no automotive catalog access unless separately granted.

Update `seed_roles`, `docs/PERMISSIONS.md`, navigation discovery, and permission
tests together.

### Validation

- Migrations apply on a fresh database and an upgraded v0.7.3 database.
- A missing settings namespace and an explicit master switch of `false` both
  leave existing product/catalog screens, routes, navigation, and queries unchanged.
- Enabling/disabling each unused criterion immediately changes the form, browser,
  card labels, search service, and generated spreadsheet contract as documented.
- Disabling a used criterion is blocked with an accurate affected-fitment count;
  master disable/re-enable preserves and restores all extension data.
- Permissions return 403 for unauthorized direct URL access.
- Model constraints and scope boundaries have focused tests.

### Exit gate

The schema can represent one SKU fitting multiple model/year ranges without
duplicating Product, ProductVariant, or stock records.

---

## Phase 2 — Fitment Management and Reverse Lookup

### Goal

Let authorized staff maintain compatibility from the product they already know.

### Staff UI

1. Add Make and Model management screens plus management for each enabled
   criterion using existing DjangoLux list/modal patterns. Each selector is
   constrained by the relevant vehicle levels above it.
2. Add a **Fits Vehicles** section to the operational Product card:
   - make and model;
   - inclusive year range;
   - each enabled chassis/generation, engine/fuel, trim, transmission, and
     position constraint;
   - concise label such as `Toyota Corolla · 2014–2019`;
   - edit/remove actions only for authorized users.
3. Add a product fitment editor that supports several compatibility rows in one
   save. Reuse existing products; never create product copies.
4. Use dependent selectors so an invalid model/generation/engine/trim combination
   cannot be submitted from the normal UI. Disabled criteria are not rendered.
5. Show clear duplicate, overlapping-range, inconsistent-configuration, and
   invalid-year messages.
   Overlaps for the same product/model should be consolidated or explicitly
   confirmed rather than accumulating confusing rows.
6. Add reverse lookup to product keyword search so an employee can find a part
   by make/model, chassis, or engine text as well as SKU, barcode, name, and
   size/specification.

### Product card behavior

- “Fits Vehicles” is shown only when the feature is enabled, and its labels use
  only the store's enabled criteria.
- Empty state explains how an authorized manager adds compatibility.
- Existing variants, quantity, pricing, and movement history remain unchanged.
- A fitment describes the product, not a variant. Variant-level fitment is out of
  scope unless Phase 0 proves that physically different SKUs are being modeled as
  variants incorrectly.

### Validation

- Product → vehicles and vehicle → products queries return the same association.
- Editing a fitment never posts a stock movement or changes invoice history.
- A product compatible with four vehicles still has one aggregate stock balance.
- Product card rendering is covered in English and Arabic.

### Exit gate

A manager can create Toyota/Corolla/E170, select the correct engine, trim,
transmission, year range, and position, and attach them to a product. Any employee
with view permission can see the complete relationship from the Product card.

---

## Phase 3 — Vehicle Browser MVP

> Implemented for v0.8.0. The browser is linked from the Products ribbon,
> automotive hub and Product card only while the enhancement is enabled. The
> hub is also available as one optional, permission-gated sidebar-builder entry;
> its individual management lists stay behind the hub. Its
> regression suite covers feature gating, distinct counts, broad/all matching,
> selector skipping, direct search and query growth with 50 additional fitments.
> Out-of-stock Products are shown with a status badge pending the retailer's
> Phase 0/pilot decision.

### Goal

Deliver the retailer's requested pyramid as a fast, guided search experience.

### Primary route and navigation

Add a dedicated **Browse by Vehicle** entry when automotive is enabled. Preserve
the chosen path in query parameters so browser Back, refresh, and shared URLs work:

```text
/staff/automotive/browse/?make=…&model=…&year=…&generation=…&engine=…&category=…
```

### User flow

1. **Make** — active makes with a distinct compatible-product count.
2. **Model** — models belonging to the selected make, with counts.
3. **Year** — dynamically generated from stored ranges; no `VehicleYear` table.
4. **Generation/Chassis** — only shown when more than one compatible choice can
   change the result for the selected model/year and the criterion is enabled.
5. **Engine** — code and human-readable displacement/fuel label.
6. **Trim/Transmission** — progressively shown when they narrow compatibility.
7. **Category** — current Product categories represented in the matching result.
8. **Position** — available positions relevant to the category/result.
9. **Products** — compatible products using the existing card/list components.

The browser should skip a selector when its criterion is disabled or there is
only one valid choice. It must also include broad fitments whose blank qualifier
explicitly means “all,” rather than filtering them out when the customer supplies
a more specific vehicle.

The final query is conceptually:

```text
fitment.vehicle_model.make = selected make
fitment.vehicle_model = selected model
fitment.year_from <= selected year
fitment.year_to >= selected year
fitment.generation = selected generation OR fitment.generation is broad/all
fitment.engine = selected engine OR fitment.engine is broad/all
fitment.trim/transmission match OR the corresponding qualifier is broad/all
product.category = selected category (when provided)
```

Use `distinct()` so overlapping or duplicate-compatible ranges cannot repeat a
product. Product counts count distinct SKUs, not units on hand.

### Result behavior

- Default to active products and active makes/models.
- Clearly mark out-of-stock and low-stock products; decide with the retailer
  whether out-of-stock products are shown by default.
- Open the existing Product card from every result.
- Support direct SKU/barcode/name search without forcing a vehicle path.
- Provide breadcrumb/back controls and a one-click “change vehicle” action.
- Handle missing levels and empty results without resetting the whole path.
- Verify touch targets and RTL flow on the devices used at the counter.

### Performance

- Use `select_related`/`prefetch_related` and aggregate counts; avoid per-card
  compatibility queries.
- Add query-count tests for the final product result.
- Test with a realistic volume agreed in Phase 0, not a ten-row fixture only.
- Cache stable make/model choices if profiling shows a real need; do not cache
  live stock quantities in the compatibility layer.

### Exit gate

An employee can navigate Toyota → Corolla → 2017 → E170 → 1.8L → Brakes, open a
compatible product, sell it through the existing invoice flow, and immediately
see the same reduced stock when reaching that SKU through another compatible
vehicle.

---

## Phase 4 — Bulk Migration, Audit, and Retailer Pilot

### Goal

Make launch data practical to load and safe to verify.

### Fitment spreadsheet import

Reuse the Opening Stock upload pattern: select `.xlsx`, validate, preview a diff,
show conflicts, then finalize transactionally.

Recommended columns:

```text
Product SKU* | Make* | Model* | Year From* | Year To* |
Generation [if enabled] | Chassis Code [if enabled] |
Engine Code / Size [if enabled] | Fuel Type [if enabled] |
Trim [if enabled] | Transmission [if enabled] | Position [if enabled] | Notes
```

The generated template and the modal's required-header guide include core
make/model/year columns plus only the criteria enabled in Optional Enhancements.
Disabled-criterion columns in an uploaded workbook are reported as ignored or
blocking according to the agreed import policy; they are never saved invisibly.

Import rules:

- Product SKU is the stable product identity; product names are display-only.
- Existing makes/models and controlled qualifier values are matched
  case-insensitively after normalization.
- Unknown products are blocking conflicts.
- Unknown makes/models are shown explicitly. The initial importer should either
  create them as a clearly previewed action or require them to be created first;
  it must never create misspelled values silently.
- Unknown qualifier values, impossible model/generation/engine relationships,
  and ambiguous aliases are conflicts; they are never silently reduced to notes.
- Exact existing fitments are unchanged, changed ranges/qualifiers are explicit
  updates, and duplicates/overlaps are conflicts or consolidation suggestions.
- Preview performs no writes; finalization is atomic and audit logged.
- Import limits, file safety checks, user-scoped preview tokens, and stale-token
  behavior should match the hardened Opening Stock importer.

### Pilot sequence

1. Back up the retailer database.
2. Enable automotive only in the pilot environment/store.
3. Import make/model data and fitments from a reviewed workbook.
4. Compare at least 30 parts against the retailer's source records.
5. Run counter exercises with two employees:
   - vehicle-first lookup;
   - product-first reverse lookup;
   - same SKU reached through two vehicles;
   - out-of-stock and low-stock results;
   - correction of an incorrect fitment.
6. Collect search failures for two working weeks and classify them as missing
   data, poor terminology, incorrect broad/all semantics, or matching defects.

### Operational documentation

- How to enable/disable the module.
- Who may maintain compatibility.
- Fitment import template and conflict resolution.
- Backup/rollback and data correction procedure.
- Explicit warning that fitment indicates catalog compatibility, not guaranteed
  installation suitability when the source data is incomplete.

### Exit gate

The reviewed source and CRM agree on the pilot sample, staff can complete the
common lookup flow without advanced filters, and no duplicated inventory was
introduced. This is the retailer launch-candidate milestone.

---

## Phase 5 — Fitment Quality and Counter-Workflow Refinement

### Goal

Improve the required qualifier workflow using evidence from the retailer pilot,
without changing stock identity or burdening non-automotive stores.

### Data-quality work

- Merge duplicate aliases while retaining redirects/audit history.
- Report products with no fitments and qualifier records used by no products.
- Report contradictory broad/all and specific fitments for the same product.
- Suggest consolidation of adjacent or overlapping year ranges with identical
  qualifier sets.
- Track whether a fitment was retailer-entered, imported, or externally sourced.

### Workflow refinements

- Remember a counter user's last selected vehicle only as a user preference, with
  an obvious reset/change-vehicle action.
- Add frequently used vehicles or recent vehicle paths if observed use supports it.
- Offer batch assignment of one fitment set to several selected products.
- Add printable/exportable “Fits Vehicles” information where staff need shelf or
  customer-facing references.
- Tune selector ordering and labels using failed-search logs rather than guesses.

### Search behavior

- Make/model/year remains the simple entry path.
- Qualifiers progressively narrow results only when relevant.
- A broad fitment with no engine qualifier means “all engines” only when that was
  explicitly intended; document and test this matching rule.
- Reverse lookup shows every qualifier needed to distinguish fitment rows.

### Exit gate

The dominant pilot search failures are resolved, compatibility maintenance has a
repeatable audit workflow, and the feature remains invisible when disabled.

---

## Phase 6 — Part Identity and External Catalog Intelligence

### Goal

Improve lookup quality once the retailer's own fitment data is stable.

### Possible capabilities

1. **Product references** — OEM number, manufacturer number, supplier number,
   and aftermarket cross-reference aliases attached to one Product.
2. **Barcode/SKU/reference search** — include references in product and vehicle
   result search without changing stock identity.
3. **VIN-assisted lookup** — decode a VIN into vehicle attributes, then apply the
   local fitment query. Treat decoder results as input, not proof of compatibility.
4. **External fitment catalog import/API** — only after evaluating coverage,
   licensing, update frequency, regional vehicle naming, and data ownership.
5. **Data-quality reports** — products without fitments, impossible ranges,
   inactive models still in use, and overlapping/conflicting fitments.

Each integration needs provenance and a last-updated timestamp so employees can
distinguish retailer-entered compatibility from imported catalog claims.

---

## Cross-Phase Test Matrix

Every implementation phase must cover:

- model constraints, year boundaries, duplicate and overlap handling;
- permissions and direct-URL denial;
- scope isolation where applicable;
- missing configuration and master-off upgrade behavior;
- every criterion toggle, dependency, and used-data disable guard;
- master disable/re-enable data preservation;
- make/model/year/category query correctness and `distinct()` behavior;
- a multi-vehicle SKU retaining one stock balance;
- Product card reverse fitment rendering;
- English, Arabic, and RTL layout;
- spreadsheet safety, dry preview, conflicts, atomic finalize, and replay denial;
- migrations on fresh and upgraded databases;
- full existing finance/catalog/sales regression suite.

## Explicit Non-Goals for the MVP

- No make/model/year columns on `catalog.Product`.
- No automotive feature or criterion columns on Product, ProductVariant, stock,
  purchase, or sales tables; only the optional extension relates back to Product.
- No product duplication per vehicle.
- No individual `VehicleYear` table.
- No nested vehicle values inside `Category`.
- No VIN decoder or paid third-party catalog dependency.
- No separate stock balance per fitment.
- No claim that compatibility data guarantees installation correctness.

## Recommended Next Action

Run Phase 0 with the retailer and obtain the sample workbook before writing the
migration. Use it to validate controlled values, broad/all semantics, the
retailer's initial criterion switches and the implemented Phases 1–3 workflow.
Then use Phase 4 to load and validate the retailer's real catalog. Ship the
Optional Enhancements namespace with Automotive Compatibility off by default,
including for the smart-lock store and every already-running installation.
