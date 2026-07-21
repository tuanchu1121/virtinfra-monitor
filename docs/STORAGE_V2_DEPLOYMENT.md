# Storage V2 deployment and verification

Release: `50.5.9-prod-r22.3-maintenance-queue-backup-hotfix`

This package is designed for a new deployment. It does not import history from another monitor. Current application functionality, Agent payload and route compatibility remain part of the release.

## Push with GitHub Desktop

1. Extract the release ZIP.
2. Open the extracted folder in GitHub Desktop with **File > Add local repository**.
3. Commit all files.
4. Push to the configured repository and branch.
5. Confirm `VERSION` contains `50.5.9-prod-r22.3-maintenance-queue-backup-hotfix` and `SHA256SUMS` is included.

## Database image requirement

Keep the default `timescale/timescaledb:2.27.2-pg17` image. Storage V2 requires TimescaleDB Community Edition for background retention and compression policies. The installer rejects an Apache-only `-oss` image before applying V2 migration objects.

## Fresh installation

Public IP:

```bash
curl -fsSL https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install.sh | \
bash -s -- --public-ip YOUR_MONITOR_IP --port 8080
```

Domain and HTTPS:

```bash
curl -fsSL https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install.sh | \
bash -s -- --domain monitor.example.com --email ops@example.com
```

The installer creates PostgreSQL/TimescaleDB, creates the existing application schema, applies `001` through `004`, installs the full code, starts services and requires `/login` health to pass.

## Immediate verification

```bash
virtinfra-monitorctl version
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl doctor
virtinfra-monitorctl storage-v2
virtinfra-monitorctl db-check
```

Expected Storage V2 state:

```text
3 V2 hypertables
3 retention jobs
2 compression jobs
VIRTINFRA_STORAGE_V2=0
VIRTINFRA_READ_CHART_V2=0
VIRTINFRA_RAW_V2=0
```

Check application logs after Agents push:

```bash
virtinfra-monitorctl logs monitor 300 | grep 'push_perf'
```

Check row growth:

```bash
virtinfra-monitorctl storage-v2 --json
```

## Functional verification

Verify without changing any settings:

```text
Login
Dashboard
Top VM and Top Node
VM Abuse and Abuse events
Node Health and miss detail
one Node Detail page
one VM Detail page
Storage I/O
Consumption list and node detail
Admin overview, users, API key and maintenance pages
API v1 health/current/Abuse endpoints
```

For VM and node charts, test `2H`, `6H`, `24H`, `3D` and `7D`. The new installation naturally fills history over time; no old chart is backfilled.

## Old-versus-V2 validation on the new installation

The release intentionally keeps compatibility history writes. After at least several pushes, compare one VM:

```bash
set -a
. /etc/default/bw-monitor
set +a

/opt/bw-monitor/venv/bin/python3 \
  /opt/bw-monitor/tools/validate-storage-v2.py \
  --node NODE_NAME \
  --vm-uuid VM_UUID \
  --start 1720972800 \
  --end 1721145600 \
  --tolerance 0.01
```

Run the validation over representative single-NIC, dual-NIC, 3-NIC, Public-only, Private-only and mixed VMs during the first 24 to 48 hours.

## Read-only benchmark

```bash
set -a
. /etc/default/bw-monitor
set +a

/opt/bw-monitor/venv/bin/python3 \
  /opt/bw-monitor/tools/benchmark-storage-v2.py \
  --node NODE_NAME \
  --vm-uuid VM_UUID \
  --start 1720972800 \
  --end 1721145600 \
  --runs 5 \
  > /root/storage-v2-benchmark.json
```

The tool reports measured query times, row counts, query plans/buffers and table sizes. Do not infer a production speedup before collecting this output under real load.

## Fast chart-read rollback

```bash
virtinfra-monitorctl rollback-storage-v2
```

This sets:

```text
VIRTINFRA_READ_CHART_V2=0
```

then restarts and verifies `bw-monitor.service`. It does not drop V2 tables, disable V2 writes or delete V2 data.

To re-enable V2 reads:

```bash
sed -i "s/^VIRTINFRA_READ_CHART_V2=.*/VIRTINFRA_READ_CHART_V2='1'/" /etc/default/bw-monitor
systemctl restart bw-monitor.service
virtinfra-monitorctl health
```

## Database policy verification

```bash
virtinfra-monitorctl psql
```

Then:

```sql
SELECT hypertable_name,num_chunks,compression_enabled
FROM timescaledb_information.hypertables
WHERE hypertable_schema='public'
  AND hypertable_name IN ('vm_chart_5m','vm_raw_detail_5m','node_chart_5m');

SELECT j.job_id,j.hypertable_name,j.proc_name,j.schedule_interval,j.scheduled,
       s.last_run_status,s.last_successful_finish
FROM timescaledb_information.jobs j
LEFT JOIN timescaledb_information.job_stats s USING(job_id)
WHERE j.hypertable_schema='public'
  AND j.hypertable_name IN ('vm_chart_5m','vm_raw_detail_5m','node_chart_5m')
ORDER BY j.hypertable_name,j.proc_name;
```

## Important operational notes

- Do not run `VACUUM FULL` as routine V2 retention.
- Do not manually delete millions of V2 rows for normal aging. Let background chunk retention run.
- VM/node purge and complete reset actions already include V2 tables.
- Abuse event retention and Consumption behavior are independent from V2 raw/chart retention.
- A 7-day chart on a new installation becomes complete only after the monitor has collected seven days of pushes.
