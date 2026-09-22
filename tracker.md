# Project Tracker (switch-pos) [Max 100 lines total]

## Part 1: Project Related [Max 55 lines]
### Current Verified Snapshot: [Max 5 lines]
- Django POS/ERP v0.7.3 (untagged) after tagged v0.7.2; pins `django-lux[updater]==1.8.13`; repo `debeski/dlux-crm`, image `debeski/dlux-crm:sales`; apps: finance, catalog, sales, common, public_catalog.
- Public `/`/`/shop/...`/`/contact/modal/`; staff under `/staff/...`; Caddy terminates automatic TLS for apex/www and redirects legacy ERP host.
- `DLUX_APP_VERSION` now comes from `get_project_version(BASE_DIR)` (manifest); root `VERSION` stays the release-gate input and is version-locked to schema-1 `release-manifest.json`.
- Hardened topology: `composer-executor` holds Docker authority, `composer-agent` none, `docker-socket-proxy` read-only. `db-backup`/`pgadmin`/`dlux-updater` retired; their volumes are kept.
- Current verified baseline 2026-09-02: 224 tests pass, `composer check` is all-clean, and the dev stack runs on http://localhost:84 (9 services, all healthy) on the 1.8.3 scaffold.
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
- Inline DjangoLux updates need composer 1.3.10 on this stack (`./start.sh update-self`): the agent now stages the wheel and the executor swaps it offline. No compose change — the agent already mounts `dlux_runtime` rw.
- Local reused SQLite has obsolete `sales_invoice.attachment`; fresh migrated databases are correct.
### Incomplete Tasks: [Max 20 lines]
- **Priority 1 — run it:**
  - [ ] Click through the running stack at http://localhost:84: row-menu modals, the invoice editor, a purchase invoice, the layout toggle. All 17 lists are verified to RENDER the ribbon server-side; none has been driven by hand.
  - [ ] Confirm the ribbon's Arabic/RTL rendering, `ui_view`/`ui_edit` row labels in Arabic, and the new year dropdown on Invoices/Payments/Expenses.
  - [ ] Verify `show_scan=True` still renders a scanner button on the purchase-invoice/expense attachment: ScanLink is opt-in since dlux 1.8.0.
  - [ ] Verify the packaged smtp-relay reads `SystemSettings.email_config` — the deployment's unset SMTP credentials may be fixable through the UI now.
- **Priority 2 — decisions and follow-ups:**
  - [ ] Execute Automotive Phase 0: obtain retailer sample data, normalize criteria, and confirm the initial Optional Enhancements switch profile before schema work.
  - [ ] Design ribbon tab strips (Invoice status — `_status_counts` already feeds `get_ribbon_tab_counts`; StockMovement type; PurchaseInvoice status; Product category).
  - [ ] Ask upstream for a detail-modal hook: `get_modal_context()` is merged before `auto_detail_fields` is set, the only reason `templates/dlux/helpers/dynamic_modal_detail.html` is forked.
  - [ ] Re-check that fork against dlux's partial on every upgrade (a test asserts the audit trail and Back control, not full parity).
  - [ ] Purchase-invoice/stock-take/opening-stock editors do NOT fit `DocumentEditorView` — intake lines are plain Forms that create Products, not an inline formset. Left alone deliberately; revisit only if they gain a header+lines shape.
  - [ ] Publish v0.7.0 and confirm the image exposes both baked-version and project-manifest labels.
