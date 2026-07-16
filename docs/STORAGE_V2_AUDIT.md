# Storage V2 source audit

Release: `50.4.7-prod-r1-custom-theme-library`

This audit was generated from the complete `app/app.py`, Agent, installer, PostgreSQL helper, maintenance and deployment source before the Storage V2 read path was enabled. The existing route names, response shapes, templates, CSS, authentication, CSRF, timezone, Agent payload, Abuse policy and Consumption calculations remain unchanged.

## Runtime map

| Layer | Existing implementation | Storage V2 decision |
|---|---|---|
| Web | Flask + Gunicorn in `app/app.py` | Kept |
| Database | PostgreSQL 17 + TimescaleDB | Kept |
| Connection layer | `app/bw_pg.py`, pooled psycopg connections | Kept |
| Agent | local 15-second samples, 300-second operational push | Kept |
| Consumption | separate 2-hour node bucket endpoint | Kept |
| Authentication | Dashboard/Admin sessions, API keys, push token | Kept |
| Time display | `Asia/Ho_Chi_Minh` | Kept |
| Current state | `vm_current_fast`, `vm_iface_current`, `node_current_fast`, existing latest tables | Reused, not duplicated |
| Chart history | legacy `node_stats`, `vm_perf_stats`, `node_host_stats` | Default reads switch to compact V2 tables with legacy fallback |
| Raw technical detail | existing history plus current detail tables | New interface-level V2 hypertable retained 48 hours |
| Abuse | current state, events, incidents and policy versions | Unchanged and independent from V2 retention |
| Storage I/O | VM disk and node storage current/summary tables | Unchanged |
| Consumption | `node_bandwidth_consumption_2h` | Unchanged |

## Flask/API route inventory

