# Operational QA — 2026-10-03

Verification uses isolated test databases, with the running CRM app/framework code. Real stock, invoices and payments are not changed. PostgreSQL checks use a dedicated `crm-operations-qa-db` container, never the CRM database.

## Customer-day simulation

- Buy six EUR pumps (€20 cost, €30 price) and three USD filters ($10 cost, $15 price). Rates: USD 7, EUR 8 LYD. The EUR purchase freezes 960 LYD.
- Sell two pumps with 10% discount: 432 LYD. Collect 100 LYD; cancel to customer credit. Stock returns to six pumps and credit becomes 100 LYD.
- Sell one pump and one filter: 345 LYD. Apply the 100 credit and collect 245 cash. Invoice is paid, remaining credit/debt are zero, stock is five pumps/two filters.
- Change EUR rate to 10. Reports retain 345 LYD revenue and 230 LYD COGS for the issued sale; cash receipts total 345 LYD including the receipt converted to credit.

## Confirmed defects fixed

- **Last-unit race:** before the fix, two concurrent issues both sold the only unit. PostgreSQL regression now requires exactly one sale/one rejection, zero remaining stock, one outgoing movement. Product/variant rows are locked and balances re-read before checking demand.
- **Shared stock limit:** variant and unassigned invoice lines jointly obey the product balance; rejection leaves no outgoing movements.
- **Opening-stock currency preview:** row currency was not wired into the price preview, causing EUR prices to use the default rate. The row now carries per-currency rate hooks; purchase rows continue using the invoice currency.

## Other exercised behavior

Existing regression suites cover invoice editing/deletion, fractional quantities, shortages and transaction rollback, stock variants/counts/rebuilds, repeated POS requests, cash change/card validation/discount permissions, partial payments, cancellation/refunds/credit reuse, concurrent receipt resolution and credit overdraw, permission/ownership isolation, aliases, USD/EUR selection and fallback rates, opening-stock workbooks, storefront and report rendering.

No machinery restructuring is attempted; it still awaits the customer specification. Automated request/service workflows and concurrency checks supplement previous desktop/mobile browser checks; they are not a complete manual browser click-through of every operation.

Validation logs: `/tmp/crm-operations-verified-suite.log`, `/tmp/crm-real-life-postgres-final.log`, `/tmp/crm-real-life-node.log`. The separate PostgreSQL QA container is stopped after verification and retained for recovery.

## Final validation

407 full-suite cases pass (4 PostgreSQL-only cases skipped on SQLite); the separate 51-case PostgreSQL run passes including row-lock concurrency. Two Node invoice-editor regressions pass, system check and migration drift are clean. Read-only live audit: 37 tracked products, zero negative balances, zero ledger mismatches, zero cancelled invoices with debt. Initial scaffold checks needed source-only files excluded from the Docker image; supplying those test fixtures made all scaffold checks pass. Both fixes are deployed through a web-service restart; no schema change or production data write is needed.

## Machinery client workflow — 2026-10-03

419 project tests pass on isolated PostgreSQL 17 using the same mounted DLux source as local CRM (no skips); two Node checks pass. Machinery tests cover idempotent diagram seed, descendant filtering/full-path imports/cycles, purchase stock + shared-model fitments, Repair as a service-only quoted job, disabled endpoints/fields, scoped/inactive choice rejection, settings independence, legacy model/shared-engine copying, and DLux modal/list protocol. Desktop 1366×900 and mobile 390×844 browser checks verify CIFA/F8/category navigation and category/model preselection in service entry. Two older catalog tests now check the actual product URL and invoice format rather than assuming sequences start at 1. Logs: `/tmp/machinery-project-postgres-final.log`, `/tmp/machinery-node.log`.

Live rollout verified machinery hub/model list/browser/workspace return HTTP 200, with 21 copied + 4 diagram models, 26 compatible products, all 37 product records intact and no negative stock. The machinery suite was rerun after the cache fix (12 passing on PostgreSQL), including historical migration/settings refresh; the migration clears the singleton through commit. Database backup: `/tmp/crm-sales-dev-before-machinery-verified.dump` (554K). Local development runtime is the `currency-switch` worktree; its existing DLux source mounts and Compose settings were preserved.

Sidebar follow-up: 150 common/automotive/machinery cases pass, including saved direct links, cached navigation surfaces, empty-group removal, independent switches and saved-order restoration. Log: `/tmp/crm-sidebar-verified.log`.

- 2026-10-03 machinery UI: 251 common/automotive/machinery/catalog tests pass on isolated PostgreSQL 17. Browser jump search, shared operational product card, Repair service modal and 390px mobile layout verified against the isolated fixture.

- 2026-10-04 enhancement controls: four product ribbon switch combinations, additive machine assignment and disabled endpoint covered; 111 targeted PostgreSQL cases (label assertions updated), with all 12 management/label cases passing on final rerun. Machine hub subtitle and assignment modal checked on desktop/390px mobile.

- 2026-10-04 settings parity: 46 automotive/machinery tests pass, then all 18 foundation cases rerun with machine Manage assertions. Browser verified immediate off/on behavior, first-save vehicle hint and 390px layout. Live modal returns HTTP 200 with both Manage actions and the machinery dependent block; static refreshed.

- 2026-10-04 vehicle criteria policy: 96 automotive/machinery/sidebar regressions pass; 19 foundation cases pass on final rerun, including an invariant for exactly five optional switches and normalization of legacy year/engine/transmission flags. Settings checked enabled/disabled at desktop and 390px, with preview cards removed and Manage machinery spacing.

- v0.11.0 release gate (2026-10-04): all 428 project tests pass on PostgreSQL 17; all 423 packaged-image tests pass on SQLite (4 PostgreSQL-only skips); 2 Node checks pass. Fresh pinned 1.10.1 image passes system/migration/Gunicorn smoke; `.xclude` is absent. Logs: `/tmp/v011-release-postgres.log`, `/tmp/v011-release-stable.log`, `/tmp/v011-release-node.log`, `/tmp/v011-release-smoke.log`.
