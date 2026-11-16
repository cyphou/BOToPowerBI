"""Tests for the offline BW-8 cutover and retirement declaration assessment."""

import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from migrate_bw_cutover_assess import main
from powerbi_import.bw_cutover_assessment import (
    CHECK_KINDS,
    BWCutoverAssessmentError,
    assess_bw_cutover,
    load_cutover_manifest,
    validate_cutover_manifest,
)
from powerbi_import.bw_wave_evidence_index import LAYERS, OPERATIONAL_KINDS

ROOT = Path(__file__).resolve().parents[1]


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
    inventory["dependencies"] = []
    inventory["unknowns"] = []
    inventory["errors"] = []
    inventory["unsupported_features"] = []
    for item in inventory["objects"]:
        if item["disposition"] == "in_scope":
            item["discovery_status"] = "observed"
            item["business_owner"] = "synthetic-owner"
            if item["criticality"] == "unknown":
                item["criticality"] = "medium"
        if item["type"] == "consumer":
            item["business_owner"] = "synthetic-owner"
    return inventory


def _wave_manifest(inventory):
    object_ids = [
        item["id"] for item in inventory["objects"]
        if item["disposition"] == "in_scope"
    ]
    return {
        "schema_version": "1.0",
        "wave_id": "synthetic-wave-01",
        "inventory_scope": {
            "inventory_id": inventory["source_system"]["id"],
            "inventory_run_id": inventory["run_id"],
            "object_ids": object_ids,
        },
        "traceability": {
            "source_version_reference": "synthetic-source-version",
            "target_version_reference": "synthetic-target-version",
            "extract_boundary_reference": "synthetic-extract-boundary",
            "grain_reference": "synthetic-grain",
        },
        "object_evidence": [
            {
                "object_id": object_id,
                "layers": [
                    {
                        "kind": layer,
                        "applicability": "applicable",
                        "status": "pass",
                        "evidence_reference": f"synthetic-{object_id}-{layer}-evidence",
                        "owner_reference": "synthetic-layer-owner",
                        "exception_ids": [],
                    }
                    for layer in LAYERS
                ],
            }
            for object_id in object_ids
        ],
        "operational_evidence": [
            {
                "kind": kind,
                "status": "pass",
                "evidence_reference": f"synthetic-{kind}-evidence",
                "owner_reference": "synthetic-operations-owner",
            }
            for kind in OPERATIONAL_KINDS
        ],
        "exceptions": [],
    }


