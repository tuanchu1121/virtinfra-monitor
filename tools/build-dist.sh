#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cat "$ROOT/VERSION")"
NAME="virtinfra-monitor-${VERSION}"
DIST="$ROOT/dist"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$DIST" "$TMP/$NAME"

cd "$ROOT"

printf '\n==> Refresh canonical source checksum manifest\n'
find . \
  -path './.git' -prune -o \
  -path './dist' -prune -o \
  -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -o \
  -type f ! -name SHA256SUMS ! -name '*.pyc' ! -name '*.pyo' \
  ! -name '*.zip' ! -name '*.tar.gz' -print0 \
| sort -z | xargs -0 sha256sum > SHA256SUMS
sha256sum -c SHA256SUMS >/dev/null
python3 tests/test_manifest_contract.py

tar \
  --exclude='./.git' \
  --exclude='./dist' \
  --exclude='*/__pycache__' \
  --exclude='*/.pytest_cache' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='*.zip' \
  --exclude='*.tar.gz' \
  -cf - . | tar -xf - -C "$TMP/$NAME"

rm -f "$DIST/$NAME.zip" "$DIST/$NAME.tar.gz" "$DIST/SHA256SUMS"
(
  cd "$TMP"
  tar -czf "$DIST/$NAME.tar.gz" "$NAME"
  if command -v zip >/dev/null 2>&1; then
    zip -qr "$DIST/$NAME.zip" "$NAME"
  else
    python3 - "$NAME" "$DIST/$NAME.zip" <<'PY_ZIP'
import pathlib, sys, zipfile
root=pathlib.Path(sys.argv[1]); out=pathlib.Path(sys.argv[2])
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for p in root.rglob('*'):
        if p.is_file(): z.write(p, p.as_posix())
PY_ZIP
  fi
)
(cd "$DIST" && sha256sum "$NAME.tar.gz" "$NAME.zip" > SHA256SUMS)
ls -lh "$DIST/$NAME.tar.gz" "$DIST/$NAME.zip" "$DIST/SHA256SUMS"
