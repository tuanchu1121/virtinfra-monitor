# Changelog

## 50.5.9-prod-r14-purge-queue-visibility-hotfix

- Fixed purge feedback visibility without changing purge semantics or inventory UI.
- Successful Node, VM, purge-all-VM and bulk purge actions now open the existing Maintenance queue at the accepted job row area.
- Queue insertion failures now open the same Maintenance area and display the existing error notice instead of returning silently to Nodes/VMs.
- Hide and Restore actions keep their original Nodes/VMs navigation.
- Added an end-to-end runtime regression that inserts purge jobs and confirms they render in Recent maintenance jobs.

## 50.5.9-prod-r13-conservative-refresh30-retention-verified

### Scope

- Preserves the current UI structure, Flask routes, endpoint names, request/response payloads, database schema, Agent protocol and all monitoring calculations.
- Keeps the conservative Admin, Maintenance, Queue, Node Group visibility, purge and password correctness fixes already present in the source.
- Changes only the browser live refresh interval from 5 seconds to 30 seconds, including Node Groups.
- Fixes the release preflight reference so it invokes the test file that is actually shipped.

### Retention verification

- Latest 48 hours retain every real five-minute Agent push.
- From 48 hours through day 7, one real retained snapshot per Node and local hour is preserved.
- Historical metric rows older than 7 days are deleted while current inventory/state remains preserved.
- The release includes an executable regression test that populates points across days 1, 3, 6 and 8 and verifies the effective retention function end to end.

### Compatibility boundary

- CPU, RAM, network Mbps/PPS, disk throughput/IOPS, Consumption, Abuse, snapshot selection, Queue batching and retention formulas are unchanged.
- Static UI assets are unchanged.
- Fresh installation remains `install.sh`; update with backup preservation remains `update.sh`.
