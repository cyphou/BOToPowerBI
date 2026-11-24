"""Tests for explicitly declared SAP BW Power Query navigation."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from bo_export.compat import generate_power_query_m
from bo_export.m_query_builder import build_m_query
from powerbi_import.dataflow_generator import DataflowGenerator
from powerbi_import.pbip_generator import PowerBIProjectGenerator
from powerbi_import.tmdl_generator import _build_table, generate_tmdl
from powerbi_import.validator import ArtifactValidator


class TestSapBwMQuery(unittest.TestCase):
    def setUp(self):
        self.connection = {
            "type": "sap_bw",
            "server": 'bw "test" #(lf)',
            "system_number": "00",
            "client_id": "001",
        }
        self.navigation = {
            "info_area": "$INFOCUBE",
            "cube_id": "$0D_DECU",
            "dimensions": [{
                "selector": "[0CALDAY]",
                "attributes": ["[0CALDAY].[LEVEL01]"],
                "columns": ["Calendar day"],
            }],
            "measures": [{
                "selector": "[Measures].[0D_INV_QTY]",
                "column": "Quantity",
            }],
        }
        self.table = {"name": "Sales", "sap_bw_navigation": self.navigation}

    def test_explicit_cube_selection_is_escaped_and_uses_v2_connector(self):
        original_connection = copy.deepcopy(self.connection)
        original_table = copy.deepcopy(self.table)
        result = generate_power_query_m(self.connection, self.table)
        self.assertIn(
            'SapBusinessWarehouse.Cubes("bw ""test"" #(#)(lf)", "00", "001", '
            '[Implementation="2.0"])',
            result,
        )
        self.assertIn('Source{[Name="$INFOCUBE"]}[Data]', result)
        self.assertIn('InfoArea{[Id="$0D_DECU"]}[Data]', result)
        self.assertIn(
            '{Cube.AddAndExpandDimensionColumn, "[0CALDAY]", '
            '{"[0CALDAY].[LEVEL01]"}, {"Calendar day"}}',
            result,
        )
        self.assertIn('{Cube.AddMeasureColumn, "Quantity", "[Measures].[0D_INV_QTY]"}', result)
        self.assertNotIn("Schema=", result)
        self.assertNotIn("Value.NativeQuery", result)
        self.assertEqual(self.connection, original_connection)
        self.assertEqual(self.table, original_table)

    def test_missing_or_ambiguous_information_fails_explicitly(self):
        for field in ("server", "system_number", "client_id"):
            connection = copy.deepcopy(self.connection)
            connection.pop(field)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                generate_power_query_m(connection, self.table)
        with self.assertRaisesRegex(ValueError, "sap_bw_navigation"):
            generate_power_query_m(self.connection, {"name": "Sales"})
        with self.assertRaisesRegex(ValueError, "SQL or transforms"):
            build_m_query(self.connection, custom_sql="SELECT * FROM SALES")
        with self.assertRaisesRegex(ValueError, "SQL or transforms"):
            build_m_query(self.connection, transforms=[{"type": "filter"}])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            build_m_query(self.connection, tables=["A", "B"])

        for mutation in ("empty", "wrong_lengths", "duplicate", "bad_selector", "control"):
            navigation = copy.deepcopy(self.navigation)
            if mutation == "empty":
                navigation["dimensions"] = []
                navigation["measures"] = []
            elif mutation == "wrong_lengths":
                navigation["dimensions"][0]["columns"] = []
            elif mutation == "duplicate":
                navigation["measures"][0]["column"] = "calendar day"
            elif mutation == "bad_selector":
                navigation["measures"][0]["selector"] = ""
            else:
                navigation["cube_id"] = "Cube\x00"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                generate_power_query_m(
                    self.connection, {"name": "Sales", "sap_bw_navigation": navigation}
                )

    def test_explicit_connection_without_table_returns_navigation_catalog(self):
        result = build_m_query(self.connection)
        self.assertIn('SapBusinessWarehouse.Cubes(', result)
        self.assertTrue(result.endswith('in\n    #"Source"'))

    def test_member_property_preserves_escaped_source_column(self):
        table = copy.deepcopy(self.table)
        dimension = table["sap_bw_navigation"]["dimensions"][0]
        dimension["columns"] = ['Jour "ouvré" #(lf)']
        dimension["properties"] = [{
            "source_column": 'Jour "ouvré" #(lf)',
            "selector": '[Clé "BW"]',
            "column": "Clé jour",
        }]
        result = generate_power_query_m(self.connection, table)
        self.assertIn(
            '{Table.AddColumn, "Clé jour", each '
            'Cube.AttributeMemberProperty([#"Jour ""ouvré"" #(#)(lf)"], '
            '"[Clé ""BW""]")}',
            result,
        )
        self.assertLess(
            result.index("Cube.AddAndExpandDimensionColumn"),
            result.index("Cube.AttributeMemberProperty"),
        )

    def test_explicit_cube_parameters_preserve_argument_shape_and_escaping(self):
        table = copy.deepcopy(self.table)
        table["sap_bw_navigation"]["parameters"] = [
            {
                "selector": "[!V001]",
                "bex_variable_id": "synthetic-region-variable",
                "arguments": ['Région "A" #(lf)'],
            },
            {"selector": "[!V002]", "arguments": [["one", "two"]]},
        ]
        result = generate_power_query_m(self.connection, table)
        self.assertIn(
            '{Cube.ApplyParameter, "[!V001]", {"Région ""A"" #(#)(lf)"}}',
            result,
        )
        self.assertIn(
            '{Cube.ApplyParameter, "[!V002]", {{"one", "two"}}}',
            result,
        )
        self.assertLess(result.index('Cube.ApplyParameter, "[!V001]"'), result.index('Cube.ApplyParameter, "[!V002]"'))
        self.assertLess(result.index("Cube.ApplyParameter"), result.index("Cube.AddAndExpandDimensionColumn"))
        self.assertLess(result.index("Cube.ApplyParameter"), result.index("Cube.AddMeasureColumn"))

    def test_invalid_cube_parameters_are_rejected(self):
        cases = [
            [{"selector": "[!V001]", "arguments": []}],
            [{"selector": "[!V001]", "arguments": [[]]}],
            [{"selector": "[!V001]", "arguments": [123]}],
            [{"selector": "[!V001]", "arguments": [[["deep"]]]}],
            [{"selector": "", "arguments": ["ok"]}],
            [{"selector": "[!V001]", "arguments": ["value\x00"]}],
            [{"selector": "[!V001]", "arguments": ["ok"], "extra": True}],
            [{"selector": "[!V001]", "bex_variable_id": "", "arguments": ["ok"]}],
            [
                {"selector": "[!V001]", "bex_variable_id": "duplicate", "arguments": ["one"]},
                {"selector": "[!V002]", "bex_variable_id": "duplicate", "arguments": ["two"]},
            ],
            [
                {"selector": "[!V001]", "arguments": ["one"]},
                {"selector": "[!V001]", "arguments": ["two"]},
            ],
        ]
        for parameters in cases:
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                table = copy.deepcopy(self.table)
                table["sap_bw_navigation"]["parameters"] = parameters
                generate_power_query_m(self.connection, table)

    def test_dataflow_uses_table_navigation_not_sql_table_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = {"datasources": [{
                "name": "BW", "connection": self.connection,
                "tables": [{**self.table, "columns": [
                    {"name": "Calendar day"}, {"name": "Quantity"},
                ]}],
            }]}
            DataflowGenerator(temporary, "BW").generate(data)
            query = (
                Path(temporary) / "BW.Dataflow" / "queries" / "Sales.m"
            ).read_text(encoding="utf-8")
        self.assertIn('SapBusinessWarehouse.Cubes(', query)
        self.assertIn('InfoArea{[Id="$0D_DECU"]}[Data]', query)
        self.assertIn('Cube.AddMeasureColumn', query)
        self.assertNotIn('Source{[Schema=', query)

    def test_import_model_uses_the_declared_cube_selection(self):
        data = [{
            "name": "BW", "connection": self.connection,
            "tables": [{**self.table, "columns": [
                {"name": "Calendar day", "datatype": "string"},
                {"name": "Quantity", "datatype": "decimal"},
            ]}],
        }]
        with tempfile.TemporaryDirectory() as temporary:
            generate_tmdl(data, "BW", {}, temporary)
            table = (
                Path(temporary) / "definition" / "tables" / "Sales.tmdl"
            ).read_text(encoding="utf-8")
        self.assertIn('SapBusinessWarehouse.Cubes(', table)
        self.assertIn('InfoArea{[Id="$0D_DECU"]}[Data]', table)
        self.assertIn('Cube.AddMeasureColumn', table)
        self.assertIn('sourceColumn: "Calendar day"', table)
        self.assertIn("sourceColumn: Quantity", table)
        self.assertIn("mode: import", table)
        self.assertNotIn('Source{[Schema=', table)

    def test_generated_bw_server_and_quoted_alias_use_their_own_literal_escapes(self):
        table = copy.deepcopy(self.table)
        table_name = 'Sales "review"'
        alias = 'Jour "ouvré" #(lf)'
        table["name"] = table_name
        table["sap_bw_navigation"]["dimensions"][0]["columns"] = [alias]
        table["columns"] = [
            {"name": alias, "datatype": "string"},
            {"name": "Quantity", "datatype": "decimal"},
        ]
        data = [{"name": "BW", "connection": self.connection, "tables": [table]}]
        with tempfile.TemporaryDirectory() as temporary:
            generate_tmdl(data, "BW", {}, temporary)
            definition = Path(temporary) / "definition"
            expressions = (definition / "expressions.tmdl").read_text(encoding="utf-8")
            model = (definition / "model.tmdl").read_text(encoding="utf-8")
            table_path, = (definition / "tables").glob("*.tmdl")
            table_text = table_path.read_text(encoding="utf-8")

        self.assertIn(
            'expression ServerName = "bw ""test"" #(#)(lf)" meta '
            '[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
            expressions.splitlines(),
        )
        table_lines = table_text.splitlines()
        self.assertIn(
            '\t\t\t\t    #"Source" = SapBusinessWarehouse.Cubes('
            '"bw ""test"" #(#)(lf)", "00", "001", [Implementation="2.0"]),',
            table_lines,
        )
        self.assertIn(
            '\t\t\t\t        {Cube.AddAndExpandDimensionColumn, "[0CALDAY]", '
            '{"[0CALDAY].[LEVEL01]"}, {"Jour ""ouvré"" #(#)(lf)"}},',
            table_lines,
        )
        self.assertIn('\t\tsourceColumn: "Jour ""ouvré"" #(lf)"', table_lines)
        query_order_prefix = "annotation PBI_QueryOrder = "
        self.assertEqual(
            [json.loads(line.removeprefix(query_order_prefix)) for line in model.splitlines()
             if line.startswith(query_order_prefix)],
            [[table_name]],
        )

    def test_non_bw_date_enrichments_remain_enabled(self):
        data = [{
            "name": "SQL",
            "connection": {"type": "sql_server", "server": "synthetic", "database": "db"},
            "tables": [{
                "name": "Sales",
                "columns": [{"name": "Order date", "datatype": "datetime"}],
            }],
        }]
        with tempfile.TemporaryDirectory() as temporary:
            generate_tmdl(data, "SQL", {}, temporary)
            table_dir = Path(temporary) / "definition" / "tables"
            self.assertTrue((table_dir / "Calendar.tmdl").is_file())
            text = (table_dir / "Sales.tmdl").read_text(encoding="utf-8")
            self.assertIn("Order date Hierarchy", text)

    def test_numeric_bw_columns_are_not_summarized_but_other_sources_keep_default(self):
        table = copy.deepcopy(self.table)
        table["sap_bw_navigation"]["dimensions"].append({
            "selector": "[0YEAR]",
            "attributes": ["[0YEAR].[LEVEL01]"],
            "columns": ["Fiscal year"],
        })
        table["sap_bw_navigation"]["measures"].append({
            "selector": "[Measures].[0D_MARGIN]",
            "column": "Margin",
        })
        table["columns"] = [
            {"name": "Fiscal year", "datatype": "integer"},
            {"name": "Quantity", "datatype": "integer"},
            {"name": "Margin", "datatype": "real"},
        ]

        bw_table = _build_table(
            table, self.connection, [], [], model_mode="import"
        )
        bw_summarization = {
            column["name"]: column["summarizeBy"]
            for column in bw_table["columns"]
        }
        self.assertEqual(
            bw_summarization,
            {"Fiscal year": "none", "Quantity": "none", "Margin": "none"},
        )

        non_bw_table = _build_table(
            {"name": "Sales", "columns": [
                {"name": "Units", "datatype": "integer"},
                {"name": "Revenue", "datatype": "real"},
            ]},
            {"type": "sql_server"},
            [],
            [],
            m_query_override="let Source = 1 in Source",
            model_mode="import",
        )
        non_bw_summarization = {
            column["name"]: column["summarizeBy"]
            for column in non_bw_table["columns"]
        }
        self.assertEqual(
            non_bw_summarization, {"Units": "sum", "Revenue": "sum"}
        )

    def test_pbip_contains_bw_import_model_and_empty_report(self):
        data = {"datasources": [{
            "name": "BW", "connection": self.connection,
            "tables": [{**self.table, "columns": [
                {"name": "Calendar day", "datatype": "string"},
                {"name": "Quantity", "datatype": "decimal"},
            ]}],
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(PowerBIProjectGenerator(temporary).generate_project("BW", data))
            model = project / "BW.SemanticModel"
            table = (model / "definition" / "tables" / "Sales.tmdl").read_text(encoding="utf-8")
            pbip = json.loads((project / "BW.pbip").read_text(encoding="utf-8"))
            report = project / pbip["artifacts"][0]["report"]["path"]
            pbir = json.loads((report / "definition.pbir").read_text(encoding="utf-8"))
            validation = ArtifactValidator.validate_project(project)
            self.assertTrue(validation["valid"], validation["errors"])
            self.assertEqual(pbir["datasetReference"]["byPath"]["path"], "../BW.SemanticModel")
            self.assertEqual(list(report.rglob("visual.json")), [])
            self.assertIn('InfoArea{[Id="$0D_DECU"]}[Data]', table)
            self.assertIn("sourceColumn: Quantity", table)
            self.assertIn("mode: import", table)

    def test_pbip_surfaces_missing_bw_navigation(self):
        data = {"datasources": [{
            "name": "BW", "connection": self.connection,
            "tables": [{"name": "Sales", "columns": [{"name": "Quantity"}]}],
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "sap_bw_navigation"):
                PowerBIProjectGenerator(temporary).generate_project("BW", data)
            self.assertFalse((Path(temporary) / "BW").exists())


if __name__ == "__main__":
    unittest.main()
