"""Bridge adapter: maps BO extracted data (15 JSON types) to the
``converted_objects`` schema consumed by the generation layer.

Usage::

    from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
    from bo_export.extract_bo_data import load_extracted_data

    extracted = load_extracted_data("output_dir")
    converted = adapt_bo_to_converted_objects(extracted)
    # ``converted`` is now ready for PowerBIProjectGenerator / tmdl_generator
"""

from __future__ import annotations

import logging
from typing import Any

from bo_export.dax_converter import convert_bo_formula_to_dax
from bo_export.compat import map_bo_to_powerbi_type

logger = logging.getLogger(__name__)


def adapt_bo_to_converted_objects(extracted: dict[str, list]) -> dict[str, Any]:
    """Map BO's 15 extracted JSON types to the generation ``converted_objects`` dict.

    Args:
        extracted: Dict returned by ``extract_bo_data`` / ``load_extracted_data``,
                   with keys: reports, queries, datasources, formulas, prompts,
                   filters, tables, columns, joins, groups, sorts, alerts,
                   subreports, charts, custom_sql.

    Returns:
        Dict compatible with ``PowerBIProjectGenerator.generate_project()``
        and ``generate_tmdl()``.
    """
    adapted_worksheets = _adapt_worksheets(extracted)
    _apply_alerts_to_worksheets(adapted_worksheets, extracted.get("alerts", []))
    subreport_ws, subreport_actions = _adapt_subreports(extracted)
    adapted_worksheets.extend(subreport_ws)

    return {
        "datasources": _adapt_datasources(extracted),
        "worksheets": adapted_worksheets,
        "dashboards": _adapt_dashboards(extracted, adapted_worksheets),
        "calculations": _adapt_calculations(extracted),
        "parameters": _adapt_parameters(extracted),
        "filters": _adapt_filters(extracted),
        "stories": [],
        "actions": subreport_actions,
        "sets": [],
        "groups": _adapt_groups(extracted),
        "bins": [],
        "hierarchies": _adapt_hierarchies(extracted),
        "sort_orders": _adapt_sorts(extracted),
        "aliases": _adapt_aliases(extracted),
        "custom_sql": extracted.get("custom_sql", []),
        "relationships": _adapt_relationships_toplevel(extracted),
        "user_filters": [],
        "hyper_files": [],
        "custom_shapes": [],
    }


# ───────────────────────────────────────────────────────────────
#  Datasources  (the core nested structure)
# ───────────────────────────────────────────────────────────────

def _adapt_datasources(extracted: dict) -> list[dict]:
    """Build the nested ``datasources[]`` structure expected by the generators.

    Each datasource contains: connection, tables (with nested columns),
    calculations, and relationships.
    """
    bo_datasources = extracted.get("datasources", [])
    bo_tables = extracted.get("tables", [])
    bo_columns = extracted.get("columns", [])
    bo_joins = extracted.get("joins", [])
    bo_formulas = extracted.get("formulas", [])
    bo_custom_sql = extracted.get("custom_sql", [])

    # Index columns by table name (case-insensitive)
    columns_by_table: dict[str, list[dict]] = {}
    for col in bo_columns:
        tname = (col.get("table") or "").lower()
        columns_by_table.setdefault(tname, []).append(col)

    result = []

    for ds in bo_datasources:
        ds_name = ds.get("name", "")

        # Build connection dict
        connection = {
            "type": ds.get("type", "odbc"),
            "server": ds.get("server", ""),
            "database": ds.get("database", ""),
            "schema": ds.get("schema", "dbo"),
        }
        if ds.get("connection_string"):
            connection["connectionString"] = ds["connection_string"]

        # Build tables with nested columns
        tables = _build_tables(ds_name, bo_tables, columns_by_table, bo_custom_sql)

        # If no tables found from the tables list, create one from the DS itself
        if not tables and ds_name:
            ds_cols = columns_by_table.get(ds_name.lower(), [])
            if ds_cols:
                tables = [{
                    "name": ds_name,
                    "columns": [_adapt_column(c) for c in ds_cols],
                }]

        # Build calculations from formulas
        calculations = [_adapt_formula_to_calc(f, ds_name) for f in bo_formulas]

        # Build relationships from joins
        relationships = _adapt_relationships(bo_joins)

        # Ensure join key columns exist in their tables
        _ensure_join_columns(tables, bo_joins)

        result.append({
            "name": ds_name,
            "connection": connection,
            "connection_map": {ds_name: connection} if ds_name else {},
            "tables": tables,
            "columns": [],  # DS-level columns (tables contain their own)
            "calculations": calculations,
            "relationships": relationships,
            "m_query_overrides": {},
        })

    # If no datasources were extracted, create a synthetic one from tables
    if not result and bo_tables:
        tables = _build_tables("", bo_tables, columns_by_table, bo_custom_sql)
        result.append({
            "name": "BO_DataSource",
            "connection": {"type": "odbc", "server": "", "database": ""},
            "connection_map": {},
            "tables": tables,
            "columns": [],
            "calculations": [_adapt_formula_to_calc(f, "") for f in bo_formulas],
            "relationships": _adapt_relationships(bo_joins),
            "m_query_overrides": {},
        })

    return result


