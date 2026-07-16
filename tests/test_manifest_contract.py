#!/usr/bin/env python3
"""Verify SHA256SUMS covers the exact canonical source tree with fresh hashes."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "SHA256SUMS"


def fail(message: str) -> None:
    raise AssertionError(message)


def included_files() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in {".git", "dist", "__pycache__"} for part in rel.parts):
            continue
        if path.name == "SHA256SUMS" or path.suffix in {".pyc", ".pyo"}:
            continue
        result[rel.as_posix()] = path
    return result


if not MANIFEST.is_file():
    fail("SHA256SUMS is missing")

entries: dict[str, str] = {}
for line_no, raw in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), 1):
    line = raw.strip()
    if not line:
        continue
    try:
        digest, name = line.split(None, 1)
    except ValueError as exc:
        raise AssertionError(f"invalid SHA256SUMS line {line_no}: {raw!r}") from exc
    name = name.lstrip("*")
    if name.startswith("./"):
        name = name[2:]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
        fail(f"invalid SHA-256 digest on line {line_no}")
    if name in entries:
        fail(f"duplicate manifest path: {name}")
    entries[name] = digest.lower()

expected = included_files()
missing = sorted(set(expected) - set(entries))
extra = sorted(set(entries) - set(expected))
if missing:
    fail("manifest missing files: " + ", ".join(missing[:20]))
if extra:
    fail("manifest contains excluded/missing files: " + ", ".join(extra[:20]))

bad: list[str] = []
for name, path in sorted(expected.items()):
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != entries[name]:
        bad.append(name)
if bad:
    fail("stale checksum entries: " + ", ".join(bad[:20]))

print(f"PASS: SHA256SUMS has fresh hashes and exact coverage for {len(expected)} source files")
