"""Tests for offline BW transformation golden-vector comparison."""

import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import localcontext
from io import StringIO
from pathlib import Path
from unittest.mock import patch

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
        fixtures = ROOT / "docs" / "fixtures"
        cls.conversion_vectors = json.loads(
            (fixtures / "sap_bw_conversion_vectors.example.json").read_text(
                encoding="utf-8"
            )
        )
        cls.conversion_inventory = fixtures / "sap_bw_conversion_inventory.example.json"
        cls.conversion_plan_path = fixtures / "sap_bw_conversion_plan.example.json"
        cls.conversion_plan = json.loads(
            cls.conversion_plan_path.read_text(encoding="utf-8")
        )
        cls.conversion_definition = (
            fixtures / "sap_bw_conversion_definition.example.txt"
        )
        cls.conversion_rule_ledger = fixtures / "sap_bw_source_rules.example.json"

    def _assert_declaration_preflight_not_run(self, report):
        preflight = report["source_declaration_preflight"]
        self.assertEqual(preflight["status"], "not_run")
        self.assertEqual(preflight["source_evidence"], {
            "definition_sha256_check": "not_run",
            "plan_vs_declared_ledger": "not_run",
            "source_definition_authenticity": "not_verified",
            "ledger_source_correspondence": "not_verified",
            "source_owner_approval": "not_run",
        })

    def _source_preflight_args(
        self,
        vectors_path,
        report_path,
        definition_path=None,
        ledger_path=None,
        inventory_path=None,
        transformation_path=None,
    ):
        args = ["--vectors", str(vectors_path), "--output", str(report_path)]
        if inventory_path is not None:
            args.extend(["--inventory", str(inventory_path)])
        if transformation_path is not None:
            args.extend(["--transformation", str(transformation_path)])
        if definition_path is not None:
            args.extend(["--definition-file", str(definition_path)])
        if ledger_path is not None:
            args.extend(["--rule-ledger", str(ledger_path)])
        return args

    def _assert_preflight_cli_rejected(self, args, report_path):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            try:
                result = main(args)
            except SystemExit as error:
                self.assertEqual(error.code, 2)
            else:
                self.assertEqual(result, 2)
        self.assertFalse(report_path.exists())

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

    def test_exact_comparison_preserves_nested_json_types(self):
        examples = (
            ({"nested": [1]}, {"nested": [True]}, "type_mismatch"),
            ([{"nested": 0}], [{"nested": False}], "type_mismatch"),
            ({"nested": [1]}, {"nested": [2]}, "value_mismatch"),
            ({"nested": [1]}, {"other": [1]}, "value_mismatch"),
        )
        for expected, actual, reason in examples:
            with self.subTest(expected=expected, actual=actual):
                manifest = copy.deepcopy(self.manifest)
                case = manifest["cases"][0]
                case["expected_output"]["region"] = expected
                case["target_output"]["region"] = actual
                report = compare_transform_vectors(manifest)
                check = next(
                    item for item in report["checks"]
                    if item["case_id"] == case["case_id"] and item["field"] == "region"
                )
                self.assertEqual(check["status"], "fail")
                self.assertEqual(check["failure_reason"], reason)

    def test_tolerance_does_not_round_a_difference_above_the_limit(self):
        manifest = copy.deepcopy(self.manifest)
        case = manifest["cases"][0]
        case["expected_output"]["amount"] = "0.0"
        case["target_output"]["amount"] = "1.0000000000000000000000000001"
        manifest["rules"]["amount"] = {
            "mode": "tolerance",
            "absolute_tolerance": "1.0000000000000000000000000000",
            "relative_tolerance": "0",
        }
        with localcontext() as context:
            context.prec = 4
            report = compare_transform_vectors(manifest)
        check = next(
            item for item in report["checks"]
            if item["case_id"] == case["case_id"] and item["field"] == "amount"
        )
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["failure_reason"], "tolerance_exceeded")
        self.assertEqual(check["absolute_difference"], "1.0000000000000000000000000001")

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

    def test_conversion_plan_linkage_is_independent_of_value_comparison(self):
        report = compare_transform_vectors(
            self.conversion_vectors,
            conversion_plan=self.conversion_plan,
        )
        self.assertEqual(report["conversion_plan_linkage"], "pass")
        self.assertEqual(report["comparison_status"], "pass")
        self._assert_declaration_preflight_not_run(report)

        mismatched_values = copy.deepcopy(self.conversion_vectors)
        mismatched_values["cases"][0]["target_output"]["sale_id"] = "OTHER"
        report = compare_transform_vectors(
            mismatched_values,
            conversion_plan=self.conversion_plan,
        )
        self.assertEqual(report["conversion_plan_linkage"], "pass")
        self.assertEqual(report["comparison_status"], "fail")
        self._assert_declaration_preflight_not_run(report)

    def test_linked_plan_evaluates_supported_rules_and_normalizes_decimal_scale(self):
        manifest = copy.deepcopy(self.conversion_vectors)
        # Decimal values are compared numerically, not by their textual scale.
        first = manifest["cases"][0]
        first["expected_output"]["gross_amount"] = "120.0"
        first["target_output"]["gross_amount"] = "120.0"
        first["expected_output"]["net_amount"] = "125.0000"
        first["target_output"]["net_amount"] = "125.0000"
        first["expected_output"]["difference_amount"] = "115"
        first["target_output"]["difference_amount"] = "115"

        # Both decimal operands include a null case to verify null propagation.
        null_case = copy.deepcopy(manifest["cases"][0])
        null_case["case_id"] = "null-decimal-input"
        null_case["input"]["VenteID"] = "S-NULL"
        null_case["input"]["Montant"] = None
        null_case["input"]["Ajustement"] = "2.50"
        null_case["expected_output"].update({
            "sale_id": "S-NULL",
            "gross_amount": None,
            "net_amount": None,
            "difference_amount": None,
        })
        null_case["target_output"] = copy.deepcopy(null_case["expected_output"])
        manifest["cases"].append(null_case)

        report = compare_transform_vectors(
            manifest,
            conversion_plan=self.conversion_plan,
        )

        self.assertEqual(report["comparison_status"], "pass")
        evaluation = report["normalized_rule_evaluation"]
        self.assertEqual(evaluation["status"], "pass")
        self.assertTrue(evaluation["checks"])
        self.assertTrue(all(check["status"] == "pass" for check in evaluation["checks"]))

    def test_linked_plan_accepts_zero_decimal_input_with_excess_scale(self):
        manifest = copy.deepcopy(self.conversion_vectors)
        case = copy.deepcopy(manifest["cases"][0])
        case["case_id"] = "zero-with-excess-input-scale"
        case["input"].update({
            "VenteID": "S-ZERO",
            "Montant": "0.000",
            "Ajustement": "0.00",
            "Région": "FR",
        })
        case["expected_output"] = {
            "sale_id": "S-ZERO",
            "region": "FR",
            "gross_amount": "0.00",
            "net_amount": "0.00",
            "difference_amount": "0.00",
            "source_label": "BW",
        }
        case["target_output"] = copy.deepcopy(case["expected_output"])
        manifest["cases"] = [case]

        report = compare_transform_vectors(
            manifest,
            conversion_plan=self.conversion_plan,
        )

        self.assertEqual(report["comparison_status"], "pass")
        self.assertEqual(report["normalized_rule_evaluation"]["status"], "pass")

    def test_linked_plan_evaluation_detects_consistent_expected_and_target_mutation(self):
        manifest = copy.deepcopy(self.conversion_vectors)
        manifest["cases"][0]["expected_output"]["net_amount"] = "999.00"
        manifest["cases"][0]["target_output"]["net_amount"] = "999.00"

        report = compare_transform_vectors(
            manifest,
            conversion_plan=self.conversion_plan,
        )

        self.assertEqual(report["comparison_status"], "pass")
        evaluation = report["normalized_rule_evaluation"]
        self.assertEqual(evaluation["status"], "fail")
        mismatch = next(
            check for check in evaluation["checks"]
            if check["case_id"] == manifest["cases"][0]["case_id"]
            and check["field"] == "net_amount"
        )
        self.assertEqual(mismatch["status"], "fail")
        self.assertEqual(mismatch["failure_reason"], "plan_output_mismatch")

    def test_linked_plan_evaluation_reports_invalid_decimal_input_as_failure(self):
        manifest = copy.deepcopy(self.conversion_vectors)
        manifest["cases"][0]["input"]["Montant"] = "not-a-decimal"

        report = compare_transform_vectors(
            manifest,
            conversion_plan=self.conversion_plan,
        )

        evaluation = report["normalized_rule_evaluation"]
        self.assertEqual(evaluation["status"], "fail")
        failed_fields = {
            check["field"] for check in evaluation["checks"]
            if check["case_id"] == manifest["cases"][0]["case_id"]
            and check["status"] == "fail"
        }
        self.assertTrue(
            {"gross_amount", "net_amount", "difference_amount"} & failed_fields
        )

    def test_linked_plan_reports_which_input_values_are_checked(self):
        manifest = copy.deepcopy(self.conversion_vectors)
        plan = copy.deepcopy(self.conversion_plan)
        plan["input_columns"].append({"name": "unused_field", "spark_type": "int"})
        for case in manifest["cases"]:
            case["input"]["unused_field"] = "not_an_integer"

        report = compare_transform_vectors(manifest, conversion_plan=plan)

        evaluation = report["normalized_rule_evaluation"]
        self.assertEqual(evaluation["status"], "pass")
        self.assertEqual(evaluation["input_validation_scope"], "referenced_rule_inputs_only")

    def test_unsupported_plan_spark_type_is_explicitly_not_run(self):
        plan = copy.deepcopy(self.conversion_plan)
        next(rule for rule in plan["rules"] if rule["target"] == "gross_amount")[
            "spark_type"
        ] = "array<string>"

        report = compare_transform_vectors(
            self.conversion_vectors,
            conversion_plan=plan,
        )

        self.assertEqual(report["comparison_status"], "pass")
        self.assertEqual(report["normalized_rule_evaluation"]["status"], "not_run")

    def test_cli_fails_and_writes_report_for_plan_evaluation_mismatch(self):
        manifest = copy.deepcopy(self.conversion_vectors)
        manifest["cases"][0]["expected_output"]["net_amount"] = "999.00"
        manifest["cases"][0]["target_output"]["net_amount"] = "999.00"

        with tempfile.TemporaryDirectory() as directory:
            vectors_path = Path(directory) / "vectors.json"
            report_path = Path(directory) / "report.json"
            vectors_path.write_text(json.dumps(manifest), encoding="utf-8")
            args = [
                "--vectors", str(vectors_path),
                "--output", str(report_path),
                "--inventory", str(self.conversion_inventory),
                "--transformation", str(self.conversion_plan_path),
            ]

            with redirect_stdout(StringIO()):
                result = main(args)

            self.assertEqual(result, 1)
            self.assertTrue(report_path.is_file())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["comparison_status"], "pass")
            self.assertEqual(
                report["normalized_rule_evaluation"]["status"],
                "fail",
            )

    def test_normalized_rule_evaluation_is_not_run_without_conversion_plan(self):
        report = compare_transform_vectors(self.conversion_vectors)

        self.assertEqual(report["normalized_rule_evaluation"]["status"], "not_run")

    def test_direct_compare_rejects_mismatched_conversion_plan_identity(self):
        mutations = [
            ("transformation_object_id", "mismatched"),
            ("definition_reference", "mismatched"),
            ("definition_sha256", "0" * 64),
        ]
        for field, value in mutations:
            plan = copy.deepcopy(self.conversion_plan)
            plan[field] = value
            with self.subTest(field=field):
                with self.assertRaises(BWTransformValidationError):
                    compare_transform_vectors(
                        self.conversion_vectors,
                        conversion_plan=plan,
                    )

    def test_direct_compare_rejects_casefold_colliding_plan_input_names(self):
        manifest = copy.deepcopy(self.conversion_vectors)
        plan = copy.deepcopy(self.conversion_plan)
        plan["input_columns"].append(
            {"name": "venteid", "spark_type": "string"}
        )
        for case in manifest["cases"]:
            case["input"]["venteid"] = case["input"]["VenteID"]
        with self.assertRaises(BWTransformValidationError):
            compare_transform_vectors(manifest, conversion_plan=plan)

    def test_direct_compare_rejects_casefold_colliding_plan_rule_targets(self):
        manifest = copy.deepcopy(self.conversion_vectors)
        plan = copy.deepcopy(self.conversion_plan)
        plan["rules"].append({
            "source_rule_id": "RULE-CASEFOLD-COLLISION",
            "kind": "constant",
            "target": "SALE_ID",
            "spark_type": "string",
            "value": "duplicate-target",
        })
        manifest["rules"]["SALE_ID"] = {"mode": "exact"}
        for case in manifest["cases"]:
            case["expected_output"]["SALE_ID"] = "duplicate-target"
            case["target_output"]["SALE_ID"] = "duplicate-target"
        with self.assertRaises(BWTransformValidationError):
            compare_transform_vectors(manifest, conversion_plan=plan)

    def test_direct_compare_rejects_extra_or_missing_plan_output_targets(self):
        mutations = []
        extra_target = copy.deepcopy(self.conversion_plan)
        extra_target["rules"].append(
            {"source_rule_id": "RULE-EXTRA", "kind": "constant", "target": "extra"}
        )
        mutations.append(extra_target)

        missing_target = copy.deepcopy(self.conversion_plan)
        missing_target["rules"].pop()
        mutations.append(missing_target)

        for plan in mutations:
            with self.subTest(targets=[rule["target"] for rule in plan["rules"]]):
                with self.assertRaises(BWTransformValidationError):
                    compare_transform_vectors(
                        self.conversion_vectors,
                        conversion_plan=plan,
                    )

    def test_direct_compare_rejects_missing_or_extra_per_case_input_fields(self):
        mutations = []
        missing_input = copy.deepcopy(self.conversion_vectors)
        missing_input["cases"][0]["input"].pop("Montant")
        mutations.append(missing_input)

        extra_input = copy.deepcopy(self.conversion_vectors)
        extra_input["cases"][1]["input"]["Unexpected"] = "value"
        mutations.append(extra_input)

        for manifest in mutations:
            with self.subTest(input_fields=manifest["cases"][0]["input"]):
                with self.assertRaises(BWTransformValidationError):
                    compare_transform_vectors(
                        manifest,
                        conversion_plan=self.conversion_plan,
                    )

    def test_standalone_conversion_vectors_and_cli_report_linkage_not_run(self):
        report = compare_transform_vectors(self.conversion_vectors)
        self.assertEqual(report["comparison_status"], "pass")
        self.assertEqual(report["conversion_plan_linkage"], "not_run")
        self._assert_declaration_preflight_not_run(report)

        with tempfile.TemporaryDirectory() as directory:
            vectors_path = Path(directory) / "vectors.json"
            report_path = Path(directory) / "report.json"
            vectors_path.write_text(
                json.dumps(self.conversion_vectors), encoding="utf-8"
            )
            self.assertEqual(
                main(["--vectors", str(vectors_path), "--output", str(report_path)]),
                0,
            )
            cli_report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(cli_report["comparison_status"], "pass")
            self.assertEqual(cli_report["conversion_plan_linkage"], "not_run")
            self._assert_declaration_preflight_not_run(cli_report)

    def test_cli_accepts_paired_linkage_inputs_and_validates_the_full_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            vectors_path = Path(directory) / "vectors.json"
            report_path = Path(directory) / "linked-report.json"
            vectors_path.write_text(
                json.dumps(self.conversion_vectors), encoding="utf-8"
            )
            args = [
                "--vectors", str(vectors_path),
                "--output", str(report_path),
                "--inventory", str(self.conversion_inventory),
                "--transformation", str(self.conversion_plan_path),
            ]
            self.assertEqual(main(args), 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["conversion_plan_linkage"], "pass")
            self.assertEqual(report["comparison_status"], "pass")
            self._assert_declaration_preflight_not_run(report)

            invalid_plan = copy.deepcopy(self.conversion_plan)
            invalid_plan["rules"][0]["source"] = "not_an_input_column"
            invalid_plan_path = Path(directory) / "invalid-plan.json"
            invalid_plan_path.write_text(
                json.dumps(invalid_plan), encoding="utf-8"
            )
            invalid_report_path = Path(directory) / "invalid-plan-report.json"
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main([
                        "--vectors", str(vectors_path),
                        "--output", str(invalid_report_path),
                        "--inventory", str(self.conversion_inventory),
                        "--transformation", str(invalid_plan_path),
                    ]),
                    2,
                )
            self.assertFalse(invalid_report_path.exists())

    def test_cli_source_declaration_preflight_reports_bounded_evidence_only(self):
        with tempfile.TemporaryDirectory() as directory:
            vectors_path = Path(directory) / "vectors.json"
            report_path = Path(directory) / "preflight-report.json"
            vectors_path.write_text(
                json.dumps(self.conversion_vectors), encoding="utf-8"
            )
            args = self._source_preflight_args(
                vectors_path,
                report_path,
                definition_path=self.conversion_definition,
                ledger_path=self.conversion_rule_ledger,
                inventory_path=self.conversion_inventory,
                transformation_path=self.conversion_plan_path,
            )

            # A preflight may build an in-memory notebook for complete plan
            # validation, but it must never execute notebook code or Spark.
            with patch.dict(sys.modules, {"pyspark": None}), patch(
                "builtins.exec"
            ) as exec_mock:
                self.assertEqual(main(args), 0)
            exec_mock.assert_not_called()

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["source_declaration_preflight"], {
                "status": "pass",
                "source_evidence": {
                    "definition_sha256_check": "pass",
                    "plan_vs_declared_ledger": "pass",
                    "source_definition_authenticity": "not_verified",
                    "ledger_source_correspondence": "not_verified",
                    "source_owner_approval": "not_run",
                },
            })
            self.assertIn("source_declaration_preflight", report)
            self.assertEqual(
                report["source_declaration_preflight"]["status"], "pass"
            )
            self.assertIn("conversion_plan_linkage", report)
            self.assertEqual(report["conversion_plan_linkage"], "pass")
            self.assertIn("comparison_status", report)
            self.assertEqual(report["comparison_status"], "pass")
            self.assertEqual(report["runtime_evidence"], {
                "source_golden_case_execution": "not_run",
                "target_transformation_execution": "not_run",
                "business_approval": "not_run",
            })
            self.assertFalse(list(Path(directory).glob("*.ipynb")))

    def test_cli_rejects_incomplete_source_declaration_and_plan_argument_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            vectors_path = Path(directory) / "vectors.json"
            vectors_path.write_text(
                json.dumps(self.conversion_vectors), encoding="utf-8"
            )

            invalid_pairs = (
                ("definition-file-without-ledger", {
                    "definition_path": self.conversion_definition,
                    "inventory_path": self.conversion_inventory,
                    "transformation_path": self.conversion_plan_path,
                }),
                ("ledger-without-definition-file", {
                    "ledger_path": self.conversion_rule_ledger,
                    "inventory_path": self.conversion_inventory,
                    "transformation_path": self.conversion_plan_path,
                }),
                ("definition-file-alone", {
                    "definition_path": self.conversion_definition,
                }),
                ("ledger-alone", {
                    "ledger_path": self.conversion_rule_ledger,
                }),
                ("declarations-without-plan", {
                    "definition_path": self.conversion_definition,
                    "ledger_path": self.conversion_rule_ledger,
                }),
                ("declarations-with-inventory-only", {
                    "definition_path": self.conversion_definition,
                    "ledger_path": self.conversion_rule_ledger,
                    "inventory_path": self.conversion_inventory,
                }),
                ("declarations-with-transformation-only", {
                    "definition_path": self.conversion_definition,
                    "ledger_path": self.conversion_rule_ledger,
                    "transformation_path": self.conversion_plan_path,
                }),
            )
            for name, options in invalid_pairs:
                with self.subTest(case=name):
                    report_path = Path(directory) / f"{name}.json"
                    args = self._source_preflight_args(
                        vectors_path, report_path, **options
                    )
                    self._assert_preflight_cli_rejected(args, report_path)

    def test_cli_does_not_create_report_on_source_declaration_preflight_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            vectors_path = Path(directory) / "vectors.json"
            vectors_path.write_text(
                json.dumps(self.conversion_vectors), encoding="utf-8"
            )
            changed_definition = Path(directory) / "changed-definition.txt"
            changed_definition.write_bytes(
                self.conversion_definition.read_bytes() + b"\nchanged"
            )
            changed_ledger = copy.deepcopy(
                json.loads(self.conversion_rule_ledger.read_text(encoding="utf-8"))
            )
            changed_ledger["rules"][0]["mapping"]["source"] = "NotAVectorColumn"
            changed_ledger_path = Path(directory) / "changed-ledger.json"
            changed_ledger_path.write_text(
                json.dumps(changed_ledger), encoding="utf-8"
            )
            invalid_plan = copy.deepcopy(self.conversion_plan)
            invalid_plan["rules"][0]["source"] = "NotAPlanColumn"
            invalid_plan_path = Path(directory) / "invalid-plan.json"
            invalid_plan_path.write_text(
                json.dumps(invalid_plan), encoding="utf-8"
            )
            malformed_ledger_path = Path(directory) / "malformed-ledger.json"
            malformed_ledger_path.write_text('{"schema_version":', encoding="utf-8")
            missing_definition = Path(directory) / "missing-definition.txt"
            invalid_inventory_path = Path(directory) / "invalid-inventory.json"
            invalid_inventory_path.write_text("{}", encoding="utf-8")

            invalid_preflights = (
                ("changed-definition-bytes", changed_definition, self.conversion_rule_ledger,
                 self.conversion_plan_path, self.conversion_inventory),
                ("changed-ledger", self.conversion_definition, changed_ledger_path,
                 self.conversion_plan_path, self.conversion_inventory),
                ("invalid-plan", self.conversion_definition, self.conversion_rule_ledger,
                 invalid_plan_path, self.conversion_inventory),
                ("malformed-ledger", self.conversion_definition, malformed_ledger_path,
                 self.conversion_plan_path, self.conversion_inventory),
                ("unreadable-definition", missing_definition, self.conversion_rule_ledger,
                 self.conversion_plan_path, self.conversion_inventory),
                ("invalid-inventory", self.conversion_definition, self.conversion_rule_ledger,
                 self.conversion_plan_path, invalid_inventory_path),
            )
            for name, definition_path, ledger_path, transformation_path, inventory_path in invalid_preflights:
                with self.subTest(case=name):
                    report_path = Path(directory) / f"{name}-report.json"
                    args = self._source_preflight_args(
                        vectors_path,
                        report_path,
                        definition_path=definition_path,
                        ledger_path=ledger_path,
                        inventory_path=inventory_path,
                        transformation_path=transformation_path,
                    )
                    self._assert_preflight_cli_rejected(args, report_path)
                    self.assertFalse(
                        list(Path(directory).glob(f"{name}*.ipynb"))
                    )

    def test_cli_rejects_unpaired_linkage_options(self):
        with tempfile.TemporaryDirectory() as directory:
            vectors_path = Path(directory) / "vectors.json"
            vectors_path.write_text(
                json.dumps(self.conversion_vectors), encoding="utf-8"
            )
            for option, value in (
                ("--inventory", str(self.conversion_inventory)),
                ("--transformation", str(self.conversion_plan_path)),
            ):
                report_path = Path(directory) / f"{option[2:]}-unpaired.json"
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as exc:
                    main([
                        "--vectors", str(vectors_path),
                        "--output", str(report_path),
                        option, value,
                    ])
                self.assertEqual(exc.exception.code, 2)
                self.assertFalse(report_path.exists())

    def test_cli_does_not_create_report_when_conversion_linkage_mismatches(self):
        with tempfile.TemporaryDirectory() as directory:
            mismatched = copy.deepcopy(self.conversion_vectors)
            mismatched["transformation"]["object_id"] = "DIFFERENT-OBJECT"
            vectors_path = Path(directory) / "mismatched-vectors.json"
            vectors_path.write_text(json.dumps(mismatched), encoding="utf-8")
            report_path = Path(directory) / "report.json"
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main([
                    "--vectors", str(vectors_path),
                    "--output", str(report_path),
                    "--inventory", str(self.conversion_inventory),
                    "--transformation", str(self.conversion_plan_path),
                ])
            self.assertEqual(result, 2)
            self.assertFalse(report_path.exists())

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
