"""Tests for Crystal Reports extraction, subreport→drill-through, cross-tab→matrix,
BIAR batch pipeline, and batch validation.

Covers Sprints 13–18 of Phase 3.
"""

import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bo_export.crystal_extractor import extract_crystal
from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects


def _make_crystal_metadata():
    """Create metadata dict simulating parsed .rpt binary output."""
    return {
        "raw_text": (
            "Server=sql01.corp.com\n"
            "Database=SalesDB\n"
            "{Orders.OrderID} {Orders.Amount} {Customer.Name}\n"
            "Group #1 on {Orders.Region}\n"
            "Group #2 on {Customer.Country}\n"
            "Group Header #3 - Orders.Year\n"
            "Sort on {Orders.Amount} Descending\n"
            "Sort on {Customer.Name} Ascending\n"
            "Chart Revenue by Region: Bar\n"
            "Chart Monthly Trend: Line\n"
            "CrossTab summary view\n"
            "Subreport: Order Details\n"
            "Subreport Link: {Orders.OrderID} -> {Detail.OrderID}\n"
            "ConditionFormula: {Orders.Amount} > 10000 -> #FF0000\n"
            "Highlight Rule: {Orders.Discount} >= 0.2\n"
            "Running Total: GrandTotal on {Orders.Amount}\n"
            "{@TotalRevenue}\n"
            "{?Country}\n"
        ),
        "sections": [],
        "formulas_raw": ["{@TotalRevenue}", "{@DiscountCalc}"],
        "group_markers": [
            {"index": 1, "field": "Orders.Region"},
            {"index": 2, "field": "Customer.Country"},
        ],
        "sort_markers": [
            {"field": "Orders.Amount", "direction": "descending"},
            {"field": "Customer.Name", "direction": "ascending"},
        ],
        "chart_markers": [
            {"name": "Revenue by Region", "type": "bar"},
            {"name": "Monthly Trend", "type": "line"},
        ],
        "subreport_markers": ["Order Details"],
        "subreport_links": [
            {"parent_field": "Orders.OrderID", "child_field": "Detail.OrderID"},
        ],
        "cond_format_markers": [
            "{Orders.Amount} > 10000 -> #FF0000",
            "{Orders.Discount} >= 0.2",
        ],
        "crosstab_markers": [True],
        "running_total_markers": [
            {"name": "GrandTotal", "field": "Orders.Amount"},
        ],
    }


