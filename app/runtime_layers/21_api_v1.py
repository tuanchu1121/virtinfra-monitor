# Design goals:
# - Keep the existing Agent /push token completely separate from external API keys.
# - Store only SHA-256 hashes of high-entropy API secrets; show plaintext once.
# - Read bounded current/cache tables only for current VM and abuse endpoints.
# - Support scopes, optional IP/CIDR allowlists, expiry, revoke/rotate and audit.
# - Avoid a write per poll: last-used metadata is flushed at most once per minute.
# - Do not enable CORS implicitly. Native Windows clients do not need CORS.

V48110_VERSION = "48.11.0"
API_VERSION = "v1"
API_KEY_PREFIX = "bwm_live"
API_SUPPORTED_SCOPES = {
    "abuse:read": "Read current VM abuse state",
    "abuse_events:read": "Read VM abuse event history",
    "vm:read": "Read current VM metrics",
    "node:read": "Read lightweight node context",
    "bandwidth:read": "Read VM bandwidth counters and rates",
}
API_DEFAULT_SCOPES = ("abuse:read", "abuse_events:read")
API_RATE_LIMIT_PER_MINUTE = max(10, int(os.environ.get("BW_API_RATE_LIMIT_PER_MINUTE", "120")))
API_MAX_LIMIT = max(50, min(5000, int(os.environ.get("BW_API_MAX_LIMIT", "500"))))
API_LAST_USED_FLUSH_SECONDS = max(10, int(os.environ.get("BW_API_LAST_USED_FLUSH_SECONDS", "60")))
API_TRUST_PROXY = os.environ.get("BW_API_TRUST_PROXY", "0") == "1"
API_TRUSTED_PROXIES_RAW = os.environ.get("BW_API_TRUSTED_PROXIES", "127.0.0.1/32,::1/128")

import hashlib
import hmac
import ipaddress
import threading
from functools import wraps
from flask import g

_api_schema_lock = threading.Lock()
_api_schema_ready = False
_api_rate_lock = threading.Lock()
_api_rate_windows = {}
_api_last_used_lock = threading.Lock()
_api_last_used_cache = {}

def _api_parse_networks(raw):
    values = []
    for item in str(raw or "").replace("\n", ",").replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            app.logger.warning("Ignoring invalid trusted proxy network: %s", item)
    return tuple(values)

API_TRUSTED_PROXIES = _api_parse_networks(API_TRUSTED_PROXIES_RAW)

_db_v48110_base = db

def _v48110_ensure_schema(conn):
    """Create API tables additively. Existing monitor tables are never rebuilt."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        secret_hash TEXT NOT NULL,
        scopes_json TEXT NOT NULL DEFAULT '[]',
        allowed_ips_json TEXT NOT NULL DEFAULT '[]',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        expires_at INTEGER,
        last_used_at INTEGER,
        last_used_ip TEXT NOT NULL DEFAULT '',
        use_count INTEGER NOT NULL DEFAULT 0,
        revoked_at INTEGER,
        revoked_by TEXT NOT NULL DEFAULT '',
        rotated_from_key_id TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT ''
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_key_id ON api_keys(key_id);
    CREATE INDEX IF NOT EXISTS idx_api_keys_active_expiry ON api_keys(is_active, expires_at);
    CREATE INDEX IF NOT EXISTS idx_api_keys_created ON api_keys(created_at DESC, id DESC);

    CREATE TABLE IF NOT EXISTS api_key_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_time INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        key_id TEXT NOT NULL DEFAULT '',
        key_name TEXT NOT NULL DEFAULT '',
        actor TEXT NOT NULL DEFAULT '',
        source_ip TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_api_key_events_time ON api_key_events(event_time DESC, id DESC);
    CREATE INDEX IF NOT EXISTS idx_api_key_events_key_time ON api_key_events(key_id, event_time DESC, id DESC);
    CREATE INDEX IF NOT EXISTS idx_api_key_events_type_time ON api_key_events(event_type, event_time DESC, id DESC);
    """)
    conn.commit()

def db():
    global _api_schema_ready
    conn = _db_v48110_base()
    if not _api_schema_ready:
        with _api_schema_lock:
            if not _api_schema_ready:
                _v48110_ensure_schema(conn)
                _api_schema_ready = True
    return conn

def _api_json_load_list(value):
    try:
        data = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []

def _api_clean_scopes(values):
    if isinstance(values, str):
        values = [values]
    cleaned = []
    for value in values or []:
        value = str(value or "").strip().lower()
        if value in API_SUPPORTED_SCOPES and value not in cleaned:
            cleaned.append(value)
    return cleaned

def _api_clean_name(value):
    value = " ".join(str(value or "").strip().split())
    if len(value) < 3:
        raise ValueError("API key name must be at least 3 characters.")
    if len(value) > 80:
        raise ValueError("API key name must not exceed 80 characters.")
    return value

def _api_normalize_allowlist(raw):
    """Validate exact IPs and CIDRs; return canonical strings."""
    if isinstance(raw, (list, tuple)):
        tokens = list(raw)
    else:
        text = str(raw or "").replace("\r", "\n")
        for sep in (",", ";", " ", "\t"):
            text = text.replace(sep, "\n")
        tokens = text.split("\n")
    result = []
    for token in tokens:
        token = str(token or "").strip()
        if not token:
            continue
        try:
            if "/" in token:
                canonical = str(ipaddress.ip_network(token, strict=False))
            else:
                canonical = str(ipaddress.ip_address(token))
        except ValueError as exc:
            raise ValueError(f"Invalid allowed IP or CIDR: {token}") from exc
        if canonical not in result:
            result.append(canonical)
    if len(result) > 64:
        raise ValueError("A maximum of 64 IP/CIDR entries is allowed per key.")
    return result

def _api_secret_hash(secret):
    return hashlib.sha256(str(secret).encode("utf-8")).hexdigest()

def _api_generate_token():
    key_id = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    return key_id, secret, f"{API_KEY_PREFIX}_{key_id}_{secret}"

def _api_parse_token(token):
    token = str(token or "").strip()
    parts = token.split("_", 3)
    if len(parts) != 4 or parts[0] != "bwm" or parts[1] != "live":
        return None, None
    key_id, secret = parts[2].strip().lower(), parts[3].strip()
    if len(key_id) != 12 or any(ch not in "0123456789abcdef" for ch in key_id):
        return None, None
    if len(secret) < 32 or len(secret) > 256:
        return None, None
    return key_id, secret

def _api_log_event(conn, event_type, key_id="", key_name="", actor="", source_ip="", detail=""):
    conn.execute(
        """INSERT INTO api_key_events(event_time,event_type,key_id,key_name,actor,source_ip,detail)
           VALUES(?,?,?,?,?,?,?)""",
        (now_ts(), str(event_type or "")[:48], str(key_id or "")[:64], str(key_name or "")[:120],
         str(actor or "")[:120], str(source_ip or "")[:128], str(detail or "")[:1000]),
    )

def _api_create_key_record(conn, name, scopes, allowed_ips, expires_at, actor, note="", rotated_from=""):
    name = _api_clean_name(name)
    scopes = _api_clean_scopes(scopes)
    if not scopes:
        raise ValueError("Select at least one API permission.")
    allowed_ips = _api_normalize_allowlist(allowed_ips)
    expires_at = safe_int(expires_at, 0) or None
    if expires_at is not None and expires_at <= now_ts():
        raise ValueError("Expiration must be in the future.")
    note = str(note or "").strip()[:500]
    actor = str(actor or "admin").strip()[:120]

    for _ in range(5):
        key_id, secret, token = _api_generate_token()
        try:
            conn.execute(
                """INSERT INTO api_keys(
                    key_id,name,secret_hash,scopes_json,allowed_ips_json,is_active,
                    created_at,created_by,expires_at,rotated_from_key_id,note
                ) VALUES(?,?,?,?,?,1,?,?,?,?,?)""",
                (key_id, name, _api_secret_hash(secret), json.dumps(scopes, separators=(",", ":")),
                 json.dumps(allowed_ips, separators=(",", ":")), now_ts(), actor,
                 expires_at, str(rotated_from or "")[:64], note),
            )
            _api_log_event(
                conn, "KEY_CREATED", key_id=key_id, key_name=name, actor=actor,
                source_ip=api_client_ip(), detail=f"scopes={','.join(scopes)}; expires_at={expires_at or 'never'}",
            )
            return key_id, token
        except dbapi.IntegrityError:
            continue
    raise RuntimeError("Could not allocate a unique API key ID.")

