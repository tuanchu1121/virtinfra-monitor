"""PostgreSQL compatibility and pooling layer for VirtInfra Monitor v50.

The application UI and business logic historically used Python's sqlite3 API.
This module preserves the small DB-API surface used by VirtInfra Monitor while all
runtime data is stored in PostgreSQL/TimescaleDB.  It is intentionally isolated
so routes and abuse/storage logic can be refactored incrementally without
running two databases or duplicating data.
"""
from __future__ import annotations

import atexit
import os
import re
import threading
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Iterable, Sequence

try:
    import psycopg
    from psycopg import errors, sql as pg_sql
    from psycopg_pool import ConnectionPool
except Exception as exc:  # pragma: no cover - installer provides dependencies
    raise RuntimeError(
        "VirtInfra Monitor v50 requires psycopg 3 and psycopg_pool. "
        "Install requirements.txt before importing the application."
    ) from exc

# sqlite3-compatible exception names used by the legacy business logic.
Error = psycopg.Error
DatabaseError = psycopg.DatabaseError
OperationalError = psycopg.OperationalError
IntegrityError = psycopg.IntegrityError
ProgrammingError = psycopg.ProgrammingError
InterfaceError = psycopg.InterfaceError
Binary = psycopg.Binary

DEFAULT_DSN = "postgresql://bw_monitor@127.0.0.1:5432/bw_monitor"
_DSN = (
    os.environ.get("BW_DATABASE_URL")
    or os.environ.get("BW_POSTGRES_DSN")
    or os.environ.get("DATABASE_URL")
    or DEFAULT_DSN
)
_POOL_MIN = max(1, int(os.environ.get("BW_DB_POOL_MIN", "2")))
_POOL_MAX = max(_POOL_MIN, int(os.environ.get("BW_DB_POOL_MAX", "20")))
_POOL_TIMEOUT = max(1.0, float(os.environ.get("BW_DB_POOL_TIMEOUT", "10")))
_STATEMENT_TIMEOUT_MS = max(0, int(os.environ.get("BW_DB_STATEMENT_TIMEOUT_MS", "30000")))
_LOCK_TIMEOUT_MS = max(0, int(os.environ.get("BW_DB_LOCK_TIMEOUT_MS", "10000")))
_IDLE_TX_TIMEOUT_MS = max(0, int(os.environ.get("BW_DB_IDLE_TX_TIMEOUT_MS", "60000")))

_pool: ConnectionPool | None = None
_pool_lock = threading.RLock()

# Tables whose id column is generated.  The wrapper appends RETURNING id when
# callers use Cursor.lastrowid, matching sqlite3 behavior.
_SERIAL_TABLES = {
    # Only tables whose callers actually consume Cursor.lastrowid. Keeping this
    # list small avoids a RETURNING round trip on high-volume metric inserts.
    "maintenance_jobs", "retention_runs", "dashboard_users", "api_keys",
    "vm_abuse_events", "vm_abuse_incidents", "node_groups",
}

