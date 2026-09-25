"""CityPulse Operations Copilot (Phase 9).

Upgrades the Phase 3 companion into a data-grounded analytical assistant.

Tool contract (enforced in code):
- Tools are small, named, read-only functions. Each declares its parameters,
  which are validated (type/range/allowlist) BEFORE any call — the LLM never
  sees the database, never writes, and never produces SQL.
- The LLM (when configured) only receives: the question + JSON tool outputs,
  under the same evidence-only prompt rules as ai_summary (number validation
  still applies via _validate_output).
- The deterministic path answers from tool outputs alone, so the feature works
  with zero AI keys and degrades gracefully.

Tools: get_metric, get_anomalies, compare_zones, list_events, run_scenario,
       get_resilience
"""
from __future__ import annotations

import logging

from backend.ai_summary import _validate_output, _call_llm
from backend.companion import answer_from_evidence
from backend.database import fetch_latest_by_metric, fetch_metric_series

logger = logging.getLogger("citypulse.copilot")

MAX_TOOL_OUTPUT_CHARS = 12000

# ---------------------------------------------------------------------------
# Read-only tools. Every tool: (a) validates inputs, (b) returns compact JSON.
# ---------------------------------------------------------------------------

def _tool_get_metric(city: str, args: dict) -> dict:
    metric = str(args.get("metric") or "").strip()
    allowed = {
        "pm25_ugm3", "pm10_ugm3", "o3_ugm3", "temperature_c", "humidity_pct",
        "precipitation_mm", "wind_speed_kmh", "delay_min", "load_factor_pct",
        "incident_count",
    }
    if metric not in allowed:
        return {"tool": "get_metric", "error": f"metric must be one of {sorted(allowed)}"}
    hours = _bounded_int(args.get("hours"), 24, 6, 720)
    ok, series = fetch_metric_series(source_type=None, metric=metric, city=city, hours=hours)
    if not ok:
        return {"tool": "get_metric", "metric": metric, "error": str(series)}
    values = [r["avg_value"] for r in series or [] if r.get("avg_value") is not None]
    latest = values[-1] if values else None
    return {
        "tool": "get_metric",
        "metric": metric,
        "city": city,
        "hours": hours,
        "n_points": len(values),
        "latest": latest,
        "avg": round(sum(values) / len(values), 2) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "series_tail": [{"bucket": r["bucket"], "avg_value": r["avg_value"]} for r in (series or [])[-8:]],
    }


def _tool_get_anomalies(city: str, args: dict) -> dict:
    from backend.database import fetch_recent_anomalies
    limit = _bounded_int(args.get("limit"), 10, 1, 50)
    ok, rows = fetch_recent_anomalies(city, limit=limit)
    if not ok:
        return {"tool": "get_anomalies", "error": str(rows)}
    return {
        "tool": "get_anomalies",
        "city": city,
        "count": len(rows or []),
        "anomalies": [
            {k: r.get(k) for k in (
                "metric", "observed_bucket", "observed_value", "baseline_value",
                "deviation_score", "confidence")}
            for r in (rows or [])
        ],
    }


def _tool_compare_zones(city: str, args: dict) -> dict:
    """City-wide vs per-location averages for one metric (read-only)."""
    metric = str(args.get("metric") or "pm25_ugm3").strip()
    hours = _bounded_int(args.get("hours"), 24, 6, 336)
    from backend.database import fetch_location_comparison
    ok, rows = fetch_location_comparison(city, hours=hours, metrics=[metric], limit_locations=12)
    if not ok:
        return {"tool": "compare_zones", "error": str(rows)}
    zones = [
        {
            "location": r["location_name"],
            "avg": round(float(r["avg_value"]), 2) if r["avg_value"] is not None else None,
            "observations": int(r["observations"]),
            "hours_covered": int(r["hours_covered"]),
        }
        for r in rows or []
        if r.get("metric") == metric
    ]
    zones.sort(key=lambda z: (z["avg"] is None, z["avg"] if z["avg"] is not None else 0))
    return {
        "tool": "compare_zones",
        "metric": metric,
        "city": city,
        "hours": hours,
        "zones": zones,
        "note": "Differences may reflect sensor coverage, not conditions; sample sizes disclosed.",
    }


