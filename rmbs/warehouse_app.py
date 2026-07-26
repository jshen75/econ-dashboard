"""Warehouse App UI: upload presale, confirm extraction, compute warehouse analysis."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict
from uuid import uuid4
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from mortgage.page import default_input_text, parse_input_value

from .calculator import RmbsInputs, project_rmbs_waterfall, rate
from .page import (
    advance_optimization,
    build_results_object,
    build_warehouse_excel_download,
    inject_rmbs_css,
    render_scenario_a_equity_summary,
    render_scenario_a_visual_grid,
    render_warehouse_metric_blocks,
    render_warehouse_tables,
    smm,
    mdr,
    pct_text,
)
from .presale_parser import (
    ASSUMED_DEFAULTS,
    build_inputs_from_confirmed,
    extract_pdf_text,
    extraction_rows,
    extraction_summary,
    midpoint,
    nuance_rows,
    numeric_value,
    parse_presale_with_anthropic,
)
from .presale_store import (
    get_presale_parse,
    recent_presale_parses,
    upsert_presale_parse,
)


def anthropic_api_key() -> tuple[str | None, str | None]:
    try:
        value = st.secrets.get("ANTHROPIC_API_KEY")
        return (str(value), None) if value else (None, None)
    except Exception as exc:
        return None, str(exc)


def hydrate_latest_saved_parse() -> None:
    if st.session_state.get("warehouse_app_extraction"):
        return
    if st.session_state.get("warehouse_app_auto_hydrate_attempted"):
        return
    st.session_state.warehouse_app_auto_hydrate_attempted = True
    try:
        rows = recent_presale_parses(limit=1)
    except Exception as exc:
        st.warning(f"Could not load latest saved parse: {exc}")
        return
    if rows:
        load_saved_parse(str(rows[0]["id"]))


def render_saved_parse_selector() -> None:
    try:
        rows = recent_presale_parses(limit=25)
    except Exception as exc:
        st.warning(f"Could not load previous parses: {exc}")
        return

    options = [""] + [str(row["id"]) for row in rows]
    row_by_id = {str(row["id"]): row for row in rows}

    def label_for(parse_id: str) -> str:
        if not parse_id:
            return "Select a previous parsed presale"
        row = row_by_id[parse_id]
        return row.get("deal_name") or "Unknown deal"

    current_parse_id = str(st.session_state.get("warehouse_app_parse_id") or "")
    pending_parse_id = str(st.session_state.get("warehouse_app_pending_selector_parse_id") or "")
    selector_key = "warehouse-app-previous-parse-selector"
    if pending_parse_id and pending_parse_id in options:
        st.session_state[selector_key] = pending_parse_id
        current_parse_id = pending_parse_id
        st.session_state.warehouse_app_pending_selector_parse_id = None
    selected_index = options.index(current_parse_id) if current_parse_id in options else 0
    selected = st.selectbox(
        "Previous Parsed Presales",
        options,
        index=selected_index,
        format_func=label_for,
        key=selector_key,
    )
    if selected and selected != current_parse_id:
        load_saved_parse(selected)
        st.rerun()
    if not rows:
        st.caption("No previous parses found yet.")


def load_saved_parse(parse_id: str) -> None:
    saved = get_presale_parse(parse_id)
    if not saved:
        st.warning("Saved parse was not found.")
        return
    st.session_state.warehouse_app_parse_id = saved["id"]
    st.session_state.warehouse_app_loaded_parse_id = saved["id"]
    st.session_state.warehouse_app_file_name = saved["file_name"]
    st.session_state.warehouse_app_file_sha256 = saved["file_sha256"]
    st.session_state.warehouse_app_extraction = saved["raw_extraction"]
    st.session_state.warehouse_app_saved_parse_id = saved["id"]
    run_key = safe_file_slug(str(saved["id"]))[:12]
    st.session_state[f"warehouse_app_confirmed_rows_{run_key}"] = (
        saved.get("confirmed_inputs", {}).get("confirmed_rows") or extraction_rows(saved["raw_extraction"])
    )
    initialize_nuance_snapshot(saved["raw_extraction"], f"warehouse_app_confirmed_rows_{run_key}", force=True)
    saved_inputs = dict(saved.get("confirmed_inputs", {}).get("inputs") or {})
    saved_summary = extraction_summary(saved["raw_extraction"])
    debt_seed = debt_tranche_pct(saved_summary["ce_sizes"])
    if debt_seed:
        saved_inputs["advance_rate_pct"] = debt_seed
    initialize_assumption_state(run_key, saved_inputs, force=True)
    st.session_state.warehouse_app_loaded_parse_label = f"{saved['deal_name']} - {saved['created_at']}"


def render_warehouse_app_page() -> None:
    inject_rmbs_css()
    inject_warehouse_app_css()
    hydrate_latest_saved_parse()
    st.title("Risk Engine")

    render_saved_parse_selector()

    upload_col, status_col = st.columns([2, 1])
    with upload_col:
        uploaded = st.file_uploader("Presale PDF", type=["pdf"], key="warehouse-app-presale")
    with status_col:
        api_key, secret_error = anthropic_api_key()
        st.markdown("<div class='warehouse-parse-button-spacer'></div>", unsafe_allow_html=True)
        parse_clicked = st.button(
            "Parse Presale",
            type="primary",
            use_container_width=True,
            disabled=uploaded is None or bool(secret_error) or not api_key,
            key="warehouse-app-parse-button",
        )
    if secret_error:
        st.error(
            "Streamlit could not parse `.streamlit/secrets.toml`. Put the key in quotes, for example:\n\n"
            '```toml\nANTHROPIC_API_KEY = "sk-ant-..."\n```'
        )

    if uploaded and parse_clicked:
        parse_uploaded_presale(uploaded.name, uploaded.getvalue())

    parsed = st.session_state.get("warehouse_app_extraction")
    if not parsed:
        return

    summary = extraction_summary(parsed)
    run_key = warehouse_app_run_key(parsed, summary)
    confirmed_key = f"warehouse_app_confirmed_rows_{run_key}"
    initialize_nuance_snapshot(parsed, confirmed_key)
    render_extraction_review(parsed, summary, confirmed_key, run_key)
    inputs = render_confirmed_inputs(parsed, summary, confirmed_key, run_key)

    schedule, tranche_summary, metrics = project_rmbs_waterfall(inputs)
    results = build_results_object(inputs, schedule, tranche_summary, metrics)
    benchmarks = warehouse_app_loss_benchmarks(inputs)
    safety_threshold = severe_benchmark_threshold(benchmarks)
    advance_df, optima = advance_optimization(inputs, safety_threshold=safety_threshold)
    persist_parse_memory(parsed, summary, inputs, metrics, confirmed_key)

    analysis_tab, workbook_tab = st.tabs(["Analysis Layer", "Workbook Layer"])
    confirmed_values = confirmed_values_for_sensitivity(parsed, confirmed_key)
    with analysis_tab:
        render_warehouse_metric_blocks(inputs, metrics)
        render_warehouse_sensitivity_tables(inputs, confirmed_values)
        render_scenario_a_equity_summary(inputs, results)
        render_scenario_a_visual_grid(inputs, results, advance_df, optima, key_prefix=f"warehouse-app-{run_key}")
    with workbook_tab:
        render_warehouse_tables(schedule)
        st.download_button(
            "Download Scenario A Workbook",
            data=build_warehouse_excel_download(inputs, schedule, metrics),
            file_name=f"{safe_file_slug(summary['deal_name'])}_warehouse_app.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key=f"{run_key}-warehouse-app-download",
        )


def parse_uploaded_presale(file_name: str, pdf_bytes: bytes) -> None:
    api_key, secret_error = anthropic_api_key()
    if secret_error:
        st.error(
            "Fix `.streamlit/secrets.toml` before parsing. The API key must be quoted:\n\n"
            '```toml\nANTHROPIC_API_KEY = "sk-ant-..."\n```'
        )
        return
    if not api_key:
        st.error("Missing `ANTHROPIC_API_KEY` in Streamlit secrets.")
        return
    try:
        with st.spinner("Extracting PDF text..."):
            extracted_text, warnings = extract_pdf_text(pdf_bytes)
        for warning in warnings:
            st.warning(warning)
        if not extracted_text.strip():
            return
        with st.spinner("Parsing presale with Claude Sonnet 4.6..."):
            parsed = parse_presale_with_anthropic(extracted_text, str(api_key))
        parse_id = str(uuid4())
        st.session_state.warehouse_app_parse_id = parse_id
        st.session_state.warehouse_app_pending_selector_parse_id = parse_id
        st.session_state.warehouse_app_file_name = file_name
        st.session_state.warehouse_app_file_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        st.session_state.warehouse_app_extraction = parsed
        st.session_state.warehouse_app_saved_parse_id = None
        st.session_state.warehouse_app_loaded_parse_id = None
        st.session_state.warehouse_app_loaded_parse_label = None
        for key in list(st.session_state):
            if str(key).startswith("warehouse_app_confirmed_rows_"):
                del st.session_state[key]
                continue
            if str(key).endswith("_nuance_snapshot"):
                del st.session_state[key]
                continue
            if str(key).endswith("__assumption_raw") or str(key).endswith("__assumption_widget"):
                del st.session_state[key]
        initialize_nuance_snapshot(parsed, f"warehouse_app_confirmed_rows_{safe_file_slug(parse_id)[:12]}", force=True)
        st.success("Presale parsed. Review extracted fields below.")
    except Exception as exc:  # UI boundary: show provider/parser errors without crashing app.
        detail = str(exc)
        if parser_credit_error(detail):
            st.error("Presale parsing failed: not enough parser credits. Please reach out to admin for more credits.")
        else:
            st.error(f"Presale parsing failed: {exc}")


def parser_credit_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "credit",
            "quota",
            "insufficient_quota",
            "billing",
            "payment required",
            "balance",
            "overloaded_error",
            "rate_limit",
            "rate limit",
        )
    )


def warehouse_app_run_key(parsed: dict[str, Any], summary: dict[str, Any]) -> str:
    parse_id = st.session_state.get("warehouse_app_parse_id")
    if parse_id:
        return safe_file_slug(str(parse_id))[:12]
    deal_name = str(summary.get("deal_name") or parsed.get("deal_name", {}).get("value") or "warehouse-app")
    return safe_file_slug(deal_name)


def safe_file_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return slug or "warehouse_app"


def inject_warehouse_app_css() -> None:
    st.markdown(
        """
        <style>
          div[data-testid="stFileUploaderDropzoneInstructions"] {
            display: none !important;
          }
          .warehouse-parse-button-spacer {
            height: 36px;
          }
          .warehouse-review-flags {
            margin: 4px 0 0 18px;
            padding: 0;
            font-size: 13px;
            line-height: 1.35;
          }
          .warehouse-review-flags li {
            margin: 7px 0;
            padding-left: 4px;
          }
          .warehouse-assumption-label {
            font-size: 18px;
            font-weight: 700;
            color: #263244;
            margin: 0 0 5px;
            line-height: 1.1;
            white-space: nowrap;
          }
          .warehouse-assumption-note {
            color: #667085;
            font-size: 14px;
            margin: -2px 0 12px;
            line-height: 1.15;
          }
          div[data-testid="stTextInput"] {
            margin-bottom: 0;
          }
          div[data-testid="stTextInput"] input {
            min-height: 38px;
            height: 38px;
            border: 0;
            border-bottom: 1px solid #d7deea;
            border-radius: 0;
            background: transparent;
            color: #174ea6;
            font-weight: 700;
            font-size: 21px;
            text-align: right;
            box-shadow: none;
            padding: 2px 2px 3px;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def warehouse_app_loss_benchmarks(inputs: RmbsInputs) -> dict[str, float]:
    low = float(inputs.b_foreclosure_frequency_pct or 0)
    high = float(inputs.aaa_foreclosure_frequency_pct or 0)
    if low > 0 and high > 0:
        if high < low:
            low, high = high, low
        return {
            "Low FF": low,
            "Mid FF": (low + high) / 2,
            "High FF": high,
        }
    return {"Haircut": max(0.0, 100 - inputs.advance_rate_pct)}


def severe_benchmark_threshold(benchmarks: dict[str, float]) -> float:
    return max(benchmarks.values()) if benchmarks else 0.0


def render_extraction_review(
    parsed: dict[str, Any],
    summary: dict[str, Any],
    confirmed_key: str,
    run_key: str,
) -> None:
    st.metric("Deal Name", summary["deal_name"])

    render_review_details(parsed, summary, confirmed_key)

    source_rows = st.session_state.get(confirmed_key) or extraction_rows(parsed)
    review_col, ce_col = st.columns([1.25, 1])
    with review_col:
        st.markdown("**Pulled Headline Values**")
        rows = field_review_display_df(source_rows)
        edited = st.data_editor(
            rows,
            hide_index=True,
            use_container_width=True,
            disabled=["Label", "Page", "Verified"],
            column_config={
                "Label": st.column_config.TextColumn("Field"),
                "approved_value": st.column_config.TextColumn("Approved Value"),
                "Page": st.column_config.TextColumn("Page"),
                "Verified": st.column_config.TextColumn("Verified"),
            },
            key=f"{run_key}-warehouse-app-field-review",
        )
    confirmed_rows = merge_field_review_edits(source_rows, edited.to_dict("records"))
    st.session_state[confirmed_key] = confirmed_rows

    with ce_col:
        if summary["ce_sizes"]:
            render_tranche_thickness_chart(summary["ce_sizes"], run_key)

    require_manual_sourced_inputs(confirmed_rows, confirmed_key, run_key)


def render_review_details(parsed: dict[str, Any], summary: dict[str, Any], confirmed_key: str) -> None:
    flags = list(summary["validation_flags"])
    nuance_df = nuance_review_display_df(parsed, confirmed_key)
    flag_count = len(flags)
    nuance_count = int(nuance_df["Verified"].eq("✅").sum()) if not nuance_df.empty else 0
    if flag_count:
        st.warning(f"{flag_count} review flags. Open Review Details for parser notes and nuanced presale fields.")
    else:
        st.success("Headline fields parsed. Open Review Details for nuanced presale fields.")

    with st.expander("Review Details - parser flags, ranges, triggers, and fee nuances", expanded=False):
        if flags:
            st.markdown("**Parser Flags**")
            st.markdown(review_flags_html(flags), unsafe_allow_html=True)
        else:
            st.caption("No parser flags.")
        st.markdown(f"**Nuanced Parsed Fields ({nuance_count} of {len(nuance_df)} verified)**")
        st.dataframe(nuance_df, use_container_width=True, hide_index=True)


def review_flags_html(flags: list[str]) -> str:
    items = []
    for flag in flags:
        subject, detail = readable_review_flag(flag)
        if subject:
            message = f"<strong>{html.escape(subject)}</strong> {html.escape(detail)}"
        else:
            message = html.escape(detail)
        items.append(f"<li>{message}</li>")
    return f"<ol class='warehouse-review-flags'>{''.join(items)}</ol>"


def readable_review_flag(flag: str) -> tuple[str, str]:
    cleaned = str(flag).strip()
    for label in sorted(set(ALL_REVIEW_FLAG_LABELS), key=len, reverse=True):
        if cleaned.startswith(label):
            detail = cleaned[len(label):].strip()
            detail = detail[0].lower() + detail[1:] if detail else ""
            return label, detail
    if ":" in cleaned:
        subject, detail = cleaned.split(":", 1)
        return humanize_flag_subject(subject), detail.strip()
    if " and " in cleaned and " differ " in cleaned:
        subject, detail = cleaned.split(" differ ", 1)
        return humanize_flag_subject(subject), f"differ {detail}"
    subject = infer_review_flag_subject(cleaned)
    if subject:
        detail = re.sub(re.escape(subject), "", cleaned, count=1, flags=re.IGNORECASE).strip()
        detail = detail[0].lower() + detail[1:] if detail else ""
        return subject, detail
    return "", cleaned


ALL_REVIEW_FLAG_LABELS = [
    "Collateral notional",
    "Collateral Summary Notional",
    "Collateral Notional",
    "Tranche CE-gap sizes",
    "WA Original Term",
    "WA Coupon",
    "WA Seasoning",
    "WA FICO",
    "WA CLTV",
    "WA DSCR",
    "Severity Low",
    "Severity High",
    "Foreclosure Frequency Low",
    "Foreclosure Frequency High",
    "Prepayment Low",
    "Prepayment High",
    "Cumulative Loss Trigger",
    "Delinquency Trigger",
    "Servicing Fee",
]


def humanize_flag_subject(value: str) -> str:
    text = str(value).strip().replace("_", " ")
    return " ".join(part.capitalize() for part in text.split())


def infer_review_flag_subject(flag: str) -> str:
    lowered = flag.lower()
    subjects = {
        "severity": "Severity",
        "foreclosure": "Foreclosure Frequency",
        "prepayment": "Prepayment",
        "servicing": "Servicing Fee",
        "coupon": "WA Coupon",
        "fico": "WA FICO",
        "cltv": "WA CLTV",
        "dscr": "WA DSCR",
        "seasoning": "WA Seasoning",
        "term": "WA Original Term",
        "tranche": "Tranche CE-gap sizes",
        "collateral": "Collateral Notional",
    }
    for token, subject in subjects.items():
        if token in lowered:
            return subject
    return ""


def nuance_review_display_df(parsed: dict[str, Any], stable_key: str | None = None) -> pd.DataFrame:
    stable_values = stable_nuance_values(parsed, stable_key) if stable_key else nuance_values(parsed)
    rows = []
    for row in nuance_rows(parsed):
        value = stable_values.get(row["field"], row.get("value"))
        anchor = row.get("anchor")
        if row["field"] in {"prepayment_low_pct", "prepayment_high_pct"} and numeric_value(row.get("value")) is None:
            anchor = "Model fallback when presale CPR range is unavailable"
        rows.append(nuance_display_row(
            str(row.get("field") or ""),
            str(row.get("label") or ""),
            {
                "value": value,
                "page_hint": row.get("page"),
                "source_anchor_text": anchor,
            },
            category="Nuanced",
        ))
    return pd.DataFrame(rows, dtype=object)


def nuance_display_row(field: str, label: str, data: dict[str, Any], category: str) -> dict[str, str]:
    value = data.get("value")
    return {
        "Label": label,
        "Value": "" if value is None else str(value),
        "Page": str(data.get("page_hint") or ""),
        "Verified": "✅" if numeric_value(value) is not None else "",
        "Evidence": str(data.get("source_anchor_text") or ""),
    }


def field_review_display_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Label": str(row.get("label") or ""),
            "approved_value": "" if row.get("approved_value") is None else str(row.get("approved_value")),
            "Page": str(row.get("page") or ""),
            "Verified": "✅" if numeric_value(row.get("approved_value")) is not None else "",
        }
        for row in rows
        if row.get("field") != "collateral_summary_notional"
    ], dtype=object)


