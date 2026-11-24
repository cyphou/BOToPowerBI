"""Tests for the offline BW-to-Fabric snapshot control comparator."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal, localcontext
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from migrate_bw_reconcile import main
from powerbi_import.bw_reconciliation import (
    BWReconciliationError,
    compare_bex_result_vectors,
    compare_controls,
    load_bex_result_vectors,
    load_comparison,
)

ROOT = Path(__file__).resolve().parents[1]


class TestBWReconciliation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (ROOT / "docs" / "fixtures" / "sap_bw_reconciliation.example.json")
            .read_text(encoding="utf-8")
        )

    def test_synthetic_controls_pass_and_runtime_evidence_remains_not_run(self):
        report = compare_controls(self.manifest)

        self.assertEqual(report["comparison_status"], "pass")
        self.assertEqual(report["evidence_boundary"], "declared_local_controls_only")
        self.assertEqual(report["summary"], {"controls_compared": 3, "controls_failed": 0})
        self.assertEqual(report["runtime_evidence"], {
            "sap_extraction": "not_run",
            "fabric_execution": "not_run",
            "business_approval": "not_run",
        })
        sales = next(check for check in report["checks"] if check["metric"] == "net_sales_eur")
        self.assertEqual(sales["difference"], "0.01")
        self.assertEqual(sales["allowed_difference"], "0.02")

    def test_numeric_tolerance_uses_the_larger_explicit_absolute_or_relative_limit(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["source"]["metrics"]["net_sales_eur"]["value"] = "1000"
        manifest["target"]["metrics"]["net_sales_eur"]["value"] = "1000.10"
        manifest["rules"]["net_sales_eur"] = {
            "mode": "tolerance",
            "absolute_tolerance": "0.01",
            "relative_tolerance": "0.0001",
        }
        self.assertEqual(compare_controls(manifest)["comparison_status"], "pass")

        manifest["target"]["metrics"]["net_sales_eur"]["value"] = "1000.11"
        self.assertEqual(compare_controls(manifest)["comparison_status"], "fail")

    def test_tolerances_use_exact_arithmetic_independent_of_decimal_context(self):
        manifest = copy.deepcopy(self.manifest)
        source = manifest["source"]["metrics"]["net_sales_eur"]
        target = manifest["target"]["metrics"]["net_sales_eur"]
        source["value"] = "0.0"
        target["value"] = "1.0000000000000000000000000001"
        manifest["rules"]["net_sales_eur"] = {
            "mode": "tolerance",
            "absolute_tolerance": "1.0000000000000000000000000000",
            "relative_tolerance": "0",
        }
        with localcontext() as context:
            context.prec = 4
            report = compare_controls(manifest)
        check = next(item for item in report["checks"] if item["metric"] == "net_sales_eur")
        self.assertEqual(report["comparison_status"], "fail")
        self.assertEqual(check["difference"], "1.0000000000000000000000000001")
        self.assertEqual(check["allowed_difference"], "1.0000000000000000000000000000")

        with localcontext() as context:
            context.prec = 100
            reference = Decimal("1234567890123456789012345678.9")
            relative = Decimal("0.12345678901234567890")
            boundary = reference * relative
            at_boundary = reference + boundary
            above_boundary = at_boundary + Decimal("0.00000000000000000000001")
        source["value"] = str(reference)
        manifest["rules"]["net_sales_eur"].update({
            "absolute_tolerance": "0",
            "relative_tolerance": str(relative),
        })
        with localcontext() as context:
            context.prec = 4
            target["value"] = format(at_boundary, "f")
            at_report = compare_controls(manifest)
            target["value"] = format(above_boundary, "f")
            above_report = compare_controls(manifest)
        self.assertEqual(at_report["comparison_status"], "pass")
        self.assertEqual(above_report["comparison_status"], "fail")
        check = next(item for item in above_report["checks"] if item["metric"] == "net_sales_eur")
        self.assertEqual(check["allowed_difference"], str(boundary))

    def test_exact_key_count_difference_is_reported_as_failure(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["target"]["metrics"]["distinct_key_count"]["value"] = 2
        report = compare_controls(manifest)
        self.assertEqual(report["comparison_status"], "fail")
        self.assertEqual(report["summary"]["controls_failed"], 1)

    def test_only_required_exact_counts_are_a_valid_minimal_comparison(self):
        manifest = copy.deepcopy(self.manifest)
        for side in ("source", "target"):
            manifest[side]["metrics"].pop("net_sales_eur")
        manifest["rules"].pop("net_sales_eur")
        report = compare_controls(manifest)
        self.assertEqual(report["comparison_status"], "pass")
        self.assertEqual(report["summary"]["controls_compared"], 2)

    def test_rejects_mismatched_scope_units_metrics_rules_and_unsupported_fields(self):
        mutations = []
        mismatch = copy.deepcopy(self.manifest)
        mismatch["target"]["scope"]["snapshot_id"] = "different-snapshot"
        mutations.append(mismatch)
        mismatch = copy.deepcopy(self.manifest)
        mismatch["target"]["metrics"]["net_sales_eur"]["unit"] = "USD"
        mutations.append(mismatch)
        mismatch = copy.deepcopy(self.manifest)
        mismatch["target"]["metrics"].pop("net_sales_eur")
        mutations.append(mismatch)
        mismatch = copy.deepcopy(self.manifest)
        mismatch["rules"].pop("net_sales_eur")
        mutations.append(mismatch)
        mismatch = copy.deepcopy(self.manifest)
        mismatch["source"]["unexpected"] = True
        mutations.append(mismatch)
        mismatch = copy.deepcopy(self.manifest)
        mismatch["scope"]["snapshot_cutoff_utc"] = "2026-10-31T23:59:59+01:00"
        mutations.append(mismatch)
        mismatch = copy.deepcopy(self.manifest)
        mismatch["rules"]["row_count"] = {"mode": "tolerance", "absolute_tolerance": "0", "relative_tolerance": "0"}
        mutations.append(mismatch)

        for manifest in mutations:
            with self.subTest(manifest=manifest):
                with self.assertRaises(BWReconciliationError):
                    compare_controls(manifest)

    def test_rejects_credentials_non_finite_values_and_binary_floats(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["source"]["evidence_ref"] = "token=do-not-store"
        with self.assertRaises(BWReconciliationError):
            compare_controls(manifest)

        manifest = copy.deepcopy(self.manifest)
        manifest["source"]["metrics"]["net_sales_eur"]["value"] = Decimal("NaN")
        with self.assertRaises(BWReconciliationError):
            compare_controls(manifest)

        manifest = copy.deepcopy(self.manifest)
        manifest["source"]["metrics"]["net_sales_eur"]["value"] = 1.25
        with self.assertRaises(BWReconciliationError):
            compare_controls(manifest)

        manifest = copy.deepcopy(self.manifest)
        manifest["source"]["metrics"]["net_sales_eur"]["value"] = "01.25"
        with self.assertRaises(BWReconciliationError):
            compare_controls(manifest)

    def test_loader_rejects_duplicate_keys_and_non_json_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.json"
            for content in (
                '{"schema_version":"1.0","schema_version":"1.0"}',
                '{"value":NaN}',
                '{"value":Infinity}',
            ):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content):
                    with self.assertRaises(BWReconciliationError):
                        load_comparison(path)

    def test_cli_writes_new_report_and_returns_failure_for_control_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            report_path = Path(directory) / "report.json"
            failed_path = Path(directory) / "failed.json"
            manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
            self.assertEqual(main(["--comparison", str(manifest_path), "--output", str(report_path)]), 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["comparison_status"], "pass")
            self.assertEqual(report["schema_version"], "1.0")
            self.assertNotIn("plan_linkage", report)
            self.assertNotIn("observation_requirement", report)
            self.assertEqual(main(["--comparison", str(manifest_path), "--output", str(report_path)]), 2)

            failed = copy.deepcopy(self.manifest)
            failed["target"]["metrics"]["row_count"]["value"] = 4
            failed_path_manifest = Path(directory) / "failed-manifest.json"
            failed_path_manifest.write_text(json.dumps(failed), encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(["--comparison", str(failed_path_manifest), "--output", str(failed_path)]),
                    1,
                )
            self.assertEqual(
                json.loads(failed_path.read_text(encoding="utf-8"))["comparison_status"],
                "fail",
            )


class TestBExResultVectorReconciliation(unittest.TestCase):
    fixtures = ROOT / "docs" / "fixtures"
    pilot_plan_path = fixtures / "sap_bw_bex_pilot_plan.example.json"
    pilot_inventory_path = fixtures / "sap_bw_bex_pilot_inventory.example.json"
    pilot_semantics_path = fixtures / "sap_bw_bex_pilot_semantics.example.json"
    pilot_vectors_path = fixtures / "sap_bw_bex_pilot_result_vectors.example.json"

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (ROOT / "docs" / "fixtures" / "sap_bw_bex_result_vectors.example.json")
            .read_text(encoding="utf-8")
        )

    def assert_evidence_remains_unverified(self, report):
        self.assertEqual(report["schema_version"], "1.0")
        self.assertEqual(report["runtime_evidence"], {
            "sap_execution": "not_run",
            "fabric_execution": "not_run",
            "business_approval": "not_run",
        })
        self.assertEqual(report["verification_status"], {
            "authenticity": "not_verified",
            "provenance": "not_verified",
            "source_coverage": "not_verified",
            "semantic_equivalence": "not_verified",
        })
        self.assertNotIn("plan_linkage", report)
        self.assertNotIn("observation_requirement", report)

    def _pilot_linkage_args(self, plan_path=None):
        return [
            "--plan", str(self.pilot_plan_path if plan_path is None else plan_path),
            "--inventory", str(self.pilot_inventory_path),
            "--semantics", str(self.pilot_semantics_path),
        ]

    def assert_linked_cli_refusal(self, vectors_path, report_path, diagnostic, *, plan_path=None):
        args = [
            "--bex-result-vectors", str(vectors_path),
            *self._pilot_linkage_args(plan_path),
            "--output", str(report_path),
        ]
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as stderr:
            self.assertEqual(main(args), 2, stderr.getvalue())
        self.assertIn(diagnostic, stderr.getvalue())
        self.assertFalse(report_path.exists())
        return stderr.getvalue()

    def test_synthetic_fixture_reports_missing_extra_duplicate_and_measure_tolerance(self):
        report = compare_bex_result_vectors(self.manifest)

        self.assertEqual(report["comparison_status"], "fail")
        self.assertEqual(report["evidence_boundary"], "declared_local_bex_result_vectors_only")
        self.assertEqual(report["missing_keys"], [
            {"region_key": "SOUTH", "item_key": "C-03"},
        ])
        self.assertEqual(report["extra_keys"], [
            {"region_key": "WEST", "item_key": "D-04"},
        ])
        self.assertEqual(report["duplicate_keys"], [{
            "key": {"region_key": "SOUTH", "item_key": "B-02"},
            "source_count": 1,
            "target_count": 2,
        }])
        self.assertEqual(report["summary"], {
            "source_rows": 3,
            "target_rows": 4,
            "source_distinct_keys": 3,
            "target_distinct_keys": 3,
            "missing_keys": 1,
            "extra_keys": 1,
            "duplicate_keys": 1,
            "measures_compared": 2,
            "measure_mismatches": 1,
        })
        mismatch = report["measure_mismatches"][0]
        self.assertEqual(mismatch["key"], {"region_key": "NORTH", "item_key": "A-01"})
        self.assertEqual(mismatch["measure"], "net_sales")
        self.assertEqual(mismatch["difference"], "0.05")
        self.assertEqual(mismatch["allowed_difference"], "0.02")
        self.assert_evidence_remains_unverified(report)

    def test_exact_match_pass_and_tolerance_boundary_passes_but_above_fails(self):
        exact = copy.deepcopy(self.manifest)
        exact["target"]["rows"] = copy.deepcopy(exact["source"]["rows"])
        exact_report = compare_bex_result_vectors(exact)
        self.assertEqual(exact_report["comparison_status"], "pass")
        self.assertEqual(exact_report["summary"]["measures_compared"], 6)
        self.assert_evidence_remains_unverified(exact_report)
        self.assertNotIn(
            "no_measure_observations_compared",
            exact_report["limitations"],
        )

        manifest = copy.deepcopy(exact)
        manifest["source"]["rows"] = [{
            "key": {"region_key": "R", "item_key": "I"},
            "measures": {"net_sales": "100", "units": "1"},
        }]
        manifest["target"]["rows"] = [{
            "key": {"region_key": "R", "item_key": "I"},
            "measures": {"net_sales": "100.02", "units": "1"},
        }]
        boundary = compare_bex_result_vectors(manifest)
        self.assertEqual(boundary["comparison_status"], "pass")
        self.assertEqual(boundary["checks"][0]["difference"], "0.02")
        self.assertEqual(boundary["checks"][0]["allowed_difference"], "0.02")
        self.assert_evidence_remains_unverified(boundary)

        manifest["target"]["rows"][0]["measures"]["net_sales"] = "100.0200000000000000000001"
        with localcontext() as context:
            context.prec = 3
            above_boundary = compare_bex_result_vectors(manifest)
        self.assertEqual(above_boundary["comparison_status"], "fail")
        self.assertEqual(
            above_boundary["measure_mismatches"][0]["difference"],
            "0.0200000000000000000001",
        )
        self.assert_evidence_remains_unverified(above_boundary)

    def test_zero_measure_observations_report_limitation_and_preserve_key_failures(self):
        both_empty = copy.deepcopy(self.manifest)
        both_empty["source"]["rows"] = []
        both_empty["target"]["rows"] = []

        one_empty = copy.deepcopy(self.manifest)
        one_empty["source"]["rows"] = []

        disjoint = copy.deepcopy(self.manifest)
        disjoint["source"]["rows"] = [copy.deepcopy(self.manifest["source"]["rows"][0])]
        disjoint["target"]["rows"] = [copy.deepcopy(self.manifest["target"]["rows"][0])]
        disjoint["target"]["rows"][0]["key"]["item_key"] = "DISJOINT"

        duplicate_only = copy.deepcopy(self.manifest)
        duplicate_row = copy.deepcopy(self.manifest["source"]["rows"][0])
        duplicate_only["source"]["rows"] = [
            copy.deepcopy(duplicate_row),
            copy.deepcopy(duplicate_row),
        ]
        duplicate_only["target"]["rows"] = [
            copy.deepcopy(duplicate_row),
            copy.deepcopy(duplicate_row),
        ]

        cases = (
            ("both_empty", both_empty, "pass"),
            ("one_empty", one_empty, "fail"),
            ("disjoint", disjoint, "fail"),
            ("duplicate_only", duplicate_only, "fail"),
        )
        reports = {}
        for name, manifest, expected_status in cases:
            with self.subTest(case=name):
                report = compare_bex_result_vectors(manifest)
                reports[name] = report
                self.assertEqual(report["comparison_status"], expected_status)
                self.assertEqual(report["summary"]["measures_compared"], 0)
                self.assertIn(
                    "no_measure_observations_compared",
                    report["limitations"],
                )
                self.assert_evidence_remains_unverified(report)

        self.assertEqual(reports["both_empty"]["summary"]["source_rows"], 0)
        self.assertEqual(reports["both_empty"]["summary"]["target_rows"], 0)
        self.assertEqual(reports["both_empty"]["missing_keys"], [])
        self.assertEqual(reports["both_empty"]["extra_keys"], [])
        self.assertEqual(reports["both_empty"]["duplicate_keys"], [])

        self.assertEqual(reports["one_empty"]["missing_keys"], [])
        self.assertEqual(
            reports["one_empty"]["extra_keys"],
            [
                {"region_key": "NORTH", "item_key": "A-01"},
                {"region_key": "SOUTH", "item_key": "B-02"},
                {"region_key": "WEST", "item_key": "D-04"},
            ],
        )
        self.assertEqual(reports["one_empty"]["duplicate_keys"], [{
            "key": {"region_key": "SOUTH", "item_key": "B-02"},
            "source_count": 0,
            "target_count": 2,
        }])

        self.assertEqual(
            reports["disjoint"]["missing_keys"],
            [self.manifest["source"]["rows"][0]["key"]],
        )
        self.assertEqual(
            reports["disjoint"]["extra_keys"],
            [{"region_key": "NORTH", "item_key": "DISJOINT"}],
        )

        self.assertEqual(reports["duplicate_only"]["missing_keys"], [])
        self.assertEqual(reports["duplicate_only"]["extra_keys"], [])
        self.assertEqual(reports["duplicate_only"]["duplicate_keys"], [{
            "key": duplicate_row["key"],
            "source_count": 2,
            "target_count": 2,
        }])

    def test_zero_observation_cli_pass_notices_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            manifest = copy.deepcopy(self.manifest)
            manifest["source"]["rows"] = []
            manifest["target"]["rows"] = []
            manifest_path = directory / "empty-vectors.json"
            report_path = directory / "empty-report.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable, str(ROOT / "migrate_bw_reconcile.py"),
                    "--bex-result-vectors", str(manifest_path),
                    "--output", str(report_path),
                ],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("no measure observations", completed.stdout.lower())
            self.assertIn("compared", completed.stdout.lower())
            report_bytes = report_path.read_bytes()
            report = json.loads(report_bytes)
            self.assertEqual(report["comparison_status"], "pass")
            self.assertEqual(report["summary"]["measures_compared"], 0)
            self.assertIn(
                "no_measure_observations_compared",
                report["limitations"],
            )
            self.assert_evidence_remains_unverified(report)

            existing_path = subprocess.run(
                [
                    sys.executable, str(ROOT / "migrate_bw_reconcile.py"),
                    "--bex-result-vectors", str(manifest_path),
                    "--output", str(report_path),
                ],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(existing_path.returncode, 2)
            self.assertEqual(report_path.read_bytes(), report_bytes)

    def test_relative_tolerance_comparison_is_independent_of_decimal_context(self):
        manifest = copy.deepcopy(self.manifest)
        for side in ("source", "target"):
            manifest[side]["rows"] = [{
                "key": {"region_key": "R", "item_key": "I"},
                "measures": {"net_sales": "1234567890123456789012345678.9", "units": 1},
            }]
        reference = Decimal("1234567890123456789012345678.9")
        relative = Decimal("0.12345678901234567890")
        with localcontext() as context:
            context.prec = 100
            difference = reference * relative
            boundary_target = reference + difference
            above_target = boundary_target + Decimal("0.00000000000000000000001")
        manifest["rules"]["net_sales"] = {
            "mode": "tolerance",
            "absolute_tolerance": "0",
            "relative_tolerance": str(relative),
        }
        with localcontext() as context:
            context.prec = 4
            manifest["target"]["rows"][0]["measures"]["net_sales"] = format(boundary_target, "f")
            at_boundary = compare_bex_result_vectors(manifest)
            manifest["target"]["rows"][0]["measures"]["net_sales"] = format(above_target, "f")
            above_boundary = compare_bex_result_vectors(manifest)

        self.assertEqual(at_boundary["comparison_status"], "pass")
        self.assertEqual(above_boundary["comparison_status"], "fail")
        self.assertEqual(
            above_boundary["measure_mismatches"][0]["allowed_difference"],
            str(difference),
        )
        self.assert_evidence_remains_unverified(at_boundary)
        self.assert_evidence_remains_unverified(above_boundary)

    def test_rejects_mismatched_query_scope_role_prompt_context_and_grain(self):
        mutations = []
        mismatch = copy.deepcopy(self.manifest)
        mismatch["target"]["scope"]["query_scope_id"] = "different-scope"
        mutations.append(mismatch)
        for field in ("role", "prompt_context_ref", "grain"):
            mismatch = copy.deepcopy(self.manifest)
            mismatch["target"][field] = "different-" + field
            mutations.append(mismatch)

        for manifest in mutations:
            with self.subTest(manifest=manifest):
                with self.assertRaises(BWReconciliationError):
                    compare_bex_result_vectors(manifest)

    def test_rejects_malformed_keys_measures_rules_and_credentials(self):
        mutations = []
        malformed = copy.deepcopy(self.manifest)
        malformed["source"]["rows"][0]["key"].pop("item_key")
        mutations.append(malformed)
        malformed = copy.deepcopy(self.manifest)
        malformed["source"]["rows"][0]["key"]["item_key"] = 1.5
        mutations.append(malformed)
        malformed = copy.deepcopy(self.manifest)
        malformed["source"]["rows"][0]["measures"]["net_sales"] = "01.25"
        mutations.append(malformed)
        malformed = copy.deepcopy(self.manifest)
        malformed["source"]["rows"][0]["measures"].pop("units")
        mutations.append(malformed)
        malformed = copy.deepcopy(self.manifest)
        malformed["rules"]["net_sales"]["absolute_tolerance"] = "-0.01"
        mutations.append(malformed)
        malformed = copy.deepcopy(self.manifest)
        malformed["rules"]["units"] = {"mode": "unsupported"}
        mutations.append(malformed)
        malformed = copy.deepcopy(self.manifest)
        malformed["target"]["evidence_ref"] = "token=do-not-store"
        mutations.append(malformed)

        for manifest in mutations:
            with self.subTest(manifest=manifest):
                with self.assertRaises(BWReconciliationError):
                    compare_bex_result_vectors(manifest)

    def test_bex_loader_rejects_duplicate_keys_invalid_json_and_non_json_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vectors.json"
            for content in (
                '{"schema_version":"1.0","schema_version":"1.0"}',
                '{"value":NaN}',
                '{"value":Infinity}',
                '{"value":-Infinity}',
                '{"value":',
            ):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content):
                    with self.assertRaises(BWReconciliationError):
                        load_bex_result_vectors(path)

    def test_bex_cli_pass_fail_no_overwrite_and_mutually_exclusive_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            manifest_path = directory / "vectors.json"
            passing_path = directory / "passing-report.json"
            failing_path = directory / "failing-report.json"
            manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

            failed = subprocess.run(
                [
                    sys.executable, str(ROOT / "migrate_bw_reconcile.py"),
                    "--bex-result-vectors", str(manifest_path),
                    "--output", str(failing_path),
                ],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(failed.returncode, 1, failed.stderr)
            failed_report = json.loads(failing_path.read_text(encoding="utf-8"))
            self.assertEqual(failed_report["comparison_status"], "fail")
            self.assert_evidence_remains_unverified(failed_report)

            # The fixture intentionally contains discrepancies; a clean local comparison
            # must instead return zero.
            clean_manifest = copy.deepcopy(self.manifest)
            clean_manifest["target"]["rows"] = copy.deepcopy(clean_manifest["source"]["rows"])
            manifest_path.write_text(json.dumps(clean_manifest), encoding="utf-8")
            passing = subprocess.run(
                [
                    sys.executable, str(ROOT / "migrate_bw_reconcile.py"),
                    "--bex-result-vectors", str(manifest_path),
                    "--output", str(passing_path),
                ],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(passing.returncode, 0, passing.stderr)
            passing_report = json.loads(passing_path.read_text(encoding="utf-8"))
            self.assertEqual(passing_report["comparison_status"], "pass")
            self.assert_evidence_remains_unverified(passing_report)

            overwritten = subprocess.run(
                [
                    sys.executable, str(ROOT / "migrate_bw_reconcile.py"),
                    "--bex-result-vectors", str(manifest_path),
                    "--output", str(passing_path),
                ],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(overwritten.returncode, 2)
            self.assertEqual(
                json.loads(passing_path.read_text(encoding="utf-8")),
                passing_report,
            )

            both_inputs = subprocess.run(
                [
                    sys.executable, str(ROOT / "migrate_bw_reconcile.py"),
                    "--comparison", str(manifest_path),
                    "--bex-result-vectors", str(manifest_path),
                    "--output", str(directory / "mutually-exclusive.json"),
                ],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(both_inputs.returncode, 2)

    def test_bex_cli_reconciles_linked_synthetic_pilot(self):
        plan = json.loads(self.pilot_plan_path.read_text(encoding="utf-8"))
        semantics = json.loads(self.pilot_semantics_path.read_text(encoding="utf-8"))
        inventory = json.loads(self.pilot_inventory_path.read_text(encoding="utf-8"))
        linkage = plan["bex_linkage"]
        query_id = linkage["query_id"]
        measure = "synthetic-billed-quantity"
        self.assertEqual(query_id, semantics["query"]["object_id"])
        self.assertEqual(
            [binding["key_figure_id"] for binding in linkage["key_figure_bindings"]],
            [measure],
        )
        self.assertIn(measure, {figure["id"] for figure in semantics["key_figures"]})

        expected_linkage = {
            "status": "pass",
            "evidence_boundary": "declared_local_plan_inventory_and_bex_only",
            "query_id": query_id,
            "provider_id": linkage["provider_id"],
            "cube_id": linkage["cube_id"],
            "project_name": plan["project_name"],
            "table_name": plan["datasource"]["tables"][0]["name"],
            "vector_measure_bindings": [{
                "key_figure_id": measure,
                "selector": "[Measures].[ZPILOT_QTY]",
                "column": "Quantité facturée",
            }],
            "native_infocube_identity_verification": "not_verified",
            "gate_closed": False,
        }
        mismatch = {
            "key": {"day_key": "2026-11-24"},
            "measure": measure,
            "source_value": "11",
            "target_value": "12",
            "difference": "1",
            "allowed_difference": "0",
            "status": "fail",
        }
        cases = (
            (self.pilot_vectors_path, 0, "pass", []),
            (
                self.fixtures / "sap_bw_bex_pilot_result_vectors_mismatch.example.json",
                1, "fail", [mismatch],
            ),
        )
        command = [sys.executable, str(ROOT / "migrate_bw_reconcile.py")]
        for vectors_path, returncode, status, mismatches in cases:
            with self.subTest(fixture=vectors_path.name), tempfile.TemporaryDirectory() as directory:
                vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
                report_path = Path(directory) / "report.json"
                vector_args = ["--bex-result-vectors", str(vectors_path)]
                completed = subprocess.run(
                    [*command, *vector_args, "--output", str(report_path)],
                    cwd=ROOT, capture_output=True, text=True, check=False,
                )
                self.assertEqual(completed.returncode, returncode, completed.stderr)
                report = json.loads(report_path.read_text(encoding="utf-8"))

                # The standalone report preserves the local declarations without claiming linkage.
                self.assertEqual(vectors["rules"], {measure: {"mode": "exact"}})
                self.assertEqual(report["scope"], vectors["scope"])
                for declaration in (vectors, report):
                    self.assertEqual(declaration["scope"]["query_id"], query_id)
                    self.assertEqual(declaration["source"]["object_id"], query_id)
                    self.assertEqual(declaration["source"]["system_id"], inventory["source_system"]["id"])
                    self.assertEqual(declaration["target"]["object_id"], plan["project_name"])

                self.assertEqual(report["comparison_status"], status)
                summary = report["summary"]
                self.assertEqual(summary["measures_compared"], 2)
                self.assertCountEqual(
                    [(check["key"], check["measure"]) for check in report["checks"]],
                    [({"day_key": day}, measure) for day in ("2026-11-23", "2026-11-24")],
                )
                for issue in ("missing_keys", "extra_keys", "duplicate_keys"):
                    self.assertEqual(report[issue], [], issue)
                    self.assertEqual(summary[issue], 0, issue)
                self.assertEqual(report["measure_mismatches"], mismatches)
                self.assertEqual(summary["measure_mismatches"], len(mismatches))
                self.assertEqual(report["evidence_boundary"], "declared_local_bex_result_vectors_only")
                self.assertNotIn("no_measure_observations_compared", report["limitations"])
                self.assert_evidence_remains_unverified(report)

                linked_path = Path(directory) / "linked-report.json"
                linked_args = [*vector_args, *self._pilot_linkage_args(), "--output", str(linked_path)]
                linked = subprocess.run(
                    [*command, *linked_args],
                    cwd=ROOT, capture_output=True, text=True, check=False,
                )
                self.assertEqual(linked.returncode, returncode, linked.stderr)
                self.assertIn("required measure observations: pass", linked.stdout)
                linked_bytes = linked_path.read_bytes()
                linked_report = json.loads(linked_bytes)
                self.assertEqual(linked_report, {
                    **report,
                    "schema_version": "1.1",
                    "plan_linkage": expected_linkage,
                    "observation_requirement": {"status": "pass", "minimum_measure_observations": 1},
                })
                self.assertIs(linked_report["plan_linkage"]["gate_closed"], False)

                if status == "pass":
                    with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as stderr:
                        self.assertEqual(main(linked_args), 2, stderr.getvalue())
                    self.assertIn("failed while writing the report", stderr.getvalue())
                    self.assertEqual(linked_path.read_bytes(), linked_bytes)

    def test_linked_bex_cli_requires_measure_observations(self):
        manifest = load_bex_result_vectors(self.pilot_vectors_path)
        cases = (
            ("both_empty", [], "pass"),
            ("duplicate_only", manifest["source"]["rows"][:1] * 2, "fail"),
        )
        for case, rows, status in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                vectors_path = Path(directory) / "vectors.json"
                report_path = Path(directory) / "report.json"
                vectors = copy.deepcopy(manifest)
                for side in ("source", "target"):
                    vectors[side]["rows"] = rows
                vectors_path.write_text(json.dumps(vectors), encoding="utf-8")
                with redirect_stdout(StringIO()) as stdout, redirect_stderr(StringIO()) as stderr:
                    self.assertEqual(main([
                        "--bex-result-vectors", str(vectors_path),
                        *self._pilot_linkage_args(),
                        "--output", str(report_path),
                    ]), 1, stderr.getvalue())
                self.assertIn("required measure observations: fail", stdout.getvalue())
                self.assertIn("No measure observations were compared", stdout.getvalue())
                report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(report["comparison_status"], status)
                self.assertEqual(report["plan_linkage"]["status"], "pass")
                self.assertEqual(report["observation_requirement"], {
                    "status": "fail", "minimum_measure_observations": 1,
                })
                self.assertEqual(report["checks"], [])
                self.assertEqual(report["summary"]["measures_compared"], 0)
                self.assertIn("no_measure_observations_compared", report["limitations"])

    def test_linked_bex_cli_rejects_vector_linkage_mismatches(self):
        manifest = load_bex_result_vectors(self.pilot_vectors_path)
        cases = (
            ("scope", "query_id"),
            ("source", "object_id"),
            ("source", "system_id"),
            ("target", "object_id"),
            ("rules", None),
        )
        for section, field in cases:
            path = f"$.{section}" if field is None else f"$.{section}.{field}"
            with self.subTest(path=path), tempfile.TemporaryDirectory() as directory:
                vectors = copy.deepcopy(manifest)
                if field is None:
                    measure = next(iter(vectors["rules"]))
                    caption = "Synthetic billed quantity"
                    vectors["rules"][caption] = vectors["rules"].pop(measure)
                    for side in ("source", "target"):
                        for row in vectors[side]["rows"]:
                            row["measures"][caption] = row["measures"].pop(measure)
                else:
                    vectors[section][field] = "unrelated-id"
                    if section == "scope":
                        for side in ("source", "target"):
                            vectors[side]["scope"] = vectors["scope"].copy()
                self.assertEqual(compare_bex_result_vectors(vectors)["comparison_status"], "pass")
                vectors_path = Path(directory) / "vectors.json"
                vectors_path.write_text(json.dumps(vectors), encoding="utf-8")
                self.assert_linked_cli_refusal(
                    vectors_path, Path(directory) / "report.json", f"at {path}:",
                )

    def test_linked_bex_cli_requires_trio_with_vectors(self):
        linkage_args = self._pilot_linkage_args()
        vector_args = ["--bex-result-vectors", str(self.pilot_vectors_path)]
        cases = (
            ("missing-plan", [*vector_args, *linkage_args[2:]], "must be supplied together"),
            ("missing-semantics", [*vector_args, *linkage_args[:-2]], "must be supplied together"),
            ("controls", [
                "--comparison", str(self.fixtures / "sap_bw_reconciliation.example.json"),
                *linkage_args,
            ], "require --bex-result-vectors"),
        )
        with tempfile.TemporaryDirectory() as directory:
            for case, args, diagnostic in cases:
                with self.subTest(case=case), redirect_stderr(StringIO()) as stderr:
                    report_path = Path(directory) / f"{case}-report.json"
                    with self.assertRaises(SystemExit) as raised:
                        main([*args, "--output", str(report_path)])
                    self.assertEqual(raised.exception.code, 2)
                    self.assertIn(f"--plan, --inventory and --semantics {diagnostic}.", stderr.getvalue())
                    self.assertFalse(report_path.exists())

    def test_linked_bex_cli_reuses_plan_validation(self):
        plan = json.loads(self.pilot_plan_path.read_text(encoding="utf-8"))
        plan["datasource"]["connection"]["client_id"] = "001"
        with tempfile.TemporaryDirectory() as directory:
            wrong_client = Path(directory) / "wrong-client.json"
            wrong_client.write_text(json.dumps(plan), encoding="utf-8")
            cases = (
                (wrong_client, "$.datasource.connection.client_id does not match the BW inventory source client"),
                (
                    self.fixtures / "sap_bw_bex_pbip_plan.example.json",
                    "BEx linkage is required when BW-5 inputs are supplied",
                ),
            )
            for plan_path, diagnostic in cases:
                with self.subTest(plan=plan_path.name):
                    self.assert_linked_cli_refusal(
                        self.pilot_vectors_path, Path(directory) / f"{plan_path.stem}-report.json",
                        diagnostic, plan_path=plan_path,
                    )

    def test_linked_bex_cli_rejects_unsafe_plan_json(self):
        plan = self.pilot_plan_path.read_text(encoding="utf-8")
        client = '"client_id": "000"'
        json_error = "Unable to load valid local linked BW cube plan JSON."
        credential_error = "Credential-like content is not allowed in the linked BW cube plan."
        table_sentinel, figure_sentinel = "FAKE-TABLE", "FAKE-FIGURE"
        cases = (
            # A last-value-wins loader would keep the valid client.
            ("duplicate_client", client, f'"client_id": "001", {client}', json_error),
            ("non_json_constant", client, '"client_id": NaN', json_error),
            (
                "table_name", '"name": "Ventes d\'été"',
                f'"name": "password={table_sentinel}"', credential_error,
            ),
            (
                "key_figure_id", '"key_figure_id": "synthetic-billed-quantity"',
                f'"key_figure_id": "token={figure_sentinel}"', credential_error,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for case, original, replacement, diagnostic in cases:
                with self.subTest(case=case):
                    self.assertEqual(plan.count(original), 1)
                    plan_path = directory / f"{case}.json"
                    plan_path.write_text(plan.replace(original, replacement, 1), encoding="utf-8")
                    stderr = self.assert_linked_cli_refusal(
                        self.pilot_vectors_path, directory / f"{case}-report.json",
                        diagnostic, plan_path=plan_path,
                    )
                    self.assertNotIn(table_sentinel, stderr)
                    self.assertNotIn(figure_sentinel, stderr)


if __name__ == "__main__":
    unittest.main()
