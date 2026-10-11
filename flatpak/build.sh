#!/bin/bash

set -euo pipefail

# Use the same dependency, native binding and startup checks as the release workflow.
cd "$(dirname "$0")/.."
exec python3 builders/flatpak-builder.py "$@"
