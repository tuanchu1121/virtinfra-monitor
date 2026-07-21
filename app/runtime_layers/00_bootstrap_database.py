from flask import Flask, request, jsonify, Response, url_for, redirect, session
import os
import secrets
import bw_pg as dbapi
import storage_v2
import maintenance_native
import maintenance_queue
import time
import math
import shutil
import platform
import json
import gzip
import io
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

# compressed request body; a separate post-decompression limit prevents gzip
# expansion from consuming unbounded memory. Plain JSON agents remain valid.
MAX_COMPRESSED_PUSH_BYTES = max(1024 * 1024, int(os.environ.get("BW_MAX_COMPRESSED_PUSH_BYTES", str(16 * 1024 * 1024))))
MAX_UNCOMPRESSED_PUSH_BYTES = max(MAX_COMPRESSED_PUSH_BYTES, int(os.environ.get("BW_MAX_UNCOMPRESSED_PUSH_BYTES", str(64 * 1024 * 1024))))
app.config["MAX_CONTENT_LENGTH"] = MAX_COMPRESSED_PUSH_BYTES

# v48.6.2: VM Abuse page, fixed node VM perf join, aligned tables, queued purge batches
# v48.8.4: AVG Mbps abuse, custom snapshot across metric pages, physical-NIC SRC fix
# v48.8.3: admin-only abuse deletion, richer policy controls, cleaner serialized queue UI
# v48.10.2: one-column dual CPU sort, 5s partial refresh, abuse R/W sort, minute labels, full operational reset
# v48.10.4: compact guest-aware VM RAM rows with a collapsed four-mode sort menu
# v48.10.6: contrast polish, balanced VM tables, CPU meters, dedicated login layout
# v48.7.0: Fast current cache + sustained directional abuse
# v48.6.0: Local 15-second network peak summaries, still one push per 5 minutes
# v48.5.2: Fast Node Health query; no history backfill inside web requests

# v48.4.7: unified node/IP/UUID/interface search across dashboard pages
# 50.5.7-prod-r2: retain VM/uplink MAC identity, search by MAC, show MAC on VM/Node detail

TOKEN = str(os.environ.get("BW_MONITOR_TOKEN") or "").strip()
DB = os.environ.get("BW_MONITOR_DB", "/var/lib/bw-monitor/postgresql")
DATABASE_URL = os.environ.get("BW_DATABASE_URL") or os.environ.get("BW_POSTGRES_DSN", "")

