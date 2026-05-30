"""The indicator registry (brief §2/§3). Config, not code — add a row to add an
indicator. FRED series ids do the heavy lifting; FRED computes MoM (`pch`) and
YoY (`pc1`) for us, so we just declare which transform we want.

FRED `units` transforms used below:
    lin = level            pch = % change (MoM/QoQ)      pc1 = % change YoY
    chg = change           pca = compounded annual rate (for GDP)
"""

from __future__ import annotations

from .models import (
    SOURCE_FRED,
    SOURCE_MANUAL,
    SOURCE_SCRAPE,
    Indicator,
    SeriesSpec,
)

INDICATORS: list[Indicator] = [
    # ---- SECTION A — DEMAND SIDE → GDP ----------------------------------
    Indicator(
        key="gdp",
        name="Real GDP (annualized)",
        section="A · Demand → GDP",
        cadence="quarterly",
        intuition="Headline growth; watch the contribution split (consumption vs. "
                  "net exports vs. investment).",
        source_url="https://www.bea.gov/data/gdp/gross-domestic-product",
        source_type=SOURCE_FRED,
        series=[SeriesSpec("Real GDP, annualized", "GDPC1", "pca", "%", headline=True)],
    ),
    Indicator(
        key="trade_balance",
        name="Trade Balance (Goods & Services)",
        section="A · Demand → GDP",
        cadence="monthly",
        intuition="Net exports component of GDP; a widening deficit drags GDP; "
                  "front-running tariffs distorts imports.",
        source_url="https://www.bea.gov/news/2025/us-international-trade-goods-and-services-march-2025",
        source_type=SOURCE_FRED,
        series=[SeriesSpec("Balance, $B", "BOPGSTB", "lin", "$B", scale=0.001, headline=True)],
    ),
    Indicator(
        key="retail_sales",
        name="Advance Retail Sales",
        section="A · Demand → GDP",
        cadence="monthly",
        intuition="Fastest read on consumer demand; volatile, watch revisions.",
        source_url="https://www.census.gov/retail/sales.html",
        source_type=SOURCE_FRED,
        series=[
            SeriesSpec("MoM", "RSAFS", "pch", "%", headline=True),
            SeriesSpec("YoY", "RSAFS", "pc1", "%"),
        ],
    ),
    Indicator(
        key="pce",
        name="Personal Income & Outlays (PCE)",
        section="A · Demand → GDP",
        cadence="monthly",
        intuition="PCE is the consumption backbone of GDP; saving rate shows cushion; "
                  "spending > income = drawing down savings.",
        source_url="https://www.bea.gov/data/income-saving/personal-income",
        source_type=SOURCE_FRED,
        series=[
            SeriesSpec("PCE MoM", "PCE", "pch", "%", headline=True),
            SeriesSpec("Personal income MoM", "PI", "pch", "%"),
            SeriesSpec("Saving rate", "PSAVERT", "lin", "%"),
        ],
    ),
    Indicator(
        key="durable_goods",
        name="Durable Goods Orders",
        section="A · Demand → GDP",
        cadence="monthly",
        intuition="Proxy for business investment/capex appetite; ex-transport & "
                  "ex-defense are the cleaner signals.",
        source_url="https://www.census.gov/manufacturing/m3/adv/current/index.html",
        source_type=SOURCE_FRED,
        series=[
            SeriesSpec("New orders MoM", "DGORDER", "pch", "%", headline=True),
            SeriesSpec("Ex-transportation MoM", "ADXTNO", "pch", "%"),
        ],
    ),
    Indicator(
        key="fiscal_deficit",
        name="Federal Surplus/Deficit & Debt (context)",
        section="A · Demand → GDP",
        cadence="monthly",
        intuition="Government contribution to demand and the long-run sustainability "
                  "backdrop.",
        source_url="https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/",
        source_type=SOURCE_FRED,
        series=[
            SeriesSpec("Monthly surplus/deficit, $B", "MTSDS133FMS", "lin", "$B",
                       scale=0.001, headline=True),
            SeriesSpec("Total public debt, $T", "GFDEBTN", "lin", "$T", scale=1e-6),
        ],
    ),
    # ---- SECTION B — INCOME SIDE (Labor) --------------------------------
    Indicator(
        key="nonfarm_payroll",
        name="Employment Situation (Payrolls + Unemployment)",
        section="B · Income / Labor",
        cadence="monthly",
        intuition="Payroll growth + low unemployment = income engine for consumption; "
                  "watch sector mix and gov't drag.",
        source_url="https://www.bls.gov/news.release/empsit.nr0.htm",
        source_type=SOURCE_FRED,
        series=[
            SeriesSpec("Payrolls MoM change, K", "PAYEMS", "chg", "K", headline=True),
            SeriesSpec("Unemployment rate", "UNRATE", "lin", "%"),
        ],
    ),
    Indicator(
        key="real_earnings",
        name="Average Hourly Earnings (real proxy)",
        section="B · Income / Labor",
        cadence="monthly",
        intuition="Nominal wages minus inflation = real purchasing power; negative "
                  "real = inflation eating raises.",
        source_url="https://www.bls.gov/news.release/realer.nr0.htm",
        source_type=SOURCE_FRED,
        series=[
            SeriesSpec("Nominal AHE MoM", "CES0500000003", "pch", "%", headline=True),
            SeriesSpec("Nominal AHE YoY", "CES0500000003", "pc1", "%"),
        ],
    ),
    # ---- SECTION C — PRODUCTION -----------------------------------------
    Indicator(
        key="industrial_production",
        name="Industrial Production & Capacity Utilization",
        section="C · Production",
        cadence="monthly",
        intuition="Weak capacity utilization = slack in existing factories → less "
                  "incentive to invest.",
        source_url="https://www.federalreserve.gov/releases/g17/current/default.htm",
        source_type=SOURCE_FRED,
        series=[
            SeriesSpec("IP MoM", "INDPRO", "pch", "%", headline=True),
            SeriesSpec("IP YoY", "INDPRO", "pc1", "%"),
            SeriesSpec("Capacity utilization", "TCU", "lin", "%"),
        ],
    ),
    Indicator(
        key="ism_pmi",
        name="ISM PMI (Manufacturing & Services)",
        section="C · Production",
        cadence="monthly",
        intuition="Leading sentiment gauge; 50 is the expansion/contraction line; "
                  "services dominates the US economy.",
        source_url="https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/",
        source_type=SOURCE_SCRAPE,  # not on FRED (licensed); scrape best-effort + manual fallback
        series=[
            SeriesSpec("Manufacturing PMI", None, "lin", "index", headline=True),
            SeriesSpec("Services PMI", None, "lin", "index"),
        ],
    ),
    # ---- SECTION D — INFLATION ------------------------------------------
    Indicator(
        key="cpi",
        name="Consumer Price Index (CPI-U)",
        section="D · Inflation",
        cadence="monthly",
        intuition="Core strips volatile food/energy; shelter is sticky; this gates "
                  "Fed rate decisions.",
        source_url="https://www.bls.gov/cpi/",
        source_type=SOURCE_FRED,
        series=[
            SeriesSpec("Headline YoY", "CPIAUCSL", "pc1", "%", headline=True),
            SeriesSpec("Headline MoM", "CPIAUCSL", "pch", "%"),
            SeriesSpec("Core YoY", "CPILFESL", "pc1", "%"),
            SeriesSpec("Core MoM", "CPILFESL", "pch", "%"),
        ],
    ),
    Indicator(
        key="pce_price",
        name="PCE Price Index (Fed's preferred gauge)",
        section="D · Inflation",
        cadence="monthly",
        intuition="Fed's target gauge (2% goal); broader basket than CPI.",
        source_url="https://www.bea.gov/data/personal-consumption-expenditures-price-index",
        source_type=SOURCE_FRED,
        series=[
            SeriesSpec("Headline YoY", "PCEPI", "pc1", "%", headline=True),
            SeriesSpec("Core YoY", "PCEPILFE", "pc1", "%"),
        ],
    ),
    # ---- SECTION E — RATES ----------------------------------------------
    Indicator(
        key="yield_curve",
        name="Daily Treasury Yield Curve",
        section="E · Rates",
        cadence="daily",
        intuition="Inversion = recession warning; steepening long end = growth/"
                  "inflation expectations; pin Fed policy via the short end.",
        source_url="https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
        source_type=SOURCE_FRED,
        is_curve=True,
        series=[
            SeriesSpec("3M", "DGS3MO", "lin", "%"),
            SeriesSpec("2Y", "DGS2", "lin", "%"),
            SeriesSpec("5Y", "DGS5", "lin", "%"),
            SeriesSpec("10Y", "DGS10", "lin", "%", headline=True),
            SeriesSpec("20Y", "DGS20", "lin", "%"),
            SeriesSpec("30Y", "DGS30", "lin", "%"),
        ],
    ),
    # ---- SECTION F — TARIFFS / GEOPOLITICS (qualitative) ----------------
    Indicator(
        key="tariffs",
        name="Tariffs / Geopolitics",
        section="F · Tariffs / Geopolitics",
        cadence="irregular",
        intuition="The macro wildcard — feeds inflation, trade balance, durable-goods "
                  "front-running, and the rate path.",
        source_url="https://www.reuters.com/markets/us/",
        source_type=SOURCE_MANUAL,
        series=[SeriesSpec("Note", None, "lin", "", headline=True)],
    ),
]


def by_key(key: str) -> Indicator | None:
    return next((i for i in INDICATORS if i.key == key), None)


def sections() -> list[str]:
    seen: list[str] = []
    for ind in INDICATORS:
        if ind.section not in seen:
            seen.append(ind.section)
    return seen
