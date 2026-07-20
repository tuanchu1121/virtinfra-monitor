# Security policy

## Secrets

Never commit or publish:

- `/root/bw-monitor-credentials.env`
- `/etc/default/bw-monitor`
- `/etc/default/bw-monitor-postgres`
- `/etc/virtinfra-agent.env` (and legacy `/etc/bwagent.env` during migration)
- PostgreSQL dumps or backup directories
- production Ansible inventories
- Ansible Vault password files
- private SSH keys or TLS private keys
- real Agent tokens or scoped REST API keys

The repository `.gitignore` blocks common secret/data file patterns, but review every commit before pushing.

## Network exposure

- PostgreSQL is bound only to `127.0.0.1:55432` by default.
- In domain mode, expose Nginx TCP 80/443 and keep Gunicorn on loopback.
- In IP mode, expose only the configured application port when required.
- Do not publish Docker volume paths or database credentials.
- Use HTTPS domain mode for Internet-facing production deployments.

## Authentication

Agent `/push` uses a dedicated `BW_MONITOR_TOKEN`. REST API keys are separate, scoped and support Allowed IP/CIDR, expiry and rate limits. Do not reuse Agent tokens as REST API keys.

Dashboard sessions are invalidated on the next request after a password reset, role change, disable or account deletion. User Management cannot alter the currently signed-in account, and the final enabled Super Admin cannot be downgraded, disabled or deleted. Initial `/admin/setup` is available only while no dashboard user exists.

## Host hardening

The Agent service keeps `ProtectHome=read-only` so it can inspect storage under `/home` without writable home access. The Monitor database container uses a named volume and bounded JSON logs. Keep Docker, OS packages and the repository release updated.

## Reporting

Report vulnerabilities privately to the repository owner. Do not include production credentials, customer data or raw database dumps in public issues.
