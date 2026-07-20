# Storage V2 architecture

Release: `50.5.9-prod-r20-consumption-node-vm-rollup-alignment-hotfix`

## Final data path

```text
VirtInfra Agent
  15s local sampling
  300s operational push
  Consumption rollup from the same 5-minute push
          |
          v
POST /push
  authenticate + validate
  normalize existing payload once
  existing inventory/history/health/storage writes
  existing current/latest writer
  existing Abuse engine
  batch raw-interface V2 rows
  batch compact VM chart V2 rows
  one node chart V2 row
  one transaction commit
          |
          +-- current/latest tables -> Dashboard, Top VM, realtime cards, health
          +-- vm_chart_5m -> exact 5-minute VM/node aggregate charts for 7 days
          +-- vm_raw_detail_5m -> interface/bridge raw detail for 48 hours
          +-- node_chart_5m -> exact 5-minute physical-host charts for 7 days
          +-- Abuse tables -> unchanged, independent retention
          +-- Consumption rollups -> per-VM and compact Node hourly/daily tables
```

## Why existing Latest is reused

The source already contains bounded current-state tables including `vm_current_fast`, `vm_iface_current`, `node_current_fast`, `vm_latest_metrics`, `node_host_latest`, current disk/storage summaries and Agent health latest. Creating another Latest family would duplicate write work and introduce consistency risk. Storage V2 reads these authoritative current values after the existing writer finishes.

## New schema

### `vm_chart_5m`

One row per `(bucket, node, vm_uuid)`.

It stores:

- exact 5-minute bucket and last push timestamp
- Public/Private and generic RX/TX bytes, packets, Mbps and PPS
- directional and role peak Mbps/PPS
- sample count/expected/gap/quality and threshold durations
- drops/errors
- CPU full/core and vCPU count
- RAM current/assigned/RSS/available/unused/usable
- disk read/write B/s and IOPS
- compact N-interface JSON needed by the existing bridge/interface chart selector

Retention: 7 days. Compression policy starts after 48 hours.

### `vm_raw_detail_5m`

One row per `(bucket, node, vm_uuid, bridge, iface)`.

It stores exact per-interface counters, peaks, sample quality, Public/Private/other role and error/drop data. No NIC count is hardcoded.

Retention: 48 hours. It is not used by Dashboard or Top VM.

### `node_chart_5m`

One row per `(bucket, node)`.

It stores exact physical-host load, CPU, RAM, swap, host disk throughput, uptime and aggregate current network counters needed by the existing host chart.

Retention: 7 days. Compression policy starts after 48 hours.

## Chunk intervals

| Hypertable | Chunk interval | Reason |
|---|---:|---|
| `vm_chart_5m` | 3 hours | At the target scale, bounds each chunk while avoiding hundreds of tiny daily chunks |
| `vm_raw_detail_5m` | 3 hours | Raw interface volume is higher; the same interval keeps retention precise and chunk operations bounded |
| `node_chart_5m` | 6 hours | Node-level row volume is much smaller |

At 40,000 VMs and one row per VM per 5 minutes, a full 3-hour VM chart chunk is approximately 1.44 million rows before retries/availability effects. With 80,000 interfaces, a full 3-hour raw chunk is approximately 2.88 million rows. These are capacity-planning estimates, not a measured production benchmark.

Because retention drops only complete chunks, actual retained wall time may exceed the nominal policy by up to roughly one chunk interval.

## Indexes

| Index | Query served | Write cost control |
|---|---|---|
| Primary `(bucket,node,vm_uuid)` | retry idempotency and time partition requirement | One required unique index |
| `vm_chart_5m(node,vm_uuid,bucket DESC)` | VM network/performance chart | Direct point lookup, no broad metric indexes |
| `vm_chart_5m(node,bucket DESC)` | node aggregate charts | One node/time index |
| Primary raw identity | retry idempotency | Required only |
| `vm_raw_detail_5m(node,vm_uuid,bucket DESC)` | one VM raw investigation | Targeted |
| `vm_raw_detail_5m(node,bucket DESC)` | node raw investigation | Targeted |
| `vm_raw_detail_5m(node,bridge,bucket DESC)` | role/bridge investigation | Targeted |
| Primary `(bucket,node)` plus `node_chart_5m(node,bucket DESC)` | physical host chart | Minimal |

No index is created on every metric column. Current page sorting continues to use the existing current-state indexes.

## TimescaleDB edition requirement

Storage V2 uses Timescale background retention and compression policies. The default database image is pinned to `timescale/timescaledb:2.27.2-pg17` (Community Edition). Do not replace it with the `-oss` image: the Apache-only build does not expose the policy capabilities required by migration `004_storage_v2.sql`. Both the installer and the migration fail closed before leaving a partial V2 setup.

## Retention and compression

`004_storage_v2.sql` installs background Timescale jobs:

```text
vm_chart_5m       drop after 7 days, check hourly
vm_raw_detail_5m  drop after 48 hours, check hourly
node_chart_5m     drop after 7 days, check hourly
vm_chart_5m       compress after 48 hours, check hourly
node_chart_5m     compress after 48 hours, check hourly
```

No large V2 history `DELETE`, automatic `VACUUM FULL`, hourly aggregation or daily aggregation runs inside `/push`.

## Environment variables

| Variable | Default | Meaning |
|---|---:|---|
| `VIRTINFRA_STORAGE_V2` | `0` | Optional V2 writes, disabled in production single-write mode |
| `VIRTINFRA_READ_CHART_V2` | `0` | Optional V2 chart reader, disabled by default |
| `VIRTINFRA_RAW_V2` | `0` | Optional raw interface history, disabled by default |
| `VIRTINFRA_PUSH_OBSERVABILITY` | `1` | Emit sanitized push timing/row-count logs |

## Observability log

One accepted non-duplicate push logs a line with:

```text
push_perf node=... bucket=...
total_ms=... parse_ms=...
chart_write_ms=... raw_write_ms=... node_write_ms=... commit_ms=...
rows_chart=... rows_raw=... rows_node=...
```

Tokens, passwords, API secrets, cookies and session secrets are never included.

## Compatibility history

This release does not import old data and is intended for a fresh deployment, but the existing source's compatibility history tables/writers remain enabled because other page/API/maintenance paths still use them and because they provide an immediate chart-read rollback. They can be retired only in a later measured release after all consumers are explicitly moved and regression-tested.
