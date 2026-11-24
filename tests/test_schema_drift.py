"""Behavioral tests for schema drift comparisons and local snapshots."""

import json
import tempfile
import unittest
from pathlib import Path

from powerbi_import.schema_drift import (
    SchemaDriftEntry,
    detect_schema_drift,
    load_snapshot,
    save_snapshot,
)


def _snapshot(**overrides):
    data = {
        "datasources": [],
        "worksheets": [],
        "dashboards": [],
        "calculations": [],
        "parameters": [],
        "filters": [],
    }
    data.update(overrides)
    return data


def _entries_by_category(report, category):
    return {(entry.change_type, entry.name, entry.table, entry.detail)
            for entry in report.by_category(category)}


class TestSchemaDriftComparison(unittest.TestCase):
    def test_tables_columns_and_datatype_changes_are_reported_with_context(self):
        previous = _snapshot(datasources=[{
            "tables": [
                {"name": "Orders", "columns": [
                    {"name": "Order ID", "datatype": "integer"},
                    {"name": "Legacy Note", "datatype": "string"},
                ]},
                {"name": "Retired Table", "columns": []},
            ],
        }])
        current = _snapshot(datasources=[{
            "tables": [
                {"name": "Orders", "columns": [
                    {"name": "Order ID", "datatype": "string"},
                    {"name": "Net €", "datatype": "decimal"},
                ]},
                {"name": "New Table", "columns": []},
            ],
        }])

        report = detect_schema_drift(current, previous, source_name="Sales & Finance")

        self.assertEqual(_entries_by_category(report, "table"), {
            ("added", "New Table", "", ""),
            ("removed", "Retired Table", "", ""),
        })
        self.assertEqual(_entries_by_category(report, "column"), {
            ("modified", "Order ID", "Orders", "type changed: integer → string"),
            ("added", "Net €", "Orders", ""),
            ("removed", "Legacy Note", "Orders", ""),
        })
        self.assertEqual(report.source_name, "Sales & Finance")
        self.assertTrue(report.has_drift)

    def test_calculations_report_added_modified_and_removed_formulas(self):
        previous = _snapshot(calculations=[
            {"name": "Net Revenue", "formula": "[Sales] - [Returns]"},
            {"caption": "Old Margin", "formula": "[Profit] / [Sales]"},
        ])
        current = _snapshot(calculations=[
            {"name": "Net Revenue", "formula": "[Sales] - [Credits]"},
            {"name": "Gross Margin", "formula": "[Profit] / [Sales]"},
        ])

        report = detect_schema_drift(current, previous)

        self.assertEqual(_entries_by_category(report, "calculation"), {
            ("modified", "Net Revenue", "", "formula changed"),
            ("added", "Gross Margin", "", ""),
            ("removed", "Old Margin", "", ""),
        })
        self.assertEqual(len(report.added), 1)
        self.assertEqual(len(report.removed), 1)
        self.assertEqual(len(report.modified), 1)

    def test_relationship_additions_and_removals_compare_full_endpoints(self):
        previous = _snapshot(datasources=[{
            "relationships": [
                {"from_table": "Orders", "from_column": "Customer ID",
                 "to_table": "Customers", "to_column": "ID"},
                {"from_table": "Orders", "from_column": "Legacy ID",
                 "to_table": "Legacy", "to_column": "ID"},
            ],
        }])
        current = _snapshot(datasources=[{
            "relationships": [
                {"from_table": "Orders", "from_column": "Customer ID",
                 "to_table": "Customers", "to_column": "ID"},
                {"from_table": "Orders", "from_column": "Invoice ID",
                 "to_table": "Invoices", "to_column": "ID"},
            ],
        }])

        report = detect_schema_drift(current, previous)

        self.assertEqual({(entry.change_type, entry.name)
                          for entry in report.by_category("relationship")}, {
            ("added", "Orders.Invoice ID → Invoices.ID"),
            ("removed", "Orders.Legacy ID → Legacy.ID"),
        })

    def test_worksheets_report_add_remove_and_changed_fields(self):
        previous = _snapshot(worksheets=[
            {"name": "Overview", "fields": [{"name": "Revenue"}, {"name": "Region"}]},
            {"name": "Legacy View", "fields": []},
        ])
        current = _snapshot(worksheets=[
            {"name": "Overview", "fields": [{"name": "Revenue"}, {"name": "Country"}]},
            {"name": "New View", "fields": []},
        ])

        report = detect_schema_drift(current, previous)

        self.assertEqual(_entries_by_category(report, "worksheet"), {
            ("modified", "Overview", "", "+1 fields, -1 fields"),
            ("added", "New View", "", ""),
            ("removed", "Legacy View", "", ""),
        })

    def test_parameters_report_value_add_and_removal_and_filters_report_field_changes(self):
        previous = _snapshot(
            parameters=[
                {"name": "Start Date", "current_value": "2025-01-01"},
                {"name": "Legacy Region", "current_value": "West"},
            ],
            filters=[{"field": "Status"}, {"field": "Legacy Segment"}],
        )
        current = _snapshot(
            parameters=[
                {"name": "Start Date", "current_value": "2026-01-01"},
                {"name": "Country", "current_value": "日本"},
            ],
            filters=[{"field": "Status"}, {"field": "Order Date"}],
        )

        report = detect_schema_drift(current, previous)

        self.assertEqual(_entries_by_category(report, "parameter"), {
            ("modified", "Start Date", "", "value: 2025-01-01 → 2026-01-01"),
            ("added", "Country", "", ""),
            ("removed", "Legacy Region", "", ""),
        })
        self.assertEqual({(entry.change_type, entry.name)
                          for entry in report.by_category("filter")}, {
            ("added", "Order Date"),
            ("removed", "Legacy Segment"),
        })

    def test_report_summary_and_json_include_category_and_change_totals(self):
        report = detect_schema_drift(
            _snapshot(calculations=[{"name": "Revenue", "formula": "SUM([Amount])"}],
                      filters=[{"field": "Region"}]),
            _snapshot(calculations=[{"name": "Revenue", "formula": "SUM([Sales])"}],
                      filters=[{"field": "Status"}]),
            source_name="Quarterly Report",
        )

        summary = report.summary()
        payload = json.loads(report.to_json())

        self.assertIn("Schema drift detected (3 changes):", summary)
        self.assertIn("filter: +1, -1", summary)
        self.assertIn("calculation: ~1", summary)
        self.assertEqual(payload["source_name"], "Quarterly Report")
        self.assertTrue(payload["has_drift"])
        self.assertEqual(payload["total_changes"], 3)
        self.assertEqual(payload["summary"], {
            "added": 1, "removed": 1, "modified": 1, "renamed": 0,
        })

    def test_no_drift_has_stable_empty_summary(self):
        snapshot = _snapshot(datasources=[{"tables": [{"name": "Orders", "columns": []}]}])

        report = detect_schema_drift(snapshot, snapshot)

        self.assertFalse(report.has_drift)
        self.assertEqual(report.entries, [])
        self.assertEqual(report.summary(), "No schema drift detected.")
        self.assertEqual(report.to_dict()["total_changes"], 0)

    def test_schema_drift_report_save_writes_unicode_json_artifact(self):
        report = detect_schema_drift(
            _snapshot(parameters=[{"name": "地域", "current_value": "東"}]),
            _snapshot(),
            source_name="売上 & Sales",
        )

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested" / "drift.json"
            report.save(str(output))
            saved = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(saved["source_name"], "売上 & Sales")
        self.assertEqual(saved["entries"][0]["name"], "地域")
        self.assertEqual(saved["summary"]["added"], 1)


