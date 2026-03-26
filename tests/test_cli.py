"""Tests for the CLI entry point (migrate.py)."""

import sys
import unittest
from unittest.mock import patch

from migrate import build_parser, main, EXIT_GENERAL_ERROR


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


if __name__ == "__main__":
    unittest.main()
