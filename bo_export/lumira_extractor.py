"""SAP Lumira extractor.

Parses Lumira Discovery (.lumx) and Lumira Designer (.lums) files
to extract datasets, visualizations, stories, and formulas.
"""

import json
import logging
import os
import xml.etree.ElementTree as ET
import zipfile

logger = logging.getLogger(__name__)


def extract_lumira(input_path, artifact_data=None):
    """Extract all objects from a Lumira file.

    Args:
        input_path: Path to .lumx or .lums file.
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

    ext = os.path.splitext(input_path)[1].lower()

    if ext == ".lumx":
        metadata = _parse_lumira_discovery(input_path)
    elif ext == ".lums":
        metadata = _parse_lumira_designer(input_path)
    else:
        logger.warning("Unsupported Lumira format: %s", ext)
        return extracted

    if not metadata:
        return extracted

    extracted["datasources"] = _extract_datasources(metadata)
    extracted["tables"] = _extract_datasets(metadata)
    extracted["columns"] = _extract_dimensions_measures(metadata)
    extracted["charts"] = _extract_visualizations(metadata)
    extracted["reports"] = _extract_stories(metadata)
    extracted["formulas"] = _extract_calculated_fields(metadata)
    extracted["filters"] = _extract_filters(metadata)

    logger.info(
        "Lumira extraction: %d datasets, %d columns, %d charts",
        len(extracted["tables"]),
        len(extracted["columns"]),
        len(extracted["charts"]),
    )
    return extracted


def _parse_lumira_discovery(input_path):
    """Parse Lumira Discovery .lumx file (ZIP with JSON/XML)."""
    metadata = {}
    if not zipfile.is_zipfile(input_path):
        return metadata

    with zipfile.ZipFile(input_path, "r") as zf:
        for entry in zf.namelist():
            if ".." in entry or entry.startswith("/"):
                continue
            try:
                content = zf.read(entry).decode("utf-8", errors="replace")
                if entry.endswith(".json"):
                    metadata[entry] = json.loads(content)
                elif entry.endswith(".xml"):
                    metadata[entry] = content
            except Exception:
                pass

    return metadata


def _parse_lumira_designer(input_path):
    """Parse Lumira Designer .lums file."""
    metadata = {}
    if not zipfile.is_zipfile(input_path):
        return metadata

    with zipfile.ZipFile(input_path, "r") as zf:
        for entry in zf.namelist():
            if ".." in entry or entry.startswith("/"):
                continue
            try:
                content = zf.read(entry).decode("utf-8", errors="replace")
                metadata[entry] = content
            except Exception:
                pass

    return metadata


def _extract_datasources(metadata):
    """Extract datasource connections."""
    datasources = []
    for key, value in metadata.items():
        if isinstance(value, dict) and "datasource" in key.lower():
            datasources.append({
                "name": value.get("name", ""),
                "type": value.get("type", ""),
                "connection": value.get("connection", ""),
            })
    return datasources


def _extract_datasets(metadata):
    """Extract dataset/table definitions."""
    tables = []
    for key, value in metadata.items():
        if isinstance(value, dict):
            for ds_key in ("datasets", "data", "tables"):
                if ds_key in value:
                    items = value[ds_key]
                    if isinstance(items, list):
                        for item in items:
                            tables.append({
                                "name": item.get("name", ""),
                                "type": "dataset",
                                "source": "lumira",
                            })
    return tables


def _extract_dimensions_measures(metadata):
    """Extract dimension and measure columns."""
    columns = []
    for key, value in metadata.items():
        if isinstance(value, dict):
            for col_key in ("dimensions", "measures", "columns", "fields"):
                if col_key in value:
                    items = value[col_key]
                    if isinstance(items, list):
                        for item in items:
                            qual = "measure" if col_key == "measures" else "dimension"
                            columns.append({
                                "name": item.get("name", item) if isinstance(item, dict) else str(item),
                                "qualification": qual,
                                "data_type": item.get("type", "string") if isinstance(item, dict) else "string",
                            })
    return columns


def _extract_visualizations(metadata):
    """Extract chart/visualization definitions."""
    charts = []
    for key, value in metadata.items():
        if isinstance(value, dict):
            for viz_key in ("visualizations", "charts", "components"):
                if viz_key in value:
                    items = value[viz_key]
                    if isinstance(items, list):
                        for item in items:
                            charts.append({
                                "name": item.get("name", ""),
                                "type": item.get("type", "bar"),
                                "title": item.get("title", ""),
                            })
    return charts


def _extract_stories(metadata):
    """Extract story page definitions."""
    stories = []
    for key, value in metadata.items():
        if isinstance(value, dict):
            if "pages" in value:
                for page in value["pages"]:
                    stories.append({
                        "name": page.get("name", page.get("title", "")),
                        "type": "story_page",
                    })
    return stories


def _extract_calculated_fields(metadata):
    """Extract calculated/derived fields."""
    formulas = []
    for key, value in metadata.items():
        if isinstance(value, dict):
            for f_key in ("calculatedFields", "formulas", "derivedMeasures"):
                if f_key in value:
                    items = value[f_key]
                    if isinstance(items, list):
                        for item in items:
                            formulas.append({
                                "name": item.get("name", ""),
                                "formula": item.get("formula", item.get("expression", "")),
                                "qualification": "measure",
                            })
    return formulas


def _extract_filters(metadata):
    """Extract filter definitions."""
    filters = []
    for key, value in metadata.items():
        if isinstance(value, dict):
            if "filters" in value:
                for f in value["filters"]:
                    filters.append({
                        "name": f.get("name", f.get("dimension", "")),
                        "type": "story_filter",
                        "values": f.get("values", []),
                    })
    return filters
