#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "tuanchu1121/virtinfra-monitor"
LEGACY = "tuanchu1121/" + "bw-monitor" + "-production" + ".1"
LEGACY_SHORT = "bw-monitor" + "-production" + ".1"


def need(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


need((ROOT / "CANONICAL_REPOSITORY").read_text(encoding="utf-8").strip() == CANONICAL,
     "CANONICAL_REPOSITORY does not match the standalone repository")

required_defaults = {
    "install.sh": f'REPO="${{BW_GITHUB_REPO:-{CANONICAL}}}"',
    "install-agent.sh": f'REPO="${{BW_GITHUB_REPO:-{CANONICAL}}}"',
    "uninstall-agent.sh": f'REPO="${{BW_GITHUB_REPO:-{CANONICAL}}}"',
    "deploy/postgres/install-postgres-native.sh": f'GITHUB_REPO="${{BW_GITHUB_REPO:-{CANONICAL}}}"',
    "publish-github.sh": f'REPO="{CANONICAL}"',
}
for rel, marker in required_defaults.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    need(marker in text, f"{rel} does not default to {CANONICAL}")

update_text = (ROOT / "update.sh").read_text(encoding="utf-8")
need(CANONICAL in update_text, "update.sh does not contain the canonical repository fallback")
ctl_text = (ROOT / "deploy/postgres/bw-monitorctl.sh").read_text(encoding="utf-8")
need(CANONICAL in ctl_text, "virtinfra-monitorctl does not contain the canonical repository fallback")

skip_dirs = {".git", "dist", "__pycache__"}
for path in ROOT.rglob("*"):
    if not path.is_file() or any(part in skip_dirs for part in path.parts) or path.name == "SHA256SUMS":
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    need(LEGACY not in text, f"legacy repository reference remains in {path.relative_to(ROOT)}")
    need(LEGACY_SHORT not in text, f"legacy repository name remains in {path.relative_to(ROOT)}")

for rel in ("README.md", "START_HERE_VI.md", "GITHUB_DESKTOP_VI.md", "HUONG_DAN_REPO_MOI_VI.md",
            "docs/INSTALL.md", "docs/AGENT.md", "docs/UPGRADE.md", "docs/PUBLISHING.md"):
    text = (ROOT / rel).read_text(encoding="utf-8")
    need(CANONICAL in text, f"canonical repository is missing from {rel}")

print("PASS: standalone repository contract and zero legacy repository references")
