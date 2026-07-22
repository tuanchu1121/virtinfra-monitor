# Validation Report R22.12.1

Release: `50.5.9-prod-r22.12.2-preflight-contract-hotfix`

## Result

The R22.12 installer preflight contract mismatch is fixed without changing the
VM shared snapshot runtime, migration 019 contents, UI, API, Agent or ingest.

## Validation completed

- Original failing equivalence file: 4 tests passed.
- Focused snapshot, Consumption, runtime architecture, manifest, installer and
  responsive UI set: 55 tests passed.
- `tools/test-installer-flow.sh`: passed.
- `tools/test-installer-manifest-paths.sh`: passed.
- Canonical `SHA256SUMS`: exact coverage and valid hashes.
- Shell syntax was validated by the preflight before dependency installation.

## Environment limitations

The complete isolated `preflight.sh` could not proceed past dependency setup
because the build environment has no Internet access and pip could not download
PyYAML. A full repository pytest collection was also unavailable in the base
interpreter because `psycopg` is not installed there. These were environment
limitations, not assertion failures from the patched source.

## Runtime impact

None. This release changes only legacy preflight/test fixtures and release
identity metadata. It does not change query execution, database tables,
statement timeout, sorting behavior, routes or response payloads.
