-- CityPulse Phase 2 migration: provider-aware ingestion columns + ops tables.
-- Idempotent: safe to run multiple times. Never drops or recreates civic_data,
-- so existing Phase 1 rows are preserved.

-- 1. Extra provenance / metric columns on civic_data -------------
ALTER TABLE civic_data ADD COLUMN IF NOT EXISTS provider   TEXT;
ALTER TABLE civic_data ADD COLUMN IF NOT EXISTS metric     TEXT;
ALTER TABLE civic_data ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE civic_data ADD COLUMN IF NOT EXISTS metadata   JSONB;

CREATE INDEX IF NOT EXISTS idx_civic_data_metric    ON civic_data (source_type, metric);
CREATE INDEX IF NOT EXISTS idx_civic_data_provider  ON civic_data (provider);
CREATE INDEX IF NOT EXISTS idx_civic_data_rec_city  ON civic_data (city, recorded_at DESC);

-- 2. Provider health tracking ------------------------------------
CREATE TABLE IF NOT EXISTS provider_status (
    source_type        TEXT PRIMARY KEY,
    provider           TEXT NOT NULL,
    is_configured      BOOLEAN NOT NULL DEFAULT FALSE,
    is_synthetic       BOOLEAN NOT NULL DEFAULT FALSE,
    last_attempt_at    TIMESTAMPTZ,
    last_success_at    TIMESTAMPTZ,
    last_error         TEXT,
    record_count_last  INTEGER NOT NULL DEFAULT 0,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Ingestion audit log (bounded retention; see ingest.py) -------
CREATE TABLE IF NOT EXISTS ingestion_log (
    id          BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    ok          BOOLEAN,
    records     INTEGER,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingestion_log_started ON ingestion_log (started_at DESC);