def _build_tables(ds_name: str, bo_tables: list, columns_by_table: dict,
                  bo_custom_sql: list) -> list[dict]:
    """Build the tables[] list with nested columns."""
    tables = []

    for tbl in bo_tables:
        tname = tbl.get("name", "")
        if not tname:
            continue

        # Match columns to this table
        pbi_columns = [_adapt_column(c) for c in columns_by_table.get(tname.lower(), [])]

        table_dict: dict[str, Any] = {
            "name": tname,
            "columns": pbi_columns,
        }
        if tbl.get('schema'):
            table_dict['schema'] = tbl['schema']

        # Check if this table has a custom SQL definition
        if tbl.get("type") == "derived" and tbl.get("sql"):
            table_dict["sql"] = tbl["sql"]
            table_dict["type"] = "custom_sql"

        tables.append(table_dict)

    # Add custom SQL as virtual tables
    for cs in bo_custom_sql:
        sql = cs.get("sql", "")
        name = cs.get("name", f"CustomSQL_{len(tables) + 1}")
        if sql and not any(t["name"] == name for t in tables):
            tables.append({
                "name": name,
                "columns": [],
                "sql": sql,
                "type": "custom_sql",
            })

    return tables


def _adapt_column(bo_col: dict) -> dict:
    """Convert a BO column dict to the generation-expected column shape."""
    qualification = bo_col.get("qualification", "dimension")
    role = "measure" if qualification == "measure" else "dimension"
    data_type = map_bo_to_powerbi_type(bo_col.get('data_type', 'string'))
    source_type = {'int64': 'integer', 'double': 'real', 'decimal': 'currency',
                   'dateTime': 'datetime'}.get(data_type, data_type)
    if str(bo_col.get('data_type', '')).strip().lower() == 'date':
        source_type = 'date'

    return {
        "name": bo_col.get("name", ""),
        "dataType": data_type,
        "datatype": source_type,
        "role": role,
        "caption": bo_col.get("description", bo_col.get("name", "")),
        "hidden": False,
        "description": bo_col.get("description", ""),
        "semantic_role": bo_col.get("semantic_role", ""),
    }


def _adapt_formula_to_calc(formula: dict, ds_name: str) -> dict:
    """Convert a BO formula to the calculations[] shape expected by generators."""
    qualification = formula.get("qualification", "measure")
    role = "measure" if qualification == "measure" else "dimension"
    name = formula.get("name", "")

    return {
        "name": name,
        "caption": name,
        "formula": formula.get("formula", ""),
        "role": role,
        "datatype": formula.get("data_type", "string"),
        "datasource_name": ds_name,
    }


# ───────────────────────────────────────────────────────────────
#  Relationships / Joins
# ───────────────────────────────────────────────────────────────

