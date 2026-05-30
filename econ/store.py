"""SQLite persistence with revision tracking (brief §4).

Government data revises constantly, so we never silently overwrite: when a new
fetch reports a different value for a period we already have, we keep the old
number in `prior_value` so the UI can show "revised from X to Y".

One reading is keyed by (indicator_key, series_label, period). Plain stdlib
sqlite3 — no ORM needed for a single-user dashboard.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path

from .models import Reading

DB_PATH = Path(__file__).resolve().parent.parent / "econ.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    indicator_key TEXT NOT NULL,
    series_label  TEXT NOT NULL,
    period        TEXT NOT NULL,          -- ISO date of the data period
    value         REAL,
    unit          TEXT DEFAULT '',
    release_date  TEXT,
    commentary    TEXT DEFAULT '',
    raw_snippet   TEXT DEFAULT '',
    source        TEXT DEFAULT '',
    prior_value   REAL,                    -- previous value if revised
    fetched_at    TEXT NOT NULL,
    PRIMARY KEY (indicator_key, series_label, period)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def upsert_readings(readings: Iterable[Reading]) -> dict[str, int]:
    """Insert/update readings. Returns counts of new vs. revised rows.

    Revision rule: if a row already exists for (key, series, period) and the new
    value differs, move the old value into prior_value before updating.
    """
    stats = {"new": 0, "revised": 0, "unchanged": 0}
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        for r in readings:
            existing = conn.execute(
                "SELECT value FROM readings WHERE indicator_key=? AND "
                "series_label=? AND period=?",
                (r.indicator_key, r.series_label, _iso(r.period)),
            ).fetchone()

            prior = r.prior_value
            if existing is None:
                stats["new"] += 1
            elif existing["value"] != r.value:
                prior = existing["value"]  # record the revision
                stats["revised"] += 1
            else:
                stats["unchanged"] += 1

            conn.execute(
                """
                INSERT INTO readings (indicator_key, series_label, period, value,
                    unit, release_date, commentary, raw_snippet, source,
                    prior_value, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(indicator_key, series_label, period) DO UPDATE SET
                    value=excluded.value, unit=excluded.unit,
                    release_date=excluded.release_date,
                    commentary=excluded.commentary,
                    raw_snippet=excluded.raw_snippet, source=excluded.source,
                    prior_value=excluded.prior_value, fetched_at=excluded.fetched_at
                """,
                (r.indicator_key, r.series_label, _iso(r.period), r.value, r.unit,
                 _iso(r.release_date), r.commentary, r.raw_snippet, r.source,
                 prior, now),
            )
    return stats


def get_readings(indicator_key: str, series_label: str | None = None) -> list[Reading]:
    """Return readings for an indicator (optionally one series), oldest first."""
    sql = "SELECT * FROM readings WHERE indicator_key=?"
    args: list = [indicator_key]
    if series_label is not None:
        sql += " AND series_label=?"
        args.append(series_label)
    sql += " ORDER BY period ASC"
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_reading(row) for row in rows]


def latest_reading(indicator_key: str, series_label: str) -> Reading | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM readings WHERE indicator_key=? AND series_label=? "
            "ORDER BY period DESC LIMIT 1",
            (indicator_key, series_label),
        ).fetchone()
    return _row_to_reading(row) if row else None


def _row_to_reading(row: sqlite3.Row) -> Reading:
    return Reading(
        indicator_key=row["indicator_key"],
        series_label=row["series_label"],
        period=date.fromisoformat(row["period"]),
        value=row["value"],
        unit=row["unit"] or "",
        release_date=date.fromisoformat(row["release_date"]) if row["release_date"] else None,
        commentary=row["commentary"] or "",
        raw_snippet=row["raw_snippet"] or "",
        source=row["source"] or "",
        prior_value=row["prior_value"],
    )


def set_meta(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_meta(key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None
