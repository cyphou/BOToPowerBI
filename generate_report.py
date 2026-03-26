"""HTML migration report generator.

Runs the full extraction → generation pipeline on SAP BusinessObjects
artifacts, collects per-artifact statistics, and generates a consolidated
HTML migration report with executive summary, conversion donut/bar charts,
per-artifact detail tables, pipeline flow diagrams, and fidelity scoring.

Usage:
    python generate_report.py                          # examples/ → report
    python generate_report.py path/to/files/           # custom dir → report
    python generate_report.py f1.wid f2.rpt f3.unx    # specific files
"""

import glob
import json
import logging
import os
import sys
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# BO file extensions handled by the extraction pipeline
_BO_EXTENSIONS = {".wid", ".rpt", ".unx", ".unv", ".lumx", ".lums"}

# JSON files written by the extraction step
_EXTRACTION_FILES = [
    "reports", "queries", "datasources", "formulas", "prompts",
    "filters", "tables", "columns", "joins", "groups", "sorts",
    "alerts", "subreports", "charts", "custom_sql",
]

# Friendly source type labels
_TYPE_LABELS = {
    ".wid": "WebI", ".rpt": "Crystal", ".unx": "Universe IDT",
    ".unv": "Universe Designer", ".lumx": "Lumira", ".lums": "Lumira",
}


# ═══════════════════════════════════════════════════════════════════════
#  Pipeline: extract + generate for a single file
# ═══════════════════════════════════════════════════════════════════════

def _migrate_one(input_path, output_root):
    """Run extract → generate for one BO artifact.

    Returns a dict with extraction counts, generation counts, timing,
    and status (success/error).
    """
    from bo_export.extract_bo_data import extract_bo_data

    name = os.path.splitext(os.path.basename(input_path))[0]
    ext = os.path.splitext(input_path)[1].lower()
    out_dir = os.path.join(output_root, name)
    os.makedirs(out_dir, exist_ok=True)

    result = {
        "name": name,
        "source_file": os.path.basename(input_path),
        "source_type": _TYPE_LABELS.get(ext, ext),
        "output_dir": out_dir,
        "extraction": {},
        "generation": {},
        "status": "success",
        "error": None,
        "elapsed": 0.0,
    }

    t0 = time.time()

    # ── Step 1: Extraction ────────────────────────────────────
    try:
        extracted = extract_bo_data(input_path, output_dir=out_dir)
        for key in _EXTRACTION_FILES:
            items = extracted.get(key, [])
            result["extraction"][key] = len(items) if isinstance(items, list) else 0
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"Extraction: {exc}"
        result["elapsed"] = time.time() - t0
        return result

    # ── Step 2: Generation ────────────────────────────────────
    try:
        from powerbi_import.import_to_powerbi import PowerBIImporter
        importer = PowerBIImporter(source_dir=out_dir)
        importer.import_all(report_name=name, output_dir=out_dir)

        # Collect generation stats from .pbip output
        gen = {"tables": 0, "columns": 0, "measures": 0,
               "relationships": 0, "pages": 0, "visuals": 0}
        pbip_dir = os.path.join(out_dir, name)
        if os.path.isdir(pbip_dir):
            tmdl_dir = os.path.join(pbip_dir, f"{name}.SemanticModel",
                                    "definition")
            if os.path.isdir(tmdl_dir):
                # Tables = .tmdl files in tables/ subdirectory
                tables_dir = os.path.join(tmdl_dir, "tables")
                if os.path.isdir(tables_dir):
                    gen["tables"] = sum(
                        1 for f in os.listdir(tables_dir)
                        if f.endswith(".tmdl"))
                # Columns/measures from table files; relationships from
                # relationships.tmdl — patterns start at beginning of
                # line so check both startswith and \n prefix.
                for root, _dirs, files in os.walk(tmdl_dir):
                    for f in files:
                        if f.endswith(".tmdl"):
                            content = _read_text(os.path.join(root, f))
                            gen["columns"] += content.count("\n\tcolumn ")
                            gen["measures"] += content.count("\n\tmeasure ")
                            gen["relationships"] += (
                                content.count("\nrelationship ")
                                + (1 if content.startswith("relationship ") else 0))
            # Count report pages / visuals
            report_dir = os.path.join(pbip_dir, f"{name}.Report")
            if os.path.isdir(report_dir):
                for root, _dirs, files in os.walk(report_dir):
                    for f in files:
                        if f == "page.json":
                            gen["pages"] += 1
                        elif f == "visual.json":
                            gen["visuals"] += 1
        result["generation"] = gen
    except Exception as exc:
        result["status"] = "partial"
        result["error"] = f"Generation: {exc}"

    result["elapsed"] = time.time() - t0
    return result


