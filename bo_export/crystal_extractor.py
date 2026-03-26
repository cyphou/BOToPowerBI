"""Crystal Reports extractor.

Parses .rpt files to extract formulas, record/group selection,
subreports, running totals, cross-tabs, parameters, groups, sorting,
and conditional formatting.
"""

import logging
import os
import re
import struct

logger = logging.getLogger(__name__)

# Crystal formula field reference pattern: {Table.Field}
FIELD_REF_PATTERN = re.compile(r"\{(\w+)\.(\w+)\}")
# Crystal formula reference: {@FormulaName}
FORMULA_REF_PATTERN = re.compile(r"\{@(\w+)\}")
# Crystal parameter reference: {?ParameterName}
PARAM_REF_PATTERN = re.compile(r"\{\?(\w+)\}")


def extract_crystal(input_path, artifact_data=None):
    """Extract all objects from a Crystal Report file.

    Args:
        input_path: Path to .rpt file.
        artifact_data: Pre-parsed artifact data (from BIAR).

    Returns:
        dict: Extracted data with 15 object type keys.
    """
    extracted = {
        "reports": [],
        "queries": [],
        "datasources": [],
        "formulas": [],
        "prompts": [],
        "filters": [],
        "tables": [],
        "columns": [],
        "joins": [],
        "groups": [],
        "sorts": [],
        "alerts": [],
        "subreports": [],
        "charts": [],
        "custom_sql": [],
    }

    if artifact_data:
        metadata = artifact_data
    else:
        metadata = _parse_rpt_file(input_path)

    if not metadata:
        logger.warning("No metadata extracted from %s", input_path)
        return extracted

    # Extract report structure
    extracted["reports"] = _extract_report_sections(metadata)

    # Extract datasource connections
    extracted["datasources"] = _extract_datasources(metadata)
    extracted["tables"] = _extract_tables(metadata)
    extracted["columns"] = _extract_columns(metadata)
    extracted["joins"] = _extract_joins(metadata)

    # Extract formulas
    extracted["formulas"] = _extract_formulas(metadata)

    # Extract parameters (prompts)
    extracted["prompts"] = _extract_parameters(metadata)

    # Extract record/group selection (filters)
    extracted["filters"] = _extract_selection_formulas(metadata)

    # Extract groups and sorting
    extracted["groups"] = _extract_groups(metadata)
    extracted["sorts"] = _extract_sorts(metadata)

    # Extract subreports
    extracted["subreports"] = _extract_subreports(metadata)

    # Extract charts
    extracted["charts"] = _extract_charts(metadata)

    # Extract conditional formatting (alerts)
    extracted["alerts"] = _extract_conditional_formatting(metadata)

    # Extract custom SQL (Command objects)
    extracted["custom_sql"] = _extract_command_objects(metadata)

    logger.info(
        "Crystal extraction: %d formulas, %d params, %d groups, %d subreports",
        len(extracted["formulas"]),
        len(extracted["prompts"]),
        len(extracted["groups"]),
        len(extracted["subreports"]),
    )
    return extracted


