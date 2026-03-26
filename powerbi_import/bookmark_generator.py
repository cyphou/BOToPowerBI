"""Bookmark Generator — BO navigation → Power BI bookmarks + button navigation.

Converts BO document tabs, hyperlinks, OpenDocument links, and report-level
navigation into PBI bookmarks with navigator buttons.

Usage:
    from powerbi_import.bookmark_generator import generate_bookmarks
    bookmarks = generate_bookmarks(extracted_data)
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def generate_bookmarks(extracted_data):
    """Generate Power BI bookmark definitions from BO navigation.

    Sources:
    - Report tabs → page bookmarks
    - BO navigation links → cross-report bookmarks
    - OpenDocument URLs → drillthrough bookmarks
    - Input controls → slicer state bookmarks

    Returns:
        dict: {
            "bookmarks": [{"name": ..., "displayName": ..., "explorationState": {...}}],
            "bookmark_bar": [{"name": ..., "target_bookmark": ...}],
        }
    """
    bookmarks = []
    bookmark_bar = []

    # 1. Tab-based bookmarks (each BO tab → a PBI page bookmark)
    reports = extracted_data.get("reports", [])
    for i, report in enumerate(reports):
        tab_name = report.get("name", f"Tab {i + 1}")
        bookmark_id = _make_bookmark_id(tab_name)

        bookmarks.append({
            "name": bookmark_id,
            "displayName": tab_name,
            "explorationState": {
                "activeSection": _sanitize_section_name(tab_name),
            },
            "options": {
                "currentPage": True,
                "allVisuals": False,
                "dataPoint": False,
            },
        })

        bookmark_bar.append({
            "name": tab_name,
            "target_bookmark": bookmark_id,
            "order": i,
        })

    # 2. Navigation links from charts/elements
    for chart in extracted_data.get("charts", []):
        nav_links = chart.get("navigation_links", []) or []
        if isinstance(nav_links, str):
            nav_links = [nav_links]

        for link in nav_links:
            target = _parse_navigation_target(link, reports)
            if target:
                bk_name = f"Nav_{chart.get('name', '')}_{target}"
                bookmarks.append({
                    "name": _make_bookmark_id(bk_name),
                    "displayName": f"Navigate to {target}",
                    "explorationState": {
                        "activeSection": _sanitize_section_name(target),
                    },
                    "options": {
                        "currentPage": True,
                        "allVisuals": False,
                        "dataPoint": False,
                    },
                })

    # 3. Prompt/filter state bookmarks
    prompts = extracted_data.get("prompts", [])
    if prompts:
        # Create a "Reset Filters" bookmark
        bookmarks.append({
            "name": "Bookmark_ResetFilters",
            "displayName": "Reset All Filters",
            "explorationState": {
                "filters": {"type": "Reset"},
            },
            "options": {
                "currentPage": False,
                "allVisuals": True,
                "dataPoint": False,
                "display": True,
            },
        })

    logger.info("Generated %d bookmarks, %d bar items",
                len(bookmarks), len(bookmark_bar))
    return {
        "bookmarks": bookmarks,
        "bookmark_bar": bookmark_bar,
    }


def generate_bookmark_buttons(bookmarks_result, page_name="Page 1"):
    """Generate PBIR visual configs for bookmark navigation buttons.

    Args:
        bookmarks_result: output from generate_bookmarks()
        page_name: PBI page to place the navigation bar on

    Returns:
        list of visual config dicts suitable for PBIR visual containers
    """
    buttons = []
    bar_items = bookmarks_result.get("bookmark_bar", [])

    if not bar_items:
        return []

    # Position buttons horizontally at the top
    x_start = 16
    y = 8
    btn_width = 120
    btn_height = 32
    gap = 8

    for i, item in enumerate(bar_items):
        buttons.append({
            "name": f"BookmarkBtn_{i}",
            "type": "actionButton",
            "x": x_start + i * (btn_width + gap),
            "y": y,
            "width": btn_width,
            "height": btn_height,
            "config": {
                "buttonStyle": {
                    "text": item["name"],
                    "icon": "Bookmark",
                    "outline": "None",
                },
                "action": {
                    "type": "Bookmark",
                    "bookmark": item["target_bookmark"],
                },
            },
        })

    return buttons


def generate_drillthrough_bookmarks(extracted_data):
    """Generate drillthrough page bookmarks from BO subreport links.

    Maps BO subreport calls to PBI drillthrough page definitions.

    Returns:
        list of drillthrough configs
    """
    subreports = extracted_data.get("subreports", [])
    drillthroughs = []

    for sub in subreports:
        target = sub.get("target_report") or sub.get("subreport_name", "")
        params = sub.get("parameters", {})

        if not target:
            continue

        # Map BO parameters to PBI drillthrough filters
        filters = []
        for pname, pval in params.items():
            if isinstance(pval, dict):
                filters.append({
                    "table": pval.get("table", ""),
                    "column": pval.get("column", pname),
                    "type": "column",
                })
            else:
                filters.append({"column": pname, "type": "column"})

        drillthroughs.append({
            "page_name": f"Drillthrough_{_sanitize_section_name(target)}",
            "display_name": f"Detail: {target}",
            "drillthrough_filters": filters,
            "source_subreport": sub.get("name", target),
        })

    logger.info("Generated %d drillthrough configs", len(drillthroughs))
    return drillthroughs


def _make_bookmark_id(name):
    """Create a safe bookmark ID."""
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    return f"Bookmark_{safe[:50]}"


def _sanitize_section_name(name):
    """Create PBI section name from tab name."""
    return re.sub(r'[^a-zA-Z0-9 _-]', '', name).strip()


def _parse_navigation_target(link, reports):
    """Parse a BO navigation link to find the target tab/report."""
    if not link:
        return None

    # OpenDocument URL format
    m = re.search(r'sDocName=([^&]+)', link)
    if m:
        return m.group(1)

    # Direct tab reference
    report_names = {r.get("name", "") for r in reports}
    for rname in report_names:
        if rname and rname.lower() in link.lower():
            return rname

    return None
