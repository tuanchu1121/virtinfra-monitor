# R22.10 VM Five-Minute Slot Rolling Window

## Goal

Make VM Consumption periods mean the actual rolling duration selected by the user, ending at the latest closed five-minute Agent bucket, without reintroducing raw VM/NIC scans or a high-cardinality `vm_consumption_5m` table.

## Data model

Migration `017_vm_consumption_5m_slots.sql` adds three columns to the existing `vm_consumption_hourly` hypertable:

- `rx_5m_slots BIGINT[]`
- `tx_5m_slots BIGINT[]`
- `sample_5m_mask INTEGER NOT NULL DEFAULT 0`

Each hourly VM+bridge row still has one primary-key row. The arrays contain twelve five-minute contributions; the bitmask records which positions were observed.

## Ingestion

The packed slot is written inside the existing hourly `INSERT ... ON CONFLICT` statement in both the native COPY path and compatibility path. There is no second UPDATE, no additional row per sample and no Agent/API payload change. Existing `push_receipts` de-duplication continues to protect exact HTTP retries.

Full hourly and daily totals, RX/TX direction formulas, packet/error fields and retention behavior remain unchanged.

## Rolling reads

- Request end is floored to the latest closed five-minute bucket.
- Request start is exactly the selected duration before that end.
- Only the first and last partial hour read selected slot elements.
- Complete hours use `vm_consumption_hourly` totals.
- Complete local days use `vm_consumption_daily` totals.
- VM Consumption does not read `node_stats`, `usage` or raw NIC history.
- Global sorting remains server-side before pagination.

Node and Group retain their compact Node 5m/hourly/daily pipeline but use the same normalized rolling boundaries.

## Upgrade warm-up

Pre-R22.10 hourly rows have no packed slots. During warm-up, selected exact slots are preserved and only the remaining unpacked hourly residual is proportionally distributed across missing positions. This avoids a sudden undercount when the first new slot enters an existing hour.

No raw-history backfill is started automatically. A period becomes fully exact after the new slot data spans that period, approximately one hour for 1H, 24 hours for 24H and seven days for 7D.

## Capacity impact

Row count, index cardinality and hourly UPSERT count do not increase. Hourly rows become wider. Two twelve-element PostgreSQL `BIGINT[]` values add roughly 240–250 bytes per populated VM+bridge+hour row before tuple/TOAST effects. At tens of thousands of VMs this can add several gigabytes across seven days and increase WAL bytes, so production database growth must be observed.

## Unchanged

No UI layout, route, API, Agent payload, Top VM, Storage I/O, Abuse, RBAC, Backup/Restore, Nuclear, RX/TX formula or non-Consumption behavior is changed.
