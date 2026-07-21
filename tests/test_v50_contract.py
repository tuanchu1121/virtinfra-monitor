#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def need(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)

version = (ROOT / "VERSION").read_text().strip()
need(version == "50.5.9-prod-r22.8-vm-consumption-exact-window-sort-alignment", f"unexpected VERSION: {version}")

from runtime_source import read_app_source
app = read_app_source()
pg = (ROOT / "app/bw_pg.py").read_text()
agent = (ROOT / "deploy/agent/agent.py").read_text()
playbook = (ROOT / "ansible/deploy-agent.yml").read_text()
installer = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text()
compose = (ROOT / "postgres/docker-compose.yml").read_text()
timescale = (ROOT / "postgres/sql/002_timescale.sql").read_text()
indexes = (ROOT / "postgres/sql/003_native_indexes.sql").read_text()
storage_sql = (ROOT / "postgres/sql/004_storage_v2.sql").read_text()
storage_py = (ROOT / "app/storage_v2.py").read_text()

# Exact cadence and retention from the supplied production code.
need("CACHE_BUCKET_SECONDS = 300" in app, "monitor cadence is not 300 seconds")
need("local 15-second network peak summaries, still one push per 5 minutes" in app.lower(), "original 15s/5m marker missing")
need("RAW_RETENTION_DAYS = min(2" in app, "2-day raw retention missing")
need("HOURLY_RETENTION_DAYS = min(7" in app, "7-day hourly retention missing")
need("SAMPLE_SECONDS = max(5, int(os.environ.get(\"VIRTINFRA_AGENT_SAMPLE_SECONDS\") or os.environ.get(\"BW_AGENT_SAMPLE_SECONDS\", \"15\")))" in agent, "Agent 15-second sampler default missing")
need("PUSH_SECONDS = max(60, int(os.environ.get(\"VIRTINFRA_AGENT_PUSH_SECONDS\") or os.environ.get(\"BW_AGENT_PUSH_SECONDS\", \"300\")))" in agent, "Agent 300-second push default missing")
need("bwagent_sample_seconds: 15" in playbook and "bwagent_push_seconds: 300" in playbook, "Ansible cadence defaults missing")

# PostgreSQL/TimescaleDB is the only runtime data store.
need("import sqlite3" not in "\n".join(p.read_text(errors="ignore") for p in (ROOT / "app").glob("*.py")), "runtime imports sqlite3")
runtime_py = "\n".join(p.read_text(errors="ignore") for base in (ROOT / "app", ROOT / "deploy") for p in base.rglob("*.py"))
need("sqlite3.connect" not in runtime_py, "sqlite3.connect remains in runtime Python source")
need("psycopg_pool" in pg and "ConnectionPool" in pg, "psycopg connection pool missing")
need("CREATE EXTENSION IF NOT EXISTS timescaledb" in timescale, "TimescaleDB extension setup missing")
need("create_hypertable" in timescale and "set_integer_now_func" in timescale, "Timescale hypertable setup missing")
need("127.0.0.1:${BW_PG_PORT:-55432}:5432" in compose, "PostgreSQL is not loopback-only")
need("timescale/timescaledb:2.27.2-pg17" in compose, "pinned TimescaleDB Community image missing")
need("2.27.2-pg17-oss" not in compose, "Apache-only TimescaleDB image cannot satisfy Storage V2 policies")
need("current_setting('timescaledb.license', TRUE)" in storage_sql, "Storage V2 Community capability guard missing")
need("add_retention_policy" in installer and "add_compression_policy" in installer, "installer policy capability checks missing")
need("BW_REDIS_ENABLED='$REDIS_CACHE'" in installer, "optional Redis flag missing")
need("REDIS_CACHE=0" in installer, "Redis must be disabled by default")
need("VirtInfra Monitor fresh installer" in installer, "fresh installer contract missing")
need("Fresh mode refuses to overwrite an existing VirtInfra Monitor installation" in installer, "fresh overwrite guard missing")
need("update.sh requires an existing VirtInfra Monitor installation" in installer, "explicit update contract missing")


