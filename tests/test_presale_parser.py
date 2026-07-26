import unittest
from rmbs.presale_parser import (
    build_inputs_from_confirmed,
    compute_ce_gap_sizes,
    extraction_rows,
    extraction_summary,
    nuance_rows,
    numeric_value,
    validation_flags,
)
from rmbs.presale_store import json_safe
from rmbs.calculator import RmbsInputs
from rmbs.warehouse_app import (
    advance_spread_equity_irr_table,
    advance_spread_sensitivity_table,
    cpr_cdr_sensitivity_table,
    cdr_severity_equity_irr_table,
    cdr_severity_sensitivity_table,
    debt_tranche_pct,
    field_review_display_df,
    missing_sourced_rows,
    nuance_review_display_df,
    parser_credit_error,
    review_flags_html,
    sensitivity_table_html,
    simple_range_note,
    tranche_a1_pct,
    tranche_stack_label,
)


class PresaleParserTest(unittest.TestCase):
    def test_parser_credit_error_detects_credit_and_quota_messages(self):
        self.assertTrue(parser_credit_error("insufficient_quota: billing credits exhausted"))
        self.assertTrue(parser_credit_error("Payment required: account balance is too low"))
        self.assertFalse(parser_credit_error("PDF text extraction failed"))

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

    def test_ce_gap_sizing_uses_aggregate_a1_over_a1a_component(self):
        attachments = [
            {"class_name": "A-1", "rating": "AAA", "credit_enhancement_pct": 23.26,
             "is_representative": True, "source_anchor_text": "A-1 23.26", "page_hint": "p1", "confidence": 0.9},
            {"class_name": "A-1-A", "rating": "AAA", "credit_enhancement_pct": 33.26,
             "is_representative": True, "source_anchor_text": "A-1-A 33.26", "page_hint": "p1", "confidence": 0.9},
            {"class_name": "A-1-B", "rating": "AAA", "credit_enhancement_pct": 23.26,
             "is_representative": False, "source_anchor_text": "A-1-B 23.26", "page_hint": "p1", "confidence": 0.9},
            {"class_name": "A-2", "rating": "AA", "credit_enhancement_pct": 18.0,
             "is_representative": True, "source_anchor_text": "A-2 18.00", "page_hint": "p1", "confidence": 0.9},
            {"class_name": "B-3", "rating": "NR", "credit_enhancement_pct": 0.0,
             "is_representative": True, "source_anchor_text": "B-3 0.00", "page_hint": "p1", "confidence": 0.9},
        ]

        sizes = compute_ce_gap_sizes(attachments)

        self.assertEqual(sizes[0]["class_name"], "A-1")
        self.assertAlmostEqual(sizes[0]["attachment_pct"], 23.26)
        self.assertAlmostEqual(sizes[0]["thickness_pct"], 76.74)
        self.assertNotIn("A-1-A", [row["class_name"] for row in sizes])

    def test_ce_gap_sizing_infers_a1_from_junior_component_when_aggregate_missing(self):
        attachments = [
            {"class_name": "A-1-A", "rating": "AAA", "credit_enhancement_pct": 33.26,
             "is_representative": True, "source_anchor_text": "A-1-A 33.26", "page_hint": "p1", "confidence": 0.9},
            {"class_name": "A-1-B", "rating": "AAA", "credit_enhancement_pct": 23.26,
             "is_representative": True, "source_anchor_text": "A-1-B 23.26", "page_hint": "p1", "confidence": 0.9},
            {"class_name": "B-3", "rating": "NR", "credit_enhancement_pct": 0.0,
             "is_representative": True, "source_anchor_text": "B-3 0.00", "page_hint": "p1", "confidence": 0.9},
        ]

        sizes = compute_ce_gap_sizes(attachments)

        self.assertEqual(sizes[0]["class_name"], "A-1")
        self.assertAlmostEqual(sizes[0]["attachment_pct"], 23.26)
        self.assertAlmostEqual(sizes[0]["thickness_pct"], 76.74)

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
            "cumulative_loss_trigger_pct": 2.25,
            "delinquency_trigger_pct": 4.50,
            "servicing_fee_pct": 0.28,
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
        self.assertEqual(inputs.stepdown_cum_loss_trigger_pct, 2.25)
        self.assertEqual(inputs.stepdown_dq_trigger_pct, 4.50)
        self.assertEqual(inputs.servicing_fee_pct, 0.3)
        self.assertEqual(inputs.admin_fee_pct, 0.0)
        self.assertAlmostEqual(100 - inputs.advance_rate_pct, 16.0)

    def test_build_inputs_uses_sourced_servicing_when_assumption_missing(self):
        inputs = build_inputs_from_confirmed(
            {"collateral_notional": 100_000_000, "servicing_fee_pct": 0.42},
            {"cpr_pct": 8.0, "cdr_pct": 1.0, "yield_target_pct": 7.0, "sofr_pct": 4.0,
             "spread_pct": 2.0, "advance_rate_pct": 80.0},
            [],
        )

        self.assertEqual(inputs.servicing_fee_pct, 0.42)
        self.assertEqual(inputs.admin_fee_pct, 0.0)

    def test_parse_memory_json_sanitizer_handles_non_finite_metrics(self):
        safe = json_safe({"good": 1.5, "bad": float("inf"), "nested": [float("nan")]})

        self.assertEqual(safe["good"], 1.5)
        self.assertIsNone(safe["bad"])
        self.assertIsNone(safe["nested"][0])

    def test_nan_confirmed_values_are_flagged_for_manual_input(self):
        rows = [
            {"field": "term_months", "label": "WA Original Term", "approved_value": float("nan")},
            {"field": "wa_coupon_pct", "label": "WA Coupon", "approved_value": 12.45},
            {"field": "severity_high_pct", "label": "Severity High", "approved_value": "nan"},
        ]

        self.assertIsNone(numeric_value(float("nan")))
        self.assertIsNone(numeric_value("nan"))
        self.assertEqual(
            [row["field"] for row in missing_sourced_rows(rows)],
            ["term_months", "severity_high_pct"],
        )

    def test_field_review_display_hides_internal_parser_columns(self):
        display = field_review_display_df([
            {
                "field": "wa_coupon_pct",
                "label": "WA Coupon",
                "approved_value": 12.45,
                "page": "PAGE 7",
                "confidence": 0.95,
                "anchor": "source text",
            },
            {
                "field": "collateral_summary_notional",
                "label": "Collateral Summary Notional",
                "approved_value": 525_000_000,
                "page": "PAGE 8",
                "confidence": 0.95,
                "anchor": "summary text",
            }
        ])

        self.assertEqual(list(display.columns), ["Label", "approved_value", "Page", "Verified"])
        self.assertEqual(len(display), 1)
        self.assertEqual(display.iloc[0]["Verified"], "✅")
        self.assertEqual(display["approved_value"].dtype, object)
        self.assertEqual(display.iloc[0]["approved_value"], "12.45")

    def test_headline_review_excludes_nuanced_presale_fields(self):
        parsed = {
            "fields": {
                "collateral_notional": {"value": 100_000_000, "page_hint": "PAGE 1", "source_anchor_text": "balance", "confidence": 1},
                "severity_low_pct": {"value": 20, "page_hint": "PAGE 8", "source_anchor_text": "B severity", "confidence": 1},
                "prepayment_high_pct": {"value": 25, "page_hint": "PAGE 9", "source_anchor_text": "AAA CPR", "confidence": 1},
                "servicing_fee_pct": {"value": 0.25, "page_hint": "PAGE 10", "source_anchor_text": "servicing fee", "confidence": 1},
            }
        }

        headline_fields = [row["field"] for row in extraction_rows(parsed)]
        nuance_fields = [row["field"] for row in nuance_rows(parsed)]
        nuance_display = nuance_review_display_df(parsed)

        self.assertIn("collateral_notional", headline_fields)
        self.assertNotIn("severity_low_pct", headline_fields)
        self.assertNotIn("servicing_fee_pct", headline_fields)
        self.assertIn("severity_low_pct", nuance_fields)
        self.assertIn("prepayment_high_pct", nuance_fields)
        self.assertEqual(len(nuance_display), 3)
        self.assertNotIn("WA DSCR", nuance_display["Label"].tolist())
        self.assertIn("Servicing Fee", nuance_display["Label"].tolist())

    def test_headline_review_supports_dynamic_deal_metrics(self):
        parsed = {
            "fields": {
                "collateral_notional": {"value": 100_000_000, "page_hint": "PAGE 1", "source_anchor_text": "balance", "confidence": 1},
                "wa_coupon_pct": {"value": 10.2, "page_hint": "PAGE 2", "source_anchor_text": "APR", "confidence": 1},
                "term_months": {"value": 72, "page_hint": "PAGE 2", "source_anchor_text": "term", "confidence": 1},
                "seasoning_months": {"value": 9, "page_hint": "PAGE 2", "source_anchor_text": "seasoning", "confidence": 1},
            },
            "headline_metrics": [
                {
                    "label": "YSOA",
                    "value": 93.4,
                    "unit": "%",
                    "page_hint": "PAGE 5",
                    "source_anchor_text": "yielding share of assets 93.4%",
                    "confidence": 0.91,
                }
            ],
        }

        display = field_review_display_df(extraction_rows(parsed))

        self.assertIn("YSOA (%)", display["Label"].tolist())
        self.assertNotIn("WA DSCR", display["Label"].tolist())
        self.assertTrue(display.loc[display["Label"].eq("YSOA (%)"), "Verified"].eq("✅").all())

    def test_review_flags_render_as_numbered_notes_without_parser_note_label(self):
        html = review_flags_html([
            "Severity High is missing and needs review.",
            "This unusual flag has no obvious field.",
        ])

        self.assertIn("<ol", html)
        self.assertIn("<strong>Severity High</strong> is missing and needs review.", html)
        self.assertIn("This unusual flag has no obvious field.", html)
        self.assertNotIn("Parser note", html)

    def test_warehouse_app_sensitivity_tables_recompute_scenarios(self):
        inputs = RmbsInputs()

        cdr_table = cdr_severity_equity_irr_table(inputs)
        advance_table = advance_spread_equity_irr_table(inputs)
        speed_table = cpr_cdr_sensitivity_table(inputs, "Levered Equity IRR")

        self.assertEqual(cdr_table.shape, (5, 5))
        self.assertEqual(advance_table.shape, (5, 5))
        self.assertEqual(speed_table.shape, (5, 5))
        self.assertEqual(cdr_table.index[0], "0.25%")
        self.assertIn("35%", cdr_table.columns)
        self.assertIn("2%", advance_table.columns)
        self.assertIn("8%", speed_table.columns)
        self.assertTrue(cdr_table.map(lambda value: isinstance(value, float)).all().all())
        self.assertTrue(advance_table.map(lambda value: isinstance(value, float)).all().all())
        self.assertTrue(speed_table.map(lambda value: isinstance(value, float)).all().all())

    def test_warehouse_app_sensitivity_tables_support_selectable_metrics(self):
        inputs = RmbsInputs()

        collateral_wal_table = cdr_severity_sensitivity_table(inputs, "Collateral WAL")
        facility_wal_table = advance_spread_sensitivity_table(inputs, "Facility WAL")
        net_loss_table = cdr_severity_sensitivity_table(inputs, "Cumulative Net Loss")
        lender_loss_table = advance_spread_sensitivity_table(inputs, "Lender Loss")

        self.assertEqual(collateral_wal_table.shape, (5, 5))
        self.assertEqual(facility_wal_table.shape, (5, 5))
        self.assertTrue((collateral_wal_table > 0).all().all())
        self.assertTrue((facility_wal_table >= 0).all().all())
        self.assertTrue((net_loss_table >= 0).all().all())
        self.assertTrue((lender_loss_table >= 0).all().all())

    def test_warehouse_app_sensitivity_tables_use_presale_ranges_and_single_base_cell(self):
        inputs = RmbsInputs(cdr_pct=10.0, severity_pct=35.0)
        confirmed = {
            "foreclosure_freq_low_pct": 4.22,
            "foreclosure_freq_high_pct": 28.67,
            "severity_low_pct": 20.14,
            "severity_high_pct": 49.88,
        }

        table = cdr_severity_sensitivity_table(inputs, "Levered Equity IRR", confirmed)
        rendered = sensitivity_table_html(
            "Credit Stress",
            "test",
            table,
            "10.33%",
            "35.01%",
            "Levered Equity IRR",
            "CDR",
            "Severity",
        )

        self.assertIn("4.22%", table.index)
        self.assertIn("28.67%", table.index)
        self.assertIn("20.14%", table.columns)
        self.assertIn("49.88%", table.columns)
        self.assertEqual(len(table.index), 5)
        self.assertEqual(len(table.columns), 5)
        self.assertIn("class='y-axis-label'", rendered)
        self.assertIn(">Severity</th>", rendered)
        self.assertEqual(rendered.count("base-cell"), 2)  # CSS rule + one highlighted value cell.

    def test_tranche_stack_label_collapses_exchangeable_senior_variants(self):
        self.assertEqual(tranche_stack_label({"class_name": "A-1A"}, 0), "A1")
        self.assertEqual(tranche_stack_label({"class_name": "A-1B"}, 0), "A1")
        self.assertEqual(tranche_stack_label({"class_name": "Class B"}, 1), "B")

    def test_assumption_note_helpers_are_concise_and_debt_tranche_seeded(self):
        self.assertEqual(simple_range_note("Presale range", 1, 25), "Presale range: 1%-25%")
        self.assertEqual(simple_range_note("Presale range", None, None), "Presale range: n/a")
        ce_sizes = [
            {"class_name": "A-1A", "thickness_pct": 67.44},
            {"class_name": "B", "thickness_pct": 24.36},
            {"class_name": "Residual", "thickness_pct": 8.20},
        ]
        self.assertEqual(debt_tranche_pct(ce_sizes), 91.8)
        self.assertEqual(tranche_a1_pct(ce_sizes), 91.8)


if __name__ == "__main__":
    unittest.main()
