import unittest
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

import pandas as pd

from rmbs.calculator import RmbsInputs, TRANCHES, project_rmbs_waterfall, tranche_initial_balances
from rmbs.page import (
    SCENARIO_A_COLUMNS,
    advance_optimization,
    analysis_sanity_checks,
    attachment_sensitivity,
    build_excel_download,
    build_warehouse_excel_download,
    build_results_object,
    cdr_sensitivity,
    equity_irr_zero_point_text,
    investment_report_fact_packet,
    named_warehouse_scenario_summary,
    structural_breakeven_loss_pct,
    warehouse_table,
)
from rmbs.report_writer import validate_llm_report


class RmbsCalculatorTest(unittest.TestCase):
    def test_defaults_match_obx_2026_nqm8_seed_values(self):
        inputs = RmbsInputs()

        self.assertEqual(inputs.deal_balance, 1_022_400_000.0)
        self.assertEqual(inputs.gross_coupon_pct, 6.80)
        self.assertEqual(inputs.term_months, 358)
        self.assertEqual(inputs.seasoning_months, 3)
        self.assertEqual(inputs.severity_pct, 35.0)
        self.assertEqual(inputs.aaa_attachment_pct, 20.0)
        self.assertEqual(inputs.wa_fico, 757)
        self.assertEqual(inputs.wa_cltv_pct, 68.9)
        self.assertEqual(inputs.wa_dscr, 1.11)
        self.assertEqual(inputs.aaa_loss_severity_pct, 49.88)
        self.assertEqual(inputs.b_loss_severity_pct, 20.14)
        self.assertEqual(inputs.aaa_foreclosure_frequency_pct, 28.67)
        self.assertEqual(inputs.b_foreclosure_frequency_pct, 4.22)

    def test_tranche_balances_sum_to_deal_balance(self):
        inputs = RmbsInputs()
        balances = tranche_initial_balances(inputs)

        self.assertAlmostEqual(sum(balances.values()), inputs.deal_balance, places=2)
        self.assertEqual(TRANCHES[0], "A1")
        self.assertEqual(TRANCHES[-1], "B3")
        self.assertAlmostEqual(balances["A1"] / inputs.deal_balance, 0.80, places=6)
        self.assertAlmostEqual(balances["A2"] / inputs.deal_balance, 0.041, places=6)
        self.assertAlmostEqual(balances["A3"] / inputs.deal_balance, 0.0785, places=6)
        self.assertAlmostEqual(balances["M1"] / inputs.deal_balance, 0.035, places=6)
        self.assertAlmostEqual(balances["B3"] / inputs.deal_balance, 0.008, places=6)
        self.assertNotIn("A1A", balances)

    def test_default_case_steps_down_after_lockout(self):
        schedule, tranche_summary, metrics = project_rmbs_waterfall(RmbsInputs())

        self.assertFalse(schedule.empty)
        self.assertFalse(tranche_summary.empty)
        self.assertEqual(schedule.loc[schedule["Period"] == 36, "Payment Mode"].iloc[0], "Sequential")
        self.assertEqual(
            schedule.loc[schedule["Period"] == 37, "Payment Mode"].iloc[0],
            "Modified pro-rata",
        )
        self.assertGreater(metrics["Senior WAL"], 0)
        self.assertGreater(metrics["Senior IRR"], 0)

    def test_collateral_engine_uses_scenario_one_performing_pool_logic(self):
        inputs = RmbsInputs()
        schedule, _tranche_summary, metrics = project_rmbs_waterfall(inputs)
        row = schedule.loc[schedule["Period"] == 1].iloc[0]

        self.assertIn("Survival Factor", schedule.columns)
        self.assertIn("Remaining Performing Balance", schedule.columns)
        self.assertIn("Scheduled Payment", schedule.columns)
        self.assertIn("Balance Decline %", schedule.columns)
        self.assertAlmostEqual(
            row["Collateral Interest"],
            row["Remaining Performing Balance"] * inputs.gross_coupon_pct / 100 / 12,
            places=2,
        )
        self.assertAlmostEqual(
            row["Servicing Fee"],
            row["Remaining Performing Balance"] * inputs.servicing_fee_pct / 100 / 12,
            places=2,
        )
        self.assertAlmostEqual(
            row["Admin Fee"],
            row["Remaining Performing Balance"] * inputs.admin_fee_pct / 100 / 12,
            places=2,
        )
        self.assertAlmostEqual(
            row["Prepayments"],
            (row["Collateral Beginning Balance"] - row["Surviving Scheduled Principal"])
            * metrics["SMM"],
            places=2,
        )
        self.assertGreater(metrics["Purchase Price ($)"], 0)
        self.assertGreater(metrics["Collateral WAL"], 0)
        self.assertGreater(metrics["Cumulative Defaults %"], metrics["Cumulative Net Loss %"])

    def test_warehouse_sidecar_metrics_are_present(self):
        schedule, _tranche_summary, metrics = project_rmbs_waterfall(RmbsInputs())

        self.assertIn("Facility Beginning Balance", schedule.columns)
        self.assertIn("Facility Interest Owed", schedule.columns)
        self.assertIn("Facility Ending Balance", schedule.columns)
        self.assertIn("Warehouse Equity Cashflow", schedule.columns)
        self.assertIn("Unlevered Equity Cashflow", schedule.columns)
        self.assertAlmostEqual(metrics["Facility Rate"], 0.0561, places=6)
        self.assertGreater(metrics["Initial Facility Notional"], 0)
        self.assertGreater(metrics["Facility WAL"], 0)
        self.assertGreater(metrics["Scenario A Equity IRR - Levered"], metrics["Scenario A Equity IRR - Unlevered"])
        self.assertGreater(metrics["Scenario A Equity IRR - Unlevered"], 0)

    def test_scenario_a_page_columns_exclude_waterfall_details(self):
        schedule, _tranche_summary, _metrics = project_rmbs_waterfall(RmbsInputs())
        table = warehouse_table(schedule)

        self.assertIn("Facility Beginning Balance", SCENARIO_A_COLUMNS)
        self.assertIn("Scenario A Levered Equity Cashflow", SCENARIO_A_COLUMNS)
        self.assertIn("Scenario A Unlevered Equity Cashflow", SCENARIO_A_COLUMNS)
        self.assertIn("Facility Beginning Balance", table.columns)
        self.assertIn("Scenario A Levered Equity Cashflow", table.columns)
        self.assertIn("Scenario A Unlevered Equity Cashflow", table.columns)
        self.assertNotIn("Admin Fee", table.columns)
        self.assertNotIn("Warehouse Equity Cashflow", table.columns)
        self.assertNotIn("Scenario B Debt Proceeds", table.columns)
        self.assertNotIn("Bond Ending Balance", table.columns)
        self.assertNotIn("Payment Mode", table.columns)
        self.assertNotIn("Excess Spread", table.columns)
        self.assertFalse(any(col.startswith("A1 ") for col in table.columns))

    def test_warehouse_scenario_summary_excludes_tranche_fields(self):
        summary = named_warehouse_scenario_summary(RmbsInputs())

        self.assertIn("Warehouse Return", summary.columns)
        self.assertIn("Unlevered Equity IRR", summary.columns)
        self.assertIn("Breakeven Loss (%)", summary.columns)
        self.assertNotIn("First Impaired Tranche", summary.columns)
        self.assertFalse(summary.empty)

    def test_structural_facility_breakeven_matches_haircut(self):
        inputs = RmbsInputs(advance_rate_pct=85.0)
        breakeven = structural_breakeven_loss_pct(inputs)

        self.assertAlmostEqual(breakeven, 15.0)
        self.assertAlmostEqual(breakeven / 100, 1 - inputs.advance_rate_pct / 100)

    def test_advance_optimization_flags_expected_points(self):
        inputs = RmbsInputs()
        schedule, tranche_summary, metrics = project_rmbs_waterfall(inputs)
        results = build_results_object(inputs, schedule, tranche_summary, metrics)

        advance_df, optima = advance_optimization(inputs)

        self.assertEqual(optima["Lender-Optimal"], 85)
        self.assertEqual(optima["Equity-Optimal"], 92)
        self.assertIn(optima["Balanced-Optimal"], set(advance_df["Advance Rate"]))
        self.assertEqual(analysis_sanity_checks(inputs, results, advance_df, optima), [])

    def test_equity_irr_zero_point_interpolates_advance_crossing(self):
        advance_df = pd.DataFrame({
            "Advance Rate": [80.0, 81.0],
            "Equity IRR": [-0.02, 0.02],
        })

        self.assertEqual(equity_irr_zero_point_text(advance_df), "80.5% advance")

    def test_investment_report_fact_packet_uses_lender_optimal_recommendation(self):
        inputs = RmbsInputs()
        schedule, tranche_summary, metrics = project_rmbs_waterfall(inputs)
        results = build_results_object(inputs, schedule, tranche_summary, metrics)
        advance_df, optima = advance_optimization(inputs)

        facts = investment_report_fact_packet(inputs, results, advance_df, optima, full_rmbs=False)

        self.assertEqual(facts["recommendation"]["basis"], "Lender-Optimal")
        self.assertEqual(facts["recommendation"]["recommended_advance_pct"], optima["Lender-Optimal"])
        self.assertIn("evidence_boundaries", facts)

    def test_llm_report_validation_rejects_unsupported_market_slop(self):
        facts = {
            "recommendation": {
                "action": "fund",
                "recommended_advance_pct": 85,
                "levered_equity_irr": 0.07,
            }
        }

        with self.assertRaises(RuntimeError):
            validate_llm_report("FUND at 85%. This is market-standard.", facts)

    def test_sensitivity_analysis_does_not_overflow_irr_solver(self):
        inputs = RmbsInputs()

        cdr_df = cdr_sensitivity(inputs)
        attachment_df = attachment_sensitivity(inputs)

        self.assertFalse(cdr_df.empty)
        self.assertFalse(attachment_df.empty)
        self.assertIn("Senior IRR", cdr_df.columns)
        self.assertIn("XS/R Value", attachment_df.columns)

    def test_results_object_feeds_app_analysis_layer(self):
        inputs = RmbsInputs()
        schedule, tranche_summary, metrics = project_rmbs_waterfall(inputs)

        results = build_results_object(inputs, schedule, tranche_summary, metrics)

        self.assertIn("inputs", results)
        self.assertIn("collateral", results)
        self.assertIn("facility", results)
        self.assertIn("equity", results)
        self.assertIn("tranche_stack", results)
        self.assertEqual(results["inputs"]["deal_balance"], inputs.deal_balance)
        self.assertIn("scenarioA_levered_cf", results["equity"])
        self.assertIn("xs_r_strict_equity_cf", results["equity"])
        self.assertEqual(len(results["collateral"]), len(schedule))

    def test_losses_allocate_to_b_notes_before_senior_class(self):
        stressed = RmbsInputs(cdr_pct=3.0, severity_pct=35.0)
        _schedule, tranche_summary, _metrics = project_rmbs_waterfall(stressed)
        summary = tranche_summary.set_index("Class")

        b_note_losses = sum(summary.loc[f"Class {label}", "Loss Allocated"] for label in ["B-1A", "B-1B", "B-2", "B-3"])
        self.assertGreater(b_note_losses, 0)
        self.assertEqual(summary.loc["Class A-1", "Loss Allocated"], 0)
        self.assertEqual(summary.loc["XS + R Strict Equity", "Initial Balance"], 0)

    def test_excel_export_contains_formula_reference_sheet(self):
        inputs = RmbsInputs()
        schedule, tranche_summary, metrics = project_rmbs_waterfall(inputs)

        workbook = build_excel_download(inputs, schedule, tranche_summary, metrics)

        self.assertTrue(workbook.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(workbook)) as zf:
            workbook_xml = zf.read("xl/workbook.xml").decode()
            shared_strings = zf.read("xl/sharedStrings.xml").decode()
            scenario_sheet = zf.read("xl/worksheets/sheet1.xml").decode()
            helper_sheet = zf.read("xl/worksheets/sheet2.xml").decode()
        self.assertIn("Formula Reference", workbook_xml)
        self.assertIn("Tranche Cashflows", workbook_xml)
        self.assertIn('state="hidden"', workbook_xml)
        self.assertNotIn("<pane", scenario_sheet)
        self.assertIn("OBX 2026-NQM8", shared_strings)
        self.assertIn("RMBS requires tranche-level waterfall modeling", shared_strings)
        self.assertIn("PMT(", scenario_sheet)
        self.assertIn("IRR('Tranche Cashflows'", scenario_sheet)
        self.assertIn("Facility Interest Owed", shared_strings)
        self.assertIn("Survival Factor", shared_strings)
        self.assertIn("Cashflow Present Value", shared_strings)
        self.assertIn("Class A-1", shared_strings)
        self.assertNotIn("A1A Beginning Balance", shared_strings)
        self.assertIn("XS/R Equity Cashflow", shared_strings)
        self.assertIn("Scenario A Levered Equity Cashflow", shared_strings)
        self.assertIn("Scenario A Unlevered Equity Cashflow", shared_strings)
        self.assertIn("MAX(", helper_sheet)

    def test_warehouse_excel_export_is_formula_linked(self):
        inputs = RmbsInputs()
        schedule, _tranche_summary, metrics = project_rmbs_waterfall(inputs)

        workbook = build_warehouse_excel_download(inputs, schedule, metrics)

        self.assertTrue(workbook.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(workbook)) as zf:
            workbook_xml = zf.read("xl/workbook.xml").decode()
            shared_strings = zf.read("xl/sharedStrings.xml").decode()
            scenario_sheet = zf.read("xl/worksheets/sheet1.xml")
        formulas = sheet_formulas(scenario_sheet)

        self.assertNotIn("Scenario A Cashflows", workbook_xml)
        self.assertNotIn('state="hidden"', workbook_xml)
        self.assertNotIn(b"<pane", scenario_sheet)
        self.assertNotIn("Admin Fee", shared_strings)
        self.assertIn("Scenario A Levered Equity Cashflow", shared_strings)
        self.assertIn("Scenario A Unlevered Equity Cashflow", shared_strings)
        self.assertEqual(formulas["B8"], "1-(1-$B$7)^(1/12)")
        self.assertEqual(formulas["B10"], "1-(1-$B$9)^(1/12)")
        self.assertEqual(formulas["B12"], "1-$B$11")
        self.assertEqual(formulas["I5"], "$I$3+$I$4")
        self.assertEqual(formulas["I7"], "$B$3*$I$6")
        self.assertEqual(formulas["I8"], "$B$3-$I$7")
        self.assertEqual(formulas["P4"], "SUM(Y26:Y383)")
        self.assertIn("LET(cf,_xlfn.VSTACK(-($B$3-$I$7),AL26:AL383)", formulas["P13"])
        self.assertIn("IFERROR(IRR(cf,0.005)", formulas["P13"])
        self.assertIn("IFERROR(IRR(cf,-0.005)", formulas["P13"])
        self.assertTrue(formulas["P13"].endswith("r*12)"))
        self.assertIn("LET(cf,_xlfn.VSTACK(-$B$3,AM26:AM383)", formulas["P14"])
        self.assertIn("NA()", formulas["P14"])
        self.assertEqual(formulas["P15"], "$P$13-$P$14")
        self.assertEqual(formulas["A26"], "1")
        self.assertEqual(formulas["D26"], "PMT($B$4/12,$B$5,-$B$3)")

    def test_excel_export_uses_correct_base_row_formulas(self):
        inputs = RmbsInputs()
        schedule, tranche_summary, metrics = project_rmbs_waterfall(inputs)

        workbook = build_excel_download(inputs, schedule, tranche_summary, metrics)

        with zipfile.ZipFile(BytesIO(workbook)) as zf:
            scenario_sheet = zf.read("xl/worksheets/sheet1.xml")
            helper_sheet = zf.read("xl/worksheets/sheet2.xml")
            shared_strings = zf.read("xl/sharedStrings.xml").decode()
        formulas = sheet_formulas(scenario_sheet)
        helper_formulas = sheet_formulas(helper_sheet)

        self.assertIn("Scenario A Asset Side", shared_strings)
        self.assertIn("Scenario A Equity", shared_strings)
        self.assertIn("Scenario A Equity — Levered", shared_strings)
        self.assertIn("Scenario A Equity — Unlevered", shared_strings)
        self.assertIn("Scenario B Debt", shared_strings)
        self.assertIn("Scenario B Equity", shared_strings)
        self.assertIn("pre-securitization", shared_strings)
        formula_values = set(formulas.values())
        self.assertIn("MIN(MAX(D58-E58,0),C58)", formula_values)
        self.assertIn("W58*$B$14/12", formula_values)
        self.assertIn("W58*$B$15/12", formula_values)
        self.assertEqual(formulas["AR58"], "MAX(J58-AH58,0)")
        self.assertEqual(formulas["AS58"], "AA58-AM58")
        self.assertEqual(formulas["AT58"], "MAX(AF58-AN58,0)")
        self.assertEqual(formulas["AU58"], "IFERROR(AS58*12/AR58,0)")
        self.assertEqual(formulas["AV58"], "J58")
        self.assertEqual(formulas["AW58"], "AA58-O58-P58")
        self.assertEqual(formulas["AX58"], "AF58")
        self.assertEqual(formulas["AY58"], "IFERROR(AW58*12/AV58,0)")
        self.assertIn("LET(cf,'Tranche Cashflows'!U2:U360", formulas["P22"])
        self.assertIn("IFERROR(IRR(cf,0.005)", formulas["P22"])
        self.assertIn("NA()", formulas["P22"])
        self.assertTrue(formulas["P22"].endswith("r*12)"))
        self.assertIn("LET(cf,'Tranche Cashflows'!V2:V360", formulas["P23"])
        self.assertIn("IFERROR(IRR(cf,-0.005)", formulas["P23"])
        self.assertIn("NA()", formulas["P23"])
        self.assertEqual(helper_formulas["U2"], "-('RMBS Scenario'!$B$3-'RMBS Scenario'!$W$7)")
        self.assertEqual(helper_formulas["V2"], "-'RMBS Scenario'!$B$3")
        self.assertEqual(helper_formulas["U3"], "'RMBS Scenario'!AS58")
        self.assertEqual(helper_formulas["V3"], "'RMBS Scenario'!AW58")
        self.assertIn(
            "MAX(AC58-(BH58+BM58+BR58+BW58+CB58+CG58+CL58+CQ58+CV58),0)",
            formula_values,
        )
        self.assertIn(
            "MIN(MAX((MAX(BQ58-BT58,0))*$AD$18/12+'Tranche Cashflows'!N2,0),MAX(AC58-(BH58+BM58),0))",
            formula_values,
        )
        self.assertEqual(formulas["BB58"], "$B$3*$AD$7+$B$3*$AD$8+$B$3*$AD$9+$B$3*$AD$10+$B$3*$AD$11+$B$3*$AD$12+$B$3*$AD$13+$B$3*$AD$14+$B$3*$AD$15")
        self.assertIn("MIN(CU58,MAX(T58-(0),0))", formula_values)
        self.assertIn(
            "MIN(BG58,MAX(T58-(CX58+CS58+CN58+CI58+CD58+BY58+BT58+BO58),0))",
            formula_values,
        )
        self.assertIn("SUM(DA58:DA415)", formula_values)


def sheet_formulas(sheet_xml: bytes) -> dict[str, str]:
    root = ET.fromstring(sheet_xml)
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    formulas = {}
    for cell in root.findall(".//a:c", ns):
        formula = cell.find("a:f", ns)
        if formula is not None:
            formulas[cell.attrib["r"]] = formula.text or ""
    return formulas


if __name__ == "__main__":
    unittest.main()