def merge_field_review_edits(source_rows: list[dict[str, Any]], display_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = []
    display_iter = iter(display_rows)
    for source in source_rows:
        updated = dict(source)
        if source.get("field") != "collateral_summary_notional":
            display = next(display_iter, {})
            updated["approved_value"] = display.get("approved_value")
        merged.append(updated)
    return merged


def missing_sourced_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if row.get("field") != "collateral_summary_notional"
        and not str(row.get("field") or "").startswith("headline_metric_")
        and numeric_value(row.get("approved_value")) is None
    ]


def confirmed_values_for_sensitivity(parsed: dict[str, Any], confirmed_key: str) -> dict[str, Any]:
    confirmed_rows = st.session_state.get(confirmed_key) or extraction_rows(parsed)
    values = {row["field"]: row.get("approved_value") for row in confirmed_rows}
    values.update(stable_nuance_values(parsed, confirmed_key))
    return values


def initialize_nuance_snapshot(parsed: dict[str, Any], stable_key: str, *, force: bool = False) -> None:
    snapshot_key = f"{stable_key}_nuance_snapshot"
    if not force and snapshot_key in st.session_state:
        return
    snapshot = {}
    for row in nuance_rows(parsed):
        field = row["field"]
        value = row.get("value")
        if field == "prepayment_low_pct" and numeric_value(value) is None:
            value = 4.0
        elif field == "prepayment_high_pct" and numeric_value(value) is None:
            value = 12.0
        snapshot[field] = value
    st.session_state[snapshot_key] = snapshot


