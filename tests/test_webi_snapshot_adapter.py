"""Tests for adapting a WebI CMS snapshot to BO extraction collections."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
from bo_export.webi_snapshot_adapter import extract_webi_snapshot
from powerbi_import.pbip_generator import PowerBIProjectGenerator
from powerbi_import.tmdl_generator import generate_tmdl
from powerbi_import.validator import ArtifactValidator

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

    def _snapshot_with_provider(self, provider):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["data_providers"] = [provider]
        return snapshot

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

    def test_snapshot_without_visuals_creates_a_report_shell_for_the_model(self):
        extracted = extract_webi_snapshot(self.snapshot, CONNECTION)
        converted = adapt_bo_to_converted_objects(extracted)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(PowerBIProjectGenerator(directory).generate_project("Snapshot", converted))
            descriptor = json.loads((project / "Snapshot.pbip").read_text(encoding="utf-8"))
            report_path = descriptor["artifacts"][0]["report"]["path"]
            self.assertEqual(report_path, "Snapshot.Report")
            report = project / report_path
            definition = json.loads((report / "definition.pbir").read_text(encoding="utf-8"))
            self.assertEqual(definition["datasetReference"]["byPath"]["path"],
                             "../Snapshot.SemanticModel")
            pages = json.loads((report / "definition" / "pages" / "pages.json")
                               .read_text(encoding="utf-8"))
            self.assertEqual(len(pages["pageOrder"]), 1)
            page = json.loads((report / "definition" / "pages" / pages["pageOrder"][0]
                               / "page.json").read_text(encoding="utf-8"))
            self.assertEqual(page["displayName"], "BusinessObjects Migration")
            self.assertEqual(list(report.rglob("visual.json")), [])
            validation = ArtifactValidator.validate_project(project)
            self.assertTrue(validation["valid"], validation["errors"])

    def test_empty_report_shell_does_not_replace_an_existing_report(self):
        extracted = extract_webi_snapshot(self.snapshot, CONNECTION)
        converted = adapt_bo_to_converted_objects(extracted)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "Snapshot"
            report = project / "Snapshot.Report"
            report.mkdir(parents=True)
            sentinel = report / "existing.txt"
            sentinel.write_text("existing report", encoding="utf-8")
            descriptor = project / "Snapshot.pbip"
            descriptor.write_text("existing project", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                PowerBIProjectGenerator(directory).generate_project("Snapshot", converted)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing report")
            self.assertEqual(descriptor.read_text(encoding="utf-8"), "existing project")
            self.assertFalse((project / "Snapshot.SemanticModel").exists())

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

    def test_matching_query_plan_linkage_preserves_the_sql(self):
        sql = "SELECT [Region] FROM [dbo].[Sales]"
        provider = self._provider("DP0", "Sales", [
            {"index": "1", "sql": sql, "operators": []},
        ])

        extracted = extract_webi_snapshot(
            self._snapshot_with_provider(provider), CONNECTION
        )

        self.assertEqual(extracted["queries"][0]["sql"], sql)
        self.assertEqual(extracted["custom_sql"][0]["sql"], sql)

    def test_query_plan_linkage_mismatches_fail_without_disclosing_sql(self):
        sentinel_sql = "SELECT 'QUERY_PLAN_LINKAGE_SENTINEL' AS secret"
        mismatch_cases = (
            ("document_id", "another-document"),
            ("provider_id", "another-provider"),
        )
        for field, value in mismatch_cases:
            with self.subTest(field=field):
                provider = self._provider("DP0", "Sales", [
                    {"index": "1", "sql": sentinel_sql, "operators": []},
                ])
                provider["query_plan"][field] = value
                with self.assertRaises(ValueError) as raised:
                    extract_webi_snapshot(
                        self._snapshot_with_provider(provider), CONNECTION
                    )
                self.assertNotIn(sentinel_sql, str(raised.exception))

    def test_missing_query_plan_linkage_ids_fail(self):
        for missing_id in (
            "snapshot_document_id",
            "plan_document_id",
            "summary_provider_id",
            "plan_provider_id",
        ):
            with self.subTest(missing_id=missing_id):
                provider = self._provider("DP0", "Sales", [
                    {"index": "1", "sql": "SELECT 1", "operators": []},
                ])
                snapshot = self._snapshot_with_provider(provider)
                if missing_id == "snapshot_document_id":
                    del snapshot["document_id"]
                elif missing_id == "plan_document_id":
                    del provider["query_plan"]["document_id"]
                elif missing_id == "summary_provider_id":
                    del provider["summary"]["id"]
                else:
                    del provider["query_plan"]["provider_id"]

                with self.assertRaises(ValueError):
                    extract_webi_snapshot(snapshot, CONNECTION)

    def test_declared_single_statement_requires_a_valid_direct_sql_plan(self):
        invalid_plans = (
            ("malformed status", {"status": "failed"}),
            ("missing status", {"status": None}),
            ("zero statements", {"statements": []}),
            ("multiple statements", {"statements": [
                {"index": "1", "sql": "SELECT 1", "operators": []},
                {"index": "2", "sql": "SELECT 2", "operators": []},
            ]}),
            ("non-list statements", {"statements": None}),
            ("non-object statement", {"statements": ["SELECT 1"]}),
            ("missing statement SQL", {"statements": [{"index": "1", "operators": []}]}),
            ("empty SQL", {"statements": [
                {"index": "1", "sql": "  ", "operators": []},
            ]}),
            ("statement has operators", {"statements": [
                {"index": "1", "sql": "SELECT 1", "operators": ["JOIN"]},
            ]}),
        )
        for label, changes in invalid_plans:
            with self.subTest(plan=label):
                provider = self._provider("DP0", "Sales", [
                    {"index": "1", "sql": "SELECT 1", "operators": []},
                ])
                provider["query_plan"].update(changes)
                with self.assertRaises(ValueError):
                    extract_webi_snapshot(
                        self._snapshot_with_provider(provider), CONNECTION
                    )

    def test_duplicate_normalized_provider_summary_ids_fail(self):
        providers = [
            self._provider(7, "Numeric provider", [
                {"index": "1", "sql": "SELECT 1", "operators": []},
            ]),
            self._provider("7", "String provider", [
                {"index": "1", "sql": "SELECT 2", "operators": []},
            ]),
        ]
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["data_providers"] = providers

        with self.assertRaises(ValueError):
            extract_webi_snapshot(snapshot, CONNECTION)

    def test_numeric_summary_provider_id_matches_its_string_plan_id(self):
        provider = self._provider(7, "Numeric provider", [
            {"index": "1", "sql": "SELECT 7", "operators": []},
        ])
        provider["query_plan"]["provider_id"] = "7"

        extracted = extract_webi_snapshot(
            self._snapshot_with_provider(provider), CONNECTION
        )

        self.assertEqual(extracted["queries"][0]["id"], "7")
        self.assertEqual(extracted["queries"][0]["sql"], "SELECT 7")

    def test_absent_plans_and_non_single_statement_plans_keep_skip_warning(self):
        no_plan = {
            "summary": {"id": "DP0", "name": "No plan"},
            "details": {"id": "DP0"},
        }
        non_single = self._provider("DP1", "Multiple", [
            {"index": "1", "sql": "SELECT 1", "operators": []},
        ])
        non_single["query_plan"]["single_statement"] = False
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["data_providers"] = [no_plan, non_single]

        with self.assertLogs("bo_export.webi_snapshot_adapter", level="WARNING") as logged:
            extracted = extract_webi_snapshot(snapshot, CONNECTION)

        self.assertEqual(extracted["queries"], [])
        self.assertEqual(extracted["custom_sql"], [])
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