# ── Binary marker patterns found in .rpt files ──────────────────────
_GROUP_MARKER = re.compile(
    r"Group\s*#?(\d+)\s*[-–:]?\s*(?:on\s+)?\{?(\w+\.\w+)\}?",
    re.IGNORECASE,
)
_SORT_MARKER = re.compile(
    r"Sort\s+(?:on\s+)?\{?(\w+(?:\.\w+)?)\}?\s*(Ascending|Descending|A-Z|Z-A)?",
    re.IGNORECASE,
)
_CHART_MARKER = re.compile(
    r"Chart\s+(\w[\w\s]*?)\s*[-–:]\s*(Bar|Line|Pie|Area|Scatter|Doughnut|Radar|Bubble|Stock|Funnel|Gauge|3D|Column|Histogram|Gantt|BoxPlot)",
    re.IGNORECASE,
)
_SUBREPORT_MARKER = re.compile(
    r"Subreport\s*[-–:]?\s*(\w[\w\s]*?)(?:\s*\(|$)",
    re.IGNORECASE,
)
_SUBREPORT_LINK = re.compile(
    r"(?:Subreport|Sub)\s*Link\s*[-–:]?\s*\{?(\w+(?:\.\w+)?)\}?\s*(?:→|->|to)\s*\{?(\w+(?:\.\w+)?)\}?",
    re.IGNORECASE,
)
_COND_FORMAT_MARKER = re.compile(
    r"(?:Condition|Highlight)[\s_]*(?:Formula|Format|Rule)\s*[-–:]?\s*(.+?)(?=\n|$)",
    re.IGNORECASE,
)
_CROSSTAB_MARKER = re.compile(
    r"Cross[-_]?Tab|CrossTab|OLAP\s+Grid",
    re.IGNORECASE,
)
_RUNNING_TOTAL_MARKER = re.compile(
    r"Running\s*Total\s*[-–:]?\s*(\w+)\s+on\s+\{?(\w+(?:\.\w+)?)\}?",
    re.IGNORECASE,
)


def _parse_rpt_file(input_path):
    """Parse a Crystal Reports .rpt file.

    Crystal .rpt files are binary with embedded structures.
    We extract readable text segments and structured metadata.
    """
    metadata = {
        "raw_text": "",
        "sections": [],
        "formulas_raw": [],
        "group_markers": [],
        "sort_markers": [],
        "chart_markers": [],
        "subreport_markers": [],
        "subreport_links": [],
        "cond_format_markers": [],
        "crosstab_markers": [],
        "running_total_markers": [],
    }

    try:
        with open(input_path, "rb") as f:
            raw = f.read()

        # Extract readable text segments (Crystal embeds text in binary)
        text_segments = []
        current = []
        for byte in raw:
            if 32 <= byte <= 126:
                current.append(chr(byte))
            else:
                if len(current) > 4:  # Only keep meaningful strings
                    text_segments.append("".join(current))
                current = []
        if len(current) > 4:
            text_segments.append("".join(current))

        full_text = "\n".join(text_segments)
        metadata["raw_text"] = full_text

        # Look for formula markers in text segments
        for segment in text_segments:
            if segment.startswith("@") or "{" in segment:
                metadata["formulas_raw"].append(segment)

        # Scan for structured markers
        for m in _GROUP_MARKER.finditer(full_text):
            metadata["group_markers"].append({
                "index": int(m.group(1)),
                "field": m.group(2),
            })
        for m in _SORT_MARKER.finditer(full_text):
            direction = (m.group(2) or "ascending").lower()
            if direction in ("z-a",):
                direction = "descending"
            elif direction in ("a-z",):
                direction = "ascending"
            metadata["sort_markers"].append({
                "field": m.group(1),
                "direction": direction,
            })
        for m in _CHART_MARKER.finditer(full_text):
            metadata["chart_markers"].append({
                "name": m.group(1).strip(),
                "type": m.group(2).strip().lower(),
            })
        for m in _SUBREPORT_MARKER.finditer(full_text):
            metadata["subreport_markers"].append(m.group(1).strip())
        for m in _SUBREPORT_LINK.finditer(full_text):
            metadata["subreport_links"].append({
                "parent_field": m.group(1),
                "child_field": m.group(2),
            })
        for m in _COND_FORMAT_MARKER.finditer(full_text):
            metadata["cond_format_markers"].append(m.group(1).strip())
        if _CROSSTAB_MARKER.search(full_text):
            metadata["crosstab_markers"].append(True)
        for m in _RUNNING_TOTAL_MARKER.finditer(full_text):
            metadata["running_total_markers"].append({
                "name": m.group(1),
                "field": m.group(2),
            })

    except Exception as e:
        logger.warning("Failed to parse RPT file %s: %s", input_path, e)

    return metadata


