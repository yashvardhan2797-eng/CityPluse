"""CityPulse Urban Digital Twin (Phase 9).

A lightweight, software-only twin: zones are the real observed locations in
civic_data (grouped by location_name with mean coordinates). For each zone the
twin assembles:

- current state: recent-window metric averages with observation counts;
- historical change: delta vs the previous, equally-sized window (computed
  from stored rows only — no interpolation);
- anomalies: stored anomaly flags whose observed footprints fall nearest the
  zone (distance-bounded);
- incidents: active civic events within a radius of the zone;
- advisories: applicable advisory interventions from the impact engine.

Trust rules: zones exist only where data exists; gaps are disclosed, never
filled. Nothing simulated appears without a SIMULATED label. The twin is a
monitoring/exploration surface — it executes nothing.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from backend.database import fetch_normalized_data, fetch_recent_anomalies

ZONE_RADIUS_KM = 1.2          # anomaly/event attach radius around a zone
MAX_ZONES = 24                # keep responses bounded
DELTA_EPSILON = 1e-9

ADVISORY = "Advisory exploration only — the twin does not execute interventions."


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def build_twin(city: str, hours: int = 24) -> dict:
    """Assemble zone-level twin state for one city from stored data only."""
    now = datetime.now(timezone.utc)
    ok, rows = fetch_normalized_data(city=city, since_hours=hours * 2, limit=1200)
    if not ok:
        return {
            "city": city, "status": "unavailable", "zones": [],
            "error": str(rows), "advisory": ADVISORY,
            "note": "Twin state requires stored observations; nothing is fabricated in demo mode.",
        }
    rows = rows or []
    cutoff = now.timestamp() - hours * 3600

    zones: dict[str, dict] = {}
    for r in rows:
        lat, lon = r.get("latitude"), r.get("longitude")
        if lat is None or lon is None:
            continue
        rec_ts = (_parse(r.get("recorded_at")) or now).timestamp()
        metric = r.get("metric") or "unspecified"
        z = zones.setdefault(str(r.get("location_name") or "unspecified location"), {
            "location": str(r.get("location_name") or "unspecified location"),
            "lat_sum": 0.0, "lon_sum": 0.0, "coords_n": 0,
            "recent": {}, "previous": {},
        })
        z["lat_sum"] += float(lat)
        z["lon_sum"] += float(lon)
        z["coords_n"] += 1
        bucket = z["recent"] if rec_ts >= cutoff else z["previous"]
        agg = bucket.setdefault(metric, {"sum": 0.0, "n": 0, "last_recorded_at": None})
        if r.get("value") is not None:
            agg["sum"] += float(r["value"])
            agg["n"] += 1
        stamp = r.get("recorded_at")
        if stamp and (agg["last_recorded_at"] is None or str(stamp) > str(agg["last_recorded_at"])):
            agg["last_recorded_at"] = stamp

    zone_list: list[dict] = []
    for z in zones.values():
        metrics: dict[str, dict] = {}
        for metric, agg in {**z["previous"], **z["recent"]}.items():
            cur = z["recent"].get(metric)
            prev = z["previous"].get(metric)
            recent_avg = round(cur["sum"] / cur["n"], 2) if cur and cur["n"] else None
            prev_avg = round(prev["sum"] / prev["n"], 2) if prev and prev["n"] else None
            delta_pct = None
            if recent_avg is not None and prev_avg is not None and abs(prev_avg) > DELTA_EPSILON:
                delta_pct = round((recent_avg - prev_avg) / abs(prev_avg) * 100.0, 1)
            metrics[metric] = {
                "recent_avg": recent_avg,
                "previous_avg": prev_avg,
                "delta_pct": delta_pct,
                "recent_observations": cur["n"] if cur else 0,
                "previous_observations": prev["n"] if prev else 0,
                "last_recorded_at": (cur or prev or {}).get("last_recorded_at"),
                "note": None if prev_avg is not None else "no previous-window observations — delta undisclosed",
            }
        zone_list.append({
            "id": z["location"].lower().replace(" ", "-"),
            "location": z["location"],
            "latitude": round(z["lat_sum"] / z["coords_n"], 6),
            "longitude": round(z["lon_sum"] / z["coords_n"], 6),
            "metrics": dict(sorted(metrics.items())),
            "coverage": {
                "recent_window_hours": hours,
                "recent_metric_points": sum(m["recent_observations"] for m in metrics.values()),
            },
        })

    zone_list.sort(key=lambda zz: -zz["coverage"]["recent_metric_points"])
    zone_list = zone_list[:MAX_ZONES]

    # Anomaly footprints: real recorded rows near each zone (from same rows).
    ok_an, anomalies = fetch_recent_anomalies(city, limit=50)
    anomaly_flags = anomalies if ok_an else []
    event_layers = _active_events(city)
    _attach_proximity(zone_list, rows, anomaly_flags, event_layers, hours)

    return {
        "city": city,
        "status": "ok",
        "window_hours": hours,
        "zone_count": len(zone_list),
        "zones": zone_list,
        "layers": {
            "anomalies": [
                {
                    "metric": a.get("metric"),
                    "observed_bucket": a.get("observed_bucket"),
                    "observed_value": a.get("observed_value"),
                    "deviation_score": a.get("deviation_score"),
                    "confidence": a.get("confidence"),
                }
                for a in anomaly_flags[:20]
            ],
            "events": event_layers,
            "note": "Anomaly layer lists stored flags; zone proximity is computed from geolocated observations.",
        },
        "advisory": ADVISORY,
        "data_policy": (
            "Zones appear only where observations exist; missing windows are "
            "disclosed, never zero-filled. All values come from stored records."
        ),
        "generated_at": now.isoformat(),
    }


def _active_events(city: str) -> list[dict]:
    from backend.events import list_events
    try:
        listing = list_events(
            city=city,
            statuses=("open", "acknowledged", "in_progress"),
            include_simulated=True,
            limit=50,
        )
        events = listing.get("events", []) if isinstance(listing, dict) else []
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            "event_ref": ev.get("event_ref"),
            "title": ev.get("title"),
            "severity": ev.get("severity"),
            "status": ev.get("status"),
            "category": ev.get("category"),
            "latitude": ev.get("latitude"),
            "longitude": ev.get("longitude"),
            "location_name": ev.get("location_name"),
            "is_simulated": bool(ev.get("is_simulated")),
            "reported_at": ev.get("reported_at"),
        }
        for ev in events
        if ev.get("latitude") is not None and ev.get("longitude") is not None
    ]


def _attach_proximity(zone_list: list[dict], rows: list[dict],
                      anomaly_flags: list[dict], events: list[dict],
                      hours: int) -> None:
    """Attach nearest-zone attribution to rows/anomalies and events to zones."""
    if not zone_list:
        return
    # Mean coordinate per (metric, hour) footprint for anomaly pinning.
    footprints: dict[tuple[str, str], dict] = {}
    cutoff_ts = datetime.now(timezone.utc).timestamp() - hours * 3600 * 2
    for r in rows:
        if r.get("latitude") is None or r.get("metric") is None:
            continue
        ts = (_parse(r.get("recorded_at")) or datetime.now(timezone.utc)).timestamp()
        if ts < cutoff_ts:
            continue
        key = (r["metric"], str(r.get("recorded_at"))[:13])
        fp = footprints.setdefault(key, {"lat": 0.0, "lon": 0.0, "n": 0})
        fp["lat"] += float(r["latitude"])
        fp["lon"] += float(r["longitude"])
        fp["n"] += 1

    for zone in zone_list:
        anomaly_hits: list[dict] = []
        event_hits: list[dict] = []
        for a in anomaly_flags:
            fp = footprints.get((a.get("metric"), str(a.get("observed_bucket"))[:13]))
            if not fp:
                continue
            d = _haversine_km(zone["latitude"], zone["longitude"], fp["lat"] / fp["n"], fp["lon"] / fp["n"])
            if d <= ZONE_RADIUS_KM:
                anomaly_hits.append({**{k: a.get(k) for k in
                                        ("metric", "observed_bucket", "observed_value", "deviation_score")},
                                     "distance_km": round(d, 2)})
        for ev in events:
            d = _haversine_km(zone["latitude"], zone["longitude"],
                              float(ev["latitude"]), float(ev["longitude"]))
            if d <= ZONE_RADIUS_KM * 2:
                event_hits.append({**{k: ev.get(k) for k in
                                      ("event_ref", "title", "severity", "status", "is_simulated")},
                                   "distance_km": round(d, 2)})
        zone["anomalies_nearby"] = sorted(anomaly_hits, key=lambda x: x["distance_km"])[:5]
        zone["events_nearby"] = sorted(event_hits, key=lambda x: x["distance_km"])[:5]
        zone["advisories"] = _zone_advisories(zone)

    # Zone attribution for the anomaly layer (reverse mapping).
    for a in anomaly_flags:
        fp = footprints.get((a.get("metric"), str(a.get("observed_bucket"))[:13]))
        if not fp:
            continue
        best = min(
            zone_list,
            key=lambda zz: _haversine_km(zz["latitude"], zz["longitude"], fp["lat"] / fp["n"], fp["lon"] / fp["n"]),
            default=None,
        )
        if best is not None:
            d = _haversine_km(best["latitude"], best["longitude"], fp["lat"] / fp["n"], fp["lon"] / fp["n"])
            a["nearest_zone"] = best["location"]
            a["zone_distance_km"] = round(d, 2)


def _zone_advisories(zone: dict) -> list[dict]:
    """Advisory interventions applicable to this zone's flagged anomalies."""
    from backend.impact import IMPACT_PATHS, INTERVENTION_CATALOG
    out: list[dict] = []
    seen: set[str] = set()
    for hit in zone.get("anomalies_nearby", []):
        path = IMPACT_PATHS.get(hit.get("metric") or "")
        for iv in INTERVENTION_CATALOG.get(path or "", []):
            if iv["id"] in seen:
                continue
            seen.add(iv["id"])
            out.append({**iv, "triggered_by_metric": hit.get("metric"), "advisory": True})
    return out[:4]
