"""Shared HTTP helpers for providers: timeouts + bounded exponential backoff."""
from __future__ import annotations

import time
import logging

import requests

logger = logging.getLogger("citypulse.providers.http")

DEFAULT_TIMEOUT = 10
MAX_RETRIES = 2          # total attempts = 1 + MAX_RETRIES
BACKOFF_BASE = 1.5       # seconds; grows exponentially


def get_with_retries(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
) -> requests.Response:
    """GET with timeout and bounded exponential backoff on transient errors.

    Retries only on network errors, 429, and 5xx; raises for other statuses
    so callers can surface provider-specific messages.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(
                url, params=params, headers=headers, timeout=timeout
            )
            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_exc = requests.HTTPError(f"{response.status_code} from {url}")
                if attempt < max_retries:
                    delay = BACKOFF_BASE ** (attempt + 1)
                    logger.warning("HTTP %s from %s — retry in %.1fs", response.status_code, url, delay)
                    time.sleep(delay)
                    continue
                response.raise_for_status()
            return response
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = BACKOFF_BASE ** (attempt + 1)
                logger.warning("Network error (%s) — retry in %.1fs", exc.__class__.__name__, delay)
                time.sleep(delay)
                continue
            raise
    raise last_exc if last_exc else RuntimeError("unreachable")