def _extract_report_sections(metadata):
    """Extract report sections (header, detail, footer, groups)."""
    sections = [
        {"name": "Report Header", "type": "header"},
        {"name": "Page Header", "type": "page_header"},
        {"name": "Detail", "type": "detail"},
        {"name": "Report Footer", "type": "footer"},
        {"name": "Page Footer", "type": "page_footer"},
    ]
    return [{"name": "Main Report", "type": "crystal_report", "sections": sections}]


def _extract_datasources(metadata):
    """Extract datasource connections from Crystal metadata."""
    datasources = []
    raw = metadata.get("raw_text", "")

    # Look for connection string patterns
    conn_patterns = [
        r"Server=([^;]+)",
        r"Database=([^;]+)",
        r"DSN=([^;]+)",
    ]

    server = ""
    database = ""
    for pattern in conn_patterns:
        match = re.search(pattern, raw, re.IGNORECASE)
        if match:
            if "Server" in pattern:
                server = match.group(1)
            elif "Database" in pattern:
                database = match.group(1)

    if server or database:
        datasources.append({
            "name": f"{server}/{database}" if server else database,
            "type": "direct",
            "server": server,
            "database": database,
            "connection_string": "",
        })

    return datasources


def _extract_tables(metadata):
    """Extract table references from Crystal formulas and fields."""
    tables = set()
    raw = metadata.get("raw_text", "")

    for match in FIELD_REF_PATTERN.finditer(raw):
        tables.add(match.group(1))

    return [{"name": t, "schema": "", "type": "table", "source": "crystal"} for t in sorted(tables)]


def _extract_columns(metadata):
    """Extract column references from field references."""
    columns = []
    seen = set()
    raw = metadata.get("raw_text", "")

    for match in FIELD_REF_PATTERN.finditer(raw):
        table, column = match.group(1), match.group(2)
        key = f"{table}.{column}"
        if key not in seen:
            seen.add(key)
            columns.append({
                "name": column,
                "table": table,
                "data_type": "string",
                "qualification": "dimension",
            })

    return columns


def _extract_joins(metadata):
    """Extract join definitions (Crystal link tables)."""
    # Crystal joins are embedded in binary — would need SDK for full extraction
    return []


def _extract_formulas(metadata):
    """Extract Crystal formula definitions."""
    formulas = []
    seen = set()

    for raw_formula in metadata.get("formulas_raw", []):
        # Look for @FormulaName patterns
        for match in FORMULA_REF_PATTERN.finditer(raw_formula):
            name = match.group(1)
            if name not in seen:
                seen.add(name)
                formulas.append({
                    "name": name,
                    "formula": raw_formula,
                    "qualification": "measure",
                    "data_type": "number",
                    "type": "crystal_formula",
                })

    return formulas


def _extract_parameters(metadata):
    """Extract Crystal parameter fields."""
    params = []
    seen = set()
    raw = metadata.get("raw_text", "")

    for match in PARAM_REF_PATTERN.finditer(raw):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            params.append({
                "name": name,
                "type": "text",
                "required": True,
                "multi_value": False,
                "default_values": [],
                "operator": "Equal To",
            })

    return params


def _extract_selection_formulas(metadata):
    """Extract record selection and group selection formulas."""
    filters = []
    raw = metadata.get("raw_text", "")

    # Look for selection formula patterns
    selection_patterns = [
        (r"RecordSelection\s*=\s*(.+?)(?:\n|$)", "record_selection"),
        (r"GroupSelection\s*=\s*(.+?)(?:\n|$)", "group_selection"),
    ]

    for pattern, filter_type in selection_patterns:
        match = re.search(pattern, raw, re.IGNORECASE)
        if match:
            filters.append({
                "name": filter_type,
                "type": filter_type,
                "formula": match.group(1).strip(),
                "level": "query" if filter_type == "record_selection" else "group",
            })

    return filters


