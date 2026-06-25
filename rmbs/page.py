"""Streamlit UI for RMBS collateral and tranche scenario analysis."""

from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from mortgage.page import (
    ASSET_BLUE,
    DEBT_GREEN,
    EQUITY_PEACH,
    INPUT_BLUE,
    format_number_cell,
    input_row,
)

from .calculator import (
    B_NOTE_TRANCHES,
    EXCHANGEABLE_LABELS,
    RmbsInputs,
    TRANCHE_LABELS,
    TRANCHES,
    mdr,
    project_rmbs_waterfall,
    rate,
    smm,
    tranche_initial_balances,
)

TRANCHE_SIZE_FIELDS = {
    "A1": "a1_pct",
    "A1F": "a1f_pct",
    "A2": "a2_pct",
    "A3": "a3_pct",
    "M1": "m1_pct",
    "B1A": "b1a_pct",
    "B1B": "b1b_pct",
    "B2": "b2_pct",
    "B3": "b3_pct",
}
TRANCHE_COUPON_FIELDS = {
    "A1": "a1_coupon_pct",
    "A1F": "a1f_coupon_pct",
    "A2": "a2_coupon_pct",
    "A3": "a3_coupon_pct",
    "M1": "m1_coupon_pct",
    "B1A": "b1a_coupon_pct",
    "B1B": "b1b_coupon_pct",
    "B2": "b2_coupon_pct",
    "B3": "b3_coupon_pct",
}
SPACER_COLUMNS = ["Spacer 1", "Spacer 2"]

COLLATERAL_COLUMNS = [
    "Period",
    "Years",
    "Scheduled Collateral Beginning Balance",
    "Scheduled Payment",
    "Scheduled Interest",
    "Scheduled Principal",
    "Scheduled Collateral Ending Balance",
    "Payment Mode",
    "Trigger Breached",
    "Collateral Beginning Balance",
    "Survival Factor",
    "Surviving Scheduled Payment",
    "Surviving Scheduled Principal",
    "Collateral Interest",
    "Servicing Fee",
    "Admin Fee",
    "Prepayments",
    "Defaults",
    "Recoveries",
    "Net Loss",
    "Cumulative Defaults %",
    "Cumulative Net Loss %",
    "Remaining Performing Balance",
    "Scheduled Payment of Performing Collateral",
    "Scheduled Principal of Performing Collateral",
    "Principal Collections",
    "Asset Total Cashflow",
    "Cashflow Present Value",
    "Interest Available",
    "Excess Spread",
    "Residual Excess Spread",
    "Collateral Ending Balance",
    "Balance Decline %",
]

IDEAL_ASSET_COLUMNS = {
    "Period",
    "Years",
    "Scheduled Collateral Beginning Balance",
    "Scheduled Payment",
    "Scheduled Interest",
    "Scheduled Principal",
    "Scheduled Collateral Ending Balance",
}

WAREHOUSE_COLUMNS = [
    "Facility Beginning Balance",
    "Facility Interest Owed",
    "Facility Interest Paid",
    "Facility Interest Shortfall",
    "Facility Principal Paid",
    "Facility Total Cashflow",
    "Facility Ending Balance",
    "Facility Balance Decline %",
    "Advance Rate to Purchase Price",
    "Advance Rate to Par",
]

WAREHOUSE_EQUITY_COLUMNS = [
    "Warehouse Equity Beginning Balance",
    "Warehouse Equity Cashflow",
    "Warehouse Equity Ending Balance",
    "Warehouse Equity ROE",
]

UNLEVERED_EQUITY_COLUMNS = [
    "Unlevered Equity Beginning Balance",
    "Unlevered Equity Cashflow",
    "Unlevered Equity Ending Balance",
    "Unlevered Equity ROE",
]

TAKEOUT_COLUMNS = [
    "Scenario B Debt Proceeds",
    "Warehouse Takeout Surplus / (Shortfall)",
]

TRANCHE_META_COLUMNS = [
    "Bond Ending Balance",
    "Credit Enhancement %",
    "Cleanup Call Eligible",
]

SCENARIO_B_EQUITY_COLUMNS = [
    "XS/R Equity Cashflow",
    "XS/R Equity PV",
]

TRANCHE_COLUMNS = [
    f"{tranche} {field}"
    for tranche in TRANCHES
    for field in ["Beginning Balance", "Interest Paid", "Principal Paid", "Loss Allocated", "Ending Balance"]
]

WATERFALL_COLUMNS = (
    COLLATERAL_COLUMNS
    + WAREHOUSE_COLUMNS
    + WAREHOUSE_EQUITY_COLUMNS
    + UNLEVERED_EQUITY_COLUMNS
    + SPACER_COLUMNS
    + TAKEOUT_COLUMNS
    + TRANCHE_META_COLUMNS
    + TRANCHE_COLUMNS
    + SCENARIO_B_EQUITY_COLUMNS
)

SCENARIO_A_COLLATERAL_COLUMNS = [
    col for col in COLLATERAL_COLUMNS
    if col not in {
        "Payment Mode",
        "Trigger Breached",
        "Interest Available",
        "Excess Spread",
        "Residual Excess Spread",
    }
]

SCENARIO_A_COLUMNS = (
    SCENARIO_A_COLLATERAL_COLUMNS
    + WAREHOUSE_COLUMNS
    + WAREHOUSE_EQUITY_COLUMNS
    + UNLEVERED_EQUITY_COLUMNS
)

PERCENT_COLUMNS = {
    "Survival Factor",
    "Cumulative Defaults %",
    "Cumulative Net Loss %",
    "Balance Decline %",
    "Facility Balance Decline %",
    "Advance Rate to Purchase Price",
    "Advance Rate to Par",
    "Credit Enhancement %",
    "Coupon",
    "IRR",
    "Advance Rate",
    "Breakeven Loss",
    "Breakeven Loss (%)",
    "Facility IRR",
    "Equity IRR",
    "SEVERE Cushion Remaining",
    "Warehouse Equity ROE",
    "Unlevered Equity ROE",
    "Facility Loss %",
    "Facility IRR",
    "Warehouse Return",
    "Equity IRR (Lev)",
    "Unlevered Equity IRR",
    "Leverage Premium",
}

SOURCE_NOTE = (
    "Default assumptions are seeded from the OBX 2026-NQM8 presale. "
    "The model reads the subject-deal column only and uses credit-enhancement gaps for tranche sizing."
)