_RE_COLLATE_NOCASE = re.compile(r"\s+COLLATE\s+NOCASE\b", re.I)
_RE_WITHOUT_ROWID = re.compile(r"\s+WITHOUT\s+ROWID\b", re.I)
_RE_AUTOINC_ID = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s+INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
    re.I,
)
_RE_INSERT_OR = re.compile(
    r'^\s*INSERT\s+OR\s+(REPLACE|IGNORE)\s+INTO\s+([\w\."]+)\s*\((.*?)\)',
    re.I | re.S,
)
_RE_INSERT = re.compile(r'^\s*INSERT\s+INTO\s+([\w\."]+)\s*(?:\((.*?)\))?', re.I | re.S)
_RE_GROUP_CONCAT_DISTINCT = re.compile(r"GROUP_CONCAT\s*\(\s*DISTINCT\s+([^\)]+?)\s*\)", re.I)
_RE_GROUP_CONCAT_SEP = re.compile(r"GROUP_CONCAT\s*\(\s*([^,\)]+?)\s*,\s*('(?:''|[^'])*')\s*\)", re.I)
_RE_GROUP_CONCAT = re.compile(r"GROUP_CONCAT\s*\(\s*([^\)]+?)\s*\)", re.I)
_RE_STRFTIME_NOW = re.compile(r"strftime\s*\(\s*'%s'\s*,\s*'now'\s*\)", re.I)
_RE_TEMP_PREFIX = re.compile(r"\btemp\.([A-Za-z_][A-Za-z0-9_]*)\b", re.I)
_RE_PRAGMA_TABLE_INFO = re.compile(r"^\s*PRAGMA\s+table_info\s*\(\s*([\w\"]+)\s*\)\s*;?\s*$", re.I)
_RE_PRAGMA = re.compile(r"^\s*PRAGMA\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:=\s*([^;]+))?\s*;?\s*$", re.I)
_RE_CREATE_TABLE = re.compile(r"^\s*CREATE\s+(TEMP(?:ORARY)?\s+)?TABLE\s+", re.I)
_RE_CREATE_TABLE_NAME = re.compile(r"^\s*CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w\.\"]+)", re.I)
_RE_TABLE_LIKE_CLAUSE = re.compile(
    r"(\(\s*)LIKE(\s+(?:[A-Za-z_][A-Za-z0-9_$]*|\"(?:\"\"|[^\"])+\")"
    r"(?:\.(?:[A-Za-z_][A-Za-z0-9_$]*|\"(?:\"\"|[^\"])+\"))*"
    r"(?:\s+(?:INCLUDING|EXCLUDING)\s+"
    r"(?:COMMENTS|COMPRESSION|CONSTRAINTS|DEFAULTS|GENERATED|IDENTITY|INDEXES|STATISTICS|STORAGE|ALL))*"
    r"\s*\))",
    re.I,
)

# Append-only history tables become Timescale hypertables after application
# schema initialization. Their generated id is intentionally not a standalone
# primary key because every unique index on a hypertable must include the time
# partition column. The application never relies on id uniqueness for these
# tables.
_HISTORY_IDENTITY_TABLES = {
    "usage", "vm_perf_stats", "node_host_stats", "node_filesystem_stats",
    "node_physical_net_stats", "agent_health_stats",
}


def _configure_connection(conn: psycopg.Connection) -> None:
    """Apply safe per-session settings used by every pooled connection."""
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC'")
        cur.execute("SET application_name = 'virtinfra-monitor-v50'")
        if _STATEMENT_TIMEOUT_MS:
            cur.execute("SELECT set_config('statement_timeout', %s, false)", (f"{_STATEMENT_TIMEOUT_MS}ms",))
        if _LOCK_TIMEOUT_MS:
            cur.execute("SELECT set_config('lock_timeout', %s, false)", (f"{_LOCK_TIMEOUT_MS}ms",))
        if _IDLE_TX_TIMEOUT_MS:
            cur.execute("SELECT set_config('idle_in_transaction_session_timeout', %s, false)", (f"{_IDLE_TX_TIMEOUT_MS}ms",))
    conn.commit()


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                conninfo=_DSN,
                min_size=_POOL_MIN,
                max_size=_POOL_MAX,
                timeout=_POOL_TIMEOUT,
                open=True,
                configure=_configure_connection,
                kwargs={"connect_timeout": max(2, int(_POOL_TIMEOUT))},
                name="virtinfra-monitor-v50",
            )
        return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


atexit.register(close_pool)


def database_size() -> int:
    """Return the current PostgreSQL database size in bytes."""
    conn = connect()
    try:
        row = conn.execute("SELECT pg_database_size(current_database())").fetchone()
        return int(row[0] or 0) if row else 0
    finally:
        conn.close()


def wal_size() -> int:
    """Approximate WAL directory size visible to PostgreSQL, when permitted."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(size),0)::bigint FROM pg_ls_waldir()"
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        conn.close()


def database_stats() -> dict[str, int]:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT pg_database_size(current_database())::bigint,
                   current_setting('block_size')::bigint,
                   COALESCE((SELECT SUM(n_dead_tup)::bigint FROM pg_stat_user_tables),0)
            """
        ).fetchone() or (0, 8192, 0)
        db_bytes, block_size, dead_rows = map(int, row)
        return {
            "db_size": db_bytes,
            "wal_size": wal_size(),
            "shm_size": 0,
            "page_size": block_size,
            "page_count": db_bytes // max(1, block_size),
            "freelist_count": dead_rows,
            "reusable_bytes": 0,
        }
    finally:
        conn.close()


