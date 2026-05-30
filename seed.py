"""Seed the DB with the hand-tracked data from ECON_DASHBOARD_BRIEF.md §2.

Why seed at all when FRED provides the quantitative series? Two reasons:
  1. The dashboard shows real numbers immediately, before you add a FRED key.
  2. ISM PMI and Tariffs are NOT on FRED — these seeds are their source of truth.

Series labels here must match indicators.py so they render under the right
indicator. A later `refresh` overlays/extends FRED series on top of these.

Run:  python seed.py
"""

from __future__ import annotations

from datetime import date

from econ import store
from econ.models import Reading


def R(key, label, period, value, unit, release=None, note="", src="seed:brief"):
    return Reading(
        indicator_key=key, series_label=label, period=period, value=value,
        unit=unit, release_date=release, commentary=note, source=src,
    )


# Periods are the DATA period (first of month / quarter); release dates per §2.
SEED: list[Reading] = [
    # A1 GDP (quarterly, annualized)
    R("gdp", "Real GDP, annualized", date(2025, 10, 1), 0.5, "%", date(2026, 4, 30),
      "Q4 2025 read."),
    R("gdp", "Real GDP, annualized", date(2026, 1, 1), 2.0, "%", date(2026, 4, 30),
      "Q1 2026; advance estimate referenced -0.3% — confirm vs. source."),

    # A2 Trade balance ($B, negative = deficit)
    R("trade_balance", "Balance, $B", date(2026, 3, 1), -60.3, "$B", date(2026, 5, 5),
      "Deficit up $2.5B from $57.8B (Feb, revised). YTD -$211.2B (-55.0%)."),

    # A4 Retail sales
    R("retail_sales", "MoM", date(2025, 1, 1), -0.9, "%", date(2025, 2, 17), "Possible cool-down."),
    R("retail_sales", "MoM", date(2025, 3, 1), 1.6, "%", date(2026, 5, 14), "Revised from +1.7%."),
    R("retail_sales", "MoM", date(2026, 4, 1), 0.5, "%", date(2026, 5, 14),
      "$757.1B (+/-0.4) MoM; +4.9% YoY."),
    R("retail_sales", "YoY", date(2026, 4, 1), 4.9, "%", date(2026, 5, 14)),

    # A5 PCE / personal income
    R("pce", "PCE MoM", date(2025, 1, 1), -0.2, "%", date(2025, 2, 28),
      "-0.5% real — biggest monthly decline since Feb 2021."),
    R("pce", "PCE MoM", date(2026, 3, 1), 0.9, "%", date(2026, 4, 30), "+$195.4B."),
    R("pce", "Personal income MoM", date(2026, 3, 1), 0.6, "%", date(2026, 4, 30), "+$149.2B."),
    R("pce", "Saving rate", date(2026, 3, 1), 3.6, "%", date(2026, 4, 30), "$857.3B saved."),

    # A6 Durable goods
    R("durable_goods", "New orders MoM", date(2025, 1, 1), 3.1, "%", date(2025, 2, 27),
      "+$8.7B to $286.0B; ended two declines."),
    R("durable_goods", "New orders MoM", date(2026, 3, 1), 0.8, "%", date(2026, 4, 26),
      "+$2.6B to $318.9B; ended 3 monthly declines."),
    R("durable_goods", "Ex-transportation MoM", date(2026, 3, 1), 0.9, "%", date(2026, 4, 26)),

    # A7 Fiscal context
    R("fiscal_deficit", "Total public debt, $T", date(2026, 3, 1), 36.0, "$T", None,
      "~$36T total federal debt; ~$840B deficit this period."),

    # B1 Payrolls + unemployment
    R("nonfarm_payroll", "Payrolls MoM change, K", date(2025, 1, 1), 143, "K", date(2025, 2, 7)),
    R("nonfarm_payroll", "Payrolls MoM change, K", date(2025, 3, 1), 228, "K", date(2025, 4, 4)),
    R("nonfarm_payroll", "Payrolls MoM change, K", date(2026, 4, 1), 115, "K", date(2026, 5, 8),
      "Gains in health care, transport/warehousing, retail; federal gov't still declining."),
    R("nonfarm_payroll", "Unemployment rate", date(2025, 1, 1), 4.0, "%", date(2025, 2, 7)),
    R("nonfarm_payroll", "Unemployment rate", date(2026, 4, 1), 4.3, "%", date(2026, 5, 8)),

    # B2 Real earnings (nominal AHE proxy)
    R("real_earnings", "Nominal AHE MoM", date(2026, 4, 1), 0.2, "%", date(2026, 5, 13),
      "Real -0.5% (CPI-U +0.6%) — inflation ate the raise."),

    # C1 Industrial production
    R("industrial_production", "IP MoM", date(2025, 3, 1), -0.3, "%", date(2025, 4, 16),
      "+5.5% annual; cap-util 77.8%."),
    R("industrial_production", "IP MoM", date(2026, 4, 1), 0.7, "%", date(2026, 5, 15),
      "Mfg +0.6%, utilities +1.9%; IP 102.5% of 2017 avg, +1.4% YoY."),
    R("industrial_production", "Capacity utilization", date(2026, 4, 1), 76.1, "%", date(2026, 5, 15),
      "3.3pp below long-run (1972-2025) average."),

    # C2 ISM PMI (NOT on FRED — seed is source of truth)
    R("ism_pmi", "Manufacturing PMI", date(2025, 2, 1), 50.9, "index", date(2025, 3, 1), src="seed:brief"),
    R("ism_pmi", "Services PMI", date(2025, 2, 1), 52.8, "index", date(2025, 3, 1)),
    R("ism_pmi", "Manufacturing PMI", date(2025, 5, 1), 48.7, "index", date(2025, 6, 1), "Contraction."),
    R("ism_pmi", "Services PMI", date(2025, 5, 1), 53.7, "index", date(2025, 6, 1)),
    R("ism_pmi", "Manufacturing PMI", date(2026, 4, 1), 52.7, "index", date(2026, 5, 1), "Same as March."),
    R("ism_pmi", "Services PMI", date(2026, 4, 1), 53.6, "index", date(2026, 5, 1), "-0.4pp from 54.0%."),

    # D1 CPI
    R("cpi", "Headline YoY", date(2026, 4, 1), 3.8, "%", date(2026, 5, 12), "Shelter & gasoline up."),
    R("cpi", "Headline MoM", date(2026, 4, 1), 0.6, "%", date(2026, 5, 12)),
    R("cpi", "Core YoY", date(2026, 4, 1), 2.8, "%", date(2026, 5, 12)),
    R("cpi", "Core MoM", date(2026, 4, 1), 0.4, "%", date(2026, 5, 12)),

    # D2 PCE price index
    R("pce_price", "Headline YoY", date(2025, 3, 1), 2.3, "%", date(2025, 4, 30),
      "Down from 2.7% Feb — disinflation."),

    # E1 Yield curve (2026-05-26 snapshot)
    R("yield_curve", "3M", date(2026, 5, 26), 4.43, "%", date(2026, 5, 26)),
    R("yield_curve", "2Y", date(2026, 5, 26), 4.60, "%", date(2026, 5, 26)),
    R("yield_curve", "5Y", date(2026, 5, 26), 4.72, "%", date(2026, 5, 26)),
    R("yield_curve", "10Y", date(2026, 5, 26), 4.85, "%", date(2026, 5, 26)),
    R("yield_curve", "20Y", date(2026, 5, 26), 5.02, "%", date(2026, 5, 26)),
    R("yield_curve", "30Y", date(2026, 5, 26), 5.05, "%", date(2026, 5, 26)),

    # F Tariffs / Geopolitics (qualitative notes)
    R("tariffs", "Note", date(2025, 2, 28), None, "", date(2025, 2, 28),
      "China +10%; 25% on Mexico & Canada; Europe VAT rebated on exports.", "seed:brief"),
    R("tariffs", "Note", date(2025, 5, 2), None, "", date(2025, 5, 2),
      "Imports strong ahead of tariffs; negotiations with UK, Mexico, Canada, EU, "
      "Japan, China. UK ~baseline 10%.", "seed:brief"),
]


def main() -> None:
    store.init_db()
    stats = store.upsert_readings(SEED)
    store.set_meta("seeded_at", date.today().isoformat())
    print(f"Seeded {len(SEED)} readings: {stats}")


if __name__ == "__main__":
    main()
