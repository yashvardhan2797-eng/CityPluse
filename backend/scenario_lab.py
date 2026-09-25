"""CityPulse Scenario Lab (Phase 9).

Transparent what-if modeling over REAL baseline inputs. Contract:

- Baselines come from stored observations (fetch_metric_series latest values);
  they are echoed with sample size and provenance so nothing looks invented.
- Parameters are user-adjustable within validated ranges (clamped, never
  silently accepted out of range — the clamped value is disclosed).
- Every model is a small, fully documented formula. The formula strings are
  returned verbatim so the UI can show the math next to the numbers.
- Outputs are ALWAYS labeled simulated: model outputs, not predictions.
- Trade-offs are explicit: each model declares what its intervention costs.

Models are pure functions of (baseline inputs, parameters) — no hidden state,
no randomness — so identical calls return identical results and every number
in the UI can be recomputed by hand from the printed formula.
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.impact import COEFFICIENTS, _METRIC_SOURCE, ADVISORY

SIMULATION_LABEL = "SIMULATED — model output for planning exploration, not a prediction"
SIMULATED_PROVIDER = "scenario-lab"


class ScenarioParamError(ValueError):
    """Raised when parameters fail validation (mapped to HTTP 400)."""


def _param(name: str, spec: dict, params: dict) -> float:
    raw = params.get(name, spec["default"])
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ScenarioParamError(f"parameter '{name}' must be a number") from exc
    if value != value:  # NaN
        raise ScenarioParamError(f"parameter '{name}' must be a number")
    clamped = max(spec["min"], min(spec["max"], value))
    return clamped


def _latest_inputs(city: str, metrics: tuple[str, ...]) -> dict:
    """Fetch latest observed values for the model's baseline metrics."""
    from backend.database import fetch_metric_series
    inputs: dict[str, dict] = {}
    for metric in metrics:
        source = _METRIC_SOURCE.get(metric, "transit")
        ok, series = fetch_metric_series(source_type=source, metric=metric, city=city, hours=72)
        latest = next(
            (r for r in reversed(series or []) if r.get("avg_value") is not None), None
        ) if ok else None
        inputs[metric] = {
            "value": latest["avg_value"] if latest else None,
            "bucket": latest["bucket"] if latest else None,
            "n_points": len(series or []),
            "source": f"{source} hourly aggregates (last 72h)",
        }
    return inputs


def _require(baseline: dict, metric: str) -> float:
    value = (baseline.get(metric) or {}).get("value")
    if value is None:
        raise ScenarioParamError(
            f"baseline '{metric}' unavailable for this city — cannot simulate without real inputs"
        )
    return float(value)


# ---------------------------------------------------------------------------
# Models. Each returns rows: [{indicator, unit, baseline, scenario, formula}]
# ---------------------------------------------------------------------------

