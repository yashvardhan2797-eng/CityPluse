"""Civic event lifecycle management (Phase 3).

A *civic event* is an operational incident a city team can act on: a water main
break, a transit disruption, an air-quality spike, a road closure. This module
owns the domain rules; routes.py only translates HTTP to/from it.

Lifecycle
---------
    open -> acknowledged -> in_progress -> resolved -> closed
             \\______________________________/
      (any active state may resolve directly; resolved may be reopened)

* ``ALLOWED_TRANSITIONS`` is the single source of truth. Illegal jumps are
  rejected with HTTP 409, so the API can never write a state the UI cannot
  explain.
* Every transition is appended to ``civic_event_timeline`` (who / what / when /
  why), which is what makes the lifecycle auditable rather than just mutable.

Honesty rules (consistent with the rest of CityPulse)
-----------------------------------------------------
* Simulated events carry ``is_simulated = True`` and a ``simulation_run_id``.
  They flow through exactly the same validation and lifecycle code, but they
  are always separable from official reports and never overwrite a genuine
  observation (see simulation.py).
* Evidence is stored as supplied and labelled — the API never invents
  supporting readings.
* Storage degrades safely: when PostgreSQL is unreachable the module keeps
  working against a clearly-labeled in-process demo store so the dashboard and
  its event workflow stay usable during an outage.
"""
from __future__ import annotations

import itertools
import logging
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from backend import database as db
from backend.demo_data import DEMO_CITIES
from backend.realtime import get_bus

logger = logging.getLogger("citypulse.events")

# --------------------------------------------------------------- vocabulary

EVENT_STATUSES: tuple[str, ...] = (
    "open", "acknowledged", "in_progress", "resolved", "closed",
)
ACTIVE_STATUSES: tuple[str, ...] = ("open", "acknowledged", "in_progress")
TERMINAL_STATUSES: tuple[str, ...] = ("closed",)
EVENT_SEVERITIES: tuple[str, ...] = ("low", "moderate", "high", "critical")
EVENT_SOURCE_TYPES: tuple[str, ...] = ("weather", "air_quality", "transit", "incident")

ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("acknowledged", "in_progress", "resolved", "closed"),
    "acknowledged": ("in_progress", "resolved", "closed"),
    "in_progress": ("resolved", "closed"),
    "resolved": ("in_progress", "closed"),   # reopen keeps the full history
    "closed": (),                            # terminal state
}

ACTION_TARGET: dict[str, str] = {
    "acknowledge": "acknowledged",
    "start": "in_progress",
    "resolve": "resolved",
    "close": "closed",
    "reopen": "in_progress",
}

# Canonical action for each (status -> next status) pair. Used to tell the UI
# which buttons to offer: "reopen" is the right label for a resolved event even
# though it targets the same status as "start".
STATUS_ACTIONS: dict[str, dict[str, str]] = {
    "open": {
        "acknowledged": "acknowledge",
        "in_progress": "start",
        "resolved": "resolve",
        "closed": "close",
    },
    "acknowledged": {
        "in_progress": "start",
        "resolved": "resolve",
        "closed": "close",
    },
    "in_progress": {"resolved": "resolve", "closed": "close"},
    "resolved": {"in_progress": "reopen", "closed": "close"},
    "closed": {},
}

# Category keeps incidents comparable without hard-coding every city's taxonomy.
CATEGORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
SUGGESTED_CATEGORIES: tuple[str, ...] = (
    "air_quality", "water", "flooding", "transit", "power", "road",
    "weather", "sanitation", "public_safety", "other",
)

MAX_TITLE = 160
MAX_DESCRIPTION = 2000
MAX_LOCATION = 160
MAX_NOTE = 1000
MAX_EVIDENCE_ITEMS = 20
MAX_TAGS = 10
FUTURE_TOLERANCE = timedelta(minutes=5)
EARLIEST_REPORT = datetime(2000, 1, 1, tzinfo=timezone.utc)


