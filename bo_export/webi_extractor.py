"""Web Intelligence document extractor.

Parses .wid files to extract data providers (queries), variables (formulas),
report tabs, prompts, filters, charts, tables, input controls, alerters,
breaks, sections, and data tracking configurations.
"""

import hashlib
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections import Counter

logger = logging.getLogger(__name__)

# WebI variable types
VARIABLE_TYPES = {"dimension", "measure", "detail"}
_NATIVE_WID_RECORD_LIMIT = 16 * 1024 * 1024
_NATIVE_WID_TOTAL_LIMIT = 64 * 1024 * 1024
_NATIVE_PROVIDER_PATH = re.compile(
    r"Data/C3/DATAPROVIDERS/(DP[0-9]+)/DP_Generic", re.IGNORECASE,
)
_NATIVE_REPORT_ELEMENT_TAGS = frozenset({"htable", "vtable", "xtable"})
_NATIVE_PROMPT_ATTRIBUTES = (
    ("VALUETYPE", "value_type", frozenset({"numeric", "date", "string", "realdate"})),
    ("KIND", "kind", frozenset({"monovalue", "multivalue"})),
    ("MULTI", "multi", frozenset({"mono", "multi"})),
    ("ANSWERTYPE", "answer_type", frozenset({"monovalue", "multivalue"})),
)
_NATIVE_PROMPT_INFO_ATTRIBUTES = (
    ("OPTIONAL", "optional", frozenset({"yes", "no"})),
    ("CONSTRAINED", "constrained", frozenset({"FreeLov", "Free"})),
    ("PERSISTENT", "persistent", frozenset({"yes", "no"})),
)


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

    native = {"reports": [], "queries": []}
    if artifact_data:
        metadata = artifact_data
    else:
        metadata, native = _parse_wid_file(input_path)

    if not metadata and not any(native.values()):
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

    for category in ("reports", "queries"):
        _merge_native_wid_objects(extracted[category], native[category], category)

    logger.info(
        "WebI extraction: %d queries, %d formulas, %d reports, %d prompts",
        len(extracted["queries"]),
        len(extracted["formulas"]),
        len(extracted["reports"]),
        len(extracted["prompts"]),
    )
    return extracted


def _parse_wid_file(input_path):
    """Parse a .wid file and return generic metadata and partial native objects.

    WID files are typically ZIP archives containing XML metadata.
    Falls back to treating as raw XML if not a valid ZIP.
    """
    metadata = {}
    native = {"reports": [], "queries": []}

    if zipfile.is_zipfile(input_path):
        with zipfile.ZipFile(input_path, "r") as zf:
            native = _extract_native_wid(zf)
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

    return metadata, native


def _extract_native_wid(zf):
    """Read only the native records whose structure has been established."""
    extracted = {"reports": [], "queries": []}
    records = []
    for info in zf.infolist():
        provider = _NATIVE_PROVIDER_PATH.fullmatch(info.filename)
        if info.filename.casefold() == "data/re/docspec":
            records.append((info, "reports", None))
        elif provider:
            records.append((info, "queries", provider.group(1)))
    if not records:
        return extracted

    logger.warning(
        "Native WID extraction is partial; SQL, connections, full layouts, formulas "
        "and source completeness are not established."
    )
    counts = Counter(info.filename.casefold() for info, _, _ in records)
    duplicates_logged = set()
    remaining = _NATIVE_WID_TOTAL_LIMIT
    for info, category, provider_id in records:
        key = info.filename.casefold()
        if counts[key] != 1:
            if key not in duplicates_logged:
                logger.warning("Skipping ambiguous duplicate native WID member: %s", info.filename)
                duplicates_logged.add(key)
            continue
        if info.file_size > _NATIVE_WID_RECORD_LIMIT or info.file_size > remaining:
            logger.warning("Skipping native WID member exceeding size limits: %s", info.filename)
            continue
        remaining -= info.file_size
        try:
            with zf.open(info) as member:
                data = member.read(_NATIVE_WID_RECORD_LIMIT + 1)
            if len(data) != info.file_size or len(data) > _NATIVE_WID_RECORD_LIMIT:
                raise ValueError("record size does not match ZIP metadata")
            if category == "reports":
                extracted[category].extend(_parse_native_docspec(data))
            else:
                extracted[category].append(
                    _parse_native_provider(data, provider_id, info.filename)
                )
        except (ValueError, UnicodeError, ET.ParseError, OSError, EOFError,
                RuntimeError, NotImplementedError, zipfile.BadZipFile, zlib.error) as error:
            logger.warning("Cannot parse native WID member %s: %s", info.filename, error)
    return extracted


