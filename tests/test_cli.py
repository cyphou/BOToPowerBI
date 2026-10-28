"""Tests for the CLI entry point (migrate.py)."""

import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from migrate import build_parser, main, EXIT_GENERAL_ERROR, EXIT_SUCCESS, EXIT_VALIDATION_ERROR


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

    def test_generation_reads_default_extraction_and_can_skip_optimizer(self):
        with patch("bo_export.extract_bo_data.extract_bo_data", return_value={}) as extract, \
             patch("powerbi_import.import_to_powerbi.PowerBIImporter") as importer, \
             patch("powerbi_import.dax_optimizer.optimize_dax_project") as optimize, \
             patch("powerbi_import.comparison_report.generate_comparison_report") as compare:
            self.assertEqual(main(["report.wid", "--no-optimize-dax", "--no-compare"]), EXIT_SUCCESS)
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
            self.assertEqual(main(["report.wid", "--no-optimize-dax"]), EXIT_SUCCESS)
            self.assertEqual(compare.call_args.args[1], "generated-project")

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
