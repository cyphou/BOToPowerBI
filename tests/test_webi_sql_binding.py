"""Contract tests for binding WebI freehand SQL to its Power Query source."""

import tempfile
import unittest
from pathlib import Path

from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
from bo_export.m_query_builder import build_m_query, build_m_query_for_universe
from bo_export.webi_extractor import extract_webi
from powerbi_import.dataflow_generator import DataflowGenerator
from powerbi_import.tmdl_generator import generate_tmdl


class TestWebiSqlExtractionBinding(unittest.TestCase):
    def test_query_filters_are_not_providers_or_column_binding_conflicts(self):
        xml = """\
        <document>
          <connection id="sales-ref" name="Sales DB" type="SQL Server"/>
          <dataProvider name="Sales_Query" connectionId="sales-ref">
            <ResultObject name="Revenue" table="Sales_Query" dataType="number"/>
            <SQL>SELECT Revenue FROM Sales</SQL>
            <QueryFilter name="Sales_Query" object="Revenue" operator="Greater Than">
              <Value>0</Value>
            </QueryFilter>
          </dataProvider>
          <QueryCondition name="Other condition" object="Revenue"/>
        </document>
        """
        extracted = extract_webi("in-memory.wid", artifact_data={"document.xml": xml})

        self.assertEqual([query["name"] for query in extracted["queries"]], ["Sales_Query"])
        self.assertEqual([filt["name"] for filt in extracted["filters"]],
                         ["Sales_Query", "Other condition"])
        converted = adapt_bo_to_converted_objects(extracted)
        table = converted["datasources"][0]["tables"][0]
        self.assertEqual(table["sql"], "SELECT Revenue FROM Sales")
        self.assertEqual([column["name"] for column in table["columns"]], ["Revenue"])

    def test_namespaced_query_with_filter_remains_a_provider(self):
        xml = """\
        <document xmlns:w="urn:webi">
          <w:query name="Sales">
            <w:resultObject name="Revenue"/>
            <w:queryFilter name="Minimum Revenue" object="Revenue"/>
          </w:query>
        </document>
        """
        extracted = extract_webi("in-memory.wid", artifact_data={"document.xml": xml})

        self.assertEqual([query["name"] for query in extracted["queries"]], ["Sales"])
        self.assertEqual([filt["name"] for filt in extracted["filters"]], ["Minimum Revenue"])

    def test_synthetic_sales_sample_keeps_filters_separate_from_query(self):
        source = Path(__file__).resolve().parents[1] / "examples" / "Enterprise_Sales.wid"
        extracted = extract_webi(str(source))

        self.assertEqual([query["name"] for query in extracted["queries"]], ["Sales_Query"])
        self.assertEqual([filt["name"] for filt in extracted["filters"]],
                         ["Year Filter", "Active Products"])
        self.assertEqual(len(extracted["columns"]), 12)
        self.assertTrue(all(not column["table"] for column in extracted["columns"]))

    def test_sql_data_providers_resolve_connection_references(self):
        xml = """\
        <document>
          <connection id="conn-ref-sales" name="Sales DB" type="SQL Server"
                      server="sales-db.example.invalid" database="SalesWarehouse"/>
          <connection id="conn-ref-people" name="People DB" type="PostgreSQL"
                      server="people-db.example.invalid" database="PeopleWarehouse"/>
          <dataProvider id="provider-sales" name="Sales Orders"
                        type="sql" connectionId="conn-ref-sales">
            <sql>SELECT OrderId FROM SalesOrders</sql>
          </dataProvider>
          <dataProvider id="provider-people" name="People List"
                        type="sql" connectionId="conn-ref-people">
            <sql>SELECT PersonId FROM People</sql>
          </dataProvider>
        </document>
        """

        extracted = extract_webi("in-memory.wid", artifact_data={"document.xml": xml})

        self.assertEqual(
            {query["name"]: query["sql"] for query in extracted["queries"]},
            {
                "Sales Orders": "SELECT OrderId FROM SalesOrders",
                "People List": "SELECT PersonId FROM People",
            },
        )
        self.assertEqual(
            {query["name"]: query["datasource"] for query in extracted["queries"]},
            {
                "Sales Orders": "conn-ref-sales",
                "People List": "conn-ref-people",
            },
        )
        self.assertEqual(
            {query["name"]: (query["sql"], query["datasource"])
             for query in extracted["custom_sql"]},
            {
                "Sales Orders": ("SELECT OrderId FROM SalesOrders", "conn-ref-sales"),
                "People List": ("SELECT PersonId FROM People", "conn-ref-people"),
            },
        )

    def test_unnamed_sql_providers_receive_unique_query_names(self):
        xml = """\
        <document>
          <connection id="warehouse-ref" name="Warehouse" type="SQL Server"
                      server="warehouse.example.invalid" database="Warehouse"/>
          <dataProvider id="provider-one" type="sql" connectionId="warehouse-ref">
            <sql>SELECT 1 AS FirstValue</sql>
          </dataProvider>
          <dataProvider id="provider-two" type="sql" connectionId="warehouse-ref">
            <sql>SELECT 2 AS SecondValue</sql>
          </dataProvider>
        </document>
        """

        extracted = extract_webi("in-memory.wid", artifact_data={"document.xml": xml})

        self.assertEqual(len(extracted["queries"]), 2)
        query_names = [query["name"] for query in extracted["queries"]]
        self.assertTrue(all(query_names), query_names)
        self.assertEqual(len(set(query_names)), 2)
        self.assertEqual(len(extracted["custom_sql"]), 2)
        sql_names = [query["name"] for query in extracted["custom_sql"]]
        self.assertTrue(all(sql_names), sql_names)
        self.assertEqual(len(set(sql_names)), 2)


class TestWebiSqlDatasourceAndDataflowContract(unittest.TestCase):
    @staticmethod
    def _extracted(custom_sql, datasources):
        """Minimal extracted-data fixture; no exported BO artifact is used."""
        return {
            "datasources": datasources,
            "tables": [],
            "columns": [],
            "custom_sql": custom_sql,
        }

    @staticmethod
    def _sql_tables(converted):
        return [
            (datasource["name"], table)
            for datasource in converted["datasources"]
            for table in datasource.get("tables", [])
            if table.get("type") == "custom_sql"
        ]

    def test_explicit_query_table_columns_reach_import_model(self):
        xml = """\
        <document>
          <connection id="sales-ref" name="Sales DB" type="SQL Server"
                      server="sales.example.invalid" database="Sales"/>
          <dataProvider name="Sales_Query" connectionId="sales-ref">
            <ResultObject name="Région" table="Sales_Query" dataType="string"/>
            <ResultObject name="Revenue" table="sales_query" dataType="number"
                          qualification="measure"/>
            <ResultObject name="Unbound" dataType="string"/>
            <SQL>SELECT [Région], Revenue FROM Sales</SQL>
          </dataProvider>
        </document>
        """
        extracted = extract_webi("in-memory.wid", artifact_data={"document.xml": xml})
        converted = adapt_bo_to_converted_objects(extracted)
        attached = self._sql_tables(converted)

        self.assertEqual(len(attached), 1)
        self.assertEqual(
            [column["name"] for column in attached[0][1]["columns"]],
            ["Région", "Revenue"],
        )
        self.assertEqual(
            [column["sourceColumn"] for column in attached[0][1]["columns"]],
            ["Région", "Revenue"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            generate_tmdl(converted["datasources"], "Sales", {}, temporary)
            table = (Path(temporary) / "definition" / "tables" / "Sales_Query.tmdl"
                     ).read_text(encoding="utf-8")
            DataflowGenerator(temporary, "Sales").generate(converted)
            dataflow = (Path(temporary) / "Sales.Dataflow" / "queries" / "Sales_Query.m"
                        ).read_text(encoding="utf-8")
        self.assertIn("sourceColumn: 'Région'", table)
        self.assertIn("sourceColumn: Revenue", table)
        self.assertIn("SELECT [Région], Revenue FROM Sales", table)
        self.assertNotIn("column Unbound", table)
        self.assertIn(
            'List.Difference({"Région", "Revenue"}, Table.ColumnNames(SourceTable))',
            dataflow,
        )
        self.assertIn('Table.RenameColumns(CheckedSource, {{"Région", "R_gion"}})',
                      dataflow)
        self.assertNotIn("MissingField.Ignore", dataflow)

    def test_ambiguous_sql_table_names_do_not_bind_columns(self):
        for second_sql, expected_tables in (("SELECT Id FROM People", 2), ("", 1)):
            with self.subTest(second_sql=second_sql):
                extracted = self._extracted(
                    [
                        {"name": "Shared Query", "sql": "SELECT Id FROM Sales",
                         "datasource": "Sales DB"},
                        {"name": "shared query", "sql": second_sql,
                         "datasource": "People DB"},
                    ],
                    [
                        {"name": "Sales DB", "type": "SQL Server"},
                        {"name": "People DB", "type": "SQL Server"},
                    ],
                )
                extracted["columns"] = [
                    {"name": "Id", "table": "SHARED QUERY", "data_type": "integer"},
                ]
                attached = self._sql_tables(adapt_bo_to_converted_objects(extracted))

                self.assertEqual(len(attached), expected_tables)
                self.assertTrue(all(not table["columns"] for _, table in attached))

    def test_sql_table_columns_are_not_bound_to_conflicting_provider_names(self):
        xml = """\
        <document>
          <connection id="sales-ref" name="Sales DB" type="SQL Server"/>
          <dataProvider name="Sales_Query" connectionId="sales-ref">
            <ResultObject name="OrderId" table="Sales_Query"/>
            <SQL>SELECT OrderId FROM Sales</SQL>
          </dataProvider>
          <dataProvider name="sales_query" connectionId="sales-ref">
            <ResultObject name="EmployeeId" table="Sales_Query"/>
          </dataProvider>
        </document>
        """
        extracted = extract_webi("in-memory.wid", artifact_data={"document.xml": xml})
        with self.assertLogs("bo_export.converted_objects_adapter", level="WARNING") as logged:
            attached = self._sql_tables(adapt_bo_to_converted_objects(extracted))

        self.assertEqual(len(extracted["queries"]), 2)
        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0][1]["columns"], [])
        self.assertIn("ambiguous or incomplete", " ".join(logged.output))

    def test_sql_table_columns_are_not_bound_to_a_different_named_query(self):
        extracted = self._extracted(
            [{"name": "Orders", "sql": "SELECT OrderId FROM Sales",
              "datasource": "Sales DB"}],
            [{"name": "Sales DB", "type": "SQL Server"}],
        )
        extracted["columns"] = [{"name": "OrderId", "table": "Orders"}]
        for query in (
            {"name": "Orders", "sql": "", "datasource": "Sales DB"},
            {"name": "Orders", "sql": "SELECT OrderId FROM Sales",
             "datasource": "Other DB"},
        ):
            with self.subTest(query=query):
                extracted["queries"] = [query]
                attached = self._sql_tables(adapt_bo_to_converted_objects(extracted))
                self.assertEqual(len(attached), 1)
                self.assertEqual(attached[0][1]["columns"], [])

    def test_sql_name_colliding_with_physical_table_does_not_bind_columns(self):
        extracted = self._extracted(
            [{"name": "sales", "sql": "SELECT Id FROM OtherSales"}],
            [{"name": "Sales DB", "type": "SQL Server"}],
        )
        extracted["tables"] = [{"name": "Sales", "type": "physical"}]
        extracted["columns"] = [
            {"name": "Id", "table": "Sales", "data_type": "integer"},
        ]
        attached = self._sql_tables(adapt_bo_to_converted_objects(extracted))

        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0][1]["columns"], [])

    def test_bound_sql_is_attached_once_and_generates_source_specific_m(self):
        extracted = self._extracted(
            [
                {"name": "Sales SQL", "sql": "SELECT OrderId FROM SalesOrders",
                 "datasource": "conn-ref-sales"},
                {"name": "People SQL", "sql": "SELECT PersonId FROM People",
                 "datasource": "conn-ref-people"},
            ],
            [
                {"id": "conn-ref-sales", "name": "Sales DB", "type": "SQL Server",
                 "server": "sales-db.example.invalid", "database": "SalesWarehouse"},
                {"id": "conn-ref-people", "name": "People DB", "type": "PostgreSQL",
                 "server": "people-db.example.invalid", "database": "PeopleWarehouse"},
            ],
        )
        extracted["columns"] = [
            {"name": "OrderId", "table": "Sales SQL", "data_type": "integer"},
            {"name": "PersonId", "table": "People SQL", "data_type": "integer"},
        ]
        extracted["queries"] = [
            {"name": "Sales SQL", "sql": "SELECT OrderId FROM SalesOrders",
             "datasource": "conn-ref-sales"},
            {"name": "People SQL", "sql": "SELECT PersonId FROM People",
             "datasource": "conn-ref-people"},
        ]
        converted = adapt_bo_to_converted_objects(extracted)

        attached = self._sql_tables(converted)
        self.assertEqual(
            {(source, table["name"], table["sql"]) for source, table in attached},
            {
                ("Sales DB", "Sales SQL", "SELECT OrderId FROM SalesOrders"),
                ("People DB", "People SQL", "SELECT PersonId FROM People"),
            },
        )
        self.assertEqual(len(attached), 2)
        self.assertEqual(
            {source: [column["name"] for column in table["columns"]]
             for source, table in attached},
            {"Sales DB": ["OrderId"], "People DB": ["PersonId"]},
        )

        with tempfile.TemporaryDirectory() as temporary:
            DataflowGenerator(temporary, "SqlBinding").generate(converted)
            query_dir = Path(temporary) / "SqlBinding.Dataflow" / "queries"
            sales_m = (query_dir / "Sales_SQL.m").read_text(encoding="utf-8")
            people_m = (query_dir / "People_SQL.m").read_text(encoding="utf-8")

        self.assertIn('Sql.Database("sales-db.example.invalid", "SalesWarehouse")', sales_m)
        self.assertIn("Value.NativeQuery", sales_m)
        self.assertIn("SELECT OrderId FROM SalesOrders", sales_m)
        self.assertNotIn("people-db.example.invalid", sales_m)
        self.assertIn('PostgreSQL.Database("people-db.example.invalid", "PeopleWarehouse")', people_m)
        self.assertIn("Value.NativeQuery", people_m)
        self.assertIn("SELECT PersonId FROM People", people_m)
        self.assertNotIn("sales-db.example.invalid", people_m)

    def test_unbound_sql_infers_the_only_datasource(self):
        extracted = self._extracted(
            [{"name": "Unbound SQL", "sql": "SELECT ItemId FROM Items"}],
            [{"name": "Only Source", "type": "SQL Server",
              "server": "only-db.example.invalid", "database": "OnlyDatabase"}],
        )
        converted = adapt_bo_to_converted_objects(extracted)
        attached = self._sql_tables(converted)

        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0][0], "Only Source")
        with tempfile.TemporaryDirectory() as temporary:
            DataflowGenerator(temporary, "SingleSource").generate(converted)
            m_query = (Path(temporary) / "SingleSource.Dataflow" / "queries"
                       / "Unbound_SQL.m").read_text(encoding="utf-8")

        self.assertIn('Sql.Database("only-db.example.invalid", "OnlyDatabase")', m_query)
        self.assertIn("Value.NativeQuery", m_query)
        self.assertIn("SELECT ItemId FROM Items", m_query)
        self.assertNotIn('Sql.Database("localhost", "MyDB")', m_query)

    def test_native_sql_and_connection_preserve_m_literal_values(self):
        extracted = self._extracted(
            [{"name": "Sales SQL", "datasource": "Sales DB",
              "sql": 'SELECT "Région", \'#(lf)\' AS Marker\r\n'
                     'FROM [dbo].[Sales]\tWHERE [Active] = 1'}],
            [{"name": "Sales DB", "type": "SQL Server",
              "server": r"dbhost\REPORTS", "database": 'Ventes "#(cr)"'}],
        )
        converted = adapt_bo_to_converted_objects(extracted)

        with tempfile.TemporaryDirectory() as temporary:
            DataflowGenerator(temporary, "Escaping").generate(converted)
            m_query = (Path(temporary) / "Escaping.Dataflow" / "queries"
                       / "Sales_SQL.m").read_text(encoding="utf-8")

        self.assertIn(
            'Sql.Database("dbhost\\REPORTS", "Ventes ""#(#)(cr)""")', m_query
        )
        self.assertIn(
            'Value.NativeQuery(Source, "SELECT ""Région"", \'#(#)(lf)\' AS Marker'
            '#(cr)#(lf)FROM [dbo].[Sales]#(tab)WHERE [Active] = 1")',
            m_query,
        )

    def test_file_connection_keeps_windows_path_and_literal_escape_marker(self):
        m_query = build_m_query({
            "type": "excel",
            "file_path": r"C:\Data\Région#(tab).xlsx",
        })

        self.assertIn(
            'File.Contents("C:\\Data\\Région#(#)(tab).xlsx")', m_query
        )

    def test_universe_table_navigation_preserves_schema_and_m_identifiers(self):
        table_name = 'Orders "2026" #(lf)'
        extracted = {
            "datasources": [
                {"name": "Warehouse", "type": "SQL Server",
                 "server": "sql.example.test", "database": "Sales"}
            ],
            "tables": [
                {"name": table_name, "schema": 'Finance "East" #(tab)', "type": "table"}
            ],
            "columns": [{"name": "OrderID", "table": table_name, "data_type": "integer"}],
            "custom_sql": [],
        }
        converted = adapt_bo_to_converted_objects(extracted)
        expected = (
            'Source{[Schema="Finance ""East"" #(#)(tab)", '
            'Item="Orders ""2026"" #(#)(lf)"]}[Data]'
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generate_tmdl(converted["datasources"], "Sales", {}, temporary)
            DataflowGenerator(temporary, "Sales").generate(converted)
            model_tables = [
                path.read_text(encoding="utf-8")
                for path in (root / "definition" / "tables").glob("*.tmdl")
            ]
            dataflow_queries = [
                path.read_text(encoding="utf-8")
                for path in (root / "Sales.Dataflow" / "queries").glob("*.m")
            ]

        self.assertTrue(any(expected in table for table in model_tables))
        self.assertTrue(any(expected in query for query in dataflow_queries))

    def test_universe_query_map_uses_each_table_schema_without_mutating_connection(self):
        connection = {"type": "SQL Server", "server": "sql.example.test",
                      "database": "Sales", "schema": "dbo"}
        queries = build_m_query_for_universe(connection, [
            {"name": "Orders", "schema": "finance"},
            {"name": "Customers", "schema": "crm"},
            {"name": "Default"},
        ], [], [])

        self.assertIn('Schema="finance", Item="Orders"', queries["Orders"])
        self.assertIn('Schema="crm", Item="Customers"', queries["Customers"])
        self.assertIn('Schema="dbo", Item="Default"', queries["Default"])
        self.assertEqual(connection["schema"], "dbo")

    def test_import_model_keeps_sql_and_navigation_errors_visible(self):
        extracted = {
            "datasources": [
                {"name": "Sales DB", "type": "SQL Server",
                 "server": r"dbhost\REPORTS", "database": "Sales"}
            ],
            "tables": [
                {"name": "Sales", "type": "physical"},
                {"name": "Native SQL", "type": "derived",
                 "sql": 'SELECT "Id", \'#(lf)\' AS Marker\nFROM [dbo].[Sales]'},
            ],
            "columns": [
                {"name": "Id", "table": "Sales", "data_type": "integer"},
                {"name": "Id", "table": "Native SQL", "data_type": "integer"},
            ],
            "custom_sql": [],
        }
        converted = adapt_bo_to_converted_objects(extracted)

        with tempfile.TemporaryDirectory() as temporary:
            generate_tmdl(converted["datasources"], "Sales", {}, temporary)
            table_dir = Path(temporary) / "definition" / "tables"
            sql_table = (table_dir / "Native SQL.tmdl").read_text(encoding="utf-8")
            physical_table = (table_dir / "Sales.tmdl").read_text(encoding="utf-8")

        self.assertIn('Sql.Database("dbhost\\REPORTS", "Sales")', sql_table)
        self.assertIn(
            'Value.NativeQuery(Source, "SELECT ""Id"", \'#(#)(lf)\' AS Marker'
            '#(lf)FROM [dbo].[Sales]")',
            sql_table,
        )
        self.assertIn('Source{[Schema="dbo", Item="Sales"]}[Data]', physical_table)
        self.assertNotIn("otherwise", sql_table)
        self.assertNotIn("otherwise", physical_table)

    def test_explicit_universe_column_sources_and_unsupported_expressions(self):
        extracted = {
            "datasources": [
                {"name": "Warehouse", "type": "SQL Server",
                 "server": "sql.example.test", "database": "Sales"}
            ],
            "tables": [{"name": "DIM_TIME", "type": "table"}],
            "columns": [
                {"name": "Business Year", "table": "DIM_TIME", "data_type": "integer",
                 "select_sql": "DIM_TIME.[Fiscal Year]"},
                {"name": "Revenue", "table": "DIM_TIME", "qualification": "measure",
                 "select_sql": "SUM(DIM_TIME.REVENUE)"},
                {"name": "Other source", "table": "DIM_TIME",
                 "select_sql": "OTHER.VALUE"},
                {"name": "Filtered", "table": "DIM_TIME", "select_sql": "DIM_TIME.VALUE",
                 "where_clause": "DIM_TIME.ACTIVE = 1"},
            ],
        }

        converted = adapt_bo_to_converted_objects(extracted)
        columns = {
            column["name"]: column
            for column in converted["datasources"][0]["tables"][0]["columns"]
        }
        self.assertEqual(columns["Business Year"]["sourceColumn"], "Fiscal Year")
        self.assertTrue(columns["Revenue"]["source_expression_untranslated"])
        self.assertTrue(columns["Other source"]["source_expression_untranslated"])
        self.assertTrue(columns["Filtered"]["source_expression_untranslated"])
        self.assertNotIn("sourceColumn", columns["Revenue"])
        self.assertNotIn("sourceColumn", columns["Other source"])

        with tempfile.TemporaryDirectory() as temporary:
            generate_tmdl(converted["datasources"], "Universe", {}, temporary)
            table = (Path(temporary) / "definition" / "tables" / "DIM_TIME.tmdl"
                     ).read_text(encoding="utf-8")
        business_year = table.split("\tcolumn 'Business Year'", 1)[1].split("\n\tcolumn ", 1)[0]
        self.assertIn("sourceColumn: 'Fiscal Year'", business_year)
        self.assertIn('Source{[Schema="dbo", Item="DIM_TIME"]}[Data]', table)

    def test_unbound_sql_with_multiple_datasources_is_not_duplicated_or_guessed(self):
        extracted = self._extracted(
            [{"name": "Ambiguous SQL", "sql": "SELECT Id FROM UnknownSource"}],
            [
                {"name": "Source A", "type": "SQL Server",
                 "server": "source-a.example.invalid", "database": "A"},
                {"name": "Source B", "type": "SQL Server",
                 "server": "source-b.example.invalid", "database": "B"},
            ],
        )
        converted = adapt_bo_to_converted_objects(extracted)

        attached = self._sql_tables(converted)
        self.assertEqual(attached, [], "An ambiguous SQL query must not be attached to a datasource")
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "(?i)ambiguous|datasource|data source"):
                DataflowGenerator(temporary, "AmbiguousSources").generate(converted)

            generated_files = list(
                (Path(temporary) / "AmbiguousSources.Dataflow").rglob("*.m")
            )
            for path in generated_files:
                m_query = path.read_text(encoding="utf-8")
                self.assertNotIn('Sql.Database("localhost", "MyDB")', m_query)


if __name__ == "__main__":
    unittest.main()
