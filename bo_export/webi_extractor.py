"""Web Intelligence document extractor.

Parses .wid files to extract data providers (queries), variables (formulas),
report tabs, prompts, filters, charts, tables, input controls, alerters,
breaks, sections, and data tracking configurations.
"""

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
import zipfile

logger = logging.getLogger(__name__)

# WebI variable types
VARIABLE_TYPES = {"dimension", "measure", "detail"}


def extract_webi(input_path, artifact_data=None):
    """Extract all objects from a Web Intelligence document.

    Args:
        input_path: Path to .wid file.
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
        metadata = _parse_wid_file(input_path)

    if not metadata:
        logger.warning("No metadata extracted from %s", input_path)
        return extracted

    # Extract data providers (queries)
    extracted["queries"] = _extract_data_providers(metadata)

    # Extract datasource connections
    extracted["datasources"] = _extract_datasources(metadata)

    # Extract variables (formulas)
    extracted["formulas"] = _extract_variables(metadata)

    # Extract report tabs
    extracted["reports"] = _extract_report_tabs(metadata)

    # Extract prompts
    extracted["prompts"] = _extract_prompts(metadata)

    # Extract filters (query + report level)
    extracted["filters"] = _extract_filters(metadata)

    # Extract tables and columns from data providers
    extracted["tables"] = _extract_tables(metadata)
    extracted["columns"] = _extract_columns(metadata)

    # Extract groups/breaks
    extracted["groups"] = _extract_breaks(metadata)

    # Extract sorts
    extracted["sorts"] = _extract_sorts(metadata)

    # Extract alerters
    extracted["alerts"] = _extract_alerters(metadata)

    # Extract charts
    extracted["charts"] = _extract_charts(metadata)

    # Extract freehand SQL
    extracted["custom_sql"] = _extract_freehand_sql(metadata)

    # Extract subreports (document linking)
    extracted["subreports"] = _extract_document_links(metadata)

    logger.info(
        "WebI extraction: %d queries, %d formulas, %d reports, %d prompts",
        len(extracted["queries"]),
        len(extracted["formulas"]),
        len(extracted["reports"]),
        len(extracted["prompts"]),
    )
    return extracted


def _parse_wid_file(input_path):
    """Parse a .wid file and return metadata dictionary.

    WID files are typically ZIP archives containing XML metadata.
    Falls back to treating as raw XML if not a valid ZIP.
    """
    metadata = {}

    if zipfile.is_zipfile(input_path):
        with zipfile.ZipFile(input_path, "r") as zf:
            for entry in zf.namelist():
                # Security: reject path traversal
                if ".." in entry or entry.startswith("/"):
                    logger.warning("Skipping suspicious ZIP entry: %s", entry)
                    continue

                if entry.endswith(".xml") or entry.endswith(".json"):
                    try:
                        content = zf.read(entry).decode("utf-8", errors="replace")
                        metadata[entry] = content
                    except Exception as e:
                        logger.warning("Failed to read %s: %s", entry, e)
    else:
        # Try as raw XML
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                content = f.read()
            metadata["document.xml"] = content
        except Exception as e:
            logger.warning("Failed to read %s as XML: %s", input_path, e)

    return metadata


def _extract_data_providers(metadata):
    """Extract data providers (queries) from WebI metadata."""
    queries = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for dp in root.iter():
            if "dataprovider" in dp.tag.lower() or "query" in dp.tag.lower():
                query = {
                    "name": dp.get("name", dp.get("id", "")),
                    "type": dp.get("type", "universe"),
                    "universe": dp.get("universe", ""),
                    "sql": "",
                    "objects": [],
                    "filters": [],
                }

                # Extract query objects
                for obj in dp.iter():
                    if "object" in obj.tag.lower() or "resultobject" in obj.tag.lower():
                        query["objects"].append({
                            "name": obj.get("name", obj.text or ""),
                            "qualification": obj.get("qualification", "dimension"),
                            "path": obj.get("path", ""),
                        })

                # Extract embedded SQL
                for sql_elem in dp.iter():
                    if "sql" in sql_elem.tag.lower() and sql_elem.text:
                        query["sql"] = sql_elem.text.strip()

                queries.append(query)

    return queries


def _extract_datasources(metadata):
    """Extract datasource connection information."""
    datasources = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for ds in root.iter():
            if "connection" in ds.tag.lower() or "datasource" in ds.tag.lower():
                datasource = {
                    "name": ds.get("name", ""),
                    "type": ds.get("type", ""),
                    "server": ds.get("server", ""),
                    "database": ds.get("database", ""),
                    "universe": ds.get("universe", ""),
                    "connection_string": "",
                }
                datasources.append(datasource)

    return datasources


def _extract_variables(metadata):
    """Extract WebI variables (dimensions, measures, details) with formulas."""
    variables = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for var in root.iter():
            if "variable" in var.tag.lower() or "formula" in var.tag.lower():
                qualification = var.get("qualification", "measure").lower()
                if qualification not in VARIABLE_TYPES:
                    qualification = "measure"

                variable = {
                    "name": var.get("name", var.get("id", "")),
                    "formula": var.get("formula", var.text or ""),
                    "qualification": qualification,
                    "data_type": var.get("dataType", var.get("type", "string")),
                    "description": var.get("description", ""),
                }
                variables.append(variable)

    return variables


def _extract_report_tabs(metadata):
    """Extract report tabs with their sections and elements."""
    reports = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for report in root.iter():
            if "reportelement" in report.tag.lower() or "report" in report.tag.lower():
                report_tab = {
                    "name": report.get("name", report.get("id", "")),
                    "type": report.get("type", "report"),
                    "sections": [],
                    "elements": [],
                }

                for section in report.iter():
                    if "section" in section.tag.lower():
                        report_tab["sections"].append({
                            "name": section.get("name", ""),
                            "type": section.get("type", "body"),
                        })

                reports.append(report_tab)

    return reports


def _extract_prompts(metadata):
    """Extract prompts with LOV (List of Values) configuration."""
    prompts = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for prompt in root.iter():
            if "prompt" in prompt.tag.lower() or "inputcontrol" in prompt.tag.lower():
                prompt_data = {
                    "name": prompt.get("name", ""),
                    "type": prompt.get("type", "text"),
                    "required": prompt.get("required", "true").lower() == "true",
                    "multi_value": prompt.get("multiValue", "false").lower() == "true",
                    "default_values": [],
                    "lov_type": prompt.get("lovType", "static"),
                    "associated_dimension": prompt.get("dimension", ""),
                    "operator": prompt.get("operator", "Equal To"),
                }

                # Extract default values
                for val in prompt.iter():
                    if "value" in val.tag.lower() or "default" in val.tag.lower():
                        if val.text:
                            prompt_data["default_values"].append(val.text.strip())

                prompts.append(prompt_data)

    return prompts


def _extract_filters(metadata):
    """Extract query-level and report-level filters."""
    filters = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for filt in root.iter():
            if "filter" in filt.tag.lower() or "condition" in filt.tag.lower():
                filter_data = {
                    "name": filt.get("name", ""),
                    "type": filt.get("type", "query"),
                    "operator": filt.get("operator", "Equal To"),
                    "object": filt.get("object", filt.get("dimension", "")),
                    "values": [],
                    "level": "query" if "query" in filt.tag.lower() else "report",
                }

                for val in filt.iter():
                    if "value" in val.tag.lower() and val.text:
                        filter_data["values"].append(val.text.strip())

                filters.append(filter_data)

    return filters


def _extract_tables(metadata):
    """Extract table definitions from data providers."""
    tables = []
    seen = set()
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for table in root.iter():
            if "table" in table.tag.lower():
                name = table.get("name", "")
                if name and name not in seen:
                    seen.add(name)
                    tables.append({
                        "name": name,
                        "schema": table.get("schema", ""),
                        "type": table.get("type", "table"),
                        "source": "webi",
                    })

    return tables


def _extract_columns(metadata):
    """Extract column definitions from data providers and universe objects."""
    columns = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for col in root.iter():
            if "column" in col.tag.lower() or "object" in col.tag.lower():
                columns.append({
                    "name": col.get("name", col.text or ""),
                    "table": col.get("table", ""),
                    "data_type": col.get("dataType", col.get("type", "string")),
                    "qualification": col.get("qualification", "dimension"),
                    "description": col.get("description", ""),
                })

    return columns


def _extract_breaks(metadata):
    """Extract break/group definitions."""
    groups = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for brk in root.iter():
            if "break" in brk.tag.lower() or "group" in brk.tag.lower():
                groups.append({
                    "name": brk.get("name", ""),
                    "object": brk.get("object", brk.get("dimension", "")),
                    "sort_order": brk.get("sortOrder", "ascending"),
                    "type": "break",
                })

    return groups


def _extract_sorts(metadata):
    """Extract sort definitions."""
    sorts = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for sort in root.iter():
            if "sort" in sort.tag.lower():
                sorts.append({
                    "object": sort.get("object", sort.get("dimension", "")),
                    "order": sort.get("order", "ascending"),
                    "type": sort.get("type", "value"),
                })

    return sorts


def _extract_alerters(metadata):
    """Extract alerter (conditional formatting) definitions."""
    alerters = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for alert in root.iter():
            if "alerter" in alert.tag.lower() or "alert" in alert.tag.lower():
                alerters.append({
                    "name": alert.get("name", ""),
                    "condition": alert.get("condition", ""),
                    "format": alert.get("format", ""),
                    "target_objects": [],
                })

    return alerters


def _extract_charts(metadata):
    """Extract chart definitions with axes and series data."""
    charts = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for chart in root.iter():
            tag_lower = chart.tag.lower()
            if "chart" not in tag_lower and "graph" not in tag_lower:
                continue

            chart_type = (chart.get("type")
                          or chart.get("chartType")
                          or chart.get("graphType")
                          or "bar")

            # Extract dimension (axis) fields
            dimensions = []
            for axis in chart.iter():
                axis_tag = axis.tag.lower()
                if any(k in axis_tag for k in ("axis", "category", "dimension")):
                    name = axis.get("name", axis.get("expression", axis.text or "")).strip()
                    if name:
                        dimensions.append(name)

            # Extract measure (series/value) fields
            measures = []
            for val in chart.iter():
                val_tag = val.tag.lower()
                if any(k in val_tag for k in ("series", "value", "measure", "data")):
                    name = val.get("name", val.get("expression", val.text or "")).strip()
                    if name:
                        measures.append(name)

            # Determine report tab association
            report_ref = (chart.get("report")
                          or chart.get("tab")
                          or chart.get("section")
                          or "")

            chart_data = {
                "name": chart.get("name", chart.get("id", "")),
                "type": chart_type,
                "title": chart.get("title", ""),
                "report": report_ref,
                "dimensions": dimensions,
                "measures": measures,
                "axes": dimensions,
                "series": measures,
            }
            charts.append(chart_data)

    return charts


def _extract_freehand_sql(metadata):
    """Extract freehand SQL queries."""
    custom_sql = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for sql_elem in root.iter():
            if "sql" in sql_elem.tag.lower() or "freehand" in sql_elem.tag.lower():
                if sql_elem.text and sql_elem.text.strip():
                    custom_sql.append({
                        "name": sql_elem.get("name", "FreehandSQL"),
                        "sql": sql_elem.text.strip(),
                        "datasource": sql_elem.get("datasource", ""),
                    })

    return custom_sql


def _extract_document_links(metadata):
    """Extract document linking (subreport-like navigation)."""
    links = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for link in root.iter():
            if "hyperlink" in link.tag.lower() or "documentlink" in link.tag.lower():
                links.append({
                    "name": link.get("name", ""),
                    "target_document": link.get("target", link.get("document", "")),
                    "parameters": [],
                    "type": "document_link",
                })

    return links


def _safe_parse_xml(content):
    """Parse XML content with XXE protection."""
    if not content or not content.strip():
        return None
    # Block DOCTYPE with ENTITY declarations (XXE protection)
    if "<!ENTITY" in content.upper():
        logger.warning("Blocked XML with ENTITY declaration (XXE protection)")
        return None
    try:
        return ET.fromstring(content)
    except ET.ParseError:
        return None