def _native_wid_body(data, signatures):
    if len(data) < 8 or int.from_bytes(data[:4], "little") != len(data):
        raise ValueError("invalid native record length")
    if data[4:8] not in signatures:
        raise ValueError("unsupported native record header")
    return data[8:]


def _native_wid_xml(text):
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("prohibited XML declaration")
    return ET.fromstring(text)


def _parse_native_docspec(data):
    text = _native_wid_body(data, (b"\x05\x00\x02\x00",)).decode("utf-8-sig")
    root = _native_wid_xml(text)
    if root.tag != "DOCUMENT" or root.get("RSVERSION") != "2.5":
        raise ValueError("unsupported native document specification")

    reports = root.findall("REPORT")
    ids = Counter(report.get("RID") for report in reports if report.get("RID"))
    result = []
    for report in reports:
        report_id = report.get("RID")
        names = [
            item.text for item in report.findall("PLIST/PVAL")
            if item.get("NAME") == "name"
        ]
        if not report_id or not report_id.strip() or ids[report_id] != 1 or len(names) != 1:
            logger.warning("Skipping native WID report with missing or ambiguous identity/name")
            continue
        try:
            localized = json.loads(names[0] or "")
        except (TypeError, ValueError):
            logger.warning("Skipping native WID report %s with invalid name", report_id)
            continue
        name = localized.get("l") if isinstance(localized, dict) else None
        if not isinstance(name, str) or not name.strip():
            logger.warning("Skipping native WID report %s with invalid name", report_id)
            continue
        result.append({
            "id": report_id,
            "name": name,
            "type": "report",
            "sections": _native_report_sections(report),
            "elements": _native_report_elements(report),
            "native_wid_partial": True,
        })
    return result


def _native_report_sections(report):
    sections = []
    for element in report.iter():
        if element is report or element.tag.rsplit("}", 1)[-1].casefold() != "section":
            continue
        section = {"type": "section", "native_wid_partial": True}
        section_id = element.get("BID")
        if section_id:
            section["id"] = section_id
        sections.append(section)
    return sections


def _native_report_elements(report):
    elements = []
    for element in report.iter():
        if element is report:
            continue
        tag = element.tag.rsplit("}", 1)[-1].casefold()
        if tag not in _NATIVE_REPORT_ELEMENT_TAGS:
            continue
        item = {"type": tag, "native_wid_partial": True}
        element_id = element.get("BID")
        if element_id:
            item["id"] = element_id
        rows = sum(
            1 for child in element.iter()
            if child is not element
            and child.tag.rsplit("}", 1)[-1].casefold() == "rowinfo"
        )
        columns = sum(
            1 for child in element.iter()
            if child is not element
            and child.tag.rsplit("}", 1)[-1].casefold() == "colinfo"
        )
        if rows:
            item["row_info_count"] = rows
        if columns:
            item["column_info_count"] = columns
        elements.append(item)
    return elements


