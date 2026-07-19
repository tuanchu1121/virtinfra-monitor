# Rollback — r7 to r6

Rollback source archive: `virtinfra-monitor-50.5.9-prod-r6-node-groups-admin-bulk-management-retention-safe-maintenance-hotfix-production-slim.zip`.

This hotfix has no database migration and does not alter API/Agent payloads, so rollback is a source-only operation.

1. Keep the existing production release directory and data directory untouched.
2. Extract the r6 archive into a new, versioned release directory; never overwrite the running tree in place.
3. Reuse the existing environment file and persistent PostgreSQL/data paths. Do not copy credentials into the release tree.
4. Run the r6 preflight against a disposable/staging database. Do not run destructive maintenance.
5. For a low-downtime cutover, start the validated r6 application on a parallel socket/port, verify `/health`, then switch the reverse-proxy upstream atomically and drain r7. If the deployment uses one Gunicorn socket, atomically switch the release symlink and use its documented graceful reload.
6. Verify login for Viewer/Admin/Super Admin, Dashboard, Top VM, Storage, Consumption, VM Abuse and Admin inventory.
7. Retain the r7 directory and logs until rollback verification is complete.

Rollback does not require reversing data because r7 adds no schema and performs no data conversion.

