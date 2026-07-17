# Storage V2 compatibility matrix

Release: `50.5.8-prod-r2-friendly-agent-logs`

Status values: **UNCHANGED**, **V2 READ**, **V2 WRITE**, **ADDITIVE**, **FALLBACK AVAILABLE**.

| Current feature | Current route | Current table/source | Current function | New data source | Status | Regression risk/control |
|---|---|---|---|---|---|---|
| Dashboard | `/` | current/latest, snapshots | `index` | Same | UNCHANGED | No template/query switch in this release |
| Top VM | `/top` | `vm_current_fast`, latest/summary tables | `top_page` | Same | UNCHANGED | No sort/filter/output changes |
| Top Node | `/top/nodes` | node current/latest | `top_node_page` | Same | UNCHANGED | No output changes |
| VM network chart | `/vm` | `node_stats` | `query_vm_chart` | `vm_chart_5m` | V2 READ, FALLBACK AVAILABLE | Existing return keys retained; `VIRTINFRA_READ_CHART_V2=0` restores old reader |
| VM CPU/RAM/disk chart | `/vm` | `vm_perf_stats` | `query_vm_perf_chart` | `vm_chart_5m` | V2 READ, FALLBACK AVAILABLE | Existing full/core CPU and guest-aware RAM output retained |
| Node aggregate network chart | `/node/<node>` | `node_stats` | `query_node_chart` | `vm_chart_5m` | V2 READ, FALLBACK AVAILABLE | Hidden VM and search behavior retained |
| Node PPS/drop/error chart | `/node/<node>` | `node_stats` | `query_node_network_health_chart` | `vm_chart_5m` | V2 READ, FALLBACK AVAILABLE | Same result keys and units |
| Node CPU/RAM/disk chart | `/node/<node>` | `vm_perf_stats` | `query_node_perf_chart` | `vm_chart_5m` | V2 READ, FALLBACK AVAILABLE | Same aggregate formulas and output keys |
| Physical host chart | `/node/<node>` | `node_host_stats` | `query_node_host_chart` | `node_chart_5m` | V2 READ, FALLBACK AVAILABLE | Same host metric fields |
| Current VM metrics | current pages/API | `vm_current_fast`, `vm_latest_metrics` | current readers | Same | UNCHANGED | Existing authoritative writer reused |
| Current node metrics | current pages/API | `node_current_fast`, host latest | current readers | Same | UNCHANGED | No duplicate Latest schema |
| Current VM Abuse | `/abuse/vms`, API v1 | `vm_abuse_state` | existing Abuse engine/readers | Same | UNCHANGED | Thresholds/cycles/reasons untouched |
| Abuse events/incidents | Admin/API | `vm_abuse_events`, `vm_abuse_incidents` | existing event/incident flow | Same | UNCHANGED | Independent from V2 retention |
| Abuse clear/manage | Admin POST routes | Abuse tables | existing handlers | Same | UNCHANGED | CSRF and semantics untouched |
| Storage I/O | `/storage`, API performance | storage current/summary tables | existing storage functions | Same | UNCHANGED | Multi-disk behavior untouched |
| Node Health | `/health/nodes` | inventory, misses, Agent health | existing health functions | Same | UNCHANGED | No status threshold changes |
| Agent health | current/admin | `agent_health_latest/stats` | existing ingest/readers | Same | UNCHANGED | Existing payload fields untouched |
| Public/Private network | VM/node pages | bridge-aware current/history | existing mapping | V2 stores role-aware fields and compact N-NIC snapshot | V2 WRITE/READ | Unknown bridges remain `other`, never forced into Public/Private |
| Multi-NIC | VM/node charts | N `node_stats` rows | current aggregation | one VM chart row plus `interfaces_json`; N raw rows | V2 WRITE/READ | No hardcoded NIC count |
| Multi-disk | VM/storage | Agent aggregate plus per-disk current | current disk ingest | Chart keeps authoritative aggregate; per-disk current stays existing | UNCHANGED | No first-disk shortcut |
| Consumption | `/bandwidth-consumption*`, push endpoint | `node_bandwidth_consumption_2h` | v50.3 module | Same | UNCHANGED | No UUID, formula, UI or retention changes |
| Login/session | login/logout routes | user/settings tables | existing auth | Same | UNCHANGED | Secret/session/CSRF untouched |
| API keys | `/admin/api-keys*` | API key/log tables | existing API auth | Same | UNCHANGED | Scopes/rate limits untouched |
| API v1 responses | `/api/v1/*` | current/Abuse sources | existing endpoints | Same | UNCHANGED | No field removal/type change |
| Search/sort/filter | all pages | existing current/read queries | existing handlers | Same, except chart SQL receives same `q` semantics | UNCHANGED | Existing controls/templates untouched |
| Time selector/timezone | VM/node/chart pages | period helpers, HCM timezone | existing helpers | Same | UNCHANGED | Exact bucket timestamp, no hourly conversion |
| Push endpoint/response | `/push` | existing write flow | `push` | additive V2 write before same commit | ADDITIVE | URL, auth, payload and response unchanged |
| Push idempotency | `/push` | `push_receipts`, current UPSERTs | existing receipt lock | V2 keys include bucket+identity | UNCHANGED/ADDITIVE | Retry updates same row |
| VM purge | Admin queue/actions | all VM tables | `purge_vm_data` | also V2 chart/raw | ADDITIVE | Existing result retained, V2 rows removed |
| Node purge | Admin queue/actions | all node tables | `purge_node_data` | also V2 VM/raw/node chart | ADDITIVE | Existing behavior retained |
| Clear/reset | Admin maintenance | monitoring/reset table tuples | existing clear/reset | V2 tables appended | ADDITIVE | No existing table removed |
| Health | `/healthz` | DB health | `virtinfra_healthz` | additive V2 table/policy status | ADDITIVE | Existing fields retained; deployment fails health if V2 schema absent |
| Installer/update | `install.sh`, `update.sh` | deployment scripts | native installer | installs migration/module/tools | ADDITIVE | Existing config/secrets/data preserved on update |
| Backup/restore | management commands | PostgreSQL/config backup | existing scripts | Same database includes V2 | UNCHANGED | No separate datastore |

## Fast rollback

The release keeps compatibility history writes. To switch only chart reads back without restoring a database:

```bash
virtinfra-monitorctl rollback-storage-v2
```

Equivalent manual action:

```bash
sed -i "s/^VIRTINFRA_READ_CHART_V2=.*/VIRTINFRA_READ_CHART_V2='0'/" /etc/default/bw-monitor
systemctl restart bw-monitor.service
```

V2 writes and V2 data remain intact during this read rollback.