def stable_nuance_values(parsed: dict[str, Any], stable_key: str | None) -> dict[str, Any]:
    if not stable_key:
        return nuance_values(parsed)
    initialize_nuance_snapshot(parsed, stable_key)
    return dict(st.session_state.get(f"{stable_key}_nuance_snapshot") or {})


SENSITIVITY_METRICS = {
    "Levered Equity IRR": {
        "key": "Scenario A Equity IRR - Levered",
        "kind": "return_pct",
        "subtitle": "Annualized Scenario A sponsor residual IRR after warehouse debt service",
    },
    "Collateral WAL": {
        "key": "Collateral WAL",
        "kind": "years",
        "subtitle": "Weighted-average collateral principal repayment life",
    },
    "Cumulative Net Loss": {
        "key": "Cumulative Net Loss %",
        "kind": "loss_pct",
        "subtitle": "Lifetime net loss as a percentage of collateral notional",
    },
    "Facility WAL": {
        "key": "Facility WAL",
        "kind": "years",
        "subtitle": "Weighted-average facility paydown life",
    },
    "Lender Loss": {
        "key": "Facility / Lender Loss %",
        "kind": "loss_pct",
        "subtitle": "Modeled facility interest shortfall as a percentage of initial facility notional",
    },
    "Leverage Pickup": {
        "key": "Scenario A Leverage Premium",
        "kind": "return_pct",
        "subtitle": "Levered Equity IRR minus Unlevered Equity IRR; positive means warehouse leverage is accretive",
    },
}


