#!/usr/bin/env bash
# Build the Mini App bundle, generating catalog.json and policies.json first.
# Used by CI and for local builds. Tolerates missing inputs by writing
# empty-but-valid JSON so the bundle step never fails on absent sources.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

db_path="${1:-${MINIAPP_TEST_DB:-tools/fixtures/test.sqlite3}}"
mkdir -p miniapp

# Ensure generated files exist even if exporters fail on missing inputs.
printf '{"products": []}\n' > miniapp/catalog.json
printf '{"policies": []}\n' > miniapp/policies.json

python3 tools/export_catalog.py --db "$db_path" || {
  echo "WARN: export_catalog.py failed; keeping empty catalog" >&2
  printf '{"products": []}\n' > miniapp/catalog.json
}

python3 tools/export_policies.py || {
  echo "WARN: export_policies.py failed; keeping empty policies" >&2
  printf '{"policies": []}\n' > miniapp/policies.json
}

python3 tools/build_miniapp_bundle.py
echo "Mini App bundle built."
