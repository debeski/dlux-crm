# Project Tracker (Sales CRM) [Max 100 lines total]
## Part 1: Project Related [Max 55 lines]
### Current Verified Snapshot: [Max 5 lines]
- 2026-11-23: v0.13.0 (DjangoLux 1.16.1, Composer 1.10.1, stack schema 5: `worker` beside the project `celery`, F3 report fix) is on `feat/dlux-1-16-1`, PR https://github.com/debeski/dlux-crm/pull/2 open and held, UNMERGED/UNTAGGED. Published release is still v0.12.0 (DjangoLux 1.15.3, schema 4).
- Sales skips DjangoLux 1.16.2: it goes 1.16.1 -> 1.16.3 (+ Composer 1.10.3) in one step once both are stable (Phase B, owner's OK already given: stack files from the 1.16.3 scaffold, image, tests, testbeds incl. stress, push, merge #2, tag, deployment zip).
- Product name is **Sales CRM** (repo/image `debeski/dlux-crm:sales`, project slug `dlux-crm-sales`); the old name "Switch POS" is gone from docs and comments. Stored identifiers keep the legacy `switch_pos` name (see Known Bugs).
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
- Stored identifiers still carry the old name: cookies `switch_pos_sessionid`/`switch_pos_csrftoken`, the `switch_pos.*` settings/preference namespaces, the `switch.workspace.dashboard.v1` localStorage key, the `switch-pos` User-Agent in `relay/operations.json` + `finance/services.py`, the `switch_pos_db` fallback in `config/settings.py`. Renaming is a Phase B decision with an upgrade test.
- Live VM likely runs a stale stack (old portfolio on apex/www, stored files open to v0.11.4): one-hop upgrade per `deploy/README.md`; check its project and database names first: v0.1.0 `switch_pos`/`switch_pos_db`, v0.1.2 `sales-crm`/`sales_crm_db`, v0.1.3+ `sales`/`sales_db` (a pre-v0.1.3 server would start empty volumes under `name: sales`).
- SMTP credentials unset on the deployment, so the contact relay cannot authenticate. Updates card can show a stale "Could not read the DjangoLux release index" until a check completes.
### Incomplete Tasks: [Max 20 lines]
- **Priority 1 — Phase B (wait for the parent session's message that 1.16.3 + Composer 1.10.3 are stable):**
  - [ ] Pin `django-lux[updater]==1.16.3`; regenerate stack files from that scaffold (drops dead `BACKUP_INTERVAL`/`pgadmin_data`; keep `agent run`/`executor run` if the template still emits the flat form); `check --fix` on a scratch copy and diff; re-test the Caddyfile comment edits.
  - [ ] Rebuild image; suite on amd64 + PostgreSQL-only modules; testbed upgrade from the published v0.12.0 state AND the v0.11.4 state; stress tests (stored-file/media attacks, load, rollback cycle, relay refresh); click through POS checkout (its JS reads cookie `csrftoken`, the project names it `switch_pos_csrftoken`).
  - [ ] Push, merge #2, tag `v0.13.0` (or the next version), let CI release, re-run the testbed from the published image, build `dist/crm-sales-<version>-deploy.zip`.
  - [ ] Decide the stored-identifier renames (list above) with an upgrade test that proves data and sessions survive; unsafe ones stay with a docs note.
- **Priority 2 — owner decisions and follow-ups:**
  - [ ] Keep the project `celery` until DjangoLux 1.17 or move `refresh_market_rates` to `dlux.taskrunner` (about 2-3 h plus a testbed run; no test covers the task). `currency-switch` and `automotive-parts-first` carry uncommitted work on old pins.
  - [ ] Client-brand defaults in code: `DLUX_CONFIG` public title "Switch Libya", `switchlibya.ly` defaults in `compose.yml`, `deploy/env.template` and `ALLOWED_HOSTS`; `portfolio/` is no longer used by the stack; CI tests on Python 3.13, the image runs 3.14.
  - [ ] POS phase 2 (phone as scanner, parked sales, guided certificate install, shifts/Z-report, returns); Automotive Phases 0/4 (retailer workbook, reviewed import); ribbon tab strips; storefront polish (mobile `/shop/` search, hero kicker contrast).
- **Completed Recently:**
  - [x] 2026-11-18: v0.13.0 prepared, pushed, PR #2; testbed acceptance from v0.12.0 and v0.11.4 passed.
  - [x] 2026-11-23: docs audit Phase A (rename to Sales CRM, real README and app READMEs, OPERATIONS/RELEASING rebuilt, doc fixes).
### One-line info about last verified Tests: [Max 5 lines]
- 2026-11-18 (DjangoLux 1.16.1): 490 pass in the amd64 image (6 PostgreSQL-only skips; those modules' 30 cases pass on PostgreSQL 17); testbed upgrade from v0.12.0 and v0.11.4 passed. Evidence: `testbeds/crm-sales/.xclude/acceptance-1.16.1/`. Phase A (2026-11-23) ran no tests, only `py_compile`.
### One-line info about last time edited Docs: [Max 2 lines]
- 2026-11-23: README, per-app READMEs, `docs/*` (OPERATIONS, RELEASING, PERMISSIONS, BUSINESS_RULES, ARCHITECTURE, automotive/QA docs), `deploy/README.md`, template and comment fixes; CHANGELOG history untouched.
## Part 2: Global [Max 20 lines]
### Global Standard Helpers, Shortcuts, Info, etc.:
- No project venv: run the suite in the amd64 image with the worktree copied over `/app` (`--entrypoint sh`; `.dockerignore` drops tests/docs), under `config.settings_dev_sqlite`. Validate releases with `python tools/validate_project_release_manifest.py --tag vX.Y.Z --repository debeski/dlux-crm`.
- Read-only reference sources: `~/Desktop/depy/pkg-django-lux/main` (DjangoLux), `~/Desktop/depy/app-composer/main` (Composer README).
### Global Rulesets:
- Keep tracker under 100 lines; preserve user work; update changelog/docs with feature/config changes.
### Agent Handoff Rules:
- Branch `feat/dlux-1-16-1` (upstream set): push only that branch (`git push origin feat/dlux-1-16-1`), never `main`; merge/tag/release only with the owner's go-ahead (given for Phase B once 1.16.3 + Composer 1.10.3 are stable). Phase A commits are local until then. Composer 1.10.x uses `agent run`/`executor run`; the 1.16.1 scaffold template emits the flat form (upstream defect): never regenerate those blocks from it.
- Testbed `~/Desktop/depy/testbeds/crm-sales`: stop what you start, `docker update --restart=no`; one heavy Docker job at a time.
### References and Links:
- Releasing: `docs/RELEASING.md`; operations: `docs/OPERATIONS.md`; bundle: `deploy/README.md`; PR: https://github.com/debeski/dlux-crm/pull/2.
