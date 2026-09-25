"""Flask-compatible real-time updates: Server-Sent Events (SSE).

Why SSE and not Flask-SocketIO
------------------------------
* Flask-SocketIO requires an async worker (eventlet/gevent) or its threading
  mode plus a client library. SSE needs neither, so it adds **zero** new
  dependencies and keeps the existing deployment (`python app.py`, or any
  WSGI server) working unchanged.
* CityPulse only needs server -> browser push. Operator actions (acknowledge,
  resolve, close, simulation runs) are ordinary REST POSTs, which keeps the
  REST API as the primary and fully-functional interface.
* `text/event-stream` streams through the Vite dev proxy and WSGI servers
  natively, so no extra proxy configuration is required.

Correctness guarantees
----------------------
* Every published message carries a monotonic ``notification_id``. Clients
  de-duplicate on it, so a reconnect, a replayed message, or a polling
  fallback running alongside the stream can never produce a duplicate alert.
* Each subscriber owns a bounded queue; a slow or abandoned client is dropped
  instead of blocking ingestion — memory stays constant.
* ``publish`` never raises. Real-time delivery is an enhancement layered on
  top of the REST API, never a dependency of the write path.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from datetime import datetime, timezone
from typing import Any, Iterator

logger = logging.getLogger("citypulse.realtime")

MAX_QUEUE_PER_SUBSCRIBER = 256
RECENT_HISTORY = 64          # notifications kept for catch-up after reconnect
DEFAULT_HEARTBEAT_SECONDS = 20


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventBus:
    """In-process fan-out of change notifications to SSE subscribers."""

    def __init__(self, max_queue: int = MAX_QUEUE_PER_SUBSCRIBER) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, queue.Queue] = {}
        self._next_subscriber_id = 0
        self._last_notification_id = 0
        self._history: list[dict[str, Any]] = []
        self._max_queue = max_queue

    # ------------------------------------------------------------ publishing
    def publish(self, message: dict[str, Any]) -> int:
        """Broadcast a message to every subscriber; returns its notification id.

        Never raises: a delivery problem must not fail the HTTP request that
        produced the change.
        """
        try:
            with self._lock:
                self._last_notification_id += 1
                envelope = {
                    **message,
                    "notification_id": self._last_notification_id,
                    "published_at": _utc_iso(),
                }
                self._history.append(envelope)
                if len(self._history) > RECENT_HISTORY:
                    del self._history[:-RECENT_HISTORY]
                subscribers = list(self._subscribers.values())

            for sub in subscribers:
                try:
                    sub.put_nowait(envelope)
                except queue.Full:
                    # Slow client: drop the oldest item and keep the newest, so
                    # the client still resyncs once it catches up.
                    try:
                        sub.get_nowait()
                        sub.put_nowait(envelope)
                    except (queue.Empty, queue.Full):
                        logger.debug("dropped notification for a saturated subscriber")
            return envelope["notification_id"]
        except Exception:  # noqa: BLE001 - never break the request path
            logger.exception("publish failed")
            return -1

    def since(self, notification_id: int) -> list[dict[str, Any]]:
        """Notifications newer than ``notification_id`` (polling fallback)."""
        with self._lock:
            return [
                item for item in self._history
                if item["notification_id"] > notification_id
            ]


    # ----------------------------------------------------------- subscribing
    def subscribe(self) -> tuple[int, queue.Queue]:
        with self._lock:
            self._next_subscriber_id += 1
            subscriber_id = self._next_subscriber_id
            channel: queue.Queue = queue.Queue(maxsize=self._max_queue)
            self._subscribers[subscriber_id] = channel
        logger.debug("SSE subscriber %s connected (%d active)",
                     subscriber_id, self.subscriber_count())
        return subscriber_id, channel

    def unsubscribe(self, subscriber_id: int) -> None:
        with self._lock:
            self._subscribers.pop(subscriber_id, None)
        logger.debug("SSE subscriber %s disconnected (%d active)",
                     subscriber_id, self.subscriber_count())

    # ------------------------------------------------------------ diagnostics
    @property
    def last_notification_id(self) -> int:
        with self._lock:
            return self._last_notification_id

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def stats(self) -> dict[str, Any]:
        return {
            "transport": "sse",
            "subscribers": self.subscriber_count(),
            "last_notification_id": self.last_notification_id,
        }


_BUS = EventBus()


def get_bus() -> EventBus:
    """Process-wide bus shared by every request thread."""
    return _BUS


def reset_bus() -> None:
    """Replace the process-wide bus (used by tests to isolate state)."""
    global _BUS
    _BUS = EventBus()


# --------------------------------------------------------------- SSE helpers

def format_sse(message: dict[str, Any], event: str | None = None) -> str:
    """Serialize one SSE frame (`event:` is optional; clients read `data:`)."""
    payload = json.dumps(message, default=str, separators=(",", ":"))
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {payload}\n\n"


def stream(
    subscriber_id: int,
    channel: queue.Queue,
    heartbeat_seconds: int = DEFAULT_HEARTBEAT_SECONDS,
    max_seconds: int | None = None,
) -> Iterator[str]:
    """Yield SSE frames for one subscriber until the client disconnects.

    Emits a comment heartbeat when idle so intermediary proxies keep the
    connection open and the browser notices a dead stream quickly.
    """
    import time

    started = time.monotonic()
    try:
        while max_seconds is None or (time.monotonic() - started) < max_seconds:
            try:
                item = channel.get(timeout=max(1, heartbeat_seconds))
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield format_sse(item, event=str(item.get("type", "message")))
    except GeneratorExit:  # client closed the tab / navigated away
        return
    finally:
        get_bus().unsubscribe(subscriber_id)
