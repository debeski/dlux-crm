# Project Tracker (Sales CRM) [Max 100 lines total]
## Part 1: Project Related [Max 55 lines]
### Current Verified Snapshot: [Max 5 lines]
- 2026-11-28: **v0.14.0 prepared** on `feat/dlux-1-17-0` (not pushed) for DjangoLux 1.17.0 + Composer 1.11.0: nonce-only CSP + `style-src 'self'`, `dlux.cache_sessions`, wrapper 8, no docker proxy, snapshot Redis, 1.17 `manage.py`. Only the pin bump (`requirements.txt` + `tests/test_scaffold.py` exact-pin test) waits for the stables; owner wants it released right after 1.17.0 stable (customer instance stuck).
- 2026-11-24: **v0.13.0 released** (DjangoLux 1.16.3, Composer 1.10.3, schema 5): PR #2 merged as `8c65cfc`, tag `v0.13.0`, `debeski/dlux-crm:sales-v0.13.0` = `:sales` (`sha256:38661ad2…`, amd64+arm64), GitHub release published. Deploy zip `dist/crm-sales-0.13.0-deploy.zip` (from the tag tree, sha256 `5060067b…`).
- Published image re-tested on the testbed (v0.12.0 → zip + `:sales`) and a fresh install from the zip; testbed left on the published image, stopped.
- Product name is **Sales CRM** (repo/image `debeski/dlux-crm:sales`, project slug `dlux-crm-sales`); the old name "Switch POS" and the customer brand are gone from docs, code defaults and stored identifiers (`sales_crm_*` cookies, `sales_crm.*` settings moved by `common.0001`).
- Public `/`, `/shop/...`, `/contact/modal/`; staff under `/staff/...`; Caddy terminates automatic TLS and redirects the legacy ERP host.
### Current Project Adopted Standards: [Max 5 lines]
- Scoped models via `dlux.ScopedModel`; lists are `common.ScopedListView` on the dlux Ribbon + `dlux/list_page.html` (non-list pages use `common.RibbonPageMixin`), CRUD through the modal manager.
- Products retain `currency`; sales freeze `unit_price_lyd` + six-decimal `unit_cost_lyd`, purchases freeze their own currency/rate; finance is dependency root. Decimals fed to JS go through `|unlocalize`.
- Variants own stock buckets and the ledger is append-only (undo by compensating movement); images use `ManagedAssetField` (`adopt_image_assets --apply`).
- Row visibility uses `OWNER_FIELDS` + `view_all_<model>` and `common.access.apply_ownership` at read boundaries only.
- Public catalog is a curated projection; public contact writes are DB-idempotent.
### Adopted Standards' rules and policies: [Max 5 lines]
- Never delete files; move obsolete paths under `.xclude/` preserving relative paths. Consumers ship only on published stables (no beta pin, `:beta` image or beta channel).
- Four-network isolation: `web` has no egress or Docker API access; the rate refresh reaches the internet only through the Composer relay (`relay/operations.json`, hash-locked in `operations.lock`).
- Future reservation/purchase/checkout writes require DB-backed idempotency keys.
- Release changes update CHANGELOG/docs; tag, `VERSION` and `release-manifest.json` stay aligned. Manuals describe the present: history in CHANGELOG, evidence in `.xclude/validation`.
### Cross-Cutting Audits if any: [Max 3 lines]
- 2026-11-23 docs audit (Phase A, static): rename, README, OPERATIONS/RELEASING rebuilt, BUSINESS_RULES/PERMISSIONS/ARCHITECTURE/AUTOMOTIVE checked against code. Report: `docs-audit-crm-sales.md` in the session notes folder.
### Current Project's Unsolved Known Bugs: [Max 5 lines]
- Soft-resetting `OpeningStockDraft` leaves the scope uniqueness constraint on trashed rows, blocking replacement drafts (permanent reset works).
- Fetch Metadata gate exempts the storefront image folders by path: keep `.proxy/Caddyfile` in step with `DLUX_PUBLIC_MEDIA` (test enforces).
- Live VM likely runs a stale stack (old portfolio on apex/www, stored files open to v0.11.4): one-hop upgrade per `deploy/README.md`; check its project and database names first: v0.1.0 `switch_pos`/`switch_pos_db`, v0.1.2 `sales-crm`/`sales_crm_db`, v0.1.3+ `sales`/`sales_db` (a pre-v0.1.3 server would start empty volumes under `name: sales`).
- SMTP credentials unset on the deployment, so the contact relay cannot authenticate. Updates card can show a stale "Could not read the DjangoLux release index" until a check completes.
### Incomplete Tasks: [Max 20 lines]
- **Priority 1 — follow-ups:**
  - [ ] v0.14.0: pinned to 1.17.0 and testbed-accepted; push, PR, tag and deploy zip on the owner's OK.
  - [ ] Customer instance stuck on the maintenance page (owner-only; operator steps in the 1.17 notes folder `crm-sales-stuck-maintenance.md`).
