\set ON_ERROR_STOP on

-- VirtInfra Monitor 50.5.6 PostgreSQL-native maintenance guard.
-- Reconcile any stale duplicate active rows before creating the hard database
-- invariant. The newest active row survives; older duplicates become errors.
WITH ranked AS (
    SELECT id,
           row_number() OVER (ORDER BY id DESC) AS rn
    FROM public.maintenance_jobs
    WHERE status IN ('queued', 'running')
)
UPDATE public.maintenance_jobs AS jobs
SET status = 'error',
    finished_at = COALESCE(jobs.finished_at, EXTRACT(EPOCH FROM clock_timestamp())::bigint),
    message = 'Recovered duplicate active maintenance row during 50.5.6 migration'
FROM ranked
WHERE jobs.id = ranked.id
  AND ranked.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_maintenance_jobs_one_active
ON public.maintenance_jobs ((1))
WHERE status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_maintenance_jobs_status_created
ON public.maintenance_jobs (status, created_at DESC);
