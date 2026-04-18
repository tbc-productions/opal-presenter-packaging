#!/usr/bin/env bash
# Upload a single asset to a Gitea release, replacing any existing asset with
# the same filename. Required env: CI_TOKEN, RELEASE_REPO, RELEASE_ID,
# GITHUB_SERVER_URL. Optional env: ORIGIN_IP - if set, curl will tunnel
# the HTTP connection directly to that address (supports "IP" or
# "IP:PORT") while keeping the configured host/SNI, bypassing any HTTP
# proxy (e.g. Cloudflare body-size limits). TLS verification is disabled
# on the bypass path since the origin cert usually won't match.
set -euo pipefail

asset_path="${1:?usage: upload-release-asset.sh <path>}"
asset_name="$(basename "$asset_path")"

: "${CI_TOKEN:?CI_TOKEN is required}"
: "${RELEASE_REPO:?RELEASE_REPO is required}"
: "${RELEASE_ID:?RELEASE_ID is required}"
: "${GITHUB_SERVER_URL:?GITHUB_SERVER_URL is required}"

bypass_args=()
if [ -n "${ORIGIN_IP:-}" ]; then
  host="${GITHUB_SERVER_URL#*://}"
  host="${host%%/*}"
  case "$GITHUB_SERVER_URL" in
    https://*) url_port=443 ;;
    http://*)  url_port=80 ;;
    *)         url_port=443 ;;
  esac
  if [[ "$ORIGIN_IP" == *:* ]]; then
    origin_ip="${ORIGIN_IP%:*}"
    origin_port="${ORIGIN_IP##*:}"
  else
    origin_ip="$ORIGIN_IP"
    origin_port="$url_port"
  fi
  bypass_args=(--connect-to "${host}:${url_port}:${origin_ip}:${origin_port}" -k)
  echo "Bypassing proxy via ${host}:${url_port} -> ${origin_ip}:${origin_port} (TLS verification disabled)"
fi

base="${GITHUB_SERVER_URL}/api/v1/repos/${RELEASE_REPO}/releases/${RELEASE_ID}/assets"

existing_id=$(curl -fsSL "${bypass_args[@]}" \
  -H "Authorization: token ${CI_TOKEN}" \
  "$base" \
  | jq -r --arg name "$asset_name" '.[] | select(.name == $name) | .id' \
  | head -n 1)

if [ -n "$existing_id" ]; then
  echo "Deleting existing asset $asset_name (id=$existing_id)"
  curl -fsSL "${bypass_args[@]}" -X DELETE \
    -H "Authorization: token ${CI_TOKEN}" \
    "$base/$existing_id"
fi

echo "Uploading $asset_path"
curl -fsSL "${bypass_args[@]}" -X POST \
  -H "Authorization: token ${CI_TOKEN}" \
  -H "Content-Type: application/octet-stream" \
  --data-binary "@$asset_path" \
  "$base?name=$asset_name"
