BEGIN;

CREATE TABLE IF NOT EXISTS node_groups (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    country_code VARCHAR(2),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    hidden BOOLEAN NOT NULL DEFAULT FALSE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    CONSTRAINT node_groups_country_code_check
      CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{2}$'),
    CONSTRAINT node_groups_name_not_blank
      CHECK (BTRIM(name) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS node_groups_name_unique
    ON node_groups (LOWER(BTRIM(name)));

CREATE UNIQUE INDEX IF NOT EXISTS node_groups_single_default
    ON node_groups (is_default)
    WHERE is_default = TRUE;

CREATE TABLE IF NOT EXISTS node_group_memberships (
    node_name TEXT PRIMARY KEY,
    group_id BIGINT NOT NULL REFERENCES node_groups(id) ON DELETE CASCADE,
    assigned_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    CONSTRAINT node_group_memberships_node_not_blank
      CHECK (BTRIM(node_name) <> '')
);

CREATE INDEX IF NOT EXISTS node_group_memberships_group_idx
    ON node_group_memberships(group_id, node_name);

CREATE TABLE IF NOT EXISTS node_group_membership_history (
    id BIGSERIAL PRIMARY KEY,
    node_name TEXT NOT NULL,
    group_id BIGINT,
    valid_from BIGINT NOT NULL,
    valid_to BIGINT,
    changed_at BIGINT NOT NULL,
    CONSTRAINT node_group_history_node_not_blank
      CHECK (BTRIM(node_name) <> ''),
    CONSTRAINT node_group_history_window_check
      CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE INDEX IF NOT EXISTS node_group_history_lookup_idx
    ON node_group_membership_history(node_name, valid_from, valid_to);

CREATE UNIQUE INDEX IF NOT EXISTS node_group_history_one_open_row
    ON node_group_membership_history(node_name)
    WHERE valid_to IS NULL;

COMMIT;
