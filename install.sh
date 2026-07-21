#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${BW_GITHUB_REPO:-tuanchu1121/virtinfra-monitor}"
REF="${BW_GITHUB_REF:-main}"
TOKEN="${GITHUB_TOKEN:-}"
ACTION="${BW_BOOTSTRAP_ACTION:-install}"
SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$PWD}")" 2>/dev/null && pwd || true)"
TMP_ROOT=""

case "$ACTION" in install|update) ;; *) echo "Unsupported BW_BOOTSTRAP_ACTION: $ACTION" >&2; exit 2;; esac

cleanup() {
  [[ -z "$TMP_ROOT" ]] || rm -rf -- "$TMP_ROOT"
}
trap cleanup EXIT

repo_complete() {
  local root="$1" path
  local missing=()
  for path in \
    deploy/postgres/install-postgres-native.sh \
    deploy/postgres/update-postgres-native.sh \
    deploy/postgres/provision-postgres-native.sh \
    app/app.py \
    app/runtime_loader.py \
    app/runtime_layers/manifest.json \
    app/runtime_layers/00_bootstrap_database.py \
    app/runtime_layers/43_node_groups_loader.py \
    app/node_groups.py \
    app/static/vendor/flag-icons/node-groups.css \
    app/static/vendor/flag-icons/LICENSE \
    app/static/vendor/flag-icons/SOURCE.md \
    app/static/vendor/flag-icons/flags/4x3/vn.svg \
    app/static/flags/node-groups.css \
    app/static/flags/neutral.svg \
    app/static/flags/vn.svg \
    app/bw_pg.py \
    app/storage_v2.py \
    app/maintenance_native.py \
    app/maintenance_queue.py \
    app/maintenance_dispatch.py \
    postgres/docker-compose.yml \
    postgres/sql/004_storage_v2.sql \
    postgres/sql/006_postgres_native_maintenance.sql \
    postgres/sql/007_safe_maintenance_queue.sql \
    postgres/sql/011_node_groups.sql \
    postgres/sql/012_node_groups_r6_safety.sql \
    postgres/sql/013_maintenance_queue_boolean.sql \
    postgres/sql/014_node_vm_consumption_rollups.sql \
    postgres/sql/015_consumption_ingest_preaggregation.sql \
    requirements.txt \
    VERSION \
    CANONICAL_REPOSITORY \
    SHA256SUMS
  do
    [[ -f "$root/$path" ]] || missing+=("$path")
  done
  if ((${#missing[@]})); then
    printf 'Downloaded repository is incomplete. Missing:\n' >&2
    printf '  - %s\n' "${missing[@]}" >&2
    printf 'Push the complete v50 release to: %s@%s\n' "$REPO" "$REF" >&2
    return 1
  fi
}

normalize_shell_modes() {
  local root="$1"
  # GitHub Desktop on Windows may publish shell files as 0644. Runtime calls
  # scripts through bash, then normalizes permissions in the staged copy.
  find "$root" -type f -name '*.sh' -exec chmod 0755 {} + 2>/dev/null || true
}

stage_canonical_tree() {
  local source_root="$1" clean_root="$2"
  local checksum listed rel source_file target_file

  repo_complete "$source_root"

  printf '\n==> Verify canonical v50 source manifest\n'
  (
    cd "$source_root"
    sha256sum -c SHA256SUMS >/dev/null
  ) || {
    printf 'ERROR: SHA256SUMS verification failed. Re-copy the complete release to GitHub.\n' >&2
    return 1
  }

  mkdir -p "$clean_root"

  # Only files listed in the signed release manifest are staged. This makes
  # one-command installs safe even when Windows Explorer/GitHub Desktop left
  # unlisted stale directories in the repository.
  while read -r checksum listed; do
    [[ "$checksum" =~ ^[0-9a-fA-F]{64}$ ]] || {
      printf 'ERROR: Invalid checksum entry: %s %s\n' "$checksum" "$listed" >&2
      return 1
    }

    listed="${listed#\*}"
    case "$listed" in
      ./*) rel="${listed#./}" ;;
      /*|'')
        printf 'ERROR: Unsafe manifest path: %s\n' "$listed" >&2
        return 1
        ;;
      *) rel="$listed" ;;
    esac

    case "$rel" in
      ''|.|..|../*|*/../*|*/..|./*|*/./*|*/.|*'//'* )
        printf 'ERROR: Unsafe manifest path: %s\n' "$listed" >&2
        return 1
        ;;
    esac

    source_file="$source_root/$rel"
    target_file="$clean_root/$rel"
    [[ -f "$source_file" ]] || {
      printf 'ERROR: Manifest file is missing: %s\n' "$rel" >&2
      return 1
    }

    mkdir -p "$(dirname -- "$target_file")"
    cp -a -- "$source_file" "$target_file"
  done < "$source_root/SHA256SUMS"

  cp -a -- "$source_root/SHA256SUMS" "$clean_root/SHA256SUMS"
  normalize_shell_modes "$clean_root"
  repo_complete "$clean_root"

  printf 'Canonical source staged. Unlisted files are ignored.\n'
}

run_from_source() {
  local source_root="$1"
  shift

  TMP_ROOT="$(mktemp -d)"
  local clean_root="$TMP_ROOT/canonical"
  stage_canonical_tree "$source_root" "$clean_root"

  export BW_GITHUB_REPO="$REPO" BW_GITHUB_REF="$REF"
  case "$ACTION" in
    install) bash "$clean_root/deploy/postgres/install-postgres-native.sh" "$@" ;;
    update) bash "$clean_root/deploy/postgres/update-postgres-native.sh" "$@" ;;
    *) printf 'ERROR: Unsupported bootstrap action: %s\n' "$ACTION" >&2; return 2 ;;
  esac
}

