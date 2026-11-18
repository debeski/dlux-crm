# Project Tracker (switch-pos) [Max 100 lines total]
## Part 1: Project Related [Max 55 lines]
### Current Verified Snapshot: [Max 5 lines]
- 2026-11-17: v0.13.0 on branch `feat/dlux-1-16-1` (from v0.12.0 `042195e`), pushed 2026-11-18, PR https://github.com/debeski/dlux-crm/pull/2 open, UNMERGED/UNTAGGED: DjangoLux 1.16.1 + Composer 1.10.1, stack schema 5 (`worker` beside project `celery`), F3 fix in `sales/reports.py`, one pin line. Version v0.13.0 (not v0.12.1: schema/service/Composer minimum change) is the owner's call. v0.12.0 (tag `c43e305`, DjangoLux 1.15.3, schema 4) is the published release.
- v0.11.0 published 2026-10-04 at tag 33df98e; CI and Release 37209994905 green: concurrent purchase currencies under existing permissions, per-product USD/EUR prices, mixed-currency sales/valuation and local aliases. Live dev at :84 now runs v0.11.0; migrations/static applied, all services healthy.
- Public `/`/`/shop/...`/`/contact/modal/`; staff under `/staff/...`; Caddy terminates automatic TLS for apex/www and redirects legacy ERP host.
- `DLUX_APP_VERSION` now comes from `get_project_version(BASE_DIR)` (manifest); root `VERSION` stays the release-gate input and is version-locked to schema-1 `release-manifest.json`.
- Hardened topology: `composer-executor` holds Docker authority, `composer-agent` none, `docker-socket-proxy` read-only. `db-backup`/`pgadmin`/`dlux-updater` retired; their volumes are kept.
### Current Project Adopted Standards: [Max 5 lines]
- Scoped models via `dlux.ScopedModel`; lists are `common.ScopedListView` on the dlux Ribbon + `dlux/list_page.html` (non-list pages use `common.RibbonPageMixin`), CRUD through the modal manager.
- Products retain `currency`; sales freeze `unit_price_lyd` + six-decimal `unit_cost_lyd`, purchases freeze their own currency/rate; finance is dependency root. Decimals fed to JS go through `|unlocalize` (Arabic renders `9,85`).
- Quantity inputs use `common.forms.QUANTITY_INPUT_ATTRS` (`step="any"`); site-wide JS loads via `common/templates/dlux/includes/custom_scripts.html`.
- Variants own stock buckets and the ledger is append-only (undo by compensating movement); images use `ManagedAssetField` namespaced by model — read `image_url`, backfill via `adopt_image_assets --apply`.
- Row visibility uses `OWNER_FIELDS` + `view_all_<model>` and `common.access.apply_ownership` at read boundaries only.
- Public catalog is a curated projection; public contact writes are DB-idempotent.
### Adopted Standards' rules and policies: [Max 5 lines]
- Never delete files; move obsolete paths under `.xclude/` preserving relative paths.
- CSP and four-network isolation remain enforced; web has no egress or Docker API access.
- External rate fetches run in Celery; network changes require `./start.sh -d` recreation.
- Future reservation/purchase/checkout writes require DB-backed idempotency keys.
- Release changes update CHANGELOG/docs and keep tag, `VERSION`, and project manifest aligned.
### Cross-Cutting Audits if any: [Max 3 lines]
- 2026-07-18: Release/update path audit covers Caddy TLS, Composer recovery, baked Dlux gate, and project manifest metadata.
- 2026-08-03: Fixed DLUX source resolves 24 nav candidates/0 API; suffix and nested API names reject while `rapid_report` remains valid.
### Current Project's Unsolved Known Bugs: [Max 5 lines]
- 2026-10-18: Soft-resetting OpeningStockDraft leaves scope uniqueness on trashed rows, blocking replacement drafts. Permanent reset of Stock Movements + Opening Stock Drafts is verified to reopen intake; soft reset still needs a constraint fix.
- v0.11.4 and older: stored files reachable without login; fixed in v0.12.0 and part of the single v0.13.0 upgrade (image first, then release files, then `./start.sh restart caddy`).
- Live VPS/SSH stays severely slow with Compose down; disk/CPU/kernel logs are clean, narrowing the fault to UFW configuration or the provider network/hypervisor rather than Dlux.
- Live VM likely runs stale Caddy/Compose (old portfolio on apex/www; repo proxies Django, redirects ERP): it jumps to v0.13.0 in ONE hop; the bundle README covers it, including orphan containers.
- Deployment SMTP credentials are unset, so contact relay cannot authenticate.
- Updates card can show a stale "Could not read the DjangoLux release index" after an image upgrade until a check completes (DjangoLux `last_check_error`).
### Incomplete Tasks: [Max 20 lines]
- **Priority 1 — run it:**
  - [ ] Pushed with PR #2 (2026-11-18). Owner OK to merge and tag `v0.13.0`; then re-run the testbed from the published image and upgrade the VM in one hop from `dist/crm-sales-0.13.0-deploy.zip` (README order: pull image, `update self`, copy files, `check --fix`, `./start.sh`, orphans, `restart caddy`). Needs `DLUX_FRONT_PROXY` only if a proxy sits in front of Caddy. Retire `feat/unsaved-guard` (ported).
  - [x] v0.10.1 released 2026-10-01: `{% asset %}` content-hash versioning for all 31 project CSS/JS links (stale workspace card after update).
  - [x] Customer 2026-10-03: USD + EUR together, existing purchase permission only, per-product pricing currencies, frozen LYD costs and mixed valuation (v0.11.0 deployed locally).
  - [ ] Owner decision: keep the project `celery` (rate refresh, relay-based) until DjangoLux 1.17 or move that one task to `dlux.taskrunner` (`@task`, `DLUX_TASK_SCHEDULE`, `worker_started`); assessment in the v0.13.0 hand-over. Celery stays off `egress` (relay needs the rw runtime mount); the dev overlay must keep celery/worker runtime `:rw`. `currency-switch` and `automotive-parts-first` carry uncommitted work on old pins: merge this branch's stack files there deliberately.
  - [ ] Click through the running stack at http://localhost:84: row-menu modals, the invoice editor, a purchase invoice, the layout toggle. All 17 lists are verified to RENDER the ribbon server-side; none has been driven by hand.
  - [ ] Confirm the ribbon's Arabic/RTL rendering, `ui_view`/`ui_edit` row labels in Arabic, and the new year dropdown on Invoices/Payments/Expenses.
  - [ ] Verify `show_scan=True` still renders a scanner button on the purchase-invoice/expense attachment: ScanLink is opt-in since dlux 1.8.0.
  - [ ] Verify the packaged smtp-relay reads `SystemSettings.email_config` — the deployment's unset SMTP credentials may be fixable through the UI now.