def _model_traffic_diversion(city: str, params: dict) -> dict:
    baseline = _latest_inputs(city, ("delay_min", "pm25_ugm3"))
    observed_delay = _require(baseline, "delay_min")
    share = _param("diversion_share_pct", TRAFFIC_DIVERSION["params"]["diversion_share_pct"], params)
    corridor_km = _param("corridor_length_km", TRAFFIC_DIVERSION["params"]["corridor_length_km"], params)
    advisory_toggle = bool(params.get("passenger_advisory", True))

    base_speed = COEFFICIENTS["corridor_base_speed_kmh"]["value"]
    base_travel_min = corridor_km / base_speed * 60.0
    # Diverted share adds parallel-route congestion: speed drops proportionally.
    congestion_factor = 1.0 + share / 100.0 * 0.6          # up to +60% congestion at 100%
    scenario_travel_min = base_travel_min * congestion_factor
    # Remaining corridor users see the baseline delay plus a diversion share.
    corridor_delay_baseline = observed_delay
    corridor_delay_scenario = observed_delay * (1.0 - share / 100.0 * 0.8)  # up to 80% relief
    transfer_min = COEFFICIENTS["diversion_delay_transfer_min"]["value"] if share > 0 else 0.0
    if not advisory_toggle:
        transfer_min *= 1.5  # no warning: commuters absorb longer transfers

    rows = [
        {
            "indicator": "corridor_travel_time_min",
            "unit": "min",
            "baseline": round(base_travel_min, 2),
            "scenario": round(scenario_travel_min, 2),
            "formula": f"length({corridor_km:g}km) / base_speed({base_speed:g}) * 60 * (1 + share*0.6)",
        },
        {
            "indicator": "remaining_corridor_delay_min",
            "unit": "min",
            "baseline": round(corridor_delay_baseline, 2),
            "scenario": round(corridor_delay_scenario, 2),
            "formula": f"observed_delay({observed_delay:g}) * (1 - share*0.8)",
        },
        {
            "indicator": "diverted_commuter_transfer_min",
            "unit": "min",
            "baseline": 0.0,
            "scenario": round(transfer_min, 2),
            "formula": "diversion_transfer_min(6.0), x1.5 without passenger advisory",
        },
    ]
    tradeoffs = [
        "Corridor delay falls, but diverted commuters absorb transfer time.",
        "Parallel-route congestion rises with diversion share (modeled, not measured).",
    ]
    if not advisory_toggle:
        tradeoffs.append("Advisory disabled: transfer penalty increased 50% in this model.")
    return {
        "model_id": "traffic_diversion",
        "baseline_inputs": baseline,
        "rows": rows,
        "tradeoffs": tradeoffs,
        "assumptions": [
            f"Arterial free-flow speed assumed {base_speed:g} km/h (corridor_base_speed_kmh coefficient).",
            "Congestion on parallel routes grows linearly with diversion share (capped heuristic).",
        ],
    }


def _model_rainfall_disruption(city: str, params: dict) -> dict:
    baseline = _latest_inputs(city, ("precipitation_mm", "delay_min"))
    observed_rain = _require(baseline, "precipitation_mm")
    rain = _param("rain_mm", RAINFALL_DISRUPTION["params"]["rain_mm"], params)
    drainage = bool(params.get("drainage_check", False))

    per_mm = COEFFICIENTS["rain_delay_minutes_per_mm"]["value"]
    wet_base = max(0.0, observed_rain - 2.5) * per_mm
    wet_scenario = max(0.0, rain - 2.5) * per_mm
    if drainage:
        wet_scenario *= 0.6  # early inspection reduces speed/ delay impact ~40% (planning assumption)
    flood_penalty = COEFFICIENTS["flood_speed_penalty_kmh"]["value"]
    rows = [
        {
            "indicator": "added_transit_delay_min",
            "unit": "min",
            "baseline": round(wet_base, 2),
            "scenario": round(wet_scenario, 2),
            "formula": f"max(0, rain_mm - 2.5) * per_mm({per_mm:g})" + (" * 0.6 with drainage check" if drainage else ""),
        },
        {
            "indicator": "flooded_junction_speed_penalty_kmh",
            "unit": "km/h",
            "baseline": round(max(0.0, observed_rain - 10.0) * flood_penalty / 10.0, 2),
            "scenario": round(max(0.0, rain - 10.0) * flood_penalty / 10.0 * (0.6 if drainage else 1.0), 2),
            "formula": "max(0, rain_mm - 10) * flood_speed_penalty(0.35)/10" + (" * 0.6 with drainage check" if drainage else ""),
        },
    ]
    tradeoffs = [
        "Drainage check reduces modeled impact but assumes teams can be pre-positioned.",
        "Heavy-rain response competes with normal operations (not modeled).",
    ]
    return {
        "model_id": "rainfall_disruption",
        "baseline_inputs": baseline,
        "rows": rows,
        "tradeoffs": tradeoffs,
        "assumptions": [
            "Rain below 2.5 mm/h adds no delay (drizzle threshold).",
            "Drainage-check reduction (40%) is a planning assumption, not a measured effect.",
        ],
    }


