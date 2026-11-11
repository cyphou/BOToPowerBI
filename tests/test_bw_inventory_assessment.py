"""Tests for the offline BW-0 inventory review assessment."""

import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from migrate_bw_assess import main
from powerbi_import.bw_inventory import BWInventoryError, assess_bw0


ROOT = Path(__file__).resolve().parents[1]


class TestBWInventoryAssessment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads(
            (ROOT / "docs" / "fixtures" / "sap_bw_inventory.partial.example.json")
            .read_text(encoding="utf-8")
        )

    def _review_candidate(self):
        inventory = copy.deepcopy(self.inventory)
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

    def test_partial_example_reports_blockers_without_claiming_runtime_evidence(self):
        original = copy.deepcopy(self.inventory)
        report = assess_bw0(self.inventory)

        self.assertEqual(self.inventory, original)
        self.assertEqual(report["gate_status"], "open")
        self.assertFalse(report["gate_closed"])
        self.assertEqual(
            report["evidence_boundary"],
            "validated_local_inventory_declarations_only",
        )
        self.assertGreater(report["summary"]["blockers"], 0)
        self.assertEqual(report["runtime_evidence"], {
            "live_sap_discovery": "not_run",
            "source_owner_attestation_verification": "not_run",
            "bw0_exit_approval": "not_run",
        })

    def test_complete_declared_inventory_is_only_a_candidate_for_owner_review(self):
        report = assess_bw0(self._review_candidate())

        self.assertEqual(report["gate_status"], "candidate_for_owner_review")
        self.assertFalse(report["gate_closed"])
        self.assertEqual(report["summary"]["blockers"], 0)

    def test_missing_owner_and_unresolved_dependencies_are_blockers(self):
        inventory = self._review_candidate()
        provider = next(item for item in inventory["objects"] if item["disposition"] == "in_scope")
        provider["business_owner"] = None
        inventory["dependencies"] = [{
            "source_id": "unresolved-source",
            "target_id": "unresolved-target",
            "kind": "feeds",
            "evidence_status": "unknown",
            "resolution_status": "unresolved",
            "evidence_reference": None,
        }]

        report = assess_bw0(inventory)
        codes = {finding["code"] for finding in report["findings"]}
        self.assertEqual(report["gate_status"], "open")
        self.assertIn("object_owner_missing", codes)
        self.assertIn("dependency_unresolved", codes)

    def test_owned_unknowns_and_known_gaps_require_review_not_silent_closure(self):
        inventory = self._review_candidate()
        inventory["unknowns"] = [{
            "id": "synthetic-unknown",
            "path": "$.objects[0].definition",
            "reason": "Synthetic unresolved metadata",
            "status": "unknown",
            "owner": "synthetic-owner",
        }]
        inventory["scope"]["known_gaps"] = ["Synthetic consumer usage gap"]

        report = assess_bw0(inventory)
        self.assertEqual(report["gate_status"], "candidate_for_owner_review")
        self.assertFalse(report["gate_closed"])
        self.assertEqual(report["summary"]["review_items"], 2)

    def test_cli_writes_report_and_returns_nonzero_for_open_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory_path = Path(directory) / "inventory.json"
            report_path = Path(directory) / "assessment.json"
            inventory_path.write_text(json.dumps(self.inventory), encoding="utf-8")

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(["--inventory", str(inventory_path), "--output", str(report_path)]),
                    1,
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["gate_status"], "open")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(["--inventory", str(inventory_path), "--output", str(report_path)]),
                    2,
                )

    def test_rejects_invalid_inventory(self):
        inventory = copy.deepcopy(self.inventory)
        inventory["schema_version"] = "9.0"
        with self.assertRaises(BWInventoryError):
            assess_bw0(inventory)


if __name__ == "__main__":
    unittest.main()