def _adapt_relationships(bo_joins: list) -> list[dict]:
    """Convert BO flat join dicts to nested left/right structure with cardinality."""
    # Map BO cardinality strings to TMDL values
    _CARDINALITY_MAP = {
        "one-to-one": "oneToOne",
        "one-to-many": "oneToMany",
        "many-to-one": "manyToOne",
        "many-to-many": "manyToMany",
        "1:1": "oneToOne",
        "1:n": "oneToMany",
        "1:*": "oneToMany",
        "n:1": "manyToOne",
        "*:1": "manyToOne",
        "n:n": "manyToMany",
        "*:*": "manyToMany",
    }

    relationships = []
    for join in bo_joins:
        bo_card = (join.get("cardinality", "") or "").lower().strip()
        cardinality = _CARDINALITY_MAP.get(bo_card, "manyToOne")

        join_type = (join.get("type", "inner") or "inner").lower()
        cross_filter = "bothDirections" if join_type == "full" else "oneDirection"

        relationships.append({
            "left": {
                "table": join.get("left_table", ""),
                "column": join.get("left_column", ""),
            },
            "right": {
                "table": join.get("right_table", ""),
                "column": join.get("right_column", ""),
            },
            "type": join_type,
            "cardinality": cardinality,
            "crossFilteringBehavior": cross_filter,
            "context": join.get("context", ""),
        })
    return relationships


def _ensure_join_columns(tables: list[dict], bo_joins: list) -> None:
    """Add join key columns to tables if they are missing.

    Join keys are often technical columns not extracted as business objects.
    This ensures the TMDL generator can validate relationships.
    """
    table_map: dict[str, dict] = {t["name"]: t for t in tables}

    for join in bo_joins:
        for side in ("left", "right"):
            tname = join.get(f"{side}_table", "")
            cname = join.get(f"{side}_column", "")
            if not tname or not cname:
                continue
            table = table_map.get(tname)
            if table is None:
                continue
            existing = {c.get("name", "") for c in table.get("columns", [])}
            if cname not in existing:
                table["columns"].append({
                    "name": cname,
                    "dataType": "Int64",
                    "sourceColumn": cname,
                    "isHidden": True,
                    "summarizeBy": "none",
                })


def _adapt_relationships_toplevel(extracted: dict) -> list[dict]:
    """Top-level relationships key for converted_objects."""
    return _adapt_relationships(extracted.get("joins", []))


# ───────────────────────────────────────────────────────────────
#  Worksheets  (report tabs + charts)
# ───────────────────────────────────────────────────────────────

def _adapt_worksheets(extracted: dict) -> list[dict]:
    """Convert BO reports/charts to worksheet dicts.

    Each chart becomes its own worksheet so multi-chart report tabs produce
    multiple visuals. Reports with no charts get a default tableEx worksheet.
    """
    reports = extracted.get("reports", [])
    charts = extracted.get("charts", [])

    # Index charts by report/tab name
    charts_by_report: dict[str, list[dict]] = {}
    for chart in charts:
        report_ref = chart.get("report", chart.get("tab", ""))
        charts_by_report.setdefault(report_ref, []).append(chart)

    worksheets = []
    for report in reports:
        report_name = report.get("name", "Report")
        report_charts = charts_by_report.get(report_name, [])

        if not report_charts:
            # No charts → one tableEx worksheet per report tab
            worksheets.append(_make_worksheet(
                name=report_name,
                chart_type="tableEx",
                fields=[],
                title=report.get("title", report_name),
                datasource=report.get("datasource", ""),
            ))
        elif len(report_charts) == 1:
            # Single chart → one worksheet named after the report tab
            chart = report_charts[0]
            worksheets.append(_make_worksheet(
                name=report_name,
                chart_type=_map_bo_chart_type(chart.get("type", "table")),
                fields=_extract_fields_from_chart(chart),
                title=report.get("title", report_name),
                datasource=report.get("datasource", ""),
            ))
        else:
            # Multiple charts → one worksheet per chart
            for idx, chart in enumerate(report_charts):
                chart_name = chart.get("name") or f"{report_name}_Chart{idx + 1}"
                worksheets.append(_make_worksheet(
                    name=chart_name,
                    chart_type=_map_bo_chart_type(chart.get("type", "table")),
                    fields=_extract_fields_from_chart(chart),
                    title=chart.get("title", chart_name),
                    datasource=report.get("datasource", ""),
                ))

    # If no reports but we have charts, create worksheets from charts
    if not worksheets and charts:
        for i, chart in enumerate(charts):
            worksheets.append(_make_worksheet(
                name=chart.get("name", f"Chart_{i + 1}"),
                chart_type=_map_bo_chart_type(chart.get("type", "table")),
                fields=_extract_fields_from_chart(chart),
                title=chart.get("name", ""),
                datasource="",
            ))

    # Enrich matrix worksheets with Crystal groups as dimensions/measures
    bo_groups = extracted.get("groups", [])
    if bo_groups:
        for ws in worksheets:
            if ws.get("chart_type") == "matrix":
                existing_fields = {f["name"] for f in ws.get("fields", [])}
                dims = list(ws.get("dimensions", []))
                for g in bo_groups:
                    col_name = g.get("object", "")
                    if col_name and col_name not in existing_fields:
                        ws["fields"].append({
                            "name": col_name,
                            "role": "dimension",
                            "aggregation": "",
                        })
                        existing_fields.add(col_name)
                    if col_name:
                        dims.append({"name": col_name, "field": col_name})
                ws["dimensions"] = dims

    return worksheets