def _tool_list_events(city: str, args: dict) -> dict:
    from backend.events import list_events
    status = str(args.get("status") or "open").strip().lower()
    if status not in ("open", "acknowledged", "in_progress", "resolved", "closed"):
        status = "open"
    limit = _bounded_int(args.get("limit"), 10, 1, 50)
    try:
        listing = list_events(city=city, statuses=(status,), include_simulated=True, limit=limit)
        events = listing.get("events", []) if isinstance(listing, dict) else []
    except Exception as exc:  # noqa: BLE001
        return {"tool": "list_events", "error": f"event store unavailable: {exc}"}
    return {
        "tool": "list_events",
        "city": city,
        "status_filter": status,
        "count": len(events),
        "events": [
            {k: ev.get(k) for k in (
                "event_ref", "title", "severity", "status", "category",
                "location_name", "is_simulated", "reported_at")}
            for ev in events
        ],
    }


def _tool_run_scenario(city: str, args: dict) -> dict:
    from backend.scenario_lab import ScenarioParamError, run_model
    model_id = str(args.get("model") or "").strip()
    try:
        result = run_model(city, model_id, args.get("params") if isinstance(args.get("params"), dict) else {})
    except ScenarioParamError as exc:
        return {"tool": "run_scenario", "error": str(exc), "models": list(_scenario_catalog())}
    return {
        "tool": "run_scenario",
        "model": result["model_id"],
        "simulation_label": result["simulation_label"],
        "rows": result["rows"],
        "tradeoffs": result["tradeoffs"],
    }


def _scenario_catalog() -> list[str]:
    from backend.scenario_lab import MODELS
    return sorted(MODELS)


def _tool_get_resilience(city: str, args: dict) -> dict:
    from backend.resilience import compute_resilience
    hours = _bounded_int(args.get("hours"), 168, 24, 720)
    report = compute_resilience(city, hours=hours)
    return {
        "tool": "get_resilience",
        "city": report["city"],
        "resilience_score": report["resilience_score"],
        "category": report["category"],
        "components": {
            k: {"value": v["value"], "status": v["status"]}
            for k, v in report["components"].items()
        },
        "disclaimer": report["disclaimer"],
    }


_TOOLS = {
    "get_metric": _tool_get_metric,
    "get_anomalies": _tool_get_anomalies,
    "compare_zones": _tool_compare_zones,
    "list_events": _tool_list_events,
    "run_scenario": _tool_run_scenario,
    "get_resilience": _tool_get_resilience,
}

TOOL_SPECS = [
    {"name": "get_metric", "description": "Latest/average/min/max for one metric over a window",
     "params": {"metric": "string (allowlisted metric name, required)", "hours": "int 6-720"}},
    {"name": "get_anomalies", "description": "Recent stored anomaly flags",
     "params": {"limit": "int 1-50"}},
    {"name": "compare_zones", "description": "Per-location averages for one metric with coverage",
     "params": {"metric": "string", "hours": "int 6-336"}},
    {"name": "list_events", "description": "Civic events by status",
     "params": {"status": "open|acknowledged|in_progress|resolved|closed", "limit": "int 1-50"}},
    {"name": "run_scenario", "description": "Run a labeled scenario-lab model",
     "params": {"model": "traffic_diversion|rainfall_disruption|air_quality_stress|resource_allocation",
                "params": "object of model parameters"}},
    {"name": "get_resilience", "description": "Explainable resilience indicator with components",
     "params": {"hours": "int 24-720"}},
]