def _read_text(path):
    """Read a text file, swallowing errors."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════
#  Data collection
# ═══════════════════════════════════════════════════════════════════════

def _discover_bo_files(paths):
    """Discover BO files from a list of paths (files or directories)."""
    files = []
    for p in paths:
        if os.path.isfile(p):
            if os.path.splitext(p)[1].lower() in _BO_EXTENSIONS:
                files.append(os.path.abspath(p))
        elif os.path.isdir(p):
            for ext in _BO_EXTENSIONS:
                files.extend(
                    os.path.abspath(f)
                    for f in glob.glob(os.path.join(p, f"*{ext}"))
                )
    return sorted(set(files))


def run_migration_batch(input_paths, output_root):
    """Run extraction + generation for all discovered BO files.

    Returns:
        dict with aggregate stats and per-artifact results.
    """
    t_start = time.time()
    results = []
    for path in input_paths:
        print(f"  Migrating: {os.path.basename(path)} ...", end=" ", flush=True)
        r = _migrate_one(path, output_root)
        icon = "\u2705" if r["status"] == "success" else (
            "\u26A0\uFE0F" if r["status"] == "partial" else "\u274C")
        print(f"{icon}  ({r['elapsed']:.2f}s)")
        results.append(r)

    elapsed_total = time.time() - t_start

    # Aggregate
    agg = {
        "total_artifacts": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "partial": sum(1 for r in results if r["status"] == "partial"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "total_queries": sum(r["extraction"].get("queries", 0) for r in results),
        "total_formulas": sum(r["extraction"].get("formulas", 0) for r in results),
        "total_charts": sum(r["extraction"].get("charts", 0) for r in results),
        "total_tables": sum(r["extraction"].get("tables", 0) for r in results),
        "total_columns": sum(r["extraction"].get("columns", 0) for r in results),
        "total_joins": sum(r["extraction"].get("joins", 0) for r in results),
        "total_prompts": sum(r["extraction"].get("prompts", 0) for r in results),
        "total_filters": sum(r["extraction"].get("filters", 0) for r in results),
        "gen_tables": sum(r["generation"].get("tables", 0) for r in results),
        "gen_columns": sum(r["generation"].get("columns", 0) for r in results),
        "gen_measures": sum(r["generation"].get("measures", 0) for r in results),
        "gen_relationships": sum(r["generation"].get("relationships", 0) for r in results),
        "gen_pages": sum(r["generation"].get("pages", 0) for r in results),
        "gen_visuals": sum(r["generation"].get("visuals", 0) for r in results),
        "elapsed_seconds": round(elapsed_total, 2),
    }

    return {"aggregate": agg, "artifacts": results}


# ═══════════════════════════════════════════════════════════════════════
#  HTML report builder — uses powerbi_import.html_template components
# ═══════════════════════════════════════════════════════════════════════

def _build_html_report(data):
    """Build a rich HTML migration report from collected data."""
    from powerbi_import.html_template import (
        html_open, html_close, stat_card, stat_grid, section_open,
        section_close, badge, fidelity_bar, donut_chart, bar_chart,
        data_table, flow_diagram, card, esc,
    )

    agg = data["aggregate"]
    artifacts = data["artifacts"]

    # ── Compute fidelity ──────────────────────────────
    success_count = agg["success"] + agg["partial"]
    fidelity = round(success_count / agg["total_artifacts"] * 100, 1) if agg["total_artifacts"] else 0

    # ── Header ────────────────────────────────────────
    html = html_open(
        title="SAP BusinessObjects \u2192 Power BI Migration Report",
        subtitle=f'{agg["total_artifacts"]} artifact(s) processed in {agg["elapsed_seconds"]:.1f}s',
    )

    # ── Executive Summary ─────────────────────────────
    html += section_open("exec", "Executive Summary", icon="\U0001F4CA")
    html += stat_grid([
        stat_card(agg["total_artifacts"], "Artifacts Processed", accent="blue"),
        stat_card(agg["success"], "Fully Migrated", accent="success"),
        stat_card(agg["partial"], "Partial", accent="warn") if agg["partial"] else "",
        stat_card(agg["errors"], "Failed", accent="fail") if agg["errors"] else "",
        stat_card(f'{fidelity:.0f}%', "Migration Fidelity", accent="blue"),
        stat_card(f'{agg["elapsed_seconds"]:.1f}s', "Total Time"),
    ])

    # Donut: conversion status
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:16px 0">'
    html += card(donut_chart([
        ("Fully Migrated", agg["success"], "#107c10"),
        ("Partial", agg["partial"], "#797600"),
        ("Failed", agg["errors"], "#a4262c"),
    ], center_text=f'{fidelity:.0f}%'), title="Migration Status")

    # Bar: source type breakdown
    type_counts = {}
    for a in artifacts:
        t = a["source_type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    colors = {"WebI": "#0078d4", "Crystal": "#8764b8", "Universe IDT": "#038387",
              "Universe Designer": "#ca5010", "Lumira": "#107c10"}
    html += card(bar_chart([
        (t, c, colors.get(t, "#605e5c")) for t, c in sorted(type_counts.items())
    ]), title="Artifacts by Source Type")
    html += '</div>'

    html += section_close()

    # ── Pipeline Flow ─────────────────────────────────
    html += section_open("flow", "Migration Pipeline", icon="\U0001F504")
    html += flow_diagram([
        ("SAP BO Artifacts<br><small>.wid .rpt .unx .unv .lumx</small>", False),
        ("Extraction<br><small>15 JSON types</small>", True),
        ("DAX Converter<br><small>150+ mappings</small>", True),
        ("PBIP Generator<br><small>TMDL + PBIR v4.0</small>", True),
        ("Power BI Project<br><small>.pbip output</small>", False),
    ])
    html += section_close()

    # ── Extraction Summary ────────────────────────────
    html += section_open("extract", "Extraction Results", icon="\U0001F50D")
    html += stat_grid([
        stat_card(agg["total_queries"], "Queries", accent="blue"),
        stat_card(agg["total_formulas"], "Formulas", accent="purple"),
        stat_card(agg["total_charts"], "Charts", accent="teal"),
        stat_card(agg["total_tables"], "Tables"),
        stat_card(agg["total_columns"], "Columns"),
        stat_card(agg["total_joins"], "Joins"),
        stat_card(agg["total_prompts"], "Prompts"),
        stat_card(agg["total_filters"], "Filters"),
    ])

    # Bar chart: extraction by category
    ext_items = [
        ("Queries", agg["total_queries"], "#0078d4"),
        ("Formulas", agg["total_formulas"], "#8764b8"),
        ("Charts", agg["total_charts"], "#038387"),
        ("Tables", agg["total_tables"], "#ca5010"),
        ("Columns", agg["total_columns"], "#107c10"),
        ("Joins", agg["total_joins"], "#004578"),
        ("Prompts", agg["total_prompts"], "#797600"),
        ("Filters", agg["total_filters"], "#a4262c"),
    ]
    html += card(bar_chart(ext_items), title="Extracted Object Counts")
    html += section_close()

    # ── Generation Summary ────────────────────────────
    html += section_open("gen", "Generated Artifacts", icon="\U0001F528")
    html += stat_grid([
        stat_card(agg["gen_tables"], "TMDL Tables", accent="blue"),
        stat_card(agg["gen_columns"], "TMDL Columns"),
        stat_card(agg["gen_measures"], "DAX Measures", accent="purple"),
        stat_card(agg["gen_relationships"], "Relationships", accent="teal"),
        stat_card(agg["gen_pages"], "Report Pages"),
        stat_card(agg["gen_visuals"], "Visuals", accent="success"),
    ])
    html += section_close()

    # ── Per-Artifact Details Table ────────────────────
    html += section_open("details", "Per-Artifact Details", icon="\U0001F4C4")
    rows = []
    for a in artifacts:
        ext = a["extraction"]
        gen = a["generation"]
        status_badge = badge("PASS", "green") if a["status"] == "success" else (
            badge("PARTIAL", "yellow") if a["status"] == "partial" else badge("FAIL", "red"))
        rows.append([
            esc(a["name"]),
            f'<span style="font-size:0.85em;color:#605e5c">{esc(a["source_type"])}</span>',
            status_badge,
            str(ext.get("queries", 0)),
            str(ext.get("formulas", 0)),
            str(ext.get("charts", 0)),
            str(ext.get("tables", 0)),
            str(ext.get("columns", 0)),
            str(gen.get("tables", 0)),
            str(gen.get("measures", 0)),
            str(gen.get("visuals", 0)),
            f'{a["elapsed"]:.2f}s',
        ])
    html += data_table(
        headers=["Artifact", "Type", "Status", "Queries", "Formulas",
                 "Charts", "Tables", "Columns",
                 "TMDL Tables", "DAX Measures", "Visuals", "Time"],
        rows=rows,
        table_id="artifact-table",
        sortable=True,
        searchable=True,
    )
    html += section_close()

    # ── Per-Artifact Expansion Cards ──────────────────
    html += section_open("cards", "Artifact Deep Dive", icon="\U0001F50E", collapsed=True)
    for a in artifacts:
        ext = a["extraction"]
        gen = a["generation"]
        inner = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'
        inner += '<div><strong>Extraction</strong><br>'
        for k in _EXTRACTION_FILES:
            v = ext.get(k, 0)
            if v:
                inner += f'<span style="display:inline-block;margin:2px 6px 2px 0;padding:2px 8px;background:#deecf9;border-radius:4px;font-size:0.82em">{k}: {v}</span>'
        inner += '</div>'
        inner += '<div><strong>Generation</strong><br>'
        for k, v in gen.items():
            if v:
                inner += f'<span style="display:inline-block;margin:2px 6px 2px 0;padding:2px 8px;background:#dff6dd;border-radius:4px;font-size:0.82em">{k}: {v}</span>'
        inner += '</div></div>'
        if a.get("error"):
            inner += f'<div style="margin-top:8px;color:#a4262c;font-size:0.85em">\u26A0 {esc(a["error"])}</div>'
        html += card(inner, title=f'{a["name"]} ({a["source_type"]})')
    html += section_close()

    # ── Footer ────────────────────────────────────────
    # Override Tableau reference in html_close
    html += f"""
