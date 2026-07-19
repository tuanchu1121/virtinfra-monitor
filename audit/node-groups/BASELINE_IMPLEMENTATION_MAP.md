# Baseline Runtime Implementation Map

- Source: `baseline-backup`
- app.py lines: 36432

## Final top-level definitions

| Symbol | Definitions | Runtime-final line |
|---|---|---:|
| `page` | 5878, 14869, 15965, 16128, 16548, 17351, 17386, 17581, 17711, 20650, 20935, 21200, 22561, 23014, 23564, 24319, 28592, 29121, 30933, 36077, 36424 | 36424 |
| `_v490_admin_nav` | 14672, 18981, 30905 | 30905 |
| `_v490_admin_overview` | 14758, 29020, 29814, 30917 | 30917 |
| `_v48134_admin_nodes` | 25697 | 25697 |
| `_v48134_admin_nodes_section` | 25868 | 25868 |
| `_v48134_admin_vms` | 25794 | 25794 |
| `_v48134_admin_vms_section` | 25890 | 25890 |
| `index_v480` | 12175 | 12175 |
| `top_page_v484` | 14239 | 14239 |
| `get_node_health_rows` | 5225 | 5225 |
| `node_health_page` | 7256 | 7256 |
| `storage_io_page_v48138` | 27296 | 27296 |
| `bandwidth_consumption_page_v5058c` | 34274 | 34274 |
| `vm_abuse_page_v48139` | 27667 | 27667 |

## Registered Flask view functions

| Area | Endpoint | Function object | First line |
|---|---|---|---:|
| Admin | `admin_page` | `admin_page_v48134` | 25912 |
| Dashboard | `index` | `index_v480` | 28550 |
| Top VM | `top_page` | `top_page_v484` | 28550 |
| Node Health | `node_health_page` | `node_health_page` | 7255 |
| Storage I/O | `storage_io_page` | `storage_io_page_v48138` | 28550 |
| Consumption | `bandwidth_consumption_page` | `bandwidth_consumption_page_v5058c` | 28550 |
| VM Abuse | `vm_abuse_page` | `vm_abuse_page_v48129` | 28550 |

## Admin section helpers used by the registered Admin page

- Admin Overview: `_v490_admin_overview`, runtime-final line 30917
- Admin Nodes query/renderer: `_v48134_admin_nodes` line 25697 and `_v48134_admin_nodes_section` line 25868
- Admin VMs query/renderer: `_v48134_admin_vms` line 25794 and `_v48134_admin_vms_section` line 25890

The hotfix must attach only after these objects are registered. Earlier duplicate definitions remain untouched.
