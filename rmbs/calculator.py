"""RMBS collateral and tranche waterfall calculations."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import pandas as pd

from mortgage.calculator import pmt, weighted_average


TRANCHES = ["A1", "A1F", "A2", "A3", "M1", "B1A", "B1B", "B2", "B3"]
B_NOTE_TRANCHES = ["B1A", "B1B", "B2", "B3"]
EXCHANGEABLE_CLASSES = ["A1A", "A1B", "A1FCF", "A1LCF"]
TRANCHE_LABELS = {
    "A1": "Class A-1",
    "A1F": "Class A-1F",
    "A2": "Class A-2",
    "A3": "Class A-3",
    "M1": "Class M-1",
    "B1A": "Class B-1A",
    "B1B": "Class B-1B",
    "B2": "Class B-2",
    "B3": "Class B-3",
    "XSR": "XS + R Strict Equity",
    "RETAINED": "Sponsor Retained Position",
}
EXCHANGEABLE_LABELS = {
    "A1A": "Class A-1A",
    "A1B": "Class A-1B",
    "A1FCF": "Class A-1FCF",
    "A1LCF": "Class A-1LCF",
}


@dataclass(frozen=True)
class RmbsInputs:
    # Defaults sourced from the OBX 2026-NQM8 presale. Values come from the
    # subject-deal column only; exchangeable senior classes are not additive.
    deal_balance: float = 1_022_400_000.0
    gross_coupon_pct: float = 6.80
    term_months: int = 358
    seasoning_months: int = 3
    cpr_pct: float = 8.0
    cdr_pct: float = 1.0
    severity_pct: float = 35.0
    yield_target_pct: float = 8.0
    servicing_fee_pct: float = 0.25
    admin_fee_pct: float = 0.05
    aaa_attachment_pct: float = 20.0
    wa_fico: int = 757
    wa_cltv_pct: float = 68.9
    wa_dscr: float = 1.11
    arm_pct: float = 8.0
    io_pct: float = 5.0
    aaa_loss_severity_pct: float = 49.88
    b_loss_severity_pct: float = 20.14
    aaa_foreclosure_frequency_pct: float = 28.67
    b_foreclosure_frequency_pct: float = 4.22
    number_of_loans: int = 0
    average_loan_size: float = 0.0
    lockout_months: int = 36
    stepdown_cum_loss_trigger_pct: float = 2.0
    stepdown_dq_trigger_pct: float = 4.0
    cleanup_call_factor_pct: float = 10.0
    sofr_pct: float = 3.61
    spread_pct: float = 2.0
    advance_rate_pct: float = 80.0
    a1_pct: float = 80.0
    a1f_pct: float = 0.0
    a2_pct: float = 4.10
    a3_pct: float = 7.85
    m1_pct: float = 3.50
    b1a_pct: float = 1.45
    b1b_pct: float = 1.60
    b2_pct: float = 0.70
    b3_pct: float = 0.80
    a1_coupon_pct: float = 5.50
    a1f_coupon_pct: float = 5.65
    a2_coupon_pct: float = 6.25
    a3_coupon_pct: float = 6.75
    m1_coupon_pct: float = 7.25
    b1a_coupon_pct: float = 8.25
    b1b_coupon_pct: float = 8.75
    b2_coupon_pct: float = 9.50
    b3_coupon_pct: float = 10.50


def project_rmbs_waterfall(inputs: RmbsInputs) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    tranche_sizes = tranche_initial_balances(inputs)
    tranche_coupons = tranche_coupon_rates(inputs)
    tranche_balances = tranche_sizes.copy()
    interest_shortfalls = {tranche: 0.0 for tranche in TRANCHES}
    tranche_cashflows = {tranche: [-tranche_sizes[tranche]] for tranche in TRANCHES}
    ideal_collateral_balance = inputs.deal_balance
    collateral_balance = inputs.deal_balance
    facility_balance = inputs.deal_balance * rate(inputs.advance_rate_pct)
    rows: list[dict[str, float | str | bool]] = []
    tranche_rows: list[dict[str, float | str]] = []
    scheduled_payment = pmt(rate(inputs.gross_coupon_pct) / 12, inputs.term_months, -inputs.deal_balance)
    monthly_smm = smm(inputs.cpr_pct)
    monthly_mdr = mdr(inputs.cdr_pct)
    recovery_rate = 1 - rate(inputs.severity_pct)
    target_yield = rate(inputs.yield_target_pct)
    facility_note_rate = rate(inputs.sofr_pct + inputs.spread_pct)
    cumulative_loss = 0.0
    cumulative_defaults = 0.0

    rows.append(base_row(0, ideal_collateral_balance, collateral_balance, tranche_balances,
                         facility_balance, "Closing", False))
    for tranche in TRANCHES:
        tranche_cashflows[tranche][0] = -tranche_sizes[tranche]

    for period in range(1, inputs.term_months + 1):
        if collateral_balance <= 1e-6 and sum(tranche_balances.values()) <= 1e-6:
            break
        scheduled_beginning = ideal_collateral_balance
        scheduled_interest = scheduled_beginning * rate(inputs.gross_coupon_pct) / 12
        scheduled_principal = min(max(scheduled_payment - scheduled_interest, 0), scheduled_beginning)
        ideal_collateral_balance = max(scheduled_beginning - scheduled_principal, 0)

        beginning_collateral = collateral_balance
        survival_factor = safe_div(beginning_collateral, scheduled_beginning)
        surviving_scheduled_payment = scheduled_payment * survival_factor
        surviving_scheduled_principal = scheduled_principal * survival_factor
        defaults = beginning_collateral * monthly_mdr
        cumulative_defaults += defaults
        recoveries = defaults * recovery_rate
        net_loss = defaults - recoveries
        cumulative_loss += net_loss
        remaining_performing = max(beginning_collateral - defaults, 0)
        servicing_fee = remaining_performing * rate(inputs.servicing_fee_pct) / 12
        admin_fee = remaining_performing * rate(inputs.admin_fee_pct) / 12
        scheduled_payment_performing = (
            surviving_scheduled_payment * safe_div(remaining_performing, beginning_collateral)
        )
        collateral_interest = remaining_performing * rate(inputs.gross_coupon_pct) / 12
        scheduled_principal_performing = scheduled_payment_performing - collateral_interest
        prepayments = max(beginning_collateral - surviving_scheduled_principal, 0) * monthly_smm
        principal_collections = min(
            scheduled_principal_performing + prepayments + recoveries,
            beginning_collateral,
        )
        asset_total_cashflow = principal_collections + collateral_interest
        cashflow_present_value = asset_total_cashflow / ((1 + target_yield / 12) ** period)
        collateral_balance = max(
            beginning_collateral - defaults - scheduled_principal_performing - prepayments,
            0,
        )
        balance_decline_pct = safe_div(beginning_collateral - collateral_balance, inputs.deal_balance)

        facility_beginning = facility_balance
        facility_interest_owed = facility_beginning * facility_note_rate / 12
        facility_total_cashflow = min(asset_total_cashflow, facility_interest_owed + facility_beginning)
        facility_interest_paid = min(facility_interest_owed, facility_total_cashflow)
        facility_interest_shortfall = facility_interest_owed - facility_interest_paid
        facility_principal_paid = facility_total_cashflow - facility_interest_paid
        facility_balance = max(facility_beginning - facility_principal_paid, 0)
        facility_decline_pct = safe_div(
            facility_beginning - facility_balance,
            inputs.deal_balance * rate(inputs.advance_rate_pct),
        )
        advance_rate_to_par = safe_div(facility_balance, collateral_balance)

        loss_allocations = allocate_losses(tranche_balances, net_loss)
        cumulative_loss_pct = cumulative_loss / inputs.deal_balance
        cumulative_defaults_pct = cumulative_defaults / inputs.deal_balance
        dq_proxy = monthly_mdr * 12
        stepdown_allowed = period > inputs.lockout_months
        trigger_breached = (
            cumulative_loss_pct > rate(inputs.stepdown_cum_loss_trigger_pct)
            or dq_proxy > rate(inputs.stepdown_dq_trigger_pct)
        )
        payment_mode = "Sequential" if trigger_breached or not stepdown_allowed else "Modified pro-rata"

        interest_available = max(collateral_interest - servicing_fee - admin_fee, 0)
        interest_paid, interest_available = pay_interest(
            tranche_balances, tranche_coupons, interest_shortfalls, interest_available
        )
        excess_spread = interest_available
        principal_available = principal_collections
        residual_excess = excess_spread
        if payment_mode == "Sequential":
            principal_available += excess_spread
            residual_excess = 0.0

        principal_paid = allocate_principal(tranche_balances, principal_available, payment_mode)
        ending_collateral = collateral_balance
        ending_bond_balance = sum(tranche_balances.values())
        credit_enhancement = safe_div(ending_collateral - tranche_balances["A1"], ending_collateral)
        cleanup_call_eligible = ending_collateral <= inputs.deal_balance * rate(inputs.cleanup_call_factor_pct)
        warehouse_equity_beginning = max(beginning_collateral - facility_beginning, 0)
        warehouse_equity_cashflow = asset_total_cashflow - facility_total_cashflow
        warehouse_equity_ending = max(ending_collateral - facility_balance, 0)
        warehouse_equity_roe = safe_div(warehouse_equity_cashflow * 12, warehouse_equity_beginning)
        unlevered_equity_beginning = beginning_collateral
        unlevered_equity_cashflow = asset_total_cashflow - servicing_fee - admin_fee
        unlevered_equity_ending = ending_collateral
        unlevered_equity_roe = safe_div(unlevered_equity_cashflow * 12, unlevered_equity_beginning)
        xsr_equity_cashflow = residual_excess
        xsr_equity_pv = xsr_equity_cashflow / ((1 + target_yield / 12) ** period)

        row = {
            "Period": period,
            "Years": period / 12,
            "Scheduled Collateral Beginning Balance": scheduled_beginning,
            "Scheduled Payment": scheduled_payment,
            "Scheduled Interest": scheduled_interest,
            "Scheduled Principal": scheduled_principal,
            "Scheduled Collateral Ending Balance": ideal_collateral_balance,
            "Payment Mode": payment_mode,
            "Trigger Breached": trigger_breached,
            "Collateral Beginning Balance": beginning_collateral,
            "Survival Factor": survival_factor,
            "Surviving Scheduled Payment": surviving_scheduled_payment,
            "Surviving Scheduled Principal": surviving_scheduled_principal,
            "Collateral Interest": collateral_interest,
            "Servicing Fee": servicing_fee,
            "Admin Fee": admin_fee,
            "Prepayments": prepayments,
            "Defaults": defaults,
            "Recoveries": recoveries,
            "Net Loss": net_loss,
            "Cumulative Defaults %": cumulative_defaults_pct,
            "Cumulative Net Loss %": cumulative_loss_pct,
            "Remaining Performing Balance": remaining_performing,
            "Scheduled Payment of Performing Collateral": scheduled_payment_performing,
            "Scheduled Principal of Performing Collateral": scheduled_principal_performing,
            "Principal Collections": principal_collections,
            "Asset Total Cashflow": asset_total_cashflow,
            "Cashflow Present Value": cashflow_present_value,
            "Interest Available": collateral_interest - servicing_fee - admin_fee,
            "Excess Spread": excess_spread,
            "Residual Excess Spread": residual_excess,
            "Collateral Ending Balance": ending_collateral,
            "Balance Decline %": balance_decline_pct,
            "Facility Beginning Balance": facility_beginning,
            "Facility Interest Owed": facility_interest_owed,
            "Facility Interest Paid": facility_interest_paid,
            "Facility Interest Shortfall": facility_interest_shortfall,
            "Facility Principal Paid": facility_principal_paid,
            "Facility Total Cashflow": facility_total_cashflow,
            "Facility Ending Balance": facility_balance,
            "Facility Balance Decline %": facility_decline_pct,
            "Advance Rate to Par": advance_rate_to_par,
            "Advance Rate to Purchase Price": 0.0,
            "Warehouse Equity Beginning Balance": warehouse_equity_beginning,
            "Warehouse Equity Cashflow": warehouse_equity_cashflow,
            "Warehouse Equity Ending Balance": warehouse_equity_ending,
            "Warehouse Equity ROE": warehouse_equity_roe,
            "Unlevered Equity Beginning Balance": unlevered_equity_beginning,
            "Unlevered Equity Cashflow": unlevered_equity_cashflow,
            "Unlevered Equity Ending Balance": unlevered_equity_ending,
            "Unlevered Equity ROE": unlevered_equity_roe,
            "Scenario B Debt Proceeds": 0.0,
            "Warehouse Takeout Surplus / (Shortfall)": 0.0,
            "Bond Ending Balance": ending_bond_balance,
            "Credit Enhancement %": credit_enhancement,
            "Cleanup Call Eligible": cleanup_call_eligible,
            "XS/R Equity Cashflow": xsr_equity_cashflow,
            "XS/R Equity PV": xsr_equity_pv,
        }
        for tranche in TRANCHES:
            row[f"{tranche} Beginning Balance"] = tranche_balances[tranche] + principal_paid[tranche] + loss_allocations[tranche]
            row[f"{tranche} Interest Paid"] = interest_paid[tranche]
            row[f"{tranche} Principal Paid"] = principal_paid[tranche]
            row[f"{tranche} Loss Allocated"] = loss_allocations[tranche]
            row[f"{tranche} Ending Balance"] = tranche_balances[tranche]
            cashflow = interest_paid[tranche] + principal_paid[tranche]
            tranche_cashflows[tranche].append(cashflow)
        rows.append(row)

    schedule = pd.DataFrame(rows)
    purchase_price = float(schedule["Cashflow Present Value"].sum())
    debt_proceeds = sum(tranche_sizes.values())
    initial_facility = inputs.deal_balance * rate(inputs.advance_rate_pct)
    strict_equity_value = float(schedule["XS/R Equity PV"].sum())
    b_note_balance = sum(tranche_sizes[tranche] for tranche in B_NOTE_TRANCHES)
    sponsor_retained_position = b_note_balance + strict_equity_value
    takeout_surplus = debt_proceeds - initial_facility
    schedule["Advance Rate to Purchase Price"] = (
        schedule["Advance Rate to Par"] * safe_div(inputs.deal_balance, purchase_price)
    )
    schedule["Scenario B Debt Proceeds"] = debt_proceeds
    schedule["Warehouse Takeout Surplus / (Shortfall)"] = takeout_surplus
    for tranche in TRANCHES:
        tranche_rows.append({
            "Class": TRANCHE_LABELS[tranche],
            "Initial Balance": tranche_sizes[tranche],
            "Coupon": tranche_coupons[tranche],
            "Principal Paid": schedule.get(f"{tranche} Principal Paid", pd.Series(dtype=float)).sum(),
            "Interest Paid": schedule.get(f"{tranche} Interest Paid", pd.Series(dtype=float)).sum(),
            "Loss Allocated": schedule.get(f"{tranche} Loss Allocated", pd.Series(dtype=float)).sum(),
            "Ending Balance": schedule.iloc[-1].get(f"{tranche} Ending Balance", 0.0),
            "WAL": tranche_wal(schedule, tranche, tranche_sizes[tranche]),
            "IRR": stable_monthly_irr(tranche_cashflows[tranche]) * 12,
        })
    tranche_summary = pd.DataFrame(tranche_rows)
    tranche_summary = pd.concat([
        tranche_summary,
        pd.DataFrame([
            {
                "Class": TRANCHE_LABELS["XSR"],
                "Initial Balance": 0.0,
                "Coupon": 0.0,
                "Principal Paid": 0.0,
                "Interest Paid": float(schedule["XS/R Equity Cashflow"].sum()),
                "Loss Allocated": 0.0,
                "Ending Balance": 0.0,
                "WAL": weighted_average(schedule["Years"], schedule["XS/R Equity Cashflow"]),
                "IRR": 0.0,
            },
            {
                "Class": TRANCHE_LABELS["RETAINED"],
                "Initial Balance": sponsor_retained_position,
                "Coupon": 0.0,
                "Principal Paid": 0.0,
                "Interest Paid": float(schedule["XS/R Equity Cashflow"].sum()),
                "Loss Allocated": sum(
                    schedule.get(f"{tranche} Loss Allocated", pd.Series(dtype=float)).sum()
                    for tranche in B_NOTE_TRANCHES
                ),
                "Ending Balance": sponsor_retained_position,
                "WAL": 0.0,
                "IRR": 0.0,
            },
        ]),
    ], ignore_index=True)
    warehouse_equity = inputs.deal_balance - initial_facility
    warehouse_asset_income = inputs.deal_balance * rate(inputs.gross_coupon_pct)
    warehouse_funding_cost = initial_facility * facility_note_rate
    warehouse_net_margin = warehouse_asset_income - warehouse_funding_cost
    levered_equity_irr = stable_monthly_irr(
        [-warehouse_equity] + schedule.loc[schedule["Period"] > 0, "Warehouse Equity Cashflow"].tolist()
    ) * 12
    unlevered_equity_irr = stable_monthly_irr(
        [-inputs.deal_balance] + schedule.loc[schedule["Period"] > 0, "Unlevered Equity Cashflow"].tolist()
    ) * 12
    metrics = {
        "SMM": monthly_smm,
        "MDR": monthly_mdr,
        "Recoveries": recovery_rate,
        "Purchase Price ($)": purchase_price,
        "Purchase Price (%)": safe_div(purchase_price, inputs.deal_balance),
        "Collateral WAL": weighted_average(schedule["Years"], schedule["Balance Decline %"]),
        "Macaulay Duration": weighted_average(schedule["Years"], schedule["Cashflow Present Value"]),
        "Modified Duration": weighted_average(schedule["Years"], schedule["Cashflow Present Value"])
        / (1 + target_yield / 2),
        "Cumulative Defaults %": safe_div(schedule["Defaults"].sum(), inputs.deal_balance),
        "Initial Senior Credit Enhancement": safe_div(inputs.deal_balance - tranche_sizes["A1"], inputs.deal_balance),
        "Final Senior Credit Enhancement": schedule.iloc[-1]["Credit Enhancement %"],
        "Cumulative Net Loss %": safe_div(schedule["Net Loss"].sum(), inputs.deal_balance),
        "Facility Rate": facility_note_rate,
        "Initial Facility Notional": initial_facility,
        "Warehouse Equity / Haircut": warehouse_equity,
        "Warehouse Asset Income": warehouse_asset_income,
        "Warehouse Funding Cost": warehouse_funding_cost,
        "Warehouse Net Margin": warehouse_net_margin,
        "Warehouse Levered ROE": safe_div(warehouse_net_margin, warehouse_equity),
        "Scenario A Equity IRR - Levered": levered_equity_irr,
        "Scenario A Equity IRR - Unlevered": unlevered_equity_irr,
        "Scenario A Leverage Premium": levered_equity_irr - unlevered_equity_irr,
        "Facility WAL": weighted_average(schedule["Years"], schedule["Facility Balance Decline %"]),
        "Facility / Lender Loss %": safe_div(schedule["Facility Interest Shortfall"].sum(), initial_facility),
        "Facility / Lender Loss $": float(schedule["Facility Interest Shortfall"].sum()),
        "Total Excess Spread": schedule["Excess Spread"].sum(),
        "Residual Excess Spread": schedule["Residual Excess Spread"].sum(),
        "Scenario B Debt Proceeds": debt_proceeds,
        "Warehouse Takeout Surplus / (Shortfall)": takeout_surplus,
        "XS/R Strict Equity Value": strict_equity_value,
        "Sponsor Retained Position": sponsor_retained_position,
        "B-Note Retained Debt Balance": b_note_balance,
        "Senior WAL": float(tranche_summary.loc[tranche_summary["Class"] == TRANCHE_LABELS["A1"], "WAL"].iloc[0]),
        "Senior IRR": float(tranche_summary.loc[tranche_summary["Class"] == TRANCHE_LABELS["A1"], "IRR"].iloc[0]),
        "First Trigger Period": first_trigger_period(schedule),
    }
    return schedule, tranche_summary, metrics


def base_row(period: int, ideal_collateral_balance: float, collateral_balance: float,
             tranche_balances: dict[str, float], facility_balance: float, mode: str,
             trigger: bool) -> dict[str, float | str | bool]:
    row: dict[str, float | str | bool] = {
        "Period": period,
        "Years": 0.0,
        "Scheduled Collateral Beginning Balance": 0.0,
        "Scheduled Payment": 0.0,
        "Scheduled Interest": 0.0,
        "Scheduled Principal": 0.0,
        "Scheduled Collateral Ending Balance": ideal_collateral_balance,
        "Payment Mode": mode,
        "Trigger Breached": trigger,
        "Collateral Beginning Balance": 0.0,
        "Survival Factor": 0.0,
        "Surviving Scheduled Payment": 0.0,
        "Surviving Scheduled Principal": 0.0,
        "Collateral Interest": 0.0,
        "Servicing Fee": 0.0,
        "Admin Fee": 0.0,
        "Prepayments": 0.0,
        "Defaults": 0.0,
        "Recoveries": 0.0,
        "Net Loss": 0.0,
        "Cumulative Defaults %": 0.0,
        "Cumulative Net Loss %": 0.0,
        "Remaining Performing Balance": 0.0,
        "Scheduled Payment of Performing Collateral": 0.0,
        "Scheduled Principal of Performing Collateral": 0.0,
        "Principal Collections": 0.0,
        "Asset Total Cashflow": 0.0,
        "Cashflow Present Value": 0.0,
        "Interest Available": 0.0,
        "Excess Spread": 0.0,
        "Residual Excess Spread": 0.0,
        "Collateral Ending Balance": collateral_balance,
        "Balance Decline %": 0.0,
        "Facility Beginning Balance": 0.0,
        "Facility Interest Owed": 0.0,
        "Facility Interest Paid": 0.0,
        "Facility Interest Shortfall": 0.0,
        "Facility Principal Paid": 0.0,
        "Facility Total Cashflow": 0.0,
        "Facility Ending Balance": facility_balance,
        "Facility Balance Decline %": 0.0,
        "Advance Rate to Par": safe_div(facility_balance, collateral_balance),
        "Advance Rate to Purchase Price": 0.0,
        "Warehouse Equity Beginning Balance": 0.0,
        "Warehouse Equity Cashflow": 0.0,
        "Warehouse Equity Ending Balance": max(collateral_balance - facility_balance, 0),
        "Warehouse Equity ROE": 0.0,
        "Unlevered Equity Beginning Balance": 0.0,
        "Unlevered Equity Cashflow": 0.0,
        "Unlevered Equity Ending Balance": collateral_balance,
        "Unlevered Equity ROE": 0.0,
        "Scenario B Debt Proceeds": sum(tranche_balances.values()),
        "Warehouse Takeout Surplus / (Shortfall)": sum(tranche_balances.values()) - facility_balance,
        "Bond Ending Balance": sum(tranche_balances.values()),
        "Credit Enhancement %": 1 - safe_div(tranche_balances["A1"], collateral_balance),
        "Cleanup Call Eligible": False,
        "XS/R Equity Cashflow": 0.0,
        "XS/R Equity PV": 0.0,
    }
    for tranche in TRANCHES:
        row[f"{tranche} Beginning Balance"] = 0.0
        row[f"{tranche} Interest Paid"] = 0.0
        row[f"{tranche} Principal Paid"] = 0.0
        row[f"{tranche} Loss Allocated"] = 0.0
        row[f"{tranche} Ending Balance"] = tranche_balances[tranche]
    return row


def tranche_initial_balances(inputs: RmbsInputs) -> dict[str, float]:
    pct_map = {
        "A1": inputs.a1_pct,
        "A1F": inputs.a1f_pct,
        "A2": inputs.a2_pct,
        "A3": inputs.a3_pct,
        "M1": inputs.m1_pct,
        "B1A": inputs.b1a_pct,
        "B1B": inputs.b1b_pct,
        "B2": inputs.b2_pct,
        "B3": inputs.b3_pct,
    }
    return {tranche: inputs.deal_balance * rate(pct_map[tranche]) for tranche in TRANCHES}


def tranche_coupon_rates(inputs: RmbsInputs) -> dict[str, float]:
    return {
        "A1": rate(inputs.a1_coupon_pct),
        "A1F": rate(inputs.a1f_coupon_pct),
        "A2": rate(inputs.a2_coupon_pct),
        "A3": rate(inputs.a3_coupon_pct),
        "M1": rate(inputs.m1_coupon_pct),
        "B1A": rate(inputs.b1a_coupon_pct),
        "B1B": rate(inputs.b1b_coupon_pct),
        "B2": rate(inputs.b2_coupon_pct),
        "B3": rate(inputs.b3_coupon_pct),
    }


def allocate_losses(tranche_balances: dict[str, float], loss_amount: float) -> dict[str, float]:
    allocations = {tranche: 0.0 for tranche in TRANCHES}
    remaining = loss_amount
    for tranche in reversed(TRANCHES):
        amount = min(tranche_balances[tranche], remaining)
        tranche_balances[tranche] -= amount
        allocations[tranche] = amount
        remaining -= amount
        if remaining <= 1e-9:
            break
    return allocations


def pay_interest(tranche_balances: dict[str, float], coupons: dict[str, float],
                 shortfalls: dict[str, float], available: float) -> tuple[dict[str, float], float]:
    paid = {tranche: 0.0 for tranche in TRANCHES}
    for tranche in TRANCHES:
        due = tranche_balances[tranche] * coupons[tranche] / 12 + shortfalls[tranche]
        amount = min(due, available)
        paid[tranche] = amount
        shortfalls[tranche] = due - amount
        available -= amount
    return paid, available


def allocate_principal(tranche_balances: dict[str, float], principal: float, mode: str) -> dict[str, float]:
    paid = {tranche: 0.0 for tranche in TRANCHES}
    remaining = principal
    if mode == "Sequential":
        for tranche in TRANCHES:
            amount = min(tranche_balances[tranche], remaining)
            tranche_balances[tranche] -= amount
            paid[tranche] = amount
            remaining -= amount
            if remaining <= 1e-9:
                break
        return paid

    pro_rata_classes = [tranche for tranche in TRANCHES if tranche_balances[tranche] > 1e-9]
    if not pro_rata_classes:
        pro_rata_classes = [tranche for tranche in TRANCHES if tranche_balances[tranche] > 1e-9]
    total = sum(tranche_balances[tranche] for tranche in pro_rata_classes)
    for tranche in pro_rata_classes:
        amount = min(tranche_balances[tranche], principal * safe_div(tranche_balances[tranche], total))
        tranche_balances[tranche] -= amount
        paid[tranche] = amount
    return paid


def tranche_wal(schedule: pd.DataFrame, tranche: str, initial_balance: float) -> float:
    if initial_balance == 0 or f"{tranche} Principal Paid" not in schedule:
        return 0.0
    principal = schedule[f"{tranche} Principal Paid"]
    return float((schedule["Years"] * principal).sum() / initial_balance)


def first_trigger_period(schedule: pd.DataFrame) -> float:
    breached = schedule[schedule["Trigger Breached"] == True]
    if breached.empty:
        return 0.0
    return float(breached.iloc[0]["Period"])


def rate(value: float) -> float:
    return value / 100


def smm(cpr_pct: float) -> float:
    return 1 - (1 - rate(max(cpr_pct, 0))) ** (1 / 12)


def mdr(cdr_pct: float) -> float:
    return 1 - (1 - rate(max(cdr_pct, 0))) ** (1 / 12)


def safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def stable_monthly_irr(cashflows: list[float]) -> float:
    if not cashflows or not any(cf < 0 for cf in cashflows):
        return 0.0
    if not any(cf > 0 for cf in cashflows):
        return -1.0 / 12

    def npv(discount_rate: float) -> float:
        base = 1 + discount_rate
        if base <= 0:
            return float("inf")
        total = 0.0
        for idx, cf in enumerate(cashflows):
            if cf == 0:
                continue
            try:
                total += cf / (base ** idx)
            except (OverflowError, ZeroDivisionError):
                continue
        return total

    roots: list[tuple[float, float]] = []
    search_points = [-0.999, -0.95, -0.90, -0.80, -0.70, -0.60, -0.50]
    search_points += [idx / 100 for idx in range(-40, 101)]
    search_points += [1.25, 1.50, 2.0, 3.0, 5.0, 10.0]
    previous_rate = search_points[0]
    previous_npv = npv(previous_rate)

    for current_rate in search_points[1:]:
        current_npv = npv(current_rate)
        if not all(math.isfinite(value) for value in (previous_npv, current_npv)):
            previous_rate = current_rate
            previous_npv = current_npv
            continue
        if previous_npv == 0:
            roots.append((previous_rate, previous_rate))
        elif previous_npv * current_npv <= 0:
            roots.append((previous_rate, current_rate))
        previous_rate = current_rate
        previous_npv = current_npv

    if not roots:
        return -1.0 / 12

    low, high = min(roots, key=lambda pair: abs((pair[0] + pair[1]) / 2 - 0.005))
    low_npv = npv(low)
    for _ in range(100):
        mid = (low + high) / 2
        mid_npv = npv(mid)
        if abs(mid_npv) < 1e-7:
            return mid
        if low_npv * mid_npv <= 0:
            high = mid
            high_npv = mid_npv
        else:
            low = mid
            low_npv = mid_npv
    return (low + high) / 2


def update_inputs(inputs: RmbsInputs, **changes: float | int) -> RmbsInputs:
    return replace(inputs, **changes)
