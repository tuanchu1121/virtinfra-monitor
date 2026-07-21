"""Safe catalog operations for full emergency PostgreSQL backups.

Full backups are disaster-recovery artifacts only.  The web UI may verify,
protect, download the database dump, or delete them.  It intentionally exposes
no in-place restore operation.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import shutil
import json
import time
from pathlib import Path, PurePosixPath
from typing import Any

BACKUP_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}$")
REQUIRED_FILES = {"database.dump", "database.list", "SHA256SUMS"}


def backup_root() -> Path:
    root = Path(os.environ.get("BW_BACKUP_ROOT", "/var/backups/bw-monitor"))
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root.resolve()


def _safe_backup_dir(backup_id: str) -> Path:
    name = str(backup_id or "").strip()
    if not BACKUP_ID_RE.fullmatch(name):
        raise ValueError("Invalid full emergency backup id")
    target = (backup_root() / name).resolve()
    try:
        target.relative_to(backup_root())
    except ValueError as exc:
        raise ValueError("Unsafe full emergency backup path") from exc
    return target


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_manifest(backup_dir: Path) -> dict[str, str]:
    manifest_file = backup_dir / "SHA256SUMS"
    if not manifest_file.is_file():
        raise ValueError("Full backup SHA256SUMS is missing")
    values: dict[str, str] = {}
    for raw in manifest_file.read_text(encoding="utf-8", errors="strict").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            raise ValueError("Invalid full backup manifest line")
        relative = parts[1].lstrip("* ").replace("\\", "/")
        while relative.startswith("./"):
            relative = relative[2:]
        logical = PurePosixPath(relative)
        if logical.is_absolute() or any(part in {"", ".", ".."} for part in logical.parts):
            raise ValueError("Unsafe full backup manifest path")
        normalized = logical.as_posix()
        target = (backup_dir / Path(*logical.parts)).resolve()
        try:
            target.relative_to(backup_dir.resolve())
        except ValueError as exc:
            raise ValueError("Unsafe full backup manifest path") from exc
        if not target.is_file():
            raise ValueError(f"Full backup file is missing: {normalized}")
        actual = _sha256_file(target)
        expected = parts[0].lower()
        if not hmac.compare_digest(actual, expected):
            raise ValueError(f"Full backup checksum mismatch: {normalized}")
        if normalized in values and not hmac.compare_digest(values[normalized], actual):
            raise ValueError(f"Conflicting full backup manifest entry: {normalized}")
        values[normalized] = actual
    if not {"database.dump", "database.list"}.issubset(values):
        raise ValueError("Full backup manifest does not cover database.dump and database.list")
    return values


def _read_metadata(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    metadata = path / "metadata.txt"
    if not metadata.is_file():
        return result
    for raw in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _verified_marker_path(target: Path) -> Path:
    return target / ".verified.json"


def record_verified_backup(
    backup_id: str,
    *,
    dump_sha256: str,
    dump_bytes: int,
    manifest_files_verified: int,
) -> dict[str, Any]:
    target = _safe_backup_dir(backup_id)
    dump = target / "database.dump"
    manifest = target / "SHA256SUMS"
    if not target.is_dir() or not dump.is_file() or not manifest.is_file():
        raise FileNotFoundError("Full emergency backup is incomplete")
    payload = {
        "dump_sha256": str(dump_sha256),
        "dump_bytes": int(dump_bytes),
        "dump_mtime_ns": int(dump.stat().st_mtime_ns),
        "manifest_mtime_ns": int(manifest.stat().st_mtime_ns),
        "manifest_files_verified": int(manifest_files_verified),
        "verified_at": int(time.time()),
    }
    marker = _verified_marker_path(target)
    tmp = marker.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, marker)
    return payload


def _cached_verification(target: Path) -> dict[str, Any] | None:
    marker = _verified_marker_path(target)
    dump = target / "database.dump"
    manifest = target / "SHA256SUMS"
    if not marker.is_file() or not dump.is_file() or not manifest.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if int(payload.get("dump_bytes", -1)) != dump.stat().st_size:
            return None
        if int(payload.get("dump_mtime_ns", -1)) != dump.stat().st_mtime_ns:
            return None
        if int(payload.get("manifest_mtime_ns", -1)) != manifest.stat().st_mtime_ns:
            return None
        if not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("dump_sha256", ""))):
            return None
        return payload
    except Exception:
        return None


def verify_emergency_backup(backup_id: str) -> dict[str, Any]:
    target = _safe_backup_dir(backup_id)
    if not target.is_dir():
        raise FileNotFoundError("Full emergency backup does not exist")
    missing = [name for name in REQUIRED_FILES if not (target / name).is_file()]
    if missing:
        raise ValueError("Full emergency backup is incomplete: " + ", ".join(sorted(missing)))
    dump = target / "database.dump"
    catalog = target / "database.list"
    if dump.stat().st_size <= 0 or catalog.stat().st_size <= 0:
        raise ValueError("Full emergency backup dump or catalog is empty")
    verified = _verify_manifest(target)
    if len(catalog.read_text(encoding="utf-8", errors="replace").splitlines()) < 2:
        raise ValueError("Full emergency backup pg_restore catalog is unexpectedly empty")
    cached = record_verified_backup(
        target.name,
        dump_sha256=verified["database.dump"],
        dump_bytes=dump.stat().st_size,
        manifest_files_verified=len(verified),
    )
    return {
        "backup_id": target.name,
        "status": "verified",
        "path": str(target),
        "dump_path": str(dump),
        "dump_bytes": dump.stat().st_size,
        "sha256": verified["database.dump"],
        "manifest_files_verified": len(verified),
        "verified_at": int(cached["verified_at"]),
        "protected": (target / ".protected").is_file(),
        "metadata": _read_metadata(target),
        "created_at": int(target.stat().st_mtime),
    }


def list_emergency_backups() -> list[dict[str, Any]]:
    """List backups without hashing large database dumps on page render."""
    rows: list[dict[str, Any]] = []
    for target in sorted(backup_root().iterdir(), reverse=True):
        if not target.is_dir() or not BACKUP_ID_RE.fullmatch(target.name):
            continue
        dump = target / "database.dump"
        catalog = target / "database.list"
        manifest = target / "SHA256SUMS"
        missing = [name for name, path in (("database.dump", dump), ("database.list", catalog), ("SHA256SUMS", manifest)) if not path.is_file()]
        cached = _cached_verification(target)
        if missing:
            status = "corrupted"
            error = "Missing: " + ", ".join(missing)
        elif cached is None:
            status = "unverified"
            error = "Run Verify to calculate checksums"
        else:
            status = "verified"
            error = ""
        rows.append({
            "backup_id": target.name,
            "status": status,
            "path": str(target),
            "dump_path": str(dump) if dump.is_file() else "",
            "dump_bytes": dump.stat().st_size if dump.is_file() else 0,
            "sha256": str((cached or {}).get("dump_sha256", "")),
            "manifest_files_verified": int((cached or {}).get("manifest_files_verified", 0)),
            "verified_at": int((cached or {}).get("verified_at", 0)),
            "protected": (target / ".protected").is_file(),
            "metadata": _read_metadata(target),
            "created_at": int(target.stat().st_mtime),
            "error": error,
        })
    return rows


def set_emergency_backup_protected(backup_id: str, protected: bool) -> bool:
    target = _safe_backup_dir(backup_id)
    if not target.is_dir():
        raise FileNotFoundError("Full emergency backup does not exist")
    marker = target / ".protected"
    if protected:
        marker.write_text("protected\n", encoding="ascii")
        os.chmod(marker, 0o600)
    else:
        marker.unlink(missing_ok=True)
    return protected


def delete_emergency_backup(backup_id: str) -> None:
    target = _safe_backup_dir(backup_id)
    if not target.is_dir():
        raise FileNotFoundError("Full emergency backup does not exist")
    if (target / ".protected").is_file():
        raise PermissionError("Protected full emergency backup must be unprotected before deletion")
    shutil.rmtree(target)


def emergency_dump_path(backup_id: str) -> Path:
    target = _safe_backup_dir(backup_id)
    dump = target / "database.dump"
    if not target.is_dir() or not dump.is_file() or dump.stat().st_size <= 0:
        raise FileNotFoundError("Full emergency database dump does not exist")
    return dump
