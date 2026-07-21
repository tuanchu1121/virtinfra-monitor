"""Selective configuration backup/restore for VirtInfra Monitor.

Configuration archives deliberately exclude monitoring/inventory/history data.
They contain only administrator-managed users, API credentials, safe UI/policy
settings, Node Group definitions and stable Node-to-Group assignments.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import maintenance_native

FORMAT_NAME = "virtinfra-configuration-backup"
FORMAT_VERSION = 1
BACKUP_ID_RE = re.compile(r"^config-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.zip$")
EXPECTED_ENTRIES = {"configuration.json", "metadata.json", "MANIFEST.sha256"}

SAFE_SETTING_KEYS = {
    "simple_theme_settings_v3",
    "simple_theme_settings_v4",
    "bw_queue_auto_refresh",
    "abuse_network_enabled",
    "abuse_network_pps",
    "abuse_network_required_seconds",
    "abuse_network_mbps_enabled",
    "abuse_network_avg_mbps",
    "abuse_network_mbps_required_seconds",
    "abuse_cpu_enabled",
    "abuse_cpu_full_percent",
    "abuse_cpu_required_seconds",
    "abuse_ram_enabled",
    "abuse_ram_rss_percent",
    "abuse_ram_guest_used_percent",
    "abuse_ram_low_usable_percent",
    "abuse_ram_required_seconds",
    "abuse_disk_enabled",
    "abuse_disk_read_bps",
    "abuse_disk_write_bps",
    "abuse_disk_bps",
    "abuse_disk_iops",
    "abuse_disk_required_seconds",
}
VALID_SECTIONS = {"users", "api_keys", "settings", "groups", "node_group_mapping"}
VALID_ROLES = {"viewer", "admin", "super_admin"}


def backup_root() -> Path:
    root = Path(os.environ.get("BW_CONFIGURATION_BACKUP_ROOT", "/var/backups/bw-monitor/configuration"))
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root.resolve()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_version() -> str:
    for path in (Path(__file__).with_name("DEPLOY_VERSION"), Path(__file__).parent.parent / "VERSION"):
        try:
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            continue
    return os.environ.get("BW_RELEASE_VERSION", "unknown")


def _safe_backup_path(backup_id: str) -> Path:
    name = str(backup_id or "").strip()
    if not BACKUP_ID_RE.fullmatch(name):
        raise ValueError("Invalid configuration backup id")
    target = (backup_root() / name).resolve()
    try:
        target.relative_to(backup_root())
    except ValueError as exc:
        raise ValueError("Unsafe configuration backup path") from exc
    return target


def _fetch_dicts(cur, query: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cur.execute(query, tuple(params))
    columns = [str(item.name) for item in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _export_configuration(actor: str) -> dict[str, Any]:
    conn = maintenance_native.dedicated_connection(
        application_name="virtinfra-configuration-backup:export",
        statement_timeout_ms=60_000,
        lock_timeout_ms=15_000,
    )
    try:
        with conn.cursor() as cur:
            users = _fetch_dicts(cur, """
                SELECT username,password_hash,role,is_active,created_at,updated_at
                  FROM public.dashboard_users
                 ORDER BY LOWER(username),id
            """)
            api_keys = _fetch_dicts(cur, """
                SELECT key_id,name,secret_hash,scopes_json,allowed_ips_json,
                       is_active,created_at,created_by,expires_at,revoked_at,
                       revoked_by,rotated_from_key_id,note
                  FROM public.api_keys
                 ORDER BY id
            """)
            settings = _fetch_dicts(cur, """
                SELECT key,value,updated_at
                  FROM public.admin_settings
                 WHERE key = ANY(%s)
                 ORDER BY key
            """, (list(sorted(SAFE_SETTING_KEYS)),))
            groups = _fetch_dicts(cur, """
                SELECT name,description,country_code,is_active,hidden_at
                  FROM public.node_groups
                 WHERE COALESCE(is_system,0)=0
                 ORDER BY LOWER(name),id
            """)
            mappings = _fetch_dicts(cur, """
                SELECT m.node,g.name AS group_name
                  FROM public.node_group_memberships m
                  JOIN public.node_groups g ON g.id=m.group_id
                 WHERE COALESCE(g.is_system,0)=0
                 ORDER BY m.node
            """)
    finally:
        conn.close()
    return {
        "users": users,
        "api_keys": api_keys,
        "settings": settings,
        "groups": groups,
        "node_group_mapping": mappings,
        "exported_by": str(actor or "super_admin"),
    }


def create_configuration_backup(actor: str, *, reason: str = "manual", protect: bool = False) -> dict[str, Any]:
    now = int(time.time())
    name = time.strftime("config-%Y%m%dT%H%M%SZ-", time.gmtime(now)) + secrets.token_hex(6) + ".zip"
    target = _safe_backup_path(name)
    configuration = _export_configuration(actor)
    counts = {section: len(configuration.get(section, [])) for section in VALID_SECTIONS}
    metadata = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "app_version": _release_version(),
        "created_at": now,
        "created_by": str(actor or "super_admin"),
        "reason": str(reason or "manual")[:120],
        "sections": sorted(VALID_SECTIONS),
        "counts": counts,
    }
    config_bytes = _canonical_json(configuration)
    metadata_bytes = _canonical_json(metadata)
    manifest = (
        f"{_sha256_bytes(config_bytes)}  configuration.json\n"
        f"{_sha256_bytes(metadata_bytes)}  metadata.json\n"
    ).encode("ascii")
    tmp = target.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("configuration.json", config_bytes)
        archive.writestr("metadata.json", metadata_bytes)
        archive.writestr("MANIFEST.sha256", manifest)
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)
    if protect:
        target.with_suffix(target.suffix + ".protected").write_text(str(now), encoding="ascii")
        os.chmod(target.with_suffix(target.suffix + ".protected"), 0o600)
    result = verify_configuration_backup(name)
    result.update({"backup_id": name, "path": str(target), "sha256": _sha256_file(target)})
    return result


def _parse_manifest(raw: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            raise ValueError("Invalid configuration backup manifest")
        relative = parts[1].lstrip("* ").replace("\\", "/")
        path = PurePosixPath(relative)
        if path.is_absolute() or len(path.parts) != 1 or path.name not in {"configuration.json", "metadata.json"}:
            raise ValueError("Unsafe configuration backup manifest path")
        values[path.name] = parts[0].lower()
    if set(values) != {"configuration.json", "metadata.json"}:
        raise ValueError("Configuration backup manifest is incomplete")
    return values


def verify_configuration_backup(backup_id: str) -> dict[str, Any]:
    target = _safe_backup_path(backup_id)
    if not target.is_file() or target.stat().st_size <= 0:
        raise FileNotFoundError("Configuration backup does not exist")
    with zipfile.ZipFile(target, "r") as archive:
        names = set(archive.namelist())
        if names != EXPECTED_ENTRIES:
            raise ValueError("Configuration backup contains unexpected or missing files")
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or len(path.parts) != 1 or item.file_size > 64 * 1024 * 1024:
                raise ValueError("Unsafe configuration backup archive entry")
        config_bytes = archive.read("configuration.json")
        metadata_bytes = archive.read("metadata.json")
        manifest = _parse_manifest(archive.read("MANIFEST.sha256").decode("ascii", "strict"))
    if not hmac.compare_digest(_sha256_bytes(config_bytes), manifest["configuration.json"]):
        raise ValueError("Configuration payload checksum mismatch")
    if not hmac.compare_digest(_sha256_bytes(metadata_bytes), manifest["metadata.json"]):
        raise ValueError("Configuration metadata checksum mismatch")
    configuration = json.loads(config_bytes.decode("utf-8"))
    metadata = json.loads(metadata_bytes.decode("utf-8"))
    if metadata.get("format") != FORMAT_NAME or int(metadata.get("format_version", 0)) != FORMAT_VERSION:
        raise ValueError("Unsupported configuration backup format")
    if not isinstance(configuration, dict):
        raise ValueError("Invalid configuration payload")
    for section in VALID_SECTIONS:
        if not isinstance(configuration.get(section, []), list):
            raise ValueError(f"Invalid configuration section: {section}")
    return {
        "status": "verified",
        "metadata": metadata,
        "configuration": configuration,
        "size_bytes": target.stat().st_size,
        "protected": target.with_suffix(target.suffix + ".protected").exists(),
        "sha256": _sha256_file(target),
    }


def list_configuration_backups() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(backup_root().glob("config-*.zip"), reverse=True):
        if not BACKUP_ID_RE.fullmatch(path.name):
            continue
        try:
            info = verify_configuration_backup(path.name)
            metadata = info["metadata"]
            rows.append({
                "backup_id": path.name,
                "status": "verified",
                "created_at": int(metadata.get("created_at", 0) or 0),
                "created_by": str(metadata.get("created_by", "")),
                "reason": str(metadata.get("reason", "")),
                "app_version": str(metadata.get("app_version", "")),
                "counts": metadata.get("counts", {}),
                "size_bytes": int(info["size_bytes"]),
                "protected": bool(info["protected"]),
                "sha256": str(info["sha256"]),
            })
        except Exception as exc:
            rows.append({
                "backup_id": path.name,
                "status": "corrupted",
                "created_at": int(path.stat().st_mtime),
                "created_by": "",
                "reason": str(exc)[:200],
                "app_version": "",
                "counts": {},
                "size_bytes": path.stat().st_size,
                "protected": path.with_suffix(path.suffix + ".protected").exists(),
                "sha256": _sha256_file(path),
            })
    return rows


def set_configuration_backup_protected(backup_id: str, protected: bool) -> bool:
    target = _safe_backup_path(backup_id)
    if not target.is_file():
        raise FileNotFoundError("Configuration backup does not exist")
    marker = target.with_suffix(target.suffix + ".protected")
    if protected:
        marker.write_text(str(int(time.time())), encoding="ascii")
        os.chmod(marker, 0o600)
    else:
        marker.unlink(missing_ok=True)
    return protected


def delete_configuration_backup(backup_id: str) -> None:
    target = _safe_backup_path(backup_id)
    if target.with_suffix(target.suffix + ".protected").exists():
        raise PermissionError("Protected configuration backup must be unprotected before deletion")
    target.unlink()


def configuration_backup_path(backup_id: str) -> Path:
    target = _safe_backup_path(backup_id)
    if not target.is_file():
        raise FileNotFoundError("Configuration backup does not exist")
    return target


def _clean_sections(sections: Iterable[str] | None) -> set[str]:
    values = {str(item).strip().lower() for item in (sections or VALID_SECTIONS)}
    selected = values & VALID_SECTIONS
    if not selected:
        raise ValueError("Select at least one configuration section")
    return selected


def _validate_actor(cur, actor_user_id: int, actor_username: str) -> None:
    cur.execute("""
        SELECT username,role,is_active
          FROM public.dashboard_users
         WHERE id=%s
         FOR UPDATE
    """, (int(actor_user_id),))
    row = cur.fetchone()
    if not row:
        raise PermissionError("Current super_admin no longer exists")
    if str(row[0]) != str(actor_username) or str(row[1]) != "super_admin" or int(row[2] or 0) != 1:
        raise PermissionError("Current account is no longer an active super_admin")


def restore_configuration_backup(
    backup_id: str,
    *,
    actor_user_id: int,
    actor_username: str,
    sections: Iterable[str] | None = None,
) -> dict[str, Any]:
    verified = verify_configuration_backup(backup_id)
    payload = verified["configuration"]
    selected = _clean_sections(sections)
    now = int(time.time())
    conn = maintenance_native.dedicated_connection(
        application_name="virtinfra-configuration-backup:restore",
        statement_timeout_ms=0,
        lock_timeout_ms=120_000,
    )
    counts = {section: 0 for section in selected}
    try:
        with conn.cursor() as cur:
            maintenance_native.advisory_xact_lock(cur, maintenance_native.MAINTENANCE_GLOBAL_LOCK)
            _validate_actor(cur, actor_user_id, actor_username)

            if "users" in selected:
                cur.execute("DELETE FROM public.dashboard_users WHERE id<>%s", (int(actor_user_id),))
                for item in payload.get("users", []):
                    username = str(item.get("username", "")).strip()
                    role = str(item.get("role", "viewer")).strip().lower()
                    password_hash = str(item.get("password_hash", ""))
                    if not username or username == actor_username or role not in VALID_ROLES or not password_hash:
                        continue
                    cur.execute("""
                        INSERT INTO public.dashboard_users(
                            username,password_hash,role,is_active,created_at,updated_at,last_login
                        ) VALUES (%s,%s,%s,%s,%s,%s,NULL)
                        ON CONFLICT(username) DO UPDATE SET
                            password_hash=EXCLUDED.password_hash,
                            role=EXCLUDED.role,
                            is_active=EXCLUDED.is_active,
                            updated_at=EXCLUDED.updated_at,
                            last_login=NULL
                    """, (
                        username, password_hash, role,
                        1 if int(item.get("is_active", 1) or 0) else 0,
                        int(item.get("created_at", now) or now), now,
                    ))
                    counts["users"] += 1

            if "api_keys" in selected:
                cur.execute("TRUNCATE TABLE public.api_keys RESTART IDENTITY CASCADE")
                for item in payload.get("api_keys", []):
                    key_id = str(item.get("key_id", "")).strip()
                    secret_hash = str(item.get("secret_hash", ""))
                    if not key_id or not secret_hash:
                        continue
                    cur.execute("""
                        INSERT INTO public.api_keys(
                            key_id,name,secret_hash,scopes_json,allowed_ips_json,is_active,
                            created_at,created_by,expires_at,last_used_at,last_used_ip,use_count,
                            revoked_at,revoked_by,rotated_from_key_id,note
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,'',0,%s,%s,%s,%s)
                    """, (
                        key_id, str(item.get("name", "")), secret_hash,
                        str(item.get("scopes_json", "[]")), str(item.get("allowed_ips_json", "[]")),
                        1 if int(item.get("is_active", 1) or 0) else 0,
                        int(item.get("created_at", now) or now), str(item.get("created_by", "")),
                        item.get("expires_at"), item.get("revoked_at"), str(item.get("revoked_by", "")),
                        str(item.get("rotated_from_key_id", "")), str(item.get("note", "")),
                    ))
                    counts["api_keys"] += 1

            if "settings" in selected:
                cur.execute("DELETE FROM public.admin_settings WHERE key = ANY(%s)", (list(sorted(SAFE_SETTING_KEYS)),))
                for item in payload.get("settings", []):
                    key = str(item.get("key", ""))
                    if key not in SAFE_SETTING_KEYS:
                        continue
                    cur.execute("""
                        INSERT INTO public.admin_settings(key,value,updated_at)
                        VALUES (%s,%s,%s)
                        ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=EXCLUDED.updated_at
                    """, (key, str(item.get("value", "")), now))
                    counts["settings"] += 1

            group_ids: dict[str, int] = {}
            if "groups" in selected:
                cur.execute("""
                    SELECT id FROM public.node_groups WHERE is_system=1 ORDER BY id LIMIT 1
                """)
                system = cur.fetchone()
                if not system:
                    cur.execute("""
                        INSERT INTO public.node_groups(
                            name,description,country_code,is_active,is_system,created_at,updated_at,hidden_at
                        ) VALUES ('Ungrouped','Default group for nodes without an explicit assignment','',1,1,%s,%s,NULL)
                        RETURNING id
                    """, (now, now))
                    system_id = int(cur.fetchone()[0])
                else:
                    system_id = int(system[0])
                cur.execute("UPDATE public.node_group_memberships SET group_id=%s,assigned_at=%s,assigned_by=%s", (system_id, now, actor_username))
                cur.execute("DELETE FROM public.node_groups WHERE COALESCE(is_system,0)=0")
                for item in payload.get("groups", []):
                    name = str(item.get("name", "")).strip()
                    if not name or name.lower() == "ungrouped":
                        continue
                    cur.execute("""
                        INSERT INTO public.node_groups(
                            name,description,country_code,is_active,is_system,created_at,updated_at,hidden_at
                        ) VALUES (%s,%s,%s,%s,0,%s,%s,%s)
                        ON CONFLICT((LOWER(name))) DO UPDATE SET
                            description=EXCLUDED.description,
                            country_code=EXCLUDED.country_code,
                            is_active=EXCLUDED.is_active,
                            updated_at=EXCLUDED.updated_at,
                            hidden_at=EXCLUDED.hidden_at
                        RETURNING id
                    """, (
                        name, str(item.get("description", "")), str(item.get("country_code", ""))[:2].upper(),
                        1 if int(item.get("is_active", 1) or 0) else 0,
                        now, now, item.get("hidden_at"),
                    ))
                    group_ids[name.lower()] = int(cur.fetchone()[0])
                    counts["groups"] += 1
            else:
                cur.execute("SELECT id,name FROM public.node_groups WHERE COALESCE(is_system,0)=0")
                group_ids = {str(name).lower(): int(group_id) for group_id, name in cur.fetchall()}

            if "node_group_mapping" in selected:
                cur.execute("TRUNCATE TABLE public.pending_node_group_restore")
                for item in payload.get("node_group_mapping", []):
                    node = str(item.get("node", "")).strip()
                    group_name = str(item.get("group_name", "")).strip()
                    group_id = group_ids.get(group_name.lower())
                    if not node or not group_id:
                        continue
                    cur.execute("SELECT 1 FROM public.node_inventory WHERE node=%s", (node,))
                    if cur.fetchone():
                        cur.execute("""
                            INSERT INTO public.node_group_memberships(node,group_id,assigned_at,assigned_by)
                            VALUES (%s,%s,%s,%s)
                            ON CONFLICT(node) DO UPDATE SET
                                group_id=EXCLUDED.group_id,
                                assigned_at=EXCLUDED.assigned_at,
                                assigned_by=EXCLUDED.assigned_by
                        """, (node, group_id, now, actor_username))
                    else:
                        cur.execute("""
                            INSERT INTO public.pending_node_group_restore(node,group_name,restored_at,restored_by)
                            VALUES (%s,%s,%s,%s)
                            ON CONFLICT(node) DO UPDATE SET
                                group_name=EXCLUDED.group_name,
                                restored_at=EXCLUDED.restored_at,
                                restored_by=EXCLUDED.restored_by
                        """, (node, group_name, now, actor_username))
                    counts["node_group_mapping"] += 1

            if "users" in selected:
                cur.execute("""
                    INSERT INTO public.admin_settings(key,value,updated_at)
                    VALUES ('app_secret_key',%s,%s)
                    ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=EXCLUDED.updated_at
                """, (secrets.token_urlsafe(64), now))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "backup_id": backup_id,
        "sections": sorted(selected),
        "restored": counts,
        "actor": actor_username,
        "finished_at": int(time.time()),
        "sessions_rotated": "users" in selected,
    }
