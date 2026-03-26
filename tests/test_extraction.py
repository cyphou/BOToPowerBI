"""Tests for the main extraction orchestrator."""

import json
import os
import tempfile
import unittest

from bo_export.extract_bo_data import (
    EXTRACTED_TYPES,
    SUPPORTED_EXTENSIONS,
    _write_json_outputs,
    load_extracted_data,
)


class TestExtractedTypes(unittest.TestCase):
    """Test extraction type definitions."""

    def test_15_extracted_types(self):
        self.assertEqual(len(EXTRACTED_TYPES), 15)

    def test_required_types_present(self):
        required = ["reports", "queries", "datasources", "formulas", "prompts",
                     "filters", "tables", "columns", "joins", "groups",
                     "sorts", "alerts", "subreports", "charts", "custom_sql"]
        for t in required:
            self.assertIn(t, EXTRACTED_TYPES)

    def test_supported_extensions(self):
        self.assertIn(".wid", SUPPORTED_EXTENSIONS)
        self.assertIn(".rpt", SUPPORTED_EXTENSIONS)
        self.assertIn(".unx", SUPPORTED_EXTENSIONS)
        self.assertIn(".unv", SUPPORTED_EXTENSIONS)
        self.assertIn(".biar", SUPPORTED_EXTENSIONS)
        self.assertIn(".lumx", SUPPORTED_EXTENSIONS)
        self.assertIn(".lums", SUPPORTED_EXTENSIONS)


class TestJsonOutputs(unittest.TestCase):
    """Test JSON file writing."""

    def test_write_json_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {t: [] for t in EXTRACTED_TYPES}
            data["reports"] = [{"name": "Test Report"}]
            _write_json_outputs(data, tmp)

            for t in EXTRACTED_TYPES:
                path = os.path.join(tmp, f"{t}.json")
                self.assertTrue(os.path.isfile(path), f"Missing {t}.json")

            # Verify content
            with open(os.path.join(tmp, "reports.json"), "r") as f:
                reports = json.load(f)
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["name"], "Test Report")

    def test_load_extracted_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Write sample data
            data = {t: [] for t in EXTRACTED_TYPES}
            data["formulas"] = [{"name": "F1", "formula": "=Sum([X])"}]
            _write_json_outputs(data, tmp)

            # Load back
            loaded = load_extracted_data(tmp)
            self.assertEqual(len(loaded["formulas"]), 1)
            self.assertEqual(loaded["formulas"][0]["name"], "F1")

    def test_load_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load_extracted_data(tmp)
            for t in EXTRACTED_TYPES:
                self.assertEqual(loaded[t], [])


class TestFileValidation(unittest.TestCase):
    """Test input file validation."""

    def test_unsupported_extension(self):
        from bo_export.extract_bo_data import extract_bo_data
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
            f.flush()
            try:
                with self.assertRaises(ValueError):
                    extract_bo_data(f.name)
            finally:
                os.unlink(f.name)

    def test_file_not_found(self):
        from bo_export.extract_bo_data import extract_bo_data
        with self.assertRaises(FileNotFoundError):
            extract_bo_data("/nonexistent/file.wid")


if __name__ == "__main__":
    unittest.main()
