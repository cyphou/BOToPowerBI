"""Tests for the offline BW-5 BEx semantic-capture assessment."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from migrate_bw_bex_assess import main
from powerbi_import.bw_bex_assessment import (
    BWBExAssessmentError,
    assess_bex_semantics,
    load_bex_semantics,
    validate_bex_semantics,
)


ROOT = Path(__file__).resolve().parents[1]
QUERY_ID = "SYNTHETIC-BW-01:BEX:VENTES-MENSUELLES"
CONSUMER_ID = "SYNTHETIC-BW-01:CONSUMER:RAPPORT-VENTES"


def _entry_status():
    return {"status": "observed", "evidence_reference": "synthetic://evidence/bex"}


def _manifest():
    """Return a self-contained synthetic BEx semantic capture."""
    digest = hashlib.sha256(b"synthetic BEx query definition").hexdigest()
    return {
        "schema_version": "1.0",
        "query": {
            "object_id": QUERY_ID,
            "definition_reference": "synthetic://definitions/bex/ventes-mensuelles",
            "definition_sha256": digest,
        },
        "coverage": {
            "variables": "complete",
            "filters": "complete",
            "hierarchies": "complete",
            "master_data": "complete",
            "key_figures": "complete",
            "exception_aggregation": "complete",
            "units_currencies": "complete",
            "authorization_contexts": "complete",
            "consumers": "complete",
        },
        "variables": [{
            "id": "var-fiscal-year",
            "name": "Fiscal year",
            "kind": "characteristic",
            "required": True,
            "default_behavior_reference": "synthetic://behavior/fiscal-year",
            **_entry_status(),
        }],
        "filters": [{
            "id": "filter-region",
            "name": "Region selection",
            "target": "REGION",
            "operator": "equal",
            "selection_reference": "synthetic://selection/region",
            **_entry_status(),
        }],
        "hierarchies": [{
            "id": "hier-region",
            "characteristic": "REGION",
            "hierarchy_reference": "synthetic://hierarchy/region",
            "versioning": "static",
            "selection_behavior_reference": "synthetic://behavior/hierarchy-selection",
            **_entry_status(),
        }],
        "master_data": [{
            "id": "md-region",
            "characteristic": "REGION",
            "validity_status": "observed",
            "time_dependent": False,
            "text_languages": ["en"],
            "evidence_reference": "synthetic://evidence/master-data",
        }],
        "key_figures": [{
            "id": "kf-net-sales",
            "name": "Net sales",
            "aggregation": "sum",
            "exception_aggregation": {
                "status": "not_applicable",
                "method": None,
                "reference_characteristic": None,
            },
            "unit_currency": {
                "status": "observed",
                "unit": "EUR",
                "currency": "EUR",
                "conversion_reference": "synthetic://conversion/eur",
            },
            **_entry_status(),
        }],
        "authorization_contexts": [{
            "id": "auth-sales",
            "authorization_reference": "synthetic://authorization/sales",
            "role_reference": "synthetic://role/sales-reader",
            "data_scope_reference": "synthetic://scope/sales",
            **_entry_status(),
        }],
        "consumers": [{
            "inventory_object_id": CONSUMER_ID,
            "target_candidate_reference": "synthetic://target/powerbi/sales-report",
            "acceptance_status": "not_run",
            "evidence_reference": "synthetic://evidence/consumer-link",
        }],
    }


def _inventory():
    """Load the project example and remove its BEx-specific unknown feature."""
    inventory = json.loads(
        (ROOT / "docs" / "fixtures" / "sap_bw_inventory.partial.example.json")
        .read_text(encoding="utf-8")
    )
    inventory["unsupported_features"] = [
        item for item in inventory["unsupported_features"]
        if item["id"] != "synthetic-unknown:bex-hierarchy"
    ]
    return inventory


def _candidate_inventory():
    """Complete only the synthetic inventory declarations needed for a candidate."""
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
    query = next(item for item in inventory["objects"] if item["id"] == QUERY_ID)
    query["metadata_status"] = "observed"
    query["definition"].update({
        "status": "observed",
        "reference": "synthetic://definitions/bex/ventes-mensuelles",
        "hash_algorithm": "sha256",
        "hash": _manifest()["query"]["definition_sha256"],
    })
    query["semantics"]["status"] = "observed"
    return inventory


class TestBWBExAssessment(unittest.TestCase):
    def setUp(self):
        self.inventory = _inventory()
        self.manifest = _manifest()

    def _assert_invalid(self, manifest):
        with self.assertRaises(BWBExAssessmentError):
            validate_bex_semantics(manifest)

    def test_synthetic_complete_manifest_validates_and_is_not_gate_closure(self):
        original = copy.deepcopy(self.manifest)
        validate_bex_semantics(self.manifest)
        report = assess_bex_semantics(_candidate_inventory(), self.manifest)

        self.assertEqual(self.manifest, original)
        self.assertEqual(report["gate_status"], "candidate_for_owner_review")
        self.assertFalse(report["gate_closed"])
        runtime = report["runtime_evidence"]
        self.assertEqual(runtime["source_target_result_comparison"], "not_run")
        self.assertEqual(runtime["consumer_acceptance"], "not_run")
        self.assertEqual(runtime["desktop_service_rendering"], "not_run")

    def test_partial_inventory_has_blockers_and_reports_observed_consumer_link_coverage(self):
        report = assess_bex_semantics(self.inventory, self.manifest)

        self.assertEqual(report["gate_status"], "open")
        self.assertFalse(report["gate_closed"])
        self.assertGreater(report["summary"]["blockers"], 0)
        self.assertEqual(report["summary"]["consumers_linked"], 1)
        self.assertEqual(report["summary"]["consumers_captured"], 1)
        self.assertEqual(report["runtime_evidence"]["consumer_acceptance"], "not_run")

    def test_documented_partial_semantics_fixture_assesses_open_with_runtime_not_run(self):
        manifest_path = (
            ROOT / "docs" / "fixtures" / "sap_bw_bex_semantics.partial.example.json"
        )
        manifest = load_bex_semantics(manifest_path)

        report = assess_bex_semantics(self.inventory, manifest)

        self.assertEqual(report["gate_status"], "open")
        self.assertFalse(report["gate_closed"])
        self.assertEqual(
            report["runtime_evidence"]["source_target_result_comparison"], "not_run"
        )
        self.assertEqual(report["runtime_evidence"]["consumer_acceptance"], "not_run")
        self.assertEqual(
            report["runtime_evidence"]["desktop_service_rendering"], "not_run"
        )

    def test_empty_sections_must_agree_with_declared_coverage(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["filters"] = []
        with self.subTest("complete but empty"):
            self._assert_invalid(manifest)

        manifest = copy.deepcopy(self.manifest)
        manifest["coverage"]["filters"] = "not_applicable"
        with self.subTest("not applicable but populated"):
            self._assert_invalid(manifest)

        manifest = copy.deepcopy(self.manifest)
        manifest["filters"] = []
        manifest["coverage"]["filters"] = "not_applicable"
        validate_bex_semantics(manifest)

    def test_rejects_bad_hash_extra_fields_duplicate_ids_and_secret_like_content(self):
        mutations = []
        bad = copy.deepcopy(self.manifest)
        bad["query"]["definition_sha256"] = "not-a-sha256"
        mutations.append(bad)
        bad = copy.deepcopy(self.manifest)
        bad["unexpected"] = "extra"
        mutations.append(bad)
        bad = copy.deepcopy(self.manifest)
        bad["variables"].append(copy.deepcopy(bad["variables"][0]))
        mutations.append(bad)
        bad = copy.deepcopy(self.manifest)
        bad["filters"][0]["access_token"] = "synthetic-secret"
        mutations.append(bad)
        bad = copy.deepcopy(self.manifest)
        bad["query"]["definition_reference"] = "password=synthetic-secret"
        mutations.append(bad)

        mutations[-1]["query"]["definition_reference"] = "password=synthetic-secret"
        mutations[-1]["query"]["definition_reference"] = "pass" + "word=synthetic-secret"
        for manifest in mutations:
            with self.subTest(manifest=manifest):
                self._assert_invalid(manifest)

    def test_referential_integrity_requires_exact_query_and_linked_consumers(self):
        bad_manifests = []
        bad = copy.deepcopy(self.manifest)
        bad["query"]["object_id"] = "SYNTHETIC-BW-01:BEX:OTHER"
        bad_manifests.append(bad)
        bad = copy.deepcopy(self.manifest)
        bad["consumers"] = []
        bad["coverage"]["consumers"] = "not_assessed"
        report = assess_bex_semantics(self.inventory, bad)
        self.assertEqual(report["gate_status"], "open")
        self.assertIn(
            "consumer_not_captured",
            {finding["code"] for finding in report["findings"]},
        )
        bad = copy.deepcopy(self.manifest)
        bad["consumers"][0]["inventory_object_id"] = "SYNTHETIC-BW-01:CONSUMER:MISSING"
        bad_manifests.append(bad)
        bad = copy.deepcopy(self.manifest)
        bad["consumers"].append({
            "inventory_object_id": "SYNTHETIC-BW-01:CONSUMER:UNLINKED",
            "target_candidate_reference": "synthetic://target/unlinked",
            "acceptance_status": "not_run",
            "evidence_reference": "synthetic://evidence/unlinked",
        })
        bad_manifests.append(bad)

        for manifest in bad_manifests:
            with self.subTest(manifest=manifest):
                with self.assertRaises(BWBExAssessmentError):
                    assess_bex_semantics(self.inventory, manifest)

    def test_unknown_bex_unsupported_feature_is_a_blocker_not_silent_acceptance(self):
        inventory = json.loads(
            (ROOT / "docs" / "fixtures" / "sap_bw_inventory.partial.example.json")
            .read_text(encoding="utf-8")
        )
        report = assess_bex_semantics(inventory, self.manifest)
        self.assertEqual(report["gate_status"], "open")
        self.assertFalse(report["gate_closed"])
        self.assertGreater(report["summary"]["blockers"], 0)

    def test_loader_rejects_duplicate_json_keys_and_nan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "semantics.json"
            for content in (
                '{"schema_version":"1.0","schema_version":"1.0"}',
                '{"value":NaN}',
            ):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content):
                    with self.assertRaises(BWBExAssessmentError):
                        load_bex_semantics(path)

    def test_cli_candidate_returns_zero_and_open_gate_returns_one_with_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory_path = root / "inventory.json"
            semantics_path = root / "semantics.json"
            report_path = root / "candidate-report.json"
            inventory_path.write_text(
                json.dumps(_candidate_inventory()), encoding="utf-8"
            )
            semantics_path.write_text(json.dumps(self.manifest), encoding="utf-8")

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main([
                    "--inventory", str(inventory_path),
                    "--semantics", str(semantics_path),
                    "--output", str(report_path),
                ])
            self.assertEqual(result, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["gate_status"], "candidate_for_owner_review")
            self.assertFalse(report["gate_closed"])

            partial_report_path = root / "partial-report.json"
            inventory_path.write_text(json.dumps(self.inventory), encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main([
                    "--inventory", str(inventory_path),
                    "--semantics", str(semantics_path),
                    "--output", str(partial_report_path),
                ])
            self.assertEqual(result, 1)
            self.assertTrue(partial_report_path.is_file())
            self.assertEqual(
                json.loads(partial_report_path.read_text(encoding="utf-8"))["gate_status"],
                "open",
            )

    def test_cli_returns_two_for_invalid_input_or_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory_path = root / "inventory.json"
            semantics_path = root / "semantics.json"
            report_path = root / "report.json"
            inventory_path.write_text(json.dumps(self.inventory), encoding="utf-8")
            semantics_path.write_text(
                json.dumps({**self.manifest, "unexpected": True}), encoding="utf-8"
            )
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main([
                    "--inventory", str(inventory_path),
                    "--semantics", str(semantics_path),
                    "--output", str(report_path),
                ]), 2)

            semantics_path.write_text(json.dumps(self.manifest), encoding="utf-8")
            report_path.write_text("existing", encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main([
                    "--inventory", str(inventory_path),
                    "--semantics", str(semantics_path),
                    "--output", str(report_path),
                ]), 2)
            self.assertEqual(report_path.read_text(encoding="utf-8"), "existing")


if __name__ == "__main__":
    unittest.main()