class TestSchemaDriftSnapshots(unittest.TestCase):
    def test_snapshot_round_trip_preserves_all_supported_collections(self):
        extracted = _snapshot(
            datasources=[{"name": "Source", "tables": [{"name": "Orders"}]}],
            worksheets=[{"name": "Overview"}],
            dashboards=[{"name": "Executive"}],
            calculations=[{"name": "Revenue", "formula": "SUM([Amount])"}],
            parameters=[{"name": "Year", "current_value": "2026"}],
            filters=[{"field": "Region", "value": "北"}],
        )

        with tempfile.TemporaryDirectory() as temporary:
            save_snapshot(extracted, temporary)
            loaded = load_snapshot(temporary)

        self.assertEqual(loaded, extracted)

    def test_missing_and_corrupt_snapshot_files_default_to_empty_collections(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "datasources.json").write_text("{broken", encoding="utf-8")
            (directory / "worksheets.json").write_text('[{"name":"Résumé"}]',
                                                       encoding="utf-8")
            (directory / "calculations.json").write_text("[]", encoding="utf-8")

            loaded = load_snapshot(temporary)

        self.assertEqual(loaded["datasources"], [])
        self.assertEqual(loaded["worksheets"], [{"name": "Résumé"}])
        self.assertEqual(loaded["calculations"], [])
        self.assertEqual(loaded["dashboards"], [])
        self.assertEqual(loaded["parameters"], [])
        self.assertEqual(loaded["filters"], [])


if __name__ == "__main__":
    unittest.main()