def _api_key_row_to_dict(row):
    if not row:
        return None
    keys = (
        "id", "key_id", "name", "secret_hash", "scopes_json", "allowed_ips_json", "is_active",
        "created_at", "created_by", "expires_at", "last_used_at", "last_used_ip", "use_count",
        "revoked_at", "revoked_by", "rotated_from_key_id", "note",
    )
    data = dict(zip(keys, row))
    data["scopes"] = _api_json_load_list(data.pop("scopes_json", "[]"))
    data["allowed_ips"] = _api_json_load_list(data.pop("allowed_ips_json", "[]"))
    return data

def _api_get_key_by_id(conn, key_id):
    row = conn.execute(
        """SELECT id,key_id,name,secret_hash,scopes_json,allowed_ips_json,is_active,
                  created_at,created_by,expires_at,last_used_at,last_used_ip,use_count,
                  revoked_at,revoked_by,rotated_from_key_id,note
           FROM api_keys WHERE key_id=?""",
        (str(key_id or "").lower(),),
    ).fetchone()
    return _api_key_row_to_dict(row)

def _api_ip_in_networks(ip_value, networks):
    try:
        address = ipaddress.ip_address(str(ip_value or "").strip())
    except ValueError:
        return False
    return any(address in network for network in networks)

def api_client_ip():
    """Return the API caller IP without blindly trusting spoofable XFF headers."""
    remote = str(request.remote_addr or "").strip()
    if not API_TRUST_PROXY or not _api_ip_in_networks(remote, API_TRUSTED_PROXIES):
        return remote
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return remote

def _api_allowlist_matches(client_ip, allowed_items):
    if not allowed_items:
        return True
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for item in allowed_items:
        try:
            if "/" in item:
                if address in ipaddress.ip_network(item, strict=False):
                    return True
            elif address == ipaddress.ip_address(item):
                return True
        except ValueError:
            continue
    return False

def _api_response(payload=None, status=200):
    body = {"ok": 200 <= int(status) < 300, "api_version": API_VERSION, "generated_at": now_ts()}
    if payload:
        body.update(payload)
    response = jsonify(body)
    response.status_code = int(status)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    request_id = getattr(g, "api_request_id", "") or secrets.token_hex(8)
    response.headers["X-Request-ID"] = request_id
    return response

def _api_error(code, message, status, detail=None):
    error = {"code": str(code), "message": str(message)}
    if detail:
        error["detail"] = str(detail)
    return _api_response({"error": error}, status=status)

def _api_extract_bearer():
    header = str(request.headers.get("Authorization") or "").strip()
    if not header:
        return ""
    scheme, sep, value = header.partition(" ")
    if not sep or scheme.lower() != "bearer":
        return ""
    return value.strip()