class EventError(Exception):
    """Domain error carrying the HTTP status the route layer should return."""

    def __init__(self, message: str, *, code: str = "invalid_event", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | str | None) -> str | None:
    """ISO-8601 string for a datetime (existing strings pass through)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.astimezone(timezone.utc).isoformat()


def _clean_text(value: Any, field: str, *, max_len: int, required: bool = True) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise EventError(f"{field} must be a string", code="validation_error")
    if required and not text:
        raise EventError(f"{field} is required", code="validation_error")
    if len(text) > max_len:
        raise EventError(f"{field} exceeds {max_len} characters", code="validation_error")
    return text


def _parse_timestamp(value: Any, field: str, *, default: datetime | None = None) -> datetime:
    """Parse an ISO-8601 timestamp; timezone-aware values only."""
    if value in (None, ""):
        if default is None:
            raise EventError(f"{field} is required", code="validation_error")
        return default
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise EventError(
                f"{field} must be an ISO-8601 timestamp", code="validation_error"
            ) from exc
    else:
        raise EventError(f"{field} must be a string", code="validation_error")

    if parsed.tzinfo is None:
        raise EventError(
            f"{field} must include a timezone offset (e.g. 2026-01-01T10:00:00Z)",
            code="validation_error",
        )
    parsed = parsed.astimezone(timezone.utc)
    if parsed > _utc_now() + FUTURE_TOLERANCE:
        raise EventError(f"{field} cannot be in the future", code="validation_error")
    if parsed < EARLIEST_REPORT:
        raise EventError(f"{field} is implausibly old", code="validation_error")
    return parsed


def _coord(value: Any, field: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EventError(f"{field} must be a number", code="validation_error") from exc
    if not (low <= number <= high):
        raise EventError(
            f"{field} must be between {low} and {high}", code="validation_error"
        )
    return round(number, 6)


def _resolve_city(city_id: Any, city_name: Any = None) -> dict[str, Any]:
    """Map a city id or display name onto the canonical city record."""
    candidate = (str(city_id).strip() if city_id else "") or (
        str(city_name).strip() if city_name else ""
    )
    if not candidate:
        raise EventError("city is required", code="validation_error")
    lowered = candidate.lower()
    for city in DEMO_CITIES:
        if city["id"].lower() == lowered or city["name"].lower() == lowered:
            return city
    raise EventError(
        f"unknown city '{candidate}'; expected one of "
        f"{', '.join(c['id'] for c in DEMO_CITIES)}",
        code="unknown_city",
    )


def _normalize_evidence(items: Any) -> list[dict[str, Any]]:
    """Validate the evidence list (supporting readings attached to an event)."""
    if items in (None, ""):
        return []
    if not isinstance(items, list):
        raise EventError("evidence must be a list", code="validation_error")
    if len(items) > MAX_EVIDENCE_ITEMS:
        raise EventError(
            f"evidence supports at most {MAX_EVIDENCE_ITEMS} items",
            code="validation_error",
        )
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise EventError(f"evidence[{index}] must be an object", code="validation_error")
        entry: dict[str, Any] = {
            "kind": _clean_text(
                item.get("kind"), f"evidence[{index}].kind", max_len=40
            ).lower(),
            "label": _clean_text(
                item.get("label"), f"evidence[{index}].label", max_len=200
            ),
        }
        for key, max_len in (("unit", 24), ("source", 120), ("ref", 120)):
            if item.get(key):
                entry[key] = _clean_text(
                    item[key], f"evidence[{index}].{key}", max_len=max_len
                )
        if item.get("value") not in (None, ""):
            try:
                entry["value"] = float(item["value"])
            except (TypeError, ValueError) as exc:
                raise EventError(
                    f"evidence[{index}].value must be numeric", code="validation_error"
                ) from exc
        if item.get("observed_at"):
            entry["observed_at"] = utc_iso(
                _parse_timestamp(item["observed_at"], f"evidence[{index}].observed_at")
            )
        entry["synthetic"] = bool(item.get("synthetic", False))
        normalized.append(entry)
    return normalized


def _normalize_tags(tags: Any) -> list[str]:
    if tags in (None, ""):
        return []
    if not isinstance(tags, list):
        raise EventError("tags must be a list", code="validation_error")
    if len(tags) > MAX_TAGS:
        raise EventError(f"at most {MAX_TAGS} tags are allowed", code="validation_error")
    cleaned: list[str] = []
    for tag in tags:
        text = _clean_text(tag, "tag", max_len=32).lower()
        if not CATEGORY_PATTERN.match(text):
            raise EventError(
                f"tag '{text}' must be lowercase letters, digits, '-' or '_'",
                code="validation_error",
            )
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def generate_event_ref(prefix: str = "CP") -> str:
    """Stable public identifier for an event, e.g. ``CP-20260924-1A2B3C``."""
    stamp = _utc_now().strftime("%Y%m%d")
    return f"{prefix}-{stamp}-{secrets.token_hex(3).upper()}"


def normalize_new_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a create-event request body into database-ready fields.

    This is the single validation gate for every source of events (operator
    form, open-data ingestion, and the simulation engine), so a simulated
    incident is subject to exactly the same rules as a real one.
    """
    if not isinstance(payload, dict):
        raise EventError("request body must be a JSON object", code="validation_error")

    city = _resolve_city(
        payload.get("city_id") or payload.get("city"), payload.get("city_name")
    )

    source_type = str(payload.get("source_type") or "incident").strip().lower()
    if source_type not in EVENT_SOURCE_TYPES:
        raise EventError(
            f"source_type must be one of {', '.join(EVENT_SOURCE_TYPES)}",
            code="validation_error",
        )

    category = str(payload.get("category") or "other").strip().lower()
    if not CATEGORY_PATTERN.match(category):
        raise EventError(
            "category must be 2-40 chars of lowercase letters, digits, '-' or '_'",
            code="validation_error",
        )

    severity = str(payload.get("severity") or "moderate").strip().lower()
    if severity not in EVENT_SEVERITIES:
        raise EventError(
            f"severity must be one of {', '.join(EVENT_SEVERITIES)}",
            code="validation_error",
        )

    reported_at = _parse_timestamp(
        payload.get("reported_at"), "reported_at", default=_utc_now()
    )

    return {
        "event_ref": str(payload.get("event_ref") or "").strip() or generate_event_ref(),
        "external_key": (
            _clean_text(payload["external_key"], "external_key", max_len=200)
            if payload.get("external_key")
            else None
        ),
        "city": city["name"],
        "city_id": city["id"],
        "source_type": source_type,
        "category": category,
        "title": _clean_text(payload.get("title"), "title", max_len=MAX_TITLE),
        "description": _clean_text(
            payload.get("description"), "description", max_len=MAX_DESCRIPTION
        ),
        "severity": severity,
        "status": "open",
        "latitude": _coord(payload.get("latitude"), "latitude", -90, 90),
        "longitude": _coord(payload.get("longitude"), "longitude", -180, 180),
        "location_name": _clean_text(
            payload.get("location_name"), "location_name", max_len=MAX_LOCATION
        ),
        "reported_at": reported_at,
        "evidence": _normalize_evidence(payload.get("evidence")),
        "tags": _normalize_tags(payload.get("tags")),
        "is_simulated": bool(payload.get("is_simulated", False)),
        "simulation_run_id": (
            _clean_text(payload["simulation_run_id"], "simulation_run_id", max_len=64)
            if payload.get("simulation_run_id")
            else None
        ),
        "revision": 1,
    }


