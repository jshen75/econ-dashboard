"""Deal-agnostic presale parsing helpers for the Warehouse App."""

from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
from typing import Any

from .calculator import RmbsInputs


ANTHROPIC_MODEL = "claude-sonnet-4-6"
PARSER_TOOL_NAME = "emit_presale_extraction"

FIELD_LABELS = {
    "collateral_notional": "Collateral Notional",
    "collateral_summary_notional": "Collateral Summary Notional",
    "wa_coupon_pct": "WA Coupon",
    "term_months": "WA Original Term",
    "seasoning_months": "WA Seasoning",
    "wa_fico": "WA FICO",
    "wa_cltv_pct": "WA CLTV",
    "wa_dscr": "WA DSCR",
    "severity_low_pct": "Severity Low",
    "severity_high_pct": "Severity High",
    "foreclosure_freq_low_pct": "Foreclosure Frequency Low",
    "foreclosure_freq_high_pct": "Foreclosure Frequency High",
}

TRANCHE_SIZE_FIELDS = ["a1_pct", "a1f_pct", "a2_pct", "a3_pct", "m1_pct", "b1a_pct", "b1b_pct", "b2_pct", "b3_pct"]

ASSUMED_DEFAULTS = {
    "cpr_pct": RmbsInputs.cpr_pct,
    "cdr_pct": RmbsInputs.cdr_pct,
    "yield_target_pct": RmbsInputs.yield_target_pct,
    "servicing_fee_pct": RmbsInputs.servicing_fee_pct,
    "admin_fee_pct": RmbsInputs.admin_fee_pct,
    "sofr_pct": RmbsInputs.sofr_pct,
    "spread_pct": RmbsInputs.spread_pct,
    "advance_rate_pct": RmbsInputs.advance_rate_pct,
}


SYSTEM_PROMPT = """
You are an institutional structured-finance presale extraction engine.
Parse any RMBS presale generically. Do not rely on fixed deal values.

First discover the subject transaction from the title/first page and rated transaction sections.
The subject deal is the transaction being rated, not comparison or benchmark deal columns.
In multi-column tables, use only the column whose header matches the discovered subject deal name.
Ignore comparison deals and archetypal-pool columns.

For each sourced value, return value, source_anchor_text, page_hint, and confidence.
If no anchor is found, return null with low confidence. Never guess.

Rules:
- collateral_notional comes from Closing pool balance or a collateral-summary paragraph. Convert million-dollar units to absolute dollars.
- tranche sizing uses Credit enhancement (%) attachment points from the Preliminary Ratings table. Do not sum preliminary amount rows.
- collapse exchangeable, notional, interest-only, first-cashflow, and last-cashflow variants into one representative per credit-enhancement level.
- collateral stats and loss-estimation ranges come from the subject column only.
- SOFR, financing spread, advance rate, CPR, CDR, yield target, fees, and tranche coupons are assumed and must not be sourced.

Return only the requested structured object through the tool.
"""