CREDIT_SENSITIVITY_METRICS = [
    "Levered Equity IRR",
    "Cumulative Net Loss",
    "Facility WAL",
    "Collateral WAL",
]
FINANCING_SENSITIVITY_METRICS = [
    "Levered Equity IRR",
    "Facility WAL",
    "Lender Loss",
    "Leverage Pickup",
]
SPEED_SENSITIVITY_METRICS = [
    "Levered Equity IRR",
    "Facility WAL",
    "Collateral WAL",
    "Cumulative Net Loss",
]


def render_warehouse_sensitivity_tables(inputs: RmbsInputs, confirmed: dict[str, Any] | None = None) -> None:
    st.markdown("### Stress Sensitivity")
    c1, c2 = st.columns(2)
    with c1:
        credit_metric = st.selectbox(
            "Credit stress output",
            CREDIT_SENSITIVITY_METRICS,
            index=0,
            key="warehouse-app-credit-stress-output",
        )
        credit_df = cdr_severity_sensitivity_table(inputs, credit_metric, confirmed)
        st.markdown(sensitivity_table_html(
            "Credit Stress",
            "",
            credit_df,
            nearest_axis_label(credit_df.index, inputs.cdr_pct),
            nearest_axis_label(credit_df.columns, inputs.severity_pct),
            credit_metric,
            "CDR",
            "Severity",
        ), unsafe_allow_html=True)
    with c2:
        financing_metric = st.selectbox(
            "Financing stress output",
            FINANCING_SENSITIVITY_METRICS,
            index=0,
            key="warehouse-app-financing-stress-output",
        )
        financing_df = advance_spread_sensitivity_table(inputs, financing_metric)
        st.markdown(sensitivity_table_html(
            "Financing Stress",
            "",
            financing_df,
            nearest_axis_label(financing_df.index, inputs.advance_rate_pct),
            nearest_axis_label(financing_df.columns, inputs.spread_pct),
            financing_metric,
            "Advance Rate",
            "Spread",
        ), unsafe_allow_html=True)
    _left, center, _right = st.columns([0.25, 0.5, 0.25])
    with center:
        speed_metric = st.selectbox(
            "Prepayment / speed stress output",
            SPEED_SENSITIVITY_METRICS,
            index=0,
            key="warehouse-app-speed-stress-output",
        )
        speed_df = cpr_cdr_sensitivity_table(inputs, speed_metric, confirmed)
        st.markdown(sensitivity_table_html(
            "Prepayment / Speed Stress",
            "",
            speed_df,
            nearest_axis_label(speed_df.index, inputs.cdr_pct),
            nearest_axis_label(speed_df.columns, inputs.cpr_pct),
            speed_metric,
            "CDR",
            "CPR",
        ), unsafe_allow_html=True)


def cdr_severity_equity_irr_table(inputs: RmbsInputs) -> pd.DataFrame:
    return cdr_severity_sensitivity_table(inputs, "Levered Equity IRR")


def cdr_severity_sensitivity_table(
    inputs: RmbsInputs,
    metric_name: str,
    confirmed: dict[str, Any] | None = None,
) -> pd.DataFrame:
    confirmed = confirmed or {}
    cdr_values = stress_axis_values(
        confirmed.get("foreclosure_freq_low_pct"),
        confirmed.get("foreclosure_freq_high_pct"),
        inputs.cdr_pct,
        [0.25, 0.50, 1.0, 2.0, 3.0],
    )
    severity_values = stress_axis_values(
        confirmed.get("severity_low_pct"),
        confirmed.get("severity_high_pct"),
        inputs.severity_pct,
        [25.0, 35.0, 45.0, 55.0, 65.0],
    )
    rows: list[list[float]] = []
    for cdr in cdr_values:
        row = []
        for severity in severity_values:
            scenario = RmbsInputs(**{**asdict(inputs), "cdr_pct": cdr, "severity_pct": severity})
            _schedule, _summary, metrics = project_rmbs_waterfall(scenario)
            row.append(sensitivity_metric_value(metrics, metric_name, scenario))
        rows.append(row)
    return pd.DataFrame(
        rows,
        index=[pct_axis_label(value) for value in cdr_values],
        columns=[pct_axis_label(value) for value in severity_values],
    )