def _make_worksheet(*, name, chart_type, fields, title, datasource, **extra):
    """Build a worksheet dict with both 'type' and 'chart_type' keys."""
    ws = {
        "name": name,
        "type": chart_type,
        "chart_type": chart_type,
        "fields": fields,
        "filters": [],
        "title": title,
        "datasource": datasource,
    }
    ws.update(extra)
    return ws


def _extract_fields_from_charts(charts: list[dict]) -> list[dict]:
    """Extract field references from a list of charts."""
    fields = []
    seen = set()
    for chart in charts:
        for f in _extract_fields_from_chart(chart):
            if f["name"] not in seen:
                fields.append(f)
                seen.add(f["name"])
    return fields


def _extract_fields_from_chart(chart: dict) -> list[dict]:
    """Extract field references from a single chart."""
    fields = []

    # Axes / dimensions
    for dim in chart.get("dimensions", chart.get("axes", [])):
        name = dim if isinstance(dim, str) else dim.get("name", "")
        if name:
            fields.append({"name": name, "role": "dimension", "aggregation": ""})

    # Measures / values
    for meas in chart.get("measures", chart.get("values", chart.get("series", []))):
        name = meas if isinstance(meas, str) else meas.get("name", "")
        if name:
            fields.append({"name": name, "role": "measure", "aggregation": "SUM"})

    return fields


_BO_CHART_TYPE_MAP = {
    # ── Bar / Column ─────────────────────────────────────────
    "bar": "clusteredBarChart",
    "horizontal_bar": "clusteredBarChart",
    "horizontal_stacked_bar": "stackedBarChart",
    "horizontal_100_stacked_bar": "hundredPercentStackedBarChart",
    "vertical_bar": "clusteredColumnChart",
    "column": "clusteredColumnChart",
    "stacked_bar": "stackedBarChart",
    "stacked_column": "stackedColumnChart",
    "100_stacked_bar": "hundredPercentStackedBarChart",
    "100_stacked_column": "hundredPercentStackedColumnChart",
    "3d_bar": "clusteredColumnChart",
    "3d_column": "clusteredColumnChart",
    "cylinder": "clusteredColumnChart",
    "cone": "clusteredColumnChart",
    "pyramid_bar": "clusteredColumnChart",
    # ── Line / Area ──────────────────────────────────────────
    "line": "lineChart",
    "dual_line": "lineChart",
    "3d_line": "lineChart",
    "area": "areaChart",
    "stacked_area": "stackedAreaChart",
    "100_stacked_area": "hundredPercentStackedAreaChart",
    "3d_area": "areaChart",
    "surface": "areaChart",
    "sparkline": "lineChart",
    # ── Combo ────────────────────────────────────────────────
    "combined": "lineClusteredColumnComboChart",
    "combined_bar_line": "lineClusteredColumnComboChart",
    "bar_line": "lineClusteredColumnComboChart",
    "dual_bar_line": "lineClusteredColumnComboChart",
    "dual_axis": "lineClusteredColumnComboChart",
    # ── Pie / Donut / Funnel ─────────────────────────────────
    "pie": "pieChart",
    "3d_pie": "pieChart",
    "ring": "donutChart",
    "donut": "donutChart",
    "semi_pie": "donutChart",
    "funnel": "funnel",
    # ── Scatter / Bubble ─────────────────────────────────────
    "scatter": "scatterChart",
    "point": "scatterChart",
    "bubble": "scatterChart",
    "3d_scatter": "scatterChart",
    "xy": "scatterChart",
    "xy_scatter": "scatterChart",
    # ── Radar / Polar ────────────────────────────────────────
    "radar": "lineChart",
    "spider": "lineChart",
    "polar": "lineChart",
    # ── Map ──────────────────────────────────────────────────
    "map": "map",
    "geo": "filledMap",
    "geo_map": "filledMap",
    "choropleth": "filledMap",
    # ── Table / Matrix / Crosstab ────────────────────────────
    "table": "tableEx",
    "crosstab": "matrix",
    "cross_tab": "matrix",
    "pivot": "matrix",
    "pivot_table": "matrix",
    "heatmap": "matrix",
    "heat_map": "matrix",
    # ── KPI / Card / Gauge ───────────────────────────────────
    "gauge": "gauge",
    "dial": "gauge",
    "speedometer": "gauge",
    "thermometer": "gauge",
    "kpi": "card",
    "text": "card",
    "number": "card",
    "indicator": "card",
    "summary": "card",
    # ── Treemap / Hierarchy ──────────────────────────────────
    "treemap": "treemap",
    "tree_map": "treemap",
    "sunburst": "sunburst",
    # ── Waterfall / Box ──────────────────────────────────────
    "waterfall": "waterfallChart",
    "boxplot": "boxAndWhisker",
    "box_plot": "boxAndWhisker",
    # ── Specialty ────────────────────────────────────────────
    "tag_cloud": "wordCloud",
    "word_cloud": "wordCloud",
    "cloud": "wordCloud",
    "ribbon": "ribbonChart",
    "image": "image",
    # ── Crystal Reports specific ─────────────────────────────
    "cross-tab": "matrix",
    "ole_object": "image",
    "subreport": "tableEx",
    "group_chart": "clusteredColumnChart",
}