class TestCrystalExtractor(unittest.TestCase):
    """Sprint 13: Crystal extractor — groups, sorts, charts, subreports, alerts."""

    def setUp(self):
        self.metadata = _make_crystal_metadata()

    def test_extract_groups(self):
        result = extract_crystal("dummy.rpt", artifact_data=self.metadata)
        groups = result["groups"]
        # 2 from structured markers + 1 from raw text fallback
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups[0]["object"], "Region")
        self.assertEqual(groups[0]["table"], "Orders")
        self.assertEqual(groups[1]["object"], "Country")

    def test_extract_sorts(self):
        result = extract_crystal("dummy.rpt", artifact_data=self.metadata)
        sorts = result["sorts"]
        self.assertEqual(len(sorts), 2)
        self.assertEqual(sorts[0]["object"], "Amount")
        self.assertEqual(sorts[0]["order"], "descending")
        self.assertEqual(sorts[1]["object"], "Name")
        self.assertEqual(sorts[1]["order"], "ascending")

    def test_extract_charts(self):
        result = extract_crystal("dummy.rpt", artifact_data=self.metadata)
        charts = result["charts"]
        # 2 named charts + 1 cross-tab
        self.assertEqual(len(charts), 3)
        self.assertEqual(charts[0]["type"], "bar")
        self.assertEqual(charts[1]["type"], "line")
        self.assertEqual(charts[2]["type"], "cross_tab")

    def test_extract_subreports(self):
        result = extract_crystal("dummy.rpt", artifact_data=self.metadata)
        subs = result["subreports"]
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["name"], "Order Details")
        self.assertEqual(len(subs[0]["link_fields"]), 1)
        self.assertEqual(subs[0]["link_fields"][0]["parent_field"], "Orders.OrderID")
        self.assertEqual(subs[0]["link_fields"][0]["child_field"], "Detail.OrderID")

    def test_extract_alerts(self):
        result = extract_crystal("dummy.rpt", artifact_data=self.metadata)
        alerts = result["alerts"]
        # 2 cond_format + 1 running_total
        self.assertGreaterEqual(len(alerts), 2)
        parsed_alert = next(a for a in alerts if a.get("object") == "Amount"
                            and a.get("color") == "#FF0000")
        self.assertEqual(parsed_alert["operator"], ">")
        self.assertEqual(parsed_alert["value"], "10000")

    def test_extract_formulas(self):
        result = extract_crystal("dummy.rpt", artifact_data=self.metadata)
        formulas = result["formulas"]
        names = [f["name"] for f in formulas]
        self.assertIn("TotalRevenue", names)
        self.assertIn("DiscountCalc", names)

    def test_extract_parameters(self):
        result = extract_crystal("dummy.rpt", artifact_data=self.metadata)
        params = result["prompts"]
        names = [p["name"] for p in params]
        self.assertIn("Country", names)

    def test_extract_field_names_with_spaces_unicode_and_punctuation(self):
        metadata = {
            "raw_text": (
                "{Sales Orders.Région d'affaires / % (net)} "
                "{Sales Orders.Total Revenue}"
            ),
        }

        result = extract_crystal("dummy.rpt", artifact_data=metadata)

        self.assertEqual([table["name"] for table in result["tables"]], ["Sales Orders"])
        self.assertEqual(
            [(column["table"], column["name"]) for column in result["columns"]],
            [
                ("Sales Orders", "Région d'affaires / % (net)"),
                ("Sales Orders", "Total Revenue"),
            ],
        )
        converted = adapt_bo_to_converted_objects(result)
        converted_table = converted["datasources"][0]["tables"][0]
        self.assertEqual(
            [column["name"] for column in converted_table["columns"]],
            ["Région d'affaires / % (net)", "Total Revenue"],
        )

    def test_extract_formula_and_parameter_names_with_special_characters(self):
        formula_name = "Chiffre d'affaires / % (net)"
        parameter_name = "Région sélectionnée / %"
        result = extract_crystal("dummy.rpt", artifact_data={
            "raw_text": f"{{?{parameter_name}}}",
            "formulas_raw": [f"{{@{formula_name}}}"],
        })

        self.assertEqual([formula["name"] for formula in result["formulas"]], [formula_name])
        self.assertEqual([prompt["name"] for prompt in result["prompts"]], [parameter_name])
        converted = adapt_bo_to_converted_objects(result)
        self.assertEqual([item["name"] for item in converted["calculations"]], [formula_name])
        self.assertEqual([item["name"] for item in converted["parameters"]], [parameter_name])

    def test_extract_group_and_sort_fields_with_spaces_and_punctuation(self):
        field_name = "Region / Net (%)"
        report_bytes = (
            f"Group #1 on {{Sales Orders.{field_name}}}\n"
            f"Sort on {{Sales Orders.{field_name}}} Descending"
        ).encode("ascii")
        with tempfile.NamedTemporaryFile(suffix=".rpt", delete=False) as report:
            report.write(report_bytes)
            report_path = report.name

        try:
            result = extract_crystal(report_path)
        finally:
            os.unlink(report_path)

        self.assertEqual(
            [(group["table"], group["object"]) for group in result["groups"]],
            [("Sales Orders", field_name)],
        )
        self.assertEqual(
            [(sort["object"], sort["order"]) for sort in result["sorts"]],
            [(field_name, "descending")],
        )