# Bootstrap defaults. Real dashboard/admin users are stored in PostgreSQL.
ADMIN_USERNAME = os.environ.get("BW_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.environ.get("BW_ADMIN_PASSWORD_HASH", "")

def get_or_create_app_secret():
    """Return one stable Flask secret shared by all Gunicorn workers.

    Why the database instead of a random module-level value:
    - gunicorn -w 2 starts multiple Python processes.
    - a random per-process secret makes sessions/CSRF fail randomly.
    - storing the secret in PostgreSQL makes it stable after deploy/restart.

    BW_ADMIN_SECRET_KEY is still accepted as a bootstrap value. If the DB already
    has app_secret_key, the DB value wins so multiple workers stay consistent.
    """
    db_dir = os.path.dirname(DB)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    env_secret = (os.environ.get("BW_ADMIN_SECRET_KEY") or "").strip()
    conn = dbapi.connect(DB, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        row = conn.execute("SELECT value FROM admin_settings WHERE key='app_secret_key'").fetchone()
        if row and row[0]:
            return row[0]

        secret = env_secret or secrets.token_urlsafe(64)
        conn.execute("""
            INSERT OR REPLACE INTO admin_settings(key, value, updated_at)
            VALUES ('app_secret_key', ?, ?)
        """, (secret, int(time.time())))
        conn.commit()
        return secret
    finally:
        conn.close()

app.secret_key = get_or_create_app_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("BW_ADMIN_COOKIE_SECURE", "0") == "1",
)

TZ_NAME = "Asia/Ho_Chi_Minh"
TZ = ZoneInfo(TZ_NAME)
PRODUCT_NAME = "VirtInfra Monitor"

PUBLIC_BRIDGE = "br0"
PRIVATE_BRIDGE = "br1"
NODE_DISK_READ_REF_BPS = float(os.environ.get("BW_NODE_DISK_READ_REF_BPS", str(1024 * 1024 * 1024)))
NODE_DISK_WRITE_REF_BPS = float(os.environ.get("BW_NODE_DISK_WRITE_REF_BPS", str(1024 * 1024 * 1024)))
VM_NET_WARN_PPS = float(os.environ.get("BW_VM_NET_WARN_PPS", "100000"))
VM_NET_CRIT_PPS = float(os.environ.get("BW_VM_NET_CRIT_PPS", "300000"))
VM_NET_WARN_MBPS = float(os.environ.get("BW_VM_NET_WARN_MBPS", "800"))
VM_NET_CRIT_MBPS = float(os.environ.get("BW_VM_NET_CRIT_MBPS", "950"))
ABUSE_CPU_FULL_PERCENT = float(os.environ.get("BW_ABUSE_CPU_FULL_PERCENT", "90"))
ABUSE_RAM_RSS_PERCENT = float(os.environ.get("BW_ABUSE_RAM_RSS_PERCENT", "90"))
ABUSE_AVG_PPS = float(os.environ.get("BW_ABUSE_AVG_PPS", str(VM_NET_WARN_PPS)))
ABUSE_PEAK_PPS = float(os.environ.get("BW_ABUSE_PEAK_PPS", str(VM_NET_CRIT_PPS)))
ABUSE_AVG_MBPS = float(os.environ.get("BW_ABUSE_AVG_MBPS", str(VM_NET_WARN_MBPS)))
ABUSE_PEAK_MBPS = float(os.environ.get("BW_ABUSE_PEAK_MBPS", str(VM_NET_CRIT_MBPS)))
ABUSE_NETWORK_PPS = float(os.environ.get("BW_ABUSE_NETWORK_PPS", "200000"))
ABUSE_NETWORK_REQUIRED_SECONDS = int(os.environ.get("BW_ABUSE_NETWORK_REQUIRED_SECONDS", "270"))
ABUSE_CPU_REQUIRED_SECONDS = int(os.environ.get("BW_ABUSE_CPU_REQUIRED_SECONDS", "1800"))
ABUSE_DISK_BPS = float(os.environ.get("BW_ABUSE_DISK_BPS", str(200 * 1024 * 1024)))
ABUSE_DISK_IOPS = float(os.environ.get("BW_ABUSE_DISK_IOPS", "5000"))
ABUSE_DISK_REQUIRED_SECONDS = int(os.environ.get("BW_ABUSE_DISK_REQUIRED_SECONDS", "900"))
FAST_CURRENT_STALE_SECONDS = int(os.environ.get("BW_FAST_CURRENT_STALE_SECONDS", "900"))
MAX_PURGE_ITEMS_PER_JOB = max(1, min(10, int(os.environ.get("BW_MAX_PURGE_ITEMS_PER_JOB", "3"))))
MAX_ACTIVE_MAINTENANCE_JOBS = 1  # v48.12.4: exactly one exclusive maintenance job
CACHE_BUCKET_SECONDS = 300  # 5 minutes
# Node status is based on missed 5-minute pushes, not arbitrary wall-clock labels.
# 0-1 missed pushes: Online; exactly 2 missed pushes: Missed; more than 2: Down.
STATUS_PUSH_SECONDS = max(60, int(os.environ.get("BW_STATUS_PUSH_SECONDS", str(CACHE_BUCKET_SECONDS))))
STATUS_WARNING_MISSES = max(1, int(os.environ.get("BW_STATUS_WARNING_MISSES", "2")))
STALE_GREEN_SECONDS = STATUS_PUSH_SECONDS * STATUS_WARNING_MISSES
STALE_YELLOW_SECONDS = STATUS_PUSH_SECONDS * (STATUS_WARNING_MISSES + 1)

VM_STALE_SECONDS = 3 * 86400
VM_AUTO_DELETE_SECONDS = 15 * 86400
NODE_AUTO_DELETE_SECONDS = 7 * 86400
# VM migration/state controls. A VM is not marked migrated immediately just because
# the UUID appears on another node. The old node must first miss it for a few
# pushes, which avoids false positives during short live-migration overlap or
# temporary collection gaps.
VM_MIGRATION_CONFIRM_PUSHES = max(1, int(os.environ.get("BW_VM_MIGRATION_CONFIRM_PUSHES", "3")))
VM_MIGRATION_CONFIRM_SECONDS = max(CACHE_BUCKET_SECONDS, int(os.environ.get("BW_VM_MIGRATION_CONFIRM_SECONDS", str(3 * CACHE_BUCKET_SECONDS))))
VM_MIGRATION_PURGE_SECONDS = max(3600, int(os.environ.get("BW_VM_MIGRATION_PURGE_SECONDS", str(4 * 86400))))
# Raw usage history is normally billing/history data, so migrated VM purge only
# removes dashboard/cache rows by default. Set to 1 only if you really want to
# delete raw usage rows for the old node too.
VM_MIGRATION_PURGE_RAW_HISTORY = os.environ.get("BW_VM_MIGRATION_PURGE_RAW_HISTORY", "0") == "1"
NODE_AUTO_DELETE_SECONDS = 7 * 86400
# Avoid scanning large historical usage table on process startup.
# Enable manually only for one-time maintenance if you really need full historical backfill.
BACKFILL_CACHE_ON_START = os.environ.get("BW_BACKFILL_CACHE_ON_START", "0") == "1"
BACKFILL_INVENTORY_ON_START = os.environ.get("BW_BACKFILL_INVENTORY_ON_START", "0") == "1"

# Bounded 7-day tiered history retention.
# - latest 48 hours: keep every real 5-minute agent push
# - 48 hours to 7 days: keep one real push per local hour
# - older than 7 days: delete history/log/event rows
# The hard upper clamps intentionally override stale 7/30-day environment values
# left by older releases, so upgrading is deterministic.
RAW_RETENTION_DAYS = min(2, max(1, int(os.environ.get("BW_RAW_RETENTION_DAYS", "2"))))
HOURLY_RETENTION_DAYS = min(7, max(RAW_RETENTION_DAYS + 1, int(os.environ.get("BW_HOURLY_RETENTION_DAYS", "7"))))
HISTORY_RETENTION_DAYS = 7
EVENT_RETENTION_DAYS = 7
RETENTION_BATCH_ROWS = max(1000, int(os.environ.get("BW_RETENTION_BATCH_ROWS", "25000")))
WRITE_LEGACY_USAGE = os.environ.get("BW_WRITE_LEGACY_USAGE", "0") == "1"
# Vietnam has no DST. This offset makes hourly/daily buckets line up with the
# dashboard timezone instead of UTC.
RETENTION_TZ_OFFSET_SECONDS = int(os.environ.get("BW_RETENTION_TZ_OFFSET_SECONDS", "25200"))

PERIODS = {
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "6h": 21600,
    "12h": 43200,
    "24h": 86400,
    "2d": 2 * 86400,
    "7d": 604800,
}

# Keep old links/bookmarks working, but clamp every legacy long-range link
# to the supported 7-day window.
PERIOD_ALIASES = {
    "30d": "7d",
    "48h": "2d",
    "60d": "7d",
    "6mo": "7d",
    "1mo": "7d",
}

PERIOD_LABELS = {
    "2d": "2d",
    "7d": "7d",
}

def table_columns(conn, table):
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()

def ensure_column(conn, table, column, ddl):
    # Compatible additive PostgreSQL migration: ADD COLUMN only when missing.
    # This keeps older PostgreSQL schemas working without DROP/CREATE.
    if column not in table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

def normalize_mac_address(value):
    """Return a canonical lower-case colon MAC or an empty string."""
    raw = str(value or "").strip().lower()
    compact = "".join(ch for ch in raw if ch in "0123456789abcdef")
    if len(compact) != 12:
        return ""
    return ":".join(compact[pos:pos + 2] for pos in range(0, 12, 2))

def read_agent_json_request():
    """Read a plain or gzip-compressed Agent JSON object with hard limits."""
    raw = request.get_data(cache=False, as_text=False)
    if not raw:
        return {}
    encoding = str(request.headers.get("Content-Encoding") or "").strip().lower()
    if encoding in ("", "identity"):
        decoded = raw
    elif encoding == "gzip":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as stream:
                decoded = stream.read(MAX_UNCOMPRESSED_PUSH_BYTES + 1)
        except (OSError, EOFError) as exc:
            raise ValueError("invalid gzip payload") from exc
    else:
        raise ValueError("unsupported content encoding")
    if len(decoded) > MAX_UNCOMPRESSED_PUSH_BYTES:
        raise ValueError("uncompressed payload too large")
    try:
        data = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid json payload") from exc
    if not isinstance(data, dict):
        raise ValueError("payload is not a JSON object")
    return data

def db():
    db_dir = os.path.dirname(DB)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = dbapi.connect(DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")

    # Keep the old usage schema compatible with the current agent.
    # MAC is retained as searchable interface identity metadata.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER,
        node TEXT,
        vm_uuid TEXT,
        iface TEXT,
        bridge TEXT,
        mac TEXT,
        rx_delta INTEGER,
        tx_delta INTEGER,
        rx_packets_delta INTEGER NOT NULL DEFAULT 0,
        tx_packets_delta INTEGER NOT NULL DEFAULT 0,
        rx_drop_delta INTEGER NOT NULL DEFAULT 0,
        tx_drop_delta INTEGER NOT NULL DEFAULT 0,
        rx_error_delta INTEGER NOT NULL DEFAULT 0,
        tx_error_delta INTEGER NOT NULL DEFAULT 0,
        interval_seconds INTEGER NOT NULL DEFAULT 300
    )
    """)

    # Cached 5-minute buckets. Dashboard reads this table instead of scanning usage.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_stats (
        bucket INTEGER NOT NULL,
        node TEXT NOT NULL,
        bridge TEXT NOT NULL,
        iface TEXT NOT NULL,
        vm_uuid TEXT NOT NULL,
        rx_delta INTEGER NOT NULL DEFAULT 0,
        tx_delta INTEGER NOT NULL DEFAULT 0,
        rx_packets_delta INTEGER NOT NULL DEFAULT 0,
        tx_packets_delta INTEGER NOT NULL DEFAULT 0,
        rx_drop_delta INTEGER NOT NULL DEFAULT 0,
        tx_drop_delta INTEGER NOT NULL DEFAULT 0,
        rx_error_delta INTEGER NOT NULL DEFAULT 0,
        tx_error_delta INTEGER NOT NULL DEFAULT 0,
        rx_mbps_peak REAL NOT NULL DEFAULT 0,
        tx_mbps_peak REAL NOT NULL DEFAULT 0,
        rx_pps_peak REAL NOT NULL DEFAULT 0,
        tx_pps_peak REAL NOT NULL DEFAULT 0,
        rx_packet_size_avg REAL NOT NULL DEFAULT 0,
        tx_packet_size_avg REAL NOT NULL DEFAULT 0,
        network_sample_count INTEGER NOT NULL DEFAULT 0,
        network_sample_expected INTEGER NOT NULL DEFAULT 0,
        network_sample_max_gap_seconds REAL NOT NULL DEFAULT 0,
        seconds_over_pps INTEGER NOT NULL DEFAULT 0,
        seconds_over_mbps INTEGER NOT NULL DEFAULT 0,
        network_sample_quality TEXT NOT NULL DEFAULT 'LEGACY',
        interval_seconds INTEGER NOT NULL DEFAULT 300,
        last_push INTEGER NOT NULL,
        PRIMARY KEY (bucket, node, bridge, iface, vm_uuid)
    )
    """)

    # Inventory/state tables. usage stays raw bandwidth history.
    # deleted_at means hidden from dashboard. Purge routes delete raw rows too.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_inventory (
        node TEXT PRIMARY KEY,
        first_seen INTEGER NOT NULL,
        last_push INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        hidden_at INTEGER,
        deleted_at INTEGER
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS vm_inventory (
        node TEXT NOT NULL,
        vm_uuid TEXT NOT NULL,
        first_seen INTEGER NOT NULL,
        last_seen INTEGER NOT NULL,
        last_iface TEXT,
        last_bridge TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        hidden_at INTEGER,
        deleted_at INTEGER,
        PRIMARY KEY (node, vm_uuid)
    )
    """)

    # Online additive migrations for existing PostgreSQL deployments.
    # Old app/agent only had rx_delta/tx_delta; new metrics are additive.
    for col in (
        "rx_packets_delta",
        "tx_packets_delta",
        "rx_drop_delta",
        "tx_drop_delta",
        "rx_error_delta",
        "tx_error_delta",
    ):
        ensure_column(conn, "usage", col, "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "node_stats", col, "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "usage", "interval_seconds", f"INTEGER NOT NULL DEFAULT {CACHE_BUCKET_SECONDS}")
    ensure_column(conn, "node_stats", "interval_seconds", f"INTEGER NOT NULL DEFAULT {CACHE_BUCKET_SECONDS}")

    network_metric_columns = {
        "rx_mbps_peak": "REAL NOT NULL DEFAULT 0",
        "tx_mbps_peak": "REAL NOT NULL DEFAULT 0",
        "rx_pps_peak": "REAL NOT NULL DEFAULT 0",
        "tx_pps_peak": "REAL NOT NULL DEFAULT 0",
        "rx_packet_size_avg": "REAL NOT NULL DEFAULT 0",
        "tx_packet_size_avg": "REAL NOT NULL DEFAULT 0",
        "network_sample_count": "INTEGER NOT NULL DEFAULT 0",
        "network_sample_expected": "INTEGER NOT NULL DEFAULT 0",
        "network_sample_max_gap_seconds": "REAL NOT NULL DEFAULT 0",
        "seconds_over_pps": "INTEGER NOT NULL DEFAULT 0",
        "seconds_over_mbps": "INTEGER NOT NULL DEFAULT 0",
        "network_sample_quality": "TEXT NOT NULL DEFAULT 'LEGACY'",
    }
    for column, ddl in network_metric_columns.items():
        ensure_column(conn, "node_stats", column, ddl)

    # Optional VM performance history from agent v2 virsh domstats.
    # Old agents can omit this completely; dashboard will show 0/-.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS vm_perf_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER NOT NULL,
        bucket INTEGER NOT NULL,
        node TEXT NOT NULL,
        vm_uuid TEXT NOT NULL,
        interval_seconds INTEGER NOT NULL DEFAULT 300,
        vcpu_current INTEGER NOT NULL DEFAULT 0,
        cpu_percent REAL NOT NULL DEFAULT 0,
        ram_current_kib INTEGER NOT NULL DEFAULT 0,
        ram_maximum_kib INTEGER NOT NULL DEFAULT 0,
        ram_rss_kib INTEGER NOT NULL DEFAULT 0,
        ram_available_kib INTEGER NOT NULL DEFAULT 0,
        ram_unused_kib INTEGER NOT NULL DEFAULT 0,
        ram_usable_kib INTEGER NOT NULL DEFAULT 0,
        disk_read_delta INTEGER NOT NULL DEFAULT 0,
        disk_write_delta INTEGER NOT NULL DEFAULT 0,
        disk_read_reqs_delta INTEGER NOT NULL DEFAULT 0,
        disk_write_reqs_delta INTEGER NOT NULL DEFAULT 0,
        last_push INTEGER NOT NULL
    )
    """)

    # Latest VM metrics cache. /top and node pages read this instead of raw history.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS vm_latest_metrics (
        node TEXT NOT NULL,
        vm_uuid TEXT NOT NULL,
        iface TEXT,
        bridge TEXT,
        last_seen INTEGER NOT NULL,
        interval_seconds INTEGER NOT NULL DEFAULT 300,
        rx_mbps REAL NOT NULL DEFAULT 0,
        tx_mbps REAL NOT NULL DEFAULT 0,
        rx_pps REAL NOT NULL DEFAULT 0,
        tx_pps REAL NOT NULL DEFAULT 0,
        rx_mbps_peak REAL NOT NULL DEFAULT 0,
        tx_mbps_peak REAL NOT NULL DEFAULT 0,
        rx_pps_peak REAL NOT NULL DEFAULT 0,
        tx_pps_peak REAL NOT NULL DEFAULT 0,
        rx_packet_size_avg REAL NOT NULL DEFAULT 0,
        tx_packet_size_avg REAL NOT NULL DEFAULT 0,
        network_sample_count INTEGER NOT NULL DEFAULT 0,
        network_sample_expected INTEGER NOT NULL DEFAULT 0,
        network_sample_max_gap_seconds REAL NOT NULL DEFAULT 0,
        seconds_over_pps INTEGER NOT NULL DEFAULT 0,
        seconds_over_mbps INTEGER NOT NULL DEFAULT 0,
        network_sample_quality TEXT NOT NULL DEFAULT 'LEGACY',
        rx_drop_delta INTEGER NOT NULL DEFAULT 0,
        tx_drop_delta INTEGER NOT NULL DEFAULT 0,
        rx_error_delta INTEGER NOT NULL DEFAULT 0,
        tx_error_delta INTEGER NOT NULL DEFAULT 0,
        cpu_percent REAL NOT NULL DEFAULT 0,
        vcpu_current INTEGER NOT NULL DEFAULT 0,
        ram_current_kib INTEGER NOT NULL DEFAULT 0,
        ram_maximum_kib INTEGER NOT NULL DEFAULT 0,
        ram_rss_kib INTEGER NOT NULL DEFAULT 0,
        ram_available_kib INTEGER NOT NULL DEFAULT 0,
        disk_read_bps REAL NOT NULL DEFAULT 0,
        disk_write_bps REAL NOT NULL DEFAULT 0,
        alert_level TEXT NOT NULL DEFAULT 'ok',
        alert_flags TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (node, vm_uuid)
    )
    """)

    for column, ddl in network_metric_columns.items():
        ensure_column(conn, "vm_latest_metrics", column, ddl)

    # Physical host/node metrics from agent v3. This is separate from VM aggregate metrics.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_host_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER NOT NULL,
        bucket INTEGER NOT NULL,
        node TEXT NOT NULL,
        interval_seconds INTEGER NOT NULL DEFAULT 300,
        load1 REAL NOT NULL DEFAULT 0,
        load5 REAL NOT NULL DEFAULT 0,
        load15 REAL NOT NULL DEFAULT 0,
        cpu_count INTEGER NOT NULL DEFAULT 0,
        cpu_percent REAL NOT NULL DEFAULT 0,
        mem_total INTEGER NOT NULL DEFAULT 0,
        mem_available INTEGER NOT NULL DEFAULT 0,
        mem_used INTEGER NOT NULL DEFAULT 0,
        swap_total INTEGER NOT NULL DEFAULT 0,
        swap_used INTEGER NOT NULL DEFAULT 0,
        disk_read_delta INTEGER NOT NULL DEFAULT 0,
        disk_write_delta INTEGER NOT NULL DEFAULT 0,
        disk_read_bps REAL NOT NULL DEFAULT 0,
        disk_write_bps REAL NOT NULL DEFAULT 0,
        uptime_seconds INTEGER NOT NULL DEFAULT 0,
        last_push INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_host_latest (
        node TEXT PRIMARY KEY,
        last_seen INTEGER NOT NULL DEFAULT 0,
        interval_seconds INTEGER NOT NULL DEFAULT 300,
        load1 REAL NOT NULL DEFAULT 0,
        load5 REAL NOT NULL DEFAULT 0,
        load15 REAL NOT NULL DEFAULT 0,
        cpu_count INTEGER NOT NULL DEFAULT 0,
        cpu_percent REAL NOT NULL DEFAULT 0,
        mem_total INTEGER NOT NULL DEFAULT 0,
        mem_available INTEGER NOT NULL DEFAULT 0,
        mem_used INTEGER NOT NULL DEFAULT 0,
        swap_total INTEGER NOT NULL DEFAULT 0,
        swap_used INTEGER NOT NULL DEFAULT 0,
        disk_read_bps REAL NOT NULL DEFAULT 0,
        disk_write_bps REAL NOT NULL DEFAULT 0,
        disk_read_delta INTEGER NOT NULL DEFAULT 0,
        disk_write_delta INTEGER NOT NULL DEFAULT 0,
        uptime_seconds INTEGER NOT NULL DEFAULT 0,
        alert_level TEXT NOT NULL DEFAULT 'ok',
        alert_flags TEXT NOT NULL DEFAULT ''
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_filesystem_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER NOT NULL,
        node TEXT NOT NULL,
        mount TEXT NOT NULL,
        device TEXT,
        fstype TEXT,
        size INTEGER NOT NULL DEFAULT 0,
        used INTEGER NOT NULL DEFAULT 0,
        avail INTEGER NOT NULL DEFAULT 0,
        use_percent REAL NOT NULL DEFAULT 0,
        last_push INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_filesystem_latest (
        node TEXT NOT NULL,
        mount TEXT NOT NULL,
        device TEXT,
        fstype TEXT,
        size INTEGER NOT NULL DEFAULT 0,
        used INTEGER NOT NULL DEFAULT 0,
        avail INTEGER NOT NULL DEFAULT 0,
        use_percent REAL NOT NULL DEFAULT 0,
        last_seen INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (node, mount)
    )
    """)

    # Physical NIC/uplink metrics from agent v4.
    # This is deliberately separate from VM/tap traffic. VM traffic remains in usage/node_stats.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_physical_net_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER NOT NULL,
        bucket INTEGER NOT NULL,
        node TEXT NOT NULL,
        role TEXT NOT NULL,
        bridge TEXT NOT NULL,
        iface TEXT NOT NULL,
        interval_seconds INTEGER NOT NULL DEFAULT 300,
        rx_delta INTEGER NOT NULL DEFAULT 0,
        tx_delta INTEGER NOT NULL DEFAULT 0,
        rx_packets_delta INTEGER NOT NULL DEFAULT 0,
        tx_packets_delta INTEGER NOT NULL DEFAULT 0,
        rx_drop_delta INTEGER NOT NULL DEFAULT 0,
        tx_drop_delta INTEGER NOT NULL DEFAULT 0,
        rx_error_delta INTEGER NOT NULL DEFAULT 0,
        tx_error_delta INTEGER NOT NULL DEFAULT 0,
        last_push INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_physical_net_latest (
        node TEXT NOT NULL,
        role TEXT NOT NULL,
        bridge TEXT NOT NULL,
        iface TEXT NOT NULL,
        last_seen INTEGER NOT NULL DEFAULT 0,
        interval_seconds INTEGER NOT NULL DEFAULT 300,
        rx_mbps REAL NOT NULL DEFAULT 0,
        tx_mbps REAL NOT NULL DEFAULT 0,
        rx_pps REAL NOT NULL DEFAULT 0,
        tx_pps REAL NOT NULL DEFAULT 0,
        rx_delta INTEGER NOT NULL DEFAULT 0,
        tx_delta INTEGER NOT NULL DEFAULT 0,
        rx_packets_delta INTEGER NOT NULL DEFAULT 0,
        tx_packets_delta INTEGER NOT NULL DEFAULT 0,
        rx_drop_delta INTEGER NOT NULL DEFAULT 0,
        tx_drop_delta INTEGER NOT NULL DEFAULT 0,
        rx_error_delta INTEGER NOT NULL DEFAULT 0,
        tx_error_delta INTEGER NOT NULL DEFAULT 0,
        alert_level TEXT NOT NULL DEFAULT 'ok',
        alert_flags TEXT NOT NULL DEFAULT '',
        mac TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (node, role)
    )
    """)

    # Current IPv4/IPv6 addresses assigned directly to public/private bridges.
    # Addresses are kept separately from physical NIC counters because Linux
    # normally assigns the node IP to br0/br1 rather than the member NIC.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_bridge_addresses_latest (
        node TEXT NOT NULL,
        role TEXT NOT NULL,
        bridge TEXT NOT NULL,
        last_seen INTEGER NOT NULL DEFAULT 0,
        primary_ipv4 TEXT NOT NULL DEFAULT '',
        primary_ipv6 TEXT NOT NULL DEFAULT '',
        ipv4_json TEXT NOT NULL DEFAULT '[]',
        ipv6_json TEXT NOT NULL DEFAULT '[]',
        operstate TEXT NOT NULL DEFAULT '',
        carrier INTEGER NOT NULL DEFAULT 0,
        mtu INTEGER NOT NULL DEFAULT 0,
        mac TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (node, role)
    )
    """)

    # Agent runtime/self-health metrics from agent v4. This helps find slow libvirt/domstats nodes.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS agent_health_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER NOT NULL,
        bucket INTEGER NOT NULL,
        node TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 0,
        interval_seconds INTEGER NOT NULL DEFAULT 300,
        duration_ms INTEGER NOT NULL DEFAULT 0,
        virsh_list_ms INTEGER NOT NULL DEFAULT 0,
        vm_network_ms INTEGER NOT NULL DEFAULT 0,
        vm_perf_ms INTEGER NOT NULL DEFAULT 0,
        node_host_ms INTEGER NOT NULL DEFAULT 0,
        physical_network_ms INTEGER NOT NULL DEFAULT 0,
        api_push_ms INTEGER NOT NULL DEFAULT 0,
        vm_names INTEGER NOT NULL DEFAULT 0,
        interfaces INTEGER NOT NULL DEFAULT 0,
        vms INTEGER NOT NULL DEFAULT 0,
        physical_interfaces INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0,
        errors_json TEXT,
        last_push INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS agent_health_latest (
        node TEXT PRIMARY KEY,
        last_seen INTEGER NOT NULL DEFAULT 0,
        version INTEGER NOT NULL DEFAULT 0,
        interval_seconds INTEGER NOT NULL DEFAULT 300,
        duration_ms INTEGER NOT NULL DEFAULT 0,
        virsh_list_ms INTEGER NOT NULL DEFAULT 0,
        vm_network_ms INTEGER NOT NULL DEFAULT 0,
        vm_perf_ms INTEGER NOT NULL DEFAULT 0,
        node_host_ms INTEGER NOT NULL DEFAULT 0,
        physical_network_ms INTEGER NOT NULL DEFAULT 0,
        api_push_ms INTEGER NOT NULL DEFAULT 0,
        vm_names INTEGER NOT NULL DEFAULT 0,
        interfaces INTEGER NOT NULL DEFAULT 0,
        vms INTEGER NOT NULL DEFAULT 0,
        physical_interfaces INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0,
        errors_json TEXT,
        alert_level TEXT NOT NULL DEFAULT 'ok',
        alert_flags TEXT NOT NULL DEFAULT ''
    )
    """)

    # Latest known location for each VM UUID across all server nodes.
    # This lets the dashboard detect live migration / node moves without deleting old traffic history.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS vm_location_latest (
        vm_uuid TEXT PRIMARY KEY,
        node TEXT NOT NULL,
        first_seen INTEGER NOT NULL,
        last_seen INTEGER NOT NULL,
        previous_node TEXT,
        moved_at INTEGER,
        move_count INTEGER NOT NULL DEFAULT 0,
        last_iface TEXT,
        last_bridge TEXT,
        alert_level TEXT NOT NULL DEFAULT 'ok',
        alert_flags TEXT NOT NULL DEFAULT ''
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS vm_migration_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER NOT NULL,
        vm_uuid TEXT NOT NULL,
        old_node TEXT NOT NULL,
        new_node TEXT NOT NULL,
        old_last_seen INTEGER,
        new_seen INTEGER NOT NULL,
        detail TEXT
    )
    """)

    # Per-node VM presence/state. This table is used to confirm migrations only
    # after the old node has missed the VM for a few pushes, and to keep node
    # pages filterable by active/missing/pending/migrated/purged.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS vm_node_presence (
        vm_uuid TEXT NOT NULL,
        node TEXT NOT NULL,
        first_seen INTEGER NOT NULL,
        last_seen INTEGER NOT NULL,
        last_push INTEGER NOT NULL DEFAULT 0,
        missing_since INTEGER,
        missing_count INTEGER NOT NULL DEFAULT 0,
        present_count INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',
        pending_node TEXT,
        migrated_to TEXT,
        migrated_at INTEGER,
        purged_at INTEGER,
        last_iface TEXT,
        last_bridge TEXT,
        alert_flags TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (vm_uuid, node)
    )
    """)

    # One compact row per node/push bucket. Exact snapshot selection reads this
    # table instead of UNION-scanning the large metric tables.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_push_snapshots (
        node TEXT NOT NULL,
        bucket INTEGER NOT NULL,
        push_time INTEGER NOT NULL,
        last_push INTEGER NOT NULL,
        vm_count INTEGER NOT NULL DEFAULT 0,
        iface_count INTEGER NOT NULL DEFAULT 0,
        inventory_complete INTEGER NOT NULL DEFAULT 0,
        retention_tier TEXT NOT NULL DEFAULT 'raw',
        PRIMARY KEY (node, bucket)
    )
    """)

    # Persistent outage history. One compact row is written when a node
    # recovers after missing one or more complete 5-minute cycles.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_missed_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        node TEXT NOT NULL,
        last_good_push INTEGER NOT NULL,
        missed_from INTEGER NOT NULL,
        recovered_at INTEGER NOT NULL,
        missed_cycles INTEGER NOT NULL DEFAULT 0,
        gap_seconds INTEGER NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT 'live',
        created_at INTEGER NOT NULL
    )
    """)

    # De-duplicate an identical POST retry. A second real agent run in the same
    # 5-minute bucket has a different push_time and is still accepted.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS push_receipts (
        node TEXT NOT NULL,
        push_time INTEGER NOT NULL,
        bucket INTEGER NOT NULL,
        received_at INTEGER NOT NULL,
        PRIMARY KEY (node, push_time)
    )
    """)

    # Exact billing rollups. These are incremented from every accepted interface
    # delta before old raw metrics are thinned/deleted.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS bandwidth_hourly (
        hour_start INTEGER NOT NULL,
        node TEXT NOT NULL,
        vm_uuid TEXT NOT NULL,
        bridge TEXT NOT NULL,
        rx_bytes INTEGER NOT NULL DEFAULT 0,
        tx_bytes INTEGER NOT NULL DEFAULT 0,
        rx_packets INTEGER NOT NULL DEFAULT 0,
        tx_packets INTEGER NOT NULL DEFAULT 0,
        rx_drops INTEGER NOT NULL DEFAULT 0,
        tx_drops INTEGER NOT NULL DEFAULT 0,
        rx_errors INTEGER NOT NULL DEFAULT 0,
        tx_errors INTEGER NOT NULL DEFAULT 0,
        sample_count INTEGER NOT NULL DEFAULT 0,
        last_push INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (hour_start, node, vm_uuid, bridge)
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS bandwidth_daily (
        day_start INTEGER NOT NULL,
        node TEXT NOT NULL,
        vm_uuid TEXT NOT NULL,
        bridge TEXT NOT NULL,
        rx_bytes INTEGER NOT NULL DEFAULT 0,
        tx_bytes INTEGER NOT NULL DEFAULT 0,
        rx_packets INTEGER NOT NULL DEFAULT 0,
        tx_packets INTEGER NOT NULL DEFAULT 0,
        rx_drops INTEGER NOT NULL DEFAULT 0,
        tx_drops INTEGER NOT NULL DEFAULT 0,
        rx_errors INTEGER NOT NULL DEFAULT 0,
        tx_errors INTEGER NOT NULL DEFAULT 0,
        sample_count INTEGER NOT NULL DEFAULT 0,
        last_push INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day_start, node, vm_uuid, bridge)
    )
    """)

    # Canonical per-VM Consumption tables are safe to create before migration.
    # Migration 015 merges any pre-existing legacy tables and replaces their
    # names with read-only compatibility views. Avoid exception-based table
    # detection here because one PostgreSQL error aborts the whole transaction.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS vm_consumption_hourly (
        hour_start INTEGER NOT NULL,
        node TEXT NOT NULL,
        vm_uuid TEXT NOT NULL,
        bridge TEXT NOT NULL,
        rx_bytes INTEGER NOT NULL DEFAULT 0,
        tx_bytes INTEGER NOT NULL DEFAULT 0,
        rx_packets INTEGER NOT NULL DEFAULT 0,
        tx_packets INTEGER NOT NULL DEFAULT 0,
        rx_drops INTEGER NOT NULL DEFAULT 0,
        tx_drops INTEGER NOT NULL DEFAULT 0,
        rx_errors INTEGER NOT NULL DEFAULT 0,
        tx_errors INTEGER NOT NULL DEFAULT 0,
        sample_count INTEGER NOT NULL DEFAULT 0,
        last_push INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (hour_start, node, vm_uuid, bridge)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS vm_consumption_daily (
        day_start INTEGER NOT NULL,
        node TEXT NOT NULL,
        vm_uuid TEXT NOT NULL,
        bridge TEXT NOT NULL,
        rx_bytes INTEGER NOT NULL DEFAULT 0,
        tx_bytes INTEGER NOT NULL DEFAULT 0,
        rx_packets INTEGER NOT NULL DEFAULT 0,
        tx_packets INTEGER NOT NULL DEFAULT 0,
        rx_drops INTEGER NOT NULL DEFAULT 0,
        tx_drops INTEGER NOT NULL DEFAULT 0,
        rx_errors INTEGER NOT NULL DEFAULT 0,
        tx_errors INTEGER NOT NULL DEFAULT 0,
        sample_count INTEGER NOT NULL DEFAULT 0,
        last_push INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day_start, node, vm_uuid, bridge)
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS retention_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at INTEGER NOT NULL,
        finished_at INTEGER,
        status TEXT NOT NULL,
        raw_cutoff INTEGER NOT NULL,
        hourly_cutoff INTEGER NOT NULL,
        detail TEXT
    )
    """)

    # Admin-triggered maintenance runs outside Gunicorn in a transient systemd
    # unit. HTTP requests only enqueue work, so long VACUUM/retention jobs cannot
    # block a dashboard worker or hold a browser request open.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS maintenance_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at INTEGER NOT NULL,
        started_at INTEGER,
        finished_at INTEGER,
        action TEXT NOT NULL,
        parameters TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'queued',
        requested_by TEXT,
        message TEXT,
        unit_name TEXT,
        heartbeat_at INTEGER,
        progress INTEGER NOT NULL DEFAULT 0,
        attempt INTEGER NOT NULL DEFAULT 0,
        cancel_requested BOOLEAN NOT NULL DEFAULT FALSE
    )
    """)

    # Admin settings are stored in PostgreSQL so the initial password and later
    # password changes can be managed from the web UI instead of systemd env.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS admin_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """)

    # Dashboard/admin UI users. Admin role can access /admin. Viewer role can only view dashboard pages.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS dashboard_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'viewer',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        last_login INTEGER
    )
    """)

    # Account login/audit logs. This is separate from node/agent logs.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS account_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER NOT NULL,
        realm TEXT NOT NULL,
        event TEXT NOT NULL,
        username TEXT,
        role TEXT,
        source_ip TEXT,
        user_agent TEXT,
        path TEXT,
        detail TEXT
    )
    """)

    # Node/agent push logs. This is separate from account login logs.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS node_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER NOT NULL,
        event TEXT NOT NULL,
        node TEXT,
        source_ip TEXT,
        user_agent TEXT,
        status_code INTEGER,
        vm_count INTEGER,
        iface_count INTEGER,
        detail TEXT
    )
    """)

    ensure_column(conn, "node_host_stats", "cpu_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "node_host_latest", "cpu_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "node_filesystem_stats", "bucket", "INTEGER NOT NULL DEFAULT 0")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_time_node_bridge ON usage(time, node, bridge)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_node_time ON usage(node, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_vm_time ON usage(node, vm_uuid, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_vm_exact_chart ON usage(node, vm_uuid, bridge, iface, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_stats_last_push ON node_stats(last_push)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_stats_node_last_push ON node_stats(node, last_push)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_stats_search ON node_stats(node, vm_uuid, iface)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_stats_vm_chart ON node_stats(node, vm_uuid, bridge, iface, bucket)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_stats_packets ON node_stats(node, last_push, rx_packets_delta, tx_packets_delta)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_perf_node_vm_time ON vm_perf_stats(node, vm_uuid, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_perf_bucket_node ON vm_perf_stats(bucket, node)")
    # The primary key (node, vm_uuid) already supports node-scoped current reads.
    # Avoid a last_seen index that would be rewritten for every VM every push.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_location_node_seen ON vm_location_latest(node, last_seen)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_migration_events_time ON vm_migration_events(time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_migration_events_vm_time ON vm_migration_events(vm_uuid, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_migration_events_nodes ON vm_migration_events(old_node, new_node, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_node_presence_node_status ON vm_node_presence(node, status, last_seen)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_node_presence_vm_status ON vm_node_presence(vm_uuid, status, last_seen)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_node_presence_migrated ON vm_node_presence(status, migrated_at, purged_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_host_stats_node_time ON node_host_stats(node, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_host_stats_bucket_node ON node_host_stats(bucket, node)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_fs_stats_node_time ON node_filesystem_stats(node, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_fs_latest_node_usage ON node_filesystem_latest(node, use_percent)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_physical_net_stats_node_time ON node_physical_net_stats(node, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_physical_net_stats_bucket_node ON node_physical_net_stats(bucket, node)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_physical_net_stats_role ON node_physical_net_stats(node, role, bucket)")
    # node_physical_net_latest has only public/private rows per node; a
    # volatile last_seen index costs more to maintain than it saves.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_bridge_addresses_seen ON node_bridge_addresses_latest(last_seen)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_health_stats_node_time ON agent_health_stats(node, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_health_stats_bucket_node ON agent_health_stats(bucket, node)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_inventory_status ON vm_inventory(status, last_seen)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_inventory_last_seen ON vm_inventory(last_seen)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_inventory_last_push ON node_inventory(last_push)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dashboard_users_username ON dashboard_users(username)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_account_logs_time ON account_logs(time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_account_logs_user_time ON account_logs(username, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_logs_time ON node_logs(time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_logs_node_time ON node_logs(node, time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_stats_node_bucket_retention ON node_stats(node, bucket)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_perf_node_bucket_retention ON vm_perf_stats(node, bucket)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_host_node_bucket_retention ON node_host_stats(node, bucket)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_physical_node_bucket_retention ON node_physical_net_stats(node, bucket)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_health_node_bucket_retention ON agent_health_stats(node, bucket)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_fs_node_bucket_retention ON node_filesystem_stats(node, bucket)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_push_snapshots_bucket ON node_push_snapshots(bucket, node)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_node_missed_unique ON node_missed_events(node, last_good_push, recovered_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_missed_node_time ON node_missed_events(node, recovered_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_push_snapshots_node_tier_bucket ON node_push_snapshots(node, retention_tier, bucket)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_push_receipts_received ON push_receipts(received_at)")
    
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_consumption_hourly_vm_time ON vm_consumption_hourly(vm_uuid, hour_start)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_consumption_hourly_node_time ON vm_consumption_hourly(node, hour_start)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_consumption_daily_vm_time ON vm_consumption_daily(vm_uuid, day_start)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vm_consumption_daily_node_time ON vm_consumption_daily(node, day_start)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_maintenance_jobs_created ON maintenance_jobs(created_at DESC)")
    # Fast bounded current-state tables. One row per VM/interface/node.
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS vm_current_fast (
      node TEXT NOT NULL, vm_uuid TEXT NOT NULL, last_seen INTEGER NOT NULL,
      interval_seconds INTEGER NOT NULL DEFAULT 300, iface_count INTEGER NOT NULL DEFAULT 0,
      public_rx_bytes INTEGER NOT NULL DEFAULT 0, public_tx_bytes INTEGER NOT NULL DEFAULT 0,
      private_rx_bytes INTEGER NOT NULL DEFAULT 0, private_tx_bytes INTEGER NOT NULL DEFAULT 0,
      rx_bytes INTEGER NOT NULL DEFAULT 0, tx_bytes INTEGER NOT NULL DEFAULT 0, total_bytes INTEGER NOT NULL DEFAULT 0,
      public_mbps REAL NOT NULL DEFAULT 0, private_mbps REAL NOT NULL DEFAULT 0,
      rx_mbps REAL NOT NULL DEFAULT 0, tx_mbps REAL NOT NULL DEFAULT 0, total_mbps REAL NOT NULL DEFAULT 0,
      public_pps REAL NOT NULL DEFAULT 0, private_pps REAL NOT NULL DEFAULT 0,
      rx_pps REAL NOT NULL DEFAULT 0, tx_pps REAL NOT NULL DEFAULT 0, total_pps REAL NOT NULL DEFAULT 0,
      public_peak_mbps REAL NOT NULL DEFAULT 0, private_peak_mbps REAL NOT NULL DEFAULT 0,
      rx_peak_mbps REAL NOT NULL DEFAULT 0, tx_peak_mbps REAL NOT NULL DEFAULT 0, total_peak_mbps REAL NOT NULL DEFAULT 0,
      public_peak_pps REAL NOT NULL DEFAULT 0, private_peak_pps REAL NOT NULL DEFAULT 0,
      rx_peak_pps REAL NOT NULL DEFAULT 0, tx_peak_pps REAL NOT NULL DEFAULT 0, total_peak_pps REAL NOT NULL DEFAULT 0,
      sample_count INTEGER NOT NULL DEFAULT 0, sample_expected INTEGER NOT NULL DEFAULT 0,
      sample_max_gap REAL NOT NULL DEFAULT 0, sample_quality TEXT NOT NULL DEFAULT 'LEGACY',
      seconds_over_rx_pps INTEGER NOT NULL DEFAULT 0, seconds_over_tx_pps INTEGER NOT NULL DEFAULT 0,
      drops INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
      cpu_full_percent REAL NOT NULL DEFAULT 0, cpu_core_percent REAL NOT NULL DEFAULT 0, vcpu_current INTEGER NOT NULL DEFAULT 0,
      ram_current_kib INTEGER NOT NULL DEFAULT 0, ram_rss_kib INTEGER NOT NULL DEFAULT 0, ram_available_kib INTEGER NOT NULL DEFAULT 0,
      disk_read_bps REAL NOT NULL DEFAULT 0, disk_write_bps REAL NOT NULL DEFAULT 0,
      disk_read_iops REAL NOT NULL DEFAULT 0, disk_write_iops REAL NOT NULL DEFAULT 0,
      PRIMARY KEY(node, vm_uuid)
    );
    CREATE TABLE IF NOT EXISTS vm_iface_current (
      node TEXT NOT NULL, vm_uuid TEXT NOT NULL, bridge TEXT NOT NULL, iface TEXT NOT NULL,
      mac TEXT NOT NULL DEFAULT '',
      last_seen INTEGER NOT NULL, interval_seconds INTEGER NOT NULL DEFAULT 300,
      rx_bytes INTEGER NOT NULL DEFAULT 0, tx_bytes INTEGER NOT NULL DEFAULT 0,
      rx_packets INTEGER NOT NULL DEFAULT 0, tx_packets INTEGER NOT NULL DEFAULT 0,
      rx_mbps REAL NOT NULL DEFAULT 0, tx_mbps REAL NOT NULL DEFAULT 0, total_mbps REAL NOT NULL DEFAULT 0,
      rx_peak_mbps REAL NOT NULL DEFAULT 0, tx_peak_mbps REAL NOT NULL DEFAULT 0, total_peak_mbps REAL NOT NULL DEFAULT 0,
      rx_pps REAL NOT NULL DEFAULT 0, tx_pps REAL NOT NULL DEFAULT 0, total_pps REAL NOT NULL DEFAULT 0,
      rx_peak_pps REAL NOT NULL DEFAULT 0, tx_peak_pps REAL NOT NULL DEFAULT 0, total_peak_pps REAL NOT NULL DEFAULT 0,
      sample_count INTEGER NOT NULL DEFAULT 0, sample_expected INTEGER NOT NULL DEFAULT 0,
      sample_max_gap REAL NOT NULL DEFAULT 0, sample_quality TEXT NOT NULL DEFAULT 'LEGACY',
      seconds_over_rx_pps INTEGER NOT NULL DEFAULT 0, seconds_over_tx_pps INTEGER NOT NULL DEFAULT 0,
      drops INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(node, vm_uuid, bridge, iface)
    );
    CREATE TABLE IF NOT EXISTS node_current_fast (
      node TEXT PRIMARY KEY, last_seen INTEGER NOT NULL, interval_seconds INTEGER NOT NULL DEFAULT 300,
      vm_count INTEGER NOT NULL DEFAULT 0, iface_count INTEGER NOT NULL DEFAULT 0,
      public_bytes INTEGER NOT NULL DEFAULT 0, private_bytes INTEGER NOT NULL DEFAULT 0, total_bytes INTEGER NOT NULL DEFAULT 0,
      public_packets INTEGER NOT NULL DEFAULT 0, private_packets INTEGER NOT NULL DEFAULT 0, total_packets INTEGER NOT NULL DEFAULT 0,
      drops INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
      load1 REAL NOT NULL DEFAULT 0, load5 REAL NOT NULL DEFAULT 0, load15 REAL NOT NULL DEFAULT 0,
      cpu_count INTEGER NOT NULL DEFAULT 0, cpu_percent REAL NOT NULL DEFAULT 0,
      mem_total INTEGER NOT NULL DEFAULT 0, mem_used INTEGER NOT NULL DEFAULT 0,
      disk_read_bps REAL NOT NULL DEFAULT 0, disk_write_bps REAL NOT NULL DEFAULT 0, uptime_seconds INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS vm_abuse_state (
      node TEXT NOT NULL, vm_uuid TEXT NOT NULL, last_seen INTEGER NOT NULL,
      is_abuse INTEGER NOT NULL DEFAULT 0, abuse_since INTEGER, abuse_flags TEXT NOT NULL DEFAULT '', severity REAL NOT NULL DEFAULT 0,
      network_rx_hit INTEGER NOT NULL DEFAULT 0, network_tx_hit INTEGER NOT NULL DEFAULT 0,
      cpu_streak_seconds INTEGER NOT NULL DEFAULT 0, disk_streak_seconds INTEGER NOT NULL DEFAULT 0,
      rx_pps REAL NOT NULL DEFAULT 0, tx_pps REAL NOT NULL DEFAULT 0, rx_peak_pps REAL NOT NULL DEFAULT 0, tx_peak_pps REAL NOT NULL DEFAULT 0,
      seconds_over_rx_pps INTEGER NOT NULL DEFAULT 0, seconds_over_tx_pps INTEGER NOT NULL DEFAULT 0,
      cpu_full_percent REAL NOT NULL DEFAULT 0, cpu_core_percent REAL NOT NULL DEFAULT 0, vcpu_current INTEGER NOT NULL DEFAULT 0,
      disk_read_bps REAL NOT NULL DEFAULT 0, disk_write_bps REAL NOT NULL DEFAULT 0,
      disk_read_iops REAL NOT NULL DEFAULT 0, disk_write_iops REAL NOT NULL DEFAULT 0,
      PRIMARY KEY(node, vm_uuid)
    );
    CREATE INDEX IF NOT EXISTS idx_vm_iface_current_node_bridge ON vm_iface_current(node,bridge);
    CREATE INDEX IF NOT EXISTS idx_vm_abuse_active
      ON vm_abuse_state(severity DESC,last_seen DESC,node,vm_uuid)
      WHERE is_abuse=1;
    CREATE TABLE IF NOT EXISTS vm_abuse_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      event_time INTEGER NOT NULL,
      event_type TEXT NOT NULL,
      node TEXT NOT NULL,
      vm_uuid TEXT NOT NULL,
      abuse_flags TEXT NOT NULL DEFAULT '',
      severity REAL NOT NULL DEFAULT 0,
      rx_pps REAL NOT NULL DEFAULT 0,
      tx_pps REAL NOT NULL DEFAULT 0,
      rx_peak_pps REAL NOT NULL DEFAULT 0,
      tx_peak_pps REAL NOT NULL DEFAULT 0,
      seconds_over_rx_pps INTEGER NOT NULL DEFAULT 0,
      seconds_over_tx_pps INTEGER NOT NULL DEFAULT 0,
      cpu_full_percent REAL NOT NULL DEFAULT 0,
      cpu_core_percent REAL NOT NULL DEFAULT 0,
      vcpu_current INTEGER NOT NULL DEFAULT 0,
      cpu_streak_seconds INTEGER NOT NULL DEFAULT 0,
      disk_read_bps REAL NOT NULL DEFAULT 0,
      disk_write_bps REAL NOT NULL DEFAULT 0,
      disk_read_iops REAL NOT NULL DEFAULT 0,
      disk_write_iops REAL NOT NULL DEFAULT 0,
      disk_streak_seconds INTEGER NOT NULL DEFAULT 0,
      thresholds_json TEXT NOT NULL DEFAULT '{}',
      detail TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_vm_abuse_events_time ON vm_abuse_events(event_time DESC,id DESC);
    CREATE INDEX IF NOT EXISTS idx_vm_abuse_events_vm_time ON vm_abuse_events(node,vm_uuid,event_time DESC);
    CREATE INDEX IF NOT EXISTS idx_vm_abuse_events_type_time ON vm_abuse_events(event_type,event_time DESC);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_vm_abuse_events_dedupe
      ON vm_abuse_events(node,vm_uuid,event_time,event_type,abuse_flags);
    """)
    ensure_column(conn, "vm_iface_current", "mac", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "node_physical_net_latest", "mac", "TEXT NOT NULL DEFAULT ''")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS vm_nic_identity_lookup (
      node TEXT NOT NULL, vm_uuid TEXT NOT NULL, bridge TEXT NOT NULL, iface TEXT NOT NULL,
      mac TEXT NOT NULL DEFAULT '', first_seen INTEGER NOT NULL, changed_at INTEGER NOT NULL,
      PRIMARY KEY(node,vm_uuid,bridge,iface)
    );
    CREATE INDEX IF NOT EXISTS idx_vm_nic_identity_lookup_mac
      ON vm_nic_identity_lookup(mac) WHERE mac<>'';
    CREATE TABLE IF NOT EXISTS node_nic_identity_lookup (
      node TEXT NOT NULL, role TEXT NOT NULL, bridge TEXT NOT NULL DEFAULT '',
      iface TEXT NOT NULL DEFAULT '', mac TEXT NOT NULL DEFAULT '',
      first_seen INTEGER NOT NULL, changed_at INTEGER NOT NULL,
      PRIMARY KEY(node,role)
    );
    CREATE INDEX IF NOT EXISTS idx_node_nic_identity_lookup_mac
      ON node_nic_identity_lookup(mac) WHERE mac<>'';
    """)
    conn.commit()
    return conn