def _bounded_int(raw, default: int, lo: int, hi: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Intent routing (deterministic path). Pure substring matching over the
# question — no model required; LLM path receives tool outputs as evidence.
# ---------------------------------------------------------------------------

def _route_intents(question: str) -> list[tuple[str, dict]]:
    q = question.lower()
    plans: list[tuple[str, dict]] = []

    def has(*words: str) -> bool:
        return any(w in q for w in words)

    scenario_ids = {
        "traffic": "traffic_diversion", "divert": "traffic_diversion",
        "rain": "rainfall_disruption", "flood": "rainfall_disruption",
        "air quality": "air_quality_stress", "pm2.5": "air_quality_stress",
        "pm25": "air_quality_stress", "ambulance": "resource_allocation",
        "resource": "resource_allocation", "team": "resource_allocation",
    }
    metric_words = [
        ("pm2.5", "pm25_ugm3"), ("pm25", "pm25_ugm3"), ("air quality", "pm25_ugm3"),
        ("temperature", "temperature_c"), ("rain", "precipitation_mm"),
        ("precip", "precipitation_mm"), ("wind", "wind_speed_kmh"),
        ("delay", "delay_min"), ("transit", "delay_min"), ("load", "load_factor_pct"),
        ("incident", "incident_count"), ("humidity", "humidity_pct"), ("ozone", "o3_ugm3"),
    ]

    if has("resilien"):
        plans.append(("get_resilience", {}))
    if has("scenario", "what if", "what-if", "simulate"):
        matched = next((m for w, m in scenario_ids.items() if w in q), "traffic_diversion")
        plans.append(("run_scenario", {"model": matched}))
    if has("zone", "compare", "area", "neighborhood", "neighbourhood", "location"):
        metric = next((m for w, m in metric_words if w in q), None)
        plans.append(("compare_zones", {"metric": metric or "pm25_ugm3"}))
    if has("anomal", "unusual", "spike"):
        plans.append(("get_anomalies", {}))
    if has("event", "incident", "accident"):
        plans.append(("list_events", {"status": "open"}))
    metric = next((m for w, m in metric_words if w in q), None)
    if metric:
        plans.append(("get_metric", {"metric": metric, "hours": 24}))
    return plans


def _deterministic_answer(question: str, city: str, tool_outputs: list[dict]) -> str:
    """Compose an answer strictly from tool outputs (deterministic fallback)."""
    q = question.lower()

    def fmt(v, suffix=""):
        return "no data" if v is None else f"{v:g}{suffix}"

    # Scenario results
    scenario = next((t for t in tool_outputs if t.get("tool") == "run_scenario"), None)
    if scenario and not scenario.get("error") and has_token(q, "scenario", "what if", "what-if", "simulate", "divert", "rain", "flood", "ambulance", "resource", "team"):
        rows_txt = "; ".join(
            f"{r['indicator']}: baseline {fmt(r['baseline'])} → scenario {fmt(r['scenario'])} {r.get('unit', '')}".rstrip()
            for r in scenario.get("rows", [])[:3]
        )
        return (
            f"Simulated ({scenario.get('simulation_label', 'SIMULATED')}): {rows_txt}. "
            f"Trade-offs: {' '.join(scenario.get('tradeoffs', [])[:2])} "
            "Model output over real baseline data — not a prediction."
        )

    # Zone comparison
    zones = next((t for t in tool_outputs if t.get("tool") == "compare_zones"), None)
    if zones and not zones.get("error") and has_token(q, "zone", "compare", "area", "location", "neighborhood", "neighbourhood"):
        zl = zones.get("zones", [])
        if not zl:
            return f"No per-location observations for {zones.get('metric')} in the window — comparison unavailable (coverage statement, not a condition claim)."
        top = ", ".join(f"{z['location']} {z['avg'] if z['avg'] is not None else 'no data'}" for z in zl[:3])
        return (
            f"{zones.get('metric')} by location over {zones.get('hours')}h: {top}. "
            "Sample sizes differ per location; differences may reflect coverage, not conditions."
        )

    # Resilience
    resil = next((t for t in tool_outputs if t.get("tool") == "get_resilience"), None)
    if resil and not resil.get("error") and has_token(q, "resilien"):
        comps = ", ".join(f"{k} {fmt(v.get('value'))}" for k, v in resil.get("components", {}).items())
        return (
            f"Resilience for {resil.get('city')}: score {fmt(resil.get('resilience_score'))} "
            f"(category: {resil.get('category')}). Components: {comps}. {resil.get('disclaimer', '')}"
        )

    # Anomalies
    anom = next((t for t in tool_outputs if t.get("tool") == "get_anomalies"), None)
    if anom and not anom.get("error") and has_token(q, "anomal", "unusual", "spike"):
        if not anom.get("anomalies"):
            return f"No anomalies currently flagged for {anom.get('city')} — insufficient evidence or within baseline; not a claim that conditions are normal."
        a = anom["anomalies"][0]
        return (
            f"Most recent flagged anomaly: {a.get('metric')} at {fmt(a.get('observed_value'))} "
            f"vs baseline {fmt(a.get('baseline_value'))} (z={fmt(a.get('deviation_score'))}, "
            f"confidence {a.get('confidence')}) in bucket {str(a.get('observed_bucket'))[:16]}Z. "
            "A statistical flag, not an explanation."
        )

    # Events
    ev = next((t for t in tool_outputs if t.get("tool") == "list_events"), None)
    if ev and not ev.get("error") and has_token(q, "event", "incident", "accident"):
        el = ev.get("events", [])
        if not el:
            return f"No {ev.get('status_filter')} civic events for {ev.get('city')} right now (per the event store)."
        e0 = el[0]
        sim = " (SIMULATED drill)" if e0.get("is_simulated") else ""
        return (
            f"{ev.get('count')} {ev.get('status_filter')} event(s); most recent: "
            f"“{e0.get('title')}” — severity {e0.get('severity')}{sim}, reported {str(e0.get('reported_at'))[:16]}Z."
        )

    # Metrics (fall through)
    met = next((t for t in tool_outputs if t.get("tool") == "get_metric" and not t.get("error")), None)
    if met:
        return (
            f"{met.get('metric')} for {met.get('city')} over last {met.get('hours')}h: "
            f"latest {fmt(met.get('latest'))}, avg {fmt(met.get('avg'))}, range "
            f"{fmt(met.get('min'))}–{fmt(met.get('max'))} across {met.get('n_points')} hourly points."
        )

    return (
        "I can answer from platform data only: metrics, anomalies, zone comparisons, "
        "civic events, resilience, and labeled scenario models. Rephrase with one of those, "
        "or note that this question is outside the available evidence."
    )


def has_token(q: str, *words: str) -> bool:
    return any(w in q for w in words)


def _llm_answer(question: str, city: str, tool_outputs: list[dict]) -> str | None:
    """Optional LLM synthesis over tool outputs; number-validated, else None."""
    import json as _json

    blob = _json.dumps({"city": city, "question": question, "tool_outputs": tool_outputs})
    if len(blob) > MAX_TOOL_OUTPUT_CHARS:
        return None
    prompt = (
        "You are the CityPulse Operations Copilot. You are given JSON tool outputs "
        "(already retrieved, read-only). Rules:\n"
        "- Use ONLY numbers present in the tool outputs. Never invent values.\n"
        "- Associations are not causes; scenario numbers are labeled model outputs.\n"
        "- If the outputs do not cover the question, say exactly that.\n"
        "- Answer in 1-5 short sentences of plain text. No markdown.\n\n"
        f"DATA: {blob}"
    )
    try:
        text = _call_llm(prompt)
        return _validate_output(text, {"tool_outputs": tool_outputs})
    except Exception as exc:  # noqa: BLE001
        logger.info("copilot LLM path unavailable, using deterministic answer: %s", exc)
        return None


def answer(city: str, question: str, window_hours: int = 72) -> dict:
    """Operations Copilot entry point: route → tools → grounded answer."""
    question = str(question or "").strip()[:500]
    if not question:
        return {"city": city, "error": "question is required"}

    plans = _route_intents(question)
    tool_outputs: list[dict] = []
    for tool_name, args in plans[:4]:
        fn = _TOOLS.get(tool_name)
        if fn is None:
            continue
        try:
            out = fn(city, args)
        except Exception as exc:  # noqa: BLE001
            out = {"tool": tool_name, "error": str(exc)}
        tool_outputs.append(out)

    llm_text = _llm_answer(question, city, tool_outputs) if tool_outputs else None
    if llm_text is None:
        llm_text = _deterministic_answer(question, city, tool_outputs)

    # Keep the Phase 3 companion path as an additional fallback for pure
    # evidence questions that routed to no tool at all.
    if not tool_outputs:
        from backend.companion import answer_question
        legacy = answer_question(city, question, window_hours)
        return {
            "city": city,
            "mode": "copilot_fallback",
            "answer": legacy.get("answer"),
            "tools_used": [],
            "grounding": legacy.get("evidence"),
            "disclaimer": "Grounded in stored evidence; associations are not causes.",
        }

    return {
        "city": city,
        "mode": "copilot_tools",
        "answer": llm_text,
        "tools_used": [t.get("tool") for t in tool_outputs],
        "tool_outputs": tool_outputs,
        "tool_specs": TOOL_SPECS,
        "disclaimer": (
            "Answers cite tool outputs (read-only, validated inputs). Scenario figures "
            "are labeled model outputs; associations are not causes."
        ),
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }
