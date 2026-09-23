# Project Tracker (switch-pos) [Max 100 lines total]

## Part 1: Project Related [Max 55 lines]
### Current Verified Snapshot: [Max 5 lines]
- Django POS/ERP v0.8.0 released after v0.7.3; pins `django-lux[updater]==1.9.1`; apps: finance, catalog, automotive, sales, common, public_catalog.
- Public `/`/`/shop/...`/`/contact/modal/`; staff under `/staff/...`; Caddy terminates automatic TLS for apex/www and redirects legacy ERP host.
- `DLUX_APP_VERSION` now comes from `get_project_version(BASE_DIR)` (manifest); root `VERSION` stays the release-gate input and is version-locked to schema-1 `release-manifest.json`.
- Hardened topology: `composer-executor` holds Docker authority, `composer-agent` none, `docker-socket-proxy` read-only. `db-backup`/`pgadmin`/`dlux-updater` retired; their volumes are kept.
- Current verified baseline 2026-09-23: v0.8.0 released; 285 tests pass on DjangoLux 1.9.1; amd64 image carries the exact pin/manifest and passes the runtime smoke gate.
### Current Project Adopted Standards: [Max 5 lines]
- Scoped models via `dlux.ScopedModel`; lists are `common.ScopedListView` on the dlux Ribbon + `dlux/list_page.html` (non-list pages use `common.RibbonPageMixin`), CRUD through the modal manager.
- Money is frozen per invoice (`exchange_rate`, `unit_price_lyd`); finance is dependency root. Decimals fed to JS go through `|unlocalize` (Arabic renders `9,85`).
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
- Live VPS/SSH stays severely slow with Compose down; disk/CPU/kernel logs are clean, narrowing the fault to UFW configuration or the provider network/hypervisor rather than Dlux.
- Live VM likely runs stale Caddy/Compose: apex/www serve old portfolio while current repo proxies Django and redirects ERP.
- Deployment SMTP credentials are unset, so contact relay cannot authenticate.
- Composer 1.4.1 scaffold v3 is active; resident services use `agent run` / `executor run`. Update Composer with `./start.sh self update`.
- Local reused SQLite has obsolete `sales_invoice.attachment`; fresh migrated databases are correct.
### Incomplete Tasks: [Max 20 lines]
- **Priority 1 — run it:**
  - [ ] Click through the running stack at http://localhost:84: row-menu modals, the invoice editor, a purchase invoice, the layout toggle. All 17 lists are verified to RENDER the ribbon server-side; none has been driven by hand.
  - [ ] Confirm the ribbon's Arabic/RTL rendering, `ui_view`/`ui_edit` row labels in Arabic, and the new year dropdown on Invoices/Payments/Expenses.
  - [ ] Verify `show_scan=True` still renders a scanner button on the purchase-invoice/expense attachment: ScanLink is opt-in since dlux 1.8.0.
  - [ ] Verify the packaged smtp-relay reads `SystemSettings.email_config` — the deployment's unset SMTP credentials may be fixable through the UI now.
- **Priority 2 — decisions and follow-ups:**
  - [ ] Automotive Phases 0/4: obtain the retailer workbook, confirm controlled values/out-of-stock behavior, then build reviewed XLSX import, audit and pilot tooling.
  - [ ] Design ribbon tab strips (Invoice status — `_status_counts` already feeds `get_ribbon_tab_counts`; StockMovement type; PurchaseInvoice status; Product category).
  - [ ] Ask upstream for a detail-modal hook: `get_modal_context()` is merged before `auto_detail_fields` is set, the only reason `templates/dlux/helpers/dynamic_modal_detail.html` is forked.
  - [ ] Re-check that fork against dlux's partial on every upgrade (a test asserts the audit trail and Back control, not full parity).
  - [ ] Purchase-invoice/stock-take/opening-stock editors do NOT fit `DocumentEditorView` — intake lines are plain Forms that create Products, not an inline formset. Left alone deliberately; revisit only if they gain a header+lines shape.
  - [ ] Publish v0.7.0 and confirm the image exposes both baked-version and project-manifest labels.
- **Completed Recently:**
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
  - [x] `common/css/ribbon_actions.css` repairs a `.btn-group` in the ribbon's action area — the panel skin pilled each button, splitting the Products layout switch into loose half-pills (2026-09-02).
  - [x] Scaffold: `composer check --fix` (wrappers v1, executor hardening, obsolete services out, post-start label), image rebuilt on 1.8.3, `dlux-updater` retired, `DLUX_BAKED_VERSION` removed, dev on :84 (2026-09-02).
  - [x] Date filters: Invoice/Payment/Expense on `DatedFilterSet` (year + range); `date_from` -> `date_gte`, old bookmarks lose their filter — user's call (2026-09-02).
### One-line info about last verified Tests: [Max 5 lines]
- 2026-09-23: DjangoLux 1.9.1 clean Python 3.12 environment passes 285/285; amd64 v0.8.0 image label is 1.9.1 and release smoke gate passes checks, migration and Gunicorn.
- 2026-09-23: Brand-neutral `config.json` parses, normalizes to 76 settings, contains no Switch/SwitchLibya/store-contact remnants, and scaffold tests pass 5/5.
- 2026-09-23: 285/285 baseline; automotive 37/37 after gating sidebar discovery/rendering on the persisted enhancement state, with enabled/disabled and bilingual regressions.
- 2026-09-23: Rebuilt live Docker stack 9/9 healthy; `/health/` 200, installed django-lux 1.9.1 confirmed, `automotive.0001_initial` applied.
- 2026-09-11: v0.7.3 — 237 OK on dlux 1.8.13 in a scratch py3.13 venv (`finance catalog sales common public_catalog tests`, sqlite); 231 OK in `sales-web-1` on mounted 1.8.14b3 before the valuation render test; manifest gate OK for v0.7.3.
### One-line info about last time edited Docs: [Max 2 lines]
- 2026-09-23: Architecture names DjangoLux 1.9.1; Operations documents brand-neutral config/port 84; automotive fitment docs cover Phase 3 and sidebar gating.
- 2026-09-11: `docs/BUSINESS_RULES.md` Inventory valuation covers sale value, expected profit and margin.
- 2026-09-04: `docs/RELEASING.md` + `docs/OPERATIONS.md` name `debeski/dlux-crm` and the `:sales-<ver>` / `:sales` tags.

## Part 2: Global [Max 20 lines]
### Global Standard Helpers, Shortcuts, Info, etc.:
- No project venv: run tests in `sales-web-1` (`python manage.py test ... --settings=config.settings_dev_sqlite`); new static needs `collectstatic` there before Caddy serves it.
- Validate releases with `python tools/validate_project_release_manifest.py --tag vX.Y.Z --repository debeski/dlux-crm`.
### Global Rulesets:
- Keep tracker under 100 lines; preserve user work; update changelog/docs with feature/config changes.
### Agent Handoff Rules:
- v0.8.0 is released with automotive Phases 1–3 and DjangoLux 1.9.1. Retailer Phase 0 data decisions and Phase 4 import/pilot remain open.
### References and Links:
- Dlux source: `../../pkg-django-lux`; release guide: `docs/RELEASING.md`; operations: `docs/OPERATIONS.md`.
