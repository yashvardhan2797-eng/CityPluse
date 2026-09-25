"""Scenario simulation (Phase 3).

Purpose: let an operator exercise the whole incident pipeline (validation →
persistence → analytics → event lifecycle → real-time push → dashboard) without
waiting for a real incident, and without ever contaminating real data.

Safety contract — enforced in code and covered by tests
-------------------------------------------------------
1. Simulated observations are written with ``provider="simulation"`` and a
   ``source_id`` that always starts with ``SIMULATION_ID_PREFIX``. The
   ``civic_data`` unique key is ``(source_type, source_id)``, so a simulated row
   can never share a key with a live provider row and therefore can never
   overwrite one. ``_assert_simulation_identifier`` re-checks this immediately
   before every write.
2. Observations are built as ``NormalizedObservation`` instances and pass the
   exact same ``validate_observation`` gate the live providers use, so a
   scenario cannot inject implausible coordinates, values, or mislabelled data.
3. Simulated events are created through ``events.create_event`` with
   ``is_simulated=True`` and a ``simulation_run_id``, so they obey the same
   validation and state machine as real events while staying separable (and are
   excluded by ``include_simulated=false`` filters and operational counts).
4. Nothing here deletes or rewrites existing rows. ``reset_run`` only closes
   (status -> closed) the events that belong to that specific run.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend import database as db
from backend.demo_data import DEMO_CITIES
from backend.events import EventError, create_event, get_event, transition_event
from backend.providers.base import (
    NormalizedObservation,
    ProviderError,
    validate_observation,
)
from backend.providers.demo_generators import current_bucket

logger = logging.getLogger("citypulse.simulation")

SIMULATION_ID_PREFIX = "simulation-"
SIMULATION_PROVIDER = "simulation"
DRILL_SUFFIX = " Simulated exercise, not an official report."


def _drill(summary: str) -> str:
    """Standard, unambiguous description for a scenario drill."""
    return f"Scenario drill: {summary}{DRILL_SUFFIX}"


@dataclass(frozen=True)
class Scenario:
    """A deterministic what-if exercise for one city."""

    id: str
    name: str
    summary: str
    source_type: str
    category: str
    metric: str
    unit: str
    value: float
    severity: str
    title: str
    description: str
    location_name: str
    offset: tuple[float, float]          # lat/lon delta from the city centre
    tags: tuple[str, ...] = ()
    evidence: tuple[tuple[str, str, float | None, str], ...] = ()
    recommended_actions: tuple[str, ...] = ()
    duration_minutes: int = 90

    def as_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "source_type": self.source_type,
            "category": self.category,
            "metric": self.metric,
            "unit": self.unit,
            "value": self.value,
            "severity": self.severity,
            "duration_minutes": self.duration_minutes,
            "recommended_actions": list(self.recommended_actions),
        }


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="water_main_break",
        name="Water main break",
        summary="a burst trunk main is flooding a junction near the city centre.",
        source_type="incident",
        category="water",
        metric="incident_count",
        unit="count",
        value=1,
        severity="critical",
        title="Simulated: trunk main break near {city} city centre",
        description=_drill(
            "a large-diameter distribution main has failed, inundating the "
            "carriageway and dropping line pressure in surrounding wards."
        ),
        location_name="{city} city centre (simulated)",
        offset=(0.012, 0.014),
        tags=("drill", "utilities"),
        evidence=(
            ("reading", "Line pressure vs 24h baseline", -41.0, "%"),
            ("sensor", "Pressure-logger station P-17", None, ""),
            ("report", "Two independent inbound caller reports", None, ""),
        ),
        recommended_actions=("Isolate the affected trunk section",
                             "Dispatch repair crew",
                             "Publish a boil-water advisory"),
        duration_minutes=180,
    ),
    Scenario(
        id="flash_flood",
        name="Flash flooding",
        summary="a convective downpour has overwhelmed storm drains in low-lying wards.",
        source_type="weather",
        category="flooding",
        metric="precipitation_mm",
        unit="mm",
        value=96.4,
        severity="critical",
        title="Simulated: flash flooding across {city}",
        description=_drill(
            "an intense convective cell produced a three-hour rainfall total far "
            "above the seasonal norm, overwhelming storm-drain capacity."
        ),
        location_name="{city} low-lying wards (simulated)",
        offset=(-0.018, -0.011),
        tags=("drill", "drainage"),
        evidence=(
            ("reading", "3-hour rainfall accumulation", 96.4, "mm"),
            ("reading", "Storm-drain level vs baseline", 82.0, "%"),
            ("sensor", "Ward-4 water-level gauge", None, ""),
        ),
        recommended_actions=("Pre-position pumping units", "Close the underpass",
                             "Issue a short-notice public alert"),
        duration_minutes=150,
    ),
    Scenario(
        id="transit_disruption",
        name="Transit disruption",
        summary="a signalling fault has cascaded into network-wide delays.",
        source_type="transit",
        category="transit",
        metric="delay_min",
        unit="min",
        value=24.5,
        severity="high",
        title="Simulated: signalling fault on the {city} metro core",
        description=_drill(
            "an interlocking failure has cascaded across the core section, "
            "pushing average delays well above the daily baseline."
        ),
        location_name="{city} metro core interchange (simulated)",
        offset=(0.004, -0.006),
        tags=("drill", "transit"),
        evidence=(
            ("reading", "Average network delay", 24.5, "min"),
            ("reading", "Peak platform load factor", 112.0, "%"),
            ("report", "Operator log: interlocking fault 41-B", None, ""),
        ),
        recommended_actions=("Activate bus-replacement shuttles",
                             "Push in-app travel advisories",
                             "Staff the worst-affected platforms"),
        duration_minutes=120,
    ),
    Scenario(
        id="air_quality_spike",
        name="Air quality spike",
        summary="a shallow inversion has trapped particulate matter over the city.",
        source_type="air_quality",
        category="air_quality",
        metric="pm25_ugm3",
        unit="µg/m³",
        value=213.0,
        severity="high",
        title="Simulated: PM2.5 spike over {city}",
        description=_drill(
            "a shallow inversion with very low wind has trapped particulates near "
            "the surface, pushing PM2.5 far above the health threshold."
        ),
        location_name="{city} central monitoring zone (simulated)",
        offset=(-0.003, 0.008),
        tags=("drill", "health"),
        evidence=(
            ("reading", "PM2.5 vs 7-day median", 213.0, "µg/m³"),
            ("reading", "Surface wind speed", 1.8, "km/h"),
            ("reading", "Vertical mixing depth", 180.0, "m"),
        ),
        recommended_actions=("Issue a health advisory for sensitive groups",
                             "Pause dust-generating municipal works",
                             "Advise schools to limit outdoor activity"),
        duration_minutes=240,
    ),
    Scenario(
        id="power_grid_strain",
        name="Power grid strain",
        summary="feeder loading has crossed its emergency rating during peak demand.",
        source_type="incident",
        category="power",
        metric="incident_count",
        unit="count",
        value=1,
        severity="high",
        title="Simulated: distribution transformer overload in {city}",
        description=_drill(
            "a distribution feeder has crossed its short-term emergency rating "
            "during peak demand, risking a localised outage."
        ),
        location_name="{city} industrial feeder (simulated)",
        offset=(0.021, -0.017),
        tags=("drill", "utilities"),
        evidence=(
            ("reading", "Feeder load vs rating", 118.0, "%"),
            ("reading", "Transformer oil temperature", 94.0, "°C"),
            ("sensor", "Substation S-9 telemetry", None, ""),
        ),
        recommended_actions=("Shift load to the adjacent feeder",
                             "Deploy a mobile transformer as contingency",
                             "Notify large industrial consumers"),
        duration_minutes=120,
    ),
    Scenario(
        id="road_closure",
        name="Arterial road closure",
        summary="an emergency inspection has closed lanes on a key arterial.",
        source_type="incident",
        category="road",
        metric="incident_count",
        unit="count",
        value=1,
        severity="moderate",
        title="Simulated: emergency lane closure on a {city} arterial",
        description=_drill(
            "a structural inspection has closed lanes on a key arterial approach, "
            "pushing diversion traffic onto residential streets."
        ),
        location_name="{city} arterial approach (simulated)",
        offset=(-0.014, 0.019),
        tags=("drill", "traffic"),
        evidence=(
            ("report", "Structural inspection flag (category 2)", None, ""),
            ("reading", "Corridor volume vs baseline", 58.0, "%"),
        ),
        recommended_actions=("Set up signed diversion routes",
                             "Retime signals on the parallel corridor",
                             "Publish a travel advisory"),
        duration_minutes=360,
    ),
)

SCENARIOS_BY_ID: dict[str, Scenario] = {scenario.id: scenario for scenario in SCENARIOS}


def _city(city_id: str) -> dict[str, Any]:
    for city in DEMO_CITIES:
        if city["id"].lower() == str(city_id).strip().lower():
            return city
    raise EventError(
        f"unknown city '{city_id}'; expected one of {', '.join(c['id'] for c in DEMO_CITIES)}",
        code="unknown_city",
    )


def _assert_simulation_identifier(source_id: str) -> None:
    """Hard guard: simulated observations must never share a live provider id."""
    if not source_id.startswith(SIMULATION_ID_PREFIX):
        raise EventError(
            f"simulated source_id must start with '{SIMULATION_ID_PREFIX}' "
            "(so it can never overwrite a live observation)",
            code="simulation_identifier_denied",
            status=500,
        )


def list_scenarios_public() -> list[dict[str, Any]]:
    """Scenario catalogue for the dashboard's simulation controls."""
    return [scenario.as_public() for scenario in SCENARIOS]