def _extract_groups(metadata):
    """Extract Crystal group definitions from binary markers and formula refs."""
    groups = []
    seen = set()

    # From structured markers ("Group #1 on {Table.Field}")
    for gm in metadata.get("group_markers", []):
        field = gm.get("field", "")
        if field and field not in seen:
            seen.add(field)
            parts = field.split(".", 1)
            groups.append({
                "name": f"Group {gm.get('index', len(groups) + 1)}",
                "object": parts[-1],
                "table": parts[0] if len(parts) > 1 else "",
                "sort_direction": "ascending",
                "index": gm.get("index", len(groups) + 1),
            })

    # Fallback: scan raw text for group header/footer section patterns
    raw = metadata.get("raw_text", "")
    for m in re.finditer(r"Group\s+Header\s*#?(\d+)\s*[-–:]?\s*([\w.]+)", raw, re.IGNORECASE):
        field = m.group(2)
        if field not in seen:
            seen.add(field)
            parts = field.split(".", 1)
            groups.append({
                "name": f"Group {m.group(1)}",
                "object": parts[-1],
                "table": parts[0] if len(parts) > 1 else "",
                "sort_direction": "ascending",
                "index": int(m.group(1)),
            })

    groups.sort(key=lambda g: g.get("index", 0))
    return groups


def _extract_sorts(metadata):
    """Extract sort definitions from binary markers."""
    sorts = []
    seen = set()

    for sm in metadata.get("sort_markers", []):
        field = sm.get("field", "")
        if field and field not in seen:
            seen.add(field)
            sorts.append({
                "object": field.split(".")[-1],
                "order": sm.get("direction", "ascending"),
            })

    return sorts


def _extract_subreports(metadata):
    """Extract subreport definitions with link fields for drill-through."""
    subreports = []
    seen = set()

    # Named subreports from binary markers
    for name in metadata.get("subreport_markers", []):
        if name and name not in seen:
            seen.add(name)
            subreports.append({
                "name": name,
                "type": "subreport",
                "parameters": [],
                "link_fields": [],
            })

    # Attach link fields (parameter bindings between parent ↔ subreport)
    links = metadata.get("subreport_links", [])
    if links and subreports:
        # Attach links to the last known subreport
        for link in links:
            subreports[-1]["link_fields"].append({
                "parent_field": link["parent_field"],
                "child_field": link["child_field"],
            })
    elif links and not subreports:
        subreports.append({
            "name": "Linked Subreport",
            "type": "subreport",
            "parameters": [],
            "link_fields": [{"parent_field": l["parent_field"],
                             "child_field": l["child_field"]} for l in links],
        })

    # Fallback: raw text scan
    if not subreports:
        raw = metadata.get("raw_text", "")
        if "subreport" in raw.lower():
            subreports.append({
                "name": "Embedded Subreport",
                "type": "subreport",
                "parameters": [],
                "link_fields": [],
            })

    return subreports


def _extract_charts(metadata):
    """Extract chart definitions from Crystal report."""
    charts = []

    # From structured chart markers
    for cm in metadata.get("chart_markers", []):
        chart_type = cm.get("type", "bar")
        charts.append({
            "name": cm.get("name", f"Chart {len(charts) + 1}"),
            "type": chart_type,
            "report": "Main Report",
            "dimensions": [],
            "measures": [],
        })

    # Detect cross-tab as a chart-like object
    if metadata.get("crosstab_markers"):
        charts.append({
            "name": "Cross-Tab",
            "type": "cross_tab",
            "report": "Main Report",
            "dimensions": [],
            "measures": [],
        })

    return charts