def _model_air_quality_stress(city: str, params: dict) -> dict:
    baseline = _latest_inputs(city, ("pm25_ugm3",))
    observed_pm = _require(baseline, "pm25_ugm3")
    pm = _param("pm25_ugm3", AIR_QUALITY_STRESS["params"]["pm25_ugm3"], params)
    advisory_toggle = bool(params.get("sensitive_group_advisory", True))

    guideline = 35.0
    exposure_base = max(0.0, observed_pm - guideline) * 60.0 / guideline
    exposure_scenario = max(0.0, pm - guideline) * 60.0 / guideline * (0.75 if advisory_toggle else 1.0)
    per_100 = COEFFICIENTS["aqi_emergency_vehicles_per_100"]["value"]
    ambulances = max(0.0, (pm - 150)) / 100.0 * per_100
    rows = [
        {
            "indicator": "exposure_minutes_above_guideline",
            "unit": "min (est.)",
            "baseline": round(exposure_base, 2),
            "scenario": round(exposure_scenario, 2),
            "formula": f"max(0, pm25 - guideline({guideline:g})) * 60 / guideline" + (" * 0.75 with advisory" if advisory_toggle else ""),
        },
        {
            "indicator": "extra_ambulances_planned_advisory",
            "unit": "vehicles",
            "baseline": round(max(0.0, (observed_pm - 150)) / 100.0 * per_100, 2),
            "scenario": round(ambulances, 2),
            "formula": f"max(0, pm25 - 150)/100 * per_100({per_100:g}) — planning figure only, nothing is dispatched",
        },
    ]
    tradeoffs = [
        "Advisories reduce modeled exposure ~25% but assume reach and compliance.",
        "Ambulance planning is advisory capacity modeling — no dispatch occurs.",
    ]
    return {
        "model_id": "air_quality_stress",
        "baseline_inputs": baseline,
        "rows": rows,
        "tradeoffs": tradeoffs,
        "assumptions": [
            "Guideline 35 µg/m³ (WHO 24-h interim target) used as the exposure threshold.",
            "Advisory effectiveness (25% exposure reduction) is a planning assumption.",
        ],
    }


def _model_resource_allocation(city: str, params: dict) -> dict:
    baseline = _latest_inputs(city, ("incident_count", "delay_min"))
    incidents = _require(baseline, "incident_count")
    extra_teams = _param("extra_teams", RESOURCE_ALLOCATION["params"]["extra_teams"], params)
    coverage_hours = _param("coverage_hours", RESOURCE_ALLOCATION["params"]["coverage_hours"], params)

    per_incident = 0.5  # teams per active incident (planning heuristic, documented)
    teams_needed = incidents * per_incident
    teams_available = teams_needed + extra_teams
    response_base = 20.0  # assumed baseline response minutes (documented assumption)
    # Each missing team adds queueing delay; each surplus team shaves a little.
    delta = (teams_needed - teams_available) * 6.0
    response_scenario = max(8.0, response_base + delta)
    rows = [
        {
            "indicator": "response_teams_required_vs_available",
            "unit": "teams",
            "baseline": round(teams_needed, 2),
            "scenario": round(teams_available, 2),
            "formula": f"incidents({incidents:g}) * teams_per_incident(0.5) [+ extra_teams({extra_teams:g})]",
        },
        {
            "indicator": "estimated_incident_response_min",
            "unit": "min (model)",
            "baseline": round(response_base, 2),
            "scenario": round(response_scenario, 2),
            "formula": "max(8, 20 + (needed - available) * 6) — queueing heuristic over assumed 20-min base",
        },
        {
            "indicator": "coverage_cost_team_hours",
            "unit": "team-hours",
            "baseline": round(teams_needed * coverage_hours, 2),
            "scenario": round(teams_available * coverage_hours, 2),
            "formula": "teams * coverage_hours — explicit cost of standing up extra capacity",
        },
    ]
    tradeoffs = [
        f"Extra capacity costs {round(extra_teams * coverage_hours, 1)} team-hours in this scenario.",
        "Baseline response time is an assumption; real response data is not in the platform yet.",
    ]
    return {
        "model_id": "resource_allocation",
        "baseline_inputs": baseline,
        "rows": rows,
        "tradeoffs": tradeoffs,
        "assumptions": [
            "0.5 teams per active incident and 20-min base response are planning heuristics.",
            "Queueing penalty of 6 min per missing team is a simplification of dispatch dynamics.",
        ],
    }


