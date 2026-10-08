#!/usr/bin/env bash
# Build the Mini App bundle, generating catalog.json and policies.json first.
# Used by CI and for local builds.
#
# By default, tolerates missing inputs by writing empty-but-valid JSON so the
# bundle step never fails on absent sources (fixture/dev mode).
#
# Set MINIAPP_FAIL_CLOSED=1 for production builds: any exporter failure aborts
# the build instead of silently shipping an empty catalog (audit 17).
set -euo pipefail

fail_closed="${MINIAPP_FAIL_CLOSED:-0}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

db_path="${1:-${MINIAPP_TEST_DB:-tools/fixtures/test.sqlite3}}"
mkdir -p miniapp

# Ensure generated files exist even if exporters fail on missing inputs.
printf '{"products": []}\n' > miniapp/catalog.json
printf '{"policies": []}\n' > miniapp/policies.json

if ! python3 tools/export_catalog.py --db "$db_path"; then
  if [ "$fail_closed" = "1" ]; then
    echo "ERROR: export_catalog.py failed (fail-closed mode)" >&2
    exit 1
  fi
  echo "WARN: export_catalog.py failed; keeping empty catalog" >&2
  printf '{"products": []}\n' > miniapp/catalog.json
fi

if ! python3 tools/export_policies.py; then
  if [ "$fail_closed" = "1" ]; then
    echo "ERROR: export_policies.py failed (fail-closed mode)" >&2
    exit 1
  fi
  echo "WARN: export_policies.py failed; keeping empty policies" >&2
  printf '{"policies": []}\n' > miniapp/policies.json
fi

python3 tools/build_miniapp_bundle.py
echo "Mini App bundle built."
