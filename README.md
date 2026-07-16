# VirtInfra Monitor v50 PostgreSQL Native

Production monitoring for KVM/libvirt nodes and virtual machines. This repository keeps the complete v48/v49 dashboard, Abuse Engine, storage views, Admin tools, REST API and Agent protocol, while replacing the runtime data store with one PostgreSQL 17 + TimescaleDB database.

> Release: `50.3.2-prod-r1-github-desktop-operations-guide`

> **Canonical-source bootstrap:** the installer verifies `SHA256SUMS` and stages only files in the release manifest. Old v48/v49 folders accidentally left in a GitHub Desktop repository are ignored during installation.

> Windows GitHub Desktop is supported. The bootstrap validates required files, invokes source scripts through `bash`, and normalizes Linux shell modes after download.

## Architecture

```text
KVM/libvirt node
  └─ virtinfra-agent.service
       ├─ samples local counters every 15 seconds
       ├─ builds one durable 5-minute operational payload
       ├─ accumulates node-only Public/Private RX/TX locally
       ├─ POST /push every 300 seconds
       └─ POST /push/bandwidth-consumption once per completed local 2-hour bucket
                    │
                    ▼
         Nginx :443 or public IP:8080
                    │
                    ▼
            Gunicorn + Flask
                    │
                    ▼
      PostgreSQL 17 + TimescaleDB
      single source of truth, loopback only
```

Runtime data is not split between databases. PostgreSQL stores users, settings, inventory, current metrics, Abuse state/events, storage data and history. TimescaleDB is an extension inside the same PostgreSQL database and is used for time-series history. Redis is optional page cache only, disabled by default, and never stores authoritative data.

## Exact sampling and retention

The Agent behavior is unchanged:

- local sampling: every **15 seconds**;
- durable Monitor push: every **300 seconds / 5 minutes**;
- duplicate retry protection: `node + push_time`;
- latest 48 hours: retain every real 5-minute push;
- 48 hours to 7 days: retain one real synchronized push per hour;
- older than 7 days: delete bounded history/log/event data;
- current inventory, users, settings, API keys and active state are not removed by history retention.

## Features preserved

- Login, viewer/admin roles and account logs
- Dashboard, Top VM, Node Health, Node Detail and VM Detail
- VM CPU, RAM, network Mbps/PPS, drops/errors and sample quality
- Per-VM disk capacity, allocation, physical size, throughput and IOPS
- Node storage `/`, `/home`, `/home2`, `/home3`, swap, filesystem capacity and I/O
- Current Abuse, Abuse Events, dynamic CPU/network/disk policies
- UUID-first Storage I/O views, search, filters, sort and pagination
- Admin node/VM management, queued destructive jobs and exact UUID purge
- Scoped REST API keys, Allowed IP/CIDR and rate limits
- Dark/light UI and existing route compatibility
- Agent deployment through one-command installer or Ansible
- Consumption after Storage I/O: separate Physical Public, Physical Private, aggregate VM Public and aggregate VM Private RX/TX, node search/filter/sort, coverage and 7-day retention

## Consumption

The new page is placed immediately after **Storage I/O**. It is intentionally isolated from the existing 5-minute monitoring and Abuse paths.

- one compact request per node for each completed local 2-hour bucket;
- no VM UUIDs and no per-VM bandwidth history;
- Physical Public, Physical Private, aggregate VM Public and aggregate VM Private stay separate;
- RX, TX and RX+TX total are shown only within the same network section;
- Public and Private differences are calculated separately;
- hidden nodes are excluded from search, filters, tables, summary cards and coverage without deleting their history;
- ranges: 2H, 6H, 12H, 1D through 7D;
- rows older than 7 days are deleted by retention;
- Admin cleanup, clear-history and Reset ALL integration are included.

Agent `runtime.json` durably stores the current accumulator and retry list. A full reset advances a Monitor-side acceptance epoch so old Agent retries cannot recreate deleted history.

## New server, public IP

Supported hosts: Debian 12+ and Ubuntu 22.04+ with systemd. Run as root:

```bash
apt-get update
apt-get install -y curl ca-certificates tar

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install.sh \
| bash -s -- \
--public-ip 203.0.113.10 \
--port 8080
```

Open:

```text
http://203.0.113.10:8080
```

Credentials are written with root-only permissions to:

```text
/root/bw-monitor-credentials.env
```

Show URLs and credentials:

```bash
virtinfra-monitorctl urls
virtinfra-monitorctl credentials
```

## New server, domain + HTTPS

Before installation:

