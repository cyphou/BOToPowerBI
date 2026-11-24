import argparse
import json
import os
import tempfile
import unittest

from powerbi_import.config.migration_config import (
    MigrationConfig,
    load_config,
)


class MigrationConfigTests(unittest.TestCase):
    def test_defaults_and_deep_copy(self):
        config = MigrationConfig()

        self.assertIsNone(config.tableau_file)
        self.assertIsNone(config.prep_flow)
        self.assertIsNone(config.output_dir)
        self.assertEqual(config.output_format, "pbip")
        self.assertIsNone(config.report_name)
        self.assertEqual(config.model_mode, "import")
        self.assertEqual(config.culture, "en-US")
        self.assertEqual(config.calendar_start, 2020)
        self.assertEqual(config.calendar_end, 2030)
        self.assertEqual(config.template_vars, {})
        self.assertFalse(config.skip_extraction)
        self.assertFalse(config.dry_run)
        self.assertFalse(config.rollback)
        self.assertFalse(config.verbose)
        self.assertIsNone(config.log_file)
        self.assertEqual(config.plugins, [])

        exported = config.to_dict()
        exported["connections"]["template_vars"]["SERVER"] = "mutated"
        exported["plugins"].append("mutated")
        self.assertEqual(config.template_vars, {})
        self.assertEqual(config.plugins, [])

    def test_partial_merge_preserves_unspecified_defaults(self):
        config = MigrationConfig({
            "output": {"directory": "artifacts/test", "format": "fabric"},
            "model": {"culture": "fr-FR"},
            "connections": {"template_vars": {"DATABASE": "sales"}},
            "plugins": ["uno"],
        })

        self.assertEqual(config.output_dir, "artifacts/test")
        self.assertEqual(config.output_format, "fabric")
        self.assertEqual(config.culture, "fr-FR")
        self.assertEqual(config.template_vars, {"DATABASE": "sales"})
        self.assertEqual(config.plugins, ["uno"])
        self.assertEqual(config.calendar_start, 2020)

    def test_from_args_maps_supported_values_and_ignores_false_flags(self):
        args = argparse.Namespace(
            tableau_file="sales.wid",
            prep="sales.prep",
            output_dir="out",
            output_format="fabric",
            mode="directlake",
            culture="de-DE",
            calendar_start=2018,
            calendar_end=2026,
            skip_extraction=True,
            skip_conversion=False,
            dry_run=True,
            rollback=True,
            verbose=True,
            log_file="migration.log",
        )

        config = MigrationConfig.from_args(args)

        self.assertEqual(config.tableau_file, "sales.wid")
        self.assertEqual(config.prep_flow, "sales.prep")
        self.assertEqual(config.output_dir, "out")
        self.assertEqual(config.output_format, "fabric")
        self.assertEqual(config.model_mode, "directlake")
        self.assertEqual(config.culture, "de-DE")
        self.assertEqual(config.calendar_start, 2018)
        self.assertEqual(config.calendar_end, 2026)
        self.assertTrue(config.skip_extraction)
        self.assertFalse(config.to_dict()["migration"]["skip_conversion"])
        self.assertTrue(config.dry_run)
        self.assertTrue(config.rollback)
        self.assertTrue(config.verbose)
        self.assertEqual(config.log_file, "migration.log")

    def test_from_args_handles_missing_attributes_and_none(self):
        config = MigrationConfig.from_args(argparse.Namespace(output_dir=None, mode=None, verbose=False))
        self.assertIsNone(config.output_dir)
        self.assertEqual(config.model_mode, "import")
        self.assertFalse(config.verbose)

    def test_merge_with_args_cli_wins_but_defaults_do_not_overwrite_file(self):
        base = MigrationConfig({
            "output": {"directory": "config-out", "format": "pbip", "report_name": "ConfigReport"},
            "model": {"culture": "fr-FR", "calendar_start": 2010},
            "migration": {"dry_run": True, "verbose": True},
        })
        args = argparse.Namespace(
            output_dir="cli-out",
            output_format="fabric",
            culture="en-GB",
            dry_run=False,
            verbose=False,
        )

        merged = base.merge_with_args(args)

        self.assertEqual(merged.output_dir, "cli-out")
        self.assertEqual(merged.output_format, "fabric")
        self.assertEqual(merged.culture, "en-GB")
        self.assertEqual(merged.report_name, "ConfigReport")
        self.assertEqual(merged.calendar_start, 2010)
        self.assertTrue(merged.dry_run)
        self.assertTrue(merged.verbose)

    def test_load_save_round_trip_unicode_and_load_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config", "migration.json")
            config = MigrationConfig({
                "output": {"directory": "résultats", "report_name": "Ventés/Été"},
                "connections": {"template_vars": {"SERVEUR": "hébergement"}},
            })

            config.save(path)

            self.assertTrue(os.path.isfile(path))
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertIn("résultats", payload["output"]["directory"])
            self.assertIn("Ventés", payload["output"]["report_name"])

            loaded = MigrationConfig.from_file(path)
            self.assertEqual(loaded.output_dir, "résultats")
            self.assertEqual(loaded.template_vars["SERVEUR"], "hébergement")

            args = argparse.Namespace(output_dir="cli-override", verbose=True)
            from_file_and_args = load_config(path, args)
            self.assertEqual(from_file_and_args.output_dir, "cli-override")
            self.assertTrue(from_file_and_args.verbose)

            from_args = load_config(args=args)
            self.assertEqual(from_args.output_dir, "cli-override")
            self.assertEqual(load_config().to_dict(), MigrationConfig().to_dict())

    def test_missing_file_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "missing-config.json")
            with self.assertRaises(FileNotFoundError) as caught:
                MigrationConfig.from_file(missing)
            self.assertIn(os.path.abspath(missing), str(caught.exception))

    def test_malformed_json_raises_decode_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "bad.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"output":')
            with self.assertRaises(json.JSONDecodeError):
                MigrationConfig.from_file(path)


if __name__ == "__main__":
    unittest.main()