def _api_rate_allowed(key_id, client_ip):
    current_minute = int(time.time() // 60)
    bucket_key = (str(key_id), str(client_ip), current_minute)
    with _api_rate_lock:
        # Bound memory even when random invalid callers spray requests.
        if len(_api_rate_windows) > 10000:
            stale = [key for key in _api_rate_windows if key[2] < current_minute - 2]
            for key in stale[:8000]:
                _api_rate_windows.pop(key, None)
        count = safe_int(_api_rate_windows.get(bucket_key), 0) + 1
        _api_rate_windows[bucket_key] = count
    return count <= API_RATE_LIMIT_PER_MINUTE, count

def _api_flush_last_used(key_id, client_ip):
    now = now_ts()
    cache_key = (str(key_id), str(client_ip))
    with _api_last_used_lock:
        last = safe_int(_api_last_used_cache.get(cache_key), 0)
        if now - last < API_LAST_USED_FLUSH_SECONDS:
            return
        _api_last_used_cache[cache_key] = now
    conn = db()
    try:
        conn.execute(
            """UPDATE api_keys
               SET last_used_at=?,last_used_ip=?,use_count=use_count+1
               WHERE key_id=? AND is_active=1""",
            (now, str(client_ip or "")[:128], str(key_id)),
        )
        conn.commit()
    finally:
        conn.close()

def _api_authenticate(required_scopes=()):
    g.api_request_id = secrets.token_hex(8)
    client_ip = api_client_ip()
    token = _api_extract_bearer()
    key_id, secret = _api_parse_token(token)
    if not key_id:
        return None, _api_error("missing_or_invalid_api_key", "Provide a valid Bearer API key.", 401)

    conn = db()
    try:
        key = _api_get_key_by_id(conn, key_id)
        if not key:
            # Do not persist arbitrary unknown key IDs. This prevents unauthenticated
            # internet scans from turning the audit table into a write-amplification vector.
            return None, _api_error("invalid_api_key", "The API key is invalid.", 401)
        if not hmac.compare_digest(str(key.get("secret_hash") or ""), _api_secret_hash(secret)):
            _api_log_event(conn, "AUTH_FAILED", key_id=key_id, key_name=key.get("name"), actor="api", source_ip=client_ip, detail=request.path)
            conn.commit()
            return None, _api_error("invalid_api_key", "The API key is invalid.", 401)
        if not safe_int(key.get("is_active"), 0):
            return None, _api_error("api_key_revoked", "The API key has been revoked.", 401)
        expires_at = safe_int(key.get("expires_at"), 0)
        if expires_at and expires_at <= now_ts():
            return None, _api_error("api_key_expired", "The API key has expired.", 401)
        if not _api_allowlist_matches(client_ip, key.get("allowed_ips") or []):
            _api_log_event(conn, "IP_DENIED", key_id=key_id, key_name=key.get("name"), actor="api", source_ip=client_ip, detail=request.path)
            conn.commit()
            return None, _api_error("source_ip_not_allowed", "This source IP is not allowed for the API key.", 403)
        missing = [scope for scope in required_scopes if scope not in (key.get("scopes") or [])]
        if missing:
            _api_log_event(conn, "SCOPE_DENIED", key_id=key_id, key_name=key.get("name"), actor="api", source_ip=client_ip, detail=f"path={request.path}; missing={','.join(missing)}")
            conn.commit()
            return None, _api_error("insufficient_scope", f"Required scope: {', '.join(missing)}.", 403)
    finally:
        conn.close()

    allowed, count = _api_rate_allowed(key_id, client_ip)
    if not allowed:
        return None, _api_error("rate_limit_exceeded", "Too many API requests. Retry after the next minute window.", 429, detail=f"limit={API_RATE_LIMIT_PER_MINUTE}/minute")

    g.api_key = key
    g.api_client_ip = client_ip
    g.api_rate_count = count
    _api_flush_last_used(key_id, client_ip)
    return key, None

def require_api_scopes(*scopes):
    scopes = tuple(_api_clean_scopes(scopes))

    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            _key, error = _api_authenticate(scopes)
            if error is not None:
                return error
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def _api_limit_offset(default=200):
    limit = max(1, min(API_MAX_LIMIT, safe_int(request.args.get("limit"), default)))
    offset = max(0, safe_int(request.args.get("offset"), 0))
    return limit, offset

def _api_parse_flags(value):
    return [item for item in str(value or "").split(",") if item]

def _api_vm_abuse_item(row):
    # Keep this mapping explicit so API compatibility does not depend on SELECT *.
    (
        node, vm_uuid, last_seen, abuse_since, flags, severity,
        network_rx_hit, network_tx_hit, network_rx_mbps_hit, network_tx_mbps_hit,
        rx_mbps, tx_mbps, rx_pps, tx_pps, rx_peak_pps, tx_peak_pps,
        seconds_over_rx_pps, seconds_over_tx_pps,
        network_rx_mbps_streak_seconds, network_tx_mbps_streak_seconds,
        cpu_full_percent, cpu_core_percent, vcpu_current, cpu_streak_seconds,
        disk_read_bps, disk_write_bps, disk_read_iops, disk_write_iops, disk_streak_seconds,
        policy_revision, engine_version, sample_quality, sample_count, sample_expected, sample_max_gap,
        last_bridge, last_iface,
    ) = row
    return {
        "node": str(node),
        "vm_uuid": str(vm_uuid),
        "last_seen": safe_int(last_seen, 0),
        "abuse_since": safe_int(abuse_since, 0) or None,
        "severity": round(safe_float(severity, 0), 4),
        "flags": _api_parse_flags(flags),
        "network": {
            "rx_hit": bool(network_rx_hit), "tx_hit": bool(network_tx_hit),
            "rx_mbps_hit": bool(network_rx_mbps_hit), "tx_mbps_hit": bool(network_tx_mbps_hit),
            "rx_mbps": round(safe_float(rx_mbps, 0), 4), "tx_mbps": round(safe_float(tx_mbps, 0), 4),
            "rx_pps": round(safe_float(rx_pps, 0), 4), "tx_pps": round(safe_float(tx_pps, 0), 4),
            "rx_peak_pps": round(safe_float(rx_peak_pps, 0), 4), "tx_peak_pps": round(safe_float(tx_peak_pps, 0), 4),
            "seconds_over_rx_pps": safe_int(seconds_over_rx_pps, 0),
            "seconds_over_tx_pps": safe_int(seconds_over_tx_pps, 0),
            "rx_mbps_streak_seconds": safe_int(network_rx_mbps_streak_seconds, 0),
            "tx_mbps_streak_seconds": safe_int(network_tx_mbps_streak_seconds, 0),
        },
        "cpu": {
            "full_percent": round(safe_float(cpu_full_percent, 0), 4),
            "core_percent": round(safe_float(cpu_core_percent, 0), 4),
            "vcpu": safe_int(vcpu_current, 0),
            "streak_seconds": safe_int(cpu_streak_seconds, 0),
        },
        "disk": {
            "read_bps": round(safe_float(disk_read_bps, 0), 4),
            "write_bps": round(safe_float(disk_write_bps, 0), 4),
            "read_iops": round(safe_float(disk_read_iops, 0), 4),
            "write_iops": round(safe_float(disk_write_iops, 0), 4),
            "streak_seconds": safe_int(disk_streak_seconds, 0),
        },
        "sample": {
            "quality": str(sample_quality or "UNKNOWN"),
            "count": safe_int(sample_count, 0),
            "expected": safe_int(sample_expected, 0),
            "max_gap_seconds": round(safe_float(sample_max_gap, 0), 4),
        },
        "placement": {"bridge": str(last_bridge or ""), "iface": str(last_iface or "")},
        "policy": {"revision": safe_int(policy_revision, 0), "engine_version": str(engine_version or "")},
    }

_API_ABUSE_SELECT = """
SELECT a.node,a.vm_uuid,a.last_seen,a.abuse_since,a.abuse_flags,a.severity,
       a.network_rx_hit,a.network_tx_hit,
       COALESCE(a.network_rx_mbps_hit,0),COALESCE(a.network_tx_mbps_hit,0),
       COALESCE(a.rx_mbps,0),COALESCE(a.tx_mbps,0),
       a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,
       a.seconds_over_rx_pps,a.seconds_over_tx_pps,
       COALESCE(a.network_rx_mbps_streak_seconds,0),COALESCE(a.network_tx_mbps_streak_seconds,0),
       a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,a.cpu_streak_seconds,
       a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,a.disk_streak_seconds,
       COALESCE(a.policy_revision,0),COALESCE(a.engine_version,''),
       COALESCE(c.sample_quality,'UNKNOWN'),COALESCE(c.sample_count,0),COALESCE(c.sample_expected,0),COALESCE(c.sample_max_gap,0),
       COALESCE(v.last_bridge,''),COALESCE(v.last_iface,'')
FROM vm_abuse_state a
LEFT JOIN vm_current_fast c ON c.node=a.node AND c.vm_uuid=a.vm_uuid
LEFT JOIN vm_inventory v ON v.node=a.node AND v.vm_uuid=a.vm_uuid
"""

def _api_abuse_filters(include_uuid=False):
    where = ["a.is_abuse=1", "a.last_seen>=?"]
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS]
    node = str(request.args.get("node") or "").strip()
    q = str(request.args.get("q") or "").strip()
    kind = str(request.args.get("type") or "").strip().lower()
    severity_min = max(0.0, safe_float(request.args.get("severity_min"), 0.0))
    if node:
        where.append("a.node=?")
        params.append(node)
    if q:
        p = like_pattern(q)
        where.append("(a.node LIKE ? OR a.vm_uuid LIKE ?)")
        params.extend([p, p])
    if kind == "network":
        where.append("a.abuse_flags LIKE '%NETWORK%'")
    elif kind == "cpu":
        where.append("a.abuse_flags LIKE '%CPU%'")
    elif kind == "disk":
        where.append("a.abuse_flags LIKE '%DISK%'")
    elif kind not in ("", "all"):
        raise ValueError("type must be one of: all, network, cpu, disk")
    if severity_min > 0:
        where.append("a.severity>=?")
        params.append(severity_min)
    return where, params

@app.route("/api/v1/me", methods=["GET"])
@require_api_scopes()
def api_v1_me():
    key = g.api_key
    return _api_response({"data": {
        "key_id": key["key_id"], "name": key["name"], "scopes": key["scopes"],
        "allowed_ips": key["allowed_ips"], "expires_at": safe_int(key.get("expires_at"), 0) or None,
        "rate_limit_per_minute": API_RATE_LIMIT_PER_MINUTE,
    }})

@app.route("/api/v1/health", methods=["GET"])
@require_api_scopes()
def api_v1_health():
    conn = db()
    try:
        conn.execute("SELECT 1").fetchone()
        current_abuse = safe_int(conn.execute(
            "SELECT COUNT(*) FROM vm_abuse_state WHERE is_abuse=1 AND last_seen>=?",
            (now_ts() - FAST_CURRENT_STALE_SECONDS,),
        ).fetchone()[0], 0)
    finally:
        conn.close()
    return _api_response({"data": {
        "status": "ok", "app_version": V48110_VERSION, "database": "ok", "current_abuse_count": current_abuse,
    }})

