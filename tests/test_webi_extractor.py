"""Tests for WebI extractor."""

import os
import tempfile
import unittest
import zipfile

from bo_export.webi_extractor import extract_webi, _safe_parse_xml


class TestSafeParseXml(unittest.TestCase):
    """Test XXE protection in XML parsing."""

    def test_valid_xml(self):
        result = _safe_parse_xml("<root><item name='test'/></root>")
        self.assertIsNotNone(result)

    def test_empty_string(self):
        result = _safe_parse_xml("")
        self.assertIsNone(result)

    def test_none(self):
        result = _safe_parse_xml(None)
        self.assertIsNone(result)

    def test_invalid_xml(self):
        result = _safe_parse_xml("not xml at all")
        self.assertIsNone(result)

    def test_xxe_blocked(self):
        xxe = '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><root/>'
        result = _safe_parse_xml(xxe)
        self.assertIsNone(result)


class TestWebiExtraction(unittest.TestCase):
    """Test Web Intelligence document extraction."""

    def test_extract_from_xml_content(self):
        """Test extraction from pre-parsed XML metadata."""
        metadata = {
            "document.xml": """<document>
                <dataprovider name="Query1" type="universe" universe="Sales">
                    <resultobject name="Revenue" qualification="measure"/>
                    <resultobject name="Country" qualification="dimension"/>
                </dataprovider>
                <variable name="Total" formula="=Sum([Revenue])" qualification="measure"/>
                <prompt name="SelectCountry" type="text" required="true"/>
                <chart name="Revenue Chart" type="bar"/>
            </document>"""
        }

        extracted = extract_webi("dummy.wid", artifact_data=metadata)

        self.assertIsInstance(extracted, dict)
        self.assertIn("queries", extracted)
        self.assertIn("formulas", extracted)
        self.assertIn("prompts", extracted)
        self.assertIn("charts", extracted)

    def test_extract_empty_metadata(self):
        """Test extraction with empty metadata."""
        extracted = extract_webi("dummy.wid", artifact_data={})
        # Should return structure with all keys
        self.assertEqual(len(extracted), 15)
        for key in extracted:
            self.assertIsInstance(extracted[key], list)

    def test_extract_from_zip(self):
        """Test extraction from a ZIP-based .wid file."""
        with tempfile.NamedTemporaryFile(suffix=".wid", delete=False) as f:
            wid_path = f.name

        try:
            with zipfile.ZipFile(wid_path, "w") as zf:
                zf.writestr("content.xml", """<report>
                    <variable name="Total Revenue" formula="=Sum([Revenue])" qualification="measure"/>
                    <table name="Sales"/>
                </report>""")

            extracted = extract_webi(wid_path)
            self.assertIsInstance(extracted, dict)
        finally:
            os.unlink(wid_path)


class TestWebiPathTraversal(unittest.TestCase):
    """Test ZIP entry path traversal protection."""

    def test_traversal_entries_skipped(self):
        with tempfile.NamedTemporaryFile(suffix=".wid", delete=False) as f:
            wid_path = f.name

        try:
            with zipfile.ZipFile(wid_path, "w") as zf:
                zf.writestr("../../../etc/passwd", b"malicious")
                zf.writestr("content.xml", "<report/>")

            # Should not raise, traversal entries silently skipped
            extracted = extract_webi(wid_path)
            self.assertIsInstance(extracted, dict)
        finally:
            os.unlink(wid_path)


if __name__ == "__main__":
    unittest.main()
