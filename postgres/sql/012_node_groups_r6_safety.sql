\set ON_ERROR_STOP on

-- 50.5.9-r6 Node Groups safety and hot-path decoupling.
-- Additive and idempotent. No metric table is altered.

CREATE INDEX IF NOT EXISTS idx_node_group_memberships_node
    ON node_group_memberships (node);
CREATE INDEX IF NOT EXISTS idx_node_group_memberships_group_id
    ON node_group_memberships (group_id);
CREATE INDEX IF NOT EXISTS idx_node_groups_hidden
    ON node_groups (is_active, hidden_at, id);

INSERT INTO node_groups(
    name, description, country_code, is_active, is_system,
    created_at, updated_at, hidden_at
)
SELECT 'Ungrouped',
       'Default group for nodes without an explicit assignment',
       '', 1, 1,
       EXTRACT(EPOCH FROM NOW())::BIGINT,
       EXTRACT(EPOCH FROM NOW())::BIGINT,
       NULL
WHERE NOT EXISTS (SELECT 1 FROM node_groups WHERE is_system = 1);

INSERT INTO node_group_memberships(node, group_id, assigned_at, assigned_by)
SELECT ni.node, ng.id, EXTRACT(EPOCH FROM NOW())::BIGINT, 'migration-r6'
  FROM node_inventory ni
 CROSS JOIN LATERAL (
       SELECT id FROM node_groups WHERE is_system = 1 ORDER BY id LIMIT 1
 ) ng
 WHERE NOT EXISTS (
       SELECT 1 FROM node_group_memberships gm WHERE gm.node = ni.node
 );

CREATE OR REPLACE FUNCTION virtinfra_assign_ungrouped_membership()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    target_group_id BIGINT;
BEGIN
    SELECT id INTO target_group_id
      FROM node_groups
     WHERE is_system = 1
     ORDER BY id
     LIMIT 1;

    IF target_group_id IS NULL THEN
        INSERT INTO node_groups(
            name, description, country_code, is_active, is_system,
            created_at, updated_at, hidden_at
        ) VALUES (
            'Ungrouped',
            'Default group for nodes without an explicit assignment',
            '', 1, 1,
            EXTRACT(EPOCH FROM NOW())::BIGINT,
            EXTRACT(EPOCH FROM NOW())::BIGINT,
            NULL
        )
        RETURNING id INTO target_group_id;
    END IF;

    INSERT INTO node_group_memberships(node, group_id, assigned_at, assigned_by)
    VALUES (
        NEW.node,
        target_group_id,
        EXTRACT(EPOCH FROM NOW())::BIGINT,
        'trigger'
    )
    ON CONFLICT (node) DO NOTHING;

    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS trg_node_inventory_assign_ungrouped ON node_inventory;
CREATE TRIGGER trg_node_inventory_assign_ungrouped
AFTER INSERT ON node_inventory
FOR EACH ROW
EXECUTE FUNCTION virtinfra_assign_ungrouped_membership();
