# Node Groups and local country flags

Release: `50.6.0-prod-r2-node-groups-update-detection-fix`

## Data model

Node Group membership is keyed only by the exact value of `node_inventory.node`.
IP addresses, interfaces, MAC addresses and VM UUIDs are never used to infer or
change membership.

- `node_groups`: Group metadata, ISO 3166-1 alpha-2 country code and state.
- `node_group_memberships`: one current Group at most for each exact Node name.
- `node_group_membership_history`: assignment windows for audit and later
  time-aware reporting.
- VMs do not have a Group column or direct Group relationship. A VM inherits the
  current Group of its Node.
- `Ungrouped` is virtual and is not stored as a database row.

## Admin

The Admin menu is ordered as Overview, Nodes, Node Groups, VMs and Maintenance.
Node Groups supports create, edit, delete, description, country, enabled,
hidden and default states. Deleting a Group returns its Nodes to Ungrouped and
does not delete monitoring data.

Admin Nodes can assign, move or remove Group membership using only the exact
Node name. Admin VMs can filter by Group and Node and display inherited Group
identity, but they cannot assign a VM directly.

## Flags

The database stores only uppercase country codes such as `JP`, `US` and `SG`.
SVG files are vendored under `static/flags/4x3/` and served locally at
`/static/flags/4x3/jp.svg`. The standard table icon is fixed at 16 by 12 pixels.
Missing assets fall back to a country emoji and then the Global symbol.

The vendored assets are from flag-icons 7.5.0 under the MIT license. See
`THIRD_PARTY_NOTICES.md` and `THIRD_PARTY_LICENSES/flag-icons-LICENSE.txt`.

## Consumption

Consumption provides VM, Node and Group views. Group totals are built from
physical Node counters. Group coverage is calculated as:

`SUM(valid bucket seconds) / SUM(expected bucket seconds)`

It is never calculated by averaging per-Node coverage percentages.

## Compatibility

Existing Agent payloads, API endpoints and response contracts, metric formulas,
retention, queue behavior and the five-minute push cadence remain unchanged.
No production deployment or service restart is performed by the source build.
