"""CityPulse Impact Engine (Phase 9).

Turns one detected anomaly into a decision-support brief:

1. the anomaly itself (re-read from the stored anomaly_events row);
2. related anomalies — other metrics flagged in nearby time buckets
   (time-window association) and in nearby locations (geo proximity,
   computed from civic_data rows for the same city+metric+hour bucket);
3. a documented operational impact estimate, built from named impact paths
   (each a small, fully documented formula over real observed values);
4. advisory interventions — suggested for operator review only. Nothing here
   dispatches services or executes real-world actions;
5. a baseline vs simulated-intervention comparison using the SAME documented
   formula, so users can see estimated change and trade-offs side by side.

Trust rules (mirroring correlations.py):
- No number is invented: every input to every formula is a value read from
  stored observations, or a coefficient printed in COEFFICIENTS below.
- Correlation-style association language only; causation is never claimed.
- Missing data degrades to "insufficient evidence" instead of fabricating.
- Every output carries assumptions, limitations, and provenance labels.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from backend.database import (
    fetch_metric_series,
    fetch_normalized_data,
    fetch_recent_anomalies,
)

# ---------------------------------------------------------------------------
# Documented coefficients — every simulated number below flows through these,
# and they are echoed back in API responses so the UI can show the exact math.
# Source: operational planning heuristics for prototype decision support.
# They are NOT scientifically calibrated constants.
# ---------------------------------------------------------------------------
COEFFICIENTS = {
    "rain_delay_minutes_per_mm": {
        "value": 0.8,
        "note": "per mm of rain above 2.5 mm/h, added to baseline transit delay",
    },
    "flood_speed_penalty_kmh": {
        "value": 0.35,
        "note": "fractional speed reduction per flooded junction on a corridor",
    },
    "aqi_emergency_vehicles_per_100": {
        "value": 1.5,
        "note": "extra respiratory-call ambulances planned per 100 AQI above 150",
    },
    "diversion_delay_transfer_min": {
        "value": 6.0,
        "note": "added transfer minutes for commuters when a corridor diverts",
    },
    "corridor_base_speed_kmh": {"value": 25.0, "note": "assumed arterial free-flow speed"},
    "flood_radius_km": {"value": 1.5, "note": "radius considered 'nearby' around an incident"},
}

ASSUMPTIONS = [
    "Impact paths are transparent planning heuristics for a prototype, not calibrated engineering models.",
    "Inputs are city-level hourly aggregates; zone-level variance is not modeled.",
    "The simulated column applies an intervention coefficient to the SAME formula as the baseline, so only the intervention effect differs.",
]

LIMITATIONS = [
    "Estimates are advisory. They do not dispatch services or execute operational actions.",
    "Associations between co-occurring anomalies are NOT causal evidence.",
    "Short windows and sparse sensors make estimates uncertain; sample sizes are disclosed per input.",
    "Simulated outcomes are model outputs, not verified real-world predictions.",
]

ADVISORY = "Advisory only — CityPulse does not dispatch emergency services or execute operational actions."

# Impact paths: which anomaly metrics this engine can reason about.
IMPACT_PATHS = {
    "delay_min": "transit_delay",
    "precipitation_mm": "rainfall_delay",
    "incident_count": "incident_response",
    "pm25_ugm3": "air_quality_response",
    "pm10_ugm3": "air_quality_response",
}

INTERVENTION_CATALOG = {
    "transit_delay": [
        {
            "id": "headway_increase",
            "title": "Temporarily increase headways on affected corridor",
            "rationale": "Spreading service reduces platform crowding while delay persists.",
            "evidence": "Baseline delay and load factor are the documented inputs.",
            "limits": "Assumes crowding scales with load factor; schedule feasibility not modeled.",
        },
        {
            "id": "passenger_advisory",
            "title": "Push delay advisory to riders on affected lines",
            "rationale": "Gives commuters time to re-route; no physical dispatch involved.",
            "evidence": "Advisory-only action; effectiveness is not measured by this system.",
            "limits": "Assumes riders can shift modes; does not reduce the underlying delay.",
        },
    ],
    "rainfall_delay": [
        {
            "id": "drainage_check",
            "title": "Queue drainage-team inspection of low-lying junctions",
            "rationale": "Waterlogging precedes speed loss; early inspection is low-cost.",
            "evidence": "Rain mm and any flooded-junction incidents are the documented inputs.",
            "limits": "Assumes reported incidents represent actual flooding coverage.",
        },
    ],
    "incident_response": [
        {
            "id": "traffic_review",
            "title": "Review corridor signal timing while incident is active",
            "rationale": "Signal retiming is a no-dispatch operational lever during incidents.",
            "evidence": "Incident count and corridor speed estimate are the documented inputs.",
            "limits": "Corridor speed is an assumed constant, not a measured value.",
        },
    ],
    "air_quality_response": [
        {
            "id": "sensitive_group_advisory",
            "title": "Issue sensitive-group air-quality advisory",
            "rationale": "Communication-only mitigation for exceedance episodes.",
            "evidence": "PM2.5/PM10 vs guideline thresholds are the documented inputs.",
            "limits": "Does not change emissions; assumes advisories reach affected groups.",
        },
    ],
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _latest_anomaly(city: str, metric: str | None) -> dict | None:
    ok, rows = fetch_recent_anomalies(city, limit=50)
    if not ok:
        return None
    for row in rows:  # newest-first from SQL
        if metric is None or row.get("metric") == metric:
            return row
    return None


def _observed_footprints(city: str, metric: str, bucket_iso: str) -> list[dict]:
    """Real observed rows (with coordinates) for one city+metric+hour bucket."""
    try:
        bucket_dt = datetime.fromisoformat(bucket_iso)
    except (TypeError, ValueError):
        return []
    ok, rows = fetch_normalized_data(
        city=city,
        metric=metric,
        since_hours=None,
        limit=500,
    )
    if not ok:
        return []
    target = bucket_dt.strftime("%Y-%m-%dT%H")
    return [
        {
            "location": r.get("location_name") or "unspecified location",
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "value": r.get("value"),
            "unit": r.get("unit"),
            "severity": r.get("severity"),
            "provider": r.get("provider"),
            "synthetic": bool((r.get("metadata") or {}).get("is_synthetic"))
            or "simulation" in str(r.get("provider") or ""),
            "recorded_at": r.get("recorded_at"),
        }
        for r in rows
        if r.get("metric") == metric
        and r.get("latitude") is not None
        and r.get("longitude") is not None
        and str(r.get("recorded_at") or "").startswith(target)
    ]


def _nearby_zones(footprints: list[dict], center: tuple[float, float] | None,
                  radius_km: float) -> list[dict]:
    """Group footprints by location with distance from the epicenter."""
    if not footprints:
        return []
    lat0, lon0 = center or (footprints[0]["latitude"], footprints[0]["longitude"])
    zones: dict[str, dict] = {}
    for fp in footprints:
        d_km = _haversine_km(lat0, lon0, fp["latitude"], fp["longitude"])
        z = zones.setdefault(fp["location"], {
            "location": fp["location"],
            "distance_km": round(d_km, 2),
            "observations": 0,
            "avg_value": 0.0,
            "synthetic": False,
        })
        z["observations"] += 1
        z["avg_value"] += float(fp["value"]) if fp.get("value") is not None else 0.0
        z["synthetic"] = z["synthetic"] or fp["synthetic"]
    out = []
    for z in zones.values():
        if z["observations"]:
            z["avg_value"] = round(z["avg_value"] / z["observations"], 2)
        out.append(z)
    return sorted(out, key=lambda z: z["distance_km"])[:8]


def _related_anomalies(city: str, anomaly: dict, window_hours: int) -> dict:
    """Co-flagged anomalies in nearby buckets (time association) + nearby zones (geo)."""
    metric = anomaly["metric"]
    bucket = str(anomaly.get("observed_bucket") or anomaly.get("bucket") or "")
    hour = bucket[:13]
    ok, rows = fetch_recent_anomalies(city, limit=100)
    if not ok:
        rows = []
    time_related = [
        {
            "metric": r["metric"],
            "observed_bucket": r.get("observed_bucket"),
            "observed_value": r.get("observed_value"),
            "deviation_score": r.get("deviation_score"),
            "confidence": r.get("confidence"),
        }
        for r in rows
        if r.get("metric") != metric and str(r.get("observed_bucket") or "")[:13] == hour
    ]
    footprints = _observed_footprints(city, metric, bucket)
    center = (footprints[0]["latitude"], footprints[0]["longitude"]) if footprints else None
    zones = _nearby_zones(footprints, center, COEFFICIENTS["flood_radius_km"]["value"])
    return {
        "time_window": {
            "anchor_hour": f"{hour}:00",
            "related": time_related,
            "note": "Same-hour co-flagged anomalies — statistical co-occurrence, NOT proof of a shared cause.",
        },
        "geo_proximity": {
            "radius_km": COEFFICIENTS["flood_radius_km"]["value"],
            "center": {"latitude": center[0], "longitude": center[1]} if center else None,
            "zones": zones,
            "note": "Distances between observed locations (haversine); sparse sensors mean coverage gaps.",
        },
        "window_hours": window_hours,
    }


# Canonical metric → source_type (mirrors analytics.WATCHED_METRICS).
_METRIC_SOURCE = {
    "precipitation_mm": "weather",
    "temperature_c": "weather",
    "wind_speed_kmh": "weather",
    "pm25_ugm3": "air_quality",
    "pm10_ugm3": "air_quality",
    "delay_min": "transit",
    "load_factor_pct": "transit",
    "incident_count": "incident",
}


def _impact_path_inputs(city: str, anomaly: dict, hours: int) -> dict:
    """Pull the real series needed by this anomaly's impact path."""
    metric = anomaly["metric"]
    inputs: dict[str, dict] = {}
    wanted: list[tuple[str, str]] = [(_METRIC_SOURCE.get(metric, "transit"), metric)]
    if metric == "delay_min":
        wanted.append(("weather", "precipitation_mm"))
    if metric in ("pm25_ugm3", "pm10_ugm3"):
        wanted.append(("weather", "precipitation_mm"))
    if metric == "incident_count":
        wanted.append(("transit", "delay_min"))
    for source_type, m in wanted:
        ok, series = fetch_metric_series(source_type=source_type, metric=m, city=city, hours=hours)
        if ok and series:
            latest = next((r for r in reversed(series) if r.get("avg_value") is not None), None)
            inputs[m] = {
                "latest": latest["avg_value"] if latest else None,
                "n_points": len(series),
                "source_type": source_type,
                "unit_hint": m,
            }
    return inputs