| Route | Methods | Function | Source line at audit |
|---|---|---|---:|
| `/login` | GET,POST | `dashboard_login` | 6901 |
| `/logout` | GET | `dashboard_logout` | 6966 |
| `/` | GET | `index` | 7118 |
| `/health/nodes` | GET | `node_health_page` | 7148 |
| `/health/nodes/<path:node>/misses` | GET | `node_missed_detail_page` | 7186 |
| `/top/nodes` | GET | `top_node_page` | 7280 |
| `/abuse/vms` | GET | `vm_abuse_page` | 7595 |
| `/top` | GET | `top_page` | 7635 |
| `/node/<path:node>` | GET | `node_page` | 8163 |
| `/vm` | GET | `vm_page` | 8289 |
| `/admin/setup` | GET,POST | `admin_setup` | 8513 |
| `/admin/login` | GET,POST | `admin_login` | 8568 |
| `/admin/password` | GET,POST | `admin_change_password` | 8657 |
| `/admin/logout` | GET | `admin_logout` | 8706 |
| `/admin/users` | GET | `admin_users_page` | 8715 |
| `/admin/users/create` | POST | `admin_create_user` | 8823 |
| `/admin/users/action` | POST | `admin_user_action` | 8841 |
| `/admin/logs` | GET | `admin_logs_page` | 8892 |
| `/admin/logs/clear` | POST | `admin_logs_clear` | 9027 |
| `/admin/system-health` | GET | `admin_system_health_page` | 9048 |
| `/admin` | GET | `admin_page` | 9066 |
| `/admin/database-maintenance` | POST | `admin_database_maintenance` | 9237 |
| `/admin/cleanup` | POST | `admin_run_cleanup` | 9641 |
| `/admin/delete_vm` | POST | `admin_delete_vm` | 9650 |
| `/admin/restore_vm` | POST | `admin_restore_vm` | 9687 |
| `/admin/delete_node` | POST | `admin_delete_node` | 9708 |
| `/admin/restore_node` | POST | `admin_restore_node` | 9744 |
| `/admin/purge_node_vms` | POST | `admin_purge_node_vms` | 9764 |
| `/admin/bulk_nodes` | POST | `admin_bulk_nodes` | 9785 |
| `/admin/bulk_vms` | POST | `admin_bulk_vms` | 9845 |
| `/admin/api/system-health` | GET | `admin_api_system_health` | 9913 |
| `/health` | GET | `health` | 9921 |
| `/push` | POST | `push` | 10383 |
| `/summary` | GET | `summary` | 11908 |
| `/abuse/vms/clear` | POST | `clear_abuse_events` | 12426 |
| `/admin/abuse-settings` | POST | `admin_abuse_settings` | 12450 |
| `/admin/abuse` | GET | `admin_abuse_page_v483` | 12924 |
| `/admin/live-cache/clear` | POST | `admin_clear_live_cache` | 14370 |
| `/api/v1/me` | GET | `api_v1_me` | 18284 |
| `/api/v1/health` | GET | `api_v1_health` | 18295 |
| `/api/v1/abuse/vms` | GET | `api_v1_abuse_vms` | 18312 |
| `/api/v1/abuse/vms/<vm_uuid>` | GET | `api_v1_abuse_vm` | 18347 |
| `/api/v1/abuse/events` | GET | `api_v1_abuse_events` | 18371 |
| `/api/v1/vms` | GET | `api_v1_vms` | 18484 |
| `/api/v1/vms/<vm_uuid>/current` | GET | `api_v1_vm_current` | 18514 |
| `/api/v1/nodes` | GET | `api_v1_nodes` | 18535 |
| `/admin/api-keys` | GET | `admin_api_keys_page` | 18650 |
| `/admin/api-keys/create` | POST | `admin_api_key_create` | 18739 |
| `/admin/api-keys/revoke` | POST | `admin_api_key_revoke` | 18768 |
| `/admin/api-keys/rotate` | POST | `admin_api_key_rotate` | 18794 |
| `/api/v1/bandwidth/vms` | GET | `api_v1_bandwidth_vms` | 18841 |
| `/api/v1/bandwidth/vms/<vm_uuid>` | GET | `api_v1_bandwidth_vm` | 18894 |
| `/api/v1/abuse/summary` | GET | `api_v1_abuse_summary` | 19378 |
| `/admin/api-keys/delete` | POST | `admin_api_key_delete` | 19642 |
| `/admin/api-logs/clear` | POST | `admin_api_logs_clear` | 19676 |
| `/admin/api-keys/edit` | GET,POST | `admin_api_key_edit` | 19969 |
| `/api/v1/logs/requests` | GET | `api_v1_request_logs` | 20087 |
| `/api/v1/logs/events` | GET | `api_v1_management_logs` | 20140 |
| `/admin/abuse-vm-data/clear` | POST | `clear_vm_abuse_data_v48128` | 23085 |
| `/admin/abuse-data/reset-all-v48129` | POST | `reset_all_abuse_data_v48129` | 23768 |
| `/admin/abuse-vm-data/manage-v48129` | POST | `manage_vm_abuse_data_v48129` | 23790 |
| `/storage` | GET | `storage_io_page` | 24404 |
| `/api/v1/performance` | GET | `api_v1_performance_v48140` | 28113 |
| `/livez` | GET | `virtinfra_livez` | 28484 |
| `/healthz` | GET | `virtinfra_healthz` | 28489 |
| `/push/bandwidth-consumption` | POST | `push_bandwidth_consumption` | 28773 |
| `/bandwidth-consumption` | GET | `bandwidth_consumption_page` | 29048 |
| `/admin/bandwidth-consumption` | POST | `admin_bandwidth_consumption_action` | 29278 |
| `/bandwidth-consumption/node/<path:node>` | GET | `bandwidth_consumption_node_page` | 29424 |

## Page inventory and data flow

