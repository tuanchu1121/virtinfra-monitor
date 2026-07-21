# Publish the canonical release to GitHub

The repository root must contain `install.sh`, `update.sh`, `app/`, `postgres/`, `deploy/`, `ansible/`, `tests/`, `tools/`, `docs/`, `VERSION` and `SHA256SUMS`.

## GitHub Desktop or Git

Copy the complete extracted release into the repository working tree, excluding `.git`, real inventory files and credentials. Then run:

```bash
./preflight.sh
./tools/release-audit.sh
git status --short
git add -A
git commit -m 'Release VirtInfra Monitor 50.5.9-prod-r22.4-preflight-contract-hotfix'
git push origin main
```

Verify the published version:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/VERSION
```

Expected:

```text
50.5.9-prod-r22.4-preflight-contract-hotfix
```

Never commit production credentials, environment files, database dumps, private SSH keys, real inventories or Vault password files.