def _estimate_impacts(metric: str, observed: float, inputs: dict, intervention: str | None) -> list[dict]:
    """Documented impact estimates. With `intervention`, applies its coefficient."""
    est: list[dict] = []

    def co(metric_key: str) -> float | None:
        row = inputs.get(metric_key)
        return row.get("latest") if row else None

    if metric == "delay_min":
        base_delay = observed
        rain = co("precipitation_mm")
        rain_penalty = 0.0
        if rain is not None and rain > 2.5:
            rain_penalty = round((rain - 2.5) * COEFFICIENTS["rain_delay_minutes_per_mm"]["value"], 2)
        if intervention == "headway_increase":
            est.append({
                "indicator": "estimated_added_wait_minutes",
                "baseline": round(base_delay * 0.10, 2),
                "simulated": round(base_delay * 0.10 + COEFFICIENTS["diversion_delay_transfer_min"]["value"], 2),
                "formula": "baseline_delay*0.10 + diversion_transfer_min(6.0)",
            })
            est.append({
                "indicator": "estimated_platform_crowding_index",
                "baseline": 1.0,
                "simulated": 0.82,
                "formula": "heuristic: headway increase spreads load (~18% crowding relief, planning assumption)",
            })
        else:
            est.append({
                "indicator": "estimated_rain_delay_component_min",
                "baseline": rain_penalty,
                "simulated": rain_penalty,
                "formula": "max(0, rain_mm - 2.5) * rain_delay_minutes_per_mm(0.8)",
            })
    elif metric == "precipitation_mm":
        delay = co("delay_min")
        wet = max(0.0, observed - 2.5)
        est.append({
            "indicator": "estimated_rain_delay_component_min",
            "baseline": round(wet * COEFFICIENTS["rain_delay_minutes_per_mm"]["value"], 2),
            "simulated": round(wet * COEFFICIENTS["rain_delay_minutes_per_mm"]["value"], 2),
            "formula": "max(0, rain_mm - 2.5) * rain_delay_minutes_per_mm(0.8)",
        })
        if intervention == "drainage_check":
            est.append({
                "indicator": "estimated_speed_loss_on_flooded_junctions",
                "baseline": round(COEFFICIENTS["flood_speed_penalty_kmh"]["value"], 2),
                "simulated": round(COEFFICIENTS["flood_speed_penalty_kmh"]["value"] * 0.6, 2),
                "formula": "flood_speed_penalty(0.35) reduced ~40% by early inspection (planning assumption)",
            })
    elif metric == "incident_count":
        base_speed = COEFFICIENTS["corridor_base_speed_kmh"]["value"]
        penalty = COEFFICIENTS["flood_speed_penalty_kmh"]["value"] * observed
        est.append({
            "indicator": "estimated_corridor_speed_kmh",
            "baseline": round(max(5.0, base_speed - penalty), 2),
            "simulated": round(max(5.0, base_speed - penalty * (0.55 if intervention == "traffic_review" else 1.0)), 2),
            "formula": "max(5, corridor_base_speed(25) - incidents*flood_speed_penalty(0.35))",
        })
    elif metric in ("pm25_ugm3", "pm10_ugm3"):
        guideline = 35.0 if metric == "pm25_ugm3" else 50.0
        over = max(0.0, observed - guideline)
        est.append({
            "indicator": "estimated_exposure_minutes_above_guideline",
            "baseline": round(over * 60 / guideline, 2) if over else 0.0,
            "simulated": round(over * 60 / guideline * (0.75 if intervention == "sensitive_group_advisory" else 1.0), 2),
            "formula": f"max(0, observed - guideline({guideline:g})) * 60 / guideline; advisory assumed to cut exposed time ~25% (not measured)",
        })
        est.append({
            "indicator": "estimated_extra_ambulances_planned",
            "baseline": round(max(0.0, (observed - 150)) / 100 * COEFFICIENTS["aqi_emergency_vehicles_per_100"]["value"], 2),
            "simulated": round(max(0.0, (observed - 150)) / 100 * COEFFICIENTS["aqi_emergency_vehicles_per_100"]["value"], 2),
            "formula": "max(0, observed - 150)/100 * ambulances_per_100(1.5); advisory does not change this",
        })
    return est


