# Modular runtime refactor report R7

Release: `50.5.9-prod-r7-modular-runtime-refactor`

## Result

- `app/app.py`: reduced from 36,449 lines to a 14-line WSGI entrypoint.
- Runtime: split into 44 ordered files under `app/runtime_layers/`.
- Largest runtime layer: fewer than 1,800 lines.
- Canonical order and per-layer SHA-256 are stored in `app/runtime_layers/manifest.json`.
- Existing modules such as `bw_pg.py`, `node_groups.py`, maintenance, retention and storage remain separate.

## Compatibility model

The loader compiles each runtime layer using its own filename and executes it in the shared application module namespace. This preserves the historical append-only override order, Flask application object and global function bindings.

This is an intentionally conservative transition architecture. It removes the single-file bottleneck and improves review/debugging without attempting a high-risk rewrite into independent Flask blueprints in the same release.

## Preserved contracts

- 83 Flask routes, endpoint names and HTTP methods.
- Request query/form keys and `url_for()` endpoint references.
- Agent protocol and `/push` behavior.
- PostgreSQL schema and SQL migrations.
- Maintenance queue, retention and storage behavior.
- UI compatibility layers and Node Groups loader order.

## Packaging changes

The canonical bootstrap and production installer now require and deploy:

- `app/runtime_loader.py`
- `app/runtime_layers/manifest.json`
- every `app/runtime_layers/*.py` file

The installer removes stale runtime layer files before installing the current set.

## Scope boundary

This release is a structural refactor. Known functional and RBAC findings from the prior review were intentionally not mixed into this change, so behavioral equivalence can be verified independently. Those fixes should be delivered as a separate hotfix with dedicated authorization tests.
