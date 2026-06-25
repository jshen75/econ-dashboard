"""Warehouse App UI: upload presale, confirm extraction, compute warehouse analysis."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict
from uuid import uuid4
from typing import Any

import pandas as pd
import streamlit as st

from mortgage.page import input_row

from .calculator import RmbsInputs, project_rmbs_waterfall, rate
from .page import (
    advance_optimization,
    analysis_sanity_checks,
    build_results_object,
    build_warehouse_excel_download,
    inject_rmbs_css,
    render_headline_callouts,
    render_investment_report,
    render_optimal_advance_section,
    render_scenario_a_equity_view,
    render_warehouse_assumptions_sources_panel,
    render_warehouse_metric_blocks,
    render_warehouse_stress_view,
    render_warehouse_tables,
    render_warehouse_view,
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
    numeric_value,
    parse_presale_with_anthropic,
)
from .presale_store import (
    get_presale_parse,
    presale_store_backend_name,
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
        st.warning(f"Could not load latest saved parse from {presale_store_backend_name()}: {exc}")
        return
    if rows:
        load_saved_parse(str(rows[0]["id"]))


def render_saved_parse_selector() -> None:
    try:
        rows = recent_presale_parses(limit=25)
    except Exception as exc:
        st.warning(f"Could not load previous parses from {presale_store_backend_name()}: {exc}")
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
        st.caption(f"No previous parses found in {presale_store_backend_name()} yet.")


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
        st.caption(f"Parse memory: {presale_store_backend_name()}")
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
    sanity = analysis_sanity_checks(inputs, results, advance_df, optima)
    persist_parse_memory(parsed, summary, inputs, metrics, confirmed_key)

    st.divider()
    st.markdown(f"**Computed Warehouse Model - {summary['deal_name']}**")
    _, download_col = st.columns([4, 1])
    with download_col:
        st.download_button(
            "Download Scenario A",
            data=build_warehouse_excel_download(inputs, schedule, metrics),
            file_name=f"{safe_file_slug(summary['deal_name'])}_warehouse_app.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            key=f"{run_key}-warehouse-app-download",
        )
    render_warehouse_metric_blocks(inputs, metrics)
    render_warehouse_tables(schedule)

    st.markdown("**Analysis Layer - Live Readout From Approved Extraction**")
    render_headline_callouts(inputs, results, sanity)
    view1, view2 = st.columns(2)
    with view1:
        render_warehouse_view(results, key_prefix=f"warehouse-app-{run_key}", benchmarks=benchmarks)
    with view2:
        render_scenario_a_equity_view(inputs, results, advance_df, optima, key_prefix=f"warehouse-app-{run_key}")
    render_warehouse_stress_view(inputs, key_prefix=f"warehouse-app-{run_key}", benchmarks=benchmarks)
    render_optimal_advance_section(
        advance_df, optima, key_prefix="warehouse-app", safety_threshold=safety_threshold)
    render_investment_report(
        inputs,
        results,
        advance_df,
        optima,
        full_rmbs=False,
        deal_name=summary["deal_name"],
        benchmarks=benchmarks,
        safety_threshold=safety_threshold,
    )
    render_warehouse_assumptions_sources_panel(summary["deal_name"])
    render_recent_parse_memory()


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

    if summary["validation_flags"]:
        st.warning("Review flags: " + " | ".join(summary["validation_flags"]))
    else:
        st.success("Internal validation checks passed.")

    st.markdown("**Sourced Field Review**")
    rows = pd.DataFrame(extraction_rows(parsed))
    edited = st.data_editor(
        rows,
        hide_index=True,
        width="stretch",
        disabled=["field", "label", "confidence", "page", "anchor"],
        key=f"{run_key}-warehouse-app-field-review",
    )
    st.session_state[confirmed_key] = edited.to_dict("records")

    if summary["ce_sizes"]:
        st.markdown("**Computed CE-Gap Tranche Thickness**")
        st.dataframe(pd.DataFrame(summary["ce_sizes"]), width="stretch", hide_index=True)


def render_confirmed_inputs(
    parsed: dict[str, Any],
    summary: dict[str, Any],
    confirmed_key: str,
    run_key: str,
) -> RmbsInputs:
    confirmed_rows = st.session_state.get(confirmed_key) or extraction_rows(parsed)
    confirmed = {row["field"]: row.get("approved_value") for row in confirmed_rows}
    severity_seed = midpoint(
        numeric_value(confirmed.get("severity_low_pct")),
        numeric_value(confirmed.get("severity_high_pct")),
        RmbsInputs.severity_pct,
    )

    st.markdown("**Assumptions - Not Sourced From Presale**")
    c1, c2, c3 = st.columns(3)
    with c1:
        cpr = input_row("CPR", f"{run_key}-warehouse-app-cpr", ASSUMED_DEFAULTS["cpr_pct"], kind="pct")
        st.caption(f"SMM {pct_text(smm(cpr))}")
        cdr = input_row("CDR", f"{run_key}-warehouse-app-cdr", ASSUMED_DEFAULTS["cdr_pct"], kind="pct")
        st.caption(f"MDR {pct_text(mdr(cdr))}")
        severity = input_row("Severity Seed", f"{run_key}-warehouse-app-severity", severity_seed, kind="pct")
    with c2:
        yield_target = input_row(
            "Yield Target", f"{run_key}-warehouse-app-yield", ASSUMED_DEFAULTS["yield_target_pct"], kind="pct")
        servicing = input_row(
            "Servicing Fee", f"{run_key}-warehouse-app-servicing", ASSUMED_DEFAULTS["servicing_fee_pct"], kind="pct")
        admin = input_row("Admin Fee", f"{run_key}-warehouse-app-admin", ASSUMED_DEFAULTS["admin_fee_pct"], kind="pct")
    with c3:
        sofr = input_row("SOFR", f"{run_key}-warehouse-app-sofr", ASSUMED_DEFAULTS["sofr_pct"], kind="pct")
        spread = input_row("Spread", f"{run_key}-warehouse-app-spread", ASSUMED_DEFAULTS["spread_pct"], kind="pct")
        advance = input_row(
            "Advance Rate", f"{run_key}-warehouse-app-advance", ASSUMED_DEFAULTS["advance_rate_pct"], kind="pct")
        st.caption(f"Facility Rate {pct_text(rate(sofr + spread))}")

    assumptions = {
        "cpr_pct": cpr,
        "cdr_pct": cdr,
        "severity_pct": severity,
        "yield_target_pct": yield_target,
        "servicing_fee_pct": servicing,
        "admin_fee_pct": admin,
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
            st.success(f"Parse memory saved to {presale_store_backend_name()}.")
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
