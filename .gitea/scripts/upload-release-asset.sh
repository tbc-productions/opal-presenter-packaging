#!/usr/bin/env bash
# Upload a single asset to a Gitea release, replacing any existing asset with
# the same filename. Requires CI_TOKEN, RELEASE_REPO, RELEASE_ID, and
# GITHUB_SERVER_URL in the environment.
set -euo pipefail

asset_path="${1:?usage: upload-release-asset.sh <path>}"
asset_name="$(basename "$asset_path")"

: "${CI_TOKEN:?CI_TOKEN is required}"
: "${RELEASE_REPO:?RELEASE_REPO is required}"
: "${RELEASE_ID:?RELEASE_ID is required}"
: "${GITHUB_SERVER_URL:?GITHUB_SERVER_URL is required}"

base="${GITHUB_SERVER_URL}/api/v1/repos/${RELEASE_REPO}/releases/${RELEASE_ID}/assets"

existing_id=$(curl -fsSL \
  -H "Authorization: token ${CI_TOKEN}" \
  "$base" \
  | jq -r --arg name "$asset_name" '.[] | select(.name == $name) | .id' \
  | head -n 1)

if [ -n "$existing_id" ]; then
  echo "Deleting existing asset $asset_name (id=$existing_id)"
  curl -fsSL -X DELETE \
    -H "Authorization: token ${CI_TOKEN}" \
    "$base/$existing_id"
fi

echo "Uploading $asset_path"
curl -fsSL -X POST \
  -H "Authorization: token ${CI_TOKEN}" \
  -H "Content-Type: application/octet-stream" \
  --data-binary "@$asset_path" \
  "$base?name=$asset_name"
