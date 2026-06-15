"""Orchestration: fetch -> normalize -> store, for one or all indicators.

Never lets one bad source kill the whole run (brief §4). Returns a per-indicator
status so the UI can show what updated, what was revised, and what failed.
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter

from . import sources, store
from .indicators import INDICATORS
from .models import Indicator


def refresh_indicator(ind: Indicator) -> dict:
    """Refresh one indicator; returns a status dict (never raises)."""
    started = perf_counter()
    try:
        readings = sources.collect(ind)
    except sources.MissingApiKey as exc:
        return _result(ind.key, "no_key", str(exc), {}, started)
    except Exception as exc:  # noqa: BLE001 - log loudly, keep the run alive
        return _result(ind.key, "error", str(exc), {}, started)

    if not readings:
        note = "manual / seeded" if ind.source_type == "manual" else "no data parsed"
        return _result(ind.key, "skipped", note, {}, started)

    counts = store.upsert_readings(readings)
    return _result(ind.key, "ok", "", counts, started)


def _result(key: str, status: str, detail: str, counts: dict, started: float) -> dict:
    return {
        "key": key,
        "status": status,
        "detail": detail,
        "counts": counts,
        "seconds": round(perf_counter() - started, 2),
    }


def refresh_all() -> dict:
    """Refresh every indicator. Returns a run summary for the UI."""
    return refresh_many(INDICATORS)


def refresh_many(indicators: list[Indicator]) -> dict:
    """Refresh selected indicators. Returns a run summary for the UI."""
    store.init_db()
    results = [refresh_indicator(ind) for ind in indicators]
    now = datetime.now().isoformat(timespec="seconds")
    store.set_meta("last_refresh", now)
    return {
        "ran_at": now,
        "results": results,
        "ok": sum(r["status"] == "ok" for r in results),
        "revised": sum(r["counts"].get("revised", 0) for r in results),
        "new": sum(r["counts"].get("new", 0) for r in results),
        "errors": [r for r in results if r["status"] in ("error", "no_key")],
    }


if __name__ == "__main__":
    summary = refresh_all()
    print(f"Refreshed at {summary['ran_at']}: {summary['ok']} ok, "
          f"{summary['new']} new, {summary['revised']} revised.")
    for r in summary["results"]:
        line = f"  {r['status']:>8}  {r['key']}"
        if r["counts"]:
            line += f"  {r['counts']}"
        if r["detail"]:
            line += f"  — {r['detail'][:60]}"
        print(line)