def _split_sql_script(script: str) -> list[str]:
    """Split a SQL script on semicolons outside quoted strings/comments."""
    out: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    dollar_tag: str | None = None
    line_comment = False
    block_comment = False
    i = 0
    n = len(script)
    while i < n:
        ch = script[i]
        nxt = script[i + 1] if i + 1 < n else ""
        if line_comment:
            buf.append(ch)
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 2
                block_comment = False
            else:
                i += 1
            continue
        if quote:
            buf.append(ch)
            if ch == quote:
                if nxt == quote:
                    buf.append(nxt)
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if dollar_tag:
            if script.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
            else:
                buf.append(ch)
                i += 1
            continue
        if ch == "-" and nxt == "-":
            buf.extend([ch, nxt]); i += 2; line_comment = True; continue
        if ch == "/" and nxt == "*":
            buf.extend([ch, nxt]); i += 2; block_comment = True; continue
        if ch in ("'", '"'):
            quote = ch; buf.append(ch); i += 1; continue
        if ch == "$":
            m = re.match(r"\$[A-Za-z_0-9]*\$", script[i:])
            if m:
                dollar_tag = m.group(0); buf.append(dollar_tag); i += len(dollar_tag); continue
        if ch == ";":
            statement = "".join(buf).strip()
            if statement:
                out.append(statement)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    statement = "".join(buf).strip()
    if statement:
        out.append(statement)
    return out


def _qmarks_to_psycopg(sql: str) -> str:
    """Convert SQLite qmark placeholders outside strings/comments to %s."""
    out: list[str] = []
    quote: str | None = None
    line_comment = False
    block_comment = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if line_comment:
            out.append(ch)
            if ch == "\n": line_comment = False
            i += 1; continue
        if block_comment:
            out.append(ch)
            if ch == "*" and nxt == "/":
                out.append(nxt); i += 2; block_comment = False
            else: i += 1
            continue
        if quote:
            out.append(ch)
            if ch == quote:
                if nxt == quote:
                    out.append(nxt); i += 2; continue
                quote = None
            i += 1; continue
        if ch == "-" and nxt == "-":
            out.extend([ch, nxt]); i += 2; line_comment = True; continue
        if ch == "/" and nxt == "*":
            out.extend([ch, nxt]); i += 2; block_comment = True; continue
        if ch in ("'", '"'):
            quote = ch; out.append(ch); i += 1; continue
        if ch == "?":
            out.append("%s")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _named_to_psycopg(sql: str) -> str:
    """Convert SQLite ``:name`` parameters to psycopg ``%(name)s``."""
    return re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", r"%(\1)s", sql)


def _escape_psycopg_percent(sql: str) -> str:
    """Escape literal percent signs for psycopg parameterized execution.

    Psycopg uses percent placeholders even when the percent occurs inside a
    quoted SQL literal. Doubling every non-placeholder percent is safe: the
    adapter receives only application SQL, and psycopg restores ``%%`` to a
    literal ``%`` before PostgreSQL parses it.
    """
    out: list[str] = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch != "%":
            out.append(ch)
            i += 1
            continue
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if nxt == "(":
            end = sql.find(")s", i + 2)
            if end != -1 and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", sql[i + 2:end]):
                out.append(sql[i:end + 2])
                i = end + 2
                continue
        if nxt in {"s", "b", "t", "%"}:
            out.extend([ch, nxt])
            i += 2
        else:
            out.append("%%")
            i += 1
    return "".join(out)