def advance_spread_equity_irr_table(inputs: RmbsInputs) -> pd.DataFrame:
    return advance_spread_sensitivity_table(inputs, "Levered Equity IRR")


def advance_spread_sensitivity_table(inputs: RmbsInputs, metric_name: str) -> pd.DataFrame:
    advance_values = stress_axis_values(78.0, 92.0, inputs.advance_rate_pct, [78.0, 92.0])
    spread_values = stress_axis_values(
        max(inputs.spread_pct - 1.0, 0.0),
        inputs.spread_pct + 1.0,
        inputs.spread_pct,
        [max(inputs.spread_pct - 1.0, 0.0), inputs.spread_pct + 1.0],
    )
    rows: list[list[float]] = []
    for advance in advance_values:
        row = []
        for spread in spread_values:
            scenario = RmbsInputs(**{**asdict(inputs), "advance_rate_pct": advance, "spread_pct": spread})
            _schedule, _summary, metrics = project_rmbs_waterfall(scenario)
            row.append(sensitivity_metric_value(metrics, metric_name, scenario))
        rows.append(row)
    return pd.DataFrame(
        rows,
        index=[pct_axis_label(value) for value in advance_values],
        columns=[pct_axis_label(value) for value in spread_values],
    )


def cpr_cdr_sensitivity_table(
    inputs: RmbsInputs,
    metric_name: str,
    confirmed: dict[str, Any] | None = None,
) -> pd.DataFrame:
    confirmed = confirmed or {}
    cdr_values = stress_axis_values(
        confirmed.get("foreclosure_freq_low_pct"),
        confirmed.get("foreclosure_freq_high_pct"),
        inputs.cdr_pct,
        [0.25, 0.50, 1.0, 2.0, 3.0],
    )
    cpr_values = stress_axis_values(
        confirmed.get("prepayment_low_pct"),
        confirmed.get("prepayment_high_pct"),
        inputs.cpr_pct,
        [4.0, 6.0, 8.0, 10.0, 12.0],
    )
    rows: list[list[float]] = []
    for cdr in cdr_values:
        row = []
        for cpr in cpr_values:
            scenario = RmbsInputs(**{**asdict(inputs), "cdr_pct": cdr, "cpr_pct": cpr})
            _schedule, _summary, metrics = project_rmbs_waterfall(scenario)
            row.append(sensitivity_metric_value(metrics, metric_name, scenario))
        rows.append(row)
    return pd.DataFrame(
        rows,
        index=[pct_axis_label(value) for value in cdr_values],
        columns=[pct_axis_label(value) for value in cpr_values],
    )


def stress_axis_values(
    low: Any,
    high: Any,
    current: float,
    fallback_values: list[float],
    *,
    points: int = 5,
) -> list[float]:
    low_value = numeric_value(low)
    high_value = numeric_value(high)
    if low_value is not None and high_value is not None and abs(high_value - low_value) > 0.00001:
        lo, hi = sorted([float(low_value), float(high_value)])
        current_value = float(current)
        if lo <= current_value <= hi:
            return [round(value, 2) for value in evenly_spaced_axis(lo, hi, points)]
        edge_low = min(lo, current_value)
        edge_high = max(hi, current_value)
        return [round(value, 2) for value in evenly_spaced_axis(edge_low, edge_high, points)]
    elif low_value is not None or high_value is not None:
        center = float(low_value if low_value is not None else high_value)
        width = max(abs(center) * 0.5, 1.0)
        lo = max(min(center, float(current)) - width, 0.0)
        hi = max(center, float(current)) + width
    else:
        fallback_numeric = [float(value) for value in fallback_values if numeric_value(value) is not None]
        lo = min(fallback_numeric + [float(current)])
        hi = max(fallback_numeric + [float(current)])
    if abs(hi - lo) < 0.00001:
        hi = lo + 1.0
    return [round(value, 2) for value in evenly_spaced_axis(max(lo, 0.0), max(hi, 0.0), points)]


def evenly_spaced_axis(low: float, high: float, points: int) -> list[float]:
    if points <= 1:
        return [low]
    step = (high - low) / (points - 1)
    return [low + step * idx for idx in range(points)]


def nearest_axis_label(values: pd.Index, current: float) -> str:
    current_value = float(current)
    best_label = min(values, key=lambda label: abs((numeric_value(label) or 0.0) - current_value))
    return str(best_label)


def pct_axis_label(value: float) -> str:
    return f"{round(float(value), 2):g}%"


def sensitivity_metric_value(metrics: dict[str, float], metric_name: str, inputs: RmbsInputs) -> float:
    config = SENSITIVITY_METRICS[metric_name]
    value = float(metrics[str(config["key"])])
    if str(config["kind"]).endswith("_pct"):
        return value * 100
    return value


