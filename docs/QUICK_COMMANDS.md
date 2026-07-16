# Quick commands

```bash
virtinfra-monitorctl status
virtinfra-monitorctl doctor
virtinfra-monitorctl db-check
virtinfra-monitorctl logs all 200
virtinfra-monitorctl follow monitor
virtinfra-monitorctl restart
virtinfra-monitorctl backup
virtinfra-monitorctl retention
virtinfra-monitorctl vacuum
virtinfra-monitorctl psql
virtinfra-monitorctl urls
virtinfra-monitorctl credentials
virtinfra-monitorctl version
virtinfra-monitorctl update
```

Agent:

```bash
systemctl status virtinfra-agent.service --no-pager -l
journalctl -fu virtinfra-agent.service
```

Ansible Agent deployment:

```bash
bash ansible/deploy-agent.sh \
-i ansible/test.txt \
--api 'https://monitor.example.com/push' \
--token "$BW_TOKEN" \
--forks 20 \
--serial 10
```

Maintenance queue:

```bash
systemctl status bw-monitor-maintenance-watchdog.timer --no-pager
systemctl start bw-monitor-maintenance-dispatch.service
journalctl -u bw-monitor-maintenance-dispatch.service -n 200 --no-pager
```

Agent identity/state repair:

```bash
bash ./fix-agent-uuid.sh --node NEW-NODE-NAME
bash ./fix-agent-uuid.sh --purge-vm OLD-VM-UUID
```
