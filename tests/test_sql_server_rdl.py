"""Contract tests for SQL Server-backed explicitly mapped RDL."""

import copy
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from bo_export.extract_bo_data import extract_bo_data
from bo_export.server_client import BOServerClient, load_webi_query_plan
from bo_export.webi_extractor import extract_webi
from migrate import main
from migrate_paginated import main as paginated_main
from powerbi_import.paginated_generator import generate_semantic_model_rdl


NS = {
    "r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition",
}


def _sql_mapping(source_kind="webi"):
    return {
        "title": "Synthèse des ventes",
        "source_kind": source_kind,
        "server": "sql.example.test",
        "database": "SalesWarehouse",
        "sql": "SELECT [Region], [Net Sales] FROM [dbo].[Sales]",
        "columns": ["Region", "Net Sales"],
    }


def _webi_api_plan(xml, provider_id="DP0"):
    client = BOServerClient("https://bo.example.invalid", token="synthetic-token")
    client.logon()
    with patch("bo_export.server_client.urllib.request.urlopen",
               return_value=BytesIO(xml.encode("utf-8"))):
        return client.get_webi_query_plan("synthetic-document", provider_id)


def _make_native_wid(path, provider_id="DP0"):
    document = ET.Element("DOCUMENT", RSVERSION="2.5")
    report = ET.SubElement(document, "REPORT", RID="1")
    name = ET.SubElement(ET.SubElement(report, "PLIST"), "PVAL", NAME="name")
    name.text = json.dumps({"l": "Synthetic report"})
    document_body = ET.tostring(document, encoding="utf-8")
    document_record = (
        (len(document_body) + 8).to_bytes(4, "little")
        + b"\x05\x00\x02\x00" + document_body
    )
    provider_name = "Synthetic provider".encode("utf-16le")
    provider_xml = (
        '<queryspec:QuerySpec xmlns:queryspec="http://com.sap.sl.queryspec" '
        f'dataProviderId="{provider_id}"><queriesTree><bOQuery>'
        '<resultObjects identifier="obj-1" name="Region"/>'
        '</bOQuery></queriesTree></queryspec:QuerySpec>'
    ).encode("utf-16le")
    provider_body = (
        (len(provider_name) // 2).to_bytes(4, "little") + provider_name
        + b"\x01\x00" + provider_xml + b"\x00binary-tail"
    )
    provider_record = (
        (len(provider_body) + 8).to_bytes(4, "little")
        + b"\x02\x00\x03\x00" + provider_body
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Data/RE/DOCSPEC", document_record)
        archive.writestr(f"Data/C3/DATAPROVIDERS/{provider_id}/DP_Generic", provider_record)


class SqlServerRdlTests(unittest.TestCase):
    def test_api_query_plan_and_native_wid_generate_rdl_and_power_query(self):
        sql = "SELECT [Region], [Net Sales] FROM [dbo].[Sales] WHERE [Net Sales] > 0"
        plan = _webi_api_plan(
            '<queryplan><statement index="1">SELECT [Region], [Net Sales] '
            'FROM [dbo].[Sales] WHERE [Net Sales] &gt; 0</statement></queryplan>'
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wid = root / "synthetic.wid"
            _make_native_wid(wid)
            extracted = extract_webi(str(wid))
            self.assertEqual(extracted["queries"][0]["id"], "DP0")
            self.assertTrue(extracted["queries"][0]["native_wid_partial"])
            self.assertEqual(extracted["queries"][0]["sql"], "")
            self.assertEqual(extracted["datasources"], [])

            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            mapping = _sql_mapping()
            del mapping["sql"]
            mapping["columns"] = [
                {"field": "Region", "label": "Région"},
                {"field": "Net Sales", "label": "Chiffre d'affaires"},
            ]
            mapping_path = root / "mapping.json"
            mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
            report_path = root / "report.rdl"
            query_path = root / "query.m"

            self.assertEqual(main([
                "--output-format", "rdl", "--rdl-mapping", str(mapping_path),
                "--rdl-output", str(report_path), "--rdl-webi-plan", str(plan_path),
                "--rdl-bo-source", str(wid), "--rdl-power-query-output", str(query_path),
            ]), 0)
            report = ET.parse(report_path).getroot()
            self.assertEqual(report.findtext(".//r:CommandText", namespaces=NS), sql)
            self.assertEqual(
                [field.text for field in report.findall(".//r:Fields/r:Field/r:DataField", NS)],
                ["Region", "Net Sales"],
            )
            self.assertEqual(
                report.findtext(".//r:Textbox[@Name='Header1']//r:Value", namespaces=NS),
                "Région",
            )
            self.assertEqual(
                report.findtext(".//r:Textbox[@Name='Header2']//r:Value", namespaces=NS),
                "Chiffre d'affaires",
            )
            self.assertIn(sql, query_path.read_text(encoding="utf-8"))
            self.assertIn(
                'Sql.Database("sql.example.test", "SalesWarehouse")',
                query_path.read_text(encoding="utf-8"),
            )

    def test_documented_webi_plan_example_generates_rdl_and_m(self):
        fixtures = Path(__file__).resolve().parent.parent / "docs" / "fixtures"
        plan = fixtures / "webi_query_plan.example.json"
        mapping = fixtures / "webi_rdl_mapping.example.json"
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "example.rdl"
            query_path = Path(directory) / "example.m"
            self.assertEqual(main([
                "--output-format", "rdl", "--rdl-mapping", str(mapping),
                "--rdl-webi-plan", str(plan), "--rdl-output", str(report_path),
                "--rdl-power-query-output", str(query_path),
            ]), 0)
            report = ET.parse(report_path).getroot()
            sql = "SELECT [Region], [Net Sales] FROM [dbo].[Sales]"
            self.assertEqual(report.findtext(".//r:CommandText", namespaces=NS), sql)
            self.assertIn(sql, query_path.read_text(encoding="utf-8"))

    def test_webi_plan_rejects_complex_or_inconsistent_queries_before_output(self):
        single = _webi_api_plan(
            '<queryplan><statement index="1">SELECT [Region] FROM [dbo].[Sales]'
            '</statement></queryplan>'
        )
        combined = _webi_api_plan(
            '<queryplan><union><statement index="1">SELECT 1</statement>'
            '<statement index="2">SELECT 2</statement></union></queryplan>'
        )
        empty = _webi_api_plan('<queryplan/>')
        prompted = _webi_api_plan(
            "<queryplan><statement>SELECT @Prompt('Region', 'A',,Mono,Free)"
            "</statement></queryplan>"
        )
        tampered = copy.deepcopy(combined)
        tampered["single_statement"] = True
        altered_sql = copy.deepcopy(single)
        altered_sql["statements"][0]["sql"] = "SELECT 2"
        non_boolean = copy.deepcopy(single)
        non_boolean["single_statement"] = 1
        prohibited = copy.deepcopy(single)
        prohibited["xml"] = '<!DOCTYPE queryplan><queryplan/>'
        stray_text = _webi_api_plan(
            '<queryplan>unexpected<statement>SELECT 1</statement></queryplan>'
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mapping = _sql_mapping()
            del mapping["sql"]
            mapping_path = root / "mapping.json"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            plan_path = root / "plan.json"
            report_path = root / "report.rdl"
            query_path = root / "query.m"
            for plan in (combined, empty, prompted, tampered, altered_sql,
                         non_boolean, prohibited, stray_text):
                with self.subTest(plan=plan):
                    plan_path.write_text(json.dumps(plan), encoding="utf-8")
                    self.assertEqual(paginated_main([
                        "--mapping", str(mapping_path), "--output", str(report_path),
                        "--webi-plan", str(plan_path), "--power-query-output", str(query_path),
                    ]), 2)
                    self.assertFalse(report_path.exists())
                    self.assertFalse(query_path.exists())

    def test_webi_plan_requires_matching_provider_and_unambiguous_options(self):
        plan = _webi_api_plan('<queryplan><statement>SELECT 1</statement></queryplan>')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            mapping = _sql_mapping()
            del mapping["sql"]
            mapping_path = root / "mapping.json"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            wid = root / "synthetic.wid"
            _make_native_wid(wid, "DP1")
            report = root / "report.rdl"
            base = ["--mapping", str(mapping_path), "--output", str(report),
                    "--webi-plan", str(plan_path)]
            for extra in (
                ["--bo-source", str(wid)],
                ["--bo-source", str(plan_path)],
                ["--sql-name", "Query"],
                ["--extracted-sql", str(plan_path)],
            ):
                with self.subTest(extra=extra):
                    self.assertEqual(paginated_main(base + extra), 2)
                    self.assertFalse(report.exists())

            mapping["source_kind"] = "crystal"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            self.assertEqual(paginated_main(base), 2)
            self.assertFalse(report.exists())
            mapping["source_kind"] = "webi"
            mapping["sql"] = "SELECT 2"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            self.assertEqual(paginated_main(base), 2)
            self.assertFalse(report.exists())
            self.assertEqual(main(["--rdl-webi-plan", str(plan_path)]), 3)

    def test_webi_plan_snapshot_rejects_duplicate_keys_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text('{"document_id":"1","document_id":"2"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate key"):
                load_webi_query_plan(path)
            path.write_text('{"document_id":"synthetic"}', encoding="utf-8")
            with patch("bo_export.server_client._WEBI_PLAN_SNAPSHOT_LIMIT", 4):
                with self.assertRaisesRegex(ValueError, "maximum supported size"):
                    load_webi_query_plan(path)

    def test_synthetic_bo_examples_emit_selected_sql_in_rdl_and_m(self):
        examples = Path(__file__).resolve().parent.parent / "examples"
        cases = (
            ("webi", "Enterprise_Sales.wid", "Sales_Query",
             ["YEAR", "QUARTER", "PRODUCT_LINE", "REGION"]),
            ("universe", "eFashion_Universe.unx", "SALES_SUMMARY",
             ["FISCAL_YEAR", "PRODUCT_LINE", "REGION", "TOTAL_REV"]),
        )
        for kind, filename, sql_name, fields in cases:
            with self.subTest(source=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = examples / filename
                extracted = extract_bo_data(str(source), output_dir=str(root / "extracted"))
                expected_sql = next(
                    query["sql"] for query in extracted["custom_sql"]
                    if query["name"] == sql_name
                )
                mapping = _sql_mapping(kind)
                del mapping["sql"]
                mapping["columns"] = fields
                mapping_path = root / "mapping.json"
                mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
                report_path = root / "report.rdl"
                query_path = root / "query.m"

                self.assertEqual(main([
                    "--output-format", "rdl", "--rdl-mapping", str(mapping_path),
                    "--rdl-output", str(report_path), "--rdl-bo-source", str(source),
                    "--rdl-sql-name", sql_name, "--rdl-power-query-output", str(query_path),
                ]), 0)
                report = ET.parse(report_path).getroot()
                self.assertEqual(report.findtext(".//r:CommandText", namespaces=NS), expected_sql)
                self.assertEqual(
                    [field.text for field in report.findall(".//r:Fields/r:Field/r:DataField", NS)],
                    fields,
                )
                m_query = query_path.read_text(encoding="utf-8")
                self.assertIn(expected_sql, m_query)
                self.assertIn('Sql.Database("sql.example.test", "SalesWarehouse")', m_query)

    def test_webi_and_universe_mappings_generate_sql_dataset(self):
        for source_kind in ("webi", "crystal", "lumira", "desktop_intelligence",
                            "xcelsius", "analysis_olap", "universe"):
            with self.subTest(source_kind=source_kind):
                mapping = _sql_mapping(source_kind)
                root = ET.fromstring(generate_semantic_model_rdl(mapping))

                self.assertEqual(root.tag, f"{{{NS['r']}}}Report")
                self.assertIn(f"source: {source_kind}", root.findtext("r:Description", namespaces=NS))
                self.assertEqual(
                    root.findtext(".//r:DataProvider", namespaces=NS),
                    "SQL",
                )
                connect_string = root.findtext(".//r:ConnectString", namespaces=NS)
                self.assertIsNotNone(connect_string)
                connection_parts = [
                    part.strip().split("=", 1) for part in connect_string.split(";")
                ]
                self.assertTrue(all(len(part) == 2 for part in connection_parts))
                self.assertEqual(
                    {key.strip().casefold(): value.strip() for key, value in connection_parts},
                    {
                        "data source": mapping["server"],
                        "initial catalog": mapping["database"],
                    },
                )
                self.assertEqual(
                    root.findtext(".//r:CommandType", namespaces=NS),
                    "Text",
                )
                self.assertEqual(
                    root.findtext(".//r:CommandText", namespaces=NS),
                    mapping["sql"],
                )
                self.assertIsNone(root.find("r:ReportParameters", NS))
                self.assertIsNone(root.find(".//r:QueryParameters", NS))
                self.assertEqual(
                    [
                        field.text
                        for field in root.findall(".//r:Fields/r:Field/r:DataField", NS)
                    ],
                    mapping["columns"],
                )

    def test_new_source_labels_work_through_both_cli_entry_points(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for kind in ("crystal", "lumira", "desktop_intelligence", "xcelsius", "analysis_olap"):
                with self.subTest(kind=kind):
                    mapping = folder / f"{kind}.json"
                    mapping.write_text(json.dumps(_sql_mapping(kind)), encoding="utf-8")
                    for entry in ("main", "standalone"):
                        output = folder / f"{kind}-{entry}.rdl"
                        if entry == "main":
                            result = main(["--output-format", "rdl", "--rdl-mapping",
                                           str(mapping), "--rdl-output", str(output)])
                        else:
                            result = paginated_main(["--mapping", str(mapping), "--output", str(output)])
                        self.assertEqual(result, 0)
                        root = ET.parse(output).getroot()
                        self.assertEqual(root.findtext(".//r:CommandText", namespaces=NS),
                                         "SELECT [Region], [Net Sales] FROM [dbo].[Sales]")
                        self.assertIn(f"source: {kind}", root.findtext("r:Description", namespaces=NS))

    def test_rejects_unknown_source_kind_and_connection_string_injection(self):
        mutations = (
            {"source_kind": "unknown"},
            {"server": "sql.example.test;Initial Catalog=OtherDb"},
            {"database": "SalesWarehouse;Encrypt=False"},
            {"server": "sql.example.test};Initial Catalog=OtherDb"},
            {"database": "{SalesWarehouse};Encrypt=False"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                mapping = _sql_mapping()
                mapping.update(mutation)
                with self.assertRaises(ValueError):
                    generate_semantic_model_rdl(mapping)

    def test_preserves_unicode_and_punctuation_in_connection_values(self):
        mapping = _sql_mapping()
        mapping["server"] = "sql-équipe O'Brien%/cluster (east)"
        mapping["database"] = "Ventes d'été 100% / région (2026)"

        root = ET.fromstring(generate_semantic_model_rdl(mapping))

        self.assertEqual(
            root.findtext(".//r:ConnectString", namespaces=NS),
            f"Data Source={mapping['server']};Initial Catalog={mapping['database']}",
        )

    def test_sql_mapping_requires_the_exact_contract_keys(self):
        extra_key = _sql_mapping()
        extra_key["workspace"] = "Not part of the SQL mapping"
        missing_key = _sql_mapping()
        del missing_key["database"]

        for mapping in (extra_key, missing_key):
            with self.subTest(keys=sorted(mapping)):
                with self.assertRaises(ValueError):
                    generate_semantic_model_rdl(mapping)

    def test_rejects_credentials_and_sql_containing_a_possible_secret(self):
        mutations = (
            {"server": "sql.example.test;User ID=synthetic;Password=not-a-real-secret"},
            {"sql": "SELECT 'password=not-a-real-secret' AS [Value]"},
        )
        for mutation in mutations:
            with self.subTest(field=next(iter(mutation))):
                mapping = _sql_mapping()
                mapping.update(mutation)
                with self.assertRaises(ValueError):
                    generate_semantic_model_rdl(mapping)

    def test_rejects_empty_sql_and_invalid_columns(self):
        mutations = (
            {"sql": ""},
            {"sql": "   "},
            {"columns": []},
            {"columns": ["Region", "region"]},
            {"columns": ["Region", ""]},
            {"columns": ["Region", "Net Sales\nFROM SecretTable"]},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                mapping = _sql_mapping()
                mapping.update(copy.deepcopy(mutation))
                with self.assertRaises(ValueError):
                    generate_semantic_model_rdl(mapping)

    def test_rejects_non_select_and_data_modification_queries(self):
        queries = (
            "UPDATE [dbo].[Sales] SET [Region] = 'West'",
            "DELETE FROM [dbo].[Sales]",
            "INSERT INTO [dbo].[Sales] ([Region]) VALUES ('West')",
            "DROP TABLE [dbo].[Sales]",
        )
        for sql in queries:
            with self.subTest(sql=sql):
                mapping = _sql_mapping()
                mapping["sql"] = sql
                with self.assertRaises(ValueError):
                    generate_semantic_model_rdl(mapping)

    def test_rejects_multi_statement_sql_and_select_into(self):
        queries = (
            "SELECT [Region] FROM [dbo].[Sales]; DELETE FROM [dbo].[Sales]",
            "SELECT [Region] INTO [dbo].[SalesCopy] FROM [dbo].[Sales]",
        )
        for sql in queries:
            with self.subTest(sql=sql):
                mapping = _sql_mapping()
                mapping["sql"] = sql
                with self.assertRaises(ValueError):
                    generate_semantic_model_rdl(mapping)

    def test_rejects_businessobjects_prompt_and_variable_macros(self):
        queries = (
            "SELECT @Prompt('Region', 'A',,Mono,Free) AS [Region]",
            "SELECT @Variable('BOUSER') AS [UserName]",
        )
        for sql in queries:
            with self.subTest(sql=sql):
                mapping = _sql_mapping()
                mapping["sql"] = sql
                with self.assertRaises(ValueError):
                    generate_semantic_model_rdl(mapping)

    def test_rejects_unbound_sql_server_parameter(self):
        mapping = _sql_mapping()
        mapping["sql"] = (
            "SELECT [Region] FROM [dbo].[Sales] WHERE [Region] = @Region"
        )

        with self.assertRaises(ValueError):
            generate_semantic_model_rdl(mapping)

    def test_explicit_scalar_parameters_bind_sql_and_report_parameters(self):
        mapping = _sql_mapping()
        mapping["sql"] = (
            "SELECT [Region], [Net Sales] FROM [dbo].[Sales] "
            "WHERE [Region] = @Region AND [Net Sales] >= @MinimumSales "
            "AND [Active] = @IsActive AND [Date] >= @StartDate "
            "AND [Id] >= @MinimumId AND [Note] <> '@Literal' "
            "-- @Comment\nAND @@SPID > 0"
        )
        mapping["parameters"] = [
            {"name": "Region", "data_type": "String"},
            {"name": "MinimumSales", "data_type": "Float"},
            {"name": "IsActive", "data_type": "Boolean"},
            {"name": "StartDate", "data_type": "DateTime"},
            {"name": "MinimumId", "data_type": "Integer"},
        ]

        root = ET.fromstring(generate_semantic_model_rdl(mapping))

        self.assertEqual(
            [(parameter.get("Name"),
              parameter.findtext("r:DataType", namespaces=NS),
              parameter.findtext("r:Prompt", namespaces=NS))
             for parameter in root.findall(".//r:ReportParameters/r:ReportParameter", NS)],
            [(parameter["name"], parameter["data_type"], parameter["name"])
             for parameter in mapping["parameters"]],
        )
        self.assertEqual(
            [
                (parameter.get("Name"), parameter.findtext("r:Value", namespaces=NS))
                for parameter in root.findall(".//r:QueryParameters/r:QueryParameter", NS)
            ],
            [("@Region", "=Parameters!Region.Value"),
             ("@MinimumSales", "=Parameters!MinimumSales.Value"),
             ("@IsActive", "=Parameters!IsActive.Value"),
             ("@StartDate", "=Parameters!StartDate.Value"),
             ("@MinimumId", "=Parameters!MinimumId.Value")],
        )

    def test_parameter_references_are_complete_and_unambiguous(self):
        mapping = _sql_mapping()
        mapping["sql"] = (
            "SELECT [Region] FROM [dbo].[Sales] WHERE [Region] = @Region"
        )
        invalid_parameter_contracts = (
            [{"name": "Other", "data_type": "String"}],
            [{"name": "Region", "data_type": "String"},
             {"name": "region", "data_type": "Integer"}],
            [{"name": "Region", "data_type": "Unsupported"}],
            [{"name": "Region", "data_type": []}],
            [{"name": "Region Name", "data_type": "String"}],
            [{"name": "Region", "data_type": "String", "default": "West"}],
            {"name": "Region", "data_type": "String"},
        )
        for parameters in invalid_parameter_contracts:
            with self.subTest(parameters=parameters):
                mapping["parameters"] = parameters
                with self.assertRaises(ValueError):
                    generate_semantic_model_rdl(mapping)

    def test_parameter_declarations_are_scoped_to_sql_rdl_mappings(self):
        mapping = _sql_mapping()
        mapping["sql"] = "SELECT [Region] FROM [dbo].[Sales] WHERE [Region] = @Region"
        mapping["parameters"] = [{"name": "Region", "data_type": "String"}]
        generated = generate_semantic_model_rdl(mapping)
        self.assertIn("QueryParameters", generated)

        dax_mapping = {
            "title": "Sales",
            "source_kind": "webi",
            "workspace": "Workspace",
            "semantic_model": "Model",
            "dax": "EVALUATE 'Sales'",
            "columns": ["Region"],
            "parameters": [{"name": "Region", "data_type": "String"}],
        }
        with self.assertRaises(ValueError):
            generate_semantic_model_rdl(dax_mapping)

    def test_migrate_cli_generates_sql_server_rdl_from_mapping_file(self):
        mapping = _sql_mapping()

        with tempfile.TemporaryDirectory() as directory:
            mapping_path = Path(directory) / "mapping.json"
            output_path = Path(directory) / "report.rdl"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")

            result = main([
                "--output-format",
                "rdl",
                "--rdl-mapping",
                str(mapping_path),
                "--rdl-output",
                str(output_path),
            ])

            self.assertEqual(result, 0)
            root = ET.parse(output_path).getroot()
            self.assertEqual(
                root.findtext(".//r:DataProvider", namespaces=NS),
                "SQL",
            )
            self.assertEqual(
                root.findtext(".//r:CommandText", namespaces=NS),
                mapping["sql"],
            )

    def test_sql_fields_can_have_explicit_business_labels(self):
        mapping = _sql_mapping()
        mapping["columns"] = [
            {"field": "Region", "label": "Région d'été & ventes"},
            "Net Sales",
        ]
        root = ET.fromstring(generate_semantic_model_rdl(mapping))
        self.assertEqual(
            [field.text for field in root.findall(".//r:Fields/r:Field/r:DataField", NS)],
            ["Region", "Net Sales"],
        )
        self.assertEqual(
            [value.text for value in root.findall(
                ".//r:CellContents/r:Textbox/r:Paragraphs/r:Paragraph/r:TextRuns/r:TextRun/r:Value", NS
            )],
            ["Région d'été & ventes", "Net Sales", "=Fields!Field1.Value", "=Fields!Field2.Value"],
        )

    def test_rejects_invalid_business_labels_and_field_mappings(self):
        columns = (
            [{"field": "Region", "label": "=Globals!PageNumber"}],
            [{"field": "Region", "label": "bad\nlabel"}],
            [{"field": "Region", "label": "password=secret"}],
            [{"field": "Region"}],
            [{"field": "Region", "label": "Région", "other": "extra"}],
            [{"field": "Region", "label": "Région"}, {"field": "region", "label": "Autre"}],
        )
        for value in columns:
            with self.subTest(columns=value):
                mapping = _sql_mapping()
                mapping["columns"] = value
                with self.assertRaises(ValueError):
                    generate_semantic_model_rdl(mapping)

    def test_direct_webi_and_universe_file_to_rdl(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            webi = folder / "report.wid"
            webi.write_text(
                '<document><dataProvider name="Ventes"><sql>SELECT Region FROM Sales</sql>'
                '</dataProvider></document>',
                encoding="utf-8",
            )
            universe = folder / "universe.unx"
            with zipfile.ZipFile(universe, "w") as archive:
                archive.writestr(
                    "dataFoundation.xml",
                    '<dataFoundation><derivedTable name="Derived" '
                    'sql="SELECT Region FROM Sales"/></dataFoundation>',
                )
            for source, kind, query_name in (
                (webi, "webi", "Ventes"), (universe, "universe", "Derived")
            ):
                with self.subTest(source=source.name):
                    mapping = _sql_mapping(kind)
                    del mapping["sql"]
                    mapping["columns"] = [{"field": "Region", "label": "Région"}]
                    mapping_path = folder / f"{kind}.json"
                    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
                    output = folder / f"{kind}.rdl"
                    self.assertEqual(main([
                        "--output-format", "rdl", "--rdl-mapping", str(mapping_path),
                        "--rdl-output", str(output), "--rdl-bo-source", str(source),
                        "--rdl-sql-name", query_name,
                    ]), 0)
                    root = ET.parse(output).getroot()
                    self.assertEqual(root.findtext(".//r:CommandText", namespaces=NS),
                                     "SELECT Region FROM Sales")
                    self.assertEqual(root.findtext(".//r:DataField", namespaces=NS), "Region")
                    self.assertEqual(
                        root.findtext('.//r:Textbox[@Name="Header1"]//r:Value', namespaces=NS),
                        "Région",
                    )
            self.assertEqual({p.name for p in folder.iterdir()},
                             {"report.wid", "universe.unx", "webi.json", "universe.json",
                              "webi.rdl", "universe.rdl"})

    def test_direct_crystal_command_sql_to_rdl_and_power_query(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "sales.rpt"
            sql = "SELECT Region, Amount FROM dbo.Sales"
            source.write_bytes(b"\x00Crystal report text\x00" + sql.encode("ascii") + b";\x00")
            mapping = _sql_mapping("crystal")
            del mapping["sql"]
            mapping["columns"] = ["Region", "Amount"]
            mapping_path = folder / "crystal.json"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            rdl_path = folder / "crystal.rdl"
            m_path = folder / "crystal.m"

            self.assertEqual(main([
                "--output-format", "rdl", "--rdl-mapping", str(mapping_path),
                "--rdl-output", str(rdl_path), "--rdl-power-query-output", str(m_path),
                "--rdl-bo-source", str(source), "--rdl-sql-name", "CommandSQL",
            ]), 0)

            root = ET.parse(rdl_path).getroot()
            self.assertEqual(root.findtext(".//r:CommandText", namespaces=NS), sql)
            self.assertIn("source: crystal", root.findtext("r:Description", namespaces=NS))
            self.assertIn(f'Value.NativeQuery(Source, "{sql}")', m_path.read_text(encoding="utf-8"))

    def test_direct_bo_source_refuses_ambiguous_mismatched_and_missing_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "report.wid"
            source.write_text(
                '<document><dataProvider name="Query"><sql>SELECT 1</sql>'
                '<sql>SELECT 2</sql></dataProvider></document>', encoding="utf-8",
            )
            mapping = _sql_mapping()
            del mapping["sql"]
            mapping_path = folder / "mapping.json"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            output = folder / "report.rdl"
            base = ["--mapping", str(mapping_path), "--output", str(output)]
            for extra in (
                ["--bo-source", str(source), "--sql-name", "Query"],
                ["--bo-source", str(source), "--sql-name", "Missing"],
                ["--bo-source", str(source)],
                ["--bo-source", str(source), "--extracted-sql", "other.json", "--sql-name", "Query"],
                ["--bo-source", str(folder / "missing.wid"), "--sql-name", "Query"],
                ["--bo-source", str(mapping_path), "--sql-name", "Query"],
            ):
                with self.subTest(extra=extra):
                    self.assertEqual(paginated_main(base + extra), 2)
                    self.assertFalse(output.exists())
            mapping["source_kind"] = "universe"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            self.assertEqual(paginated_main(
                base + ["--bo-source", str(source), "--sql-name", "Query"]), 2)
            self.assertFalse(output.exists())
            mapping["source_kind"] = "crystal"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            self.assertEqual(paginated_main(
                base + ["--bo-source", str(source), "--sql-name", "Query"]), 2)
            self.assertFalse(output.exists())
            self.assertEqual(main(["--rdl-bo-source", str(source)]), 3)

    def test_new_source_labels_do_not_enable_unsupported_direct_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for kind, suffix in (("lumira", ".lumx"), ("desktop_intelligence", ".rep"), ("xcelsius", ".xlf"),
                                 ("analysis_olap", ".analysis")):
                with self.subTest(kind=kind):
                    source = folder / f"source{suffix}"
                    source.write_bytes(b"synthetic")
                    mapping = _sql_mapping(kind)
                    del mapping["sql"]
                    mapping_path = folder / f"{kind}.json"
                    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
                    output = folder / f"{kind}.rdl"
                    self.assertEqual(paginated_main(["--mapping", str(mapping_path),
                        "--output", str(output), "--bo-source", str(source),
                        "--sql-name", "Query"]), 2)
                    self.assertFalse(output.exists())

    def test_selected_bo_sql_generates_matching_rdl_and_power_query(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            webi = folder / "report.wid"
            webi.write_text(
                '<document><dataProvider name="Sales"><sql>'
                'SELECT &quot;Region&quot;, \'#(cr)\' AS Marker\nFROM [dbo].[Sales]'
                '</sql></dataProvider></document>',
                encoding="utf-8",
            )
            universe = folder / "universe.unx"
            with zipfile.ZipFile(universe, "w") as archive:
                archive.writestr(
                    "dataFoundation.xml",
                    '<dataFoundation><derivedTable name="Derived" '
                    'sql="SELECT Region FROM Sales"/></dataFoundation>',
                )

            for source, kind, query_name, expected_sql in (
                (webi, "webi", "Sales",
                 'SELECT "Region", \'#(cr)\' AS Marker\nFROM [dbo].[Sales]'),
                (universe, "universe", "Derived", "SELECT Region FROM Sales"),
            ):
                with self.subTest(kind=kind):
                    mapping = _sql_mapping(kind)
                    del mapping["sql"]
                    mapping["server"] = r"dbhost\REPORTS"
                    mapping["columns"] = ["Region"]
                    mapping_path = folder / f"{kind}.json"
                    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
                    rdl_path = folder / f"{kind}.rdl"
                    m_path = folder / f"{kind}.m"

                    self.assertEqual(main([
                        "--output-format", "rdl", "--rdl-mapping", str(mapping_path),
                        "--rdl-output", str(rdl_path),
                        "--rdl-power-query-output", str(m_path),
                        "--rdl-bo-source", str(source), "--rdl-sql-name", query_name,
                    ]), 0)
                    root = ET.parse(rdl_path).getroot()
                    self.assertEqual(
                        root.findtext(".//r:CommandText", namespaces=NS), expected_sql
                    )
                    m_query = m_path.read_text(encoding="utf-8")
                    self.assertIn(
                        'Sql.Database("dbhost\\REPORTS", "SalesWarehouse")', m_query
                    )
                    if kind == "webi":
                        self.assertIn(
                            'Value.NativeQuery(Source, "SELECT ""Region"", '
                            "'#(#)(cr)' AS Marker#(lf)FROM [dbo].[Sales]\")",
                            m_query,
                        )
                    else:
                        self.assertIn(
                            'Value.NativeQuery(Source, "SELECT Region FROM Sales")',
                            m_query,
                        )
                    self.assertNotIn("otherwise", m_query)

    def test_paired_outputs_preserve_sql_line_endings_inside_literals(self):
        mapping = _sql_mapping()
        mapping["sql"] = "SELECT 'first & second\r\nthird\rfourth\nfifth' AS [Value]"
        mapping["columns"] = ["Value"]

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            mapping_path = folder / "mapping.json"
            rdl_path = folder / "report.rdl"
            m_path = folder / "query.m"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")

            self.assertEqual(paginated_main([
                "--mapping", str(mapping_path), "--output", str(rdl_path),
                "--power-query-output", str(m_path),
            ]), 0)
            self.assertEqual(
                ET.parse(rdl_path).getroot().findtext(".//r:CommandText", namespaces=NS),
                mapping["sql"],
            )
            self.assertIn(
                "SELECT 'first & second#(cr)#(lf)third#(cr)fourth#(lf)fifth' AS [Value]",
                m_path.read_text(encoding="utf-8"),
            )

    def test_power_query_pair_rejects_unsupported_inputs_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            mapping_path = folder / "mapping.json"
            rdl_path = folder / "report.rdl"
            m_path = folder / "query.m"
            args = ["--mapping", str(mapping_path), "--output", str(rdl_path),
                    "--power-query-output", str(m_path)]

            for sql in ("SELECT @Region", "SELECT @Prompt('Region', 'A',,Mono,Free)"):
                with self.subTest(sql=sql):
                    mapping = _sql_mapping()
                    mapping["sql"] = sql
                    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
                    self.assertEqual(paginated_main(args), 2)
                    self.assertFalse(rdl_path.exists())
                    self.assertFalse(m_path.exists())

            dax_mapping = {
                "title": "Sales", "source_kind": "webi", "workspace": "Workspace",
                "semantic_model": "Model", "dax": "EVALUATE Sales",
                "columns": ["Sales[Amount]"],
            }
            mapping_path.write_text(json.dumps(dax_mapping), encoding="utf-8")
            self.assertEqual(paginated_main(args), 2)
            self.assertFalse(rdl_path.exists())
            self.assertFalse(m_path.exists())

            mapping_path.write_text(json.dumps(_sql_mapping()), encoding="utf-8")
            invalid_args = args[:-1] + [str(folder / "query.txt")]
            self.assertEqual(paginated_main(invalid_args), 2)
            self.assertFalse(rdl_path.exists())

            m_path.write_text("existing M", encoding="utf-8")
            self.assertEqual(paginated_main(args), 2)
            self.assertEqual(m_path.read_text(encoding="utf-8"), "existing M")
            self.assertFalse(rdl_path.exists())
            m_path.unlink()
            rdl_path.write_text("existing RDL", encoding="utf-8")
            self.assertEqual(paginated_main(args), 2)
            self.assertEqual(rdl_path.read_text(encoding="utf-8"), "existing RDL")
            self.assertFalse(m_path.exists())
            self.assertEqual(main(["--rdl-power-query-output", str(m_path)]), 3)

    def test_power_query_pair_rejects_parameterized_sql_without_outputs(self):
        mapping = _sql_mapping()
        mapping["sql"] = "SELECT [Region] FROM [dbo].[Sales] WHERE [Region] = @Region"
        mapping["parameters"] = [{"name": "Region", "data_type": "String"}]

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            mapping_path = folder / "mapping.json"
            rdl_path = folder / "report.rdl"
            m_path = folder / "query.m"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")

            self.assertEqual(paginated_main([
                "--mapping", str(mapping_path), "--output", str(rdl_path),
                "--power-query-output", str(m_path),
            ]), 2)
            self.assertFalse(rdl_path.exists())
            self.assertFalse(m_path.exists())

    def test_direct_bo_source_rejects_unresolved_prompt_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "report.wid"
            source.write_text(
                '<document><dataProvider name="Query"><sql>'
                "SELECT @Prompt('Region', 'A',,Mono,Free)"
                '</sql></dataProvider></document>', encoding="utf-8",
            )
            mapping = _sql_mapping()
            del mapping["sql"]
            mapping_path = folder / "mapping.json"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            output = folder / "report.rdl"
            args = ["--mapping", str(mapping_path), "--output", str(output),
                    "--bo-source", str(source), "--sql-name", "Query"]
            self.assertEqual(paginated_main(args), 2)
            self.assertFalse(output.exists())
            source.write_text(
                '<document><dataProvider name="Query"><sql>SELECT 1</sql>'
                '</dataProvider></document>', encoding="utf-8",
            )
            output.write_text("existing output", encoding="utf-8")
            self.assertEqual(paginated_main(args), 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "existing output")

    def test_extracted_webi_sql_generates_a_tabular_rdl(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "report.wid"
            source.write_text(
                '<document><dataProvider name="Ventes d&#39;été / région">'
                '<sql>SELECT [Region], [Net Sales] FROM [dbo].[Sales] '
                'WHERE [Region] = @Region</sql>'
                '<resultObject name="Région"/></dataProvider></document>',
                encoding="utf-8",
            )
            extraction = folder / "extraction"
            extracted = extract_bo_data(str(source), output_dir=str(extraction))
            self.assertEqual(extracted["queries"][0]["objects"][0]["name"], "Région")
            mapping = _sql_mapping()
            del mapping["sql"]
            mapping["parameters"] = [{"name": "Region", "data_type": "String"}]
            mapping_path = folder / "mapping.json"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            output = folder / "report.rdl"
            result = main([
                "--output-format", "rdl", "--rdl-mapping", str(mapping_path),
                "--rdl-output", str(output), "--rdl-extracted-sql",
                str(extraction / "custom_sql.json"), "--rdl-sql-name",
                "Ventes d'été / région",
            ])
            self.assertEqual(result, 0)
            root = ET.parse(output).getroot()
            self.assertEqual(root.findtext(".//r:CommandText", namespaces=NS),
                             "SELECT [Region], [Net Sales] FROM [dbo].[Sales] "
                             "WHERE [Region] = @Region")
            self.assertEqual(
                [field.text for field in root.findall(".//r:Fields/r:Field/r:DataField", NS)],
                ["Region", "Net Sales"],
            )
            self.assertEqual(
                root.findtext(".//r:QueryParameter/r:Value", namespaces=NS),
                "=Parameters!Region.Value",
            )

    def test_extracted_sql_selection_rejects_ambiguity_and_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            mapping = _sql_mapping()
            del mapping["sql"]
            mapping_path = folder / "mapping.json"
            sql_path = folder / "custom_sql.json"
            output = folder / "report.rdl"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            for entries in (
                [],
                [{"name": "Query", "sql": "SELECT 1"}, {"name": "Query", "sql": "SELECT 2"}],
                [{"name": "Query", "sql": ""}],
                [{"name": "Query", "sql": "SELECT @Region"}],
                {"name": "Query", "sql": "SELECT 1"},
            ):
                with self.subTest(entries=entries):
                    sql_path.write_text(json.dumps(entries), encoding="utf-8")
                    self.assertEqual(paginated_main([
                        "--mapping", str(mapping_path), "--output", str(output),
                        "--extracted-sql", str(sql_path), "--sql-name", "Query",
                    ]), 2)
                    self.assertFalse(output.exists())
            self.assertEqual(paginated_main([
                "--mapping", str(mapping_path), "--output", str(output),
                "--extracted-sql", str(sql_path),
            ]), 2)
            self.assertFalse(output.exists())
            self.assertEqual(main(["--rdl-sql-name", "Query"]), 3)

    def test_extracted_universe_sql_uses_explicit_mapping_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "universe.unx"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr(
                    "dataFoundation.xml",
                    '<dataFoundation><derivedTable name="Derived" '
                    'sql="SELECT 1 AS Region"/></dataFoundation>',
                )
            extraction = folder / "extraction"
            extract_bo_data(str(source), output_dir=str(extraction))
            mapping = _sql_mapping("universe")
            del mapping["sql"]
            mapping_path = folder / "mapping.json"
            sql_path = extraction / "custom_sql.json"
            output = folder / "report.rdl"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            args = ["--mapping", str(mapping_path), "--output", str(output),
                    "--extracted-sql", str(sql_path), "--sql-name", "Derived"]
            self.assertEqual(paginated_main(args), 0)
            before = output.read_bytes()
            self.assertEqual(paginated_main(args), 2)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(ET.fromstring(before).findtext(".//r:CommandText", namespaces=NS),
                             "SELECT 1 AS Region")
            mapping["sql"] = "SELECT 2"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            output.unlink()
            self.assertEqual(paginated_main(args), 2)
            self.assertFalse(output.exists())

    def test_existing_semantic_model_dax_contract_remains_supported(self):
        dax_mapping = {
            "title": "Ventes par région",
            "source_kind": "webi",
            "workspace": "Finance",
            "semantic_model": "Sales Model",
            "dax": "EVALUATE 'Sales'",
            "columns": ["Sales[Region]", "Sales[Amount]"],
        }

        root = ET.fromstring(generate_semantic_model_rdl(dax_mapping))

        self.assertEqual(
            root.findtext(".//r:DataProvider", namespaces=NS),
            "OLEDB-MD",
        )
        self.assertEqual(
            root.findtext(".//r:CommandText", namespaces=NS),
            dax_mapping["dax"],
        )
        self.assertEqual(
            [
                field.text
                for field in root.findall(".//r:Fields/r:Field/r:DataField", NS)
            ],
            dax_mapping["columns"],
        )


if __name__ == "__main__":
    unittest.main()
