# Project Tracker (switch-pos) [Max 100 lines total]

## Part 1: Project Related [Max 55 lines]
### Current Verified Snapshot: [Max 5 lines]
- Sales v0.8.3 released 2026-09-26 on `django-lux[updater]==1.9.4` (hash-pinned wheel; tag pushed, CI publishes `debeski/dlux-crm`). Local tag v0.8.2 was never pushed and is superseded. Apps: finance, catalog, automotive, sales, common, public_catalog.
- Public `/`/`/shop/...`/`/contact/modal/`; staff under `/staff/...`; Caddy terminates automatic TLS for apex/www and redirects legacy ERP host.
- `DLUX_APP_VERSION` now comes from `get_project_version(BASE_DIR)` (manifest); root `VERSION` stays the release-gate input and is version-locked to schema-1 `release-manifest.json`.
- Hardened topology: `composer-executor` holds Docker authority, `composer-agent` none, `docker-socket-proxy` read-only. `db-backup`/`pgadmin`/`dlux-updater` retired; their volumes are kept.
- 2026-09-24 baseline: official PyPI 1.9.3 wheel SHA-256 verified; 285 tests (including automotive) and cached-base ARM64 image smoke pass. Fresh amd64 build blocked by PyPI download failures.
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
  - [x] v0.10.1 released 2026-10-01: `{% asset %}` content-hash versioning for all 31 project CSS/JS links (stale workspace card after update).
  - [ ] v0.10.0 (branch `currency-switch`): pricing currency switch implemented (finance.currency, convert on SystemSettings pre_save, Invoice/PurchaseInvoice.currency, common.wording engine with terminology + currency axes, two-currency rate board). Released as v0.10.0 (2026-10-01).
  - [ ] Exchange rates through the Composer relay: merged to `main` 2026-09-30 (unpushed, unreleased) and LIVE on the `automotive-parts-first` dev stack (Composer 1.6.0 stable, DjangoLux 1.10.0; celery on `internal` only; refresh proven through the agent). Do NOT drop `egress` from celery in `main`'s `compose.yml` until Composer 1.6 is stable and production stacks run it: without the relay the scrape then fails. The dev overlay had celery's runtime volume `:ro` (fixed on main, and in the dev tree's uncommitted `compose.dev.yml`), which silently forced the direct-fetch fallback. `automotive-parts-first` also has uncommitted `compose.yml` (beta image tags, no celery egress) and an untracked `.composer-channel`; its uncommitted `CHANGELOG.md` overlaps `main`, so commit your work before merging `main` there.
  - [ ] Click through the running stack at http://localhost:84: row-menu modals, the invoice editor, a purchase invoice, the layout toggle. All 17 lists are verified to RENDER the ribbon server-side; none has been driven by hand.
  - [ ] Confirm the ribbon's Arabic/RTL rendering, `ui_view`/`ui_edit` row labels in Arabic, and the new year dropdown on Invoices/Payments/Expenses.
  - [ ] Verify `show_scan=True` still renders a scanner button on the purchase-invoice/expense attachment: ScanLink is opt-in since dlux 1.8.0.
  - [ ] Verify the packaged smtp-relay reads `SystemSettings.email_config` — the deployment's unset SMTP credentials may be fixable through the UI now.
- **Priority 2 — decisions and follow-ups:**
  - [ ] Decide store-type architecture for Optional enhancements (parts-fitment pack with vehicle/machine flavours vs future pharmacy/cafe packs).
  - [ ] POS phase 2 (P1 committed `80c7d96`; till polish + CRM options committed `e430ab0`): P2 phone paired as scanner (server cart per user+till, 1s polling), parked sales, guided cert install (Caddy internal CA on the PC's static IP, QR setup page); P3 shifts/Z-report, returns. Heavy-equipment serial ranges deferred.
  - [ ] Automotive Phases 0/4: obtain the retailer workbook, confirm controlled values/out-of-stock behavior, then build reviewed XLSX import, audit and pilot tooling.
  - [ ] Design ribbon tab strips (Invoice status — `_status_counts` already feeds `get_ribbon_tab_counts`; StockMovement type; PurchaseInvoice status; Product category).
  - [ ] Ask upstream for a detail-modal hook: `get_modal_context()` is merged before `auto_detail_fields` is set, the only reason `templates/dlux/helpers/dynamic_modal_detail.html` is forked.
  - [ ] Re-check that fork against dlux's partial on every upgrade (a test asserts the audit trail and Back control, not full parity).
  - [ ] Purchase-invoice/stock-take/opening-stock editors do NOT fit `DocumentEditorView` — intake lines are plain Forms that create Products, not an inline formset. Left alone deliberately; revisit only if they gain a header+lines shape.
  - [ ] Publish v0.7.0 and confirm the image exposes both baked-version and project-manifest labels.
  - [ ] Storefront polish: mobile `/shop/` search input collapses (placeholder hidden); landing hero kicker has low contrast.
- **Completed Recently:**
  - [x] Workspace: *Open the till* / *Browse by vehicle* quick actions + `pos_today` / `vehicle_browser` tiles while enabled (2026-09-30).
  - [x] Removed POS *Open the till on login* and the parts-mode `/staff/` landing (never applied: DLux login goes to its Home); landing = DLux Home (store/per-user; per-group coming in dlux); real-login test `common.tests.test_login_landing` (2026-09-30).
  - [x] Machine wording synced on `SystemSettings` post_save (wizard/import safe); dlux pinned 1.10.0 stable (2026-09-30); relay rates need Composer 1.6.0.
  - [x] Dependent settings: POS and Optional-enhancements dependents greyed/disabled with dlux tooltip instead of hidden; stored values kept while off (2026-09-29).
  - [x] CRM options tile on dlux 1.10.0b1 settings groups (`register_app_settings_group` + `group=`); layout/public catalog/POS as sections, namespaces unchanged; `common/crm_options.py` retired to `.xclude/` (2026-09-30).
  - [x] Test data (2026-09-29): PINV-000003 "Libya Heavy Parts Co." — 21 machines/7 Arabic types, 13 shared engines, 35 products (EAN-13 `624…`, size variants with own codes, low/out-of-stock cases, Fleetguard supplier-label extra code).
  - [x] POS phase 1: till `/staff/sales/pos/`, `sales.pos.complete_sale` (idempotent `PosSale`), card method, discount cap, receipts, `ProductBarcode`; dev POS on; all demo data soft-deleted (2026-09-29).
  - [x] Heavy machinery: `EquipmentType`, shared engines + engine-only/all-years fitments (`automotive.0003`), `equipment_type`/`model_year` criteria, machine wording switch via tracked translation overrides; heavy demo data on PINV-000002; dev set to "equipment" wording (2026-09-29).
  - [x] v0.9.0 (untagged) parts-first automotive UX: Fits picker in Product modal, Same cars as…/Assign vehicles, `PartProfile`/`ProductPartNumber` extension (Product unchanged), browser Find a vehicle + Add part, purchase-line fits, `/staff/` → browser, Vehicle/Year product filters (2026-09-28).
  - [x] v0.8.4 (untagged, merged into this branch): public storefront labels, modals, contact form/links and untouched homepage seed copy follow the visitor language (`public_*` / `hp_seed_*` keys) (2026-09-29).
  - [x] Generated app READMEs now recommend the Dlux Ribbon instead of the deprecated `advanced_filter_helper`; active code has no helper or `AUDIT_FIELD_NAMES` dependency (merged 2026-09-26).
  - [x] v0.8.1 version/manifest/changelog aligned and DjangoLux pinned exactly to 1.9.2 for patch-release validation (2026-09-23).
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
  - [x] Scaffold: `composer check --fix` (wrappers v1, executor hardening, obsolete services out, post-start label), image rebuilt on 1.8.3, `dlux-updater` retired, `DLUX_BAKED_VERSION` removed, dev on :84 (2026-09-02).
### One-line info about last verified Tests: [Max 5 lines]
- 2026-10-01: v0.10.0 — 366/366 incl. scaffold on the 1.10.0 image; manifest validated for v0.10.0; workspace rate board and CRM pricing section checked in the browser.
- 2026-09-30: v0.9.0 release check — 358/358 incl. automotive + scaffold on the 1.10.0 image; manifest validated for tag v0.9.0.
- 2026-09-30: 347/347 on dlux 1.10.0b1 (real-login landing, workspace enhancement tiles).
- 2026-09-29: 344/344 app tests after v0.8.4 merge + dependent settings; earlier 341/341 (+popular, +post-migrate wording, +4 `common.tests.test_crm_options`); CRM tile rendered and saved in-browser; till dropdown/outside-click, payment balancing and ZXing load driven in-browser.
- 2026-09-29: 320/320 app tests in `sales-web-1` (SQLite; +8 `test_heavy_equipment`), check + makemigrations clean.
- 2026-09-28: v0.9.0 — 312/312 in `sales-web-1` (SQLite; new: `test_quick_fits` 26, `test_arabic_ui` 3, `test_neutral_branding` 3), `check` + `makemigrations --check` clean, manifest validator OK; UI checked in-browser desktop + 375px.
- 2026-09-29: v0.8.4 storefront i18n — CI set 249/249 (SQLite, throwaway `sales-deck-shots` container), migrations clean, manifest validator OK for v0.8.4.
- 2026-09-26: dlux 1.9.4 — CI test set 248/248 (SQLite), check/migration drift clean, 17 enabled ribbon lists render; hashed 1.9.4 wheel from PyPI.
### One-line info about last time edited Docs: [Max 2 lines]
- 2026-09-29: ARCHITECTURE (CRM options tile, storefront localization), BUSINESS_RULES (POS grid, payment balancing, ZXing, CRM options).
- 2026-09-28: BUSINESS_RULES/ARCHITECTURE/PERMISSIONS/AUTOMOTIVE_FITMENT_PLAN (Phase 3.5) describe quick Fits entry, part identity and parts-mode navigation.

## Part 2: Global [Max 20 lines]
### Global Standard Helpers, Shortcuts, Info, etc.:
- No project venv: run tests in `sales-web-1` (`python manage.py test ... --settings=config.settings_dev_sqlite`); new static needs `collectstatic` there before Caddy serves it.
- Validate releases with `python tools/validate_project_release_manifest.py --tag vX.Y.Z --repository debeski/dlux-crm`.
### Global Rulesets:
- Keep tracker under 100 lines; preserve user work; update changelog/docs with feature/config changes.
### Agent Handoff Rules:
- v0.9.0 lives on branch `automotive-parts-first` (worktree `../automotive-parts-first`; branding + Arabic UI fixes committed); the dev stack runs FROM that folder (own copies of `.secrets/`, `media/`). Demo parts: supplier "Demo Parts Supply", invoice PINV-000001 (30 products, 92 fitments). Dev DB holds a 10-make/127-generation vehicle seed; user's Camry "7th" and Accord "4th"/"5th" rows carry placeholder chassis/years. v0.8.3 is released. On PostgreSQL, 2 tests assume fresh IDs (`test_grid_layout_renders_cards`, purchase-invoice numbering); CI's SQLite set passes. Retailer Phase 0/4 remain open.
### References and Links:
- Dlux source: `../../pkg-django-lux`; release guide: `docs/RELEASING.md`; operations: `docs/OPERATIONS.md`.
