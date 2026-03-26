"""Tests for Phase 11: Advanced Visual Fidelity.

Tests theme generation, layout engine, bookmark generation,
and fidelity scoring.
"""
import pytest
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from powerbi_import.theme_generator import (
    generate_theme,
    write_theme_file,
    _normalize_color,
    _map_font,
)
from powerbi_import.layout_engine import (
    LayoutEngine,
    compute_page_sizes,
)
from powerbi_import.bookmark_generator import (
    generate_bookmarks,
    generate_bookmark_buttons,
    generate_drillthrough_bookmarks,
)
from powerbi_import.fidelity_scorer import (
    score_fidelity,
    compare_color_palettes,
    compare_layouts,
)


# ═══════════════════════════════════════════════════════════════════
#  Theme Generator Tests
# ═══════════════════════════════════════════════════════════════════

class TestNormalizeColor:
    def test_hex_passthrough(self):
        assert _normalize_color("#FF0000") == "#FF0000"

    def test_named_color(self):
        assert _normalize_color("red") == "#FF0000"
        assert _normalize_color("Blue") == "#0000FF"

    def test_rgb_format(self):
        assert _normalize_color("rgb(255, 128, 0)") == "#FF8000"

    def test_integer_color(self):
        # BGR integer encoding
        result = _normalize_color("255")  # pure red (R=255, G=0, B=0)
        assert result == "#FF0000"

    def test_none_input(self):
        assert _normalize_color(None) is None
        assert _normalize_color("") is None


class TestMapFont:
    def test_known_fonts(self):
        assert _map_font("Arial") == "Arial"
        assert _map_font("Helvetica") == "Segoe UI"
        assert _map_font("Verdana") == "Segoe UI"

    def test_unknown_font(self):
        assert _map_font("CustomFont") == "CustomFont"

    def test_none(self):
        assert _map_font(None) == "Segoe UI"


class TestGenerateTheme:
    def test_basic_theme(self):
        data = {
            "reports": [{"name": "Sales Report"}],
            "charts": [],
            "alerts": [],
        }
        theme = generate_theme(data)
        assert theme["name"] == "Sales Report Theme"
        assert "dataColors" in theme
        assert len(theme["dataColors"]) > 0
        assert "background" in theme
        assert "foreground" in theme

    def test_custom_name(self):
        theme = generate_theme({"reports": [], "charts": [], "alerts": []},
                               theme_name="My Theme")
        assert theme["name"] == "My Theme"

    def test_colors_from_charts(self):
        data = {
            "reports": [],
            "charts": [
                {"color": "#AA0000"},
                {"color": "#00BB00"},
            ],
            "alerts": [],
        }
        theme = generate_theme(data)
        colors = theme["dataColors"]
        assert "#AA0000" in colors or "#00BB00" in colors

    def test_has_visual_styles(self):
        theme = generate_theme({"reports": [], "charts": [], "alerts": []})
        assert "visualStyles" in theme
        assert "textClasses" in theme

    def test_write_theme_file(self):
        theme = generate_theme({"reports": [], "charts": [], "alerts": []})
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode='w') as f:
            path = f.name
        try:
            write_theme_file(theme, path)
            with open(path, 'r') as f:
                loaded = json.load(f)
            assert loaded["name"] == theme["name"]
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════════
#  Layout Engine Tests
# ═══════════════════════════════════════════════════════════════════

class TestLayoutEngine:
    def test_auto_grid_single(self):
        engine = LayoutEngine()
        data = {
            "reports": [{"name": "Page 1"}],
            "charts": [{"name": "Chart1", "type": "bar"}],
        }
        pages = engine.compute_layout(data)
        assert len(pages) >= 1
        assert len(pages[0]["visuals"]) == 1

    def test_auto_grid_multiple(self):
        engine = LayoutEngine()
        data = {
            "reports": [{"name": "Page 1"}],
            "charts": [
                {"name": f"Chart{i}", "type": "bar"} for i in range(4)
            ],
        }
        pages = engine.compute_layout(data)
        assert len(pages[0]["visuals"]) == 4
        # Verify no overlapping
        positions = [(v["x"], v["y"]) for v in pages[0]["visuals"]]
        assert len(set(positions)) == 4  # All unique positions

    def test_bo_coordinate_scaling(self):
        engine = LayoutEngine(canvas_width=1280, canvas_height=720)
        data = {
            "reports": [{"name": "P1", "width": 2560, "height": 1440}],
            "charts": [
                {"name": "C1", "type": "bar", "x": 0, "y": 0, "width": 1280, "height": 720},
                {"name": "C2", "type": "line", "x": 1280, "y": 0, "width": 1280, "height": 720},
            ],
        }
        pages = engine.compute_layout(data)
        visuals = pages[0]["visuals"]
        # C1 should be in top-left half, C2 in top-right half
        assert visuals[0]["x"] < visuals[1]["x"]

    def test_empty_data(self):
        engine = LayoutEngine()
        pages = engine.compute_layout({"reports": [], "charts": []})
        assert pages == []

    def test_grid_snap(self):
        engine = LayoutEngine()
        val = engine._snap(17)
        assert val % 8 == 0  # Should snap to 8-pixel grid


class TestComputePageSizes:
    def test_default_16_9(self):
        result = compute_page_sizes({"reports": []})
        assert result[0]["type"] == "16:9"
        assert result[0]["width"] == 1280

    def test_custom_size(self):
        result = compute_page_sizes({"reports": [
            {"name": "Wide", "width": 2000, "height": 500}
        ]})
        assert result[0]["type"] in ("letter_landscape", "custom")


