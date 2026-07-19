# VirtInfra Monitor modular runtime

Release: `50.5.9-prod-r7-modular-runtime-refactor`

## Purpose

The former `app/app.py` contained the complete append-only runtime in one file. The new entrypoint is intentionally small and loads ordered runtime components from `app/runtime_layers/`.

This release is a structural refactor only. It preserves the existing Flask application object, route paths, endpoint names, payloads, SQL behavior, schema, queue behavior, retention behavior and compatibility overrides.

## Runtime layout

- `app/app.py`: WSGI entrypoint.
- `app/runtime_loader.py`: validates and executes the ordered runtime layer manifest.
- `app/runtime_layers/manifest.json`: canonical file order, original source ranges and SHA-256 for every layer.
- `app/runtime_layers/00_*.py` through `43_*.py`: functional and compatibility layers.
- `app/node_groups.py`: additive Node Groups/RBAC integration, retained as an independently testable module.

Each layer is compiled using its own filename, then executed in the shared `app.py` module namespace. This keeps the exact historical binding order while making stack traces and reviews point to the responsible component.

## Safety properties

- The combined layer source is byte-equivalent to the pre-refactor runtime.
- Runtime validation confirms the same 83 Flask routes.
- Existing contract tests read the canonical combined runtime through `tests/runtime_source.py`.
- The production installer removes stale runtime layers before installing the current manifest.
- `preflight.sh` verifies syntax, hashes, architecture, route contracts and installer packaging.

## Rollback

No database migration is introduced. Rollback is source-only:

1. Stop `virtinfra-monitor.service`.
2. Restore the previous application source and `DEPLOY_VERSION` from backup.
3. Start the service.
4. Verify `/livez`, `/healthz`, login and `/push`.

Do not leave a mixed deployment containing the new `app.py` without `runtime_loader.py` and the complete `runtime_layers/` directory.
