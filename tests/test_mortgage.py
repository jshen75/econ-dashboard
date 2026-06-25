from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import unittest

from mortgage.calculator import MortgageInputs, mdr, project_waterfall, recoveries, smm
from mortgage.page import build_excel_download


class MortgageCalculatorTests(unittest.TestCase):
    def test_input_derived_rates_follow_requested_formulas(self) -> None:
        inputs = MortgageInputs(cpr_pct=20.0, cdr_pct=5.0, severity_pct=90.0)
        _schedule, metrics = project_waterfall(inputs)

        self.assertAlmostEqual(metrics["SMM"], 1 - (1 - 0.20) ** (1 / 12))
        self.assertAlmostEqual(metrics["MDR"], 1 - (1 - 0.05) ** (1 / 12))
        self.assertAlmostEqual(metrics["Recoveries"], 0.10)
        self.assertAlmostEqual(metrics["SMM"], smm(inputs.cpr_pct))
        self.assertAlmostEqual(metrics["MDR"], mdr(inputs.cdr_pct))
        self.assertAlmostEqual(metrics["Recoveries"], recoveries(inputs.severity_pct))

    def test_asset_purchase_price_and_facility_inputs(self) -> None:
        inputs = MortgageInputs(
            collateral_notional=100_000_000,
            coupon_pct=15,
            term_months=36,
            cpr_pct=20,
            cdr_pct=5,
            severity_pct=90,
            yield_target_pct=8,
            sofr_pct=5,
            spread_pct=2.75,
            advance_rate_pct=80,
        )
        schedule, metrics = project_waterfall(inputs)

        self.assertEqual(schedule.iloc[0]["Period"], 0)
        self.assertEqual(schedule.iloc[0]["Ideal Collateral Ending Balance"], 100_000_000)
        self.assertEqual(schedule.iloc[0]["Asset Collateral Ending Balance"], 100_000_000)
        self.assertEqual(schedule.iloc[0]["Facility Ending Balance"], 80_000_000)
        self.assertAlmostEqual(
            metrics["Purchase Price ($)"],
            schedule["Cashflow Present Value"].sum(),
        )
        self.assertAlmostEqual(metrics["Facility Rate"], 0.0775)
        self.assertAlmostEqual(metrics["Initial Notional"], 80_000_000)
        self.assertAlmostEqual(
            schedule.iloc[0]["Levered Equity Cashflow"],
            metrics["Initial Notional"] - metrics["Purchase Price ($)"],
        )
        self.assertAlmostEqual(
            schedule.iloc[0]["Unlevered Equity Cashflow"],
            -metrics["Purchase Price ($)"],
        )

    def test_first_period_uses_requested_asset_and_debt_waterfall(self) -> None:
        inputs = MortgageInputs()
        schedule, metrics = project_waterfall(inputs)
        row = schedule.iloc[1]
        prior = schedule.iloc[0]

        self.assertAlmostEqual(
            row["Ideal Collateral Beginning Balance"],
            prior["Ideal Collateral Ending Balance"],
        )
        self.assertAlmostEqual(
            row["Asset Collateral Beginning Balance"],
            prior["Asset Collateral Ending Balance"],
        )
        self.assertAlmostEqual(
            row["Defaults"],
            row["Asset Collateral Beginning Balance"] * metrics["MDR"],
        )
        self.assertAlmostEqual(row["Recovery"], row["Defaults"] * metrics["Recoveries"])
        self.assertAlmostEqual(row["Net Loss"], row["Defaults"] - row["Recovery"])
        self.assertAlmostEqual(
            row["Facility Beginning Balance"],
            prior["Facility Ending Balance"],
        )
        self.assertAlmostEqual(
            row["Interest Owed"],
            row["Facility Beginning Balance"] * metrics["Facility Rate"] / 12,
        )

    def test_excel_export_contains_linked_formulas(self) -> None:
        inputs = MortgageInputs()
        schedule, metrics = project_waterfall(inputs)
        blob = build_excel_download(inputs, schedule, metrics)
        formulas = workbook_formulas(blob)

        self.assertEqual(formulas["B7"], "1-(1-$B$6)^(1/12)")
        self.assertEqual(formulas["J5"], "SUM(V17:V53)")
        self.assertEqual(formulas["J7"], "SUMPRODUCT(B17:B53,X17:X53)/SUM(X17:X53)")
        self.assertEqual(formulas["AA5"], "$AA$3+$AA$4")
        self.assertEqual(formulas["AL5"], "IRR(AI17:AI53)*12")
        self.assertEqual(formulas["D18"], "PMT($B$4/12,$B$5,-$B$3)")
        self.assertEqual(formulas["V18"], "U18/(1+$J$3/12)^A18")
        self.assertGreater(len(formulas), 1_000)


def workbook_formulas(blob: bytes) -> dict[str, str]:
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    formulas: dict[str, str] = {}
    with ZipFile(BytesIO(blob)) as workbook:
        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
    for cell in sheet.findall(".//a:c", namespace):
        formula = cell.find("a:f", namespace)
        if formula is not None:
            formulas[cell.attrib["r"]] = formula.text or ""
    return formulas


if __name__ == "__main__":
    unittest.main()
