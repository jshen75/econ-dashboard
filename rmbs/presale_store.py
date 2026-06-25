"""Persistence for Warehouse App presale parse memory."""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from econ.store import _connect, _placeholder, backend_name


_SCHEMA = """
CREATE TABLE IF NOT EXISTS warehouse_presale_parses (
    id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    deal_name TEXT NOT NULL,
    raw_extraction_json TEXT NOT NULL,
    confirmed_inputs_json TEXT NOT NULL,
    computed_metrics_json TEXT NOT NULL,
    validation_flags_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def init_presale_store() -> None:
    with _connect() as conn:
        conn.execute(_SCHEMA)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return json_safe(value.item())
    return str(value)


def upsert_presale_parse(
    *,
    parse_id: str,
    file_name: str,
    file_sha256: str,
    deal_name: str,
    raw_extraction: dict[str, Any],
    confirmed_inputs: dict[str, Any],
    computed_metrics: dict[str, Any],
    validation_flags: list[str],
) -> None:
    init_presale_store()
    ph = _placeholder()
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            f"""
            INSERT INTO warehouse_presale_parses (
                id, file_name, file_sha256, deal_name, raw_extraction_json,
                confirmed_inputs_json, computed_metrics_json,
                validation_flags_json, created_at
            )
            VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
            ON CONFLICT(id) DO UPDATE SET
                file_name=excluded.file_name,
                file_sha256=excluded.file_sha256,
                deal_name=excluded.deal_name,
                raw_extraction_json=excluded.raw_extraction_json,
                confirmed_inputs_json=excluded.confirmed_inputs_json,
                computed_metrics_json=excluded.computed_metrics_json,
                validation_flags_json=excluded.validation_flags_json
            """,
            (
                parse_id,
                file_name,
                file_sha256,
                deal_name,
                json.dumps(json_safe(raw_extraction), sort_keys=True),
                json.dumps(json_safe(confirmed_inputs), sort_keys=True),
                json.dumps(json_safe(computed_metrics), sort_keys=True),
                json.dumps(json_safe(validation_flags), sort_keys=True),
                now,
            ),
        )


def recent_presale_parses(limit: int = 5) -> list[dict[str, Any]]:
    init_presale_store()
    safe_limit = max(1, min(int(limit), 25))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, file_name, file_sha256, deal_name, confirmed_inputs_json, "
            "computed_metrics_json, validation_flags_json, created_at "
            f"FROM warehouse_presale_parses ORDER BY created_at DESC LIMIT {safe_limit}"
        ).fetchall()
    return [summarize_parse_row(dict(row)) for row in rows]


def get_presale_parse(parse_id: str) -> dict[str, Any] | None:
    init_presale_store()
    ph = _placeholder()
    with _connect() as conn:
        row = conn.execute(
            f"SELECT * FROM warehouse_presale_parses WHERE id={ph}",
            (parse_id,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["raw_extraction"] = json.loads(data.pop("raw_extraction_json"))
    data["confirmed_inputs"] = json.loads(data.pop("confirmed_inputs_json"))
    data["computed_metrics"] = json.loads(data.pop("computed_metrics_json"))
    data["validation_flags"] = json.loads(data.pop("validation_flags_json"))
    return data


def summarize_parse_row(row: dict[str, Any]) -> dict[str, Any]:
    confirmed = json.loads(row.pop("confirmed_inputs_json", "{}") or "{}")
    metrics = json.loads(row.pop("computed_metrics_json", "{}") or "{}")
    flags = json.loads(row.pop("validation_flags_json", "[]") or "[]")
    inputs = confirmed.get("inputs") or {}
    return {
        **row,
        "deal_balance": inputs.get("deal_balance"),
        "wa_coupon_pct": inputs.get("gross_coupon_pct"),
        "advance_rate_pct": inputs.get("advance_rate_pct"),
        "warehouse_return": metrics.get("Facility Rate"),
        "equity_irr_levered": metrics.get("Scenario A Equity IRR - Levered"),
        "validation_flags": "; ".join(flags),
    }


def presale_store_backend_name() -> str:
    return backend_name()