class TestSubreportDrillThrough(unittest.TestCase):
    """Sprint 15: Crystal subreport → PBI drill-through page."""

    def _make_extraction_with_subreports(self):
        return {
            "reports": [
                {"name": "Main Report", "type": "crystal_report",
                 "datasource": "SalesDB"},
            ],
            "queries": [],
            "datasources": [
                {"name": "SalesDB", "type": "sql_server",
                 "server": "sql01", "database": "SalesDB", "schema": "dbo"},
            ],
            "formulas": [],
            "prompts": [],
            "filters": [],
            "tables": [{"name": "Orders", "type": "physical"}],
            "columns": [
                {"name": "OrderID", "table": "Orders", "data_type": "integer",
                 "qualification": "dimension"},
                {"name": "Amount", "table": "Orders", "data_type": "number",
                 "qualification": "measure"},
            ],
            "joins": [],
            "groups": [],
            "sorts": [],
            "alerts": [],
            "subreports": [
                {"name": "Order Details", "type": "subreport",
                 "parameters": [],
                 "link_fields": [
                     {"parent_field": "Orders.OrderID",
                      "child_field": "Detail.OrderID"}
                 ]},
            ],
            "charts": [
                {"name": "Summary Table", "type": "table",
                 "report": "Main Report",
                 "dimensions": ["OrderID"], "measures": ["Amount"]},
            ],
            "custom_sql": [],
        }

    def test_subreport_creates_drillthrough_worksheet(self):
        converted = adapt_bo_to_converted_objects(
            self._make_extraction_with_subreports())
        ws_names = [w["name"] for w in converted["worksheets"]]
        self.assertIn("Order Details", ws_names)

    def test_subreport_worksheet_has_drillthrough_type(self):
        converted = adapt_bo_to_converted_objects(
            self._make_extraction_with_subreports())
        dt_ws = next(w for w in converted["worksheets"]
                     if w["name"] == "Order Details")
        self.assertEqual(dt_ws.get("pageType"), "Drillthrough")

    def test_subreport_creates_filter_action(self):
        converted = adapt_bo_to_converted_objects(
            self._make_extraction_with_subreports())
        actions = converted["actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "filter")
        self.assertEqual(actions[0]["target_worksheet"], "Order Details")
        self.assertEqual(actions[0]["source_field"], "OrderID")

    def test_no_subreports_no_actions(self):
        ext = self._make_extraction_with_subreports()
        ext["subreports"] = []
        converted = adapt_bo_to_converted_objects(ext)
        self.assertEqual(converted["actions"], [])


class TestCrossTabMatrix(unittest.TestCase):
    """Sprint 16: Crystal cross-tab → PBI matrix visual."""

    def _make_extraction_with_crosstab(self):
        return {
            "reports": [
                {"name": "Sales Report", "type": "crystal_report",
                 "datasource": "SalesDB"},
            ],
            "queries": [],
            "datasources": [
                {"name": "SalesDB", "type": "sql_server",
                 "server": "sql01", "database": "SalesDB", "schema": "dbo"},
            ],
            "formulas": [],
            "prompts": [],
            "filters": [],
            "tables": [{"name": "Sales", "type": "physical"}],
            "columns": [
                {"name": "Region", "table": "Sales", "data_type": "string",
                 "qualification": "dimension"},
                {"name": "Product", "table": "Sales", "data_type": "string",
                 "qualification": "dimension"},
                {"name": "Revenue", "table": "Sales", "data_type": "number",
                 "qualification": "measure"},
            ],
            "joins": [],
            "groups": [
                {"name": "Group 1", "object": "Region", "table": "Sales",
                 "sort_direction": "ascending", "index": 1},
                {"name": "Group 2", "object": "Product", "table": "Sales",
                 "sort_direction": "ascending", "index": 2},
            ],
            "sorts": [],
            "alerts": [],
            "subreports": [],
            "charts": [
                {"name": "Cross-Tab", "type": "cross_tab",
                 "report": "Sales Report",
                 "dimensions": [], "measures": ["Revenue"]},
            ],
            "custom_sql": [],
        }

    def test_crosstab_becomes_matrix(self):
        converted = adapt_bo_to_converted_objects(
            self._make_extraction_with_crosstab())
        ws = next(w for w in converted["worksheets"]
                  if w["name"] == "Sales Report")
        self.assertEqual(ws["chart_type"], "matrix")

    def test_crosstab_enriched_with_groups(self):
        converted = adapt_bo_to_converted_objects(
            self._make_extraction_with_crosstab())
        ws = next(w for w in converted["worksheets"]
                  if w["name"] == "Sales Report")
        dims = ws.get("dimensions", [])
        dim_names = [d.get("name") for d in dims]
        self.assertIn("Region", dim_names)
        self.assertIn("Product", dim_names)

    def test_crosstab_group_fields_added(self):
        converted = adapt_bo_to_converted_objects(
            self._make_extraction_with_crosstab())
        ws = next(w for w in converted["worksheets"]
                  if w["name"] == "Sales Report")
        field_names = [f["name"] for f in ws.get("fields", [])]
        self.assertIn("Region", field_names)
        self.assertIn("Product", field_names)


class TestBiarBatchPipeline(unittest.TestCase):
    """Sprint 17: BIAR batch extraction → adapter → generation pipeline."""

    def _make_test_biar(self, tmp_dir):
        """Create a minimal test BIAR archive with a WebI and Crystal artifact."""
        biar_path = os.path.join(tmp_dir, "test_archive.biar")
        with zipfile.ZipFile(biar_path, "w") as zf:
            # WebI artifact (binary with extractable text)
            webi_content = b"some header" + b"\x00" * 10
            webi_content += b"[Revenue]" + b"\x00" * 5
            webi_content += b"SalesReport" + b"\x00" * 5
            zf.writestr("reports/sales.wid", webi_content)

            # Crystal artifact
            crystal_content = b"Server=sql01.corp.com" + b"\x00" * 5
            crystal_content += b"{Orders.Amount}" + b"\x00" * 5
            zf.writestr("reports/orders.rpt", crystal_content)

        return biar_path

    def test_biar_read_and_classify(self):
        from bo_export.biar_reader import read_biar_archive
        with tempfile.TemporaryDirectory() as tmp:
            biar_path = self._make_test_biar(tmp)
            artifacts = read_biar_archive(biar_path)
            self.assertEqual(len(artifacts), 2)
            types = {a["type"] for a in artifacts}
            self.assertIn("webi", types)
            self.assertIn("crystal", types)

    def test_biar_extract_per_artifact(self):
        from bo_export.biar_reader import read_biar_archive
        from bo_export.extract_bo_data import _route_extraction
        with tempfile.TemporaryDirectory() as tmp:
            biar_path = self._make_test_biar(tmp)
            artifacts = read_biar_archive(biar_path)
            for art in artifacts:
                extracted = _route_extraction(
                    art["type"], art["path"], False, artifact_data=art)
                self.assertIn("reports", extracted)
                self.assertIn("formulas", extracted)

    def test_biar_full_pipeline_per_artifact(self):
        from bo_export.biar_reader import read_biar_archive
        from bo_export.extract_bo_data import _route_extraction
        with tempfile.TemporaryDirectory() as tmp:
            biar_path = self._make_test_biar(tmp)
            artifacts = read_biar_archive(biar_path)
            for art in artifacts:
                extracted = _route_extraction(
                    art["type"], art["path"], False, artifact_data=art)
                converted = adapt_bo_to_converted_objects(extracted)
                self.assertIn("worksheets", converted)
                self.assertIn("datasources", converted)


class TestBatchValidation(unittest.TestCase):
    """Sprint 18: Batch validation & HTML report generation."""

    def _make_batch_output(self, tmp_dir):
        """Create a sample batch output directory structure."""
        art1_dir = os.path.join(tmp_dir, "sales_report")
        art2_dir = os.path.join(tmp_dir, "broken_report")
        os.makedirs(art1_dir)
        os.makedirs(art2_dir)

        # Successful artifact: has JSON + converted_objects
        for jf in ["reports.json", "queries.json", "datasources.json",
                    "formulas.json", "tables.json", "columns.json"]:
            with open(os.path.join(art1_dir, jf), "w") as f:
                json.dump([{"name": "test"}], f)
        with open(os.path.join(art1_dir, "converted_objects.json"), "w") as f:
            json.dump({"worksheets": []}, f)

        # Failed artifact: only empty JSON files
        for jf in ["reports.json", "datasources.json"]:
            with open(os.path.join(art2_dir, jf), "w") as f:
                json.dump([], f)

        # Write batch summary
        summary = {
            "total": 2,
            "succeeded": 1,
            "failed": 1,
            "artifacts": [
                {"name": "sales_report", "type": "webi", "status": "success",
                 "error": None, "output_dir": art1_dir},
                {"name": "broken_report", "type": "crystal", "status": "failed",
                 "error": "Parse error", "output_dir": art2_dir},
            ],
        }
        with open(os.path.join(tmp_dir, "batch_summary.json"), "w") as f:
            json.dump(summary, f)

        return tmp_dir

    def test_validate_batch(self):
        from bo_export.batch_report import validate_batch_output
        with tempfile.TemporaryDirectory() as tmp:
            self._make_batch_output(tmp)
            result = validate_batch_output(tmp)
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["passed"], 1)
            self.assertEqual(result["failed"], 1)

    def test_successful_artifact_valid(self):
        from bo_export.batch_report import validate_batch_output
        with tempfile.TemporaryDirectory() as tmp:
            self._make_batch_output(tmp)
            result = validate_batch_output(tmp)
            sales = next(a for a in result["artifacts"]
                         if a["name"] == "sales_report")
            self.assertTrue(sales["validation"]["valid"])

    def test_failed_artifact_invalid(self):
        from bo_export.batch_report import validate_batch_output
        with tempfile.TemporaryDirectory() as tmp:
            self._make_batch_output(tmp)
            result = validate_batch_output(tmp)
            broken = next(a for a in result["artifacts"]
                          if a["name"] == "broken_report")
            self.assertFalse(broken["validation"]["valid"])
            self.assertGreater(len(broken["validation"]["issues"]), 0)

    def test_generate_html_report(self):
        from bo_export.batch_report import validate_batch_output, generate_batch_report
        with tempfile.TemporaryDirectory() as tmp:
            self._make_batch_output(tmp)
            result = validate_batch_output(tmp)
            report_path = os.path.join(tmp, "report.html")
            output = generate_batch_report(result, report_path)
            self.assertTrue(os.path.isfile(output))
            with open(output, "r", encoding="utf-8") as f:
                html_content = f.read()
            self.assertIn("BIAR Batch Migration Report", html_content)
            self.assertIn("sales_report", html_content)
            self.assertIn("broken_report", html_content)
            self.assertIn("50%", html_content)  # 1/2 = 50% success rate

    def test_generate_migration_report_links_from_custom_location(self):
        from bo_export.batch_report import generate_migration_batch_report
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = os.path.join(tmp, "output")
            rdl_dir = os.path.join(output_dir, "Sales.wid", "PaginatedReport")
            os.makedirs(rdl_dir)
            for filename in ("report.rdl", "query.m"):
                with open(os.path.join(rdl_dir, filename), "w", encoding="utf-8") as handle:
                    handle.write("fixture")
            manifest = {
                "artifacts": [{
                    "source": "<script>alert(1)</script>.wid",
                    "source_kind": "webi",
                    "status": "success",
                    "targets": {
                        "paginated": {
                            "status": "success",
                            "output_dir": rdl_dir,
                            "error": None,
                        },
                    },
                    "warnings": ["Review selected query"],
                }],
                "skipped": [],
            }
            with open(os.path.join(output_dir, "batch_manifest.json"), "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
            report_path = os.path.join(tmp, "migration.html")
            generate_migration_batch_report(output_dir, report_path)

            with open(report_path, "r", encoding="utf-8") as handle:
                report_html = handle.read()
            self.assertIn('href="output/Sales.wid/PaginatedReport/report.rdl"', report_html)
            self.assertIn('href="output/Sales.wid/PaginatedReport/query.m"', report_html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;.wid", report_html)
            self.assertNotIn("<script>alert(1)</script>", report_html)
            self.assertIn("Review selected query", report_html)
            self.assertIn("does not prove", report_html)
            self.assertIn(".table-wrap", report_html)

    def test_generate_migration_report_omits_symlinked_external_artifact(self):
        from bo_export.batch_report import generate_migration_batch_report
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = os.path.join(tmp, "output")
            rdl_dir = os.path.join(output_dir, "Sales.wid", "PaginatedReport")
            os.makedirs(rdl_dir)
            external_report = os.path.join(tmp, "outside.rdl")
            with open(external_report, "w", encoding="utf-8") as handle:
                handle.write("fixture")
            try:
                os.symlink(external_report, os.path.join(rdl_dir, "report.rdl"))
            except OSError:
                self.skipTest("File symlinks are unavailable")
            manifest = {
                "artifacts": [{
                    "source": "Sales.wid",
                    "source_kind": "webi",
                    "targets": {"paginated": {"status": "success", "output_dir": rdl_dir}},
                }],
                "skipped": [],
            }
            with open(os.path.join(output_dir, "batch_manifest.json"), "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
            report_path = generate_migration_batch_report(output_dir)
            with open(report_path, "r", encoding="utf-8") as handle:
                report_html = handle.read()
            self.assertNotIn('href="Sales.wid/PaginatedReport/report.rdl"', report_html)


if __name__ == "__main__":
    unittest.main()
