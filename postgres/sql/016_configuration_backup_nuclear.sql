\set ON_ERROR_STOP on

-- R22.5 selective configuration backup/restore and true Nuclear Reset support.
CREATE TABLE IF NOT EXISTS public.pending_node_group_restore (
    node TEXT PRIMARY KEY,
    group_name TEXT NOT NULL,
    restored_at BIGINT NOT NULL,
    restored_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_pending_node_group_restore_group
ON public.pending_node_group_restore (LOWER(group_name), node);

ALTER TABLE public.maintenance_nuclear_audit
    ADD COLUMN IF NOT EXISTS actor_user_id BIGINT,
    ADD COLUMN IF NOT EXISTS started_at BIGINT,
    ADD COLUMN IF NOT EXISTS finished_at BIGINT,
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS backup_status TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS backup_kind TEXT NOT NULL DEFAULT '';

DELETE FROM public.maintenance_nuclear_audit old
USING public.maintenance_nuclear_audit newer
WHERE old.job_id IS NOT NULL
  AND old.job_id=newer.job_id
  AND old.id<newer.id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_maintenance_nuclear_audit_job
ON public.maintenance_nuclear_audit (job_id)
WHERE job_id IS NOT NULL;

CREATE OR REPLACE FUNCTION virtinfra_assign_ungrouped_membership()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    target_group_id BIGINT;
    pending_group_name TEXT;
BEGIN
    SELECT group_name INTO pending_group_name
      FROM public.pending_node_group_restore
     WHERE node=NEW.node;

    IF pending_group_name IS NOT NULL THEN
        SELECT id INTO target_group_id
          FROM public.node_groups
         WHERE LOWER(name)=LOWER(pending_group_name)
           AND COALESCE(is_system,0)=0
         ORDER BY id LIMIT 1;
    END IF;

    IF target_group_id IS NULL THEN
        SELECT id INTO target_group_id
          FROM public.node_groups
         WHERE is_system=1
         ORDER BY id LIMIT 1;
    END IF;

    IF target_group_id IS NULL THEN
        INSERT INTO public.node_groups(
            name,description,country_code,is_active,is_system,
            created_at,updated_at,hidden_at
        ) VALUES (
            'Ungrouped','Default group for nodes without an explicit assignment',
            '',1,1,EXTRACT(EPOCH FROM NOW())::BIGINT,
            EXTRACT(EPOCH FROM NOW())::BIGINT,NULL
        ) RETURNING id INTO target_group_id;
    END IF;

    INSERT INTO public.node_group_memberships(node,group_id,assigned_at,assigned_by)
    VALUES (NEW.node,target_group_id,EXTRACT(EPOCH FROM NOW())::BIGINT,
            CASE WHEN pending_group_name IS NULL THEN 'trigger' ELSE 'configuration-restore' END)
    ON CONFLICT(node) DO UPDATE SET
        group_id=EXCLUDED.group_id,
        assigned_at=EXCLUDED.assigned_at,
        assigned_by=EXCLUDED.assigned_by;

    IF pending_group_name IS NOT NULL THEN
        DELETE FROM public.pending_node_group_restore WHERE node=NEW.node;
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS trg_node_inventory_assign_ungrouped ON public.node_inventory;
CREATE TRIGGER trg_node_inventory_assign_ungrouped
AFTER INSERT ON public.node_inventory
FOR EACH ROW EXECUTE FUNCTION virtinfra_assign_ungrouped_membership();

INSERT INTO bw_meta.schema_migrations(version, description)
VALUES ('016_configuration_backup_nuclear', 'Selective Configuration Backup/Restore and true Nuclear Reset hardening')
ON CONFLICT(version) DO NOTHING;
