"""Layout Engine — preserve BO spatial layouts in Power BI canvas.

Maps BO report tab/section coordinates (free-form placement) to Power BI
visual container positions, preserving relative sizing and alignment.

Usage:
    from powerbi_import.layout_engine import LayoutEngine
    engine = LayoutEngine(canvas_width=1280, canvas_height=720)
    positions = engine.compute_layout(extracted_data)
"""

import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)

# Power BI canvas default dimensions
PBI_CANVAS_WIDTH = 1280
PBI_CANVAS_HEIGHT = 720

# Minimum visual sizes
MIN_VISUAL_WIDTH = 100
MIN_VISUAL_HEIGHT = 60

# Grid alignment snap (pixels)
GRID_SNAP = 8


class LayoutEngine:
    """Compute Power BI visual positions from BO report coordinates."""

    def __init__(self, canvas_width=PBI_CANVAS_WIDTH, canvas_height=PBI_CANVAS_HEIGHT):
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height

    def compute_layout(self, extracted_data):
        """Compute visual positions for all reports/tabs.

        Args:
            extracted_data: dict containing reports, charts, etc.

        Returns:
            list of dicts: [{
                "page": str,
                "visuals": [{
                    "name": str,
                    "type": str,
                    "x": int, "y": int,
                    "width": int, "height": int,
                }]
            }]
        """
        reports = extracted_data.get("reports", [])
        charts = extracted_data.get("charts", [])

        if not reports and not charts:
            return []

        pages = []

        # Group charts by their report/tab
        charts_by_tab = defaultdict(list)
        for chart in charts:
            tab = chart.get("tab", chart.get("report", "Page 1"))
            charts_by_tab[tab].append(chart)

        for report in reports or [{"name": "Page 1"}]:
            tab_name = report.get("name", "Page 1")
            tab_charts = charts_by_tab.get(tab_name, [])

            if not tab_charts:
                # Check if there are charts without tab assignment
                if not pages and charts_by_tab.get("Page 1"):
                    tab_charts = charts_by_tab["Page 1"]
                elif not pages and charts:
                    tab_charts = charts
                else:
                    continue

            visuals = self._position_visuals(tab_charts, report)
            pages.append({"page": tab_name, "visuals": visuals})

        return pages

    def _position_visuals(self, charts, report):
        """Position visuals on a single page.

        If BO provides explicit coordinates, scale them to canvas.
        Otherwise, use auto-grid layout.
        """
        has_coords = any(
            chart.get("x") is not None or chart.get("left") is not None
            for chart in charts
        )

        if has_coords:
            return self._scale_from_bo_coords(charts, report)
        else:
            return self._auto_grid_layout(charts)

    def _scale_from_bo_coords(self, charts, report):
        """Scale BO absolute coordinates to PBI canvas coordinates."""
        # Determine BO canvas bounds from report or from the data
        bo_width = report.get("width") or report.get("page_width") or 11906  # ~A4 at 96dpi
        bo_height = report.get("height") or report.get("page_height") or 16838

        # Get actual bounds from chart positions to normalize
        xs = []
        ys = []
        for chart in charts:
            x = chart.get("x") or chart.get("left") or 0
            y = chart.get("y") or chart.get("top") or 0
            w = chart.get("width", 200)
            h = chart.get("height", 150)
            xs.append(x)
            xs.append(x + w)
            ys.append(y)
            ys.append(y + h)

        if not xs:
            return self._auto_grid_layout(charts)

        # Use the larger of declared page size or actual content bounds
        content_right = max(xs)
        content_bottom = max(ys)
        source_width = max(bo_width, content_right, 1)
        source_height = max(bo_height, content_bottom, 1)

        scale_x = self.canvas_width / source_width
        scale_y = self.canvas_height / source_height

        visuals = []
        for chart in charts:
            x = (chart.get("x") or chart.get("left") or 0) * scale_x
            y = (chart.get("y") or chart.get("top") or 0) * scale_y
            w = (chart.get("width", 200)) * scale_x
            h = (chart.get("height", 150)) * scale_y

            # Enforce minimums and snap to grid
            w = max(w, MIN_VISUAL_WIDTH)
            h = max(h, MIN_VISUAL_HEIGHT)
            x = self._snap(x)
            y = self._snap(y)
            w = self._snap(w)
            h = self._snap(h)

            # Clamp to canvas
            x = min(x, self.canvas_width - MIN_VISUAL_WIDTH)
            y = min(y, self.canvas_height - MIN_VISUAL_HEIGHT)

            visuals.append({
                "name": chart.get("name", f"Visual_{len(visuals)}"),
                "type": chart.get("type", "table"),
                "x": int(x), "y": int(y),
                "width": int(w), "height": int(h),
            })

        return visuals

    def _auto_grid_layout(self, charts):
        """Auto-arrange visuals in a responsive grid.

        Uses a simple grid algorithm:
        - 1 visual  → full width
        - 2 visuals → side by side
        - 3 visuals → 2+1 or 3 across
        - 4+ visuals → 2-column grid
        """
        n = len(charts)
        if n == 0:
            return []

        margin = 16
        usable_w = self.canvas_width - margin * 2
        usable_h = self.canvas_height - margin * 2

        if n == 1:
            cols, rows = 1, 1
        elif n == 2:
            cols, rows = 2, 1
        elif n <= 4:
            cols, rows = 2, 2
        elif n <= 6:
            cols, rows = 3, 2
        elif n <= 9:
            cols, rows = 3, 3
        else:
            cols = min(4, math.ceil(math.sqrt(n)))
            rows = math.ceil(n / cols)

        cell_w = usable_w // cols
        cell_h = usable_h // rows
        gap = 8

        visuals = []
        for i, chart in enumerate(charts):
            col = i % cols
            row = i // cols
            x = margin + col * cell_w + gap
            y = margin + row * cell_h + gap
            w = cell_w - gap * 2
            h = cell_h - gap * 2

            visuals.append({
                "name": chart.get("name", f"Visual_{i}"),
                "type": chart.get("type", "table"),
                "x": self._snap(x), "y": self._snap(y),
                "width": max(self._snap(w), MIN_VISUAL_WIDTH),
                "height": max(self._snap(h), MIN_VISUAL_HEIGHT),
            })

        return visuals

    def _snap(self, value):
        """Snap value to grid."""
        return round(value / GRID_SNAP) * GRID_SNAP


def compute_page_sizes(extracted_data):
    """Determine page sizes for all tabs.

    Returns:
        list of dicts: [{"page": str, "width": int, "height": int, "type": "16:9"|"4:3"|"custom"}]
    """
    reports = extracted_data.get("reports", [])
    result = []

    for report in reports:
        w = report.get("width") or report.get("page_width")
        h = report.get("height") or report.get("page_height")

        if w and h:
            ratio = w / max(h, 1)
            if abs(ratio - 16 / 9) < 0.1:
                page_type = "16:9"
            elif abs(ratio - 4 / 3) < 0.1:
                page_type = "4:3"
            elif ratio > 1.8:
                page_type = "letter_landscape"
            else:
                page_type = "custom"
        else:
            w = PBI_CANVAS_WIDTH
            h = PBI_CANVAS_HEIGHT
            page_type = "16:9"

        result.append({
            "page": report.get("name", "Page 1"),
            "width": w, "height": h,
            "type": page_type,
        })

    return result or [{"page": "Page 1", "width": PBI_CANVAS_WIDTH,
                       "height": PBI_CANVAS_HEIGHT, "type": "16:9"}]