def _extract_conditional_formatting(metadata):
    """Extract conditional formatting (highlight expert) rules."""
    alerts = []

    for raw_rule in metadata.get("cond_format_markers", []):
        # Try to parse "field > value → color" patterns
        m = re.match(
            r"\{?(\w+(?:\.\w+)?)\}?\s*(>|>=|<|<=|=|!=)\s*([\d.]+)"
            r"(?:\s*(?:→|->|:)\s*(#[0-9A-Fa-f]{6}))?",
            raw_rule,
        )
        if m:
            alerts.append({
                "name": f"Highlight {m.group(1)}",
                "object": m.group(1).split(".")[-1],
                "operator": m.group(2),
                "value": m.group(3),
                "color": m.group(4) or "#FF0000",
            })
        else:
            # Unparseable rule — store raw for manual review
            alerts.append({
                "name": "Conditional Format",
                "object": "",
                "operator": ">",
                "value": "0",
                "color": "#FF0000",
                "raw_rule": raw_rule,
            })

    # Running totals → implicit alerters (common Crystal pattern)
    for rt in metadata.get("running_total_markers", []):
        field = rt.get("field", "")
        if field:
            alerts.append({
                "name": f"RunningTotal {rt['name']}",
                "object": field.split(".")[-1],
                "operator": ">",
                "value": "0",
                "color": "#4472C4",
                "type": "running_total",
            })

    return alerts


def _extract_command_objects(metadata):
    """Extract SQL Command objects (freehand SQL in Crystal)."""
    custom_sql = []
    raw = metadata.get("raw_text", "")

    # Look for SQL patterns
    sql_pattern = re.compile(r"(SELECT\s+.+?FROM\s+.+?)(?:;|\n\n)", re.IGNORECASE | re.DOTALL)
    for match in sql_pattern.finditer(raw):
        custom_sql.append({
            "name": "CommandSQL",
            "sql": match.group(1).strip(),
            "datasource": "",
        })

    return custom_sql


# ═══════════════════════════════════════════════════════════════════
#  Phase 8: Deep Crystal Analysis
# ═══════════════════════════════════════════════════════════════════

# Additional binary signature patterns for Crystal .rpt files
_CRYSTAL_HEADER_SIG = b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'  # OLE2 compound doc
_PRINT_OBJECT_SIG = re.compile(b'PrintObject', re.IGNORECASE)
_DATASOURCE_SIG = re.compile(
    rb'(?:DatabaseName|ServerName|ServerType|ConnectionURL|UserId|LogonProperties)',
    re.IGNORECASE,
)


def deep_parse_crystal(input_path):
    """Enhanced Crystal parsing with binary structure analysis.

    Goes deeper than _parse_rpt_file by:
    - Detecting OLE2 compound document structure
    - Extracting embedded images (BMP/PNG headers)
    - Parsing page layout (margins, orientation, paper size)
    - Reading datasource connection details
    - Extracting cross-tab row/col/summary fields

    Args:
        input_path: Path to .rpt file.

    Returns:
        dict: Deep metadata extending base extraction.
    """
    deep = {
        "page_layout": {},
        "embedded_images": [],
        "datasource_details": [],
        "crosstab_fields": [],
        "group_hierarchy": [],
        "section_formatting": [],
        "print_objects": [],
    }

    try:
        with open(input_path, 'rb') as f:
            raw = f.read()
    except (OSError, IOError) as e:
        logger.warning("Cannot read %s for deep analysis: %s", input_path, e)
        return deep

    # ── Page layout extraction ──
    deep["page_layout"] = _extract_page_layout(raw)

    # ── Embedded images ──
    deep["embedded_images"] = _find_embedded_images(raw)

    # ── Enhanced datasource details ──
    deep["datasource_details"] = _extract_deep_datasource(raw)

    # ── Cross-tab field extraction ──
    deep["crosstab_fields"] = _extract_crosstab_fields(raw)

    # ── Group hierarchy with summaries ──
    deep["group_hierarchy"] = _build_group_hierarchy(raw)

    # ── Section formatting ──
    deep["section_formatting"] = _extract_section_formatting(raw)

    logger.info(
        "Deep Crystal parse: layout=%s, images=%d, crosstab_fields=%d, groups=%d",
        bool(deep["page_layout"]),
        len(deep["embedded_images"]),
        len(deep["crosstab_fields"]),
        len(deep["group_hierarchy"]),
    )
    return deep


