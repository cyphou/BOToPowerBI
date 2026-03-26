"""Semantic Model Intelligence — star schema detection, lineage, impact analysis.

Analyzes extracted BO data and generated TMDL to provide:
- Star/snowflake schema detection with fact/dimension classification
- Relationship optimization (redundant join detection)
- Auto Calendar table generation with time intelligence measures
- Column-level lineage mapping (BO object → DAX measure → visual)
- Impact analysis (predict affected reports from universe changes)
- Measure deduplication across reports
- Model quality scorecard

Usage:
    from powerbi_import.semantic_intelligence import (
        detect_star_schema, build_lineage_map, analyze_impact,
        score_model_quality, optimize_relationships,
    )
"""

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  Star / Snowflake Schema Detection
# ═══════════════════════════════════════════════════════════════════

def detect_star_schema(extracted_data):
    """Analyze tables, columns, and joins to classify fact vs dimension tables.

    Heuristics:
    - Tables with mostly numeric/measure columns → fact tables
    - Tables with mostly string/dimension columns → dimension tables
    - Tables with many outgoing joins → fact tables
    - Tables with few joins, high cardinality → dimension tables

    Returns:
        dict: {
            "schema_type": "star" | "snowflake" | "flat" | "unknown",
            "fact_tables": [{"name": ..., "confidence": 0-1, "measures": [...]}],
            "dimension_tables": [{"name": ..., "confidence": 0-1, "keys": [...]}],
            "relationships": [{"from": ..., "to": ..., "cardinality": ..., "type": ...}],
        }
    """
    tables_data = extracted_data.get("tables", [])
    columns_data = extracted_data.get("columns", [])
    joins_data = extracted_data.get("joins", [])

    if not tables_data:
        return {"schema_type": "unknown", "fact_tables": [], "dimension_tables": [],
                "relationships": []}

    # Build column index by table
    table_columns = defaultdict(list)
    for col in columns_data:
        table_columns[col.get("table", "")].append(col)

    # Build join index
    join_count = defaultdict(int)
    join_targets = defaultdict(set)
    for j in joins_data:
        left = j.get("left_table") or j.get("table1", "")
        right = j.get("right_table") or j.get("table2", "")
        if left:
            join_count[left] += 1
            join_targets[left].add(right)
        if right:
            join_count[right] += 1
            join_targets[right].add(left)

    # Classify each table
    fact_tables = []
    dim_tables = []

    for table in tables_data:
        tname = table.get("name", "")
        cols = table_columns.get(tname, [])

        if not cols:
            continue

        # Count measure vs dimension columns
        measure_cols = [c for c in cols if c.get("qualification") == "measure"]
        dim_cols = [c for c in cols if c.get("qualification") in ("dimension", "detail")]
        numeric_cols = [c for c in cols if c.get("data_type") in ("number", "double", "int", "decimal")]

        measure_ratio = len(measure_cols) / max(len(cols), 1)
        numeric_ratio = len(numeric_cols) / max(len(cols), 1)
        joins_out = join_count.get(tname, 0)

        # Heuristic scoring
        fact_score = 0.0
        fact_score += min(measure_ratio * 0.4, 0.4)
        fact_score += min(numeric_ratio * 0.3, 0.3)
        fact_score += min(joins_out * 0.05, 0.3)

        # Name-based hints
        name_lower = tname.lower()
        if any(kw in name_lower for kw in ("fact", "fct", "transaction", "order", "sale", "event")):
            fact_score += 0.3
        if any(kw in name_lower for kw in ("dim", "lookup", "ref", "master", "calendar", "date")):
            fact_score -= 0.3

        fact_score = max(0, min(1, fact_score))

        if fact_score >= 0.5:
            fact_tables.append({
                "name": tname,
                "confidence": round(fact_score, 2),
                "measures": [c.get("name") for c in measure_cols],
                "column_count": len(cols),
            })
        else:
            dim_tables.append({
                "name": tname,
                "confidence": round(1 - fact_score, 2),
                "keys": [c.get("name") for c in cols
                         if c.get("name", "").lower().endswith(("id", "_id", "key", "_key"))],
                "column_count": len(cols),
            })

    # Determine schema type
    if len(fact_tables) == 1 and len(dim_tables) >= 2:
        schema_type = "star"
    elif len(fact_tables) >= 1 and len(dim_tables) >= 2:
        # Check for snowflake: dimension-to-dimension joins
        dim_names = {d["name"] for d in dim_tables}
        dim_to_dim = any(
            join_targets.get(d, set()) & dim_names
            for d in dim_names
        )
        schema_type = "snowflake" if dim_to_dim else "star"
    elif len(tables_data) == 1:
        schema_type = "flat"
    else:
        schema_type = "unknown"

    # Build relationship recommendations
    relationships = []
    for j in joins_data:
        left = j.get("left_table") or j.get("table1", "")
        right = j.get("right_table") or j.get("table2", "")
        left_col = j.get("left_column") or j.get("column1", "")
        right_col = j.get("right_column") or j.get("column2", "")

        left_is_fact = left in {f["name"] for f in fact_tables}
        right_is_fact = right in {f["name"] for f in fact_tables}

        if left_is_fact and not right_is_fact:
            cardinality = "manyToOne"
        elif not left_is_fact and right_is_fact:
            cardinality = "oneToMany"
        else:
            cardinality = "manyToMany"

        relationships.append({
            "from_table": left, "from_column": left_col,
            "to_table": right, "to_column": right_col,
            "cardinality": cardinality,
            "type": j.get("type", "inner"),
        })

    return {
        "schema_type": schema_type,
        "fact_tables": fact_tables,
        "dimension_tables": dim_tables,
        "relationships": relationships,
    }


