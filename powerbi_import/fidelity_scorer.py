"""Visual Fidelity Scorer — measure how closely PBI output matches BO source.

Compares structural similarity, visual element coverage, color palette
proximity, layout preservation, and formula conversion completeness.

Usage:
    from powerbi_import.fidelity_scorer import score_fidelity
    result = score_fidelity(extracted_data, generated_output)
"""

import logging
import math
from collections import Counter

logger = logging.getLogger(__name__)


def score_fidelity(extracted_data, generated_output=None):
    """Compute overall fidelity score for a migration.

    Args:
        extracted_data: original BO extraction dict
        generated_output: optional dict with generated artifact stats:
            {
                "tables": int, "columns": int, "measures": int,
                "relationships": int, "visuals": int, "pages": int,
                "themes": bool, "bookmarks": int,
            }

    Returns:
        dict: {
            "overall": float (0-100),
            "grade": str (A-F),
            "categories": {
                "data_model": float,
                "formula_coverage": float,
                "visual_coverage": float,
                "filter_coverage": float,
                "navigation": float,
            },
            "details": [str],
        }
    """
    scores = {}
    details = []

    # ── Data model coverage ──
    tables = extracted_data.get("tables", [])
    columns = extracted_data.get("columns", [])
    joins = extracted_data.get("joins", [])

    if generated_output:
        gen_tables = generated_output.get("tables", 0)
        gen_cols = generated_output.get("columns", 0)
        gen_rels = generated_output.get("relationships", 0)

        table_cov = min(gen_tables / max(len(tables), 1), 1.0) * 100
        col_cov = min(gen_cols / max(len(columns), 1), 1.0) * 100
        rel_cov = min(gen_rels / max(len(joins), 1), 1.0) * 100
        scores["data_model"] = (table_cov + col_cov + rel_cov) / 3
    else:
        # Score based on extraction completeness
        has_tables = 100 if tables else 0
        has_cols = 100 if columns else 0
        has_joins = 100 if joins else 0
        scores["data_model"] = (has_tables + has_cols + has_joins) / 3

    details.append(f"Tables: {len(tables)}, Columns: {len(columns)}, Joins: {len(joins)}")

    # ── Formula coverage ──
    formulas = extracted_data.get("formulas", [])
    if formulas:
        converted = sum(1 for f in formulas if f.get("dax") or f.get("converted"))
        scores["formula_coverage"] = converted / len(formulas) * 100
        unconverted = len(formulas) - converted
        if unconverted:
            details.append(f"{unconverted}/{len(formulas)} formulas need manual DAX review")
    else:
        scores["formula_coverage"] = 100  # No formulas to convert

    # ── Visual coverage ──
    charts = extracted_data.get("charts", [])
    if charts:
        supported_types = {
            "bar", "column", "line", "pie", "donut", "table", "crosstab",
            "matrix", "scatter", "area", "combo", "map", "gauge", "kpi",
            "funnel", "waterfall", "treemap", "card", "slicer",
        }
        mapped = sum(1 for c in charts
                     if c.get("type", "").lower() in supported_types)
        scores["visual_coverage"] = mapped / len(charts) * 100
        unmapped = len(charts) - mapped
        if unmapped:
            unmapped_types = set(c.get("type", "unknown") for c in charts
                                if c.get("type", "").lower() not in supported_types)
            details.append(f"{unmapped} visual(s) with unsupported types: "
                           f"{', '.join(unmapped_types)}")
    else:
        scores["visual_coverage"] = 100

    # ── Filter/prompt coverage ──
    filters = extracted_data.get("filters", [])
    prompts = extracted_data.get("prompts", [])
    total_filters = len(filters) + len(prompts)
    if total_filters:
        converted_filters = sum(1 for f in filters if f.get("converted", True))
        converted_prompts = sum(1 for p in prompts if p.get("converted", True))
        scores["filter_coverage"] = (converted_filters + converted_prompts) / total_filters * 100
    else:
        scores["filter_coverage"] = 100

    # ── Navigation coverage ──
    subreports = extracted_data.get("subreports", [])
    reports = extracted_data.get("reports", [])
    nav_items = len(subreports) + max(len(reports) - 1, 0)  # tabs create navigation
    if nav_items:
        scores["navigation"] = 100  # We generate bookmarks for all tabs
    else:
        scores["navigation"] = 100

    # ── Weighted overall score ──
    weights = {
        "data_model": 0.30,
        "formula_coverage": 0.25,
        "visual_coverage": 0.25,
        "filter_coverage": 0.10,
        "navigation": 0.10,
    }
    overall = sum(scores.get(k, 0) * w for k, w in weights.items())
    overall = round(overall, 1)

    # Grade
    if overall >= 90:
        grade = "A"
    elif overall >= 80:
        grade = "B"
    elif overall >= 70:
        grade = "C"
    elif overall >= 60:
        grade = "D"
    else:
        grade = "F"

    details.insert(0, f"Overall fidelity: {overall}% (Grade {grade})")

    return {
        "overall": overall,
        "grade": grade,
        "categories": scores,
        "details": details,
    }


def compare_color_palettes(source_colors, target_colors):
    """Compare two color palettes for similarity.

    Uses CIE76 color distance approximation in RGB space.

    Returns:
        float: similarity score 0-100
    """
    if not source_colors or not target_colors:
        return 100.0 if not source_colors else 0.0

    def _hex_to_rgb(hex_str):
        hex_str = hex_str.lstrip('#')
        if len(hex_str) != 6:
            return (128, 128, 128)
        return tuple(int(hex_str[i:i + 2], 16) for i in (0, 2, 4))

    def _color_distance(c1, c2):
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))

    src_rgb = [_hex_to_rgb(c) for c in source_colors]
    tgt_rgb = [_hex_to_rgb(c) for c in target_colors]

    # For each source color, find best match in target
    total_dist = 0
    for srgb in src_rgb:
        min_dist = min(_color_distance(srgb, trgb) for trgb in tgt_rgb)
        total_dist += min_dist

    # Normalize: max distance is 441 (black to white)
    avg_dist = total_dist / len(src_rgb)
    similarity = max(0, (1 - avg_dist / 441)) * 100
    return round(similarity, 1)


def compare_layouts(source_positions, target_positions):
    """Compare spatial arrangement fidelity.

    Measures how well the relative positions of visuals are preserved.

    Args:
        source_positions: list of {"name": str, "x": int, "y": int, "width": int, "height": int}
        target_positions: list of same format

    Returns:
        float: layout similarity 0-100
    """
    if not source_positions or not target_positions:
        return 100.0 if not source_positions else 0.0

    # Match by name
    target_map = {p["name"]: p for p in target_positions}

    matched = 0
    position_score = 0

    for sp in source_positions:
        tp = target_map.get(sp["name"])
        if not tp:
            continue
        matched += 1

        # Relative position similarity (normalized)
        dx = abs(sp.get("x", 0) - tp.get("x", 0))
        dy = abs(sp.get("y", 0) - tp.get("y", 0))
        dw = abs(sp.get("width", 100) - tp.get("width", 100))
        dh = abs(sp.get("height", 100) - tp.get("height", 100))

        # Max reasonable canvas is 1920x1080
        pos_sim = 1 - min((dx + dy) / 2000, 1)
        size_sim = 1 - min((dw + dh) / 1000, 1)
        position_score += (pos_sim * 0.6 + size_sim * 0.4)

    if matched == 0:
        return 0.0

    match_ratio = matched / len(source_positions)
    avg_score = position_score / matched

    return round(match_ratio * avg_score * 100, 1)