def sensitivity_table_html(
    title: str,
    subtitle: str,
    df: pd.DataFrame,
    base_row: str,
    base_col: str,
    metric_name: str,
    row_axis_label: str,
    col_axis_label: str,
) -> str:
    metric_kind = str(SENSITIVITY_METRICS[metric_name]["kind"])
    flat_values = [float(value) for value in df.to_numpy().ravel()]
    min_value = min(flat_values) if flat_values else 0.0
    max_value = max(flat_values) if flat_values else 0.0
    col_span = len(df.columns) + 1
    header_rows = [
        f"<tr><th class='axis-spacer'></th><th class='x-axis-label' colspan='{col_span}'>{html.escape(col_axis_label)}</th></tr>"
    ]
    header_cells = ["<th class='axis-spacer'></th>", "<th></th>"]
    for column in df.columns:
        header_cells.append(f"<th>{html.escape(str(column))}</th>")
    header_rows.append(f"<tr>{''.join(header_cells)}</tr>")
    body_rows = []
    for row_idx, (index, row) in enumerate(df.iterrows()):
        cells = []
        if row_idx == 0:
            cells.append(
                f"<th class='y-axis-label' rowspan='{len(df)}'><span>{html.escape(row_axis_label)}</span></th>"
            )
        cells.append(f"<th>{html.escape(str(index))}</th>")
        for column, value in row.items():
            classes = ["sens-cell", sensitivity_cell_class(float(value), metric_kind, min_value, max_value)]
            if index == base_row and column == base_col:
                classes.append("base-cell")
            cells.append(f"<td class='{' '.join(classes)}'>{format_sensitivity_value(float(value), metric_kind)}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"""
    <style>
      .warehouse-sens-card {{
        border: 1px solid #d8dee9;
        border-radius: 8px;
        background: #ffffff;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
        padding: 14px 14px 12px;
        margin: 8px 0 18px;
      }}
      .warehouse-sens-title {{
        font-size: 16px;
        font-weight: 750;
        color: #182033;
        margin-bottom: 10px;
      }}
      .warehouse-sens-wrap {{
        overflow-x: auto;
      }}
      .warehouse-sens-table {{
        border-collapse: separate;
        border-spacing: 3px;
        width: 100%;
        min-width: 520px;
        table-layout: fixed;
        font-size: 11px;
        line-height: 1.05;
      }}
      .warehouse-sens-table th {{
        background: #f3f6fb;
        color: #384152;
        border-radius: 4px;
        padding: 6px 7px;
        text-align: right;
        font-weight: 700;
        white-space: nowrap;
      }}
      .warehouse-sens-table td {{
        border-radius: 4px;
        padding: 7px 7px;
        text-align: right;
        font-weight: 750;
        white-space: nowrap;
        border: 1px solid transparent;
      }}
      .warehouse-sens-table .axis-spacer {{
        background: transparent;
        padding: 0;
        width: 24px;
      }}
      .warehouse-sens-table .x-axis-label {{
        background: transparent;
        color: #667085;
        text-align: center;
        font-size: 11px;
        padding: 0 0 4px;
      }}
      .warehouse-sens-table .y-axis-label {{
        background: transparent;
        color: #667085;
        text-align: center;
        width: 22px;
        min-width: 22px;
        padding: 0;
        vertical-align: middle;
      }}
      .warehouse-sens-table .y-axis-label span {{
        writing-mode: vertical-rl;
        transform: rotate(180deg);
        display: inline-block;
        letter-spacing: 0;
      }}
      .warehouse-sens-table .base-cell {{
        box-shadow: inset 0 0 0 2px #2f80ed;
      }}
      .sens-bad {{ background: #f9d6d5; color: #9f1d20; }}
      .sens-weak {{ background: #fde7ca; color: #8a4b05; }}
      .sens-ok {{ background: #fff4bf; color: #6f5600; }}
      .sens-good {{ background: #dff3dc; color: #1f6f34; }}
      .sens-strong {{ background: #b9e7c6; color: #0d5624; }}
      .sens-scale-1 {{ background: #eef5ff; color: #174ea6; }}
      .sens-scale-2 {{ background: #d7e9ff; color: #174ea6; }}
      .sens-scale-3 {{ background: #b8d8ff; color: #123f7a; }}
      .sens-scale-4 {{ background: #86bfff; color: #0b315f; }}
      .sens-scale-5 {{ background: #4d96e8; color: #ffffff; }}
      .warehouse-sens-legend {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 9px;
        color: #667085;
        font-size: 11px;
      }}
      .warehouse-sens-legend span {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
      }}
      .warehouse-sens-dot {{
        width: 10px;
        height: 10px;
        border-radius: 2px;
        display: inline-block;
      }}
    </style>
    <div class="warehouse-sens-card">
      <div class="warehouse-sens-title">{html.escape(title)}</div>
      <div class="warehouse-sens-wrap">
        <table class="warehouse-sens-table">
          <thead>{''.join(header_rows)}</thead>
          <tbody>{''.join(body_rows)}</tbody>
        </table>
      </div>
      <div class="warehouse-sens-legend">
        <span><i class="warehouse-sens-dot sens-bad"></i>lowest / weak</span>
        <span><i class="warehouse-sens-dot sens-ok"></i>mid</span>
        <span><i class="warehouse-sens-dot sens-strong"></i>strong / highest</span>
      </div>
    </div>
    """


def format_sensitivity_value(value: float, metric_kind: str) -> str:
    if metric_kind.endswith("_pct"):
        return f"{value:.1f}%"
    return f"{value:.2f}"


def sensitivity_cell_class(value: float, metric_kind: str, min_value: float, max_value: float) -> str:
    if metric_kind == "return_pct":
        return return_cell_class(value)
    if metric_kind == "loss_pct":
        return loss_cell_class(value)
    if max_value <= min_value:
        return "sens-scale-3"
    bucket = int((value - min_value) / (max_value - min_value) * 4)
    bucket = max(0, min(4, bucket))
    return f"sens-scale-{bucket + 1}"


def return_cell_class(value: float) -> str:
    if value < 0:
        return "sens-bad"
    if value < 5:
        return "sens-weak"
    if value < 8:
        return "sens-ok"
    if value < 12:
        return "sens-good"
    return "sens-strong"


def loss_cell_class(value: float) -> str:
    if value < 1:
        return "sens-strong"
    if value < 3:
        return "sens-good"
    if value < 6:
        return "sens-ok"
    if value < 10:
        return "sens-weak"
    return "sens-bad"


def render_tranche_thickness_chart(ce_sizes: list[dict[str, Any]], run_key: str) -> None:
    df = pd.DataFrame(ce_sizes)
    if df.empty:
        return
    labels = [tranche_visual_label(row, idx) for idx, row in df.iterrows()]
    colors = ["#183a6b", "#2f6fb2", "#55a8d9", "#a3d5ee", "#f0c35a", "#eb8f45", "#dd5f48", "#a8334e", "#6f2447"]
    stack_total = max(100.0, sum(float(row.get("thickness_pct") or 0.0) for _, row in df.iterrows()))
    show_inside = {"A1", "A1-A", "A1-B", "A2", "A3"}
    fig = go.Figure()
    for idx, row in df.iterrows():
        thickness = float(row.get("thickness_pct") or 0.0)
        label = labels[idx]
        inside_label = label if label in show_inside and thickness >= 3.0 else ""
        fig.add_trace(go.Bar(
            x=[thickness],
            y=[""],
            orientation="h",
            name=f"{label} {thickness:.1f}%",
            text=[inside_label],
            textposition="inside",
            insidetextanchor="middle",
            textangle=0,
            marker_color=colors[idx % len(colors)],
            hovertemplate=(
                f"<b>{html.escape(label)}</b><br>"
                "Thickness %{y:.2f}%<br>"
                f"Attachment {float(row.get('attachment_pct') or 0):.2f}%<extra></extra>"
            ),
        ))
    fig.update_layout(
        title=dict(text="Credit Enhancement Tranche", x=0.0, xanchor="left", y=0.96),
        barmode="stack",
        height=330,
        margin=dict(l=10, r=10, t=54, b=118),
        xaxis=dict(
            title=dict(text="Pool thickness (%)", standoff=34),
            ticksuffix="%",
            ticklabelstandoff=1,
            automargin=True,
        ),
        yaxis_title="",
        showlegend=True,
        legend=dict(orientation="h", yanchor="top", y=-0.34, xanchor="center", x=0.5),
        uniformtext=dict(minsize=11, mode="hide"),
    )
    fig.update_xaxes(range=[0, stack_total])
    fig.update_yaxes(showticklabels=False)
    st.plotly_chart(fig, use_container_width=True, key=f"{run_key}-tranche-thickness-chart")


def tranche_visual_label(row: dict[str, Any] | pd.Series, idx: int) -> str:
    preferred = ["A1", "A2", "A3", "M1", "B1-A", "B1-B", "B2", "B3"]
    raw = str(row.get("class_name") or "").upper().replace("CLASS", "").strip()
    compact = raw.replace("-", "").replace(" ", "")
    replacements = {
        "A1A": "A1-A",
        "A1B": "A1-B",
        "A1FCF": "A1",
        "A1LCF": "A1",
        "A1IO": "A1",
        "A2": "A2",
        "A3": "A3",
        "M1": "M1",
        "B1A": "B1-A",
        "B1B": "B1-B",
        "B2": "B2",
        "B3": "B3",
    }
    for token, label in replacements.items():
        if token in compact:
            return label
    return preferred[idx] if idx < len(preferred) else f"Class {idx + 1}"


def tranche_stack_label(row: dict[str, Any] | pd.Series, idx: int) -> str:
    preferred = ["A1", "A2", "A3", "M1", "B1A", "B1B", "B2", "B3"]
    raw = str(row.get("class_name") or "").upper().replace("-", "").replace(" ", "")
    if raw.startswith("CLASS"):
        raw = raw[5:]
    if raw in {"A", "B", "C", "D", "E", "F", "G", "H"}:
        return raw
    replacements = {
        "A1A": "A1",
        "A1B": "A1",
        "A1FCF": "A1",
        "A1LCF": "A1",
        "A1IO": "A1",
        "A1": "A1",
        "A2": "A2",
        "A3": "A3",
        "M1": "M1",
        "B1A": "B1A",
        "B1B": "B1B",
        "B2": "B2",
        "B3": "B3",
    }
    for token, label in replacements.items():
        if token in raw:
            return label
    return preferred[idx] if idx < len(preferred) else f"Class {idx + 1}"


def require_manual_sourced_inputs(rows: list[dict[str, Any]], confirmed_key: str, run_key: str) -> None:
    missing = missing_sourced_rows(rows)
    if not missing:
        return

    st.error(
        "Manual input required: the parser could not source every field. "
        "Enter numeric values below before running the warehouse model."
    )
    updated_rows = [dict(row) for row in rows]
    field_index = {row["field"]: idx for idx, row in enumerate(updated_rows)}
    unresolved = []
    for row in missing:
        field = str(row["field"])
        label = str(row.get("label") or field)
        manual_value = st.text_input(
            label,
            value="",
            placeholder="Enter numeric value",
            key=f"{run_key}-manual-{field}",
        )
        if numeric_value(manual_value) is None:
            unresolved.append(label)
        else:
            updated_rows[field_index[field]]["approved_value"] = manual_value

    st.session_state[confirmed_key] = updated_rows
    if unresolved:
        st.warning("Still needed: " + ", ".join(unresolved))
        st.stop()


def nuance_values(parsed: dict[str, Any]) -> dict[str, Any]:
    return {row["field"]: row.get("value") for row in nuance_rows(parsed)}


def simple_range_note(title: str, low: Any, high: Any) -> str:
    low_value = numeric_value(low)
    high_value = numeric_value(high)
    if low_value is None and high_value is None:
        return f"{title}: n/a"
    if low_value is not None and high_value is not None:
        return f"{title}: {low_value:g}%-{high_value:g}%"
    value = low_value if low_value is not None else high_value
    return f"{title}: {value:g}%"


def debt_tranche_pct(ce_sizes: list[dict[str, Any]]) -> float:
    total = 0.0
    for idx, row in enumerate(ce_sizes):
        if not is_plain_debt_tranche(row, idx):
            continue
        total += float(row.get("thickness_pct") or 0.0)
    return min(max(total, 0.0), 100.0)


def tranche_a1_pct(ce_sizes: list[dict[str, Any]]) -> float:
    return debt_tranche_pct(ce_sizes)


def is_plain_debt_tranche(row: dict[str, Any] | pd.Series, idx: int) -> bool:
    label = tranche_stack_label(row, idx)
    raw_name = str(row.get("class_name") or "").upper()
    compact = re.sub(r"[^A-Z0-9]", "", raw_name.replace("CLASS", ""))
    label_compact = re.sub(r"[^A-Z0-9]", "", label.upper())
    special_markers = {
        "MEZZ",
        "MEZZANINE",
        "XS",
        "XSR",
        "RESIDUAL",
        "EQUITY",
        "IO",
        "FCF",
        "LCF",
        "EXCHANGEABLE",
    }
    if any(marker in compact for marker in special_markers):
        return False
    if compact in {"R"} or label_compact in {"R"}:
        return False
    if compact.startswith("M") or label_compact.startswith("M"):
        return False
    return bool(re.fullmatch(r"[A-H][0-9]?[A-Z]?", label_compact))


def render_confirmed_inputs(
    parsed: dict[str, Any],
    summary: dict[str, Any],
    confirmed_key: str,
    run_key: str,
) -> RmbsInputs:
    confirmed_rows = st.session_state.get(confirmed_key) or extraction_rows(parsed)
    confirmed = {row["field"]: row.get("approved_value") for row in confirmed_rows}
    confirmed.update(stable_nuance_values(parsed, confirmed_key))
    severity_seed = midpoint(
        numeric_value(confirmed.get("severity_low_pct")),
        numeric_value(confirmed.get("severity_high_pct")),
        RmbsInputs.severity_pct,
    )
    cpr_seed = midpoint(
        numeric_value(confirmed.get("prepayment_low_pct")),
        numeric_value(confirmed.get("prepayment_high_pct")),
        ASSUMED_DEFAULTS["cpr_pct"],
    )
    yield_seed = numeric_value(confirmed.get("wa_coupon_pct")) or ASSUMED_DEFAULTS["yield_target_pct"]
    servicing_seed = numeric_value(confirmed.get("servicing_fee_pct")) or RmbsInputs.servicing_fee_pct
    advance_seed = debt_tranche_pct(summary["ce_sizes"]) or ASSUMED_DEFAULTS["advance_rate_pct"]
    initialize_assumption_state(
        run_key,
        {
            "cpr_pct": cpr_seed,
            "cdr_pct": ASSUMED_DEFAULTS["cdr_pct"],
            "severity_pct": severity_seed,
            "yield_target_pct": yield_seed,
            "servicing_fee_pct": servicing_seed,
            "sofr_pct": ASSUMED_DEFAULTS["sofr_pct"],
            "spread_pct": ASSUMED_DEFAULTS["spread_pct"],
            "advance_rate_pct": advance_seed,
        },
    )

    st.markdown("**Assumptions**")
    row1 = st.columns(4, gap="medium")
    with row1[0]:
        cpr = compact_input("CPR", f"{run_key}-warehouse-app-cpr", cpr_seed, kind="pct")
        compact_note(simple_range_note("Presale range", confirmed.get("prepayment_low_pct"), confirmed.get("prepayment_high_pct")))
    with row1[1]:
        cdr = compact_input("CDR", f"{run_key}-warehouse-app-cdr", ASSUMED_DEFAULTS["cdr_pct"], kind="pct")
        compact_note(simple_range_note("Presale range", confirmed.get("foreclosure_freq_low_pct"), confirmed.get("foreclosure_freq_high_pct")))
    with row1[2]:
        severity = compact_input("Severity", f"{run_key}-warehouse-app-severity", severity_seed, kind="pct")
        compact_note(simple_range_note("Presale range", confirmed.get("severity_low_pct"), confirmed.get("severity_high_pct")))
    with row1[3]:
        yield_target = compact_input(
            "Yield Target", f"{run_key}-warehouse-app-yield", yield_seed, kind="pct")
        compact_note("Seeded at WA Coupon")

    row2 = st.columns(4, gap="medium")
    with row2[0]:
        servicing = compact_input(
            "Servicing Fee", f"{run_key}-warehouse-app-servicing", servicing_seed, kind="pct")
    with row2[1]:
        sofr = compact_input("SOFR", f"{run_key}-warehouse-app-sofr", ASSUMED_DEFAULTS["sofr_pct"], kind="pct")
    with row2[2]:
        spread = compact_input("Spread", f"{run_key}-warehouse-app-spread", ASSUMED_DEFAULTS["spread_pct"], kind="pct")
    with row2[3]:
        advance = compact_input(
            "Advance Rate", f"{run_key}-warehouse-app-advance", advance_seed, kind="pct")
        compact_note("Seeded at total debt tranche size")

    assumptions = {
        "cpr_pct": cpr,
        "cdr_pct": cdr,
        "severity_pct": severity,
        "yield_target_pct": yield_target,
        "servicing_fee_pct": servicing,
        "sofr_pct": sofr,
        "spread_pct": spread,
        "advance_rate_pct": advance,
    }
    return build_inputs_from_confirmed(confirmed, assumptions, summary["ce_sizes"])


ASSUMPTION_STATE_FIELDS = {
    "cpr": ("cpr_pct", "pct"),
    "cdr": ("cdr_pct", "pct"),
    "severity": ("severity_pct", "pct"),
    "yield": ("yield_target_pct", "pct"),
    "servicing": ("servicing_fee_pct", "pct"),
    "sofr": ("sofr_pct", "pct"),
    "spread": ("spread_pct", "pct"),
    "advance": ("advance_rate_pct", "pct"),
}


def initialize_assumption_state(run_key: str, values: dict[str, Any], *, force: bool = False) -> None:
    for slug, (field, kind) in ASSUMPTION_STATE_FIELDS.items():
        value = numeric_value(values.get(field))
        if value is None:
            continue
        state_key = assumption_raw_key(run_key, slug)
        widget_key = assumption_widget_key(run_key, slug)
        if force or state_key not in st.session_state:
            st.session_state[state_key] = default_input_text(float(value), kind)
        if force or widget_key not in st.session_state:
            st.session_state[widget_key] = st.session_state[state_key]


def assumption_raw_key(run_key: str, slug: str) -> str:
    return f"{run_key}-warehouse-app-{slug}__assumption_raw"


def assumption_widget_key(run_key: str, slug: str) -> str:
    return f"{run_key}-warehouse-app-{slug}__assumption_widget"


def compact_input(label: str, key: str, value: float | int, *, kind: str) -> float:
    st.markdown(f"<div class='warehouse-assumption-label'>{html.escape(label)}</div>", unsafe_allow_html=True)
    slug = key.replace("-warehouse-app-", "|").split("|")[-1]
    raw_key = assumption_raw_key(key.split("-warehouse-app-")[0], slug)
    widget_key = assumption_widget_key(key.split("-warehouse-app-")[0], slug)
    if raw_key not in st.session_state:
        st.session_state[raw_key] = default_input_text(float(value), kind)
    if widget_key not in st.session_state:
        st.session_state[widget_key] = st.session_state[raw_key]
    raw = st.text_input(label, key=widget_key, label_visibility="collapsed")
    st.session_state[raw_key] = raw
    return parse_input_value(raw, float(value), kind)


def compact_note(text: str) -> None:
    st.markdown(f"<div class='warehouse-assumption-note'>{html.escape(text)}</div>", unsafe_allow_html=True)


def persist_parse_memory(
    parsed: dict[str, Any],
    summary: dict[str, Any],
    inputs: RmbsInputs,
    metrics: dict[str, float],
    confirmed_key: str,
) -> None:
    parse_id = st.session_state.get("warehouse_app_parse_id")
    if not parse_id:
        return
    confirmed_inputs = {
        "inputs": asdict(inputs),
        "confirmed_rows": st.session_state.get(confirmed_key) or extraction_rows(parsed),
    }
    try:
        upsert_presale_parse(
            parse_id=str(parse_id),
            file_name=str(st.session_state.get("warehouse_app_file_name") or ""),
            file_sha256=str(st.session_state.get("warehouse_app_file_sha256") or ""),
            deal_name=str(summary["deal_name"]),
            raw_extraction=parsed,
            confirmed_inputs=confirmed_inputs,
            computed_metrics=metrics,
            validation_flags=list(summary["validation_flags"]),
        )
        if st.session_state.get("warehouse_app_saved_parse_id") != parse_id:
            st.session_state.warehouse_app_saved_parse_id = parse_id
            st.session_state.warehouse_app_pending_selector_parse_id = parse_id
            st.success("Parse memory saved.")
    except Exception as exc:
        st.warning(f"Parse memory was not saved: {exc}")


def render_recent_parse_memory() -> None:
    with st.expander("Recent Parse Memory", expanded=False):
        try:
            rows = recent_presale_parses(limit=5)
        except Exception as exc:
            st.warning(f"Could not load parse memory: {exc}")
            return
        if not rows:
            st.caption("No saved parses yet.")
            return
        display = pd.DataFrame(rows)
        if "file_sha256" in display.columns:
            display["file_sha256"] = display["file_sha256"].astype(str).str[:12]
        st.dataframe(display, use_container_width=True, hide_index=True)
