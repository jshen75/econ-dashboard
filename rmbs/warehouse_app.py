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

from mortgage.page import input_row

from .calculator import RmbsInputs, project_rmbs_waterfall, rate
from .page import (
    advance_optimization,
    build_results_object,
    build_warehouse_excel_download,
    inject_rmbs_css,
    render_scenario_a_equity_summary,
    render_scenario_a_visual_grid,
    render_warehouse_assumptions_sources_panel,
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
        created = row.get("created_at") or ""
        return f"{row.get('deal_name') or 'Unknown deal'} - {created}"

    current_parse_id = str(st.session_state.get("warehouse_app_parse_id") or "")
    selector_key = f"warehouse-app-previous-parse-{safe_file_slug(current_parse_id or 'none')[:12]}"
    selected_index = options.index(current_parse_id) if current_parse_id in options else 0
    selected = st.selectbox(
        "Previous Parsed Presales",
        options,
        index=selected_index,
        format_func=label_for,
        key=selector_key,
    )
    if selected and st.button("Load Saved Parse", width="stretch", key="warehouse-app-load-saved-parse"):
        load_saved_parse(selected)
        st.rerun()

    if rows:
        with st.expander("Saved Presales - Simplified Data", expanded=False):
            display = pd.DataFrame(rows)[[
                "created_at",
                "deal_name",
                "file_name",
                "deal_balance",
                "wa_coupon_pct",
                "advance_rate_pct",
                "warehouse_return",
                "equity_irr_levered",
                "validation_flags",
            ]].copy()
            display["deal_balance"] = display["deal_balance"].map(lambda value: f"{float(value) / 1_000_000:,.1f}mm" if value else "")
            for col in ["wa_coupon_pct", "advance_rate_pct"]:
                display[col] = display[col].map(lambda value: f"{float(value):.2f}%" if value is not None else "")
            for col in ["warehouse_return", "equity_irr_levered"]:
                display[col] = display[col].map(lambda value: f"{float(value):.2%}" if value is not None else "")
            st.dataframe(display, width="stretch", hide_index=True)
    else:
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
    st.session_state.warehouse_app_loaded_parse_label = f"{saved['deal_name']} - {saved['created_at']}"


def render_warehouse_app_page() -> None:
    inject_rmbs_css()
    hydrate_latest_saved_parse()
    st.title("Warehouse App")
    st.caption(
        "Upload an RMBS presale, extract the subject-deal fields with Claude, approve the evidence, "
        "then run the deterministic warehouse model."
    )

    render_saved_parse_selector()
    if st.session_state.get("warehouse_app_loaded_parse_label"):
        st.caption(f"Loaded from parse memory: {st.session_state.warehouse_app_loaded_parse_label}")

    upload_col, status_col = st.columns([2, 1])
    with upload_col:
        uploaded = st.file_uploader("Presale PDF", type=["pdf"], key="warehouse-app-presale")
    with status_col:
        api_key, secret_error = anthropic_api_key()
        st.markdown("**Parser**")
        st.caption("Claude Sonnet 4.6")
    if secret_error:
        st.error(
            "Streamlit could not parse `.streamlit/secrets.toml`. Put the key in quotes, for example:\n\n"
            '```toml\nANTHROPIC_API_KEY = "sk-ant-..."\n```'
        )

    if uploaded and st.button("Parse Presale", type="primary", width="stretch"):
        parse_uploaded_presale(uploaded.name, uploaded.getvalue())

    parsed = st.session_state.get("warehouse_app_extraction")
    if not parsed:
        return

    summary = extraction_summary(parsed)
    run_key = warehouse_app_run_key(parsed, summary)
    confirmed_key = f"warehouse_app_confirmed_rows_{run_key}"
    render_extraction_review(parsed, summary, confirmed_key, run_key)
    inputs = render_confirmed_inputs(parsed, summary, confirmed_key, run_key)

    schedule, tranche_summary, metrics = project_rmbs_waterfall(inputs)
    results = build_results_object(inputs, schedule, tranche_summary, metrics)
    benchmarks = warehouse_app_loss_benchmarks(inputs)
    safety_threshold = severe_benchmark_threshold(benchmarks)
    advance_df, optima = advance_optimization(inputs, safety_threshold=safety_threshold)
    persist_parse_memory(parsed, summary, inputs, metrics, confirmed_key)

    st.divider()
    st.markdown(f"**Computed Warehouse Model - {summary['deal_name']}**")
    analysis_tab, workbook_tab = st.tabs(["Analysis Layer", "Workbook Layer"])
    with analysis_tab:
        render_warehouse_metric_blocks(inputs, metrics)
        render_warehouse_sensitivity_tables(inputs)
        render_scenario_a_equity_summary(inputs, results)
        render_scenario_a_visual_grid(inputs, results, advance_df, optima, key_prefix=f"warehouse-app-{run_key}")
        render_warehouse_assumptions_sources_panel(summary["deal_name"])
    with workbook_tab:
        render_warehouse_tables(schedule)
        st.download_button(
            "Download Scenario A Workbook",
            data=build_warehouse_excel_download(inputs, schedule, metrics),
            file_name=f"{safe_file_slug(summary['deal_name'])}_warehouse_app.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
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
        st.session_state.warehouse_app_file_name = file_name
        st.session_state.warehouse_app_file_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        st.session_state.warehouse_app_extraction = parsed
        st.session_state.warehouse_app_saved_parse_id = None
        st.session_state.warehouse_app_loaded_parse_id = None
        st.session_state.warehouse_app_loaded_parse_label = None
        for key in list(st.session_state):
            if str(key).startswith("warehouse_app_confirmed_rows_"):
                del st.session_state[key]
        st.success("Presale parsed. Review extracted fields below.")
    except Exception as exc:  # UI boundary: show provider/parser errors without crashing app.
        st.error(f"Presale parsing failed: {exc}")


def warehouse_app_run_key(parsed: dict[str, Any], summary: dict[str, Any]) -> str:
    parse_id = st.session_state.get("warehouse_app_parse_id")
    if parse_id:
        return safe_file_slug(str(parse_id))[:12]
    deal_name = str(summary.get("deal_name") or parsed.get("deal_name", {}).get("value") or "warehouse-app")
    return safe_file_slug(deal_name)


def safe_file_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return slug or "warehouse_app"


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
    deal = parsed.get("deal_name") or {}
    st.markdown("**Subject Deal Discovery**")
    c1, c2, c3 = st.columns([1.2, 1, 1])
    c1.metric("Deal Name", summary["deal_name"])
    c2.metric("Confidence", f"{float(deal.get('confidence') or 0):.0%}")
    c3.metric("Tranche Size Sum", f"{sum(row['thickness_pct'] for row in summary['ce_sizes']):.1f}%")
    if deal.get("source_anchor_text"):
        st.caption(f"Deal anchor: {deal.get('source_anchor_text')} ({deal.get('page_hint') or 'page not reported'})")

    render_review_details(parsed, summary)

    st.markdown("**Sourced Field Review**")
    source_rows = st.session_state.get(confirmed_key) or extraction_rows(parsed)
    rows = field_review_display_df(source_rows)
    edited = st.data_editor(
        rows,
        hide_index=True,
        width="stretch",
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

    if summary["ce_sizes"]:
        st.markdown("**Computed CE-Gap Tranche Thickness**")
        render_tranche_thickness_chart(summary["ce_sizes"], run_key)

    require_manual_sourced_inputs(confirmed_rows, confirmed_key, run_key)


def render_review_details(parsed: dict[str, Any], summary: dict[str, Any]) -> None:
    flags = list(summary["validation_flags"])
    nuance_df = nuance_review_display_df(parsed)
    flag_count = len(flags)
    nuance_count = int(nuance_df["Verified"].eq("✅").sum()) if not nuance_df.empty else 0
    if flag_count:
        st.warning(f"{flag_count} review flags. Open Review Details for parser notes and nuanced presale fields.")
    else:
        st.success("Headline fields parsed. Open Review Details for nuanced presale fields.")

    with st.expander("Review Details - parser flags, ranges, triggers, and fee nuances", expanded=False):
        if flags:
            st.markdown("**Parser Flags**")
            st.dataframe(review_flags_df(flags), width="stretch", hide_index=True)
        else:
            st.caption("No parser flags.")
        st.markdown(f"**Nuanced Parsed Fields ({nuance_count} verified)**")
        st.dataframe(nuance_df, width="stretch", hide_index=True)


def review_flags_df(flags: list[str]) -> pd.DataFrame:
    rows = []
    for flag in flags:
        lowered = flag.lower()
        if "missing" in lowered:
            category = "Missing"
        elif "low confidence" in lowered:
            category = "Low confidence"
        elif "anchor" in lowered:
            category = "Evidence"
        elif "sum" in lowered or "differ" in lowered:
            category = "Validation"
        else:
            category = "Parser note"
        rows.append({"Type": category, "Note": flag})
    return pd.DataFrame(rows)


def nuance_review_display_df(parsed: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for row in nuance_rows(parsed):
        value = row.get("value")
        rows.append({
            "Label": row.get("label"),
            "Value": "" if value is None else str(value),
            "Page": row.get("page") or "",
            "Verified": "✅" if numeric_value(value) is not None else "",
            "Evidence": row.get("anchor") or "",
        })
    return pd.DataFrame(rows, dtype=object)


def field_review_display_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Label": str(row.get("label") or ""),
            "approved_value": "" if row.get("approved_value") is None else str(row.get("approved_value")),
            "Page": str(row.get("page") or ""),
            "Verified": "✅" if numeric_value(row.get("approved_value")) is not None else "",
        }
        for row in rows
    ], dtype=object)


def merge_field_review_edits(source_rows: list[dict[str, Any]], display_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = []
    for source, display in zip(source_rows, display_rows):
        updated = dict(source)
        updated["approved_value"] = display.get("approved_value")
        merged.append(updated)
    return merged


def missing_sourced_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if numeric_value(row.get("approved_value")) is None]


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
    "Macaulay Duration": {
        "key": "Macaulay Duration",
        "kind": "years",
        "subtitle": "PV-weighted asset cashflow duration",
    },
    "Modified Duration": {
        "key": "Modified Duration",
        "kind": "years",
        "subtitle": "Yield-adjusted asset duration",
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
}


def render_warehouse_sensitivity_tables(inputs: RmbsInputs) -> None:
    st.markdown("### Stress Sensitivity")
    st.caption(
        "Each cell reruns the deterministic warehouse model. Levered Equity IRR is the Scenario A sponsor residual IRR after warehouse debt service. "
        "Blue outlines mark the current approved assumption row and column."
    )
    c1, c2 = st.columns(2)
    with c1:
        credit_metric = st.selectbox(
            "Credit stress output",
            list(SENSITIVITY_METRICS),
            index=0,
            key="warehouse-app-credit-stress-output",
        )
        st.markdown(sensitivity_table_html(
            "Credit Stress",
            SENSITIVITY_METRICS[credit_metric]["subtitle"],
            cdr_severity_sensitivity_table(inputs, credit_metric),
            f"CDR {inputs.cdr_pct:g}%",
            f"Sev {inputs.severity_pct:g}%",
            credit_metric,
        ), unsafe_allow_html=True)
    with c2:
        financing_metric = st.selectbox(
            "Financing stress output",
            list(SENSITIVITY_METRICS),
            index=0,
            key="warehouse-app-financing-stress-output",
        )
        st.markdown(sensitivity_table_html(
            "Financing Stress",
            SENSITIVITY_METRICS[financing_metric]["subtitle"],
            advance_spread_sensitivity_table(inputs, financing_metric),
            f"Adv {inputs.advance_rate_pct:g}%",
            f"Spr {inputs.spread_pct:g}%",
            financing_metric,
        ), unsafe_allow_html=True)


def cdr_severity_equity_irr_table(inputs: RmbsInputs) -> pd.DataFrame:
    return cdr_severity_sensitivity_table(inputs, "Levered Equity IRR")


def cdr_severity_sensitivity_table(inputs: RmbsInputs, metric_name: str) -> pd.DataFrame:
    cdr_values = sorted({0.25, 0.50, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, round(inputs.cdr_pct, 2)})
    severity_values = sorted({20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0, round(inputs.severity_pct, 2)})
    rows: list[list[float]] = []
    for cdr in cdr_values:
        row = []
        for severity in severity_values:
            scenario = RmbsInputs(**{**asdict(inputs), "cdr_pct": cdr, "severity_pct": severity})
            _schedule, _summary, metrics = project_rmbs_waterfall(scenario)
            row.append(sensitivity_metric_value(metrics, metric_name))
        rows.append(row)
    return pd.DataFrame(
        rows,
        index=[f"CDR {value:g}%" for value in cdr_values],
        columns=[f"Sev {value:g}%" for value in severity_values],
    )


def advance_spread_equity_irr_table(inputs: RmbsInputs) -> pd.DataFrame:
    return advance_spread_sensitivity_table(inputs, "Levered Equity IRR")


def advance_spread_sensitivity_table(inputs: RmbsInputs, metric_name: str) -> pd.DataFrame:
    advance_values = sorted({76.0, 78.0, 80.0, 82.0, 84.0, 86.0, 88.0, 90.0, 92.0, round(inputs.advance_rate_pct, 2)})
    spread_values = sorted({
        round(max(inputs.spread_pct - 1.00, 0.0), 2),
        round(max(inputs.spread_pct - 0.50, 0.0), 2),
        round(inputs.spread_pct, 2),
        round(inputs.spread_pct + 0.50, 2),
        round(inputs.spread_pct + 1.00, 2),
        round(inputs.spread_pct + 1.50, 2),
        round(inputs.spread_pct + 2.00, 2),
    })
    rows: list[list[float]] = []
    for advance in advance_values:
        row = []
        for spread in spread_values:
            scenario = RmbsInputs(**{**asdict(inputs), "advance_rate_pct": advance, "spread_pct": spread})
            _schedule, _summary, metrics = project_rmbs_waterfall(scenario)
            row.append(sensitivity_metric_value(metrics, metric_name))
        rows.append(row)
    return pd.DataFrame(
        rows,
        index=[f"Adv {value:g}%" for value in advance_values],
        columns=[f"Spr {value:g}%" for value in spread_values],
    )


def sensitivity_metric_value(metrics: dict[str, float], metric_name: str) -> float:
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
) -> str:
    metric_kind = str(SENSITIVITY_METRICS[metric_name]["kind"])
    flat_values = [float(value) for value in df.to_numpy().ravel()]
    min_value = min(flat_values) if flat_values else 0.0
    max_value = max(flat_values) if flat_values else 0.0
    header_cells = ["<th></th>"]
    for column in df.columns:
        cls = "base-axis" if column == base_col else ""
        header_cells.append(f"<th class='{cls}'>{html.escape(str(column))}</th>")
    body_rows = []
    for index, row in df.iterrows():
        row_class = "base-axis" if index == base_row else ""
        cells = [f"<th class='{row_class}'>{html.escape(str(index))}</th>"]
        for column, value in row.items():
            classes = ["sens-cell", sensitivity_cell_class(float(value), metric_kind, min_value, max_value)]
            if index == base_row or column == base_col:
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
        margin-bottom: 2px;
      }}
      .warehouse-sens-subtitle {{
        font-size: 12px;
        color: #667085;
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
      .warehouse-sens-table .base-axis {{
        background: #eaf2ff;
        color: #174ea6;
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
      <div class="warehouse-sens-subtitle"><b>{html.escape(metric_name)}</b></div>
      <div class="warehouse-sens-subtitle">{html.escape(subtitle)}</div>
      <div class="warehouse-sens-wrap">
        <table class="warehouse-sens-table">
          <thead><tr>{''.join(header_cells)}</tr></thead>
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
    labels = [tranche_stack_label(row, idx) for idx, row in df.iterrows()]
    colors = ["#0b3d91", "#1f6fba", "#40a3d8", "#8ecae6", "#f6c85f", "#f29e4c", "#e76f51", "#b23a48", "#7a1f3d"]
    fig = go.Figure()
    for idx, row in df.iterrows():
        thickness = float(row.get("thickness_pct") or 0.0)
        label = labels[idx]
        fig.add_trace(go.Bar(
            x=["CE-Gap Stack"],
            y=[thickness],
            name=label,
            text=[f"{label}<br>{thickness:.1f}%"],
            textposition="inside",
            marker_color=colors[idx % len(colors)],
            hovertemplate=(
                f"<b>{html.escape(label)}</b><br>"
                "Thickness %{y:.2f}%<br>"
                f"Attachment {float(row.get('attachment_pct') or 0):.2f}%<extra></extra>"
            ),
        ))
    fig.update_layout(
        barmode="stack",
        height=360,
        margin=dict(l=10, r=10, t=20, b=30),
        yaxis_title="Pool thickness (%)",
        xaxis_title="",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
    )
    fig.update_yaxes(range=[0, max(100, sum(float(row.get("thickness_pct") or 0.0) for row in ce_sizes))])
    st.plotly_chart(fig, width="stretch", key=f"{run_key}-tranche-thickness-chart")


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


def tranche_a1_pct(ce_sizes: list[dict[str, Any]]) -> float:
    for idx, row in enumerate(ce_sizes):
        label = tranche_stack_label(row, idx)
        if label == "A1" or (label == "A" and idx == 0):
            return float(row.get("thickness_pct") or 0.0)
    return 0.0


def render_confirmed_inputs(
    parsed: dict[str, Any],
    summary: dict[str, Any],
    confirmed_key: str,
    run_key: str,
) -> RmbsInputs:
    confirmed_rows = st.session_state.get(confirmed_key) or extraction_rows(parsed)
    confirmed = {row["field"]: row.get("approved_value") for row in confirmed_rows}
    confirmed.update(nuance_values(parsed))
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
    advance_seed = tranche_a1_pct(summary["ce_sizes"]) or ASSUMED_DEFAULTS["advance_rate_pct"]

    st.markdown("**Assumptions - Not Sourced From Presale**")
    c1, c2, c3 = st.columns(3)
    with c1:
        cpr = input_row("CPR", f"{run_key}-warehouse-app-cpr", cpr_seed, kind="pct")
        st.caption(simple_range_note("Presale range", confirmed.get("prepayment_low_pct"), confirmed.get("prepayment_high_pct")))
        st.caption(f"SMM {pct_text(smm(cpr))}")
        cdr = input_row("CDR", f"{run_key}-warehouse-app-cdr", ASSUMED_DEFAULTS["cdr_pct"], kind="pct")
        st.caption(simple_range_note("Presale range", confirmed.get("foreclosure_freq_low_pct"), confirmed.get("foreclosure_freq_high_pct")))
        st.caption(f"MDR {pct_text(mdr(cdr))}")
        severity = input_row("Severity", f"{run_key}-warehouse-app-severity", severity_seed, kind="pct")
        st.caption(simple_range_note("Presale range", confirmed.get("severity_low_pct"), confirmed.get("severity_high_pct")))
    with c2:
        yield_target = input_row(
            "Yield Target", f"{run_key}-warehouse-app-yield", yield_seed, kind="pct")
        st.caption("Seeded at WA Coupon")
        servicing = input_row(
            "Servicing Fee", f"{run_key}-warehouse-app-servicing", servicing_seed, kind="pct")
    with c3:
        sofr = input_row("SOFR", f"{run_key}-warehouse-app-sofr", ASSUMED_DEFAULTS["sofr_pct"], kind="pct")
        spread = input_row("Spread", f"{run_key}-warehouse-app-spread", ASSUMED_DEFAULTS["spread_pct"], kind="pct")
        advance = input_row(
            "Advance Rate", f"{run_key}-warehouse-app-advance", advance_seed, kind="pct")
        st.caption("Seeded at A1 tranche size")

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
        st.dataframe(display, width="stretch", hide_index=True)