def _manifest(inventory):
    consumers = [
        item for item in inventory["objects"] if item["type"] == "consumer"
    ]
    return {
        "schema_version": "1.0",
        "wave_id": "synthetic-wave-01",
        "inventory_scope": {
            "inventory_id": inventory["source_system"]["id"],
            "inventory_run_id": inventory["run_id"],
            "dependency_coverage": "complete",
        },
        "dependency_dispositions": [
            {
                "id": f"synthetic-dependency-{index}",
                "category": "bo_consumer",
                "inventory_object_id": item["id"],
                "inventory_edge": None,
                "disposition": "migrated",
                "owner_reference": "synthetic-consumer-owner",
                "evidence_reference": "synthetic-consumer-evidence",
                "approval_reference": None,
            }
            for index, item in enumerate(consumers)
        ],
        "cutover_plan": {
            "runbook_reference": "synthetic-cutover-runbook",
            "freeze_checkpoint_reference": "synthetic-freeze-checkpoint",
            "watermark_catchup_reference": "synthetic-watermark-catchup",
            "reconciliation_threshold_reference": "synthetic-reconciliation-thresholds",
            "consumer_switch_plan_reference": "synthetic-consumer-switch",
            "communications_plan_reference": "synthetic-communications",
            "monitoring_plan_reference": "synthetic-monitoring",
            "escalation_plan_reference": "synthetic-escalation",
        },
        "parallel_run": {
            "minimum_days": 10,
            "completed_days": 10,
            "evidence_reference": "synthetic-parallel-run",
            "owner_reference": "synthetic-operations-owner",
        },
        "independent_observation": {
            "minimum_days": 5,
            "completed_days": 5,
            "evidence_reference": "synthetic-bw-independent-observation",
            "owner_reference": "synthetic-operations-owner",
        },
        "rollback": {
            "trigger_reference": "synthetic-rollback-triggers",
            "time_limit_minutes": 60,
            "recovery_objective_reference": "synthetic-recovery-objectives",
            "divergence_handling_reference": "synthetic-divergence-handling",
            "runbook_reference": "synthetic-rollback-runbook",
            "exercise_status": "pass",
            "exercise_evidence_reference": "synthetic-rollback-exercise",
            "owner_reference": "synthetic-operations-owner",
        },
        "checks": [
            {
                "kind": kind,
                "status": "pass",
                "evidence_reference": f"synthetic-{kind}-evidence",
                "owner_reference": "synthetic-owner",
                "approval_reference": (
                    f"synthetic-{kind}-approval"
                    if kind in {
                        "bw0_to_bw7_owner_acceptance", "planning_retention_signed_off",
                        "business_go_no_go", "source_owner_go_no_go",
                        "security_go_no_go", "compliance_go_no_go",
                        "operations_go_no_go", "decommission_approval",
                    }
                    else None
                ),
            }
            for kind in CHECK_KINDS
        ],
    }


