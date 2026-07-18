\set ON_ERROR_STOP on

CREATE SCHEMA IF NOT EXISTS bw_meta;

CREATE TABLE IF NOT EXISTS bw_meta.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now(),
    description text NOT NULL DEFAULT ''
);

INSERT INTO bw_meta.schema_migrations(version, description)
VALUES ('001_bootstrap', 'PostgreSQL-native bootstrap')
ON CONFLICT (version) DO NOTHING;
