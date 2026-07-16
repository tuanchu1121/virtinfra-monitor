# Troubleshooting

Start with:

```bash
virtinfra-monitorctl doctor
virtinfra-monitorctl status
virtinfra-monitorctl logs all 300
virtinfra-monitorctl db-check
```

## Web not opening

```bash
systemctl status virtinfra-monitor.service --no-pager -l
journalctl -u virtinfra-monitor.service -n 300 --no-pager
curl -I http://127.0.0.1:8080/login
```

In domain mode:

```bash
nginx -t
systemctl status nginx --no-pager -l
curl -I https://monitor.example.com/login
```

## PostgreSQL container not healthy

```bash
docker ps -a --filter name=bw-timescaledb
docker logs --tail 300 bw-timescaledb
cat /etc/default/bw-monitor-postgres
```

Do not paste real passwords/tokens into public tickets.

## Agent does not appear

```bash
systemctl status virtinfra-agent.service --no-pager -l
journalctl -u virtinfra-agent.service -n 300 --no-pager
cat /etc/virtinfra-agent.env
```

Confirm endpoint, token, DNS/TLS and outbound connectivity. A new Agent normally appears after its next 300-second push.

## Ansible says sudo not found

Set `ansible_user=root`. The bundled playbook automatically disables privilege escalation for root. Non-root users need sudo.

## `/home` missing from storage

```bash
systemctl show virtinfra-agent.service -p ProtectHome
```

Expected:

```text
ProtectHome=read-only
```

Redeploy the Agent if it still says `true`.

## Backup/restore problem

```bash
find /var/backups/bw-monitor -maxdepth 2 -name SHA256SUMS -print
virtinfra-monitorctl logs postgres 300
```

The restore command creates a pre-restore dump before replacing the database.
