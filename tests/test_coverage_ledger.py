"""Contract and subprocess tests for offline coverage declarations."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from powerbi_import.coverage_ledger import (  # noqa: E402
    CoverageLedgerError,
    build_coverage_ledger,
    validate_coverage_ledger,
)

FIXTURE = ROOT / "docs" / "fixtures" / "feature_coverage_ledger.synthetic.example.json"
SCHEMA = ROOT / "docs" / "schemas" / "feature_coverage_ledger.schema.json"
CLI = ROOT / "migrate_coverage_ledger.py"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def implemented():
    manifest = fixture()
    entry = manifest["entries"][0]
    manifest["entries"] = [entry]
    entry.update({
        "declared_status": "implemented",
        "target": {
            "applicability": "applicable",
            "choice": "synthetic target",
            "object_binding": "synthetic binding",
        },
        "dependency": {"status": "none", "description": None},
        "disposition": "accepted",
        "runtime_evidence": {
            "status": "pass", "reference": "synthetic-runtime-ref",
            "check": "Declared runtime check", "command": None,
        },
    })
    return manifest


class TestCoverageLedger(unittest.TestCase):
    def test_fixture_schema_and_open_findings(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        manifest = fixture()
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0")
        self.assertEqual(set(schema["required"]), set(manifest))
        self.assertEqual(set(schema["$defs"]["entry"]["required"]), set(manifest["entries"][0]))
        report = build_coverage_ledger(manifest)
        self.assertEqual(report["report_kind"], "offline_feature_coverage_declarations")
        self.assertEqual(report["wave_id"], manifest["wave_id"])
        self.assertEqual(report["declared_status_counts"], {
            "implemented": 0, "partial": 1, "unsupported": 0, "planned": 0, "unverified": 1,
        })
        self.assertEqual(report["declared_stage_counts"], {
            "extraction": 1, "conversion": 1, "target_generation": 0,
            "reporting": 0, "remote_operations": 0,
        })
        findings = {finding["feature_id"]: finding["reasons"] for finding in report["findings"]}
        self.assertEqual(findings["synthetic-provider"], [
            "declared_partial", "manual_disposition_unresolved", "runtime_evidence_declared_not_run",
        ])
        self.assertEqual(findings["synthetic-calculation"], [
            "declared_unverified", "source_declaration_incomplete", "target_declaration_incomplete",
            "dependency_unknown", "manual_disposition_unknown", "local_evidence_declared_unknown",
            "runtime_evidence_declared_not_run",
        ])

    def test_nonimplemented_statuses_stay_open_even_with_complete_declarations(self):
        for status in ("partial", "unsupported", "planned", "unverified"):
            with self.subTest(status=status):
                manifest = implemented()
                manifest["entries"][0]["declared_status"] = status
                report = build_coverage_ledger(manifest)
                self.assertEqual(report["findings"][0]["reasons"], ["declared_" + status])
                self.assertEqual(report["declared_status_counts"][status], 1)

    def test_exact_verification_claims_are_never_upgraded_by_declarations(self):
        expected = {
            "evidence_authenticity": "not_verified",
            "evidence_freshness_and_correctness": "not_verified",
            "source_identity_and_coverage": "not_verified",
            "feature_coverage": "not_verified",
            "semantic_equivalence": "not_verified",
            "approvals": "not_verified",
            "local_evidence_execution": "not_run",
            "desktop_rendering": "not_run",
            "refresh": "not_run",
            "remote_execution": "not_run",
        }
        for stage in ("extraction", "remote_operations"):
            with self.subTest(stage=stage):
                manifest = implemented()
                manifest["entries"][0]["stage"] = stage
                report = build_coverage_ledger(manifest)
                self.assertEqual(report["findings"], [])
                self.assertEqual(report["verification"], expected)
                self.assertEqual(report["checks_performed"], [
                    {"check": "manifest_contract_validation", "status": "pass", "command": None},
                    {"check": "duplicate_source_feature_stage_check", "status": "pass", "command": None},
                ])

    def test_input_and_returned_nested_data_are_detached_and_sort_is_deterministic(self):
        manifest = fixture()
        before = copy.deepcopy(manifest)
        validate_coverage_ledger(manifest)
        first = build_coverage_ledger(manifest)
        reverse = copy.deepcopy(manifest)
        reverse["entries"].reverse()
        self.assertEqual(first, build_coverage_ledger(reverse))
        self.assertEqual(manifest, before)
        first["declared_entries"][0]["source"]["artifact_kind"] = "changed"
        first["findings"][0]["source"]["artifact_kind"] = "changed finding"
        self.assertEqual(manifest, before)
        self.assertEqual(build_coverage_ledger(manifest), build_coverage_ledger(before))

    def test_explicit_identity_sorting_and_status_counts(self):
        manifest = implemented()
        template = manifest["entries"][0]
        rows = [
            ("Synthetic kind", "v", "doc", "f", "reporting", "unverified"),
            ("synthetic kind", None, "doc", "f", "reporting", "unverified"),
            ("synthetic kind", "v", "doc-a", "f", "conversion", "planned"),
            ("synthetic kind", "v", "doc-a", "f", "extraction", "partial"),
            ("synthetic kind", "v", "doc-a", "g", "conversion", "implemented"),
            ("synthetic kind", "v", "doc-a", "g", "extraction", "partial"),
            ("synthetic kind", "v", "doc-b", "f", "extraction", "unsupported"),
        ]
        entries = []
        for kind, version, document, feature, stage, status in reversed(rows):
            entry = copy.deepcopy(template)
            entry["source"].update(artifact_kind=kind, version=version, document_id=document)
            entry.update(feature_id=feature, stage=stage, declared_status=status)
            entries.append(entry)
        manifest["entries"] = entries
        report = build_coverage_ledger(manifest)
        self.assertEqual([
            (entry["source"]["artifact_kind"], entry["source"]["version"], entry["source"]["document_id"],
             entry["feature_id"], entry["stage"], entry["declared_status"])
            for entry in report["declared_entries"]
        ], rows)
        self.assertEqual(report["declared_status_counts"], {
            "implemented": 1, "partial": 2, "unsupported": 1, "planned": 1, "unverified": 2,
        })
        self.assertEqual(report["declared_stage_counts"], {
            "extraction": 3, "conversion": 2, "target_generation": 0,
            "reporting": 2, "remote_operations": 0,
        })

    def test_duplicate_identity_and_each_distinct_identity_component(self):
        original = implemented()["entries"][0]
        for field in ("artifact_kind", "version", "document_id", "feature_id", "stage"):
            with self.subTest(distinct=field):
                other = copy.deepcopy(original)
                if field in ("artifact_kind", "version", "document_id"):
                    other["source"][field] += "-other"
                elif field == "feature_id":
                    other[field] += "-other"
                else:
                    other[field] = "conversion"
                manifest = implemented()
                manifest["entries"].append(other)
                self.assertEqual(len(build_coverage_ledger(manifest)["declared_entries"]), 2)

        duplicate = copy.deepcopy(original)
        duplicate["owner"] = "another owner"
        duplicate["source"]["provenance"] = "another provenance"
        manifest = implemented()
        manifest["entries"].append(duplicate)
        with self.assertRaisesRegex(CoverageLedgerError, "duplicate"):
            validate_coverage_ledger(manifest)

        manifest = fixture()
        unknown_identity = copy.deepcopy(manifest["entries"][1])
        unknown_identity["owner"] = "another owner"
        manifest["entries"].append(unknown_identity)
        with self.assertRaisesRegex(CoverageLedgerError, "duplicate"):
            validate_coverage_ledger(manifest)

        manifest = implemented()
        different_case = copy.deepcopy(original)
        different_case["feature_id"] = original["feature_id"].upper()
        manifest["entries"].append(different_case)
        self.assertEqual(len(build_coverage_ledger(manifest)["declared_entries"]), 2)

    def test_missing_extra_and_invalid_fields_rejected(self):
        # Paths include all nested object types and representative schema constraints.
        cases = [
            ((), "wave_id", "delete"),
            ((), "unexpected", "extra"),
            ((), "schema_version", "2.0"),
            ((), "wave_id", "  "),
            ((), "entries", []),
            (("entries", 0), "owner", "delete"),
            (("entries", 0), "feature_id", None),
            (("entries", 0), "scope", "x" * 513),
            (("entries", 0), "stage", "unknown"),
            (("entries", 0), "declared_status", "unknown"),
            (("entries", 0), "disposition", "approved"),
            (("entries", 0, "source"), "artifact_kind", None),
            (("entries", 0, "source"), "version", 1),
            (("entries", 0, "source"), "evidence_reference", "has space"),
            (("entries", 0, "source"), "provenance", "delete"),
            (("entries", 0, "target"), "applicability", None),
            (("entries", 0, "target"), "choice", "delete"),
            (("entries", 0, "dependency"), "status", "available"),
            (("entries", 0, "local_evidence"), "status", "passed"),
            (("entries", 0, "runtime_evidence"), "command", "delete"),
            (("entries", 0, "runtime_evidence"), "reference", "x" * 257),
        ]
        for path, field, value in cases:
            with self.subTest(path=path, field=field, value=value):
                manifest = fixture()
                obj = manifest
                for part in path:
                    obj = obj[part]
                if value == "delete":
                    del obj[field]
                else:
                    obj[field] = value
                with self.assertRaises(CoverageLedgerError):
                    validate_coverage_ledger(manifest)

    def test_conditional_fields_and_declared_evidence(self):
        cases = [
            ("target", {"applicability": "unknown", "choice": "target", "object_binding": None}),
            ("target", {"applicability": "not_applicable", "choice": None, "object_binding": "binding"}),
            ("dependency", {"status": "identified", "description": None}),
            ("dependency", {"status": "none", "description": "unexpected"}),
            ("dependency", {"status": "unknown", "description": "unexpected"}),
            ("local_evidence", {"status": "pass", "reference": None, "check": "check", "command": None}),
            ("local_evidence", {"status": "fail", "reference": "ref", "check": None, "command": None}),
            ("disposition", "not_applicable"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                manifest = fixture()
                manifest["entries"][0][field] = value
                with self.assertRaises(CoverageLedgerError):
                    validate_coverage_ledger(manifest)
        for disposition in ("unresolved", "resolved", "accepted"):
            with self.subTest(disposition=disposition):
                manifest = fixture()
                manifest["entries"][0].update(disposition=disposition, manual_action=None)
                with self.assertRaises(CoverageLedgerError):
                    validate_coverage_ledger(manifest)

        manifest = fixture()
        entry = manifest["entries"][0]
        entry.update(manual_action=None, disposition="not_applicable")
        entry["dependency"] = {"status": "none", "description": None}
        entry["local_evidence"] = {"status": "not_run", "reference": "plan-ref", "check": None, "command": None}
        self.assertEqual(build_coverage_ledger(manifest)["declared_status_counts"]["partial"], 1)

    def test_implemented_requires_declared_proof_and_remote_runtime_pass(self):
        for field in ("version", "document_id", "provenance", "evidence_reference"):
            with self.subTest(source_field=field):
                manifest = implemented()
                manifest["entries"][0]["source"][field] = None
                with self.assertRaises(CoverageLedgerError):
                    validate_coverage_ledger(manifest)
        for field in ("scope",):
            manifest = implemented()
            manifest["entries"][0][field] = None
            with self.assertRaises(CoverageLedgerError):
                validate_coverage_ledger(manifest)
        for field in ("choice", "object_binding"):
            with self.subTest(target_field=field):
                manifest = implemented()
                manifest["entries"][0]["target"][field] = None
                with self.assertRaises(CoverageLedgerError):
                    validate_coverage_ledger(manifest)
        manifest = implemented()
        manifest["entries"][0]["target"] = {
            "applicability": "unknown", "choice": None, "object_binding": None,
        }
        with self.assertRaises(CoverageLedgerError):
            validate_coverage_ledger(manifest)
        for status in ("not_run", "unknown", "fail"):
            with self.subTest(local_status=status):
                manifest = implemented()
                manifest["entries"][0]["local_evidence"]["status"] = status
                with self.assertRaises(CoverageLedgerError):
                    validate_coverage_ledger(manifest)
        manifest = implemented()
        manifest["entries"][0]["runtime_evidence"]["status"] = "fail"
        with self.assertRaises(CoverageLedgerError):
            validate_coverage_ledger(manifest)
        for status in ("not_run", "unknown", "fail"):
            with self.subTest(remote_status=status):
                manifest = implemented()
                manifest["entries"][0]["stage"] = "remote_operations"
                manifest["entries"][0]["runtime_evidence"]["status"] = status
                with self.assertRaises(CoverageLedgerError):
                    validate_coverage_ledger(manifest)
        manifest = implemented()
        manifest["entries"][0]["stage"] = "remote_operations"
        self.assertEqual(build_coverage_ledger(manifest)["findings"], [])
        manifest["entries"][0]["stage"] = "extraction"
        manifest["entries"][0]["target"] = {
            "applicability": "not_applicable", "choice": None, "object_binding": None,
        }
        manifest["entries"][0]["runtime_evidence"]["status"] = "not_run"
        self.assertIn("runtime_evidence_declared_not_run", build_coverage_ledger(manifest)["findings"][0]["reasons"])

    def test_not_applicable_target_is_invalid_for_implemented_target_and_remote_stages(self):
        for stage in ("target_generation", "remote_operations"):
            with self.subTest(stage=stage):
                manifest = implemented()
                entry = manifest["entries"][0]
                entry["stage"] = stage
                entry["target"] = {
                    "applicability": "not_applicable", "choice": None, "object_binding": None,
                }
                with self.assertRaisesRegex(CoverageLedgerError, r"\$\.entries\[0\]\.target\.applicability"):
                    build_coverage_ledger(manifest)
                # The restriction applies to implemented declarations, not all statuses.
                entry["declared_status"] = "partial"
                report = build_coverage_ledger(manifest)
                self.assertIn("declared_partial", report["findings"][0]["reasons"])

        for stage in ("extraction", "conversion", "reporting"):
            with self.subTest(stage=stage):
                manifest = implemented()
                manifest["entries"][0]["stage"] = stage
                manifest["entries"][0]["target"] = {
                    "applicability": "not_applicable", "choice": None, "object_binding": None,
                }
                self.assertEqual(build_coverage_ledger(manifest)["declared_status_counts"]["implemented"], 1)

    def test_implemented_remote_declared_pass_does_not_run_runtime(self):
        manifest = implemented()
        entry = manifest["entries"][0]
        entry["stage"] = "remote_operations"
        report = build_coverage_ledger(manifest)
        self.assertEqual(report["declared_entries"][0]["target"], entry["target"])
        self.assertEqual(report["declared_entries"][0]["runtime_evidence"]["status"], "pass")
        self.assertEqual(report["declared_status_counts"]["implemented"], 1)
        self.assertEqual(report["declared_stage_counts"]["remote_operations"], 1)
        self.assertEqual(report["findings"], [])
        for check in ("local_evidence_execution", "desktop_rendering", "refresh", "remote_execution"):
            self.assertEqual(report["verification"][check], "not_run")

    def test_references_and_commands_are_neither_opened_nor_executed(self):
        manifest = implemented()
        entry = manifest["entries"][0]
        entry["source"]["evidence_reference"] = "https://example.invalid/synthetic-source"
        entry["local_evidence"]["reference"] = "nonexistent-synthetic-file"
        entry["local_evidence"]["command"] = "synthetic command that must not run"
        entry["runtime_evidence"]["reference"] = "https://example.invalid/synthetic-runtime"
        entry["runtime_evidence"]["command"] = "another synthetic command"
        with (
            patch("builtins.open", side_effect=AssertionError("opened a reference")),
            patch("pathlib.Path.open", side_effect=AssertionError("opened a reference")),
            patch("urllib.request.urlopen", side_effect=AssertionError("dereferenced a URL")),
            patch("socket.create_connection", side_effect=AssertionError("opened a connection")),
            patch("subprocess.Popen", side_effect=AssertionError("executed a command")),
        ):
            report = build_coverage_ledger(manifest)
        self.assertEqual(report["declared_entries"][0]["local_evidence"]["command"],
                         "synthetic command that must not run")
        self.assertEqual(report["verification"]["evidence_authenticity"], "not_verified")


class TestCoverageLedgerCLI(unittest.TestCase):
    def run_cli(self, manifest, output):
        return subprocess.run(
            [sys.executable, str(CLI), "--manifest", str(manifest), "--output", str(output)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )

    def test_utf8_fixture_report_is_written_as_declarations(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = fixture()
            manifest["wave_id"] = "SYNTHETIC-équipe-東京"
            source = Path(directory) / "manifest.json"
            output = Path(directory) / "rapport-é.json"
            source.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            result = self.run_cli(source, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = output.read_bytes()
            self.assertIn("équipe-東京".encode("utf-8"), data)
            self.assertEqual(json.loads(data.decode("utf-8")), build_coverage_ledger(manifest))

    def test_stage_target_restriction_and_declared_remote_pass_through_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "manifest.json"
            output = root / "report.json"
            for stage in ("target_generation", "remote_operations"):
                with self.subTest(stage=stage):
                    manifest = implemented()
                    entry = manifest["entries"][0]
                    entry["stage"] = stage
                    entry["target"] = {
                        "applicability": "not_applicable", "choice": None, "object_binding": None,
                    }
                    source.write_text(json.dumps(manifest), encoding="utf-8")
                    result = self.run_cli(source, output)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(output.exists())

            manifest = implemented()
            manifest["entries"][0]["stage"] = "remote_operations"
            source.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_cli(source, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["declared_entries"][0]["runtime_evidence"]["status"], "pass")
            self.assertEqual(report["verification"]["remote_execution"], "not_run")

    def test_invalid_or_missing_manifest_does_not_create_or_replace_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canary = "SENSITIVE-CANARY-VALUE"
            invalid = fixture()
            invalid["entries"][0]["stage"] = canary
            inputs = {
                f"missing-{canary}.json": None,
                "malformed.json": '{"wave_id":"' + canary + '","schema_version":',
                "invalid.json": json.dumps(invalid),
            }
            for name, contents in inputs.items():
                with self.subTest(input=name):
                    source = root / name
                    if contents is not None:
                        source.write_text(contents, encoding="utf-8")
                    output = root / (name + ".out")
                    result = self.run_cli(source, output)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(canary, result.stdout + result.stderr)
                    self.assertFalse(output.exists())
                    original = b"existing report must remain untouched\n"
                    output.write_bytes(original)
                    result = self.run_cli(source, output)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(canary, result.stdout + result.stderr)
                    self.assertEqual(output.read_bytes(), original)

    def test_duplicate_json_keys_at_root_and_nested_levels_are_rejected_without_leaks(self):
        canary = "SENSITIVE-CANARY-VALUE"
        valid = json.dumps(fixture())
        replacements = {
            "root": ('"wave_id": "SYNTHETIC-wave"',
                     f'"wave_id": "{canary}", "wave_id": "SYNTHETIC-wave"'),
            "nested source": ('"artifact_kind": "synthetic WebI snapshot"',
                              f'"artifact_kind": "{canary}", "artifact_kind": "synthetic WebI snapshot"'),
            "nested evidence": ('"status": "pass"',
                                f'"status": "{canary}", "status": "pass"'),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, (needle, replacement) in replacements.items():
                with self.subTest(level=label):
                    self.assertIn(needle, valid)
                    duplicate = valid.replace(needle, replacement, 1)
                    # Ordinary last-key-wins parsing would produce a valid manifest.
                    self.assertEqual(json.loads(duplicate), fixture())
                    source = root / "duplicate.json"
                    source.write_text(duplicate, encoding="utf-8")
                    output = root / "output.json"
                    result = self.run_cli(source, output)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(canary, result.stdout + result.stderr)
                    self.assertFalse(output.exists())
                    original = b"existing report must remain untouched\n"
                    output.write_bytes(original)
                    result = self.run_cli(source, output)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(canary, result.stdout + result.stderr)
                    self.assertEqual(output.read_bytes(), original)
                    output.unlink()

    def test_valid_manifest_does_not_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            original = b"existing report must remain untouched\n"
            output.write_bytes(original)
            result = self.run_cli(FIXTURE, output)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
