"""Central configuration for CityPulse, loaded from environment variables.

Secrets (database password, API keys) live only in .env on the backend and are
never sent to the browser or committed to Git (.env is git-ignored).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a hard dependency in practice
    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False

_ENV_LOADED = False


def load_env() -> None:
    """Load the project-root .env file once (idempotent).

    override=True makes .env authoritative over ambient environment variables
    (some dev machines export a global PORT, which would otherwise win).
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(os.path.join(base_dir, ".env"), override=True)
    _ENV_LOADED = True


def _get_bool(name: str, default: bool = False) -> bool:
    """Boolean env parsing; the default applies when the variable is UNSET."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    """Typed snapshot of environment configuration."""

    debug: bool
    port: int
    cors_origins: list[str] = field(default_factory=list)

    # --- database (backend only) ---
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    database_url: str = ""

    # --- Phase 2: data providers ---
    openaq_api_key: str = ""                 # https://explore.openaq.org (free)
    transit_gtfs_rt_url: str = ""            # agency GTFS-RT VehiclePositions URL
    incidents_socrata_url: str = ""          # Socrata-style resource URL (.json)
    incidents_field_map_json: str = ""       # JSON mapping our fields -> dataset columns
    weather_enabled: bool = True             # Open-Meteo is keyless; disable to force demo
    ingest_cooldown_seconds: int = 120       # min seconds between /api/refresh runs
    refresh_token: str = ""                  # optional X-Refresh-Token for POST /api/refresh

    # --- Phase 3: AI provider (optional; fallback summary used when absent) ---
    ai_provider: str = ""                    # "" | "openai-compatible"
    ai_api_key: str = ""
    ai_base_url: str = ""                    # e.g. https://api.groq.com/openai/v1
    ai_model: str = ""                       # e.g. llama-3.1-8b-instant (verify availability)

    # --- Phase 3: anomaly detection thresholds (explainable, configurable) ---
    anomaly_z_threshold: float = 3.5         # robust z needed to flag an anomaly
    anomaly_severe_z_threshold: float = 6.0  # robust z for medium confidence

    # --- Phase 3: event lifecycle, real-time transport, simulation ---
    realtime_enabled: bool = True            # SSE stream at /api/events/stream
    sse_heartbeat_seconds: int = 20          # keep-alive comment interval
    sse_max_stream_seconds: int = 1800       # reconnect window (EventSource retries)
    simulation_enabled: bool = True          # scenario drills (clearly labelled)
    event_stale_hours: int = 4               # "needs attention" threshold in the UI

    @property
    def incidents_field_map(self) -> dict[str, str] | None:
        raw = (self.incidents_field_map_json or "").strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def get_settings() -> Settings:
    load_env()
    return Settings(
        debug=_get_bool("FLASK_DEBUG"),
        port=int(os.getenv("PORT", "5000") or "5000"),
        cors_origins=[
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "").split(",")
            if origin.strip()
        ],
        supabase_url=os.getenv("SUPABASE_URL", "").strip(),
        supabase_publishable_key=os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip(),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        openaq_api_key=os.getenv("OPENAQ_API_KEY", "").strip(),
        transit_gtfs_rt_url=os.getenv("TRANSIT_GTFS_RT_URL", "").strip(),
        incidents_socrata_url=os.getenv("INCIDENTS_SOCRATA_URL", "").strip(),
        incidents_field_map_json=os.getenv("INCIDENTS_FIELD_MAP", "").strip(),
        weather_enabled=_get_bool("WEATHER_ENABLED", default=True),
        ingest_cooldown_seconds=int(os.getenv("INGEST_COOLDOWN_SECONDS", "120") or "120"),
        refresh_token=os.getenv("REFRESH_TOKEN", "").strip(),
        ai_provider=os.getenv("AI_PROVIDER", "").strip(),
        ai_api_key=os.getenv("AI_API_KEY", "").strip(),
        ai_base_url=os.getenv("AI_BASE_URL", "").strip(),
        ai_model=os.getenv("AI_MODEL", "").strip(),
        anomaly_z_threshold=float(os.getenv("ANOMALY_Z_THRESHOLD", "3.5") or "3.5"),
        anomaly_severe_z_threshold=float(os.getenv("ANOMALY_SEVERE_Z_THRESHOLD", "6.0") or "6.0"),
        realtime_enabled=_get_bool("REALTIME_ENABLED", default=True),
        sse_heartbeat_seconds=int(os.getenv("SSE_HEARTBEAT_SECONDS", "20") or "20"),
        sse_max_stream_seconds=int(os.getenv("SSE_MAX_STREAM_SECONDS", "1800") or "1800"),
        simulation_enabled=_get_bool("SIMULATION_ENABLED", default=True),
        event_stale_hours=int(os.getenv("EVENT_STALE_HOURS", "4") or "4"),
    )