- **Priority 2 — decisions and follow-ups:**
  - [x] Client diagram implemented/deployed: independent machinery, category hierarchy/service leaves, product/service/intake compatibility; docs/CLIENT_CATEGORIZATION.md. Only F8 branches seeded; other model fitments require actual compatibility data.
  - [x] Optional enhancement architecture: independent vehicle and machinery flows; future pharmacy/cafe packs remain deferred.
  - [ ] POS phase 2 (P1 committed `80c7d96`; till polish + CRM options committed `e430ab0`): P2 phone paired as scanner (server cart per user+till, 1s polling), parked sales, guided cert install (Caddy internal CA on the PC's static IP, QR setup page); P3 shifts/Z-report, returns. Heavy-equipment serial ranges deferred.
  - [ ] Automotive Phases 0/4: obtain the retailer workbook, confirm controlled values/out-of-stock behavior, then build reviewed XLSX import, audit and pilot tooling.
  - [ ] Design ribbon tab strips (Invoice status — `_status_counts` already feeds `get_ribbon_tab_counts`; StockMovement type; PurchaseInvoice status; Product category).
  - [ ] Ask upstream for a detail-modal hook: `get_modal_context()` is merged before `auto_detail_fields` is set, the only reason `templates/dlux/helpers/dynamic_modal_detail.html` is forked.
  - [ ] Re-check that fork against dlux's partial on every upgrade (a test asserts the audit trail and Back control, not full parity).
  - [ ] Purchase-invoice/stock-take/opening-stock editors do NOT fit `DocumentEditorView` — intake lines are plain Forms that create Products, not an inline formset. Left alone deliberately; revisit only if they gain a header+lines shape.
  - [ ] Publish v0.7.0 and confirm the image exposes both baked-version and project-manifest labels.
  - [ ] Storefront polish: mobile `/shop/` search input collapses (placeholder hidden); landing hero kicker has low contrast.
- **Completed Recently:**
  - [x] 2026-11-18: v0.13.0 prepared (PR #2): pin 1.16.1, schema 5, `worker` beside project `celery`, `db` env narrowed, F3 in `build_sales_report_xlsx`, one-hop upgrade README, testbed acceptance from v0.12.0 and v0.11.4. Celery→`dlux.taskrunner` move assessed, not done (no test covers the task; owner's call).
  - [x] 2026-10-02: invoice row deletion/save + cancelled debt; `sales.0010` refunds/customer credit/later modal and idempotent credit use, cancellation releases used credit; receipts retained and reports separate refund/credit liabilities.
  - [x] Removed POS *Open the till on login* and the parts-mode `/staff/` landing (never applied: DLux login goes to its Home); landing = DLux Home (store/per-user; per-group coming in dlux); real-login test `common.tests.test_login_landing` (2026-09-30).
  - [x] Machine wording synced on `SystemSettings` post_save (wizard/import safe); dlux pinned 1.10.0 stable (2026-09-30); relay rates need Composer 1.6.0.
  - [x] Dependent settings: POS and Optional-enhancements dependents greyed/disabled with dlux tooltip instead of hidden; stored values kept while off (2026-09-29).
  - [x] CRM options tile on dlux 1.10.0b1 settings groups (`register_app_settings_group` + `group=`); layout/public catalog/POS as sections, namespaces unchanged; `common/crm_options.py` retired to `.xclude/` (2026-09-30).
  - [x] Test data (2026-09-29): PINV-000003 "Libya Heavy Parts Co." — 21 machines/7 Arabic types, 13 shared engines, 35 products (EAN-13 `624…`, size variants with own codes, low/out-of-stock cases, Fleetguard supplier-label extra code).
  - [x] POS phase 1: till `/staff/sales/pos/`, `sales.pos.complete_sale` (idempotent `PosSale`), card method, discount cap, receipts, `ProductBarcode`; dev POS on; all demo data soft-deleted (2026-09-29).
  - [x] Machinery replacement (2026-10-03): new scoped app, client vocabulary, shared model fitments, local aliases, DLux browser and modals; original engines/year/trim records retained for recovery. No engine/trim controls in machine flow.
  - [x] v0.9.0 (untagged) parts-first automotive UX: Fits picker in Product modal, Same cars as…/Assign vehicles, `PartProfile`/`ProductPartNumber` extension (Product unchanged), browser Find a vehicle + Add part, purchase-line fits, `/staff/` → browser, Vehicle/Year product filters (2026-09-28).
  - [x] v0.8.4 (untagged, merged into this branch): public storefront labels, modals, contact form/links and untouched homepage seed copy follow the visitor language (`public_*` / `hp_seed_*` keys) (2026-09-29).
  - [x] DjangoLux runtime pin advanced exactly from 1.8.13 to 1.9.1 for the v0.8.0 release candidate (2026-09-23).
  - [x] Bundled `config.json` made retailer-neutral: removed Switch/SwitchLibya assets, copy, contacts and public-site app payloads; retained a valid generic settings snapshot (2026-09-23).
  - [x] Automotive UX: removed settings notice, save-gated Manage action, enhancement-gated bilingual hub sidebar entry, and consistent hover/focus behavior across all seven hub cards (2026-09-23).
  - [x] Dev runtime: automotive mounted into web/Celery; Composer v3 wrappers/resident commands; rebuilt on dlux 1.8.13; 9/9 services healthy and automotive migration applied (2026-09-23).
  - [x] v0.8.0 Phase 3: gated Make → Model → Year browser, progressive optional criteria, broad-fitment matching, distinct-SKU counts, stock status and direct Product search (2026-09-23).
  - [x] v0.8.0 Phase 2: gated vehicle-data managers, multi-row fitment editor, Product-card compatibility and reverse keyword search (2026-09-23).
  - [x] v0.8.0 foundation: default-off Optional Enhancements card, configurable automotive criteria/guards, scoped fitment schema and role permissions (2026-09-22).
  - [x] v0.7.3: Opening Stock XLSX validation/diff/finalize; USD+EUR manual/scraped rates; operational Product card; purchase-invoice missing-product path re-verified (2026-09-22).
  - [x] v0.7.3: Inventory Valuation expected profit/margin; purchase-invoice LYD total no longer uses the rate's whole part; quantity step 1 + wheel guard; dlux 1.8.13 (2026-09-11).
  - [x] Product/Service/Listing images moved onto dlux 1.8.4 `ManagedAssetField` (namespaces `catalog.product`, `catalog.service`, `public_catalog.publiccataloglisting`), with `image_url` readers, camera capture, and the `adopt_image_assets` dry-run backfill (2026-09-02).
  - [x] Stock balances rebuild from the live ledger after a dlux data reset (`catalog/stock_balance.py` on `data_reset_finished`); fixes products keeping stock after their movements were cleared (2026-09-02).
  - [x] Ribbons everywhere: `RibbonPageMixin` + `refresh_ribbon()` put a real ribbon on Inventory Valuation, Sales Overview, Sales Report, Financial Report and both public-site builders; 6 more lists gained descriptions (2026-09-02).
### One-line info about last verified Tests: [Max 5 lines]
- 2026-11-18 v0.13.0/DLux 1.16.1: 490 PASS (6 PG-only skips; those modules' 30 cases pass on PostgreSQL 17) in the amd64 image, check + makemigrations + smoke-test clean; testbeds/crm-sales upgraded from v0.12.0 (schema 4) AND from v0.11.4 (DLux 1.12.0, wrapper 3) in the README order: `check` exit 0 (stack-schema 5, stored-files, task-worker OK, front-proxy WARN by design), table+media hashes identical, signed-out attachments 200→403, refresh task OK via relay, XLSX 0 formula cells, 20/20 browser steps per path. Evidence `testbeds/crm-sales/.xclude/acceptance-1.16.1/`.
- 2026-10-12: SQLite throwaway `sales-web` container on `main`: 431 run, 1 failure = `tests.test_scaffold` still asserts the pre-v0.11.1 maintenance probe to `/` (stale test, not the template work); 8/8 Opening Stock Excel tests incl. Arabic template; check + makemigrations clean.
- 2026-10-04: 111 targeted PostgreSQL cases validated (12 management/label cases pass on final rerun); released v0.11.0: 428 PostgreSQL + 423 packaged SQLite tests (4 PG-only skips) + 2 Node checks pass; fresh image smoke passes.
- 2026-09-28: v0.9.0 — 312/312 in `sales-web-1` (SQLite; new: `test_quick_fits` 26, `test_arabic_ui` 3, `test_neutral_branding` 3), `check` + `makemigrations --check` clean, manifest validator OK; UI checked in-browser desktop + 375px.
### One-line info about last time edited Docs: [Max 2 lines]
- 2026-11-18: deploy README (one-hop upgrade, orphans, DLUX_FRONT_PROXY), OPERATIONS "Upgrading to v0.13.0", RELEASING, ARCHITECTURE, README, CHANGELOG v0.13.0 for DjangoLux 1.16.1 / stack schema 5.
## Part 2: Global [Max 20 lines]
### Global Standard Helpers, Shortcuts, Info, etc.:
- No project venv: run tests in `sales-web-1` (`python manage.py test ... --settings=config.settings_dev_sqlite`); new static needs `collectstatic` there before Caddy serves it.
- Validate releases with `python tools/validate_project_release_manifest.py --tag vX.Y.Z --repository debeski/dlux-crm`.
### Global Rulesets:
- Keep tracker under 100 lines; preserve user work; update changelog/docs with feature/config changes.
### Agent Handoff Rules:
- v0.13.0 is UNPUSHED on `feat/dlux-1-16-1` (upstream unset on purpose: push only with `-u origin feat/dlux-1-16-1`, never to `main`; no tag without the owner's OK). Bundle `dist/crm-sales-0.13.0-deploy.zip` (gitignored) via `scripts/build_deploy_zip.sh`. Images/tests need a build: amd64 for the suite (`--entrypoint sh`, copy the tree over `/app`; `.dockerignore` drops tests/docs), arm64 for the testbed. Composer 1.10.1 uses `agent run`/`executor run`; the 1.16.1 scaffold template emits the flat form (upstream defect): never regenerate those blocks from it.
### References and Links:
- Dlux source: `../../pkg-django-lux`; release guide: `docs/RELEASING.md`; operations: `docs/OPERATIONS.md`.
