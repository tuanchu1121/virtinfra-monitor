\set ON_ERROR_STOP on

-- MAC identity is bounded inventory metadata, not a historical metric.
-- These additive columns are populated by existing Agents on their next
-- accepted push. No Agent protocol or payload change is required.
ALTER TABLE public.vm_iface_current
    ADD COLUMN IF NOT EXISTS mac TEXT NOT NULL DEFAULT '';

ALTER TABLE public.node_physical_net_latest
    ADD COLUMN IF NOT EXISTS mac TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_vm_iface_current_mac
    ON public.vm_iface_current (LOWER(mac));

CREATE INDEX IF NOT EXISTS idx_node_physical_net_latest_mac
    ON public.node_physical_net_latest (LOWER(mac));
