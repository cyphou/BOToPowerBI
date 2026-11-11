"""Tests for the offline BW wave evidence index and assessment CLI."""

import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from migrate_bw_wave_assess import main
from powerbi_import.bw_inventory import load_snapshot
from powerbi_import.bw_wave_evidence_index import (
    BWWaveEvidenceError,
    LAYERS,
    OPERATIONAL_KINDS,
    assess_wave_evidence,
    load_wave_evidence,
)


ROOT = Path(__file__).resolve().parents[1]


class TestBWWaveEvidenceIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.partial_inventory = json.loads(
            (ROOT / "docs/fixtures/sap_bw_inventory.partial.example.json")
            .read_text(encoding="utf-8")
        )
        cls.partial_evidence = json.loads(
            (ROOT / "docs/fixtures/sap_bw_wave_evidence.partial.example.json")
            .read_text(encoding="utf-8")
        )

    @staticmethod
    def _owner_review_inventory():
        """Complete the synthetic partial inventory using its declared fields."""
        inventory = copy.deepcopy(TestBWWaveEvidenceIndex.partial_inventory)
        scope = inventory["scope"]
        scope["completeness"] = "complete"
        scope["owner_signoff"] = "accepted"
        scope["known_gaps"] = []
        scope["coverage"] = {
            field: ("not_applicable" if field == "planning_writeback" else "complete")
            for field in scope["coverage"]
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
        for item in inventory["objects"]:
            if item["disposition"] == "in_scope":
                item["discovery_status"] = "observed"
                item["business_owner"] = "synthetic-owner"
                if item["criticality"] == "unknown":
                    item["criticality"] = "medium"
            if item["type"] == "consumer":
                item["business_owner"] = "synthetic-owner"
        return inventory

    @staticmethod
    def _passing_evidence(inventory):
        object_ids = [
            item["id"] for item in inventory["objects"]
            if item["disposition"] == "in_scope"
        ]
        return {
            "schema_version": "1.0",
            "wave_id": "synthetic-owner-reviewed-wave",
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
                            "evidence_reference": f"synthetic-{object_id}-{layer}-report",
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
                    "evidence_reference": f"synthetic-{kind}-report",
                    "owner_reference": "synthetic-operations-owner",
                }
                for kind in OPERATIONAL_KINDS
            ],
            "exceptions": [],
        }

    def test_partial_fixtures_load_and_assessment_has_bw0_gate_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory_path = Path(directory) / "inventory.json"
            evidence_path = Path(directory) / "evidence.json"
            inventory_path.write_text(json.dumps(self.partial_inventory), encoding="utf-8")
            evidence_path.write_text(json.dumps(self.partial_evidence), encoding="utf-8")

            inventory = load_snapshot(inventory_path)
            evidence = load_wave_evidence(evidence_path)
            report = assess_wave_evidence(inventory, evidence)

        self.assertEqual(report["status"], "open")
        self.assertEqual(report["inventory_gate_status"], "open")
        self.assertFalse(report["gate_closed"])
        self.assertIn(
            {"code": "inventory_scope_gate_open", "path": "$.inventory"},
            report["findings"],
        )
        self.assertGreater(report["summary"]["blockers"], 0)

    def test_report_preserves_object_operational_references_and_exceptions(self):
        report = assess_wave_evidence(self.partial_inventory, self.partial_evidence)

        self.assertEqual(report["object_evidence"], self.partial_evidence["object_evidence"])
        self.assertEqual(
            report["operational_evidence"],
            self.partial_evidence["operational_evidence"],
        )
        self.assertEqual(report["exceptions"], self.partial_evidence["exceptions"])
        self.assertEqual(report["traceability"], self.partial_evidence["traceability"])

    def test_runtime_evidence_remains_not_run(self):
        report = assess_wave_evidence(self.partial_inventory, self.partial_evidence)

        self.assertEqual(report["runtime_evidence"], {
            "sap_execution": "not_run",
            "fabric_execution": "not_run",
            "operational_certification": "not_run",
            "retirement_approval": "not_run",
        })

    def test_all_declared_passing_evidence_is_only_candidate_not_closed(self):
        inventory = self._owner_review_inventory()
        evidence = self._passing_evidence(inventory)

        report = assess_wave_evidence(inventory, evidence)

        self.assertEqual(report["status"], "candidate_for_owner_review")
        self.assertEqual(report["summary"]["blockers"], 0)
        self.assertFalse(report["gate_closed"])
        self.assertEqual(report["inventory_gate_status"], "candidate_for_owner_review")
        self.assertEqual(report["runtime_evidence"]["sap_execution"], "not_run")
        self.assertEqual(report["runtime_evidence"]["fabric_execution"], "not_run")

    def test_missing_duplicate_layers_and_out_of_scope_references_fail_closed(self):
        inventory = self._owner_review_inventory()
        evidence = self._passing_evidence(inventory)

        missing = copy.deepcopy(evidence)
        missing["object_evidence"][0]["layers"].pop()
        with self.assertRaises(BWWaveEvidenceError):
            assess_wave_evidence(inventory, missing)

        duplicate = copy.deepcopy(evidence)
        duplicate["object_evidence"][0]["layers"].append(
            copy.deepcopy(duplicate["object_evidence"][0]["layers"][0])
        )
        with self.assertRaises(BWWaveEvidenceError):
            assess_wave_evidence(inventory, duplicate)

        out_of_scope = copy.deepcopy(evidence)
        out_of_scope["inventory_scope"]["object_ids"].append("synthetic-not-in-inventory")
        out_of_scope["object_evidence"].append({
            "object_id": "synthetic-not-in-inventory",
            "layers": copy.deepcopy(out_of_scope["object_evidence"][0]["layers"]),
        })
        with self.assertRaises(BWWaveEvidenceError):
            assess_wave_evidence(inventory, out_of_scope)

        unlisted_object = copy.deepcopy(evidence)
        unlisted_object["object_evidence"][0]["object_id"] = "synthetic-not-in-wave"
        with self.assertRaises(BWWaveEvidenceError):
            assess_wave_evidence(inventory, unlisted_object)

    def test_not_run_fail_evidence_and_unresolved_exceptions_are_blockers(self):
        inventory = self._owner_review_inventory()
        evidence = self._passing_evidence(inventory)
        object_id = evidence["object_evidence"][0]["object_id"]
        layer = evidence["object_evidence"][0]["layers"][0]
        layer["status"] = "not_run"
        layer["exception_ids"] = ["synthetic-gap"]
        evidence["exceptions"] = [{
            "id": "synthetic-gap",
            "object_id": object_id,
            "layer": layer["kind"],
            "owner_reference": "synthetic-layer-owner",
            "disposition": "unresolved",
            "approval_reference": None,
        }]
        evidence["operational_evidence"][0]["status"] = "fail"

        report = assess_wave_evidence(inventory, evidence)
        codes = {finding["code"] for finding in report["findings"]}
        self.assertEqual(report["status"], "open")
        self.assertIn(f"{layer['kind']}_not_run", codes)
        self.assertIn(
            f"operational_{evidence['operational_evidence'][0]['kind']}_fail",
            codes,
        )
        self.assertIn("exception_unresolved", codes)
        self.assertEqual(report["summary"]["blockers"], len(report["findings"]))

    def test_accepted_exception_requires_approval_reference(self):
        inventory = self._owner_review_inventory()
        evidence = self._passing_evidence(inventory)
        object_id = evidence["object_evidence"][0]["object_id"]
        layer = evidence["object_evidence"][0]["layers"][0]
        layer["exception_ids"] = ["synthetic-accepted-gap"]
        exception = {
            "id": "synthetic-accepted-gap",
            "object_id": object_id,
            "layer": layer["kind"],
            "owner_reference": "synthetic-layer-owner",
            "disposition": "accepted",
            "approval_reference": None,
        }
        evidence["exceptions"] = [exception]
        with self.assertRaises(BWWaveEvidenceError):
            assess_wave_evidence(inventory, evidence)

        exception["approval_reference"] = "synthetic-owner-approval"
        report = assess_wave_evidence(inventory, evidence)
        self.assertEqual(report["status"], "candidate_for_owner_review")
        self.assertEqual(report["exceptions"][0]["approval_reference"], "synthetic-owner-approval")

    def test_loader_rejects_duplicate_keys_nonstandard_constants_and_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            for document in (
                '{"schema_version":"1.0","schema_version":"1.0"}',
                '{"value":NaN}',
                '{"value":Infinity}',
            ):
                path.write_text(document, encoding="utf-8")
                with self.subTest(document=document), self.assertRaises(BWWaveEvidenceError):
                    load_wave_evidence(path)

            evidence = self._passing_evidence(self._owner_review_inventory())
            evidence["traceability"]["source_version_reference"] = "token=synthetic-secret"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            with self.assertRaises(BWWaveEvidenceError):
                load_wave_evidence(path)

    def test_cli_writes_new_report_preserves_existing_output_and_returns_status_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            inventory = self._owner_review_inventory()
            candidate_evidence = self._passing_evidence(inventory)
            inventory_path = base / "inventory.json"
            evidence_path = base / "evidence.json"
            output_path = base / "report.json"
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
            evidence_path.write_text(json.dumps(candidate_evidence), encoding="utf-8")
            args = [
                "--inventory", str(inventory_path),
                "--evidence", str(evidence_path),
                "--output", str(output_path),
            ]

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(args), 0)
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["status"], "candidate_for_owner_review")

            output_path.write_text("keep-existing-report", encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(args), 2)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "keep-existing-report")

            output_path.unlink()
            partial_inventory_path = base / "partial-inventory.json"
            partial_evidence_path = base / "partial-evidence.json"
            partial_inventory_path.write_text(json.dumps(self.partial_inventory), encoding="utf-8")
            partial_evidence_path.write_text(json.dumps(self.partial_evidence), encoding="utf-8")
            open_args = [
                "--inventory", str(partial_inventory_path),
                "--evidence", str(partial_evidence_path),
                "--output", str(output_path),
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(open_args), 1)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["status"], "open")

            output_path.unlink()
            evidence_path.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(args), 2)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