PRESALE_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["deal_name", "fields", "tranche_attachments", "validation_flags", "assumptions_not_sourced"],
    "properties": {
        "deal_name": {
            "type": "object",
            "additionalProperties": False,
            "required": ["value", "source_anchor_text", "page_hint", "confidence"],
            "properties": {
                "value": {"type": ["string", "null"]},
                "source_anchor_text": {"type": ["string", "null"]},
                "page_hint": {"type": ["string", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
        "fields": {
            "type": "object",
            "additionalProperties": False,
            "required": list(FIELD_LABELS),
            "properties": {
                field: {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["value", "source_anchor_text", "page_hint", "confidence"],
                    "properties": {
                        "value": {"type": ["number", "integer", "string", "null"]},
                        "source_anchor_text": {"type": ["string", "null"]},
                        "page_hint": {"type": ["string", "null"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                }
                for field in FIELD_LABELS
            },
        },
        "tranche_attachments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "class_name",
                    "rating",
                    "credit_enhancement_pct",
                    "is_representative",
                    "collapse_reason",
                    "source_anchor_text",
                    "page_hint",
                    "confidence",
                ],
                "properties": {
                    "class_name": {"type": ["string", "null"]},
                    "rating": {"type": ["string", "null"]},
                    "credit_enhancement_pct": {"type": ["number", "null"]},
                    "is_representative": {"type": "boolean"},
                    "collapse_reason": {"type": ["string", "null"]},
                    "source_anchor_text": {"type": ["string", "null"]},
                    "page_hint": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
        "validation_flags": {"type": "array", "items": {"type": "string"}},
        "assumptions_not_sourced": {"type": "array", "items": {"type": "string"}},
    },
}


def extract_pdf_text(pdf_bytes: bytes, *, max_chars: int = 180_000) -> tuple[str, list[str]]:
    """Extract text with page markers. Returns text and warnings."""
    warnings: list[str] = []
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency check is UI-facing.
        raise RuntimeError("pypdf is not installed. Run `pip install -r requirements.txt`.") from exc

    reader = PdfReader(BytesIO(pdf_bytes))
    chunks = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            chunks.append(f"\n[PAGE {idx}]\n{text}")
    combined = "\n".join(chunks).strip()
    if not combined:
        warnings.append("No embedded PDF text found. This may be a scanned PDF and may require OCR.")
    if len(combined) > max_chars:
        warnings.append(f"Extracted text was truncated to {max_chars:,} characters before LLM parsing.")
        combined = combined[:max_chars]
    return combined, warnings


def parse_presale_with_anthropic(extracted_text: str, api_key: str) -> dict[str, Any]:
    """Call Anthropic with strict tool output. Tests should fake this boundary."""
    try:
        from anthropic import Anthropic
    except ImportError as exc:  # pragma: no cover - dependency check is UI-facing.
        raise RuntimeError("anthropic is not installed. Run `pip install -r requirements.txt`.") from exc

    client = Anthropic(api_key=api_key)
    tool = {
        "name": PARSER_TOOL_NAME,
        "description": "Emit structured subject-deal presale extraction JSON.",
        "input_schema": PRESALE_EXTRACTION_SCHEMA,
        "cache_control": {"type": "ephemeral"},
    }
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=6000,
        temperature=0,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": [{
                "type": "text",
                "text": "Extract the subject-deal fields from this presale text.\n\n" + extracted_text,
            }],
        }],
        tools=[tool],
        tool_choice={"type": "tool", "name": PARSER_TOOL_NAME},
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == PARSER_TOOL_NAME:
            return dict(block.input)
    raise RuntimeError("Anthropic response did not include the expected structured extraction tool output.")


def extracted_field(parsed: dict[str, Any], field: str) -> dict[str, Any]:
    return dict(parsed.get("fields", {}).get(field) or {
        "value": None,
        "source_anchor_text": None,
        "page_hint": None,
        "confidence": 0.0,
    })


def numeric_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(",", "").replace("%", "")
    if not text:
        return None
    multiplier = 1.0
    lowered = text.lower()
    if "billion" in lowered or lowered.endswith("bn"):
        multiplier = 1_000_000_000.0
    elif "million" in lowered or lowered.endswith("mm") or lowered.endswith("mil"):
        multiplier = 1_000_000.0
    for token in ["billion", "million", "bn", "mm", "mil"]:
        text = text.lower().replace(token, "")
    try:
        return float(text.strip()) * multiplier
    except ValueError:
        return None


def compute_ce_gap_sizes(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate CE levels and compute tranche thickness from CE gaps."""
    by_ce: dict[float, dict[str, Any]] = {}
    for item in attachments:
        ce = numeric_value(item.get("credit_enhancement_pct"))
        if ce is None:
            continue
        rounded = round(ce, 6)
        if rounded not in by_ce or item.get("is_representative", True):
            by_ce[rounded] = {**item, "credit_enhancement_pct": ce}
    levels = sorted(by_ce.values(), key=lambda row: float(row["credit_enhancement_pct"]), reverse=True)
    sizes = []
    previous_attachment = 100.0
    for row in levels:
        attachment = float(row["credit_enhancement_pct"])
        thickness = max(previous_attachment - attachment, 0.0)
        sizes.append({
            "class_name": row.get("class_name"),
            "rating": row.get("rating"),
            "attachment_pct": attachment,
            "thickness_pct": thickness,
            "source_anchor_text": row.get("source_anchor_text"),
            "page_hint": row.get("page_hint"),
            "confidence": row.get("confidence", 0.0),
        })
        previous_attachment = attachment
    return sizes


def validation_flags(parsed: dict[str, Any], ce_sizes: list[dict[str, Any]]) -> list[str]:
    flags = list(parsed.get("validation_flags") or [])
    total_size = sum(float(row.get("thickness_pct") or 0) for row in ce_sizes)
    if ce_sizes and abs(total_size - 100.0) > 0.5:
        flags.append(f"Tranche CE-gap sizes sum to {total_size:.2f}%, not ~100%.")

    fields = parsed.get("fields", {})
    notional = numeric_value((fields.get("collateral_notional") or {}).get("value"))
    summary_notional = numeric_value((fields.get("collateral_summary_notional") or {}).get("value"))
    if notional and summary_notional:
        mismatch = abs(notional - summary_notional) / max(notional, summary_notional)
        if mismatch > 0.02:
            flags.append("Collateral notional and collateral-summary notional differ by more than 2%.")

    for field, data in fields.items():
        if data.get("value") is not None and not data.get("source_anchor_text"):
            flags.append(f"{FIELD_LABELS.get(field, field)} has a sourced value but no anchor text.")
        if data.get("value") is None:
            flags.append(f"{FIELD_LABELS.get(field, field)} is missing and needs review.")
        if float(data.get("confidence") or 0) < 0.65:
            flags.append(f"{FIELD_LABELS.get(field, field)} is low confidence.")
    return flags


def extraction_rows(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for field, label in FIELD_LABELS.items():
        data = extracted_field(parsed, field)
        rows.append({
            "field": field,
            "label": label,
            "approved_value": data.get("value"),
            "confidence": data.get("confidence", 0.0),
            "page": data.get("page_hint"),
            "anchor": data.get("source_anchor_text"),
        })
    return rows


def midpoint(low: float | None, high: float | None, fallback: float) -> float:
    if low is not None and high is not None:
        return (low + high) / 2
    if low is not None:
        return low
    if high is not None:
        return high
    return fallback


def build_inputs_from_confirmed(
    confirmed_values: dict[str, Any],
    assumptions: dict[str, float],
    ce_sizes: list[dict[str, Any]],
) -> RmbsInputs:
    defaults = RmbsInputs()
    notional = numeric_value(confirmed_values.get("collateral_notional")) or defaults.deal_balance
    severity_seed = midpoint(
        numeric_value(confirmed_values.get("severity_low_pct")),
        numeric_value(confirmed_values.get("severity_high_pct")),
        defaults.severity_pct,
    )
    tranche_values = {field: 0.0 for field in TRANCHE_SIZE_FIELDS}
    for field, size in zip(TRANCHE_SIZE_FIELDS, ce_sizes):
        tranche_values[field] = float(size.get("thickness_pct") or 0.0)
    return RmbsInputs(
        deal_balance=notional,
        gross_coupon_pct=numeric_value(confirmed_values.get("wa_coupon_pct")) or defaults.gross_coupon_pct,
        term_months=int(numeric_value(confirmed_values.get("term_months")) or defaults.term_months),
        seasoning_months=int(numeric_value(confirmed_values.get("seasoning_months")) or defaults.seasoning_months),
        severity_pct=float(assumptions.get("severity_pct", severity_seed)),
        wa_fico=int(numeric_value(confirmed_values.get("wa_fico")) or defaults.wa_fico),
        wa_cltv_pct=numeric_value(confirmed_values.get("wa_cltv_pct")) or defaults.wa_cltv_pct,
        wa_dscr=numeric_value(confirmed_values.get("wa_dscr")) or defaults.wa_dscr,
        aaa_loss_severity_pct=numeric_value(confirmed_values.get("severity_high_pct")) or defaults.aaa_loss_severity_pct,
        b_loss_severity_pct=numeric_value(confirmed_values.get("severity_low_pct")) or defaults.b_loss_severity_pct,
        aaa_foreclosure_frequency_pct=(
            numeric_value(confirmed_values.get("foreclosure_freq_high_pct"))
            or defaults.aaa_foreclosure_frequency_pct
        ),
        b_foreclosure_frequency_pct=(
            numeric_value(confirmed_values.get("foreclosure_freq_low_pct"))
            or defaults.b_foreclosure_frequency_pct
        ),
        **{key: float(assumptions.get(key, default)) for key, default in ASSUMED_DEFAULTS.items()},
        **tranche_values,
    )


def extraction_summary(parsed: dict[str, Any]) -> dict[str, Any]:
    ce_sizes = compute_ce_gap_sizes(parsed.get("tranche_attachments") or [])
    return {
        "deal_name": (parsed.get("deal_name") or {}).get("value") or "Unknown deal",
        "ce_sizes": ce_sizes,
        "validation_flags": validation_flags(parsed, ce_sizes),
        "assumptions_not_sourced": parsed.get("assumptions_not_sourced") or sorted(ASSUMED_DEFAULTS),
    }
