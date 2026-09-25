"""Civic incidents provider: city open-data feeds, or labeled demo.

Honest scope (Phase 2):
- 311-style open-data portals differ per city (Socrata, CKAN, custom).
  There is no single universal API we can assume, so this module provides a
  documented Socrata-style client (used when INCIDENTS_SOCRATA_URL and a
  dataset are configured) and otherwise returns clearly-labeled synthetic
  incident reports.
- Socrata example (documented pattern): GET {resource}.json?$where=...&
  $limit=..&$order=created_date DESC — column names vary per dataset and
  must be mapped in INCIDENTS_FIELD_MAP (JSON env var).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import requests

from backend.demo_data import DEMO_CITIES
from backend.providers.base import (
    NormalizedObservation,
    ProviderError,
    make_source_id,
)

TIMEOUT_SECONDS = 12


def _city_by_id(city_id: str):
    return next(c for c in DEMO_CITIES if c["id"] == city_id)


def fetch_live(
    city_id: str,
    socrata_url: str,
    field_map: dict[str, str] | None = None,
    limit: int = 50,
) -> list[NormalizedObservation]:
    """Fetch recent incident reports from a Socrata-style open-data endpoint.

    field_map maps our fields to the dataset's columns, e.g.
      {"created": "created_date", "category": "category",
       "latitude": "latitude", "longitude": "longitude", "description": "descriptor"}
    """
    if not socrata_url:
        raise ProviderError("INCIDENTS_SOCRATA_URL is not configured")
    city = _city_by_id(city_id)
    fmap = field_map or {}
    required = ["latitude", "longitude", "created"]
    missing = [f for f in required if f not in fmap]
    if missing:
        raise ProviderError(
            f"INCIDENTS_FIELD_MAP missing keys: {missing} (dataset columns vary; map them in .env)"
        )

    params = {
        "$limit": limit,
        "$order": f"{fmap['created']} DESC",
    }
    try:
        response = requests.get(socrata_url, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        rows = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(f"Incidents feed request failed: {exc}") from exc

    observations: list[NormalizedObservation] = []
    for i, row in enumerate(rows[:limit]):
        try:
            lat = float(row[fmap["latitude"]])
            lon = float(row[fmap["longitude"]])
        except (KeyError, TypeError, ValueError):
            continue  # skip rows without coordinates rather than guessing
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        raw_created = row.get(fmap["created"])
        try:
            recorded_at = datetime.fromisoformat(str(raw_created).replace("Z", "+00:00"))
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            recorded_at = datetime.now(timezone.utc)
        category = str(row.get(fmap.get("category", ""), "report"))[:60]
        description = str(row.get(fmap.get("description", ""), ""))[:200]

        observations.append(
            NormalizedObservation(
                source_type="incident",
                provider="city-open-data",
                source_id=make_source_id("city-open-data", city_id, i, recorded_at.isoformat()),
                city=city["name"],
                city_id=city_id,
                location_name=f"{city['name']} area #{i + 1}",
                latitude=lat,
                longitude=lon,
                metric="incident_count",
                value=1,
                unit="count",
                severity="moderate",
                description=f"Live incident ({category}): {description}" if description else f"Live incident ({category})",
                recorded_at=recorded_at,
                source_url=socrata_url,
                metadata={"category": category},
            )
        )
    if not observations:
        raise ProviderError("Incidents feed returned no usable rows")
    return observations


def fetch_demo(city_id: str, bucket=None) -> list[NormalizedObservation]:
    from backend.providers.demo_generators import demo_incidents

    return demo_incidents(city_id, bucket=bucket)