def _map_bo_chart_type(bo_type: str) -> str:
    """Map a BO chart type to a PBI visual type."""
    if not bo_type:
        return "tableEx"
    key = bo_type.lower().strip()
    return _BO_CHART_TYPE_MAP.get(key, "tableEx")


# ───────────────────────────────────────────────────────────────
#  Dashboards
# ───────────────────────────────────────────────────────────────

def _adapt_dashboards(extracted: dict, adapted_worksheets: list[dict] | None = None) -> list[dict]:
    """Create dashboard(s) wrapping all worksheets and prompt slicers."""
    if adapted_worksheets:
        worksheet_names = [ws.get("name", "") for ws in adapted_worksheets if ws.get("name")]
    else:
        reports = extracted.get("reports", [])
        worksheet_names = [r.get("name", "") for r in reports if r.get("name")]

    if not worksheet_names:
        return []

    # Build dashboard objects: worksheet references + prompt slicers
    objects = []

    # Worksheet references
    for name in worksheet_names:
        objects.append({
            "type": "worksheetReference",
            "worksheetName": name,
            "name": name,
        })

    # Prompt → slicer (parameter_control) objects
    prompts = extracted.get("prompts", [])
    for prompt in prompts:
        pname = prompt.get("name", "")
        if pname:
            objects.append({
                "type": "parameter_control",
                "param_name": pname,
                "name": pname,
                "field": prompt.get("associated_dimension", pname),
            })

    return [{
        "name": "BO_Dashboard",
        "worksheets": worksheet_names,
        "objects": objects,
        "theme": {},
        "size": {"width": 1280, "height": 720},
    }]


# ───────────────────────────────────────────────────────────────
#  Calculations (top-level)
# ───────────────────────────────────────────────────────────────

def _adapt_calculations(extracted: dict) -> list[dict]:
    """Convert BO formulas to top-level calculations."""
    return [_adapt_formula_to_calc(f, "") for f in extracted.get("formulas", [])]


# ───────────────────────────────────────────────────────────────
#  Parameters  (from BO prompts)
# ───────────────────────────────────────────────────────────────