</div> <!-- /container -->
<div class="report-footer">
    <p>SAP BusinessObjects &#8594; Power BI Migration Tool &nbsp;|&nbsp; Report generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
    <p>Open .pbip files in Power BI Desktop (Developer Mode) to validate</p>
</div>
<script>
"""
    from powerbi_import.html_template import get_report_js
    html += get_report_js()
    html += """
</script>
</body>
</html>"""

    return html


# ═══════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════

def generate_report(input_paths, output_path="migration_report.html",
                    output_root=None):
    """Run migrations and generate a consolidated HTML migration report.

    Args:
        input_paths: List of files or directories containing BO artifacts.
        output_path: Path to write the HTML report.
        output_root: Root directory for migration output (default: alongside report).
    """
    if not output_root:
        output_root = os.path.join(os.path.dirname(os.path.abspath(output_path)),
                                   "migration_output")

    bo_files = _discover_bo_files(input_paths)
    if not bo_files:
        print("No BO files found.")
        return

    print("=" * 64)
    print("  SAP BusinessObjects \u2192 Power BI — Batch Migration")
    print("=" * 64)
    print(f"  Artifacts found: {len(bo_files)}")
    print(f"  Output root:     {output_root}")
    print()

    data = run_migration_batch(bo_files, output_root)

    print()
    agg = data["aggregate"]
    print(f"  Results: {agg['success']} success, {agg['partial']} partial, {agg['errors']} errors")
    print(f"  Total:   {agg['elapsed_seconds']:.2f}s")
    print()

    # Save JSON summary
    json_path = os.path.splitext(output_path)[0] + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  JSON summary: {json_path}")

    # Generate HTML report
    html = _build_html_report(data)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML report:  {output_path}")
    print()

    return data


# ═══════════════════════════════════════════════════════════════════════
#  CLI entry point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Ensure stdout handles unicode
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if len(sys.argv) > 1:
        paths = sys.argv[1:]
    else:
        # Default: examples/ directory
        examples_dir = os.path.join(os.path.dirname(__file__), "examples")
        if os.path.isdir(examples_dir):
            paths = [examples_dir]
        else:
            print("Usage: python generate_report.py [path1 path2 ...]")
            print("  Default: runs on examples/ directory")
            sys.exit(1)

    report_path = os.path.join(os.path.dirname(__file__), "MIGRATION_REPORT.html")
    output_dir = os.path.join(os.path.dirname(__file__), "migration_output")

    data = generate_report(paths, output_path=report_path, output_root=output_dir)

    if data:
        agg = data["aggregate"]
        print("=" * 64)
        print(f"  Open {report_path} in your browser to view the report")
        print("=" * 64)
