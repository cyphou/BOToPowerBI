"""Tests for the CLI entry point (migrate.py)."""

import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from migrate import (build_parser, main, MigrationStats, _run_single_migration,
                     _record_migration_object_warnings,
                     EXIT_GENERAL_ERROR, EXIT_SUCCESS, EXIT_UNSUPPORTED_FORMAT,
                     EXIT_VALIDATION_ERROR)


class TestCLIParser(unittest.TestCase):
    """Test argument parser configuration."""

    def setUp(self):
        self.parser = build_parser()

    def test_single_file_input(self):
        args = self.parser.parse_args(["report.wid"])
        self.assertEqual(args.input, "report.wid")

    def test_output_dir(self):
        args = self.parser.parse_args(["report.wid", "--output-dir", "/tmp/out"])
        self.assertEqual(args.output_dir, "/tmp/out")

    def test_output_format_pbip(self):
        args = self.parser.parse_args(["report.wid", "--output-format", "pbip"])
        self.assertEqual(args.output_format, "pbip")

    def test_output_format_fabric(self):
        args = self.parser.parse_args(["report.wid", "--output-format", "fabric"])
        self.assertEqual(args.output_format, "fabric")

    def test_rdl_choice_generates_from_explicit_mapping_and_refuses_overwrite(self):
        for kind in ("crystal", "webi"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                mapping = os.path.join(directory, "mapping.json")
                output = os.path.join(directory, "report.rdl")
                with open(mapping, "w", encoding="utf-8") as handle:
                    json.dump({"title": "Sales", "source_kind": kind,
                               "workspace": "Workspace", "semantic_model": "Model",
                               "dax": "EVALUATE Sales", "columns": ["Sales[Amount]"]}, handle)
                arguments = ["--output-format", "rdl", "--rdl-mapping", mapping,
                             "--rdl-output", output]
                self.assertEqual(main(arguments), EXIT_SUCCESS)
                with open(output, "rb") as handle:
                    generated = handle.read()
                self.assertIn(b"<Report ", generated)
                self.assertEqual(main(arguments), 2)
                with open(output, "rb") as handle:
                    self.assertEqual(handle.read(), generated)

    def test_rdl_rejects_migration_options_and_rdl_options_require_rdl(self):
        for arguments in (
            ["--output-format", "rdl"],
            ["report.wid", "--output-format", "rdl", "--rdl-mapping", "map.json", "--rdl-output", "report.rdl"],
            ["--output-format", "rdl", "--rdl-mapping", "map.json", "--rdl-output", "report.rdl", "--deploy", "workspace"],
            ["report.wid", "--rdl-mapping", "map.json"],
        ):
            with self.subTest(arguments=arguments):
                with patch("migrate._run_single_migration") as run:
                    self.assertEqual(main(arguments), 3)
                    run.assert_not_called()

    def test_assess_flag(self):
        args = self.parser.parse_args(["report.wid", "--assess"])
        self.assertTrue(args.assess)

    def test_dry_run_flag(self):
        args = self.parser.parse_args(["report.wid", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_verbose_flag(self):
        args = self.parser.parse_args(["report.wid", "-v"])
        self.assertTrue(args.verbose)

    def test_biar_input(self):
        args = self.parser.parse_args(["--biar", "archive.biar", "--output-dir", "/tmp"])
        self.assertEqual(args.biar, "archive.biar")

    def test_server_connection(self):
        args = self.parser.parse_args([
            "--server", "https://bo:6405",
            "--folder", "/Public/Sales",
            "--user", "admin",
            "--auth", "enterprise",
        ])
        self.assertEqual(args.server, "https://bo:6405")
        self.assertEqual(args.folder, "/Public/Sales")
        self.assertEqual(args.user, "admin")
        self.assertEqual(args.auth, "enterprise")

    def test_server_rejects_inspection_modes_before_download(self):
        for flag in ("--assess", "--global-assess", "--dry-run"):
            with self.subTest(flag=flag), \
                 patch("migrate._run_server_migration") as server_migration, \
                 self.assertLogs("bo_migrate", level="ERROR") as logged:
                result = main([
                    "--server", "https://bo.example.test:6405",
                    "--folder", "/Public/Sales",
                    flag,
                ])

            self.assertEqual(result, EXIT_UNSUPPORTED_FORMAT)
            server_migration.assert_not_called()
            self.assertIn("not supported with --server", " ".join(logged.output))

    def test_shared_model(self):
        args = self.parser.parse_args([
            "--shared-model", "r1.wid", "r2.wid",
            "--model-name", "Shared Sales",
        ])
        self.assertEqual(args.shared_model, ["r1.wid", "r2.wid"])
        self.assertEqual(args.model_name, "Shared Sales")

    def test_deploy(self):
        args = self.parser.parse_args([
            "report.wid",
            "--deploy", "workspace-123",
            "--deploy-refresh",
        ])
        self.assertEqual(args.deploy, "workspace-123")
        self.assertTrue(args.deploy_refresh)

    def test_main_rejects_unwired_deployment_flags_before_migration(self):
        cases = (
            ["--batch", "sources", "--deploy", "workspace"],
            ["--shared-model", "first.wid", "second.wid", "--deploy", "workspace"],
            ["--batch", "sources", "--deploy-refresh"],
            ["--batch", "sources", "--deploy-bundle", "workspace"],
            ["report.wid", "--deploy", "workspace"],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), \
                 patch("migrate._run_batch_migration") as batch_migration, \
                 patch("migrate._run_shared_model_migration") as shared_migration, \
                 patch("migrate._run_single_migration") as single_migration, \
                 self.assertLogs("bo_migrate", level="ERROR") as logged:
                result = main(arguments)

            self.assertEqual(result, EXIT_UNSUPPORTED_FORMAT)
            self.assertTrue(
                any("not supported" in message for message in logged.output)
            )
            batch_migration.assert_not_called()
            shared_migration.assert_not_called()
            single_migration.assert_not_called()

    def test_calendar_options(self):
        args = self.parser.parse_args([
            "report.wid",
            "--calendar-start", "2018",
            "--calendar-end", "2028",
            "--culture", "fr-FR",
        ])
        self.assertEqual(args.calendar_start, 2018)
        self.assertEqual(args.calendar_end, 2028)
        self.assertEqual(args.culture, "fr-FR")

    def test_no_input_returns_error(self):
        """CLI with no arguments should show help and return error."""
        result = main([])
        self.assertEqual(result, EXIT_GENERAL_ERROR)

    def test_inspection_does_not_generate_or_leave_extraction(self):
        for flag in ("--assess", "--dry-run"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as temporary_dir:
                source = os.path.join(temporary_dir, "report.wid")
                with open(source, "wb") as handle:
                    handle.write(b"fixture")
                report = Mock()
                extraction_dirs = []

                def extract_fixture(input_path, output_dir, verbose):
                    extraction_dirs.append(output_dir)
                    self.assertNotEqual(output_dir, temporary_dir)
                    return {"reports": [{"name": "Report"}], "formulas": []}

                with patch("bo_export.extract_bo_data.extract_bo_data", side_effect=extract_fixture), \
                     patch("bo_export.converted_objects_adapter.adapt_bo_to_converted_objects", return_value={"calculations": []}) as adapter, \
                     patch("powerbi_import.assessment.run_assessment", return_value=report) as assessment, \
                     patch("powerbi_import.assessment.print_assessment_report"), \
                     patch("powerbi_import.import_to_powerbi.PowerBIImporter") as importer:
                    self.assertEqual(main([source, flag]), EXIT_SUCCESS)
                    importer.assert_not_called()
                    adapter.assert_called_once()
                    assessment.assert_called_once_with({"calculations": []}, workbook_name="report")
                self.assertEqual(os.listdir(temporary_dir), ["report.wid"])
                self.assertFalse(os.path.exists(extraction_dirs[0]))

    def test_dry_run_does_not_create_requested_output(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            output = os.path.join(temporary_dir, "output")
            with patch("bo_export.extract_bo_data.extract_bo_data", return_value={}), \
                 patch("bo_export.converted_objects_adapter.adapt_bo_to_converted_objects", return_value={}), \
                 patch("powerbi_import.assessment.run_assessment"), \
                 patch("powerbi_import.assessment.print_assessment_report"), \
                 patch("powerbi_import.assessment.save_assessment_report") as save:
                self.assertEqual(main(["report.wid", "--assess", "--dry-run", "--output-dir", output]), EXIT_SUCCESS)
                save.assert_not_called()
                self.assertFalse(os.path.exists(output))

    def test_empty_extraction_records_warning_without_flagging_nonempty_source(self):
        stats = MigrationStats()
        warnings = _record_migration_object_warnings({}, {}, stats)
        self.assertEqual(len(warnings), 1)
        self.assertIn("No BusinessObjects objects were extracted", warnings[0])
        self.assertEqual(stats.warnings, warnings)

        populated = {"reports": [{"name": "Report"}]}
        self.assertEqual(_record_migration_object_warnings(populated, {}, MigrationStats()), [])

    def test_native_wid_warning_survives_failed_folder_migration(self):
        xml = (
            b'<DOCUMENT RSVERSION="2.5"><REPORT RID="1"><PLIST>'
            b'<PVAL NAME="name">{"l":"Overview"}</PVAL></PLIST></REPORT></DOCUMENT>'
        )
        docspec = (len(xml) + 8).to_bytes(4, "little") + b"\x05\x00\x02\x00" + xml
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            with zipfile.ZipFile(sources / "native.wid", "w") as archive:
                archive.writestr("Data/RE/DOCSPEC", docspec)
            output = root / "output"
            with redirect_stdout(StringIO()):
                self.assertEqual(main([str(sources), "--output-dir", str(output)]),
                                 EXIT_GENERAL_ERROR)
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            artifact = manifest["artifacts"][0]
            self.assertEqual(artifact["status"], "failed")
            self.assertIn("Native WID extraction is partial", " ".join(artifact["warnings"]))
            self.assertIn("No datasources found", artifact["error"])
            reports = json.loads((output / "native.wid" / "reports.json").read_text(encoding="utf-8"))
            self.assertEqual(reports[0]["name"], "Overview")
            self.assertTrue(reports[0]["native_wid_partial"])

    def test_crystal_assessment_records_unextracted_datasource(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "report.rpt"
            source.write_bytes(b"synthetic Crystal report text")
            output = root / "assessment"
            with redirect_stdout(StringIO()):
                self.assertEqual(main([str(source), "--assess", "--output-dir", str(output)]),
                                 EXIT_SUCCESS)
            reports = list(output.glob("assessment_*.json"))
            self.assertEqual(len(reports), 1)
            assessment = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(assessment["overall_score"], "RED")
            datasource = next(c for c in assessment["categories"]
                              if c["name"] == "Datasource Compatibility")
            self.assertEqual(datasource["checks"][0]["severity"], "fail")
            self.assertIn("No datasource definitions were extracted",
                          datasource["checks"][0]["detail"])

            dry_output = root / "dry-output"
            console = StringIO()
            with redirect_stdout(console):
                self.assertEqual(main([str(source), "--dry-run", "--output-dir",
                                       str(dry_output)]), EXIT_SUCCESS)
            self.assertIn("RED", console.getvalue())
            self.assertFalse(dry_output.exists())

    def test_generation_reads_default_extraction_and_can_skip_optimizer(self):
        with patch("bo_export.extract_bo_data.extract_bo_data", return_value={}) as extract, \
             patch("powerbi_import.import_to_powerbi.PowerBIImporter") as importer, \
             patch("powerbi_import.dax_optimizer.optimize_dax_project") as optimize, \
             patch("powerbi_import.comparison_report.generate_comparison_report") as compare:
            args = build_parser().parse_args(["report.wid", "--no-optimize-dax", "--no-compare"])
            self.assertEqual(_run_single_migration(args, MigrationStats()), EXIT_SUCCESS)
            expected = os.path.splitext(os.path.abspath("report.wid"))[0] + "_pbi"
            self.assertEqual(extract.call_args.kwargs["output_dir"], expected)
            importer.assert_called_once_with(source_dir=expected)
            optimize.assert_not_called()
            compare.assert_not_called()

    def test_comparison_is_generated_from_the_returned_project_path(self):
        with patch("bo_export.extract_bo_data.extract_bo_data", return_value={}), \
             patch("powerbi_import.import_to_powerbi.PowerBIImporter") as importer, \
             patch("powerbi_import.comparison_report.generate_comparison_report") as compare:
            importer.return_value.import_all.return_value = "generated-project"
            args = build_parser().parse_args(["report.wid", "--no-optimize-dax"])
            self.assertEqual(_run_single_migration(args, MigrationStats()), EXIT_SUCCESS)
            self.assertEqual(compare.call_args.args[1], "generated-project")

    def test_single_file_migration_requires_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "report.wid"
            source.write_bytes(b"fixture")
            output = Path(temporary) / "output"
            for extra in ([], ["--output-format", "fabric"]):
                with self.subTest(extra=extra), patch("migrate._run_single_migration") as run:
                    with self.assertLogs("bo_migrate", level="ERROR") as logged:
                        self.assertEqual(main([str(source), "--output-dir", str(output), *extra]), 3)
                    self.assertIn("place the file in a directory", " ".join(logged.output))
                    run.assert_not_called()
                    self.assertFalse(output.exists())

    def test_batch_runs_full_pipeline_with_isolated_outputs(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            sources = os.path.join(temporary_dir, "sources")
            os.makedirs(sources)
            for name in ("Sales.wid", "Sales.rpt"):
                with open(os.path.join(sources, name), "wb") as handle:
                    handle.write(b"fixture")
            output = os.path.join(temporary_dir, "output")
            with patch("migrate._run_single_migration", return_value=EXIT_SUCCESS) as run:
                self.assertEqual(main(["--batch", sources, "--output-dir", output]), EXIT_SUCCESS)
                self.assertEqual(run.call_count, 2)
                outputs = {call.args[0].output_dir for call in run.call_args_list}
                self.assertEqual(len(outputs), 2)
                self.assertTrue(os.path.isfile(os.path.join(output, "batch_manifest.json")))
                self.assertTrue(os.path.isfile(os.path.join(output, "batch_report.html")))

    def test_directory_input_routes_mixed_files_and_reports_skipped_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            nested = sources / "sous dossier"
            nested.mkdir(parents=True)
            for name in ("Ventes.WID", "Ventes.rpt", "catalogue.unx", "dash.lumx", "export.LCMBIAR", "ancien.rep"):
                (nested / name).write_bytes(b"fixture")
            output = root / "output"
            with patch("migrate._run_single_migration", return_value=EXIT_SUCCESS) as single, \
                 patch("migrate._run_biar_migration", return_value=EXIT_SUCCESS) as archive:
                self.assertEqual(main([str(sources), "--output-dir", str(output),
                                       "--output-format", "fabric"]), EXIT_SUCCESS)
            self.assertEqual(single.call_count, 4)
            archive.assert_called_once()
            self.assertEqual(Path(archive.call_args.args[0].biar).name, "export.LCMBIAR")
            self.assertTrue(all(call.args[0].output_format == "fabric" for call in single.call_args_list))
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual({item["source_kind"] for item in manifest["artifacts"]},
                             {"webi", "crystal", "universe", "lumira", "biar"})
            self.assertEqual(len({item["output_dir"] for item in manifest["artifacts"]}), 5)
            self.assertEqual(manifest["skipped"][0]["source"], "sous dossier/ancien.rep")

    def test_positional_archive_uses_archive_pipeline(self):
        with patch("migrate._run_biar_migration", return_value=EXIT_SUCCESS) as archive, \
             patch("migrate._run_single_migration") as single:
            self.assertEqual(main(["export.LCMBIAR", "--dry-run"]), EXIT_SUCCESS)
            self.assertEqual(archive.call_args.args[0].biar, "export.LCMBIAR")
            single.assert_not_called()

    def test_directory_input_runs_webi_and_archive_pipelines(self):
        fixture = Path(__file__).resolve().parent.parent / "examples" / "Enterprise_Sales.wid"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / "Sales.wid").write_bytes(fixture.read_bytes())
            with zipfile.ZipFile(sources / "Export.biar", "w") as archive:
                archive.write(fixture, "Folder/Sales.wid")
            output = root / "output"
            self.assertEqual(main([str(sources), "--output-dir", str(output),
                                   "--no-compare", "--no-optimize-dax"]), EXIT_SUCCESS)
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual({item["source_kind"] for item in manifest["artifacts"]}, {"webi", "biar"})
            self.assertTrue(all(item["status"] == "success" for item in manifest["artifacts"]))
            self.assertTrue(list((output / "Sales.wid").rglob("*.pbip")))
            self.assertTrue(list((output / "Export.biar").rglob("*.pbip")))
            for item in manifest["artifacts"]:
                self.assertIn("12 extracted column(s)", " ".join(item["warnings"]))
            self.assertIn("12 extracted column(s)",
                          (output / "batch_report.html").read_text(encoding="utf-8"))

    def test_webi_sql_columns_and_unbound_warning_reach_folder_output(self):
        xml = """\
        <document>
          <connection id="sales-ref" name="Sales DB" type="SQL Server"
                      server="sales.example.invalid" database="Sales"/>
          <dataProvider name="Sales_Query" connectionId="sales-ref">
            <ResultObject name="Région" table="Sales_Query" dataType="string"/>
            <ResultObject name="Revenue" table="Sales_Query" dataType="number"
                          qualification="measure"/>
            <ResultObject name="Unbound" dataType="string"/>
            <SQL>SELECT [Région], Revenue FROM Sales</SQL>
            <QueryFilter name="Sales_Query" object="Revenue" operator="Greater Than">
              <Value>0</Value>
            </QueryFilter>
          </dataProvider>
          <Report name="Overview"/>
          <Chart name="Sales chart" type="bar" report="Overview">
            <CategoryAxis name="Région"/>
            <ValueSeries name="Revenue"/>
          </Chart>
        </document>
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / "Sales.wid").write_text(xml, encoding="utf-8")
            mapping = root / "mapping.json"
            mapping.write_text(json.dumps({
                "title": "Sales", "source_kind": "webi",
                "server": "sales.example.invalid", "database": "Sales",
                "columns": ["Région", "Revenue"],
            }, ensure_ascii=False), encoding="utf-8")
            config = root / "batch.json"
            config.write_text(json.dumps({"sources": {
                "Sales.wid": {"mapping": mapping.name, "sql_name": "Sales_Query",
                              "power_query": True},
            }}), encoding="utf-8")
            output = root / "output"
            with redirect_stdout(StringIO()):
                self.assertEqual(main([str(sources), "--output-dir", str(output),
                                       "--rdl-batch-config", str(config),
                                       "--no-compare", "--no-optimize-dax"]), EXIT_SUCCESS)

            model_path = next(output.rglob("Sales_Query.tmdl"))
            model = model_path.read_text(encoding="utf-8")
            self.assertIn("sourceColumn: 'Région'", model)
            self.assertIn("sourceColumn: Revenue", model)
            self.assertIn("SELECT [Région], Revenue FROM Sales", model)
            visuals = [
                json.loads(path.read_text(encoding="utf-8"))["visual"]
                for path in output.rglob("visual.json")
            ]
            chart = next(visual for visual in visuals
                         if visual["visualType"] == "clusteredBarChart")
            query = json.dumps(chart["query"], ensure_ascii=False)
            for name in ("Sales_Query", "Région", "Revenue"):
                self.assertIn(name, query)
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            warnings = " ".join(manifest["artifacts"][0]["warnings"])
            self.assertIn("1 extracted column(s)", warnings)
            self.assertIn("2 SQL result column(s)", warnings)
            self.assertIn("result schema has not been verified", warnings)
            html = (output / "batch_report.html").read_text(encoding="utf-8")
            self.assertIn("1 extracted column(s)", html)
            self.assertIn("2 SQL result column(s)", html)
            self.assertEqual(
                {name: target["status"]
                 for name, target in manifest["artifacts"][0]["targets"].items()},
                {"powerbi": "success", "paginated": "success"},
            )
            paginated = output / "Sales.wid" / "PaginatedReport"
            ns = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
            report = ET.parse(paginated / "report.rdl").getroot()
            self.assertEqual(
                report.findtext(".//r:CommandText", namespaces=ns),
                "SELECT [Région], Revenue FROM Sales",
            )
            self.assertEqual(
                [field.text for field in report.findall(".//r:Fields/r:Field/r:DataField", ns)],
                ["Région", "Revenue"],
            )
            self.assertIn("SELECT [Région], Revenue FROM Sales",
                          (paginated / "query.m").read_text(encoding="utf-8"))

            fabric_output = root / "fabric-output"
            with redirect_stdout(StringIO()):
                self.assertEqual(main([str(sources), "--output-dir", str(fabric_output),
                                       "--output-format", "fabric", "--no-compare",
                                       "--no-optimize-dax"]), EXIT_SUCCESS)
            fabric_model = next(fabric_output.rglob("Sales_Query.tmdl")).read_text(encoding="utf-8")
            self.assertIn("mode: directLake", fabric_model)
            self.assertIn("sourceColumn: R_gion", fabric_model)
            self.assertIn("sourceColumn: Revenue", fabric_model)
            lakehouse = json.loads(
                next(fabric_output.rglob("lakehouse_definition.json")).read_text(encoding="utf-8")
            )
            self.assertEqual(
                [column["name"] for column in lakehouse["tables"][0]["columns"]],
                ["R_gion", "Revenue"],
            )
            dataflow = next(fabric_output.rglob("Sales_Query.m")).read_text(encoding="utf-8")
            self.assertIn(
                'List.Difference({"Région", "Revenue"}, Table.ColumnNames(SourceTable))',
                dataflow,
            )
            self.assertIn('Table.RenameColumns(CheckedSource, {{"Région", "R_gion"}})',
                          dataflow)

    def test_synthetic_lumira_objects_reach_pbip_with_explicit_warnings(self):
        fixture = Path(__file__).resolve().parent.parent / "examples" / "Sales_Exploration.lumx"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / fixture.name).write_bytes(fixture.read_bytes())
            output = root / "output"
            with redirect_stdout(StringIO()):
                self.assertEqual(main([str(sources), "--output-dir", str(output),
                                       "--no-compare", "--no-optimize-dax"]), EXIT_SUCCESS)

            source_output = output / fixture.name
            columns = json.loads((source_output / "columns.json").read_text(encoding="utf-8"))
            expected_columns = {column["name"] for column in columns}
            self.assertEqual(len(expected_columns), 10)
            self.assertTrue(all(column.get("table") == "Sales" for column in columns))
            sales_tables = list(source_output.rglob("Sales.tmdl"))
            self.assertEqual(len(sales_tables), 1)
            model_columns = {
                line.strip()[len("column "):].strip("'")
                for line in sales_tables[0].read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("column ")
            }
            self.assertTrue(expected_columns.issubset(model_columns))

            pages = list(source_output.rglob("page.json"))
            unassigned = next(
                page.parent for page in pages
                if json.loads(page.read_text(encoding="utf-8"))["displayName"]
                == "BO_Unassigned_Charts"
            )
            visuals = [
                json.loads(path.read_text(encoding="utf-8"))["visual"]
                for path in unassigned.rglob("visual.json")
            ]
            visuals = [visual for visual in visuals if visual["visualType"] != "pageNavigator"]
            self.assertCountEqual(
                [visual["visualType"] for visual in visuals],
                ["clusteredBarChart", "lineChart", "treemap", "card"],
            )
            self.assertTrue(all("query" not in visual for visual in visuals))
            artifact = json.loads(
                (output / "batch_manifest.json").read_text(encoding="utf-8")
            )["artifacts"][0]
            warnings = " ".join(artifact["warnings"])
            self.assertIn("4 chart(s)", warnings)
            self.assertIn("synthetic", warnings.lower())
            html = (output / "batch_report.html").read_text(encoding="utf-8")
            self.assertIn("4 chart(s)", html)
            self.assertIn("placeholder", html.lower())

    def test_explicit_lumira_chart_fields_reach_the_generated_visual_queries(self):
        metadata = {
            "datasets": [{"name": "Sales"}],
            "dimensions": [{"name": "Région", "type": "string", "table": "Sales"}],
            "measures": [{"name": "Revenue", "type": "decimal", "table": "Sales"}],
            "pages": [{"name": "Overview"}],
            "visualizations": [
                {"name": "Bound", "type": "bar", "report": "Overview",
                 "dimensions": ["Région"], "measures": ["Revenue"]},
                {"name": "Unassigned", "type": "line",
                 "dimensions": ["Région"], "measures": ["Revenue"]},
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            with zipfile.ZipFile(sources / "report.lumx", "w") as archive:
                archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False))
            output = root / "output"
            with redirect_stdout(StringIO()):
                self.assertEqual(main([str(sources), "--output-dir", str(output),
                                       "--no-compare", "--no-optimize-dax"]), EXIT_SUCCESS)

            visuals = [
                json.loads(path.read_text(encoding="utf-8"))["visual"]
                for path in output.rglob("visual.json")
            ]
            for visual_type in ("clusteredBarChart", "lineChart"):
                visual = next(v for v in visuals if v["visualType"] == visual_type)
                query = json.dumps(visual["query"], ensure_ascii=False)
                self.assertIn("Sales", query)
                self.assertIn("Région", query)
                self.assertIn("Revenue", query)
            artifact = json.loads(
                (output / "batch_manifest.json").read_text(encoding="utf-8")
            )["artifacts"][0]
            self.assertIn("1 chart(s)", " ".join(artifact["warnings"]))

    def test_ambiguous_universe_sql_warns_in_folder_and_archive_reports(self):
        fixture = Path(__file__).resolve().parent.parent / "examples" / "eFashion_Universe.unx"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / fixture.name).write_bytes(fixture.read_bytes())
            with zipfile.ZipFile(sources / "universe.biar", "w") as archive:
                archive.write(fixture, "Folder/Fashion.unx")
            output = root / "output"
            with redirect_stdout(StringIO()):
                self.assertEqual(main([str(sources), "--output-dir", str(output),
                                       "--no-compare", "--no-optimize-dax"]), EXIT_SUCCESS)

            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            for artifact in manifest["artifacts"]:
                self.assertEqual(artifact["status"], "success")
                self.assertIn("no matching SQL-bearing table",
                              " ".join(artifact["warnings"]))
                self.assertIn("SQL expressions or filters", " ".join(artifact["warnings"]))
            self.assertIn("no matching SQL-bearing table",
                          (output / "batch_report.html").read_text(encoding="utf-8"))
            archive_output = output / "universe.biar"
            archive_summary = json.loads(
                (archive_output / "batch_summary.json").read_text(encoding="utf-8")
            )
            self.assertIn("no matching SQL-bearing table",
                          " ".join(archive_summary["artifacts"][0]["warnings"]))
            self.assertIn("no matching SQL-bearing table",
                          (archive_output / "batch_report.html").read_text(encoding="utf-8"))
            sql = json.loads(
                (output / fixture.name / "custom_sql.json").read_text(encoding="utf-8")
            )[0]["sql"]
            tmdl_files = list((output / fixture.name).rglob("*.tmdl"))
            self.assertTrue(tmdl_files)
            self.assertTrue(all(sql not in path.read_text(encoding="utf-8") for path in tmdl_files))
            time_table = next(path for path in tmdl_files if path.name == "DIM_TIME.tmdl")
            model = time_table.read_text(encoding="utf-8")
            year = model.split("\tcolumn Year", 1)[1].split("\n\tcolumn ", 1)[0]
            self.assertIn("sourceColumn: FISCAL_YEAR", year)

    def test_rdl_folder_routes_mixed_sources_and_optional_power_query(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            nested = sources / "équipe"
            nested.mkdir(parents=True)
            (nested / "Ventes.wid").write_text(
                '<document><dataProvider name="Sales"><sql>SELECT Region FROM Sales</sql>'
                '</dataProvider></document>', encoding="utf-8")
            (sources / "Crystal.rpt").write_bytes(
                b"\x00Crystal report text\x00SELECT Amount FROM dbo.Sales;\x00")
            (sources / "Tableau.lumx").write_bytes(b"fixture")
            (sources / "ancien.rep").write_bytes(b"unsupported")
            mappings = root / "mappings"
            mappings.mkdir()
            common = {"title": "Ventes", "server": "sql.example.test", "database": "Sales"}
            files = {
                "webi.json": {**common, "source_kind": "webi", "columns": ["Region"]},
                "crystal.json": {**common, "source_kind": "crystal", "columns": ["Amount"]},
                "lumira.json": {"title": "Dashboard", "source_kind": "lumira",
                                "workspace": "Workspace", "semantic_model": "Model",
                                "dax": "EVALUATE Sales", "columns": ["Sales[Amount]"]},
            }
            for name, mapping in files.items():
                (mappings / name).write_text(json.dumps(mapping), encoding="utf-8")
            config = mappings / "batch.json"
            config.write_text(json.dumps({"sources": {
                "équipe\\Ventes.wid": {"mapping": "webi.json", "sql_name": "Sales"},
                "Crystal.rpt": {"mapping": "crystal.json", "sql_name": "CommandSQL", "power_query": True},
                "Tableau.lumx": {"mapping": "lumira.json"},
            }}, ensure_ascii=False), encoding="utf-8")
            output = root / "output"
            arguments = [str(sources), "--output-format", "rdl", "--rdl-batch-config",
                         str(config), "--output-dir", str(output)]
            self.assertEqual(main(arguments + ["--dry-run"]), EXIT_SUCCESS)
            self.assertFalse(output.exists())
            self.assertEqual(main(arguments), EXIT_SUCCESS)

            ns = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
            for relative, expected in (("équipe/Ventes.wid", "SELECT Region FROM Sales"),
                                       ("Crystal.rpt", "SELECT Amount FROM dbo.Sales"),
                                       ("Tableau.lumx", "EVALUATE Sales")):
                report = output.joinpath(*relative.split("/"), "report.rdl")
                self.assertEqual(ET.parse(report).getroot().findtext(".//r:CommandText", namespaces=ns), expected)
            self.assertIn("SELECT Amount FROM dbo.Sales",
                          (output / "Crystal.rpt" / "query.m").read_text(encoding="utf-8"))
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([item["status"] for item in manifest["artifacts"]], ["success"] * 3)
            self.assertEqual(manifest["skipped"][0]["source"], "ancien.rep")
            report_html = (output / "batch_report.html").read_text(encoding="utf-8")
            self.assertIn("Crystal SQL extraction is heuristic", report_html)
            self.assertIn("ancien.rep", report_html)
            crystal = next(item for item in manifest["artifacts"]
                           if item["source"] == "Crystal.rpt")
            self.assertIn("Crystal SQL extraction is heuristic", crystal["warnings"])

    def test_batch_can_generate_pbip_and_paginated_report_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            source_name = "Sales & Region.wid"
            (sources / source_name).write_text("<document/>", encoding="utf-8")
            mapping = root / "sales.json"
            mapping.write_text(json.dumps({
                "title": "Sales", "source_kind": "webi",
                "server": "sql.example.test", "database": "Sales",
                "sql": "SELECT Region FROM Sales", "columns": ["Region"],
            }), encoding="utf-8")
            config = root / "batch.json"
            config.write_text(json.dumps({"sources": {
                source_name: {"mapping": "sales.json", "power_query": True},
            }}), encoding="utf-8")
            output = root / "output"
            with patch("migrate._run_single_migration", return_value=EXIT_SUCCESS) as powerbi:
                self.assertEqual(main([
                    str(sources), "--rdl-batch-config", str(config),
                    "--output-dir", str(output),
                ]), EXIT_SUCCESS)

            powerbi.assert_called_once()
            source_output = output / source_name / "PaginatedReport"
            self.assertTrue((source_output / "report.rdl").is_file())
            self.assertTrue((source_output / "query.m").is_file())
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            artifact = manifest["artifacts"][0]
            self.assertEqual(artifact["status"], "success")
            self.assertEqual(set(artifact["targets"]), {"powerbi", "paginated"})
            self.assertEqual(
                {target["status"] for target in artifact["targets"].values()},
                {"success"},
            )
            report_html = (output / "batch_report.html").read_text(encoding="utf-8")
            self.assertIn("Sales &amp; Region.wid", report_html)
            self.assertIn(
                'href="Sales%20%26%20Region.wid/PaginatedReport/report.rdl"',
                report_html,
            )
            self.assertIn("does not prove", report_html)

    def test_dual_target_manifest_reports_missing_paginated_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / "Sales.wid").write_text("<document/>", encoding="utf-8")
            config = root / "batch.json"
            config.write_text(json.dumps({"sources": {}}), encoding="utf-8")
            output = root / "output"
            with patch("migrate._run_single_migration", return_value=EXIT_SUCCESS):
                self.assertEqual(main([
                    str(sources), "--rdl-batch-config", str(config),
                    "--output-dir", str(output),
                ]), EXIT_GENERAL_ERROR)
            artifact = json.loads(
                (output / "batch_manifest.json").read_text(encoding="utf-8")
            )["artifacts"][0]
            self.assertEqual(artifact["targets"]["powerbi"]["status"], "success")
            self.assertEqual(artifact["targets"]["paginated"]["status"], "failed")
            self.assertIn("No RDL mapping", artifact["targets"]["paginated"]["error"])

    def test_rdl_folder_reports_missing_mapping_mismatch_and_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            for name in ("bad.rpt", "missing.wid", "archive.biar"):
                (sources / name).write_bytes(b"fixture")
            (sources / "good.wid").write_text("<document/>", encoding="utf-8")
            (root / "wrong.json").write_text(json.dumps({"source_kind": "webi"}), encoding="utf-8")
            (root / "good.json").write_text(json.dumps({
                "title": "Good", "source_kind": "webi", "server": "sql.example.test",
                "database": "Sales", "sql": "SELECT Region FROM Sales", "columns": ["Region"],
            }), encoding="utf-8")
            config = root / "batch.json"
            config.write_text(json.dumps({"sources": {
                "bad.rpt": {"mapping": "wrong.json"},
                "archive.biar": {"mapping": "wrong.json"},
                "good.wid": {"mapping": "good.json"},
            }}), encoding="utf-8")
            output = root / "output"
            self.assertEqual(main(["--batch", str(sources), "--output-format", "rdl",
                                   "--rdl-batch-config", str(config), "--output-dir", str(output)]),
                             EXIT_GENERAL_ERROR)
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            errors = {item["source"]: item["error"] for item in manifest["artifacts"]}
            self.assertIn("source_kind", errors["bad.rpt"])
            self.assertIn("No RDL mapping", errors["missing.wid"])
            self.assertIn("BIAR/LCMBIAR", errors["archive.biar"])
            self.assertIsNone(errors["good.wid"])
            self.assertTrue((output / "good.wid" / "report.rdl").is_file())
            self.assertFalse((output / "bad.rpt").exists())

    def test_rdl_folder_rejects_nonempty_output_and_stale_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / "report.wid").write_bytes(b"fixture")
            config = root / "batch.json"
            config.write_text(json.dumps({"sources": {
                "typo.wid": {"mapping": "unused.json"}}}), encoding="utf-8")
            output = root / "output"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            arguments = [str(sources), "--output-format", "rdl", "--rdl-batch-config",
                         str(config), "--output-dir", str(output)]
            self.assertNotEqual(main(arguments), EXIT_SUCCESS)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
            sentinel.unlink()
            self.assertNotEqual(main(arguments), EXIT_SUCCESS)
            self.assertEqual(list(output.iterdir()), [])

    def test_positional_directory_does_not_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / "report.wid").write_bytes(b"fixture")
            output = root / "output"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            with patch("migrate._run_single_migration") as single:
                self.assertNotEqual(main([str(sources), "--output-dir", str(output)]), EXIT_SUCCESS)
                self.assertNotEqual(main([str(sources), "--output-dir", str(root)]), EXIT_SUCCESS)
                single.assert_not_called()
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_rdl_folder_rejects_unsupported_options_and_mapping_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / "report.wid").write_bytes(b"fixture")
            config_dir = root / "config"
            config_dir.mkdir()
            (root / "outside.json").write_text(json.dumps({"source_kind": "webi"}), encoding="utf-8")
            config = config_dir / "batch.json"
            config.write_text(json.dumps({"sources": {
                "report.wid": {"mapping": "../outside.json"}}}), encoding="utf-8")
            output = root / "output"
            arguments = [str(sources), "--output-format", "rdl", "--rdl-batch-config",
                         str(config), "--output-dir", str(output)]
            self.assertNotEqual(main(arguments + ["--deploy", "workspace"]), EXIT_SUCCESS)
            self.assertFalse(output.exists())
            self.assertEqual(main(arguments), EXIT_GENERAL_ERROR)
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("within the batch config directory", manifest["artifacts"][0]["error"])
            self.assertFalse((output / "report.wid").exists())

    def test_rdl_folder_rejects_ambiguous_crystal_sql(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / "multiple.rpt").write_bytes(
                b"\x00SELECT Region FROM FirstTable; SELECT Region FROM SecondTable;\x00")
            mapping = {"title": "Crystal", "source_kind": "crystal", "server": "sql.example.test",
                       "database": "Sales", "columns": ["Region"]}
            (root / "mapping.json").write_text(json.dumps(mapping), encoding="utf-8")
            config = root / "batch.json"
            config.write_text(json.dumps({"sources": {
                "multiple.rpt": {"mapping": "mapping.json", "sql_name": "CommandSQL"}
            }}), encoding="utf-8")
            output = root / "output"
            self.assertEqual(main([str(sources), "--output-format", "rdl", "--rdl-batch-config",
                                   str(config), "--output-dir", str(output)]), EXIT_GENERAL_ERROR)
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("match exactly one entry", manifest["artifacts"][0]["error"])
            self.assertFalse((output / "multiple.rpt" / "report.rdl").exists())

    def test_batch_reports_partial_failure(self):
        with tempfile.TemporaryDirectory() as sources:
            for name in ("A.wid", "B.wid"):
                with open(os.path.join(sources, name), "wb") as handle:
                    handle.write(b"fixture")
            with patch("migrate._run_single_migration", side_effect=[RuntimeError("bad source"), EXIT_SUCCESS]) as run:
                self.assertEqual(main(["--batch", sources, "--dry-run"]), EXIT_GENERAL_ERROR)
                self.assertEqual(run.call_count, 2)
                self.assertFalse(os.path.exists(sources + "_pbi"))

    def test_batch_preserves_quality_exit_code_and_manifest_diagnostic(self):
        import json

        with tempfile.TemporaryDirectory() as temporary:
            sources = os.path.join(temporary, 'sources')
            os.makedirs(sources)
            with open(os.path.join(sources, 'Sales.wid'), 'wb') as handle:
                handle.write(b'fixture')
            output = os.path.join(temporary, 'output')
            with patch('migrate._run_single_migration', return_value=EXIT_VALIDATION_ERROR):
                self.assertEqual(main(['--batch', sources, '--output-dir', output]), EXIT_VALIDATION_ERROR)
            with open(os.path.join(output, 'batch_manifest.json'), encoding='utf-8') as handle:
                artifact = json.load(handle)['artifacts'][0]
            self.assertEqual(artifact['exit_code'], EXIT_VALIDATION_ERROR)
            self.assertEqual(artifact['status'], 'failed')
            self.assertIn('quality', artifact['error'])

    def test_biar_preserves_quality_block_and_continues_other_artifacts(self):
        with tempfile.TemporaryDirectory() as output:
            artifacts = [{'name': name, 'type': 'webi', 'path': name + '.wid'} for name in ['A', 'B']]
            with (
                patch('bo_export.biar_reader.read_biar_archive', return_value=artifacts),
                patch('bo_export.biar_reader.extract_artifact_from_biar', return_value='fixture.wid'),
                patch('bo_export.extract_bo_data.extract_bo_data', return_value={}),
                patch('bo_export.converted_objects_adapter.adapt_bo_to_converted_objects', return_value={}),
                patch('migrate._generate_pbip_for_artifact', return_value=output) as generate,
                patch('migrate._validate_fabric_output', side_effect=[EXIT_VALIDATION_ERROR, EXIT_SUCCESS]),
            ):
                self.assertEqual(main(['--biar', 'archive.biar', '--output-format', 'fabric', '--output-dir', output]), EXIT_VALIDATION_ERROR)
                self.assertEqual(generate.call_count, 2)

    def test_shared_model_checks_the_generated_fabric_bundle(self):
        with patch('bo_export.extract_bo_data.extract_bo_data', return_value={}), \
             patch('bo_export.converted_objects_adapter.adapt_bo_to_converted_objects', return_value={}), \
             patch('powerbi_import.import_to_powerbi.PowerBIImporter') as importer, \
             patch('migrate._validate_fabric_output', return_value=EXIT_VALIDATION_ERROR) as validate:
            importer.return_value.import_shared_model.return_value = {'model_path': os.path.join('bundle', 'Shared.SemanticModel')}
            self.assertEqual(main(['--shared-model', 'A.wid', 'B.wid', '--output-format', 'fabric']), EXIT_VALIDATION_ERROR)
            self.assertEqual(validate.call_args.args[:2], ('bundle', 'fabric'))

    def test_shared_model_invokes_existing_merge_engine(self):
        with patch("bo_export.extract_bo_data.extract_bo_data", return_value={}), \
             patch("bo_export.converted_objects_adapter.adapt_bo_to_converted_objects", return_value={"datasources": []}), \
             patch("powerbi_import.import_to_powerbi.PowerBIImporter") as importer:
            importer.return_value.import_shared_model.return_value = {"model_path": "generated"}
            self.assertEqual(main(["--shared-model", "A.wid", "B.wid", "--model-name", "Shared"]), EXIT_SUCCESS)
            merge = importer.return_value.import_shared_model
            merge.assert_called_once()
            self.assertEqual(merge.call_args.args[0], "Shared")
            self.assertEqual(merge.call_args.args[2], ["A", "B"])

    def test_shared_model_requires_two_inputs(self):
        with patch("bo_export.extract_bo_data.extract_bo_data") as extract:
            self.assertNotEqual(main(["--shared-model", "A.wid"]), EXIT_SUCCESS)
            extract.assert_not_called()

    def test_fabric_output_uses_fabric_generator(self):
        from powerbi_import.import_to_powerbi import PowerBIImporter

        with tempfile.TemporaryDirectory() as output, \
             patch("powerbi_import.fabric_project_generator.FabricProjectGenerator") as fabric, \
             patch("powerbi_import.import_to_powerbi.PowerBIProjectGenerator") as pbip:
            fabric.return_value.generate_project.return_value = {"project_path": "fabric-project"}
            result = PowerBIImporter().generate_powerbi_project("Sales", {}, output_dir=output, output_format="fabric")
            self.assertEqual(result, "fabric-project")
            fabric.return_value.generate_project.assert_called_once()
            pbip.assert_not_called()

    def test_generation_errors_are_not_silently_successful(self):
        from powerbi_import.import_to_powerbi import PowerBIImporter

        with tempfile.TemporaryDirectory() as output, \
             patch("powerbi_import.import_to_powerbi.PowerBIProjectGenerator") as generator:
            generator.return_value.generate_project.side_effect = RuntimeError("generation failed")
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                PowerBIImporter().generate_powerbi_project("Sales", {}, output_dir=output)

    def test_batch_routes_archives_to_biar_pipeline(self):
        with tempfile.TemporaryDirectory() as sources:
            with open(os.path.join(sources, "archive.biar"), "wb") as handle:
                handle.write(b"fixture")
            with patch("migrate._run_biar_migration", return_value=EXIT_SUCCESS) as biar, \
                 patch("migrate._run_single_migration") as single:
                self.assertEqual(main(["--batch", sources, "--dry-run"]), EXIT_SUCCESS)
                biar.assert_called_once()
                single.assert_not_called()

    def test_biar_dry_run_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = os.path.join(temporary, "output")
            with (
                patch("bo_export.biar_reader.read_biar_archive", return_value=[{"name": "Sales", "type": "webi", "path": "Sales.wid"}]),
                patch("bo_export.biar_reader.extract_artifact_from_biar", return_value="Sales.wid"),
                patch("bo_export.extract_bo_data.extract_bo_data", return_value={}),
                patch("bo_export.converted_objects_adapter.adapt_bo_to_converted_objects", return_value={}),
                patch("powerbi_import.assessment.run_assessment"),
                patch("powerbi_import.assessment.print_assessment_report"),
                patch("migrate._generate_pbip_for_artifact") as generate,
            ):
                self.assertEqual(main(["--biar", "archive.biar", "--dry-run", "--output-dir", output]), EXIT_SUCCESS)
                generate.assert_not_called()
                self.assertFalse(os.path.exists(output))

    def test_biar_with_no_recognized_artifacts_reports_error_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = os.path.join(temporary, "segmented.lcmbiar")
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("BusinessObjects.xml", "<metadata/>")
                handle.writestr("content.001", b"unrecognized segment")

            for dry_run in (False, True):
                with self.subTest(dry_run=dry_run):
                    output = os.path.join(temporary, f"output-{dry_run}")
                    args = ["--biar", archive, "--output-dir", output]
                    if dry_run:
                        args.append("--dry-run")
                    with self.assertLogs("bo_migrate", level="ERROR") as logged:
                        self.assertEqual(main(args), EXIT_GENERAL_ERROR)
                    self.assertIn("No supported standalone", " ".join(logged.output))
                    self.assertFalse(os.path.exists(output))

    def test_batch_refuses_duplicate_archive_names_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            with zipfile.ZipFile(sources / "archive.biar", "w") as archive:
                archive.writestr("first/Sales.wid", b"fixture")
                archive.writestr("second/sales.rpt", b"fixture")
            output = root / "output"
            self.assertEqual(main([str(sources), "--output-dir", str(output)]), EXIT_GENERAL_ERROR)
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["artifacts"][0]["status"], "failed")
            self.assertIn("same output name", manifest["artifacts"][0]["error"])
            self.assertFalse((output / "archive.biar").exists())

    def test_positional_archive_does_not_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "archive.biar"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("Sales.wid", b"fixture")
            output = root / "output"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            with patch("migrate._generate_pbip_for_artifact") as generate:
                self.assertNotEqual(main([str(source), "--output-dir", str(output)]), EXIT_SUCCESS)
                generate.assert_not_called()
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_biar_generation_failure_returns_error(self):
        with tempfile.TemporaryDirectory() as output:
            with (
                patch("bo_export.biar_reader.read_biar_archive", return_value=[{"name": "Sales", "type": "webi", "path": "Sales.wid"}]),
                patch("bo_export.biar_reader.extract_artifact_from_biar", return_value="Sales.wid"),
                patch("bo_export.extract_bo_data.extract_bo_data", return_value={}),
                patch("bo_export.converted_objects_adapter.adapt_bo_to_converted_objects", return_value={}),
                patch("migrate._generate_pbip_for_artifact", side_effect=RuntimeError("generation failed")),
            ):
                self.assertEqual(main(["--biar", "archive.biar", "--output-dir", output]), EXIT_GENERAL_ERROR)


if __name__ == "__main__":
    unittest.main()