def _adapt_parameters(extracted: dict) -> list[dict]:
    """Convert BO prompts to What-If parameter definitions.

    The TMDL generator reads:
        name, caption, datatype ('integer'|'real'|'date'|'string'|'boolean'),
        value (default), domain_type ('list'|'range'|'any'),
        allowable_values (list of {type, value[, alias]}),
        associated_dimension (column for slicer binding).
    """
    # Map BO prompt types to TMDL-compatible types
    _TYPE_MAP = {
        "text": "string",
        "string": "string",
        "numeric": "real",
        "number": "real",
        "integer": "integer",
        "float": "real",
        "real": "real",
        "date": "date",
        "datetime": "date",
        "boolean": "boolean",
        "bool": "boolean",
    }

    params = []
    for prompt in extracted.get("prompts", []):
        name = prompt.get("name", "")
        if not name:
            continue

        ptype = prompt.get("type", "text").lower()
        defaults = prompt.get("default_values", [])
        multi = prompt.get("multi_value", False)
        lov_type = prompt.get("lov_type", "").lower()
        associated_dim = prompt.get("associated_dimension", "")

        datatype = _TYPE_MAP.get(ptype, "string")

        # Determine default value
        default_value = defaults[0] if defaults else ""

        # Determine domain type and build allowable_values list
        if defaults:
            domain_type = "list"
            allowable_values = [{"type": "list", "value": v} for v in defaults]
        elif datatype in ("integer", "real"):
            # Numeric prompts without LOV get a range
            domain_type = "range"
            allowable_values = [{"type": "range", "min": "0", "max": "100", "step": "1"}]
        else:
            domain_type = "any"
            allowable_values = []

        params.append({
            "name": name,
            "caption": name,
            "datatype": datatype,
            "value": default_value,
            "domain_type": domain_type,
            "allowable_values": allowable_values,
            "associated_dimension": associated_dim,
            "multi_value": multi,
            "lov_type": lov_type,
            "display_as": "dropdown" if multi or defaults else "text",
        })
    return params


# ───────────────────────────────────────────────────────────────
#  Filters
# ───────────────────────────────────────────────────────────────

def _adapt_filters(extracted: dict) -> list[dict]:
    """Convert BO filters to the generation-expected shape."""
    result = []
    for f in extracted.get("filters", []):
        col = f.get("object", f.get("column", ""))
        operator = f.get("operator", "=")

        # Map BO operators to PBI filter types
        if operator in ("in", "=", "InList"):
            ftype = "categorical"
            mode = "include"
        elif operator in ("not in", "!=", "NotInList"):
            ftype = "categorical"
            mode = "exclude"
        elif operator in (">", ">=", "<", "<=", "Between"):
            ftype = "range"
            mode = "include"
        else:
            ftype = "categorical"
            mode = "include"

        result.append({
            "column": col,
            "type": ftype,
            "values": f.get("values", []),
            "mode": mode,
            "datasource": f.get("datasource", ""),
        })
    return result


# ───────────────────────────────────────────────────────────────
#  Groups
# ───────────────────────────────────────────────────────────────

def _adapt_groups(extracted: dict) -> list[dict]:
    """Convert BO break groups to PBI group definitions."""
    result = []
    for g in extracted.get("groups", []):
        result.append({
            "name": g.get("name", g.get("object", "")),
            "field": g.get("object", g.get("column", "")),
            "type": "group",
            "members": [],
        })
    return result


# ───────────────────────────────────────────────────────────────
#  Hierarchies  (derived from universe column paths)
# ───────────────────────────────────────────────────────────────

def _adapt_hierarchies(extracted: dict) -> list[dict]:
    """Derive drill hierarchies from universe column path metadata."""
    columns = extracted.get("columns", [])

    path_groups: dict[str, list[str]] = {}
    for col in columns:
        path = col.get("path", "")
        if not path:
            continue
        parts = path.strip("\\").split("\\")
        if len(parts) >= 2:
            hier_name = parts[0]
            col_name = col.get("name", "")
            if col_name:
                path_groups.setdefault(hier_name, []).append(col_name)

    return [{"name": k, "levels": v} for k, v in path_groups.items()]


# ───────────────────────────────────────────────────────────────
#  Sorts
# ───────────────────────────────────────────────────────────────

def _adapt_sorts(extracted: dict) -> list[dict]:
    """Convert BO sorts to sort_orders."""
    result = []
    for s in extracted.get("sorts", []):
        result.append({
            "column": s.get("object", s.get("column", "")),
            "order": s.get("order", "ascending"),
        })
    return result


