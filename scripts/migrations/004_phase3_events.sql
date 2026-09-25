-- CityPulse Phase 3 migration: civic event lifecycle + simulation runs.
-- Idempotent (CREATE ... IF NOT EXISTS / ADD COLUMN IF NOT EXISTS only) and
-- purely additive: no existing table is dropped, renamed, or rewritten, so
-- Phase 1/2 data (civic_data, provider_status, ingestion_log, anomaly_events)
-- is preserved exactly as-is.
--
-- Design notes
-- * civic_events holds civic incidents as first-class records with a status
--   machine (open -> acknowledged -> in_progress -> resolved -> closed).
--   `event_ref` is the stable public identifier shown in the UI/API;
--   `external_key` uniquely identifies an upstream report so re-ingesting the
--   same feed item can never create a duplicate event.
-- * civic_event_timeline is an append-only audit trail for every transition
--   (who/what/when/why), which is what makes the lifecycle explainable.
-- * simulation_runs records synthetic exercises. Simulated events are flagged
--   is_simulated = TRUE so they can always be excluded from operational counts
--   and can never be mistaken for official reports.

-- 1. Civic events ------------------------------------------------------
CREATE TABLE IF NOT EXISTS civic_events (
    id                BIGSERIAL PRIMARY KEY,
    event_ref         TEXT             NOT NULL UNIQUE,
    external_key      TEXT             UNIQUE,
    city              TEXT             NOT NULL,
    city_id           TEXT,
    source_type       TEXT             NOT NULL,
    category          TEXT             NOT NULL,
    title             TEXT             NOT NULL,
    description       TEXT             NOT NULL,
    severity          TEXT             NOT NULL
                      CHECK (severity IN ('low', 'moderate', 'high', 'critical')),
    status            TEXT             NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'acknowledged', 'in_progress',
                                        'resolved', 'closed')),
    latitude          DOUBLE PRECISION NOT NULL,
    longitude         DOUBLE PRECISION NOT NULL,
    location_name     TEXT             NOT NULL,
    reported_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
    acknowledged_at   TIMESTAMPTZ,
    resolved_at       TIMESTAMPTZ,
    closed_at         TIMESTAMPTZ,
    acknowledged_by   TEXT,
    resolved_by       TEXT,
    resolution_note   TEXT,
    evidence          JSONB            NOT NULL DEFAULT '[]'::jsonb,
    tags              JSONB            NOT NULL DEFAULT '[]'::jsonb,
    is_simulated      BOOLEAN          NOT NULL DEFAULT FALSE,
    simulation_run_id TEXT,
    revision          INTEGER          NOT NULL DEFAULT 1,
    created_at        TIMESTAMPTZ      NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ      NOT NULL DEFAULT now()
);

-- Upgrade path for tables created by an earlier revision of this migration.
ALTER TABLE civic_events ADD COLUMN IF NOT EXISTS tags           JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE civic_events ADD COLUMN IF NOT EXISTS revision       INTEGER NOT NULL DEFAULT 1;
ALTER TABLE civic_events ADD COLUMN IF NOT EXISTS simulation_run_id TEXT;
ALTER TABLE civic_events ADD COLUMN IF NOT EXISTS resolution_note TEXT;
ALTER TABLE civic_events ADD COLUMN IF NOT EXISTS closed_at      TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_civic_events_city_status
    ON civic_events (city, status, reported_at DESC);
CREATE INDEX IF NOT EXISTS idx_civic_events_status_updated
    ON civic_events (status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_civic_events_severity
    ON civic_events (severity, status);
CREATE INDEX IF NOT EXISTS idx_civic_events_source
    ON civic_events (source_type, category);
CREATE INDEX IF NOT EXISTS idx_civic_events_sim
    ON civic_events (is_simulated, simulation_run_id);
CREATE INDEX IF NOT EXISTS idx_civic_events_updated
    ON civic_events (updated_at DESC);

-- 2. Append-only lifecycle audit trail --------------------------------
CREATE TABLE IF NOT EXISTS civic_event_timeline (
    id           BIGSERIAL PRIMARY KEY,
    event_id     BIGINT      NOT NULL REFERENCES civic_events (id) ON DELETE CASCADE,
    action       TEXT        NOT NULL,
    from_status  TEXT,
    to_status    TEXT,
    actor        TEXT,
    note         TEXT,
    at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_civic_event_timeline_event
    ON civic_event_timeline (event_id, at);

-- 3. Simulation runs (clearly separated from real civic operations) ----
CREATE TABLE IF NOT EXISTS simulation_runs (
    id               BIGSERIAL PRIMARY KEY,
    run_ref          TEXT        NOT NULL UNIQUE,
    scenario_id      TEXT        NOT NULL,
    scenario_name    TEXT        NOT NULL,
    city             TEXT        NOT NULL,
    city_id          TEXT        NOT NULL,
    status           TEXT        NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'completed', 'reset')),
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    events_created   INTEGER     NOT NULL DEFAULT 0,
    observations_written INTEGER NOT NULL DEFAULT 0,
    actor            TEXT,
    notes            TEXT
);

CREATE INDEX IF NOT EXISTS idx_simulation_runs_city
    ON simulation_runs (city_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_simulation_runs_status
    ON simulation_runs (status, started_at DESC);