- **Completed Recently:**
  - [x] v0.7.3: Opening Stock XLSX validation/diff/finalize; USD+EUR manual/scraped rates; operational Product card; purchase-invoice missing-product path re-verified (2026-09-22).
  - [x] v0.7.3: Inventory Valuation expected profit/margin; purchase-invoice LYD total no longer uses the rate's whole part; quantity step 1 + wheel guard; dlux 1.8.13 (2026-09-11).
  - [x] Product/Service/Listing images moved onto dlux 1.8.4 `ManagedAssetField` (namespaces `catalog.product`, `catalog.service`, `public_catalog.publiccataloglisting`), with `image_url` readers, camera capture, and the `adopt_image_assets` dry-run backfill (2026-09-02).
  - [x] Stock balances rebuild from the live ledger after a dlux data reset (`catalog/stock_balance.py` on `data_reset_finished`); fixes products keeping stock after their movements were cleared (2026-09-02).
  - [x] Ribbons everywhere: `RibbonPageMixin` + `refresh_ribbon()` put a real ribbon on Inventory Valuation, Sales Overview, Sales Report, Financial Report and both public-site builders; 6 more lists gained descriptions (2026-09-02).
  - [x] `common/css/ribbon_actions.css` repairs a `.btn-group` in the ribbon's action area — the panel skin pilled each button, splitting the Products layout switch into loose half-pills (2026-09-02).
  - [x] Scaffold: `composer check --fix` (wrappers v1, executor hardening, obsolete services out, post-start label), image rebuilt on 1.8.3, `dlux-updater` retired, `DLUX_BAKED_VERSION` removed, dev on :84 (2026-09-02).
  - [x] Date filters: Invoice/Payment/Expense on `DatedFilterSet` (year + range); `date_from` -> `date_gte`, old bookmarks lose their filter — user's call (2026-09-02).
### One-line info about last verified Tests: [Max 5 lines]
- 2026-09-22: 248/248 pass in scratch Python 3.12 venv (`finance catalog sales common public_catalog tests`, sqlite); `makemigrations --check`, Django `check`, manifest v0.7.3 and `git diff --check` pass.
- 2026-09-11: v0.7.3 — 237 OK on dlux 1.8.13 in a scratch py3.13 venv (`finance catalog sales common public_catalog tests`, sqlite); 231 OK in `sales-web-1` on mounted 1.8.14b3 before the valuation render test; manifest gate OK for v0.7.3.
- 2026-09-04: v0.7.2 release prep — full CI set (`finance catalog sales common public_catalog tests`) 233 OK on sqlite, `check` clean, manifest gate OK for v0.7.2; local build confirms the image carries `org.dlux_crm.dlux_baked_version`.
- 2026-09-03: 231/231 pass after the ribbon, stock-rebuild and asset-library work; fixed a nightly 22:00-UTC timezone flake in `DatedFilterSetTests` — 219 in-container (`finance catalog sales common public_catalog`, sqlite settings) + 5 host scaffold tests (`tests/` is not in the image).
- 2026-09-02: Live probe renders all 17 lists plus the 4 report/overview pages and both builders with ribbon title + description; the layout switch and the builders' controls sit inside `.dlux-ribbon-actions`.
- 2026-09-02: The CREATE/UPDATE audit fix is asserted against the editor's own `log_user_action` call, not ActivityLog: dlux writes its own rows for scoped CRUD and `recalc_totals()` adds another.
### One-line info about last time edited Docs: [Max 2 lines]
- 2026-09-22: Added phased `AUTOMOTIVE_FITMENT_PLAN.md` with off-by-default Optional Enhancements and per-criterion switches; other docs cover XLSX/card/rates.
- 2026-09-11: `docs/BUSINESS_RULES.md` Inventory valuation covers sale value, expected profit and margin.
- 2026-09-04: `docs/RELEASING.md` + `docs/OPERATIONS.md` name `debeski/dlux-crm` and the `:sales-<ver>` / `:sales` tags.

## Part 2: Global [Max 20 lines]
### Global Standard Helpers, Shortcuts, Info, etc.:
- No project venv: run tests in `sales-web-1` (`python manage.py test ... --settings=config.settings_dev_sqlite`); new static needs `collectstatic` there before Caddy serves it.
- Validate releases with `python tools/validate_project_release_manifest.py --tag vX.Y.Z --repository debeski/dlux-crm`.
### Global Rulesets:
- Keep tracker under 100 lines; preserve user work; update changelog/docs with feature/config changes.
### Agent Handoff Rules:
- Release rollout remains pending; do not report image labels live until the tagged image is built and inspected.
### References and Links:
- Dlux source: `../../pkg-django-lux`; release guide: `docs/RELEASING.md`; operations: `docs/OPERATIONS.md`.