def render_rmbs_page() -> None:
    inject_rmbs_css()
    st.title("RMBS Scenario Model")
    st.caption(SOURCE_NOTE)

    inputs = render_input_blocks()
    schedule, tranche_summary, metrics = project_rmbs_waterfall(inputs)

    _, download_col = st.columns([4, 1])
    with download_col:
        st.download_button(
            "Download RMBS Scenario",
            data=build_excel_download(inputs, schedule, tranche_summary, metrics),
            file_name="rmbs_scenario.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

    render_summary_blocks(inputs, metrics)
    render_formula_reference()
    render_tables(schedule, tranche_summary)
    render_app_analysis_layer(inputs, schedule, tranche_summary, metrics)


def render_warehouse_page() -> None:
    inject_rmbs_css()
    st.title("Scenario A Warehouse Facility")
    st.caption(
        "Pre-securitization whole-loan financing view. This tab removes the securitization waterfall "
        "and focuses on the collateral pool, warehouse lender, and sponsor equity."
    )

    inputs = render_scenario_a_input_blocks()
    schedule, tranche_summary, metrics = project_rmbs_waterfall(inputs)

    _, download_col = st.columns([4, 1])
    with download_col:
        st.download_button(
            "Download Scenario A",
            data=build_warehouse_excel_download(inputs, schedule, metrics),
            file_name="warehouse_facility_scenario_a.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

    render_warehouse_metric_blocks(inputs, metrics)
    render_warehouse_formula_reference()
    render_warehouse_tables(schedule)
    render_warehouse_analysis_layer(inputs, schedule, tranche_summary, metrics)


def render_scenario_a_input_blocks() -> RmbsInputs:
    defaults = RmbsInputs()
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("**Collateral / Credit Inputs**")
        deal_balance = input_row("Deal Balance", "warehouse-deal-balance", defaults.deal_balance, kind="money")
        gross_coupon = input_row("WA Gross Coupon", "warehouse-gross-coupon", defaults.gross_coupon_pct, kind="pct")
        term_months = int(input_row("WA Original Term (Months)", "warehouse-term", defaults.term_months, kind="int"))
        cpr = input_row("CPR", "warehouse-cpr", defaults.cpr_pct, kind="pct")
        calc_row("SMM", pct_text(smm(cpr)))
        cdr = input_row("CDR", "warehouse-cdr", defaults.cdr_pct, kind="pct")
        calc_row("MDR", pct_text(mdr(cdr)))
        severity = input_row("Severity (Assumed)", "warehouse-severity", defaults.severity_pct, kind="pct")
        calc_row("Recoveries", pct_text(1 - rate(severity)))
        yield_target = input_row(
            "Yield Target (Assumed)", "warehouse-yield-target", defaults.yield_target_pct, kind="pct")
        servicing_fee = input_row(
            "Servicing Fee", "warehouse-servicing-fee", defaults.servicing_fee_pct, kind="pct")
        admin_fee = input_row("Admin Fee", "warehouse-admin-fee", defaults.admin_fee_pct, kind="pct")

    with c2:
        st.markdown("**Presale Deal Metrics**")
        calc_row("Collateral Type", "Expanded Prime / Non-QM")
        calc_row("Sponsor", "Onslow Bay Financial LLC")
        calc_row("View", "Scenario A - warehouse only")
        wa_fico = int(input_row("WA Original FICO", "warehouse-fico", defaults.wa_fico, kind="int"))
        wa_cltv = input_row("WA Orig CLTV", "warehouse-cltv", defaults.wa_cltv_pct, kind="pct")
        wa_dscr = input_row("WA DSCR", "warehouse-dscr", defaults.wa_dscr, kind="number")
        seasoning_months = int(input_row(
            "WA Seasoning (Months)", "warehouse-seasoning", defaults.seasoning_months, kind="int"))
        arm = input_row("ARM", "warehouse-arm", defaults.arm_pct, kind="pct")
        io = input_row("IO", "warehouse-io", defaults.io_pct, kind="pct")
        calc_row("Severity Stress Range",
                 f"{defaults.b_loss_severity_pct:.2f}% - {defaults.aaa_loss_severity_pct:.2f}%")
        calc_row("Foreclosure Freq Range",
                 f"{defaults.b_foreclosure_frequency_pct:.2f}% - {defaults.aaa_foreclosure_frequency_pct:.2f}%")

    with c3:
        st.markdown("**Warehouse Facility (Assumed - Confirm Desk)**")
        sofr = input_row("SOFR", "warehouse-sofr", defaults.sofr_pct, kind="pct")
        spread = input_row("Spread", "warehouse-spread", defaults.spread_pct, kind="pct")
        calc_row("Facility Rate", pct_text(rate(sofr + spread)))
        advance_rate = input_row("Advance Rate", "warehouse-advance-rate", defaults.advance_rate_pct, kind="pct")
        calc_row("Initial Facility Notional", number_text(deal_balance * rate(advance_rate), 0))
        calc_row("Sponsor Equity / Haircut", number_text(deal_balance * (1 - rate(advance_rate)), 0))
        calc_row("No Tranches", "Scenario B hidden on this tab")

    return RmbsInputs(
        deal_balance=deal_balance,
        gross_coupon_pct=gross_coupon,
        term_months=term_months,
        seasoning_months=seasoning_months,
        cpr_pct=cpr,
        cdr_pct=cdr,
        severity_pct=severity,
        yield_target_pct=yield_target,
        servicing_fee_pct=servicing_fee,
        admin_fee_pct=admin_fee,
        wa_fico=wa_fico,
        wa_cltv_pct=wa_cltv,
        wa_dscr=wa_dscr,
        arm_pct=arm,
        io_pct=io,
        number_of_loans=defaults.number_of_loans,
        average_loan_size=defaults.average_loan_size,
        sofr_pct=sofr,
        spread_pct=spread,
        advance_rate_pct=advance_rate,
    )


def render_input_blocks() -> RmbsInputs:
    defaults = RmbsInputs()
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("**Collateral / Credit Inputs**")
        deal_balance = input_row("Deal Balance", "rmbs-deal-balance", defaults.deal_balance, kind="money")
        gross_coupon = input_row("WA Gross Coupon", "rmbs-gross-coupon", defaults.gross_coupon_pct, kind="pct")
        term_months = int(input_row("WA Original Term (Months)", "rmbs-term", defaults.term_months, kind="int"))
        cpr = input_row("CPR", "rmbs-cpr", defaults.cpr_pct, kind="pct")
        calc_row("SMM", pct_text(smm(cpr)))
        cdr = input_row("CDR", "rmbs-cdr", defaults.cdr_pct, kind="pct")
        calc_row("MDR", pct_text(mdr(cdr)))
        severity = input_row("Severity (Assumed)", "rmbs-severity", defaults.severity_pct, kind="pct")
        calc_row("Recoveries", pct_text(1 - rate(severity)))
        yield_target = input_row(
            "Yield Target (Assumed)", "rmbs-yield-target", defaults.yield_target_pct, kind="pct")
        servicing_fee = input_row(
            "Servicing Fee", "rmbs-servicing-fee", defaults.servicing_fee_pct, kind="pct")
        admin_fee = input_row("Admin Fee", "rmbs-admin-fee", defaults.admin_fee_pct, kind="pct")

    with c2:
        st.markdown("**Presale Deal Metrics**")
        calc_row("Collateral Type", "Expanded Prime / Non-QM")
        calc_row("Sponsor", "Onslow Bay Financial LLC")
        calc_row("Structure", "Modified Pro-Rata")
        aaa_attachment = input_row(
            "Original Attachment to AAA", "rmbs-aaa-attachment",
            defaults.aaa_attachment_pct, kind="pct")
        wa_fico = int(input_row("WA Original FICO", "rmbs-fico", defaults.wa_fico, kind="int"))
        wa_cltv = input_row("WA Orig CLTV", "rmbs-cltv", defaults.wa_cltv_pct, kind="pct")
        wa_dscr = input_row("WA DSCR", "rmbs-dscr", defaults.wa_dscr, kind="number")
        seasoning_months = int(input_row(
            "WA Seasoning (Months)", "rmbs-seasoning", defaults.seasoning_months, kind="int"))
        arm = input_row("ARM", "rmbs-arm", defaults.arm_pct, kind="pct")
        io = input_row("IO", "rmbs-io", defaults.io_pct, kind="pct")
        calc_row("Severity Stress Range",
                 f"{defaults.b_loss_severity_pct:.2f}% - {defaults.aaa_loss_severity_pct:.2f}%")
        calc_row("Foreclosure Freq Range",
                 f"{defaults.b_foreclosure_frequency_pct:.2f}% - {defaults.aaa_foreclosure_frequency_pct:.2f}%")
        calc_row("Number of Loans", "Not pulled")
        calc_row("Average Loan Size", "Not pulled")

    with c3:
        st.markdown("**Warehouse / Analytics (Assumed - Confirm Desk)**")
        sofr = input_row("SOFR", "rmbs-sofr", defaults.sofr_pct, kind="pct")
        spread = input_row("Spread", "rmbs-spread", defaults.spread_pct, kind="pct")
        calc_row("Facility Rate", pct_text(rate(sofr + spread)))
        advance_rate = input_row("Advance Rate", "rmbs-advance-rate", defaults.advance_rate_pct, kind="pct")
        calc_row("Initial Facility Notional",
                 number_text(deal_balance * rate(advance_rate), 0))

    t1, t2, t3 = st.columns(3)
    with t1:
        st.markdown("**Tranching / Triggers**")
        lockout_months = int(input_row(
            "Stepdown Lockout", "rmbs-lockout", defaults.lockout_months, kind="int"))
        cum_loss_trigger = input_row(
            "Cum Loss Trigger", "rmbs-loss-trigger",
            defaults.stepdown_cum_loss_trigger_pct, kind="pct")
        dq_trigger = input_row(
            "DQ Trigger", "rmbs-dq-trigger", defaults.stepdown_dq_trigger_pct, kind="pct")
        cleanup_call = input_row(
            "Clean-up Call Factor", "rmbs-cleanup-call",
            defaults.cleanup_call_factor_pct, kind="pct")

    with t2:
        st.markdown("**Scenario B Debt Note Sizes**")
        tranche_sizes = {
            tranche: input_row(
                f"{TRANCHE_LABELS[tranche]} Size",
                f"rmbs-{tranche.lower()}-pct",
                getattr(defaults, TRANCHE_SIZE_FIELDS[tranche]),
                kind="pct",
            )
            for tranche in TRANCHES
        }

    with t3:
        st.markdown("**Scenario B Debt Note Coupons**")
        tranche_coupons = {
            tranche: input_row(
                f"{TRANCHE_LABELS[tranche]} Coupon",
                f"rmbs-{tranche.lower()}-cpn",
                getattr(defaults, TRANCHE_COUPON_FIELDS[tranche]),
                kind="pct",
            )
            for tranche in TRANCHES
        }
        calc_row("Strict Equity", "XS + R, no principal balance")

    return RmbsInputs(
        deal_balance=deal_balance,
        gross_coupon_pct=gross_coupon,
        term_months=term_months,
        seasoning_months=seasoning_months,
        cpr_pct=cpr,
        cdr_pct=cdr,
        severity_pct=severity,
        yield_target_pct=yield_target,
        servicing_fee_pct=servicing_fee,
        admin_fee_pct=admin_fee,
        aaa_attachment_pct=aaa_attachment,
        wa_fico=wa_fico,
        wa_cltv_pct=wa_cltv,
        wa_dscr=wa_dscr,
        arm_pct=arm,
        io_pct=io,
        number_of_loans=defaults.number_of_loans,
        average_loan_size=defaults.average_loan_size,
        lockout_months=lockout_months,
        stepdown_cum_loss_trigger_pct=cum_loss_trigger,
        stepdown_dq_trigger_pct=dq_trigger,
        cleanup_call_factor_pct=cleanup_call,
        sofr_pct=sofr,
        spread_pct=spread,
        advance_rate_pct=advance_rate,
        **{field: tranche_sizes[tranche] for tranche, field in TRANCHE_SIZE_FIELDS.items()},
        **{field: tranche_coupons[tranche] for tranche, field in TRANCHE_COUPON_FIELDS.items()},
    )


def render_summary_blocks(inputs: RmbsInputs, metrics: dict[str, float]) -> None:
    tranche_balances = tranche_initial_balances(inputs)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Collateral Metrics**")
        calc_row("Deal Balance", number_text(inputs.deal_balance, 0))
        calc_row("SMM", pct_text(smm(inputs.cpr_pct)))
        calc_row("MDR", pct_text(mdr(inputs.cdr_pct)))
        calc_row("Recoveries", pct_text(1 - rate(inputs.severity_pct)))
    with c2:
        st.markdown("**PV / Duration**")
        calc_row("Purchase Price / Value (%)", pct_text(metrics["Purchase Price (%)"]))
        calc_row("Purchase Px ($)", number_text(metrics["Purchase Price ($)"], 0))
        calc_row("Collateral WAL", f"{metrics['Collateral WAL']:.2f}")
        calc_row("Macaulay Duration", f"{metrics['Macaulay Duration']:.2f}")
        calc_row("Modified Duration", f"{metrics['Modified Duration']:.2f}")
    with c3:
        st.markdown("**Credit Metrics**")
        calc_row("Cumulative Defaults", pct_text(metrics["Cumulative Defaults %"]))
        calc_row("Initial Senior CE", pct_text(metrics["Initial Senior Credit Enhancement"]))
        calc_row("Final Senior CE", pct_text(metrics["Final Senior Credit Enhancement"]))
        calc_row("Cumulative Net Loss", pct_text(metrics["Cumulative Net Loss %"]))
        calc_row("First Trigger Period", number_text(metrics["First Trigger Period"], 0))
    c4, c5 = st.columns(2)
    with c4:
        st.markdown("**Scenario A - Warehouse Metrics**")
        calc_row("Facility Rate", pct_text(metrics["Facility Rate"]))
        calc_row("Initial Notional", number_text(metrics["Initial Facility Notional"], 0))
        calc_row("Equity / Haircut", number_text(metrics["Warehouse Equity / Haircut"], 0))
        calc_row("Asset Income", number_text(metrics["Warehouse Asset Income"], 0))
        calc_row("Funding Cost", number_text(metrics["Warehouse Funding Cost"], 0))
        calc_row("Net Margin", number_text(metrics["Warehouse Net Margin"], 0))
        calc_row("Levered ROE", pct_text(metrics["Warehouse Levered ROE"]))
        calc_row("Levered Equity IRR", pct_text(metrics["Scenario A Equity IRR - Levered"]))
        calc_row("Unlevered Equity IRR", pct_text(metrics["Scenario A Equity IRR - Unlevered"]))
        calc_row("Leverage Premium", pct_text(metrics["Scenario A Leverage Premium"]))
        calc_row("Facility WAL", f"{metrics['Facility WAL']:.2f}")
        calc_row("Lender Loss (%)", pct_text(metrics["Facility / Lender Loss %"]))
        calc_row("Lender Loss ($)", number_text(metrics["Facility / Lender Loss $"], 0))
    with c5:
        st.markdown("**Scenario B - Securitization Metrics**")
        calc_row("Debt Proceeds", number_text(metrics["Scenario B Debt Proceeds"], 0))
        calc_row("Takeout Surplus / (Shortfall)",
                 number_text(metrics["Warehouse Takeout Surplus / (Shortfall)"], 0))
        calc_row("Class A-1 Balance", number_text(tranche_balances["A1"], 0))
        calc_row("Subordination to A-1", number_text(inputs.deal_balance - tranche_balances["A1"], 0))
        calc_row("XS/R Strict Equity Value", number_text(metrics["XS/R Strict Equity Value"], 0))
        calc_row("Sponsor Retained Position", number_text(metrics["Sponsor Retained Position"], 0))
        calc_row("Senior WAL", f"{metrics['Senior WAL']:.2f}")
        calc_row("Senior IRR", pct_text(metrics["Senior IRR"]))
        calc_row("Total Excess Spread", number_text(metrics["Total Excess Spread"], 0))
        calc_row("Residual Excess Spread", number_text(metrics["Residual Excess Spread"], 0))
        calc_row("Lockout Months", number_text(inputs.lockout_months, 0))
        calc_row("Clean-up Call", pct_text(rate(inputs.cleanup_call_factor_pct)))


def render_warehouse_metric_blocks(inputs: RmbsInputs, metrics: dict[str, float]) -> None:
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Collateral Metrics**")
        calc_row("Deal Balance", number_text(inputs.deal_balance, 0))
        calc_row("SMM", pct_text(smm(inputs.cpr_pct)))
        calc_row("MDR", pct_text(mdr(inputs.cdr_pct)))
        calc_row("Recoveries", pct_text(1 - rate(inputs.severity_pct)))
        calc_row("Cumulative Defaults", pct_text(metrics["Cumulative Defaults %"]))
        calc_row("Cumulative Net Loss", pct_text(metrics["Cumulative Net Loss %"]))
    with c2:
        st.markdown("**PV / Duration**")
        calc_row("Purchase Price / Value (%)", pct_text(metrics["Purchase Price (%)"]))
        calc_row("Purchase Px ($)", number_text(metrics["Purchase Price ($)"], 0))
        calc_row("Collateral WAL", f"{metrics['Collateral WAL']:.2f}")
        calc_row("Macaulay Duration", f"{metrics['Macaulay Duration']:.2f}")
        calc_row("Modified Duration", f"{metrics['Modified Duration']:.2f}")
    with c3:
        st.markdown("**Warehouse / Equity Metrics**")
        calc_row("Facility Rate", pct_text(metrics["Facility Rate"]))
        calc_row("Initial Notional", number_text(metrics["Initial Facility Notional"], 0))
        calc_row("Equity / Haircut", number_text(metrics["Warehouse Equity / Haircut"], 0))
        calc_row("Facility WAL", f"{metrics['Facility WAL']:.2f}")
        calc_row("Lender Loss (%)", pct_text(metrics["Facility / Lender Loss %"]))
        calc_row("Levered Equity IRR", pct_text(metrics["Scenario A Equity IRR - Levered"]))
        calc_row("Unlevered Equity IRR", pct_text(metrics["Scenario A Equity IRR - Unlevered"]))
        calc_row("Leverage Premium", pct_text(metrics["Scenario A Leverage Premium"]))


def render_warehouse_tables(schedule: pd.DataFrame) -> None:
    st.markdown("**Excel View - Scenario A Warehouse Facility**")
    st.caption(
        "White columns are ideal scheduled collateral; blue columns are credit-adjusted collateral; "
        "green columns are the facility lender; red columns are sponsor equity."
    )
    table = warehouse_table(schedule)
    st.markdown(render_waterfall_html(table), unsafe_allow_html=True)


def warehouse_table(schedule: pd.DataFrame) -> pd.DataFrame:
    table = schedule.copy()
    return table[[col for col in SCENARIO_A_COLUMNS if col in table.columns]].copy()


def render_charts(schedule: pd.DataFrame, tranche_summary: pd.DataFrame) -> None:
    st.markdown("**RMBS Waterfall Analysis**")
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(balance_figure(schedule), width="stretch", key="rmbs-balances")
    with c2:
        st.plotly_chart(tranche_cashflow_figure(tranche_summary), width="stretch", key="rmbs-tranche-cashflows")
    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(credit_figure(schedule), width="stretch", key="rmbs-credit")
    with c4:
        st.plotly_chart(excess_spread_figure(schedule), width="stretch", key="rmbs-excess-spread")


def render_tables(schedule: pd.DataFrame, tranche_summary: pd.DataFrame) -> None:
    st.markdown("**Tranche Summary**")
    st.dataframe(
        format_table(tranche_summary),
        width="stretch",
        hide_index=True,
    )
    st.markdown("**Excel View - RMBS Waterfall**")
    table = waterfall_table(schedule)
    st.markdown(render_waterfall_html(table), unsafe_allow_html=True)


def waterfall_table(schedule: pd.DataFrame) -> pd.DataFrame:
    table = schedule.copy()
    for spacer in SPACER_COLUMNS:
        table[spacer] = ""
    return table[[col for col in WATERFALL_COLUMNS if col in table.columns]].copy()


def render_sensitivity_analysis(inputs: RmbsInputs) -> None:
    st.markdown("**Sensitivity Analysis**")
    cdr_df = cdr_sensitivity(inputs)
    attachment_df = attachment_sensitivity(inputs)
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(cdr_sensitivity_figure(cdr_df), width="stretch", key="rmbs-cdr-sensitivity")
    with c2:
        st.plotly_chart(attachment_sensitivity_figure(attachment_df), width="stretch", key="rmbs-attachment")


PRESALE_LOSS_BENCHMARKS = {
    "B": 0.85,
    "BBB": 3.85,
    "AA": 10.90,
    "AAA": 14.30,
}
AAA_SAFETY_THRESHOLD = PRESALE_LOSS_BENCHMARKS["AAA"]

KPI_HELP = {
    "Warehouse Return": (
        "SOFR + financing_spread",
        "What the lender earns on the advance. Thin spread, low risk.",
    ),
    "Equity Return": (
        "IRR(-initial_equity, residual_t)",
        "What the first-loss equity earns after debt service.",
    ),
    "Breakeven Loss": (
        "1 - advance_rate = equity_cushion / deal_balance",
        "Cumulative pool loss the haircut absorbs before the lender loses a dollar.",
    ),
    "Equity Cushion": (
        "(1 - advance_rate) * deal_balance",
        "First-loss capital beneath the facility = lender protection.",
    ),
    "Peak Exposure": (
        "MAX(facility_balance)",
        "Largest dollars the lender ever has at risk; sizes the line.",
    ),
    "Leverage Pickup": (
        "levered_IRR - unlevered_IRR",
        "Extra return from financing. Negative means the facility creates negative carry.",
    ),
    "MOIC": (
        "SUM(equity_distributions) / initial_equity",
        "Cash multiple. Less than 1.0x means equity lost money.",
    ),
    "Payback": (
        "First period where cumulative equity cashflow >= initial equity",
        "Years to return the equity check.",
    ),
    "Sponsor Retained": (
        "B-notes + PV(XS/R residual)",
        "Risk-retention bundle in the securitization view, not pure Scenario A equity.",
    ),
}

CHART_HELP = {
    "Collateral Cashflow Split": (
        "collateral_CF = facility_interest + facility_principal + residual_to_equity",
        "Where every dollar of collateral cash goes. Equity only gets paid after the facility.",
    ),
    "Facility vs Collateral Balance": (
        "gap = collateral_balance - facility_balance = cushion_t",
        "The shaded gap is the live equity cushion; if collateral falls into the facility line, the lender is under-collateralized.",
    ),
    "Leverage Curve": (
        "levered_IRR(advance) for advance in 78%..92%",
        "How leverage amplifies equity IRR. Markers show lender, equity, and balanced optima.",
    ),
    "Facility Loss vs Pool Loss": (
        "facility_loss = MAX(cum_pool_loss - (1 - advance_rate), 0)",
        "The lender stays at zero loss until pool loss crosses the breakeven line.",
    ),
}

NAMED_SCENARIOS = {
    "BASE": {"cdr_pct": 0.50, "severity_pct": 35.0, "cpr_pct": 8.0},
    "BENIGN": {"cdr_pct": 0.25, "severity_pct": 25.0, "cpr_pct": 12.0},
    "MILD": {"cdr_pct": 1.0, "severity_pct": 35.0, "cpr_pct": 8.0},
    "SEVERE": {"cdr_pct": 2.0, "severity_pct": 50.0, "cpr_pct": 5.0, "sofr_delta": 2.0},
    "CRISIS": {
        "cdr_pct": 3.0,
        "severity_pct": 50.0,
        "cpr_pct": 5.0,
        "sofr_delta": 2.0,
        "advance_rate_pct": 92.0,
    },
}


def render_app_analysis_layer(
    base_inputs: RmbsInputs,
    base_schedule: pd.DataFrame,
    base_tranche_summary: pd.DataFrame,
    base_metrics: dict[str, float],
) -> None:
    st.markdown("**Analysis Layer - Live Readout From Excel Model**")
    st.caption(
        "These dashboards read from the live model outputs. Changing a scenario reruns the same cashflow engine; "
        "the workbook remains the downloadable source-of-truth artifact."
    )

    scenario_name = st.selectbox(
        "Scenario",
        list(NAMED_SCENARIOS.keys()) + ["CUSTOM"],
        index=0,
        key="rmbs-analysis-scenario",
    )
    scenario_seed = apply_named_scenario(base_inputs, scenario_name)
    control_key = scenario_name.lower().replace(" ", "-")

    with st.expander("Stress Controls", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            cdr = st.slider(
                "CDR", 0.25, 3.0, float(scenario_seed.cdr_pct), 0.25,
                format="%.2f%%", key=f"rmbs-stress-cdr-{control_key}"
            )
            severity = st.slider(
                "Severity", 25.0, 50.0, float(scenario_seed.severity_pct), 1.0,
                format="%.0f%%", key=f"rmbs-stress-severity-{control_key}"
            )
        with c2:
            cpr = st.slider(
                "CPR", 5.0, 20.0, float(scenario_seed.cpr_pct), 1.0,
                format="%.0f%%", key=f"rmbs-stress-cpr-{control_key}"
            )
            sofr = st.slider(
                "SOFR", 0.0, 8.0, float(scenario_seed.sofr_pct), 0.25,
                format="%.2f%%", key=f"rmbs-stress-sofr-{control_key}"
            )
        with c3:
            spread = st.slider(
                "Financing Spread", 0.50, 5.00, float(scenario_seed.spread_pct), 0.25,
                format="%.2f%%", key=f"rmbs-stress-spread-{control_key}"
            )
            advance = st.slider(
                "Advance Rate", 78.0, 92.0, float(scenario_seed.advance_rate_pct), 1.0,
                format="%.0f%%", key=f"rmbs-stress-advance-{control_key}"
            )

    analysis_inputs = RmbsInputs(**{
        **asdict(scenario_seed),
        "cdr_pct": cdr,
        "severity_pct": severity,
        "cpr_pct": cpr,
        "sofr_pct": sofr,
        "spread_pct": spread,
        "advance_rate_pct": advance,
    })
    if analysis_inputs == base_inputs:
        schedule, tranche_summary, metrics = base_schedule, base_tranche_summary, base_metrics
    else:
        schedule, tranche_summary, metrics = project_rmbs_waterfall(analysis_inputs)
    results = build_results_object(analysis_inputs, schedule, tranche_summary, metrics)
    advance_df, optima = advance_optimization(analysis_inputs)
    sanity = analysis_sanity_checks(analysis_inputs, results, advance_df, optima)

    render_headline_callouts(analysis_inputs, results, sanity)
    view1, view2 = st.columns(2)
    with view1:
        render_warehouse_view(results)
    with view2:
        render_equity_view(analysis_inputs, results, advance_df, optima)

    render_stress_test_view(analysis_inputs)
    render_optimal_advance_section(advance_df, optima, key_prefix="rmbs")
    render_investment_report(analysis_inputs, results, advance_df, optima, full_rmbs=True)
    render_assumptions_sources_panel()


def build_results_object(
    inputs: RmbsInputs,
    schedule: pd.DataFrame,
    tranche_summary: pd.DataFrame,
    metrics: dict[str, float],
) -> dict[str, object]:
    return {
        "inputs": {
            "deal_balance": inputs.deal_balance,
            "wa_coupon": inputs.gross_coupon_pct,
            "term": inputs.term_months,
            "seasoning": inputs.seasoning_months,
            "cpr": inputs.cpr_pct,
            "cdr": inputs.cdr_pct,
            "severity": inputs.severity_pct,
            "recoveries": 1 - rate(inputs.severity_pct),
            "yield_target": inputs.yield_target_pct,
            "servicing": inputs.servicing_fee_pct,
            "admin": inputs.admin_fee_pct,
            "sofr": inputs.sofr_pct,
            "financing_spread": inputs.spread_pct,
            "advance_rate": inputs.advance_rate_pct,
        },
        "collateral": schedule[[
            "Period",
            "Collateral Ending Balance",
            "Collateral Interest",
            "Principal Collections",
            "Prepayments",
            "Defaults",
            "Recoveries",
            "Net Loss",
            "Asset Total Cashflow",
            "Cumulative Net Loss %",
        ]].to_dict("records"),
        "facility": schedule[[
            "Period",
            "Facility Beginning Balance",
            "Facility Interest Owed",
            "Facility Interest Paid",
            "Facility Interest Shortfall",
            "Facility Principal Paid",
            "Facility Total Cashflow",
            "Facility Ending Balance",
            "Advance Rate to Par",
            "Advance Rate to Purchase Price",
        ]].to_dict("records"),
        "equity": {
            "scenarioA_levered_cf": schedule["Warehouse Equity Cashflow"].tolist(),
            "scenarioA_unlevered_cf": schedule["Unlevered Equity Cashflow"].tolist(),
            "xs_r_strict_equity_cf": schedule["XS/R Equity Cashflow"].tolist(),
            "sponsor_retained": metrics["Sponsor Retained Position"],
        },
        "tranche_stack": tranche_summary.to_dict("records"),
        "metrics": metrics,
        "schedule": schedule,
        "tranche_summary": tranche_summary,
    }


def apply_named_scenario(inputs: RmbsInputs, scenario_name: str) -> RmbsInputs:
    if scenario_name == "CUSTOM":
        return inputs
    overrides = dict(NAMED_SCENARIOS[scenario_name])
    sofr_delta = overrides.pop("sofr_delta", 0.0)
    if sofr_delta:
        overrides["sofr_pct"] = inputs.sofr_pct + sofr_delta
    return RmbsInputs(**{**asdict(inputs), **overrides})


def render_headline_callouts(inputs: RmbsInputs, results: dict[str, object], sanity: list[str] | None = None) -> None:
    metrics = results["metrics"]
    breakeven = structural_breakeven_loss_pct(inputs)
    breakeven_value = f"{breakeven:.1f}%"
    current_loss = metrics["Cumulative Net Loss %"] * 100
    breakeven_detail = f"Current modeled cumulative loss {current_loss:.1f}%"
    st.markdown(
        "<div class='rmbs-kpi-grid'>"
        + analysis_kpi_card(
            "Warehouse Return",
            pct_text(metrics["Facility Rate"]),
            f"Facility WAL {metrics['Facility WAL']:.2f} yrs",
            *KPI_HELP["Warehouse Return"],
        )
        + analysis_kpi_card(
            "Equity Return",
            pct_text(metrics["Scenario A Equity IRR - Levered"]),
            f"Unlevered {pct_text(metrics['Scenario A Equity IRR - Unlevered'])}",
            *KPI_HELP["Equity Return"],
        )
        + analysis_kpi_card(
            "Breakeven Loss",
            breakeven_value,
            breakeven_detail,
            *KPI_HELP["Breakeven Loss"],
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    if sanity:
        st.error("Sanity check issue: " + " | ".join(sanity))


def analysis_kpi_card(
    label: str,
    value: str,
    detail: str,
    formula: str | None = None,
    question: str | None = None,
) -> str:
    tooltip = ""
    if formula or question:
        tooltip = f"Formula: {formula or '-'}\nQuestion: {question or '-'}"
    return (
        "<div class='rmbs-kpi-card'>"
        f"<div class='rmbs-kpi-label'>{html_escape(label)}{info_icon(tooltip)}</div>"
        f"<div class='rmbs-kpi-value'>{html_escape(value)}</div>"
        f"<div class='rmbs-kpi-detail'>{html_escape(detail)}</div>"
        "</div>"
    )


def info_icon(tooltip: str) -> str:
    if not tooltip:
        return ""
    return f" <span class='rmbs-info' title='{html_escape(tooltip)}'>i</span>"


def chart_heading(title: str, formula: str, question: str) -> None:
    tooltip = f"Formula: {formula}\nQuestion: {question}"
    st.markdown(
        f"<div class='rmbs-chart-heading'>{html_escape(title)}{info_icon(tooltip)}</div>",
        unsafe_allow_html=True,
    )


def render_warehouse_view(
    results: dict[str, object],
    key_prefix: str = "rmbs",
    benchmarks: dict[str, float] | None = None,
) -> None:
    st.markdown("**Warehouse Facility**")
    metrics = results["metrics"]
    schedule: pd.DataFrame = results["schedule"]
    inputs = results["inputs"]
    peak_exposure = float(schedule["Facility Beginning Balance"].max())
    cushion = inputs["deal_balance"] - metrics["Initial Facility Notional"]
    st.markdown(
        "<div class='rmbs-mini-kpi-grid'>"
        + analysis_kpi_card("Peak Exposure", f"{number_text(peak_exposure / 1_000_000, 1)}mm",
                            f"{pct_text(peak_exposure / inputs['deal_balance'])} of pool",
                            *KPI_HELP["Peak Exposure"])
        + analysis_kpi_card("Equity Cushion", number_text(cushion, 0),
                            "Collateral value below facility advance",
                            *KPI_HELP["Equity Cushion"])
        + "</div>",
        unsafe_allow_html=True,
    )

    chart_heading("Collateral Cashflow Split", *CHART_HELP["Collateral Cashflow Split"])
    st.plotly_chart(facility_cashflow_stack_figure(schedule), width="stretch",
                    key=f"{key_prefix}-facility-cf-stack")
    chart_heading("Facility vs Collateral Balance", *CHART_HELP["Facility vs Collateral Balance"])
    st.plotly_chart(facility_cushion_figure(schedule), width="stretch",
                    key=f"{key_prefix}-facility-cushion")
    chart_heading("Facility Loss vs Pool Loss", *CHART_HELP["Facility Loss vs Pool Loss"])
    st.plotly_chart(facility_loss_curve_figure(results, benchmarks), width="stretch",
                    key=f"{key_prefix}-facility-loss-curve")


def render_equity_view(
    inputs: RmbsInputs,
    results: dict[str, object],
    advance_df: pd.DataFrame | None = None,
    optima: dict[str, int] | None = None,
) -> None:
    st.markdown("**Equity Return**")
    metrics = results["metrics"]
    schedule: pd.DataFrame = results["schedule"]
    tranche_summary: pd.DataFrame = results["tranche_summary"]
    levered_moic = equity_moic(
        -(metrics["Warehouse Equity / Haircut"]),
        schedule.loc[schedule["Period"] > 0, "Warehouse Equity Cashflow"],
    )
    unlevered_moic = equity_moic(
        -inputs.deal_balance,
        schedule.loc[schedule["Period"] > 0, "Unlevered Equity Cashflow"],
    )
    st.markdown(
        "<div class='rmbs-mini-kpi-grid'>"
        + analysis_kpi_card(
            "Levered / Unlevered IRR",
            f"{pct_text(metrics['Scenario A Equity IRR - Levered'])} / "
            f"{pct_text(metrics['Scenario A Equity IRR - Unlevered'])}",
            f"Pickup {pct_text(metrics['Scenario A Leverage Premium'])}",
            *KPI_HELP["Equity Return"],
        )
        + analysis_kpi_card(
            "MOIC",
            f"{levered_moic:.2f}x / {unlevered_moic:.2f}x",
            "Levered / unlevered",
            *KPI_HELP["MOIC"],
        )
        + analysis_kpi_card(
            "Sponsor Retained",
            number_text(metrics["Sponsor Retained Position"], 0),
            "B-notes plus XS/R strict equity value",
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs(["IRR vs Advance", "Annual Cashflow", "Tranche Loss"])
    with tab1:
        chart_heading("Leverage Curve", *CHART_HELP["Leverage Curve"])
        st.plotly_chart(leverage_curve_figure(inputs, advance_df, optima), width="stretch", key="rmbs-leverage-curve")
    with tab2:
        chart_heading(
            "Annual Equity Distributions",
            "annual_equity_distribution = SUM(monthly_equity_cashflow by year)",
            "How much cash equity receives by year, levered versus unlevered.",
        )
        st.plotly_chart(annual_equity_distribution_figure(schedule), width="stretch",
                        key="rmbs-annual-equity-bars")
    with tab3:
        st.plotly_chart(tranche_writedown_ladder_figure(tranche_summary), width="stretch",
                        key="rmbs-writedown-ladder")


def render_stress_test_view(inputs: RmbsInputs) -> None:
    st.markdown("**View 3 - Stress Tests**")
    h1, h2 = st.columns(2)
    with h1:
        st.plotly_chart(equity_irr_heatmap_figure(inputs), width="stretch", key="rmbs-equity-heatmap")
    with h2:
        st.plotly_chart(advance_spread_heatmap_figure(inputs), width="stretch", key="rmbs-adv-spread-heatmap")
    h3, h4 = st.columns(2)
    with h3:
        st.plotly_chart(tornado_figure(inputs), width="stretch", key="rmbs-tornado")
    with h4:
        st.plotly_chart(named_scenario_loss_figure(inputs), width="stretch", key="rmbs-scenario-loss")
    summary = named_scenario_summary(inputs)
    st.dataframe(format_table(summary), width="stretch", hide_index=True)


def render_assumptions_sources_panel() -> None:
    with st.expander("Assumptions & Sources", expanded=False):
        st.markdown(
            """
**Sourced from OBX 2026-NQM8 presale subject-deal column**

Deal balance, WA current rate, WA original term, WA seasoning, FICO, CLTV, DSCR, loss-severity stress range, foreclosure-frequency stress range, and credit-enhancement attachment points.

**ASSUMED - seed / range / confirm desk**

SOFR, financing spread, advance rate, CPR, annual CDR, yield target, servicing/admin fees, tranche coupons, lockout, clean-up call, and performance triggers.

**Parsing control**

Collateral values use the OBX 2026-NQM8 column only. Tranche sizes use credit-enhancement gaps only, not preliminary amount rows, so exchangeable senior certificates are not double-counted.
            """
        )


def render_warehouse_analysis_layer(
    base_inputs: RmbsInputs,
    base_schedule: pd.DataFrame,
    base_tranche_summary: pd.DataFrame,
    base_metrics: dict[str, float],
) -> None:
    st.markdown("**Scenario A Analysis Layer - Live Readout From Warehouse Model**")
    st.caption(
        "These charts read from the same Scenario A cashflow vectors shown above. "
        "No tranche waterfall or Scenario B takeout is included on this tab."
    )

    scenario_name = st.selectbox(
        "Scenario",
        list(NAMED_SCENARIOS.keys()) + ["CUSTOM"],
        index=0,
        key="warehouse-analysis-scenario",
    )
    scenario_seed = apply_named_scenario(base_inputs, scenario_name)
    control_key = scenario_name.lower().replace(" ", "-")

    with st.expander("Stress Controls", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            cdr = st.slider("CDR", 0.25, 3.0, float(scenario_seed.cdr_pct), 0.25,
                            format="%.2f%%", key=f"warehouse-stress-cdr-{control_key}")
            severity = st.slider("Severity", 25.0, 50.0, float(scenario_seed.severity_pct), 1.0,
                                 format="%.0f%%", key=f"warehouse-stress-severity-{control_key}")
        with c2:
            cpr = st.slider("CPR", 5.0, 20.0, float(scenario_seed.cpr_pct), 1.0,
                            format="%.0f%%", key=f"warehouse-stress-cpr-{control_key}")
            sofr = st.slider("SOFR", 0.0, 8.0, float(scenario_seed.sofr_pct), 0.25,
                             format="%.2f%%", key=f"warehouse-stress-sofr-{control_key}")
        with c3:
            spread = st.slider(
                "Financing Spread", 0.50, 5.00, float(scenario_seed.spread_pct), 0.25,
                format="%.2f%%", key=f"warehouse-stress-spread-{control_key}"
            )
            advance = st.slider("Advance Rate", 78.0, 92.0, float(scenario_seed.advance_rate_pct), 1.0,
                                format="%.0f%%", key=f"warehouse-stress-advance-{control_key}")

    analysis_inputs = RmbsInputs(**{
        **asdict(scenario_seed),
        "cdr_pct": cdr,
        "severity_pct": severity,
        "cpr_pct": cpr,
        "sofr_pct": sofr,
        "spread_pct": spread,
        "advance_rate_pct": advance,
    })
    if analysis_inputs == base_inputs:
        schedule, tranche_summary, metrics = base_schedule, base_tranche_summary, base_metrics
    else:
        schedule, tranche_summary, metrics = project_rmbs_waterfall(analysis_inputs)
    results = build_results_object(analysis_inputs, schedule, tranche_summary, metrics)
    advance_df, optima = advance_optimization(analysis_inputs)
    sanity = analysis_sanity_checks(analysis_inputs, results, advance_df, optima)

    render_headline_callouts(analysis_inputs, results, sanity)
    view1, view2 = st.columns(2)
    with view1:
        render_warehouse_view(results, key_prefix="warehouse-only")
    with view2:
        render_scenario_a_equity_view(analysis_inputs, results, advance_df, optima, key_prefix="warehouse-only")

    render_warehouse_stress_view(analysis_inputs, key_prefix="warehouse-only")
    render_optimal_advance_section(advance_df, optima, key_prefix="warehouse")
    render_investment_report(analysis_inputs, results, advance_df, optima, full_rmbs=False)
    render_warehouse_assumptions_sources_panel()


def render_scenario_a_equity_view(
    inputs: RmbsInputs,
    results: dict[str, object],
    advance_df: pd.DataFrame | None = None,
    optima: dict[str, int] | None = None,
    key_prefix: str = "warehouse",
) -> None:
    st.markdown("**Equity Return**")
    metrics = results["metrics"]
    schedule: pd.DataFrame = results["schedule"]
    levered_moic = equity_moic(
        -(metrics["Warehouse Equity / Haircut"]),
        schedule.loc[schedule["Period"] > 0, "Warehouse Equity Cashflow"],
    )
    unlevered_moic = equity_moic(
        -inputs.deal_balance,
        schedule.loc[schedule["Period"] > 0, "Unlevered Equity Cashflow"],
    )
    st.markdown(
        "<div class='rmbs-mini-kpi-grid'>"
        + analysis_kpi_card(
            "Leverage Pickup",
            pct_text(metrics["Scenario A Leverage Premium"]),
            "Levered IRR less unlevered IRR",
            *KPI_HELP["Leverage Pickup"],
        )
        + analysis_kpi_card(
            "MOIC",
            f"{levered_moic:.2f}x / {unlevered_moic:.2f}x",
            "Levered / unlevered",
            *KPI_HELP["MOIC"],
        )
        + analysis_kpi_card(
            "Payback",
            payback_text(-metrics["Warehouse Equity / Haircut"], schedule["Warehouse Equity Cashflow"]),
            "Levered equity cashflow",
            *KPI_HELP["Payback"],
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    tab1, tab2 = st.tabs(["IRR vs Advance", "Annual Cashflow"])
    with tab1:
        chart_heading("Leverage Curve", *CHART_HELP["Leverage Curve"])
        st.plotly_chart(leverage_curve_figure(inputs, advance_df, optima), width="stretch",
                        key=f"{key_prefix}-leverage-curve")
    with tab2:
        chart_heading(
            "Annual Equity Distributions",
            "annual_equity_distribution = SUM(monthly_equity_cashflow by year)",
            "How much cash equity receives by year, levered versus unlevered.",
        )
        st.plotly_chart(annual_equity_distribution_figure(schedule), width="stretch",
                        key=f"{key_prefix}-annual-equity-bars")


def render_warehouse_stress_view(
    inputs: RmbsInputs,
    key_prefix: str = "warehouse",
    benchmarks: dict[str, float] | None = None,
) -> None:
    st.markdown("**Stress Readout**")
    h1, h2 = st.columns(2)
    with h1:
        st.plotly_chart(equity_irr_heatmap_figure(inputs), width="stretch", key=f"{key_prefix}-equity-heatmap")
    with h2:
        st.plotly_chart(advance_spread_heatmap_figure(inputs), width="stretch",
                        key=f"{key_prefix}-adv-spread-heatmap")
    h3, h4 = st.columns(2)
    with h3:
        st.plotly_chart(tornado_figure(inputs), width="stretch", key=f"{key_prefix}-tornado")
    with h4:
        st.plotly_chart(named_warehouse_scenario_loss_figure(inputs, benchmarks), width="stretch",
                        key=f"{key_prefix}-scenario-loss")
    summary = named_warehouse_scenario_summary(inputs)
    st.dataframe(format_table(summary), width="stretch", hide_index=True)


def named_warehouse_scenario_loss_figure(
    inputs: RmbsInputs,
    benchmarks: dict[str, float] | None = None,
) -> go.Figure:
    summary = named_warehouse_scenario_summary(inputs)
    fig = go.Figure(go.Bar(x=summary["Scenario"], y=summary["Cumulative Loss %"], name="Scenario Loss"))
    for label, value in (benchmarks or PRESALE_LOSS_BENCHMARKS).items():
        fig.add_hline(y=value, line_dash="dot", annotation_text=label, annotation_position="right")
    fig.update_layout(title="Scenario Loss vs Presale Benchmarks", height=340,
                      yaxis_title="Cumulative Net Loss (%)", margin=dict(l=10, r=10, t=42, b=10))
    return fig


def named_warehouse_scenario_summary(inputs: RmbsInputs) -> pd.DataFrame:
    rows = []
    for name in NAMED_SCENARIOS:
        scenario = apply_named_scenario(inputs, name)
        schedule, _tranche_summary, metrics = project_rmbs_waterfall(scenario)
        rows.append({
            "Scenario": name,
            "Warehouse Return": metrics["Facility Rate"],
            "Equity IRR (Lev)": metrics["Scenario A Equity IRR - Levered"],
            "Unlevered Equity IRR": metrics["Scenario A Equity IRR - Unlevered"],
            "Breakeven Loss (%)": structural_breakeven_loss_pct(scenario) / 100,
            "Facility Loss %": metrics["Facility / Lender Loss %"],
            "Cumulative Loss %": metrics["Cumulative Net Loss %"] * 100,
        })
    return pd.DataFrame(rows)


def advance_optimization(
    inputs: RmbsInputs,
    safety_threshold: float = AAA_SAFETY_THRESHOLD,
) -> tuple[pd.DataFrame, dict[str, int]]:
    rows = []
    carry_positive = rate(inputs.sofr_pct + inputs.spread_pct) < rate(inputs.gross_coupon_pct)
    for advance in range(78, 93):
        scenario = RmbsInputs(**{**asdict(inputs), "advance_rate_pct": float(advance)})
        _schedule, _summary, metrics = project_rmbs_waterfall(scenario)
        severe = apply_named_scenario(scenario, "SEVERE")
        _severe_schedule, _severe_summary, severe_metrics = project_rmbs_waterfall(severe)
        breakeven = structural_breakeven_loss_pct(scenario)
        severe_loss = severe_metrics["Cumulative Net Loss %"] * 100
        severe_cushion = breakeven - severe_loss
        score = (
            metrics["Scenario A Equity IRR - Levered"] / severe_cushion
            if severe_cushion > 0 and metrics["Scenario A Equity IRR - Levered"] > 0
            else float("-inf")
        )
        rows.append({
            "Advance Rate": advance,
            "Equity IRR": metrics["Scenario A Equity IRR - Levered"],
            "Breakeven Loss": breakeven,
            "Facility IRR": metrics["Facility Rate"],
            "SEVERE Cumulative Loss": severe_loss,
            "SEVERE Cushion Remaining": severe_cushion,
            "Risk-Adjusted Score": score,
            "Carry Positive": carry_positive,
            "Initial Equity": scenario.deal_balance * (1 - rate(advance)),
        })
    df = pd.DataFrame(rows)
    lender_candidates = df[df["Breakeven Loss"] >= safety_threshold]
    lender_opt = int(lender_candidates["Advance Rate"].max()) if not lender_candidates.empty else int(df["Advance Rate"].min())
    equity_candidates = df[(df["Initial Equity"] > 0) & (df["Carry Positive"])]
    equity_opt = (
        int(equity_candidates.sort_values(["Equity IRR", "Advance Rate"], ascending=[False, False]).iloc[0]["Advance Rate"])
        if not equity_candidates.empty else int(df["Advance Rate"].min())
    )
    balanced_candidates = df[df["Risk-Adjusted Score"] != float("-inf")]
    balanced_opt = (
        int(balanced_candidates.sort_values(
            ["Risk-Adjusted Score", "Advance Rate"], ascending=[False, False]
        ).iloc[0]["Advance Rate"])
        if not balanced_candidates.empty else lender_opt
    )
    optima = {
        "Lender-Optimal": lender_opt,
        "Equity-Optimal": equity_opt,
        "Balanced-Optimal": balanced_opt,
    }
    return df, optima


def render_optimal_advance_section(
    advance_df: pd.DataFrame,
    optima: dict[str, int],
    key_prefix: str,
    safety_threshold: float = AAA_SAFETY_THRESHOLD,
) -> None:
    st.markdown("**Optimal Advance Solver**")
    st.caption(
        f"Lender threshold uses severe loss coverage of {safety_threshold:.1f}%. "
        "Balanced optimizes levered equity IRR per unit of remaining SEVERE cushion."
    )
    display = advance_df[[
        "Advance Rate",
        "Equity IRR",
        "Breakeven Loss",
        "Facility IRR",
        "SEVERE Cushion Remaining",
    ]].copy()
    for col in ["Advance Rate", "Breakeven Loss", "SEVERE Cushion Remaining"]:
        display[col] = display[col] / 100
    display["Optimum"] = display["Advance Rate"].map(
        lambda advance: ", ".join(
            label for label, value in optima.items() if abs(value / 100 - advance) < 1e-9
        )
    )
    st.dataframe(format_table(display), width="stretch", hide_index=True)


def structural_breakeven_loss_pct(inputs: RmbsInputs) -> float:
    return max(0.0, 100 - inputs.advance_rate_pct)


def report_stress_summary(inputs: RmbsInputs) -> pd.DataFrame:
    rows = []
    for name in NAMED_SCENARIOS:
        scenario = apply_named_scenario(inputs, name)
        schedule, tranche_summary, metrics = project_rmbs_waterfall(scenario)
        rows.append({
            "Scenario": name,
            "Facility IRR": metrics["Facility Rate"],
            "Equity IRR (Lev)": metrics["Scenario A Equity IRR - Levered"],
            "Equity Wiped": "Yes" if metrics["Scenario A Equity IRR - Levered"] <= 0 else "No",
            "First Impaired Tranche": first_impaired_tranche(tranche_summary),
            "Facility Takes Loss": "Yes" if facility_impairment_pct(schedule, metrics) > 1e-8 else "No",
            "Cumulative Loss %": metrics["Cumulative Net Loss %"] * 100,
        })
    return pd.DataFrame(rows)


def render_investment_report(
    inputs: RmbsInputs,
    results: dict[str, object],
    advance_df: pd.DataFrame,
    optima: dict[str, int],
    *,
    full_rmbs: bool,
    deal_name: str = "OBX 2026-NQM8",
    benchmarks: dict[str, float] | None = None,
    safety_threshold: float = AAA_SAFETY_THRESHOLD,
) -> None:
    report = investment_report_markdown(
        inputs,
        results,
        advance_df,
        optima,
        full_rmbs=full_rmbs,
        deal_name=deal_name,
        benchmarks=benchmarks,
        safety_threshold=safety_threshold,
    )
    with st.expander("Investment Report", expanded=False):
        st.markdown(report)


def investment_report_markdown(
    inputs: RmbsInputs,
    results: dict[str, object],
    advance_df: pd.DataFrame,
    optima: dict[str, int],
    *,
    full_rmbs: bool,
    deal_name: str = "OBX 2026-NQM8",
    benchmarks: dict[str, float] | None = None,
    safety_threshold: float = AAA_SAFETY_THRESHOLD,
) -> str:
    metrics = results["metrics"]
    schedule: pd.DataFrame = results["schedule"]
    balanced_rate = optima["Balanced-Optimal"]
    balanced_inputs = RmbsInputs(**{**asdict(inputs), "advance_rate_pct": float(balanced_rate)})
    balanced_schedule, balanced_tranche_summary, balanced_metrics = project_rmbs_waterfall(balanced_inputs)
    balanced_row = advance_df.loc[advance_df["Advance Rate"] == balanced_rate].iloc[0]
    stress = report_stress_summary(balanced_inputs)
    current_loss = balanced_metrics["Cumulative Net Loss %"] * 100
    breakeven = structural_breakeven_loss_pct(balanced_inputs)
    active_benchmarks = benchmarks or PRESALE_LOSS_BENCHMARKS
    severe_label, severe_value = max(active_benchmarks.items(), key=lambda item: item[1])
    beyond_aaa = "beyond" if breakeven >= safety_threshold else "inside"
    facility_loss = facility_impairment_pct(balanced_schedule, balanced_metrics)
    recommendation = "fund-with-conditions"
    if facility_loss > 1e-8 or breakeven < min(safety_threshold, severe_value):
        recommendation = "pass"
    elif breakeven >= safety_threshold and balanced_row["SEVERE Cushion Remaining"] >= 0:
        recommendation = "fund"

    levered_moic = equity_moic(
        -balanced_metrics["Warehouse Equity / Haircut"],
        balanced_schedule.loc[balanced_schedule["Period"] > 0, "Warehouse Equity Cashflow"],
    )
    unlevered_moic = equity_moic(
        -balanced_inputs.deal_balance,
        balanced_schedule.loc[balanced_schedule["Period"] > 0, "Unlevered Equity Cashflow"],
    )
    payback = payback_text(
        -balanced_metrics["Warehouse Equity / Haircut"],
        balanced_schedule["Warehouse Equity Cashflow"],
    )
    next_row = advance_df.loc[advance_df["Advance Rate"] == balanced_rate + 1]
    if next_row.empty:
        one_pct = "At the recommended point, an extra 1% advance is outside the modeled sweep."
    else:
        next_row = next_row.iloc[0]
        irr_delta = (next_row["Equity IRR"] - balanced_row["Equity IRR"]) * 100
        cushion_delta = next_row["Breakeven Loss"] - balanced_row["Breakeven Loss"]
        one_pct = (
            f"Each extra 1% advance near the recommendation adds about {irr_delta:.2f} pts of levered equity IRR "
            f"and costs {abs(cushion_delta):.1f} pt of breakeven loss cushion."
        )

    opt_table = advance_df[[
        "Advance Rate", "Equity IRR", "Breakeven Loss", "Facility IRR", "SEVERE Cushion Remaining"
    ]].copy()
    opt_table["Flag"] = opt_table["Advance Rate"].map(
        lambda advance: ", ".join(label for label, value in optima.items() if value == advance)
    )
    opt_lines = [
        "| Advance | Equity IRR | Breakeven | Facility IRR | SEVERE Cushion | Flag |",
        "|---:|---:|---:|---:|---:|---|",
    ]
    for _, row in opt_table.iterrows():
        if not row["Flag"]:
            continue
        opt_lines.append(
            f"| {row['Advance Rate']:.0f}% | {row['Equity IRR']:.2%} | {row['Breakeven Loss']:.1f}% | "
            f"{row['Facility IRR']:.2%} | {row['SEVERE Cushion Remaining']:.1f}% | {row['Flag']} |"
        )

    stress_lines = [
        "| Scenario | Facility IRR | Equity IRR | Equity Wiped | First Impaired Tranche | Facility Loss? |",
        "|---|---:|---:|---|---|---|",
    ]
    for _, row in stress.iterrows():
        stress_lines.append(
            f"| {row['Scenario']} | {row['Facility IRR']:.2%} | {row['Equity IRR (Lev)']:.2%} | "
            f"{row['Equity Wiped']} | {row['First Impaired Tranche']} | {row['Facility Takes Loss']} |"
        )

    benchmark_text = ", ".join(f"{label} {value:.2f}%" for label, value in active_benchmarks.items())

    takeout = "repaid by the securitization takeout" if full_rmbs else "expected to be repaid by takeout/refinancing execution"
    return f"""
**1. Recommendation**

{recommendation.upper()}: recommend a {balanced_rate:.0f}% advance. At that structure, warehouse IRR is {balanced_metrics['Facility Rate']:.2%} and levered equity IRR is {balanced_metrics['Scenario A Equity IRR - Levered']:.2%}.

**2. The Facility**

Facility against ${balanced_inputs.deal_balance / 1_000_000:,.1f}mm of {deal_name} collateral, sourced from the presale subject-deal column. Collateral quality is FICO {balanced_inputs.wa_fico} / CLTV {balanced_inputs.wa_cltv_pct:.1f}%. Advance is {balanced_rate:.0f}%, SOFR + spread is {balanced_metrics['Facility Rate']:.2%}, and the line is {takeout}.

**3. Return Profile**

Warehouse IRR is {balanced_metrics['Facility Rate']:.2%}; facility WAL is {balanced_metrics['Facility WAL']:.2f} years. Equity levered IRR is {balanced_metrics['Scenario A Equity IRR - Levered']:.2%} versus unlevered IRR of {balanced_metrics['Scenario A Equity IRR - Unlevered']:.2%}, for {balanced_metrics['Scenario A Leverage Premium']:.2%} leverage pickup. Levered / unlevered MOIC is {levered_moic:.2f}x / {unlevered_moic:.2f}x. Levered payback is {payback}.

**4. Protection**

Breakeven loss is {breakeven:.1f}% versus parsed presale benchmarks {benchmark_text}; the structure is protected to {breakeven:.1f}%, {beyond_aaa} {severe_label}. Current modeled cumulative loss is {current_loss:.1f}%.

**5. Optimal Structure**

{chr(10).join(opt_lines)}

Balanced is recommended because it maximizes return per unit of remaining SEVERE cushion within the 78-92% sweep. {one_pct}

**6. Stress Summary**

{chr(10).join(stress_lines)}

**7. Key Risks**

Negative carry if SOFR plus spread exceeds asset coupon; securitization takeout/execution risk; mark-to-market and spread widening risk; and deal-specific product/geographic concentration risk. Inputs tagged ASSUMED include SOFR, spread, advance, CPR, CDR, severity, yield target, and fees. Inputs tagged SOURCED-from-presale include balance, WA coupon, term, seasoning, FICO, CLTV, DSCR, and stress benchmark context.

**8. Conclusion**

The thesis is a warehouse line protected by first-loss sponsor equity and repaid through takeout execution. Recommended advance is {balanced_rate:.0f}%, with {balanced_metrics['Facility Rate']:.2%} warehouse IRR, {balanced_metrics['Scenario A Equity IRR - Levered']:.2%} levered equity IRR, and {breakeven:.1f}% structural breakeven loss.
"""


def analysis_sanity_checks(
    inputs: RmbsInputs,
    results: dict[str, object],
    advance_df: pd.DataFrame,
    optima: dict[str, int],
) -> list[str]:
    issues = []
    metrics = results["metrics"]
    breakeven = structural_breakeven_loss_pct(inputs)
    equity_cushion_pct = metrics["Warehouse Equity / Haircut"] / inputs.deal_balance * 100
    if abs(breakeven - equity_cushion_pct) > 1e-6:
        issues.append("breakeven_loss does not equal equity_cushion / deal_balance")
    loss_points = [value / 10 for value in range(0, int(breakeven * 10))]
    facility_losses = [max(loss - breakeven, 0) for loss in loss_points]
    if any(loss > 1e-9 for loss in facility_losses):
        issues.append("facility_loss is nonzero below breakeven in the loss curve")
    irr_values = advance_df["Equity IRR"].tolist()
    if any(not math.isfinite(value) or abs(value) < 1e-12 for value in irr_values):
        issues.append("one or more advance-sweep IRRs are not finite")
    if any(next_value + 1e-9 < value for value, next_value in zip(irr_values, irr_values[1:])):
        issues.append("leverage curve is not monotonic")
    advance_values = set(advance_df["Advance Rate"].astype(int))
    if any(value not in advance_values for value in optima.values()):
        issues.append("one or more optima do not lie on the leverage curve")
    return issues


def render_warehouse_assumptions_sources_panel(deal_name: str = "OBX 2026-NQM8") -> None:
    with st.expander("Assumptions & Sources", expanded=False):
        st.markdown(
            f"""
**Sourced from {deal_name} presale subject-deal column**

Deal balance, WA current rate, WA original term, WA seasoning, FICO, CLTV, DSCR, loss-severity stress range, and foreclosure-frequency stress range.

**ASSUMED - seed / range / confirm desk**

SOFR, financing spread, advance rate, CPR, annual CDR, yield target, and servicing/admin fees. These are desk/market assumptions and are not sourced from the presale.

**Scenario A scope**

This tab is the pre-securitization warehouse view only. It answers lender advance/loss/WAL questions and sponsor levered-vs-unlevered equity economics while the whole-loan pool is financed on balance sheet. Tranche sizing, exchangeable certificates, XS/R, and securitization takeout mechanics are intentionally excluded here and remain in the full RMBS tab.
            """
        )


def facility_cashflow_stack_figure(schedule: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    x = schedule["Period"]
    fig.add_trace(go.Scatter(x=x, y=schedule["Facility Interest Paid"] / 1_000_000, stackgroup="one",
                             name="Facility Interest"))
    fig.add_trace(go.Scatter(x=x, y=schedule["Facility Principal Paid"] / 1_000_000, stackgroup="one",
                             name="Facility Principal"))
    fig.add_trace(go.Scatter(x=x, y=schedule["Warehouse Equity Cashflow"] / 1_000_000, stackgroup="one",
                             name="Residual to Equity"))
    fig.update_layout(title="Collateral Cashflow Split", height=300, yaxis_title="$mm",
                      margin=dict(l=10, r=10, t=42, b=10), hovermode="x unified")
    return fig


def facility_cushion_figure(schedule: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=schedule["Period"], y=schedule["Collateral Ending Balance"] / 1_000_000,
                             mode="lines", name="Collateral Balance"))
    fig.add_trace(go.Scatter(x=schedule["Period"], y=schedule["Facility Ending Balance"] / 1_000_000,
                             mode="lines", name="Facility Balance", fill="tonexty"))
    fig.update_layout(title="Facility Balance vs Collateral Balance", height=300, yaxis_title="$mm",
                      margin=dict(l=10, r=10, t=42, b=10), hovermode="x unified")
    return fig


def facility_loss_curve_figure(
    results: dict[str, object],
    benchmarks: dict[str, float] | None = None,
) -> go.Figure:
    metrics = results["metrics"]
    deal_balance = results["inputs"]["deal_balance"]
    initial_facility = metrics["Initial Facility Notional"]
    cushion_pct = structural_facility_cushion_pct(results) / 100
    x_values = [value / 10 for value in range(0, 251)]
    y_values = [
        max(0.0, loss / 100 - cushion_pct) * deal_balance / initial_facility * 100
        for loss in x_values
    ]
    fig = go.Figure(go.Scatter(x=x_values, y=y_values, mode="lines", name="Facility Loss %"))
    for label, value in (benchmarks or PRESALE_LOSS_BENCHMARKS).items():
        fig.add_vline(x=value, line_dash="dot", annotation_text=label, annotation_position="top")
    fig.add_vline(
        x=cushion_pct * 100,
        line_dash="dash",
        line_color="#111827",
        annotation_text="Breakeven",
        annotation_position="top",
    )
    fig.update_layout(title="", height=300,
                      xaxis_title="Cumulative Pool Loss (%)", yaxis_title="Facility Loss (%)",
                      margin=dict(l=10, r=10, t=42, b=10))
    return fig


def leverage_curve_figure(
    inputs: RmbsInputs,
    advance_df: pd.DataFrame | None = None,
    optima: dict[str, int] | None = None,
) -> go.Figure:
    df = advance_df if advance_df is not None else advance_optimization(inputs)[0]
    fig = go.Figure(go.Scatter(
        x=df["Advance Rate"],
        y=df["Equity IRR"] * 100,
        mode="lines+markers",
        name="Levered Equity IRR",
    ))
    if optima:
        marker_specs = {
            "Lender-Optimal": ("Lender", "#2563eb"),
            "Equity-Optimal": ("Equity", "#dc2626"),
            "Balanced-Optimal": ("Balanced", "#059669"),
        }
        for key, (label, color) in marker_specs.items():
            advance = optima.get(key)
            point = df.loc[df["Advance Rate"] == advance]
            if point.empty:
                continue
            fig.add_trace(go.Scatter(
                x=point["Advance Rate"],
                y=point["Equity IRR"] * 100,
                mode="markers+text",
                marker=dict(size=12, color=color),
                text=[label],
                textposition="top center",
                name=label,
            ))
    fig.update_layout(title="", height=300, xaxis_title="Advance Rate (%)",
                      yaxis_title="Levered Equity IRR (%)", margin=dict(l=10, r=10, t=42, b=10))
    return fig


def annual_equity_distribution_figure(schedule: pd.DataFrame) -> go.Figure:
    periods = schedule[schedule["Period"] > 0].copy()
    periods["Year"] = ((periods["Period"] - 1) // 12 + 1).astype(int)
    annual = periods.groupby("Year", as_index=False)[["Warehouse Equity Cashflow", "Unlevered Equity Cashflow"]].sum()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=annual["Year"], y=annual["Warehouse Equity Cashflow"] / 1_000_000,
                         name="Levered"))
    fig.add_trace(go.Bar(x=annual["Year"], y=annual["Unlevered Equity Cashflow"] / 1_000_000,
                         name="Unlevered"))
    fig.update_layout(title="Annual Equity Distributions", height=300, barmode="group",
                      xaxis_title="Year", yaxis_title="$mm", margin=dict(l=10, r=10, t=42, b=10))
    return fig


def tranche_writedown_ladder_figure(tranche_summary: pd.DataFrame) -> go.Figure:
    debt = tranche_summary[tranche_summary["Class"].str.startswith("Class ")].copy()
    order = [TRANCHE_LABELS[tranche] for tranche in reversed(TRANCHES)]
    debt["Class"] = pd.Categorical(debt["Class"], categories=order, ordered=True)
    debt = debt.sort_values("Class")
    fig = go.Figure(go.Bar(x=debt["Class"].astype(str), y=debt["Loss Allocated"] / 1_000_000))
    fig.update_layout(title="Tranche Writedown Ladder", height=300, xaxis_title="Bottom-up order",
                      yaxis_title="Loss Allocated ($mm)", margin=dict(l=10, r=10, t=42, b=10))
    return fig


def equity_irr_heatmap_figure(inputs: RmbsInputs) -> go.Figure:
    cdr_values = [0.25, 0.50, 1.0, 2.0, 3.0]
    severity_values = [25.0, 35.0, 50.0]
    z = []
    for cdr in cdr_values:
        row = []
        for severity in severity_values:
            scenario = RmbsInputs(**{**asdict(inputs), "cdr_pct": cdr, "severity_pct": severity})
            _schedule, _summary, metrics = project_rmbs_waterfall(scenario)
            row.append(metrics["Scenario A Equity IRR - Levered"] * 100)
        z.append(row)
    fig = go.Figure(go.Heatmap(x=severity_values, y=cdr_values, z=z, colorscale="RdYlGn",
                               colorbar=dict(title="IRR %")))
    fig.update_layout(title="Equity IRR Heatmap", height=340, xaxis_title="Severity (%)",
                      yaxis_title="CDR (%)", margin=dict(l=10, r=10, t=42, b=10))
    return fig


def advance_spread_heatmap_figure(inputs: RmbsInputs) -> go.Figure:
    advance_values = [78.0, 85.0, 92.0]
    spread_values = [
        max(inputs.spread_pct - 0.50, 0.0),
        inputs.spread_pct,
        inputs.spread_pct + 0.50,
        inputs.spread_pct + 1.00,
    ]
    z = []
    for advance in advance_values:
        row = []
        for spread in spread_values:
            scenario = RmbsInputs(**{**asdict(inputs), "advance_rate_pct": advance, "spread_pct": spread})
            _schedule, _summary, metrics = project_rmbs_waterfall(scenario)
            row.append(metrics["Scenario A Equity IRR - Levered"] * 100)
        z.append(row)
    fig = go.Figure(go.Heatmap(x=spread_values, y=advance_values, z=z, colorscale="RdYlGn",
                               colorbar=dict(title="IRR %")))
    fig.update_layout(title="Advance / Spread Heatmap", height=340, xaxis_title="Financing Spread (%)",
                      yaxis_title="Advance Rate (%)", margin=dict(l=10, r=10, t=42, b=10))
    return fig


def tornado_figure(inputs: RmbsInputs) -> go.Figure:
    base = equity_irr_for(inputs)
    specs = {
        "CDR": ({"cdr_pct": 0.25}, {"cdr_pct": 3.0}),
        "Severity": ({"severity_pct": 25.0}, {"severity_pct": 50.0}),
        "CPR": ({"cpr_pct": 5.0}, {"cpr_pct": 20.0}),
        "SOFR": ({"sofr_pct": max(inputs.sofr_pct - 1.0, 0.0)}, {"sofr_pct": inputs.sofr_pct + 2.0}),
        "Spread": ({"spread_pct": max(inputs.spread_pct - 0.5, 0.0)}, {"spread_pct": inputs.spread_pct + 1.0}),
        "Advance": ({"advance_rate_pct": 78.0}, {"advance_rate_pct": 92.0}),
    }
    rows = []
    for name, (low, high) in specs.items():
        low_irr = equity_irr_for(RmbsInputs(**{**asdict(inputs), **low}))
        high_irr = equity_irr_for(RmbsInputs(**{**asdict(inputs), **high}))
        rows.append({"Driver": name, "Swing": (high_irr - low_irr) * 100, "Abs": abs(high_irr - low_irr)})
    df = pd.DataFrame(rows).sort_values("Abs", ascending=True)
    fig = go.Figure(go.Bar(x=df["Swing"], y=df["Driver"], orientation="h"))
    fig.add_vline(x=0, line_color="#111827")
    fig.update_layout(title=f"Tornado: Equity IRR Driver Swing (Base {base * 100:.1f}%)", height=340,
                      xaxis_title="IRR swing (pts)", margin=dict(l=10, r=10, t=42, b=10))
    return fig


def named_scenario_loss_figure(inputs: RmbsInputs) -> go.Figure:
    summary = named_scenario_summary(inputs)
    fig = go.Figure(go.Bar(x=summary["Scenario"], y=summary["Cumulative Loss %"], name="Scenario Loss"))
    for label, value in PRESALE_LOSS_BENCHMARKS.items():
        fig.add_hline(y=value, line_dash="dot", annotation_text=label, annotation_position="right")
    fig.update_layout(title="Scenario Loss vs Presale Benchmarks", height=340,
                      yaxis_title="Cumulative Net Loss (%)", margin=dict(l=10, r=10, t=42, b=10))
    return fig


def named_scenario_summary(inputs: RmbsInputs) -> pd.DataFrame:
    rows = []
    for name in NAMED_SCENARIOS:
        scenario = apply_named_scenario(inputs, name)
        schedule, tranche_summary, metrics = project_rmbs_waterfall(scenario)
        rows.append({
            "Scenario": name,
            "Facility Loss %": metrics["Facility / Lender Loss %"],
            "Facility IRR": metrics["Facility Rate"],
            "Equity IRR (Lev)": metrics["Scenario A Equity IRR - Levered"],
            "Equity Wiped": "Yes" if metrics["Scenario A Equity IRR - Levered"] <= 0 else "No",
            "First Impaired Tranche": first_impaired_tranche(tranche_summary),
            "Cumulative Loss %": metrics["Cumulative Net Loss %"] * 100,
        })
    return pd.DataFrame(rows)


def equity_irr_for(inputs: RmbsInputs) -> float:
    _schedule, _summary, metrics = project_rmbs_waterfall(inputs)
    return metrics["Scenario A Equity IRR - Levered"]


def structural_facility_cushion_pct(results: dict[str, object]) -> float:
    metrics = results["metrics"]
    deal_balance = results["inputs"]["deal_balance"]
    return max(0.0, (deal_balance - metrics["Initial Facility Notional"]) / deal_balance * 100)


def modeled_facility_breakeven_loss_pct(inputs: RmbsInputs) -> float | None:
    """Return cumulative net loss where the warehouse facility first shows impairment."""
    low_cdr = 0.0
    high_cdr = 100.0

    high_inputs = RmbsInputs(**{**asdict(inputs), "cdr_pct": high_cdr})
    high_schedule, _high_summary, high_metrics = project_rmbs_waterfall(high_inputs)
    if facility_impairment_pct(high_schedule, high_metrics) <= 1e-8:
        return None

    for _ in range(16):
        mid_cdr = (low_cdr + high_cdr) / 2
        scenario = RmbsInputs(**{**asdict(inputs), "cdr_pct": mid_cdr})
        schedule, _summary, metrics = project_rmbs_waterfall(scenario)
        if facility_impairment_pct(schedule, metrics) > 1e-8:
            high_cdr = mid_cdr
        else:
            low_cdr = mid_cdr

    threshold_inputs = RmbsInputs(**{**asdict(inputs), "cdr_pct": high_cdr})
    _schedule, _summary, threshold_metrics = project_rmbs_waterfall(threshold_inputs)
    return threshold_metrics["Cumulative Net Loss %"] * 100


def facility_impairment_pct(schedule: pd.DataFrame, metrics: dict[str, float]) -> float:
    initial_facility = metrics["Initial Facility Notional"]
    if initial_facility <= 0:
        return 0.0
    interest_shortfall = schedule["Facility Interest Shortfall"].sum()
    principal_deficiency = max(
        float((schedule["Facility Ending Balance"] - schedule["Collateral Ending Balance"]).max()),
        0.0,
    )
    return max(interest_shortfall, principal_deficiency) / initial_facility


def equity_moic(initial_outflow: float, cashflows: pd.Series) -> float:
    if initial_outflow == 0:
        return 0.0
    return float(cashflows[cashflows > 0].sum() / abs(initial_outflow))


def payback_text(initial_outflow: float, cashflows: pd.Series) -> str:
    cumulative = initial_outflow
    for idx, cf in enumerate(cashflows, start=0):
        cumulative += cf
        if idx > 0 and cumulative >= 0:
            return f"{idx / 12:.2f} yrs"
    return "Not reached"


def first_impaired_tranche(tranche_summary: pd.DataFrame) -> str:
    summary = tranche_summary.set_index("Class")
    for tranche in reversed(TRANCHES):
        label = TRANCHE_LABELS[tranche]
        if label in summary.index and summary.loc[label, "Loss Allocated"] > 1:
            return label
    return "-"


def render_warehouse_formula_reference() -> None:
    with st.expander("Scenario A Formula and Structuring Logic", expanded=True):
        st.markdown(
            """
**Modeling stance**

Scenario A is the pre-securitization warehouse view. The whole-loan pool sits on the sponsor's balance sheet and is financed by a warehouse lender. There are no rated tranches, no exchangeable certificates, no XS/R equity, and no securitization takeout inside this tab.

**Collateral formulas**

SMM = 1 - (1 - CPR)^(1/12). MDR = 1 - (1 - CDR)^(1/12). Recoveries = 1 - Severity. Scheduled Payment = PMT(WA Gross Coupon / 12, Term, -Deal Balance). Survival Factor = Collateral Beginning Balance / Scheduled Collateral Beginning Balance. Defaults are taken before interest, so Collateral Interest = Remaining Performing Balance x WA Gross Coupon / 12. Principal collections equal scheduled principal of performing collateral plus prepayments plus recoveries.

**Warehouse formulas**

Facility Rate = SOFR + Spread. Initial Facility Notional = Deal Balance x Advance Rate. Sponsor Equity / Haircut = Deal Balance - Initial Facility Notional. Facility Total Cashflow = MIN(Asset Total Cashflow, Facility Interest Owed + Facility Beginning Balance). Facility Principal Paid = Facility Total Cashflow - Facility Interest Paid. Facility Ending Balance = Facility Beginning Balance - Facility Principal Paid. Advance Rate to Par = Facility Ending Balance / Collateral Ending Balance.

**Sponsor equity**

Levered equity is the sponsor residual after the warehouse facility. Its initial equity check is the haircut, and monthly cashflow is Asset Total Cashflow minus Facility Total Cashflow. Unlevered equity assumes the sponsor owns 100% of the same pool with no facility; monthly cashflow is Asset Total Cashflow less servicing and admin fees. The difference between levered and unlevered equity IRR is the gross leverage premium of the warehouse financing.

**Not from the presale**

SOFR, financing spread, advance rate, CPR, annual CDR, yield target, and servicing/admin fees are model assumptions. They should be replaced with desk or diligence inputs when available.
            """
        )


def render_formula_reference() -> None:
    with st.expander("Formula and Structuring Logic", expanded=True):
        st.markdown(
            """
**Modeling stance**

This is an institutional RMBS trust-level model, not a loan-by-loan servicer tape. Scenario A and Scenario B are linked stages, not stacked liabilities. Scenario A is the pre-securitization warehouse view: the whole-loan pool finances a facility lender and a red haircut/equity piece. Scenario B is the at/post-securitization view: debt note proceeds take out the warehouse, and the trust cashflows through the securitization waterfall.

**Presale-seeded collateral**

The base case uses the OBX 2026-NQM8 presale subject-deal column only: $1.0224 billion closing pool balance, 6.80% WA current rate, 358-month WA original term, 3 months WA seasoning, 757 WA FICO, 68.9% WA original CLTV, and 1.11 WA DSCR. The presale loss-estimation range is 49.88% AAA loss severity down to 20.14% B loss severity, with foreclosure frequency from 28.67% AAA to 4.22% B. The base severity seed is 35.00%, a midpoint-style modeling assumption within that stress range.

**Not from the PDF - replace when diligence gives the real numbers**

SOFR, financing spread, advance rate, CPR, CDR, yield target, servicing/admin fees, lockout, clean-up call factor, performance triggers, and tranche coupons are not pulled from the presale. They remain ASSUMED - confirm desk. CDR is an annual model input; the presale foreclosure-frequency rows are lifetime/stress defaults, not annual CDRs.

**Collateral formulas**

SMM = 1 - (1 - CPR)^(1/12). MDR = 1 - (1 - CDR)^(1/12). Recoveries = 1 - Severity. Scheduled Payment = PMT(WA Gross Coupon / 12, Term, -Deal Balance). Survival Factor = Collateral Beginning Balance / Scheduled Collateral Beginning Balance. Surviving Scheduled Payment = Scheduled Payment x Survival Factor. Surviving Scheduled Principal = Scheduled Principal x Survival Factor. Defaults = Collateral Beginning Balance x MDR. Remaining Performing Balance = Collateral Beginning Balance - Defaults. Collateral Interest = Remaining Performing Balance x WA Gross Coupon / 12. Scheduled Principal of Performing Collateral = Scheduled Payment of Performing Collateral - Collateral Interest. Prepayments = (Collateral Beginning Balance - Surviving Scheduled Principal) x SMM. Principal Collections = Scheduled Principal of Performing Collateral + Prepayments + Recoveries. Collateral Ending Balance = Beginning Balance - Defaults - Scheduled Principal of Performing Collateral - Prepayments.

**Scenario 1 methodology fixes**

The three big differences are corrected here: interest is earned only on remaining performing balance; scheduled principal is scaled by both survival factor and remaining-performing-pool logic; and prepayments use the Scenario 1 base of beginning balance minus surviving scheduled principal rather than separately subtracting defaults.

**Scenario A - warehouse formulas**

Facility Rate = SOFR + Spread. Initial Facility Notional = Deal Balance x Advance Rate. Warehouse Equity / Haircut = Deal Balance - Initial Facility Notional. Annual Asset Income = Deal Balance x WA Gross Coupon. Annual Funding Cost = Initial Facility Notional x Facility Rate. Net Margin = Asset Income - Funding Cost. Levered ROE = Net Margin / Warehouse Equity. Facility interest, principal, WAL, advance rate to par, advance rate to purchase price, and lender loss are calculated using the asset total cashflow.

Scenario A equity is shown two ways. Levered equity is the sponsor residual after the warehouse facility: monthly cashflow equals Asset Total Cashflow minus Facility Total Cashflow, with the initial equity check equal to Deal Balance minus Initial Facility Notional. Unlevered equity assumes the sponsor owns 100% of the pool with no facility: monthly cashflow equals Asset Total Cashflow minus servicing and admin fees, with the initial equity check equal to Deal Balance. The difference between the two equity IRRs is the gross leverage premium of warehouse financing.

**PV and duration formulas**

Cashflow Present Value = Asset Total Cashflow / (1 + Yield Target / 12)^Period. Purchase Price = SUM(Cashflow Present Value). Collateral WAL = SUMPRODUCT(Years, Balance Decline %) / SUM(Balance Decline %). Macaulay Duration = SUMPRODUCT(Years, Cashflow Present Value) / SUM(Cashflow Present Value). Modified Duration = Macaulay Duration / (1 + Yield Target / 2).

**Scenario B - securitization waterfall**

Fees are taken before bond interest: Interest Available = Collateral Interest - Servicing Fee - Admin Fee. Debt note interest is paid senior-to-subordinate from A-1 through B-3. Any unpaid interest is carried as a shortfall. Losses are allocated reverse sequentially from B-3 upward, with A-1 exposed last. XS + R is strict equity: it has no principal balance and is valued as PV of residual excess spread. Exchangeable labels such as A-1A, A-1B, A-1FCF, and A-1LCF are not additive debt balances in this model; they are alternative/exchangeable certificates and must not be counted on top of the non-overlapping stack.

**Principal allocation**

During the stepdown lockout, principal pays sequentially from A-1 down to B-3. After the lockout, the model permits modified pro-rata principal across debt notes only if performance triggers are passing. If a trigger breaches, the structure goes back to sequential/turbo mode. B-1A through B-3 are still debt notes; they are only grouped with XS/R when viewing a sponsor retained position.

**Triggers and excess spread**

Stepdown is blocked if cumulative net loss exceeds the cumulative loss trigger or the delinquency proxy exceeds the DQ trigger. While triggers pass, remaining excess spread flows to XS/R equity. When triggers fail, excess spread is redirected into principal as turbo protection. Clean-up call eligibility is flagged once collateral has paid down to the configured percentage of original deal balance; the model flags eligibility rather than forcing the call because the actual call decision is issuer/economics-dependent.

**Metrics**

Senior Credit Enhancement = (Collateral Ending Balance - Class A-1 Ending Balance) / Collateral Ending Balance. Cumulative Net Loss = SUM(Net Loss) / Deal Balance. WAL = SUMPRODUCT(Years, Tranche Principal Paid) / Initial Tranche Balance. Tranche IRR is annualized monthly IRR using closing-date note purchase as the initial outflow and monthly interest/principal cashflows as inflows. Strict Equity Value = PV of XS/R excess-spread cashflows. Sponsor Retained Position = B-1A through B-3 debt balances + XS/R strict equity value; it is a retained risk bundle, not pure equity.

**Why these complications matter**

The warehouse view answers lender advance / loss / WAL / haircut equity questions before securitization. The securitization view answers note sizing, waterfall, enhancement, duration, and residual-value questions after the takeout. At securitization close, Scenario B debt proceeds repay Scenario A debt drawn, and the Scenario A haircut converts into retained risk capital.
            """
        )


def formula_reference_rows() -> list[tuple[str, str]]:
    return [
        ("Source deal", "OBX 2026-NQM8 subject-deal column only: $1.0224bn balance; 6.80% WA current rate; 358-month WA original term; 3-month seasoning; 757 FICO; 68.9% CLTV; 1.11 DSCR."),
        ("Loss estimation", "Presale stress range: loss severity 49.88% AAA to 20.14% B; foreclosure frequency 28.67% AAA to 4.22% B. Base severity seed is assumed at 35.00%."),
        ("Not from PDF", "SOFR, spread, advance rate, CPR, annual CDR, yield target, fees, tranche coupons, lockout, clean-up call, and trigger levels are ASSUMED - confirm desk."),
        ("Tranche sizing", "Use CE gaps, not preliminary dollar amounts: AAA 80.00%, AA 4.10%, A 7.85%, BBB 3.50%, B-1A 1.45%, B-1B 1.60%, B-2 0.70%, B-3 0.80%."),
        ("SMM", "1 - (1 - CPR)^(1/12)"),
        ("MDR", "1 - (1 - CDR)^(1/12)"),
        ("Recoveries", "1 - Severity"),
        ("Scheduled Payment", "PMT(WA Gross Coupon / 12, Term, -Deal Balance)"),
        ("Survival Factor", "Collateral Beginning Balance / Scheduled Collateral Beginning Balance"),
        ("Remaining Performing Balance", "Collateral Beginning Balance - Defaults"),
        ("Collateral Interest", "Remaining Performing Balance x WA Gross Coupon / 12"),
        ("Scheduled Principal", "Scheduled Payment of Performing Collateral - Collateral Interest"),
        ("Defaults", "Collateral Beginning Balance x MDR"),
        ("Recoveries $", "Defaults x Recovery Rate"),
        ("Net Loss", "Defaults - Recoveries"),
        ("Prepayments", "max(Collateral Beginning Balance - Surviving Scheduled Principal, 0) x SMM"),
        ("Principal Collections", "Scheduled Principal of Performing Collateral + Prepayments + Recoveries"),
        ("Collateral Ending Balance", "Beginning Balance - Defaults - Scheduled Principal of Performing Collateral - Prepayments"),
        ("Purchase Price", "SUM(Cashflow Present Value)"),
        ("Macaulay Duration", "SUMPRODUCT(Years, Cashflow Present Value) / SUM(Cashflow Present Value)"),
        ("Facility Rate", "SOFR + Spread"),
        ("Scenario A", "Warehouse facility is pre-securitization: debt draw = advance rate x collateral; equity/haircut = collateral - debt draw."),
        ("Warehouse ROE", "Levered ROE = (Deal Balance x WAC - Initial Facility Notional x Facility Rate) / Warehouse Equity."),
        ("Levered Equity IRR", "IRR of period-0 -(Deal Balance - Initial Facility Notional), then monthly Warehouse Equity Cashflow."),
        ("Unlevered Equity IRR", "IRR of period-0 -Deal Balance, then monthly Asset Total Cashflow less servicing and admin fees."),
        ("Leverage Premium", "Levered Equity IRR minus Unlevered Equity IRR; negative if warehouse financing is dilutive."),
        ("Fees", "Servicing Fee and Admin Fee are deducted from collateral interest before bond interest."),
        ("Scenario B", "Non-overlapping securitization debt stack is A-1, A-1F, A-2, A-3, M-1, and B-notes; XS + R is strict equity with no principal balance."),
        ("Exchangeables", f"{', '.join(EXCHANGEABLE_LABELS.values())} are exchangeable certificate labels, not additive debt balances; they are excluded from debt proceeds."),
        ("Takeout", "Scenario B debt proceeds repay Scenario A warehouse debt at securitization close."),
        ("Interest Waterfall", "Debt note interest pays senior-to-subordinate from A-1 through B-3; unpaid amounts carry as shortfalls."),
        ("Loss Allocation", "Reverse sequential: B-3 upward, with A-1 exposed last."),
        ("Principal Waterfall", "Sequential during lockout/trigger breach; modified pro-rata across debt notes when triggers pass."),
        ("Excess Spread", "Residual cashflow to XS/R when triggers pass; redirected as turbo principal when triggers breach."),
        ("Stepdown Trigger", "Pro-rata blocked if cumulative net loss or delinquency proxy exceeds trigger levels."),
        ("Clean-up Call", "Eligibility flag when collateral factor is at or below the configured call factor; call is not forced."),
        ("Strict Equity", "XS/R value = PV of residual excess spread stream; it is not pool balance minus bond balance."),
        ("Retained Position", "Sponsor retained position = B-1A..B-3 debt + XS/R equity; label this retained risk, not pure equity."),
        ("Senior CE", "(Collateral Ending Balance - Class A-1 Ending Balance) / Collateral Ending Balance"),
        ("Cumulative Net Loss", "SUM(Net Loss) / Deal Balance"),
        ("WAL", "SUMPRODUCT(Years, Tranche Principal Paid) / Initial Tranche Balance"),
        ("IRR", "Monthly IRR of tranche cashflows x 12"),
        ("Industry rationale", "RMBS requires tranche-level waterfall modeling because credit enhancement, triggers, excess spread, and loss allocation drive class-specific risk, duration, and economics."),
    ]


def cdr_sensitivity(inputs: RmbsInputs) -> pd.DataFrame:
    rows = []
    for cdr in scenario_range(inputs.cdr_pct, lower=max(0, inputs.cdr_pct - 1), upper=inputs.cdr_pct + 5, step=0.5):
        scenario = RmbsInputs(**{**asdict(inputs), "cdr_pct": cdr})
        schedule, tranche_summary, metrics = project_rmbs_waterfall(scenario)
        rows.append({
            "CDR": cdr,
            "Senior CE": metrics["Final Senior Credit Enhancement"] * 100,
            "Cumulative Net Loss": metrics["Cumulative Net Loss %"] * 100,
            "Senior IRR": metrics["Senior IRR"] * 100,
            "XS/R Value": metrics["XS/R Strict Equity Value"] / 1_000_000,
            "Total Principal": schedule["Principal Collections"].sum(),
        })
    return pd.DataFrame(rows)


def attachment_sensitivity(inputs: RmbsInputs) -> pd.DataFrame:
    rows = []
    class_a_values = scenario_range(
        inputs.a1_pct,
        lower=max(40, inputs.a1_pct - 15),
        upper=min(80, inputs.a1_pct + 10),
        step=5,
    )
    for a1 in class_a_values:
        scenario = RmbsInputs(**{**asdict(inputs), "a1_pct": a1})
        schedule, tranche_summary, metrics = project_rmbs_waterfall(scenario)
        rows.append({
            "A-1 Size": a1,
            "Senior CE": metrics["Initial Senior Credit Enhancement"] * 100,
            "Senior WAL": metrics["Senior WAL"],
            "Senior IRR": metrics["Senior IRR"] * 100,
            "XS/R Value": metrics["XS/R Strict Equity Value"] / 1_000_000,
            "Debt Proceeds": metrics["Scenario B Debt Proceeds"] / 1_000_000,
            "Total Principal": schedule["Principal Collections"].sum() / 1_000_000,
        })
    return pd.DataFrame(rows)


def balance_figure(schedule: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=schedule["Period"], y=schedule["Collateral Ending Balance"] / 1_000_000,
                             mode="lines", name="Collateral"))
    for tranche in ["A1", "A1F", "A2", "A3", "M1", "B1A", "B3"]:
        fig.add_trace(go.Scatter(
            x=schedule["Period"], y=schedule[f"{tranche} Ending Balance"] / 1_000_000,
            mode="lines", name=TRANCHE_LABELS[tranche]))
    fig.update_layout(
        title="Collateral and Tranche Balances",
        height=360,
        margin=dict(l=10, r=10, t=42, b=10),
        yaxis_title="$mm",
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.28),
    )
    return fig


def tranche_cashflow_figure(tranche_summary: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=tranche_summary["Class"], y=tranche_summary["Principal Paid"] / 1_000_000,
        name="Principal Paid"))
    fig.add_trace(go.Bar(
        x=tranche_summary["Class"], y=tranche_summary["Interest Paid"] / 1_000_000,
        name="Interest Paid"))
    fig.add_trace(go.Bar(
        x=tranche_summary["Class"], y=tranche_summary["Loss Allocated"] / 1_000_000,
        name="Loss Allocated"))
    fig.update_layout(
        title="Principal, Interest, and Loss by Tranche",
        height=360,
        barmode="group",
        margin=dict(l=10, r=10, t=42, b=10),
        yaxis_title="$mm",
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.28),
    )
    return fig


def credit_figure(schedule: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=schedule["Period"], y=schedule["Credit Enhancement %"] * 100,
        mode="lines", name="Senior CE"))
    fig.add_trace(go.Scatter(
        x=schedule["Period"], y=schedule["Cumulative Net Loss %"] * 100,
        mode="lines", name="Cumulative Net Loss"))
    fig.update_layout(
        title="Senior Credit Enhancement vs Net Loss",
        height=340,
        margin=dict(l=10, r=10, t=42, b=10),
        yaxis_title="%",
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.25),
    )
    return fig


def excess_spread_figure(schedule: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=schedule["Period"], y=schedule["Residual Excess Spread"] / 1_000_000,
        name="Residual Excess Spread"))
    fig.add_trace(go.Scatter(
        x=schedule["Period"], y=schedule["Excess Spread"] / 1_000_000,
        mode="lines", name="Gross Excess Spread"))
    fig.update_layout(
        title="Excess Spread",
        height=340,
        margin=dict(l=10, r=10, t=42, b=10),
        yaxis_title="$mm",
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.25),
    )
    return fig


def cdr_sensitivity_figure(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["CDR"], y=df["Senior CE"], mode="lines+markers", name="Senior CE"))
    fig.add_trace(go.Scatter(
        x=df["CDR"], y=df["Senior IRR"], mode="lines+markers", name="Senior IRR", yaxis="y2"))
    fig.add_trace(go.Scatter(
        x=df["CDR"], y=df["XS/R Value"], mode="lines+markers", name="XS/R Value ($mm)", yaxis="y2"))
    fig.add_trace(go.Bar(
        x=df["CDR"], y=df["Cumulative Net Loss"], name="Cumulative Net Loss", opacity=0.25))
    fig.update_layout(
        title="CDR Sensitivity",
        height=380,
        margin=dict(l=10, r=10, t=42, b=10),
        xaxis_title="CDR (%)",
        yaxis_title="Credit / Loss (%)",
        yaxis2=dict(title="IRR / Value", overlaying="y", side="right", showgrid=False),
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.25),
    )
    return fig


