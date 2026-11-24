"""Subprocess tests for the local synthetic BEx/InfoCube pilot."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "docs" / "fixtures"
PROJECT = "Synthetic BEx InfoCube Pilot"
MEASURE = "synthetic-billed-quantity"
INPUT_FIXTURES = {
    "plan": "sap_bw_bex_pilot_plan.example.json",
    "inventory": "sap_bw_bex_pilot_inventory.example.json",
    "semantics": "sap_bw_bex_pilot_semantics.example.json",
    "csv-mapping": "sap_bw_bex_pilot_csv_mapping.example.json",
    "source-csv": "sap_bw_bex_pilot_source.example.csv",
    "target-csv": "sap_bw_bex_pilot_target.example.csv",
}


class TestBWBExPilot(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.inputs = self.directory / "inputs"
        self.inputs.mkdir()
        self.paths = {}
        for flag, name in INPUT_FIXTURES.items():
            path = self.inputs / name
            path.write_bytes((FIXTURES / name).read_bytes())
            self.paths[flag] = path
        self.output = self.directory / "pilot"

    def _arguments(self, output=None):
        args = []
        for flag, path in self.paths.items():
            args.extend(("--" + flag, str(path)))
        return [*args, "--output-dir", str(output or self.output)]

    def _run(self, script, args, expected):
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(ROOT / script), *args],
            cwd=self.directory, capture_output=True, encoding="utf-8",
            errors="replace", check=False, timeout=120,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def _run_pilot(self, expected, output=None):
        return self._run("migrate_bw_bex_pilot.py", self._arguments(output), expected)

    def _json(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, flag, value):
        self.paths[flag].write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def _pilot_bundle_declaration(self):
        return {
            "schema_version": "1.0",
            **{flag.replace("-", "_"): path.name for flag, path in self.paths.items()},
            "output_dir": "bundle-output",
        }

    def _assert_published_evidence(self, expected_status, expected_mismatches):
        self.assertTrue(self.output.is_dir())
        for name in ("assessment.json", "reconciliation.json", "pilot_report.json", "static-quality.json"):
            self.assertTrue((self.output / name).is_file(), name)
        project = self.output / "pbip" / PROJECT
        self.assertTrue((project / (PROJECT + ".pbip")).is_file())
        self.assertFalse(any(path.name.startswith(".inputs-") for path in self.output.iterdir()))

        assessment = self._json(self.output / "assessment.json")
        comparison = self._json(self.output / "reconciliation.json")
        quality = self._json(self.output / "static-quality.json")
        pilot = self._json(self.output / "pilot_report.json")
        linkage = self._json(self.output / "pbip" / "bex_linkage_assessment.json")
        plan = self._json(self.paths["plan"])

        self.assertEqual(pilot["workflow_status"], expected_status)
        self.assertEqual(pilot["exit_code"], 0 if expected_status == "pass" else 1)
        self.assertEqual(pilot["partial_output"], expected_status != "pass")
        self.assertEqual(pilot["project_path"], "pbip/" + PROJECT)
        self.assertEqual(pilot["generation"], {"status": "pass", "exit_code": 0})
        self.assertEqual(assessment["gate_status"], "candidate_for_owner_review")
        self.assertEqual(assessment["summary"]["blockers"], 0)
        self.assertEqual(pilot["bex_assessment"]["gate_status"], assessment["gate_status"])
        self.assertEqual(pilot["bex_assessment"]["summary"], assessment["summary"])
        self.assertEqual(comparison["comparison_status"], expected_status)
        self.assertEqual(comparison["summary"]["measures_compared"], 2)
        self.assertEqual(comparison["summary"]["measure_mismatches"], expected_mismatches)
        self.assertEqual(len(comparison["measure_mismatches"]), expected_mismatches)
        self.assertEqual(comparison["observation_requirement"]["status"], "pass")
        self.assertEqual(pilot["reconciliation"]["comparison_status"], expected_status)
        self.assertEqual(pilot["reconciliation"]["summary"], comparison["summary"])
        self.assertEqual(comparison["plan_linkage"]["status"], "pass")
        self.assertEqual(comparison["plan_linkage"]["project_name"], PROJECT)
        self.assertEqual(comparison["plan_linkage"]["query_id"], plan["bex_linkage"]["query_id"])
        self.assertEqual(comparison["plan_linkage"]["provider_id"], plan["bex_linkage"]["provider_id"])
        self.assertEqual(comparison["plan_linkage"]["cube_id"], plan["bex_linkage"]["cube_id"])
        self.assertEqual(comparison["plan_linkage"]["vector_measure_bindings"], plan["bex_linkage"]["key_figure_bindings"])
        self.assertEqual(linkage["plan_linkage"], plan["bex_linkage"])
        self.assertEqual(linkage["key_figure_selection"]["selected"], [MEASURE])
        self.assertEqual(linkage["bw5_assessment"]["summary"]["blockers"], 0)
        self.assertEqual(quality["status"], "PASS")
        self.assertEqual(quality["summary"]["errors"], 0)
        self.assertEqual(quality["summary"]["warnings"], 0)
        self.assertEqual(pilot["static_quality"]["status"], "PASS")
        self.assertEqual(pilot["static_quality"]["summary"], quality["summary"])
        self.assertEqual(pilot["static_quality"]["exit_code"], 0)
        self.assertEqual(pilot["native_infocube_identity_verification"], "not_verified")
        self.assertEqual(linkage["native_infocube_identity_verification"], "not_verified")
        self.assertEqual(comparison["plan_linkage"]["native_infocube_identity_verification"], "not_verified")
        for report in (pilot, assessment):
            self.assertEqual(set(report["verification"].values()), {"not_verified"})
            self.assertEqual(set(report["runtime_evidence"].values()), {"not_run"})
        return comparison, pilot

    def _assert_direct_parity(self, comparison, expected):
        direct = self.directory / "direct-reconciliation.json"
        args = []
        for flag, path in self.paths.items():
            reconcile_flag = "bex-csv-mapping" if flag == "csv-mapping" else flag
            args.extend(("--" + reconcile_flag, str(path)))
        self._run("migrate_bw_reconcile.py", [*args, "--output", str(direct)], expected)
        self.assertEqual(self._json(direct), comparison)

    def test_synthetic_pilot_passes_and_matches_direct_reconciliation(self):
        self._run_pilot(0)
        comparison, pilot = self._assert_published_evidence("pass", 0)
        self.assertIsNone(pilot["failure_stage"])
        self._assert_direct_parity(comparison, 0)

    def test_bundle_relative_paths_match_direct_pilot(self):
        bundle = self.inputs / "bundle.json"
        bundle.write_text(
            json.dumps(self._pilot_bundle_declaration(), ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        before = {path: path.read_bytes() for path in self.inputs.iterdir()}
        bundle_output = self.inputs / "bundle-output"

        # The subprocess runs from self.directory, not the bundle's parent.
        self._run("migrate_bw_bex_pilot.py", ["--bundle", str(bundle)], 0)
        self.assertEqual(set(self.directory.iterdir()), {self.inputs})
        self.assertEqual(set(self.inputs.iterdir()), set(before) | {bundle_output})
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertTrue(bundle_output.is_dir())
        self.assertFalse(self.output.exists())

        direct_output = self.output
        self.output = bundle_output
        bundle_comparison, bundle_pilot = self._assert_published_evidence("pass", 0)
        self.assertIsNone(bundle_pilot["failure_stage"])
        self.assertEqual(len(bundle_comparison["checks"]), 2)
        self.output = direct_output

        self._run_pilot(0)
        direct_comparison, direct_pilot = self._assert_published_evidence("pass", 0)
        self.assertEqual(bundle_pilot, direct_pilot)
        self.assertEqual(bundle_comparison, direct_comparison)
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual(set(self.directory.iterdir()), {self.inputs, direct_output})
        self.assertEqual(set(self.inputs.iterdir()), set(before) | {bundle_output})

    def test_invalid_bundle_is_rejected_without_output(self):
        bundle = self.inputs / "bundle.json"
        declaration = self._pilot_bundle_declaration()
        valid = json.dumps(declaration, ensure_ascii=False, allow_nan=False)
        missing = dict(declaration)
        del missing["plan"]
        cases = {
            "duplicate key": '{"schema_version": "1.0", ' + valid[1:],
            "extra key": json.dumps({**declaration, "unexpected": "value"}, allow_nan=False),
            "missing key": json.dumps(missing, allow_nan=False),
            "wrong schema": json.dumps({**declaration, "schema_version": "2.0"}, allow_nan=False),
            "non-string path": json.dumps({**declaration, "plan": 42}, allow_nan=False),
            "non-json number": valid.replace('"schema_version": "1.0"', '"schema_version": NaN'),
        }
        for case, content in cases.items():
            with self.subTest(case=case):
                bundle.write_text(content, encoding="utf-8")
                before = {path: path.read_bytes() for path in self.inputs.iterdir()}
                self._run("migrate_bw_bex_pilot.py", ["--bundle", str(bundle)], 2)
                self.assertEqual(set(self.directory.iterdir()), {self.inputs})
                self.assertEqual(set(self.inputs.iterdir()), set(before))
                self.assertEqual({path: path.read_bytes() for path in before}, before)
                self.assertFalse((self.inputs / "bundle-output").exists())
                self.assertFalse(self.output.exists())

    def test_bundle_rejects_each_direct_argument_without_output(self):
        bundle = self.inputs / "bundle.json"
        bundle.write_text(
            json.dumps(self._pilot_bundle_declaration(), ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        before = {path: path.read_bytes() for path in self.inputs.iterdir()}
        direct = self._arguments()
        for index in range(0, len(direct), 2):
            with self.subTest(flag=direct[index]):
                self._run(
                    "migrate_bw_bex_pilot.py",
                    ["--bundle", str(bundle), *direct[index:index + 2]],
                    2,
                )
                self.assertEqual(set(self.directory.iterdir()), {self.inputs})
                self.assertEqual(set(self.inputs.iterdir()), set(before))
                self.assertEqual({path: path.read_bytes() for path in before}, before)
                self.assertFalse((self.inputs / "bundle-output").exists())
                self.assertFalse(self.output.exists())

    def test_mismatch_publishes_partial_evidence_and_matches_direct_reconciliation(self):
        target = self.paths["target-csv"]
        original = target.read_bytes()
        self.assertIn(b"11.00,2026-11-24", original)
        target.write_bytes(original.replace(b"11.00,2026-11-24", b"12.00,2026-11-24", 1))
        self._run_pilot(1)
        comparison, pilot = self._assert_published_evidence("fail", 1)
        self.assertEqual(pilot["failure_stage"], "local_checks")
        mismatch = comparison["measure_mismatches"][0]
        self.assertEqual(mismatch["key"], {"day_key": "2026-11-24"})
        self.assertEqual(mismatch["measure"], MEASURE)
        self.assertEqual((mismatch["source_value"], mismatch["target_value"]), ("11", "12.00"))
        self._assert_direct_parity(comparison, 1)

    def test_empty_captures_fail_observation_requirement_and_retain_evidence(self):
        for flag in ("source-csv", "target-csv"):
            path = self.paths[flag]
            path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
        self._run_pilot(1)
        comparison = self._json(self.output / "reconciliation.json")
        pilot = self._json(self.output / "pilot_report.json")
        self.assertEqual(comparison["comparison_status"], "pass")
        self.assertEqual(comparison["summary"]["measures_compared"], 0)
        self.assertEqual(comparison["observation_requirement"]["status"], "fail")
        self.assertEqual(pilot["workflow_status"], "fail")
        self.assertEqual(pilot["exit_code"], 1)
        self.assertIs(pilot["partial_output"], True)
        self.assertEqual(pilot["reconciliation"]["observation_requirement"]["status"], "fail")
        self.assertEqual(pilot["static_quality"]["status"], "PASS")
        self.assertTrue((self.output / "static-quality.json").is_file())
        self.assertTrue((self.output / "pbip" / PROJECT / (PROJECT + ".pbip")).is_file())
        self._assert_direct_parity(comparison, 1)

    def test_same_csv_for_both_sides_is_rejected(self):
        self.paths["target-csv"] = self.paths["source-csv"]
        self._run_pilot(2)
        self.assertFalse(self.output.exists())
        self.assertEqual(set(self.directory.iterdir()), {self.inputs})

    def test_existing_destination_and_nested_overlap_are_rejected_without_writes(self):
        self.output.mkdir()
        before = {path: path.read_bytes() for path in self.inputs.iterdir()}
        self._run_pilot(2)
        self.assertEqual(list(self.output.iterdir()), [])
        # A destination containing inputs already exists; a destination inside an
        # input file cannot have a directory parent. Both overlaps must fail closed.
        self._run_pilot(2, self.inputs)
        nested = self.paths["source-csv"] / "nested-output"
        self._run_pilot(2, nested)
        self.assertFalse(nested.exists())
        self.assertEqual({path: path.read_bytes() for path in self.inputs.iterdir()}, before)
        self.assertEqual(set(self.directory.iterdir()), {self.inputs, self.output})

    def test_malformed_declarations_and_csv_fail_preflight_without_publication(self):
        cases = (
            ("plan", b"{invalid json"),
            ("inventory", b"{invalid json"),
            ("semantics", b"{invalid json"),
            ("csv-mapping", b"{invalid json"),
            ("source-csv", b"ZPILOT_DAY,ZPILOT_QTY\n2026-11-24\n"),
            ("target-csv", b"wrong,header\n11,2026-11-24\n"),
        )
        for flag, invalid in cases:
            with self.subTest(input=flag):
                path = self.paths[flag]
                original = path.read_bytes()
                try:
                    path.write_bytes(invalid)
                    self._run_pilot(2)
                    self.assertFalse(self.output.exists())
                    self.assertEqual(set(self.directory.iterdir()), {self.inputs})
                finally:
                    path.write_bytes(original)

    def test_required_flags_and_nonempty_values_are_rejected(self):
        args = self._arguments()
        for index in range(0, len(args), 2):
            with self.subTest(flag=args[index], case="missing"):
                self._run("migrate_bw_bex_pilot.py", args[:index] + args[index + 2:], 2)
                self.assertFalse(self.output.exists())
            with self.subTest(flag=args[index], case="empty"):
                empty = args.copy()
                empty[index + 1] = " "
                self._run("migrate_bw_bex_pilot.py", empty, 2)
                self.assertFalse(self.output.exists())
        self.assertEqual(set(self.directory.iterdir()), {self.inputs})

    def test_inconsistent_linkage_declarations_fail_preflight(self):
        cases = (
            ("plan", ("bex_linkage", "query_id"), "different-query"),
            ("plan", ("bex_linkage", "provider_id"), "different-provider"),
            ("plan", ("bex_linkage", "cube_id"), "$DIFFERENT_CUBE"),
            ("inventory", ("source_system", "id"), "different-system"),
            ("semantics", ("query", "definition_sha256"), "0" * 64),
            ("csv-mapping", ("target", "object_id"), "Different Project"),
            ("csv-mapping", ("key_figure_id",), "different-measure"),
        )
        for flag, keys, value in cases:
            with self.subTest(input=flag, field=".".join(keys)):
                original = self.paths[flag].read_bytes()
                try:
                    declaration = self._json(self.paths[flag])
                    nested = declaration
                    for key in keys[:-1]:
                        nested = nested[key]
                    nested[keys[-1]] = value
                    self._write_json(flag, declaration)
                    self._run_pilot(2)
                    self.assertFalse(self.output.exists())
                    self.assertEqual(set(self.directory.iterdir()), {self.inputs})
                finally:
                    self.paths[flag].write_bytes(original)


if __name__ == "__main__":
    unittest.main()
