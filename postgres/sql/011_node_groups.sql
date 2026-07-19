\set ON_ERROR_STOP on

-- 50.5.9-r5 additive Node Groups schema.
-- No metric/history table is altered. Existing nodes are assigned to the
-- immutable system group "Ungrouped".

CREATE TABLE IF NOT EXISTS node_groups (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    country_code VARCHAR(2) NOT NULL DEFAULT '',
    is_active SMALLINT NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    is_system SMALLINT NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    hidden_at BIGINT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_node_groups_name_ci
    ON node_groups (LOWER(name));
CREATE UNIQUE INDEX IF NOT EXISTS uq_node_groups_single_system
    ON node_groups (is_system) WHERE is_system = 1;

INSERT INTO node_groups(
    name, description, country_code, is_active, is_system,
    created_at, updated_at, hidden_at
)
SELECT 'Ungrouped', 'Default group for nodes without an explicit assignment', '', 1, 1,
       EXTRACT(EPOCH FROM NOW())::BIGINT, EXTRACT(EPOCH FROM NOW())::BIGINT, NULL
WHERE NOT EXISTS (SELECT 1 FROM node_groups WHERE is_system = 1);

CREATE TABLE IF NOT EXISTS node_group_memberships (
    node TEXT PRIMARY KEY REFERENCES node_inventory(node) ON DELETE CASCADE,
    group_id BIGINT NOT NULL REFERENCES node_groups(id) ON DELETE RESTRICT,
    assigned_at BIGINT NOT NULL,
    assigned_by TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_node_group_memberships_group_node
    ON node_group_memberships (group_id, node);

CREATE TABLE IF NOT EXISTS node_group_membership_history (
    id BIGSERIAL PRIMARY KEY,
    event TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    node TEXT,
    old_group_id BIGINT,
    old_group_name TEXT NOT NULL DEFAULT '',
    new_group_id BIGINT,
    new_group_name TEXT NOT NULL DEFAULT '',
    created_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_node_group_history_time
    ON node_group_membership_history (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_node_group_history_node_time
    ON node_group_membership_history (node, created_at DESC);

INSERT INTO node_group_memberships(node, group_id, assigned_at, assigned_by)
SELECT ni.node, ng.id, EXTRACT(EPOCH FROM NOW())::BIGINT, 'migration'
  FROM node_inventory ni
 CROSS JOIN LATERAL (
       SELECT id FROM node_groups WHERE is_system = 1 ORDER BY id LIMIT 1
 ) ng
 WHERE NOT EXISTS (
       SELECT 1 FROM node_group_memberships m WHERE m.node = ni.node
 );

-- One-time role namespace migration. The marker makes the operation idempotent:
-- old role=admin accounts become super_admin once, while future role=admin
-- accounts remain the new restricted administrator role.
DO $node_groups_role_migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM admin_settings
         WHERE key = 'node_groups_role_migration_v1'
    ) THEN
        UPDATE dashboard_users
           SET role = 'super_admin', updated_at = EXTRACT(EPOCH FROM NOW())::BIGINT
         WHERE role = 'admin';

        INSERT INTO admin_settings(key, value, updated_at)
        VALUES (
            'node_groups_role_migration_v1',
            'completed',
            EXTRACT(EPOCH FROM NOW())::BIGINT
        )
        ON CONFLICT(key) DO NOTHING;
    END IF;
END
$node_groups_role_migration$;