# ───────────────────────────────────────────────────────────────
#  Aliases
# ───────────────────────────────────────────────────────────────

def _adapt_aliases(extracted: dict) -> dict:
    """Build aliases dict from column descriptions / display names."""
    aliases = {}
    for col in extracted.get("columns", []):
        name = col.get("name", "")
        desc = col.get("description", "")
        if desc and desc != name:
            aliases[name] = desc
    return aliases


# ───────────────────────────────────────────────────────────────
#  Alerts → Conditional Formatting
# ───────────────────────────────────────────────────────────────

# BO operator → PBI conditional formatting operator
_ALERT_OP_MAP = {
    ">": "greaterThan",
    ">=": "greaterThanOrEqual",
    "<": "lessThan",
    "<=": "lessThanOrEqual",
    "=": "is",
    "==": "is",
    "!=": "isNot",
    "between": "between",
}


def _apply_alerts_to_worksheets(worksheets: list[dict], bo_alerts: list) -> None:
    """Enrich worksheets with conditional formatting rules from BO alerters.

    Each BO alert specifies an object (measure/column) and a color rule.
    We attach them to worksheets that reference the same field.
    """
    if not bo_alerts:
        return

    # Index worksheets by field name for fast lookup
    ws_by_field: dict[str, list[dict]] = {}
    for ws in worksheets:
        for f in ws.get("fields", []):
            fname = f.get("name", "")
            if fname:
                ws_by_field.setdefault(fname, []).append(ws)

    for alert in bo_alerts:
        obj_name = alert.get("object", alert.get("column", ""))
        if not obj_name:
            continue

        pbi_op = _ALERT_OP_MAP.get(alert.get("operator", ""), "greaterThan")
        color = alert.get("color", "#FF0000")
        value = alert.get("value", "0")
        icon = alert.get("icon", "")
        font_color = alert.get("font_color", "")
        bg_color = alert.get("background_color", color)

        rule = {
            "field": obj_name,
            "operator": pbi_op,
            "value": value,
            "formatting": {},
        }

        # Background color rule
        if bg_color:
            rule["formatting"]["backgroundColor"] = bg_color

        # Font color rule
        if font_color:
            rule["formatting"]["fontColor"] = font_color
        elif color and not font_color:
            rule["formatting"]["fontColor"] = color

        # Icon set mapping (BO alert icons → PBI icon set names)
        if icon:
            rule["formatting"]["iconSet"] = icon

        # Attach to matching worksheets
        targets = ws_by_field.get(obj_name, [])
        if targets:
            for ws in targets:
                ws.setdefault("conditionalFormatting", []).append(rule)
        else:
            # No field match → attach to all worksheets
            for ws in worksheets:
                ws.setdefault("conditionalFormatting", []).append(rule)


# ───────────────────────────────────────────────────────────────
#  Subreports → Drill-Through Pages + Actions
# ───────────────────────────────────────────────────────────────

def _adapt_subreports(extracted: dict) -> tuple[list[dict], list[dict]]:
    """Convert Crystal subreports to drill-through worksheets + filter actions.

    Returns:
        (worksheets, actions) tuple — worksheets are drill-through targets,
        actions wire up the filter context from parent to child.
    """
    subreports = extracted.get("subreports", [])
    worksheets: list[dict] = []
    actions: list[dict] = []

    for sub in subreports:
        sub_name = sub.get("name", "Subreport")
        link_fields = sub.get("link_fields", [])

        # Create a drill-through worksheet for the subreport
        worksheets.append({
            "name": sub_name,
            "type": "tableEx",
            "chart_type": "tableEx",
            "fields": [],
            "filters": [],
            "title": sub_name,
            "datasource": "",
            "pageType": "Drillthrough",
            "drillthrough_fields": [lf.get("child_field", "").split(".")[-1]
                                    for lf in link_fields if lf.get("child_field")],
        })

        # Create filter actions wiring parent fields → subreport page
        for lf in link_fields:
            parent_field = lf.get("parent_field", "").split(".")[-1]
            if parent_field:
                actions.append({
                    "type": "filter",
                    "source_field": parent_field,
                    "target_worksheet": sub_name,
                    "target_worksheets": [sub_name],
                    "field": parent_field,
                })

    return worksheets, actions
