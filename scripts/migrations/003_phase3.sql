-- CityPulse Phase 3 migration: persisted anomaly events.
-- Anomalies are keyed by (city, metric, observed_bucket) so re-running
-- detection can never produce duplicate alerts for the same event.
CREATE TABLE IF NOT EXISTS anomaly_events (
    id               BIGSERIAL PRIMARY KEY,
    city             TEXT NOT NULL,
    source_type      TEXT NOT NULL,
    metric           TEXT NOT NULL,
    observed_bucket  TIMESTAMPTZ NOT NULL,
    observed_value   DOUBLE PRECISION,
    baseline_value   DOUBLE PRECISION,
    deviation_score  DOUBLE PRECISION,
    method           TEXT NOT NULL,
    window_hours     INTEGER,
    sample_size      INTEGER,
    confidence       TEXT,
    limitations      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (city, metric, observed_bucket)
);

CREATE INDEX IF NOT EXISTS idx_anomaly_events_city_time
    ON anomaly_events (city, observed_bucket DESC);
