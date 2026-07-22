# R15 validation report

## Scope

This release changes only the Maintenance authorization boundary and the Queue cancel-flag schema compatibility required for permanent purge and database jobs. The existing UI structure, routes, monitoring calculations, Agent payload, API payload, retention policy and inventory behavior remain unchanged.

## Authorization

- Maintenance and Queue are visible and callable only by `super_admin`.
- Regular `admin` receives HTTP 403 for Maintenance, Queue cancellation and permanent Node/VM purge actions.
- Permanent purge controls are removed from the regular Admin Nodes and VMs views.
- Reversible Hide and Restore remain available to regular Admin.

## Queue schema

- Fresh installations create `cancel_requested` as Boolean.
- Update migration 013 converts legacy numeric values: zero becomes false and non-zero becomes true.
- Existing Queue rows are preserved.
- Provisioning verifies the resulting type and performs a transactional insert followed by rollback.

## Runtime validation

- Super Admin purge tests cover VM purge, all-VMs-on-Node purge and Node purge.
- Each accepted purge produces a Queue job and redirects to the existing Maintenance Queue area.
- Enqueue failure restores the previous inventory visibility state.
- Admin role tests verify hidden Maintenance cards, absent purge controls and direct HTTP 403 enforcement.

## Unchanged contracts

- CPU, RAM, network Mbps/PPS, disk throughput/IOPS, Consumption and Abuse formulas.
- PostgreSQL metric and inventory tables other than the queue flag type correction.
- Agent collection and delivery cadence.
- Flask route count and endpoint names.
- UI layout and 30-second browser refresh interval.
- Retention: full five-minute core history for 48 hours, hourly retained snapshots through day 7, then deletion.