# ------------------------------------------------------------- storage mode

def storage_mode() -> str:
    """'database' when PostgreSQL answers, otherwise 'demo' (in-process)."""
    return "database" if db.database_available() else "demo"


# --------------------------------------------------- in-process demo store
#
# Used only when PostgreSQL is unreachable so the event workflow (create,
# acknowledge, resolve, filter, stream) stays demonstrable. Responses built
# from this store are labelled ``"mode": "demo"`` with ``persisted: false``,
# so nobody can mistake them for durable civic records.

_DEMO_LOCK = threading.RLock()
_DEMO_EVENTS: list[dict[str, Any]] = []
_DEMO_TIMELINE: dict[str, list[dict[str, Any]]] = {}
_DEMO_IDS = itertools.count(1)

_STATUS_ORDER = {
    status: index
    for index, status in enumerate(
        ("open", "acknowledged", "in_progress", "resolved", "closed")
    )
}


def _sort_stamp(value: Any) -> float:
    """Numeric sort key for a reported_at that may be str or datetime."""
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _demo_row(fields: dict[str, Any]) -> dict[str, Any]:
    """Fill in the server-managed columns for a stored demo event."""
    now = _utc_now()
    row = dict(fields)
    row["id"] = next(_DEMO_IDS)
    row["status"] = row.get("status") or "open"
    row["created_at"] = now
    row["updated_at"] = now
    for key in ("acknowledged_at", "resolved_at", "closed_at"):
        row.setdefault(key, None)
    for key in ("acknowledged_by", "resolved_by", "resolution_note"):
        row.setdefault(key, None)
    row.setdefault("revision", 1)
    row.setdefault("evidence", [])
    row.setdefault("tags", [])
    return row


