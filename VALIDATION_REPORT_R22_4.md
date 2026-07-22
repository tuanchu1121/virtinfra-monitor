# Validation Report R22.4

- Target regression: `tests/test_v5059_r1_contract_equivalence.py`
- Root cause: obsolete aggregate SQL digest from the pre-R22.1 baseline.
- Resolution: protected migrations are checked individually against the approved per-file digest manifest.
- Runtime code changed: no.
