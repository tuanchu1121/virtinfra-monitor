# Contributing

1. Create a branch.
2. Preserve the exact Agent defaults unless the change explicitly updates the protocol: local sample 15 seconds, durable push 300 seconds.
3. Keep PostgreSQL/TimescaleDB as the only authoritative runtime database.
4. Do not add a second persistent store or make Redis authoritative.
5. Keep the existing UI/routes and operational behavior backward compatible unless the release notes explicitly document a change.
6. Run:

```bash
./preflight.sh
```

For database/runtime changes, run against a disposable PostgreSQL database:

```bash
BW_TEST_DATABASE_URL='postgresql://user:pass@127.0.0.1:5432/bw_monitor_test' \
./preflight.sh --use-current-python
```

Before release:

```bash
./tools/release-audit.sh
./tools/build-dist.sh
```

Never commit credentials, production inventories, dumps, keys or generated archives.
