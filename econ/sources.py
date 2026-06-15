"""Source adapters: turn an Indicator into normalized Readings.

One interface, many source types (brief §4): `collect(indicator)` routes on
`source_type`. FRED handles clean numeric series; scrape handles public pages
that lack APIs; news handles aggregate coverage indexes; manual indicators are
owned by the DB/seed, so refresh is a no-op for them.
"""

from __future__ import annotations

import os
import re
from calendar import month_name
from datetime import date, datetime, timedelta
from html import unescape

from . import store
from .fetch import FetchError, fetch
from .models import (
    SOURCE_FRED,
    SOURCE_MANUAL,
    SOURCE_NEWS,
    SOURCE_SCRAPE,
    Indicator,
    Reading,
    SeriesSpec,
)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
GDELT_DOC_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

# Only chart a few years of history (keeps the DB and charts snappy).
_HISTORY_START = "2018-01-01"
_FRED_REVISION_LOOKBACK_DAYS = {
    "daily": 14,
    "weekly": 35,
    "monthly": 120,
    "quarterly": 450,
}


class MissingApiKey(Exception):
    """Raised when a FRED key is needed but not configured."""


def fred_api_key() -> str | None:
    """Resolve the FRED key from env or Streamlit secrets (either works)."""
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    try:  # optional: only present when running under Streamlit
        import streamlit as st

        return st.secrets.get("FRED_API_KEY")  # type: ignore[no-any-return]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# FRED
# ---------------------------------------------------------------------------


def _fred_observation_start(spec: SeriesSpec, ind: Indicator) -> str:
    latest = store.latest_reading(ind.key, spec.label)
    if latest is None:
        return _HISTORY_START
    lookback_days = _FRED_REVISION_LOOKBACK_DAYS.get(ind.cadence, 120)
    return max(latest.period - timedelta(days=lookback_days),
               date.fromisoformat(_HISTORY_START)).isoformat()


def _fred_series(spec: SeriesSpec, ind: Indicator, api_key: str) -> list[Reading]:
    payload = fetch(
        FRED_BASE,
        params={
            "series_id": spec.fred_id,
            "api_key": api_key,
            "file_type": "json",
            "units": spec.transform,
            "observation_start": _fred_observation_start(spec, ind),
            "sort_order": "asc",
        },
        timeout_s=15,
        expect_json=True,
    )
    readings: list[Reading] = []
    for obs in payload.get("observations", []):
        raw = obs.get("value")
        if raw in (None, ".", ""):
            continue  # FRED uses "." for missing
        try:
            value = float(raw) * spec.scale
        except ValueError:
            continue
        readings.append(
            Reading(
                indicator_key=ind.key,
                series_label=spec.label,
                period=date.fromisoformat(obs["date"]),
                value=round(value, 4),
                unit=spec.unit,
                release_date=date.today(),
                commentary=ind.intuition,
                source=f"fred:{spec.fred_id}",
            )
        )
    return readings


def collect_fred(ind: Indicator) -> list[Reading]:
    api_key = fred_api_key()
    if not api_key:
        raise MissingApiKey(
            "Set FRED_API_KEY (env or .streamlit/secrets.toml). "
            "Get a free key at https://fredaccount.stlouisfed.org/apikeys"
        )
    out: list[Reading] = []
    for spec in ind.series:
        if spec.fred_id:
            out.extend(_fred_series(spec, ind, api_key))
    return out


# ---------------------------------------------------------------------------
# ISM (scrape, best-effort — page is JS/licensed, so this may return nothing
# and the seeded/manual values stand. Fails soft, never stores garbage.)
# ---------------------------------------------------------------------------

_PMI_PATTERNS = {
    "Manufacturing PMI": re.compile(
        r"Manufacturing PMI[^0-9]{0,40}?(\d{2}(?:\.\d)?)\s*percent", re.IGNORECASE),
    "Services PMI": re.compile(
        r"Services?(?:\s+PMI|\s+index)?[^0-9]{0,40}?(\d{2}(?:\.\d)?)\s*percent",
        re.IGNORECASE),
}

_MONTH_BY_NAME = {month_name[i]: i for i in range(1, 13)}


def _plain_lines(html: str) -> list[str]:
    text = re.sub(r"<[^>]+>", "\n", html)
    return [line.strip() for line in unescape(text).splitlines() if line.strip()]


def collect_scrape(ind: Indicator) -> list[Reading]:
    if ind.key == "warn_notices":
        return collect_warn_notices(ind)

    try:
        html = fetch(ind.source_url, timeout_s=8, max_retries=1)
    except FetchError:
        return []  # fail soft; keep whatever is seeded
    text = re.sub(r"<[^>]+>", " ", html)
    out: list[Reading] = []
    for spec in ind.series:
        pat = _PMI_PATTERNS.get(spec.label)
        if not pat:
            continue
        m = pat.search(text)
        if not m:
            continue
        snippet = " ".join(text[max(0, m.start() - 60):m.end() + 20].split())
        out.append(
            Reading(
                indicator_key=ind.key,
                series_label=spec.label,
                period=date.today().replace(day=1),
                value=float(m.group(1)),
                unit=spec.unit,
                release_date=date.today(),
                commentary=ind.intuition,
                raw_snippet=snippet,
                source="scrape:ism",
            )
        )
    return out


# ---------------------------------------------------------------------------
# WARN notices (scrape, fragmented by state)
# ---------------------------------------------------------------------------


