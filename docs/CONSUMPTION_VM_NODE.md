# Consumption VM/Node

Release: `50.5.8-prod-r3-consumption-vm-node`

## Scope

This release changes only the effective `/bandwidth-consumption` page. Existing Agent collection, push endpoints, Abuse, Dashboard, Top VM, Storage I/O, Node Health, retention, maintenance and database write paths are preserved.

No Agent reinstall is required.

## Overview cards

The page always shows four totals for the selected range:

- Physical Public: RX, TX, Total
- Physical Private: RX, TX, Total
- VM Public: RX, TX, Total
- VM Private: RX, TX, Total

The supported rolling ranges are `1H`, `2H`, `6H`, `12H`, `24H`, `2D` and `7D`. The default is `24H`. The application continues to use its existing fixed display timezone; no new timezone selector is introduced.

Search, Coverage filters and pagination affect only the table. The range and explicit VM-tab node filter affect the overview totals.

## VM Consumption

VM rows are grouped by canonical VM UUID across historical nodes. The current node and its public node IP come from the existing current inventory tables.

Columns:

- UUID with copy action
- Node / Node IP
- Public Card RX, TX, Total
- Private Card RX, TX, Total
- Coverage
- Latest Sample

MAC is search-only and is not displayed. VM IP is neither displayed nor searched because the monitor does not maintain an authoritative UUID-to-VM-IP mapping.

The table defaults to `Public Total DESC`. It supports server-side sorting and `100`, `200` or `500` rows per page.

VM Consumption reuses `bandwidth_hourly` and `bandwidth_daily`. Host tap direction is normalized for display:

- guest RX = host tap TX
- guest TX = host tap RX

No second VM Consumption history table is created.

## Node Consumption

Columns:

- Node / Node IP
- Physical Public RX, TX, Total
- Physical Private RX, TX, Total
- Coverage
- Latest Sample

Physical NICs with the same role are aggregated. The page does not assume a fixed Card 1/Card 2 layout and does not show Difference columns.

Ranges through `24H` use retained physical samples. Longer ranges reuse the existing idempotent `node_bandwidth_consumption_2h` data plus current raw edges. No new Agent payload or timer is added.

## Compatibility

The legacy `/push/bandwidth-consumption` endpoint and its 2-hour storage remain unchanged for compatibility and long-range Physical totals. Existing Admin cleanup/reset integration remains unchanged.