def attachment_sensitivity_figure(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["A-1 Size"], y=df["Total Principal"], name="Principal Collections ($mm)"))
    fig.add_trace(go.Scatter(
        x=df["A-1 Size"], y=df["Senior WAL"], mode="lines+markers",
        name="Senior WAL", yaxis="y2"))
    fig.add_trace(go.Scatter(
        x=df["A-1 Size"], y=df["XS/R Value"], mode="lines+markers",
        name="XS/R Value ($mm)", yaxis="y3"))
    fig.update_layout(
        title="A-1 Size / Attachment Sensitivity",
        height=380,
        margin=dict(l=10, r=10, t=42, b=10),
        xaxis_title="A-1 Size (%)",
        yaxis_title="Principal ($mm)",
        yaxis2=dict(title="Senior WAL", overlaying="y", side="right", showgrid=False),
        yaxis3=dict(title="XS/R Value ($mm)", overlaying="y", side="right", anchor="free",
                    position=0.96, showgrid=False),
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.25),
    )
    return fig


def render_waterfall_html(df: pd.DataFrame) -> str:
    header_cells = []
    body_rows = []
    for idx, col in enumerate(df.columns):
        section = rmbs_section(col)
        label = "" if col in SPACER_COLUMNS else col.replace(" Beginning ", "\nBeginning ").replace(" Ending ", "\nEnding ")
        header_cells.append(
            f"<th class='{section} {section_boundary_class(idx, df.columns)}'>{html_escape(label).replace(chr(10), '<br>')}</th>"
        )
    for _, row in df.iterrows():
        cells = []
        for idx, col in enumerate(df.columns):
            section = rmbs_section(col)
            classes = f"{section} {section_boundary_class(idx, df.columns)}"
            cells.append(f"<td class='{classes}'>{html_escape(format_waterfall_value(col, row[col]))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        "<div class='rmbs-excel-wrap'><table class='rmbs-excel-table'>"
        f"<thead><tr>{''.join(header_cells)}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def rmbs_section(col: str) -> str:
    if col in IDEAL_ASSET_COLUMNS:
        return "rmbs-xl-ideal"
    if col in SPACER_COLUMNS:
        return "rmbs-xl-spacer"
    if col in COLLATERAL_COLUMNS:
        return "rmbs-xl-asset"
    if col in WAREHOUSE_COLUMNS or col in TAKEOUT_COLUMNS:
        return "rmbs-xl-warehouse"
    if col in WAREHOUSE_EQUITY_COLUMNS or col in UNLEVERED_EQUITY_COLUMNS or col in SCENARIO_B_EQUITY_COLUMNS:
        return "rmbs-xl-equity"
    if col in TRANCHE_META_COLUMNS:
        return "rmbs-xl-tranche"
    if any(col.startswith(f"{tranche} ") for tranche in TRANCHES):
        return "rmbs-xl-tranche"
    return "rmbs-xl-equity"


def section_boundary_class(idx: int, columns: pd.Index) -> str:
    col = columns[idx]
    previous = columns[idx - 1] if idx > 0 else None
    next_col = columns[idx + 1] if idx + 1 < len(columns) else None
    classes = []
    if idx == 0 or rmbs_section(col) != rmbs_section(previous):
        classes.append("rmbs-xl-section-start")
    if idx + 1 == len(columns) or rmbs_section(col) != rmbs_section(next_col):
        classes.append("rmbs-xl-section-end")
    return " ".join(classes)


def format_table(df: pd.DataFrame) -> pd.DataFrame:
    display = df.copy()
    for col in display.columns:
        if col in PERCENT_COLUMNS:
            display[col] = display[col].map(pct_text)
        elif pd.api.types.is_numeric_dtype(display[col]):
            display[col] = display[col].map(lambda value: number_text(value, 2))
    return display


def format_waterfall_value(col: str, value: object) -> str:
    if isinstance(value, str):
        return value
    if col in SPACER_COLUMNS:
        return ""
    if col in {"Trigger Breached", "Cleanup Call Eligible"}:
        return "Yes" if value else "-"
    numeric = float(value)
    if col == "Period":
        return number_text(numeric, 0)
    if col == "Years":
        return f"{numeric:.2f}"
    if "%" in col:
        return "-" if abs(numeric) < 1e-9 else f"{numeric:.1%}"
    return format_number_cell(numeric)


def build_warehouse_excel_download(
    inputs: RmbsInputs,
    schedule: pd.DataFrame,
    metrics: dict[str, float],
) -> bytes:
    import xlsxwriter
    from xlsxwriter.utility import xl_rowcol_to_cell

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_calc_mode("auto")
    ws = workbook.add_worksheet("Scenario A Warehouse")
    ws.hide_gridlines(2)
    cashflow_ws = workbook.add_worksheet("Scenario A Cashflows")
    cashflow_ws.hide()

    title_fmt = workbook.add_format({"bold": True, "font_size": 11})
    note_fmt = workbook.add_format({"italic": True, "font_color": "#555555", "text_wrap": True})
    label_fmt = workbook.add_format({"border": 1, "bold": True, "bg_color": "#f4f4f4"})
    input_money_fmt = workbook.add_format({"border": 1, "font_color": "blue", "bold": True,
                                           "bg_color": INPUT_BLUE, "num_format": "#,##0.00"})
    input_int_fmt = workbook.add_format({"border": 1, "font_color": "blue", "bold": True,
                                         "bg_color": INPUT_BLUE, "num_format": "#,##0"})
    input_pct_fmt = workbook.add_format({"border": 1, "font_color": "blue", "bold": True,
                                         "bg_color": INPUT_BLUE, "num_format": "0.00%"})
    calc_fmt = workbook.add_format({"border": 1, "bg_color": "white",
                                    "num_format": "#,##0.00;(#,##0.00);-"})
    calc_pct_fmt = workbook.add_format({"border": 1, "bg_color": "white", "num_format": "0.00%"})
    header_fmt = workbook.add_format({"bold": True, "border": 1, "align": "center",
                                      "valign": "bottom", "text_wrap": True})
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
    equity_pct_fmt = workbook.add_format({"bg_color": EQUITY_PEACH, "border": 1,
                                          "num_format": "0.0%;(0.0%);-"})
    ideal_fmt = workbook.add_format({"bg_color": "white", "border": 1,
                                     "num_format": "#,##0.00;(#,##0.00);-"})
    ideal_pct_fmt = workbook.add_format({"bg_color": "white", "border": 1,
                                         "num_format": "0.0%;(0.0%);-"})
    pct_fmt = workbook.add_format({"border": 1, "num_format": "0.0%;(0.0%);-"})
    section_fmt = workbook.add_format({"bold": True, "border": 2, "align": "center",
                                       "valign": "vcenter", "bg_color": "#f3f4f6"})

    table = warehouse_table(schedule)
    table = table[table["Period"] > 0].copy()
    section_row = 23
    header_row = 24
    data_start = 25
    data_end = data_start + len(table) - 1
    col_map = {col: idx for idx, col in enumerate(table.columns)}
    table_refs = {
        col: f"{xl_rowcol_to_cell(data_start, idx)}:{xl_rowcol_to_cell(data_end, idx)}"
        for col, idx in col_map.items()
    }
    input_refs = {
        "deal_balance": "$B$3",
        "gross_coupon": "$B$4",
        "term_months": "$B$5",
        "seasoning_months": "$B$6",
        "cpr": "$B$7",
        "smm": "$B$8",
        "cdr": "$B$9",
        "mdr": "$B$10",
        "severity": "$B$11",
        "recoveries": "$B$12",
        "yield_target": "$B$13",
        "servicing_fee": "$B$14",
        "admin_fee": "$B$15",
        "sofr": "$I$3",
        "spread": "$I$4",
        "facility_rate": "$I$5",
        "advance_rate": "$I$6",
        "initial_facility": "$I$7",
        "purchase_price": "$P$4",
    }
    levered_equity_irr_range = f"'Scenario A Cashflows'!A2:A{len(table) + 2}"
    unlevered_equity_irr_range = f"'Scenario A Cashflows'!B2:B{len(table) + 2}"

    write_box(ws, 0, 0, "Collateral / Credit Inputs", [
        ("Deal Balance", inputs.deal_balance, input_money_fmt),
        ("WA Gross Coupon", inputs.gross_coupon_pct / 100, input_pct_fmt),
        ("WA Original Term (Months)", inputs.term_months, input_int_fmt),
        ("WA Seasoning (Months)", inputs.seasoning_months, input_int_fmt),
        ("CPR", inputs.cpr_pct / 100, input_pct_fmt),
        ("SMM", smm(inputs.cpr_pct), calc_pct_fmt, "=1-(1-$B$7)^(1/12)"),
        ("CDR", inputs.cdr_pct / 100, input_pct_fmt),
        ("MDR", mdr(inputs.cdr_pct), calc_pct_fmt, "=1-(1-$B$9)^(1/12)"),
        ("Severity", inputs.severity_pct / 100, input_pct_fmt),
        ("Recoveries", 1 - rate(inputs.severity_pct), calc_pct_fmt, "=1-$B$11"),
        ("Yield Target", inputs.yield_target_pct / 100, input_pct_fmt),
        ("Servicing Fee", inputs.servicing_fee_pct / 100, input_pct_fmt),
        ("Admin Fee", inputs.admin_fee_pct / 100, input_pct_fmt),
    ], title_fmt, label_fmt)

    write_box(ws, 0, 7, "Warehouse Facility", [
        ("SOFR", inputs.sofr_pct / 100, input_pct_fmt),
        ("Spread", inputs.spread_pct / 100, input_pct_fmt),
        ("Facility Rate", metrics["Facility Rate"], calc_pct_fmt, "=$I$3+$I$4"),
        ("Advance Rate", inputs.advance_rate_pct / 100, input_pct_fmt),
        ("Initial Facility Notional", metrics["Initial Facility Notional"], calc_fmt, "=$B$3*$I$6"),
        ("Sponsor Equity / Haircut", metrics["Warehouse Equity / Haircut"], calc_fmt, "=$B$3-$I$7"),
    ], title_fmt, label_fmt)

    write_box(ws, 0, 14, "Outputs", [
        ("Purchase Px / Value (%)", metrics["Purchase Price (%)"], calc_pct_fmt, "=$P$4/$B$3"),
        ("Purchase Px ($)", metrics["Purchase Price ($)"], calc_fmt,
         f"=SUM({table_refs['Cashflow Present Value']})"),
        ("Collateral WAL", metrics["Collateral WAL"], calc_fmt,
         f"=SUMPRODUCT({table_refs['Years']},{table_refs['Balance Decline %']})/"
         f"SUM({table_refs['Balance Decline %']})"),
        ("Macaulay Duration", metrics["Macaulay Duration"], calc_fmt,
         f"=SUMPRODUCT({table_refs['Years']},{table_refs['Cashflow Present Value']})/"
         f"SUM({table_refs['Cashflow Present Value']})"),
        ("Modified Duration", metrics["Modified Duration"], calc_fmt, "=$P$6/(1+$B$13/2)"),
        ("Cumulative Defaults", metrics["Cumulative Defaults %"], calc_pct_fmt,
         f"=SUM({table_refs['Defaults']})/$B$3"),
        ("Cumulative Net Loss", metrics["Cumulative Net Loss %"], calc_pct_fmt,
         f"=SUM({table_refs['Net Loss']})/$B$3"),
        ("Facility WAL", metrics["Facility WAL"], calc_fmt,
         f"=SUMPRODUCT({table_refs['Years']},{table_refs['Facility Balance Decline %']})/"
         f"SUM({table_refs['Facility Balance Decline %']})"),
        ("Lender Loss (%)", metrics["Facility / Lender Loss %"], calc_pct_fmt,
         f"=SUM({table_refs['Facility Interest Shortfall']})/$I$7"),
        ("Lender Loss ($)", metrics["Facility / Lender Loss $"], calc_fmt,
         f"=SUM({table_refs['Facility Interest Shortfall']})"),
        ("Levered Equity IRR", metrics["Scenario A Equity IRR - Levered"], calc_pct_fmt,
         f"=IFERROR(IRR({levered_equity_irr_range})*12,0)"),
        ("Unlevered Equity IRR", metrics["Scenario A Equity IRR - Unlevered"], calc_pct_fmt,
         f"=IFERROR(IRR({unlevered_equity_irr_range})*12,0)"),
        ("Leverage Premium", metrics["Scenario A Leverage Premium"], calc_pct_fmt, "=$P$13-$P$14"),
    ], title_fmt, label_fmt)

    ws.merge_range(
        19, 0, 19, 16,
        "Scenario A only: whole-loan collateral finances a warehouse lender and sponsor equity. "
        "No securitization tranches, exchangeable certificates, XS/R, or takeout proceeds are included.",
        note_fmt,
    )

    merge_if_possible(ws, section_row, col_map[COLLATERAL_COLUMNS[0]], col_map[COLLATERAL_COLUMNS[-1]],
                      "Scenario A Asset Side", section_fmt)
    merge_if_possible(ws, section_row, col_map[WAREHOUSE_COLUMNS[0]], col_map[WAREHOUSE_COLUMNS[-1]],
                      "Scenario A Liability - Warehouse Facility", section_fmt)
    merge_if_possible(ws, section_row, col_map[WAREHOUSE_EQUITY_COLUMNS[0]], col_map[UNLEVERED_EQUITY_COLUMNS[-1]],
                      "Scenario A Equity - Levered and Unlevered", section_fmt)

    for col_idx, col in enumerate(table.columns):
        ws.write(header_row, col_idx, col, header_fmt)
    for row_offset, (_, data) in enumerate(table.iterrows()):
        row_idx = data_start + row_offset
        for col_idx, col in enumerate(table.columns):
            fmt = excel_col_format(
                col, asset_fmt, debt_fmt, equity_fmt, pct_fmt, ideal_fmt, None,
                asset_pct_fmt, debt_pct_fmt, equity_pct_fmt, ideal_pct_fmt
            )
            value = data[col]
            formula = warehouse_waterfall_formula(
                col, row_idx, data_start, col_map, input_refs, xl_rowcol_to_cell
            )
            if isinstance(value, str):
                ws.write(row_idx, col_idx, value, fmt)
            elif col in {"Trigger Breached", "Cleanup Call Eligible"}:
                ws.write(row_idx, col_idx, format_bool_for_excel(value), fmt)
            elif formula:
                ws.write_formula(row_idx, col_idx, formula, fmt, value)
            else:
                ws.write(row_idx, col_idx, value, fmt)

    for col_idx, col in enumerate(table.columns):
        ws.set_column(col_idx, col_idx, 16 if len(col) < 18 else 20)
    ws.freeze_panes(data_start, 2)
    write_warehouse_cashflow_helper(
        cashflow_ws, table, col_map, data_start, xl_rowcol_to_cell, header_fmt, calc_fmt
    )
    workbook.close()
    return output.getvalue()


def build_excel_download(
    inputs: RmbsInputs,
    schedule: pd.DataFrame,
    tranche_summary: pd.DataFrame,
    metrics: dict[str, float],
) -> bytes:
    import xlsxwriter
    from xlsxwriter.utility import xl_rowcol_to_cell

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_calc_mode("auto")
    ws = workbook.add_worksheet("RMBS Scenario")
    ws.hide_gridlines(2)
    cashflow_ws = workbook.add_worksheet("Tranche Cashflows")
    cashflow_ws.hide()
    formula_ws = workbook.add_worksheet("Formula Reference")
    formula_ws.hide_gridlines(2)

    title_fmt = workbook.add_format({"bold": True, "font_size": 11})
    note_fmt = workbook.add_format({"italic": True, "font_color": "#555555", "text_wrap": True})
    label_fmt = workbook.add_format({"border": 1, "bold": True, "bg_color": "#f4f4f4"})
    input_fmt = workbook.add_format({"border": 1, "font_color": "blue", "bold": True,
                                     "bg_color": INPUT_BLUE, "num_format": "#,##0.00"})
    input_int_fmt = workbook.add_format({"border": 1, "font_color": "blue", "bold": True,
                                         "bg_color": INPUT_BLUE, "num_format": "#,##0"})
    input_pct_fmt = workbook.add_format({"border": 1, "font_color": "blue", "bold": True,
                                         "bg_color": INPUT_BLUE, "num_format": "0.00%"})
    calc_fmt = workbook.add_format({"border": 1, "bg_color": "white",
                                    "num_format": "#,##0.00;(#,##0.00);-"})
    calc_pct_fmt = workbook.add_format({"border": 1, "bg_color": "white", "num_format": "0.00%"})
    header_fmt = workbook.add_format({"bold": True, "border": 1, "align": "center",
                                      "valign": "bottom", "text_wrap": True})
    section_header_fmt = workbook.add_format({
        "bold": True,
        "border": 2,
        "align": "center",
        "valign": "vcenter",
        "text_wrap": True,
        "bg_color": "#f3f4f6",
    })
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
    equity_pct_fmt = workbook.add_format({"bg_color": EQUITY_PEACH, "border": 1,
                                          "num_format": "0.0%;(0.0%);-"})
    ideal_fmt = workbook.add_format({"bg_color": "white", "border": 1,
                                     "num_format": "#,##0.00;(#,##0.00);-"})
    ideal_pct_fmt = workbook.add_format({"bg_color": "white", "border": 1,
                                         "num_format": "0.0%;(0.0%);-"})
    spacer_fmt = workbook.add_format({"bg_color": "white", "border": 0})
    pct_fmt = workbook.add_format({"border": 1, "num_format": "0.0%;(0.0%);-"})
    text_fmt = workbook.add_format({"border": 1})

    summary_start = 35
    table_start = max(summary_start + len(tranche_summary) + 5, 55)
    section_header_row = table_start
    column_header_row = table_start + 1
    data_start = table_start + 2
    export_schedule = schedule[schedule["Period"] > 0].copy()
    for spacer in SPACER_COLUMNS:
        export_schedule[spacer] = ""
    data_end = data_start + len(export_schedule) - 1
    columns = [col for col in WATERFALL_COLUMNS if col in export_schedule.columns]
    col_map = {col: idx for idx, col in enumerate(columns)}
    table_refs = {
        col: f"{xl_rowcol_to_cell(data_start, idx)}:{xl_rowcol_to_cell(data_end, idx)}"
        for col, idx in col_map.items()
    }
    equity_helper_start_col = len(TRANCHES) * 2 + 2
    levered_equity_irr_range = (
        f"'Tranche Cashflows'!{xl_rowcol_to_cell(1, equity_helper_start_col)}:"
        f"{xl_rowcol_to_cell(1 + len(export_schedule), equity_helper_start_col)}"
    )
    unlevered_equity_irr_range = (
        f"'Tranche Cashflows'!{xl_rowcol_to_cell(1, equity_helper_start_col + 1)}:"
        f"{xl_rowcol_to_cell(1 + len(export_schedule), equity_helper_start_col + 1)}"
    )

    input_refs = {
        "deal_balance": "$B$3",
        "gross_coupon": "$B$4",
        "term_months": "$B$5",
        "seasoning_months": "$B$6",
        "cpr": "$B$7",
        "smm": "$B$8",
        "cdr": "$B$9",
        "mdr": "$B$10",
        "severity": "$B$11",
        "recoveries": "$B$12",
        "yield_target": "$B$13",
        "servicing_fee": "$B$14",
        "admin_fee": "$B$15",
        "aaa_attachment": "$I$3",
        "purchase_price": "$P$4",
        "sofr": "$W$3",
        "spread": "$W$4",
        "facility_rate": "$W$5",
        "advance_rate": "$W$6",
        "initial_facility": "$W$7",
        "lockout": "$AD$3",
        "cum_loss_trigger": "$AD$4",
        "dq_trigger": "$AD$5",
        "cleanup_call": "$AD$6",
    }
    tranche_input_col = 29
    for idx, tranche in enumerate(TRANCHES):
        input_refs[f"{tranche}_size"] = xl_rowcol_to_cell(6 + idx, tranche_input_col, True, True)
        input_refs[f"{tranche}_coupon"] = xl_rowcol_to_cell(6 + len(TRANCHES) + idx, tranche_input_col, True, True)

    write_box(ws, 0, 0, "Collateral / Credit Inputs", [
        ("Deal Balance", inputs.deal_balance, input_int_fmt),
        ("WA Gross Coupon", inputs.gross_coupon_pct / 100, input_pct_fmt),
        ("WA Original Term (Months)", inputs.term_months, input_int_fmt),
        ("WA Seasoning (Months)", inputs.seasoning_months, input_int_fmt),
        ("CPR", inputs.cpr_pct / 100, input_pct_fmt),
        ("SMM", smm(inputs.cpr_pct), calc_pct_fmt, "=1-(1-$B$7)^(1/12)"),
        ("CDR", inputs.cdr_pct / 100, input_pct_fmt),
        ("MDR", mdr(inputs.cdr_pct), calc_pct_fmt, "=1-(1-$B$9)^(1/12)"),
        ("Severity (Assumed)", inputs.severity_pct / 100, input_pct_fmt),
        ("Recoveries", 1 - rate(inputs.severity_pct), calc_pct_fmt, "=1-$B$11"),
        ("Yield Target", inputs.yield_target_pct / 100, input_pct_fmt),
        ("Servicing Fee", inputs.servicing_fee_pct / 100, input_pct_fmt),
        ("Admin Fee", inputs.admin_fee_pct / 100, input_pct_fmt),
    ], title_fmt, label_fmt)

    write_box(ws, 0, 7, "Deal Metrics", [
        ("Original AAA Attachment", inputs.aaa_attachment_pct / 100, input_pct_fmt),
        ("WA Original FICO", inputs.wa_fico, input_int_fmt),
        ("WA Orig CLTV", inputs.wa_cltv_pct / 100, input_pct_fmt),
        ("WA DSCR", inputs.wa_dscr, calc_fmt),
        ("AAA Loss Severity", inputs.aaa_loss_severity_pct / 100, calc_pct_fmt),
        ("B Loss Severity", inputs.b_loss_severity_pct / 100, calc_pct_fmt),
        ("AAA Foreclosure Freq", inputs.aaa_foreclosure_frequency_pct / 100, calc_pct_fmt),
        ("B Foreclosure Freq", inputs.b_foreclosure_frequency_pct / 100, calc_pct_fmt),
        ("ARM", inputs.arm_pct / 100, input_pct_fmt),
        ("IO", inputs.io_pct / 100, input_pct_fmt),
    ], title_fmt, label_fmt)

    write_box(ws, 0, 21, "Warehouse / Analytics - Not PDF", [
        ("SOFR", inputs.sofr_pct / 100, input_pct_fmt),
        ("Spread", inputs.spread_pct / 100, input_pct_fmt),
        ("Facility Rate", metrics["Facility Rate"], calc_pct_fmt, "=$W$3+$W$4"),
        ("Advance Rate", inputs.advance_rate_pct / 100, input_pct_fmt),
        ("Initial Facility Notional", metrics["Initial Facility Notional"], calc_fmt, "=$B$3*$W$6"),
    ], title_fmt, label_fmt)

    tranche_box_rows = [
        ("Stepdown Lockout", inputs.lockout_months, input_int_fmt),
        ("Cum Loss Trigger", inputs.stepdown_cum_loss_trigger_pct / 100, input_pct_fmt),
        ("DQ Trigger", inputs.stepdown_dq_trigger_pct / 100, input_pct_fmt),
        ("Clean-up Call Factor", inputs.cleanup_call_factor_pct / 100, input_pct_fmt),
    ]
    tranche_box_rows.extend(
        (f"{TRANCHE_LABELS[tranche]} Size",
         getattr(inputs, TRANCHE_SIZE_FIELDS[tranche]) / 100,
         input_pct_fmt)
        for tranche in TRANCHES
    )
    tranche_box_rows.extend(
        (f"{TRANCHE_LABELS[tranche]} Coupon",
         getattr(inputs, TRANCHE_COUPON_FIELDS[tranche]) / 100,
         input_pct_fmt)
        for tranche in TRANCHES
    )
    write_box(ws, 0, 28, "Scenario B Debt Notes - Not PDF", tranche_box_rows, title_fmt, label_fmt)

    write_box(ws, 0, 14, "Outputs", [
        ("Purchase Px / Value (%)", metrics["Purchase Price (%)"], calc_pct_fmt, "=$P$4/$B$3"),
        ("Purchase Px ($)", metrics["Purchase Price ($)"], calc_fmt,
         f"=SUM({table_refs['Cashflow Present Value']})"),
        ("Collateral WAL", metrics["Collateral WAL"], calc_fmt,
         f"=SUMPRODUCT({table_refs['Years']},{table_refs['Balance Decline %']})/"
         f"SUM({table_refs['Balance Decline %']})"),
        ("Macaulay Duration", metrics["Macaulay Duration"], calc_fmt,
         f"=SUMPRODUCT({table_refs['Years']},{table_refs['Cashflow Present Value']})/"
         f"SUM({table_refs['Cashflow Present Value']})"),
        ("Modified Duration", metrics["Modified Duration"], calc_fmt, "=$P$6/(1+$B$13/2)"),
        ("Cumulative Defaults", metrics["Cumulative Defaults %"], calc_pct_fmt,
         f"=SUM({table_refs['Defaults']})/$B$3"),
        ("Cumulative Net Loss", metrics["Cumulative Net Loss %"], calc_pct_fmt,
         f"=SUM({table_refs['Net Loss']})/$B$3"),
        ("Initial Senior CE", metrics["Initial Senior Credit Enhancement"], calc_pct_fmt,
         f"=1-{input_refs['A1_size']}"),
        ("Final Senior CE", metrics["Final Senior Credit Enhancement"], calc_pct_fmt,
         f"={xl_rowcol_to_cell(data_end, col_map['Credit Enhancement %'])}"),
        ("Senior WAL", metrics["Senior WAL"], calc_fmt,
         f"=IFERROR(SUMPRODUCT({table_refs['Years']},{table_refs['A1 Principal Paid']})/"
         f"($B$3*{input_refs['A1_size']}),0)"),
        ("Senior IRR", metrics["Senior IRR"], calc_pct_fmt,
         "=IFERROR(IRR('Tranche Cashflows'!A2:A500)*12,0)"),
        ("Facility WAL", metrics["Facility WAL"], calc_fmt,
         f"=SUMPRODUCT({table_refs['Years']},{table_refs['Facility Balance Decline %']})/"
         f"SUM({table_refs['Facility Balance Decline %']})"),
        ("Lender Loss (%)", metrics["Facility / Lender Loss %"], calc_pct_fmt,
         f"=SUM({table_refs['Facility Interest Shortfall']})/$W$7"),
        ("Lender Loss ($)", metrics["Facility / Lender Loss $"], calc_fmt,
         f"=SUM({table_refs['Facility Interest Shortfall']})"),
        ("Total Excess Spread", metrics["Total Excess Spread"], calc_fmt,
         f"=SUM({table_refs['Excess Spread']})"),
        ("Residual Excess Spread", metrics["Residual Excess Spread"], calc_fmt,
         f"=SUM({table_refs['Residual Excess Spread']})"),
        ("XS/R Strict Equity Value", metrics["XS/R Strict Equity Value"], calc_fmt,
         f"=SUM({table_refs['XS/R Equity PV']})"),
        ("Sponsor Retained Position", metrics["Sponsor Retained Position"], calc_fmt,
         f"=SUM({'+'.join('$B$3*' + input_refs[f'{tranche}_size'] for tranche in B_NOTE_TRANCHES)})+"
         f"SUM({table_refs['XS/R Equity PV']})"),
        ("First Trigger Period", metrics["First Trigger Period"], calc_fmt,
         f'=IFERROR(INDEX({table_refs["Period"]},MATCH("Yes",{table_refs["Trigger Breached"]},0)),0)'),
        ("Scenario A Equity IRR — Levered", metrics["Scenario A Equity IRR - Levered"], calc_pct_fmt,
         f"=IFERROR(IRR({levered_equity_irr_range})*12,0)"),
        ("Scenario A Equity IRR — Unlevered", metrics["Scenario A Equity IRR - Unlevered"], calc_pct_fmt,
         f"=IFERROR(IRR({unlevered_equity_irr_range})*12,0)"),
    ], title_fmt, label_fmt)

    ws.merge_range(
        19, 0, 19, 12,
        "Note: Warehouse Facility and Tranche Waterfall are parallel alternative analyses. "
        "Scenario A assumes the full collateral cashflow finances a warehouse lender with no tranches. "
        "Scenario B assumes the same full collateral cashflow is securitized into rated tranches with no warehouse.",
        note_fmt,
    )

    row = summary_start
    ws.write(row, 0, "Tranche Summary", title_fmt)
    for col_idx, col in enumerate(tranche_summary.columns):
        ws.write(row + 1, col_idx, col, header_fmt)
    for row_offset, (_, data) in enumerate(tranche_summary.iterrows(), start=2):
        tranche_idx = row_offset - 2
        tranche = TRANCHES[tranche_idx] if tranche_idx < len(TRANCHES) else None
        for col_idx, col in enumerate(tranche_summary.columns):
            fmt = calc_pct_fmt if col in PERCENT_COLUMNS else calc_fmt
            value = data[col]
            formula = (
                tranche_summary_formula(
                    col, tranche, row + row_offset, row + 2, table_refs, input_refs,
                    xl_rowcol_to_cell,
                )
                if tranche else None
            )
            if formula:
                ws.write_formula(row + row_offset, col_idx, formula, fmt, value)
            elif isinstance(value, str):
                ws.write(row + row_offset, col_idx, value, text_fmt)
            else:
                ws.write(row + row_offset, col_idx, value, fmt)

    write_alternative_scenario_headers(ws, section_header_row, col_map, section_header_fmt, note_fmt)
    for col_idx, col in enumerate(columns):
        ws.write(column_header_row, col_idx, "" if col in SPACER_COLUMNS else col, header_fmt)
    for row_offset, (_, data) in enumerate(export_schedule[columns].iterrows(), start=0):
        row_idx = data_start + row_offset
        for col_idx, col in enumerate(columns):
            value = data[col]
            fmt = excel_col_format(
                col, asset_fmt, debt_fmt, equity_fmt, pct_fmt, ideal_fmt, spacer_fmt,
                asset_pct_fmt, debt_pct_fmt, equity_pct_fmt, ideal_pct_fmt
            )
            formula = rmbs_waterfall_formula(
                col, row_idx, data_start, col_map, input_refs, xl_rowcol_to_cell
            )
            if formula:
                cached = format_bool_for_excel(value) if col in {
                    "Trigger Breached", "Cleanup Call Eligible"
                } else value
                ws.write_formula(row_idx, col_idx, formula, fmt, cached)
            elif isinstance(value, str):
                ws.write(row_idx, col_idx, value, fmt)
            elif col in {"Trigger Breached", "Cleanup Call Eligible"}:
                ws.write(row_idx, col_idx, format_bool_for_excel(value), fmt)
            else:
                ws.write(row_idx, col_idx, value, fmt)

    for col_idx, col in enumerate(columns):
        if col in SPACER_COLUMNS:
            ws.set_column(col_idx, col_idx, 4)
        else:
            ws.set_column(col_idx, col_idx, 16 if len(col) < 18 else 20)
    ws.freeze_panes(data_start, 2)
    write_cashflow_helper(
        cashflow_ws, columns, col_map, data_start, data_end, row + 2,
        xl_rowcol_to_cell, workbook, header_fmt, calc_fmt, input_refs
    )

    formula_ws.write(0, 0, "Formula Reference", title_fmt)
    for idx, (name, formula) in enumerate(formula_reference_rows(), start=2):
        formula_ws.write(idx, 0, name, label_fmt)
        formula_ws.write(idx, 1, formula, calc_fmt)
    formula_ws.set_column(0, 0, 24)
    formula_ws.set_column(1, 1, 88)

    workbook.close()
    return output.getvalue()


def write_warehouse_cashflow_helper(
    cashflow_ws,
    table: pd.DataFrame,
    col_map: dict[str, int],
    data_start: int,
    cell,
    header_fmt,
    calc_fmt,
) -> None:
    cashflow_ws.write(0, 0, "Scenario A Levered Equity Cashflow", header_fmt)
    cashflow_ws.write(0, 1, "Scenario A Unlevered Equity Cashflow", header_fmt)
    cashflow_ws.write_formula(1, 0, "=-('Scenario A Warehouse'!$B$3-'Scenario A Warehouse'!$I$7)", calc_fmt)
    cashflow_ws.write_formula(1, 1, "=-'Scenario A Warehouse'!$B$3", calc_fmt)
    for row_offset in range(len(table)):
        source_row = data_start + row_offset
        helper_row = row_offset + 2
        cashflow_ws.write_formula(
            helper_row,
            0,
            f"='Scenario A Warehouse'!{cell(source_row, col_map['Warehouse Equity Cashflow'])}",
            calc_fmt,
        )
        cashflow_ws.write_formula(
            helper_row,
            1,
            f"='Scenario A Warehouse'!{cell(source_row, col_map['Unlevered Equity Cashflow'])}",
            calc_fmt,
        )
    cashflow_ws.set_column(0, 1, 26)


def write_box(ws, row: int, col: int, title: str, rows: list[tuple], title_fmt, label_fmt) -> None:
    ws.write(row, col, title, title_fmt)
    for offset, row_data in enumerate(rows, start=2):
        label, value, value_fmt, *formula = row_data
        ws.write(row + offset, col, label, label_fmt)
        if formula:
            ws.write_formula(row + offset, col + 1, formula[0], value_fmt, value)
        else:
            ws.write(row + offset, col + 1, value, value_fmt)


def write_alternative_scenario_headers(ws, row: int, col_map: dict[str, int], fmt, note_fmt) -> None:
    merge_if_possible(
        ws,
        row,
        col_map[COLLATERAL_COLUMNS[0]],
        col_map[COLLATERAL_COLUMNS[-1]],
        "Scenario A Asset Side — whole-loan collateral engine (white ideal schedule, blue credit-adjusted pool)",
        fmt,
    )
    merge_if_possible(
        ws,
        row,
        col_map[WAREHOUSE_COLUMNS[0]],
        col_map[WAREHOUSE_COLUMNS[-1]],
        "Scenario A Liability — warehouse/facility lender, pre-securitization (no tranches)",
        fmt,
    )
    merge_if_possible(
        ws,
        row,
        col_map[WAREHOUSE_EQUITY_COLUMNS[0]],
        col_map[WAREHOUSE_EQUITY_COLUMNS[-1]],
        "Scenario A Equity — Levered (sponsor's residual after warehouse facility)",
        fmt,
    )
    merge_if_possible(
        ws,
        row,
        col_map[UNLEVERED_EQUITY_COLUMNS[0]],
        col_map[UNLEVERED_EQUITY_COLUMNS[-1]],
        "Scenario A Equity — Unlevered (sponsor owns 100% of pool, no warehouse)",
        fmt,
    )
    merge_if_possible(
        ws,
        row - 1,
        col_map[WAREHOUSE_EQUITY_COLUMNS[0]],
        col_map[UNLEVERED_EQUITY_COLUMNS[-1]],
        "Compare the levered and unlevered Scenario A equity IRRs to read the leverage premium of warehouse financing.",
        note_fmt,
    )
    for spacer in SPACER_COLUMNS:
        ws.write(row, col_map[spacer], "", fmt)
    merge_if_possible(
        ws,
        row,
        col_map[TAKEOUT_COLUMNS[0]],
        col_map[TRANCHE_COLUMNS[-1]],
        "Scenario B Debt — securitization note waterfall; debt proceeds repay Scenario A facility",
        fmt,
    )
    merge_if_possible(
        ws,
        row,
        col_map[SCENARIO_B_EQUITY_COLUMNS[0]],
        col_map[SCENARIO_B_EQUITY_COLUMNS[-1]],
        "Scenario B Equity — XS + R strict equity, no principal balance",
        fmt,
    )


def merge_if_possible(ws, row: int, first_col: int, last_col: int, value: str, fmt) -> None:
    if first_col == last_col:
        ws.write(row, first_col, value, fmt)
    else:
        ws.merge_range(row, first_col, row, last_col, value, fmt)


def tranche_summary_formula(
    col: str,
    tranche: str,
    row_idx: int,
    first_summary_row: int,
    refs: dict[str, str],
    input_refs: dict[str, str],
    cell,
) -> str | None:
    size_ref = input_refs[f"{tranche}_size"]
    coupon_ref = input_refs[f"{tranche}_coupon"]
    tranche_idx = TRANCHES.index(tranche)
    cashflow_col = cell(1, tranche_idx).split("$")[-1].rstrip("0123456789")
    # The helper sheet uses row 2 as the initial outflow and then period 1..N.
    cashflow_range = f"'Tranche Cashflows'!{cashflow_col}2:{cashflow_col}500"
    initial_cell = cell(row_idx, 1)
    if col == "Initial Balance":
        return f"=$B$3*{size_ref}"
    if col == "Coupon":
        return f"={coupon_ref}"
    if col == "Principal Paid":
        return f"=SUM({refs[f'{tranche} Principal Paid']})"
    if col == "Interest Paid":
        return f"=SUM({refs[f'{tranche} Interest Paid']})"
    if col == "Loss Allocated":
        return f"=SUM({refs[f'{tranche} Loss Allocated']})"
    if col == "Ending Balance":
        return f"=INDEX({refs[f'{tranche} Ending Balance']},ROWS({refs[f'{tranche} Ending Balance']}))"
    if col == "WAL":
        return f"=IFERROR(SUMPRODUCT({refs['Years']},{refs[f'{tranche} Principal Paid']})/{initial_cell},0)"
    if col == "IRR":
        return f"=IFERROR(IRR({cashflow_range})*12,0)"
    return None


def warehouse_waterfall_formula(
    col: str,
    row_idx: int,
    data_start: int,
    col_map: dict[str, int],
    input_refs: dict[str, str],
    cell,
) -> str | None:
    def at(name: str, row: int = row_idx) -> str:
        return cell(row, col_map[name])

    def prev(name: str) -> str:
        return cell(row_idx - 1, col_map[name])

    first_projection_row = row_idx == data_start
    formulas = {
        "Period": "=1" if first_projection_row else f"={prev('Period')}+1",
        "Years": f"={at('Period')}/12",
        "Scheduled Collateral Beginning Balance": (
            f"={input_refs['deal_balance']}"
            if first_projection_row else f"={prev('Scheduled Collateral Ending Balance')}"
        ),
        "Scheduled Payment": (
            f"=PMT({input_refs['gross_coupon']}/12,{input_refs['term_months']},"
            f"-{input_refs['deal_balance']})"
        ),
        "Scheduled Interest": (
            f"={at('Scheduled Collateral Beginning Balance')}*{input_refs['gross_coupon']}/12"
        ),
        "Scheduled Principal": (
            f"=MIN(MAX({at('Scheduled Payment')}-{at('Scheduled Interest')},0),"
            f"{at('Scheduled Collateral Beginning Balance')})"
        ),
        "Scheduled Collateral Ending Balance": (
            f"=MAX({at('Scheduled Collateral Beginning Balance')}-{at('Scheduled Principal')},0)"
        ),
        "Collateral Beginning Balance": (
            f"={input_refs['deal_balance']}" if first_projection_row else f"={prev('Collateral Ending Balance')}"
        ),
        "Survival Factor": (
            f"=IFERROR({at('Collateral Beginning Balance')}/"
            f"{at('Scheduled Collateral Beginning Balance')},0)"
        ),
        "Surviving Scheduled Payment": f"={at('Scheduled Payment')}*{at('Survival Factor')}",
        "Surviving Scheduled Principal": f"={at('Scheduled Principal')}*{at('Survival Factor')}",
        "Defaults": f"={at('Collateral Beginning Balance')}*{input_refs['mdr']}",
        "Recoveries": f"={at('Defaults')}*{input_refs['recoveries']}",
        "Net Loss": f"={at('Defaults')}-{at('Recoveries')}",
        "Cumulative Defaults %": (
            f"={at('Defaults')}/{input_refs['deal_balance']}"
            if first_projection_row
            else f"={prev('Cumulative Defaults %')}+{at('Defaults')}/{input_refs['deal_balance']}"
        ),
        "Cumulative Net Loss %": (
            f"={at('Net Loss')}/{input_refs['deal_balance']}"
            if first_projection_row
            else f"={prev('Cumulative Net Loss %')}+{at('Net Loss')}/{input_refs['deal_balance']}"
        ),
        "Remaining Performing Balance": (
            f"=MAX({at('Collateral Beginning Balance')}-{at('Defaults')},0)"
        ),
        "Servicing Fee": f"={at('Remaining Performing Balance')}*{input_refs['servicing_fee']}/12",
        "Admin Fee": f"={at('Remaining Performing Balance')}*{input_refs['admin_fee']}/12",
        "Scheduled Payment of Performing Collateral": (
            f"={at('Surviving Scheduled Payment')}*IFERROR("
            f"{at('Remaining Performing Balance')}/{at('Collateral Beginning Balance')},0)"
        ),
        "Collateral Interest": f"={at('Remaining Performing Balance')}*{input_refs['gross_coupon']}/12",
        "Scheduled Principal of Performing Collateral": (
            f"={at('Scheduled Payment of Performing Collateral')}-{at('Collateral Interest')}"
        ),
        "Prepayments": (
            f"=MAX({at('Collateral Beginning Balance')}-{at('Surviving Scheduled Principal')},0)*"
            f"{input_refs['smm']}"
        ),
        "Principal Collections": (
            f"=MIN({at('Scheduled Principal of Performing Collateral')}+{at('Prepayments')}+"
            f"{at('Recoveries')},{at('Collateral Beginning Balance')})"
        ),
        "Asset Total Cashflow": f"={at('Principal Collections')}+{at('Collateral Interest')}",
        "Cashflow Present Value": (
            f"={at('Asset Total Cashflow')}/(1+{input_refs['yield_target']}/12)^{at('Period')}"
        ),
        "Collateral Ending Balance": (
            f"=MAX({at('Collateral Beginning Balance')}-{at('Defaults')}-"
            f"{at('Scheduled Principal of Performing Collateral')}-{at('Prepayments')},0)"
        ),
        "Balance Decline %": (
            f"=({at('Collateral Beginning Balance')}-{at('Collateral Ending Balance')})/"
            f"{input_refs['deal_balance']}"
        ),
        "Facility Beginning Balance": (
            f"={input_refs['initial_facility']}" if first_projection_row else f"={prev('Facility Ending Balance')}"
        ),
        "Facility Interest Owed": (
            f"={at('Facility Beginning Balance')}*{input_refs['facility_rate']}/12"
        ),
        "Facility Total Cashflow": (
            f"=MIN({at('Asset Total Cashflow')},{at('Facility Interest Owed')}+"
            f"{at('Facility Beginning Balance')})"
        ),
        "Facility Interest Paid": (
            f"=MIN({at('Facility Interest Owed')},{at('Facility Total Cashflow')})"
        ),
        "Facility Interest Shortfall": f"={at('Facility Interest Owed')}-{at('Facility Interest Paid')}",
        "Facility Principal Paid": f"={at('Facility Total Cashflow')}-{at('Facility Interest Paid')}",
        "Facility Ending Balance": (
            f"=MAX({at('Facility Beginning Balance')}-{at('Facility Principal Paid')},0)"
        ),
        "Facility Balance Decline %": (
            f"=IFERROR(({at('Facility Beginning Balance')}-{at('Facility Ending Balance')})/"
            f"{input_refs['initial_facility']},0)"
        ),
        "Advance Rate to Par": (
            f"=IFERROR({at('Facility Ending Balance')}/{at('Collateral Ending Balance')},0)"
        ),
        "Advance Rate to Purchase Price": (
            f"={at('Advance Rate to Par')}*{input_refs['deal_balance']}/{input_refs['purchase_price']}"
        ),
        "Warehouse Equity Beginning Balance": (
            f"=MAX({at('Collateral Beginning Balance')}-{at('Facility Beginning Balance')},0)"
        ),
        "Warehouse Equity Cashflow": f"={at('Asset Total Cashflow')}-{at('Facility Total Cashflow')}",
        "Warehouse Equity Ending Balance": (
            f"=MAX({at('Collateral Ending Balance')}-{at('Facility Ending Balance')},0)"
        ),
        "Warehouse Equity ROE": (
            f"=IFERROR({at('Warehouse Equity Cashflow')}*12/"
            f"{at('Warehouse Equity Beginning Balance')},0)"
        ),
        "Unlevered Equity Beginning Balance": f"={at('Collateral Beginning Balance')}",
        "Unlevered Equity Cashflow": (
            f"={at('Asset Total Cashflow')}-{at('Servicing Fee')}-{at('Admin Fee')}"
        ),
        "Unlevered Equity Ending Balance": f"={at('Collateral Ending Balance')}",
        "Unlevered Equity ROE": (
            f"=IFERROR({at('Unlevered Equity Cashflow')}*12/"
            f"{at('Unlevered Equity Beginning Balance')},0)"
        ),
    }
    return formulas.get(col)


def rmbs_waterfall_formula(
    col: str,
    row_idx: int,
    data_start: int,
    col_map: dict[str, int],
    input_refs: dict[str, str],
    cell,
) -> str | None:
    def at(name: str, row: int = row_idx) -> str:
        return cell(row, col_map[name])

    def prev(name: str) -> str:
        return cell(row_idx - 1, col_map[name])

    first_projection_row = row_idx == data_start

    if col in SPACER_COLUMNS:
        return None

    if col in {
        "Period",
        "Years",
        "Payment Mode",
        "Trigger Breached",
        "Scheduled Collateral Beginning Balance",
        "Scheduled Payment",
        "Scheduled Interest",
        "Scheduled Principal",
        "Scheduled Collateral Ending Balance",
        "Collateral Beginning Balance",
        "Survival Factor",
        "Surviving Scheduled Payment",
        "Surviving Scheduled Principal",
        "Collateral Interest",
        "Servicing Fee",
        "Admin Fee",
        "Prepayments",
        "Defaults",
        "Recoveries",
        "Net Loss",
        "Cumulative Defaults %",
        "Cumulative Net Loss %",
        "Remaining Performing Balance",
        "Scheduled Payment of Performing Collateral",
        "Scheduled Principal of Performing Collateral",
        "Principal Collections",
        "Asset Total Cashflow",
        "Cashflow Present Value",
        "Interest Available",
        "Excess Spread",
        "Residual Excess Spread",
        "Collateral Ending Balance",
        "Balance Decline %",
        "Facility Beginning Balance",
        "Facility Interest Owed",
        "Facility Interest Paid",
        "Facility Interest Shortfall",
        "Facility Principal Paid",
        "Facility Total Cashflow",
        "Facility Ending Balance",
        "Facility Balance Decline %",
        "Advance Rate to Purchase Price",
        "Advance Rate to Par",
        "Warehouse Equity Beginning Balance",
        "Warehouse Equity Cashflow",
        "Warehouse Equity Ending Balance",
        "Warehouse Equity ROE",
        "Unlevered Equity Beginning Balance",
        "Unlevered Equity Cashflow",
        "Unlevered Equity Ending Balance",
        "Unlevered Equity ROE",
        "Scenario B Debt Proceeds",
        "Warehouse Takeout Surplus / (Shortfall)",
        "Bond Ending Balance",
        "Credit Enhancement %",
        "Cleanup Call Eligible",
        "XS/R Equity Cashflow",
        "XS/R Equity PV",
    }:
        tranche_interest_cols = "+".join(
            at(f"{tranche} Interest Paid")
            for tranche in TRANCHES
            if f"{tranche} Interest Paid" in col_map
        ) or "0"
        collateral_formulas = {
            "Period": "=1" if first_projection_row else f"={prev('Period')}+1",
            "Years": f"={at('Period')}/12",
            "Scheduled Collateral Beginning Balance": (
                f"={input_refs['deal_balance']}"
                if first_projection_row else f"={prev('Scheduled Collateral Ending Balance')}"
            ),
            "Scheduled Payment": (
                f"=PMT({input_refs['gross_coupon']}/12,{input_refs['term_months']},"
                f"-{input_refs['deal_balance']})"
            ),
            "Scheduled Interest": (
                f"={at('Scheduled Collateral Beginning Balance')}*"
                f"{input_refs['gross_coupon']}/12"
            ),
            "Scheduled Principal": (
                f"=MIN(MAX({at('Scheduled Payment')}-{at('Scheduled Interest')},0),"
                f"{at('Scheduled Collateral Beginning Balance')})"
            ),
            "Scheduled Collateral Ending Balance": (
                f"=MAX({at('Scheduled Collateral Beginning Balance')}-"
                f"{at('Scheduled Principal')},0)"
            ),
            "Trigger Breached": (
                f'=IF(OR({at("Cumulative Net Loss %")}>{input_refs["cum_loss_trigger"]},'
                f'{input_refs["mdr"]}*12>{input_refs["dq_trigger"]}),"Yes","-")'
            ),
            "Payment Mode": (
                f'=IF(OR({at("Period")}<={input_refs["lockout"]},'
                f'{at("Trigger Breached")}="Yes"),"Sequential","Modified pro-rata")'
            ),
            "Collateral Beginning Balance": (
                f"={input_refs['deal_balance']}"
                if first_projection_row else f"={prev('Collateral Ending Balance')}"
            ),
            "Survival Factor": (
                f"=IFERROR({at('Collateral Beginning Balance')}/"
                f"{at('Scheduled Collateral Beginning Balance')},0)"
            ),
            "Surviving Scheduled Payment": (
                f"={at('Scheduled Payment')}*{at('Survival Factor')}"
            ),
            "Surviving Scheduled Principal": (
                f"={at('Scheduled Principal')}*{at('Survival Factor')}"
            ),
            "Servicing Fee": (
                f"={at('Remaining Performing Balance')}*{input_refs['servicing_fee']}/12"
            ),
            "Admin Fee": (
                f"={at('Remaining Performing Balance')}*{input_refs['admin_fee']}/12"
            ),
            "Defaults": f"={at('Collateral Beginning Balance')}*{input_refs['mdr']}",
            "Recoveries": f"={at('Defaults')}*{input_refs['recoveries']}",
            "Net Loss": f"={at('Defaults')}-{at('Recoveries')}",
            "Cumulative Defaults %": (
                f"={at('Defaults')}/{input_refs['deal_balance']}"
                if first_projection_row
                else f"={prev('Cumulative Defaults %')}+{at('Defaults')}/{input_refs['deal_balance']}"
            ),
            "Cumulative Net Loss %": (
                f"={at('Net Loss')}/{input_refs['deal_balance']}"
                if first_projection_row
                else f"={prev('Cumulative Net Loss %')}+{at('Net Loss')}/{input_refs['deal_balance']}"
            ),
            "Remaining Performing Balance": (
                f"=MAX({at('Collateral Beginning Balance')}-{at('Defaults')},0)"
            ),
            "Scheduled Payment of Performing Collateral": (
                f"={at('Surviving Scheduled Payment')}*IFERROR("
                f"{at('Remaining Performing Balance')}/{at('Collateral Beginning Balance')},0)"
            ),
            "Collateral Interest": (
                f"={at('Remaining Performing Balance')}*{input_refs['gross_coupon']}/12"
            ),
            "Scheduled Principal of Performing Collateral": (
                f"={at('Scheduled Payment of Performing Collateral')}-{at('Collateral Interest')}"
            ),
            "Prepayments": (
                f"=MAX({at('Collateral Beginning Balance')}-"
                f"{at('Surviving Scheduled Principal')},0)*{input_refs['smm']}"
            ),
            "Principal Collections": (
                f"=MIN({at('Scheduled Principal of Performing Collateral')}+{at('Prepayments')}+"
                f"{at('Recoveries')},{at('Collateral Beginning Balance')})"
            ),
            "Asset Total Cashflow": (
                f"={at('Principal Collections')}+{at('Collateral Interest')}"
            ),
            "Cashflow Present Value": (
                f"={at('Asset Total Cashflow')}/(1+{input_refs['yield_target']}/12)^"
                f"{at('Period')}"
            ),
            "Interest Available": (
                f"=MAX({at('Collateral Interest')}-{at('Servicing Fee')}-{at('Admin Fee')},0)"
            ),
            "Excess Spread": f"=MAX({at('Interest Available')}-({tranche_interest_cols}),0)",
            "Residual Excess Spread": (
                f'=IF({at("Payment Mode")}="Sequential",0,{at("Excess Spread")})'
            ),
            "Collateral Ending Balance": (
                f"=MAX({at('Collateral Beginning Balance')}-{at('Defaults')}-"
                f"{at('Scheduled Principal of Performing Collateral')}-{at('Prepayments')},0)"
            ),
            "Balance Decline %": (
                f"=({at('Collateral Beginning Balance')}-{at('Collateral Ending Balance')})/"
                f"{input_refs['deal_balance']}"
            ),
            "Facility Beginning Balance": (
                f"={input_refs['initial_facility']}"
                if first_projection_row else f"={prev('Facility Ending Balance')}"
            ),
            "Facility Interest Owed": (
                f"={at('Facility Beginning Balance')}*{input_refs['facility_rate']}/12"
            ),
            "Facility Total Cashflow": (
                f"=MIN({at('Asset Total Cashflow')},{at('Facility Interest Owed')}+"
                f"{at('Facility Beginning Balance')})"
            ),
            "Facility Interest Paid": (
                f"=MIN({at('Facility Interest Owed')},{at('Facility Total Cashflow')})"
            ),
            "Facility Interest Shortfall": (
                f"={at('Facility Interest Owed')}-{at('Facility Interest Paid')}"
            ),
            "Facility Principal Paid": (
                f"={at('Facility Total Cashflow')}-{at('Facility Interest Paid')}"
            ),
            "Facility Ending Balance": (
                f"=MAX({at('Facility Beginning Balance')}-{at('Facility Principal Paid')},0)"
            ),
            "Facility Balance Decline %": (
                f"=IFERROR(({at('Facility Beginning Balance')}-{at('Facility Ending Balance')})/"
                f"{input_refs['initial_facility']},0)"
            ),
            "Advance Rate to Par": (
                f"=IFERROR({at('Facility Ending Balance')}/{at('Collateral Ending Balance')},0)"
            ),
            "Advance Rate to Purchase Price": (
                f"={at('Advance Rate to Par')}*{input_refs['deal_balance']}/"
                f"{input_refs['purchase_price']}"
            ),
            "Warehouse Equity Beginning Balance": (
                f"=MAX({at('Collateral Beginning Balance')}-{at('Facility Beginning Balance')},0)"
            ),
            "Warehouse Equity Cashflow": (
                f"={at('Asset Total Cashflow')}-{at('Facility Total Cashflow')}"
            ),
            "Warehouse Equity Ending Balance": (
                f"=MAX({at('Collateral Ending Balance')}-{at('Facility Ending Balance')},0)"
            ),
            "Warehouse Equity ROE": (
                f"=IFERROR({at('Warehouse Equity Cashflow')}*12/{at('Warehouse Equity Beginning Balance')},0)"
            ),
            "Unlevered Equity Beginning Balance": f"={at('Collateral Beginning Balance')}",
            "Unlevered Equity Cashflow": (
                f"={at('Asset Total Cashflow')}-{at('Servicing Fee')}-{at('Admin Fee')}"
            ),
            "Unlevered Equity Ending Balance": f"={at('Collateral Ending Balance')}",
            "Unlevered Equity ROE": (
                f"=IFERROR({at('Unlevered Equity Cashflow')}*12/"
                f"{at('Unlevered Equity Beginning Balance')},0)"
            ),
            "Scenario B Debt Proceeds": (
                "=" + "+".join(
                    f"{input_refs['deal_balance']}*{input_refs[f'{tranche}_size']}"
                    for tranche in TRANCHES
                )
            ),
            "Warehouse Takeout Surplus / (Shortfall)": (
                f"={at('Scenario B Debt Proceeds')}-{input_refs['initial_facility']}"
            ),
            "Bond Ending Balance": (
                "=" + "+".join(at(f"{tranche} Ending Balance") for tranche in TRANCHES)
            ),
            "Credit Enhancement %": (
                f"=IFERROR(({at('Collateral Ending Balance')}-{at('A1 Ending Balance')})/"
                f"{at('Collateral Ending Balance')},0)"
            ),
            "Cleanup Call Eligible": (
                f'=IF({at("Collateral Ending Balance")}<={input_refs["deal_balance"]}*'
                f'{input_refs["cleanup_call"]},"Yes","-")'
            ),
            "XS/R Equity Cashflow": f"={at('Residual Excess Spread')}",
            "XS/R Equity PV": (
                f"={at('XS/R Equity Cashflow')}/(1+{input_refs['yield_target']}/12)^"
                f"{at('Period')}"
            ),
        }
        return collateral_formulas[col]

    for tranche in TRANCHES:
        if not col.startswith(f"{tranche} "):
            continue
        post_loss = f"MAX({at(f'{tranche} Beginning Balance')}-{at(f'{tranche} Loss Allocated')},0)"
        if col == f"{tranche} Beginning Balance":
            if first_projection_row:
                return f"={input_refs['deal_balance']}*{input_refs[f'{tranche}_size']}"
            return f"={prev(f'{tranche} Ending Balance')}"
        if col == f"{tranche} Loss Allocated":
            return tranche_loss_formula(tranche, at)
        if col == f"{tranche} Interest Paid":
            prior_paid = "+".join(
                at(f"{prior} Interest Paid")
                for prior in TRANCHES[:TRANCHES.index(tranche)]
            ) or "0"
            shortfall = previous_shortfall_ref(tranche, row_idx, data_start, cell)
            return (
                f"=MIN(MAX(({post_loss})*{input_refs[f'{tranche}_coupon']}/12+"
                f"{shortfall},0),MAX({at('Interest Available')}-({prior_paid}),0))"
            )
        if col == f"{tranche} Principal Paid":
            principal_available = (
                f"({at('Principal Collections')}+IF({at('Payment Mode')}="
                f'"Sequential",{at("Excess Spread")},0))'
            )
            return tranche_principal_formula(tranche, at, post_loss, principal_available)
        if col == f"{tranche} Ending Balance":
            return (
                f"=MAX({at(f'{tranche} Beginning Balance')}-{at(f'{tranche} Loss Allocated')}-"
                f"{at(f'{tranche} Principal Paid')},0)"
            )
    return None


def tranche_loss_formula(tranche: str, at) -> str:
    loss_order = list(reversed(TRANCHES))
    prior_losses = [
        at(f"{prior} Loss Allocated")
        for prior in loss_order[:loss_order.index(tranche)]
    ]
    already_allocated = "+".join(prior_losses) if prior_losses else "0"
    return (
        f"=MIN({at(f'{tranche} Beginning Balance')},"
        f"MAX({at('Net Loss')}-({already_allocated}),0))"
    )


def tranche_principal_formula(tranche: str, at, post_loss: str, principal_available: str) -> str:
    prior_paid = "+".join(
        at(f"{prior} Principal Paid") for prior in TRANCHES[:TRANCHES.index(tranche)]
    ) or "0"
    debt_denominator = "+".join(
        f"MAX({at(f'{debt_tranche} Beginning Balance')}-{at(f'{debt_tranche} Loss Allocated')},0)"
        for debt_tranche in TRANCHES
    )
    return (
        f'=IF({at("Payment Mode")}="Sequential",'
        f"MIN({post_loss},MAX({principal_available}-({prior_paid}),0)),"
        f"MIN({post_loss},IFERROR({principal_available}*({post_loss})/"
        f"({debt_denominator}),0)))"
    )


def previous_shortfall_ref(tranche: str, row_idx: int, data_start: int, cell) -> str:
    tranche_idx = TRANCHES.index(tranche)
    shortfall_col = len(TRANCHES) + 2 + tranche_idx
    helper_row = row_idx - data_start + 1
    return f"'Tranche Cashflows'!{cell(helper_row, shortfall_col)}"


def write_cashflow_helper(
    cashflow_ws,
    columns: list[str],
    col_map: dict[str, int],
    data_start: int,
    data_end: int,
    first_summary_row: int,
    cell,
    workbook,
    header_fmt,
    calc_fmt,
    input_refs: dict[str, str],
) -> None:
    cashflow_ws.write(0, 0, "Tranche Cashflows", header_fmt)
    shortfall_start = len(TRANCHES) + 2
    equity_helper_start = shortfall_start + len(TRANCHES)
    for tranche_idx, tranche in enumerate(TRANCHES):
        cashflow_ws.write(0, tranche_idx, f"{tranche} Cashflow", header_fmt)
        summary_initial = f"'RMBS Scenario'!{cell(first_summary_row + tranche_idx, 1)}"
        cashflow_ws.write_formula(1, tranche_idx, f"=-{summary_initial}", calc_fmt)
        cashflow_ws.write(0, shortfall_start + tranche_idx, f"{tranche} Interest Shortfall", header_fmt)
        cashflow_ws.write_formula(1, shortfall_start + tranche_idx, "=0", calc_fmt)
    cashflow_ws.write(0, equity_helper_start, "Scenario A Levered Equity Cashflow", header_fmt)
    cashflow_ws.write_formula(
        1,
        equity_helper_start,
        "=-('RMBS Scenario'!$B$3-'RMBS Scenario'!$W$7)",
        calc_fmt,
    )
    cashflow_ws.write(0, equity_helper_start + 1, "Scenario A Unlevered Equity Cashflow", header_fmt)
    cashflow_ws.write_formula(1, equity_helper_start + 1, "=-'RMBS Scenario'!$B$3", calc_fmt)

    helper_row = 2
    for visible_row in range(data_start, data_end + 1):
        for tranche_idx, tranche in enumerate(TRANCHES):
            interest = f"'RMBS Scenario'!{cell(visible_row, col_map[f'{tranche} Interest Paid'])}"
            principal = f"'RMBS Scenario'!{cell(visible_row, col_map[f'{tranche} Principal Paid'])}"
            cashflow_ws.write_formula(helper_row, tranche_idx, f"={interest}+{principal}", calc_fmt)

            beg = f"'RMBS Scenario'!{cell(visible_row, col_map[f'{tranche} Beginning Balance'])}"
            loss = f"'RMBS Scenario'!{cell(visible_row, col_map[f'{tranche} Loss Allocated'])}"
            paid = f"'RMBS Scenario'!{cell(visible_row, col_map[f'{tranche} Interest Paid'])}"
            coupon = input_refs[f"{tranche}_coupon"]
            prev_shortfall = cell(helper_row - 1, shortfall_start + tranche_idx)
            formula = f"=MAX(({beg}-{loss})*{coupon}/12+{prev_shortfall}-{paid},0)"
            cashflow_ws.write_formula(helper_row, shortfall_start + tranche_idx, formula, calc_fmt)
        cashflow_ws.write_formula(
            helper_row,
            equity_helper_start,
            f"='RMBS Scenario'!{cell(visible_row, col_map['Warehouse Equity Cashflow'])}",
            calc_fmt,
        )
        cashflow_ws.write_formula(
            helper_row,
            equity_helper_start + 1,
            f"='RMBS Scenario'!{cell(visible_row, col_map['Unlevered Equity Cashflow'])}",
            calc_fmt,
        )
        helper_row += 1

    for col_idx in range(equity_helper_start + 2):
        cashflow_ws.set_column(col_idx, col_idx, 18)

def format_bool_for_excel(value: object) -> str:
    return "Yes" if bool(value) and value != "-" else "-"


def excel_col_format(
    col: str,
    asset_fmt,
    debt_fmt,
    equity_fmt,
    pct_fmt,
    ideal_fmt=None,
    spacer_fmt=None,
    asset_pct_fmt=None,
    debt_pct_fmt=None,
    equity_pct_fmt=None,
    ideal_pct_fmt=None,
):
    if col in SPACER_COLUMNS and spacer_fmt is not None:
        return spacer_fmt
    section = rmbs_section(col)
    if "%" in col:
        return {
            "rmbs-xl-ideal": ideal_pct_fmt,
            "rmbs-xl-asset": asset_pct_fmt,
            "rmbs-xl-warehouse": debt_pct_fmt,
            "rmbs-xl-tranche": debt_pct_fmt,
            "rmbs-xl-equity": equity_pct_fmt,
        }.get(section) or pct_fmt
    if section == "rmbs-xl-ideal" and ideal_fmt is not None:
        return ideal_fmt
    if section == "rmbs-xl-asset":
        return asset_fmt
    if section in {"rmbs-xl-warehouse", "rmbs-xl-tranche"}:
        return debt_fmt
    return equity_fmt


def scenario_range(center: float, *, lower: float, upper: float, step: float) -> list[float]:
    values = []
    current = lower
    while current <= upper + 1e-9:
        values.append(round(current, 4))
        current += step
    if not any(abs(value - center) < 1e-9 for value in values):
        values.append(round(center, 4))
    return sorted(values)


def calc_row(label: str, value: str) -> None:
    left, right = st.columns([1.35, 1.0], gap="small")
    left.markdown(f"<div class='mort-label-cell'>{label}</div>", unsafe_allow_html=True)
    right.markdown(f"<div class='mort-calc-cell'>{value}</div>", unsafe_allow_html=True)


def number_text(value: float, decimals: int = 0) -> str:
    formatted = f"{abs(value):,.{decimals}f}"
    if value < 0:
        return f"({formatted})"
    return formatted


def pct_text(value: float) -> str:
    return f"{value:.2%}"


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def inject_rmbs_css() -> None:
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
        .rmbs-gap {
            height: 0.65rem;
        }
        .rmbs-kpi-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.65rem;
            margin: 0.45rem 0 0.8rem;
        }
        .rmbs-mini-kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 0.55rem;
            margin: 0.35rem 0 0.65rem;
        }
        .rmbs-kpi-card {
            border: 1px solid rgba(17, 24, 39, 0.16);
            background: #ffffff;
            padding: 0.62rem 0.72rem;
            min-height: 82px;
            box-shadow: 0 1px 2px rgba(17, 24, 39, 0.05);
        }
        .rmbs-kpi-label {
            color: #4b5563;
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0;
            line-height: 1.1;
        }
        .rmbs-kpi-value {
            color: #111827;
            font-size: 1.34rem;
            font-weight: 760;
            line-height: 1.15;
            margin-top: 0.18rem;
        }
        .rmbs-kpi-detail {
            color: #6b7280;
            font-size: 0.74rem;
            line-height: 1.25;
            margin-top: 0.16rem;
        }
        @media (max-width: 900px) {
            .rmbs-kpi-grid,
            .rmbs-mini-kpi-grid {
                grid-template-columns: 1fr;
            }
        }
        .rmbs-excel-wrap {
            overflow: auto;
            max-height: 760px;
            border: 2px solid #222;
            background: white;
        }
        .rmbs-excel-table {
            border-collapse: collapse;
            table-layout: fixed;
            min-width: 4600px;
            width: max-content;
            font-size: 10px;
            line-height: 1.12;
        }
        .rmbs-excel-table th,
        .rmbs-excel-table td {
            border: 1px solid rgba(31, 41, 55, 0.18);
            padding: 2px 4px;
            text-align: right;
            white-space: nowrap;
            min-width: 92px;
        }
        .rmbs-excel-table thead th {
            font-weight: 700;
            vertical-align: bottom;
            color: #111827;
            border-bottom: 2px solid #222;
            height: 48px;
        }
        .rmbs-excel-table .rmbs-xl-section-start {
            border-left: 2px solid #222;
        }
        .rmbs-excel-table .rmbs-xl-section-end {
            border-right: 2px solid #222;
        }
        .rmbs-excel-table tbody tr:last-child td {
            border-bottom: 2px solid #222;
        }
        .rmbs-xl-asset {
            background: #e9f7fb;
        }
        .rmbs-xl-ideal {
            background: #ffffff;
        }
        .rmbs-xl-debt {
            background: #e6f7e6;
        }
        .rmbs-xl-warehouse {
            background: #e6f7e6;
        }
        .rmbs-xl-tranche {
            background: #e6f7e6;
        }
        .rmbs-xl-equity {
            background: #fce4dc;
        }
        .rmbs-xl-spacer {
            background: #ffffff;
            border-left: 0 !important;
            border-right: 0 !important;
            min-width: 44px !important;
            width: 44px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