@app.route("/api/v1/abuse/vms", methods=["GET"])
@require_api_scopes("abuse:read")
def api_v1_abuse_vms():
    try:
        where, params = _api_abuse_filters()
    except ValueError as exc:
        return _api_error("invalid_filter", str(exc), 400)
    limit, offset = _api_limit_offset(200)
    sort = str(request.args.get("sort") or "severity").strip().lower()
    order = "ASC" if str(request.args.get("order") or "desc").strip().lower() == "asc" else "DESC"
    sort_map = {
        "severity": "a.severity", "last_seen": "a.last_seen", "abuse_since": "a.abuse_since",
        "node": "a.node", "rx_pps": "a.rx_pps", "tx_pps": "a.tx_pps",
        "rx_peak_pps": "a.rx_peak_pps", "tx_peak_pps": "a.tx_peak_pps",
        "rx_mbps": "a.rx_mbps", "tx_mbps": "a.tx_mbps",
        "cpu": "a.cpu_full_percent", "disk_read": "a.disk_read_bps", "disk_write": "a.disk_write_bps",
        "iops": "MAX(a.disk_read_iops,a.disk_write_iops)",
    }
    sort_sql = sort_map.get(sort, "a.severity")
    where_sql = " WHERE " + " AND ".join(where)
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_abuse_state a{where_sql}", params).fetchone()[0], 0)
        rows = conn.execute(
            _API_ABUSE_SELECT + where_sql + f" ORDER BY {sort_sql} {order},a.last_seen DESC,a.node COLLATE NOCASE,a.vm_uuid LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    finally:
        conn.close()
    return _api_response({"data": [_api_vm_abuse_item(row) for row in rows], "meta": {
        "count": len(rows), "total": total, "limit": limit, "offset": offset,
        "sort": sort if sort in sort_map else "severity", "order": order.lower(),
    }})

@app.route("/api/v1/abuse/vms/<vm_uuid>", methods=["GET"])
@require_api_scopes("abuse:read")
def api_v1_abuse_vm(vm_uuid):
    vm_uuid = str(vm_uuid or "").strip()
    if len(vm_uuid) > 128:
        return _api_error("invalid_vm_uuid", "VM UUID is invalid.", 400)
    node = str(request.args.get("node") or "").strip()
    where = ["a.vm_uuid=?", "a.is_abuse=1", "a.last_seen>=?"]
    params = [vm_uuid, now_ts() - FAST_CURRENT_STALE_SECONDS]
    if node:
        where.append("a.node=?")
        params.append(node)
    conn = db()
    try:
        rows = conn.execute(_API_ABUSE_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY a.last_seen DESC LIMIT 2", params).fetchall()
    finally:
        conn.close()
    if not rows:
        return _api_error("abuse_vm_not_found", "No active abuse record was found for this VM.", 404)
    if len(rows) > 1 and not node:
        return _api_error("ambiguous_vm_location", "The VM UUID exists on more than one node. Provide ?node=<node>.", 409)
    return _api_response({"data": _api_vm_abuse_item(rows[0])})

@app.route("/api/v1/abuse/events", methods=["GET"])
@require_api_scopes("abuse_events:read")
def api_v1_abuse_events():
    limit, offset = _api_limit_offset(200)
    where = []
    params = []
    node = str(request.args.get("node") or "").strip()
    vm_uuid = str(request.args.get("vm_uuid") or "").strip()
    q = str(request.args.get("q") or "").strip()
    event_type = str(request.args.get("event_type") or "").strip().lower()
    since = max(0, safe_int(request.args.get("since"), 0))
    until = max(0, safe_int(request.args.get("until"), 0))
    if node:
        where.append("e.node=?"); params.append(node)
    if vm_uuid:
        where.append("e.vm_uuid=?"); params.append(vm_uuid)
    if q:
        p = like_pattern(q); where.append("(e.node LIKE ? OR e.vm_uuid LIKE ? OR e.abuse_flags LIKE ? OR e.detail LIKE ?)"); params.extend([p,p,p,p])
    if event_type:
        if event_type not in ("started", "updated", "recovered"):
            return _api_error("invalid_filter", "event_type must be started, updated or recovered.", 400)
        where.append("e.event_type=?"); params.append(event_type)
    if since:
        where.append("e.event_time>=?"); params.append(since)
    if until:
        where.append("e.event_time<=?"); params.append(until)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_abuse_events e{where_sql}", params).fetchone()[0], 0)
        rows = conn.execute(f"""
            SELECT e.id,e.event_time,e.event_type,e.node,e.vm_uuid,e.abuse_flags,e.severity,
                   e.rx_mbps,e.tx_mbps,e.rx_pps,e.tx_pps,e.rx_peak_pps,e.tx_peak_pps,
                   e.seconds_over_rx_pps,e.seconds_over_tx_pps,
                   e.cpu_full_percent,e.cpu_core_percent,e.vcpu_current,e.cpu_streak_seconds,
                   e.disk_read_bps,e.disk_write_bps,e.disk_read_iops,e.disk_write_iops,e.disk_streak_seconds,
                   e.policy_revision,e.engine_version,e.detail
            FROM vm_abuse_events e{where_sql}
            ORDER BY e.event_time DESC,e.id DESC LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
    finally:
        conn.close()
    data = []
    for row in rows:
        data.append({
            "event_id": safe_int(row[0], 0), "event_time": safe_int(row[1], 0), "event_type": str(row[2]),
            "node": str(row[3]), "vm_uuid": str(row[4]), "flags": _api_parse_flags(row[5]),
            "severity": round(safe_float(row[6], 0), 4),
            "network": {
                "rx_mbps": round(safe_float(row[7], 0), 4), "tx_mbps": round(safe_float(row[8], 0), 4),
                "rx_pps": round(safe_float(row[9], 0), 4), "tx_pps": round(safe_float(row[10], 0), 4),
                "rx_peak_pps": round(safe_float(row[11], 0), 4), "tx_peak_pps": round(safe_float(row[12], 0), 4),
                "seconds_over_rx_pps": safe_int(row[13], 0), "seconds_over_tx_pps": safe_int(row[14], 0),
            },
            "cpu": {"full_percent": round(safe_float(row[15], 0), 4), "core_percent": round(safe_float(row[16], 0), 4), "vcpu": safe_int(row[17], 0), "streak_seconds": safe_int(row[18], 0)},
            "disk": {"read_bps": round(safe_float(row[19], 0), 4), "write_bps": round(safe_float(row[20], 0), 4), "read_iops": round(safe_float(row[21], 0), 4), "write_iops": round(safe_float(row[22], 0), 4), "streak_seconds": safe_int(row[23], 0)},
            "policy": {"revision": safe_int(row[24], 0), "engine_version": str(row[25] or "")},
            "detail": str(row[26] or ""),
        })
    return _api_response({"data": data, "meta": {"count": len(data), "total": total, "limit": limit, "offset": offset}})

def _api_vm_current_item(row):
    (
        node, vm_uuid, last_seen, interval_seconds, iface_count,
        public_mbps, private_mbps, rx_mbps, tx_mbps, total_mbps,
        rx_pps, tx_pps, total_pps, rx_peak_mbps, tx_peak_mbps, total_peak_mbps,
        rx_peak_pps, tx_peak_pps, total_peak_pps, sample_count, sample_expected, sample_max_gap, sample_quality,
        seconds_over_rx_pps, seconds_over_tx_pps, drops, errors,
        cpu_full, cpu_core, vcpu, ram_current, ram_rss, ram_available, ram_unused, ram_usable,
        disk_read, disk_write, disk_read_iops, disk_write_iops,
        status, last_bridge, last_iface,
    ) = row
    ram = vm_guest_ram_metrics(ram_current, ram_rss, ram_available, ram_unused, ram_usable)
    return {
        "node": str(node), "vm_uuid": str(vm_uuid), "last_seen": safe_int(last_seen, 0),
        "interval_seconds": safe_int(interval_seconds, 0), "state": str(status or "active"),
        "placement": {"iface_count": safe_int(iface_count, 0), "bridge": str(last_bridge or ""), "iface": str(last_iface or "")},
        "network": {
            "public_mbps": round(safe_float(public_mbps, 0), 4), "private_mbps": round(safe_float(private_mbps, 0), 4),
            "rx_mbps": round(safe_float(rx_mbps, 0), 4), "tx_mbps": round(safe_float(tx_mbps, 0), 4), "total_mbps": round(safe_float(total_mbps, 0), 4),
            "rx_pps": round(safe_float(rx_pps, 0), 4), "tx_pps": round(safe_float(tx_pps, 0), 4), "total_pps": round(safe_float(total_pps, 0), 4),
            "rx_peak_mbps": round(safe_float(rx_peak_mbps, 0), 4), "tx_peak_mbps": round(safe_float(tx_peak_mbps, 0), 4), "total_peak_mbps": round(safe_float(total_peak_mbps, 0), 4),
            "rx_peak_pps": round(safe_float(rx_peak_pps, 0), 4), "tx_peak_pps": round(safe_float(tx_peak_pps, 0), 4), "total_peak_pps": round(safe_float(total_peak_pps, 0), 4),
            "seconds_over_rx_pps": safe_int(seconds_over_rx_pps, 0), "seconds_over_tx_pps": safe_int(seconds_over_tx_pps, 0),
            "drops": safe_int(drops, 0), "errors": safe_int(errors, 0),
        },
        "sample": {"quality": str(sample_quality or "UNKNOWN"), "count": safe_int(sample_count, 0), "expected": safe_int(sample_expected, 0), "max_gap_seconds": round(safe_float(sample_max_gap, 0), 4)},
        "cpu": {"full_percent": round(safe_float(cpu_full, 0), 4), "core_percent": round(safe_float(cpu_core, 0), 4), "vcpu": safe_int(vcpu, 0)},
        "ram": {
            "assigned_kib": safe_int(ram_current, 0), "host_rss_kib": safe_int(ram_rss, 0), "available_kib": safe_int(ram_available, 0),
            "unused_kib": safe_int(ram_unused, 0), "usable_kib": safe_int(ram_usable, 0),
            "guest_stats_available": bool(ram["has_guest"]), "guest_used_kib": safe_int(ram["guest_used_kib"], 0), "guest_used_percent": round(safe_float(ram["guest_used_pct"], 0), 4),
        },
        "disk": {"read_bps": round(safe_float(disk_read, 0), 4), "write_bps": round(safe_float(disk_write, 0), 4), "read_iops": round(safe_float(disk_read_iops, 0), 4), "write_iops": round(safe_float(disk_write_iops, 0), 4)},
    }

_API_VM_CURRENT_SELECT = """
SELECT c.node,c.vm_uuid,c.last_seen,c.interval_seconds,c.iface_count,
       c.public_mbps,c.private_mbps,c.rx_mbps,c.tx_mbps,c.total_mbps,
       c.rx_pps,c.tx_pps,c.total_pps,c.rx_peak_mbps,c.tx_peak_mbps,c.total_peak_mbps,
       c.rx_peak_pps,c.tx_peak_pps,c.total_peak_pps,c.sample_count,c.sample_expected,c.sample_max_gap,c.sample_quality,
       c.seconds_over_rx_pps,c.seconds_over_tx_pps,c.drops,c.errors,
       c.cpu_full_percent,c.cpu_core_percent,c.vcpu_current,c.ram_current_kib,c.ram_rss_kib,c.ram_available_kib,
       COALESCE(c.ram_unused_kib,0),COALESCE(c.ram_usable_kib,0),
       c.disk_read_bps,c.disk_write_bps,c.disk_read_iops,c.disk_write_iops,
       COALESCE(v.status,'active'),COALESCE(v.last_bridge,''),COALESCE(v.last_iface,'')
FROM vm_current_fast c
LEFT JOIN vm_inventory v ON v.node=c.node AND v.vm_uuid=c.vm_uuid
"""

@app.route("/api/v1/vms", methods=["GET"])
@require_api_scopes("vm:read")
def api_v1_vms():
    limit, offset = _api_limit_offset(200)
    where = ["c.last_seen>=?"]
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS]
    node = str(request.args.get("node") or "").strip()
    q = str(request.args.get("q") or "").strip()
    if node:
        where.append("c.node=?"); params.append(node)
    if q:
        p = like_pattern(q); where.append("(c.node LIKE ? OR c.vm_uuid LIKE ? OR COALESCE(v.last_iface,'') LIKE ? OR COALESCE(v.last_bridge,'') LIKE ?)"); params.extend([p,p,p,p])
    sort = str(request.args.get("sort") or "last_seen").strip().lower()
    order = "ASC" if str(request.args.get("order") or "desc").strip().lower() == "asc" else "DESC"
    sort_map = {
        "last_seen": "c.last_seen", "node": "c.node", "cpu": "c.cpu_full_percent", "cpu_core": "c.cpu_core_percent",
        "ram_rss": "c.ram_rss_kib", "rx_mbps": "c.rx_mbps", "tx_mbps": "c.tx_mbps", "total_mbps": "c.total_mbps",
        "rx_pps": "c.rx_pps", "tx_pps": "c.tx_pps", "disk_read": "c.disk_read_bps", "disk_write": "c.disk_write_bps",
    }
    sort_sql = sort_map.get(sort, "c.last_seen")
    where_sql = " WHERE " + " AND ".join(where)
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_current_fast c LEFT JOIN vm_inventory v ON v.node=c.node AND v.vm_uuid=c.vm_uuid{where_sql}", params).fetchone()[0], 0)
        rows = conn.execute(_API_VM_CURRENT_SELECT + where_sql + f" ORDER BY {sort_sql} {order},c.node COLLATE NOCASE,c.vm_uuid LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
    finally:
        conn.close()
    return _api_response({"data": [_api_vm_current_item(row) for row in rows], "meta": {"count": len(rows), "total": total, "limit": limit, "offset": offset, "sort": sort if sort in sort_map else "last_seen", "order": order.lower()}})

@app.route("/api/v1/vms/<vm_uuid>/current", methods=["GET"])
@require_api_scopes("vm:read")
def api_v1_vm_current(vm_uuid):
    vm_uuid = str(vm_uuid or "").strip()
    node = str(request.args.get("node") or "").strip()
    where = ["c.vm_uuid=?", "c.last_seen>=?"]
    params = [vm_uuid, now_ts() - FAST_CURRENT_STALE_SECONDS]
    if node:
        where.append("c.node=?"); params.append(node)
    conn = db()
    try:
        rows = conn.execute(_API_VM_CURRENT_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY c.last_seen DESC LIMIT 2", params).fetchall()
    finally:
        conn.close()
    if not rows:
        return _api_error("vm_not_found", "No fresh current metrics were found for this VM.", 404)
    if len(rows) > 1 and not node:
        return _api_error("ambiguous_vm_location", "The VM UUID exists on more than one node. Provide ?node=<node>.", 409)
    return _api_response({"data": _api_vm_current_item(rows[0])})

@app.route("/api/v1/nodes", methods=["GET"])
@require_api_scopes("node:read")
def api_v1_nodes():
    limit, offset = _api_limit_offset(200)
    q = str(request.args.get("q") or "").strip()
    where = []
    params = []
    if q:
        p = like_pattern(q); where.append("(n.node LIKE ?)"); params.append(p)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM node_current_fast n{where_sql}", params).fetchone()[0], 0)
        rows = conn.execute(f"""
            SELECT n.node,n.last_seen,n.interval_seconds,n.vm_count,n.iface_count,
                   n.public_bytes,n.private_bytes,n.total_bytes,n.public_packets,n.private_packets,n.total_packets,
                   n.drops,n.errors,n.load1,n.load5,n.load15,n.cpu_count,n.cpu_percent,n.mem_total,n.mem_used,
                   n.disk_read_bps,n.disk_write_bps,n.uptime_seconds
            FROM node_current_fast n{where_sql}
            ORDER BY n.node COLLATE NOCASE LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
    finally:
        conn.close()
    data = []
    for r in rows:
        data.append({
            "node": str(r[0]), "last_seen": safe_int(r[1], 0), "interval_seconds": safe_int(r[2], 0),
            "vm_count": safe_int(r[3], 0), "iface_count": safe_int(r[4], 0),
            "network": {"public_bytes": safe_int(r[5], 0), "private_bytes": safe_int(r[6], 0), "total_bytes": safe_int(r[7], 0), "public_packets": safe_int(r[8], 0), "private_packets": safe_int(r[9], 0), "total_packets": safe_int(r[10], 0), "drops": safe_int(r[11], 0), "errors": safe_int(r[12], 0)},
            "host_context": {"load1": round(safe_float(r[13],0),4), "load5": round(safe_float(r[14],0),4), "load15": round(safe_float(r[15],0),4), "cpu_count": safe_int(r[16],0), "cpu_percent": round(safe_float(r[17],0),4), "mem_total_bytes": safe_int(r[18],0), "mem_used_bytes": safe_int(r[19],0), "disk_read_bps": round(safe_float(r[20],0),4), "disk_write_bps": round(safe_float(r[21],0),4), "uptime_seconds": safe_int(r[22],0)},
        })
    return _api_response({"data": data, "meta": {"count": len(data), "total": total, "limit": limit, "offset": offset}})

# ------------------------------ Admin API Management -----------------------

def _api_admin_actor():
    return str(session.get("admin_username") or session.get("dashboard_username") or "admin")[:120]

def _api_admin_redirect(msg="", err=""):
    return redirect(url_for("admin_api_keys_page", apimsg=msg or None, apierr=err or None))

def _api_expiration_from_form(value):
    value = str(value or "never").strip().lower()
    if value in ("", "never", "0"):
        return None
    try:
        days = int(value)
    except ValueError as exc:
        raise ValueError("Invalid expiration option.") from exc
    if days not in (7, 30, 90, 180, 365):
        raise ValueError("Invalid expiration option.")
    return now_ts() + days * 86400

def _api_scope_checkboxes(selected=None):
    selected = set(selected or API_DEFAULT_SCOPES)
    rows = []
    for scope, label in API_SUPPORTED_SCOPES.items():
        checked = "checked" if scope in selected else ""
        rows.append(f'<label class="api-scope"><input type="checkbox" name="scopes" value="{escape(scope,quote=True)}" {checked}><span><b>{escape(scope)}</b><small>{escape(label)}</small></span></label>')
    return "".join(rows)

def _api_admin_key_rows():
    conn = db()
    try:
        rows = conn.execute(
            """SELECT id,key_id,name,secret_hash,scopes_json,allowed_ips_json,is_active,
                      created_at,created_by,expires_at,last_used_at,last_used_ip,use_count,
                      revoked_at,revoked_by,rotated_from_key_id,note
               FROM api_keys ORDER BY created_at DESC,id DESC"""
        ).fetchall()
        events = conn.execute(
            """SELECT event_time,event_type,key_id,key_name,actor,source_ip,detail
               FROM api_key_events ORDER BY event_time DESC,id DESC LIMIT 100"""
        ).fetchall()
    finally:
        conn.close()
    return [_api_key_row_to_dict(row) for row in rows], events

def _api_admin_status(key):
    if not safe_int(key.get("is_active"), 0):
        return "Revoked", "status-down"
    expires = safe_int(key.get("expires_at"), 0)
    if expires and expires <= now_ts():
        return "Expired", "status-down"
    return "Active", "status-online"

def _api_docs_examples():
    base = request.url_root.rstrip("/")
    return f"""
    <div class="card api-docs-card">
      <div class="table-title-row"><div><h3>REST API v1</h3><div class="table-hint">Read-only endpoints. Send the key in the Authorization header. API responses are JSON and CORS remains disabled by default.</div></div><div class="count-badges"><span>Rate <b>{API_RATE_LIMIT_PER_MINUTE}/min</b></span><span>Max rows <b>{API_MAX_LIMIT}</b></span></div></div>
      <div class="api-endpoints">
        <code>GET /api/v1/me</code><span>Test key and show scopes</span>
        <code>GET /api/v1/health</code><span>Application/database health</span>
        <code>GET /api/v1/abuse/vms</code><span>Current sustained abuse</span>
        <code>GET /api/v1/abuse/vms/&lt;uuid&gt;?node=&lt;node&gt;</code><span>One current abuse VM</span>
        <code>GET /api/v1/abuse/events</code><span>Persistent abuse history</span>
        <code>GET /api/v1/vms</code><span>Current VM metrics</span>
        <code>GET /api/v1/vms/&lt;uuid&gt;/current?node=&lt;node&gt;</code><span>One VM current snapshot</span>
        <code>GET /api/v1/nodes</code><span>Lightweight node context</span>
        <code>GET /api/v1/bandwidth/vms</code><span>Current VM Mbps/PPS only</span>
        <code>GET /api/v1/bandwidth/vms/&lt;uuid&gt;?node=&lt;node&gt;</code><span>One VM network snapshot</span>
      </div>
      <div class="api-code"><pre>curl -sS \\
  -H 'Authorization: Bearer bwm_live_xxxxxxxxxxxx_SECRET' \\
  '{escape(base)}/api/v1/abuse/vms?limit=200'</pre></div>
    </div>"""

@app.route("/admin/api-keys", methods=["GET"])
def admin_api_keys_page():
    auth = require_admin()
    if auth:
        return auth
    keys, events = _api_admin_key_rows()
    once = session.pop("api_key_once", None)
    msg = str(request.args.get("apimsg") or "").strip()
    err = str(request.args.get("apierr") or "").strip()
    once_html = ""
    if isinstance(once, dict) and once.get("token"):
        once_html = f"""
        <div class="card api-secret-once">
          <div><span class="eyebrow">COPY NOW</span><h3>{escape(once.get('title') or 'API key created')}</h3><p>This plaintext secret is shown once and is not stored in the database.</p></div>
          <div class="api-secret-line"><code id="api-secret-once">{escape(once['token'])}</code><button class="btn" type="button" data-copy="{escape(once['token'],quote=True)}">Copy key</button></div>
        </div>"""

    key_rows = []
    for key in keys:
        status_label, status_class = _api_admin_status(key)
        scopes = "".join(f'<span class="api-chip">{escape(scope)}</span>' for scope in key.get("scopes") or []) or "-"
        allow = "<br>".join(escape(item) for item in key.get("allowed_ips") or []) or "Any source IP"
        expiry = fmt_full(key.get("expires_at")) if key.get("expires_at") else "Never"
        used = fmt_full(key.get("last_used_at")) if key.get("last_used_at") else "Never"
        actions = ""
        if status_label == "Active":
            actions = f"""
            <form method="post" action="{url_for('admin_api_key_rotate')}" onsubmit="return confirm('Rotate this API key? The current key will stop working immediately.')">
              <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="key_id" value="{escape(key['key_id'],quote=True)}"><button class="btn" type="submit">Rotate</button>
            </form>
            <form method="post" action="{url_for('admin_api_key_revoke')}" onsubmit="return confirm('Revoke this API key?')">
              <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="key_id" value="{escape(key['key_id'],quote=True)}"><button class="btn-danger" type="submit">Revoke</button>
            </form>"""
        else:
            actions = '<span class="table-hint">No action</span>'
        key_rows.append(f"""
        <tr>
          <td><b>{escape(key['name'])}</b><small class="muted-line">{escape(API_KEY_PREFIX)}_{escape(key['key_id'])}_…</small>{f'<small class="muted-line">{escape(key.get("note") or "")}</small>' if key.get('note') else ''}</td>
          <td><span class="status {status_class}">{escape(status_label)}</span><small class="muted-line">Created {escape(fmt_full(key['created_at']))}<br>by {escape(key.get('created_by') or '-')}</small></td>
          <td><div class="api-chip-wrap">{scopes}</div></td>
          <td><small>{allow}</small></td>
          <td><b>{escape(used)}</b><small class="muted-line">IP {escape(key.get('last_used_ip') or '-')}<br>flush count {safe_int(key.get('use_count'),0):,}</small></td>
          <td>{escape(expiry)}</td>
          <td><div class="api-actions">{actions}</div></td>
        </tr>""")
    if not key_rows:
        key_rows.append('<tr><td colspan="7" class="empty">No API keys have been created</td></tr>')

    event_rows = []
    for event_time, event_type, key_id, key_name, actor, source_ip, detail in events:
        event_rows.append(f"<tr><td>{escape(fmt_full(event_time))}</td><td><b>{escape(event_type)}</b></td><td>{escape(key_name or '-')}<small class='muted-line'>{escape(key_id or '-')}</small></td><td>{escape(actor or '-')}</td><td>{escape(source_ip or '-')}</td><td>{escape(detail or '')}</td></tr>")
    if not event_rows:
        event_rows.append('<tr><td colspan="6" class="empty">No API management events</td></tr>')

    content = f"""
    <style>
    .api-grid{{display:grid;grid-template-columns:minmax(320px,.8fr) minmax(500px,1.2fr);gap:16px;align-items:start}}
    .api-scope-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0 14px}}.api-scope{{display:flex;gap:9px;padding:10px;border:1px solid var(--line,#d0d5dd);border-radius:10px;align-items:flex-start}}.api-scope input{{margin-top:3px}}.api-scope span{{display:grid;gap:2px}}.api-scope small,.muted-line{{display:block;color:#667085;font-size:11px;margin-top:4px}}
    .api-chip-wrap{{display:flex;gap:5px;flex-wrap:wrap}}.api-chip{{display:inline-flex;padding:4px 7px;border-radius:999px;background:#eaf2ff;color:#175cd3;font-size:10px;font-weight:800}}.api-actions{{display:flex;gap:6px;flex-wrap:wrap}}.api-actions form{{margin:0}}
    .api-secret-once{{border:2px solid #12b76a!important;background:linear-gradient(135deg,#ecfdf3,#fff)!important}}.api-secret-line{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}.api-secret-line code{{font-size:13px;word-break:break-all;padding:11px;border-radius:8px;background:#101828;color:#fff;flex:1;min-width:260px}}
    .api-endpoints{{display:grid;grid-template-columns:minmax(290px,.8fr) 1fr;gap:8px 14px;margin-top:14px}}.api-endpoints code{{padding:7px 9px;background:#f2f4f7;border-radius:7px;font-size:11px}}.api-endpoints span{{font-size:12px;color:#475467;align-self:center}}.api-code pre{{white-space:pre-wrap;word-break:break-word;background:#101828;color:#e6edf3;padding:14px;border-radius:10px;margin:14px 0 0}}
    .api-form-row{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.api-form-row label,.api-form-full{{display:grid;gap:5px;font-size:12px;font-weight:800}}.api-form-row input,.api-form-row select,.api-form-full input,.api-form-full textarea{{width:100%;box-sizing:border-box}}.api-form-full{{margin-top:12px}}.api-form-full textarea{{min-height:78px;resize:vertical}}.api-table{{min-width:1240px}}
    html[data-theme=dark] .api-chip{{background:#17365d;color:#b9d7ff}}html[data-theme=dark] .api-scope{{border-color:#344054}}html[data-theme=dark] .api-endpoints code{{background:#1d2939;color:#d0d5dd}}html[data-theme=dark] .api-secret-once{{background:linear-gradient(135deg,#0f2f24,#172033)!important}}
    @media(max-width:1050px){{.api-grid{{grid-template-columns:1fr}}}}@media(max-width:650px){{.api-scope-grid,.api-form-row,.api-endpoints{{grid-template-columns:1fr}}}}
    </style>
    <div class="card page-hero"><div><span class="eyebrow">ADMIN / API</span><h2>API Management</h2><p>Create separate read-only keys for Windows apps, automation and external integrations.</p></div><div class="hero-meta"><span>Agent token <b>separate</b></span><span>Secrets <b>hash only</b></span></div></div>
    {_v490_admin_nav('api')}
    {f'<div class="success-box">{escape(msg)}</div>' if msg else ''}{f'<div class="error-box">{escape(err)}</div>' if err else ''}
    {once_html}
    <div class="api-grid">
      <div class="card">
        <div class="table-title-row"><div><h3>Create API key</h3><div class="table-hint">The generated key is displayed once. Save it in Windows Credential Manager or another protected secret store.</div></div></div>
        <form method="post" action="{url_for('admin_api_key_create')}">
          <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}">
          <div class="api-form-row"><label>Name<input name="name" maxlength="80" placeholder="Windows Abuse Monitor" required></label><label>Expiration<select name="expiration"><option value="never">Never</option><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option><option value="180">180 days</option><option value="365">365 days</option></select></label></div>
          <div class="api-form-full"><span>Permissions</span><div class="api-scope-grid">{_api_scope_checkboxes()}</div></div>
          <label class="api-form-full">Allowed source IP/CIDR <textarea name="allowed_ips" placeholder="Optional. One per line, for example:\n203.0.113.10\n10.20.0.0/16"></textarea><small>Leave empty to allow any source. When using Nginx, configure BW_API_TRUST_PROXY=1 only for a trusted local proxy.</small></label>
          <label class="api-form-full">Note<input name="note" maxlength="500" placeholder="Optional owner or purpose"></label>
          <div style="margin-top:14px"><button class="btn" type="submit">Generate API key</button></div>
        </form>
      </div>
      {_api_docs_examples()}
    </div>
    <div class="card vm-table-card"><div class="table-title-row"><div><h3>API keys</h3><div class="table-hint">{len(keys)} key record(s). Rotate creates a new key and revokes the old key atomically.</div></div></div><div class="table-wrap"><table class="api-table"><thead><tr><th>Name / ID</th><th>Status</th><th>Scopes</th><th>Allowed IP</th><th>Last used</th><th>Expires</th><th>Actions</th></tr></thead><tbody>{''.join(key_rows)}</tbody></table></div></div>
    <details class="card"><summary><b>API key audit</b> <span class="table-hint">Latest 100 management/auth-denial events</span></summary><div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>Time</th><th>Event</th><th>Key</th><th>Actor</th><th>Source IP</th><th>Detail</th></tr></thead><tbody>{''.join(event_rows)}</tbody></table></div></details>
    """
    return page("API Management", content)

@app.route("/admin/api-keys/create", methods=["POST"])
def admin_api_key_create():
    auth = require_admin()
    if auth:
        return auth
    try:
        name = request.form.get("name") or ""
        scopes = request.form.getlist("scopes")
        allowed_ips = request.form.get("allowed_ips") or ""
        expires_at = _api_expiration_from_form(request.form.get("expiration"))
        note = request.form.get("note") or ""
        actor = _api_admin_actor()
        conn = db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            key_id, token = _api_create_key_record(conn, name, scopes, allowed_ips, expires_at, actor, note=note)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        session["api_key_once"] = {"token": token, "title": f"API key created: {name}", "key_id": key_id}
        return _api_admin_redirect(msg="API key created. Copy the plaintext key now; it will not be shown again.")
    except Exception as exc:
        app.logger.exception("Could not create API key")
        return _api_admin_redirect(err=str(exc)[:500])

@app.route("/admin/api-keys/revoke", methods=["POST"])
def admin_api_key_revoke():
    auth = require_admin()
    if auth:
        return auth
    key_id = str(request.form.get("key_id") or "").strip().lower()
    actor = _api_admin_actor()
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        key = _api_get_key_by_id(conn, key_id)
        if not key:
            raise ValueError("API key not found.")
        if not safe_int(key.get("is_active"), 0):
            raise ValueError("API key is already revoked.")
        conn.execute("UPDATE api_keys SET is_active=0,revoked_at=?,revoked_by=? WHERE key_id=?", (now_ts(), actor, key_id))
        _api_log_event(conn, "KEY_REVOKED", key_id=key_id, key_name=key.get("name"), actor=actor, source_ip=client_ip(), detail="Revoked from Admin")
        conn.commit()
        return _api_admin_redirect(msg=f"API key {key.get('name')} was revoked.")
    except Exception as exc:
        conn.rollback()
        return _api_admin_redirect(err=str(exc)[:500])
    finally:
        conn.close()

@app.route("/admin/api-keys/rotate", methods=["POST"])
def admin_api_key_rotate():
    auth = require_admin()
    if auth:
        return auth
    old_key_id = str(request.form.get("key_id") or "").strip().lower()
    actor = _api_admin_actor()
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        old = _api_get_key_by_id(conn, old_key_id)
        if not old:
            raise ValueError("API key not found.")
        if not safe_int(old.get("is_active"), 0):
            raise ValueError("Only an active API key can be rotated.")
        expires_at = safe_int(old.get("expires_at"), 0) or None
        if expires_at and expires_at <= now_ts():
            expires_at = None
        new_key_id, token = _api_create_key_record(
            conn, old.get("name") or "Rotated API Key", old.get("scopes") or [], old.get("allowed_ips") or [],
            expires_at, actor, note=old.get("note") or "", rotated_from=old_key_id,
        )
        conn.execute("UPDATE api_keys SET is_active=0,revoked_at=?,revoked_by=? WHERE key_id=?", (now_ts(), actor, old_key_id))
        _api_log_event(conn, "KEY_ROTATED", key_id=old_key_id, key_name=old.get("name"), actor=actor, source_ip=client_ip(), detail=f"replacement={new_key_id}")
        conn.commit()
        session["api_key_once"] = {"token": token, "title": f"API key rotated: {old.get('name')}", "key_id": new_key_id}
        return _api_admin_redirect(msg="API key rotated. The old key is revoked; copy the new key now.")
    except Exception as exc:
        conn.rollback()
        return _api_admin_redirect(err=str(exc)[:500])
    finally:
        conn.close()

# Add API Management to the final sectioned Admin navigation without rewriting
# the entire v48.10.6 admin page.
_v48110_admin_nav_base = _v490_admin_nav

def _v490_admin_nav(active):
    html = _v48110_admin_nav_base(active)
    api_link = f'<a class="{"active" if active == "api" else ""}" href="{url_for("admin_api_keys_page")}">API</a>'
    return html.replace("</nav>", api_link + "</nav>", 1)

@app.route("/api/v1/bandwidth/vms", methods=["GET"])
@require_api_scopes("bandwidth:read")
def api_v1_bandwidth_vms():
    """Return only current VM network/bandwidth telemetry for lightweight clients."""
    limit, offset = _api_limit_offset(200)
    where = ["c.last_seen>=?"]
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS]
    node = str(request.args.get("node") or "").strip()
    q = str(request.args.get("q") or "").strip()
    if node:
        where.append("c.node=?")
        params.append(node)
    if q:
        p = like_pattern(q)
        where.append("(c.node LIKE ? OR c.vm_uuid LIKE ?)")
        params.extend([p, p])
    where_sql = " WHERE " + " AND ".join(where)
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_current_fast c{where_sql}", params).fetchone()[0], 0)
        rows = conn.execute(f"""
            SELECT c.node,c.vm_uuid,c.last_seen,c.interval_seconds,
                   c.public_mbps,c.private_mbps,c.rx_mbps,c.tx_mbps,c.total_mbps,
                   c.rx_pps,c.tx_pps,c.total_pps,
                   c.rx_peak_mbps,c.tx_peak_mbps,c.total_peak_mbps,
                   c.rx_peak_pps,c.tx_peak_pps,c.total_peak_pps,
                   c.seconds_over_rx_pps,c.seconds_over_tx_pps,
                   c.drops,c.errors,c.sample_quality,c.sample_count,c.sample_expected,c.sample_max_gap
            FROM vm_current_fast c{where_sql}
            ORDER BY c.total_mbps DESC,c.total_pps DESC,c.last_seen DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
    finally:
        conn.close()
    data = []
    for r in rows:
        data.append({
            "node": str(r[0]), "vm_uuid": str(r[1]), "last_seen": safe_int(r[2], 0),
            "interval_seconds": safe_int(r[3], 0),
            "network": {
                "public_mbps": round(safe_float(r[4], 0), 4), "private_mbps": round(safe_float(r[5], 0), 4),
                "rx_mbps": round(safe_float(r[6], 0), 4), "tx_mbps": round(safe_float(r[7], 0), 4), "total_mbps": round(safe_float(r[8], 0), 4),
                "rx_pps": round(safe_float(r[9], 0), 4), "tx_pps": round(safe_float(r[10], 0), 4), "total_pps": round(safe_float(r[11], 0), 4),
                "rx_peak_mbps": round(safe_float(r[12], 0), 4), "tx_peak_mbps": round(safe_float(r[13], 0), 4), "total_peak_mbps": round(safe_float(r[14], 0), 4),
                "rx_peak_pps": round(safe_float(r[15], 0), 4), "tx_peak_pps": round(safe_float(r[16], 0), 4), "total_peak_pps": round(safe_float(r[17], 0), 4),
                "seconds_over_rx_pps": safe_int(r[18], 0), "seconds_over_tx_pps": safe_int(r[19], 0),
                "drops": safe_int(r[20], 0), "errors": safe_int(r[21], 0),
            },
            "sample": {"quality": str(r[22] or "UNKNOWN"), "count": safe_int(r[23], 0), "expected": safe_int(r[24], 0), "max_gap_seconds": round(safe_float(r[25], 0), 4)},
        })
    return _api_response({"data": data, "meta": {"count": len(data), "total": total, "limit": limit, "offset": offset}})

@app.route("/api/v1/bandwidth/vms/<vm_uuid>", methods=["GET"])
@require_api_scopes("bandwidth:read")
def api_v1_bandwidth_vm(vm_uuid):
    vm_uuid = str(vm_uuid or "").strip()
    node = str(request.args.get("node") or "").strip()
    # Keep the single-VM response compatible with the list endpoint.
    where = ["c.vm_uuid=?", "c.last_seen>=?"]
    params = [vm_uuid, now_ts() - FAST_CURRENT_STALE_SECONDS]
    if node:
        where.append("c.node=?")
        params.append(node)
    conn = db()
    try:
        rows = conn.execute(f"""
            SELECT c.node,c.vm_uuid,c.last_seen,c.interval_seconds,
                   c.public_mbps,c.private_mbps,c.rx_mbps,c.tx_mbps,c.total_mbps,
                   c.rx_pps,c.tx_pps,c.total_pps,
                   c.rx_peak_mbps,c.tx_peak_mbps,c.total_peak_mbps,
                   c.rx_peak_pps,c.tx_peak_pps,c.total_peak_pps,
                   c.seconds_over_rx_pps,c.seconds_over_tx_pps,
                   c.drops,c.errors,c.sample_quality,c.sample_count,c.sample_expected,c.sample_max_gap
            FROM vm_current_fast c
            WHERE {" AND ".join(where)}
            ORDER BY c.last_seen DESC LIMIT 2
        """, params).fetchall()
    finally:
        conn.close()
    if not rows:
        return _api_error("vm_not_found", "No fresh bandwidth metrics were found for this VM.", 404)
    if len(rows) > 1 and not node:
        return _api_error("ambiguous_vm_location", "The VM UUID exists on more than one node. Provide ?node=<node>.", 409)
    r = rows[0]
    data = {
        "node": str(r[0]), "vm_uuid": str(r[1]), "last_seen": safe_int(r[2], 0), "interval_seconds": safe_int(r[3], 0),
        "network": {
            "public_mbps": round(safe_float(r[4], 0), 4), "private_mbps": round(safe_float(r[5], 0), 4),
            "rx_mbps": round(safe_float(r[6], 0), 4), "tx_mbps": round(safe_float(r[7], 0), 4), "total_mbps": round(safe_float(r[8], 0), 4),
            "rx_pps": round(safe_float(r[9], 0), 4), "tx_pps": round(safe_float(r[10], 0), 4), "total_pps": round(safe_float(r[11], 0), 4),
            "rx_peak_mbps": round(safe_float(r[12], 0), 4), "tx_peak_mbps": round(safe_float(r[13], 0), 4), "total_peak_mbps": round(safe_float(r[14], 0), 4),
            "rx_peak_pps": round(safe_float(r[15], 0), 4), "tx_peak_pps": round(safe_float(r[16], 0), 4), "total_peak_pps": round(safe_float(r[17], 0), 4),
            "seconds_over_rx_pps": safe_int(r[18], 0), "seconds_over_tx_pps": safe_int(r[19], 0), "drops": safe_int(r[20], 0), "errors": safe_int(r[21], 0),
        },
        "sample": {"quality": str(r[22] or "UNKNOWN"), "count": safe_int(r[23], 0), "expected": safe_int(r[24], 0), "max_gap_seconds": round(safe_float(r[25], 0), 4)},
    }
    return _api_response({"data": data})

