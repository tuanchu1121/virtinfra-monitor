#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
cleanup_test() { rm -rf -- "$TMP"; }
trap cleanup_test EXIT

load_installer_functions() {
  # Load definitions only. Stop before install.sh enters its executable main.
  # shellcheck disable=SC1090
  source <(awk '/^if repo_complete "\$SELF_DIR"/{exit} {print}' "$ROOT/install.sh")
}

create_fixture() {
  local root="$1" style="$2" file
  local required=(
    deploy/postgres/install-postgres-native.sh
    deploy/postgres/update-postgres-native.sh
    deploy/postgres/provision-postgres-native.sh
    app/app.py
    app/runtime_loader.py
    app/runtime_layers/manifest.json
    app/runtime_layers/00_bootstrap_database.py
    app/runtime_layers/43_node_groups_loader.py
    app/runtime_layers/44_consumption_node_vm_rollup.py
    app/runtime_layers/45_consumption_ingest_preaggregation.py
    app/runtime_layers/46_consumption_sort_alignment_hotfix.py
    app/node_groups.py
    app/static/vendor/flag-icons/node-groups.css
    app/static/vendor/flag-icons/LICENSE
    app/static/vendor/flag-icons/SOURCE.md
    app/static/vendor/flag-icons/flags/4x3/vn.svg
    app/static/flags/node-groups.css
    app/static/flags/neutral.svg
    app/static/flags/vn.svg
    app/bw_pg.py
    app/storage_v2.py
    app/maintenance_native.py
    app/configuration_backup.py
    app/emergency_backup.py
    app/maintenance_queue.py
    app/maintenance_dispatch.py
    postgres/docker-compose.yml
    postgres/sql/004_storage_v2.sql
    postgres/sql/006_postgres_native_maintenance.sql
    postgres/sql/007_safe_maintenance_queue.sql
    postgres/sql/011_node_groups.sql
    postgres/sql/012_node_groups_r6_safety.sql
    postgres/sql/013_maintenance_queue_boolean.sql
    postgres/sql/014_node_vm_consumption_rollups.sql
    postgres/sql/015_consumption_ingest_preaggregation.sql
    postgres/sql/016_configuration_backup_nuclear.sql
    tools/validate-consumption-query-plans.py
    tools/benchmark-r22-top-vm.py
    requirements.txt
    VERSION
    CANONICAL_REPOSITORY
    README.md
  )

  mkdir -p "$root"
  printf 'fixture\n' > "$root/.editorconfig"
  for file in "${required[@]}"; do
    mkdir -p "$(dirname -- "$root/$file")"
    printf 'fixture:%s\n' "$file" > "$root/$file"
  done

  (
    cd "$root"
    if [[ "$style" == dot ]]; then
      find . -type f ! -name SHA256SUMS -print0 \
        | sort -z | xargs -0 sha256sum > SHA256SUMS
    else
      find . -type f ! -name SHA256SUMS -print0 \
        | sort -z | xargs -0 sha256sum | sed 's#  \./#  #' > SHA256SUMS
    fi
  )
}

run_stage_test() {
  local source_root="$1" clean_root="$2"
  (
    load_installer_functions
    stage_canonical_tree "$source_root" "$clean_root" >/dev/null
  )
}

SOURCE_PLAIN="$TMP/source-plain"
create_fixture "$SOURCE_PLAIN" plain
run_stage_test "$SOURCE_PLAIN" "$TMP/clean-plain"
[[ -f "$TMP/clean-plain/.editorconfig" ]]
[[ -f "$TMP/clean-plain/app/app.py" ]]
[[ -f "$TMP/clean-plain/app/runtime_loader.py" ]]
[[ -f "$TMP/clean-plain/app/runtime_layers/manifest.json" ]]

SOURCE_DOT="$TMP/source-dot"
create_fixture "$SOURCE_DOT" dot
run_stage_test "$SOURCE_DOT" "$TMP/clean-dot"
[[ -f "$TMP/clean-dot/.editorconfig" ]]
[[ -f "$TMP/clean-dot/app/app.py" ]]
[[ -f "$TMP/clean-dot/app/runtime_loader.py" ]]
[[ -f "$TMP/clean-dot/app/runtime_layers/manifest.json" ]]

# sha256sum is deliberately allowed to resolve this file, but the staging
# validator must reject the traversal path before copying it.
SOURCE_BAD="$TMP/source-bad"
create_fixture "$SOURCE_BAD" plain
printf 'outside\n' > "$TMP/outside"
( cd "$SOURCE_BAD" && sha256sum ../outside >> SHA256SUMS )
if run_stage_test "$SOURCE_BAD" "$TMP/clean-bad" 2>/dev/null; then
  echo 'ERROR: traversal manifest path was accepted' >&2
  exit 1
fi

echo 'PASS: installer accepts safe relative manifest paths and rejects traversal'
