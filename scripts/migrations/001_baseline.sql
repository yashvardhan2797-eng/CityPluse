-- CityPulse baseline schema (matches what scripts/setup_db.py created in Phase 1).
-- Idempotent; kept so a fresh database can reach the same state via migrations.
CREATE TABLE IF NOT EXISTS civic_data (
    id            BIGSERIAL PRIMARY KEY,
    source_type   TEXT             NOT NULL,
    source_id     TEXT             NOT NULL,
    city          TEXT,
    location_name TEXT             NOT NULL,
    latitude      DOUBLE PRECISION NOT NULL,
    longitude     DOUBLE PRECISION NOT NULL,
    value         DOUBLE PRECISION,
    unit          TEXT,
    description   TEXT,
    severity      TEXT CHECK (severity IN ('low', 'moderate', 'high', 'critical')),
    recorded_at   TIMESTAMPTZ      NOT NULL DEFAULT now(),
    created_at    TIMESTAMPTZ      NOT NULL DEFAULT now()
);

ALTER TABLE civic_data ADD COLUMN IF NOT EXISTS city TEXT;

CREATE INDEX IF NOT EXISTS idx_civic_data_source_type  ON civic_data (source_type);
CREATE INDEX IF NOT EXISTS idx_civic_data_recorded_at  ON civic_data (recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_civic_data_location     ON civic_data (latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_civic_data_severity     ON civic_data (source_type, severity);
CREATE INDEX IF NOT EXISTS idx_civic_data_source       ON civic_data (source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_civic_data_city         ON civic_data (city);
CREATE UNIQUE INDEX IF NOT EXISTS uq_civic_data_source ON civic_data (source_type, source_id);
