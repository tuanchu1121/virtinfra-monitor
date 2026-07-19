# Node Groups UI Regression Report

The comparison uses deterministic HTML snapshots with the same seeded inventory and fixed time.
All original inline `<style>` blocks must remain byte-identical. Existing cards, headers, buttons, filters, navigation entries and table wrappers must be preserved.

| Page | Cards | Old headers | Old buttons | Old filters | Group filter | CSS | Navigation | Result |
|---|---:|---|---|---|---:|---|---|---|
| admin-nodes | 2→2 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| admin-overview | 6→6 | PASS | PASS | PASS | 0 | IDENTICAL | PASS | PASS |
| admin-vms | 2→2 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| consumption | 5→5 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| dashboard | 4→4 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| node-health | 2→2 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| storage-io | 5→5 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| top-vm | 3→3 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| vm-abuse | 4→4 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |

Overall: **PASS**
