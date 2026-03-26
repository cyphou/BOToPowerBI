"""Theme Generator — extract BO document styling → Power BI theme.json.

Converts BusinessObjects report formatting (colors, fonts, borders) into
Power BI theme JSON files that preserve the original visual identity.

Usage:
    from powerbi_import.theme_generator import generate_theme
    theme = generate_theme(extracted_data, theme_name="Sales Report")
    # Returns dict conforming to Power BI theme schema
"""

import json
import logging
import re
from collections import Counter

logger = logging.getLogger(__name__)

# Default PBI theme skeleton
_DEFAULT_THEME = {
    "name": "Migrated Theme",
    "dataColors": [
        "#118DFF", "#12239E", "#E66C37", "#6B007B",
        "#E044A7", "#744EC2", "#D9B300", "#D64550",
    ],
    "background": "#FFFFFF",
    "foreground": "#252423",
    "tableAccent": "#118DFF",
}

# Common BO color names → hex
_BO_COLOR_MAP = {
    "black": "#000000", "white": "#FFFFFF", "red": "#FF0000",
    "green": "#008000", "blue": "#0000FF", "yellow": "#FFFF00",
    "gray": "#808080", "grey": "#808080", "orange": "#FFA500",
    "purple": "#800080", "navy": "#000080", "teal": "#008080",
    "silver": "#C0C0C0", "maroon": "#800000",
}

# BO font families → PBI-safe equivalents
_FONT_MAP = {
    "Arial": "Arial",
    "Times New Roman": "Times New Roman",
    "Courier New": "Courier New",
    "Helvetica": "Segoe UI",
    "Verdana": "Segoe UI",
    "Tahoma": "Segoe UI",
    "Calibri": "Segoe UI",
    "Sans Serif": "Segoe UI",
}


def _normalize_color(color_str):
    """Convert BO color strings to hex format."""
    if not color_str:
        return None
    color_str = color_str.strip()

    # Already hex
    if re.match(r'^#[0-9a-fA-F]{6}$', color_str):
        return color_str.upper()

    # Named color
    if color_str.lower() in _BO_COLOR_MAP:
        return _BO_COLOR_MAP[color_str.lower()]

    # RGB format: rgb(r, g, b)
    m = re.match(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', color_str, re.I)
    if m:
        return f"#{int(m.group(1)):02X}{int(m.group(2)):02X}{int(m.group(3)):02X}"

    # BO integer color (BGR or RGB encoded in integer)
    if color_str.isdigit():
        val = int(color_str)
        r = val & 0xFF
        g = (val >> 8) & 0xFF
        b = (val >> 16) & 0xFF
        return f"#{r:02X}{g:02X}{b:02X}"

    return None


def _map_font(font_name):
    """Map BO font to PBI-safe font."""
    if not font_name:
        return "Segoe UI"
    for bo_font, pbi_font in _FONT_MAP.items():
        if bo_font.lower() in font_name.lower():
            return pbi_font
    return font_name


def _extract_colors_from_data(extracted_data):
    """Collect all colors used in the BO report."""
    colors = []

    # From charts
    for chart in extracted_data.get("charts", []):
        for color_key in ("color", "background_color", "fill_color", "series_colors"):
            val = chart.get(color_key)
            if isinstance(val, list):
                colors.extend(val)
            elif val:
                colors.append(val)

    # From alerts (conditional formatting)
    for alert in extracted_data.get("alerts", []):
        for color_key in ("color", "background_color", "font_color"):
            val = alert.get(color_key)
            if val:
                colors.append(val)

    # From formatting in reports
    for report in extracted_data.get("reports", []):
        for fmt_key in ("header_color", "background_color", "font_color",
                        "border_color", "accent_color"):
            val = report.get(fmt_key)
            if val:
                colors.append(val)

    # Normalize and deduplicate
    normalized = []
    for c in colors:
        nc = _normalize_color(str(c))
        if nc and nc not in {"#FFFFFF", "#000000"}:
            normalized.append(nc)

    # Return most common colors first
    counter = Counter(normalized)
    return [c for c, _ in counter.most_common(8)] or _DEFAULT_THEME["dataColors"]


def _extract_fonts(extracted_data):
    """Extract font information from BO report."""
    fonts = []
    for report in extracted_data.get("reports", []):
        for key in ("font", "font_family", "header_font"):
            val = report.get(key)
            if val:
                fonts.append(val)

    for chart in extracted_data.get("charts", []):
        for key in ("font", "title_font", "label_font"):
            val = chart.get(key)
            if val:
                fonts.append(val)

    if fonts:
        counter = Counter(fonts)
        return _map_font(counter.most_common(1)[0][0])
    return "Segoe UI"


def generate_theme(extracted_data, theme_name=None):
    """Generate Power BI theme JSON from extracted BO data.

    Args:
        extracted_data: dict with reports, charts, alerts, etc.
        theme_name: optional theme name; defaults to report name + " Theme"

    Returns:
        dict conforming to Power BI reportTheme schema
    """
    reports = extracted_data.get("reports", [])
    first_report = reports[0].get("name", "Migration") if reports else "Migration"
    name = theme_name or f"{first_report} Theme"

    data_colors = _extract_colors_from_data(extracted_data)
    font_family = _extract_fonts(extracted_data)

    # Determine background from first report
    bg = "#FFFFFF"
    if reports:
        bg_raw = reports[0].get("background_color")
        if bg_raw:
            bg = _normalize_color(str(bg_raw)) or "#FFFFFF"

    # Determine foreground (text color)
    fg = "#252423"
    if reports:
        fg_raw = reports[0].get("font_color")
        if fg_raw:
            fg = _normalize_color(str(fg_raw)) or "#252423"

    theme = {
        "name": name,
        "dataColors": data_colors[:8],
        "background": bg,
        "foreground": fg,
        "tableAccent": data_colors[0] if data_colors else "#118DFF",
        "visualStyles": {
            "*": {
                "*": {
                    "general": [{"responsive": True}],
                    "*": [{
                        "fontFamily": font_family,
                        "fontSize": 10,
                    }],
                }
            }
        },
        "textClasses": {
            "callout": {"fontFace": font_family, "fontSize": 45, "color": fg},
            "title": {"fontFace": font_family, "fontSize": 12, "color": fg},
            "header": {"fontFace": font_family, "fontSize": 12, "color": fg},
            "label": {"fontFace": font_family, "fontSize": 10, "color": fg},
        },
    }

    logger.info("Generated theme '%s' with %d data colors, font=%s",
                name, len(data_colors), font_family)
    return theme


def write_theme_file(theme_dict, output_path):
    """Write theme dict to JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(theme_dict, f, indent=2, ensure_ascii=False)
    logger.info("Theme written to %s", output_path)
    return output_path
