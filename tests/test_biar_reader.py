"""Tests for the BIAR archive reader."""

import os
import tempfile
import unittest
import zipfile

from bo_export.biar_reader import read_biar_archive, _classify_artifact


class TestClassifyArtifact(unittest.TestCase):
    """Test artifact type classification."""

    def test_webi(self):
        self.assertEqual(_classify_artifact("reports/sales.wid"), "webi")

    def test_crystal(self):
        self.assertEqual(_classify_artifact("reports/sales.rpt"), "crystal")

    def test_universe_unx(self):
        self.assertEqual(_classify_artifact("universes/sales.unx"), "universe")

    def test_universe_unv(self):
        self.assertEqual(_classify_artifact("universes/sales.unv"), "universe")

    def test_lumira(self):
        self.assertEqual(_classify_artifact("lumira/dashboard.lumx"), "lumira")

    def test_unknown(self):
        self.assertIsNone(_classify_artifact("metadata.xml"))

    def test_json_files_ignored(self):
        self.assertIsNone(_classify_artifact("config.json"))


class TestReadBiarArchive(unittest.TestCase):
    """Test BIAR archive reading."""

    def test_read_biar_with_artifacts(self):
        with tempfile.NamedTemporaryFile(suffix=".biar", delete=False) as f:
            biar_path = f.name

        try:
            with zipfile.ZipFile(biar_path, "w") as zf:
                zf.writestr("reports/sales.wid", b"dummy webi content")
                zf.writestr("reports/inventory.rpt", b"dummy crystal content")
                zf.writestr("universes/sales.unx", b"dummy universe content")
                zf.writestr("metadata.xml", b"<manifest/>")

            artifacts = read_biar_archive(biar_path)
            self.assertEqual(len(artifacts), 3)

            types = {a["type"] for a in artifacts}
            self.assertIn("webi", types)
            self.assertIn("crystal", types)
            self.assertIn("universe", types)
        finally:
            os.unlink(biar_path)

    def test_read_empty_biar(self):
        with tempfile.NamedTemporaryFile(suffix=".biar", delete=False) as f:
            biar_path = f.name

        try:
            with zipfile.ZipFile(biar_path, "w") as zf:
                zf.writestr("metadata.xml", b"<manifest/>")

            artifacts = read_biar_archive(biar_path)
            self.assertEqual(len(artifacts), 0)
        finally:
            os.unlink(biar_path)

    def test_path_traversal_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".biar", delete=False) as f:
            biar_path = f.name

        try:
            with zipfile.ZipFile(biar_path, "w") as zf:
                zf.writestr("../../../etc/passwd.wid", b"malicious")
                zf.writestr("reports/valid.wid", b"valid content")

            artifacts = read_biar_archive(biar_path)
            # Only valid entry should be returned
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(artifacts[0]["name"], "valid")
        finally:
            os.unlink(biar_path)

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            read_biar_archive("/nonexistent/archive.biar")

    def test_invalid_zip(self):
        with tempfile.NamedTemporaryFile(suffix=".biar", delete=False) as f:
            f.write(b"not a zip file")
            f.flush()
            biar_path = f.name

        try:
            with self.assertRaises(ValueError):
                read_biar_archive(biar_path)
        finally:
            os.unlink(biar_path)


if __name__ == "__main__":
    unittest.main()
