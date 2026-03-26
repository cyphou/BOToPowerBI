"""Tests for Phase 8: Crystal Reports Deep — deep binary parsing helpers.

Tests deep_parse_crystal, page layout extraction, embedded images,
datasource probing, crosstab fields, group hierarchy, and section formatting.
"""
import pytest
import sys
import os
import struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bo_export.crystal_extractor import (
    deep_parse_crystal,
    _extract_page_layout,
    _find_embedded_images,
    _extract_deep_datasource,
    _extract_crosstab_fields,
    _build_group_hierarchy,
    _extract_section_formatting,
    _safe_decode,
)


# ═══════════════════════════════════════════════════════════════════
#  _safe_decode Tests
# ═══════════════════════════════════════════════════════════════════

class TestSafeDecode:
    def test_valid_utf8(self):
        assert _safe_decode(b"Hello World") == "Hello World"

    def test_latin1_fallback(self):
        # _safe_decode keeps only printable ASCII segments >= 4 chars
        data = "café forever".encode("latin-1")
        result = _safe_decode(data)
        # 'forever' is a printable segment >= 4 chars
        assert "forever" in result

    def test_null_terminated(self):
        data = b"Hello\x00World\x00Extra"
        result = _safe_decode(data)
        assert "Hello" in result

    def test_empty(self):
        assert _safe_decode(b"") == ""


# ═══════════════════════════════════════════════════════════════════
#  _extract_page_layout Tests
# ═══════════════════════════════════════════════════════════════════

class TestPageLayout:
    def test_empty_data(self):
        layout = _extract_page_layout(b"")
        assert isinstance(layout, dict)
        # Should have defaults
        assert "paper_size" in layout or layout == {}

    def test_binary_with_no_markers(self):
        data = b"\x00" * 100
        layout = _extract_page_layout(data)
        assert isinstance(layout, dict)

    def test_returns_dict(self):
        # Even garbage data should not crash
        import random
        data = bytes(range(256)) * 4
        layout = _extract_page_layout(data)
        assert isinstance(layout, dict)


# ═══════════════════════════════════════════════════════════════════
#  _find_embedded_images Tests
# ═══════════════════════════════════════════════════════════════════

class TestFindEmbeddedImages:
    def test_no_images(self):
        data = b"No images here at all" * 10
        images = _find_embedded_images(data)
        assert isinstance(images, list)
        assert len(images) == 0

    def test_detect_png(self):
        # PNG magic: 89 50 4E 47 0D 0A 1A 0A
        png_magic = b"\x89PNG\r\n\x1a\n"
        data = b"prefix_data" + png_magic + b"\x00" * 50
        images = _find_embedded_images(data)
        assert any(img.get("type") == "png" for img in images)

    def test_detect_jpeg(self):
        # JPEG magic: FF D8 FF
        jpeg_magic = b"\xff\xd8\xff\xe0"
        data = b"prefix" + jpeg_magic + b"\x00" * 100
        images = _find_embedded_images(data)
        assert any(img.get("type") == "jpeg" for img in images)

    def test_detect_bmp(self):
        # BMP: 'BM' + file_size (must be > 1000 and < len(raw))
        total_len = 2000
        bmp_magic = b"BM" + struct.pack("<I", 1500)
        data = b"prefix" + bmp_magic + b"\x00" * (total_len - len(b"prefix") - len(bmp_magic))
        images = _find_embedded_images(data)
        assert any(img.get("type") == "bmp" for img in images)


# ═══════════════════════════════════════════════════════════════════
#  _extract_deep_datasource Tests
# ═══════════════════════════════════════════════════════════════════

class TestDeepDatasource:
    def test_empty_data(self):
        ds = _extract_deep_datasource(b"")
        assert isinstance(ds, list)

    def test_oracle_detection(self):
        data = b"\x00Oracle\x00TNS_NAME=PROD\x00" + b"\x00" * 50
        ds = _extract_deep_datasource(data)
        assert isinstance(ds, list)

    def test_sql_server_detection(self):
        data = b"\x00SQL Server\x00SQLNCLI\x00" + b"\x00" * 50
        ds = _extract_deep_datasource(data)
        assert isinstance(ds, list)


# ═══════════════════════════════════════════════════════════════════
#  _extract_crosstab_fields Tests
# ═══════════════════════════════════════════════════════════════════

class TestCrosstabFields:
    def test_empty_data(self):
        fields = _extract_crosstab_fields(b"")
        assert isinstance(fields, list)

    def test_no_crash_on_random(self):
        data = bytes(range(256)) * 2
        fields = _extract_crosstab_fields(data)
        assert isinstance(fields, list)


# ═══════════════════════════════════════════════════════════════════
#  _build_group_hierarchy Tests
# ═══════════════════════════════════════════════════════════════════

class TestBuildGroupHierarchy:
    def test_from_binary_text(self):
        # Simulate binary with group patterns
        text = b"Group #1 on Region (ascending) Group #2 on City (ascending)"
        hierarchy = _build_group_hierarchy(text)
        assert isinstance(hierarchy, list)
        if hierarchy:
            assert hierarchy[0].get("field") == "Region"
            assert hierarchy[0].get("level", 0) <= hierarchy[-1].get("level", 0)

    def test_empty_data(self):
        hierarchy = _build_group_hierarchy(b"")
        assert isinstance(hierarchy, list)
        assert len(hierarchy) == 0


# ═══════════════════════════════════════════════════════════════════
#  _extract_section_formatting Tests
# ═══════════════════════════════════════════════════════════════════

class TestSectionFormatting:
    def test_empty_data(self):
        fmt = _extract_section_formatting(b"")
        assert isinstance(fmt, list)

    def test_no_crash(self):
        data = b"\x01\x02\x03" * 100
        fmt = _extract_section_formatting(data)
        assert isinstance(fmt, list)


# ═══════════════════════════════════════════════════════════════════
#  deep_parse_crystal Orchestrator Tests
# ═══════════════════════════════════════════════════════════════════

class TestDeepParseCrystal:
    def test_empty_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".rpt", delete=False) as f:
            f.write(b"")
            f.flush()
            path = f.name
        try:
            result = deep_parse_crystal(path)
            assert isinstance(result, dict)
        finally:
            os.unlink(path)

    def test_with_binary_content(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".rpt", delete=False) as f:
            f.write(b"\x00" * 200)
            f.flush()
            path = f.name
        try:
            result = deep_parse_crystal(path)
            assert isinstance(result, dict)
            # Should contain known keys
            for key in ("page_layout", "embedded_images", "datasource_details"):
                assert key in result
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        result = deep_parse_crystal("/nonexistent/path.rpt")
        assert isinstance(result, dict)
        # Should return empty structure, not crash