def get_scenario(scenario_id: str) -> Scenario | None:
    return SCENARIOS_BY_ID.get(str(scenario_id or "").strip().lower())


def generate_run_ref(scenario_id: str) -> str:
    """Short, unique, human-readable run id, e.g. ``SIM-FLASHFLOO-20260924-A1B``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    token = secrets.token_hex(2).upper()
    return f"SIM-{scenario_id[:9].upper()}-{stamp}-{token}"


def build_observation(
    scenario: Scenario, city: dict[str, Any], run_ref: str
) -> NormalizedObservation:
    """Create a validated synthetic observation for a scenario (same pipeline)."""
    source_id = (
        f"{SIMULATION_ID_PREFIX}{scenario.id}-{city['id']}-"
        f"{current_bucket().strftime('%Y%m%d%H%M')}"
    )
    _assert_simulation_identifier(source_id)
    observation = NormalizedObservation(
        source_type=scenario.source_type,
        provider=SIMULATION_PROVIDER,
        source_id=source_id,
        city=city["name"],
        city_id=city["id"],
        location_name=scenario.location_name.format(city=city["name"]),
        latitude=round(float(city["lat"]) + scenario.offset[0], 6),
        longitude=round(float(city["lon"]) + scenario.offset[1], 6),
        metric=scenario.metric,
        value=scenario.value,
        unit=scenario.unit,
        severity=scenario.severity,
        description=f"Demo: {scenario.title.format(city=city['name'])}",
        recorded_at=current_bucket(),
        source_url=None,
        metadata={
            "generator": "simulation",
            "scenario_id": scenario.id,
            "scenario_name": scenario.name,
            "simulation_run_id": run_ref,
            "is_synthetic": True,
        },
        is_synthetic=True,
    )
    # Same gate the live providers must pass — no shortcut for simulations.
    validate_observation(observation)
    return observation


def _event_payload(
    scenario: Scenario, city: dict[str, Any], run_ref: str
) -> dict[str, Any]:
    """Event-shaped scenario data, fed through events.create_event validation."""
    return {
        "city_id": city["id"],
        "source_type": scenario.source_type,
        "category": scenario.category,
        "severity": scenario.severity,
        "title": scenario.title.format(city=city["name"]),
        "description": scenario.description,
        "latitude": round(float(city["lat"]) + scenario.offset[0], 6),
        "longitude": round(float(city["lon"]) + scenario.offset[1], 6),
        "location_name": scenario.location_name.format(city=city["name"]),
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "tags": ["simulation", scenario.id, *scenario.tags],
        "evidence": [
            {
                "kind": kind,
                "label": label,
                "value": value,
                "unit": unit or None,
                "source": f"scenario:{scenario.id}",
                "synthetic": True,
            }
            for kind, label, value, unit in scenario.evidence
        ],
        "is_simulated": True,
        "simulation_run_id": run_ref,
        "external_key": f"simulation:{run_ref}",
    }


_DEMO_RUNS: dict[str, dict[str, Any]] = {}


def _run_events(run_ref: str, mode: str | None = None) -> list[dict[str, Any]]:
    """Events belonging to a run, newest first."""
    from backend import events  # local import avoids a circular import at load

    if (mode or events.storage_mode()) == "database":
        ok, rows = db.fetch_simulation_run_events(run_ref)
        if not ok:
            logger.warning("simulation event query failed: %s", rows)
            return []
        return [events.to_public_event(row) for row in rows]
    with events._DEMO_LOCK:  # noqa: SLF001 - same package, deliberate reuse
        rows = [dict(row) for row in events._DEMO_EVENTS]  # noqa: SLF001
    attached = [row for row in rows if row.get("simulation_run_id") == run_ref]
    return [events.to_public_event(row) for row in attached]


def run_scenario(
    scenario_id: str,
    city_id: str,
    *,
    actor: str | None = None,
    write_observation: bool = True,
    note: str | None = None,
) -> dict[str, Any]:
    """Start a scenario: persist a labeled observation + create a civic event.

    Both artefacts pass through the production validation gates (the provider
    contract for the observation, the event state machine for the event), so a
    drill exercises the real pipeline rather than a parallel shortcut.
    """
    from backend import events  # local import avoids a circular import at load

    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise EventError(
            f"unknown scenario '{scenario_id}'; expected one of "
            f"{', '.join(SCENARIOS_BY_ID)}",
            code="unknown_scenario",
            status=404,
        )
    city = _city(city_id)
    run_ref = generate_run_ref(scenario.id)
    mode = events.storage_mode()
    actor_name = actor or "simulation-operator"

    run = {
        "run_ref": run_ref,
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "city": city["name"],
        "city_id": city["id"],
        "status": "running",
        "started_at": datetime.now(timezone.utc),
        "finished_at": None,
        "events_created": 0,
        "observations_written": 0,
        "actor": actor_name,
        "notes": note,
    }
    if mode == "database":
        ok, error = db.insert_simulation_run(run)
        if not ok:
            raise EventError(
                f"could not record simulation run: {error}",
                code="storage_error",
                status=503,
            )
    else:
        _DEMO_RUNS[run_ref] = dict(run)

    # 1. Synthetic observation through the provider validation + upsert path.
    observation = build_observation(scenario, city, run_ref)
    observations_written = 0
    observation_error: str | None = None
    if write_observation:
        if mode == "database":
            ok, payload = db.upsert_observations([observation])
            if ok:
                observations_written = int(payload)
            else:
                observation_error = str(payload)
        else:
            observation_error = "demo mode: observation validated but not persisted"

    # 2. Civic event through the same lifecycle code as a real incident.
    try:
        event = create_event(
            _event_payload(scenario, city, run_ref),
            actor=actor_name,
            is_simulated=True,
            simulation_run_id=run_ref,
        )
    except EventError:
        _finish_run(run_ref, mode, status="reset", events_created=0,
                    observations_written=observations_written)
        raise

    _finish_run(run_ref, mode, status="running", events_created=1,
                observations_written=observations_written)
    run["events_created"] = 1
    run["observations_written"] = observations_written
    run["started_at"] = run["started_at"].isoformat()

    return {
        "mode": mode,
        "persisted": mode == "database",
        "run": run,
        "event": event,
        "observation": {
            "source_id": observation.source_id,
            "provider": observation.provider,
            "metric": observation.metric,
            "value": observation.value,
            "unit": observation.unit,
            "recorded_at": observation.recorded_at.isoformat(),
            "is_synthetic": True,
            "persisted": mode == "database" and observations_written > 0,
            "error": observation_error,
        },
        "recommended_actions": list(scenario.recommended_actions),
        "disclaimer": (
            "Scenario drill: the observation and event are clearly labelled "
            "synthetic (provider 'simulation', is_simulated=true) and can never "
            "overwrite a live provider reading."
        ),
    }


def _finish_run(
    run_ref: str,
    mode: str,
    *,
    status: str,
    events_created: int,
    observations_written: int,
    finished: bool = False,
) -> None:
    """Update run counters/status in whichever store is active."""
    fields: dict[str, Any] = {
        "status": status,
        "events_created": events_created,
        "observations_written": observations_written,
    }
    if finished:
        fields["finished_at"] = datetime.now(timezone.utc)
    if mode == "database":
        ok, error = db.update_simulation_run(run_ref, fields)
        if not ok:
            logger.warning("simulation run update failed: %s", error)
        return
    stored = _DEMO_RUNS.get(run_ref)
    if stored is not None:
        stored.update(fields)


def list_runs(limit: int = 20) -> dict[str, Any]:
    """Recent simulation runs with their current event status."""
    from backend import events

    limit = max(1, min(int(limit), 100))
    mode = events.storage_mode()
    runs: list[dict[str, Any]] = []
    if mode == "database":
        ok, rows = db.fetch_simulation_runs(limit)
        if not ok:
            logger.warning("simulation run list failed, serving demo: %s", rows)
            mode = "demo"
        else:
            runs = rows
    if mode == "demo":
        runs = sorted(
            (_serialize_run(dict(run)) for run in _DEMO_RUNS.values()),
            key=lambda run: str(run.get("started_at") or ""),
            reverse=True,
        )[:limit]

    for run in runs:
        attached = _run_events(str(run["run_ref"]), mode)
        run["events"] = attached
        run["event_refs"] = [e.get("event_ref") for e in attached]
        run["open_events"] = sum(1 for e in attached if e.get("is_active"))
    return {
        "mode": mode,
        "persisted": mode == "database",
        "runs": runs,
        "count": len(runs),
        "note": "Simulation runs are drills; their observations and events are always labelled synthetic.",
    }


def _serialize_run(run: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe run record (datetimes to ISO strings)."""
    out = dict(run)
    for key in ("started_at", "finished_at"):
        value = out.get(key)
        if isinstance(value, datetime):
            out[key] = value.astimezone(timezone.utc).isoformat()
    return out


