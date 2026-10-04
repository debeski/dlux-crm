# Releasing Switch POS

The app ships as the Docker image **`debeski/dlux-crm` (edition tag `sales`)**. Releases are **tag-driven**:
pushing a `v*` git tag runs `.github/workflows/release.yml`, which builds the
multi-arch image, pushes it to Docker Hub, and creates a GitHub Release. The
root `VERSION` and `release-manifest.json.version` are version-locked release
sources; the manifest also supplies the project summary, highlights, and release URL shown by DjangoLux.
At runtime the app reads its own version from the manifest —
`config/settings.py` sets `DLUX_APP_VERSION = get_project_version(BASE_DIR)`
(django-lux 1.5.3) — while `VERSION` remains the input to the release gate, CI,
and the image smoke test. Keeping them equal is enforced by
`tools/validate_project_release_manifest.py` and `tests/test_scaffold.py`.

## v0.11.0 currency and machinery

v0.11.0 was published on 2026-10-04 from `33df98e`. CI and [Release workflow 37209994905](https://github.com/debeski/dlux-crm/actions/runs/37209994905) passed. [Release notes](https://github.com/debeski/dlux-crm/releases/tag/v0.11.0); image tags are `debeski/dlux-crm:sales-v0.11.0` and `debeski/dlux-crm:sales`.

DjangoLux stays pinned to latest stable 1.10.1 (PyPI checked 2026-10-04). This release adds concurrent USD/EUR purchase entry, per-product currencies and aliases, frozen invoice costs, independent machinery compatibility and service-only category branches. Normal startup applies `automotive.0004`, `catalog.0010–0012`, `sales.0011` and `machinery.0001–0002`. Back up the database before upgrading. The machinery data migration preserves original vehicle records and copies legacy equipment compatibility; it does not erase stock or invoices.

For the client-specific CIFA diagram, run the idempotent `python manage.py seed_machine_categories` after migration if that vocabulary is wanted. It creates the illustrated F8 branches and quoted Repair service, with no invented stock or prices. Vehicle year/engine/transmission criteria are always enabled; the five extra criteria remain configurable. Both enhancements can coexist, and saved sidebar entries obey their switches.

Release validation on 2026-10-04 passes all 428 project PostgreSQL tests and both Node invoice-editor checks. The fresh image passes `scripts/smoke-test.sh` (system checks, migration drift, complete fresh migrations and Gunicorn startup); all 423 packaged stable-wheel SQLite tests pass (4 PostgreSQL-only cases skipped, covered by the PostgreSQL run). Local dev source mounts can expose newer framework features; the published image uses the pinned stable wheel. Docker excludes `.xclude` backups; CI includes machinery tests.

## v0.10.2 cancellation settlements

DjangoLux remains pinned to the verified latest stable PyPI wheel, 1.10.1.
`sales.0010` creates receipt-linked refund/customer-credit records and credit
allocations. The normal Composer post-start migration step applies it; no
manual data rewrite is needed. Previously cancelled receipts remain unresolved
until staff choose their actual refund or credit disposition. Refund recording
is bookkeeping only: return the money before marking it refunded.

Release validation on 2026-10-02 used the running sales dev stack at
`http://localhost:84` (currency-switch checkout fast-forwarded from main):
383 app cases on SQLite (3 PostgreSQL concurrency cases skipped), 5 scaffold
checks supplied as test-only container files, 21 PostgreSQL regression/concurrency
cases, Django system check, and the rebuilt-image smoke test. Browser checks
covered new/saved row deletion, draft save, issue/stock restoration, partial
payment to credit, credit application/cancellation release, required refund
method, refund history, resolve-later/later settlement, customer balance, and
financial-report revenue/cash/refund/credit separation. The dev database was
backed up first; QA records are labelled `Release v0.10.2 QA` and the temporary
test account is disabled after verification.

## v0.10.1 dependency baseline

v0.10.1 pins `django-lux[updater]==1.10.1` (hash-pinned wheel). Same Composer
floor and no dlux migrations since 1.10.0; relay-fetched exchange rates still need
Composer 1.6.0. Check PyPI for the latest DjangoLux before every release.

## v0.9.0 dependency baseline

v0.9.0 pins `django-lux[updater]==1.10.0` (hash-pinned wheel): settings
groups, project settings in first-run setup, the unsaved-changes prompt on
project tiles, and the egress relay. DjangoLux's manifest floor is Composer
`>=1.5.3b1` with no dlux migrations since 1.9.4, but fetching exchange rates
through the relay (celery without internet access) needs **Composer 1.6.0** —
update Composer before this release. 1.10.0 removes `AUDIT_FIELD_NAMES`, the
in-container update executor, the `archive_file` names and
`advanced_filter_helper`; the sales CRM uses none of them.

## v0.8.3 dependency baseline

This release pins `django-lux[updater]==1.9.4`. The maintenance operations
introduced by DjangoLux 1.9.3 require Composer 1.5.2 or later, and 1.9.4's
manual first-launch setup (`--skip-config`) requires Composer 1.5.3. Validate the
published wheel and release image before pushing the local release tag.

## One-time setup

Add two repository **Secrets** (Settings → Secrets and variables → Actions → *Secrets* tab):

| Secret | Value |
| :--- | :--- |
| `DOCKERHUB_USERNAME` | Docker Hub namespace that owns the image (`debeski`). |
| `DOCKERHUB_TOKEN` | Docker Hub **access token** with read/write on `debeski/dlux-crm` (Docker Hub → Account Settings → Personal access tokens). |

> The token must be a **Secret**, not a *Variable* — Variables are printed in build logs.

## Cutting a release

1. Update `CHANGELOG.md`: add a new `## vX.Y.Z` section at the top describing the
   changes. The release notes are extracted from this exact section.
2. Bump `VERSION` to the same `X.Y.Z` (no `v` prefix).
3. Update `release-manifest.json` with the same version, release URL, summary,
   and up to eight highlights. Validate it locally with
   `python tools/validate_project_release_manifest.py --tag vX.Y.Z --repository debeski/dlux-crm`.
4. Commit the changelog, version, and manifest on `main`.
5. Tag and push:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
   ```

The `Release` workflow then:

- verifies `tag == VERSION == release-manifest.json.version` plus the schema-1
  summary/highlight limits and repository release URL,
- resolves the baked DjangoLux version from the pinned `django-lux[updater]==` in
  `requirements.txt` and passes it as `--build-arg DLUX_BAKED_VERSION` (stamped as
  `LABEL org.dlux_crm.dlux_baked_version` — the composer-updater version gate),
- compacts the project manifest and passes it as
  `--build-arg DLUX_PROJECT_RELEASE_MANIFEST` to both image builds, stamping
  `LABEL org.dlux.project.release-manifest` for the DjangoLux update review,
- runs `scripts/smoke-test.sh` against a freshly built image (boots the app and
  applies all migrations on SQLite — gates the push on a working image),
- builds `linux/amd64` + `linux/arm64` with Buildx,
- pushes `debeski/dlux-crm:sales-vX.Y.Z` and `debeski/dlux-crm:sales`,
- publishes the GitHub Release using the matching `CHANGELOG.md` section.

## Deploying the published image

The production `compose.yml` reads `${WEB_IMAGE:-debeski/dlux-crm:sales}`. To run the
released image instead of building locally:

```bash
WEB_IMAGE=debeski/dlux-crm:sales ./start.sh -d        # or a pinned :sales-vX.Y.Z
```

## CI

`.github/workflows/ci.yml` runs on every push/PR to `main`: runs Django's system
checks and the test suite (`config.settings_dev_sqlite`, no DB/Redis needed), and
builds the Docker image (no push) + runtime smoke test to catch `Dockerfile`
breakage before a release.

## Why a tag shows under "Tags" but not "Releases"

A git tag is just a commit pointer; a GitHub **Release** is a separate object
layered on a tag. Pushing a tag never auto-creates a Release — `release.yml` does
that for `v*` tags. (Manually: Releases → *Draft a new release* → pick the tag.)
