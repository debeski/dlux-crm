#!/usr/bin/env bash
# Runtime smoke tests for a built Sales CRM image.
#
#   Usage: scripts/smoke-test.sh <image-ref>
#
# Runs the actual image and fails (non-zero) if it is broken, so CI and the
# Release workflow can gate the Docker Hub push on it. Must be run from the repo
# root (reads ./VERSION to assert the image embeds the expected version).
#
# The image's normal entrypoint blocks until a Postgres host named "db" is
# reachable, so every check overrides the entrypoint and boots against the
# bundled SQLite dev config (config.settings_dev_sqlite) — no DB/Redis needed.
set -euo pipefail

IMAGE="${1:?usage: smoke-test.sh <image-ref>}"
DEV_SETTINGS="config.settings_dev_sqlite"
py() { docker run --rm --entrypoint python "$IMAGE" "$@"; }

echo "==> Smoke-testing image: $IMAGE"

# 1. The VERSION baked into the image matches the repo VERSION file.
expected="$(tr -d '[:space:]' < VERSION)"
actual="$(docker run --rm --entrypoint cat "$IMAGE" /app/VERSION | tr -d '[:space:]')"
echo "    version: image='$actual' file='$expected'"
[ "$actual" = "$expected" ] || { echo "::error::image VERSION '$actual' != repo VERSION '$expected'"; exit 1; }

# 2. Django system checks pass.
py manage.py check --settings="$DEV_SETTINGS"
echo "    check: system checks passed"

# 3. No model changes are missing a migration.
py manage.py makemigrations --check --dry-run --settings="$DEV_SETTINGS"
echo "    migrations: none missing"

# 4. The app actually boots and all migrations apply (against in-image SQLite).
py manage.py migrate --noinput --settings="$DEV_SETTINGS" >/dev/null
echo "    migrate: full migration run OK"

# 5. The production WSGI server is installed and runnable.
docker run --rm --entrypoint gunicorn "$IMAGE" --version >/dev/null
echo "    gunicorn: runnable"

echo "==> All runtime smoke tests passed"
