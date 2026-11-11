"""Tests for the offline BW-to-Fabric snapshot control comparator."""

import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from migrate_bw_reconcile import main
from powerbi_import.bw_reconciliation import (
    BWReconciliationError,
    compare_controls,
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
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["comparison_status"], "pass")
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


if __name__ == "__main__":
    unittest.main()
