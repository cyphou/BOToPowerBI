"""
Pre-Migration Assessment Module for BusinessObjects → Power BI.

Runs a comprehensive checklist against an extracted BO artifact
and produces a structured readiness report with:

- **Overall readiness score** (GREEN / YELLOW / RED)
- **Category-level checks** across 8 dimensions
- **Per-item findings** with severity (pass / warn / fail / info)
- **Recommendations** for manual review or remediation
- JSON + console output

Usage (CLI)::

    python migrate.py report.wid --assess

Usage (programmatic)::

    from powerbi_import.assessment import run_assessment, print_assessment_report
    report = run_assessment(extracted_data)
    print_assessment_report(report)
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Import security utilities for credential redaction
try:
    from security_validator import redact_credentials, scan_for_credentials
    _HAS_SECURITY = True
except ImportError:
    _HAS_SECURITY = False

# ── Severity levels ─────────────────────────────────────────────────

PASS = "pass"
INFO = "info"
WARN = "warn"
FAIL = "fail"

# ── Connector support tiers ─────────────────────────────────────────

_FULLY_SUPPORTED_CONNECTORS = frozenset({
    "Excel", "CSV", "SQL Server", "PostgreSQL", "MySQL",
    "GeoJSON", "OData", "Azure Blob", "ADLS",
    "Azure SQL", "Synapse", "Google Sheets", "SharePoint",
    "JSON", "XML", "PDF", "Web",
    # BO universe / direct connectors
    "sql_server", "oracle", "direct", "universe",
    "oledb", "odbc", "jdbc", "sqlserver", "postgres",
})

_PARTIALLY_SUPPORTED_CONNECTORS = frozenset({
    "BigQuery", "Oracle", "Snowflake", "Google Analytics",
    "Teradata", "SAP HANA", "SAP BW", "Redshift",
    "Databricks", "Spark", "Spark SQL", "Salesforce",
    "Vertica", "Impala", "Hadoop Hive", "Presto",
    "sap_hana", "sap_bw", "teradata", "informix", "db2",
})

_UNSUPPORTED_CONNECTORS = frozenset({
    "Splunk", "Marketo", "ServiceNow",
    "personal_data_provider", "local_csv",
})

# ── Unsupported BO functions (no DAX / PBI equivalent) ─────────────

_UNSUPPORTED_FUNCTIONS = re.compile(
    r'\b('
    r'GetLocale|GetContentLocale'
    r'|DocumentName|DocumentAuthor|DocumentDate'
    r'|ReportFilterSummary|PromptSummary'
    r'|DrillFilters|InputUser'
    r'|UserResponse|DocumentProperty'
    r')\s*\(',
    re.IGNORECASE,
)

# BO evaluation timing markers: warn, not fail (stripped in conversion)
_EVAL_TIMING_FUNCTIONS = re.compile(
    r'\b(WhilePrintingRecords|WhileReadingRecords|EvaluateAfter)\b',
    re.IGNORECASE,
)

_PARTIAL_FUNCTIONS = re.compile(
    r'\b('
    r'Previous|NoFilter|RefValue'
    r'|@Aggregate_Aware|Aggregate_Aware'
    r'|Percentage|Interpolation'
    r'|RelativeValue|Rank\b'
    r')\s*\(',
    re.IGNORECASE,
)

# BO context operator patterns (complex conversion)
_CONTEXT_PATTERN = re.compile(
    r'\b(In|ForEach|ForAll)\s*\(', re.IGNORECASE,
)

_BO_RUNNING_CALC_PATTERN = re.compile(
    r'\b(RunningSum|RunningCount|RunningAverage|RunningMax|RunningMin|RunningProduct)\s*\(',
    re.IGNORECASE,
)

# ── Chart type mapping (from visual_generator.VISUAL_TYPE_MAP) ──────

_MAPPED_CHART_TYPES = frozenset({
    "barchart", "bar", "stackedbarchart", "stacked-bar",
    "100stackedbarchart", "100-stacked-bar",
    "columnchart", "column", "stackedcolumnchart", "stacked-column",
    "100stackedcolumnchart", "100-stacked-column", "histogram",
    "linechart", "line", "areachart", "area",
    "stackedareachart", "stacked-area", "100stackedareachart",
    "sparkline",
    "combo", "combochart", "linecolumnchart", "lineclusteredcolumncombochart",
    "piechart", "pie", "donutchart", "donut", "funnel", "funnelchart",
    "semicircle", "ring",
    "scatter", "scatterplot", "scatterchart", "bubble", "bubblechart",
    "circle", "shape", "dot", "dotplot", "packedbubble", "stripplot",
    "map", "geomap", "density", "filledmap", "polygon", "multipolygon",
    "shapemap",
    "table", "text", "automatic", "straight-table", "straighttable",
    "tableex", "pivot-table", "pivottable", "pivot", "matrix",
    "heatmap", "highlighttable", "calendar",
    "kpi", "card", "multirowcard", "multi-kpi",
    "gauge", "meter", "bullet", "radial", "lollipop",
    "treemap", "square", "hex", "sunburst", "decompositiontree",
    "waterfall", "waterfallchart", "boxplot", "box-and-whisker",
    "ribbon", "ribbonchart",
    "gantt", "timeline",
    "wordcloud", "tagcloud",
    # Power BI native chart type names (may appear verbatim)
    "clusteredbarchart", "stackedbarchart", "clusteredcolumnchart",
    "stackedcolumnchart", "linechart", "areachart", "piechart",
    "donutchart", "funnelchart", "scatterchart",
})


# ═══════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CheckItem:
    """A single checklist item with a finding."""
    category: str
    name: str
    severity: str           # pass | info | warn | fail
    detail: str
    recommendation: str = ""


@dataclass
class CategoryResult:
    """Aggregated result for one assessment category."""
    name: str
    checks: List[CheckItem] = field(default_factory=list)

    @property
    def worst_severity(self) -> str:
        sev_order = {PASS: 0, INFO: 1, WARN: 2, FAIL: 3}
        if not self.checks:
            return PASS
        return max(self.checks, key=lambda c: sev_order.get(c.severity, 0)).severity

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.severity == PASS)

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.severity == WARN)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.severity == FAIL)


@dataclass
class AssessmentReport:
    """Complete pre-migration assessment report."""
    workbook_name: str
    timestamp: str
    categories: List[CategoryResult] = field(default_factory=list)
    summary: Dict = field(default_factory=dict)

    @property
    def overall_score(self) -> str:
        """GREEN / YELLOW / RED based on worst severity across categories."""
        fail_count = sum(c.fail_count for c in self.categories)
        warn_count = sum(c.warn_count for c in self.categories)
        if fail_count > 0:
            return "RED"
        if warn_count > 0:
            return "YELLOW"
        return "GREEN"

    @property
    def total_checks(self) -> int:
        return sum(len(c.checks) for c in self.categories)

    @property
    def total_pass(self) -> int:
        return sum(c.pass_count for c in self.categories)

    @property
    def total_warn(self) -> int:
        return sum(c.warn_count for c in self.categories)

    @property
    def total_fail(self) -> int:
        return sum(c.fail_count for c in self.categories)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "workbook_name": self.workbook_name,
            "timestamp": self.timestamp,
            "overall_score": self.overall_score,
            "summary": self.summary,
            "totals": {
                "checks": self.total_checks,
                "pass": self.total_pass,
                "warn": self.total_warn,
                "fail": self.total_fail,
            },
            "categories": [
                {
                    "name": cat.name,
                    "worst_severity": cat.worst_severity,
                    "checks": [
                        {
                            "name": ck.name,
                            "severity": ck.severity,
                            "detail": ck.detail,
                            "recommendation": ck.recommendation,
                        }
                        for ck in cat.checks
                    ],
                }
                for cat in self.categories
            ],
        }


# ═══════════════════════════════════════════════════════════════════
#  Assessment checks — one function per category
# ═══════════════════════════════════════════════════════════════════

def _check_datasources(extracted: Dict) -> CategoryResult:
    """Category 1: Datasource Compatibility."""
    cat = CategoryResult(name="Datasource Compatibility")
    datasources = extracted.get("datasources", [])

    if not datasources:
        cat.checks.append(CheckItem(
            cat.name, "No datasources found", WARN,
            "No datasource definitions were extracted.",
            "Verify the BO artifact contains at least one datasource.",
        ))
        return cat

    cat.checks.append(CheckItem(
        cat.name, "Datasource count", INFO,
        f"{len(datasources)} datasource(s) detected.",
    ))

    # Connection types
    connector_types: Dict[str, list] = {}
    for ds in datasources:
        ds_name = ds.get("name") or "?"
        # Skip Parameters-only datasource — not a real connector
        if ds_name == "Parameters" or ds_name.startswith("Parameters."):
            continue
        conn = ds.get("connection", {})
        conn_type = conn.get("type") or "Unknown"
        # If type is Unknown, try to infer from datasource name prefix
        if conn_type == "Unknown" and "." in ds_name:
            prefix = ds_name.split(".")[0].lower()
            if prefix in _FULLY_SUPPORTED_CONNECTORS:
                conn_type = prefix
            elif prefix in ("sqlproxy",):
                conn_type = "sqlproxy"
        connector_types.setdefault(conn_type, []).append(ds_name)

    for conn_type, ds_names in connector_types.items():
        if conn_type in _FULLY_SUPPORTED_CONNECTORS:
            cat.checks.append(CheckItem(
                cat.name, f"Connector: {conn_type}", PASS,
                f"Fully supported in Power BI. Used by: {', '.join(ds_names)}.",
            ))
        elif conn_type in _PARTIALLY_SUPPORTED_CONNECTORS:
            cat.checks.append(CheckItem(
                cat.name, f"Connector: {conn_type}", WARN,
                f"Partially supported (may require a Power BI gateway or "
                f"custom connector). Used by: {', '.join(ds_names)}.",
                "Configure an on-premises data gateway or use a certified "
                "Power BI connector for this data source.",
            ))
        elif conn_type in _UNSUPPORTED_CONNECTORS:
            cat.checks.append(CheckItem(
                cat.name, f"Connector: {conn_type}", FAIL,
                f"Not natively supported in Power BI. "
                f"Used by: {', '.join(ds_names)}.",
                "Consider migrating data to a supported source (e.g. Azure SQL, "
                "Excel, CSV) or use a custom Power Query connector.",
            ))
        elif conn_type == "sqlproxy":
            cat.checks.append(CheckItem(
                cat.name, "Connector: sqlproxy (relay)", PASS,
                f"Proxy relay detected. Used by: {', '.join(ds_names)}. "
                "The underlying datasource type is supported.",
            ))
        elif conn_type == "Unknown":
            cat.checks.append(CheckItem(
                cat.name, "Connector: Unknown", WARN,
                f"Could not detect connection type for: {', '.join(ds_names)}.",
                "Review datasource connections manually.",
            ))
        else:
            cat.checks.append(CheckItem(
                cat.name, f"Connector: {conn_type}", WARN,
                f"Unrecognised connector. Used by: {', '.join(ds_names)}.",
                "Verify manually whether Power BI supports this connector type.",
            ))

    # Data blending — filter out virtual "Parameters" datasource links
    blending = [
        b for b in extracted.get("data_blending", [])
        if b.get("secondary_datasource", "") != "Parameters"
           and b.get("datasource", "") != "Parameters"
    ]
    if blending:
        cat.checks.append(CheckItem(
            cat.name, "Data blending", INFO,
            f"{len(blending)} cross-datasource blending link(s) detected. "
            "Auto-converted: relationships generated in Semantic Model.",
            "Review generated relationships in the Semantic Model "
            "to confirm join keys match original blending links.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Data blending", PASS,
            "No cross-datasource data blending detected.",
        ))

    # Published datasources
    published = extracted.get("published_datasources", [])
    if published:
        pub_names = ", ".join(p.get("name", "?") for p in published[:3])
        cat.checks.append(CheckItem(
            cat.name, "Published datasources", INFO,
            f"{len(published)} published datasource reference(s): {pub_names}. "
            "Connection will need to be re-pointed to the actual data source in Power BI.",
            "Verify that the published datasource schema matches "
            "the data source configured in the Power BI Semantic Model.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Published datasources", PASS,
            "No published datasource references.",
        ))

    # Custom SQL
    custom_sql = extracted.get("custom_sql", [])
    if custom_sql:
        cat.checks.append(CheckItem(
            cat.name, "Custom SQL", INFO,
            f"{len(custom_sql)} custom SQL query/queries detected. "
            "Auto-converted: embedded as native SQL passthrough in Power Query M.",
            "Review the generated Power Query M for SQL compatibility "
            "with the target database.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Custom SQL", PASS,
            "No custom SQL queries.",
        ))

    return cat


def _check_calculations(extracted: Dict) -> CategoryResult:
    """Category 2: Calculation Readiness."""
    cat = CategoryResult(name="Calculation Readiness")
    calculations = extracted.get("calculations", [])

    if not calculations:
        cat.checks.append(CheckItem(
            cat.name, "No calculations", PASS,
            "No calculated fields detected.",
        ))
        return cat

    cat.checks.append(CheckItem(
        cat.name, "Calculation count", INFO,
        f"{len(calculations)} calculated field(s) detected.",
    ))

    # Classify
    unsupported = []
    partial = []
    eval_timing_calcs = []
    context_calcs = []
    running_calcs = []

    for calc in calculations:
        formula = calc.get("formula", "")
        name = calc.get("caption", calc.get("name", "?"))

        if _UNSUPPORTED_FUNCTIONS.search(formula):
            unsupported.append(name)
        if _EVAL_TIMING_FUNCTIONS.search(formula):
            eval_timing_calcs.append(name)
        if _PARTIAL_FUNCTIONS.search(formula):
            partial.append(name)
        if _CONTEXT_PATTERN.search(formula):
            context_calcs.append(name)
        if _BO_RUNNING_CALC_PATTERN.search(formula):
            running_calcs.append(name)

    # Results
    if unsupported:
        names_preview = ", ".join(unsupported[:5])
        extra = f" (+{len(unsupported) - 5} more)" if len(unsupported) > 5 else ""
        cat.checks.append(CheckItem(
            cat.name, "Unsupported functions", FAIL,
            f"{len(unsupported)} calculation(s) use functions with no DAX equivalent: "
            f"{names_preview}{extra}.",
            "GetLocale, DocumentName, ReportFilterSummary, PromptSummary "
            "and similar BO metadata functions have no Power BI equivalent. "
            "Manual rewrite or removal is required.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Unsupported functions", PASS,
            "No calculations use unsupported functions.",
        ))

    if eval_timing_calcs:
        names_preview = ", ".join(eval_timing_calcs[:5])
        extra = f" (+{len(eval_timing_calcs) - 5} more)" if len(eval_timing_calcs) > 5 else ""
        cat.checks.append(CheckItem(
            cat.name, "Evaluation timing markers", WARN,
            f"{len(eval_timing_calcs)} calculation(s) use BO evaluation timing "
            f"(WhilePrintingRecords / WhileReadingRecords): "
            f"{names_preview}{extra}.",
            "Evaluation timing markers are stripped during conversion. "
            "Power BI handles evaluation order differently — verify "
            "measure results match the original BO report.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Evaluation timing markers", PASS,
            "No BO evaluation timing markers detected.",
        ))

    if partial:
        names_preview = ", ".join(partial[:5])
        extra = f" (+{len(partial) - 5} more)" if len(partial) > 5 else ""
        cat.checks.append(CheckItem(
            cat.name, "Partially-supported functions", WARN,
            f"{len(partial)} calculation(s) use partially-supported functions: "
            f"{names_preview}{extra}.",
            "Previous, NoFilter, @Aggregate_Aware, Percentage, "
            "and Rank may require manual DAX conversion review.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Partially-supported functions", PASS,
            "No calculations use partially-supported functions.",
        ))

    if context_calcs:
        names_preview = ", ".join(context_calcs[:5])
        extra = f" (+{len(context_calcs) - 5} more)" if len(context_calcs) > 5 else ""
        cat.checks.append(CheckItem(
            cat.name, "Context operators", INFO,
            f"{len(context_calcs)} context operator expression(s) (In/ForEach/ForAll): "
            f"{names_preview}{extra}. "
            "Auto-converted to DAX CALCULATE + ALLEXCEPT/REMOVEFILTERS.",
            "Review generated DAX measures for correctness — "
            "In→CALCULATE+filter, ForEach→SUMX, ForAll→ALLEXCEPT.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Context operators", PASS,
            "No BO context operators (In/ForEach/ForAll) detected.",
        ))

    if running_calcs:
        names_preview = ", ".join(running_calcs[:5])
        extra = f" (+{len(running_calcs) - 5} more)" if len(running_calcs) > 5 else ""
        cat.checks.append(CheckItem(
            cat.name, "Running calculations", INFO,
            f"{len(running_calcs)} running calculation(s) (RunningSum/Count/Avg/Max/Min): "
            f"{names_preview}{extra}. "
            "Auto-converted to DAX CALCULATE / window functions.",
            "Verify sort order and partitioning match BO behavior.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Running calculations", PASS,
            "No running calculations detected.",
        ))

    return cat


def _check_visuals(extracted: Dict) -> CategoryResult:
    """Category 3: Visual & Dashboard Coverage."""
    cat = CategoryResult(name="Visual & Dashboard Coverage")
    worksheets = extracted.get("worksheets", [])
    dashboards = extracted.get("dashboards", [])

    cat.checks.append(CheckItem(
        cat.name, "Worksheet count", INFO,
        f"{len(worksheets)} worksheet(s) detected.",
    ))
    cat.checks.append(CheckItem(
        cat.name, "Dashboard count", INFO,
        f"{len(dashboards)} dashboard(s) detected.",
    ))

    # Chart type coverage
    unmapped_types = set()
    mapped_types = set()
    for ws in worksheets:
        chart_type = ws.get("chart_type", ws.get("mark_type", "")).lower().strip()
        if not chart_type:
            continue
        if chart_type in _MAPPED_CHART_TYPES:
            mapped_types.add(chart_type)
        else:
            unmapped_types.add(chart_type)

    if unmapped_types:
        cat.checks.append(CheckItem(
            cat.name, "Unmapped chart types", WARN,
            f"{len(unmapped_types)} chart type(s) not in mapping: "
            f"{', '.join(sorted(unmapped_types))}.",
            "These will fall back to 'table' visual. Consider customising "
            "the visual type after migration.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Chart type coverage", PASS,
            f"All {len(mapped_types)} chart type(s) have Power BI equivalents.",
        ))

    # Viz-in-tooltip
    viz_in_tooltip = sum(
        1 for ws in worksheets
        if any(t.get("is_viz_tooltip") for t in ws.get("tooltips", [{}]))
    )
    if viz_in_tooltip:
        cat.checks.append(CheckItem(
            cat.name, "Viz-in-tooltip", WARN,
            f"{viz_in_tooltip} worksheet(s) use Viz-in-Tooltip.",
            "Power BI supports report page tooltips — verify layout and "
            "page size after migration.",
        ))

    # Dual axis
    dual_axis = sum(
        1 for ws in worksheets if ws.get("dual_axis", {}).get("has_dual_axis")
    )
    if dual_axis:
        cat.checks.append(CheckItem(
            cat.name, "Dual axis charts", WARN,
            f"{dual_axis} worksheet(s) use dual axis.",
            "Dual axis is mapped to combo charts. Verify axis scaling "
            "and synchronisation.",
        ))

    # Device layouts
    device_layouts = sum(
        1 for db in dashboards if db.get("device_layouts")
    )
    if device_layouts:
        cat.checks.append(CheckItem(
            cat.name, "Device layouts", INFO,
            f"{device_layouts} dashboard(s) have device-specific layouts.",
            "Power BI mobile layouts must be configured manually in "
            "Power BI Desktop.",
        ))

    # Sprint 79: Formatting coverage sub-metric
    color_encoded = 0
    cond_format_count = 0
    custom_font_count = 0
    for ws in worksheets:
        me = ws.get('mark_encoding', {})
        if me.get('color', {}).get('field'):
            color_encoded += 1
        if ws.get('conditionalFormatting'):
            cond_format_count += len(ws['conditionalFormatting'])
        fmt = ws.get('formatting', {})
        if fmt.get('font_family') or fmt.get('font_size'):
            custom_font_count += 1
    fmt_total = color_encoded + cond_format_count + custom_font_count
    if fmt_total > 0:
        cat.checks.append(CheckItem(
            cat.name, "Formatting coverage", INFO,
            f"{color_encoded} color-encoded field(s), {cond_format_count} "
            f"conditional formatting rule(s), {custom_font_count} custom "
            f"font worksheet(s).",
            "Color encoding migrates as gradient/categorical rules. "
            "Custom fonts map to web-safe equivalents.",
        ))

    return cat


def _check_filters(extracted: Dict) -> CategoryResult:
    """Category 4: Filter & Parameter Complexity."""
    cat = CategoryResult(name="Filter & Parameter Complexity")
    filters = extracted.get("filters", [])
    parameters = extracted.get("parameters", [])

    cat.checks.append(CheckItem(
        cat.name, "Filter count", INFO,
        f"{len(filters)} top-level filter(s) detected.",
    ))
    cat.checks.append(CheckItem(
        cat.name, "Parameter count", INFO,
        f"{len(parameters)} parameter(s) detected.",
    ))

    # User filters → RLS
    user_filters = extracted.get("user_filters", [])
    if user_filters:
        cat.checks.append(CheckItem(
            cat.name, "User filters (RLS)", INFO,
            f"{len(user_filters)} user filter(s) / security calculation(s) detected. "
            "Auto-converted to TMDL RLS roles in roles.tmdl.",
            "Assign users/groups to the generated RLS roles in "
            "Power BI workspace security settings.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "User filters (RLS)", PASS,
            "No user filters — no RLS configuration needed.",
        ))

    # Parameters with allowable values
    complex_params = [
        p for p in parameters
        if p.get("allowable_values") and len(p.get("allowable_values", [])) > 20
    ]
    if complex_params:
        cat.checks.append(CheckItem(
            cat.name, "Complex parameters", INFO,
            f"{len(complex_params)} parameter(s) with >20 allowable values. "
            "Auto-converted to What-If parameter tables with GENERATESERIES/DATATABLE.",
            "Consider whether a slicer on an existing dimension would "
            "be more performant for very large domains.",
        ))

    return cat


def _check_data_model(extracted: Dict) -> CategoryResult:
    """Category 5: Data Model Complexity."""
    cat = CategoryResult(name="Data Model Complexity")
    datasources = extracted.get("datasources", [])

    # Table / column counts
    total_tables = 0
    total_columns = 0
    for ds in datasources:
        tables = ds.get("tables", [])
        total_tables += len(tables)
        for tbl in tables:
            total_columns += len(tbl.get("columns", []))
        total_columns += len(ds.get("columns", []))

    cat.checks.append(CheckItem(
        cat.name, "Table count", INFO if total_tables <= 20 else WARN,
        f"{total_tables} table(s) across all datasources.",
        "Large table counts increase model complexity." if total_tables > 20 else "",
    ))
    cat.checks.append(CheckItem(
        cat.name, "Column count", INFO if total_columns <= 200 else WARN,
        f"{total_columns} column(s) total.",
        "Wide schemas may benefit from selective column import via Power Query." if total_columns > 200 else "",
    ))

    # Relationships
    total_rels = sum(len(ds.get("relationships", [])) for ds in datasources)
    cat.checks.append(CheckItem(
        cat.name, "Relationship count", INFO,
        f"{total_rels} relationship(s) detected.",
        "" if total_rels <= 30 else "Large relationship graphs require careful review in the Semantic Model.",
    ))

    # Hierarchies
    hierarchies = extracted.get("hierarchies", [])
    cat.checks.append(CheckItem(
        cat.name, "Hierarchies", PASS if hierarchies else INFO,
        f"{len(hierarchies)} hierarchy/hierarchies detected." if hierarchies else "No hierarchies.",
    ))

    # Sets / Groups / Bins
    sets = extracted.get("sets", [])
    groups = extracted.get("groups", [])
    bins = extracted.get("bins", [])
    advanced_features = []
    if sets:
        advanced_features.append(f"{len(sets)} set(s)")
    if groups:
        advanced_features.append(f"{len(groups)} group(s)")
    if bins:
        advanced_features.append(f"{len(bins)} bin(s)")

    if advanced_features:
        cat.checks.append(CheckItem(
            cat.name, "Sets / Groups / Bins", INFO,
            f"Advanced data features: {', '.join(advanced_features)}.",
            "Sets → calculated columns, Groups → SWITCH measures, "
            "Bins → calculated columns with ROUNDDOWN.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Sets / Groups / Bins", PASS,
            "No sets, groups, or bins.",
        ))

    return cat


def _check_interactivity(extracted: Dict) -> CategoryResult:
    """Category 6: Interactivity & Actions."""
    cat = CategoryResult(name="Interactivity & Actions")
    actions = extracted.get("actions", [])
    stories = extracted.get("stories", [])

    # Check for pages shelf / dynamic zones before early return
    worksheets = extracted.get("worksheets", [])
    dashboards = extracted.get("dashboards", [])
    has_pages_shelf = any(
        ws.get("pages_shelf") and ws["pages_shelf"].get("field")
        for ws in worksheets
    )
    dz_count = sum(
        len(db.get("dynamic_zone_visibility", []))
        for db in dashboards
    )

    if not actions and not stories and not has_pages_shelf and not dz_count:
        cat.checks.append(CheckItem(
            cat.name, "No actions or stories", PASS,
            "No interactivity features detected.",
        ))
        return cat

    # Action types
    action_types: Dict[str, int] = {}
    for a in actions:
        atype = a.get("type", "").strip() or "filter"
        action_types[atype] = action_types.get(atype, 0) + 1

    for atype, count in action_types.items():
        if atype in ("filter", "highlight"):
            cat.checks.append(CheckItem(
                cat.name, f"Action: {atype}", PASS,
                f"{count} {atype} action(s) — natively supported in Power BI.",
            ))
        elif atype == "url":
            cat.checks.append(CheckItem(
                cat.name, "Action: URL", INFO,
                f"{count} URL action(s) — auto-mapped to Power BI action buttons.",
                "Verify URL patterns and parameterization after migration.",
            ))
        elif atype == "set":
            cat.checks.append(CheckItem(
                cat.name, "Action: Set", WARN,
                f"{count} set action(s) — approximated via bookmarks.",
                "Set actions have limited Power BI support. Review behavior.",
            ))
        else:
            cat.checks.append(CheckItem(
                cat.name, f"Action: {atype}", WARN,
                f"{count} {atype} action(s) — may require manual configuration.",
            ))

    # Stories
    if stories:
        total_points = sum(len(s.get("story_points", [])) for s in stories)
        cat.checks.append(CheckItem(
            cat.name, "Stories", INFO,
            f"{len(stories)} story/stories with {total_points} story point(s) → bookmarks.",
            "Stories are converted to bookmarks. Review bookmark state "
            "and navigator after migration.",
        ))

    # Pages shelf / motion charts (animation)
    pages_worksheets = [
        ws.get("name", "?") for ws in worksheets
        if ws.get("pages_shelf") and ws["pages_shelf"].get("field")
    ]
    if pages_worksheets:
        cat.checks.append(CheckItem(
            cat.name, "Pages Shelf / Animation", WARN,
            f"{len(pages_worksheets)} worksheet(s) use Pages shelf (animation): "
            f"{', '.join(pages_worksheets[:5])}.",
            "BO Pages field animates through dimension values. "
            "Converted to a slicer. Power BI Play Axis (preview) may "
            "offer similar animation — enable it manually if needed.",
        ))

    # Dynamic zone visibility (sheet-swap)
    if dz_count:
        cat.checks.append(CheckItem(
            cat.name, "Dynamic Zone Visibility", INFO,
            f"{dz_count} dynamic zone(s) detected → converted to bookmarks.",
            "Dynamic zone visibility (sheet-swap) is approximated via "
            "bookmarks. Configure visual visibility toggles in PBI Desktop.",
        ))

    return cat


def _check_extract_and_packaging(extracted: Dict) -> CategoryResult:
    """Category 7: Data Extracts & Packaging."""
    cat = CategoryResult(name="Data Extracts & Packaging")

    hyper_files = extracted.get("hyper_files", [])
    custom_shapes = extracted.get("custom_shapes", [])
    embedded_fonts = extracted.get("embedded_fonts", [])

    # .hyper extracts
    if hyper_files:
        total_size_mb = sum(h.get("size_bytes", 0) for h in hyper_files) / (1024 * 1024)
        cat.checks.append(CheckItem(
            cat.name, "Hyper extract files", INFO,
            f"{len(hyper_files)} .hyper file(s) detected ({total_size_mb:.1f} MB total).",
            "Hyper extracts indicate embedded data. Data will need to be "
            "imported via Power Query or connected to a live data source.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Hyper extract files", PASS,
            "No .hyper extract files (live connection or datasource files).",
        ))

    # Custom shapes
    if custom_shapes:
        cat.checks.append(CheckItem(
            cat.name, "Custom shapes", WARN,
            f"{len(custom_shapes)} custom shape file(s) detected.",
            "Custom shapes are not supported in Power BI. Consider using "
            "conditional formatting with icons instead.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Custom shapes", PASS,
            "No custom shapes.",
        ))

    # Embedded fonts
    if embedded_fonts:
        cat.checks.append(CheckItem(
            cat.name, "Embedded fonts", WARN,
            f"{len(embedded_fonts)} embedded font file(s) detected.",
            "Custom fonts must be installed in the Power BI tenant or "
            "replaced with standard fonts.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Embedded fonts", PASS,
            "No embedded fonts.",
        ))

    # Custom geocoding
    geocoding = extracted.get("custom_geocoding", [])
    custom_geo_files = [g for g in geocoding if g.get("type") == "custom_file"]
    if custom_geo_files:
        cat.checks.append(CheckItem(
            cat.name, "Custom geocoding", WARN,
            f"{len(custom_geo_files)} custom geocoding file(s) detected.",
            "Import custom geocoding CSVs into a lookup table and join "
            "in Power Query or the Semantic Model.",
        ))

    return cat


def _check_migration_scope(extracted: Dict) -> CategoryResult:
    """Category 8: Migration Scope & Effort Estimate."""
    cat = CategoryResult(name="Migration Scope & Effort")

    worksheets = extracted.get("worksheets", [])
    dashboards = extracted.get("dashboards", [])
    datasources = extracted.get("datasources", [])
    calculations = extracted.get("calculations", [])
    parameters = extracted.get("parameters", [])
    filters = extracted.get("filters", [])
    user_filters = extracted.get("user_filters", [])
    actions = extracted.get("actions", [])
    stories = extracted.get("stories", [])
    sets = extracted.get("sets", [])
    groups = extracted.get("groups", [])
    bins = extracted.get("bins", [])
    hierarchies = extracted.get("hierarchies", [])
    sort_orders = extracted.get("sort_orders", [])
    custom_sql = extracted.get("custom_sql", [])

    # Complexity score (simple heuristic)
    complexity = 0
    complexity += len(worksheets) * 1
    complexity += len(dashboards) * 2
    complexity += len(datasources) * 2
    complexity += len(calculations) * 1
    complexity += len(parameters) * 1
    complexity += len(filters) * 0.5
    complexity += len(user_filters) * 3
    complexity += len(actions) * 1
    complexity += len(stories) * 2
    complexity += len(sets) * 1
    complexity += len(groups) * 1
    complexity += len(bins) * 1
    complexity += len(hierarchies) * 0.5
    complexity += len(custom_sql) * 3

    # Count unsupported features for weighting
    for calc in calculations:
        formula = calc.get("formula", "")
        if _UNSUPPORTED_FUNCTIONS.search(formula):
            complexity += 5
        elif _PARTIAL_FUNCTIONS.search(formula):
            complexity += 2
        elif _CONTEXT_PATTERN.search(formula):
            complexity += 1
        elif _BO_RUNNING_CALC_PATTERN.search(formula):
            complexity += 1

    if complexity <= 20:
        level = "Low"
        estimate = "< 1 hour of post-migration review"
    elif complexity <= 60:
        level = "Medium"
        estimate = "1-4 hours of post-migration review"
    elif complexity <= 150:
        level = "High"
        estimate = "4-8 hours of post-migration review"
    else:
        level = "Very High"
        estimate = "8+ hours — consider phased migration"

    cat.checks.append(CheckItem(
        cat.name, "Complexity score", INFO,
        f"Complexity score: {complexity:.0f} ({level}).",
    ))
    cat.checks.append(CheckItem(
        cat.name, "Estimated effort", INFO,
        f"Estimated post-migration review effort: {estimate}.",
    ))

    # Object inventory
    inventory_lines = []
    obj_counts = [
        ("Datasources", len(datasources)),
        ("Worksheets", len(worksheets)),
        ("Dashboards", len(dashboards)),
        ("Calculations", len(calculations)),
        ("Parameters", len(parameters)),
        ("Filters", len(filters)),
        ("User Filters / RLS", len(user_filters)),
        ("Actions", len(actions)),
        ("Stories", len(stories)),
        ("Sets", len(sets)),
        ("Groups", len(groups)),
        ("Bins", len(bins)),
        ("Hierarchies", len(hierarchies)),
        ("Sort Orders", len(sort_orders)),
        ("Custom SQL", len(custom_sql)),
    ]
    for label, count in obj_counts:
        if count > 0:
            inventory_lines.append(f"{label}: {count}")

    cat.checks.append(CheckItem(
        cat.name, "Object inventory", INFO,
        "Objects: " + " | ".join(inventory_lines) if inventory_lines else "Empty workbook.",
    ))

    # ── Advanced BO feature detection ──
    _modern_features = []

    # Dynamic zone visibility (worksheets with visibility rules)
    for ws in worksheets:
        if ws.get('dynamic_visibility') or ws.get('zone_visibility'):
            _modern_features.append('Dynamic Zone Visibility')
            break

    # Dynamic parameters with DB queries
    for param in parameters:
        if param.get('query') or param.get('domain_type') == 'database':
            _modern_features.append('Dynamic Parameters (DB query)')
            break

    # Dynamic axis formatting / combined axis
    for ws in worksheets:
        axes = ws.get('axes', {})
        if isinstance(axes, dict):
            for ax in axes.values():
                if isinstance(ax, dict) and (ax.get('combined_axis') or ax.get('synchronized')):
                    _modern_features.append('Combined/Synchronized Axes')
                    break

    # Data-driven alert calculations / freehand SQL
    for calc in calculations:
        formula = calc.get('formula', '')
        if 'FREEHAND' in formula.upper() or '@SQL' in formula.upper():
            _modern_features.append('Freehand SQL / @SQL References')
            break

    if _modern_features:
        cat.checks.append(CheckItem(
            cat.name, "Advanced BO features", WARN,
            f"Detected advanced BO features: {', '.join(_modern_features)}. "
            "These require manual review after migration.",
            recommendation="Review each advanced feature and map to Power BI equivalents manually.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Advanced BO features", PASS,
            "No advanced BO-specific features detected.",
        ))

    return cat


# ── Sensitive credential patterns (connection string audit) ─────

_SENSITIVE_PATTERNS = [
    (re.compile(r'(?:password|passwd|pwd)\s*=\s*\S+', re.IGNORECASE), 'password'),
    (re.compile(r'(?:secret|token|apikey|api_key|api-key)\s*=\s*\S+', re.IGNORECASE), 'secret/token'),
    (re.compile(r'(?:access.?key|account.?key)\s*=\s*\S+', re.IGNORECASE), 'access key'),
    (re.compile(r'(?:private.?key)\s*=\s*\S+', re.IGNORECASE), 'private key'),
    (re.compile(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*', re.IGNORECASE), 'bearer token'),
    (re.compile(r'Basic\s+[A-Za-z0-9+/]+=*', re.IGNORECASE), 'basic auth'),
]


def _check_connection_strings(extracted: Dict) -> CategoryResult:
    """Category 9: Connection String Security Audit."""
    cat = CategoryResult(name="Connection String Security")
    datasources = extracted.get("datasources", [])

    if not datasources:
        cat.checks.append(CheckItem(
            cat.name, "No datasources", PASS,
            "No datasource connections to audit.",
        ))
        return cat

    sensitive_found = []

    for ds in datasources:
        ds_name = ds.get("name") or ds.get("caption", "?")
        conn = ds.get("connection", {})

        # Check all connection properties for sensitive data
        fields_to_check = [
            ('connection_string', conn.get('connection_string', '')),
            ('server', conn.get('server', '')),
            ('filename', conn.get('filename', '')),
            ('authentication', conn.get('authentication', '')),
            ('sslmode', conn.get('sslmode', '')),
        ]
        # Also check any additional connection attributes
        for key, val in conn.items():
            if key not in ('class', 'type', 'server', 'port', 'dbname',
                           'schema', 'filename', 'connection_string',
                           'authentication', 'sslmode', 'tables',
                           'named-connections', 'connection_map'):
                fields_to_check.append((key, str(val) if val else ''))

        for field_name, field_value in fields_to_check:
            if not field_value:
                continue
            for pattern, cred_type in _SENSITIVE_PATTERNS:
                if pattern.search(str(field_value)):
                    sensitive_found.append({
                        'datasource': ds_name,
                        'field': field_name,
                        'type': cred_type,
                    })

    if sensitive_found:
        details = "; ".join(
            f"{s['datasource']}: {s['type']} in {s['field']}"
            for s in sensitive_found[:5]
        )
        if len(sensitive_found) > 5:
            details += f" ... and {len(sensitive_found) - 5} more"
        cat.checks.append(CheckItem(
            cat.name, "Sensitive credentials detected", FAIL,
            f"{len(sensitive_found)} potential credential(s) found in connection "
            f"strings: {details}",
            "Remove sensitive data from connection strings before sharing "
            "the migration output. Use Power BI gateway or parameterized "
            "connections instead of embedded credentials.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Connection string audit", PASS,
            "No sensitive credentials detected in connection strings.",
        ))

    return cat


# ═══════════════════════════════════════════════════════════════════
#  Sprint 60: New assessment categories
# ═══════════════════════════════════════════════════════════════════

def _check_performance(extracted: Dict) -> CategoryResult:
    """Assess performance impact: query complexity, expensive patterns."""
    cat = CategoryResult(name="Performance")

    calcs = extracted.get("calculations", [])
    filters_list = extracted.get("filters", [])
    worksheets = extracted.get("worksheets", [])

    # Count context operators and running calcs
    context_count = 0
    running_calc_count = 0
    lookupvalue_count = 0
    for c in calcs:
        formula = c.get("formula", "") or ""
        if re.search(r'\b(?:In|ForEach|ForAll)\s*\(', formula, re.IGNORECASE):
            context_count += 1
        if re.search(r'\b(?:Running|RUNNING_|WINDOW_|RANK|INDEX)\b', formula, re.IGNORECASE):
            running_calc_count += 1
        if 'LOOKUPVALUE' in formula.upper():
            lookupvalue_count += 1

    complexity_score = context_count * 3 + running_calc_count * 2 + len(filters_list) + lookupvalue_count * 2

    if complexity_score > 100:
        cat.checks.append(CheckItem(
            cat.name, "Query complexity", FAIL,
            f"High complexity score ({complexity_score}): {context_count} context operators, "
            f"{running_calc_count} running calcs, {lookupvalue_count} LOOKUPVALUE chains.",
            "Consider simplifying calculations or pre-aggregating data.",
        ))
    elif complexity_score > 30:
        cat.checks.append(CheckItem(
            cat.name, "Query complexity", WARN,
            f"Moderate complexity ({complexity_score}): {context_count} context operators, "
            f"{running_calc_count} running calcs.",
            "Review performance after migration. Consider Import mode.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "Query complexity", PASS,
            f"Low complexity score ({complexity_score}).",
        ))

    # Unique DAX expression count
    dax_count = len(calcs)
    if dax_count > 50:
        cat.checks.append(CheckItem(
            cat.name, "DAX expression count", WARN,
            f"{dax_count} unique calculations — may impact model refresh time.",
            "Review for consolidation opportunities.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "DAX expression count", PASS,
            f"{dax_count} calculations — within typical range.",
        ))

    return cat


def _check_data_volume(extracted: Dict) -> CategoryResult:
    """Assess data volume: row counts, model size estimates."""
    cat = CategoryResult(name="Data Volume")

    datasources = extracted.get("datasources", [])
    total_tables = 0
    large_tables = 0

    for ds in datasources:
        tables = ds.get("tables", [])
        total_tables += len(tables)
        for tbl in tables:
            row_count = tbl.get("row_count", 0) or 0
            if row_count > 10_000_000:
                cat.checks.append(CheckItem(
                    cat.name, f"Large table: {tbl.get('name', 'unknown')}",
                    WARN,
                    f"Table has {row_count:,} rows — consider DirectQuery mode.",
                    "Use DirectQuery or incremental refresh for large tables.",
                ))
                large_tables += 1
            elif row_count > 1_000_000:
                cat.checks.append(CheckItem(
                    cat.name, f"Table size: {tbl.get('name', 'unknown')}",
                    INFO,
                    f"Table has {row_count:,} rows.",
                ))

    if large_tables == 0:
        cat.checks.append(CheckItem(
            cat.name, "Table sizes", PASS,
            f"{total_tables} tables — no excessively large tables detected.",
        ))

    return cat


def _check_prep_complexity(extracted: Dict) -> CategoryResult:
    """Assess data preparation complexity (custom SQL, derived tables)."""
    cat = CategoryResult(name="Data Preparation Complexity")

    custom_sql = extracted.get("custom_sql", [])
    derived_tables = [s for s in custom_sql if s.get("type") == "derived_table"]
    freehand_sql = [s for s in custom_sql if s.get("type") != "derived_table"]

    total = len(custom_sql)
    if total == 0:
        cat.checks.append(CheckItem(
            cat.name, "Custom SQL / Derived tables", PASS,
            "No custom SQL or derived tables detected.",
        ))
        return cat

    if len(freehand_sql) > 0:
        cat.checks.append(CheckItem(
            cat.name, "Freehand SQL",
            WARN if len(freehand_sql) > 5 else INFO,
            f"{len(freehand_sql)} freehand SQL query/queries detected.",
            "Review generated Power Query M native SQL passthrough for correctness.",
        ))

    if len(derived_tables) > 0:
        cat.checks.append(CheckItem(
            cat.name, "Derived tables",
            WARN if len(derived_tables) > 3 else INFO,
            f"{len(derived_tables)} derived table(s) detected.",
            "Derived tables are converted to Power Query reference queries. "
            "Verify logic and performance.",
        ))

    return cat


def _check_licensing(extracted: Dict) -> CategoryResult:
    """Assess licensing requirements for PBI features."""
    cat = CategoryResult(name="Licensing")

    datasources = extracted.get("datasources", [])
    calcs = extracted.get("calculations", [])
    worksheets = extracted.get("worksheets", [])

    # Estimate model complexity (proxy for size)
    total_columns = sum(
        len(tbl.get("columns", []))
        for ds in datasources
        for tbl in ds.get("tables", [])
    )
    total_measures = len(calcs)

    needs_premium = []
    if total_columns > 500:
        needs_premium.append(f"{total_columns} columns (likely >1GB model)")
    if len(worksheets) > 30:
        needs_premium.append(f"{len(worksheets)} worksheets (large report)")

    rls_count = len(extracted.get("user_filters", []))
    if rls_count > 10:
        needs_premium.append(f"{rls_count} RLS rules (complex security)")

    if needs_premium:
        cat.checks.append(CheckItem(
            cat.name, "Premium features", WARN,
            f"May require Premium/PPU: {'; '.join(needs_premium)}.",
            "Consider Power BI Premium Per User or Premium capacity.",
        ))
    else:
        cat.checks.append(CheckItem(
            cat.name, "License tier", PASS,
            "Standard Power BI Pro license should be sufficient.",
        ))

    return cat


def _check_multi_datasource(extracted: Dict) -> CategoryResult:
    """Detect worksheets pulling from multiple datasources."""
    cat = CategoryResult(name="Multi-Datasource")

    worksheets = extracted.get("worksheets", [])
    datasources = extracted.get("datasources", [])

    # Build column→datasource mapping
    col_ds_map: Dict[str, str] = {}
    for ds in datasources:
        ds_name = ds.get("name", ds.get("caption", ""))
        for tbl in ds.get("tables", []):
            for col in tbl.get("columns", []):
                col_name = col.get("name", "")
                if col_name:
                    col_ds_map[col_name] = ds_name

    multi_ds_count = 0
    for ws in worksheets:
        ds_refs = set()
        for field_entry in ws.get("fields", []):
            fname = field_entry if isinstance(field_entry, str) else field_entry.get("name", "")
            # Strip brackets
            fname = fname.strip("[]")
            if fname in col_ds_map:
                ds_refs.add(col_ds_map[fname])
        if len(ds_refs) > 1:
            multi_ds_count += 1
            cat.checks.append(CheckItem(
                cat.name,
                f"Worksheet: {ws.get('name', 'unknown')}",
                WARN,
                f"References {len(ds_refs)} datasources: {', '.join(sorted(ds_refs))}.",
                "Merge datasources or use LOOKUPVALUE for cross-source references.",
            ))

    if multi_ds_count == 0:
        cat.checks.append(CheckItem(
            cat.name, "Single datasource", PASS,
            "All worksheets use a single datasource.",
        ))

    return cat


# ═══════════════════════════════════════════════════════════════════
#  Main assessment orchestrator
# ═══════════════════════════════════════════════════════════════════

def run_assessment(
    extracted: Dict,
    *,
    workbook_name: str = "Workbook",
) -> AssessmentReport:
    """Run the full pre-migration assessment against extracted data.

    Args:
        extracted: dict from ``PowerBIImporter._load_converted_objects()``
        workbook_name: display name for the report header

    Returns:
        ``AssessmentReport`` with all category results.
    """
    report = AssessmentReport(
        workbook_name=workbook_name,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    # Run all category checks
    report.categories = [
        _check_datasources(extracted),
        _check_calculations(extracted),
        _check_visuals(extracted),
        _check_filters(extracted),
        _check_data_model(extracted),
        _check_interactivity(extracted),
        _check_extract_and_packaging(extracted),
        _check_migration_scope(extracted),
        _check_connection_strings(extracted),
        _check_performance(extracted),
        _check_data_volume(extracted),
        _check_prep_complexity(extracted),
        _check_licensing(extracted),
        _check_multi_datasource(extracted),
    ]

    # Build summary
    report.summary = {
        "workbook": workbook_name,
        "overall_score": report.overall_score,
        "total_checks": report.total_checks,
        "passed": report.total_pass,
        "warnings": report.total_warn,
        "failures": report.total_fail,
    }

    logger.info(
        "Assessment complete: %s — %s (pass=%d warn=%d fail=%d)",
        workbook_name, report.overall_score,
        report.total_pass, report.total_warn, report.total_fail,
    )

    return report


# ═══════════════════════════════════════════════════════════════════
#  Console printer
# ═══════════════════════════════════════════════════════════════════

_SEV_ICONS = {
    PASS: "✓",
    INFO: "ℹ",
    WARN: "⚠",
    FAIL: "✗",
}

_SCORE_COLORS = {
    "GREEN": "✓ GREEN",
    "YELLOW": "⚠ YELLOW",
    "RED": "✗ RED",
}


def print_assessment_report(report: AssessmentReport) -> None:
    """Pretty-print the assessment report to stdout."""
    w = 72
    print()
    print("┌" + "─" * w + "┐")
    print("│" + " PRE-MIGRATION ASSESSMENT REPORT".center(w) + "│")
    print("├" + "─" * w + "┤")
    print(f"│  Workbook:  {report.workbook_name:<{w - 14}}│")
    print(f"│  Date:      {report.timestamp:<{w - 14}}│")
    score_label = _SCORE_COLORS.get(report.overall_score, report.overall_score)
    print(f"│  Readiness: {score_label:<{w - 14}}│")
    summary = (
        f"{report.total_checks} checks | "
        f"{report.total_pass} passed | "
        f"{report.total_warn} warnings | "
        f"{report.total_fail} failures"
    )
    print(f"│  Summary:   {summary:<{w - 14}}│")
    print("├" + "─" * w + "┤")

    for cat in report.categories:
        cat_icon = _SEV_ICONS.get(cat.worst_severity, " ")
        cat_header = f" {cat_icon} {cat.name}"
        print(f"│{cat_header:<{w}}│")
        print("│" + "  " + "─" * (w - 4) + "  │")

        for ck in cat.checks:
            icon = _SEV_ICONS.get(ck.severity, " ")
            line = f"    {icon} {ck.name}: {ck.detail}"
            # Wrap long lines
            while len(line) > w:
                print(f"│{line[:w]}│")
                line = "      " + line[w:]
            print(f"│{line:<{w}}│")

            if ck.recommendation and ck.severity in (WARN, FAIL):
                rec_line = f"      → {ck.recommendation}"
                while len(rec_line) > w:
                    print(f"│{rec_line[:w]}│")
                    rec_line = "      " + rec_line[w:]
                print(f"│{rec_line:<{w}}│")

        print("│" + " " * w + "│")

    print("└" + "─" * w + "┘")
    print()


# ═══════════════════════════════════════════════════════════════════
#  JSON report saver
# ═══════════════════════════════════════════════════════════════════

def save_assessment_report(
    report: AssessmentReport,
    output_dir: str = "artifacts/migration_reports",
) -> str:
    """Save the assessment report as a JSON file.

    Returns:
        Path to the saved report file.
    """
    os.makedirs(output_dir, exist_ok=True)
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', report.workbook_name)
    filename = f"assessment_{safe_name}_{report.timestamp[:10]}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

    logger.info("Assessment report saved to %s", filepath)
    return filepath
