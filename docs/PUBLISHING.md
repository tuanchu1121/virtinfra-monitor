# Publish to GitHub

> Vietnamese step-by-step GitHub Desktop guide: [`../GITHUB_DESKTOP_VI.md`](../GITHUB_DESKTOP_VI.md)
>
> Complete deployment and operations commands: [`../COMMANDS_A_TO_Z_VI.md`](../COMMANDS_A_TO_Z_VI.md)


The root of the repository must contain `install.sh`, `app/`, `postgres/`, `deploy/`, `ansible/`, `tests/` and `docs/`.

## Windows + GitHub Desktop

Copy the complete extracted release tree into the local repository opened by GitHub Desktop, commit to `main`, and push. This release does not depend on Git executable-bit metadata. The Linux bootstrap invokes source scripts through `bash` and normalizes modes after download.

## Replace an existing checkout

Assume:

```text
checkout: /.data/agent
archive:  /root/virtinfra-monitor-50.5.9-prod-r1-ui-responsive-theme-chart-gaps-github-production.zip
```

```bash
set -euo pipefail

ZIP=/root/virtinfra-monitor-50.5.9-prod-r1-ui-responsive-theme-chart-gaps-github-production.zip
REPO=/.data/agent
TMP=/tmp/virtinfra-monitor-v50-publish

apt-get update
apt-get install -y unzip rsync git python3

rm -rf "$TMP"
mkdir -p "$TMP"
unzip -q "$ZIP" -d "$TMP"
SRC="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -n1)"

cd "$REPO"
git pull --ff-only
git branch "backup-before-v50-$(date +%Y%m%d-%H%M%S)"

rsync -a --delete \
  --exclude='.git/' \
  --exclude='ansible/*.txt' \
  --exclude='ansible/inventory*.ini' \
  --exclude='ansible/production*.ini' \
  "$SRC/" "$REPO/"

./preflight.sh
git status --short

git add -A
git commit -m 'Release VirtInfra Monitor v50 PostgreSQL Native'
git push origin main
```

## Verify raw GitHub content

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/VERSION
```

Expected:

```text
50.5.9-prod-r1-ui-responsive-theme-chart-gaps
```

## Secret review

Never commit production credentials, environment files, DB dumps, private SSH keys, real inventories or Vault password files.

```bash
git status --short
git grep -n -E 'bwm_push_[A-Za-z0-9]{40,}|BEGIN OPENSSH PRIVATE KEY|github_pat_' -- . || true
```
