"""Streamlit UI for mortgage scenario analysis."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .calculator import MortgageInputs, TABLE_SECTIONS, project_waterfall

INPUT_BLUE = "#eaf2ff"
ASSET_BLUE = "#e9f7fb"
DEBT_GREEN = "#e6f7e6"
EQUITY_PEACH = "#fce4dc"
SECTION_COLORS = {
    "Assets": "#ffffff",
    "Realistic Asset Case": ASSET_BLUE,
    "Debt / Liabilities": DEBT_GREEN,
    "Equity": EQUITY_PEACH,
}

DISPLAY_LABELS = {
    "Ideal Collateral Beginning Balance": "Collateral\nBeginning\nBalance",
    "Ideal Collateral Ending Balance": "Collateral Ending\nBalance",
    "Asset Collateral Beginning Balance": "Collateral Beginning\nBalance",
    "Survival Factor": "Survival\nFactor",
    "Surviving Scheduled Payment": "Surviving\nScheduled\nPayment",
    "Surviving Scheduled Principal": "Surviving\nScheduled\nPrincipal",
    "Remaining Performing Balance": "Remaining\nPerforming\nBalance",
    "Scheduled Payment of Performing Collateral": "Scheduled\nPayment of\nPerforming\nCollateral",
    "Asset Scheduled Interest": "Scheduled\nInterest",
    "Asset Scheduled Principal": "Scheduled\nPrincipal",
    "Asset Total Principal": "Total Principal",
    "Asset Total Cashflow": "Total Cashflow",
    "Cashflow Present Value": "Cashflow\nPresent\nValue",
    "Asset Collateral Ending Balance": "Collateral\nEnding\nBalance",
    "Balance Decline %": "Balance\nDecline %",
    "Facility Beginning Balance": "Facility\nBeginning\nBalance",
    "Interest Owed": "Interest\nOwed",
    "Interest Paid": "Interest\nPaid",
    "Interest Shortfall": "Interest\nShortfall",
    "Principal Paid": "Principal\nPaid",
    "Facility Total Cashflow": "Total\nCashflow",
    "Facility Ending Balance": "Facility\nEnding\nBalance",
    "Facility Balance Decline %": "Facility\nBalance\nDecline %",
    "Advance Rate to Purchase Price": "Advance Rate\nto Purchase Px",
    "Advance Rate to Par": "Advance Rate\nto Par",
    "Levered Equity Cashflow": "Levered\nEquity\nCashflow",
    "Unlevered Equity Cashflow": "Unlevered\nEquity\nCashflow",
}

PERCENT_COLUMNS = {
    "Survival Factor",
    "Balance Decline %",
    "Facility Balance Decline %",
    "Advance Rate to Purchase Price",
    "Advance Rate to Par",
}

TABLE_SECTION_STARTS = {0, 7, 24, 34}
TABLE_SECTION_ENDS = {6, 23, 33, 35}


def render_mortgage_page() -> None:
    inject_css()

    inputs, slots = render_input_blocks()
    schedule, metrics = project_waterfall(inputs)
    render_metric_blocks(metrics, slots)

    ordered_columns = [col for cols in TABLE_SECTIONS.values() for col in cols]
    _, download_col = st.columns([4, 1])
    with download_col:
        st.download_button(
            "Download Scenario",
            data=build_excel_download(inputs, schedule, metrics),
            file_name="mortgage_scenario.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    st.markdown(
        render_excel_table_html(schedule[ordered_columns], schedule, metrics),
        unsafe_allow_html=True,
    )
    render_sensitivity_analysis(inputs)


def render_input_blocks() -> tuple[MortgageInputs, dict[str, object]]:
    top_left, top_right = st.columns(2)
    bottom_left, bottom_right = st.columns(2)

    with top_left:
        with st.container():
            st.markdown("**Amortizing Loan / Consumer Loan Calculator**")
            collateral_notional = input_row(
                "Collateral Notional", "mort-text-collateral-notional", 100_000_000.0,
                kind="money")
            coupon = input_row("Coupon", "mort-text-coupon", 15.0, kind="pct")
            term_months = int(input_row("Term (Months)", "mort-text-term", 36, kind="int"))
            cpr = input_row("CPR", "mort-text-cpr", 20.0, kind="pct")
            render_calc_row("SMM", pct_text(1 - (1 - cpr / 100) ** (1 / 12)))
            cdr = input_row("CDR", "mort-text-cdr", 5.0, kind="pct")
            render_calc_row("MDR", pct_text(1 - (1 - cdr / 100) ** (1 / 12)))
            severity = input_row("Severity", "mort-text-severity", 90.0, kind="pct")
            render_calc_row("Recoveries", pct_text(1 - severity / 100))

    with top_right:
        with st.container():
            st.markdown("**Assets / Collateral**")
            yield_target = input_row(
                "Yield Target", "mort-text-yield-target", 8.0, kind="pct")
            asset_metrics_slot = st.empty()

    with bottom_left:
        with st.container():
            st.markdown("**Debt / Warehouse Financing**")
            sofr = input_row("1mS / SOFR", "mort-text-sofr", 5.0, kind="pct")
            spread = input_row(
                "Spread / Applicable Margin", "mort-text-spread", 2.75, kind="pct")
            debt_metrics_slot = st.empty()
            advance_rate = input_row(
                "Advance Rate", "mort-text-advance-rate", 80.0, kind="pct")
            debt_tail_slot = st.empty()

    with bottom_right:
        with st.container():
            st.markdown("**Equity / Residual**")
            equity_metrics_slot = st.empty()

    inputs = MortgageInputs(
        collateral_notional=collateral_notional,
        coupon_pct=coupon,
        term_months=term_months,
        cpr_pct=cpr,
        cdr_pct=cdr,
        severity_pct=severity,
        yield_target_pct=yield_target,
        sofr_pct=sofr,
        spread_pct=spread,
        advance_rate_pct=advance_rate,
    )
    return inputs, {
        "asset_metrics": asset_metrics_slot,
        "debt_metrics": debt_metrics_slot,
        "debt_tail": debt_tail_slot,
        "equity_metrics": equity_metrics_slot,
    }


def render_metric_blocks(metrics: dict[str, float], slots: dict[str, object]) -> None:
    with slots["asset_metrics"].container():
        render_calc_row("Purchase Price / Value (%)", pct_text(metrics["Purchase Price (%)"]))
        render_calc_row("Purchase Px ($)", number_text(metrics["Purchase Price ($)"], decimals=0))
        st.markdown("<div class='mort-gap'></div>", unsafe_allow_html=True)
        render_calc_row("WAL", f"{metrics['WAL']:.3f}")
        render_calc_row("Macaulay Duration", f"{metrics['Macaulay Duration']:.3f}")
        render_calc_row("Modified Duration", f"{metrics['Modified Duration']:.3f}")
        st.markdown("<div class='mort-gap'></div>", unsafe_allow_html=True)
        render_calc_row("Cumulative Defaults", pct_text(metrics["Cumulative Defaults (%)"]))
        render_calc_row("Cumulative Net Loss", pct_text(metrics["Cumulative Net Loss (%)"]))

    with slots["debt_metrics"].container():
        render_calc_row("Facility Rate", pct_text(metrics["Facility Rate"]))

    with slots["debt_tail"].container():
        render_calc_row("Initial Notional", number_text(metrics["Initial Notional"], decimals=2))
        st.markdown("<div class='mort-gap'></div>", unsafe_allow_html=True)
        render_calc_row("Facility WAL", f"{metrics['Facility WAL']:.2f}")
        st.markdown("<div class='mort-gap'></div>", unsafe_allow_html=True)
        render_calc_row("Facility / Lender Loss (%)", pct_text(metrics["Facility / Lender Loss (%)"]))
        render_calc_row("Facility / Lender Loss ($)", number_text(metrics["Facility / Lender Loss ($)"], decimals=2))

    with slots["equity_metrics"].container():
        st.markdown("**Levered**")
        render_calc_row("Initial Equity Check", number_text(metrics["Levered Initial Equity Check"], decimals=2))
        render_calc_row("Equity IRR / Annual Yield",
                        pct_text(metrics["Levered Equity IRR / Annual Yield"]))
        st.markdown("<div class='mort-gap'></div>", unsafe_allow_html=True)
        st.markdown("**Unlevered**")
        render_calc_row("Initial Equity Check", number_text(metrics["Unlevered Initial Equity Check"], decimals=2))
        render_calc_row("Equity IRR / Annual Yield",
                        pct_text(metrics["Unlevered Equity IRR / Annual Yield"]))


def render_sensitivity_analysis(inputs: MortgageInputs) -> None:
    st.markdown("**Sensitivity Analysis**")
    cdr_df = cdr_sensitivity(inputs)
    advance_df = advance_rate_sensitivity(inputs)
    heatmap_df = cdr_advance_heatmap(inputs)

    left, right = st.columns(2)
    with left:
        st.plotly_chart(cdr_sensitivity_figure(cdr_df), use_container_width=True,
                        key="mortgage-cdr-sensitivity")
    with right:
        st.plotly_chart(advance_rate_figure(advance_df), use_container_width=True,
                        key="mortgage-advance-rate-sensitivity")
    st.plotly_chart(levered_irr_heatmap(heatmap_df), use_container_width=True,
                    key="mortgage-irr-heatmap")


def cdr_sensitivity(inputs: MortgageInputs) -> pd.DataFrame:
    rows = []
    for cdr in scenario_range(inputs.cdr_pct, lower=max(0, inputs.cdr_pct - 5),
                              upper=min(30, inputs.cdr_pct + 10), step=1):
        scenario = MortgageInputs(**{**inputs.__dict__, "cdr_pct": cdr})
        schedule, metrics = project_waterfall(scenario)
        rows.append({
            "CDR": cdr,
            "Purchase Price %": metrics["Purchase Price (%)"] * 100,
            "Purchase Price $": metrics["Purchase Price ($)"],
            "Levered IRR": metrics["Levered Equity IRR / Annual Yield"] * 100,
            "Unlevered IRR": metrics["Unlevered Equity IRR / Annual Yield"] * 100,
            "Cumulative Net Loss": metrics["Cumulative Net Loss (%)"] * 100,
            "Asset Total Cashflow": schedule["Asset Total Cashflow"].sum(),
        })
    return pd.DataFrame(rows)


def advance_rate_sensitivity(inputs: MortgageInputs) -> pd.DataFrame:
    rows = []
    for advance_rate in scenario_range(inputs.advance_rate_pct,
                                       lower=max(0, inputs.advance_rate_pct - 30),
                                       upper=min(100, inputs.advance_rate_pct + 15),
                                       step=5):
        scenario = MortgageInputs(**{**inputs.__dict__, "advance_rate_pct": advance_rate})
        schedule, metrics = project_waterfall(scenario)
        rows.append({
            "Advance Rate": advance_rate,
            "Principal Paid": schedule["Principal Paid"].sum(),
            "Interest Paid": schedule["Interest Paid"].sum(),
            "Interest Shortfall": schedule["Interest Shortfall"].sum(),
            "Lender Loss %": metrics["Facility / Lender Loss (%)"] * 100,
            "Facility WAL": metrics["Facility WAL"],
            "Levered IRR": metrics["Levered Equity IRR / Annual Yield"] * 100,
            "Initial Equity Check": metrics["Levered Initial Equity Check"],
        })
    return pd.DataFrame(rows)


def cdr_advance_heatmap(inputs: MortgageInputs) -> pd.DataFrame:
    rows = []
    cdr_values = scenario_range(inputs.cdr_pct, lower=max(0, inputs.cdr_pct - 5),
                                upper=min(25, inputs.cdr_pct + 10), step=2.5)
    advance_values = scenario_range(inputs.advance_rate_pct,
                                    lower=max(0, inputs.advance_rate_pct - 25),
                                    upper=min(100, inputs.advance_rate_pct + 15),
                                    step=5)
    for cdr in cdr_values:
        for advance_rate in advance_values:
            scenario = MortgageInputs(**{
                **inputs.__dict__,
                "cdr_pct": cdr,
                "advance_rate_pct": advance_rate,
            })
            _schedule, metrics = project_waterfall(scenario)
            rows.append({
                "CDR": cdr,
                "Advance Rate": advance_rate,
                "Levered IRR": metrics["Levered Equity IRR / Annual Yield"] * 100,
            })
    return pd.DataFrame(rows)


def scenario_range(center: float, *, lower: float, upper: float, step: float) -> list[float]:
    values = []
    current = lower
    while current <= upper + 1e-9:
        values.append(round(current, 4))
        current += step
    if not any(abs(value - center) < 1e-9 for value in values):
        values.append(round(center, 4))
    return sorted(values)


def cdr_sensitivity_figure(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["CDR"], y=df["Purchase Price %"], mode="lines+markers",
        name="Purchase Price / Value (%)"))
    fig.add_trace(go.Scatter(
        x=df["CDR"], y=df["Levered IRR"], mode="lines+markers",
        name="Levered IRR", yaxis="y2"))
    fig.add_trace(go.Scatter(
        x=df["CDR"], y=df["Unlevered IRR"], mode="lines+markers",
        name="Unlevered IRR", yaxis="y2"))
    fig.add_trace(go.Bar(
        x=df["CDR"], y=df["Cumulative Net Loss"], name="Cumulative Net Loss",
        opacity=0.25, yaxis="y2"))
    fig.update_layout(
        title="CDR Sensitivity",
        height=380,
        margin=dict(l=10, r=10, t=42, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.25),
        xaxis=dict(title="CDR (%)"),
        yaxis=dict(title="Purchase Price / Value (%)"),
        yaxis2=dict(title="IRR / Loss (%)", overlaying="y", side="right", showgrid=False),
    )
    return fig


def advance_rate_figure(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["Advance Rate"], y=df["Principal Paid"] / 1_000_000,
        name="Principal Paid ($mm)"))
    fig.add_trace(go.Bar(
        x=df["Advance Rate"], y=df["Interest Paid"] / 1_000_000,
        name="Interest Paid ($mm)"))
    fig.add_trace(go.Scatter(
        x=df["Advance Rate"], y=df["Levered IRR"], mode="lines+markers",
        name="Levered IRR", yaxis="y2"))
    fig.add_trace(go.Scatter(
        x=df["Advance Rate"], y=df["Lender Loss %"], mode="lines+markers",
        name="Lender Loss", yaxis="y2"))
    fig.update_layout(
        title="Advance Rate Sensitivity",
        height=380,
        barmode="stack",
        margin=dict(l=10, r=10, t=42, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.25),
        xaxis=dict(title="Advance Rate (%)"),
        yaxis=dict(title="Facility Payments ($mm)"),
        yaxis2=dict(title="IRR / Loss (%)", overlaying="y", side="right", showgrid=False),
    )
    return fig


def levered_irr_heatmap(df: pd.DataFrame) -> go.Figure:
    pivot = df.pivot(index="CDR", columns="Advance Rate", values="Levered IRR")
    fig = go.Figure(data=go.Heatmap(
        x=pivot.columns,
        y=pivot.index,
        z=pivot.values,
        colorscale="RdYlGn",
        colorbar=dict(title="Levered IRR (%)"),
        hovertemplate="Advance Rate: %{x:.1f}%<br>CDR: %{y:.1f}%<br>Levered IRR: %{z:.2f}%<extra></extra>",
    ))
    fig.update_layout(
        title="Levered IRR by CDR and Advance Rate",
        height=420,
        margin=dict(l=10, r=10, t=42, b=10),
        xaxis=dict(title="Advance Rate (%)"),
        yaxis=dict(title="CDR (%)"),
    )
    return fig


def input_row(label: str, key: str, value: float | int, *, kind: str) -> float:
    left, right = st.columns([1.35, 1.0], gap="small")
    left.markdown(f"<div class='mort-label-cell'>{label}</div>", unsafe_allow_html=True)
    default = default_input_text(float(value), kind)
    raw = right.text_input(label, value=default, key=key, label_visibility="collapsed")
    return parse_input_value(raw, float(value), kind)


def render_calc_row(label: str, value: str) -> None:
    left, right = st.columns([1.35, 1.0], gap="small")
    left.markdown(f"<div class='mort-label-cell'>{label}</div>", unsafe_allow_html=True)
    right.markdown(f"<div class='mort-calc-cell'>{value}</div>", unsafe_allow_html=True)


def default_input_text(value: float, kind: str) -> str:
    if kind == "money":
        return f"{value:,.0f}"
    if kind == "int":
        return f"{int(value):,}"
    if kind == "pct":
        return f"{value:.2f}%"
    return f"{value:,.2f}"


def parse_input_value(raw: str, fallback: float, kind: str) -> float:
    cleaned = raw.strip().replace(",", "").replace("$", "")
    if kind == "pct":
        cleaned = cleaned.replace("%", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    try:
        value = float(cleaned)
    except ValueError:
        st.warning(f"Could not read {raw!r}; using {default_input_text(fallback, kind)}.")
        return fallback
    if kind in {"money", "pct"}:
        return max(value, 0.0)
    if kind == "int":
        return max(round(value), 1)
    return value


def render_excel_table_html(display_df: pd.DataFrame, schedule: pd.DataFrame,
                            metrics: dict[str, float]) -> str:
    ordered = list(display_df.columns)
    debt_start = len(TABLE_SECTIONS["Assets"]) + len(TABLE_SECTIONS["Realistic Asset Case"])
    equity_start = debt_start + len(TABLE_SECTIONS["Debt / Liabilities"])
    total_cells = []
    header_cells = []
    for idx, col in enumerate(ordered):
        group = next((name for name, cols in TABLE_SECTIONS.items() if col in cols), "")
        label = ""
        if idx == 0:
            label = "Assets"
        elif idx == debt_start:
            label = "Debt / Liabilities"
        elif idx == equity_start:
            label = "Equity"
        else:
            label = format_summary_cell(summary_value(schedule, metrics, col))
        classes = table_cell_classes(group, idx)
        total_cells.append(f"<th class='mort-xl-total {classes}'>{html_escape(label)}</th>")
        header = html_escape(DISPLAY_LABELS.get(col, col)).replace("\n", "<br>")
        header_cells.append(f"<th class='{classes}'>{header}</th>")

    body_rows = []
    for _, row in display_df.iterrows():
        cells = []
        for col in ordered:
            group = next((name for name, cols in TABLE_SECTIONS.items() if col in cols), "")
            idx = ordered.index(col)
            cells.append(f"<td class='{table_cell_classes(group, idx)}'>"
                         f"{html_escape(format_table_value(col, row[col]))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    return (
        "<div class='mort-excel-wrap'><table class='mort-excel-table'>"
        f"<thead><tr>{''.join(total_cells)}</tr><tr>{''.join(header_cells)}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def excel_css_class(group: str) -> str:
    if group == "Realistic Asset Case":
        return "mort-xl-asset"
    if group == "Debt / Liabilities":
        return "mort-xl-debt"
    if group == "Equity":
        return "mort-xl-equity"
    return "mort-xl-white"


def table_cell_classes(group: str, idx: int) -> str:
    classes = [excel_css_class(group)]
    if idx in TABLE_SECTION_STARTS:
        classes.append("mort-xl-section-start")
    if idx in TABLE_SECTION_ENDS:
        classes.append("mort-xl-section-end")
    return " ".join(classes)


def format_summary_cell(value: float | str) -> str:
    if value == "":
        return ""
    return number_text(float(value), decimals=0)


def format_table_value(col: str, value: float) -> str:
    if col == "Period":
        return f"{value:,.0f}"
    if col == "Years":
        return f"{value:.2f}"
    if col in PERCENT_COLUMNS:
        return "-" if abs(value) < 1e-9 else f"{value:.1%}"
    return format_number_cell(value)


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def styled_waterfall(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    original_columns = list(df.columns)
    display = df.copy()
    display.columns = multiindex_columns(display.columns)

    def styles(_data: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame("", index=display.index, columns=display.columns)
        for idx, col in enumerate(original_columns):
            group = next((name for name, cols in TABLE_SECTIONS.items() if col in cols), "")
            color = SECTION_COLORS.get(group, "#ffffff")
            out.iloc[:, idx] = (
                f"background-color: {color}; border: 1px solid #999; "
                "font-size: 11px;"
            )
        return out

    return display.style.apply(styles, axis=None).format(formatters(display.columns))


def multiindex_columns(columns: pd.Index) -> pd.MultiIndex:
    pairs = []
    for col in columns:
        group = next((name for name, cols in TABLE_SECTIONS.items() if col in cols), "")
        pairs.append((display_group(group), DISPLAY_LABELS.get(col, col)))
    return pd.MultiIndex.from_tuples(pairs)


def display_group(group: str) -> str:
    if group == "Realistic Asset Case":
        return "Assets"
    return group


def formatters(columns: pd.MultiIndex) -> dict:
    out = {}
    for group, col in columns:
        if col == "Period":
            out[(group, col)] = "{:,.0f}"
        elif col == "Years":
            out[(group, col)] = "{:.2f}"
        elif "%" in col or "Rate" in col or "Factor" in col:
            out[(group, col)] = format_pct_cell
        else:
            out[(group, col)] = format_number_cell
    return out


def format_number_cell(value: float) -> str:
    if abs(value) < 1e-9:
        return "-"
    if value < 0:
        return f"({abs(value):,.2f})"
    return f"{value:,.2f}"


def format_pct_cell(value: float) -> str:
    if abs(value) < 1e-9:
        return "-"
    return f"{value:.1%}"


def line_chart(df: pd.DataFrame, columns: list[str]) -> go.Figure:
    fig = go.Figure()
    for col in columns:
        fig.add_trace(go.Scatter(x=df["Period"], y=df[col], mode="lines", name=col))
    fig.update_layout(
        height=360,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Period",
        yaxis_title="Value",
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.25),
    )
    return fig


def build_excel_download(inputs: MortgageInputs, schedule: pd.DataFrame,
                         metrics: dict[str, float]) -> bytes:
    import xlsxwriter
    from xlsxwriter.utility import xl_rowcol_to_cell

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_calc_mode("auto")
    ws = workbook.add_worksheet("Scenario")
    ws.hide_gridlines(2)

    title_fmt = workbook.add_format({"bold": True, "font_size": 11})
    label_fmt = workbook.add_format({"border": 1, "bold": True, "bg_color": "#f4f4f4"})
    input_int_fmt = workbook.add_format({"border": 1, "font_color": "blue", "bold": True,
                                         "bg_color": INPUT_BLUE, "num_format": "#,##0"})
    input_fmt = workbook.add_format({"border": 1, "font_color": "blue", "bold": True,
                                     "bg_color": INPUT_BLUE, "num_format": "#,##0.00"})
    input_pct_fmt = workbook.add_format({"border": 1, "font_color": "blue", "bold": True,
                                         "bg_color": INPUT_BLUE, "num_format": "0.00%"})
    calc_fmt = workbook.add_format({"border": 1, "bg_color": "white",
                                    "num_format": "#,##0.00;(#,##0.00);-"})
    calc_int_fmt = workbook.add_format({"border": 1, "bg_color": "white",
                                        "num_format": "#,##0;(#,##0);-"})
    calc_3_fmt = workbook.add_format({"border": 1, "bg_color": "white",
                                      "num_format": "0.000"})
    calc_pct_fmt = workbook.add_format({"border": 1, "bg_color": "white", "num_format": "0.00%"})
    section_fmt = workbook.add_format({"bold": True, "border": 2, "align": "left"})
    header_fmt = workbook.add_format({"bold": True, "border": 1, "align": "center",
                                      "valign": "bottom", "text_wrap": True})
    total_fmt = workbook.add_format({"bold": True, "border": 1, "align": "right",
                                     "num_format": "#,##0;(#,##0);-"})
    asset_fmt = workbook.add_format({"bg_color": ASSET_BLUE, "border": 1,
                                     "num_format": "#,##0.00;(#,##0.00);-"})
    asset_pct_fmt = workbook.add_format({"bg_color": ASSET_BLUE, "border": 1,
                                         "num_format": "0.0%;(0.0%);-"})
    debt_fmt = workbook.add_format({"bg_color": DEBT_GREEN, "border": 1,
                                    "num_format": "#,##0.00;(#,##0.00);-"})
    debt_pct_fmt = workbook.add_format({"bg_color": DEBT_GREEN, "border": 1,
                                        "num_format": "0.0%;(0.0%);-"})
    equity_fmt = workbook.add_format({"bg_color": EQUITY_PEACH, "border": 1,
                                      "num_format": "#,##0.00;(#,##0.00);-"})
    white_fmt = workbook.add_format({"border": 1, "num_format": "#,##0.00;(#,##0.00);-"})
    white_pct_fmt = workbook.add_format({"border": 1, "num_format": "0.0%;(0.0%);-"})

    write_box(ws, 0, 0, "Amortizing Loan / Consumer Loan Calculator", [
        ("Collateral Notional", inputs.collateral_notional, input_int_fmt),
        ("Coupon", inputs.coupon_pct / 100, input_pct_fmt),
        ("Term (Months)", inputs.term_months, input_int_fmt),
        ("CPR", inputs.cpr_pct / 100, input_pct_fmt),
        ("SMM", metrics["SMM"], calc_pct_fmt, "=1-(1-$B$6)^(1/12)"),
        ("CDR", inputs.cdr_pct / 100, input_pct_fmt),
        ("MDR", metrics["MDR"], calc_pct_fmt, "=1-(1-$B$8)^(1/12)"),
        ("Severity", inputs.severity_pct / 100, input_pct_fmt),
        ("Recoveries", metrics["Recoveries"], calc_pct_fmt, "=1-$B$10"),
    ], title_fmt, label_fmt)

    ordered = [col for cols in TABLE_SECTIONS.values() for col in cols]
    start_row = 14
    data_start_row = start_row + 2
    data_end_row = data_start_row + len(schedule) - 1
    table_refs = table_column_refs(ordered, data_start_row, data_end_row, xl_rowcol_to_cell)

    write_box(ws, 0, 8, "Assets / Collateral", [
        ("Yield Target", inputs.yield_target_pct / 100, input_pct_fmt),
        ("Purchase Price / Value (%)", metrics["Purchase Price (%)"], calc_pct_fmt, "=$J$5/$B$3"),
        ("Purchase Px ($)", metrics["Purchase Price ($)"], calc_int_fmt,
         f"=SUM({table_refs['Cashflow Present Value']})"),
        ("", "", None),
        ("WAL", metrics["WAL"], calc_3_fmt,
         f"=SUMPRODUCT({table_refs['Years']},{table_refs['Balance Decline %']})/"
         f"SUM({table_refs['Balance Decline %']})"),
        ("Macaulay Duration", metrics["Macaulay Duration"], calc_3_fmt,
         f"=SUMPRODUCT({table_refs['Years']},{table_refs['Cashflow Present Value']})/"
         f"SUM({table_refs['Cashflow Present Value']})"),
        ("Modified Duration", metrics["Modified Duration"], calc_3_fmt, "=$J$8/(1+$J$3/2)"),
        ("", "", None),
        ("Cumulative Defaults", metrics["Cumulative Defaults (%)"], calc_pct_fmt,
         f"=SUM({table_refs['Defaults']})/$B$3"),
        ("Cumulative Net Loss", metrics["Cumulative Net Loss (%)"], calc_pct_fmt,
         f"=SUM({table_refs['Net Loss']})/$B$3"),
    ], title_fmt, label_fmt)

    write_box(ws, 0, 25, "Debt / Warehouse Financing", [
        ("1mS / SOFR", inputs.sofr_pct / 100, input_pct_fmt),
        ("Spread / Applicable Margin", inputs.spread_pct / 100, input_pct_fmt),
        ("Facility Rate", metrics["Facility Rate"], calc_pct_fmt, "=$AA$3+$AA$4"),
        ("", "", None),
        ("Advance Rate", inputs.advance_rate_pct / 100, input_pct_fmt),
        ("Initial Notional", metrics["Initial Notional"], calc_fmt, "=$B$3*$AA$7"),
        ("", "", None),
        ("Facility WAL", metrics["Facility WAL"], calc_fmt,
         f"=SUMPRODUCT({table_refs['Years']},{table_refs['Facility Balance Decline %']})/"
         f"SUM({table_refs['Facility Balance Decline %']})"),
        ("", "", None),
        ("Facility / Lender Loss (%)", metrics["Facility / Lender Loss (%)"], calc_pct_fmt,
         f"=SUM({table_refs['Interest Shortfall']})/$AA$8"),
        ("Facility / Lender Loss ($)", metrics["Facility / Lender Loss ($)"], calc_fmt,
         f"=SUM({table_refs['Interest Shortfall']})"),
    ], title_fmt, label_fmt)

    write_box(ws, 0, 36, "Equity / Residual", [
        ("Levered", "", None),
        ("Initial Equity Check", metrics["Levered Initial Equity Check"], calc_fmt, "=$AA$8-$J$5"),
        ("Equity IRR / Annual Yield", metrics["Levered Equity IRR / Annual Yield"], calc_pct_fmt,
         f"=IRR({table_refs['Levered Equity Cashflow']})*12"),
        ("", "", None),
        ("Unlevered", "", None),
        ("Initial Equity Check", metrics["Unlevered Initial Equity Check"], calc_fmt, "=-$J$5"),
        ("Equity IRR / Annual Yield", metrics["Unlevered Equity IRR / Annual Yield"], calc_pct_fmt,
         f"=IRR({table_refs['Unlevered Equity Cashflow']})*12"),
    ], title_fmt, label_fmt)

    debt_start = len(TABLE_SECTIONS["Assets"]) + len(TABLE_SECTIONS["Realistic Asset Case"])
    equity_start = debt_start + len(TABLE_SECTIONS["Debt / Liabilities"])
    for offset, col in enumerate(ordered):
        if offset == 0:
            ws.write(start_row, offset, "Assets", section_fmt)
        elif offset == debt_start:
            ws.write(start_row, offset, "Debt / Liabilities", section_fmt)
        elif offset == equity_start:
            ws.write(start_row, offset, "Equity", section_fmt)
        else:
            formula = summary_formula(col, table_refs)
            value = summary_value(schedule, metrics, col)
            if formula:
                ws.write_formula(start_row, offset, formula, total_fmt, value)
            else:
                ws.write(start_row, offset, value, total_fmt)
        ws.write(start_row + 1, offset, DISPLAY_LABELS.get(col, col), header_fmt)

    for row_offset, (_, row) in enumerate(schedule[ordered].iterrows(), start=2):
        row_idx = start_row + row_offset
        for group, columns in TABLE_SECTIONS.items():
            for col in columns:
                value = row[col]
                fmt = excel_cell_format(group, col, white_fmt, white_pct_fmt, asset_fmt,
                                        asset_pct_fmt, debt_fmt, debt_pct_fmt, equity_fmt)
                col_idx = ordered.index(col)
                formula = waterfall_formula(col, row_idx, col_idx, ordered, xl_rowcol_to_cell)
                ws.write_formula(row_idx, col_idx, formula, fmt, value)

    for i, col in enumerate(ordered):
        ws.set_column(i, i, 14 if len(col) < 16 else 18)
    ws.freeze_panes(start_row + 2, 2)
    workbook.close()
    return output.getvalue()


def table_column_refs(ordered: list[str], first_row: int, last_row: int, cell) -> dict[str, str]:
    refs = {}
    for col_idx, col in enumerate(ordered):
        refs[col] = f"{cell(first_row, col_idx)}:{cell(last_row, col_idx)}"
    return refs


def summary_formula(col: str, refs: dict[str, str]) -> str | None:
    summed_columns = {
        "Defaults",
        "Recovery",
        "Net Loss",
        "Scheduled Payment of Performing Collateral",
        "Asset Scheduled Interest",
        "Asset Scheduled Principal",
        "Prepayments",
        "Asset Total Principal",
        "Asset Total Cashflow",
        "Interest Owed",
        "Interest Paid",
        "Principal Paid",
        "Facility Total Cashflow",
    }
    if col in summed_columns:
        return f"=SUM({refs[col]})"
    if col == "Cashflow Present Value":
        return "=$J$5"
    if col == "Facility Beginning Balance":
        return "=$AA$8"
    return None


def waterfall_formula(col: str, row_idx: int, col_idx: int, ordered: list[str], cell) -> str:
    row = row_idx + 1
    prev = row_idx
    col_map = {name: idx for idx, name in enumerate(ordered)}

    def at(name: str, excel_row: int = row) -> str:
        return cell(excel_row - 1, col_map[name])

    if row == 17:
        seed_formulas = {
            "Period": "=0",
            "Years": f"={at('Period')}/12",
            "Ideal Collateral Beginning Balance": "=0",
            "Scheduled Payment": "=0",
            "Scheduled Interest": "=0",
            "Scheduled Principal": "=0",
            "Ideal Collateral Ending Balance": "=$B$3",
            "Asset Collateral Beginning Balance": "=0",
            "Survival Factor": "=0",
            "Surviving Scheduled Payment": "=0",
            "Surviving Scheduled Principal": "=0",
            "Defaults": "=0",
            "Recovery": "=0",
            "Net Loss": "=0",
            "Remaining Performing Balance": "=0",
            "Scheduled Payment of Performing Collateral": "=0",
            "Asset Scheduled Interest": "=0",
            "Asset Scheduled Principal": "=0",
            "Prepayments": "=0",
            "Asset Total Principal": "=0",
            "Asset Total Cashflow": "=0",
            "Cashflow Present Value": "=0",
            "Asset Collateral Ending Balance": "=$B$3",
            "Balance Decline %": "=0",
            "Facility Beginning Balance": "=0",
            "Interest Owed": "=0",
            "Interest Paid": "=0",
            "Interest Shortfall": "=0",
            "Principal Paid": "=0",
            "Facility Total Cashflow": "=0",
            "Facility Ending Balance": "=$AA$8",
            "Facility Balance Decline %": "=0",
            "Advance Rate to Purchase Price": f"={at('Advance Rate to Par')}*$B$3/$J$5",
            "Advance Rate to Par": f"=IFERROR({at('Facility Ending Balance')}/{at('Asset Collateral Ending Balance')},0)",
            "Levered Equity Cashflow": "=$AA$8-$J$5",
            "Unlevered Equity Cashflow": "=-$J$5",
        }
        return seed_formulas[col]

    formulas = {
        "Period": f"={at('Period', prev)}+1",
        "Years": f"={at('Period')}/12",
        "Ideal Collateral Beginning Balance": f"={at('Ideal Collateral Ending Balance', prev)}",
        "Scheduled Payment": "=PMT($B$4/12,$B$5,-$B$3)",
        "Scheduled Interest": f"={at('Ideal Collateral Beginning Balance')}*$B$4/12",
        "Scheduled Principal": f"={at('Scheduled Payment')}-{at('Scheduled Interest')}",
        "Ideal Collateral Ending Balance": f"=MAX({at('Ideal Collateral Beginning Balance')}-{at('Scheduled Principal')},0)",
        "Asset Collateral Beginning Balance": f"={at('Asset Collateral Ending Balance', prev)}",
        "Survival Factor": f"=IFERROR({at('Asset Collateral Beginning Balance')}/{at('Ideal Collateral Beginning Balance')},0)",
        "Surviving Scheduled Payment": f"={at('Scheduled Payment')}*{at('Survival Factor')}",
        "Surviving Scheduled Principal": f"={at('Scheduled Principal')}*{at('Survival Factor')}",
        "Defaults": f"={at('Asset Collateral Beginning Balance')}*$B$9",
        "Recovery": f"={at('Defaults')}*$B$11",
        "Net Loss": f"={at('Defaults')}-{at('Recovery')}",
        "Remaining Performing Balance": f"={at('Asset Collateral Beginning Balance')}-{at('Defaults')}",
        "Scheduled Payment of Performing Collateral": (
            f"={at('Surviving Scheduled Payment')}*"
            f"IFERROR({at('Remaining Performing Balance')}/{at('Asset Collateral Beginning Balance')},0)"
        ),
        "Asset Scheduled Interest": f"={at('Remaining Performing Balance')}*$B$4/12",
        "Asset Scheduled Principal": f"={at('Scheduled Payment of Performing Collateral')}-{at('Asset Scheduled Interest')}",
        "Prepayments": f"=({at('Asset Collateral Beginning Balance')}-{at('Surviving Scheduled Principal')})*$B$7",
        "Asset Total Principal": f"={at('Prepayments')}+{at('Asset Scheduled Principal')}+{at('Recovery')}",
        "Asset Total Cashflow": f"={at('Asset Total Principal')}+{at('Asset Scheduled Interest')}",
        "Cashflow Present Value": f"={at('Asset Total Cashflow')}/(1+$J$3/12)^{at('Period')}",
        "Asset Collateral Ending Balance": (
            f"=MAX({at('Asset Collateral Beginning Balance')}-{at('Defaults')}-"
            f"{at('Asset Scheduled Principal')}-{at('Prepayments')},0)"
        ),
        "Balance Decline %": f"=({at('Asset Collateral Beginning Balance')}-{at('Asset Collateral Ending Balance')})/$B$3",
        "Facility Beginning Balance": f"={at('Facility Ending Balance', prev)}",
        "Interest Owed": f"={at('Facility Beginning Balance')}*$AA$5/12",
        "Interest Paid": f"=MIN({at('Interest Owed')},{at('Facility Total Cashflow')})",
        "Interest Shortfall": f"={at('Interest Owed')}-{at('Interest Paid')}",
        "Principal Paid": f"={at('Facility Total Cashflow')}-{at('Interest Paid')}",
        "Facility Total Cashflow": f"=MIN({at('Asset Total Cashflow')},{at('Interest Owed')}+{at('Facility Beginning Balance')})",
        "Facility Ending Balance": f"=MAX({at('Facility Beginning Balance')}-{at('Principal Paid')},0)",
        "Facility Balance Decline %": f"=({at('Facility Beginning Balance')}-{at('Facility Ending Balance')})/$AA$8",
        "Advance Rate to Purchase Price": f"={at('Advance Rate to Par')}*$B$3/$J$5",
        "Advance Rate to Par": f"=IFERROR({at('Facility Ending Balance')}/{at('Asset Collateral Ending Balance')},0)",
        "Levered Equity Cashflow": f"={at('Asset Total Cashflow')}-{at('Facility Total Cashflow')}",
        "Unlevered Equity Cashflow": f"={at('Asset Total Cashflow')}",
    }
    return formulas[col]


def write_box(ws, row: int, col: int, title: str, rows: list[tuple],
              title_fmt, label_fmt) -> None:
    ws.write(row, col, title, title_fmt)
    current = row + 2
    for row_data in rows:
        label, value, value_fmt, *formula = row_data
        if label == "":
            current += 1
            continue
        if value_fmt is None:
            ws.write(current, col, label, title_fmt)
        else:
            ws.write(current, col, label, label_fmt)
            if formula:
                ws.write_formula(current, col + 1, formula[0], value_fmt, value)
            else:
                ws.write(current, col + 1, value, value_fmt)
        current += 1


def excel_cell_format(group: str, col: str, white_fmt, white_pct_fmt, asset_fmt,
                      asset_pct_fmt, debt_fmt, debt_pct_fmt, equity_fmt):
    pct_col = col in PERCENT_COLUMNS
    if group == "Realistic Asset Case":
        return asset_pct_fmt if pct_col else asset_fmt
    if group == "Debt / Liabilities":
        return debt_pct_fmt if pct_col else debt_fmt
    if group == "Equity":
        return equity_fmt
    return white_pct_fmt if pct_col else white_fmt


def summary_value(schedule: pd.DataFrame, metrics: dict[str, float], col: str) -> float | str:
    if col in {
        "Defaults",
        "Recovery",
        "Net Loss",
        "Scheduled Payment of Performing Collateral",
        "Asset Scheduled Interest",
        "Asset Scheduled Principal",
        "Prepayments",
        "Asset Total Principal",
        "Asset Total Cashflow",
        "Interest Owed",
        "Interest Paid",
        "Principal Paid",
        "Facility Total Cashflow",
    }:
        return float(schedule[col].sum())
    if col == "Cashflow Present Value":
        return float(metrics["Purchase Price ($)"])
    if col == "Facility Beginning Balance":
        return float(metrics["Initial Notional"])
    return ""


def number_text(value: float, *, decimals: int = 0) -> str:
    formatted = f"{abs(value):,.{decimals}f}"
    if value < 0:
        return f"({formatted})"
    return formatted


def pct_text(value: float) -> str:
    return f"{value:.2%}"


def inject_css() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextInput"] input {
            color: blue;
            font-weight: 700;
            background-color: #eaf2ff;
            text-align: right;
            min-height: 2.15rem;
            border: 1px solid #222;
            border-radius: 0;
            width: 100%;
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        div[data-testid="stTextInput"],
        div[data-testid="stNumberInput"] {
            min-width: 0;
        }
        .mort-label-cell {
            border: 1px solid #222;
            padding: 0.18rem 0.35rem;
            min-height: 2.15rem;
            font-size: 0.78rem;
            font-weight: 700;
            background: #f7f7f7;
            display: flex;
            align-items: center;
            min-width: 0;
            overflow-wrap: anywhere;
            line-height: 1.1;
        }
        .mort-calc-cell {
            border: 1px solid #222;
            padding: 0.18rem 0.35rem;
            min-height: 2.15rem;
            font-size: 0.78rem;
            background: white;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            min-width: 0;
            overflow-wrap: anywhere;
            text-align: right;
            line-height: 1.1;
        }
        .mort-gap {
            height: 0.9rem;
        }
        .mort-excel-wrap {
            overflow: auto;
            max-height: 760px;
            border: 2px solid #222;
            background: white;
        }
        .mort-excel-table {
            border-collapse: collapse;
            table-layout: fixed;
            min-width: 3450px;
            width: max-content;
            font-size: 10px;
            line-height: 1.12;
        }
        .mort-excel-table th,
        .mort-excel-table td {
            border: 1px solid rgba(31, 41, 55, 0.18);
            padding: 2px 4px;
            text-align: right;
            white-space: nowrap;
            min-width: 86px;
        }
        .mort-excel-table thead th {
            font-weight: 700;
            vertical-align: bottom;
            color: #111827;
            border-bottom: 2px solid #222;
            height: 42px;
        }
        .mort-excel-table .mort-xl-total {
            height: 18px;
            border-top: 2px solid #222;
            border-bottom: 2px solid #222;
            font-size: 10px;
        }
        .mort-excel-table .mort-xl-section-start {
            border-left: 2px solid #222;
        }
        .mort-excel-table .mort-xl-section-end {
            border-right: 2px solid #222;
        }
        .mort-excel-table tbody tr:last-child td {
            border-bottom: 2px solid #222;
        }
        .mort-excel-table .mort-xl-total:first-child,
        .mort-excel-table .mort-xl-total:nth-child(25),
        .mort-excel-table .mort-xl-total:nth-child(35) {
            text-align: left;
        }
        .mort-xl-white {
            background: #ffffff;
        }
        .mort-xl-asset {
            background: #e9f7fb;
        }
        .mort-xl-debt {
            background: #e6f7e6;
        }
        .mort-xl-equity {
            background: #fce4dc;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