def _extract_page_layout(raw_bytes):
    """Extract page layout info from .rpt binary."""
    layout = {}
    text = _safe_decode(raw_bytes)

    # Paper size patterns
    paper_match = re.search(r'PaperSize\s*=?\s*(\d+)', text, re.IGNORECASE)
    if paper_match:
        size_code = int(paper_match.group(1))
        paper_sizes = {1: 'Letter', 5: 'Legal', 8: 'A3', 9: 'A4', 11: 'A5'}
        layout['paper_size'] = paper_sizes.get(size_code, f'Custom({size_code})')

    # Orientation
    orient_match = re.search(r'(?:Print|Paper)Orientation\s*=?\s*(\d+)', text, re.IGNORECASE)
    if orient_match:
        layout['orientation'] = 'landscape' if orient_match.group(1) == '2' else 'portrait'

    # Margins (in twips: 1440 twips = 1 inch)
    for margin_name in ('TopMargin', 'BottomMargin', 'LeftMargin', 'RightMargin'):
        m = re.search(rf'{margin_name}\s*=?\s*(\d+)', text, re.IGNORECASE)
        if m:
            layout[margin_name.lower()] = int(m.group(1))

    return layout


def _find_embedded_images(raw_bytes):
    """Find embedded images in Crystal binary data."""
    images = []

    # PNG signature
    png_sig = b'\x89PNG\r\n\x1a\n'
    idx = 0
    while True:
        pos = raw_bytes.find(png_sig, idx)
        if pos < 0:
            break
        images.append({'type': 'png', 'offset': pos})
        idx = pos + len(png_sig)

    # BMP signature
    bmp_sig = b'BM'
    idx = 0
    while True:
        pos = raw_bytes.find(bmp_sig, idx)
        if pos < 0:
            break
        # Verify it looks like a real BMP (check file size field)
        if pos + 6 <= len(raw_bytes):
            bmp_size = struct.unpack_from('<I', raw_bytes, pos + 2)[0]
            if 1000 < bmp_size < len(raw_bytes):
                images.append({'type': 'bmp', 'offset': pos, 'size': bmp_size})
        idx = pos + 2

    # JPEG SOI marker
    jpg_soi = b'\xFF\xD8\xFF'
    idx = 0
    while True:
        pos = raw_bytes.find(jpg_soi, idx)
        if pos < 0:
            break
        images.append({'type': 'jpeg', 'offset': pos})
        idx = pos + 3

    return images


def _extract_deep_datasource(raw_bytes):
    """Extract detailed datasource connection info from binary."""
    details = []
    text = _safe_decode(raw_bytes)

    # Connection string patterns
    conn_patterns = {
        'server': r'(?:ServerName|Server|Data\s*Source)\s*=\s*([^\s;,\x00]+)',
        'database': r'(?:DatabaseName|Database|Initial\s*Catalog)\s*=\s*([^\s;,\x00]+)',
        'provider': r'(?:Provider|Driver)\s*=\s*([^\s;,\x00]+)',
        'dsn': r'DSN\s*=\s*([^\s;,\x00]+)',
        'user': r'(?:User\s*ID|UID|UserId)\s*=\s*([^\s;,\x00]+)',
    }

    info = {}
    for key, pattern in conn_patterns.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip('"').strip("'")
            info[key] = val

    if info:
        # Determine DB type from provider/driver
        provider = info.get('provider', '').lower()
        if 'oracle' in provider or 'ora' in provider:
            info['db_type'] = 'Oracle'
        elif 'sqloledb' in provider or 'sqlncli' in provider or 'msoledbsql' in provider:
            info['db_type'] = 'SQL Server'
        elif 'mysql' in provider:
            info['db_type'] = 'MySQL'
        elif 'postgresql' in provider or 'pgsql' in provider:
            info['db_type'] = 'PostgreSQL'
        elif 'odbc' in provider.lower() or info.get('dsn'):
            info['db_type'] = 'ODBC'
        else:
            info['db_type'] = 'Unknown'
        details.append(info)

    return details


