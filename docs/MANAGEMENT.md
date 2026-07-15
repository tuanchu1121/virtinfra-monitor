# Management CLI

`virtinfra-monitorctl` is installed at `/usr/local/sbin/virtinfra-monitorctl`.

```bash
virtinfra-monitorctl help
```

Core commands:

```bash
virtinfra-monitorctl status
virtinfra-monitorctl doctor
virtinfra-monitorctl audit
virtinfra-monitorctl db-check
virtinfra-monitorctl urls
virtinfra-monitorctl credentials
virtinfra-monitorctl version
```

Logs:

```bash
virtinfra-monitorctl logs monitor 300
virtinfra-monitorctl logs retention 300
virtinfra-monitorctl logs postgres 300
virtinfra-monitorctl logs all 300
virtinfra-monitorctl follow monitor
virtinfra-monitorctl follow postgres
```

Database and maintenance:

```bash
virtinfra-monitorctl psql
virtinfra-monitorctl retention
virtinfra-monitorctl vacuum
virtinfra-monitorctl backup
virtinfra-monitorctl restore --from PATH --yes
```

Deployment:

```bash
virtinfra-monitorctl update
virtinfra-monitorctl domain status
virtinfra-monitorctl domain set monitor.example.com ops@example.com
virtinfra-monitorctl domain remove 203.0.113.10 8080
```

The `vacuum` command runs online PostgreSQL `VACUUM/ANALYZE`; it is not a file rewrite operation.
