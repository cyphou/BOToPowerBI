"""Tests for adapting a WebI CMS snapshot to BO extraction collections."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
from bo_export.webi_snapshot_adapter import extract_webi_snapshot
from powerbi_import.tmdl_generator import generate_tmdl

ROOT = Path(__file__).resolve().parents[1]
CONNECTION = {"name": "Declared SQL", "server": "sql.example.invalid", "database": "Sales"}


class TestWebiSnapshotAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads(
            (ROOT / "docs" / "fixtures" / "webi_document_snapshot.example.json")
            .read_text(encoding="utf-8")
        )

    @staticmethod
    def _provider(provider_id, name, statements):
        return {
            "summary": {"id": provider_id, "name": name},
            "details": {"id": provider_id},
            "query_plan": {
                "document_id": "synthetic-document", "provider_id": provider_id,
                "status": "available", "xml": "<queryplan/>",
                "statements": statements, "single_statement": len(statements) == 1,
            },
            "query_specification_xml": "<QuerySpec/>",
        }

    def test_snapshot_sql_and_declared_connection_reach_the_model_without_inventing_layout(self):
        original = copy.deepcopy(self.snapshot)
        extracted = extract_webi_snapshot(self.snapshot, CONNECTION)

        self.assertEqual(self.snapshot, original)
        self.assertEqual(len(extracted), 15)
        self.assertEqual(extracted["queries"][0]["sql"], "SELECT [Region] FROM [dbo].[Sales]")
        self.assertEqual(extracted["queries"][0]["datasource"], "Declared SQL")
        self.assertEqual(extracted["columns"], [])
        self.assertTrue(extracted["reports"][0]["cms_snapshot_layout_unconverted"])

        with self.assertLogs("bo_export.converted_objects_adapter", level="WARNING"):
            converted = adapt_bo_to_converted_objects(extracted)
        self.assertEqual(converted["worksheets"], [])
        self.assertEqual(converted["dashboards"], [])
        tables = converted["datasources"][0]["tables"]
        self.assertEqual([(t["name"], t["sql"]) for t in tables],
                         [("Sales", "SELECT [Region] FROM [dbo].[Sales]")])

        with tempfile.TemporaryDirectory() as directory:
            generate_tmdl(converted["datasources"], "Sales", {}, directory)
            model = "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(directory).rglob("*.tmdl")
            )
        self.assertIn('Sql.Database("sql.example.invalid", "Sales")', model)
        self.assertIn("SELECT [Region] FROM [dbo].[Sales]", model)

    def test_only_single_statement_providers_are_used_and_names_stay_unique(self):
        snapshot = copy.deepcopy(self.snapshot)
        sql = "SELECT N'R\u00e9gion' AS \"100%\" FROM [O'Brien]"
        snapshot["data_providers"] = [
            self._provider("DP0", "Sales", [{"index": "1", "sql": sql, "operators": []}]),
            self._provider("DP1", "sales", [{"index": "1", "sql": "SELECT 1", "operators": []}]),
            self._provider("DP2", "Multi", [
                {"index": "1", "sql": "SELECT 1", "operators": ["UNION"]},
                {"index": "2", "sql": "SELECT 2", "operators": []},
            ]),
            {"summary": {"id": "DP3", "name": "No plan"}, "details": {"id": "DP3"}},
        ]
        with self.assertLogs("bo_export.webi_snapshot_adapter", level="WARNING") as logged:
            extracted = extract_webi_snapshot(snapshot, CONNECTION)

        self.assertEqual([query["name"] for query in extracted["queries"]],
                         ["Sales", "sales [DP1]"])
        self.assertEqual(extracted["queries"][0]["sql"], sql)
        self.assertEqual([item["name"] for item in extracted["custom_sql"]],
                         ["Sales", "sales [DP1]"])
        self.assertEqual(len(logged.output), 2)

    def test_rejects_unsafe_connection_declarations_and_invalid_snapshots(self):
        for connection in (
            {**CONNECTION, "password": "not-accepted"},
            {"name": "Declared SQL", "server": "sql.example.invalid"},
            {**CONNECTION, "server": " "},
            {**CONNECTION, "database": "Sales\n"},
            None,
        ):
            with self.subTest(connection=connection):
                with self.assertRaises(ValueError):
                    extract_webi_snapshot(self.snapshot, connection)
        for snapshot in (None, {}, {**self.snapshot, "schema_version": "2.0"},
                         {**self.snapshot, "reports": {}}):
            with self.subTest(snapshot=snapshot):
                with self.assertRaises(ValueError):
                    extract_webi_snapshot(snapshot, CONNECTION)


if __name__ == "__main__":
    unittest.main()
