"""Source adapters: turn an Indicator into normalized Readings.

One interface, many source types (brief §4): `collect(indicator)` routes on
`source_type`. FRED is the primary path; ISM is a best-effort scraper that
falls back gracefully; manual indicators are owned by the DB/seed, so refresh
is a no-op for them.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime

from .fetch import FetchError, fetch
from .models import (
    SOURCE_FRED,
    SOURCE_MANUAL,
    SOURCE_SCRAPE,
    Indicator,
    Reading,
    SeriesSpec,
)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Only chart a few years of history (keeps the DB and charts snappy).
_HISTORY_START = "2018-01-01"


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


def _fred_series(spec: SeriesSpec, ind: Indicator, api_key: str) -> list[Reading]:
    payload = fetch(
        FRED_BASE,
        params={
            "series_id": spec.fred_id,
            "api_key": api_key,
            "file_type": "json",
            "units": spec.transform,
            "observation_start": _HISTORY_START,
            "sort_order": "asc",
        },
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


def collect_scrape(ind: Indicator) -> list[Reading]:
    try:
        html = fetch(ind.source_url)
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
# Router
# ---------------------------------------------------------------------------


def collect(ind: Indicator) -> list[Reading]:
    """Fetch + normalize one indicator. Manual indicators refresh to nothing."""
    if ind.source_type == SOURCE_FRED:
        return collect_fred(ind)
    if ind.source_type == SOURCE_SCRAPE:
        return collect_scrape(ind)
    if ind.source_type == SOURCE_MANUAL:
        return []
    raise ValueError(f"Unknown source_type: {ind.source_type}")
