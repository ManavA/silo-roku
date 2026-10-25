#!/usr/bin/env bash
# Upload a local development ZIP to a Roku already in Developer Mode.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${ROKU_HOST:?Set ROKU_HOST to the Roku IP address shown in Developer Mode}"
if [[ ! "$ROKU_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]]; then
  echo "ROKU_HOST must be a bare IP address or host name" >&2
  exit 2
fi
if [[ -z "${ROKU_DEV_PASSWORD:-}" ]]; then
  read -r -s -p 'Roku developer password: ' ROKU_DEV_PASSWORD
  printf '\n'
fi
if [[ -z "$ROKU_DEV_PASSWORD" ]]; then
  echo "Roku developer password is required" >&2
  exit 2
fi

python3 "$project_root/tools/package.py"
archive="$project_root/dist/silo-roku.zip"
response="$project_root/dist/sideload-response.html"
curl --fail-with-body --silent --show-error --digest \
  --user "rokudev:$ROKU_DEV_PASSWORD" \
  --form 'mysubmit=Install' --form "archive=@$archive" \
  "http://$ROKU_HOST/plugin_install" > "$response"
chmod 600 "$response"
echo "Installer response saved to $response; check it for an on-device compile or install error."