def _demo_list(
    city: str | None,
    statuses: tuple[str, ...] | None,
    severities: tuple[str, ...] | None,
    source_type: str | None,
    include_simulated: bool,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    with _DEMO_LOCK:
        rows = [dict(row) for row in _DEMO_EVENTS]
    if city:
        needle = city.lower()
        rows = [r for r in rows if str(r.get("city", "")).lower() == needle]
    if statuses:
        rows = [r for r in rows if r.get("status") in statuses]
    if severities:
        rows = [r for r in rows if r.get("severity") in severities]
    if source_type:
        rows = [r for r in rows if r.get("source_type") == source_type]
    if not include_simulated:
        rows = [r for r in rows if not r.get("is_simulated")]
    rows.sort(
        key=lambda r: (
            _STATUS_ORDER.get(str(r.get("status")), 9),
            -_sort_stamp(r.get("reported_at")),
        )
    )
    return rows[offset:offset + limit]


def _demo_get(event_ref: str) -> dict[str, Any] | None:
    with _DEMO_LOCK:
        for row in _DEMO_EVENTS:
            if row["event_ref"] == event_ref:
                return dict(row)
    return None


def _demo_insert(fields: dict[str, Any]) -> dict[str, Any]:
    with _DEMO_LOCK:
        row = _demo_row(fields)
        _DEMO_EVENTS.append(row)
    _bump_version()
    return dict(row)


def _demo_update(
    event_ref: str, fields: dict[str, Any], expected_revision: int | None
) -> dict[str, Any] | None:
    with _DEMO_LOCK:
        for row in _DEMO_EVENTS:
            if row["event_ref"] != event_ref:
                continue
            if expected_revision is not None and int(row.get("revision", 1)) != int(
                expected_revision
            ):
                return None
            row.update(fields)
            row["revision"] = int(row.get("revision", 1)) + 1
            row["updated_at"] = _utc_now()
            _bump_version()
            return dict(row)
    return None


def _demo_append_timeline(
    event_ref: str,
    action: str,
    from_status: str | None,
    to_status: str | None,
    actor: str | None,
    note: str | None,
) -> None:
    with _DEMO_LOCK:
        _DEMO_TIMELINE.setdefault(event_ref, []).append({
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "actor": actor,
            "note": note,
            "at": _utc_now().isoformat(),
        })


def reset_demo_events() -> None:
    """Clear the in-process demo store (used by tests)."""
    global _DEMO_IDS, _DEMO_SEEDED
    with _DEMO_LOCK:
        _DEMO_EVENTS.clear()
        _DEMO_TIMELINE.clear()
        _DEMO_IDS = itertools.count(1)
        _DEMO_SEEDED = False


_DEMO_SEEDED = False

# Sample events for demo mode (PostgreSQL unreachable). They exist so the
# command centre demos its incident workflow without a database, they are all
# open/in-progress so the acknowledge -> resolve -> close path can be shown, and
# they go through the normal create_event validation like everything else.
_DEMO_SEED_SPECS: tuple[dict[str, Any], ...] = (
    {
        "city_id": "bengaluru",
        "source_type": "incident",
        "category": "flooding",
        "severity": "high",
        "title": "Demo event: waterlogging on the Outer Ring Road",
        "description": (
            "Demo record: repeated citizen reports of waterlogging after "
            "overnight rain. Synthetic sample shown because PostgreSQL is "
            "unreachable — not an official report."
        ),
        "latitude": 12.9352,
        "longitude": 77.6875,
        "location_name": "Outer Ring Road (demo)",
        "tags": ["demo"],
        "evidence": [
            {"kind": "report", "label": "Demo: 6 citizen reports in 40 minutes",
             "value": 6, "unit": "reports", "synthetic": True},
            {"kind": "reading", "label": "Demo: rainfall in the last 3 hours",
             "value": 38.5, "unit": "mm", "synthetic": True},
        ],
    },
    {
        "city_id": "bengaluru",
        "source_type": "transit",
        "category": "transit",
        "severity": "moderate",
        "title": "Demo event: signalling delay on the metro core",
        "description": (
            "Demo record: synthetic signalling delay used to demonstrate the "
            "lifecycle. Not an official transit report."
        ),
        "latitude": 12.9767,
        "longitude": 77.5713,
        "location_name": "Majestic Interchange (demo)",
        "tags": ["demo"],
        "evidence": [
            {"kind": "reading", "label": "Demo: average delay", "value": 9.0,
             "unit": "min", "synthetic": True},
        ],
    },
    {
        "city_id": "delhi",
        "source_type": "air_quality",
        "category": "air_quality",
        "severity": "critical",
        "title": "Demo event: particulate spike over central Delhi",
        "description": (
            "Demo record: synthetic PM2.5 spike used to demonstrate the "
            "lifecycle. Not an official measurement."
        ),
        "latitude": 28.6139,
        "longitude": 77.2090,
        "location_name": "Central Delhi monitoring zone (demo)",
        "tags": ["demo"],
        "evidence": [
            {"kind": "reading", "label": "Demo: PM2.5 (24h)", "value": 205.0,
             "unit": "µg/m³", "synthetic": True},
        ],
    },
)


def ensure_demo_events() -> None:
    """Seed the demo store once so the dashboard is never empty in demo mode."""
    global _DEMO_SEEDED
    if _DEMO_SEEDED or storage_mode() != "demo":
        return
    with _DEMO_LOCK:
        if _DEMO_SEEDED or _DEMO_EVENTS:
            _DEMO_SEEDED = True
            return
        _DEMO_SEEDED = True
    for spec in _DEMO_SEED_SPECS:
        try:
            created = create_event(dict(spec), actor="demo-seed")
            if spec.get("_acknowledge") and created.get("event_ref"):
                transition_event(created["event_ref"], "acknowledge", actor="demo-seed")
        except EventError as exc:  # a bad seed spec must never break the API
            logger.warning("demo event seed skipped: %s", exc)


# ------------------------------------------------------------ serialization

def allowed_actions(status: str) -> list[str]:
    """Action names a client may POST for this status (mirrors the state machine)."""
    return list(STATUS_ACTIONS.get(status, {}).values())


def _age_minutes(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return round((_utc_now() - value).total_seconds() / 60, 1)


def to_public_event(row: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe event payload with the derived fields the UI needs."""
    event = dict(row)
    for key in db.EVENT_TIMESTAMP_COLUMNS:
        if event.get(key) is not None:
            event[key] = utc_iso(event[key])
    status = str(event.get("status") or "open")
    event["status"] = status
    event["is_active"] = status in ACTIVE_STATUSES
    event["allowed_actions"] = allowed_actions(status)
    event["age_minutes"] = _age_minutes(event.get("reported_at"))
    event["is_simulated"] = bool(event.get("is_simulated"))
    event.setdefault("evidence", [])
    event.setdefault("tags", [])
    return event


def _publish(kind: str, event: dict[str, Any]) -> None:
    """Fan out a change notification; never raises."""
    try:
        get_bus().publish({
            "type": kind,
            "event_ref": event.get("event_ref"),
            "city": event.get("city"),
            "city_id": event.get("city_id"),
            "status": event.get("status"),
            "severity": event.get("severity"),
            "revision": event.get("revision"),
            "is_simulated": bool(event.get("is_simulated")),
            "event": event,
        })
    except Exception:  # noqa: BLE001 - real-time is best-effort by design
        logger.exception("realtime publish failed for %s", kind)


def _record_timeline(
    mode: str,
    event: dict[str, Any],
    action: str,
    from_status: str | None,
    to_status: str | None,
    actor: str | None,
    note: str | None,
) -> None:
    """Append to the audit trail (database or demo store)."""
    if mode == "database" and event.get("id") is not None:
        ok, error = db.append_event_timeline(
            int(event["id"]), action, from_status, to_status, actor, note
        )
        if not ok:
            logger.warning("timeline append failed for %s: %s", event.get("event_ref"), error)
    else:
        _demo_append_timeline(
            str(event.get("event_ref")), action, from_status, to_status, actor, note
        )


# ------------------------------------------------------------------- read

def _city_filter(value: str | None) -> str | None:
    """Map a city id (or name) onto the stored display name for filtering."""
    if not value:
        return None
    lowered = value.strip().lower()
    for city in DEMO_CITIES:
        if city["id"].lower() == lowered or city["name"].lower() == lowered:
            return city["name"]
    return value.strip() or None


def list_events(
    *,
    city: str | None = None,
    statuses: tuple[str, ...] | None = None,
    severities: tuple[str, ...] | None = None,
    source_type: str | None = None,
    include_simulated: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Filtered event list, newest-first with active statuses leading."""
    city_name = _city_filter(city)
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    mode = storage_mode()
    if mode == "demo":
        ensure_demo_events()

    if mode == "database":
        ok, rows = db.fetch_civic_events(
            city=city_name,
            statuses=statuses,
            severities=severities,
            source_type=source_type,
            include_simulated=include_simulated,
            limit=limit,
            offset=offset,
        )
        if not ok:
            logger.warning("event list query failed, serving demo: %s", rows)
            mode, rows = "demo", _demo_list(city_name, statuses, severities,
                                            source_type, include_simulated, limit, offset)
    else:
        rows = _demo_list(city_name, statuses, severities, source_type,
                          include_simulated, limit, offset)

    events = [to_public_event(row) for row in rows]
    return {
        "mode": mode,
        "persisted": mode == "database",
        "city": city_name,
        "events": events,
        "count": len(events),
        "filters": {
            "statuses": list(statuses or []),
            "severities": list(severities or []),
            "source_type": source_type,
            "include_simulated": include_simulated,
        },
        "version": event_version(city),
        "note": (
            "Simulated events are included and flagged is_simulated=true."
            if include_simulated
            else "Simulated events are excluded from this view."
        ),
    }


def get_event(event_ref: str, *, include_timeline: bool = True) -> dict[str, Any] | None:
    """One event plus its lifecycle audit trail (None when unknown)."""
    mode = storage_mode()
    row: dict[str, Any] | None
    if mode == "database":
        ok, result = db.fetch_civic_event(event_ref)
        if not ok:
            logger.warning("event lookup failed, serving demo: %s", result)
            mode, row = "demo", _demo_get(event_ref)
        else:
            row = result
    else:
        row = _demo_get(event_ref)

    if row is None:
        return None

    event = to_public_event(row)
    timeline: list[dict[str, Any]] = []
    if include_timeline:
        if mode == "database" and row.get("id") is not None:
            ok, result = db.fetch_event_timeline(int(row["id"]))
            timeline = result if ok else []
        else:
            with _DEMO_LOCK:
                timeline = [dict(item) for item in _DEMO_TIMELINE.get(event_ref, [])]
    event["timeline"] = timeline
    return {"mode": mode, "persisted": mode == "database", "event": event}


def status_breakdown(city: str | None = None) -> dict[str, int]:
    """Counts per status (all statuses always present)."""
    city_name = _city_filter(city)
    counts = {status: 0 for status in EVENT_STATUSES}
    mode = storage_mode()
    if mode == "demo":
        ensure_demo_events()
    else:
        ok, rows = db.count_civic_events_by_status(city_name)
        if ok:
            for status, total in rows.items():
                if status in counts:
                    counts[status] = int(total)
            return counts
        logger.warning("event status counts failed, serving demo: %s", rows)
    for event in _demo_list(city_name, None, None, None, True, 10_000, 0):
        status = str(event.get("status"))
        if status in counts:
            counts[status] += 1
    return counts


_DEMO_VERSION = 0


def _bump_version() -> None:
    """Advance the demo change token (see ``event_version``)."""
    global _DEMO_VERSION
    _DEMO_VERSION += 1


def event_version(city: str | None = None) -> int:
    """Opaque change token; clients compare it to decide whether to resync."""
    if storage_mode() == "database":
        ok, token = db.civic_events_version(_city_filter(city))
        if ok:
            return int(token)
    return _DEMO_VERSION


def create_event(
    payload: dict[str, Any],
    *,
    actor: str | None = None,
    is_simulated: bool | None = None,
    simulation_run_id: str | None = None,
    external_key: str | None = None,
) -> dict[str, Any]:
    """Validate + persist a new civic event and announce it.

    ``external_key`` makes ingestion idempotent: re-submitting the same upstream
    report returns the stored event (``created: False``) instead of duplicating
    it.
    """
    fields = normalize_new_event(payload)
    if is_simulated is not None:
        fields["is_simulated"] = bool(is_simulated)
    if simulation_run_id:
        fields["simulation_run_id"] = simulation_run_id
    if external_key:
        fields["external_key"] = _clean_text(
            external_key, "external_key", max_len=200
        )

    mode = storage_mode()
    if mode == "database":
        ok, result = db.insert_civic_event(fields)
        if not ok:
            raise EventError(
                f"could not persist event: {result}",
                code="storage_error",
                status=503,
            )
        row = result["event"]
        created = bool(result["inserted"])
    else:
        existing = None
        if fields.get("external_key"):
            with _DEMO_LOCK:
                existing = next(
                    (r for r in _DEMO_EVENTS
                     if r.get("external_key") == fields["external_key"]),
                    None,
                )
        row = dict(existing) if existing else _demo_insert(fields)
        created = existing is None

    event = to_public_event(row)
    if created:
        _record_timeline(mode, row, "created", None, event["status"], actor,
                         "Event created")
        _publish("event.created", event)
    return {**event, "created": created}


# ------------------------------------------------------------ update/transition

_UPDATABLE_TEXT_FIELDS = (
    ("title", "title", MAX_TITLE),
    ("description", "description", MAX_DESCRIPTION),
    ("location_name", "location_name", MAX_LOCATION),
    ("resolution_note", "resolution_note", MAX_NOTE),
)


def _collect_updates(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate an editable request body into allow-listed column updates."""
    if not isinstance(payload, dict):
        raise EventError("request body must be a JSON object", code="validation_error")
    if "status" in payload:
        raise EventError(
            "status cannot be set directly; use POST /api/events/<ref>/transition "
            "(or an acknowledge/resolve shortcut) so the audit trail stays intact",
            code="status_immutable",
            status=409,
        )

    fields: dict[str, Any] = {}
    for key, column, max_len in _UPDATABLE_TEXT_FIELDS:
        if key in payload:
            fields[column] = _clean_text(
                payload.get(key), key, max_len=max_len, required=False
            )

    if "severity" in payload:
        severity = str(payload["severity"]).strip().lower()
        if severity not in EVENT_SEVERITIES:
            raise EventError(
                f"severity must be one of {', '.join(EVENT_SEVERITIES)}",
                code="validation_error",
            )
        fields["severity"] = severity

    if "category" in payload:
        category = str(payload["category"]).strip().lower()
        if not CATEGORY_PATTERN.match(category):
            raise EventError(
                "category must be 2-40 chars of lowercase letters, digits, '-' or '_'",
                code="validation_error",
            )
        fields["category"] = category

    if "tags" in payload:
        fields["tags"] = _normalize_tags(payload["tags"])
    if "evidence" in payload:
        fields["evidence"] = _normalize_evidence(payload["evidence"])

    if "latitude" in payload or "longitude" in payload:
        if not ("latitude" in payload and "longitude" in payload):
            raise EventError(
                "latitude and longitude must be updated together",
                code="validation_error",
            )
        fields["latitude"] = _coord(payload["latitude"], "latitude", -90, 90)
        fields["longitude"] = _coord(payload["longitude"], "longitude", -180, 180)

    return fields


def update_event(
    event_ref: str,
    payload: dict[str, Any],
    *,
    actor: str | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Update the descriptive fields of an event (never its status)."""
    fields = _collect_updates(payload)
    if not fields:
        raise EventError("no updatable fields supplied", code="validation_error")

    mode = storage_mode()
    if mode == "database":
        ok, result = db.update_civic_event(event_ref, fields, expected_revision)
        if not ok:
            raise EventError(
                f"could not update event: {result}", code="storage_error", status=503
            )
        if result is None:
            found, existing = db.fetch_civic_event(event_ref)
            if found and existing is None:
                raise EventError("event not found", code="not_found", status=404)
            raise EventError(
                "event changed since it was loaded; reload and retry",
                code="revision_conflict",
                status=409,
            )
        row = result
    else:
        if _demo_get(event_ref) is None:
            raise EventError("event not found", code="not_found", status=404)
        row = _demo_update(event_ref, fields, expected_revision)
        if row is None:
            raise EventError(
                "event changed since it was loaded; reload and retry",
                code="revision_conflict",
                status=409,
            )

    event = to_public_event(row)
    _record_timeline(
        mode, row, "updated", event["status"], event["status"], actor,
        "Updated: " + ", ".join(sorted(fields)),
    )
    _publish("event.updated", event)
    return event




def transition_event(
    event_ref: str,
    action: str,
    *,
    actor: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Move an event through its lifecycle, validating the transition.

    Raises ``EventError`` (HTTP 409) for illegal or no-op transitions so the API
    can never produce a state the frontend cannot explain.
    """
    action = str(action or "").strip().lower()
    if action not in ACTION_TARGET:
        raise EventError(
            f"unknown action '{action}'; expected one of {', '.join(ACTION_TARGET)}",
            code="unknown_action",
        )
    clean_note = (
        _clean_text(note, "note", max_len=MAX_NOTE, required=False) if note else None
    )

    current = get_event(event_ref, include_timeline=False)
    if current is None:
        raise EventError("event not found", code="not_found", status=404)
    mode = str(current["mode"])
    event = current["event"]

    from_status = str(event.get("status"))
    target = ACTION_TARGET[action]
    if target == from_status:
        raise EventError(
            f"event is already '{from_status}'", code="no_op_transition", status=409
        )
    allowed = ALLOWED_TRANSITIONS.get(from_status, ())
    if target not in allowed:
        raise EventError(
            f"cannot {action} an event in status '{from_status}'; allowed next "
            f"statuses: {list(allowed) or 'none (terminal state)'}",
            code="illegal_transition",
            status=409,
        )

    now = _utc_now()
    fields: dict[str, Any] = {"status": target}
    if action == "acknowledge":
        fields["acknowledged_at"] = now
        fields["acknowledged_by"] = actor or "operator"
    elif action == "start":
        if not event.get("acknowledged_at"):
            fields["acknowledged_at"] = now
            fields["acknowledged_by"] = actor or "operator"
    elif action == "resolve":
        fields["resolved_at"] = now
        fields["resolved_by"] = actor or "operator"
        if clean_note:
            fields["resolution_note"] = clean_note
    elif action == "close":
        fields["closed_at"] = now
        if clean_note:
            fields["resolution_note"] = clean_note
    elif action == "reopen":
        # Clear the resolution stamp so a later resolve records a new time; the
        # earlier resolution stays visible in the timeline.
        fields["resolved_at"] = None
        fields["resolved_by"] = None

    expected_revision = int(event.get("revision") or 1)
    if mode == "database":
        ok, result = db.update_civic_event(event_ref, fields, expected_revision)
        if not ok:
            raise EventError(
                f"could not update event: {result}", code="storage_error", status=503
            )
        if result is None:
            raise EventError(
                "event changed while it was being actioned; reload and retry",
                code="revision_conflict",
                status=409,
            )
        row = result
    else:
        row = _demo_update(event_ref, fields, expected_revision)
        if row is None:
            raise EventError(
                "event changed while it was being actioned; reload and retry",
                code="revision_conflict",
                status=409,
            )

    updated = to_public_event(row)
    _record_timeline(
        mode, row, action, from_status, target, actor or "operator", clean_note
    )
    _publish(f"event.{action}", updated)
    return updated
