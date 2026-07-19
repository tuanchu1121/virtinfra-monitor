# Suggested r7 installation with minimal downtime

No installation was performed while building this release.

1. Extract r7 to a new immutable versioned directory.
2. Verify `SHA256SUMS`, run `python3 -m compileall -q app tests`, then run `pytest -q` and the project preflight in staging.
3. Point the new release at the existing external environment and PostgreSQL service. Do not copy databases, logs or credentials into the source tree.
4. Start r7 on a parallel socket/port and verify `/health`, authentication, monitoring visibility and Admin RBAC.
5. Atomically switch the reverse-proxy upstream to r7 and drain old r6 workers. Keep r6 available for immediate rollback.

If the deployment cannot run parallel application instances, use the existing release-symlink process plus a graceful application-server reload; this may cause a brief connection handoff but does not require a database restart.