| Page | Current route | Current read functions/tables | Storage V2 behavior |
|---|---|---|---|
| Login | `/login`, `/admin/login`, `/admin/setup` | dashboard/admin user tables and sessions | Unchanged |
| Dashboard | `/` | current/snapshot helpers, node/VM inventory | Current behavior unchanged |
| Top VM | `/top` | current/latest tables | Unchanged |
| Top Node | `/top/nodes` | current/latest tables | Unchanged |
| VM Abuse | `/abuse/vms` | `vm_abuse_state` | Unchanged |
| Abuse Events/Admin Abuse | `/admin/abuse`, clear/manage routes | `vm_abuse_events`, `vm_abuse_incidents`, policy tables | Unchanged |
| Node Health | `/health/nodes` | node inventory, push/miss state, latest health | Unchanged |
| Node Detail | `/node/<node>` | current tables plus `query_node_*_chart` | Existing chart UI reads V2 exact 5-minute rows |
| VM Detail | `/vm` | latest/current plus `query_vm_chart`, `query_vm_perf_chart` | Existing chart UI reads V2 exact 5-minute rows |
| Storage I/O | `/storage` | disk/storage current and summary tables | Unchanged |
| Admin | `/admin` and action routes | current tables, queues, logs, maintenance | Unchanged; purge/reset includes V2 tables |
| API Key | `/admin/api-keys*` | API key/event/access-log tables | Unchanged |
| API v1 | `/api/v1/*` | existing current/Abuse/Consumption sources | Response fields and types unchanged |
| Consumption | `/bandwidth-consumption*` | `node_bandwidth_consumption_2h` | Unchanged |
| Health | `/livez`, `/healthz` | application/database health | `/healthz` adds backward-compatible `storage_v2` status |

## Metric inventory

The audit found and preserved these metric families:

| Family | Preserved fields/behavior |
|---|---|
| VM CPU | full percent, core percent, vCPU count, sustained-cycle state |
| VM RAM | current/assigned, host RSS, available, unused, usable, guest-aware used/total |
| VM network | RX/TX bytes, Mbps, packets, PPS, directional peaks, sample count/expected, gap, quality, threshold durations, drops/errors |
| Network roles | Public, Private and unclassified bridge/interface detail |
| Multi-NIC | N interfaces per VM, no two-interface assumption |
| VM disk | aggregate read/write bytes per second and IOPS, current per-disk records, multi-disk summaries |
| Node host | load 1/5/15, CPU count/percent, memory, swap, host disk throughput, uptime |
| Filesystems/storage | capacity, used/free, mount/device/filesystem, per-device I/O and utilization |
| Physical network | Public/Private physical interface counters and current state |
| Agent health | duration, component timings, counts, errors, alerts and version |
| Abuse | thresholds, policy revision, PPS/Mbps/CPU/disk cycles, reasons, severity, start/update/recovery, incidents and events |
| Consumption | eight Public/Private physical/VM RX/TX counters, coverage, sample count and estimate flag |

## PostgreSQL table inventory

| Table | Classification |
|---|---|
| `admin_settings` | Current production schema |
| `usage` | Current production schema |
| `node_stats` | Current production schema |
| `node_inventory` | Current production schema |
| `vm_inventory` | Current production schema |
| `vm_perf_stats` | Current production schema |
| `vm_latest_metrics` | Current production schema |
| `node_host_stats` | Current production schema |
| `node_host_latest` | Current production schema |
| `node_filesystem_stats` | Current production schema |
| `node_filesystem_latest` | Current production schema |
| `node_physical_net_stats` | Current production schema |
| `node_physical_net_latest` | Current production schema |
| `node_bridge_addresses_latest` | Current production schema |
| `agent_health_stats` | Current production schema |
| `agent_health_latest` | Current production schema |
| `vm_location_latest` | Current production schema |
| `vm_migration_events` | Current production schema |
| `vm_node_presence` | Current production schema |
| `node_push_snapshots` | Current production schema |
| `node_missed_events` | Current production schema |
| `push_receipts` | Current production schema |
| `bandwidth_hourly` | Current production schema |
| `bandwidth_daily` | Current production schema |
| `retention_runs` | Current production schema |
| `maintenance_jobs` | Current production schema |
| `dashboard_users` | Current production schema |
| `account_logs` | Current production schema |
| `node_logs` | Current production schema |
| `vm_current_fast` | Current production schema |
| `vm_iface_current` | Current production schema |
| `node_current_fast` | Current production schema |
| `vm_abuse_state` | Current production schema |
| `vm_abuse_events` | Current production schema |
| `abuse_policy_versions` | Current production schema |
| `api_keys` | Current production schema |
| `api_key_events` | Current production schema |
| `api_access_logs` | Current production schema |
| `vm_abuse_incidents` | Current production schema |
| `vm_disk_current` | Current production schema |
| `node_storage_current` | Current production schema |
| `vm_disk_summary_current` | Current production schema |
| `node_storage_mount_summary_current` | Current production schema |
| `node_bandwidth_consumption_2h` | Current production schema |
| `vm_chart_5m` | V2 Timescale hypertable |
| `vm_raw_detail_5m` | V2 Timescale hypertable |
| `node_chart_5m` | V2 Timescale hypertable |

