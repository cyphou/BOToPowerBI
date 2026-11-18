"""Tests for the main extraction orchestrator."""

import json
import os
import tempfile
import unittest
import zipfile

from bo_export.extract_bo_data import (
    EXTRACTED_TYPES,
    SUPPORTED_EXTENSIONS,
    _write_json_outputs,
    extract_bo_data,
    load_extracted_data,
)
from powerbi_import.security_validator import redact_connection_string


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

    def test_load_extracted_data_redacts_legacy_datasource_credentials(self):
        legacy_datasource = {
            "name": "Synthetic source",
            "username": "synthetic-user",
            "connectionString": (
                "Server=synthetic-server;Database=synthetic-database;"
                "UID=synthetic-user;PWD=synthetic-password"
            ),
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "datasources.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump([legacy_datasource], f)

            loaded = load_extracted_data(tmp)
            with open(path, "r", encoding="utf-8") as f:
                persisted = json.load(f)

        self.assertEqual(loaded["datasources"][0]["username"], "***REDACTED***")
        connection_string = loaded["datasources"][0]["connectionString"]
        self.assertIn("Server=synthetic-server", connection_string)
        self.assertNotIn("synthetic-user", connection_string)
        self.assertNotIn("synthetic-password", connection_string)
        self.assertEqual(persisted, [legacy_datasource])

    def test_write_json_outputs_redacts_sensitive_datasource_fields(self):
        secrets = {
            "username": "synthetic-user",
            "password": "synthetic-password",
            "access_token": "synthetic-access-token",
        }
        datasource = {
            **secrets,
            "name": "Synthetic source",
            "server": "synthetic-server",
            "custom_metadata": "preserve this metadata",
        }
        data = {t: [] for t in EXTRACTED_TYPES}
        data["datasources"] = [datasource]

        with tempfile.TemporaryDirectory() as tmp:
            _write_json_outputs(data, tmp)
            with open(os.path.join(tmp, "datasources.json"), "r", encoding="utf-8") as f:
                exported = json.load(f)

        self.assertEqual(exported[0]["custom_metadata"], "preserve this metadata")
        for field, secret in secrets.items():
            self.assertEqual(exported[0][field], "***REDACTED***")
            self.assertNotIn(secret, json.dumps(exported))

    def test_extract_unx_redacts_connection_credentials_in_return_and_json(self):
        connection_string = (
            "Provider=SQL;UID=synthetic-user;PWD=synthetic-password"
        )
        data_foundation = (
            '<DataFoundation><Connection name="Synthetic connection" '
            'type="SQL Server" server="synthetic-server" '
            'database="synthetic-database" '
            f'connectionString="{connection_string}"/></DataFoundation>'
        )

        with tempfile.TemporaryDirectory() as tmp:
            unx_path = os.path.join(tmp, "synthetic.unx")
            output_dir = os.path.join(tmp, "extracted")
            with zipfile.ZipFile(unx_path, "w") as archive:
                archive.writestr("DataFoundation.xml", data_foundation)

            extracted = extract_bo_data(unx_path, output_dir=output_dir)
            with open(os.path.join(output_dir, "datasources.json"), "r", encoding="utf-8") as f:
                persisted = json.load(f)

        self.assertEqual(len(extracted["datasources"]), 1)
        datasource = extracted["datasources"][0]
        self.assertEqual(datasource["server"], "synthetic-server")
        self.assertEqual(datasource["database"], "synthetic-database")
        self.assertEqual(datasource["type"], "SQL Server")
        for payload in (extracted["datasources"], persisted):
            serialized = json.dumps(payload)
            self.assertNotIn("synthetic-user", serialized)
            self.assertNotIn("synthetic-password", serialized)


class TestFileValidation(unittest.TestCase):
    """Test input file validation."""

    def test_extract_bo_data_rejects_archives_without_creating_empty_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            biar_path = os.path.join(tmp, "reports.biar")
            output_dir = os.path.join(tmp, "extracted")
            with zipfile.ZipFile(biar_path, "w") as archive:
                archive.writestr("reports/sales.wid", b"WebI artifact")

            with self.assertRaisesRegex(ValueError, "extract_from_biar"):
                extract_bo_data(biar_path, output_dir=output_dir)

            self.assertFalse(os.path.exists(output_dir))

    def test_unsupported_extension(self):
        from bo_export.extract_bo_data import extract_bo_data
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
        try:
            with self.assertRaises(ValueError):
                extract_bo_data(f.name)
        finally:
            os.unlink(f.name)

    def test_file_not_found(self):
        from bo_export.extract_bo_data import extract_bo_data
        with self.assertRaises(FileNotFoundError):
            extract_bo_data("/nonexistent/file.wid")


class TestConnectionStringRedaction(unittest.TestCase):
    """Test redaction of connection strings at the extraction boundary."""

    def test_redact_quoted_braced_and_jdbc_credentials(self):
        semicolon_string = (
            'Server=synthetic-server;Database=synthetic-database;'
            'UID="synthetic-user";PWD={synthetic;password}'
        )
        jdbc_uri = (
            "jdbc:postgresql://synthetic-user:synthetic-password@"
            "synthetic-server:5432/synthetic-database"
            "?sslmode=require&access_token=synthetic-token"
        )

        redacted_semicolon = redact_connection_string(semicolon_string)
        redacted_jdbc = redact_connection_string(jdbc_uri)

        for secret in (
            "synthetic-user",
            "synthetic;password",
            "synthetic-password",
            "synthetic-token",
        ):
            self.assertNotIn(secret, redacted_semicolon + redacted_jdbc)
        for safe_component in (
            "synthetic-server",
            "synthetic-database",
        ):
            self.assertIn(safe_component, redacted_semicolon)
            self.assertIn(safe_component, redacted_jdbc)
        self.assertIn("sslmode=require", redacted_jdbc)


if __name__ == "__main__":
    unittest.main()
