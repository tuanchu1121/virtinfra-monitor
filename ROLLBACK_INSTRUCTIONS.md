# r7 rollback instructions

Use `ROLLBACK_NOTES_R7.md` for the verified source rollback procedure.

The rollback must preserve the PostgreSQL database, `bw_monitor_postgres_data`, environment files, metrics, logs, Node Groups and membership history. Stop only `bw-monitor.service` while replacing application source, compile before start, and verify `/livez` plus `/healthz`. If verification fails, restore the source backup created immediately before rollback.
