# Node Groups and local country flags

Release: `50.6.0-prod-r1-node-groups-additive`

This feature is added on top of `50.5.9-prod-r3-ui-alignment-overflow-hotfix-production-slim`. Existing Agent delivery, API payloads, metric formulas, Abuse, retention, maintenance queue, search, sort and pagination remain in place when the new Group and Node filters are not selected.

## Data model

A Node membership is identified only by the exact value of `node_inventory.node`:

```text
Node name -> node_group_memberships.node_name -> node_groups.id
```

No membership operation reads or depends on `primary_ipv4`, `private_ipv4`, `public_ipv4`, MAC addresses or interface names.

A VM never stores a Group relation. Its Group is inherited from its current Node:

```text
vm_inventory.node -> node_group_memberships.node_name -> node_groups.id
```

`Ungrouped` is virtual and means that no membership row exists.

## Admin

Admin contains these sections:

```text
Overview
Nodes
Node Groups
VMs
Maintenance
```

`Node Groups` supports create, edit and delete, description, ISO 3166-1 alpha-2 country code, Enabled, Hidden and Default state, plus a list of assigned Nodes.

`Nodes` keeps the existing hide, restore, purge-VM and purge-Node actions and bulk actions. It adds Group filtering, Node filtering, a Group/flag column and exact-name Assign, Move and Remove operations.

`VMs` keeps the existing hide, restore, purge and bulk actions. It adds Group and Node filtering and shows inherited Group/flag information beside the Node. There is no VM Group assignment button.

## State behavior

- `Enabled`: allows new Node assignments.
- `Disabled`: keeps current memberships and monitoring data but rejects new assignments.
- `Hidden`: omits the Group from normal selectors; it does not hide its Nodes or VMs from monitoring.
- `Default`: preselects the Group in an unassigned Node's Admin form. It does not silently assign Nodes during Agent pushes.
- Deleting a Group removes current memberships and returns those Nodes to `Ungrouped`. Metrics, Nodes and VMs are not deleted.

Membership changes are written transactionally and recorded in `node_group_membership_history`.

## Flags

The release vendors `flag-icons` SVG 4:3 assets locally. The database stores only an uppercase two-letter code such as `JP`, `US` or `SG`.

Runtime URL example:

```text
/static/flags/4x3/jp.svg
```

Installed path:

```text
/opt/bw-monitor/static/flags/4x3/jp.svg
```

Table icons are fixed at `16 x 12 px`. The UI uses an emoji fallback when a valid code has no SVG and `🌐` when no country is configured. No CDN, npm or upstream repository is contacted at runtime.

## Filters

Pages containing Node or VM data receive additive `group_id` and `node` query parameters:

```text
group_id=<numeric Group ID>
group_id=ungrouped
node=<exact Node name>
```

Selecting a Group limits the Node selector to members of that Group. Existing query parameters are retained through links and GET forms.

## Consumption

The existing VM and Node Consumption readers and formulas remain unchanged when no new filter is selected. Group and Node filters are applied as an additional scope.

`Group Consumption` aggregates existing physical Node counters:

```text
Node counters -> sum per Node -> sum Nodes in Group
```

It never derives physical Group totals by summing VM rows. Coverage is weighted:

```text
SUM(valid seconds) / SUM(expected seconds)
```

It is not the arithmetic average of Node coverage percentages. Current Group membership is used for the selected historical range; membership history is retained for auditing and future time-aware reporting.

## Deployment

Migration:

```text
postgres/sql/011_node_groups_country_flags.sql
```

The migration creates only the three additive Group tables and indexes. It does not alter metric hypertables, inventory columns or existing API tables.
