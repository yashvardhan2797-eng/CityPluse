"""Transit provider: GTFS-Realtime vehicle/service data, or labeled demo.

Honest scope (Phase 2):
- The protocol is documented at https://gtfs.org/realtime/ ; feeds are
  protobuf and every agency publishes its own URL + license. There is no
  universal "free GTFS-RT feed" we can assume for the demo cities, so this
  module:
    1. fetches a configured GTFS-RT VehiclePositions feed if
       TRANSIT_GTFS_RT_URL is set (protobuf via google-transit-realtime),
    2. otherwise returns clearly-labeled synthetic network stats
       (load factor + delay) in the same normalized shape. We do NOT pretend
       static GTFS schedules are live vehicle positions.
"""
from __future__ import annotations

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


def _decode_feed(payload: bytes):
    """Decode a GTFS-RT VehiclePositions protobuf message."""
    try:
        from google.transit import gtfs_realtime_pb2
    except ImportError as exc:  # optional dependency
        raise ProviderError(
            "google-transit-realtime not installed; cannot parse GTFS-RT feed"
        ) from exc
    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(payload)
    except Exception as exc:  # protobuf decode errors
        raise ProviderError(f"GTFS-RT feed decode failed: {exc}") from exc
    return feed


def fetch_live(city_id: str, feed_url: str) -> list[NormalizedObservation]:
    """Fetch vehicle positions from a configured GTFS-RT feed and aggregate."""
    if not feed_url:
        raise ProviderError("TRANSIT_GTFS_RT_URL is not configured")
    city = _city_by_id(city_id)

    try:
        response = requests.get(feed_url, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ProviderError(f"GTFS-RT request failed: {exc}") from exc

    feed = _decode_feed(response.content)
    entities = list(feed.entity)
    if not entities:
        raise ProviderError("GTFS-RT feed contained no entities (may be an empty/off-hours feed)")

    # Aggregate vehicle positions: count + average speed where available.
    # (VehiclePosition fields: position.latitude/longitude/speed, timestamp)
    positions = []
    speeds = []
    for entity in entities:
        vehicle = entity.vehicle
        if vehicle.HasField("position"):
            positions.append((vehicle.position.latitude, vehicle.position.longitude))
            if vehicle.position.speed > 0:
                speeds.append(vehicle.position.speed * 3.6)  # m/s → km/h
    if not positions:
        raise ProviderError("GTFS-RT feed had no vehicle positions with coordinates")

    recorded_at = datetime.now(timezone.utc)
    center_lat = sum(p[0] for p in positions) / len(positions)
    center_lon = sum(p[1] for p in positions) / len(positions)

    observations = [
        NormalizedObservation(
            source_type="transit",
            provider="gtfs-rt",
            source_id=make_source_id("gtfs-rt", city_id, "active-vehicles"),
            city=city["name"],
            city_id=city_id,
            location_name=f"{city['name']} (fleet, from GTFS-RT)",
            latitude=center_lat,
            longitude=center_lon,
            metric="active_vehicles",
            value=float(len(positions)),
            unit="vehicles",
            severity="moderate" if len(positions) < 50 else "low",
            description=f"Live transit: {len(positions)} vehicles reporting positions",
            recorded_at=recorded_at,
            source_url=feed_url,
            metadata={"entity_count": len(entities), "license": "see feed provider"},
        )
    ]
    if speeds:
        avg_speed = sum(speeds) / len(speeds)
        observations.append(
            NormalizedObservation(
                source_type="transit",
                provider="gtfs-rt",
                source_id=make_source_id("gtfs-rt", city_id, "avg-speed"),
                city=city["name"],
                city_id=city_id,
                location_name=f"{city['name']} (fleet, from GTFS-RT)",
                latitude=center_lat,
                longitude=center_lon,
                metric="avg_speed_kmh",
                value=round(avg_speed, 1),
                unit="km/h",
                severity="low",
                description=f"Live transit: average vehicle speed {round(avg_speed, 1)} km/h",
                recorded_at=recorded_at,
                source_url=feed_url,
                metadata={"vehicles_with_speed": len(speeds)},
            )
        )
    return observations


def fetch_demo(city_id: str, bucket=None) -> list[NormalizedObservation]:
    from backend.providers.demo_generators import demo_transit

    return demo_transit(city_id, bucket=bucket)
