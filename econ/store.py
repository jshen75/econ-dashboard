"""Persistence with revision tracking (brief §4).

Government data revises constantly, so we never silently overwrite: when a new
fetch reports a different value for a period we already have, we keep the old
number in `prior_value` so the UI can show "revised from X to Y".

One reading is keyed by (indicator_key, series_label, period). Local runs use
SQLite by default; deploys can switch to Postgres/Neon by setting DATABASE_URL
or POSTGRES_URL in the environment or Streamlit secrets.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from .models import Reading

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "econ.db"
DATABASE_URL_NAMES = ("DATABASE_URL", "POSTGRES_URL", "NEON_DATABASE_URL")

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
    "key" TEXT PRIMARY KEY,
    value TEXT
);
"""


def _secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:  # optional: only present when running under Streamlit
        import streamlit as st

        secret_value = st.secrets.get(name)
        return str(secret_value) if secret_value else None
    except Exception:
        return None


def database_url() -> str | None:
    """Return a Postgres connection URL when one is configured."""
    for name in DATABASE_URL_NAMES:
        value = _secret(name)
        if value:
            return value
    return None


def backend_name() -> str:
    """Human-readable storage backend name for status/debug output."""
    return "postgres" if database_url() else "sqlite"


def _sqlite_path() -> Path:
    return Path(os.environ.get("ECON_SQLITE_PATH", DEFAULT_DB_PATH))


def _is_postgres() -> bool:
    return database_url() is not None


def _placeholder() -> str:
    return "%s" if _is_postgres() else "?"


@contextmanager
def _connect() -> Iterator[Any]:
    url = database_url()
    if url:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on deploy env
            raise RuntimeError(
                "Postgres is configured, but psycopg is not installed. "
                "Run `pip install -r requirements.txt`."
            ) from exc

        conn = psycopg.connect(url, row_factory=dict_row)
    else:
        conn = sqlite3.connect(_sqlite_path())
        conn.row_factory = sqlite3.Row

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        if _is_postgres():
            for statement in _schema_statements():
                conn.execute(statement)
        else:
            conn.executescript(_SCHEMA)


def _schema_statements() -> list[str]:
    return [s.strip() for s in _SCHEMA.split(";") if s.strip()]


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def upsert_readings(readings: Iterable[Reading]) -> dict[str, int]:
    """Insert/update readings. Returns counts of new vs. revised rows.

    Revision rule: if a row already exists for (key, series, period) and the new
    value differs, move the old value into prior_value before updating.
    """
    stats = {"new": 0, "revised": 0, "unchanged": 0}
    now = datetime.now().isoformat(timespec="seconds")
    ph = _placeholder()
    with _connect() as conn:
        for r in readings:
            existing = conn.execute(
                f"SELECT value FROM readings WHERE indicator_key={ph} AND "
                f"series_label={ph} AND period={ph}",
                (r.indicator_key, r.series_label, _iso(r.period)),
            ).fetchone()

            prior = r.prior_value
            if existing is None:
                stats["new"] += 1
            elif _value(existing, "value") != r.value:
                prior = _value(existing, "value")  # record the revision
                stats["revised"] += 1
            else:
                stats["unchanged"] += 1

            conn.execute(
                f"""
                INSERT INTO readings (indicator_key, series_label, period, value,
                    unit, release_date, commentary, raw_snippet, source,
                    prior_value, fetched_at)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
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
    ph = _placeholder()
    sql = f"SELECT * FROM readings WHERE indicator_key={ph}"
    args: list = [indicator_key]
    if series_label is not None:
        sql += f" AND series_label={ph}"
        args.append(series_label)
    sql += " ORDER BY period ASC"
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_reading(row) for row in rows]


def latest_reading(indicator_key: str, series_label: str) -> Reading | None:
    ph = _placeholder()
    with _connect() as conn:
        row = conn.execute(
            f"SELECT * FROM readings WHERE indicator_key={ph} AND series_label={ph} "
            "ORDER BY period DESC LIMIT 1",
            (indicator_key, series_label),
        ).fetchone()
    return _row_to_reading(row) if row else None


def _value(row: Any, key: str) -> Any:
    return row[key]


def _date_from_value(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _row_to_reading(row: Any) -> Reading:
    return Reading(
        indicator_key=_value(row, "indicator_key"),
        series_label=_value(row, "series_label"),
        period=_date_from_value(_value(row, "period")),
        value=_value(row, "value"),
        unit=_value(row, "unit") or "",
        release_date=_date_from_value(_value(row, "release_date")),
        commentary=_value(row, "commentary") or "",
        raw_snippet=_value(row, "raw_snippet") or "",
        source=_value(row, "source") or "",
        prior_value=_value(row, "prior_value"),
    )


def set_meta(key: str, value: str) -> None:
    ph = _placeholder()
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO meta (\"key\", value) VALUES ({ph},{ph}) "
            "ON CONFLICT(\"key\") DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_meta(key: str) -> str | None:
    ph = _placeholder()
    with _connect() as conn:
        row = conn.execute(f"SELECT value FROM meta WHERE \"key\"={ph}", (key,)).fetchone()
    return _value(row, "value") if row else None
