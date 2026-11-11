"""Tests for the offline BW-6 security, planning, and compliance assessment."""

import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from migrate_bw_controls_assess import main
from powerbi_import.bw_controls_assessment import (
    BWControlsAssessmentError,
    assess_bw_controls,
    load_controls_manifest,
    validate_controls_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_ID = "SYNTHETIC-BW-01:AUTHORIZATION:SALES"
PLANNING_ID = "SYNTHETIC-BW-01:PLANNING:FORECAST"


def _inventory():
    return json.loads(
        (ROOT / "docs" / "fixtures" / "sap_bw_inventory.partial.example.json")
        .read_text(encoding="utf-8")
    )


def _candidate_inventory():
    inventory = _inventory()
    scope = inventory["scope"]
    scope["completeness"] = "complete"
    scope["owner_signoff"] = "accepted"
    scope["known_gaps"] = []
    scope["coverage"] = {
        key: ("not_applicable" if key == "planning_writeback" else "complete")
        for key in scope["coverage"]
    }
    inventory["discovery"].update({
        "method": "source_export",
        "evidence_reference": "synthetic-owner-export",
    })
    inventory["provenance"].update({
        "discovery_method": "source_export",
        "extraction_method": "source_export",
        "evidence_reference": "synthetic-owner-export",
    })
    inventory["extraction_access"]["status"] = "granted"
    inventory["source_system"]["landscape"]["status"] = "observed"
    inventory["unknowns"] = []
    inventory["errors"] = []
    inventory["unsupported_features"] = []
    for item in inventory["objects"]:
        if item["disposition"] == "in_scope":
            item["discovery_status"] = "observed"
            item["business_owner"] = "synthetic-owner"
            if item["criticality"] == "unknown":
                item["criticality"] = "medium"
    query = next(
        item for item in inventory["objects"]
        if item["type"] == "bex_query"
    )
    query["metadata_status"] = "observed"
    query["definition"].update({
        "status": "observed",
        "reference": "synthetic://definitions/bex/ventes-mensuelles",
        "hash_algorithm": "sha256",
        "hash": "0" * 64,
    })
    query["semantics"]["status"] = "observed"
    for object_id, object_type, name in (
        (AUTHORIZATION_ID, "authorization", "Synthetic sales authorization"),
        (PLANNING_ID, "planning_process", "Synthetic forecast planning"),
    ):
        synthetic = copy.deepcopy(query)
        synthetic.update({
            "id": object_id,
            "type": object_type,
            "name": name,
            "source_reference": f"synthetic://bw/{object_type}",
        })
        inventory["objects"].append(synthetic)
    scope["coverage"]["planning_writeback"] = "complete"
    return inventory


def _manifest():
    coverage = {
        "authorization_contexts": "complete",
        "access_matrix": "complete",
        "planning_writeback": "complete",
        "audit": "complete",
        "retention": "complete",
        "privacy": "complete",
        "legal_hold": "complete",
    }
    controls = {
        "write_back": "observed",
        "locking": "observed",
        "approval_workflow": "observed",
        "separation_of_duties": "observed",
        "audit": "observed",
        "recovery": "observed",
    }
    return {
        "schema_version": "1.0",
        "scope_id": "SYNTHETIC-BW-01",
        "coverage": coverage,
        "authorization_contexts": [{
            "id": "sales-reader",
            "inventory_object_id": AUTHORIZATION_ID,
            "role_reference": "synthetic-role-reference",
            "data_scope_reference": "synthetic-sales-scope",
            "target_control_reference": "synthetic-rls-control",
            "status": "observed",
            "evidence_reference": "synthetic://evidence/authorization",
        }],
        "access_scenarios": [
            {
                "id": "sales-allow",
                "authorization_context_id": "sales-reader",
                "expectation": "allow",
                "action_reference": "synthetic-allowed-action",
                "target_control_reference": "synthetic-rls-control",
                "execution_status": "not_run",
            },
            {
                "id": "sales-deny",
                "authorization_context_id": "sales-reader",
                "expectation": "deny",
                "action_reference": "synthetic-denied-action",
                "target_control_reference": "synthetic-rls-control",
                "execution_status": "not_run",
            },
        ],
        "planning_processes": [{
            "inventory_object_id": PLANNING_ID,
            "disposition": "replacement_selected",
            "owner_reference": "synthetic-planning-owner",
            "target_solution_reference": "synthetic-planning-solution",
            "control_coverage": copy.deepcopy(controls),
            "evidence_reference": "synthetic://evidence/planning-design",
        }],
        "obligations": [
            {
                "id": f"obligation-{category}",
                "category": category,
                "inventory_object_id": None,
                "source_control_reference": f"synthetic-source-{category}",
                "target_control_reference": f"synthetic-target-{category}",
                "owner_reference": f"synthetic-owner-{category}",
                "status": "observed",
                "evidence_reference": f"synthetic://evidence/{category}",
            }
            for category in ("audit", "retention", "privacy", "legal_hold")
        ],
    }


class TestBWControlsAssessment(unittest.TestCase):
    def setUp(self):
        self.inventory = _inventory()
        self.manifest = _manifest()

    def test_partial_documented_fixture_is_open_and_runtime_stays_not_run(self):
        controls_path = ROOT / "docs" / "fixtures" / "sap_bw_controls.partial.example.json"
        manifest = load_controls_manifest(controls_path)

        report = assess_bw_controls(self.inventory, manifest)

        self.assertEqual(report["gate_status"], "open")
        self.assertFalse(report["gate_closed"])
        self.assertGreater(report["summary"]["blockers"], 0)
        self.assertEqual(report["summary"]["inventory_gate_status"], "open")
        self.assertTrue(
            all(value == "not_run" for value in report["runtime_evidence"].values())
        )

    def test_complete_synthetic_declarations_remain_candidate_only(self):
        validate_controls_manifest(self.manifest)
        report = assess_bw_controls(_candidate_inventory(), self.manifest)

        self.assertEqual(report["gate_status"], "candidate_for_owner_review")
        self.assertFalse(report["gate_closed"])
        self.assertEqual(report["summary"]["blockers"], 0)
        self.assertEqual(report["runtime_evidence"]["positive_authorization_tests"], "not_run")
        self.assertEqual(report["runtime_evidence"]["planning_workflow_execution"], "not_run")

    def test_allow_and_deny_scenarios_are_both_required_per_authorization(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["access_scenarios"].pop()

        report = assess_bw_controls(_candidate_inventory(), manifest)

        self.assertEqual(report["gate_status"], "open")
        self.assertIn(
            "access_matrix_missing_allow_or_deny_case",
            {finding["code"] for finding in report["findings"]},
        )

    def test_planning_disposition_and_control_coverage_block_unknowns(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["planning_processes"][0]["disposition"] = "blocked"
        manifest["planning_processes"][0]["control_coverage"]["locking"] = "unknown"

        report = assess_bw_controls(_candidate_inventory(), manifest)

        finding_codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("planning_process_blocked", finding_codes)
        self.assertIn("planning_control_unassessed", finding_codes)

    def test_authorization_and_planning_references_must_resolve_to_inventory_types(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["authorization_contexts"][0]["inventory_object_id"] = PLANNING_ID
        with self.assertRaises(BWControlsAssessmentError):
            assess_bw_controls(_candidate_inventory(), manifest)

        manifest = copy.deepcopy(self.manifest)
        manifest["planning_processes"][0]["inventory_object_id"] = AUTHORIZATION_ID
        with self.assertRaises(BWControlsAssessmentError):
            assess_bw_controls(_candidate_inventory(), manifest)

    def test_compliance_obligations_require_target_control_and_owner(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["obligations"][0]["target_control_reference"] = None
        manifest["obligations"][0]["owner_reference"] = None

        report = assess_bw_controls(_candidate_inventory(), manifest)

        self.assertEqual(report["gate_status"], "open")
        self.assertIn(
            "compliance_control_unreferenced",
            {finding["code"] for finding in report["findings"]},
        )

    def test_compliance_inventory_references_must_resolve(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["obligations"][0]["inventory_object_id"] = "SYNTHETIC-BW-01:UNKNOWN"

        with self.assertRaises(BWControlsAssessmentError):
            assess_bw_controls(_candidate_inventory(), manifest)

    def test_manifest_rejects_bad_schema_extra_fields_and_claimed_test_execution(self):
        mutations = []
        bad = copy.deepcopy(self.manifest)
        bad["schema_version"] = "2.0"
        mutations.append(bad)
        bad = copy.deepcopy(self.manifest)
        bad["unexpected"] = True
        mutations.append(bad)
        bad = copy.deepcopy(self.manifest)
        bad["access_scenarios"][0]["execution_status"] = "pass"
        mutations.append(bad)
        bad = copy.deepcopy(self.manifest)
        bad["authorization_contexts"][0]["role_reference"] = "password=synthetic-secret"
        mutations.append(bad)

        for manifest in mutations:
            with self.subTest(manifest=manifest):
                with self.assertRaises(BWControlsAssessmentError):
                    validate_controls_manifest(manifest)

    def test_loader_rejects_duplicate_keys_and_nonstandard_json_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controls.json"
            for content in (
                '{"schema_version":"1.0","schema_version":"1.0"}',
                '{"value":NaN}',
            ):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content):
                    with self.assertRaises(BWControlsAssessmentError):
                        load_controls_manifest(path)

    def test_cli_writes_new_report_only_and_returns_status_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory_path = root / "inventory.json"
            controls_path = root / "controls.json"
            report_path = root / "report.json"
            inventory_path.write_text(
                json.dumps(_candidate_inventory()), encoding="utf-8"
            )
            controls_path.write_text(json.dumps(self.manifest), encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main([
                    "--inventory", str(inventory_path),
                    "--controls", str(controls_path),
                    "--output", str(report_path),
                ]), 0)
            self.assertEqual(
                json.loads(report_path.read_text(encoding="utf-8"))["gate_status"],
                "candidate_for_owner_review",
            )

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main([
                    "--inventory", str(inventory_path),
                    "--controls", str(controls_path),
                    "--output", str(report_path),
                ]), 2)

            controls_path.write_text(
                json.dumps(load_controls_manifest(
                    ROOT / "docs" / "fixtures" / "sap_bw_controls.partial.example.json"
                )),
                encoding="utf-8",
            )
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main([
                    "--inventory", str(inventory_path),
                    "--controls", str(controls_path),
                    "--output", str(root / "open-report.json"),
                ]), 1)


if __name__ == "__main__":
    unittest.main()
