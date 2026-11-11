"""Tests for offline BW transformation golden-vector comparison."""

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

from migrate_bw_transform_validate import main
from powerbi_import.bw_transform_validation import (
    BWTransformValidationError,
    compare_transform_vectors,
    load_transform_vectors,
)


ROOT = Path(__file__).resolve().parents[1]


class TestBWTransformValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (
                ROOT / "docs" / "fixtures" / "sap_bw_transform_vectors.example.json"
            ).read_text(encoding="utf-8")
        )

    def test_synthetic_vectors_pass_with_explicit_tolerance_and_runtime_boundaries(self):
        report = compare_transform_vectors(self.manifest)

        self.assertEqual(report["comparison_status"], "pass")
        self.assertEqual(report["evidence_boundary"], "declared_local_test_vectors_only")
        self.assertEqual(report["summary"], {
            "cases_compared": 2,
            "field_checks": 6,
            "failed_checks": 0,
            "cases_failed": 0,
        })
        amount = next(
            check for check in report["checks"]
            if check["case_id"] == "gross-sales-with-rounding"
            and check["field"] == "amount"
        )
        self.assertEqual(amount["absolute_difference"], "0.005")
        self.assertEqual(amount["allowed_difference"], "0.012000")
        self.assertEqual(report["runtime_evidence"], {
            "source_golden_case_execution": "not_run",
            "target_transformation_execution": "not_run",
            "business_approval": "not_run",
        })

    def test_exact_type_mismatch_and_tolerance_failure_are_reported(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["cases"][0]["target_output"]["region"] = 1
        manifest["cases"][1]["target_output"]["amount"] = "-5.30"
        report = compare_transform_vectors(manifest)

        self.assertEqual(report["comparison_status"], "fail")
        self.assertEqual(report["summary"]["failed_checks"], 2)
        failures = {
            (check["case_id"], check["field"]): check["failure_reason"]
            for check in report["checks"]
            if check["status"] == "fail"
        }
        self.assertEqual(
            failures[("gross-sales-with-rounding", "region")],
            "type_mismatch",
        )
        self.assertEqual(
            failures[("null-and-negative-case", "amount")],
            "tolerance_exceeded",
        )

    def test_missing_and_unexpected_target_fields_fail(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["cases"][0]["target_output"].pop("region")
        manifest["cases"][1]["target_output"]["unmapped"] = "value"
        report = compare_transform_vectors(manifest)
        self.assertEqual(report["comparison_status"], "fail")
        reasons = {check["failure_reason"] for check in report["checks"]}
        self.assertIn("missing_target_field", reasons)
        self.assertIn("unexpected_target_field", reasons)

    def test_numeric_tolerance_does_not_hide_representation_type_mismatch(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["cases"][0]["target_output"]["amount"] = 120
        report = compare_transform_vectors(manifest)
        amount_check = next(
            check for check in report["checks"]
            if check["case_id"] == "gross-sales-with-rounding"
            and check["field"] == "amount"
        )
        self.assertEqual(amount_check["status"], "fail")
        self.assertEqual(amount_check["failure_reason"], "type_mismatch")
        self.assertEqual(amount_check["absolute_difference"], None)

    def test_rejects_duplicate_case_ids_bad_hash_and_incomplete_rules(self):
        mutations = []
        duplicate = copy.deepcopy(self.manifest)
        duplicate["cases"][1]["case_id"] = duplicate["cases"][0]["case_id"]
        mutations.append(duplicate)

        bad_hash = copy.deepcopy(self.manifest)
        bad_hash["transformation"]["definition_sha256"] = "not-a-hash"
        mutations.append(bad_hash)

        incomplete = copy.deepcopy(self.manifest)
        incomplete["cases"][0]["expected_output"].pop("region")
        mutations.append(incomplete)

        for manifest in mutations:
            with self.subTest(manifest=manifest):
                with self.assertRaises(BWTransformValidationError):
                    compare_transform_vectors(manifest)

    def test_rejects_negative_tolerance_secrets_and_binary_floats(self):
        mutations = []
        invalid = copy.deepcopy(self.manifest)
        invalid["rules"]["amount"]["absolute_tolerance"] = "-0.01"
        mutations.append(invalid)

        invalid = copy.deepcopy(self.manifest)
        invalid["transformation"]["definition_reference"] = "token=do-not-store"
        mutations.append(invalid)

        invalid = copy.deepcopy(self.manifest)
        invalid["cases"][0]["target_output"]["amount"] = 120.01
        mutations.append(invalid)

        for manifest in mutations:
            with self.subTest(manifest=manifest):
                with self.assertRaises(BWTransformValidationError):
                    compare_transform_vectors(manifest)

    def test_rejects_non_numeric_values_under_tolerance_rule(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["cases"][0]["target_output"]["amount"] = None
        with self.assertRaises(BWTransformValidationError):
            compare_transform_vectors(manifest)

    def test_loader_rejects_duplicate_keys_and_non_json_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vectors.json"
            for content in (
                '{"schema_version":"1.0","schema_version":"1.0"}',
                '{"value":NaN}',
                '{"value":Infinity}',
            ):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content):
                    with self.assertRaises(BWTransformValidationError):
                        load_transform_vectors(path)

    def test_cli_writes_new_report_and_returns_failure_on_vector_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "vectors.json"
            report_path = Path(directory) / "report.json"
            failed_path = Path(directory) / "failed.json"
            manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
            self.assertEqual(
                main(["--vectors", str(manifest_path), "--output", str(report_path)]),
                0,
            )
            self.assertEqual(
                json.loads(report_path.read_text(encoding="utf-8"))["comparison_status"],
                "pass",
            )
            self.assertEqual(
                main(["--vectors", str(manifest_path), "--output", str(report_path)]),
                2,
            )

            failed = copy.deepcopy(self.manifest)
            failed["cases"][1]["target_output"]["region"] = "OTHER"
            failed_manifest_path = Path(directory) / "failed-vectors.json"
            failed_manifest_path.write_text(json.dumps(failed), encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main([
                        "--vectors",
                        str(failed_manifest_path),
                        "--output",
                        str(failed_path),
                    ]),
                    1,
                )
            self.assertEqual(
                json.loads(failed_path.read_text(encoding="utf-8"))[
                    "comparison_status"
                ],
                "fail",
            )


if __name__ == "__main__":
    unittest.main()
