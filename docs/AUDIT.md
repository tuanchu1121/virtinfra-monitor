# Audit and diagnostics

Fast health:

```bash
virtinfra-monitorctl doctor
```

Deep read-only audit:

```bash
virtinfra-monitorctl audit
```

Database details:

```bash
virtinfra-monitorctl db-check
```

Sanitized support bundle:

```bash
virtinfra-monitorctl diagnostics
```

Release source audit:

```bash
./tools/release-audit.sh
```
