"""Data shapes for the Econ Dashboard.

Mirrors §1 of ECON_DASHBOARD_BRIEF.md: every indicator shares one shape, and a
reading is one normalized observation. Indicators are *config* (see indicators.py),
so adding a new one is a new row here, not new code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# How an indicator is sourced. One fetch interface routes on this (brief §4).
SOURCE_FRED = "fred"        # pull clean numbers from the FRED API
SOURCE_SCRAPE = "scrape"    # scrape a human page (ISM PMI)
SOURCE_MANUAL = "manual"    # hand-entered notes (Tariffs / Geopolitics)


@dataclass(frozen=True)
class SeriesSpec:
    """One data series inside an indicator.

    An indicator can show several series (e.g. CPI shows headline YoY, headline
    MoM, core YoY, core MoM). FRED computes the transform for us server-side, so
    we just ask for the units we want.
    """

    label: str                  # human label, e.g. "Headline YoY"
    fred_id: str | None = None  # FRED series id; None for non-FRED sources
    transform: str = "lin"      # FRED `units`: lin|pch|pc1|chg|ch1|pca
    unit: str = ""             # display unit: "%", "$B", "index", "K"
    scale: float = 1.0          # multiply raw value (e.g. 1/1000 for $M -> $B)
    headline: bool = False      # show this series as the indicator's big number


@dataclass(frozen=True)
class Indicator:
    """Static config for one dashboard indicator (brief §1 data shape)."""

    key: str                    # "cpi", "nonfarm_payroll"
    name: str                   # "Consumer Price Index (CPI-U)"
    section: str                # "Inflation"
    cadence: str                # monthly | quarterly | daily | irregular
    intuition: str              # what rising/falling means
    source_url: str             # the link you open to get the latest release
    source_type: str            # SOURCE_FRED | SOURCE_SCRAPE | SOURCE_MANUAL
    series: list[SeriesSpec] = field(default_factory=list)
    is_curve: bool = False      # render as a yield-curve line (x = maturity)

    def headline_series(self) -> SeriesSpec | None:
        for s in self.series:
            if s.headline:
                return s
        return self.series[0] if self.series else None


@dataclass(frozen=True)
class Reading:
    """One normalized observation for one series of one indicator.

    Government data revises constantly (brief §4), so we keep `prior_value` to
    render "revised from X to Y" instead of silently overwriting.
    """

    indicator_key: str
    series_label: str
    period: date                # the data period (FRED observation date)
    value: float | None         # the number, already scaled
    unit: str = ""
    release_date: date | None = None  # when the agency published it
    commentary: str = ""
    raw_snippet: str = ""       # source text kept for auditing the parse
    source: str = ""            # "fred:CPIAUCSL", "scrape:ism", "manual"
    prior_value: float | None = None  # set when this period was revised
