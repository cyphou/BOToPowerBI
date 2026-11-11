"""Contract tests for the offline SAP BW inventory API."""

import copy
import json
import tempfile
import sys
import unittest
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from powerbi_import.bw_inventory import (
    BWInventoryError,
    load_snapshot,
    sanitize_snapshot,
    upgrade_snapshot,
    validate_snapshot,
)


class TestBwInventoryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repository = Path(__file__).resolve().parents[1]
        cls.schema = json.loads(
            (repository / "docs/schemas/sap_bw_inventory.schema.json")
            .read_text(encoding="utf-8")
        )
        cls.inventory = json.loads(
            (repository / "docs/fixtures/sap_bw_inventory.partial.example.json")
            .read_text(encoding="utf-8")
        )

    @staticmethod
    def _draft_01(current):
        """Project the 1.0 fixture onto the documented, known 0.1 shape."""
        draft = copy.deepcopy(current)
        draft["schema_version"] = "0.1"
        for field in ("run_id", "provenance", "errors", "unknowns", "unsupported_features"):
            draft.pop(field)
        draft["source_system"].pop("landscape")
        for item in draft["objects"]:
            for field in ("metadata_status", "definition", "keys_status", "keys", "semantics"):
                item.pop(field)
            for field in ("route", "prerequisites", "validation"):
                item["migration_decision"].pop(field)
        for edge in draft["dependencies"]:
            edge.pop("resolution_status")
        return draft

    def test_schema_and_fixture_are_current_10_inventory(self):
        self.assertEqual(self.schema["$id"], "urn:bo-to-powerbi:schema:sap-bw-inventory:1.0")
        self.assertEqual(self.schema["properties"]["schema_version"]["const"], "1.0")
        self.assertEqual(self.inventory["schema_version"], "1.0")
        required = set(self.schema["required"])
        self.assertTrue(required.issubset(self.inventory))
        validated = validate_snapshot(self.inventory)
        self.assertEqual(validated, self.inventory)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps(self.inventory, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(load_snapshot(path), validated)

    def test_upgrade_01_to_10_is_deterministic_and_preserves_known_fields(self):
        draft = self._draft_01(self.inventory)
        original = copy.deepcopy(draft)
        upgraded = upgrade_snapshot(draft)

        self.assertEqual(upgraded, upgrade_snapshot(draft))
        self.assertEqual(draft, original)
        self.assertEqual(upgraded["schema_version"], "1.0")
        self.assertEqual(upgraded["captured_at"], draft["captured_at"])
        self.assertEqual(upgraded["discovery"], draft["discovery"])
        self.assertEqual(upgraded["extraction_access"], draft["extraction_access"])
        self.assertEqual(upgraded["scope"], draft["scope"])
        for old_field, value in draft["source_system"].items():
            self.assertEqual(upgraded["source_system"][old_field], value)
        for old_obj, new_obj in zip(draft["objects"], upgraded["objects"]):
            for field, value in old_obj.items():
                if field == "migration_decision":
                    for decision_field, decision_value in value.items():
                        self.assertEqual(
                            new_obj[field][decision_field],
                            decision_value,
                            f"object {old_obj['id']} decision field {decision_field}",
                        )
                else:
                    self.assertEqual(new_obj[field], value, f"object {old_obj['id']} field {field}")
        for old_edge, new_edge in zip(draft["dependencies"], upgraded["dependencies"]):
            for field, value in old_edge.items():
                self.assertEqual(new_edge[field], value, f"dependency field {field}")
            self.assertEqual(new_edge["resolution_status"], "unknown")
        self.assertEqual(validate_snapshot(upgraded), upgraded)

    def test_unknown_versions_and_malformed_documents_are_rejected(self):
        for api in (validate_snapshot, upgrade_snapshot):
            with self.subTest(api=api.__name__):
                with self.assertRaises(BWInventoryError):
                    api({**copy.deepcopy(self.inventory), "schema_version": "9.9"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown-version.json"
            path.write_text('{"schema_version":"9.9"}', encoding="utf-8")
            with self.assertRaises(BWInventoryError):
                load_snapshot(path)
            path.write_text('{"schema_version": ', encoding="utf-8")
            with self.assertRaises(BWInventoryError):
                load_snapshot(path)
            for invalid_json in (
                '{"schema_version":"1.0","schema_version":"1.0"}',
                '{"value":NaN}',
                '{"value":Infinity}',
            ):
                path.write_text(invalid_json, encoding="utf-8")
                with self.subTest(invalid_json=invalid_json):
                    with self.assertRaises(BWInventoryError):
                        load_snapshot(path)

        malformed = copy.deepcopy(self.inventory)
        malformed["objects"] = None
        with self.assertRaises(BWInventoryError):
            validate_snapshot(malformed)
        malformed = copy.deepcopy(self.inventory)
        malformed["source_system"]["product"] = []
        with self.assertRaises(BWInventoryError):
            validate_snapshot(malformed)
        with self.assertRaises(BWInventoryError):
            upgrade_snapshot({"schema_version": "0.1"})

    def test_unicode_ids_and_dependency_lineage_are_preserved_exactly(self):
        snapshot = copy.deepcopy(self.inventory)
        first_id = "BW:Cafe\u0301"
        second_id = "BW:Café"
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(unicodedata.normalize("NFC", first_id), second_id)
        old_first = snapshot["objects"][0]["id"]
        old_second = snapshot["objects"][1]["id"]
        snapshot["objects"][0]["id"] = first_id
        snapshot["objects"][1]["id"] = second_id
        snapshot["objects"][0]["name"] = "Région — 東京"
        replacements = {old_first: first_id, old_second: second_id}
        for edge in snapshot["dependencies"]:
            for field in ("source_id", "target_id"):
                edge[field] = replacements.get(edge[field], edge[field])

        validated = validate_snapshot(snapshot)
        self.assertEqual(validated["objects"][0]["id"], first_id)
        self.assertEqual(validated["objects"][1]["id"], second_id)
        self.assertEqual(validated["objects"][0]["name"], "Région — 東京")
        self.assertTrue(
            any(edge["source_id"] == first_id and edge["target_id"] == second_id
                for edge in validated["dependencies"])
        )
        self.assertNotEqual(
            validated["objects"][0]["id"],
            unicodedata.normalize("NFC", validated["objects"][0]["id"]),
        )
        upgraded = upgrade_snapshot(self._draft_01(snapshot))
        self.assertEqual(upgraded["objects"][0]["id"], first_id)
        self.assertEqual(upgraded["objects"][1]["id"], second_id)
        self.assertTrue(
            any(edge["source_id"] == first_id and edge["target_id"] == second_id
                for edge in upgraded["dependencies"])
        )

    def test_typed_keys_references_and_uniqueness_are_enforced(self):
        valid = validate_snapshot(self.inventory)
        keyed_object = next(item for item in valid["objects"] if item["keys"])
        key = keyed_object["keys"][0]
        self.assertIsInstance(key["name"], str)
        self.assertIsInstance(key["data_type"], str)
        self.assertIs(type(key["nullable"]), bool)
        self.assertIn(key["role"], {"business", "technical", "surrogate", "partition", "unknown"})

        duplicate_object = copy.deepcopy(self.inventory)
        duplicate_object["objects"].append(copy.deepcopy(duplicate_object["objects"][0]))
        with self.assertRaises(BWInventoryError):
            validate_snapshot(duplicate_object)

        duplicate_key = copy.deepcopy(self.inventory)
        obj = next(item for item in duplicate_key["objects"] if item["keys"])
        obj["keys"].append(copy.deepcopy(obj["keys"][0]))
        with self.assertRaises(BWInventoryError):
            validate_snapshot(duplicate_key)

        invalid_key = copy.deepcopy(self.inventory)
        obj = next(item for item in invalid_key["objects"] if item["keys"])
        obj["keys"][0]["nullable"] = "false"
        with self.assertRaises(BWInventoryError):
            validate_snapshot(invalid_key)

        unresolved = copy.deepcopy(self.inventory)
        unresolved["dependencies"][0]["target_id"] = "absent-object"
        with self.assertRaises(BWInventoryError):
            validate_snapshot(unresolved)

        duplicate_edge = copy.deepcopy(self.inventory)
        duplicate_edge["dependencies"].append(copy.deepcopy(duplicate_edge["dependencies"][0]))
        with self.assertRaises(BWInventoryError):
            validate_snapshot(duplicate_edge)

    def test_sensitive_fields_and_embedded_secrets_are_redacted_without_mutation(self):
        snapshot = copy.deepcopy(self.inventory)
        snapshot["operator_password"] = "PasswordSentinel-2468"
        snapshot["metadata"] = {
            "api_key": "ApiKeySentinel-1357",
            "comment": "endpoint password=InlineSecretSentinel-9876",
        }
        original = copy.deepcopy(snapshot)
        sanitized = sanitize_snapshot(snapshot)

        self.assertEqual(snapshot, original)
        self.assertEqual(sanitized["operator_password"], "***REDACTED***")
        self.assertEqual(sanitized["metadata"]["api_key"], "***REDACTED***")
        for value in ("PasswordSentinel-2468", "ApiKeySentinel-1357", "InlineSecretSentinel-9876"):
            self.assertNotIn(value, json.dumps(sanitized, ensure_ascii=False))

        invalid = copy.deepcopy(self.inventory)
        invalid["objects"][0]["criticality"] = "password=ErrorSecretSentinel-4567"
        invalid_original = copy.deepcopy(invalid)
        with self.assertRaises(BWInventoryError) as raised:
            validate_snapshot(invalid)
        self.assertEqual(invalid, invalid_original)
        self.assertNotIn("ErrorSecretSentinel-4567", str(raised.exception))

    def test_unsupported_features_cannot_be_marked_converted_or_passing(self):
        snapshot = copy.deepcopy(self.inventory)
        feature = next(
            item for item in snapshot["unsupported_features"]
            if item["support_status"] == "unsupported"
        )
        feature["conversion_status"] = "pass"
        with self.assertRaises(BWInventoryError):
            validate_snapshot(snapshot)

        snapshot = copy.deepcopy(self.inventory)
        feature = next(
            item for item in snapshot["unsupported_features"]
            if item["support_status"] == "unsupported"
        )
        parent = next(item for item in snapshot["objects"] if item["id"] == feature["object_id"])
        parent["migration_decision"]["validation"]["status"] = "pass"
        with self.assertRaises(BWInventoryError):
            validate_snapshot(snapshot)

    def test_errors_unknowns_and_unsupported_records_remain_visible(self):
        snapshot = copy.deepcopy(self.inventory)
        error = {
            "code": "SOURCE_PERMISSION_DENIED",
            "category": "permission",
            "status": "unknown",
            "message": "Synthetic access could not be verified.",
            "evidence_reference": "synthetic://evidence/permission",
        }
        snapshot["errors"].append(error)
        unknown = {
            "id": "unknown:lineage-owner",
            "path": "objects[*].business_owner",
            "reason": "The owner was not provided.",
            "status": "not_assessed",
            "owner": None,
        }
        snapshot["unknowns"].append(unknown)

        validated = validate_snapshot(snapshot)
        self.assertIn(error, validated["errors"])
        self.assertIn(unknown, validated["unknowns"])
        self.assertTrue(validated["unsupported_features"])

        upgraded = upgrade_snapshot(self._draft_01(self.inventory))
        self.assertTrue(upgraded["unknowns"])
        self.assertTrue(any(item["id"] == "upgrade:run-id" for item in upgraded["unknowns"]))


if __name__ == "__main__":
    unittest.main()
