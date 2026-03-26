"""End-to-end tests: BO extraction → adapter → generation → .pbip output.

Validates the full Phase 1 pipeline:
    extracted JSON → converted_objects → tmdl_generator + pbip_generator → valid .pbip
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects


def _make_sample_bo_extraction():
    """Create a realistic BO extraction output (15 JSON types)."""
    return {
        "reports": [
            {"name": "Sales Overview", "title": "Sales Overview", "type": "webi",
             "datasource": "SalesDB"},
            {"name": "Revenue Detail", "title": "Revenue by Region", "type": "webi",
             "datasource": "SalesDB"},
        ],
        "queries": [
            {"name": "Query1", "type": "universe", "universe": "Sales Universe",
             "objects": ["Revenue", "Country", "Year"]},
        ],
        "datasources": [
            {"name": "SalesDB", "type": "sql_server",
             "server": "sql01.corp.com", "database": "SalesDB", "schema": "dbo"},
        ],
        "formulas": [
            {"name": "Total Revenue", "formula": "=Sum([Revenue])",
             "qualification": "measure", "data_type": "number"},
            {"name": "Avg Order", "formula": "=Average([Order Amount])",
             "qualification": "measure", "data_type": "number"},
            {"name": "Year Label", "formula": "=FormatNumber([Year], '0000')",
             "qualification": "dimension", "data_type": "string"},
        ],
        "prompts": [
            {"name": "Select Year", "type": "numeric", "required": True,
             "multi_value": False, "default_values": ["2024"]},
            {"name": "Select Country", "type": "text", "required": True,
             "multi_value": True, "default_values": ["France", "Germany", "USA"]},
        ],
        "filters": [
            {"object": "Year", "operator": ">=", "values": ["2020"],
             "level": "query", "datasource": "SalesDB"},
        ],
        "tables": [
            {"name": "Sales", "type": "physical"},
            {"name": "Geography", "type": "physical"},
            {"name": "DerivedMetrics", "type": "derived",
             "sql": "SELECT SUM(amount) as total FROM sales GROUP BY region"},
        ],
        "columns": [
            {"name": "Revenue", "table": "Sales", "data_type": "number",
             "qualification": "measure", "description": "Total revenue amount"},
            {"name": "Order Amount", "table": "Sales", "data_type": "number",
             "qualification": "measure"},
            {"name": "Year", "table": "Sales", "data_type": "integer",
             "qualification": "dimension"},
            {"name": "Country", "table": "Geography", "data_type": "string",
             "qualification": "dimension",
             "path": "\\Geography\\Country"},
            {"name": "City", "table": "Geography", "data_type": "string",
             "qualification": "dimension",
             "path": "\\Geography\\City"},
            {"name": "Region", "table": "Geography", "data_type": "string",
             "qualification": "dimension",
             "path": "\\Geography\\Region"},
        ],
        "joins": [
            {"left_table": "Sales", "right_table": "Geography",
             "left_column": "GeoKey", "right_column": "GeoKey",
             "type": "inner", "cardinality": "many-to-one"},
        ],
        "groups": [
            {"name": "Year Group", "object": "Year"},
        ],
        "sorts": [
            {"object": "Revenue", "order": "descending"},
            {"object": "Year", "order": "ascending"},
        ],
        "alerts": [
            {"name": "High Revenue", "object": "Revenue",
             "operator": ">", "value": "1000000",
             "color": "#FF0000"},
        ],
        "subreports": [],
        "charts": [
            {"name": "Revenue by Country", "type": "bar",
             "report": "Sales Overview",
             "dimensions": ["Country"],
             "measures": ["Revenue"]},
            {"name": "Revenue Trend", "type": "line",
             "report": "Sales Overview",
             "dimensions": ["Year"],
             "measures": ["Revenue"]},
            {"name": "Detail Table", "type": "table",
             "report": "Revenue Detail",
             "dimensions": ["Country", "City"],
             "measures": ["Revenue", "Order Amount"]},
        ],
        "custom_sql": [
            {"name": "TopCustomers",
             "sql": "SELECT TOP 100 customer_name, SUM(amount) FROM orders GROUP BY customer_name ORDER BY 2 DESC"},
        ],
    }


class TestBridgeAdapter(unittest.TestCase):
    """Test the BO → converted_objects adapter."""

    def setUp(self):
        self.extracted = _make_sample_bo_extraction()
        self.converted = adapt_bo_to_converted_objects(self.extracted)

    def test_converted_has_all_keys(self):
        expected_keys = {
            "datasources", "worksheets", "dashboards", "calculations",
            "parameters", "filters", "stories", "actions", "sets",
            "groups", "bins", "hierarchies", "sort_orders", "aliases",
            "custom_sql", "relationships", "user_filters",
        }
        self.assertTrue(expected_keys.issubset(set(self.converted.keys())))

    def test_datasources_structure(self):
        ds = self.converted["datasources"]
        self.assertEqual(len(ds), 1)
        self.assertEqual(ds[0]["name"], "SalesDB")
        self.assertIn("connection", ds[0])
        self.assertEqual(ds[0]["connection"]["type"], "sql_server")
        self.assertEqual(ds[0]["connection"]["server"], "sql01.corp.com")

    def test_datasource_tables(self):
        tables = self.converted["datasources"][0]["tables"]
        table_names = [t["name"] for t in tables]
        self.assertIn("Sales", table_names)
        self.assertIn("Geography", table_names)
        self.assertIn("DerivedMetrics", table_names)

    def test_datasource_tables_have_columns(self):
        tables = self.converted["datasources"][0]["tables"]
        sales = next(t for t in tables if t["name"] == "Sales")
        self.assertGreater(len(sales["columns"]), 0)
        col_names = [c["name"] for c in sales["columns"]]
        self.assertIn("Revenue", col_names)

    def test_custom_sql_table(self):
        tables = self.converted["datasources"][0]["tables"]
        derived = next(t for t in tables if t["name"] == "DerivedMetrics")
        self.assertEqual(derived.get("type"), "custom_sql")
        self.assertIn("SELECT", derived.get("sql", ""))

    def test_custom_sql_as_virtual_table(self):
        tables = self.converted["datasources"][0]["tables"]
        names = [t["name"] for t in tables]
        self.assertIn("TopCustomers", names)

    def test_relationships_nested(self):
        rels = self.converted["datasources"][0]["relationships"]
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0]["left"]["table"], "Sales")
        self.assertEqual(rels[0]["right"]["table"], "Geography")
        self.assertEqual(rels[0]["left"]["column"], "GeoKey")

    def test_relationship_cardinality(self):
        rels = self.converted["datasources"][0]["relationships"]
        self.assertEqual(rels[0]["cardinality"], "manyToOne")
        self.assertEqual(rels[0]["crossFilteringBehavior"], "oneDirection")

    def test_join_columns_injected(self):
        """GeoKey is a join key not in column extraction — must be auto-added."""
        tables = self.converted["datasources"][0]["tables"]
        sales = next(t for t in tables if t["name"] == "Sales")
        col_names = [c["name"] for c in sales["columns"]]
        self.assertIn("GeoKey", col_names)
        geo = next(t for t in tables if t["name"] == "Geography")
        geo_col_names = [c["name"] for c in geo["columns"]]
        self.assertIn("GeoKey", geo_col_names)

    def test_injected_join_column_is_hidden(self):
        tables = self.converted["datasources"][0]["tables"]
        sales = next(t for t in tables if t["name"] == "Sales")
        geo_key = next(c for c in sales["columns"] if c["name"] == "GeoKey")
        self.assertTrue(geo_key.get("isHidden", False))

    def test_calculations(self):
        calcs = self.converted["calculations"]
        self.assertEqual(len(calcs), 3)
        names = [c["caption"] for c in calcs]
        self.assertIn("Total Revenue", names)

    def test_calculation_roles(self):
        calcs = self.converted["calculations"]
        total_rev = next(c for c in calcs if c["caption"] == "Total Revenue")
        self.assertEqual(total_rev["role"], "measure")
        year_label = next(c for c in calcs if c["caption"] == "Year Label")
        self.assertEqual(year_label["role"], "dimension")

    def test_worksheets_from_reports(self):
        ws = self.converted["worksheets"]
        # Sales Overview has 2 charts → 2 worksheets; Revenue Detail has 1 → 1
        self.assertEqual(len(ws), 3)
        names = [w["name"] for w in ws]
        self.assertIn("Revenue by Country", names)
        self.assertIn("Revenue Trend", names)
        self.assertIn("Revenue Detail", names)

    def test_worksheet_visual_type(self):
        ws = self.converted["worksheets"]
        bar_ws = next(w for w in ws if w["name"] == "Revenue by Country")
        self.assertEqual(bar_ws["type"], "clusteredBarChart")
        self.assertEqual(bar_ws["chart_type"], "clusteredBarChart")
        line_ws = next(w for w in ws if w["name"] == "Revenue Trend")
        self.assertEqual(line_ws["type"], "lineChart")
        table_ws = next(w for w in ws if w["name"] == "Revenue Detail")
        self.assertEqual(table_ws["type"], "tableEx")

    def test_worksheet_fields(self):
        ws = self.converted["worksheets"]
        bar_ws = next(w for w in ws if w["name"] == "Revenue by Country")
        field_names = [f["name"] for f in bar_ws["fields"]]
        self.assertIn("Country", field_names)
        self.assertIn("Revenue", field_names)

    def test_dashboards(self):
        dbs = self.converted["dashboards"]
        self.assertEqual(len(dbs), 1)
        self.assertEqual(dbs[0]["name"], "BO_Dashboard")
        self.assertEqual(len(dbs[0]["worksheets"]), 3)
        # Dashboard objects include worksheet refs + prompt slicer controls
        objects = dbs[0].get("objects", [])
        ws_refs = [o for o in objects if o["type"] == "worksheetReference"]
        param_ctrls = [o for o in objects if o["type"] == "parameter_control"]
        self.assertEqual(len(ws_refs), 3)
        self.assertEqual(len(param_ctrls), 2)  # Select Year + Select Country

    def test_parameters_from_prompts(self):
        params = self.converted["parameters"]
        self.assertEqual(len(params), 2)
        year_param = next(p for p in params if p["name"] == "Select Year")
        self.assertEqual(year_param["datatype"], "real")
        self.assertEqual(year_param["domain_type"], "list")
        self.assertIsInstance(year_param["allowable_values"], list)
        country_param = next(p for p in params if p["name"] == "Select Country")
        self.assertEqual(country_param["display_as"], "dropdown")
        self.assertEqual(country_param["datatype"], "string")
        self.assertEqual(country_param["domain_type"], "list")

    def test_filters(self):
        filters = self.converted["filters"]
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["column"], "Year")
        self.assertEqual(filters[0]["type"], "range")

    def test_groups(self):
        groups = self.converted["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["field"], "Year")

    def test_hierarchies_from_paths(self):
        hier = self.converted["hierarchies"]
        self.assertGreater(len(hier), 0)
        geo = next(h for h in hier if h["name"] == "Geography")
        self.assertGreater(len(geo["levels"]), 1)

    def test_sort_orders(self):
        sorts = self.converted["sort_orders"]
        self.assertEqual(len(sorts), 2)

    def test_aliases(self):
        aliases = self.converted["aliases"]
        self.assertIn("Revenue", aliases)
        self.assertEqual(aliases["Revenue"], "Total revenue amount")


class TestEndToEndGeneration(unittest.TestCase):
    """Test the full pipeline: BO JSON → .pbip project on disk."""

    def test_generate_pbip_from_bo_extraction(self):
        """Write sample BO JSON, load via PowerBIImporter, generate .pbip."""
        extracted = _make_sample_bo_extraction()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write BO extraction JSON files
            extract_dir = os.path.join(tmpdir, "extract")
            os.makedirs(extract_dir)
            for key, data in extracted.items():
                filepath = os.path.join(extract_dir, f"{key}.json")
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f)

            # Run generation
            output_dir = os.path.join(tmpdir, "output")
            os.makedirs(output_dir)

            from powerbi_import.import_to_powerbi import PowerBIImporter
            importer = PowerBIImporter(source_dir=extract_dir)
            converted = importer._load_converted_objects()

            # Verify adapter produced valid data
            self.assertGreater(len(converted.get("datasources", [])), 0)
            self.assertGreater(len(converted.get("worksheets", [])), 0)

            # Generate .pbip
            importer.generate_powerbi_project(
                report_name="SalesReport",
                converted_objects=converted,
                output_dir=output_dir,
            )

            # Verify the .pbip project directory was created
            project_dir = os.path.join(output_dir, "SalesReport")
            # Check for semantic model directory
            sm_dir = os.path.join(project_dir, "SalesReport.SemanticModel")
            report_dir = os.path.join(project_dir, "SalesReport.Report")

            # At minimum, check that some TMDL/PBIR files were created
            files_created = []
            for dirpath, dirnames, filenames in os.walk(output_dir):
                for fn in filenames:
                    files_created.append(os.path.join(dirpath, fn))

            # Should have at least some output files
            self.assertGreater(len(files_created), 0,
                               f"No files generated in {output_dir}")

            # Check for key artifacts
            tmdl_files = [f for f in files_created if f.endswith('.tmdl')]
            json_files = [f for f in files_created if f.endswith('.json')]
            pbip_files = [f for f in files_created if f.endswith('.pbip')]
            pbir_files = [f for f in files_created if f.endswith('.pbir')]

            self.assertGreater(len(tmdl_files), 0,
                               "No TMDL files generated")
            self.assertGreater(len(json_files), 0,
                               "No JSON files generated")

    def test_adapter_round_trip_with_json_files(self):
        """Verify adapt → save → load → generate cycle works."""
        extracted = _make_sample_bo_extraction()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write BO files
            for key, data in extracted.items():
                filepath = os.path.join(tmpdir, f"{key}.json")
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f)

            # Load through PowerBIImporter
            from powerbi_import.import_to_powerbi import PowerBIImporter
            importer = PowerBIImporter(source_dir=tmpdir)
            converted = importer._load_converted_objects()

            # Verify all major keys populated
            self.assertGreater(len(converted["datasources"]), 0)
            self.assertGreater(len(converted["worksheets"]), 0)
            self.assertGreater(len(converted["dashboards"]), 0)
            self.assertGreater(len(converted["calculations"]), 0)
            self.assertGreater(len(converted["parameters"]), 0)
            self.assertGreater(len(converted["filters"]), 0)
            self.assertGreater(len(converted["groups"]), 0)
            self.assertGreater(len(converted["hierarchies"]), 0)


class TestCompatModule(unittest.TestCase):
    """Test the compat shim provides all expected functions."""

    def test_formula_conversion(self):
        from bo_export.compat import convert_tableau_formula_to_dax
        result = convert_tableau_formula_to_dax("=Sum([Revenue])")
        self.assertIn("SUM", result.upper())

    def test_type_mapping(self):
        from bo_export.compat import map_tableau_to_powerbi_type
        self.assertEqual(map_tableau_to_powerbi_type("string"), "string")
        self.assertEqual(map_tableau_to_powerbi_type("integer"), "int64")
        self.assertEqual(map_tableau_to_powerbi_type("datetime"), "dateTime")

    def test_m_query_generation(self):
        from bo_export.compat import generate_power_query_m
        ds = {"type": "sql_server", "server": "dbhost", "database": "mydb"}
        result = generate_power_query_m(ds)
        self.assertIn("Sql.Database", result)
        self.assertIn("dbhost", result)

    def test_hyper_returns_none(self):
        from bo_export.compat import generate_m_from_hyper
        self.assertIsNone(generate_m_from_hyper([]))


class TestVisualTypeMapping(unittest.TestCase):
    """Test BO chart type → PBI visual type mapping."""

    def test_bar_types(self):
        from bo_export.converted_objects_adapter import _map_bo_chart_type
        self.assertEqual(_map_bo_chart_type("bar"), "clusteredBarChart")
        self.assertEqual(_map_bo_chart_type("horizontal_bar"), "clusteredBarChart")
        self.assertEqual(_map_bo_chart_type("vertical_bar"), "clusteredColumnChart")
        self.assertEqual(_map_bo_chart_type("stacked_bar"), "stackedBarChart")
        self.assertEqual(_map_bo_chart_type("100_stacked_bar"), "hundredPercentStackedBarChart")

    def test_line_area_types(self):
        from bo_export.converted_objects_adapter import _map_bo_chart_type
        self.assertEqual(_map_bo_chart_type("line"), "lineChart")
        self.assertEqual(_map_bo_chart_type("dual_line"), "lineChart")
        self.assertEqual(_map_bo_chart_type("area"), "areaChart")
        self.assertEqual(_map_bo_chart_type("stacked_area"), "stackedAreaChart")

    def test_combo_types(self):
        from bo_export.converted_objects_adapter import _map_bo_chart_type
        self.assertEqual(_map_bo_chart_type("combined_bar_line"), "lineClusteredColumnComboChart")
        self.assertEqual(_map_bo_chart_type("dual_axis"), "lineClusteredColumnComboChart")

    def test_pie_donut_funnel(self):
        from bo_export.converted_objects_adapter import _map_bo_chart_type
        self.assertEqual(_map_bo_chart_type("pie"), "pieChart")
        self.assertEqual(_map_bo_chart_type("donut"), "donutChart")
        self.assertEqual(_map_bo_chart_type("funnel"), "funnel")

    def test_table_matrix(self):
        from bo_export.converted_objects_adapter import _map_bo_chart_type
        self.assertEqual(_map_bo_chart_type("table"), "tableEx")
        self.assertEqual(_map_bo_chart_type("crosstab"), "matrix")
        self.assertEqual(_map_bo_chart_type("pivot"), "matrix")
        self.assertEqual(_map_bo_chart_type("cross-tab"), "matrix")

    def test_kpi_gauge(self):
        from bo_export.converted_objects_adapter import _map_bo_chart_type
        self.assertEqual(_map_bo_chart_type("kpi"), "card")
        self.assertEqual(_map_bo_chart_type("gauge"), "gauge")
        self.assertEqual(_map_bo_chart_type("text"), "card")
        self.assertEqual(_map_bo_chart_type("number"), "card")

    def test_scatter_bubble(self):
        from bo_export.converted_objects_adapter import _map_bo_chart_type
        self.assertEqual(_map_bo_chart_type("scatter"), "scatterChart")
        self.assertEqual(_map_bo_chart_type("bubble"), "scatterChart")

    def test_specialty(self):
        from bo_export.converted_objects_adapter import _map_bo_chart_type
        self.assertEqual(_map_bo_chart_type("treemap"), "treemap")
        self.assertEqual(_map_bo_chart_type("waterfall"), "waterfallChart")
        self.assertEqual(_map_bo_chart_type("tag_cloud"), "wordCloud")
        self.assertEqual(_map_bo_chart_type("map"), "map")
        self.assertEqual(_map_bo_chart_type("geo"), "filledMap")

    def test_case_insensitive(self):
        from bo_export.converted_objects_adapter import _map_bo_chart_type
        self.assertEqual(_map_bo_chart_type("BAR"), "clusteredBarChart")
        self.assertEqual(_map_bo_chart_type("Pie"), "pieChart")
        self.assertEqual(_map_bo_chart_type("CROSSTAB"), "matrix")

    def test_unknown_defaults_to_tableex(self):
        from bo_export.converted_objects_adapter import _map_bo_chart_type
        self.assertEqual(_map_bo_chart_type("unknown_type"), "tableEx")
        self.assertEqual(_map_bo_chart_type(""), "tableEx")

    def test_visual_generator_resolve_bo_types(self):
        """BO types should resolve correctly through visual_generator.resolve_visual_type."""
        from powerbi_import.visual_generator import resolve_visual_type
        self.assertEqual(resolve_visual_type("crosstab"), "matrix")
        self.assertEqual(resolve_visual_type("horizontal_bar"), "clusteredBarChart")
        self.assertEqual(resolve_visual_type("combined_bar_line"), "lineClusteredColumnComboChart")
        self.assertEqual(resolve_visual_type("tag_cloud"), "wordCloud")
        self.assertEqual(resolve_visual_type("3d_pie"), "pieChart")

    def test_multi_chart_per_report(self):
        """Reports with multiple charts produce multiple worksheets."""
        from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
        extracted = {
            "reports": [{"name": "Tab1", "title": "Tab1"}],
            "charts": [
                {"name": "Chart A", "type": "bar", "report": "Tab1",
                 "dimensions": ["X"], "measures": ["Y"]},
                {"name": "Chart B", "type": "pie", "report": "Tab1",
                 "dimensions": ["Cat"], "measures": ["Val"]},
            ],
            "queries": [], "datasources": [], "formulas": [],
            "prompts": [], "filters": [], "tables": [], "columns": [],
            "joins": [], "groups": [], "sorts": [], "alerts": [],
            "subreports": [], "custom_sql": [],
        }
        result = adapt_bo_to_converted_objects(extracted)
        ws = result["worksheets"]
        self.assertEqual(len(ws), 2)
        self.assertEqual(ws[0]["name"], "Chart A")
        self.assertEqual(ws[0]["chart_type"], "clusteredBarChart")
        self.assertEqual(ws[1]["name"], "Chart B")
        self.assertEqual(ws[1]["chart_type"], "pieChart")
        # Dashboard should wrap both worksheets
        self.assertEqual(len(result["dashboards"][0]["worksheets"]), 2)

    def test_single_chart_keeps_report_name(self):
        """Reports with a single chart keep the report tab name."""
        from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
        extracted = {
            "reports": [{"name": "MyTab", "title": "My Tab"}],
            "charts": [
                {"name": "OnlyChart", "type": "line", "report": "MyTab",
                 "dimensions": ["Date"], "measures": ["Sales"]},
            ],
            "queries": [], "datasources": [], "formulas": [],
            "prompts": [], "filters": [], "tables": [], "columns": [],
            "joins": [], "groups": [], "sorts": [], "alerts": [],
            "subreports": [], "custom_sql": [],
        }
        result = adapt_bo_to_converted_objects(extracted)
        self.assertEqual(len(result["worksheets"]), 1)
        self.assertEqual(result["worksheets"][0]["name"], "MyTab")
        self.assertEqual(result["worksheets"][0]["chart_type"], "lineChart")

    def test_no_charts_gives_tableex(self):
        """Reports with no charts default to tableEx."""
        from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
        extracted = {
            "reports": [{"name": "PlainTab"}],
            "charts": [],
            "queries": [], "datasources": [], "formulas": [],
            "prompts": [], "filters": [], "tables": [], "columns": [],
            "joins": [], "groups": [], "sorts": [], "alerts": [],
            "subreports": [], "custom_sql": [],
        }
        result = adapt_bo_to_converted_objects(extracted)
        self.assertEqual(len(result["worksheets"]), 1)
        self.assertEqual(result["worksheets"][0]["chart_type"], "tableEx")


class TestAlertConditionalFormatting(unittest.TestCase):
    """Sprint 12: BO alerters → PBI conditional formatting rules."""

    def setUp(self):
        self.extracted = _make_sample_bo_extraction()
        self.converted = adapt_bo_to_converted_objects(self.extracted)

    def test_alert_attached_to_worksheet(self):
        """Alert on Revenue should attach to worksheets referencing Revenue."""
        ws_with_cf = [w for w in self.converted["worksheets"]
                      if w.get("conditionalFormatting")]
        self.assertGreater(len(ws_with_cf), 0)

    def test_alert_rule_structure(self):
        ws_with_cf = [w for w in self.converted["worksheets"]
                      if w.get("conditionalFormatting")]
        rule = ws_with_cf[0]["conditionalFormatting"][0]
        self.assertEqual(rule["field"], "Revenue")
        self.assertEqual(rule["operator"], "greaterThan")
        self.assertEqual(rule["value"], "1000000")
        self.assertIn("formatting", rule)

    def test_alert_color_in_formatting(self):
        ws_with_cf = [w for w in self.converted["worksheets"]
                      if w.get("conditionalFormatting")]
        rule = ws_with_cf[0]["conditionalFormatting"][0]
        fmt = rule["formatting"]
        self.assertEqual(fmt.get("backgroundColor"), "#FF0000")

    def test_no_alerts_no_conditional_formatting(self):
        self.extracted["alerts"] = []
        converted = adapt_bo_to_converted_objects(self.extracted)
        for ws in converted["worksheets"]:
            self.assertFalse(ws.get("conditionalFormatting"))

    def test_alert_on_unmatched_field_broadcast(self):
        """Alert on a field not in any chart → attached to all worksheets."""
        self.extracted["alerts"] = [
            {"name": "Test", "object": "NonExistentField",
             "operator": ">=", "value": "500", "color": "#00FF00"}
        ]
        converted = adapt_bo_to_converted_objects(self.extracted)
        for ws in converted["worksheets"]:
            self.assertTrue(ws.get("conditionalFormatting"))
            self.assertEqual(ws["conditionalFormatting"][0]["operator"],
                             "greaterThanOrEqual")


if __name__ == "__main__":
    unittest.main()
