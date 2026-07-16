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
