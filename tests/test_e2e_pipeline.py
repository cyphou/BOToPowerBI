"""End-to-end tests: BO extraction → adapter → generation → .pbip output.

Validates the full Phase 1 pipeline:
    extracted JSON → converted_objects → tmdl_generator + pbip_generator → valid .pbip
"""

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
from bo_export.lumira_extractor import extract_lumira


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


class TestLumiraObjectExtraction(unittest.TestCase):
    def test_explicit_table_and_chart_bindings_are_preserved(self):
        metadata = {
            "datasets": [{"name": "Sales"}],
            "dimensions": [
                {"name": "Région", "type": "string", "table": "Sales"},
                {"name": "Unassigned", "type": "string"},
            ],
            "measures": [{"name": "Revenue", "type": "decimal", "table": "Sales"}],
            "pages": [{"name": "Overview"}],
            "visualizations": [
                {"name": "Sales chart", "type": "bar", "report": "Overview",
                 "dimensions": ["Région"], "measures": ["Revenue"]},
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = os.path.join(temporary, "sample.lumx")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("metadata.json", json.dumps(metadata))
            extracted = extract_lumira(path)

        columns = {column["name"]: column for column in extracted["columns"]}
        self.assertEqual(columns["Région"]["table"], "Sales")
        self.assertEqual(columns["Revenue"]["table"], "Sales")
        self.assertNotIn("table", columns["Unassigned"])
        chart = extracted["charts"][0]
        self.assertEqual(chart["report"], "Overview")
        self.assertEqual(chart["dimensions"], ["Région"])
        self.assertEqual(chart["measures"], ["Revenue"])
        converted = adapt_bo_to_converted_objects(extracted)
        sales = converted["datasources"][0]["tables"][0]
        self.assertEqual({column["name"] for column in sales["columns"]},
                         {"Région", "Revenue"})
        self.assertEqual(
            [field["name"] for field in converted["worksheets"][0]["fields"]],
            ["Région", "Revenue"],
        )


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

    def test_unlinked_charts_are_not_discarded_or_assigned_to_source_reports(self):
        extracted = {
            "reports": [{"name": "Overview"}],
            "charts": [
                {"name": "Bound", "type": "bar", "report": "Overview",
                 "dimensions": ["Region"], "measures": ["Revenue"]},
                {"name": "Trend", "type": "line",
                 "dimensions": ["Year"], "measures": ["Revenue"]},
                {"name": "Overview", "type": "pie", "tab": "Missing"},
            ],
        }

        converted = adapt_bo_to_converted_objects(extracted)
        worksheets = {ws["name"]: ws for ws in converted["worksheets"]}

        self.assertEqual(set(worksheets), {"Overview", "Trend", "Overview (2)"})
        self.assertEqual(worksheets["Overview"]["chart_type"], "clusteredBarChart")
        self.assertEqual(worksheets["Trend"]["chart_type"], "lineChart")
        self.assertEqual(worksheets["Overview (2)"]["chart_type"], "pieChart")
        self.assertEqual(
            [field["name"] for field in worksheets["Trend"]["fields"]],
            ["Year", "Revenue"],
        )
        dashboards = {dashboard["name"]: dashboard for dashboard in converted["dashboards"]}
        self.assertEqual(dashboards["BO_Dashboard"]["worksheets"], ["Overview"])
        self.assertEqual(
            dashboards["BO_Unassigned_Charts"]["worksheets"], ["Trend", "Overview (2)"]
        )

    def test_charts_without_reports_are_flagged_without_dropping_prompts(self):
        converted = adapt_bo_to_converted_objects({
            "charts": [{"name": "Trend", "type": "line"}],
            "prompts": [{"name": "Choose region", "type": "text"}],
        })

        self.assertTrue(converted["worksheets"][0]["source_chart_unlinked"])
        self.assertEqual(converted["dashboards"][0]["name"], "BO_Unassigned_Charts")
        self.assertEqual(
            [obj["type"] for obj in converted["dashboards"][0]["objects"]],
            ["worksheetReference", "parameter_control"],
        )

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


class TestNotebookSessionIsolation(unittest.TestCase):
    def test_sessions_do_not_write_or_share_extractions_in_source_tree(self):
        from bo_export.extract_bo_data import extract_bo_data
        from powerbi_import.notebook_api import MigrationSession

        repo = Path(__file__).resolve().parents[1]
        extraction_dirs = []

        def guarded_extract(path, output_dir):
            output = Path(output_dir).resolve()
            self.assertNotEqual(output, (repo / "bo_export").resolve())
            extraction_dirs.append(output)
            return extract_bo_data(path, output_dir)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = MigrationSession()
            second = MigrationSession()
            with patch("bo_export.extract_bo_data.extract_bo_data", side_effect=guarded_extract):
                first.load(str(repo / "examples" / "Enterprise_Sales.wid"))
                second.load(str(repo / "examples" / "HR_Analytics.wid"))

            self.assertEqual(len(set(extraction_dirs)), 2)
            self.assertTrue(all(not path.exists() for path in extraction_dirs))
            first.generate(str(root / "sales"))
            second.generate(str(root / "hr"))
            first_tables = {p.stem for p in (root / "sales").rglob("*.tmdl")
                            if p.parent.name == "tables"}
            second_tables = {p.stem for p in (root / "hr").rglob("*.tmdl")
                             if p.parent.name == "tables"}
            self.assertIn("FACT_SALES", first_tables)
            self.assertNotIn("DIM_EMPLOYEE", first_tables)
            self.assertIn("DIM_EMPLOYEE", second_tables)
            self.assertNotIn("FACT_SALES", second_tables)


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

    def test_native_stacked_combo_chart_is_preserved(self):
        from powerbi_import.visual_generator import (
            create_visual_container, resolve_custom_visual_type, resolve_visual_type,
        )

        visual_type = "lineStackedColumnComboChart"
        for source in (visual_type, visual_type.upper()):
            with self.subTest(source=source):
                self.assertEqual(resolve_visual_type(source), visual_type)
                self.assertEqual(resolve_custom_visual_type(source), (visual_type, None))
                visual = create_visual_container({"name": "Sales", "visualType": source})
                self.assertEqual(visual["visual"]["visualType"], visual_type)

    def test_combo_queries_bind_independent_column_and_line_values(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator
        from powerbi_import.visual_generator import create_visual_container

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            generator._build_field_mapping({
                "datasources": [{"tables": [{
                    "name": "Sales",
                    "columns": [
                        {"name": "Country", "role": "dimension"},
                        {"name": "Revenue", "role": "measure"},
                        {"name": "Cost", "role": "measure"},
                    ],
                }]}],
            })
            for visual_type in ("lineStackedColumnComboChart", "lineClusteredColumnComboChart"):
                with self.subTest(visual_type=visual_type):
                    query = generator._build_visual_query({
                        "chart_type": visual_type,
                        "fields": [
                            {"name": "Country", "role": "dimension"},
                            {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
                            {"name": "Cost", "role": "measure", "aggregation": "SUM"},
                        ],
                    })["queryState"]
                    self.assertEqual(set(query), {"Category", "Y", "Y2"})
                    category = query["Category"]["projections"][0]
                    self.assertEqual(category["nativeQueryRef"], "Country")
                    for role, name in (("Y", "Revenue"), ("Y2", "Cost")):
                        projection = query[role]["projections"][0]
                        self.assertEqual(projection["field"]["Aggregation"]["Function"], 0)
                        self.assertEqual(projection["queryRef"], f"Sum(Sales.{name})")
                        self.assertEqual(projection["nativeQueryRef"], f"Sum of {name}")

                    visual = create_visual_container({
                        "name": "Combo",
                        "visualType": visual_type,
                        "dimensions": [{"name": "Country"}],
                        "measures": [{"name": "Revenue"}, {"name": "Cost"}],
                    }, col_table_map={"Country": "Sales"},
                        measure_lookup={"Revenue": ("Sales", "1"), "Cost": ("Sales", "2")})
                    state = visual["visual"]["query"]["queryState"]
                    self.assertEqual(set(state), {"Category", "Y", "Y2"})
                    self.assertEqual(state["Y"]["projections"][0]["nativeQueryRef"], "Revenue")
                    self.assertEqual(state["Y2"]["projections"][0]["nativeQueryRef"], "Cost")

                    visual = create_visual_container({
                        "name": "Combo",
                        "visualType": visual_type,
                        "dimensions": [{"name": "Country"}],
                        "measures": [
                            {"name": "Revenue", "expression": "SUM(Revenue)"},
                            {"name": "Cost", "expression": "AVG(Cost)"},
                        ],
                    }, col_table_map={"Country": "Sales", "Revenue": "Sales", "Cost": "Sales"})
                    state = visual["visual"]["query"]["queryState"]
                    for role, name, function, ref, native in (
                        ("Y", "Revenue", 0, "Sum", "Sum of Revenue"),
                        ("Y2", "Cost", 1, "Avg", "Average of Cost"),
                    ):
                        projection = state[role]["projections"][0]
                        self.assertEqual(projection["field"]["Aggregation"]["Function"], function)
                        self.assertEqual(projection["queryRef"], f"{ref}(Sales.{name})")
                        self.assertEqual(projection["nativeQueryRef"], native)

                    visual = create_visual_container({
                        "name": "Combo",
                        "visualType": visual_type,
                        "dimensions": [{"name": "Country"}],
                        "measures": [{"name": "Revenue"}],
                    }, col_table_map={"Country": "Sales"},
                        measure_lookup={"Revenue": ("Sales", "1")})
                    state = visual["visual"]["query"]["queryState"]
                    self.assertIn("Y", state)
                    self.assertNotIn("Y2", state)

    def test_bo_chart_field_roles_survive_missing_universe_column_metadata(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            generator._build_field_mapping({"datasources": []})
            state = generator._build_visual_query({
                "chart_type": "lineChart",
                "fields": [
                    {"name": "Year", "role": "dimension"},
                    {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
                    {"name": "Margin", "role": "measure", "aggregation": "SUM"},
                ],
            })["queryState"]
            self.assertEqual(set(state), {"Category", "Y"})
            values = state["Y"]["projections"]
            self.assertEqual(len(values), 2)
            self.assertTrue(all(value["field"]["Aggregation"]["Function"] == 0
                                for value in values))

            scatter = {
                "name": "Scatter",
                "chart_type": "scatterChart",
                "fields": [
                    {"name": "Country", "role": "dimension"},
                    {"name": "Region", "role": "dimension"},
                    {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
                    {"name": "Margin", "role": "measure", "aggregation": "SUM"},
                ],
            }
            generator._create_visual_worksheet(
                output, scatter, {"worksheetName": "Scatter"}, 1, 1, 0,
                [scatter], {"calculations": []},
            )
            path = next(Path(output).rglob("visual.json"))
            visual = json.loads(path.read_text(encoding="utf-8"))["visual"]
            self.assertEqual(visual["visualType"], "scatterChart")
            state = visual["query"]["queryState"]
            self.assertEqual(set(state), {"Category", "Series", "X", "Y"})
            self.assertEqual(len(state["Category"]["projections"]), 1)

    def test_filter_slicer_has_native_query_reference(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            slicer = generator._create_slicer_visual(
                "slicer", 0, 0, 200, 200, "[Country]", "Sales", 0,
            )
            projection = slicer["visual"]["query"]["queryState"]["Values"]["projections"][0]
            self.assertEqual(projection["queryRef"], "Sales.Country")
            self.assertEqual(projection["nativeQueryRef"], "Country")

    def test_unsupported_visual_aggregation_is_not_silently_summed(self):
        from powerbi_import.visual_generator import create_visual_container

        for expression in ("MEDIAN(Revenue)", "DISTINCTCOUNT(Revenue)"):
            with self.subTest(expression=expression):
                with self.assertLogs("powerbi_import.visual_generator", level="WARNING"):
                    visual = create_visual_container({
                        "name": "Chart",
                        "visualType": "lineChart",
                        "dimensions": [{"name": "Country"}],
                        "measures": [{"name": "Revenue", "expression": expression}],
                    }, col_table_map={"Country": "Sales", "Revenue": "Sales"})
                state = visual["visual"]["query"]["queryState"]
                self.assertNotIn("Y", state)

    def test_non_axis_visuals_do_not_receive_axis_formatting(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            for visual_type in ("pieChart", "donutChart", "tableEx"):
                with self.subTest(visual_type=visual_type):
                    objects = generator._build_visual_objects(
                        "Example", {"formatting": {}}, visual_type,
                    )
                    self.assertNotIn("categoryAxis", objects)
                    self.assertNotIn("valueAxis", objects)
            objects = generator._build_visual_objects("Example", {"formatting": {}}, "lineChart")
            self.assertIn("categoryAxis", objects)
            self.assertIn("valueAxis", objects)

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


class TestPBIPGeneratorCoverageSlices(unittest.TestCase):
    """Assert observable PBIR behavior across less-covered generator paths."""

    @staticmethod
    def _read_visual(visuals_dir):
        visual_path = next(Path(visuals_dir).glob("*/visual.json"))
        return json.loads(visual_path.read_text(encoding="utf-8"))

    @staticmethod
    def _read_visuals(visuals_dir):
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in Path(visuals_dir).glob("*/visual.json")
        ]

    @classmethod
    def _emit_worksheet(cls, output, worksheet):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        generator = PowerBIProjectGenerator(output)
        generator._used_custom_guids = {}
        generator._create_visual_worksheet(
            output, worksheet, {"worksheetName": worksheet["name"]},
            1, 1, 0, [worksheet], {"calculations": []},
        )
        return generator, cls._read_visual(output)

    def test_map_query_promotes_tooltip_location_and_color_measure_to_size(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            generator._build_field_mapping({"datasources": [{"tables": [{
                "name": "Sales",
                "columns": [
                    {"name": "Country"}, {"name": "Revenue"}, {"name": "Cost"},
                ],
            }]}]})
            query_state = generator._build_visual_query({
                "chart_type": "map",
                "fields": [
                    {"name": "Country", "role": "dimension", "shelf": "tooltip"},
                    {"name": "Revenue", "role": "measure", "shelf": "color"},
                    {"name": "Cost", "role": "measure", "shelf": "color"},
                ],
            })["queryState"]

        self.assertEqual(set(query_state), {"Category", "Size", "Tooltips"})
        self.assertEqual(
            query_state["Category"]["projections"][0]["nativeQueryRef"], "Country",
        )
        self.assertEqual(
            query_state["Size"]["projections"][0]["nativeQueryRef"], "Revenue",
        )
        self.assertEqual(
            [entry["nativeQueryRef"] for entry in query_state["Tooltips"]["projections"]],
              ["Cost"],
        )

    def test_worksheet_serializes_axis_and_analytics_settings(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        worksheet = {
            "name": "Monthly Revenue",
            "chart_type": "lineChart",
            "fields": [
                {"name": "Month", "role": "dimension"},
                {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
            ],
            "axes": {
                "x": {"title": "Month", "is_continuous": True,
                      "label_rotation": "45", "show_label": False},
                "y": {"title": "Revenue", "auto_range": False,
                      "range_min": 0, "range_max": 100, "scale": "log"},
            },
            "reference_lines": [{"value": 50, "label": "Target", "color": "#008800"}],
            "trend_lines": [{"type": "polynomial", "show_equation": True}],
            "annotations": [{"text": "Quarter target"}],
            "forecasting": [{"periods": 4, "prediction_interval": "90"}],
        }
        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            generator._create_visual_worksheet(
                output, worksheet, {"worksheetName": worksheet["name"]},
                1, 1, 0, [worksheet], {"calculations": []},
            )
            visual = self._read_visual(output)

        objects = visual["visual"]["objects"]
        category_axis = objects["categoryAxis"][0]["properties"]
        value_axis = objects["valueAxis"][0]["properties"]
        self.assertEqual(category_axis["show"]["expr"]["Literal"]["Value"], "false")
        self.assertEqual(category_axis["axisType"]["expr"]["Literal"]["Value"], "'Continuous'")
        self.assertEqual(value_axis["start"]["expr"]["Literal"]["Value"], "0D")
        self.assertEqual(value_axis["end"]["expr"]["Literal"]["Value"], "100D")
        self.assertEqual(value_axis["axisScale"]["expr"]["Literal"]["Value"], "'Log'")
        self.assertEqual(value_axis["referenceLine"][0]["value"], "50")
        self.assertEqual(
            objects["trend"][0]["properties"]["displayEquation"]["expr"]["Literal"]["Value"],
            "true",
        )
        self.assertIn("Quarter target", json.dumps(objects["subTitle"]))
        self.assertEqual(
            objects["forecast"][0]["properties"]["forecastLength"]["expr"]["Literal"]["Value"],
            "4L",
        )

    def test_categorical_palette_and_two_stop_gradient_emit_color_rules(self):
        cases = (
            ({
                "type": "categorical", "palette": "Tableau 10",
                "color_values": {"Retail": "#112233", "Online": "#445566"},
            }, ["#112233", "#445566"]),
            ({"type": "quantitative", "palette_colors": ["#102030", "#A0B0C0"]},
             ["#102030", "#A0B0C0"]),
        )
        for color_encoding, expected_colors in cases:
            with self.subTest(color_encoding=color_encoding), tempfile.TemporaryDirectory() as output:
                worksheet = {
                    "name": "Revenue colors",
                    "chart_type": "lineChart",
                    "fields": [
                        {"name": "Region", "role": "dimension"},
                        {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
                    ],
                    "mark_encoding": {"color": color_encoding},
                }
                _, emitted = self._emit_worksheet(output, worksheet)
                data_points = emitted["visual"]["objects"]["dataPoint"]

                if color_encoding["type"] == "categorical":
                    actual_colors = [
                        point["properties"]["fill"]["solid"]["color"]["expr"]["Literal"]["Value"]
                        for point in data_points
                    ]
                    self.assertEqual(actual_colors, [f"'{color}'" for color in expected_colors])
                else:
                    gradient = data_points[0]["rules"][0]["gradient"]
                    self.assertEqual(
                        gradient,
                        {
                            "min": {"color": {"expr": {"Literal": {"Value": "'#102030'"}}}},
                            "max": {"color": {"expr": {"Literal": {"Value": "'#A0B0C0'"}}}},
                        },
                    )
                    self.assertNotIn("mid", gradient)

    def test_stepped_color_thresholds_are_sorted_and_emitted_as_rules(self):
        worksheet = {
            "name": "Threshold colors",
            "chart_type": "clusteredColumnChart",
            "fields": [
                {"name": "Region", "role": "dimension"},
                {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
            ],
            "mark_encoding": {"color": {
                "type": "quantitative", "field": "Revenue",
                "thresholds": [
                    {"value": 100, "color": "#AA0000"},
                    {"value": 0, "color": "#00AA00"},
                    {"value": 50, "color": "#AAAA00"},
                ],
            }},
        }
        with tempfile.TemporaryDirectory() as output:
            _, emitted = self._emit_worksheet(output, worksheet)

        objects = emitted["visual"]["objects"]
        rules = objects["dataPoint"]
        self.assertEqual(
            [rule["properties"]["inputValue"]["expr"]["Literal"]["Value"] for rule in rules],
            ["0D", "50D", "100D"],
        )
        self.assertEqual(
            [rule["properties"]["operator"]["expr"]["Literal"]["Value"] for rule in rules],
            ["'LessThanOrEqual'", "'LessThanOrEqual'", "'GreaterThan'"],
        )
        self.assertEqual(
            [rule["properties"]["fill"]["solid"]["color"]["expr"]["Literal"]["Value"]
             for rule in rules],
            ["'#00AA00'", "'#AAAA00'", "'#AA0000'"],
        )
        self.assertEqual(
            objects["conditionalFormatting"][0]["properties"]["colorStyle"]["expr"]["Literal"]["Value"],
            "'rulesGradient'",
        )

    def test_statistical_band_and_median_line_are_emitted(self):
        worksheet = {
            "name": "Statistical range",
            "chart_type": "lineChart",
            "fields": [
                {"name": "Month", "role": "dimension"},
                {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
            ],
            "analytics_stats": [
                {"type": "distribution_band", "value_from": 20, "value_to": 40},
                {"type": "stat_line", "computation": "median"},
            ],
        }
        with tempfile.TemporaryDirectory() as output:
            _, emitted = self._emit_worksheet(output, worksheet)

        references = emitted["visual"]["objects"]["valueAxis"][0]["properties"]["referenceLine"]
        band, median = references
        self.assertEqual((band["type"], band["lowerBound"], band["upperBound"]),
                         ("Band", "20", "40"))
        self.assertEqual(band["transparency"]["expr"]["Literal"]["Value"], "50L")
        self.assertEqual(median["type"], "Median")
        self.assertEqual(median["show"]["expr"]["Literal"]["Value"], "true")
        self.assertEqual(median["style"]["expr"]["Literal"]["Value"], "'dashed'")

    def test_map_washout_and_dark_style_are_emitted(self):
        worksheet = {
            "name": "Regional map",
            "chart_type": "map",
            "fields": [
                {"name": "Region", "role": "dimension"},
                {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
            ],
            "map_options": {"washout": "0.35", "style": "dark"},
        }
        with tempfile.TemporaryDirectory() as output:
            _, emitted = self._emit_worksheet(output, worksheet)

        self.assertEqual(emitted["visual"]["visualType"], "map")
        map_properties = emitted["visual"]["objects"]["mapControl"][0]["properties"]
        self.assertEqual(map_properties["transparency"]["expr"]["Literal"]["Value"], "35L")
        self.assertEqual(map_properties["mapStyle"]["expr"]["Literal"]["Value"], "'darkGrayscale'")

    def test_pages_shelf_emits_small_multiple_settings_and_slicer_binding(self):
        worksheet = {
            "name": "Revenue by month",
            "chart_type": "lineChart",
            "fields": [
                {"name": "Month", "role": "dimension"},
                {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
            ],
            "pages_shelf": {"field": "Year"},
        }
        with tempfile.TemporaryDirectory() as output:
            _, emitted = self._emit_worksheet(output, worksheet)
            small_multiple = emitted["visual"]["objects"]["smallMultiple"][0]["properties"]
            self.assertEqual(small_multiple["layoutMode"]["expr"]["Literal"]["Value"], "'Flow'")
            self.assertEqual(small_multiple["showChartTitle"]["expr"]["Literal"]["Value"], "true")

            from powerbi_import.pbip_generator import PowerBIProjectGenerator
            generator = PowerBIProjectGenerator(output)
            converted = {"datasources": [{"tables": [{
                "name": "Sales", "columns": [{"name": "Year"}],
            }]}]}
            visuals_dir = os.path.join(output, "pages-shelf")
            generator._create_pages_shelf_slicer(
                visuals_dir, {"field": "Year"}, 1, 1, 0, converted,
            )
            slicer = self._read_visual(visuals_dir)["visual"]

        projection = slicer["query"]["queryState"]["Values"]["projections"][0]
        self.assertEqual(projection["field"]["Column"]["Expression"]["SourceRef"]["Entity"], "Sales")
        self.assertEqual(projection["field"]["Column"]["Property"], "Year")
        self.assertEqual(
            slicer["objects"]["general"][0]["properties"]["comments"]["expr"]["Literal"]["Value"],
            "'Pages Shelf / Play Axis: animate through values'",
        )

    def test_custom_visual_mark_emits_visual_type_and_repository_metadata(self):
        worksheet = {
            "name": "Flow by source",
            "chart_type": "tableEx",
            "original_mark_class": "sankey",
            "fields": [
                {"name": "Source", "role": "dimension"},
                {"name": "Destination", "role": "dimension"},
                {"name": "Weight", "role": "measure", "aggregation": "SUM"},
            ],
        }
        with tempfile.TemporaryDirectory() as output:
            generator, emitted = self._emit_worksheet(output, worksheet)

        self.assertEqual(emitted["visual"]["visualType"], "sankeyDiagram")
        self.assertEqual(
            generator._used_custom_guids["sankey"],
            {
                "guid": "ChicagoITSankey1.1.0",
                "name": "Sankey Diagram",
                "class": "sankeyDiagram",
                "roles": {"Source": "dimension", "Destination": "dimension", "Weight": "measure"},
            },
        )

    def test_worksheet_falls_back_from_empty_scatter_and_promotes_spatial_map(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        cases = (
            ({"name": "No measures", "chart_type": "scatterChart",
              "fields": [{"name": "Country", "role": "dimension"}]}, "table"),
            ({"name": "Coordinates", "chart_type": "map", "fields": [
                {"name": "Latitude", "role": "dimension"},
                {"name": "Longitude", "role": "dimension"},
            ]}, "azureMap"),
        )
        for worksheet, expected_type in cases:
            with self.subTest(expected_type=expected_type), tempfile.TemporaryDirectory() as output:
                generator = PowerBIProjectGenerator(output)
                generator._create_visual_worksheet(
                    output, worksheet, {"worksheetName": worksheet["name"]},
                    1, 1, 0, [worksheet], {"calculations": []},
                )
                visual = self._read_visual(output)["visual"]

                self.assertEqual(visual["visualType"], expected_type)
                self.assertIn("queryState", visual["query"])

    def test_fallback_page_emits_empty_shell_and_one_page_per_worksheet(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            empty_pages = os.path.join(output, "empty-pages")
            empty_names = generator._create_fallback_page(empty_pages, [], {})
            empty_page = json.loads(
                (Path(empty_pages) / "ReportSection" / "page.json").read_text(encoding="utf-8")
            )
            empty_visuals_created = (Path(empty_pages) / "ReportSection" / "visuals").is_dir()

            pages_dir = os.path.join(output, "worksheet-pages")
            worksheet_names = generator._create_fallback_page(
                pages_dir,
                [{"name": "Revenue", "chart_type": "lineChart", "fields": []},
                 {"name": "Customers", "chart_type": "tableEx", "fields": []}],
                {},
            )
            page_jsons = [
                json.loads((Path(pages_dir) / page_name / "page.json").read_text(encoding="utf-8"))
                for page_name in worksheet_names
            ]
            visual_jsons = [
                self._read_visual(Path(pages_dir) / page_name / "visuals")
                for page_name in worksheet_names
            ]
            fallback_cases = [
                {"name": "Placeholder fallback", "chart_type": "scatterChart", "fields": [
                    {"name": "Region", "role": "dimension", "shelf": "columns"},
                    {"name": "Placeholder", "role": "measure", "shelf": "rows"},
                ]},
                {"name": "Measure-name fallback", "chart_type": "scatterChart", "fields": [
                    {"name": "Region", "role": "dimension", "shelf": "columns"},
                    {"name": ":Measure Names", "role": "dimension"},
                    {"name": "Multiple Values", "role": "measure"},
                    {"name": "Revenue", "role": "measure", "shelf": "rows",
                     "aggregation": "SUM"},
                ]},
            ]
            fallback_names = generator._create_fallback_page(
                os.path.join(output, "scatter-fallback-pages"), fallback_cases,
                {"calculations": [{"name": "Placeholder", "formula": "MIN(1)"}]},
            )
            fallback_visuals = [
                self._read_visual(Path(output) / "scatter-fallback-pages" / page_name / "visuals")
                ["visual"] for page_name in fallback_names
            ]

        self.assertEqual(empty_names, ["ReportSection"])
        self.assertEqual(empty_page["displayName"], "BusinessObjects Migration")
        self.assertTrue(empty_visuals_created)
        self.assertEqual([page["displayName"] for page in page_jsons], ["Revenue", "Customers"])
        self.assertEqual(
            [visual["visual"]["visualType"] for visual in visual_jsons],
            ["lineChart", "tableEx"],
        )
        self.assertEqual([visual["visualType"] for visual in fallback_visuals],
                         ["multiRowCard", "clusteredBarChart"])
        self.assertIn("Placeholder", json.dumps(fallback_visuals[0]))

    def test_zone_layout_preserves_split_and_floating_pixel_boundaries(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            layout = generator._build_zone_layout_map({
                "id": "root",
                "position": {"x": 0, "y": 0, "w": 100000, "h": 100000},
                "orientation": "horz",
                "children": [
                    {"name": "Left", "position": {"w": 25, "h": 1}},
                    {"name": "Right", "position": {"w": 75, "h": 1}},
                    {"name": "Overlay", "is_floating": True,
                     "position": {"x": 50000, "y": 25000, "w": 10000, "h": 10000}},
                ],
            }, 1000, 600)

        self.assertEqual(layout["Left"], {"x": 0, "y": 0, "w": 250, "h": 600})
        self.assertEqual(layout["Right"], {"x": 250, "y": 0, "w": 750, "h": 600})
        self.assertEqual(layout["Overlay"], {"x": 500, "y": 150, "w": 100, "h": 60})

        clamped = generator._resolve_visual_position(
            {"worksheetName": "Overlay"}, layout, 1, 1, 2, 550, 180,
        )
        self.assertEqual(clamped, {
            "x": 500, "y": 150, "z": 2000, "height": 40, "width": 60,
            "tabOrder": 2000,
        })
        fallback = generator._resolve_visual_position(
            {"worksheetName": "Not in layout", "position": {"x": 20, "y": 10,
                                                                "w": 100, "h": 50}},
            {}, 2, 2, 1, 1280, 720,
        )
        self.assertEqual((fallback["x"], fallback["y"], fallback["width"],
                          fallback["height"]), (40, 20, 200, 100))

        visual_json = {"visual": {}}
        generator._apply_padding_to_visual(visual_json, {
            "name": "root", "children": [{
                "name": "Overlay", "padding": {"top": 4, "bottom": 2,
                                                  "left": 3, "right": 1},
            }],
        }, "Overlay")
        self.assertEqual(
            visual_json["visual"]["objects"]["general"][0]["properties"],
            {"paddingTop": 4, "paddingBottom": 2, "paddingLeft": 3, "paddingRight": 1},
        )

    def test_visual_filter_serialization_emits_supported_filters_and_skips_virtual_ones(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        worksheet = {
            "name": "Filtered Sales",
            "chart_type": "tableEx",
            "fields": [{"name": "Region", "role": "dimension"}],
            "filters": [
                {"field": "[Region]", "type": "categorical", "values": ["West", "East"],
                 "exclude": True},
                {"field": "Revenue", "type": "range", "min": 10, "max": 20},
                {"field": "Order Date", "filter_mode": "relative-date", "period": "month",
                 "period_count": 3, "period_type": "next"},
                {"field": "Measure Names", "values": ["Revenue"]},
                {"field": "Region", "date_part": "year", "values": ["2025"]},
                {"field": "Action Selection", "values": ["West"]},
                {"field": "Revenue", "values": []},
            ],
        }
        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            generator._build_field_mapping({"datasources": [{"tables": [{
                "name": "Sales",
                "columns": [
                    {"name": "Region"}, {"name": "Revenue"}, {"name": "Order Date"},
                ],
            }]}]})
            generator._create_visual_worksheet(
                output, worksheet, {"worksheetName": worksheet["name"]},
                1, 1, 0, [worksheet], {"calculations": []},
            )
            filters = self._read_visual(output)["filterConfig"]["filters"]

        self.assertEqual([item["type"] for item in filters], ["Categorical", "Advanced", "RelativeDate"])
        categorical = filters[0]
        self.assertEqual(categorical["field"]["Column"]["Property"], "Region")
        condition = categorical["filter"]["Where"][0]["Condition"]
        self.assertIn("Not", condition)
        self.assertEqual(
            condition["Not"]["Expression"]["In"]["Values"],
            [[{"Literal": {"Value": "'West'"}}], [{"Literal": {"Value": "'East'"}}]],
        )
        self.assertEqual(len(filters[1]["filter"]["Where"]), 2)
        relative = filters[2]["filter"]["Where"][0]["Condition"]["RelativeDate"]
        self.assertEqual(relative["TimeUnit"], 2)
        self.assertEqual(relative["TimeUnitCount"], 3)
        self.assertEqual(relative["RelativeDateFilterType"], 2)

    def test_standard_chart_promotes_color_dimension_to_category_or_series(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            with_axis = generator._build_visual_query({
                "chart_type": "clusteredColumnChart",
                "fields": [
                    {"name": "Region", "role": "dimension", "shelf": "columns"},
                    {"name": "Channel", "role": "dimension", "shelf": "color"},
                    {"name": "Revenue", "role": "measure", "shelf": "rows",
                     "aggregation": "SUM"},
                ],
            })["queryState"]
            color_only = generator._build_visual_query({
                "chart_type": "clusteredColumnChart",
                "fields": [
                    {"name": "Channel", "role": "dimension", "shelf": "color"},
                    {"name": "Revenue", "role": "measure", "shelf": "rows",
                     "aggregation": "SUM"},
                ],
            })["queryState"]

        self.assertEqual(set(with_axis), {"Category", "Series", "Y"})
        self.assertEqual(with_axis["Category"]["projections"][0]["nativeQueryRef"], "Region")
        self.assertEqual(with_axis["Series"]["projections"][0]["nativeQueryRef"], "Channel")
        self.assertEqual(with_axis["Y"]["projections"][0]["nativeQueryRef"], "Sum of Revenue")
        self.assertEqual(set(color_only), {"Category", "Y"})
        self.assertEqual(color_only["Category"]["projections"][0]["nativeQueryRef"], "Channel")

    def test_standard_chart_avoids_date_dimension_for_series(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            query_state = generator._build_visual_query({
                "chart_type": "lineChart",
                "fields": [
                    {"name": "Order Date", "role": "dimension", "shelf": "columns"},
                    {"name": "Region", "role": "dimension", "shelf": "rows"},
                    {"name": "Revenue", "role": "measure", "shelf": "rows",
                     "aggregation": "SUM"},
                ],
            })["queryState"]

        self.assertEqual(query_state["Category"]["projections"][0]["nativeQueryRef"], "Order Date")
        self.assertEqual(query_state["Series"]["projections"][0]["nativeQueryRef"], "Region")
        self.assertEqual(query_state["Y"]["projections"][0]["nativeQueryRef"], "Sum of Revenue")

    def test_measure_only_standard_charts_emit_card_or_multirowcard_bindings(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        cases = (
            (["Revenue"], "card", "Fields"),
            (["Revenue", "Cost", "Margin"], "multiRowCard", "Values"),
        )
        for names, expected_type, expected_role in cases:
            with self.subTest(expected_type=expected_type), tempfile.TemporaryDirectory() as output:
                generator = PowerBIProjectGenerator(output)
                worksheet = {
                    "name": "Measures",
                    "chart_type": "clusteredColumnChart",
                    "fields": [
                        {"name": name, "role": "measure", "shelf": "rows",
                         "aggregation": "SUM"}
                        for name in names
                    ],
                }
                generator._create_visual_worksheet(
                    output, worksheet, {"worksheetName": "Measures"},
                    1, 1, 0, [worksheet], {"calculations": []},
                )
                visual = self._read_visual(output)["visual"]

                self.assertEqual(visual["visualType"], expected_type)
                projections = visual["query"]["queryState"][expected_role]["projections"]
                self.assertEqual(
                    [entry["nativeQueryRef"] for entry in projections],
                    [f"Sum of {name}" for name in names],
                )
                self.assertTrue(all("Aggregation" in entry["field"] for entry in projections))

    def test_scatter_worksheet_recognizes_placeholder_and_measure_names_patterns(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        cases = (
            ({
                "name": "Placeholder scatter",
                "chart_type": "scatterChart",
                "fields": [
                    {"name": "Region", "role": "dimension", "shelf": "columns"},
                    {"name": "Placeholder", "role": "measure", "shelf": "rows"},
                ],
            }, {"calculations": [{"name": "Placeholder", "formula": "MIN(1)"}]},
             "multiRowCard", "Values", ["Placeholder"]),
            ({
                "name": "Measure names scatter",
                "chart_type": "scatterChart",
                "fields": [
                    {"name": "Region", "role": "dimension", "shelf": "columns"},
                    {"name": ":Measure Names", "role": "dimension"},
                    {"name": "Multiple Values", "role": "measure"},
                    {"name": "Revenue", "role": "measure", "shelf": "rows",
                     "aggregation": "SUM"},
                ],
            }, {"calculations": []}, "clusteredBarChart", "Y", ["Sum of Revenue"]),
        )
        for worksheet, converted, expected_type, expected_role, expected_bindings in cases:
            with self.subTest(expected_type=expected_type), tempfile.TemporaryDirectory() as output:
                generator = PowerBIProjectGenerator(output)
                generator._create_visual_worksheet(
                    output, worksheet, {"worksheetName": worksheet["name"]},
                    1, 1, 0, [worksheet], converted,
                )
                visual = self._read_visual(output)["visual"]

                self.assertEqual(visual["visualType"], expected_type)
                projections = visual["query"]["queryState"][expected_role]["projections"]
                self.assertEqual(
                    [entry["nativeQueryRef"] for entry in projections], expected_bindings,
                )

    def test_dashboard_emits_rich_text_slicers_actions_and_layout_positions(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        converted = {
            "datasources": [{"tables": [{
                "name": "Sales",
                "columns": [
                    {"name": "Amount", "datatype": "number"},
                    {"name": "Created", "datatype": "date"},
                    {"name": "Region", "datatype": "string", "cardinality": 5},
                ],
            }]}],
            "worksheets": [
                {"name": "Revenue", "chart_type": "tableEx", "fields": [],
                 "filters": [{"field": "Region", "values": ["West"],
                              "is_context": True}]},
                {"name": "Unmapped", "chart_type": "lineChart", "fields": []},
            ],
            "filters": [],
            "actions": [
                {"type": "url", "name": "Open source", "url": "https://example.test",
                 "source_worksheet": "Revenue"},
                {"type": "sheet-navigate", "name": "Open details",
                 "target_worksheet": "Unmapped", "source_worksheet": "Revenue"},
            ],
            "dashboards": [{
                "name": "Overview",
                "size": {"width": 800, "height": 600},
                "filters": [{"field": "Region", "values": ["West"]}],
                "zone_hierarchy": {
                    "id": "root", "position": {"w": 100000, "h": 100000},
                    "orientation": "horz",
                    "children": [
                        {"name": "Revenue", "position": {"w": 60000, "h": 100000}},
                        {"name": "Other", "position": {"w": 40000, "h": 100000}},
                    ],
                },
                "objects": [
                    {"type": "worksheetReference", "worksheetName": "Revenue",
                     "position": {"x": 0, "y": 0, "w": 300, "h": 200}},
                    {"type": "worksheetReference", "worksheetName": "Unmapped",
                     "position": {"x": 400, "y": 200, "w": 100, "h": 100}},
                    {"type": "text", "content": "Fallback text",
                     "position": {"x": 10, "y": 20, "w": 200, "h": 60},
                     "text_runs": [{"text": "Bold line\nSecond", "bold": True,
                                    "italic": True, "color": "#AA112233",
                                    "font_size": "12", "url": "https://example.test/text"},
                                   {"text": "Bad size", "font_size": "large"}]},
                    {"type": "text", "content": "Plain fallback",
                     "position": {"x": 220, "y": 20, "w": 200, "h": 60}},
                    {"type": "filter_control", "calc_column_id": "Amount",
                     "filter_mode": "range", "position": {"x": 10, "y": 100, "w": 180, "h": 50}},
                    {"type": "filter_control", "calc_column_id": "Created",
                     "filter_mode": "relative-date", "position": {"x": 200, "y": 100, "w": 180, "h": 50}},
                    {"type": "filter_control", "calc_column_id": "Region",
                     "filter_mode": "wildcard", "position": {"x": 390, "y": 100, "w": 180, "h": 50}},
                ],
            }],
        }

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            report_dir = generator.create_report_structure(output, "Synthetic", converted)
            page_dir = Path(report_dir) / "definition" / "pages" / "ReportSection"
            page = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
            visuals = self._read_visuals(page_dir / "visuals")

        textboxes = [v for v in visuals if v["visual"]["visualType"] == "textbox"]
        rich_textbox = next(v for v in textboxes if "Bold line" in json.dumps(v))
        plain_textbox = next(v for v in textboxes if "Plain fallback" in json.dumps(v))
        rich_paragraphs = rich_textbox["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
        rich_runs = [run for paragraph in rich_paragraphs for run in paragraph["textRuns"]]
        plain_paragraphs = plain_textbox["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
        slicers = [v["visual"] for v in visuals if v["visual"]["visualType"] == "slicer"]
        slicer_modes = {
            visual["query"]["queryState"]["Values"]["projections"][0]["nativeQueryRef"]:
                visual["objects"]["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"]
            for visual in slicers
        }
        action_visuals = [v["visual"] for v in visuals if v["visual"]["visualType"] == "actionButton"]
        chart_positions = {
            v["visual"]["visualType"]: v["position"]
            for v in visuals if v["visual"]["visualType"] in ("tableEx", "lineChart")
        }

        self.assertEqual([run["value"] for run in rich_runs], ["Bold line", "Second", "Bad size"])
        self.assertEqual(rich_runs[0]["textStyle"], {
            "fontWeight": "bold", "fontStyle": "italic", "color": "#112233",
            "fontSize": "12.0pt",
        })
        self.assertEqual(rich_runs[0]["url"], "https://example.test/text")
        self.assertEqual(plain_paragraphs, [{"textRuns": [{"value": "Plain fallback"}]}])
        self.assertEqual(slicer_modes, {
            "Amount": "'Between'", "Created": "'Basic'", "Region": "'Dropdown'",
        })
        self.assertIn("numericInputStyle", next(v for v in slicers if
                          v["query"]["queryState"]["Values"]["projections"][0]["nativeQueryRef"] == "Amount")["objects"])
        self.assertIn("search", next(v for v in slicers if
                          v["query"]["queryState"]["Values"]["projections"][0]["nativeQueryRef"] == "Region")["objects"])
        action_types = [a["objects"]["action"][0]["properties"]["type"]["expr"]["Literal"]["Value"]
                        for a in action_visuals]
        self.assertEqual(set(action_types), {"'WebUrl'", "'PageNavigation'"})
        self.assertEqual(chart_positions["tableEx"]["width"], 480)
        self.assertEqual(
            (chart_positions["lineChart"]["x"], chart_positions["lineChart"]["y"],
             chart_positions["lineChart"]["width"], chart_positions["lineChart"]["height"]),
            (561, 400, 140, 200),
        )
        self.assertEqual(len(page["filterConfig"]["filters"]), 2)

    def test_slicer_modes_are_inferred_from_parameters_and_column_metadata(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        names = ["RangeField", "ListField", "EventDate", "Count", "FewValues", "ManyValues"]
        controls = [
            {"type": "filter_control", "calc_column_id": name,
             "position": {"x": index * 100, "y": 0, "w": 90, "h": 40}}
            for index, name in enumerate(names)
        ]
        converted = {
            "datasources": [{"tables": [{"name": "Events", "columns": [
                {"name": "RangeField", "datatype": "string"},
                {"name": "ListField", "datatype": "string"},
                {"name": "EventDate", "datatype": "datetime"},
                {"name": "Count", "datatype": "integer"},
                {"name": "FewValues", "datatype": "string", "cardinality": 4},
                {"name": "ManyValues", "datatype": "string", "cardinality": 100},
            ]}]}],
            "parameters": [
                {"name": "[RangeParam]", "domain_type": "range"},
                {"name": "[ListParam]", "domain_type": "list"},
            ],
            "dashboards": [{"name": "Controls", "size": {"width": 700, "height": 200},
                            "objects": [dict(controls[0], param="[RangeParam]"),
                                        dict(controls[1], param="[ListParam]"), *controls[2:]]}],
            "worksheets": [],
        }

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            report_dir = generator.create_report_structure(output, "SlicerModes", converted)
            page_dir = Path(report_dir) / "definition" / "pages" / "ReportSection"
            slicers = [v["visual"] for v in self._read_visuals(page_dir / "visuals")]

        emitted_modes = {
            visual["query"]["queryState"]["Values"]["projections"][0]["nativeQueryRef"]:
                visual["objects"]["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"]
            for visual in slicers
        }
        self.assertEqual(emitted_modes, {
            "RangeField": "'Between'", "ListField": "'List'", "EventDate": "'Basic'",
            "Count": "'Between'", "FewValues": "'List'", "ManyValues": "'Dropdown'",
        })
        self.assertIn("numericInputStyle", next(v for v in slicers if
                 v["query"]["queryState"]["Values"]["projections"][0]["nativeQueryRef"] == "Count")["objects"])
        self.assertNotIn("numericInputStyle", next(v for v in slicers if
                         v["query"]["queryState"]["Values"]["projections"][0]["nativeQueryRef"] == "EventDate")["objects"])

    def test_report_and_datasource_filters_are_written_to_report_definition(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        converted = {
            "datasources": [{"tables": [{"name": "Sales", "columns": [
                {"name": "Region"}, {"name": "Amount"},
            ]}]}],
            "filters": [{"field": "[Region]", "type": "categorical", "values": ["West"]}],
            "datasource_filters": [{"field": "Amount", "type": "range", "min": 10, "max": 20}],
            "dashboards": [],
            "worksheets": [],
        }

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            report_dir = generator.create_report_structure(output, "Filtered", converted)
            report = json.loads((Path(report_dir) / "definition" / "report.json").read_text(encoding="utf-8"))

        filters = report["filterConfig"]["filters"]
        self.assertEqual(len(filters), 2)
        self.assertEqual(
            [item["field"]["Column"]["Expression"]["SourceRef"]["Entity"] for item in filters],
            ["Sales", "Sales"],
        )
        self.assertEqual(filters[0]["filter"]["Where"][0]["Condition"]["In"]["Values"],
                         [[{"Literal": {"Value": "'West'"}}]])
        self.assertEqual(len(filters[1]["filter"]["Where"]), 2)

    def test_parameter_report_filter_fragment_preserves_resolved_field_and_value(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            generator._build_field_mapping({"datasources": [{"tables": [{
                "name": "Sales", "columns": [{"name": "Region"}],
            }]}]})
            filters = generator._create_report_filters({"parameters": [
                {"displayName": "[Region]", "currentValue": '"West"'},
                {"displayName": "", "currentValue": "ignored"},
                {"caption": "Region", "currentValue": ""},
            ]})

        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["type"], "Categorical")
        self.assertEqual(filters[0]["field"]["Column"]["Expression"]["SourceRef"]["Entity"], "Sales")
        self.assertEqual(filters[0]["field"]["Column"]["Property"], "Region")
        self.assertEqual(filters[0]["filter"]["Where"][0]["Condition"]["In"]["Values"],
                         [[{"Literal": {"Value": "'West'"}}]])

    def test_tooltip_and_drillthrough_pages_are_serialized_from_worksheet_actions(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        converted = {
            "datasources": [{"tables": [{"name": "Sales", "columns": [
                {"name": "Region"}, {"name": "Amount"},
            ]}]}],
            "worksheets": [
                {"name": "Overview", "chart_type": "barChart", "fields": [
                    {"name": "Region", "role": "dimension"},
                    {"name": "Amount", "role": "measure"},
                ], "tooltips": [{"type": "viz_in_tooltip", "worksheet": "Details"}]},
                {"name": "Details", "chart_type": "tableEx", "fields": [
                    {"name": "Region", "role": "dimension"},
                ]},
            ],
            "dashboards": [{"name": "Overview", "objects": [
                {"type": "worksheetReference", "worksheetName": "Overview",
                 "position": {"x": 0, "y": 0, "w": 600, "h": 400}},
            ]}],
            "actions": [
                {"type": "filter", "target_worksheets": ["Details", "Missing"],
                 "source_field": "[Region]"},
                {"type": "set-value", "target_worksheet": "Details", "field": "Amount"},
                {"type": "url", "target_worksheet": "Missing", "field": "Amount"},
            ],
        }

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            report_dir = generator.create_report_structure(output, "PageFeatures", converted)
            pages_dir = Path(report_dir) / "definition" / "pages"
            page_names = json.loads((pages_dir / "pages.json").read_text(encoding="utf-8"))["pageOrder"]
            pages = [json.loads((pages_dir / name / "page.json").read_text(encoding="utf-8"))
                     for name in page_names]

        tooltip_page = next(page for page in pages if page.get("pageType") == "Tooltip")
        drillthrough_page = next(page for page in pages if page.get("pageType") == "Drillthrough")
        drill_filter = drillthrough_page["drillthrough"]["filters"][0]
        self.assertEqual(tooltip_page["displayName"], "Tooltip - Overview")
        self.assertEqual(drillthrough_page["displayName"], "Drillthrough - Details")
        self.assertEqual(drill_filter["field"]["Column"]["Expression"]["SourceRef"]["Entity"], "Sales")
        self.assertEqual(drill_filter["field"]["Column"]["Property"], "Region")
        self.assertEqual(sum(page.get("pageType") == "Drillthrough" for page in pages), 1)

    def test_phone_layout_page_contains_phone_sized_visual_and_skips_generated_layout(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        converted = {
            "worksheets": [{"name": "Revenue", "chart_type": "tableEx", "fields": []}],
            "dashboards": [{
                "name": "Phone dashboard",
                "objects": [{"type": "worksheetReference", "worksheetName": "Revenue",
                             "position": {"x": 0, "y": 0, "w": 600, "h": 400}}],
                "device_layouts": [
                    {"device_type": "phone", "auto_generated": True,
                     "zones": [{"name": "Revenue", "position": {"x": 0, "y": 0, "w": 300, "h": 500}}]},
                    {"device_type": "phone", "auto_generated": False,
                     "zones": [{"name": "Revenue", "position": {"x": 0, "y": 0, "w": 300, "h": 500}}]},
                ],
            }],
        }

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            report_dir = generator.create_report_structure(output, "Mobile", converted)
            pages_dir = Path(report_dir) / "definition" / "pages"
            page_names = json.loads((pages_dir / "pages.json").read_text(encoding="utf-8"))["pageOrder"]
            pages = [json.loads((pages_dir / name / "page.json").read_text(encoding="utf-8"))
                     for name in page_names]
            mobile_page = next(page for page in pages if page["displayName"].endswith("(Phone)"))
            mobile_visual = self._read_visual(pages_dir / mobile_page["name"] / "visuals")

        self.assertEqual(mobile_page["displayName"], "Phone dashboard (Phone)")
        self.assertEqual((mobile_page["width"], mobile_page["height"]), (320, 568))
        self.assertEqual(mobile_visual["visual"]["visualType"], "tableEx")
        self.assertEqual((mobile_visual["position"]["width"], mobile_visual["position"]["height"]),
                 (300, 500))


    def test_specialty_visual_queries_emit_expected_roles_to_pbir(self):
        cases = (
            ("waterfallChart", {"Category", "Y", "Breakdown"}),
            ("wordCloud", {"Category", "Values"}),
            ("decompositionTree", {"TreeItems", "Values"}),
        )
        for visual_type, expected_roles in cases:
            worksheet = {
                "name": f"{visual_type} example",
                "chart_type": visual_type,
                "fields": [
                    {"name": "Region", "role": "dimension", "shelf": "columns"},
                    {"name": "Channel", "role": "dimension", "shelf": "rows"},
                    {"name": "Revenue", "role": "measure", "shelf": "rows",
                     "aggregation": "SUM"},
                ],
            }
            with self.subTest(visual_type=visual_type), tempfile.TemporaryDirectory() as output:
                _, emitted = self._emit_worksheet(output, worksheet)
                visual = emitted["visual"]
                query_state = visual["query"]["queryState"]

                self.assertEqual(visual["visualType"], visual_type)
                self.assertEqual(set(query_state), expected_roles)
                expected_fields = {
                    "Category": "Region",
                    "Y": "Sum of Revenue",
                    "Breakdown": "Channel",
                    "Values": "Sum of Revenue",
                    "TreeItems": "Region",
                }
                for role, expected_field in expected_fields.items():
                    if role in expected_roles:
                        self.assertEqual(
                            query_state[role]["projections"][0]["nativeQueryRef"],
                            expected_field,
                        )

    def test_script_visuals_emit_python_and_r_field_bindings(self):
        import types

        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        for language, expected_visual, expected_binding in (
            ("python", "scriptVisual", 'dataset["Revenue"]'),
            ("r", "scriptRVisual", "dataset$Revenue"),
        ):
            script_info = {
                "language": language,
                "code": "plot(_arg1)",
                "function": "SCRIPT_REAL",
                "return_type": "real",
            }
            script_module = types.ModuleType("dax_converter")
            script_module.detect_script_functions = lambda formula: (
                [script_info] if formula.startswith("SCRIPT_") else []
            )
            worksheet = {
                "name": f"{language.title()} analytics",
                "chart_type": "lineChart",
                "fields": [{"name": "Revenue", "role": "measure"}],
            }
            converted = {"calculations": [{
                "name": "Revenue", "formula": 'SCRIPT_REAL("plot(_arg1)", "Revenue")',
            }]}

            with self.subTest(language=language), tempfile.TemporaryDirectory() as output:
                generator = PowerBIProjectGenerator(output)
                with patch.dict(sys.modules, {"dax_converter": script_module}):
                    generator._create_visual_worksheet(
                        output, worksheet, {"worksheetName": worksheet["name"]},
                        1, 1, 0, [worksheet], converted,
                    )
                emitted = self._read_visual(output)
                visual = emitted["visual"]

                self.assertEqual(visual["visualType"], expected_visual)
                self.assertEqual(visual["script"]["scriptProviderDefault"], language)
                self.assertIn(expected_binding, visual["script"]["scriptText"])
                self.assertTrue(emitted["name"])
                self.assertTrue(list(Path(output).glob("*/visual.json")))

        script_info = {"language": "python", "code": "plot(_arg1)",
                       "function": "SCRIPT_REAL", "return_type": "real"}
        script_module = types.ModuleType("dax_converter")
        script_module.detect_script_functions = lambda formula: (
            [script_info] if formula.startswith("SCRIPT_") else []
        )
        worksheet = {
            "name": "Embedded analytics", "chart_type": "lineChart",
            "fields": [{"name": "Revenue", "role": "measure"}],
            "mark_encoding": {"color": {"formula": "SCRIPT_REAL(_arg1)"}},
        }
        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            with patch.dict(sys.modules, {"dax_converter": script_module}):
                generator._create_visual_worksheet(
                    output, worksheet, {"worksheetName": worksheet["name"]},
                    1, 1, 0, [worksheet], {"calculations": []},
                )
            embedded = self._read_visual(output)["visual"]
        self.assertEqual(embedded["visualType"], "scriptVisual")
        self.assertIn('dataset["Revenue"]', embedded["script"]["scriptText"])

    def test_report_theme_page_bookmarks_and_authoring_metadata_are_written(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        converted = {
            "datasources": [{"tables": [{"name": "Sales", "columns": [
                {"name": "Region"}, {"name": "Revenue", "role": "measure"},
            ]}]}],
            "worksheets": [{"name": "Revenue chart", "chart_type": "lineChart", "fields": [
                {"name": "Region", "role": "dimension"},
                {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
            ]}],
            "dashboards": [
                {"name": "Executive", "size": {"width": 1024, "height": 768},
                 "theme": {"colors": ["#123456", "#ABCDEF"],
                           "font_family": "Tableau Book"},
                 "dynamic_zone_visibility": [{
                     "zone_name": "Revenue chart", "field": "View", "value": "Revenue",
                     "condition": "equals", "default_visible": True,
                 }],
                 "objects": [{"type": "worksheetReference", "worksheetName": "Revenue chart",
                              "position": {"x": 0, "y": 0, "w": 900, "h": 650}}]},
                {"name": "Operations", "size": {"width": 800, "height": 600},
                 "objects": [{"type": "worksheetReference", "worksheetName": "Revenue chart",
                              "position": {"x": 0, "y": 0, "w": 700, "h": 500}}]},
            ],
            "stories": [{"name": "Quarterly review", "story_points": [{
                "caption": "Revenue snapshot", "filters_state": {"Region": "West"},
                "captured_sheet": "Executive",
            }]}],
        }

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            report_dir = generator.create_report_structure(output, "SalesReview", converted)
            stale_marker = Path(report_dir) / "obsolete-review-marker.txt"
            stale_marker.write_text("stale", encoding="utf-8")
            report_dir = generator.create_report_structure(output, "SalesReview", converted)
            self.assertFalse(stale_marker.exists())
            generator.create_metadata(output, "SalesReview", converted, source="Synthetic BO")
            definition = Path(report_dir) / "definition"
            report = json.loads((definition / "report.json").read_text(encoding="utf-8"))
            pages_dir = definition / "pages"
            pages_index = json.loads((pages_dir / "pages.json").read_text(encoding="utf-8"))
            pages = [json.loads((pages_dir / name / "page.json").read_text(encoding="utf-8"))
                     for name in pages_index["pageOrder"]]
            visuals = self._read_visuals(pages_dir / pages_index["pageOrder"][0] / "visuals")
            theme = json.loads((definition / "RegisteredResources" /
                                "TableauMigrationTheme.json").read_text(encoding="utf-8"))
            metadata = json.loads((Path(output) / "migration_metadata.json").read_text(
                encoding="utf-8"))

        self.assertEqual(report["settings"]["exportDataMode"], "None")
        self.assertTrue(report["settings"]["useEnhancedTooltips"])
        self.assertEqual(report["themeCollection"]["customTheme"]["name"],
                         "TableauMigrationTheme")
        self.assertEqual(theme["dataColors"][:2], ["#123456", "#ABCDEF"])
        self.assertEqual(pages_index["activePageName"], pages_index["pageOrder"][0])
        self.assertEqual([page["displayName"] for page in pages], ["Executive", "Operations"])
        self.assertEqual((pages[0]["width"], pages[0]["height"]), (1024, 768))
        self.assertEqual(sum(v["visual"]["visualType"] == "pageNavigator" for v in visuals), 1)
        self.assertEqual(len(report["bookmarks"]), 2)
        self.assertEqual(metadata["source"], "Synthetic BO")
        self.assertEqual(metadata["generated_output"]["theme_applied"], True)
        self.assertEqual(metadata["generated_output"]["pages"], 2)

    def test_image_visuals_and_custom_shapes_resolve_only_local_fixture_assets(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shape_source = root / "bo_export" / "shapes" / "marker.png"
            shape_source.parent.mkdir(parents=True)
            shape_source.write_bytes(b"synthetic-shape-bytes")
            output = root / "generated"
            previous_cwd = os.getcwd()
            try:
                os.chdir(root)
                generator = PowerBIProjectGenerator(str(output))
                report_dir = generator.create_report_structure(str(output), "ImageReport", {
                    "worksheets": [],
                    "dashboards": [{"name": "Assets", "objects": [
                        {"type": "image", "source": "https://example.invalid/logo.png",
                         "position": {"x": 0, "y": 0, "w": 100, "h": 60}},
                        {"type": "image", "source": "data:image/png;base64,AA==",
                         "position": {"x": 110, "y": 0, "w": 100, "h": 60}},
                        {"type": "image", "source": "images/local.png",
                         "position": {"x": 220, "y": 0, "w": 100, "h": 60}},
                    ]}],
                    "custom_shapes": [{"filename": "marker.png"}],
                })
                page_dir = Path(report_dir) / "definition" / "pages" / "ReportSection"
                images = [visual for visual in self._read_visuals(page_dir / "visuals")
                          if visual["visual"]["visualType"] == "image"]
                copied_shape = (Path(report_dir) / "definition" / "RegisteredResources" /
                                "marker.png")
                copied_shape_bytes = copied_shape.read_bytes()
            finally:
                os.chdir(previous_cwd)

        image_sources = {
            visual["visual"]["objects"]["general"][0]["properties"]["imageUrl"]
            ["expr"]["Literal"]["Value"] for visual in images
        }
        self.assertEqual(len(images), 3)
        self.assertEqual(image_sources, {
            "'https://example.invalid/logo.png'", "'data:image/png;base64,AA=='",
            "'images/local.png'",
        })
        self.assertEqual(set(item["relative_path"] for item in
                             generator._embedded_image_paths.values()), {"images/local.png"})
        self.assertEqual(copied_shape_bytes, b"synthetic-shape-bytes")

    def test_visual_label_legend_axis_and_container_styles_are_emitted(self):
        worksheet = {
            "name": "Styled revenue",
            "chart_type": "lineClusteredColumnComboChart",
            "title": "Quarterly revenue",
            "title_format": {"font_size": "16", "bold": True, "alignment": "1"},
            "fields": [
                {"name": "Quarter", "role": "dimension"},
                {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
                {"name": "Margin", "role": "measure", "aggregation": "AVG"},
            ],
            "formatting": {
                "mark": {"mark-labels-show": "true"},
                "font": {"family": "Aptos", "size": "11pt"},
                "label": {"color": "#010203"},
                "number_format": "0.00",
                "legend": {"position": "top-right", "title": "Channel", "font-size": "11"},
                "background_color": "#FAFAFA",
            },
            "mark_encoding": {"label": {
                "font_size": 12, "font_color": "#AABBCC", "position": "top",
            }, "color": {"field": "Channel"}},
            "sort_orders": [{"field": "Sales.Region", "direction": "DESC",
                             "sort_by": "Sales.sum:Revenue"}],
            "axes": {
                "x": {"title": "Quarter", "label_rotation": "45", "is_continuous": False},
                "y": {"title": "Revenue", "auto_range": False,
                      "range_min": 0, "range_max": 500, "scale": "log"},
                "dual_axis": True,
                "dual_axis_sync": True,
            },
            "dual_axis": {"enabled": True, "synchronized": True},
        }
        with tempfile.TemporaryDirectory() as output:
            from powerbi_import.pbip_generator import PowerBIProjectGenerator

            generator = PowerBIProjectGenerator(output)
            generator._build_field_mapping({"datasources": []})
            generator._create_visual_worksheet(
                output, worksheet, {"worksheetName": worksheet["name"],
                                    "padding": {"padding-left": 6, "padding-top": 3,
                                                "border_style": "solid",
                                                "border_color": "#667788"}},
                1, 1, 0, [worksheet], {"calculations": []},
            )
            emitted = self._read_visual(output)

        visual = emitted["visual"]
        objects = visual["objects"]
        labels = objects["labels"][0]["properties"]
        self.assertEqual(labels["show"]["expr"]["Literal"]["Value"], "true")
        self.assertEqual(labels["fontSize"]["expr"]["Literal"]["Value"], "11D")
        self.assertEqual(labels["fontFamily"]["expr"]["Literal"]["Value"], "'Aptos'")
        self.assertEqual(labels["color"]["solid"]["color"]["expr"]["Literal"]["Value"],
                         "'#010203'")
        self.assertEqual(labels["labelPosition"]["expr"]["Literal"]["Value"], "'OutsideEnd'")
        self.assertEqual(labels["labelDisplayUnits"]["expr"]["Literal"]["Value"], "'0.00'")
        self.assertEqual(objects["legend"][0]["properties"]["position"]["expr"]
                         ["Literal"]["Value"], "'TopRight'")
        self.assertEqual(objects["categoryAxis"][0]["properties"]["labelAngle"]
                         ["expr"]["Literal"]["Value"], "45L")
        self.assertEqual(objects["valueAxis"][0]["properties"]["secShow"]
                         ["expr"]["Literal"]["Value"], "true")
        self.assertEqual(objects["visualContainerStyle"][0]["properties"]["background"]
                         ["solid"]["color"]["expr"]["Literal"]["Value"], "'#FAFAFA'")
        self.assertEqual(objects["padding"][0]["properties"]["left"]["expr"]
                 ["Literal"]["Value"], "6D")
        self.assertEqual(objects["border"][0]["properties"]["color"]["solid"]["color"]
                 ["expr"]["Literal"]["Value"], "'#667788'")
        sort = visual["query"]["sortDefinition"]["sort"][0]
        self.assertEqual(sort["direction"], "Descending")
        self.assertEqual(sort["field"]["Aggregation"]["Function"], 0)
        self.assertEqual(sort["field"]["Aggregation"]["Expression"]["Column"]
                 ["Property"], "Revenue")
        title = visual["visualContainerObjects"]["title"][0]["properties"]
        self.assertEqual(title["fontSize"]["expr"]["Literal"]["Value"], "16D")
        self.assertEqual(title["alignment"]["expr"]["Literal"]["Value"], "'center'")

    def test_table_visual_emits_header_banding_data_bars_totals_and_padding(self):
        worksheet = {
            "name": "Styled table",
            "chart_type": "tableEx",
            "fields": [
                {"name": "Region", "role": "dimension"},
                {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
            ],
            "formatting": {
                "header_style": {"font-size": "12", "font-weight": "bold",
                                 "font-color": "#112233", "border-style": "solid",
                                 "border-color": "#445566"},
                "worksheet_style": {"band-color": "#F0F0F0"},
            },
            "mark_encoding": {"color": {"type": "quantitative"}},
            "totals": {"grand_totals": True, "subtotals": True},
            "padding": {"padding_top": 4, "margin_left": 8},
        }
        with tempfile.TemporaryDirectory() as output:
            _, emitted = self._emit_worksheet(output, worksheet)

        objects = emitted["visual"]["objects"]
        header = objects["columnHeaders"][0]["properties"]
        self.assertEqual(header["fontSize"]["expr"]["Literal"]["Value"], "12D")
        self.assertEqual(header["bold"]["expr"]["Literal"]["Value"], "true")
        self.assertIn("gridlines", objects)
        self.assertIn("values", objects)
        self.assertIn("dataBar", objects)
        self.assertEqual(objects["total"][0]["properties"]["totals"]
                         ["expr"]["Literal"]["Value"], "true")
        self.assertEqual(objects["subTotals"][0]["properties"]["rowSubtotals"]
                         ["expr"]["Literal"]["Value"], "true")
        self.assertEqual(objects["visualContainerPadding"][0]["properties"]["top"]
                         ["expr"]["Literal"]["Value"], "4L")
        self.assertEqual(objects["visualContainerPadding"][0]["properties"]["left"]
                         ["expr"]["Literal"]["Value"], "8L")

    def test_matrix_card_kpi_treemap_and_map_roles_are_serialized(self):
        cases = (
            ({"name": "Matrix", "chart_type": "matrix", "fields": [
                {"name": "Region", "role": "dimension", "shelf": "columns"},
                {"name": "Channel", "role": "dimension", "shelf": "rows"},
                {"name": "Revenue", "role": "measure", "shelf": "rows",
                 "aggregation": "SUM"},
            ]}, {"Rows": "Region", "Columns": "Channel", "Values": "Sum of Revenue"}),
            ({"name": "Revenue card", "chart_type": "card", "fields": [
                {"name": "Revenue", "role": "measure", "aggregation": "SUM"},
            ]}, {"Fields": "Sum of Revenue"}),
            ({"name": "Region card", "chart_type": "multiRowCard", "fields": [
                {"name": "Region", "role": "dimension", "shelf": "columns"},
            ]}, {"Values": "Region"}),
            ({"name": "Revenue KPI", "chart_type": "kpi", "fields": [
                {"name": "Month", "role": "dimension", "shelf": "columns"},
                {"name": "Revenue", "role": "measure", "shelf": "rows",
                 "aggregation": "SUM"},
                {"name": "Goal", "role": "measure", "shelf": "rows",
                 "aggregation": "AVG"},
            ]}, {"Category": "Month", "Y": "Sum of Revenue", "TargetValue": "Average of Goal"}),
            ({"name": "Margin gauge", "chart_type": "gauge", "fields": [
                {"name": "Month", "role": "dimension", "shelf": "columns"},
                {"name": "Revenue", "role": "measure", "shelf": "rows",
                 "aggregation": "SUM"},
                {"name": "Goal", "role": "measure", "shelf": "rows",
                 "aggregation": "AVG"},
            ]}, {"Category": "Month", "Y": "Sum of Revenue", "TargetValue": "Average of Goal"}),
            ({"name": "Regional treemap", "chart_type": "treemap", "fields": [
                {"name": "Order Date", "role": "dimension", "shelf": "columns"},
                {"name": "Region", "role": "dimension", "shelf": "rows"},
                {"name": "Revenue", "role": "measure", "shelf": "rows",
                 "aggregation": "SUM"},
            ]}, {"Group": ["Region", "Order Date"], "Values": "Sum of Revenue"}),
            ({"name": "Customer sunburst", "chart_type": "sunburst", "fields": [
                {"name": "Region", "role": "dimension", "shelf": "rows"},
                {"name": "Revenue", "role": "measure", "shelf": "color",
                 "aggregation": "SUM"},
                {"name": "Customer", "role": "dimension", "shelf": "tooltip"},
            ]}, {"Group": "Region", "Values": "Sum of Revenue", "Tooltips": "Customer"}),
            ({"name": "Filled map", "chart_type": "filledMap", "fields": [
                {"name": "Region", "role": "dimension", "shelf": "columns"},
                {"name": "Channel", "role": "dimension", "shelf": "color"},
                {"name": "Revenue", "role": "measure", "shelf": "color",
                 "aggregation": "SUM"},
            ]}, {"Category": "Region", "Series": "Channel", "Size": "Sum of Revenue"}),
            ({"name": "Shape map", "chart_type": "shapeMap", "fields": [
                {"name": "Region", "role": "dimension", "shelf": "columns"},
                {"name": "Channel", "role": "dimension", "shelf": "color"},
                {"name": "Revenue", "role": "measure", "shelf": "color",
                 "aggregation": "SUM"},
            ]}, {"Category": "Region", "Series": "Channel", "Color": "Sum of Revenue"}),
        )
        for worksheet, expected in cases:
            with self.subTest(chart_type=worksheet["chart_type"]), \
                    tempfile.TemporaryDirectory() as output:
                _, emitted = self._emit_worksheet(output, worksheet)
                query_state = emitted["visual"]["query"]["queryState"]
                self.assertEqual(set(query_state), set(expected))
                for role, expected_value in expected.items():
                    projection = query_state[role]["projections"]
                    actual = [entry["nativeQueryRef"] for entry in projection]
                    self.assertEqual(actual, expected_value if isinstance(expected_value, list)
                                     else [expected_value])

    def test_paginated_report_files_include_only_worksheets_with_fields(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            paginated = Path(generator._create_paginated_report(output, "PrintSales", {
                "worksheets": [
                    {"name": "Regional sales", "fields": [
                        {"name": "Region"}, {"name": "Revenue"},
                    ]},
                    {"name": "Empty tab", "fields": []},
                ],
            }))
            report = json.loads((paginated / "report.json").read_text(encoding="utf-8"))
            page = json.loads((paginated / "pages" / "page1.json").read_text(encoding="utf-8"))
            header = json.loads((paginated / "header.json").read_text(encoding="utf-8"))
            footer = json.loads((paginated / "footer.json").read_text(encoding="utf-8"))
            page_filenames = sorted(path.name for path in
                                    (paginated / "pages").glob("page*.json"))

        self.assertEqual(report["pageCount"], 1)
        self.assertEqual(report["dataSource"], "PrintSales")
        self.assertEqual(page["name"], "Regional sales")
        self.assertEqual([column["header"] for column in page["body"]["items"][0]["columns"]],
                         ["Region", "Revenue"])
        self.assertEqual(header["items"][0]["value"], "PrintSales")
        self.assertIn("PageNumber", footer["items"][0]["value"])
        self.assertEqual(page_filenames, ["page1.json"])

    def test_review_table_is_bound_to_the_generated_empty_report_page(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            generator.create_report_structure(output, "Review", {
                "worksheets": [], "dashboards": [],
            })
            page_dir = Path(output) / "Review.Report" / "definition" / "pages" / "ReportSection"
            self.assertEqual(list((page_dir / "visuals").iterdir()), [])
            generator.add_review_table(
                output, "Review", "Review data", "Sales", ["Region", "Revenue"],
            )
            page = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
            visual_path, = (page_dir / "visuals").glob("*/visual.json")
            visual = json.loads(visual_path.read_text(encoding="utf-8"))

        self.assertEqual(page["displayName"], "Review data")
        self.assertEqual(visual["visual"]["visualType"], "tableEx")
        projections = visual["visual"]["query"]["queryState"]["Values"]["projections"]
        self.assertEqual([entry["field"]["Column"]["Property"] for entry in projections],
                         ["Region", "Revenue"])
        self.assertTrue(all(entry["field"]["Column"]["Expression"]["SourceRef"]["Entity"]
                            == "Sales" for entry in projections))

    def test_thin_report_content_writer_preserves_existing_report_shell(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            report_dir = Path(output) / "Thin.Report"
            report_dir.mkdir()
            platform_path = report_dir / ".platform"
            pbir_path = report_dir / "definition.pbir"
            platform_path.write_text('{"shell": "preserve"}', encoding="utf-8")
            pbir_path.write_text('{"datasetReference": {"byPath": {"path": "../Shared"}}}',
                                 encoding="utf-8")

            generator = PowerBIProjectGenerator(output)
            generator._generate_report_definition_content(str(report_dir), "Thin", {
                "worksheets": [{"name": "Region detail", "chart_type": "tableEx", "fields": [
                    {"name": "Region", "role": "dimension"},
                ]}],
                "dashboards": [{"name": "Theme source", "theme": {
                    "colors": ["#345678"], "background_color": "#FFFFFF",
                }, "objects": []}],
                "datasources": [],
            })
            definition = report_dir / "definition"
            report = json.loads((definition / "report.json").read_text(encoding="utf-8"))
            pages_index = json.loads((definition / "pages" / "pages.json").read_text(
                encoding="utf-8"))
            page = json.loads((definition / "pages" / pages_index["activePageName"] /
                               "page.json").read_text(encoding="utf-8"))
            saved_platform = json.loads(platform_path.read_text(encoding="utf-8"))
            saved_pbir = json.loads(pbir_path.read_text(encoding="utf-8"))
            theme_file_exists = (definition / "RegisteredResources" /
                                 "TableauMigrationTheme.json").is_file()
            visuals_dir_exists = (definition / "pages" / pages_index["activePageName"] /
                                  "visuals").is_dir()

        self.assertEqual(saved_platform, {"shell": "preserve"})
        self.assertEqual(saved_pbir["datasetReference"]["byPath"]["path"], "../Shared")
        self.assertEqual(report["themeCollection"]["customTheme"]["name"],
                         "TableauMigrationTheme")
        self.assertEqual(pages_index["activePageName"], pages_index["pageOrder"][0])
        self.assertEqual(page["displayName"], "Region detail")
        self.assertTrue(theme_file_exists)
        self.assertTrue(visuals_dir_exists)

    def test_scatter_query_limits_groupings_and_emits_three_axis_measures(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        worksheet = {
            "name": "Scatter by region",
            "chart_type": "scatterChart",
            "fields": [
                {"name": "Region", "role": "dimension", "shelf": "columns"},
                {"name": "Channel", "role": "dimension", "shelf": "rows"},
                {"name": "Segment", "role": "dimension", "shelf": "color"},
                {"name": "Revenue", "role": "measure", "shelf": "columns",
                 "aggregation": "SUM"},
                {"name": "Cost", "role": "measure", "shelf": "rows",
                 "aggregation": "AVG"},
                {"name": "Orders", "role": "measure", "shelf": "size",
                 "aggregation": "SUM"},
                {"name": "Margin", "role": "measure", "shelf": "color",
                 "aggregation": "AVG"},
                {"name": "Country", "role": "dimension", "shelf": "tooltip"},
            ],
        }
        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            with self.assertLogs("powerbi_import.pbip_generator", level="WARNING") as logs:
                generator._create_visual_worksheet(
                    output, worksheet, {"worksheetName": worksheet["name"]},
                    1, 1, 0, [worksheet], {"calculations": []},
                )
            visual = self._read_visual(output)["visual"]

        query_state = visual["query"]["queryState"]
        self.assertIn("only two can be represented", " ".join(logs.output))
        self.assertEqual(set(query_state), {"Category", "Series", "X", "Y", "Size", "Tooltips"})
        self.assertEqual(query_state["Category"]["projections"][0]["nativeQueryRef"], "Region")
        self.assertEqual(query_state["Series"]["projections"][0]["nativeQueryRef"], "Channel")
        self.assertEqual(query_state["X"]["projections"][0]["nativeQueryRef"], "Sum of Revenue")
        self.assertEqual(query_state["Y"]["projections"][0]["nativeQueryRef"], "Average of Cost")
        self.assertEqual(query_state["Size"]["projections"][0]["nativeQueryRef"], "Sum of Orders")
        self.assertEqual(
            [entry["nativeQueryRef"] for entry in query_state["Tooltips"]["projections"]],
            ["Country", "Average of Margin"],
        )

    def test_treemap_uses_color_measure_before_size_and_keeps_remaining_tooltips(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        cases = (
            ({
                "name": "Colored hierarchy", "chart_type": "treemap", "fields": [
                    {"name": "Order Date", "role": "dimension", "shelf": "columns"},
                    {"name": "Region", "role": "dimension", "shelf": "rows"},
                    {"name": "Segment", "role": "dimension", "shelf": "color"},
                    {"name": "Profit", "role": "measure", "shelf": "color",
                     "aggregation": "SUM"},
                    {"name": "Sales", "role": "measure", "shelf": "color",
                     "aggregation": "AVG"},
                    {"name": "Customer", "role": "dimension", "shelf": "tooltip"},
                    {"name": "Orders", "role": "measure", "shelf": "size",
                     "aggregation": "SUM"},
                ],
            }, {"Group": ["Region", "Segment", "Order Date"],
                "Values": ["Sum of Profit"], "Tooltips": ["Customer", "Average of Sales"]}),
            ({
                "name": "Size hierarchy", "chart_type": "treemap", "fields": [
                    {"name": "Region", "role": "dimension", "shelf": "rows"},
                    {"name": "Orders", "role": "measure", "shelf": "size",
                     "aggregation": "SUM"},
                ],
            }, {"Group": ["Region"], "Values": ["Sum of Orders"]}),
        )
        for worksheet, expected in cases:
            with self.subTest(name=worksheet["name"]), tempfile.TemporaryDirectory() as output:
                generator = PowerBIProjectGenerator(output)
                query_state = generator._build_visual_query(worksheet)["queryState"]

            self.assertEqual(set(query_state), set(expected))
            for role, expected_names in expected.items():
                self.assertEqual(
                    [entry["nativeQueryRef"] for entry in query_state[role]["projections"]],
                    expected_names,
                )

    def test_standard_chart_uses_size_shelf_when_no_axis_measure_exists(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        worksheet = {
            "name": "Sized categories", "chart_type": "lineChart", "fields": [
                {"name": "Region", "role": "dimension", "shelf": "columns"},
                {"name": "Orders", "role": "measure", "shelf": "size",
                 "aggregation": "SUM"},
            ],
        }
        with tempfile.TemporaryDirectory() as output:
            generator, emitted = self._emit_worksheet(output, worksheet)

        query_state = emitted["visual"]["query"]["queryState"]
        self.assertEqual(set(query_state), {"Category", "Y"})
        self.assertEqual(query_state["Category"]["projections"][0]["nativeQueryRef"], "Region")
        self.assertEqual(query_state["Y"]["projections"][0]["nativeQueryRef"], "Sum of Orders")
        self.assertEqual(emitted["visual"]["visualType"], "lineChart")
        self.assertFalse(generator._used_custom_guids)

    def test_unknown_custom_mark_and_non_mapping_tooltips_fall_back_safely(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        worksheet = {
            "name": "Unknown extension", "chart_type": "lineChart",
            "original_mark_class": "unregistered-shape",
            "fields": [{"name": "Region", "role": "dimension"}],
            "tooltips": [None, "not-a-tooltip", {"type": "viz_in_tooltip",
                                                    "worksheet": "Absent"}],
        }
        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            generator._used_custom_guids = {}
            generator._create_visual_worksheet(
                output, worksheet, {"worksheetName": worksheet["name"]},
                1, 1, 0, [worksheet], {"calculations": []},
                tooltip_page_map={"Details": "TooltipPage"},
            )
            visual = self._read_visual(output)["visual"]

        self.assertEqual(visual["visualType"], "lineChart")
        self.assertEqual(visual["query"]["queryState"]["Category"]["projections"][0]
                         ["nativeQueryRef"], "Region")
        self.assertNotIn("tooltips", visual["objects"])
        self.assertFalse(generator._used_custom_guids)

    def test_label_emission_ignores_non_mapping_format_blocks(self):
        worksheet = {
            "name": "Defensive labels", "chart_type": "lineChart",
            "fields": [{"name": "Revenue", "role": "measure"}],
            "formatting": {
                "mark": [], "label": [], "font": [], "number_format": "0.00",
            },
            "mark_encoding": {"label": {
                "show": True, "font_size": 9, "position": "unsupported",
            }},
        }
        with tempfile.TemporaryDirectory() as output:
            _, emitted = self._emit_worksheet(output, worksheet)

        labels = emitted["visual"]["objects"]["labels"][0]["properties"]
        self.assertEqual(labels["show"]["expr"]["Literal"]["Value"], "true")
        self.assertEqual(labels["fontSize"]["expr"]["Literal"]["Value"], "9D")
        self.assertEqual(labels["labelDisplayUnits"]["expr"]["Literal"]["Value"], "'0.00'")
        self.assertNotIn("labelPosition", labels)

    def test_axis_fallbacks_cover_invalid_rotation_and_unsynchronized_secondary_axis(self):
        worksheet = {
            "name": "Axis fallbacks", "chart_type": "lineClusteredColumnComboChart",
            "fields": [], "formatting": {"axis": []},
            "axes": {
                "x": {"show_title": False, "show_label": False,
                      "label_rotation": "not-an-angle", "format": "date",
                      "is_continuous": False},
                "y": {"show_title": False, "show_label": False,
                      "label_rotation": "30.8", "format": "number",
                      "is_continuous": True, "auto_range": False,
                      "range_min": 0, "range_max": 100, "scale": "log",
                      "reversed": True},
                "dual_axis": True, "dual_axis_sync": True,
            },
            "dual_axis": {"enabled": True, "synchronized": False},
        }
        with tempfile.TemporaryDirectory() as output:
            _, emitted = self._emit_worksheet(output, worksheet)

        objects = emitted["visual"]["objects"]
        category = objects["categoryAxis"][0]["properties"]
        value = objects["valueAxis"][0]["properties"]
        self.assertEqual(category["show"]["expr"]["Literal"]["Value"], "false")
        self.assertEqual(category["showAxisTitle"]["expr"]["Literal"]["Value"], "false")
        self.assertEqual(category["axisType"]["expr"]["Literal"]["Value"], "'Categorical'")
        self.assertNotIn("labelAngle", category)
        self.assertEqual(value["labelAngle"]["expr"]["Literal"]["Value"], "30L")
        self.assertEqual(value["axisType"]["expr"]["Literal"]["Value"], "'Continuous'")
        self.assertEqual(value["reverseOrder"]["expr"]["Literal"]["Value"], "true")
        self.assertNotIn("secAxisLabel", value)
        self.assertNotIn("secShow", value)
        self.assertIn("y1AxisReferenceLine", objects)

    def test_analytics_defaults_and_invalid_values_serialize_to_safe_defaults(self):
        worksheet = {
            "name": "Analytics fallbacks", "chart_type": "map", "fields": [],
            "reference_lines": [
                {"computation": "average", "field": "Revenue", "label": "Mean",
                 "style": "solid"},
                {"computation": "constant", "value": 10, "style": "wavy"},
            ],
            "trend_lines": [{"type": "unknown", "show_r_squared": True}],
            "annotations": [{"text": ""}, {"text": "Target"}],
            "forecasting": [{"periods": 3, "ignore_last": "2"}],
            "map_options": {"washout": "invalid", "style": "unknown"},
            "analytics_stats": [
                {"type": "distribution_band", "value_from": 5},
                {"type": "stat_reference", "computation": "unknown"},
            ],
            "pages_shelf": ["malformed"],
        }
        with tempfile.TemporaryDirectory() as output:
            _, emitted = self._emit_worksheet(output, worksheet)

        objects = emitted["visual"]["objects"]
        refs = objects["valueAxis"][0]["properties"]["referenceLine"]
        self.assertEqual(refs[0]["type"], "Constant")
        self.assertEqual(refs[0]["style"]["expr"]["Literal"]["Value"], "'dashed'")
        self.assertEqual(refs[1]["properties"]["type"]["expr"]["Literal"]["Value"], "'Average'")
        self.assertEqual(refs[2]["type"], "Average")
        self.assertEqual(objects["trend"][0]["properties"]["displayRSquared"]
                         ["expr"]["Literal"]["Value"], "true")
        self.assertIn("Target", objects["subTitle"][0]["properties"]["text"]
                      ["expr"]["Literal"]["Value"])
        self.assertEqual(objects["forecast"][0]["properties"]["ignoreLast"]
                         ["expr"]["Literal"]["Value"], "2L")
        self.assertEqual(objects["mapControl"][0]["properties"]["mapStyle"]
                         ["expr"]["Literal"]["Value"], "'road'")
        self.assertNotIn("transparency", objects["mapControl"][0]["properties"])
        self.assertNotIn("smallMultiple", objects)

    def test_report_empty_shell_and_empty_dashboard_fallback_keep_default_settings(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        converted = {
            "dashboards": [{"objects": []}],
            "worksheets": [
                {"name": "First sheet", "chart_type": "tableEx", "fields": []},
                {"name": "Second sheet", "chart_type": "lineChart", "fields": []},
            ],
        }
        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            report_dir = generator.create_report_structure(output, "Fallback", converted)
            report_path = Path(report_dir) / "definition" / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            pages_dir = Path(report_dir) / "definition" / "pages"
            pages_index = json.loads((pages_dir / "pages.json").read_text(encoding="utf-8"))
            pages = [json.loads((pages_dir / name / "page.json").read_text(encoding="utf-8"))
                     for name in pages_index["pageOrder"]]
            page_names = pages_index["pageOrder"]

        self.assertEqual(pages_index["activePageName"], page_names[0])
        self.assertEqual([page["displayName"] for page in pages],
                         ["First sheet", "Second sheet"])
        self.assertEqual([(page["width"], page["height"]) for page in pages],
                         [(1280, 720), (1280, 720)])
        self.assertEqual(report["settings"]["exportDataMode"], "None")
        self.assertTrue(report["settings"]["useEnhancedTooltips"])
        self.assertNotIn("filterConfig", report)
        self.assertNotIn("customVisualsRepository", report)

    def test_report_precreated_mode_preserves_shell_and_writes_empty_report_defaults(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as output:
            generator = PowerBIProjectGenerator(output)
            report_dir = Path(output) / "Precreated.Report"
            report_dir.mkdir()
            marker = report_dir / "existing-shell.txt"
            marker.write_text("keep", encoding="utf-8")
            result = generator.create_report_structure(
                output, "Precreated", {"worksheets": [], "dashboards": []},
                report_dir_precreated=True,
            )
            report = json.loads((Path(result) / "definition" / "report.json").read_text(
                encoding="utf-8"))
            pages = json.loads((Path(result) / "definition" / "pages" / "pages.json").read_text(
                encoding="utf-8"))
            self.assertTrue(marker.is_file())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

        self.assertEqual(pages["pageOrder"], ["ReportSection"])
        self.assertEqual(pages["activePageName"], "ReportSection")
        self.assertEqual(report["settings"], {
            "hideVisualContainerHeader": True,
            "useStylableVisualContainerHeader": True,
            "exportDataMode": "None",
            "defaultDrillFilterOtherVisuals": True,
            "allowChangeFilterTypes": True,
            "useEnhancedTooltips": True,
        })


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


class TestVisualDecorationEmission(unittest.TestCase):
    """Assert decorations emitted by the public PBIR visual-container API."""

    def _create(self, worksheet, visual_id):
        from powerbi_import.visual_generator import create_visual_container

        return create_visual_container(
            worksheet,
            visual_id=visual_id,
            col_table_map={
                "Region": "Sales",
                "Segment": "Sales",
                "Revenue": "Sales",
                "Margin": "Sales",
            },
        )

    def test_quantitative_palette_and_explicit_formatting_emit_data_point_settings(self):
        gradient = self._create({
            "name": "Margin by Region",
            "visualType": "lineChart",
            "dimensions": [{"name": "Region"}],
            "measures": [{"name": "Margin"}],
            "mark_encoding": {
                "color": {
                    "type": "quantitative",
                    "palette_colors": ["#B2182B", "#F7F7F7", "#2166AC"],
                },
            },
        }, "visual-quantitative-palette")
        self.assertEqual(gradient["name"], "visual-quantitative-palette")
        self.assertEqual(
            gradient["visual"]["objects"]["dataPoint"][0]["properties"]["fillRule"],
            {"linearGradient3": {
                "min": {"color": "#B2182B"},
                "mid": {"color": "#F7F7F7"},
                "max": {"color": "#2166AC"},
            }},
        )

        explicit = self._create({
            "name": "Revenue by Region",
            "visualType": "clusteredColumnChart",
            "dimensions": [{"name": "Region"}],
            "measures": [{"name": "Revenue"}],
            "conditionalFormatting": [{
                "field": "Revenue",
                "operator": "greaterThan",
                "value": 100,
                "formatting": {"backgroundColor": "#FF0000"},
            }],
        }, "visual-explicit-formatting")
        self.assertEqual(
            explicit["visual"]["objects"]["dataPoint"],
            [{"properties": {"showAllDataPoints": {
                "expr": {"Literal": {"Value": "true"}},
            }}}],
        )

    def test_label_and_axis_options_are_serialized_as_pbir_literals(self):
        container = self._create({
            "name": "Revenue Labels",
            "visualType": "lineChart",
            "dimensions": [{"name": "Region"}],
            "measures": [{"name": "Revenue"}],
            "mark_encoding": {"label": {
                "show": True,
                "font_size": 13,
                "font_color": "#123456",
                "position": "right",
                "orientation": "vertical",
            }},
            "axes": {
                "y": {
                    "auto_range": False,
                    "range_min": -5,
                    "range_max": 75,
                    "scale": "log",
                    "reversed": True,
                    "title": "Revenue (log)",
                },
                "x": {"reversed": True, "title": "Region"},
            },
        }, "visual-labels-and-axes")
        visual = container["visual"]
        self.assertEqual(visual["objects"]["labels"][0]["properties"], {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "fontSize": {"expr": {"Literal": {"Value": "13D"}}},
            "color": {"solid": {"color": "#123456"}},
            "labelPosition": {"expr": {"Literal": {"Value": "'Right'"}}},
            "orientation": {"expr": {"Literal": {"Value": "'Vertical'"}}},
        })
        self.assertEqual(visual["objects"]["valueAxis"][0]["properties"], {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "start": {"expr": {"Literal": {"Value": "-5D"}}},
            "end": {"expr": {"Literal": {"Value": "75D"}}},
            "axisScale": {"expr": {"Literal": {"Value": "'Log'"}}},
            "reverseOrder": {"expr": {"Literal": {"Value": "true"}}},
            "titleText": {"expr": {"Literal": {"Value": '"Revenue (log)"'}}},
            "showAxisTitle": {"expr": {"Literal": {"Value": "true"}}},
        })
        self.assertEqual(visual["objects"]["categoryAxis"][0]["properties"], {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "reverseOrder": {"expr": {"Literal": {"Value": "true"}}},
            "titleText": {"expr": {"Literal": {"Value": '"Region"'}}},
            "showAxisTitle": {"expr": {"Literal": {"Value": "true"}}},
        })

    def test_constant_dynamic_and_band_references_are_emitted(self):
        container = self._create({
            "name": "Revenue Reference Guide",
            "visualType": "lineChart",
            "dimensions": [{"name": "Region"}],
            "measures": [{"name": "Revenue"}],
            "referenceLines": [
                {"type": "constant", "value": 42, "label": "Target", "color": "#00AA00"},
                {"type": "average", "field": "Revenue", "label": "Mean",
                 "color": "#0000FF", "style": "dotted"},
                {"type": "band", "values": [10, 30], "label": "Expected",
                 "color": "#CCCCCC", "opacity": 0.25},
            ],
        }, "visual-reference-guides")
        objects = container["visual"]["objects"]
        self.assertEqual(objects["constantLine"][0]["properties"], {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "value": {"expr": {"Literal": {"Value": "42D"}}},
            "displayName": {"expr": {"Literal": {"Value": '"Target"'}}},
            "color": {"solid": {"color": "#00AA00"}},
            "style": {"expr": {"Literal": {"Value": "'dashed'"}}},
        })
        self.assertEqual(objects["referenceLine"][0]["properties"], {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "displayName": {"expr": {"Literal": {"Value": '"Mean"'}}},
            "color": {"solid": {"color": "#0000FF"}},
            "style": {"expr": {"Literal": {"Value": "'dotted'"}}},
            "type": {"expr": {"Literal": {"Value": "'Average'"}}},
        })
        self.assertEqual(objects["referenceBand"][0]["properties"], {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "startValue": {"expr": {"Literal": {"Value": "10D"}}},
            "endValue": {"expr": {"Literal": {"Value": "30D"}}},
            "displayName": {"expr": {"Literal": {"Value": '"Expected"'}}},
            "color": {"solid": {"color": "#CCCCCC"}},
            "transparency": {"expr": {"Literal": {"Value": "75D"}}},
        })

    def test_trend_line_and_table_data_bars_preserve_options(self):
        trend = self._create({
            "name": "Revenue Trend",
            "visualType": "lineChart",
            "dimensions": [{"name": "Region"}],
            "measures": [{"name": "Revenue"}],
            "trendLines": [{"regression_type": "polynomial", "order": 3,
                             "color": "#8844AA"}],
        }, "visual-trend-line")
        self.assertEqual(trend["visual"]["objects"]["trend"][0]["properties"], {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "lineColor": {"solid": {"color": "#8844AA"}},
            "style": {"expr": {"Literal": {"Value": "'dashed'"}}},
            "regressionType": {"expr": {"Literal": {"Value": "'Polynomial'"}}},
            "polynomialOrder": {"expr": {"Literal": {"Value": "3D"}}},
        })

        table = self._create({
            "name": "Revenue Detail",
            "visualType": "tableEx",
            "dimensions": [{"name": "Region"}],
            "measures": [{"name": "Revenue"}],
            "dataBars": [{"column": "Revenue", "minColor": "#EEEEEE",
                          "maxColor": "#008800", "showBarOnly": True}],
        }, "visual-data-bars")
        bar = table["visual"]["objects"]["values"][0]["properties"]["dataBar"][0]
        self.assertEqual(bar["id"], "dataBar_Revenue")
        self.assertEqual(bar["field"]["Column"]["Expression"]["SourceRef"]["Entity"], "Sales")
        self.assertEqual(bar["field"]["Column"]["Property"], "Revenue")
        self.assertEqual(bar["positiveColor"], {"solid": {"color": "#008800"}})
        self.assertTrue(bar["showBarOnly"])

    def test_small_multiple_field_is_bound_and_layout_options_are_emitted(self):
        container = self._create({
            "name": "Revenue by Segment",
            "visualType": "lineChart",
            "dimensions": [{"name": "Region"}],
            "measures": [{"name": "Revenue"}],
            "smallMultiples": {
                "field": "Segment",
                "layout": "fixed",
                "maxPerRow": 4,
                "showEmpty": True,
            },
        }, "visual-small-multiples")
        visual = container["visual"]
        self.assertEqual(visual["objects"]["showMultiplesCard"]["properties"]["show"], {
            "expr": {"Literal": {"Value": "true"}},
        })
        self.assertEqual(visual["objects"]["smallMultiple"][0]["properties"], {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "layoutMode": {"expr": {"Literal": {"Value": "'fixed'"}}},
            "maxItemsPerRow": {"expr": {"Literal": {"Value": "4L"}}},
            "showEmptyItems": {"expr": {"Literal": {"Value": "true"}}},
        })
        self.assertEqual(
            visual["query"]["queryState"]["SmallMultiple"]["projections"][0],
            {
                "field": {"Column": {
                    "Expression": {"SourceRef": {"Entity": "Sales"}},
                    "Property": "Segment",
                }},
                "queryRef": "Sales.Segment",
                "nativeQueryRef": "Segment",
                "active": True,
            },
        )

    def test_chart_missing_required_dimension_degrades_to_table_with_note(self):
        container = self._create({
            "name": "Revenue without category",
            "visualType": "lineChart",
            "measures": [{"name": "Revenue"}],
        }, "visual-fallback-table")
        visual = container["visual"]
        self.assertEqual(visual["visualType"], "tableEx")
        self.assertEqual(visual["annotations"], [{
            "name": "MigrationNote",
            "value": "Self-heal: 'lineChart' degraded to 'tableEx' — "
                     "missing required data roles for original type",
        }])


if __name__ == "__main__":
    unittest.main()
