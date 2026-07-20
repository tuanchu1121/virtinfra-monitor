# VirtInfra Monitor R14 Purge Queue Visibility Hotfix

## Scope

This release changes only the post-submit navigation and validation coverage for Node/VM purge operations. The purge queue implementation, database deletion functions, inventory visibility behavior, UI layout, API, Agent protocol, PostgreSQL schema, metric formulas, retention and maintenance worker architecture are unchanged.

## Confirmed root cause

Purge routes committed the immediate hidden state and enqueued the PostgreSQL maintenance job, then redirected back to the Nodes or VMs section. Those sections did not render the existing `dbmsg` or `dberr` query parameters. Operators therefore saw the row disappear but received no visible confirmation, job ID, dispatcher error or direct Queue view.

## Corrected behavior

- Successful single/bulk Node and VM purge redirects to `/admin?section=maintenance#maintenance-queue`.
- The existing Queue card displays the accepted job ID and current status.
- Enqueue failures redirect to the same Queue card and display the existing error notice.
- Hide and Restore retain their original navigation and behavior.
- Purge targets are still hidden immediately and rolled back if enqueue fails.

## Runtime invariants

- Flask routes and methods unchanged.
- No database schema or SQL migration changes.
- No CPU, RAM, network, PPS, disk, bandwidth, Abuse or Consumption formula changes.
- No Agent or API payload changes.
- No queue ordering, worker locking, batching or retention changes.
