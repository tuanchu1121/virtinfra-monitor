# Node Groups UI Regression Report

The comparison uses deterministic HTML snapshots with the same seeded inventory and fixed time.
All original inline `<style>` blocks must remain byte-identical. Existing cards, data headers, row actions, filters, navigation entries and table wrappers must be preserved, except the explicitly removed Nodes/VMs bulk checkbox column and bulk Apply button.

| Page | Cards | Old headers | Old buttons | Old filters | Group filter | CSS | Navigation | Result |
|---|---:|---|---|---|---:|---|---|---|
| admin-maintenance | 11→12 | PASS | PASS | PASS | 0 | IDENTICAL | PASS | PASS |
| admin-node-groups | 2→2 | PASS | PASS | PASS | 0 | IDENTICAL | PASS | PASS |
| admin-nodes | 2→2 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| admin-overview | 6→5 | PASS | PASS | PASS | 0 | IDENTICAL | PASS | PASS |
| admin-vms | 2→2 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| consumption | 5→5 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| dashboard | 4→4 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| node-health | 2→2 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| storage-io | 5→5 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| top-vm | 3→3 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |
| vm-abuse | 4→4 | PASS | PASS | PASS | 1 | IDENTICAL | PASS | PASS |

Overall: **PASS**