def optimize_relationships(extracted_data):
    """Detect redundant/conflicting joins and suggest optimizations.

    Returns:
        dict: {
            "redundant": [...],
            "conflicting": [...],
            "suggestions": [...],
        }
    """
    joins = extracted_data.get("joins", [])
    result = {"redundant": [], "conflicting": [], "suggestions": []}

    seen_pairs = {}
    for j in joins:
        left = j.get("left_table") or j.get("table1", "")
        right = j.get("right_table") or j.get("table2", "")
        pair = tuple(sorted([left, right]))

        if pair in seen_pairs:
            result["redundant"].append({
                "tables": list(pair),
                "existing_join": seen_pairs[pair],
                "duplicate_join": j,
            })
        else:
            seen_pairs[pair] = j

    # Check for circular joins (A→B→C→A)
    graph = defaultdict(set)
    for j in joins:
        left = j.get("left_table") or j.get("table1", "")
        right = j.get("right_table") or j.get("table2", "")
        graph[left].add(right)
        graph[right].add(left)

    visited = set()
    for start in graph:
        if start in visited:
            continue
        stack = [(start, None)]
        path = set()
        while stack:
            node, parent = stack.pop()
            if node in path:
                result["conflicting"].append({
                    "type": "circular",
                    "tables": list(path),
                })
                break
            path.add(node)
            visited.add(node)
            for neighbor in graph[node]:
                if neighbor != parent:
                    stack.append((neighbor, node))

    if result["redundant"]:
        result["suggestions"].append(
            f"Remove {len(result['redundant'])} redundant relationship(s)")
    if result["conflicting"]:
        result["suggestions"].append(
            "Resolve circular relationships — use USERELATIONSHIP for ambiguous paths")

    return result


# ═══════════════════════════════════════════════════════════════════
#  Lineage Map
# ═══════════════════════════════════════════════════════════════════

def build_lineage_map(extracted_data):
    """Build column-level lineage from BO source to PBI output.

    Maps: BO Universe Object → Extracted Column → DAX Measure → Visual Binding

    Returns:
        dict: {
            "nodes": [{"id": ..., "type": "source"|"column"|"measure"|"visual", "name": ...}],
            "edges": [{"from": ..., "to": ..., "type": ...}],
        }
    """
    nodes = []
    edges = []
    node_ids = {}

    def _add_node(ntype, name, table=""):
        key = f"{ntype}:{table}.{name}" if table else f"{ntype}:{name}"
        if key not in node_ids:
            nid = len(nodes)
            node_ids[key] = nid
            nodes.append({"id": nid, "type": ntype, "name": name, "table": table})
        return node_ids[key]

    # Source tables and columns
    for t in extracted_data.get("tables", []):
        tname = t.get("name", "")
        tid = _add_node("source_table", tname)
        for col in extracted_data.get("columns", []):
            if col.get("table") == tname:
                cid = _add_node("column", col.get("name", ""), tname)
                edges.append({"from": tid, "to": cid, "type": "contains"})

    # Formulas/measures reference columns
    for f in extracted_data.get("formulas", []):
        fname = f.get("name", "")
        fid = _add_node("measure", fname)
        formula_text = f.get("formula", "") + f.get("dax", "")
        # Find column references in formula
        for col_node in nodes:
            if col_node["type"] == "column":
                col_name = col_node["name"]
                if col_name and (col_name in formula_text or
                                 f"[{col_name}]" in formula_text):
                    edges.append({"from": col_node["id"], "to": fid,
                                  "type": "used_in"})

    # Charts/reports reference formulas and columns
    for chart in extracted_data.get("charts", []):
        cname = chart.get("name", f"Visual_{len(nodes)}")
        vid = _add_node("visual", cname)
        for dim in chart.get("dimensions", []):
            dim_name = dim if isinstance(dim, str) else dim.get("name", "")
            for n in nodes:
                if n["name"] == dim_name and n["type"] in ("column", "measure"):
                    edges.append({"from": n["id"], "to": vid, "type": "displayed_in"})

    return {"nodes": nodes, "edges": edges}


