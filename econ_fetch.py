"""
econ_fetch.py — standalone reference scraper for the Econ Dashboard.

This is a REFERENCE, not a finished module. It is dependency-free (Python 3.10+
standard library only) so it runs anywhere with zero installs. It demonstrates the
patterns the brief calls for:

    fetch (polite, retrying)  ->  parse/normalize  ->  Reading dataclass

In the real project you'll likely swap urllib for `httpx`/`requests`, add real
parsers per source, and persist Readings to SQLite/Postgres. The shapes here are
meant to match §1 and §4 of ECON_DASHBOARD_BRIEF.md.

Run it:  python3 econ_fetch.py
"""

from __future__ import annotations

import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# 1. Data shapes  (mirror the brief's "every indicator looks like this")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    """One observation for one indicator, normalized for storage/display."""

    indicator_key: str
    release_date: date          # when the agency published this
    value: float | None         # the headline number (e.g. 0.6 for +0.6%)
    unit: str = ""              # "%", "$B", "index", ...
    period: str = ""           # the data period, e.g. "2026-04" or "Q1 2026"
    commentary: str = ""       # short human note / intuition
    raw_snippet: str = ""      # keep the source text so a human can audit the parse


@dataclass(frozen=True)
class Indicator:
    """Static config for one dashboard indicator."""

    key: str
    name: str
    section: str
    cadence: str                # monthly | quarterly | daily | irregular
    intuition: str
    source_url: str
    source_type: str            # html_table | press_release | pdf | api
    parser: "Callable[[str, Indicator], list[Reading]]"


# ---------------------------------------------------------------------------
# 2. Polite, retrying fetch layer  (brief §4)
# ---------------------------------------------------------------------------

# Gov sites are picky. Several (SEC, legislation.gov.uk) REQUIRE a contact email
# in the User-Agent. Put a real address here before pointing this at production.
CONTACT_EMAIL = "you@example.com"
USER_AGENT = f"EconDashboard/1.0 ({CONTACT_EMAIL})"

# Be polite: minimum seconds between requests to the SAME host.
PER_HOST_MIN_INTERVAL_S: dict[str, float] = {
    "www.census.gov": 1.0,
    "www.bls.gov": 1.0,
    "www.bea.gov": 1.0,
    "www.federalreserve.gov": 1.0,
    "home.treasury.gov": 1.0,
    "www.ismworld.org": 2.0,
}
_DEFAULT_MIN_INTERVAL_S = 1.0

RETRIABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
# If any of these appear in the body, treat it as a soft block, not real content.
BLOCK_MARKERS = (b"captcha", b"cloudflare", b"datadome", b"access denied", b"request blocked")

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_RETRIES = 3

_last_hit_by_host: dict[str, float] = {}


class FetchError(Exception):
    """Raised when a URL cannot be fetched cleanly after retries."""


def _respect_host_rate_limit(host: str) -> None:
    """Sleep just enough so we don't hammer a single host."""
    min_interval = PER_HOST_MIN_INTERVAL_S.get(host, _DEFAULT_MIN_INTERVAL_S)
    last = _last_hit_by_host.get(host)
    if last is not None:
        elapsed = time.monotonic() - last
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
    _last_hit_by_host[host] = time.monotonic()


