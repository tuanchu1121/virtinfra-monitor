\set ON_ERROR_STOP on

-- Normalize legacy maintenance queue schemas created through the SQLite
-- compatibility layer. Older releases defined cancel_requested as INTEGER,
-- which PostgreSQL translated to BIGINT. The queue and dispatcher use Boolean
-- predicates, so every existing installation must converge on BOOLEAN.
DO $$
DECLARE
    current_type text;
BEGIN
    SELECT data_type
      INTO current_type
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = 'maintenance_jobs'
       AND column_name = 'cancel_requested';

    IF current_type IS NULL THEN
        ALTER TABLE public.maintenance_jobs
            ADD COLUMN cancel_requested BOOLEAN NOT NULL DEFAULT FALSE;
    ELSIF current_type IN ('bigint', 'integer', 'smallint', 'numeric') THEN
        ALTER TABLE public.maintenance_jobs
            ALTER COLUMN cancel_requested DROP DEFAULT;
        ALTER TABLE public.maintenance_jobs
            ALTER COLUMN cancel_requested TYPE BOOLEAN
            USING (COALESCE(cancel_requested, 0) <> 0);
        ALTER TABLE public.maintenance_jobs
            ALTER COLUMN cancel_requested SET DEFAULT FALSE;
        ALTER TABLE public.maintenance_jobs
            ALTER COLUMN cancel_requested SET NOT NULL;
    ELSIF current_type = 'boolean' THEN
        UPDATE public.maintenance_jobs
           SET cancel_requested = FALSE
         WHERE cancel_requested IS NULL;
        ALTER TABLE public.maintenance_jobs
            ALTER COLUMN cancel_requested SET DEFAULT FALSE;
        ALTER TABLE public.maintenance_jobs
            ALTER COLUMN cancel_requested SET NOT NULL;
    ELSE
        RAISE EXCEPTION
            'Unsupported public.maintenance_jobs.cancel_requested type: %',
            current_type;
    END IF;
END
$$;

DO $$
DECLARE
    final_type text;
BEGIN
    SELECT data_type
      INTO final_type
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = 'maintenance_jobs'
       AND column_name = 'cancel_requested';
    IF final_type IS DISTINCT FROM 'boolean' THEN
        RAISE EXCEPTION
            'maintenance_jobs.cancel_requested migration failed; type is %',
            final_type;
    END IF;
END
$$;