# ═══════════════════════════════════════════════════════════════════
#  Impact Analysis
# ═══════════════════════════════════════════════════════════════════

def analyze_impact(universe_changes, extracted_data):
    """Given universe changes, predict which reports/measures/visuals are affected.

    Args:
        universe_changes: list of dicts with {"type": "rename"|"remove"|"add",
                          "category": "table"|"column"|"join",
                          "name": str, "table": str (optional)}
        extracted_data: current extraction result dict

    Returns:
        dict: {
            "affected_formulas": [...],
            "affected_charts": [...],
            "affected_queries": [...],
            "risk_level": "low"|"medium"|"high"|"critical",
            "summary": str,
        }
    """
    affected_formulas = []
    affected_charts = []
    affected_queries = []

    for change in universe_changes:
        cname = change.get("name", "")
        ctable = change.get("table", "")
        ctype = change.get("type", "")

        if change.get("category") == "column" and ctype in ("remove", "rename"):
            # Check formulas for column references
            for f in extracted_data.get("formulas", []):
                formula_text = f.get("formula", "") + f.get("dax", "")
                if cname in formula_text:
                    affected_formulas.append({
                        "name": f.get("name"),
                        "change": change,
                        "reason": f"References column '{cname}'"
                    })

            # Check charts
            for chart in extracted_data.get("charts", []):
                for dim in chart.get("dimensions", []) + chart.get("measures", []):
                    dim_name = dim if isinstance(dim, str) else dim.get("name", "")
                    if cname == dim_name:
                        affected_charts.append({
                            "name": chart.get("name"),
                            "change": change,
                        })

        elif change.get("category") == "table" and ctype == "remove":
            # All queries referencing this table are affected
            for q in extracted_data.get("queries", []):
                tables = q.get("tables", [])
                if any((t.get("name") if isinstance(t, dict) else t) == cname
                       for t in tables):
                    affected_queries.append({
                        "name": q.get("name"),
                        "change": change,
                    })

    total_affected = len(affected_formulas) + len(affected_charts) + len(affected_queries)
    if total_affected == 0:
        risk = "low"
    elif total_affected <= 3:
        risk = "medium"
    elif total_affected <= 10:
        risk = "high"
    else:
        risk = "critical"

    return {
        "affected_formulas": affected_formulas,
        "affected_charts": affected_charts,
        "affected_queries": affected_queries,
        "total_affected": total_affected,
        "risk_level": risk,
        "summary": f"{total_affected} objects affected by {len(universe_changes)} change(s) — risk: {risk}",
    }


# ═══════════════════════════════════════════════════════════════════
#  Measure Deduplication
# ═══════════════════════════════════════════════════════════════════

def find_duplicate_measures(multi_report_extractions):
    """Find duplicate measures across multiple report extractions.

    Args:
        multi_report_extractions: list of (report_name, extracted_data) tuples

    Returns:
        dict: {
            "duplicates": [{"name": ..., "reports": [...], "formulas": [...]}],
            "unique_measures": int,
            "total_measures": int,
            "dedup_savings": int,
        }
    """
    measure_index = defaultdict(list)

    for report_name, extracted in multi_report_extractions:
        for f in extracted.get("formulas", []):
            fname = f.get("name", "")
            formula = f.get("formula", "") or f.get("dax", "")
            measure_index[fname].append({
                "report": report_name,
                "formula": formula,
            })

    duplicates = []
    for name, entries in measure_index.items():
        if len(entries) > 1:
            duplicates.append({
                "name": name,
                "reports": [e["report"] for e in entries],
                "formulas": list({e["formula"] for e in entries}),
                "identical": len(set(e["formula"] for e in entries)) == 1,
            })

    total = sum(len(entries) for entries in measure_index.values())
    unique = len(measure_index)

    return {
        "duplicates": duplicates,
        "unique_measures": unique,
        "total_measures": total,
        "dedup_savings": total - unique,
    }