def _parse_native_provider(data, provider_id, source_member):
    body = _native_wid_body(data, (b"\x02\x00\x03\x00", b"\x00\x00\x03\x00"))
    if len(body) < 4:
        raise ValueError("truncated native data-provider name")
    units = int.from_bytes(body[:4], "little")
    name_end = 4 + units * 2
    if not units or name_end > len(body):
        raise ValueError("invalid native data-provider name length")
    name = body[4:name_end].decode("utf-16le")
    if not name.strip() or "\x00" in name:
        raise ValueError("invalid native data-provider name")

    variants = (
        ("queryspec:QuerySpec", "utf-16le"),
        ("QuerySpecification", "utf-8"),
    )
    matches = []
    for tag, encoding in variants:
        opening = ("<" + tag).encode(encoding)
        start = body.find(opening, name_end)
        if start != -1:
            if body.find(opening, start + len(opening)) != -1:
                raise ValueError("ambiguous native query specifications")
            matches.append((tag, encoding, start))
    if len(matches) != 1:
        raise ValueError("missing or ambiguous native query specification")
    tag, encoding, start = matches[0]
    closing = ("</" + tag + ">").encode(encoding)
    end = body.find(closing, start)
    if end == -1:
        raise ValueError("truncated native query specification")
    root = _native_wid_xml(body[start:end + len(closing)].decode(encoding))

    modern = tag == "queryspec:QuerySpec"
    expected_root = "{http://com.sap.sl.queryspec}QuerySpec" if modern else "QuerySpecification"
    if root.tag != expected_root:
        raise ValueError("unexpected native query-specification root")
    xml_id = root.get("dataProviderId")
    if (modern and not xml_id) or (xml_id is not None and xml_id != provider_id):
        raise ValueError("native data-provider ID does not match its member path")

    objects = []
    for query in root.iter():
        query_tag = query.tag.rsplit("}", 1)[-1]
        if query_tag != ("bOQuery" if modern else "Query"):
            continue
        for item in query:
            if item.tag.rsplit("}", 1)[-1] != ("resultObjects" if modern else "QueryResult"):
                continue
            if modern:
                identifier, object_name = item.get("identifier"), item.get("name")
            else:
                identifier = item.get("Key")
                names = [child.text for child in item if child.tag == "Name"]
                object_name = names[0] if len(names) == 1 else None
            if (not identifier or not identifier.strip()
                    or not object_name or not object_name.strip()):
                logger.warning("Skipping native WID result object with missing or ambiguous identity/name")
                continue
            objects.append({"identifier": identifier, "name": object_name})
    return {
        "id": provider_id,
        "name": name,
        "type": "",
        "universe": "",
        "datasource": "",
        "sql": "",
        "objects": objects,
        "filters": [],
        "native_wid_partial": True,
        "native_prompt_metadata": _native_prompt_metadata(
            body, end + len(closing), encoding, provider_id, source_member,
            hashlib.sha256(data).hexdigest(),
        ),
    }


def _native_prompt_metadata(body, query_end, encoding, provider_id, source_member,
                            source_member_sha256):
    metadata = {
        "status": "not_observed",
        "provider_id": provider_id,
        "source_member": source_member,
        "source_member_sha256": source_member_sha256,
    }
    separators = (
        (b"\r\x00\n\x00", b"\n\x00")
        if encoding == "utf-16le" else (b"\r\n", b"\n")
    )
    separator = next((value for value in separators if body.startswith(value, query_end)), None)
    if separator is None:
        return metadata

    start = query_end + len(separator)
    metadata["record_offset"] = start + 8
    try:
        if start + 8 > len(body):
            raise ValueError("truncated PARAMSERVER header")
        length = int.from_bytes(body[start:start + 4], "little")
        if length < 8 or start + length > len(body):
            raise ValueError("invalid PARAMSERVER length")
        content = _native_wid_body(
            body[start:start + length], (b"\x01\x00\x01\x00",),
        ).decode("utf-8-sig")
        root = _native_wid_xml(content)
        if root.tag != "PARAMSERVER":
            raise ValueError("unexpected PARAMSERVER root")
        parameters = []
        for position, parameter in enumerate(root.findall("PARAMETER"), 1):
            if parameter.get("TYPE") != "prompt":
                continue
            item = {"position": position}
            _copy_native_prompt_attributes(parameter, item, _NATIVE_PROMPT_ATTRIBUTES)
            info = parameter.findall("PROMPTINFO")
            if len(info) > 1:
                raise ValueError("ambiguous PARAMSERVER prompt information")
            if info:
                _copy_native_prompt_attributes(info[0], item, _NATIVE_PROMPT_INFO_ATTRIBUTES)
                if "ORDER" in info[0].attrib:
                    order = info[0].attrib["ORDER"]
                    if re.fullmatch(r"-?[0-9]{1,9}", order):
                        item["order"] = int(order)
                    else:
                        logger.warning("Omitting unsupported PARAMSERVER ORDER")
                lists = info[0].findall("LISTOFVALUE")
                if len(lists) > 1:
                    raise ValueError("ambiguous PARAMSERVER list information")
                if lists:
                    _copy_native_prompt_attributes(
                        lists[0], item,
                        (("TYPELOV", "list_type", frozenset({"dynamic", "static"})),),
                    )
            parameters.append(item)
    except (ValueError, UnicodeError, ET.ParseError) as error:
        logger.warning(
            "Cannot parse native WID PARAMSERVER for %s (%s)",
            provider_id, type(error).__name__,
        )
        metadata["status"] = "invalid"
        return metadata

    metadata["status"] = "available"
    metadata["parameters"] = parameters
    return metadata


