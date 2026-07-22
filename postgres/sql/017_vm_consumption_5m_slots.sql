\set ON_ERROR_STOP on

-- R22.10: keep twelve five-minute byte slots inside each canonical VM hourly
-- row. Existing hourly/daily totals remain authoritative for complete hours
-- and days. The slot columns are intentionally nullable so adding them is a
-- metadata-only migration for existing high-cardinality hypertable chunks.
ALTER TABLE public.vm_consumption_hourly
    ADD COLUMN IF NOT EXISTS rx_5m_slots BIGINT[],
    ADD COLUMN IF NOT EXISTS tx_5m_slots BIGINT[],
    ADD COLUMN IF NOT EXISTS sample_5m_mask INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.vm_consumption_hourly.rx_5m_slots IS
    'Twelve five-minute host RX byte totals for this VM/bridge/hour; index 1 represents minute 00-05.';
COMMENT ON COLUMN public.vm_consumption_hourly.tx_5m_slots IS
    'Twelve five-minute host TX byte totals for this VM/bridge/hour; index 1 represents minute 00-05.';
COMMENT ON COLUMN public.vm_consumption_hourly.sample_5m_mask IS
    'Low twelve bits mark which five-minute slots were received for this VM/bridge/hour.';

INSERT INTO bw_meta.schema_migrations(version,description)
VALUES (
    '017_vm_consumption_5m_slots',
    'Packed five-minute VM Consumption slots for exact rolling windows without raw history scans'
)
ON CONFLICT(version) DO NOTHING;