def _translate_scalar_minmax(sql: str) -> str:
    """Translate SQLite scalar MAX/MIN(a,b,...) to PostgreSQL GREATEST/LEAST.

    Aggregate MAX(expr) and MIN(expr) are left untouched. The scanner handles
    nested functions and quoted strings, which a flat regular expression cannot.
    """
    pattern = re.compile(r"\b(MAX|MIN)\s*\(", re.I)
    while True:
        changed = False
        out: list[str] = []
        pos = 0
        for match in pattern.finditer(sql):
            if match.start() < pos:
                continue
            start = match.end() - 1
            depth = 0
            quote: str | None = None
            comma = False
            i = start
            while i < len(sql):
                ch = sql[i]
                nxt = sql[i + 1] if i + 1 < len(sql) else ""
                if quote:
                    if ch == quote:
                        if nxt == quote:
                            i += 2
                            continue
                        quote = None
                    i += 1
                    continue
                if ch in ("'", '"'):
                    quote = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                elif ch == "," and depth == 1:
                    comma = True
                i += 1
            if i >= len(sql):
                continue
            if not comma:
                continue
            out.append(sql[pos:match.start()])
            out.append("GREATEST(" if match.group(1).upper() == "MAX" else "LEAST(")
            out.append(sql[start + 1:i])
            out.append(")")
            pos = i + 1
            changed = True
            break
        if not changed:
            return sql
        out.append(sql[pos:])
        sql = "".join(out)


def _normalize_table_name(raw: str) -> str:
    return raw.strip().strip('"').split(".")[-1]


def _parse_columns(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip().strip('"') for part in raw.split(",") if part.strip()]


