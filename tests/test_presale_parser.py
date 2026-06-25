import unittest

from rmbs.presale_parser import (
    build_inputs_from_confirmed,
    compute_ce_gap_sizes,
    extraction_summary,
    validation_flags,
)
from rmbs.presale_store import json_safe


class PresaleParserTest(unittest.TestCase):
    def test_ce_gap_sizing_collapses_duplicate_attachments(self):
        attachments = [
            {"class_name": "Senior A", "rating": "AAA", "credit_enhancement_pct": 22.0,
             "is_representative": True, "source_anchor_text": "AAA 22.0", "page_hint": "p1", "confidence": 0.9},
            {"class_name": "Senior A Exchangeable", "rating": "AAA", "credit_enhancement_pct": 22.0,
             "is_representative": False, "source_anchor_text": "AAA 22.0", "page_hint": "p1", "confidence": 0.9},
            {"class_name": "Mezz", "rating": "BBB", "credit_enhancement_pct": 8.0,
             "is_representative": True, "source_anchor_text": "BBB 8.0", "page_hint": "p1", "confidence": 0.9},
            {"class_name": "Sub", "rating": "B", "credit_enhancement_pct": 0.0,
             "is_representative": True, "source_anchor_text": "B 0.0", "page_hint": "p1", "confidence": 0.9},
        ]

        sizes = compute_ce_gap_sizes(attachments)

        self.assertEqual([row["class_name"] for row in sizes], ["Senior A", "Mezz", "Sub"])
        self.assertAlmostEqual(sum(row["thickness_pct"] for row in sizes), 100.0)
        self.assertAlmostEqual(sizes[0]["thickness_pct"], 78.0)
        self.assertAlmostEqual(sizes[1]["thickness_pct"], 14.0)
        self.assertAlmostEqual(sizes[2]["thickness_pct"], 8.0)

    def test_validation_flags_are_relative_not_fixed_value_checks(self):
        parsed = {
            "fields": {
                "collateral_notional": {"value": 500_000_000, "source_anchor_text": "Closing pool balance 500", "confidence": 0.9},
                "collateral_summary_notional": {"value": 525_000_000, "source_anchor_text": "principal balance 525", "confidence": 0.9},
                "wa_coupon_pct": {"value": 7.1, "source_anchor_text": None, "confidence": 0.8},
            }
        }

        flags = validation_flags(parsed, [])

        self.assertTrue(any("differ by more than 2%" in flag for flag in flags))
        self.assertTrue(any("WA Coupon has a sourced value but no anchor text" in flag for flag in flags))

    def test_build_inputs_from_confirmed_uses_confirmed_values_and_assumptions(self):
        confirmed = {
            "collateral_notional": "750 million",
            "wa_coupon_pct": 7.25,
            "term_months": 360,
            "seasoning_months": 6,
            "wa_fico": 744,
            "wa_cltv_pct": 70.5,
            "wa_dscr": 1.18,
            "severity_low_pct": 20.0,
            "severity_high_pct": 50.0,
            "foreclosure_freq_low_pct": 3.5,
            "foreclosure_freq_high_pct": 18.0,
        }
        assumptions = {
            "cpr_pct": 9.0,
            "cdr_pct": 1.25,
            "severity_pct": 35.0,
            "yield_target_pct": 8.5,
            "servicing_fee_pct": 0.3,
            "admin_fee_pct": 0.05,
            "sofr_pct": 4.0,
            "spread_pct": 2.25,
            "advance_rate_pct": 84.0,
        }
        ce_sizes = [
            {"thickness_pct": 80.0},
            {"thickness_pct": 5.0},
            {"thickness_pct": 15.0},
        ]

        inputs = build_inputs_from_confirmed(confirmed, assumptions, ce_sizes)

        self.assertEqual(inputs.deal_balance, 750_000_000)
        self.assertEqual(inputs.gross_coupon_pct, 7.25)
        self.assertEqual(inputs.term_months, 360)
        self.assertEqual(inputs.advance_rate_pct, 84.0)
        self.assertEqual(inputs.a1_pct, 80.0)
        self.assertEqual(inputs.a1f_pct, 5.0)
        self.assertEqual(inputs.a2_pct, 15.0)
        self.assertEqual(inputs.b_foreclosure_frequency_pct, 3.5)
        self.assertEqual(inputs.aaa_foreclosure_frequency_pct, 18.0)
        self.assertAlmostEqual(100 - inputs.advance_rate_pct, 16.0)

    def test_parse_memory_json_sanitizer_handles_non_finite_metrics(self):
        safe = json_safe({"good": 1.5, "bad": float("inf"), "nested": [float("nan")]})

        self.assertEqual(safe["good"], 1.5)
        self.assertIsNone(safe["bad"])
        self.assertIsNone(safe["nested"][0])


if __name__ == "__main__":
    unittest.main()
