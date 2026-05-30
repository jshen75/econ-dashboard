"""Polite, retrying HTTP layer (brief §4).

Distilled from econ_fetch.py but using httpx. One fetch interface for every
source: per-host rate limiting, retry+backoff on transient failures, a real
User-Agent with a contact email, and loud failure on captcha/WAF blocks.
"""

from __future__ import annotations

import os
import random
import time
from urllib.parse import urlparse

import httpx

# Several gov endpoints want a contact email in the UA. Override via env.
CONTACT_EMAIL = os.environ.get("ECON_CONTACT_EMAIL", "you@example.com")
USER_AGENT = f"EconDashboard/1.0 ({CONTACT_EMAIL})"

# Minimum seconds between requests to the SAME host (be polite to .gov).
PER_HOST_MIN_INTERVAL_S: dict[str, float] = {
    "api.stlouisfed.org": 0.4,
    "www.census.gov": 1.0,
    "www.bls.gov": 1.0,
    "www.bea.gov": 1.0,
    "www.federalreserve.gov": 1.0,
    "home.treasury.gov": 1.0,
    "www.ismworld.org": 2.0,
}
_DEFAULT_MIN_INTERVAL_S = 1.0

RETRIABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
BLOCK_MARKERS = ("captcha", "datadome", "access denied", "request blocked")

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_RETRIES = 3

_last_hit_by_host: dict[str, float] = {}


class FetchError(Exception):
    """Raised when a URL cannot be fetched cleanly after retries."""


def _respect_host_rate_limit(host: str) -> None:
    min_interval = PER_HOST_MIN_INTERVAL_S.get(host, _DEFAULT_MIN_INTERVAL_S)
    last = _last_hit_by_host.get(host)
    if last is not None:
        elapsed = time.monotonic() - last
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
    _last_hit_by_host[host] = time.monotonic()


def _backoff(attempt: int) -> None:
    """Exponential backoff with jitter: ~0.5s, 1s, 2s, ... plus randomness."""
    time.sleep((2 ** (attempt - 1)) * 0.5 + random.uniform(0, 0.4))


def fetch(url: str, *, params: dict | None = None,
          timeout_s: float = DEFAULT_TIMEOUT_S,
          max_retries: int = DEFAULT_MAX_RETRIES,
          expect_json: bool = False):
    """Fetch a URL politely with retry+backoff.

    Returns parsed JSON if expect_json else the response text. Raises FetchError
    on hard failures or detected blocks.
    """
    host = urlparse(url).netloc
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json" if expect_json
        else "text/html,application/xhtml+xml,application/xml,*/*",
    }

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        _respect_host_rate_limit(host)
        try:
            resp = httpx.get(url, params=params, headers=headers,
                             timeout=timeout_s, follow_redirects=True)
        except httpx.HTTPError as exc:
            last_err = exc
            _backoff(attempt)
            continue

        if resp.status_code in RETRIABLE_STATUSES:
            last_err = httpx.HTTPStatusError(
                f"HTTP {resp.status_code}", request=resp.request, response=resp)
            _backoff(attempt)
            continue
        if resp.status_code >= 400:
            raise FetchError(f"{url} -> HTTP {resp.status_code}")

        lowered = resp.text.lower()
        if any(marker in lowered for marker in BLOCK_MARKERS):
            raise FetchError(f"{url} -> looks blocked (captcha/WAF marker in body)")

        return resp.json() if expect_json else resp.text

    raise FetchError(f"{url} -> failed after {max_retries} attempts: {last_err}")
