"""Demo mode: synthetic, clearly-labeled civic data.

Used when Supabase is not configured (DATABASE_URL empty) or unreachable.
Every record produced here is synthetic and must always be presented in the
UI as "DEMO DATA" — never as live civic information.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Cities available in the Phase 1 selector. Extend freely — coordinates are
# approximate city-centre points used to center the map and cluster markers.
DEMO_CITIES: list[dict[str, Any]] = [
    {"id": "bengaluru",   "name": "Bengaluru",  "country": "India",        "lat": 12.9716, "lon": 77.5946, "timezone": "Asia/Kolkata"},
    {"id": "mumbai",      "name": "Mumbai",     "country": "India",        "lat": 19.0760, "lon": 72.8777, "timezone": "Asia/Kolkata"},
    {"id": "delhi",       "name": "Delhi",      "country": "India",        "lat": 28.6139, "lon": 77.2090, "timezone": "Asia/Kolkata"},
    {"id": "london",      "name": "London",     "country": "UK",           "lat": 51.5074, "lon": -0.1278, "timezone": "Europe/London"},
    {"id": "new-york",    "name": "New York",   "country": "USA",          "lat": 40.7128, "lon": -74.0060, "timezone": "America/New_York"},
    {"id": "singapore",   "name": "Singapore",  "country": "Singapore",    "lat": 1.3521,  "lon": 103.8198, "timezone": "Asia/Singapore"},
]

# Station-style sample records per city (source_type keyed). All synthetic.
_SAMPLE_POINTS: dict[str, list[dict[str, Any]]] = {
    "bengaluru": [
        {"source_type": "air_quality", "source_id": "demo-aqi-blr-1", "location_name": "City Railway Station", "lat": 12.9774, "lon": 77.5726, "value": 156, "unit": "AQI", "severity": "high",      "description": "Demo: PM2.5-dominant haze near transit hub"},
        {"source_type": "air_quality", "source_id": "demo-aqi-blr-2", "location_name": "Silk Board Junction",   "lat": 12.9166, "lon": 77.6229, "value": 189, "unit": "AQI", "severity": "high",      "description": "Demo: traffic corridor hotspot"},
        {"source_type": "air_quality", "source_id": "demo-aqi-blr-3", "location_name": "Cubbon Park",           "lat": 12.9763, "lon": 77.5929, "value": 64,  "unit": "AQI", "severity": "moderate",  "description": "Demo: greener zone baseline"},
        {"source_type": "transit",     "source_id": "demo-trn-blr-1", "location_name": "Majestic Interchange",  "lat": 12.9767, "lon": 77.5713, "value": 82,  "unit": "% capacity", "severity": "moderate", "description": "Demo: evening peak crowding"},
        {"source_type": "transit",     "source_id": "demo-trn-blr-2", "location_name": "Indiranagar Metro",     "lat": 12.9784, "lon": 77.6408, "value": 45,  "unit": "% capacity", "severity": "low",      "description": "Demo: normal service load"},
        {"source_type": "incident",    "source_id": "demo-inc-blr-1", "location_name": "Outer Ring Road",       "lat": 12.9352, "lon": 77.6875, "value": 1,   "unit": "count", "severity": "moderate", "description": "Demo: reported waterlogging"},
        {"source_type": "energy",      "source_id": "demo-eng-blr-1", "location_name": "Whitefield Grid",       "lat": 12.9698, "lon": 77.7500, "value": 71,  "unit": "% load", "severity": "moderate",  "description": "Demo: substation load factor"},
    ],
    "mumbai": [
        {"source_type": "air_quality", "source_id": "demo-aqi-bom-1", "location_name": "Bandra Kurla Complex", "lat": 19.0662, "lon": 72.8697, "value": 141, "unit": "AQI", "severity": "high",      "description": "Demo: business-district haze"},
        {"source_type": "air_quality", "source_id": "demo-aqi-bom-2", "location_name": "Marine Drive",          "lat": 18.9440, "lon": 72.8230, "value": 58,  "unit": "AQI", "severity": "moderate",  "description": "Demo: sea-breeze ventilation"},
        {"source_type": "transit",     "source_id": "demo-trn-bom-1", "location_name": "Churchgate Station",    "lat": 18.9343, "lon": 72.8267, "value": 91,  "unit": "% capacity", "severity": "high", "description": "Demo: peak-hour crush loading"},
        {"source_type": "transit",     "source_id": "demo-trn-bom-2", "location_name": "Andheri Metro",         "lat": 19.1364, "lon": 72.8296, "value": 67,  "unit": "% capacity", "severity": "moderate", "description": "Demo: busy corridor"},
        {"source_type": "incident",    "source_id": "demo-inc-bom-1", "location_name": "Hindmata Junction",     "lat": 19.0285, "lon": 72.8381, "value": 1,   "unit": "count", "severity": "critical", "description": "Demo: monsoon flooding report"},
        {"source_type": "energy",      "source_id": "demo-eng-bom-1", "location_name": "Colaba Feeder",         "lat": 18.9067, "lon": 72.8147, "value": 77,  "unit": "% load", "severity": "moderate",  "description": "Demo: feeder load factor"},
    ],
    "delhi": [
        {"source_type": "air_quality", "source_id": "demo-aqi-del-1", "location_name": "Anand Vihar",          "lat": 28.6486, "lon": 77.3155, "value": 264, "unit": "AQI", "severity": "critical", "description": "Demo: severe haze episode"},
        {"source_type": "air_quality", "source_id": "demo-aqi-del-2", "location_name": "Lodhi Garden",          "lat": 28.5935, "lon": 77.2197, "value": 132, "unit": "AQI", "severity": "high",      "description": "Demo: park-area reading"},
        {"source_type": "air_quality", "source_id": "demo-aqi-del-3", "location_name": "ITO Junction",          "lat": 28.6285, "lon": 77.2410, "value": 231, "unit": "AQI", "severity": "critical", "description": "Demo: traffic hotspot"},
        {"source_type": "transit",     "source_id": "demo-trn-del-1", "location_name": "Rajiv Chowk Metro",     "lat": 28.6328, "lon": 77.2197, "value": 88,  "unit": "% capacity", "severity": "high", "description": "Demo: interchange crowding"},
        {"source_type": "transit",     "source_id": "demo-trn-del-2", "location_name": "Botanical Garden Metro","lat": 28.5640, "lon": 77.3340, "value": 52,  "unit": "% capacity", "severity": "moderate", "description": "Demo: off-peak load"},
        {"source_type": "incident",    "source_id": "demo-inc-del-1", "location_name": "Ring Road",             "lat": 28.5680, "lon": 77.2400, "value": 1,   "unit": "count", "severity": "moderate", "description": "Demo: minor traffic incident"},
        {"source_type": "energy",      "source_id": "demo-eng-del-1", "location_name": "Connaught Place Grid",  "lat": 28.6315, "lon": 77.2167, "value": 69,  "unit": "% load", "severity": "moderate",  "description": "Demo: grid load factor"},
    ],
    "london": [
        {"source_type": "air_quality", "source_id": "demo-aqi-ldn-1", "location_name": "Marylebone Road",       "lat": 51.5226, "lon": -0.1585, "value": 88,  "unit": "AQI", "severity": "moderate",  "description": "Demo: roadside NO2 corridor"},
        {"source_type": "air_quality", "source_id": "demo-aqi-ldn-2", "location_name": "Hyde Park",             "lat": 51.5073, "lon": -0.1657, "value": 31,  "unit": "AQI", "severity": "low",       "description": "Demo: park background"},
        {"source_type": "transit",     "source_id": "demo-trn-ldn-1", "location_name": "King's Cross Station",  "lat": 51.5308, "lon": -0.1238, "value": 74,  "unit": "% capacity", "severity": "moderate", "description": "Demo: interchange load"},
        {"source_type": "transit",     "source_id": "demo-trn-ldn-2", "location_name": "Oxford Circus",         "lat": 51.5152, "lon": -0.1419, "value": 85,  "unit": "% capacity", "severity": "high",      "description": "Demo: busy tube interchange"},
        {"source_type": "incident",    "source_id": "demo-inc-ldn-1", "location_name": "Blackfriars Bridge",    "lat": 51.5098, "lon": -0.1043, "value": 1,   "unit": "count", "severity": "low",      "description": "Demo: lane closure reported"},
        {"source_type": "energy",      "source_id": "demo-eng-ldn-1", "location_name": "City Substation",       "lat": 51.5142, "lon": -0.0920, "value": 63,  "unit": "% load", "severity": "moderate",  "description": "Demo: demand snapshot"},
    ],
    "new-york": [
        {"source_type": "air_quality", "source_id": "demo-aqi-nyc-1", "location_name": "Midtown East",          "lat": 40.7549, "lon": -73.9840, "value": 72, "unit": "AQI", "severity": "moderate",  "description": "Demo: urban background"},
        {"source_type": "air_quality", "source_id": "demo-aqi-nyc-2", "location_name": "Central Park",          "lat": 40.7829, "lon": -73.9654, "value": 39, "unit": "AQI", "severity": "low",       "description": "Demo: park reference site"},
        {"source_type": "transit",     "source_id": "demo-trn-nyc-1", "location_name": "Times Sq–42 St",        "lat": 40.7554, "lon": -73.9876, "value": 79, "unit": "% capacity", "severity": "high",      "description": "Demo: platform crowding"},
        {"source_type": "transit",     "source_id": "demo-trn-nyc-2", "location_name": "Union Square",          "lat": 40.7359, "lon": -73.9911, "value": 61, "unit": "% capacity", "severity": "moderate",  "description": "Demo: transfer hub load"},
        {"source_type": "incident",    "source_id": "demo-inc-nyc-1", "location_name": "Brooklyn Bridge",       "lat": 40.7061, "lon": -73.9969, "value": 1,  "unit": "count", "severity": "moderate", "description": "Demo: delayed subway signal"},
        {"source_type": "energy",      "source_id": "demo-eng-nyc-1", "location_name": "Wall St Feeder",        "lat": 40.7078, "lon": -74.0116, "value": 68, "unit": "% load", "severity": "moderate",  "description": "Demo: feeder load factor"},
    ],
    "singapore": [
        {"source_type": "air_quality", "source_id": "demo-aqi-sin-1", "location_name": "Downtown Core",         "lat": 1.2830, "lon": 103.8510, "value": 54,  "unit": "AQI", "severity": "moderate",  "description": "Demo: PSI-style composite"},
        {"source_type": "air_quality", "source_id": "demo-aqi-sin-2", "location_name": "Bukit Timah",           "lat": 1.3292, "lon": 103.7780, "value": 36,  "unit": "AQI", "severity": "low",       "description": "Demo: reserve-edge site"},
        {"source_type": "transit",     "source_id": "demo-trn-sin-1", "location_name": "Raffles Place MRT",     "lat": 1.2847, "lon": 103.8510, "value": 66,  "unit": "% capacity", "severity": "moderate",  "description": "Demo: interchange load"},
        {"source_type": "transit",     "source_id": "demo-trn-sin-2", "location_name": "Jurong East MRT",       "lat": 1.3329, "lon": 103.7436, "value": 48,  "unit": "% capacity", "severity": "low",       "description": "Demo: normal load"},
        {"source_type": "incident",    "source_id": "demo-inc-sin-1", "location_name": "Central Expressway",    "lat": 1.3480, "lon": 103.8420, "value": 1,   "unit": "count", "severity": "low",      "description": "Demo: stall reported"},
        {"source_type": "energy",      "source_id": "demo-eng-sin-1", "location_name": "Marina Grid",           "lat": 1.2810, "lon": 103.8640, "value": 59,  "unit": "% load", "severity": "moderate",  "description": "Demo: district cooling load"},
    ],
}

# Per-city summary metrics for the KPI panel (all synthetic demo values).
DEMO_SUMMARY: dict[str, dict[str, Any]] = {
    "bengaluru": {"avg_aqi": 136, "transit_load": 64, "active_incidents": 1, "grid_load": 71},
    "mumbai":    {"avg_aqi": 100, "transit_load": 79, "active_incidents": 1, "grid_load": 77},
    "delhi":     {"avg_aqi": 209, "transit_load": 70, "active_incidents": 1, "grid_load": 69},
    "london":    {"avg_aqi": 60,  "transit_load": 80, "active_incidents": 1, "grid_load": 63},
    "new-york":  {"avg_aqi": 56,  "transit_load": 70, "active_incidents": 1, "grid_load": 68},
    "singapore": {"avg_aqi": 45,  "transit_load": 57, "active_incidents": 1, "grid_load": 59},
}

SEVERITY_ORDER = ["low", "moderate", "high", "critical"]


def resolve_city(city: str) -> str:
    """Canonical city-id -> display-name resolver (single source of truth).

    Case-insensitive match on the demo city ids; unknown ids pass through
    (DB queries simply find nothing). Empty input defaults to Bengaluru so a
    missing query param still yields a coherent, populated response.
    """
    needle = (city or "").strip().lower()
    if not needle:
        return DEMO_CITIES[0]["name"]
    for c in DEMO_CITIES:
        if str(c["id"]).lower() == needle:
            return c["name"]
    return (city or DEMO_CITIES[0]["name"]).strip()


def get_demo_cities() -> list[dict[str, Any]]:
    """Public list of demo cities (stable order)."""
    return [dict(c) for c in DEMO_CITIES]


_DEFAULT_CITY_POINTS = "bengaluru"  # fallback so unknown ids never yield empty data


def build_demo_record(city_id: str) -> list[dict[str, Any]]:
    """Return synthetic civic records for a city, shaped like civic_data rows.

    Unknown city ids fall back to the Bengaluru sample set so the demo UI is
    never empty. recorded_at is generated at request time so the demo panel
    always shows a fresh-looking (but clearly synthetic) timestamp.
    """
    now = datetime.now(timezone.utc)
    records: list[dict[str, Any]] = []
    points = _SAMPLE_POINTS.get(city_id) or _SAMPLE_POINTS[_DEFAULT_CITY_POINTS]
    for offset, point in enumerate(points):
        record = dict(point)
        record["recorded_at"] = (now - timedelta(minutes=6 * (offset + 1))).isoformat()
        record["created_at"] = record["recorded_at"]
        records.append(record)
    return records


def get_demo_summary(city_id: str) -> dict[str, Any]:
    """Synthetic KPI summary for a city (never live data)."""
    summary = dict(DEMO_SUMMARY.get(city_id, {}))
    summary["data_quality"] = "synthetic"
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    return summary
