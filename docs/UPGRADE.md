# Upgrade

v50 is intended as a fresh PostgreSQL-native installation. This release does not import legacy database data. Agents can be redeployed with the generated v50 token and will repopulate current state on the next 5-minute push.

## Normal v50 update

```bash
virtinfra-monitorctl backup
virtinfra-monitorctl update
virtinfra-monitorctl doctor
```

Or:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/update.sh \
| bash
```

The installer detects the existing v50 environment and preserves PostgreSQL volume, credentials, token, Admin hash, domain/IP mode, TLS state and settings.

## Change release branch/ref

Set in `/etc/default/bw-monitor`:

```text
BW_GITHUB_REPO=tuanchu1121/virtinfra-monitor
BW_GITHUB_REF=main
```

Then run `virtinfra-monitorctl update`.
