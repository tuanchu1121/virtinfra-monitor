# Release notes R8

Release: `50.5.9-prod-r8-safe-dead-code-prune`

This release conservatively removes 26 superseded runtime function implementations totaling 1,208 physical lines. The audit was repeated until a fixed point was reached; the third pass found no additional safe candidates.

It does not intentionally change routes, endpoint names, payloads, database schema, UI assets, monitoring formulas, Agent protocol, retention, maintenance, queueing or RBAC behavior. Implementations retained by Flask, wrappers, closures or compatibility aliases were not removed.
