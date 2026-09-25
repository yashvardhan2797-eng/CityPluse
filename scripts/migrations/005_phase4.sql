-- CityPulse Phase 4 migration: alert center + supporting indexes.
-- Idempotent and purely additive: existing tables are untouched.
--
-- Design notes
-- * alert_instances rows are ALWAYS derived from verified evidence
--   (anomaly_events or an explicitly configured threshold rule evaluated
--   against stored observations). The API never invents alerts.
-- * dedup_key is unique, so re-running detection/sync can never produce
--   duplicate alerts for the same event (mirrors anomaly_events dedup).
-- * acknowledge/dismiss are user actions on top of evidence; the evidence
--   block is stored as supplied and never rewritten.
-- * alert_rules are configurable thresholds (per metric, optionally per
--   city). A rule alert is informational: "value crossed a configured
--   threshold", never an official emergency warning.

CREATE TABLE IF NOT EXISTS alert_instances (
    id              BIGSERIAL PRIMARY KEY,
    dedup_key       TEXT        NOT NULL UNIQUE,
    city            TEXT        NOT NULL,
    source_type     TEXT,
    metric          TEXT,
    severity        TEXT        NOT NULL
                    CHECK (severity IN ('low', 'moderate', 'high', 'critical')),
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    evidence        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    observed_value  DOUBLE PRECISION,
    baseline_value  DOUBLE PRECISION,
    location_name   TEXT,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by TEXT,
    dismissed_at    TIMESTAMPTZ,
    is_synthetic    BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alert_instances_city
    ON alert_instances (city, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_instances_open
    ON alert_instances (city, dismissed_at, acknowledged_at);

CREATE TABLE IF NOT EXISTS alert_rules (
    id              BIGSERIAL PRIMARY KEY,
    city            TEXT,                -- NULL = applies to all cities
    metric          TEXT        NOT NULL,
    operator        TEXT        NOT NULL DEFAULT '>'
                    CHECK (operator IN ('>', '<', '>=')),
    threshold_value DOUBLE PRECISION NOT NULL,
    window_hours    INTEGER     NOT NULL DEFAULT 24,
    enabled         BOOLEAN     NOT NULL DEFAULT TRUE,
    label           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (city, metric, operator, threshold_value)
);
