# R18 Validation Report

Release: `50.5.9-prod-r18-user-rbac-session-hardening-hotfix`

## Scope

This release audits and hardens only Dashboard user management, role enforcement, Operations authorization and session invalidation. It does not change monitoring routes, Agent/API payloads, metric calculations, PostgreSQL metric schema, Node Groups, Queue semantics, retention, Dashboard layout or the R17 single Operations shell.

## Confirmed R17 defects reproduced

1. The final enabled Super Admin could be downgraded to Admin.
2. A signed-in Admin could downgrade its own role.
3. Create User could overwrite an existing username, including a Super Admin.
4. Duplicate creation could replace the existing password and role.
5. `/admin/setup` could be claimed from the web after the system reached zero Super Admin accounts.
6. A disabled account's old browser session still viewed the Dashboard.
7. A deleted account's old browser session still viewed the Dashboard.
8. Password reset did not revoke the account's existing sessions.
9. A role change left an inconsistent old browser session until manual logout.
10. Super Admin could not create or promote another Super Admin through the normalized UI.
11. Invalid role input silently fell back to Viewer instead of being rejected.
12. User Management allowed an account to reset its own password without the current password.

## R18 corrections

- Protects the final enabled Super Admin from downgrade, disable and delete.
- Blocks self role, status, deletion and User Management password-reset operations.
- Makes Create User insert-only; duplicate usernames return HTTP 409.
- Separates password reset and role change actions and rejects invalid roles.
- Binds sessions to the current user id, username, password hash, role and enabled state through an HMAC stamp, requiring re-login after external account changes.
- Keeps an account's own Password page available and requires the current password; the current browser receives a refreshed session stamp after success.
- Restricts `/admin/setup` to the true zero-user bootstrap state.
- Allows Super Admin creation/promotion only by a Super Admin.
- Aligns Admin UI/backend permissions for Consumption cleanup, audit-log read-only access and System Health JSON.
- Records the acting Super Admin role correctly in audit events.

## Validation results

- Dedicated RBAC runtime matrix: `30/30 PASS`.
- Full pytest collection: `148 passed, 1 skipped`.
- The skipped suite requires a disposable PostgreSQL DSN through `BW_TEST_DATABASE_URL`.
- Existing Node Groups/Operations runtime matrix: PASS, route count remains `83`.
- R18 adds no metric schema migration and no Flask route.
- The main preflight completed through all legacy/R17 contracts; the R18 matrix and installer/updater checks were then run separately because the outer validation command reached the execution-tool timeout after printing the R18 stage. Every individual command returned success.

## Upgrade behavior

All browser sessions created by earlier releases intentionally require login again after R18 is deployed. This is a one-time security boundary change, not data loss.

If an older release already has zero enabled Super Admin accounts, recover one from the server console before using Operations. The web bootstrap route no longer repairs an existing user database because that behavior allowed account takeover.
