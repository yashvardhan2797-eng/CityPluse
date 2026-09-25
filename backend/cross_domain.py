"""CityPulse cross-domain intelligence (Phase 9).

Connects environmental, traffic, weather, and incident signals into one
graph of *statistical associations*:

1. time-window association: anomalies of different metrics flagged in the
   same (or adjacent) hour buckets co-occur — statistical association only;
2. geographic proximity: observed locations of co-flagged anomalies are
   clustered and compared for spatial overlap (haversine distances between
   real recorded coordinates in civic_data);
3. cross-metric correlation: reuses correlations.analyze_pair verbatim
   (same outlier rules, same minimum overlap, same associational wording);
4. a graph of nodes (metrics) and typed edges
   ("co_occurrence" | "correlation" | "co_location") that the UI renders;
5. per-edge evidence blocks: the measurements, sample sizes, timestamps, and
   provenance that support each relationship.

Terminology contract enforced here: every edge carries an `evidence_class`
label — "statistical_association" or "hypothesis" — and the response states
plainly that no causal claim is made anywhere in this module.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from backend.analytics import WATCHED_METRICS
from backend.correlations import METRIC_UNITS, analyze_pair
from backend.database import fetch_normalized_data, fetch_recent_anomalies

# How many hours apart two anomalies may be and still count as co-occurring.
CO_OCCURRENCE_WINDOW_HOURS = 2
# Observations per metric needed before geo-proximity analysis is attempted.
MIN_FOOTPRINT_ROWS = 1
GEO_RADIUS_KM = 1.5

_NOTES = {
    "association": (
        "Edges describe statistical co-occurrence and correlation, not causation. "
        "Confounding (time of day, weather systems, shared events) is not controlled."
    ),
    "hypothesis": (
        "Hypothesis edges combine two weaker signals (co-occurrence + spatial overlap). "
        "They are candidate leads for human review, never established causes."
    ),
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _hour(stamp: str | None) -> str:
    return str(stamp or "")[:13]


def _metric_source(metric: str) -> str:
    for source_type, m in WATCHED_METRICS:
        if m == metric:
            return source_type
    return "unknown"


def _footprints(city: str, metric: str, hours: int) -> list[dict]:
    """Real observed rows (with coordinates) for one metric over the window."""
    ok, rows = fetch_normalized_data(city=city, metric=metric, since_hours=hours, limit=400)
    if not ok:
        return []
    return [
        {
            "location": r.get("location_name") or "unspecified location",
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "value": r.get("value"),
            "recorded_at": r.get("recorded_at"),
        }
        for r in rows
        if r.get("latitude") is not None and r.get("longitude") is not None
    ]


def _geo_overlap(foot_a: list[dict], foot_b: list[dict], radius_km: float) -> dict:
    """Nearest-neighbor distance statistics between two metrics' footprints."""
    if not foot_a or not foot_b:
        return {"status": "insufficient_geo_data", "note": "one or both metrics lack geolocated observations"}
    distances = []
    pairs = []
    for a in foot_a[:80]:
        best = None
        for b in foot_b[:80]:
            d = _haversine_km(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
            if best is None or d < best[0]:
                best = (d, b)
        if best:
            distances.append(best[0])
            pairs.append((a, best[1], best[0]))
    if not distances:
        return {"status": "insufficient_geo_data", "note": "no coordinate pairs to compare"}
    mean_d = sum(distances) / len(distances)
    close = [p for p in pairs if p[2] <= radius_km]
    return {
        "status": "ok",
        "compared_pairs": len(pairs),
        "mean_nearest_distance_km": round(mean_d, 2),
        "min_nearest_distance_km": round(min(distances), 2),
        "pairs_within_radius": len(close),
        "radius_km": radius_km,
        "closest_examples": [
            {
                "a_location": a["location"],
                "b_location": b["location"],
                "a_recorded_at": a["recorded_at"],
                "b_recorded_at": b["recorded_at"],
                "distance_km": round(d, 2),
            }
            for a, b, d in sorted(close, key=lambda p: p[2])[:3]
        ],
        "note": "Spatial overlap of observation points only — co-location does not imply interaction.",
    }


def _time_co_occurrence(anomalies: list[dict]) -> list[dict]:
    """Pairs of different-metric anomalies within the co-occurrence window."""
    events = sorted(
        (a for a in anomalies if a.get("metric") and a.get("observed_bucket")),
        key=lambda a: str(a["observed_bucket"]),
    )
    pairs: dict[tuple[str, str], dict] = {}
    for i, a in enumerate(events):
        t_a = datetime.fromisoformat(str(a["observed_bucket"]))
        for b in events[i + 1:]:
            if b["metric"] == a["metric"]:
                continue
            t_b = datetime.fromisoformat(str(b["observed_bucket"]))
            gap_h = abs((t_b - t_a).total_seconds()) / 3600
            if gap_h > CO_OCCURRENCE_WINDOW_HOURS:
                break
            key = tuple(sorted((a["metric"], b["metric"])))
            entry = pairs.setdefault(key, {
                "metric_a": key[0],
                "metric_b": key[1],
                "pair_key": f"{key[0]}~{key[1]}",
                "co_occurrences": 0,
                "examples": [],
            })
            entry["co_occurrences"] += 1
            if len(entry["examples"]) < 3:
                entry["examples"].append({
                    "buckets": sorted([str(a["observed_bucket"]), str(b["observed_bucket"])]),
                    "gap_hours": round(gap_h, 2),
                    "values": {a["metric"]: a.get("observed_value"), b["metric"]: b.get("observed_value")},
                    "scores": {a["metric"]: a.get("deviation_score"), b["metric"]: b.get("deviation_score")},
                })
    return list(pairs.values())


def build_cross_domain_graph(city: str, window_hours: int = 72) -> dict:
    """Assemble the association graph for one city over a time window."""
    ok, anomalies = fetch_recent_anomalies(city, limit=100)
    if not ok:
        anomalies = []

    co_pairs = _time_co_occurrence(anomalies or [])

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    evidence: dict[str, dict] = {}

    for a in anomalies or []:
        nodes.setdefault(a["metric"], {
            "id": a["metric"],
            "label": a["metric"],
            "domain": _metric_source(a["metric"]),
            "unit": METRIC_UNITS.get(a["metric"], ""),
            "anomaly_count": 0,
            "last_anomaly_bucket": a.get("observed_bucket"),
            "max_deviation_score": 0.0,
        })
        node = nodes[a["metric"]]
        node["anomaly_count"] += 1
        try:
            node["max_deviation_score"] = max(
                node["max_deviation_score"], abs(float(a.get("deviation_score") or 0))
            )
        except (TypeError, ValueError):
            pass

    for pair in co_pairs:
        ma, mb = pair["metric_a"], pair["metric_b"]
        edge_id = f"co:{ma}~{mb}"
        edges.append({
            "id": edge_id,
            "source": ma,
            "target": mb,
            "kind": "co_occurrence",
            "evidence_class": "statistical_association",
            "weight": pair["co_occurrences"],
            "label": f"co-flagged {pair['co_occurrences']}x within {CO_OCCURRENCE_WINDOW_HOURS}h",
        })
        evidence[edge_id] = {
            "kind": "co_occurrence",
            "measurements": pair["examples"],
            "sample_size": pair["co_occurrences"],
            "provenance": "anomaly_events table (stored, deduplicated flags)",
            "limitations": _NOTES["association"],
        }

    # Cross-metric correlation for every co-occurring pair (reuse engine).
    for pair in co_pairs:
        ma, mb = pair["metric_a"], pair["metric_b"]
        corr = analyze_pair(city, ma, mb, window_hours)
        edge_id = f"corr:{ma}~{mb}"
        if corr.get("status") == "ok":
            r = float(corr["pearson_r"])
            edges.append({
                "id": edge_id,
                "source": ma,
                "target": mb,
                "kind": "correlation",
                "evidence_class": "statistical_association",
                "weight": abs(r),
                "label": f"r={r:+.2f} ρ={corr['spearman_rho']:+.2f} n={corr['sample_size']}",
            })
            evidence[edge_id] = {
                "kind": "correlation",
                "pearson_r": r,
                "spearman_rho": corr["spearman_rho"],
                "sample_size": corr["sample_size"],
                "outliers_excluded": corr["outliers_excluded"],
                "window_hours": corr["window_hours"],
                "interpretation": corr["interpretation"],
                "provenance": f"civic_data hourly aggregates, {city}, last {window_hours}h",
                "limitations": corr["limitations"],
            }
        else:
            evidence[edge_id] = {
                "kind": "correlation",
                "status": corr.get("status"),
                "reason": corr.get("reason"),
                "provenance": f"civic_data hourly aggregates, {city}, last {window_hours}h",
            }

    # Geo proximity for co-occurring pairs (spatial overlap of observations).
    foot_cache: dict[str, list[dict]] = {}
    for pair in co_pairs:
        ma, mb = pair["metric_a"], pair["metric_b"]
        fa = foot_cache.setdefault(ma, _footprints(city, ma, window_hours))
        fb = foot_cache.setdefault(mb, _footprints(city, mb, window_hours))
        overlap = _geo_overlap(fa, fb, GEO_RADIUS_KM)
        edge_id = f"geo:{ma}~{mb}"
        if overlap.get("status") == "ok" and overlap.get("pairs_within_radius", 0) > 0:
            edges.append({
                "id": edge_id,
                "source": ma,
                "target": mb,
                "kind": "co_location",
                "evidence_class": "hypothesis",
                "weight": round(1.0 / max(0.1, overlap["min_nearest_distance_km"]), 3),
                "label": f"{overlap['pairs_within_radius']} site pairs within {GEO_RADIUS_KM} km",
            })
        evidence[edge_id] = {"kind": "co_location", **overlap}

    # Hypothesis: pair has BOTH co-occurrence and spatial overlap.
    edge_ids = {e["id"] for e in edges}
    for pair in co_pairs:
        if f"co:{pair['metric_a']}~{pair['metric_b']}" in edge_ids and \
           f"geo:{pair['metric_a']}~{pair['metric_b']}" in edge_ids:
            hid = f"hyp:{pair['metric_a']}~{pair['metric_b']}"
            edges.append({
                "id": hid,
                "source": pair["metric_a"],
                "target": pair["metric_b"],
                "kind": "hypothesis",
                "evidence_class": "hypothesis",
                "weight": 1.0,
                "label": "co-occurrence + spatial overlap — review lead, not a cause",
            })
            evidence[hid] = {
                "kind": "hypothesis",
                "requires": ["co_occurrence", "co_location"],
                "limitations": _NOTES["hypothesis"],
            }

    # Attach live measurement evidence for correlated pairs (samples used).
    for edge in [e for e in edges if e["kind"] == "correlation"]:
        ev = evidence[edge["id"]]
        if ev.get("status") != "ok":
            continue
        fa = foot_cache.get(edge["source"]) or []
        fb = foot_cache.get(edge["target"]) or []
        ev["sample_measurements"] = {
            edge["source"]: {"n_rows": len(fa), "example": fa[0] if fa else None},
            edge["target"]: {"n_rows": len(fb), "example": fb[0] if fb else None},
        }

    return {
        "city": city,
        "window_hours": window_hours,
        "co_occurrence_window_hours": CO_OCCURRENCE_WINDOW_HOURS,
        "geo_radius_km": GEO_RADIUS_KM,
        "nodes": sorted(nodes.values(), key=lambda n: (-n["anomaly_count"], n["id"])),
        "edges": edges,
        "evidence": evidence,
        "summary": {
            "anomalies_considered": len(anomalies or []),
            "co_occurring_pairs": len(co_pairs),
            "edges": len(edges),
            "hypotheses": sum(1 for e in edges if e["kind"] == "hypothesis"),
        },
        "terminology": {
            "correlation": "a numeric association between two aligned series (Pearson/Spearman)",
            "statistical_association": "metrics moved together in this window; no cause identified",
            "hypothesis": "a review lead combining co-occurrence and spatial overlap; unverified",
            "causation": "NOT claimed anywhere in this module — see limitations per edge",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": _NOTES["association"],
    }