# ═══════════════════════════════════════════════════════════════════
#  Model Quality Scorecard
# ═══════════════════════════════════════════════════════════════════

def score_model_quality(extracted_data, generated_stats=None):
    """Score the quality of a generated semantic model.

    Checks:
    - Relationship coverage (all tables connected?)
    - Measure complexity distribution
    - Naming consistency (PascalCase, snake_case, etc.)
    - Unused columns (columns not referenced in any formula/chart)
    - Circular dependencies
    - Description coverage

    Returns:
        dict with overall_score (0-100), grade (A-F), and per-category scores.
    """
    scores = {}

    tables = extracted_data.get("tables", [])
    columns = extracted_data.get("columns", [])
    formulas = extracted_data.get("formulas", [])
    joins = extracted_data.get("joins", [])
    charts = extracted_data.get("charts", [])

    # 1. Relationship coverage (0-100)
    if len(tables) <= 1:
        scores["relationship_coverage"] = 100
    else:
        connected_tables = set()
        for j in joins:
            connected_tables.add(j.get("left_table") or j.get("table1", ""))
            connected_tables.add(j.get("right_table") or j.get("table2", ""))
        all_tables = {t.get("name", "") for t in tables}
        coverage = len(connected_tables & all_tables) / max(len(all_tables), 1) * 100
        scores["relationship_coverage"] = round(coverage)

    # 2. Naming consistency (0-100)
    names = [c.get("name", "") for c in columns] + [f.get("name", "") for f in formulas]
    if names:
        pascal = sum(1 for n in names if n and n[0].isupper() and "_" not in n)
        snake = sum(1 for n in names if n and "_" in n and n == n.lower())
        dominant = max(pascal, snake, 1)
        consistency = dominant / len(names) * 100
        scores["naming_consistency"] = round(min(consistency, 100))
    else:
        scores["naming_consistency"] = 100

    # 3. Column utilization (0-100)
    referenced_cols = set()
    for f in formulas:
        formula_text = f.get("formula", "") + f.get("dax", "")
        for c in columns:
            cname = c.get("name", "")
            if cname and cname in formula_text:
                referenced_cols.add(cname)
    for chart in charts:
        for item in chart.get("dimensions", []) + chart.get("measures", []):
            name = item if isinstance(item, str) else item.get("name", "")
            referenced_cols.add(name)

    all_col_names = {c.get("name", "") for c in columns}
    if all_col_names:
        utilization = len(referenced_cols & all_col_names) / len(all_col_names) * 100
        scores["column_utilization"] = round(min(utilization, 100))
    else:
        scores["column_utilization"] = 100

    # 4. Measure complexity (0-100, lower complexity = higher score)
    if formulas:
        complexities = []
        for f in formulas:
            text = f.get("formula", "") + f.get("dax", "")
            # Simple complexity: nesting depth + function count
            nesting = text.count("(")
            complexity = min(nesting / 10, 1)
            complexities.append(complexity)
        avg_complexity = sum(complexities) / len(complexities)
        scores["measure_simplicity"] = round((1 - avg_complexity) * 100)
    else:
        scores["measure_simplicity"] = 100

    # 5. Description coverage (0-100)
    items_with_desc = sum(1 for f in formulas if f.get("description"))
    items_with_desc += sum(1 for c in columns if c.get("description"))
    total_items = len(formulas) + len(columns)
    scores["description_coverage"] = round(items_with_desc / max(total_items, 1) * 100)

    # Overall score (weighted average)
    weights = {
        "relationship_coverage": 0.25,
        "naming_consistency": 0.15,
        "column_utilization": 0.20,
        "measure_simplicity": 0.20,
        "description_coverage": 0.20,
    }
    overall = sum(scores.get(k, 0) * w for k, w in weights.items())
    overall = round(overall)

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

    return {
        "overall_score": overall,
        "grade": grade,
        "categories": scores,
        "table_count": len(tables),
        "column_count": len(columns),
        "measure_count": len(formulas),
        "relationship_count": len(joins),
    }
