# Consumption VM/Node

Release: `50.5.9-prod-r20-consumption-node-vm-rollup-alignment-hotfix`

## Scope

R20 changes only the Consumption data/read path and its Maintenance status card.
Dashboard snapshot behavior, Agent cadence and payload, CPU/RAM/Disk/PPS formulas,
Abuse, Storage I/O, Queue, RBAC and the 2-day/7-day retention policy are unchanged.

## Active data flow

The Agent samples locally every 15 seconds and sends one durable `/push` every
300 seconds. One accepted push updates, in the same PostgreSQL transaction:

- recent VM interface rows in `node_stats`;
- per-VM `bandwidth_hourly` and `bandwidth_daily`;
- recent physical rows in `node_physical_net_stats`;
- physical Node `node_consumption_hourly` and `node_consumption_daily`;
- compact All-VM-per-Node `node_vm_consumption_hourly` and
  `node_vm_consumption_daily`.

`push_receipts` prevents an exact retry from being added twice. Guest direction
remains normalized as guest RX = host tap TX and guest TX = host tap RX.

The previous Agent-side two-hour writer is retired. The route
`/push/bandwidth-consumption` remains registered only for safe upgrades and
returns HTTP 410. `node_bandwidth_consumption_2h` remains a dormant compatibility
table until a later schema cleanup release. The `2H` page button is only a
rolling display range.

## Fast range queries

The page never scans seven days of raw interface rows:

- incomplete hour edges use retained five-minute rows;
- complete hours use hourly rollups;
- complete days use daily rollups.

At the target scale of 350 Nodes, 70,000 VMs and about 140,000 VM interfaces,
Node and Node Group pages query one compact Node row per hour/day. VM list
search, sorting and pagination remain server-side.

## VM Consumption

The VM tab shows one VM per row with Public/Private RX, TX and Total, Coverage
and Latest Sample. It uses the existing per-VM hourly/daily tables and keeps
100/200/500-row server-side pagination.

## Node Consumption

Each Node row shows aligned columns:

- Physical Public RX / TX / Total;
- All VM Public RX / TX / Total;
- Public observed difference;
- Physical Private RX / TX / Total;
- All VM Private RX / TX / Total;
- Private observed difference;
- VM reporting count, Coverage and Latest Sample.

Observed difference is Physical minus All VM for the same selected window. It
may include host traffic, protocol overhead or partial sample coverage and is
not a billing value. The Node link opens normal Node monitoring; the VM link
filters the VM Consumption tab to that Node.

## Node Group Consumption

Node Group uses the same column order, fixed widths and numeric alignment as the
Node table. It sums compact Node rollups, not all VM rows. Only active groups
and effectively visible Nodes participate. Group history follows the Node's
current group assignment.

## Maintenance

There is no separate Clear Consumption button. `Clear All Monitoring Data`
clears raw metrics and every hourly/daily Consumption rollup together while
preserving Node/VM inventory, Node Groups, flags, hidden state, users and
settings. Routine 7-day cleanup remains available. Individual VM/Node purge
rebuilds or removes the compact Node VM rollups so totals cannot remain stale.