## Write flow audit

`POST /push` keeps the existing validation, identity, inventory, host, interface, VM performance, Agent health, disk, current-state and Abuse writes. Storage V2 is called after the authoritative current-state writer and before the existing transaction commits:

```text
receive JSON
  -> authenticate X-Token
  -> validate node/lists/maps
  -> per-node PostgreSQL advisory transaction lock
  -> idempotent push_receipts insert
  -> existing inventory/history/health/storage writes
  -> existing latest/current writer
  -> existing Abuse evaluation
  -> Storage V2 batch raw rows
  -> Storage V2 batch VM chart rows
  -> Storage V2 node chart row
  -> one commit
  -> unchanged HTTP response
```

The V2 writer does not create one connection per VM, does not commit per row, does not aggregate hourly/daily, does not run cleanup and does not run database maintenance inside `/push`.

`POST /push/bandwidth-consumption` remains a separate idempotent 2-hour accounting flow and was not modified.

## Read flow audit

| Consumer | Data source after release |
|---|---|
| Dashboard/Top/current cards | Existing latest/current tables |
| VM network chart | `vm_chart_5m`, with legacy query fallback flag |
| VM CPU/RAM/disk chart | `vm_chart_5m`, with legacy query fallback flag |
| Node VM aggregate network chart | `vm_chart_5m` |
| Node VM aggregate PPS/drop/error chart | `vm_chart_5m` |
| Node VM aggregate CPU/RAM/disk chart | `vm_chart_5m` |
| Physical host chart | `node_chart_5m` |
| Current interface cards | Existing current tables |
| Raw interface investigation | `vm_raw_detail_5m` for 48 hours plus existing current/detail behavior |
| Abuse pages/API | Existing Abuse tables |
| Storage pages/API | Existing storage tables |
| Consumption pages | Existing Consumption table |

## Deployment/service/config audit

| Item | Preserved or added |
|---|---|
| `bw-monitor.service` | Preserved |
| `bw-monitor-retention.timer` | Preserved |
| backup timer and health watchdog | Preserved |
| `/opt/bw-monitor` | Preserved |
| `/etc/default/bw-monitor` | Preserved, additive V2 variables only |
| `/etc/default/bw-monitor-postgres` | Preserved |
| credentials/token/secret/API keys/users | Preserved by update installer |
| installer/update flow | Preserved, adds `004_storage_v2.sql` and V2 tools |
| backup/restore | Preserved |
| CSRF/session/login | Preserved |
| timezone | Preserved |
| Agent service/config | Preserved |

## Regression boundaries

No HTML, CSS, chart JavaScript, route URL, existing JSON response field, Agent endpoint, Agent payload field, token/UUID identity, Abuse threshold, Consumption formula, login/session, CSRF, timezone, search, sort, filter or pagination behavior was intentionally changed.