# ═══════════════════════════════════════════════════════════════════
#  Bookmark Generator Tests
# ═══════════════════════════════════════════════════════════════════

class TestBookmarks:
    def test_tab_bookmarks(self):
        data = {
            "reports": [
                {"name": "Overview"},
                {"name": "Detail"},
                {"name": "Trend"},
            ],
            "charts": [],
            "prompts": [],
            "subreports": [],
        }
        result = generate_bookmarks(data)
        assert len(result["bookmarks"]) == 3
        assert len(result["bookmark_bar"]) == 3
        assert result["bookmark_bar"][0]["name"] == "Overview"

    def test_reset_filters_bookmark(self):
        data = {
            "reports": [],
            "charts": [],
            "prompts": [{"name": "Region", "type": "text"}],
            "subreports": [],
        }
        result = generate_bookmarks(data)
        reset = [b for b in result["bookmarks"] if "Reset" in b["displayName"]]
        assert len(reset) == 1

    def test_empty_reports(self):
        result = generate_bookmarks({"reports": [], "charts": [], "prompts": [], "subreports": []})
        assert result["bookmarks"] == []

    def test_bookmark_buttons(self):
        bk_result = {
            "bookmarks": [{"name": "Bookmark_Overview", "displayName": "Overview"}],
            "bookmark_bar": [{"name": "Overview", "target_bookmark": "Bookmark_Overview", "order": 0}],
        }
        buttons = generate_bookmark_buttons(bk_result)
        assert len(buttons) == 1
        assert buttons[0]["type"] == "actionButton"
        assert buttons[0]["config"]["action"]["type"] == "Bookmark"


class TestDrillthroughBookmarks:
    def test_generates_from_subreports(self):
        data = {
            "subreports": [
                {"name": "OrderDetail", "target_report": "OrderReport",
                 "parameters": {"CustomerID": {"table": "Orders", "column": "CustID"}}},
            ],
        }
        result = generate_drillthrough_bookmarks(data)
        assert len(result) == 1
        assert "Drillthrough_" in result[0]["page_name"]
        assert len(result[0]["drillthrough_filters"]) == 1

    def test_no_subreports(self):
        result = generate_drillthrough_bookmarks({"subreports": []})
        assert result == []


# ═══════════════════════════════════════════════════════════════════
#  Fidelity Scorer Tests
# ═══════════════════════════════════════════════════════════════════

class TestFidelityScorer:
    def test_perfect_fidelity(self):
        data = {
            "tables": [{"name": "T1"}],
            "columns": [{"name": "C1", "table": "T1"}],
            "joins": [],
            "formulas": [{"name": "M1", "dax": "SUM([C1])", "converted": True}],
            "charts": [{"name": "V1", "type": "bar"}],
            "filters": [],
            "prompts": [],
            "subreports": [],
            "reports": [{"name": "Page 1"}],
        }
        result = score_fidelity(data)
        assert result["overall"] >= 70
        assert result["grade"] in ("A", "B", "C")

    def test_low_fidelity_no_dax(self):
        data = {
            "tables": [],
            "columns": [],
            "joins": [],
            "formulas": [{"name": "M1", "formula": "SUM(X)"}],  # No dax key
            "charts": [{"name": "V1", "type": "unknown_exotic_type"}],
            "filters": [],
            "prompts": [],
            "subreports": [],
            "reports": [],
        }
        result = score_fidelity(data)
        assert result["overall"] < 80

    def test_with_generated_stats(self):
        data = {
            "tables": [{"name": "T1"}, {"name": "T2"}],
            "columns": [{"name": "C1"}, {"name": "C2"}],
            "joins": [{"left_table": "T1", "right_table": "T2"}],
            "formulas": [],
            "charts": [],
            "filters": [],
            "prompts": [],
            "subreports": [],
            "reports": [],
        }
        gen_stats = {"tables": 2, "columns": 2, "relationships": 1}
        result = score_fidelity(data, gen_stats)
        assert result["categories"]["data_model"] == 100.0

    def test_has_details(self):
        data = {"tables": [], "columns": [], "joins": [], "formulas": [],
                "charts": [], "filters": [], "prompts": [], "subreports": [], "reports": []}
        result = score_fidelity(data)
        assert len(result["details"]) > 0


class TestColorPaletteComparison:
    def test_identical_palettes(self):
        colors = ["#FF0000", "#00FF00", "#0000FF"]
        assert compare_color_palettes(colors, colors) == 100.0

    def test_different_palettes(self):
        src = ["#000000"]
        tgt = ["#FFFFFF"]
        score = compare_color_palettes(src, tgt)
        assert score < 50

    def test_empty_palettes(self):
        assert compare_color_palettes([], []) == 100.0
        assert compare_color_palettes(["#FF0000"], []) == 0.0


class TestLayoutComparison:
    def test_identical_layouts(self):
        layout = [{"name": "V1", "x": 10, "y": 10, "width": 200, "height": 100}]
        assert compare_layouts(layout, layout) == 100.0

    def test_empty_layouts(self):
        assert compare_layouts([], []) == 100.0
        assert compare_layouts([{"name": "V1", "x": 0, "y": 0}], []) == 0.0

    def test_shifted_layout(self):
        src = [{"name": "V1", "x": 10, "y": 10, "width": 200, "height": 100}]
        tgt = [{"name": "V1", "x": 50, "y": 50, "width": 200, "height": 100}]
        score = compare_layouts(src, tgt)
        assert 0 < score < 100