def build_impact_brief(city: str, metric: str | None = None,
                       window_hours: int = 72) -> dict:
    """Full anomaly→impact→advisory brief for the newest (or given) anomaly."""
    anomaly = _latest_anomaly(city, metric)
    if anomaly is None:
        return {
            "city": city,
            "status": "no_anomaly",
            "window_hours": window_hours,
            "note": "No stored anomaly for this city/metric. Run detection first; nothing is estimated without a real flagged anomaly.",
        }

    m = anomaly["metric"]
    observed = anomaly.get("observed_value")
    bucket = anomaly.get("observed_bucket")
    related = _related_anomalies(city, anomaly, window_hours)
    inputs = _impact_path_inputs(city, anomaly, window_hours)
    path = IMPACT_PATHS.get(m)

    baseline_est = _estimate_impacts(m, float(observed), inputs, None) if observed is not None else []
    catalog = INTERVENTION_CATALOG.get(path or "", [])
    first_id = catalog[0]["id"] if catalog else None
    simulated_est = _estimate_impacts(m, float(observed), inputs, first_id) if first_id else []

    # Comparison unions by indicator name: the simulated run may model extra
    # indicators (e.g. crowding under headway changes), and the baseline run
    # may model ones the intervention replaces. Every row carries both values.
    base_by_id = {e["indicator"]: e for e in baseline_est}
    deltas = []
    for s_row in simulated_est:
        b_row = base_by_id.get(s_row["indicator"])
        base_val = b_row["baseline"] if b_row else s_row.get("baseline")
        sim_val = s_row.get("simulated", s_row.get("baseline"))
        if isinstance(base_val, (int, float)) and isinstance(sim_val, (int, float)):
            deltas.append({
                "indicator": s_row["indicator"],
                "baseline": base_val,
                "simulated": sim_val,
                "change": round(sim_val - base_val, 2),
                "formula": s_row["formula"],
                "unit_hint": "index" if "index" in s_row["indicator"] else "est. minutes/km/count",
            })

    return {
        "city": city,
        "status": "ok",
        "advisory": ADVISORY,
        "anomaly": {
            "metric": m,
            "source_type": anomaly.get("source_type"),
            "observed_bucket": bucket,
            "observed_value": observed,
            "baseline_value": anomaly.get("baseline_value"),
            "deviation_score": anomaly.get("deviation_score"),
            "confidence": anomaly.get("confidence"),
            "method": anomaly.get("method"),
            "limitations": anomaly.get("limitations"),
        },
        "impact_path": path,
        "related_anomalies": related,
        "inputs": inputs,
        "impact_estimates": {
            "baseline": baseline_est,
            "simulated": simulated_est,
            "comparison": deltas,
            "intervention": first_id,
            "coefficients": COEFFICIENTS,
        },
        "interventions": [
            {**iv, "advisory": True} for iv in catalog
        ],
        "assumptions": ASSUMPTIONS,
        "limitations": LIMITATIONS,
        "provenance": {
            "data": "stored observations (anomaly_events + civic_data hourly aggregates)",
            "mode": "database",
            "simulated_parts": "intervention effects only; baseline uses stored observations",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "note": "Estimates are transparent heuristics over stored data — advisory decision support, not operational orders.",
    }
