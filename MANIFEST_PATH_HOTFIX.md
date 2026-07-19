# Manifest path hotfix

## Root cause

The release `SHA256SUMS` uses safe relative filenames such as `.editorconfig`
and `app/app.py`. The bootstrap validator incorrectly required every manifest
filename to begin with `./`, so installation stopped before staging the source.

## Fix

`install.sh` now accepts both canonical safe relative forms:

- `.editorconfig`
- `./.editorconfig`
- `app/app.py`
- `./app/app.py`

It continues to reject empty paths, absolute paths, traversal components (`..`),
embedded current-directory components, and duplicate separators.

## Runtime impact

None. This patch only changes bootstrap manifest path validation. Application,
Node Groups, PostgreSQL schema, agent, metrics, retention, UI, and service
runtime code are unchanged.
