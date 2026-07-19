# Runtime mapping — r7 production-minimal hotfix

The effective application is assembled at the end of `app/app.py`. After every legacy definition and monkey patch has run, that loader imports `app/node_groups.py` and calls `install(module)`. The r7 changes therefore target only that final installer layer, plus the shared page refresh constant in the effective `page()` renderer.

| Endpoint / surface | Route | Original effective function before r7 install | Runtime function after r7 install | File changed | Reason |
|---|---|---|---|---|---|
| `admin_page` | `/admin` | `admin_page_v48134` | `node_groups.admin_page` | `app/node_groups.py` | Capability-scoped overview/navigation and canonical Nodes/VMs/Groups renderers |
| `admin_users_page` | `/admin/users` | `admin_users_page` | `node_groups.admin_users_page` | `app/node_groups.py` | Admin manages Viewer/Admin; Super Admin targets remain protected |
| `admin_create_user` | `/admin/users/create` | `admin_create_user` | `node_groups.admin_create_user` | `app/node_groups.py` | Prevent Admin creation/elevation to Super Admin |
| `admin_user_action` | `/admin/users/action` | `admin_user_action` | `node_groups.admin_user_action` | `app/node_groups.py` | Enforce target-role boundary at backend |
| `admin_change_password` | `/admin/password` | legacy global-admin implementation | `node_groups.admin_change_password` | `app/node_groups.py` | Update only current `dashboard_users.id`, preserving username/role |
| Node Groups admin | `/admin?section=groups` | r6 `node_groups.admin_page` branch | r7 `node_groups.admin_page` branch | `app/node_groups.py` | Fix group search/action/rendering without a new endpoint |
| `admin_node_groups_bulk` | `/admin/node-groups/bulk` | r6 `node_groups.admin_node_groups_bulk` | r7 same canonical function | `app/node_groups.py` | Resolve `move_all_ungrouped` target internally |
| Admin Nodes | `/admin?section=nodes` | `_v48134_admin_nodes_section` | `node_groups.admin_nodes_section` | `app/node_groups.py` | Direct row actions, sorting and separate Agent/Group visibility state |
| Admin VMs | `/admin?section=vms` | `_v48134_admin_vms_section` | `node_groups.admin_vms_section` | `app/node_groups.py` | Direct row actions and aligned canonical columns |
| `vm_abuse_page` | `/abuse` | existing final view | existing view with r7 visibility helpers | `app/node_groups.py` | Keep Abuse logic unchanged; exclude hidden-group inventory |
| `storage_io_page` | `/storage` | existing final view | `node_groups.storage_io_page` | `app/node_groups.py` | Active-group visibility and existing Search/Clear toolbar |
| `bandwidth_consumption_page` | `/bandwidth-consumption` | `bandwidth_consumption_page_v5058c` | `node_groups.bandwidth_consumption_page` | `app/node_groups.py` | Active-group filtering and aligned Group aggregation |
| `node_page` | `/node/<node>` | existing final Node detail view | r7 visibility guard, then original view | `app/node_groups.py` | Return 404 for hidden node/group outside Admin |
| `vm_page` | `/node/<node>/vm/<vm_uuid>` | existing final VM detail view | r7 visibility guard, then original view | `app/node_groups.py` | Return 404 for hidden VM/node/group; prevent inherited icon leakage |
| Shared monitoring refresh | effective HTML `page()` | 5-second global timer | one 30-second timer with cleanup | `app/app.py` | Avoid duplicate intervals and overlapping refresh requests |

The installer also replaces the final helper symbols used by these views: `_v490_admin_nav`, `_v490_admin_overview`, `_v48134_admin_nodes`, `_v48134_admin_vms`, `get_node_rows`, `get_node_health_rows`, `get_top_vm_rows`, Storage helpers, Consumption helpers and VM Abuse query helpers. No older shadowed function was edited.