# v50.4.2 Consumption authentication hotfix with exact 5-minute chart storage and short raw detail.
need("vm_chart_5m" in storage_sql and "vm_raw_detail_5m" in storage_sql and "node_chart_5m" in storage_sql, "storage V2 tables missing")
need("chunk_time_interval => 10800::bigint" in storage_sql, "3-hour VM chart/raw chunk interval missing")
need("drop_after => 604800::bigint" in storage_sql, "7-day chart retention missing")
need("drop_after => 172800::bigint" in storage_sql, "48-hour raw retention missing")
need("add_compression_policy" in storage_sql, "chart compression policy missing")
need("VIRTINFRA_READ_CHART_V2='0'" in installer, "chart V2 read flag missing from installer")
need("VIRTINFRA_RAW_V2='0'" in installer, "raw V2 flag missing from installer")
need("import storage_v2" in app and "storage_v2.write_storage_v2" in app, "storage V2 is not connected to /push")
need("_v5040_query_vm_chart_legacy" in app and "def _v5040_iface_values" in app, "backward-compatible chart fallback/filter missing")
need("conn.executemany" in storage_py, "storage V2 batch writer missing")
need("interfaces_json" in storage_py, "7-day bridge/interface chart compatibility missing")
need("return min(gaps) if gaps else CACHE_BUCKET_SECONDS" in app, "V2 chart fallback resolution must remain 5 minutes")

# Full old UI, storage and abuse behavior must remain in the package.
markers = [
    '@app.route("/push", methods=["POST"])',
    'def top_page',
    'def vm_abuse_page',
    'def storage_io_page',
    'def vm_page',
    'def purge_vm_data',
    '_v48133_disk_sort_link("SLOTS", "diskcount"',
    'storage-vm-identity',
    'storage-top-card',
    'vm_disk_current',
    'node_storage_current',
    'vm_abuse_events',
    'vm_abuse_incidents',
    'api_v1_performance',
]
for marker in markers:
    need(marker in app, f"full application marker missing: {marker}")
need(len(app.splitlines()) > 25000, "full legacy UI/business logic was not preserved")

# PostgreSQL resolves GROUP BY role to the input np.role column in this query,
# leaving np.bridge ungrouped. Group by the normalized SELECT expression via
# output position instead.
need("GROUP BY np.node, role" not in app, "PostgreSQL-incompatible physical NIC role grouping remains")
need("GROUP BY np.node, 2" in app, "PostgreSQL physical NIC role grouping fix missing")
# abuse_policy_versions is keyed by revision, not id. It must never enter the
# generated-id compatibility list or psycopg will append an invalid RETURNING id.
serial_block = pg.split("_SERIAL_TABLES = {", 1)[1].split("}", 1)[0]
need('"abuse_policy_versions"' not in serial_block, "revision-keyed abuse_policy_versions incorrectly treated as id-serial")
need('BEGIN(?:\\s+IMMEDIATE)?' in pg, "legacy BEGIN compatibility no-op missing")
need("ProtectHome=read-only" in (ROOT / "deploy/agent/install-agent.sh").read_text(), "Agent service must see /home")
need("become: \"{{ (ansible_user | default('root')) != 'root' }}\"" in playbook, "root Ansible nodes should not require sudo")

# Product deployment and operations.
for path in [
    "install.sh", "update.sh", "uninstall.sh",
    "deploy/postgres/bw-monitorctl.sh", "deploy/postgres/backup.sh",
    "deploy/postgres/restore.sh", "deploy/postgres/doctor.sh",
    "deploy/postgres/bw-monitor-retention.timer", "postgres/docker-compose.yml",
]:
    need((ROOT / path).exists(), f"missing product file: {path}")
need("--domain" in installer and "certbot --nginx" in installer, "domain/Let's Encrypt installer path missing")
need("--public-ip" in installer and "--ip-mode" in installer, "IP installer/switch mode missing")
need("pg_dump" in (ROOT / "deploy/postgres/backup.sh").read_text(), "PostgreSQL backup missing")
need("pg_restore" in (ROOT / "deploy/postgres/restore.sh").read_text(), "PostgreSQL restore missing")
need("USING brin" in indexes, "compact history BRIN indexes missing")

