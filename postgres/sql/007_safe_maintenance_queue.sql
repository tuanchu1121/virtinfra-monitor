\set ON_ERROR_STOP on

-- VirtInfra Monitor 50.5.7 safe FIFO maintenance queue.
ALTER TABLE public.maintenance_jobs
    ADD COLUMN IF NOT EXISTS heartbeat_at BIGINT,
    ADD COLUMN IF NOT EXISTS progress INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN NOT NULL DEFAULT FALSE;

DROP INDEX IF EXISTS public.uq_maintenance_jobs_one_active;

-- Retire actions removed from the product before they can block the new queue.
UPDATE public.maintenance_jobs
   SET status='cancelled',
       finished_at=COALESCE(finished_at, EXTRACT(EPOCH FROM clock_timestamp())::bigint),
       progress=100,
       message='Legacy maintenance action retired during 50.5.7 migration'
 WHERE action IN ('clear_live_cache','checkpoint')
   AND status IN ('queued','starting','running');

-- Older workers only knew queued/running. A running row has no reliable
-- heartbeat after an upgrade, so leave it running and let the watchdog inspect
-- its systemd unit before recovery.
UPDATE public.maintenance_jobs
   SET progress=CASE WHEN status IN ('ok','error','cancelled') THEN 100 ELSE progress END
 WHERE progress IS NULL OR progress < 0 OR progress > 100;

CREATE UNIQUE INDEX IF NOT EXISTS uq_maintenance_jobs_one_worker
ON public.maintenance_jobs ((1))
WHERE status IN ('starting','running');

CREATE INDEX IF NOT EXISTS idx_maintenance_jobs_fifo
ON public.maintenance_jobs (id)
WHERE status='queued';

CREATE INDEX IF NOT EXISTS idx_maintenance_jobs_heartbeat
ON public.maintenance_jobs (status, heartbeat_at)
WHERE status IN ('starting','running');

CREATE TABLE IF NOT EXISTS public.maintenance_nuclear_audit (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT,
    requested_by TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    backup_path TEXT NOT NULL,
    backup_sha256 TEXT NOT NULL,
    release_version TEXT NOT NULL,
    result_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_maintenance_nuclear_audit_created
ON public.maintenance_nuclear_audit (created_at DESC);
