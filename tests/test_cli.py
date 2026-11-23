"""Tests for the CLI entry point (migrate.py)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from migrate import (
    EXIT_GENERAL_ERROR,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED_FORMAT,
    EXIT_VALIDATION_ERROR,
    MigrationStats,
    _record_migration_object_warnings,
    _run_single_migration,
    build_parser,
    main,
)
from powerbi_import.validator import ArtifactValidator


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
             patch("powerbi_import.expression_export.export_generated_project",
                   return_value={"exports": []}), \
             patch("powerbi_import.dax_optimizer.optimize_dax_project") as optimize, \
             patch("powerbi_import.comparison_report.generate_comparison_report") as compare:
            importer.return_value.import_all.return_value = "generated-project"
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
             patch("powerbi_import.expression_export.export_generated_project",
                   return_value={"exports": []}), \
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
                                   "--dry-run"]), EXIT_SUCCESS)
            self.assertFalse(output.exists())
            self.assertEqual(main([str(sources), "--output-dir", str(output),
                                   "--no-compare", "--no-optimize-dax"]), EXIT_SUCCESS)
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual({item["source_kind"] for item in manifest["artifacts"]}, {"webi", "biar"})
            self.assertTrue(all(item["status"] == "success" for item in manifest["artifacts"]))
            self.assertTrue(list((output / "Sales.wid").rglob("*.pbip")))
            self.assertTrue(list((output / "Export.biar").rglob("*.pbip")))
            for source_output in (output / "Sales.wid", output / "Export.biar"):
                projects = list(source_output.rglob("*.pbip"))
                self.assertEqual(len(projects), 1)
                project = projects[0].parent
                exported = json.loads((project / "expression_export.json").read_text(
                    encoding="utf-8"
                ))
                self.assertTrue(any(entry["kind"] == "m_partition" for entry in exported["exports"]))
                self.assertTrue(any(entry["kind"] == "dax_measures" for entry in exported["exports"]))
                self.assertTrue((project / "DAX" / "FACT_SALES.dax").is_file())
            for item in manifest["artifacts"]:
                self.assertIn("12 extracted column(s)", " ".join(item["warnings"]))
            self.assertIn("12 extracted column(s)",
                          (output / "batch_report.html").read_text(encoding="utf-8"))

    def test_synthetic_webi_visual_model_bindings_remain_unresolved(self):
        fixture = Path(__file__).resolve().parents[1] / "examples" / "Enterprise_Sales.wid"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / fixture.name).write_bytes(fixture.read_bytes())
            output = root / "output"
            generated = subprocess.run(
                [
                    sys.executable, str(Path(__file__).resolve().parents[1] / "migrate.py"),
                    str(sources), "--output-dir", str(output),
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)

            project = output / "Enterprise_Sales.wid" / "Enterprise_Sales"
            self.assertTrue((project / "Enterprise_Sales.pbip").is_file())
            model_dir = project / "Enterprise_Sales.SemanticModel"
            symbols = ArtifactValidator._collect_model_symbols(str(model_dir))
            model_fields = {
                table: symbols["columns"].get(table, set())
                | symbols["measures"].get(table, set())
                for table in symbols["tables"]
            }

            references = []

            def collect_references(value, visual_id):
                if isinstance(value, dict):
                    for kind in ("Column", "Measure"):
                        field = value.get(kind)
                        if not isinstance(field, dict):
                            continue
                        expression = field.get("Expression", {})
                        source_ref = expression.get("SourceRef", {}) if isinstance(
                            expression, dict
                        ) else {}
                        entity = source_ref.get("Entity") if isinstance(source_ref, dict) else None
                        prop = field.get("Property")
                        if isinstance(entity, str) and isinstance(prop, str):
                            references.append((visual_id, entity, prop))
                    for child in value.values():
                        collect_references(child, visual_id)
                elif isinstance(value, list):
                    for child in value:
                        collect_references(child, visual_id)

            for visual_path in project.rglob("visual.json"):
                visual = json.loads(visual_path.read_text(encoding="utf-8"))
                collect_references(visual, visual_path.parent.name)

            self.assertTrue(references, "Generated visuals must contain model field references")
            unresolved = {
                reference for reference in references
                if reference[1] not in model_fields
                or reference[2] not in model_fields[reference[1]]
            }
            self.assertTrue(unresolved, "The synthetic sample's unresolved binding must remain visible")
            self.assertTrue(all(entity == "Table" for _, entity, _ in unresolved))
            unresolved_visuals = {visual_id for visual_id, _, _ in unresolved}

            validation = subprocess.run(
                [
                    sys.executable, str(Path(__file__).resolve().parents[1] / "migrate.py"),
                    "--validate-project", str(project),
                ],
                capture_output=True, text=True, check=False,
            )
            validation_output = validation.stdout + validation.stderr
            self.assertEqual(validation.returncode, 0, validation_output)

            report = ArtifactValidator.validate_project(project)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["errors"], [])
            expected_findings = {
                f'Visual {visual_id}: unknown Entity "Table" (not in TMDL model)'
                for visual_id in unresolved_visuals
            }
            self.assertTrue(
                expected_findings.issubset(set(report["warnings"])),
                f"Expected unresolved visual findings {expected_findings}; "
                f"got {report['warnings']}",
            )
            for finding in expected_findings:
                self.assertIn(finding, validation_output)
            self.assertTrue(report["warnings"], "Other static warnings must not be suppressed")

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
            project = model_path.parents[3]
            partition_lines = []
            for line in model.split("\t\tsource =\n", 1)[1].split("\n"):
                if not line.startswith("\t\t\t\t"):
                    break
                partition_lines.append(line[4:])
            self.assertEqual(
                (project / "PowerQuery" / "Sales_Query.pq").read_text(encoding="utf-8"),
                "\n".join(partition_lines) + "\n",
            )
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
            fabric_project = next(fabric_output.rglob("expression_export.json")).parent
            mashup = (fabric_project / "Sales.Dataflow" / "mashup.pq").read_text(
                encoding="utf-8"
            )
            self.assertIn(dataflow.split("\n\n", 1)[1].rstrip("\n"), mashup)
            self.assertEqual(
                (fabric_project / "PowerQuery" / "Dataflow" / "Sales_Query.pq").read_text(
                    encoding="utf-8"
                ),
                dataflow,
            )
            fabric_manifest = json.loads(
                (fabric_project / "expression_export.json").read_text(encoding="utf-8")
            )
            self.assertIn({
                "path": "PowerQuery/Dataflow/Sales_Query.pq",
                "source": "Sales.Dataflow/queries/Sales_Query.m",
                "kind": "dataflow_m_query",
                "source_scope": "project",
            }, fabric_manifest["exports"])

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
            self.assertTrue((sales_tables[0].parents[3] / "PowerQuery" / "Sales.pq").is_file())
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
                self.assertIn("No source report visuals were converted",
                              " ".join(artifact["warnings"]))
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
            from powerbi_import.migration_quality import build_quality_report
            quality = build_quality_report(output)
            self.assertEqual(quality["summary"]["projects"], 2)
            self.assertEqual(quality["summary"]["errors"], 0, quality["priorities"])

    def test_crystal_and_unv_projects_export_generated_expressions(self):
        repository = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / "Invoice_Report.rpt").write_bytes(
                (repository / "examples" / "Invoice_Report.rpt").read_bytes()
            )
            (sources / "Synthetic.unv").write_text(
                '<?xml version="1.0"?><DataFoundation>'
                '<Connection name="Warehouse" type="SQL Server" '
                'server="db.example.invalid" database="Sales"/>'
                '<Table name="Orders"/></DataFoundation>',
                encoding="utf-8",
            )
            output = root / "output"
            with redirect_stdout(StringIO()):
                self.assertEqual(main([str(sources), "--output-dir", str(output),
                                       "--no-compare", "--no-optimize-dax"]), EXIT_SUCCESS)
            for source, project_name in (("Invoice_Report.rpt", "Invoice_Report"),
                                         ("Synthetic.unv", "Synthetic")):
                project = output / source / project_name
                manifest = json.loads((project / "expression_export.json").read_text(
                    encoding="utf-8"
                ))
                self.assertTrue(any(entry["kind"] == "m_partition" for entry in manifest["exports"]))
                for entry in manifest["exports"]:
                    self.assertTrue((project / entry["path"]).is_file())

    def test_fabric_biar_exports_actual_dataflow_queries(self):
        fixture = Path(__file__).resolve().parent.parent / "examples" / "HR_Universe.unx"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "HR.biar"
            with zipfile.ZipFile(source, "w") as archive:
                archive.write(fixture, "Folder/HR_Universe.unx")
            output = root / "output"
            with redirect_stdout(StringIO()):
                self.assertEqual(main([str(source), "--output-dir", str(output),
                                       "--output-format", "fabric", "--no-compare",
                                       "--no-optimize-dax"]), EXIT_SUCCESS)
            project = output / "HR_Universe" / "HR_Universe"
            self.assertNotEqual(json.loads((project / "quality_report.json").read_text(
                encoding="utf-8"
            ))["status"], "FAIL")
            manifest = json.loads((project / "expression_export.json").read_text(encoding="utf-8"))
            queries = [item for item in manifest["exports"] if item["kind"] == "dataflow_m_query"]
            self.assertTrue(queries)
            mashup = (project / "HR_Universe.Dataflow" / "mashup.pq").read_text(encoding="utf-8")
            for item in queries:
                exported = (project / item["path"]).read_text(encoding="utf-8")
                self.assertEqual(exported, (project / item["source"]).read_text(encoding="utf-8"))
                self.assertIn(exported.split("\n\n", 1)[1].rstrip("\n"), mashup)

    def test_file_only_fabric_model_does_not_invent_dataflow_queries(self):
        from powerbi_import.import_to_powerbi import PowerBIImporter

        data = {"datasources": [{
            "name": "Source",
            "connection": {"type": "CSV", "details": {"filename": "orders.csv"}},
            "tables": [{"name": "Orders", "columns": [{"name": "Id", "datatype": "integer"}]}],
        }]}
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            project = Path(PowerBIImporter().generate_powerbi_project(
                "FileOnly", data, output_dir=temporary, output_format="fabric"
            ))
            manifest = json.loads((project / "expression_export.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["kind"] == "shared_m_expression" for item in manifest["exports"]))
            self.assertFalse(any(item["kind"] == "dataflow_m_query" for item in manifest["exports"]))
            self.assertFalse((project / "PowerQuery" / "Dataflow").exists())
            self.assertTrue((project / "FileOnly.Notebook" / "etl_pipeline.ipynb").is_file())

    def test_importer_tmdl_output_exports_model_expressions(self):
        from powerbi_import.import_to_powerbi import PowerBIImporter

        data = {"datasources": [{
            "name": "Source",
            "connection": {"type": "SQL Server", "server": "db.example.invalid"},
            "tables": [{"name": "Orders", "columns": [{"name": "Id", "datatype": "integer"}]}],
        }]}
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            project = Path(PowerBIImporter().generate_powerbi_project(
                "ModelOnly", data, output_dir=temporary, output_format="tmdl"
            ))
            manifest = json.loads((project / "expression_export.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["kind"] == "m_partition" for item in manifest["exports"]))
            self.assertTrue((project / "PowerQuery" / "Orders.pq").is_file())
            self.assertFalse((project / "ModelOnly.Report").exists())

    def test_export_occurs_after_optimizer_pass(self):
        fixture = Path(__file__).resolve().parent.parent / "examples" / "Enterprise_Sales.wid"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / "Sales.wid").write_bytes(fixture.read_bytes())
            output = root / "output"
            old = "CALCULATE(SUM('FACT_SALES'[Revenue]), ALL('FACT_SALES'))"
            new = "SUM('FACT_SALES'[Revenue])"

            def modify_generated_model(item_output):
                table = (Path(item_output) / "Sales" / "Sales.SemanticModel"
                         / "definition" / "tables" / "FACT_SALES.tmdl")
                text = table.read_text(encoding="utf-8")
                self.assertIn(old, text)
                table.write_text(text.replace(old, new), encoding="utf-8")
                return {"total_optimizations": 1}

            with patch("powerbi_import.dax_optimizer.optimize_dax_project",
                       side_effect=modify_generated_model) as optimize, redirect_stdout(StringIO()):
                self.assertEqual(main([str(sources), "--output-dir", str(output),
                                       "--no-compare"]), EXIT_SUCCESS)
            optimize.assert_called_once()
            exported = (output / "Sales.wid" / "Sales" / "DAX" / "FACT_SALES.dax").read_text(
                encoding="utf-8"
            )
            self.assertIn("'Total Revenue' =\n" + new, exported)
            self.assertNotIn("'Total Revenue' =\n" + old, exported)

    def test_legacy_batch_reuse_refuses_old_expression_outputs_before_model_rewrite(self):
        fixture = Path(__file__).resolve().parent.parent / "examples" / "Enterprise_Sales.wid"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / "Sales.wid").write_bytes(fixture.read_bytes())
            output = root / "output"
            args = ["--batch", str(sources), "--output-dir", str(output),
                    "--no-compare", "--no-optimize-dax"]
            with redirect_stdout(StringIO()):
                self.assertEqual(main(args), EXIT_SUCCESS)
                project = output / "Sales.wid" / "Sales"
                table = project / "Sales.SemanticModel" / "definition" / "tables" / "FACT_SALES.tmdl"
                query = project / "PowerQuery" / "FACT_SALES.pq"
                table_before, query_before = table.read_bytes(), query.read_bytes()
                self.assertEqual(main(args), EXIT_GENERAL_ERROR)
            self.assertEqual(table.read_bytes(), table_before)
            self.assertEqual(query.read_bytes(), query_before)
            artifact = json.loads((output / "batch_manifest.json").read_text(
                encoding="utf-8"
            ))["artifacts"][0]
            self.assertEqual(artifact["status"], "failed")
            self.assertIn("Expression export target already exists", artifact["error"])

    def test_expression_export_failure_is_reported_in_batch_manifest(self):
        fixture = Path(__file__).resolve().parent.parent / "examples" / "Enterprise_Sales.wid"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            sources.mkdir()
            (sources / "Sales.wid").write_bytes(fixture.read_bytes())
            output = root / "output"
            with patch("powerbi_import.expression_export.export_generated_project",
                       side_effect=ValueError("unsupported generated expression")), \
                 redirect_stdout(StringIO()):
                self.assertEqual(main([str(sources), "--output-dir", str(output),
                                       "--no-compare", "--no-optimize-dax"]), EXIT_GENERAL_ERROR)
            artifact = json.loads((output / "batch_manifest.json").read_text(
                encoding="utf-8"
            ))["artifacts"][0]
            self.assertEqual(artifact["status"], "failed")
            self.assertIn("unsupported generated expression", artifact["error"])

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
            (sources / "ancien.txt").write_bytes(b"unsupported")
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
            self.assertEqual(manifest["skipped"][0]["source"], "ancien.txt")
            report_html = (output / "batch_report.html").read_text(encoding="utf-8")
            self.assertIn("Crystal SQL extraction is heuristic", report_html)
            self.assertIn("ancien.txt", report_html)
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
             patch("powerbi_import.expression_export.export_generated_project",
                   return_value={"exports": []}) as export, \
             patch("powerbi_import.import_to_powerbi.PowerBIProjectGenerator") as pbip:
            fabric.return_value.generate_project.return_value = {"project_path": "fabric-project"}
            result = PowerBIImporter().generate_powerbi_project("Sales", {}, output_dir=output, output_format="fabric")
            self.assertEqual(result, "fabric-project")
            fabric.return_value.generate_project.assert_called_once()
            export.assert_called_once_with(
                os.path.join("fabric-project", "Sales.SemanticModel"), include_dataflow=True,
            )
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


class TestSimplifiedCLIWorkflows(unittest.TestCase):
    """Exercise the public shortcuts through the real CLI and RDL generator."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "espace de travail Ω"
        self.root.mkdir()
        self.script = Path(__file__).resolve().parents[1] / "migrate.py"

    def _run_cli(self, *arguments, timeout=30):
        return subprocess.run(
            [sys.executable, str(self.script), *arguments],
            cwd=self.root, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=timeout,
        )

    def _write_mapping(self, directory):
        directory.mkdir(parents=True)
        mapping = directory / "mappage résumé.v1.JSON"
        mapping.write_text(json.dumps({
            "title": "Ventes", "source_kind": "webi",
            "workspace": "Workspace", "semantic_model": "Sales Model",
            "dax": "EVALUATE Sales", "columns": ["Sales[Amount]"],
        }, ensure_ascii=False), encoding="utf-8")
        return mapping

    def _snapshot(self):
        return {
            path.relative_to(self.root): path.read_bytes() if path.is_file() else None
            for path in self.root.rglob("*")
        }

    def test_quick_help_and_complete_help_are_available_without_migrating(self):
        quick = self._run_cli("--help")
        short_alias = self._run_cli("-h")
        complete = self._run_cli("--help-all")

        for result in (quick, short_alias, complete):
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(short_alias.stdout, quick.stdout)
        for option in ("--help-all", "--assess", "--dry-run", "--rdl-mapping"):
            self.assertIn(option, quick.stdout)
        for option in (
            "--schema-drift", "--multi-tenant", "--calendar-start",
            "--rdl-accept-unverified-rep-sql", "--shared-model",
        ):
            self.assertIn(option, complete.stdout)
        self.assertLessEqual(len(quick.stdout.splitlines()), 40)
        self.assertLess(len(quick.stdout.splitlines()) * 2, len(complete.stdout.splitlines()))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_legacy_advanced_options_still_parse(self):
        args = build_parser().parse_args([
            "legacy report.wid", "--output-format", "fabric", "-o", "legacy output",
            "--calendar-start", "2017", "--calendar-end", "2027", "--culture", "fr-FR",
            "--universe", "sales.unx", "--no-optimize-dax", "--no-compare",
            "--refresh-config", "--multi-tenant", "tenants.json", "--incremental",
            "--schema-drift", "previous extraction", "--verbose",
        ])
        expected = {
            "input": "legacy report.wid", "output_format": "fabric",
            "output_dir": "legacy output", "calendar_start": 2017, "calendar_end": 2027,
            "culture": "fr-FR", "universe": "sales.unx", "no_optimize_dax": True,
            "no_compare": True, "refresh_config": True, "multi_tenant": "tenants.json",
            "incremental": True, "schema_drift": "previous extraction", "verbose": True,
        }
        for name, value in expected.items():
            with self.subTest(option=name):
                self.assertEqual(getattr(args, name), value)

    def test_rep_suffix_directory_dry_run_uses_existing_folder_pipeline(self):
        for directory_name in ("Rapports ventes.rep", "Rapports résumé.REP"):
            with self.subTest(directory=directory_name):
                sources = self.root / directory_name
                sources.mkdir()
                (sources / "Sales.wid").write_text(
                    '<document><Report name="Overview"/></document>', encoding="utf-8",
                )
                before = self._snapshot()
                with patch("migrate._run_batch_migration", return_value=EXIT_SUCCESS) as batch, \
                     patch("bo_export.desktop_intelligence_extractor.inspect_desktop_intelligence") as inspect, \
                     redirect_stdout(StringIO()):
                    self.assertEqual(main([str(sources), "--dry-run"]), EXIT_SUCCESS)
                batch.assert_called_once()
                self.assertEqual(batch.call_args.args[0].batch, str(sources))
                self.assertTrue(batch.call_args.args[0].dry_run)
                self.assertTrue(batch.call_args.args[0]._positional_directory)
                inspect.assert_not_called()

                result = self._run_cli(str(sources), "--dry-run")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self._snapshot(), before)

    def test_rdl_inference_and_explicit_legacy_command_generate_new_files(self):
        for mode in ("inferred-sibling", "inferred-explicit", "legacy-explicit"):
            with self.subTest(mode=mode):
                mapping = self._write_mapping(self.root / mode)
                mapping_before = mapping.read_bytes()
                sibling = mapping.with_suffix(".rdl")
                explicit = mapping.parent / "rapport choisi.rdl"
                mapping_arg = (
                    str(mapping.relative_to(self.root))
                    if mode == "inferred-sibling" else str(mapping)
                )
                arguments = ["--rdl-mapping", mapping_arg]
                if mode == "inferred-explicit":
                    arguments = [f"--rdl-mapping={mapping_arg}"]
                if mode != "inferred-sibling":
                    arguments += ["--rdl-output", str(explicit)]
                if mode == "legacy-explicit":
                    arguments = ["--output-format", "rdl", *arguments]
                output = sibling if mode == "inferred-sibling" else explicit

                result = self._run_cli(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(output.is_file())
                namespace = {
                    "r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition",
                }
                report = ET.parse(output).getroot()
                self.assertEqual(report.tag, f"{{{namespace['r']}}}Report")
                self.assertEqual(
                    report.findtext(".//r:CommandText", namespaces=namespace),
                    "EVALUATE Sales",
                )
                self.assertEqual(mapping.read_bytes(), mapping_before)
                self.assertEqual(set(mapping.parent.iterdir()), {mapping, output})

                generated = output.read_bytes()
                retry = self._run_cli(*arguments)
                self.assertNotEqual(retry.returncode, 0, retry.stdout + retry.stderr)
                self.assertEqual(output.read_bytes(), generated)
                self.assertEqual(mapping.read_bytes(), mapping_before)
                self.assertEqual(set(mapping.parent.iterdir()), {mapping, output})

    def test_inferred_rdl_does_not_replace_an_existing_destination(self):
        mapping = self._write_mapping(self.root / "protected")
        output = mapping.with_suffix(".rdl")
        sentinel = b"existing report must not be overwritten\n"
        output.write_bytes(sentinel)
        before = self._snapshot()

        result = self._run_cli("--rdl-mapping", str(mapping))

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output.read_bytes(), sentinel)
        self.assertEqual(self._snapshot(), before)

    def test_inferred_rdl_uses_utf8_streams_without_encoding_overrides(self):
        mapping = self._write_mapping(self.root / "encodage français")
        output = mapping.with_suffix(".rdl")
        environment = os.environ.copy()
        environment.pop("PYTHONIOENCODING", None)
        environment.pop("PYTHONUTF8", None)

        result = subprocess.run(
            [sys.executable, str(self.script), "--rdl-mapping", str(mapping)],
            cwd=self.root, env=environment, capture_output=True, timeout=30,
        )

        stdout = result.stdout.decode("utf-8", errors="strict")
        stderr = result.stderr.decode("utf-8", errors="strict")
        self.assertEqual(result.returncode, 0, stderr)
        self.assertIn("not_run", stdout)
        self.assertIn(str(output), stderr)
        self.assertTrue(output.is_file())

    def test_argparse_errors_use_utf8_without_encoding_overrides(self):
        mapping = self._write_mapping(self.root / "arguments français")
        environment = os.environ.copy()
        environment.pop("PYTHONIOENCODING", None)
        environment.pop("PYTHONUTF8", None)
        before = self._snapshot()
        cases = (
            (["--output-format", "périmé"], "périmé"),
            (["--rdl-mapping", str(mapping), "--option-inconnue=é"], "--option-inconnue=é"),
        )
        for arguments, invalid in cases:
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(self.script), *arguments],
                    cwd=self.root, env=environment, capture_output=True, timeout=30,
                )
                stdout = result.stdout.decode("utf-8", errors="strict")
                stderr = result.stderr.decode("utf-8", errors="strict")
                self.assertEqual(result.returncode, 2, stderr)
                self.assertEqual(stdout, "")
                self.assertIn(invalid, stderr)
                self.assertEqual(self._snapshot(), before)

    def test_only_one_concurrent_inferred_rdl_writer_succeeds(self):
        mapping = self._write_mapping(self.root / "concurrent")
        mapping_before = mapping.read_bytes()
        output = mapping.with_suffix(".rdl")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda _: self._run_cli("--rdl-mapping", str(mapping), timeout=120), range(2),
            ))

        self.assertEqual(sum(result.returncode == 0 for result in results), 1)
        namespace = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
        self.assertEqual(
            ET.parse(output).findtext(".//r:CommandText", namespaces=namespace),
            "EVALUATE Sales",
        )
        self.assertEqual(mapping.read_bytes(), mapping_before)
        self.assertEqual(set(mapping.parent.iterdir()), {mapping, output})

    def test_inferred_rdl_does_not_follow_a_dangling_output_symlink(self):
        mapping = self._write_mapping(self.root / "symlink")
        output = mapping.with_suffix(".rdl")
        victim = mapping.parent / "not-yet-created.rdl"
        try:
            output.symlink_to(victim.name)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Creating a file symlink is unavailable: {error}")
        self.assertTrue(output.is_symlink())
        self.assertFalse(output.exists())

        result = self._run_cli("--rdl-mapping", str(mapping))

        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.is_symlink())
        self.assertFalse(victim.exists())

    def test_inferred_rdl_with_dangling_power_query_symlink_creates_neither_target(self):
        directory = self.root / "RDL et requête"
        directory.mkdir()
        mapping = directory / "déclaration.sql.json"
        sql = "SELECT Region FROM Sales"
        mapping.write_text(json.dumps({
            "title": "Ventes", "source_kind": "webi", "server": "sql.example.test",
            "database": "Sales", "sql": sql, "columns": ["Region"],
        }, ensure_ascii=False), encoding="utf-8")
        original_mapping = mapping.read_bytes()
        report = mapping.with_suffix(".rdl")
        query = directory / "Requête Power Query.m"
        victim = directory / "cible manquante.m"
        arguments = [
            "--rdl-mapping", str(mapping), "--rdl-power-query-output", str(query),
        ]

        control = self._run_cli(*arguments)
        self.assertEqual(control.returncode, 0, control.stderr)
        namespace = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
        self.assertEqual(ET.parse(report).findtext(".//r:CommandText", namespaces=namespace), sql)
        self.assertIn(sql, query.read_text(encoding="utf-8"))
        report.unlink()
        query.unlink()
        try:
            query.symlink_to(victim.name)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Creating a file symlink is unavailable: {error}")
        self.assertTrue(query.is_symlink())
        self.assertFalse(query.exists())

        result = self._run_cli(*arguments)

        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertFalse(report.exists())
        self.assertFalse(victim.exists())
        self.assertTrue(query.is_symlink())
        self.assertEqual(mapping.read_bytes(), original_mapping)
        self.assertEqual(set(directory.iterdir()), {mapping, query})

    def test_explicit_pbip_and_incomplete_legacy_rdl_are_rejected(self):
        mapping = self._write_mapping(self.root / "conflicts")
        explicit = mapping.parent / "explicit.rdl"
        before = self._snapshot()
        cases = (
            ["--output-format", "pbip", "--rdl-mapping", str(mapping)],
            ["--rdl-mapping", str(mapping), "--rdl-output", str(explicit),
             "--output-format=pbip"],
            ["--output-format", "rdl", "--rdl-mapping", str(mapping)],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self._run_cli(*arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self._snapshot(), before)

    def test_invalid_or_extra_rdl_arguments_do_not_generate(self):
        mapping = self._write_mapping(self.root / "invalid")
        malformed = mapping.parent / "malformed.json"
        malformed.write_text("{ invalid JSON", encoding="utf-8")
        before = self._snapshot()
        base = ["--rdl-mapping", str(mapping)]
        cases = (
            [*base, "extra.wid"],
            [*base, "--unknown-option"],
            [*base, "--assess"],
            [*base, "--output-dir", str(self.root / "not-created")],
            [*base, "--rdl-output", str(mapping.parent / "not-an-rdl.txt")],
            [*base, "--rdl-output", ""],
            [*base, "--rdl-sql-name", "candidate"],
            [*base, "--rdl-bo-source", str(self.root / "source.rep")],
            [*base, "--rdl-accept-unverified-rep-sql"],
            [*base, "--output-format", "not-a-format"],
            ["--rdl-mapping", ""],
            ["--rdl-mapping", str(malformed)],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self._run_cli(*arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self._snapshot(), before)


if __name__ == "__main__":
    unittest.main()