def _unique_conflict_columns(raw_conn: psycopg.Connection, table: str, insert_columns: list[str]) -> list[str]:
    """Find the best PK/unique index fully covered by the INSERT columns."""
    table = _normalize_table_name(table)
    with raw_conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.indisprimary, i.indisunique,
                   array_agg(a.attname ORDER BY x.ord) AS cols
              FROM pg_class t
              JOIN pg_namespace ns ON ns.oid=t.relnamespace
              JOIN pg_index i ON i.indrelid=t.oid
              JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS x(attnum,ord) ON true
              JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=x.attnum
             WHERE t.relname=%s
               AND ns.nspname = ANY(current_schemas(true))
               AND (i.indisprimary OR i.indisunique)
               AND i.indpred IS NULL
             GROUP BY i.indexrelid,i.indisprimary,i.indisunique
             ORDER BY i.indisprimary DESC, array_length(array_agg(a.attname ORDER BY x.ord),1)
            """,
            (table,),
        )
        rows = cur.fetchall()
    offered = set(insert_columns)
    for _primary, _unique, cols in rows:
        cols = list(cols or [])
        if cols and set(cols).issubset(offered):
            return cols
    return []


def _translate_insert_or(conn: psycopg.Connection, sql: str) -> str:
    match = _RE_INSERT_OR.match(sql)
    if not match:
        return sql
    mode, raw_table, raw_cols = match.groups()
    cols = _parse_columns(raw_cols)
    translated = re.sub(r"^\s*INSERT\s+OR\s+(?:REPLACE|IGNORE)\s+INTO", "INSERT INTO", sql, count=1, flags=re.I)
    if re.search(r"\bON\s+CONFLICT\b", translated, re.I):
        return translated
    translated = translated.rstrip().rstrip(";")
    if mode.upper() == "IGNORE":
        return translated + " ON CONFLICT DO NOTHING"
    keys = _unique_conflict_columns(conn, raw_table, cols)
    if not keys:
        # This should only occur for a malformed legacy table.  Avoid data loss:
        # insert instead of emulating SQLite REPLACE as delete+insert.
        return translated + " ON CONFLICT DO NOTHING"
    updates = [c for c in cols if c not in set(keys)]
    target = ",".join(f'"{c}"' for c in keys)
    if updates:
        assignments = ",".join(f'"{c}"=EXCLUDED."{c}"' for c in updates)
        return translated + f" ON CONFLICT ({target}) DO UPDATE SET {assignments}"
    return translated + f" ON CONFLICT ({target}) DO NOTHING"


def _translate_create_table(sql: str) -> str:
    sql = _RE_WITHOUT_ROWID.sub("", sql)
    match = _RE_CREATE_TABLE_NAME.match(sql)
    table = _normalize_table_name(match.group(1)) if match else ""
    if table in _HISTORY_IDENTITY_TABLES:
        sql = _RE_AUTOINC_ID.sub(
            lambda m: f'{m.group(1)} BIGINT GENERATED BY DEFAULT AS IDENTITY', sql
        )
    else:
        sql = _RE_AUTOINC_ID.sub(lambda m: f'{m.group(1)} BIGSERIAL PRIMARY KEY', sql)
    # SQLite INTEGER is signed 64-bit. BIGINT preserves byte counters and Unix
    # timestamps without truncation.
    sql = re.sub(r"\bINTEGER\b", "BIGINT", sql, flags=re.I)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql, flags=re.I)
    return sql


def _translate_like_operators(sql: str) -> str:
    """Translate SQLite search LIKE to PostgreSQL ILIKE without corrupting
    PostgreSQL's CREATE TABLE ... (LIKE source INCLUDING ...) clone clause.

    The compatibility layer historically replaced every LIKE token globally.
    Native COPY staging introduced PostgreSQL table cloning, where LIKE is DDL
    syntax rather than a comparison operator. Protect those clauses, translate
    the remaining operators, then restore the exact DDL text.
    """
    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        marker = f"__VI_TABLE_CLONE_{len(protected)}__"
        protected.append(match.group(0))
        return marker

    translated = _RE_TABLE_LIKE_CLAUSE.sub(protect, sql)
    translated = re.sub(r"\bLIKE\b", "ILIKE", translated, flags=re.I)
    for index, original in enumerate(protected):
        translated = translated.replace(f"__VI_TABLE_CLONE_{index}__", original)
    return translated


def translate_sql(raw_conn: psycopg.Connection, sql: str) -> str:
    sql = str(sql or "").strip()
    if not sql:
        return sql
    sql = _RE_TEMP_PREFIX.sub(r"\1", sql)
    sql = _RE_COLLATE_NOCASE.sub("", sql)
    sql = _RE_WITHOUT_ROWID.sub("", sql)
    # SQLite BLOB maps directly to PostgreSQL BYTEA in both CREATE TABLE and
    # additive ALTER TABLE migrations.
    sql = re.sub(r"\bBLOB\b", "BYTEA", sql, flags=re.I)
    sql = re.sub(r"\browid\b", "ctid", sql, flags=re.I)
    sql = re.sub(r"\bchar\s*\(", "chr(", sql, flags=re.I)
    sql = _RE_STRFTIME_NOW.sub("EXTRACT(EPOCH FROM clock_timestamp())::bigint", sql)
    sql = _RE_GROUP_CONCAT_DISTINCT.sub(r"STRING_AGG(DISTINCT \1, ',')", sql)
    sql = _RE_GROUP_CONCAT_SEP.sub(r"STRING_AGG(\1, \2)", sql)
    sql = _RE_GROUP_CONCAT.sub(r"STRING_AGG(\1, ',')", sql)
    sql = re.sub(r"\bIFNULL\s*\(", "COALESCE(", sql, flags=re.I)
    if _RE_CREATE_TABLE.match(sql):
        sql = _translate_create_table(sql)
    if _RE_INSERT_OR.match(sql):
        sql = _translate_insert_or(raw_conn, sql)
    sql = _translate_scalar_minmax(sql)
    # SQLite LIKE is ASCII case-insensitive by default. ILIKE preserves the
    # search/filter behavior users already have in the dashboard. PostgreSQL
    # CREATE TABLE ... (LIKE source ...) is protected by the helper.
    sql = _translate_like_operators(sql)
    sql = _qmarks_to_psycopg(sql)
    return sql


def _sqlite_value(value: Any) -> Any:
    """Normalize PostgreSQL numeric aggregates to SQLite-like Python values."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def _sqlite_row(row: Sequence[Any] | None):
    if row is None:
        return None
    return tuple(_sqlite_value(value) for value in row)


