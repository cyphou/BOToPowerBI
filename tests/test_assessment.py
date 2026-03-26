"""Tests for assessment.py (BO patterns) and validator.py (BO leak detection).

Covers Sprint 19 of Phase 4.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from powerbi_import.assessment import (
    run_assessment,
    _UNSUPPORTED_FUNCTIONS,
    _EVAL_TIMING_FUNCTIONS,
    _PARTIAL_FUNCTIONS,
    _CONTEXT_PATTERN,
    _BO_RUNNING_CALC_PATTERN,
    _FULLY_SUPPORTED_CONNECTORS,
    _PARTIALLY_SUPPORTED_CONNECTORS,
    _UNSUPPORTED_CONNECTORS,
)
from powerbi_import.validator import ArtifactValidator


# ── Assessment pattern tests ────────────────────────────────────

class TestAssessmentPatterns(unittest.TestCase):
    """Verify BO-specific regex patterns match expected BO formula syntax."""

    def test_unsupported_matches_getlocale(self):
        self.assertIsNotNone(_UNSUPPORTED_FUNCTIONS.search("GetLocale()"))

    def test_unsupported_matches_documentname(self):
        self.assertIsNotNone(_UNSUPPORTED_FUNCTIONS.search("=DocumentName()"))

    def test_unsupported_matches_promptsummary(self):
        self.assertIsNotNone(_UNSUPPORTED_FUNCTIONS.search("PromptSummary()"))

    def test_unsupported_no_false_positive(self):
        self.assertIsNone(_UNSUPPORTED_FUNCTIONS.search("SUM([Amount])"))

    def test_eval_timing_whileprinting(self):
        self.assertIsNotNone(_EVAL_TIMING_FUNCTIONS.search("WhilePrintingRecords"))

    def test_eval_timing_whilereading(self):
        self.assertIsNotNone(_EVAL_TIMING_FUNCTIONS.search("WhileReadingRecords"))

    def test_eval_timing_no_false_positive(self):
        self.assertIsNone(_EVAL_TIMING_FUNCTIONS.search("CALCULATE(SUM(x))"))

    def test_partial_matches_previous(self):
        self.assertIsNotNone(_PARTIAL_FUNCTIONS.search("Previous([Sales])"))

    def test_partial_matches_nofilter(self):
        self.assertIsNotNone(_PARTIAL_FUNCTIONS.search("NoFilter([Region])"))

    def test_partial_matches_aggregate_aware(self):
        self.assertIsNotNone(_PARTIAL_FUNCTIONS.search("@Aggregate_Aware(Sum([Revenue]))"))

    def test_context_in(self):
        self.assertIsNotNone(_CONTEXT_PATTERN.search("In([Country]; [Sales])"))

    def test_context_foreach(self):
        self.assertIsNotNone(_CONTEXT_PATTERN.search("ForEach([Product]; Sum([Revenue]))"))

    def test_context_forall(self):
        self.assertIsNotNone(_CONTEXT_PATTERN.search("ForAll([Year]; [Profit])"))

    def test_running_sum(self):
        self.assertIsNotNone(_BO_RUNNING_CALC_PATTERN.search("RunningSum([Sales])"))

    def test_running_count(self):
        self.assertIsNotNone(_BO_RUNNING_CALC_PATTERN.search("RunningCount([Orders])"))

    def test_running_no_false_positive(self):
        self.assertIsNone(_BO_RUNNING_CALC_PATTERN.search("CALCULATE(SUM(x))"))


# ── Connector tier tests ────────────────────────────────────────

class TestConnectorTiers(unittest.TestCase):
    """Verify BO connector types are in the right tiers."""

    def test_universe_fully_supported(self):
        self.assertIn("universe", _FULLY_SUPPORTED_CONNECTORS)

    def test_oracle_direct_fully_supported(self):
        self.assertIn("direct", _FULLY_SUPPORTED_CONNECTORS)

    def test_sap_hana_partially_supported(self):
        self.assertIn("sap_hana", _PARTIALLY_SUPPORTED_CONNECTORS)

    def test_sap_bw_partially_supported(self):
        self.assertIn("sap_bw", _PARTIALLY_SUPPORTED_CONNECTORS)

    def test_personal_data_unsupported(self):
        self.assertIn("personal_data_provider", _UNSUPPORTED_CONNECTORS)


# ── Assessment end-to-end ────────────────────────────────────────

class TestAssessmentE2E(unittest.TestCase):
    """End-to-end assessment with BO-shaped extracted data."""

    def _make_extracted(self, **overrides):
        base = {
            "datasources": [{"name": "Sales", "connection": {"type": "universe"},
                             "tables": [{"name": "Orders", "columns": [{"name": "Amount"}]}],
                             "relationships": []}],
            "worksheets": [{"name": "Sheet1", "chart_type": "bar"}],
            "dashboards": [],
            "calculations": [],
            "parameters": [],
            "filters": [],
            "user_filters": [],
            "actions": [],
            "stories": [],
            "sets": [], "groups": [], "bins": [],
            "hierarchies": [], "sort_orders": [],
            "custom_sql": [],
        }
        base.update(overrides)
        return base

    def test_green_score_clean_report(self):
        report = run_assessment(self._make_extracted(), workbook_name="Clean")
        self.assertEqual(report.overall_score, "GREEN")
        self.assertEqual(report.total_fail, 0)

    def test_yellow_score_partial_function(self):
        calcs = [{"name": "PrevSales", "formula": "Previous([Sales])"}]
        report = run_assessment(self._make_extracted(calculations=calcs))
        self.assertEqual(report.overall_score, "YELLOW")
        self.assertGreater(report.total_warn, 0)

    def test_red_score_unsupported_function(self):
        calcs = [{"name": "Locale", "formula": "GetLocale()"}]
        report = run_assessment(self._make_extracted(calculations=calcs))
        self.assertEqual(report.overall_score, "RED")
        self.assertGreater(report.total_fail, 0)

    def test_context_operator_detected(self):
        calcs = [{"name": "CtxSales", "formula": "In([Region]; Sum([Sales]))"}]
        report = run_assessment(self._make_extracted(calculations=calcs))
        # Context operators are INFO, not WARN/FAIL
        ctx_checks = [
            c for cat in report.categories for c in cat.checks
            if "Context operator" in c.name
        ]
        self.assertTrue(len(ctx_checks) > 0)

    def test_running_calc_detected(self):
        calcs = [{"name": "RunTotal", "formula": "RunningSum([Amount])"}]
        report = run_assessment(self._make_extracted(calculations=calcs))
        running_checks = [
            c for cat in report.categories for c in cat.checks
            if "Running calculation" in c.name
        ]
        self.assertTrue(len(running_checks) > 0)

    def test_data_prep_custom_sql(self):
        sql = [{"name": "q1", "type": "freehand_sql", "sql": "SELECT *"}]
        report = run_assessment(self._make_extracted(custom_sql=sql))
        prep_checks = [
            c for cat in report.categories for c in cat.checks
            if "Freehand SQL" in c.name
        ]
        self.assertTrue(len(prep_checks) > 0)


# ── Validator BO leak detection ──────────────────────────────────

class TestValidatorBOLeaks(unittest.TestCase):
    """Verify validator detects BO function leaks in DAX."""

    def test_sum_leak(self):
        issues = ArtifactValidator.validate_dax_formula("=Sum([Amount])")
        bo_leaks = [i for i in issues if "BO function leak" in i]
        self.assertTrue(len(bo_leaks) > 0, f"Expected BO leak, got: {issues}")

    def test_nofilter_leak(self):
        issues = ArtifactValidator.validate_dax_formula("NoFilter([Region])")
        bo_leaks = [i for i in issues if "BO function leak" in i]
        self.assertTrue(len(bo_leaks) > 0)

    def test_foreach_leak(self):
        issues = ArtifactValidator.validate_dax_formula("ForEach([Dim]; Sum([X]))")
        bo_leaks = [i for i in issues if "BO function leak" in i]
        self.assertTrue(len(bo_leaks) > 0)

    def test_forall_leak(self):
        issues = ArtifactValidator.validate_dax_formula("ForAll([Year]; [Profit])")
        bo_leaks = [i for i in issues if "BO function leak" in i]
        self.assertTrue(len(bo_leaks) > 0)

    def test_bo_field_ref_leak(self):
        issues = ArtifactValidator.validate_dax_formula("{Orders.Amount}")
        bo_leaks = [i for i in issues if "BO function leak" in i]
        self.assertTrue(len(bo_leaks) > 0)

    def test_bo_formula_ref_leak(self):
        issues = ArtifactValidator.validate_dax_formula("{@TotalRevenue}")
        bo_leaks = [i for i in issues if "BO function leak" in i]
        self.assertTrue(len(bo_leaks) > 0)

    def test_clean_dax_no_leaks(self):
        issues = ArtifactValidator.validate_dax_formula("CALCULATE(SUM([Amount]), ALL([Region]))")
        bo_leaks = [i for i in issues if "BO function leak" in i]
        self.assertEqual(len(bo_leaks), 0)

    def test_bo_parameter_ref_leak(self):
        issues = ArtifactValidator.validate_dax_formula("{?Country}")
        bo_leaks = [i for i in issues if "BO function leak" in i]
        self.assertTrue(len(bo_leaks) > 0)


# ── Validator auto-fix ───────────────────────────────────────────

class TestValidatorAutoFix(unittest.TestCase):
    """Verify auto-fix rules convert BO leaks to DAX."""

    def test_fix_sum(self):
        fixed, repairs = ArtifactValidator.auto_fix_dax_leaks("=Sum([Amount])")
        self.assertIn("SUM(", fixed)
        self.assertTrue(len(repairs) > 0)

    def test_fix_count(self):
        fixed, repairs = ArtifactValidator.auto_fix_dax_leaks("=Count([Orders])")
        self.assertIn("COUNTA(", fixed)

    def test_fix_nofilter(self):
        fixed, repairs = ArtifactValidator.auto_fix_dax_leaks("NoFilter([Region])")
        self.assertIn("ALL(", fixed)

    def test_fix_previous(self):
        fixed, repairs = ArtifactValidator.auto_fix_dax_leaks("Previous([Sales])")
        self.assertIn("EARLIER(", fixed)

    def test_fix_foreach(self):
        fixed, repairs = ArtifactValidator.auto_fix_dax_leaks("ForEach([Dim]; Sum([X]))")
        self.assertIn("SUMX(", fixed)

    def test_fix_forall(self):
        fixed, repairs = ArtifactValidator.auto_fix_dax_leaks("ForAll([Year]; [Profit])")
        self.assertIn("CALCULATE(", fixed)

    def test_clean_dax_unchanged(self):
        formula = "CALCULATE(SUM([Amount]), ALL([Region]))"
        fixed, repairs = ArtifactValidator.auto_fix_dax_leaks(formula)
        self.assertEqual(fixed, formula)
        self.assertEqual(len(repairs), 0)


# ── DAX optimizer project-level ──────────────────────────────────

class TestDaxOptimizerProject(unittest.TestCase):
    """Test DAX optimizer at formula + project level."""

    def test_optimize_isblank_coalesce(self):
        from powerbi_import.dax_optimizer import optimize_dax
        formula = "IF(ISBLANK([Sales]), 0, [Sales])"
        optimized, rules = optimize_dax(formula)
        self.assertIn("COALESCE", optimized)
        self.assertIn("isblank_coalesce", rules)

    def test_optimize_simplify_sumx(self):
        from powerbi_import.dax_optimizer import optimize_dax
        formula = "SUMX('Orders', 'Orders'[Amount])"
        optimized, rules = optimize_dax(formula)
        self.assertIn("SUM(", optimized)
        self.assertIn("simplify_sumx", rules)

    def test_optimize_project_empty_dir(self):
        import tempfile
        from powerbi_import.dax_optimizer import optimize_dax_project
        with tempfile.TemporaryDirectory() as tmpdir:
            result = optimize_dax_project(tmpdir)
            self.assertEqual(result["total_optimizations"], 0)


# ── Server assessment ────────────────────────────────────────────

class TestServerAssessment(unittest.TestCase):
    """Test server/portfolio assessment with BO data."""

    def test_compute_complexity_bo(self):
        from powerbi_import.server_assessment import _compute_complexity
        extracted = {
            "worksheets": [{"name": "S1"}, {"name": "S2"}],
            "dashboards": [],
            "calculations": [
                {"formula": "In([Region]; Sum([Sales]))"},
                {"formula": "RunningSum([Amount])"},
            ],
            "datasources": [],
            "filters": [],
            "actions": [],
            "parameters": [],
            "user_filters": [],
            "custom_sql": [],
        }
        result = _compute_complexity(extracted)
        self.assertEqual(result["visuals"], 2)
        self.assertGreater(result["lod_expressions"], 0)
        self.assertGreater(result["running_calcs"], 0)


if __name__ == "__main__":
    unittest.main()
