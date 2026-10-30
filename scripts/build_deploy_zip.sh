#!/bin/bash
# Build dist/crm-sales-<version>-deploy.zip: the files a server needs to run the
# published image, and nothing else (no source, no data, no secrets).
#
#   ./scripts/build_deploy_zip.sh
#
# A previous build of the same version is moved to .xclude/dist/ first.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(tr -d '[:space:]' < "${root}/VERSION")"
name="crm-sales-${version}-deploy"
dist="${root}/dist"
bundle="${dist}/${name}"

mkdir -p "${dist}"
for previous in "${bundle}" "${bundle}.zip"; do
  if [[ -e "${previous}" ]]; then
    archive="${root}/.xclude/dist/$(date +%Y%m%d-%H%M%S)"
    mkdir -p "${archive}"
    mv "${previous}" "${archive}/"
  fi
done

mkdir -p "${bundle}/.proxy" "${bundle}/.secrets" "${bundle}/relay" \
  "${bundle}/media" "${bundle}/logs" "${bundle}/imports"
cp "${root}/compose.yml" "${root}/start.sh" "${root}/start.ps1" "${root}/config.json" "${bundle}/"
cp "${root}/.proxy/Caddyfile" "${bundle}/.proxy/"
cp "${root}/relay/operations.json" "${root}/relay/operations.lock" "${bundle}/relay/"
cp "${root}/deploy/README.md" "${bundle}/README.md"
cp "${root}/deploy/env.template" "${bundle}/.secrets/.env.template"
printf 'stable\n' > "${bundle}/.composer-channel"
touch "${bundle}/media/.keep" "${bundle}/logs/.keep" "${bundle}/imports/.keep"
chmod 755 "${bundle}/start.sh"
chmod 700 "${bundle}/.secrets"

# Consumers ship stable only: no beta images and no prerelease DjangoLux pin.
if grep -qE ':beta|:v?[0-9]+\.[0-9]+\.[0-9]+b[0-9]+' "${bundle}/compose.yml" \
  || grep -qE '^django-lux.*[0-9]b[0-9]+' "${root}/requirements.txt"; then
  echo "Refusing to package: compose.yml or requirements.txt references a beta." >&2
  exit 1
fi

(cd "${dist}" && zip -r -X -q "${name}.zip" "${name}" -x '*.DS_Store')
echo "${dist}/${name}.zip"