- **Priority 2 — owner decisions and follow-ups:**
  - [ ] Keep the project `celery` through 1.17.x (removed in 1.18.0) or move `refresh_market_rates` to `dlux.taskrunner` (about 2-3 h plus a testbed run; no test covers the task). `currency-switch` and `automotive-parts-first` carry uncommitted work on old pins.
  - [ ] Ask upstream (DjangoLux) for a per-model detail template or field-visibility hook, so the project need not shadow its `modal_manager` route.
  - [ ] POS phase 2 (phone as scanner, parked sales, guided certificate install, shifts/Z-report, returns); Automotive Phases 0/4 (retailer workbook, reviewed import); ribbon tab strips; storefront polish (mobile `/shop/` search, hero kicker contrast).
- **Completed Recently:**
  - [x] 2026-11-18: v0.13.0 prepared, pushed, PR #2; testbed acceptance from v0.12.0 and v0.11.4 passed.
  - [x] 2026-11-24: `deploy/README.md` first install runs `check --fix` (app-permissions advisory).
  - [x] 2026-11-23: Phase B on DjangoLux 1.16.3: stack files, storefront images exempt from the cross-site gate, stale-settings-cache guard (`common.settings_namespaces`), tested rollback order in `deploy/README.md`; testbed paths A and C passed.
  - [x] 2026-11-23: docs audit Phase A (rename to Sales CRM, real README and app READMEs, OPERATIONS/RELEASING rebuilt, doc fixes).
  - [x] 2026-11-23: ownership on writes (customer, deposit, delivery, deposit review), issued invoices undeletable, cost on the card, POS CSRF, stock-take bucket, Add Stock gating, machinery live uniqueness, till vehicle-panel permissions, no cross-store bulk links, browsable-only vehicle tile, product record view = item card on both modal routes, per-bucket stock takes (`catalog.0014`), stored-identifier renames + `common.0001`, neutral defaults, `portfolio/` retired.
### One-line info about last verified Tests: [Max 5 lines]
- 2026-11-28: 545 pass on SQLite against 1.17.0b3 and 1.17.0 (6 PG-only skips), `check`/`makemigrations --check` clean; testbed accepted on b3 and on the stables (upgrade, data identical, 34 browser steps CSP-clean, Redis pause keeps sessions, relay 4/4, edge 51/51, load, rollback, schema-4 stale flag, customer order from Composer 1.10.4). Evidence `testbeds/crm-sales/.xclude/acceptance-1.17.0b3/` + `acceptance-1.17.0-stable/`.
- 2026-11-23 (DjangoLux 1.16.3): 531 pass on SQLite (6 PG-only skips) and 531 on PostgreSQL 17 + Redis; testbed upgrade from published v0.12.0 and v0.11.4: data identical, settings moved, sign-out once, till sale, relay 4/4, journeys 20/20, edge probes 42/42, load 40 clients no 5xx, rollback + re-upgrade. Evidence `testbeds/crm-sales/.xclude/acceptance-1.16.3/REPORT.md`.
### One-line info about last time edited Docs: [Max 2 lines]
- 2026-11-28: `deploy/README.md` v0.13.0 → v0.14.0 upgrade + rollback, `deploy/env.template`, `docs/OPERATIONS.md`/`ARCHITECTURE.md` (stack, static assets, CSP)/`RELEASING.md`.
- 2026-11-23 (Phase B): `deploy/README.md` rollback order and check --fix effects, `deploy/env.template` + `docs/OPERATIONS.md` SMTP relay/registry settings, Composer 1.10.3. Earlier: README, per-app READMEs, `docs/*` (OPERATIONS, RELEASING, PERMISSIONS, BUSINESS_RULES, ARCHITECTURE, automotive/QA docs), `deploy/README.md`, template and comment fixes; CHANGELOG history untouched.
## Part 2: Global [Max 20 lines]
### Global Standard Helpers, Shortcuts, Info, etc.:
- No project venv: run the suite in the amd64 image with the worktree copied over `/app` (`--entrypoint sh`; `.dockerignore` drops tests/docs), under `config.settings_dev_sqlite`. Validate releases with `python tools/validate_project_release_manifest.py --tag vX.Y.Z --repository debeski/dlux-crm`.
- Read-only reference sources: `~/Desktop/depy/pkg-django-lux/main` (DjangoLux), `~/Desktop/depy/app-composer/main` (Composer README).
### Global Rulesets:
- Keep tracker under 100 lines; preserve user work; update changelog/docs with feature/config changes.
### Agent Handoff Rules:
- Branch `feat/dlux-1-17-0` (no upstream yet; push only with the owner's OK, never `main`); merge/tag/release only with the owner's go-ahead (given for Phase B once 1.16.3 + Composer 1.10.3 are stable). v0.13.0 released 2026-11-24; new work goes on a new branch from `main`. Composer 1.10.x uses `agent run`/`executor run` (the 1.16.3 scaffold emits it too).
- Testbed `~/Desktop/depy/testbeds/crm-sales`: stop what you start, `docker update --restart=no`; one heavy Docker job at a time.
### References and Links:
- Releasing: `docs/RELEASING.md`; operations: `docs/OPERATIONS.md`; bundle: `deploy/README.md`; PR: https://github.com/debeski/dlux-crm/pull/2.
