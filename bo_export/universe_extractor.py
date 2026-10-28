"""Universe extractor (UNX/UNV).

Parses SAP BusinessObjects Universe files to extract business layer objects,
data foundation tables, joins, contexts, derived tables, and @Aggregate_Aware
configurations.
"""

import logging
import os
import re
import xml.etree.ElementTree as ET
import zipfile

logger = logging.getLogger(__name__)


def extract_universe(input_path, artifact_data=None):
    """Extract all objects from a Universe file (.unx or .unv).

    Args:
        input_path: Path to .unx or .unv file.
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

    if ext == ".unx":
        metadata = _parse_unx_file(input_path)
    elif ext == ".unv":
        metadata = _parse_unv_file(input_path)
    else:
        logger.warning("Unsupported universe format: %s", ext)
        return extracted

    if not metadata:
        logger.warning("No metadata extracted from %s", input_path)
        return extracted

    # Extract connection info
    extracted["datasources"] = _extract_connections(metadata)

    # Extract tables (data foundation)
    extracted["tables"] = _extract_tables(metadata)

    # Extract columns (business layer objects)
    extracted["columns"] = _extract_business_objects(metadata)

    # Extract joins
    extracted["joins"] = _extract_joins(metadata)

    # Extract derived tables (custom SQL)
    extracted["custom_sql"] = _extract_derived_tables(metadata)

    # Extract formulas (@Aggregate_Aware, pre-defined conditions)
    extracted["formulas"] = _extract_predefined_formulas(metadata)

    # Extract filters (mandatory/predefined conditions)
    extracted["filters"] = _extract_predefined_filters(metadata)

    # Extract prompts (LOV-based)
    extracted["prompts"] = _extract_lov_prompts(metadata)

    logger.info(
        "Universe extraction: %d tables, %d columns, %d joins, %d derived tables",
        len(extracted["tables"]),
        len(extracted["columns"]),
        len(extracted["joins"]),
        len(extracted["custom_sql"]),
    )
    return extracted


def _parse_unx_file(input_path):
    """Parse a UNX file (Information Design Tool format).

    UNX files are ZIP archives containing XML definitions for
    business layer and data foundation.
    """
    metadata = {"business_layer": None, "data_foundation": None, "connections": []}

    if not zipfile.is_zipfile(input_path):
        # Try as raw XML
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                content = f.read()
            metadata["business_layer"] = _safe_parse_xml(content)
            return metadata
        except Exception:
            return metadata

    with zipfile.ZipFile(input_path, "r") as zf:
        for entry in zf.namelist():
            # Security: reject path traversal
            if ".." in entry or entry.startswith("/"):
                logger.warning("Skipping suspicious ZIP entry: %s", entry)
                continue

            try:
                content = zf.read(entry).decode("utf-8", errors="replace")
            except Exception:
                continue

            lower_entry = entry.lower()
            if "businesslayer" in lower_entry or "blx" in lower_entry:
                metadata["business_layer"] = _safe_parse_xml(content)
            elif "datafoundation" in lower_entry or "dfx" in lower_entry:
                metadata["data_foundation"] = _safe_parse_xml(content)
            elif "connection" in lower_entry:
                root = _safe_parse_xml(content)
                if root is not None:
                    metadata["connections"].append(root)

    return metadata


def _parse_unv_file(input_path):
    """Parse a UNV file (Designer format — legacy).

    UNV files are binary but contain embedded XML metadata sections.
    """
    metadata = {"business_layer": None, "data_foundation": None, "connections": []}

    try:
        with open(input_path, "rb") as f:
            raw = f.read()

        # Extract XML sections from binary
        text = raw.decode("utf-8", errors="replace")

        # Look for XML blocks
        xml_pattern = re.compile(r"<\?xml.+?\?>.*?</\w+>", re.DOTALL)
        for match in xml_pattern.finditer(text):
            root = _safe_parse_xml(match.group())
            if root is not None:
                tag = root.tag.lower()
                if "business" in tag or "class" in tag:
                    metadata["business_layer"] = root
                elif "data" in tag or "table" in tag:
                    metadata["data_foundation"] = root

    except Exception as e:
        logger.warning("Failed to parse UNV file: %s", e)

    return metadata


def _extract_connections(metadata):
    """Extract datasource connections from universe metadata."""
    datasources = []
    roots = list(metadata.get('connections', []))
    data_foundation = metadata.get('data_foundation')
    if data_foundation is not None:
        roots.append(data_foundation)
    seen = set()

    for conn_root in roots:
        for conn in conn_root.iter():
            if "connection" in conn.tag.lower():
                datasource = {
                    "name": conn.get("name", ""),
                    "type": conn.get("type", conn.get("dbms", "")),
                    "server": conn.get("server", conn.get("host", "")),
                    "database": conn.get("database", conn.get("catalog", "")),
                    "universe": "",
                    "connection_string": conn.get("connectionString", ""),
                }
                if not any(datasource[key] for key in ('type', 'server', 'database', 'connection_string')):
                    continue
                identity = tuple(sorted(datasource.items()))
                if identity not in seen:
                    seen.add(identity)
                    datasources.append(datasource)

    return datasources


def _extract_tables(metadata):
    """Extract tables from data foundation."""
    tables = []
    seen = set()

    df = metadata.get("data_foundation")
    if df is not None:
        for table in df.iter():
            tag = table.tag.lower()
            if "table" in tag or "alias" in tag:
                name = table.get("name", table.get("id", ""))
                if name and name not in seen:
                    seen.add(name)
                    tables.append({
                        "name": name,
                        "schema": table.get("schema", table.get("owner", "")),
                        "type": "derived" if "derived" in tag else "table",
                        "source": "universe",
                        "sql": table.get("sql", ""),
                    })

    return tables


def _extract_business_objects(metadata):
    """Extract business layer objects (dimensions, measures, details).

    Business layer objects follow class\subclass\object path notation.
    """
    columns = []
    bl = metadata.get("business_layer")
    if bl is None:
        return columns

    for obj in bl.iter():
        tag = obj.tag.lower()
        if any(kw in tag for kw in ["dimension", "measure", "detail", "object", "item"]):
            qualification = "dimension"
            if "measure" in tag or obj.get("qualification", "").lower() == "measure":
                qualification = "measure"
            elif "detail" in tag or obj.get("qualification", "").lower() == "detail":
                qualification = "detail"

            path = obj.get("path", obj.get("class", ""))
            select_sql = obj.get("select", obj.get("sql", ""))
            where_clause = obj.get("where", "")

            columns.append({
                "name": obj.get("name", obj.get("id", "")),
                "table": obj.get("table", ""),
                "data_type": obj.get("dataType", obj.get("type", "string")),
                "qualification": qualification,
                "description": obj.get("description", ""),
                "path": path,
                "select_sql": select_sql,
                "where_clause": where_clause,
                "aggregate_aware": "@Aggregate_Aware" in (select_sql or ""),
            })

    return columns


def _extract_joins(metadata):
    """Extract join definitions and contexts from data foundation."""
    joins = []
    df = metadata.get("data_foundation")
    if df is None:
        return joins

    for join in df.iter():
        tag = join.tag.lower()
        if "join" in tag or "link" in tag:
            joins.append({
                "left_table": join.get("leftTable", join.get("table1", "")),
                "right_table": join.get("rightTable", join.get("table2", "")),
                "left_column": join.get("leftColumn", join.get("column1", "")),
                "right_column": join.get("rightColumn", join.get("column2", "")),
                "type": join.get("type", join.get("joinType", "inner")),
                "cardinality": join.get("cardinality", "many-to-one"),
                "context": join.get("context", ""),
                "expression": join.get("expression", ""),
            })

    # Extract contexts (resolve chasm/fan traps)
    for ctx in df.iter():
        if "context" in ctx.tag.lower():
            context_name = ctx.get("name", "")
            context_joins = []
            for child in ctx:
                if "join" in child.tag.lower():
                    context_joins.append(child.get("ref", child.get("id", "")))

            if context_joins:
                for j in joins:
                    if not j.get("context"):
                        # Associate joins with contexts based on references
                        pass

    return joins


def _extract_derived_tables(metadata):
    """Extract derived tables (SQL subqueries in universe)."""
    derived = []
    df = metadata.get("data_foundation")
    if df is None:
        return derived

    for table in df.iter():
        if "derived" in table.tag.lower():
            sql = table.get("sql", table.text or "")
            if sql:
                derived.append({
                    "name": table.get("name", "DerivedTable"),
                    "sql": sql.strip(),
                    "datasource": "",
                })

    return derived


def _extract_predefined_formulas(metadata):
    """Extract pre-defined formulas and @Aggregate_Aware objects."""
    formulas = []
    bl = metadata.get("business_layer")
    if bl is None:
        return formulas

    for obj in bl.iter():
        select_sql = obj.get("select", obj.get("sql", ""))
        if select_sql and "@Aggregate_Aware" in select_sql:
            formulas.append({
                "name": obj.get("name", ""),
                "formula": select_sql,
                "qualification": "measure",
                "data_type": "number",
                "type": "aggregate_aware",
            })

    return formulas


def _extract_predefined_filters(metadata):
    """Extract mandatory/predefined filters from business layer."""
    filters = []
    bl = metadata.get("business_layer")
    if bl is None:
        return filters

    for filt in bl.iter() if bl is not None else []:
        tag = filt.tag.lower()
        if "filter" in tag or "condition" in tag or "predefined" in tag:
            filters.append({
                "name": filt.get("name", ""),
                "type": "predefined",
                "expression": filt.get("expression", filt.get("where", "")),
                "level": "universe",
            })

    return filters


def _extract_lov_prompts(metadata):
    """Extract List of Values definitions (universe-level prompts)."""
    prompts = []
    bl = metadata.get("business_layer")
    if bl is None:
        return prompts

    for lov in bl.iter() if bl is not None else []:
        tag = lov.tag.lower()
        if "lov" in tag or "listofvalues" in tag or "prompt" in tag:
            prompts.append({
                "name": lov.get("name", ""),
                "type": lov.get("type", "static"),
                "associated_dimension": lov.get("dimension", lov.get("object", "")),
                "sql": lov.get("sql", ""),
                "cascading": lov.get("cascading", "false").lower() == "true",
            })

    return prompts


def _safe_parse_xml(content):
    """Parse XML content with XXE protection."""
    if not content or not content.strip():
        return None
    if "<!ENTITY" in content.upper():
        logger.warning("Blocked XML with ENTITY declaration (XXE protection)")
        return None
    try:
        return ET.fromstring(content)
    except ET.ParseError:
        return None
