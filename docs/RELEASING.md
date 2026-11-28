# Releasing Sales CRM

The app ships as the Docker image **`debeski/dlux-crm`, edition tag `sales`**.
Releases are tag-driven: pushing a `v*` git tag runs
`.github/workflows/release.yml`, which builds and smoke-tests the image, pushes
it to Docker Hub for `linux/amd64` and `linux/arm64`, and creates a GitHub
Release. Per-release history is in `CHANGELOG.md`, not here.

## Version sources

`VERSION` and `release-manifest.json` (`version`) are version-locked release
sources, and the tag must equal both. The manifest also supplies the summary,
highlights and release URL that DjangoLux shows in its application-image update
review. At runtime the app reads its own version from the manifest
(`config/settings.py`: `DLUX_APP_VERSION = get_project_version(BASE_DIR)`);
`VERSION` stays the input to the release gate, CI and the image smoke test.
`tools/validate_project_release_manifest.py` and `tests/test_scaffold.py`
enforce that they agree.

Manifest limits (schema 1): a summary of at most 1000 characters, one to eight
highlights of at most 160 characters each, and an HTTPS release URL of the form
`https://github.com/debeski/dlux-crm/releases/tag/vX.Y.Z`.

## Dependencies

- **DjangoLux** is pinned by exactly one line in `requirements.txt`,
  `django-lux[updater]==X.Y.Z`: the stable published on PyPI (wheel and sdist).
  Check PyPI before every release. Never a prerelease and never a direct wheel URL.
- **Composer** is `debeski/composer:latest` (stable) in `compose.yml`, and
  `.composer-channel` holds `stable`. Never a beta image or a beta channel. The
  oldest Composer a release supports is stated in `deploy/README.md`.
- **Stack files** follow the stack schema of the pinned DjangoLux
  (`compose.yml`, `compose.dev.yml`, `Dockerfile`, `entrypoint.sh`, `gunicorn.py`,
  `.proxy/Caddyfile`, `deploy/env.template`, each carrying the schema stamp). When
  the pin moves to a version with a different schema, take the structure from that
  version's scaffold, keep the project parts (services, relay, Caddy routing,
  `db` environment), and run `./start.sh check --fix` on a scratch copy of the
  files to compare; the scratch copy's `check --fix` must change nothing, and its
  `scaffold-drift` line must be OK. The resident Composer commands keep the
  `agent run` / `executor run` form. `start.sh` and `start.ps1` are the pinned
  DjangoLux's scaffold wrappers byte for byte (`tests/test_scaffold.py`).
- **Image floor**: a DjangoLux version with a new image floor or schema cannot be
  installed inline by an existing deployment; it moves with the application image
  plus the release files (see `deploy/README.md`).

## One-time setup

Add two repository **Secrets** (Settings → Secrets and variables → Actions →
*Secrets* tab):

| Secret | Value |
| :--- | :--- |
| `DOCKERHUB_USERNAME` | Docker Hub namespace that owns the image (`debeski`). |
| `DOCKERHUB_TOKEN` | Docker Hub **access token** with read/write on `debeski/dlux-crm` (Account Settings → Personal access tokens). |

The token must be a **Secret**, not a *Variable*: Variables are printed in build logs.

## Cutting a release

1. Update `CHANGELOG.md`: add a `## vX.Y.Z` section at the top. The release notes
   are extracted from this exact section. If the current `VERSION` is already
   tagged, start a new section for the next version; otherwise append to the
   untagged one.
2. Set `VERSION` to the same `X.Y.Z` (no `v` prefix).
3. Update `release-manifest.json` with the same version, release URL, summary and
   highlights, and validate it:
   `python tools/validate_project_release_manifest.py --tag vX.Y.Z --repository debeski/dlux-crm`.
4. Run the tests and the image checks (below) and merge to `main`.
5. Tag and push:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
   ```

The **Release** workflow then:

- verifies `tag == VERSION == release-manifest.json.version`, the schema-1 limits
  and the repository release URL;
- reads the pinned DjangoLux version from `requirements.txt` and passes it as
  `--build-arg DLUX_BAKED_VERSION` (stamped as `LABEL org.dlux_crm.dlux_baked_version`,
  which Composer's version gate reads);
- compacts the project manifest into `--build-arg DLUX_PROJECT_RELEASE_MANIFEST`
  (a quote-safe `base64:` value stamped as `LABEL org.dlux.project.release-manifest`);
- builds an amd64 image and runs `scripts/smoke-test.sh` on it before anything is
  pushed (the image's version equals `VERSION`, Django system checks, no missing
  migration, the full migration run on SQLite, Gunicorn is runnable);
- builds `linux/amd64` and `linux/arm64` with Buildx and pushes
  `debeski/dlux-crm:sales-vX.Y.Z` and `debeski/dlux-crm:sales`;
- publishes the GitHub Release from the matching `CHANGELOG.md` section.

## Checks before the tag

- `python manage.py test finance catalog sales common public_catalog automotive machinery tests --settings=config.settings_dev_sqlite`
  (as CI runs it). The PostgreSQL-only modules skip on SQLite; run them against a
  PostgreSQL database for a release.
- A built image passes `./scripts/smoke-test.sh <image>`.
- The stack files pass `./start.sh check` on a test stack and the upgrade order in
  `deploy/README.md` works from the previous release.

## Deployment bundle

`./scripts/build_deploy_zip.sh` builds `dist/crm-sales-<version>-deploy.zip`: the
files a server needs to run the published image and nothing else (no source, no
data, no secrets): `compose.yml`, `start.sh`, `start.ps1`, `.composer-channel`,
`config.json`, `.proxy/Caddyfile`, `relay/`, `README.md` (from `deploy/README.md`),
`.secrets/.env.template` (from `deploy/env.template`) and empty `media/`, `logs/`
and `imports/`. A previous build of the same version moves to `.xclude/dist/`. The
script refuses to package when `compose.yml` or `requirements.txt` references a
beta. `dist/` is not committed.

## Deploying the published image

The production `compose.yml` reads `${WEB_IMAGE:-debeski/dlux-crm:sales}`. To run a
specific release, set `WEB_IMAGE=debeski/dlux-crm:sales-vX.Y.Z` in
`.secrets/.env`; remove it to follow `:sales`.

## CI

`.github/workflows/ci.yml` runs on every push and pull request to `main`: Django's
system check and the test suite (`config.settings_dev_sqlite`, no database or Redis
needed), then a Docker build (no push) with the runtime smoke test, to catch
`Dockerfile` breakage before a release.

## Tags and Releases

A git tag is only a commit pointer; a GitHub **Release** is a separate object
layered on a tag. Pushing a tag does not create a Release by itself:
`release.yml` does that for `v*` tags. (By hand: Releases → *Draft a new release*
→ pick the tag.)