1. Point the domain A/AAAA record to the Monitor server.
2. Allow inbound TCP 80 and 443.
3. Make sure the domain resolves publicly.

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install.sh \
| bash -s -- \
--domain monitor.example.com \
--email ops@example.com
```

The installer configures Nginx, obtains a Let's Encrypt certificate with Certbot, redirects HTTP to HTTPS, binds Gunicorn to loopback and prints the dashboard/Admin/Agent URLs.

## Deploy Agent from a separate Ansible server

```bash
cd /.data/agent
git pull --ff-only

read -rsp 'Enter VirtInfra Agent token: ' BW_TOKEN
echo

bash ansible/deploy-agent.sh \
  -i ansible/test.txt \
  --api 'https://monitor.example.com/push' \
  --token "$BW_TOKEN" \
  --forks 20 \
  --serial 10

unset BW_TOKEN
```

The playbook uses no `sudo` when `ansible_user=root`, keeps `ProtectHome=read-only`, and deploys the exact 15-second sampler / 300-second push defaults.

## Operations

```bash
virtinfra-monitorctl status
virtinfra-monitorctl doctor
virtinfra-monitorctl db-check
virtinfra-monitorctl logs all 200
virtinfra-monitorctl follow monitor
virtinfra-monitorctl backup
virtinfra-monitorctl retention
virtinfra-monitorctl psql
virtinfra-monitorctl update
```

Switch an existing IP deployment to domain HTTPS:

```bash
virtinfra-monitorctl domain set monitor.example.com ops@example.com
```

Switch back to IP mode:

```bash
virtinfra-monitorctl domain remove 203.0.113.10 8080
```

## Update

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/update.sh \
| bash
```

The update keeps the PostgreSQL volume, credentials, token, settings, domain/TLS configuration and current data.

## Backup and restore

```bash
virtinfra-monitorctl backup
```

Backups are stored under:

```text
/var/backups/bw-monitor/YYYYMMDD-HHMMSS/
```

Restore data:

```bash
virtinfra-monitorctl restore \
  --from /var/backups/bw-monitor/20260715-050000 \
  --yes
```

Restore data and protected configuration:

```bash
virtinfra-monitorctl restore \
  --from /var/backups/bw-monitor/20260715-050000 \
  --with-config \
  --yes
```

## Repository layout

```text
app/                         full Flask UI/business logic + PostgreSQL adapter
postgres/                    Compose and TimescaleDB SQL
postgres/sql/                bootstrap, hypertables and production indexes
deploy/postgres/             installer, service, backup/restore, doctor and CLI
deploy/agent/                complete Agent source and service installer
ansible/                     Monitor and Agent deployment playbooks
tests/                       static product contract and live PostgreSQL test
tools/                       release audit, installer test and archive builder
docs/                        operator and developer documentation
install.sh                   GitHub/new-server bootstrap
update.sh                    in-place update
```

## Validation

Static/source validation:

```bash
./preflight.sh
```

Live integration requires a disposable PostgreSQL database:

```bash
BW_TEST_DATABASE_URL='postgresql://user:pass@127.0.0.1:5432/bw_monitor_test' \
./preflight.sh --use-current-python
```

Release audit and archives:

```bash
./tools/release-audit.sh
./tools/build-dist.sh
```

## Vietnamese production runbooks

- [Start here - end-to-end deployment](START_HERE_VI.md)
- [GitHub Desktop publishing guide](GITHUB_DESKTOP_VI.md)
- [All deployment and maintenance commands A-Z](COMMANDS_A_TO_Z_VI.md)

## Documentation

- [Vietnamese full guide](docs/README_VI.md)
- [Installation](docs/INSTALL.md)
- [Domain and HTTPS](docs/DOMAIN.md)
- [Management CLI](docs/MANAGEMENT.md)
- [Database and performance](docs/DATABASE.md)
- [Backup and restore](docs/BACKUP_RESTORE.md)
- [Agent](docs/AGENT.md)
- [Ansible](docs/ANSIBLE.md)
- [Upgrade](docs/UPGRADE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Publishing to GitHub](docs/PUBLISHING.md)
- [API](docs/API.md)
- [Code guide](docs/CODE_GUIDE.md)
- [Security](SECURITY.md)


## Product identity and upgrade compatibility

The public product name is **VirtInfra Monitor** and the node collector is **VirtInfra Agent**. New Agent deployments use `virtinfra-agent.service`, `/etc/virtinfra-agent.env`, `/usr/local/lib/virtinfra-agent`, and `/var/lib/virtinfra-agent`. The monitor keeps legacy internal `/opt/bw-monitor`, `BW_*`, and `bw-monitor.service` identifiers as compatibility anchors so an upgrade does not move the PostgreSQL data volume, invalidate existing automation, or break the one-command installer. Canonical operator commands are `virtinfra-monitorctl` and `virtinfra-agent-doctor`; the legacy `bw-monitorctl`, `bw-monitor.service`, `BW_*` and old Agent identifiers remain available only as upgrade/integration compatibility anchors.
