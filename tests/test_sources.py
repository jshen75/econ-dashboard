from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from econ.indicators import by_key
from econ.models import Indicator, Reading, SeriesSpec
from econ.sources import _fred_series, parse_gdelt_timeline_readings, parse_warn_pa_readings


class SourceParserTests(unittest.TestCase):
    def test_parse_warn_pa_readings_groups_by_month(self) -> None:
        ind = by_key("warn_notices")
        assert ind is not None
        html = """
        <h2>2026</h2>
        <h3>May</h3>
        <h3>Acme Widgets</h3>
        <p>COUNTY: Allegheny</p>
        <p># AFFECTED: 125</p>
        <h3>Beta Logistics</h3>
        <p># AFFECTED: 75</p>
        <h3>March</h3>
        <h3>Gamma Foods</h3>
        <p># AFFECTED: 20</p>
        """

        readings = parse_warn_pa_readings(html, ind)
        keyed = {(r.period, r.series_label): r for r in readings}

        self.assertEqual(keyed[(date(2026, 5, 1), "Affected workers")].value, 200)
        self.assertEqual(keyed[(date(2026, 5, 1), "Notice count")].value, 2)
        self.assertEqual(keyed[(date(2026, 3, 1), "Affected workers")].value, 20)
        self.assertEqual(
            keyed[(date(2026, 5, 1), "Affected workers")].source,
            "scrape:warn:pa",
        )

    def test_parse_gdelt_timeline_readings_adds_normalized_share(self) -> None:
        ind = Indicator(
            key="immigration_news",
            name="Immigration News Coverage",
            section="F",
            cadence="daily",
            intuition="Coverage pressure.",
            source_url="https://summary.gdeltproject.org/",
            source_type="news",
            series=[
                SeriesSpec("Article count", unit="articles"),
                SeriesSpec("Share per 100k articles", unit="per 100k"),
            ],
        )
        payload = {
            "timeline": [
                {
                    "series": "Article Count",
                    "data": [
                        {"date": "20260601T000000Z", "value": 20, "norm": 40000},
                        {"date": "20260601T010000Z", "value": 30, "norm": 60000},
                        {"date": "2026-06-02", "value": "25", "norm": "50000"},
                    ],
                }
            ]
        }

        readings = parse_gdelt_timeline_readings(payload, ind)
        keyed = {(r.period, r.series_label): r for r in readings}

        self.assertEqual(keyed[(date(2026, 6, 1), "Article count")].value, 50)
        self.assertEqual(
            keyed[(date(2026, 6, 1), "Share per 100k articles")].value,
            50,
        )
        self.assertEqual(keyed[(date(2026, 6, 2), "Article count")].source, "news:gdelt")

    def test_fred_series_uses_incremental_observation_start(self) -> None:
        ind = Indicator(
            key="jobless_claims",
            name="Unemployment Insurance Claims",
            section="B",
            cadence="weekly",
            intuition="Claims pressure.",
            source_url="https://oui.doleta.gov/unemploy/claims.asp",
            source_type="fred",
            series=[],
        )
        spec = SeriesSpec("Initial claims, K", "ICSA", "lin", "K", scale=0.001)
        latest = Reading(ind.key, spec.label, date(2026, 6, 1), 240, "K")
        calls: list[dict] = []

        def fake_fetch(_url: str, **kwargs):
            calls.append(kwargs)
            return {"observations": [{"date": "2026-06-08", "value": "250000"}]}

        with patch("econ.sources.store.latest_reading", return_value=latest), \
             patch("econ.sources.fetch", side_effect=fake_fetch):
            readings = _fred_series(spec, ind, "key")

        self.assertEqual(calls[0]["params"]["observation_start"], "2026-04-27")
        self.assertEqual(readings[0].value, 250)


if __name__ == "__main__":
    unittest.main()
