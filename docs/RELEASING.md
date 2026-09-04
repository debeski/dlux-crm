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