class TestBWCutoverAssessment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.partial_inventory = _inventory()
        cls.partial_wave = json.loads(
            (ROOT / "docs" / "fixtures" / "sap_bw_wave_evidence.partial.example.json")
            .read_text(encoding="utf-8")
        )
        cls.partial_manifest = json.loads(
            (ROOT / "docs" / "fixtures" / "sap_bw_cutover.partial.example.json")
            .read_text(encoding="utf-8")
        )

    def test_partial_fixture_is_valid_but_assesses_as_blocked(self):
        manifest = validate_cutover_manifest(copy.deepcopy(self.partial_manifest))
        report = assess_bw_cutover(
            self.partial_inventory, self.partial_wave, manifest
        )

        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["gate_closed"])
        self.assertFalse(report["cutover_authorized"])
        self.assertFalse(report["retirement_authorized"])
        self.assertEqual(report["runtime_evidence"]["source_shutdown"], "not_run")
        self.assertGreater(report["summary"]["blockers"], 0)

    def test_complete_local_declarations_remain_owner_review_only(self):
        inventory = _candidate_inventory()
        wave = _wave_manifest(inventory)
        manifest = _manifest(inventory)

        report = assess_bw_cutover(inventory, wave, manifest)

        self.assertEqual(report["status"], "declarations_complete_for_owner_review")
        self.assertFalse(report["gate_closed"])
        self.assertFalse(report["cutover_authorized"])
        self.assertFalse(report["retirement_authorized"])
        self.assertEqual(report["dependency_scope"], "wave_objects_and_direct_inventory_neighbors")
        self.assertEqual(report["dependency_coverage_verification"], "not_verified")
        self.assertTrue(any("transitive dependencies" in item for item in report["limitations"]))
        self.assertEqual(report["summary"]["blockers"], 0)
        self.assertEqual(report["runtime_evidence"]["parallel_run"], "not_run")
        self.assertEqual(report["runtime_evidence"]["rollback_execution"], "not_run")

    def test_wave_assessment_does_not_require_other_waves_consumers(self):
        inventory = _candidate_inventory()
        wave = _wave_manifest(inventory)
        first_wave_object = wave["inventory_scope"]["object_ids"][0]
        wave["inventory_scope"]["object_ids"] = [first_wave_object]
        wave["object_evidence"] = [
            item for item in wave["object_evidence"]
            if item["object_id"] == first_wave_object
        ]
        manifest = _manifest(inventory)
        manifest["dependency_dispositions"] = []

        report = assess_bw_cutover(inventory, wave, manifest)

        self.assertEqual(report["status"], "declarations_complete_for_owner_review")
        self.assertEqual(report["summary"]["inventory_consumers"], 0)

    def test_bw0_open_gate_blocks_complete_declarations(self):
        inventory = _inventory()
        manifest = _manifest(_candidate_inventory())
        manifest["inventory_scope"].update({
            "inventory_id": inventory["source_system"]["id"],
            "inventory_run_id": inventory["run_id"],
        })

        report = assess_bw_cutover(inventory, self.partial_wave, manifest)

        self.assertIn("bw0_inventory_gate_open", {item["code"] for item in report["findings"]})
        self.assertEqual(report["status"], "blocked")

    def test_bw7_open_gate_blocks_cutover_declarations(self):
        inventory = _candidate_inventory()
        wave = copy.deepcopy(self.partial_wave)
        wave["inventory_scope"].update({
            "inventory_id": inventory["source_system"]["id"],
            "inventory_run_id": inventory["run_id"],
        })
        manifest = _manifest(inventory)
        wave_object_ids = set(wave["inventory_scope"]["object_ids"])
        manifest["dependency_dispositions"] = [
            item for item in manifest["dependency_dispositions"]
            if item["inventory_object_id"] in wave_object_ids
        ]

        report = assess_bw_cutover(inventory, wave, manifest)

        self.assertIn("bw7_wave_evidence_open", {item["code"] for item in report["findings"]})

    def test_wave_and_inventory_scope_must_match(self):
        inventory = _candidate_inventory()
        wave = _wave_manifest(inventory)
        manifest = _manifest(inventory)
        manifest["wave_id"] = "synthetic-other-wave"

        with self.assertRaises(BWCutoverAssessmentError):
            assess_bw_cutover(inventory, wave, manifest)

    def test_every_inventory_consumer_must_be_dispositioned(self):
        inventory = _candidate_inventory()
        wave = _wave_manifest(inventory)
        manifest = _manifest(inventory)
        manifest["dependency_dispositions"] = []

        report = assess_bw_cutover(inventory, wave, manifest)

        self.assertIn(
            "inventory_consumer_not_dispositioned",
            {item["code"] for item in report["findings"]},
        )

    def test_every_inventory_edge_must_be_dispositioned(self):
        inventory = _candidate_inventory()
        source_id, target_id = [
            item["id"] for item in inventory["objects"][:2]
        ]
        inventory["dependencies"] = [{
            "source_id": source_id,
            "target_id": target_id,
            "kind": "feeds",
            "evidence_status": "observed",
            "resolution_status": "resolved",
            "evidence_reference": "synthetic-edge",
        }]
        wave = _wave_manifest(inventory)
        manifest = _manifest(inventory)

        report = assess_bw_cutover(inventory, wave, manifest)

        self.assertIn(
            "inventory_dependency_not_dispositioned",
            {item["code"] for item in report["findings"]},
        )

    def test_incomplete_observation_period_blocks(self):
        inventory = _candidate_inventory()
        wave = _wave_manifest(inventory)
        manifest = _manifest(inventory)
        manifest["independent_observation"]["completed_days"] = 4

        report = assess_bw_cutover(inventory, wave, manifest)

        self.assertIn(
            "independent_observation_duration_incomplete",
            {item["code"] for item in report["findings"]},
        )

    def test_passing_check_without_evidence_or_approval_blocks(self):
        inventory = _candidate_inventory()
        wave = _wave_manifest(inventory)
        manifest = _manifest(inventory)
        check = next(item for item in manifest["checks"] if item["kind"] == "decommission_approval")
        check["evidence_reference"] = None
        check["approval_reference"] = None

        report = assess_bw_cutover(inventory, wave, manifest)
        codes = {item["code"] for item in report["findings"]}

        self.assertIn("decommission_approval_evidence_missing", codes)
        self.assertIn("decommission_approval_approval_reference_missing", codes)

    def test_accepted_residual_requires_approval_reference(self):
        inventory = _candidate_inventory()
        wave = _wave_manifest(inventory)
        manifest = _manifest(inventory)
        manifest["dependency_dispositions"].append({
            "id": "synthetic-accepted-residual",
            "category": "legal_record",
            "inventory_object_id": None,
            "inventory_edge": None,
            "disposition": "accepted_residual",
            "owner_reference": "synthetic-compliance-owner",
            "evidence_reference": "synthetic-retention-evidence",
            "approval_reference": None,
        })

        report = assess_bw_cutover(inventory, wave, manifest)

        self.assertIn(
            "residual_dependency_approval_missing",
            {item["code"] for item in report["findings"]},
        )

    def test_invalid_status_duplicate_check_and_credentials_are_rejected(self):
        for mutate in (
            lambda value: value["checks"][0].update({"status": "approved"}),
            lambda value: value["checks"].append(copy.deepcopy(value["checks"][0])),
            lambda value: value["rollback"].update({"exercise_status": "approved"}),
            lambda value: value["cutover_plan"].update({"runbook_reference": "token=example"}),
        ):
            manifest = copy.deepcopy(self.partial_manifest)
            mutate(manifest)
            with self.subTest(manifest=manifest):
                with self.assertRaises(BWCutoverAssessmentError):
                    validate_cutover_manifest(manifest)

    def test_bool_is_not_accepted_as_duration(self):
        manifest = copy.deepcopy(self.partial_manifest)
        manifest["parallel_run"]["minimum_days"] = True

        with self.assertRaises(BWCutoverAssessmentError):
            validate_cutover_manifest(manifest)

    def test_loader_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cutover.json"
            path.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")

            with self.assertRaises(BWCutoverAssessmentError):
                load_cutover_manifest(path)

    def test_cli_writes_blocked_report_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory_path = Path(directory) / "inventory.json"
            wave_path = Path(directory) / "wave.json"
            cutover_path = Path(directory) / "cutover.json"
            output_path = Path(directory) / "report.json"
            inventory_path.write_text(json.dumps(self.partial_inventory), encoding="utf-8")
            wave_path.write_text(json.dumps(self.partial_wave), encoding="utf-8")
            cutover_path.write_text(json.dumps(self.partial_manifest), encoding="utf-8")
            args = [
                "--inventory", str(inventory_path),
                "--wave-evidence", str(wave_path),
                "--cutover", str(cutover_path),
                "--output", str(output_path),
            ]
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main(args), 1)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["status"], "blocked")
            self.assertIn("not authorized", stdout.getvalue())

            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(main(args), 2)
            self.assertIn("failed while writing", stderr.getvalue())

    def test_cli_returns_zero_only_for_complete_declarations_not_authorization(self):
        inventory = _candidate_inventory()
        wave = _wave_manifest(inventory)
        manifest = _manifest(inventory)
        with tempfile.TemporaryDirectory() as directory:
            inventory_path = Path(directory) / "inventory.json"
            wave_path = Path(directory) / "wave.json"
            cutover_path = Path(directory) / "cutover.json"
            output_path = Path(directory) / "report.json"
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
            wave_path.write_text(json.dumps(wave), encoding="utf-8")
            cutover_path.write_text(json.dumps(manifest), encoding="utf-8")
            args = [
                "--inventory", str(inventory_path),
                "--wave-evidence", str(wave_path),
                "--cutover", str(cutover_path),
                "--output", str(output_path),
            ]

            self.assertEqual(main(args), 0)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "declarations_complete_for_owner_review")
            self.assertFalse(report["cutover_authorized"])
            self.assertFalse(report["retirement_authorized"])


if __name__ == "__main__":
    unittest.main()