def _copy_native_prompt_attributes(element, target, attributes):
    for source, destination, allowed in attributes:
        if source not in element.attrib:
            continue
        value = element.attrib[source]
        if value in allowed:
            target[destination] = value
        else:
            logger.warning("Omitting unsupported PARAMSERVER attribute %s", source)


def _merge_native_wid_objects(existing, native, category):
    generic = list(existing)
    for item in native:
        matching = []
        for other in generic:
            other_id, native_id = other.get("id"), item.get("id")
            if other_id and native_id:
                if other_id == native_id:
                    matching.append(other)
            elif (other.get("name") and item.get("name")
                  and other["name"].casefold() == item["name"].casefold()):
                matching.append(other)
        if matching:
            for other in matching:
                other["native_wid_partial"] = True
                if category == "reports":
                    for field in ("sections", "elements"):
                        existing_items = other.setdefault(field, [])
                        identities = {
                            (candidate.get("type"), candidate.get("id"))
                            for candidate in existing_items
                            if isinstance(candidate, dict)
                            and candidate.get("id")
                        }
                        for candidate in item.get(field, []):
                            identity = (candidate.get("type"), candidate.get("id"))
                            if not identity[1] or identity not in identities:
                                existing_items.append(candidate)
                                if identity[1]:
                                    identities.add(identity)
            if category == "queries":
                metadata = item.get("native_prompt_metadata")
                exact = [
                    other for other in matching
                    if other.get("id") and other["id"] == item.get("id")
                ]
                if metadata and len(matching) == 1 and len(exact) == 1:
                    exact[0]["native_prompt_metadata"] = metadata
                elif metadata and metadata["status"] != "not_observed":
                    evidence = dict(item)
                    evidence["native_wid_evidence_only"] = True
                    existing.append(evidence)
                    logger.warning(
                        "Native WID PARAMSERVER evidence retained separately; "
                        "the generic provider identity is unverified"
                    )
            logger.warning(
                "Native WID %s may duplicate generic metadata; retaining the generic entry",
                category,
            )
        else:
            existing.append(item)


def _extract_data_providers(metadata):
    """Extract data providers (queries) from WebI metadata."""
    queries = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for dp in root.iter():
            tag = dp.tag.rsplit("}", 1)[-1].lower()
            if ("dataprovider" in tag or "query" in tag) and not (
                "filter" in tag or "condition" in tag
            ):
                query = {
                    "name": dp.get("name", dp.get("id", "")),
                    "type": dp.get("type", "universe"),
                    "universe": dp.get("universe", ""),
                    "datasource": _datasource_reference(dp),
                    "sql": "",
                    "objects": [],
                    "filters": [],
                }
                if dp.get("id"):
                    query["id"] = dp.get("id")

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
                    if "sql" in sql_elem.tag.lower():
                        sql = _sql_text(sql_elem)
                        if sql:
                            query["sql"] = sql
                            if not query["datasource"]:
                                query["datasource"] = _datasource_reference(sql_elem)

                queries.append(query)

    return queries