need("VirtInfra Monitor" in app, "public product identity missing")
need('TZ_NAME = "Asia/Ho_Chi_Minh"' in app, "fixed Ho Chi Minh timezone missing")
need('DISPLAY_TIMEZONES' not in app and '@app.route("/admin/display-timezone"' not in app, "runtime timezone switch still present")
need('period_seconds(period) - CACHE_BUCKET_SECONDS' in app, "original 5m-slot snapshot selector missing")
need('offset = max(0, period_seconds(period) - CACHE_BUCKET_SECONDS)' in app, "Dashboard does not use original snapshot-slot semantics")
need('selected_display = max(selected_buckets) if selected_buckets else requested' in app, "Dashboard Selected Snapshot does not show the retained bucket actually used")
need('<div class="label">Selected Snapshot</div><div class="value">{fmt_full(start)}</div>' in app, "Dashboard Selected Snapshot label missing")
need('period_seconds(clean_period(values.get("period") or "5m")) - CACHE_BUCKET_SECONDS' in app, "Storage does not use original slot semantics")
need('@app.route("/livez")' in app and '@app.route("/healthz")' in app, "health endpoints missing")
need("pg_advisory_xact_lock" in app, "per-node PostgreSQL push lock missing")
need("WAL reserved/recycled" in app and "SHM {human" not in app, "PostgreSQL size semantics not fixed")
need("virtinfra-v502-final-ui" in app and "min-width:0!important" in app, "responsive Abuse override missing")
need("page_cache_generation" in app, "cross-worker cache generation missing")
agent_install = (ROOT / "deploy/agent/install-agent.sh").read_text(encoding="utf-8")
need("VirtInfra Agent v15" in agent and "VirtInfra-Agent/15" in agent, "VirtInfra Agent identity missing")
need("virtinfra-agent.service" in agent_install and "/var/lib/virtinfra-agent" in agent_install, "canonical Agent service/path missing")
need((ROOT / "deploy/postgres/virtinfra-monitor-health-watch.timer").exists(), "health watchdog timer missing")

# v50.3.1 compact Consumption route fix; accounting remains additive and node-level only.
need("<a href=\"{url_for('bandwidth_consumption_page')}\">Consumption</a>" in app, "Consumption nav item missing")
need(app.index('bandwidth_consumption_page') > app.index('storage_io_page'), "Consumption must be after Storage I/O")
need(".bwcons-toolbar input{min-width:100%%}" in app, "Consumption route CSS percent must be escaped inside old-style formatting")
need(".bwcons-toolbar input{min-width:100%}.bwcons-groups" not in app, "raw CSS percent would crash the Consumption route at render time")
need('@app.route("/push/bandwidth-consumption", methods=["POST"])' in app, "compact bandwidth endpoint missing")
need('node_bandwidth_consumption_2h' in app, "compact bandwidth table missing")
need('V5030_BW_RETENTION_SECONDS = 7 * 86400' in app, "7-day bandwidth retention missing")
need('physical_public_rx_bytes' in app and 'physical_private_rx_bytes' in app, "physical Public/Private counters missing")
need('vm_public_rx_bytes' in app and 'vm_private_rx_bytes' in app, "aggregate VM Public/Private counters missing")
need('No per-VM UUID history is stored' in app, "node-only accounting contract missing")
need('BANDWIDTH_CONSUMPTION_BUCKET_SECONDS' not in agent, "Agent still contains local 2-hour accounting")
need('/push/bandwidth-consumption' not in agent, "Agent still sends a separate Consumption payload")
need('data.pop("bandwidth_consumption", None)' in agent, "Agent upgrade does not discard obsolete 2-hour state")
need('node_consumption_hourly' in app and 'node_consumption_daily' in app, "server-side physical Consumption rollups missing")
need('COUNT(*) OVER()' in app, "Consumption table count is not combined with the page query")
need('@app.route("/bandwidth-consumption/node/<path:node>")' in app, "Bandwidth Consumption node detail missing")
need('V48102_RESET_APP_TABLES = tuple(dict.fromkeys(tuple(V48102_RESET_APP_TABLES) + (V5030_BW_TABLE,)))' in app, "Reset ALL does not include bandwidth table")
need('bandwidth_consumption_accept_after' in app, "reset epoch protection missing")
need('CASE WHEN bridge=? THEN host_tx' in app and 'CASE WHEN bridge=? THEN host_rx' in app, "VM guest RX/TX normalization missing")
need('run_inventory_cleanup_batches' in app and 'FOR UPDATE SKIP LOCKED' in app, "deadlock-safe inventory cleanup missing")

print("PASS: v50 static product contract")
