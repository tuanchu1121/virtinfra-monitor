#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
COPY="$TMP/repo"
mkdir -p "$COPY"

tar --exclude='./.git' --exclude='./dist' --exclude='*/__pycache__' --exclude='*/.pytest_cache' \
  -C "$ROOT" -cf - . | tar -C "$COPY" -xf -
find "$COPY" -type f -name '*.sh' -exec chmod 0644 {} +

# Simulate an Explorer copy over an old repository: stale trees and docs are
# present, but are intentionally absent from the v50 SHA256SUMS manifest.
mkdir -p "$COPY/release" "$COPY/enterprise" "$COPY/deploy/monitor" "$COPY/deploy/enterprise"
printf 'legacy sqlite runtime\n' > "$COPY/release/app.py"
printf 'SQLite WAL bandwidth.db\n' > "$COPY/docs/OLD_V48_STALE.md"

[[ ! -x "$COPY/install.sh" ]] || { echo 'Simulation failed to remove executable mode.' >&2; exit 1; }
# One canonical bootstrap run is sufficient to validate Windows-lost execute
# bits. The two legacy aliases are static wrappers around the same installer;
# executing all three would stage the complete manifest three times.
bash "$COPY/install.sh" --help >/dev/null
grep -Fq 'exec bash "$DIR/install.sh" "$@"' "$COPY/install-enterprise.sh"
grep -Fq 'exec bash "$DIR/install.sh" "$@"' "$COPY/install-core.sh"
bash "$COPY/install-agent.sh" --help >/dev/null
bash "$COPY/uninstall-agent.sh" --help >/dev/null
bash "$COPY/preflight.sh" --help >/dev/null

grep -Fq 'stage_canonical_tree "$RAW_ROOT" "$CLEAN_ROOT"' "$COPY/install.sh"
grep -Fq 'sha256sum -c SHA256SUMS' "$COPY/install.sh"
grep -Fq 'Extra legacy files are ignored.' "$COPY/install.sh"

echo 'PASS: Windows GitHub Desktop mode and stale merged-tree compatibility'