def _extract_datasources(metadata):
    """Extract datasource connection information."""
    datasources = []
    seen = set()
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        for ds in root.iter():
            if "connection" in ds.tag.lower() or "datasource" in ds.tag.lower():
                datasource = {
                    "name": ds.get("name", ""),
                    "id": ds.get("id", ""),
                    "connection_id": ds.get("connectionId", ds.get("connection", "")),
                    "type": ds.get("type", ""),
                    "server": ds.get("server", ""),
                    "database": ds.get("database", ""),
                    "universe": ds.get("universe", ""),
                    "connection_string": "",
                }
                if not any(datasource.get(key) for key in (
                    "name", "id", "connection_id", "type", "server", "database", "universe"
                )):
                    continue
                identity = tuple(
                    datasource.get(key, "")
                    for key in (
                        "name", "id", "connection_id", "type", "server",
                        "database", "universe",
                    )
                )
                if identity in seen:
                    continue
                seen.add(identity)
                datasources.append(datasource)

    return datasources


def _extract_variables(metadata):
    """Extract WebI variables (dimensions, measures, details) with formulas."""
    variables = []
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        parents = {child: parent for parent in root.iter() for child in parent}
        for var in root.iter():
            tag = var.tag.rsplit("}", 1)[-1].lower()
            is_variable = "variable" in tag
            is_formula = "formula" in tag
            if not is_variable and not is_formula:
                continue

            if is_formula and not is_variable:
                parent = parents.get(var)
                while parent is not None:
                    parent_tag = parent.tag.rsplit("}", 1)[-1].lower()
                    if "variable" in parent_tag:
                        break
                    parent = parents.get(parent)
                if parent is not None:
                    continue

            formula = var.get("formula")
            if not formula and is_variable:
                formula_element = next(
                    (
                        element for element in var.iter()
                        if element is not var
                        and "formula" in element.tag.rsplit("}", 1)[-1].lower()
                    ),
                    None,
                )
                if formula_element is not None:
                    formula = "".join(formula_element.itertext()).strip()
            if not formula:
                formula = var.text or ""

            qualification = var.get("qualification", "measure").lower()
            if qualification not in VARIABLE_TYPES:
                qualification = "measure"

            variable = {
                "name": var.get("name", var.get("id", "")),
                "formula": formula,
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
                if report.get("id"):
                    report_tab["id"] = report.get("id")

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
    """Extract SQL once, associating provider names and source references."""
    custom_sql = []
    unnamed_index = 0
    used_names = set()
    for filename, content in metadata.items():
        root = _safe_parse_xml(content)
        if root is None:
            continue

        parents = {child: parent for parent in root.iter() for child in parent}
        for sql_elem in root.iter():
            tag = sql_elem.tag.lower()
            if "sql" not in tag and "freehand" not in tag:
                continue
            sql = _sql_text(sql_elem)
            if not sql:
                continue

            # Use the nearest enclosing query/provider, if present. Its name
            # and source are more useful than generic names on SQL elements.
            provider = parents.get(sql_elem)
            while provider is not None and not (
                "dataprovider" in provider.tag.lower()
                or "query" in provider.tag.lower()
            ):
                provider = parents.get(provider)

            name = ""
            datasource = ""
            if provider is not None:
                name = provider.get("name", provider.get("id", ""))
                datasource = _datasource_reference(provider)
            if not name:
                name = sql_elem.get("name", "")
            if not datasource:
                datasource = _datasource_reference(sql_elem)
            if not name:
                unnamed_index += 1
                name = "FreehandSQL" if unnamed_index == 1 else f"FreehandSQL_{unnamed_index}"
                while name in used_names:
                    unnamed_index += 1
                    name = f"FreehandSQL_{unnamed_index}"

            used_names.add(name)
            custom_sql.append({
                "name": name,
                "sql": sql,
                "datasource": datasource,
            })

    return custom_sql


def _datasource_reference(element):
    """Return a source reference without normalizing its original value."""
    for attribute in ("datasource", "dataSource", "connection", "connectionId"):
        value = element.get(attribute)
        if value:
            return value
    return ""


def _sql_text(element):
    """Read SQL text from element content or its common SQL attribute."""
    return (element.text or element.get("sql") or "").strip()


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
