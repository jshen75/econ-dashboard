"""Mortgage asset, facility, and equity waterfall calculations."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MortgageInputs:
    collateral_notional: float = 100_000_000.0
    coupon_pct: float = 15.0
    term_months: int = 36
    cpr_pct: float = 20.0
    cdr_pct: float = 5.0
    severity_pct: float = 90.0
    yield_target_pct: float = 8.0
    sofr_pct: float = 5.0
    spread_pct: float = 2.75
    advance_rate_pct: float = 80.0


def pct(value: float) -> float:
    return value / 100


def pmt(monthly_rate: float, nper: int, present_value: float) -> float:
    if nper <= 0:
        return 0.0
    if monthly_rate == 0:
        return -present_value / nper
    return -(present_value * monthly_rate) / (1 - (1 + monthly_rate) ** -nper)


def smm(cpr_pct: float) -> float:
    return 1 - (1 - pct(max(cpr_pct, 0))) ** (1 / 12)


def mdr(cdr_pct: float) -> float:
    return 1 - (1 - pct(max(cdr_pct, 0))) ** (1 / 12)


def recoveries(severity_pct: float) -> float:
    return 1 - pct(max(severity_pct, 0))


def facility_rate(inputs: MortgageInputs) -> float:
    return pct(inputs.sofr_pct + inputs.spread_pct)


def initial_facility_notional(inputs: MortgageInputs) -> float:
    return inputs.collateral_notional * pct(inputs.advance_rate_pct)


def project_waterfall(inputs: MortgageInputs) -> tuple[pd.DataFrame, dict[str, float]]:
    coupon = pct(inputs.coupon_pct)
    target_yield = pct(inputs.yield_target_pct)
    period_smm = smm(inputs.cpr_pct)
    period_mdr = mdr(inputs.cdr_pct)
    recovery_rate = recoveries(inputs.severity_pct)
    monthly_payment = pmt(coupon / 12, inputs.term_months, -inputs.collateral_notional)
    init_facility = initial_facility_notional(inputs)
    debt_rate = facility_rate(inputs)

    ideal_ending = inputs.collateral_notional
    asset_ending = inputs.collateral_notional
    facility_ending = init_facility
    rows: list[dict[str, float]] = []

    rows.append(
        {
            "Period": 0,
            "Years": 0.0,
            "Ideal Collateral Beginning Balance": 0.0,
            "Scheduled Payment": 0.0,
            "Scheduled Interest": 0.0,
            "Scheduled Principal": 0.0,
            "Ideal Collateral Ending Balance": ideal_ending,
            "Asset Collateral Beginning Balance": 0.0,
            "Survival Factor": 0.0,
            "Surviving Scheduled Payment": 0.0,
            "Surviving Scheduled Principal": 0.0,
            "Defaults": 0.0,
            "Recovery": 0.0,
            "Net Loss": 0.0,
            "Remaining Performing Balance": 0.0,
            "Scheduled Payment of Performing Collateral": 0.0,
            "Asset Scheduled Interest": 0.0,
            "Asset Scheduled Principal": 0.0,
            "Prepayments": 0.0,
            "Asset Total Principal": 0.0,
            "Asset Total Cashflow": 0.0,
            "Cashflow Present Value": 0.0,
            "Asset Collateral Ending Balance": asset_ending,
            "Balance Decline %": 0.0,
            "Facility Beginning Balance": 0.0,
            "Interest Owed": 0.0,
            "Interest Paid": 0.0,
            "Interest Shortfall": 0.0,
            "Facility Total Cashflow": 0.0,
            "Principal Paid": 0.0,
            "Facility Ending Balance": facility_ending,
            "Facility Balance Decline %": 0.0,
            "Advance Rate to Par": safe_div(facility_ending, asset_ending),
            "Advance Rate to Purchase Price": 0.0,
            "Levered Equity Cashflow": 0.0,
            "Unlevered Equity Cashflow": 0.0,
        }
    )

    for period in range(1, inputs.term_months + 1):
        years = period / 12

        ideal_beginning = ideal_ending
        scheduled_interest = ideal_beginning * coupon / 12
        scheduled_principal = monthly_payment - scheduled_interest
        ideal_ending = max(ideal_beginning - scheduled_principal, 0)

        asset_beginning = asset_ending
        survival_factor = safe_div(asset_beginning, ideal_beginning)
        surviving_payment = monthly_payment * survival_factor
        surviving_principal = scheduled_principal * survival_factor
        defaults = asset_beginning * period_mdr
        recovery = defaults * recovery_rate
        net_loss = defaults - recovery
        remaining_performing = asset_beginning - defaults
        performing_payment = surviving_payment * safe_div(remaining_performing, asset_beginning)
        asset_interest = remaining_performing * coupon / 12
        asset_principal = performing_payment - asset_interest
        prepayments = (asset_beginning - surviving_principal) * period_smm
        total_principal = prepayments + asset_principal + recovery
        asset_cashflow = total_principal + asset_interest
        pv_cashflow = asset_cashflow / ((1 + target_yield / 12) ** period)
        asset_ending = max(asset_beginning - defaults - asset_principal - prepayments, 0)
        balance_decline_pct = safe_div(asset_beginning - asset_ending, inputs.collateral_notional)

        facility_beginning = facility_ending
        interest_owed = facility_beginning * debt_rate / 12
        interest_paid = min(interest_owed, asset_cashflow)
        interest_shortfall = interest_owed - interest_paid
        facility_cashflow = min(asset_cashflow, interest_owed + facility_beginning)
        principal_paid = facility_cashflow - interest_paid
        facility_ending = max(facility_beginning - principal_paid, 0)
        facility_decline_pct = safe_div(facility_beginning - facility_ending, init_facility)
        advance_to_par = safe_div(facility_ending, asset_ending)

        rows.append(
            {
                "Period": period,
                "Years": years,
                "Ideal Collateral Beginning Balance": ideal_beginning,
                "Scheduled Payment": monthly_payment,
                "Scheduled Interest": scheduled_interest,
                "Scheduled Principal": scheduled_principal,
                "Ideal Collateral Ending Balance": ideal_ending,
                "Asset Collateral Beginning Balance": asset_beginning,
                "Survival Factor": survival_factor,
                "Surviving Scheduled Payment": surviving_payment,
                "Surviving Scheduled Principal": surviving_principal,
                "Defaults": defaults,
                "Recovery": recovery,
                "Net Loss": net_loss,
                "Remaining Performing Balance": remaining_performing,
                "Scheduled Payment of Performing Collateral": performing_payment,
                "Asset Scheduled Interest": asset_interest,
                "Asset Scheduled Principal": asset_principal,
                "Prepayments": prepayments,
                "Asset Total Principal": total_principal,
                "Asset Total Cashflow": asset_cashflow,
                "Cashflow Present Value": pv_cashflow,
                "Asset Collateral Ending Balance": asset_ending,
                "Balance Decline %": balance_decline_pct,
                "Facility Beginning Balance": facility_beginning,
                "Interest Owed": interest_owed,
                "Interest Paid": interest_paid,
                "Interest Shortfall": interest_shortfall,
                "Facility Total Cashflow": facility_cashflow,
                "Principal Paid": principal_paid,
                "Facility Ending Balance": facility_ending,
                "Facility Balance Decline %": facility_decline_pct,
                "Advance Rate to Par": advance_to_par,
                "Advance Rate to Purchase Price": 0.0,
                "Levered Equity Cashflow": asset_cashflow - facility_cashflow,
                "Unlevered Equity Cashflow": asset_cashflow,
            }
        )

    schedule = pd.DataFrame(rows)
    purchase_price = schedule["Cashflow Present Value"].sum()
    purchase_price_pct = safe_div(purchase_price, inputs.collateral_notional)
    schedule["Advance Rate to Purchase Price"] = (
        schedule["Advance Rate to Par"] * safe_div(inputs.collateral_notional, purchase_price)
    )
    schedule.loc[schedule["Period"] == 0, "Levered Equity Cashflow"] = init_facility - purchase_price
    schedule.loc[schedule["Period"] == 0, "Unlevered Equity Cashflow"] = -purchase_price

    metrics = {
        "SMM": period_smm,
        "MDR": period_mdr,
        "Recoveries": recovery_rate,
        "Purchase Price ($)": purchase_price,
        "Purchase Price (%)": purchase_price_pct,
        "WAL": weighted_average(schedule["Years"], schedule["Balance Decline %"]),
        "Macaulay Duration": weighted_average(schedule["Years"], schedule["Cashflow Present Value"]),
        "Modified Duration": weighted_average(schedule["Years"], schedule["Cashflow Present Value"])
        / (1 + target_yield / 2),
        "Cumulative Defaults (%)": safe_div(schedule["Defaults"].sum(), inputs.collateral_notional),
        "Cumulative Net Loss (%)": safe_div(schedule["Net Loss"].sum(), inputs.collateral_notional),
        "Facility Rate": debt_rate,
        "Initial Notional": init_facility,
        "Facility WAL": weighted_average(schedule["Years"], schedule["Facility Balance Decline %"]),
        "Facility / Lender Loss (%)": safe_div(schedule["Interest Shortfall"].sum(), init_facility),
        "Facility / Lender Loss ($)": schedule["Interest Shortfall"].sum(),
        "Levered Initial Equity Check": init_facility - purchase_price,
        "Levered Equity IRR / Annual Yield": monthly_irr(
            schedule["Levered Equity Cashflow"].tolist()
        )
        * 12,
        "Unlevered Initial Equity Check": -purchase_price,
        "Unlevered Equity IRR / Annual Yield": monthly_irr(
            schedule["Unlevered Equity Cashflow"].tolist()
        )
        * 12,
    }
    return schedule, metrics


def safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def weighted_average(values: pd.Series, weights: pd.Series) -> float:
    total_weight = weights.sum()
    if total_weight == 0:
        return 0.0
    return float((values * weights).sum() / total_weight)


def monthly_irr(cashflows: list[float]) -> float:
    if not cashflows or not any(cf < 0 for cf in cashflows) or not any(cf > 0 for cf in cashflows):
        return 0.0

    def npv(rate: float) -> float:
        return sum(cf / ((1 + rate) ** idx) for idx, cf in enumerate(cashflows))

    low = -0.9999
    high = 1.0
    low_npv = npv(low)
    high_npv = npv(high)
    while low_npv * high_npv > 0 and high < 100:
        high *= 2
        high_npv = npv(high)
    if low_npv * high_npv > 0:
        return 0.0

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


TABLE_SECTIONS: dict[str, list[str]] = {
    "Assets": [
        "Period",
        "Years",
        "Ideal Collateral Beginning Balance",
        "Scheduled Payment",
        "Scheduled Interest",
        "Scheduled Principal",
        "Ideal Collateral Ending Balance",
    ],
    "Realistic Asset Case": [
        "Asset Collateral Beginning Balance",
        "Survival Factor",
        "Surviving Scheduled Payment",
        "Surviving Scheduled Principal",
        "Defaults",
        "Recovery",
        "Net Loss",
        "Remaining Performing Balance",
        "Scheduled Payment of Performing Collateral",
        "Asset Scheduled Interest",
        "Asset Scheduled Principal",
        "Prepayments",
        "Asset Total Principal",
        "Asset Total Cashflow",
        "Cashflow Present Value",
        "Asset Collateral Ending Balance",
        "Balance Decline %",
    ],
    "Debt / Liabilities": [
        "Facility Beginning Balance",
        "Interest Owed",
        "Interest Paid",
        "Interest Shortfall",
        "Principal Paid",
        "Facility Total Cashflow",
        "Facility Ending Balance",
        "Facility Balance Decline %",
        "Advance Rate to Purchase Price",
        "Advance Rate to Par",
    ],
    "Equity": ["Levered Equity Cashflow", "Unlevered Equity Cashflow"],
}


CHART_GROUPS: dict[str, list[str]] = {
    "Assets": TABLE_SECTIONS["Assets"] + TABLE_SECTIONS["Realistic Asset Case"],
    "Debt / Liabilities": TABLE_SECTIONS["Debt / Liabilities"],
    "Equity": TABLE_SECTIONS["Equity"],
}
