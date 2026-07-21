\set ON_ERROR_STOP on

-- R22.11: distinguish the corrected end-of-interval five-minute slot mapping.
-- Existing R22.10 packed arrays remain physically untouched and are ignored by
-- exact edge reads until that hourly row receives a corrected v2 slot. The
-- existing hourly byte totals remain available to the bounded warm-up fallback.
ALTER TABLE public.vm_consumption_hourly
    ADD COLUMN IF NOT EXISTS slot_5m_version SMALLINT NOT NULL DEFAULT 1;

COMMENT ON COLUMN public.vm_consumption_hourly.slot_5m_version IS
    '1=legacy R22.10 start-boundary mapping; 2=end-of-interval mapping where a push at 20:00 belongs to 19:55-20:00.';

INSERT INTO bw_meta.schema_migrations(version,description)
VALUES (
    '018_vm_consumption_slot_boundary_semantics',
    'Correct VM five-minute slot boundary semantics without rewriting historical hourly rows'
)
ON CONFLICT(version) DO NOTHING;
