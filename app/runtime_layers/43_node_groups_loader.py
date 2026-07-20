# Release: 50.5.9-prod-r18-user-rbac-session-hardening-hotfix
# Installed only after all existing append-only runtime implementations are
# registered, so baseline wrappers and view functions remain intact.
import sys as _node_groups_sys
import node_groups as _node_groups_hotfix

class _NodeGroupsModuleProxy:
    """Forward module attribute access to this exec_module() globals mapping."""

    def __getattr__(self, name):
        try:
            return globals()[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        globals()[name] = value

_node_groups_module = _node_groups_sys.modules.get(__name__)
if _node_groups_module is None:
    _node_groups_module = _NodeGroupsModuleProxy()
_node_groups_hotfix.install(_node_groups_module)