def _extract_crosstab_fields(raw_bytes):
    """Extract cross-tab row, column, and summary field assignments."""
    fields = []
    text = _safe_decode(raw_bytes)

    # Cross-tab patterns from Crystal binary
    ct_row = re.finditer(r'CrossTab\s*Row\s*[-–:]?\s*\{?(\w+(?:\.\w+)?)\}?', text, re.I)
    for m in ct_row:
        fields.append({'role': 'row', 'field': m.group(1)})

    ct_col = re.finditer(r'CrossTab\s*Col(?:umn)?\s*[-–:]?\s*\{?(\w+(?:\.\w+)?)\}?', text, re.I)
    for m in ct_col:
        fields.append({'role': 'column', 'field': m.group(1)})

    ct_sum = re.finditer(r'CrossTab\s*Sum(?:mary)?\s*[-–:]?\s*\{?(\w+(?:\.\w+)?)\}?', text, re.I)
    for m in ct_sum:
        fields.append({'role': 'summary', 'field': m.group(1)})

    return fields


def _build_group_hierarchy(raw_bytes):
    """Build hierarchical group tree with summary fields and formulas."""
    text = _safe_decode(raw_bytes)
    groups = []

    # Enhanced group detection with summary functions
    group_pattern = re.compile(
        r'Group\s*#?(\d+)\s*[-–:]?\s*(?:on\s+)?\{?(\w+(?:\.\w+)?)\}?'
        r'(?:\s*\((\w+)\))?',  # optional sort direction
        re.IGNORECASE,
    )

    for m in group_pattern.finditer(text):
        idx = int(m.group(1))
        field = m.group(2)
        sort_dir = (m.group(3) or 'ascending').lower()

        # Find associated group summaries
        summaries = []
        summary_pattern = re.compile(
            rf'Group\s*#?{idx}\s+Summary\s*[-–:]?\s*(\w+)\s*\(\{{?(\w+(?:\.\w+)?)\}}?\)',
            re.IGNORECASE,
        )
        for sm in summary_pattern.finditer(text):
            summaries.append({
                'function': sm.group(1).upper(),
                'field': sm.group(2),
            })

        groups.append({
            'index': idx,
            'field': field,
            'sort_direction': sort_dir,
            'summaries': summaries,
            'level': idx,
        })

    groups.sort(key=lambda g: g['index'])
    return groups


def _extract_section_formatting(raw_bytes):
    """Extract section-level formatting (suppress, background color, borders)."""
    text = _safe_decode(raw_bytes)
    sections = []

    section_pattern = re.compile(
        r'(Report|Page|Group)\s*(Header|Footer|Detail)\s*#?(\d*)',
        re.IGNORECASE,
    )

    for m in section_pattern.finditer(text):
        section_type = m.group(1)
        section_part = m.group(2)
        section_num = m.group(3) or ''
        name = f"{section_type} {section_part} {section_num}".strip()

        sections.append({
            'name': name,
            'type': f'{section_type.lower()}_{section_part.lower()}',
            'suppress': False,
            'background_color': None,
        })

    return sections


def _safe_decode(raw_bytes):
    """Decode binary to text, keeping only printable segments."""
    segments = []
    current = []
    for byte in raw_bytes:
        if 32 <= byte <= 126:
            current.append(chr(byte))
        else:
            if len(current) > 3:
                segments.append(''.join(current))
            current = []
    if len(current) > 3:
        segments.append(''.join(current))
    return '\n'.join(segments)
