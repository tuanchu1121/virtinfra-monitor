# Changelog

## 50.5.9-prod-r10-fresh-install-update-split

### Fresh installation

- `install.sh` is now fresh-install only.
- Existing application configuration, `/opt/bw-monitor`, the `bw-timescaledb` container and the `bw_monitor_postgres_data` volume cause a fail-closed stop instead of an implicit update.
- Removed the interactive `setup.sh` wizard and obsolete Core/Enterprise install, update and uninstall aliases.

### Update

- `update.sh` is the only update bootstrap.
- Update mode requires an existing Monitor configuration.
- PostgreSQL backup, current configuration, credentials, tokens, domain/TLS state and data preservation remain in the update path.
- Domain set/remove commands now call `update.sh`, not the fresh installer.

### Repository and documentation

- Removed duplicate release-history reports, obsolete rollback instructions and duplicate top-level manuals.
- Removed historical low-I/O and Storage V2 compatibility documents that duplicated current contracts.
- Rewrote the primary installation/update documentation around the explicit fresh/update split.

### Runtime compatibility

The Flask runtime, Agent, SQL schema, static assets and all CPU, RAM, network, PPS, disk, bandwidth, Abuse, queue, retention and maintenance calculations are unchanged apart from the release identity string.
