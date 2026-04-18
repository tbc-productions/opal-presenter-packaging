#!/usr/bin/env bash
# Upload a single asset to a Gitea release, replacing any existing asset with
# the same filename. Required env: CI_TOKEN, RELEASE_REPO, RELEASE_ID,
# GITHUB_SERVER_URL. Optional env: GITEA_ORIGIN_IP - if set, curl will be
# forced to connect to that IP while presenting the original Host/SNI,
# bypassing any HTTP proxy (e.g. Cloudflare body-size limits) in front of
# Gitea. The origin must still serve TLS for the Gitea hostname.
set -euo pipefail

asset_path="${1:?usage: upload-release-asset.sh <path>}"
asset_name="$(basename "$asset_path")"

: "${CI_TOKEN:?CI_TOKEN is required}"
: "${RELEASE_REPO:?RELEASE_REPO is required}"
: "${RELEASE_ID:?RELEASE_ID is required}"
: "${GITHUB_SERVER_URL:?GITHUB_SERVER_URL is required}"

resolve_args=()
if [ -n "${GITEA_ORIGIN_IP:-}" ]; then
  host="${GITHUB_SERVER_URL#*://}"
  host="${host%%/*}"
  case "$GITHUB_SERVER_URL" in
    https://*) port=443 ;;
    http://*)  port=80 ;;
    *)         port=443 ;;
  esac
  resolve_args=(--resolve "${host}:${port}:${GITEA_ORIGIN_IP}")
  echo "Bypassing proxy via --resolve ${host}:${port}:${GITEA_ORIGIN_IP}"
fi

base="${GITHUB_SERVER_URL}/api/v1/repos/${RELEASE_REPO}/releases/${RELEASE_ID}/assets"

existing_id=$(curl -fsSL "${resolve_args[@]}" \
  -H "Authorization: token ${CI_TOKEN}" \
  "$base" \
  | jq -r --arg name "$asset_name" '.[] | select(.name == $name) | .id' \
  | head -n 1)

if [ -n "$existing_id" ]; then
  echo "Deleting existing asset $asset_name (id=$existing_id)"
  curl -fsSL "${resolve_args[@]}" -X DELETE \
    -H "Authorization: token ${CI_TOKEN}" \
    "$base/$existing_id"
fi

echo "Uploading $asset_path"
curl -fsSL "${resolve_args[@]}" -X POST \
  -H "Authorization: token ${CI_TOKEN}" \
  -H "Content-Type: application/octet-stream" \
  --data-binary "@$asset_path" \
  "$base?name=$asset_name"