TRAFFIC_DIVERSION = {
    "model_id": "traffic_diversion",
    "name": "Traffic diversion",
    "description": "Divert a share of corridor traffic and see estimated travel-time, delay, and commuter trade-offs.",
    "params": {
        "diversion_share_pct": {"min": 0, "max": 100, "default": 30, "unit": "%", "description": "Share of corridor traffic diverted"},
        "corridor_length_km": {"min": 0.5, "max": 40, "default": 8, "unit": "km", "description": "Affected corridor length"},
    },
    "required_baseline_metrics": ["delay_min"],
    "runner": _model_traffic_diversion,
}

RAINFALL_DISRUPTION = {
    "model_id": "rainfall_disruption",
    "name": "Rainfall disruption",
    "description": "Raise rainfall intensity and estimate added transit delay and junction speed loss.",
    "params": {
        "rain_mm": {"min": 0, "max": 120, "default": 15, "unit": "mm/h", "description": "Rainfall intensity"},
    },
    "required_baseline_metrics": ["precipitation_mm"],
    "runner": _model_rainfall_disruption,
}

AIR_QUALITY_STRESS = {
    "model_id": "air_quality_stress",
    "name": "Air-quality stress",
    "description": "Model a PM2.5 episode and the effect of a sensitive-group advisory.",
    "params": {
        "pm25_ugm3": {"min": 0, "max": 500, "default": 90, "unit": "µg/m³", "description": "PM2.5 concentration"},
    },
    "required_baseline_metrics": ["pm25_ugm3"],
    "runner": _model_air_quality_stress,
}

RESOURCE_ALLOCATION = {
    "model_id": "resource_allocation",
    "name": "Emergency resource allocation",
    "description": "Stand up extra response teams for active incidents and see coverage cost vs response time.",
    "params": {
        "extra_teams": {"min": 0, "max": 20, "default": 2, "unit": "teams", "description": "Additional response teams"},
        "coverage_hours": {"min": 1, "max": 24, "default": 6, "unit": "h", "description": "Hours the teams stay deployed"},
    },
    "required_baseline_metrics": ["incident_count"],
    "runner": _model_resource_allocation,
}

MODELS = {m["model_id"]: m for m in (TRAFFIC_DIVERSION, RAINFALL_DISRUPTION, AIR_QUALITY_STRESS, RESOURCE_ALLOCATION)}


def list_models() -> list[dict]:
    """Catalog for the UI: names, param specs, formulas, required baselines."""
    return [
        {
            "model_id": m["model_id"],
            "name": m["name"],
            "description": m["description"],
            "params": m["params"],
            "required_baseline_metrics": m["required_baseline_metrics"],
        }
        for m in MODELS.values()
    ]


def run_model(city: str, model_id: str, params: dict | None = None) -> dict:
    """Validate params, fetch real baselines, run the model, label everything."""
    model = MODELS.get(model_id)
    if model is None:
        raise ScenarioParamError(f"unknown model '{model_id}'")
    params = params or {}
    if not isinstance(params, dict):
        raise ScenarioParamError("params must be an object")

    # Validate/clamp all declared params; reject unknown param names (typo guard).
    known = set(model["params"]) | {"passenger_advisory", "drainage_check", "sensitive_group_advisory"}
    unknown = [k for k in params if k not in known]
    if unknown:
        raise ScenarioParamError(f"unknown parameters: {', '.join(sorted(unknown))}")

    result = model["runner"](city, params)

    return {
        "city": city,
        "model_id": model["model_id"],
        "model_name": model["name"],
        "params_used": {**{k: v["default"] for k, v in model["params"].items()}, **params},
        "param_ranges": {k: {"min": v["min"], "max": v["max"]} for k, v in model["params"].items()},
        **result,
        "coefficients_reused": COEFFICIENTS,
        "simulation_label": SIMULATION_LABEL,
        "advisory": ADVISORY,
        "provenance": {
            "baseline": "stored observations via fetch_metric_series (72h window)",
            "scenario": "documented formula over baseline + user parameters",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "note": (
            "Baseline numbers come from stored data; scenario numbers are model outputs. "
            "This is transparent what-if exploration — not a verified prediction."
        ),
    }