def parse_warn_pa_readings(html: str, ind: Indicator) -> list[Reading]:
    """Parse a PA-style WARN page into monthly notice and affected-worker counts."""
    workers_by_period: dict[date, float] = {}
    notices_by_period: dict[date, float] = {}
    current_year: int | None = None
    current_month: int | None = None
    current_employer = ""
    snippets: dict[date, list[str]] = {}

    for line in _plain_lines(html):
        if re.fullmatch(r"20\d{2}", line):
            current_year = int(line)
            current_month = None
            continue
        if line in _MONTH_BY_NAME:
            current_month = _MONTH_BY_NAME[line]
            continue
        if not line.startswith("#") and not line.upper().startswith(("COUNTY:", "AFFECTED:")):
            current_employer = line[:80]

        match = re.search(r"(?:#\s*)?AFFECTED:\s*([0-9,]+)", line, re.IGNORECASE)
        if not match:
            continue
        year = current_year or date.today().year
        month = current_month or date.today().month
        period = date(year, month, 1)
        affected = float(match.group(1).replace(",", ""))
        workers_by_period[period] = workers_by_period.get(period, 0.0) + affected
        notices_by_period[period] = notices_by_period.get(period, 0.0) + 1
        snippets.setdefault(period, []).append(f"{current_employer}: {int(affected):,}")

    readings: list[Reading] = []
    for period in sorted(workers_by_period)[-12:]:
        snippet = " | ".join(snippets.get(period, [])[:5])
        readings.extend([
            Reading(
                indicator_key=ind.key,
                series_label="Affected workers",
                period=period,
                value=workers_by_period[period],
                unit="workers",
                release_date=date.today(),
                commentary=ind.intuition,
                raw_snippet=snippet,
                source="scrape:warn:pa",
            ),
            Reading(
                indicator_key=ind.key,
                series_label="Notice count",
                period=period,
                value=notices_by_period[period],
                unit="notices",
                release_date=date.today(),
                commentary=ind.intuition,
                raw_snippet=snippet,
                source="scrape:warn:pa",
            ),
        ])
    return readings


def collect_warn_notices(ind: Indicator) -> list[Reading]:
    html = fetch(ind.source_url, timeout_s=8, max_retries=1)
    return parse_warn_pa_readings(html, ind)


# ---------------------------------------------------------------------------
# News aggregation (GDELT DOC 2.0 timeline)
# ---------------------------------------------------------------------------


def _parse_gdelt_date(value: str) -> date:
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return date.fromisoformat(value[:10])


def _gdelt_points(payload: dict) -> list[dict]:
    timeline = payload.get("timeline", [])
    points: list[dict] = []
    for item in timeline:
        if isinstance(item, dict) and isinstance(item.get("data"), list):
            points.extend(p for p in item["data"] if isinstance(p, dict))
        elif isinstance(item, dict):
            points.append(item)
    return points


def parse_gdelt_timeline_readings(payload: dict, ind: Indicator) -> list[Reading]:
    by_period: dict[date, dict[str, float]] = {}
    for point in _gdelt_points(payload):
        raw_when = point.get("datetime") or point.get("date")
        if not raw_when:
            continue
        try:
            period = _parse_gdelt_date(str(raw_when))
            count = float(point.get("value", 0) or 0)
            norm = float(point.get("norm", 0) or 0)
        except (TypeError, ValueError):
            continue
        bucket = by_period.setdefault(period, {"count": 0.0, "norm": 0.0})
        bucket["count"] += count
        bucket["norm"] += norm

    readings: list[Reading] = []
    for period in sorted(by_period):
        count = by_period[period]["count"]
        norm_value = by_period[period]["norm"]
        readings.append(
            Reading(
                indicator_key=ind.key,
                series_label="Article count",
                period=period,
                value=count,
                unit="articles",
                release_date=date.today(),
                commentary=ind.intuition,
                raw_snippet=str(by_period[period])[:500],
                source="news:gdelt",
            )
        )
        if norm_value:
            readings.append(
                Reading(
                    indicator_key=ind.key,
                    series_label="Share per 100k articles",
                    period=period,
                    value=count / norm_value * 100_000,
                    unit="per 100k",
                    release_date=date.today(),
                    commentary=ind.intuition,
                    raw_snippet=str(by_period[period])[:500],
                    source="news:gdelt",
                )
            )
    return readings


def collect_news(ind: Indicator) -> list[Reading]:
    query = (
        '(immigration OR migrant OR asylum OR deportation OR "border policy")'
    )
    payload = fetch(
        GDELT_DOC_BASE,
        params={
            "query": query,
            "mode": "timelinevolraw",
            "format": "json",
            "timespan": "1week",
        },
        timeout_s=5,
        max_retries=1,
        expect_json=True,
    )
    return parse_gdelt_timeline_readings(payload, ind)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def collect(ind: Indicator) -> list[Reading]:
    """Fetch + normalize one indicator. Manual indicators refresh to nothing."""
    if ind.source_type == SOURCE_FRED:
        return collect_fred(ind)
    if ind.source_type == SOURCE_SCRAPE:
        return collect_scrape(ind)
    if ind.source_type == SOURCE_NEWS:
        return collect_news(ind)
    if ind.source_type == SOURCE_MANUAL:
        return []
    raise ValueError(f"Unknown source_type: {ind.source_type}")
