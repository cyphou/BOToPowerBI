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
from powerbi_import.bw_inventory import (
    BWInventoryError,
    assess_bw0,
    trace_declared_lineage,
)


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


class TestDeclaredLineageTrace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads(
            (ROOT / "docs" / "fixtures" / "sap_bw_inventory.partial.example.json")
            .read_text(encoding="utf-8")
        )
        cls.object_ids = [item["id"] for item in cls.inventory["objects"][:5]]
        cls.consumer_id = next(
            item["id"] for item in cls.inventory["objects"]
            if item["type"] == "consumer"
        )

    def _snapshot(self, edges, object_ids=None):
        snapshot = copy.deepcopy(self.inventory)
        if object_ids is not None:
            for item, object_id in zip(snapshot["objects"], object_ids):
                item["id"] = object_id
        snapshot["dependencies"] = copy.deepcopy(edges)
        return snapshot

    @staticmethod
    def _edge(source_id, target_id, *, kind="feeds", evidence="observed",
              resolution="resolved", reference="synthetic edge"):
        return {
            "source_id": source_id,
            "target_id": target_id,
            "kind": kind,
            "evidence_status": evidence,
            "resolution_status": resolution,
            "evidence_reference": reference,
        }

    def test_chain_traverses_both_edge_orientations_and_preserves_declarations(self):
        a, b, c, d, _ = self.object_ids
        edges = [
            self._edge(a, b, evidence="inferred"),
            self._edge(c, b, kind="transforms", evidence="unknown"),
            self._edge(c, d, kind="queries"),
        ]
        report = trace_declared_lineage(
            self._snapshot(edges), a, [a, b, c, d],
        )

        self.assertEqual(report["reached_object_ids"], [a, b, c, d])
        self.assertEqual(report["traversed_dependencies"], edges)
        self.assertEqual(report["unresolved_dependencies"], [])
        self.assertEqual(
            [(edge["source_id"], edge["target_id"]) for edge in report["traversed_dependencies"]],
            [(a, b), (c, b), (c, d)],
        )
        self.assertEqual(
            [(edge["evidence_status"], edge["resolution_status"])
             for edge in report["traversed_dependencies"]],
            [("inferred", "resolved"), ("unknown", "resolved"), ("observed", "resolved")],
        )

    def test_cycles_and_shared_nodes_are_cycle_safe_with_bfs_order(self):
        a, b, c, d, _ = self.object_ids
        # A triangle plus two routes to D exercises a cycle and a shared node.
        edges = [
            self._edge(b, a),
            self._edge(c, b),
            self._edge(a, c),
            self._edge(b, d, kind="transforms"),
            self._edge(c, d, kind="queries"),
        ]
        report = trace_declared_lineage(
            self._snapshot(edges), a, [a, b, c, d],
        )

        self.assertEqual(report["reached_object_ids"], [a, b, c, d])
        self.assertEqual(report["traversed_dependencies"], edges)
        self.assertEqual(len(report["reached_object_ids"]), len(set(report["reached_object_ids"])))

    def test_unresolved_and_missing_endpoint_declarations_are_reported_not_traversed(self):
        a, b, c, _, _ = self.object_ids
        edges = [
            self._edge(a, b),
            self._edge(
                b, "missing-target", evidence="unknown", resolution="unresolved",
                reference="synthetic unresolved endpoint",
            ),
            self._edge(
                "missing-source", a, kind="other", evidence="not_assessed",
                resolution="unknown", reference=None,
            ),
            self._edge(
                c, "elsewhere", evidence="unknown", resolution="unresolved",
                reference=None,
            ),
        ]
        report = trace_declared_lineage(
            self._snapshot(edges), a, [a, b, c],
        )

        self.assertEqual(report["reached_object_ids"], [a, b])
        self.assertEqual(report["traversed_dependencies"], edges[:1])
        self.assertEqual(report["unresolved_dependencies"], edges[1:3])
        self.assertEqual(
            [edge["resolution_status"] for edge in report["unresolved_dependencies"]],
            ["unresolved", "unknown"],
        )

    def test_orphan_selection_and_scope_exclusion_bound_reachability(self):
        a, b, c, _, _ = self.object_ids
        edges = [self._edge(a, b), self._edge(b, c)]

        consumer_id = self.consumer_id
        orphan = trace_declared_lineage(
            self._snapshot([]), consumer_id, [consumer_id],
        )
        self.assertEqual(orphan["reached_object_ids"], [consumer_id])
        self.assertEqual(orphan["traversed_dependencies"], [])
        self.assertEqual(orphan["unresolved_dependencies"], [])

        scoped = trace_declared_lineage(self._snapshot(edges), a, [a, b])
        self.assertEqual(scoped["reached_object_ids"], [a, b])
        self.assertEqual(scoped["traversed_dependencies"], edges[:1])
        self.assertEqual(scoped["scope_object_ids"], [a, b])

    def test_invalid_and_ambiguous_identifiers_are_rejected(self):
        a, b, _, _, _ = self.object_ids
        snapshot = self._snapshot([self._edge(a, b)])

        invalid_calls = [
            (snapshot, "", [a]),
            (snapshot, "unknown-object", [a]),
            (snapshot, a, (a, b)),
            (snapshot, a, [a, a]),
            (snapshot, a, [a, "unknown-object"]),
            (snapshot, a, [b]),
        ]
        for args in invalid_calls:
            with self.subTest(selected=args[1], scope=args[2]):
                with self.assertRaises(BWInventoryError):
                    trace_declared_lineage(*args)

        malformed = copy.deepcopy(snapshot)
        malformed["schema_version"] = "9.0"
        with self.assertRaises(BWInventoryError):
            trace_declared_lineage(malformed, a, [a, b])

    def test_unicode_identifiers_remain_exact_and_are_not_normalized(self):
        import unicodedata

        decomposed = "BW:Cafe\u0301"
        composed = "BW:Café"
        self.assertNotEqual(decomposed, composed)
        self.assertEqual(unicodedata.normalize("NFC", decomposed), composed)
        snapshot = self._snapshot(
            [self._edge(decomposed, composed)],
            [decomposed, composed, *self.object_ids[2:]],
        )

        report = trace_declared_lineage(
            snapshot, decomposed, [decomposed, composed],
        )

        self.assertEqual(report["reached_object_ids"], [decomposed, composed])
        self.assertEqual(report["traversed_dependencies"][0]["source_id"], decomposed)
        self.assertEqual(report["traversed_dependencies"][0]["target_id"], composed)

    def test_report_marks_validation_boundary_and_sanitizes_without_mutating_input(self):
        a, b, _, _, _ = self.object_ids
        secret = "LineageSecretSentinel-8264"
        edges = [self._edge(a, b, reference=f"password={secret}")]
        snapshot = self._snapshot(edges)
        original = copy.deepcopy(snapshot)

        report = trace_declared_lineage(snapshot, a, [a, b])

        self.assertEqual(snapshot, original)
        self.assertEqual(
            report["evidence_boundary"],
            "validated_local_inventory_declarations_only",
        )
        self.assertEqual(report["verification_boundaries"], {
            "source": "unverified",
            "runtime": "not_run",
            "completeness": "unverified",
        })
        self.assertNotIn(secret, json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