def fetch(url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S,
          max_retries: int = DEFAULT_MAX_RETRIES) -> str:
    """Fetch a URL as text, politely and with retry+backoff. Returns the body."""
    host = urlparse(url).netloc
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml,*/*",
        },
    )

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        _respect_host_rate_limit(host)
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code in RETRIABLE_STATUSES:
                _backoff(attempt)
                continue
            raise FetchError(f"{url} -> HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = exc
            _backoff(attempt)
            continue

        lowered = body.lower()
        if any(marker in lowered for marker in BLOCK_MARKERS):
            # Fail loudly rather than persist garbage (brief §4).
            raise FetchError(f"{url} -> looks blocked (captcha/WAF marker in body)")

        return body.decode("utf-8", errors="replace")

    raise FetchError(f"{url} -> failed after {max_retries} attempts: {last_err}")


def _backoff(attempt: int) -> None:
    """Exponential backoff with jitter: ~0.5s, 1s, 2s, ... plus randomness."""
    delay = (2 ** (attempt - 1)) * 0.5 + random.uniform(0, 0.4)
    time.sleep(delay)


# ---------------------------------------------------------------------------
# 3. Parsers  (one per source_type / source — stubs you fill in per agency)
# ---------------------------------------------------------------------------
#
# Government release formats change, so isolate the fragile bit here. Each parser
# takes the raw page text + the Indicator config and returns normalized Readings.
# Below are two illustrative deterministic parsers + a hook for an LLM parser.


_PCT_NEAR = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*percent", re.IGNORECASE)


def parse_press_release_percent(text: str, ind: Indicator) -> list[Reading]:
    """
    Toy deterministic parser: grab the first 'X percent' figure near a keyword.
    Real version: anchor on the agency's standard sentence ("rose 0.6 percent")
    and pull the period from the headline. Keep the raw snippet for auditing.
    """
    match = _PCT_NEAR.search(text)
    if not match:
        return []
    value = float(match.group(1))
    start = max(0, match.start() - 80)
    snippet = " ".join(text[start:match.end() + 80].split())
    return [
        Reading(
            indicator_key=ind.key,
            release_date=date.today(),
            value=value,
            unit="%",
            period="latest",
            commentary=ind.intuition,
            raw_snippet=snippet,
        )
    ]


def parse_html_table_stub(text: str, ind: Indicator) -> list[Reading]:
    """
    Placeholder for HTML-table sources (Census retail/durable goods, Treasury
    yield curve, Fed G.17). Real version: use html.parser / lxml / pandas.read_html
    to pull the latest row. Returns nothing until implemented.
    """
    return []


def parse_with_llm_stub(text: str, ind: Indicator) -> list[Reading]:
    """
    Optional: hand the release text to an LLM with a strict JSON schema and let it
    extract {period, value, unit, commentary}. More robust to format drift, costs
    money, needs validation. Decide deterministic-vs-LLM per the brief's §5 Q11.
    """
    raise NotImplementedError("Wire up your LLM client + JSON-schema validation here.")


# ---------------------------------------------------------------------------
# 4. Indicator registry  (config-driven, DRY — add rows, not code)
# ---------------------------------------------------------------------------

INDICATORS: list[Indicator] = [
    Indicator(
        key="cpi",
        name="Consumer Price Index (CPI-U)",
        section="Inflation",
        cadence="monthly",
        intuition="Core strips volatile food/energy; shelter is sticky; gates Fed rate path.",
        source_url="https://www.bls.gov/cpi/",
        source_type="press_release",
        parser=parse_press_release_percent,
    ),
    Indicator(
        key="nonfarm_payroll",
        name="Employment Situation (Nonfarm Payrolls)",
        section="Income / Labor",
        cadence="monthly",
        intuition="Payroll growth + low unemployment = income engine for consumption.",
        source_url="https://www.bls.gov/news.release/empsit.nr0.htm",
        source_type="press_release",
        parser=parse_press_release_percent,
    ),
    Indicator(
        key="retail_sales",
        name="Advance Retail Sales",
        section="Demand / Consumption",
        cadence="monthly",
        intuition="Fastest read on consumer demand; volatile, watch revisions.",
        source_url="https://www.census.gov/retail/sales.html",
        source_type="html_table",
        parser=parse_html_table_stub,
    ),
    Indicator(
        key="durable_goods",
        name="Advance Durable Goods Orders",
        section="Demand / Investment",
        cadence="monthly",
        intuition="Proxy for capex appetite; ex-transport & ex-defense are cleaner signals.",
        source_url="https://www.census.gov/manufacturing/m3/adv/current/index.html",
        source_type="html_table",
        parser=parse_html_table_stub,
    ),
    Indicator(
        key="yield_curve",
        name="Daily Treasury Yield Curve",
        section="Rates",
        cadence="daily",
        intuition="Inversion = recession warning; steep long end = growth/inflation expectations.",
        source_url=(
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
            "TextView?type=daily_treasury_yield_curve"
        ),
        source_type="html_table",
        parser=parse_html_table_stub,
    ),
    # ... add GDP, trade balance, PCE, real earnings, industrial production, ISM PMI, PCE price index.
]


# ---------------------------------------------------------------------------
# 5. Orchestration  (fetch -> parse -> collect; persistence is your call)
# ---------------------------------------------------------------------------


def refresh_indicator(ind: Indicator) -> list[Reading]:
    """Fetch + parse one indicator. Never lets one bad source kill the run."""
    try:
        body = fetch(ind.source_url)
    except FetchError as exc:
        print(f"  ! {ind.key}: fetch failed: {exc}")
        return []
    try:
        readings = ind.parser(body, ind)
    except NotImplementedError:
        print(f"  - {ind.key}: parser not implemented yet ({ind.source_type})")
        return []
    except Exception as exc:  # noqa: BLE001 - reference code; log loudly in prod
        print(f"  ! {ind.key}: parse error: {exc}")
        return []
    print(f"  + {ind.key}: {len(readings)} reading(s)")
    return readings


def refresh_all() -> list[Reading]:
    """Refresh every registered indicator. In prod, store these + track revisions."""
    print(f"Refreshing {len(INDICATORS)} indicators at {datetime.now():%Y-%m-%d %H:%M}")
    all_readings: list[Reading] = []
    for ind in INDICATORS:
        all_readings.extend(refresh_indicator(ind))
    return all_readings


if __name__ == "__main__":
    results = refresh_all()
    print(f"\nCollected {len(results)} reading(s).")
    for r in results:
        print(f"  [{r.indicator_key}] {r.value}{r.unit} — {r.raw_snippet[:100]}")
