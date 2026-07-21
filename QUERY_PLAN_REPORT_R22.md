# R22 Query Plan Report

## Static and executable guarantees

### Consumption Node, Group and Summary

The canonical SQL builder is owned by runtime Layer 44 and composes only:

- `node_consumption_5m`
- `node_consumption_hourly`
- `node_consumption_daily`

The runtime guard rejects forbidden VM/raw relation names before execution. Group and Summary reuse the same cached Node dataset. The retained 5-minute edge is clipped to the raw-retention boundary; older range segments use hourly/daily rollups without querying raw VM/NIC data.

### VM Consumption

VM Consumption remains a separate pipeline. Its cache key includes Group, Node, search, coverage, sort, direction, pagination and visibility generation, preventing cross-filter cache reuse.

### Top VM current view

Current Top VM reads existing bounded current sources only:

- `vm_current_fast`
- `vm_disk_summary_current`
- inventory and visibility metadata
- current interface/address metadata for search

SQL order is:

1. visibility filtering
2. Group filtering
3. Node/search/scope filtering
4. current RAM/disk enrichment
5. `ORDER BY ... NULLS LAST`
6. stable Node and VM UUID tie-breakers
7. `LIMIT`

No candidate `LIMIT 1000` is applied before RAM or disk sorting.

### Top VM selected historical snapshot

Historical Top VM keeps the existing selected-snapshot source and formulas. R22 changes the order of operations so all matching snapshot VMs are enriched and ranked before `LIMIT`; it does not substitute current data for historical measurements.

## Live plan status

No live PostgreSQL plan was generated in the build environment because no disposable DSN was available. Before production, run both commands in `BENCHMARK_REPORT_R22.md` and retain their JSON outputs as deployment evidence.

The release must not be approved if a live Node/Group/Summary plan touches raw VM/NIC or VM Consumption tables, or if a current Top VM plan reads history/raw tables or places `LIMIT` before the requested sort.