class CompatCursor:
    def __init__(self, owner: "CompatConnection", cursor: psycopg.Cursor | None = None):
        self._owner = owner
        self._cursor = cursor or owner._raw.cursor()
        self._rows: list[tuple[Any, ...]] | None = None
        self._row_index = 0
        self.lastrowid: int | None = None
        self.rowcount: int = -1
        self.description = None

    def _set_rows(self, rows: Iterable[Sequence[Any]], description: Any = None) -> "CompatCursor":
        self._rows = [_sqlite_row(r) for r in rows]
        self._row_index = 0
        self.rowcount = len(self._rows)
        self.description = description
        return self

    def _pragma(self, sql: str) -> bool:
        table_match = _RE_PRAGMA_TABLE_INFO.match(sql)
        if table_match:
            table = table_match.group(1).strip('"')
            with self._owner._raw.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.attnum-1, a.attname,
                           format_type(a.atttypid,a.atttypmod),
                           CASE WHEN a.attnotnull THEN 1 ELSE 0 END,
                           pg_get_expr(d.adbin,d.adrelid),
                           CASE WHEN EXISTS (
                             SELECT 1 FROM pg_index i
                              WHERE i.indrelid=a.attrelid AND i.indisprimary
                                AND a.attnum=ANY(i.indkey)
                           ) THEN 1 ELSE 0 END
                      FROM pg_attribute a
                      LEFT JOIN pg_attrdef d
                        ON d.adrelid=a.attrelid AND d.adnum=a.attnum
                     WHERE a.attrelid=to_regclass(%s)
                       AND a.attnum>0 AND NOT a.attisdropped
                     ORDER BY a.attnum
                    """,
                    (table,),
                )
                rows = cur.fetchall()
            self._set_rows(rows)
            return True
        match = _RE_PRAGMA.match(sql)
        if not match:
            return False
        name = match.group(1).lower()
        if name == "page_size":
            with self._owner._raw.cursor() as cur:
                cur.execute("SELECT current_setting('block_size')::bigint")
                return bool(self._set_rows(cur.fetchall()))
        if name == "page_count":
            with self._owner._raw.cursor() as cur:
                cur.execute("SELECT pg_database_size(current_database()) / current_setting('block_size')::bigint")
                return bool(self._set_rows(cur.fetchall()))
        if name == "freelist_count":
            with self._owner._raw.cursor() as cur:
                cur.execute("SELECT COALESCE(SUM(n_dead_tup),0)::bigint FROM pg_stat_user_tables")
                return bool(self._set_rows(cur.fetchall()))
        if name == "journal_mode":
            self._set_rows([("wal",)])
            return True
        if name in {
            "busy_timeout", "synchronous", "temp_store", "cache_size", "mmap_size",
            "wal_autocheckpoint", "journal_size_limit", "foreign_keys", "optimize",
            "wal_checkpoint", "integrity_check", "quick_check",
        }:
            if name in {"integrity_check", "quick_check"}:
                self._set_rows([("ok",)])
            elif name == "wal_checkpoint":
                self._set_rows([(0, 0, 0)])
            else:
                self._set_rows([])
            return True
        self._set_rows([])
        return True

    def _compat_catalog(self, sql: str, params: Any) -> bool:
        """Handle the few legacy catalog probes without creating SQLite-named DB objects.

        The application historically queried sqlite_master/sqlite_sequence only
        for table discovery and cosmetic sequence resets. PostgreSQL's catalog
        is used directly here; sequence-reset operations are deliberately no-op
        because PostgreSQL identity sequences do not affect correctness.
        """
        normalized = " ".join(str(sql or "").strip().split())
        low = normalized.lower()
        if "from sqlite_master" in low:
            if low.startswith("select name from sqlite_master"):
                with self._owner._raw.cursor() as cur:
                    cur.execute(
                        "SELECT tablename FROM pg_catalog.pg_tables "
                        "WHERE schemaname='public' ORDER BY tablename"
                    )
                    self._set_rows(cur.fetchall())
                return True
            name = None
            if params:
                if isinstance(params, Mapping):
                    name = str(next(iter(params.values())))
                else:
                    name = str(params[0])
            else:
                match = re.search(r"\bname\s*=\s*'([^']+)'", normalized, re.I)
                if match:
                    name = match.group(1)
            if name == "sqlite_sequence":
                self._set_rows([])
                return True
            if name:
                with self._owner._raw.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM pg_catalog.pg_tables "
                        "WHERE schemaname='public' AND tablename=%s",
                        (name,),
                    )
                    self._set_rows(cur.fetchall())
                return True
        if re.match(r"^\s*(?:delete\s+from|insert\s+into)\s+sqlite_sequence\b", low, re.I):
            self._set_rows([])
            self.rowcount = 0
            return True
        return False

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> "CompatCursor":
        self._rows = None
        self._row_index = 0
        self.lastrowid = None
        self.description = None
        params_obj: Any
        if isinstance(params, Mapping):
            params_obj = dict(params)
        else:
            params_obj = tuple(params or ())
        stripped = str(sql or "").strip()
        if not stripped:
            self.rowcount = -1
            return self
        if self._compat_catalog(stripped, params_obj):
            return self
        if self._pragma(stripped):
            return self
        if re.match(r"^\s*BEGIN(?:\s+IMMEDIATE)?\b", stripped, re.I):
            # psycopg automatically opens a transaction on the first real SQL
            # statement. Legacy SQLite BEGIN / BEGIN IMMEDIATE statements are
            # therefore compatibility no-ops. This avoids duplicate-BEGIN
            # warnings on pooled connections while preserving atomic commit and
            # rollback behavior for every following statement.
            self.rowcount = -1
            return self
        if re.match(r"^\s*VACUUM\b", stripped, re.I):
            # VACUUM cannot run inside a transaction.  Commit the caller's work,
            # run it through a short autocommit session, then resume normally.
            self._owner.commit()
            old = self._owner._raw.autocommit
            self._owner._raw.autocommit = True
            try:
                self._cursor.execute("VACUUM (ANALYZE)")
            finally:
                self._owner._raw.autocommit = old
            self.rowcount = -1
            return self
        translated = translate_sql(self._owner._raw, stripped)
        insert_match = _RE_INSERT.match(translated)
        serial_table = _normalize_table_name(insert_match.group(1)) if insert_match else ""
        wants_last_id = (
            serial_table in _SERIAL_TABLES
            and not re.search(r"\bRETURNING\b", translated, re.I)
            and not re.search(r"\bON\s+CONFLICT\s+DO\s+NOTHING\b", translated, re.I)
            and not re.search(r"\bSELECT\b", translated[insert_match.end():] if insert_match else "", re.I)
        )
        if wants_last_id:
            translated = translated.rstrip().rstrip(";") + " RETURNING id"
        if params_obj:
            if isinstance(params_obj, Mapping):
                translated = _escape_psycopg_percent(_named_to_psycopg(translated))
            else:
                translated = _escape_psycopg_percent(translated)
            self._cursor.execute(translated, params_obj)
        else:
            self._cursor.execute(translated)
        self.description = self._cursor.description
        self.rowcount = self._cursor.rowcount
        if wants_last_id:
            row = self._cursor.fetchone()
            self.lastrowid = int(row[0]) if row else None
            self.description = None
        if self.rowcount and self.rowcount > 0:
            self._owner.total_changes += self.rowcount
        return self

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> "CompatCursor":
        stripped = str(sql or "").strip()
        if self._pragma(stripped):
            return self
        items = list(seq_of_params)
        translated = translate_sql(self._owner._raw, stripped)
        if items and isinstance(items[0], Mapping):
            translated = _named_to_psycopg(translated)
        translated = _escape_psycopg_percent(translated)
        self._cursor.executemany(translated, items)
        self.rowcount = self._cursor.rowcount
        self.description = self._cursor.description
        if self.rowcount and self.rowcount > 0:
            self._owner.total_changes += self.rowcount
        return self

    def fetchone(self):
        if self._rows is not None:
            if self._row_index >= len(self._rows):
                return None
            row = self._rows[self._row_index]
            self._row_index += 1
            return row
        return _sqlite_row(self._cursor.fetchone())

    def fetchmany(self, size: int = 1):
        if self._rows is not None:
            start = self._row_index
            end = min(len(self._rows), start + max(0, int(size)))
            self._row_index = end
            return self._rows[start:end]
        return [_sqlite_row(row) for row in self._cursor.fetchmany(size)]

    def fetchall(self):
        if self._rows is not None:
            rows = self._rows[self._row_index:]
            self._row_index = len(self._rows)
            return rows
        return [_sqlite_row(row) for row in self._cursor.fetchall()]

    def close(self) -> None:
        try:
            self._cursor.close()
        except Exception:
            pass

    def __iter__(self):
        if self._rows is not None:
            while True:
                row = self.fetchone()
                if row is None:
                    break
                yield row
        else:
            for row in self._cursor:
                yield _sqlite_row(row)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class CompatConnection:
    def __init__(self, raw: psycopg.Connection, pool: ConnectionPool):
        self._raw = raw
        self._pool = pool
        self._closed = False
        self.total_changes = 0

    def cursor(self) -> CompatCursor:
        return CompatCursor(self)

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> CompatCursor:
        return self.cursor().execute(sql, params)

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> CompatCursor:
        return self.cursor().executemany(sql, seq_of_params)

    def copy_rows(
        self,
        table: str,
        columns: Sequence[str],
        rows: Iterable[Sequence[Any]],
    ) -> int:
        """Stream Python rows to PostgreSQL using native ``COPY FROM STDIN``.

        The method intentionally bypasses the SQLite SQL translator because COPY
        is PostgreSQL-native. Identifiers are composed with psycopg.sql.Identifier,
        so callers may safely pass an internal schema-qualified table name.
        Rows participate in the caller's existing transaction and are rolled back
        together with the rest of an Agent push if any later stage fails.
        """
        table_parts = [part for part in str(table or "").split(".") if part]
        column_names = [str(column or "") for column in columns]
        if not table_parts or not column_names:
            raise ValueError("COPY requires a table and at least one column")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in table_parts):
            raise ValueError(f"unsafe COPY table identifier: {table!r}")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column) for column in column_names):
            raise ValueError(f"unsafe COPY column identifier in {column_names!r}")

        table_sql = pg_sql.SQL(".").join(pg_sql.Identifier(part) for part in table_parts)
        columns_sql = pg_sql.SQL(",").join(pg_sql.Identifier(column) for column in column_names)
        statement = pg_sql.SQL("COPY {} ({}) FROM STDIN").format(table_sql, columns_sql)

        count = 0
        with self._raw.cursor() as cursor:
            with cursor.copy(statement) as copy:
                for row in rows:
                    values = tuple(row)
                    if len(values) != len(column_names):
                        raise ValueError(
                            f"COPY row width {len(values)} does not match {len(column_names)} columns"
                        )
                    copy.write_row(values)
                    count += 1
        self.total_changes += count
        return count

    def executescript(self, script: str) -> "CompatConnection":
        for statement in _split_sql_script(script):
            self.execute(statement)
        return self

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Never return a failed/idle transaction to the pool.
        try:
            status = self._raw.info.transaction_status
            if status != psycopg.pq.TransactionStatus.IDLE:
                self._raw.rollback()
        except Exception:
            pass
        self._pool.putconn(self._raw)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False


def connect(database: str | None = None, timeout: float | int = 30, **kwargs: Any) -> CompatConnection:
    """Return a pooled PostgreSQL connection with sqlite3-like methods.

    ``database`` is accepted for source compatibility and intentionally ignored;
    the single source of truth is BW_DATABASE_URL/BW_POSTGRES_DSN.
    """
    pool = _get_pool()
    raw = pool.getconn(timeout=max(1.0, min(float(timeout or _POOL_TIMEOUT), _POOL_TIMEOUT)))
    return CompatConnection(raw, pool)


# sqlite3 type aliases referenced in annotations.
Connection = CompatConnection
Cursor = CompatCursor


def healthcheck() -> dict[str, Any]:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT current_database(), current_user, version(), pg_database_size(current_database())"
        ).fetchone()
        return {
            "ok": True,
            "database": row[0],
            "user": row[1],
            "version": row[2],
            "bytes": int(row[3] or 0),
        }
    finally:
        conn.close()