def run_detail(run_ref: str) -> dict[str, Any] | None:
    """One run plus the events it produced (None when unknown)."""
    listed = list_runs(limit=100)
    for run in listed["runs"]:
        if run["run_ref"] == run_ref:
            return {"mode": listed["mode"], "persisted": listed["persisted"], "run": run}
    return None


def advance_run(
    run_ref: str,
    action: str,
    *,
    actor: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Apply a lifecycle action to the newest active event of a run.

    This exists so a demo can walk an incident through acknowledge -> resolve ->
    close using exactly the same transition rules the dashboard uses.
    """
    from backend import events

    detail = run_detail(run_ref)
    if detail is None:
        raise EventError("simulation run not found", code="not_found", status=404)

    attached = detail["run"].get("events") or []
    # "active" here means "not yet terminal": a resolved drill event must still
    # be closable so a run can be walked all the way to the end.
    target = next((e for e in attached if e.get("status") != "closed"), None)
    if target is None:
        raise EventError(
            "this run has no open event left to transition",
            code="no_active_event",
            status=409,
        )
    updated = events.transition_event(
        str(target["event_ref"]), action, actor=actor or "simulation-operator", note=note
    )
    refreshed = run_detail(run_ref)
    return {
        "mode": detail["mode"],
        "run": (refreshed or detail)["run"],
        "event": updated,
    }


def reset_run(run_ref: str, *, actor: str | None = None) -> dict[str, Any]:
    """Close the events created by a run and mark the run as reset.

    Only events whose ``simulation_run_id`` matches are touched, and they are
    closed (never deleted) so the audit trail survives a drill cleanup.
    """
    from backend import events

    detail = run_detail(run_ref)
    if detail is None:
        raise EventError("simulation run not found", code="not_found", status=404)
    mode = str(detail["mode"])
    closed: list[str] = []
    skipped: list[str] = []
    for event in detail["run"].get("events") or []:
        if not event.get("is_active"):
            skipped.append(str(event.get("event_ref")))
            continue
        try:
            events.transition_event(
                str(event["event_ref"]),
                "close",
                actor=actor or "simulation-operator",
                note="Simulation run reset",
            )
            closed.append(str(event.get("event_ref")))
        except EventError as exc:
            logger.warning("could not close simulated event %s: %s",
                           event.get("event_ref"), exc)
            skipped.append(str(event.get("event_ref")))

    _finish_run(
        run_ref, mode, status="reset", events_created=detail["run"].get("events_created", 0),
        observations_written=detail["run"].get("observations_written", 0), finished=True,
    )
    refreshed = run_detail(run_ref)
    return {
        "mode": mode,
        "run": (refreshed or detail)["run"],
        "closed_events": closed,
        "skipped_events": skipped,
        "note": "Simulated events were closed (not deleted) so the audit trail is preserved.",
    }


def reset_demo_runs() -> None:
    """Clear in-memory runs (tests only)."""
    _DEMO_RUNS.clear()