if repo_complete "$SELF_DIR" >/dev/null 2>&1; then
  run_from_source "$SELF_DIR" "$@"
  exit $?
fi

command -v curl >/dev/null 2>&1 || { echo 'curl is required' >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { echo 'tar is required' >&2; exit 1; }
TMP_ROOT="$(mktemp -d)"

if [[ -n "$TOKEN" ]]; then
  curl -fL --retry 4 --retry-delay 2 --connect-timeout 20 \
    -H "Authorization: Bearer $TOKEN" \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "https://api.github.com/repos/$REPO/tarball/$REF" \
    -o "$TMP_ROOT/repo.tar.gz"
else
  curl -fL --retry 4 --retry-delay 2 --connect-timeout 20 \
    "https://codeload.github.com/$REPO/tar.gz/$REF" \
    -o "$TMP_ROOT/repo.tar.gz"
fi

tar -xzf "$TMP_ROOT/repo.tar.gz" -C "$TMP_ROOT"
RAW_ROOT="$(find "$TMP_ROOT" -mindepth 1 -maxdepth 1 -type d | head -n1)"
[[ -n "$RAW_ROOT" && -d "$RAW_ROOT" ]] || {
  echo 'Downloaded repository archive could not be extracted.' >&2
  exit 1
}

# Use a separate subdirectory because RAW_ROOT may contain stale tracked files
# left by a previous release. The manifest defines the only runtime source.
CLEAN_ROOT="$TMP_ROOT/canonical"
stage_canonical_tree "$RAW_ROOT" "$CLEAN_ROOT"
export BW_GITHUB_REPO="$REPO" BW_GITHUB_REF="$REF"
case "$ACTION" in
  install) bash "$CLEAN_ROOT/deploy/postgres/install-postgres-native.sh" "$@" ;;
  update) bash "$CLEAN_ROOT/deploy/postgres/update-postgres-native.sh" "$@" ;;
  *) echo "Unsupported bootstrap action: $ACTION" >&2; exit 2 ;;
esac
