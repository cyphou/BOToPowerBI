"""Read the CMS metadata manifest of an LCM BIAR export.

An ``.lcmbiar`` archive carries a ``BusinessObjects.xml`` InfoObject manifest
(directly and/or inside one nested archive member). It records names, parameters
and the CUID relations between documents, universes and connections. This module
reads only that readable metadata. It does not read, decode or decrypt
connection strings, universe contents or report contents, and it records no
owners, credentials or parameter values.
"""

import hashlib
import io
import re
import zipfile
import xml.etree.ElementTree as ET

_MANIFEST = "BusinessObjects.xml"
_MANIFEST_LIMIT = 64 * 1024 * 1024
_NESTED_LIMIT = 256 * 1024 * 1024
_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
_DOCUMENT_TYPES = {"cr:CrystalReport": "crystal", "wi:Webi": "webi"}
_UNIVERSE_TYPES = {"dsl.unx:DSL.Universe": "unx", "un:Universe": "unv"}
_CONNECTION_TYPE = "ccis.dc:CCIS.DataConnection"
_PARAMETER_FLAGS = {
    "ALLOW_MULTIPLE_VALUE": "multiple",
    "IS_OPTIONAL": "optional",
    "HAS_DISCRETE_VALUES": "discrete",
    "DISALLOW_EDITING": "locked",
}


def _local(element):
    return element.tag.rsplit("}", 1)[-1]


def _parse_xml(data):
    if re.search(rb"<!(?:DOCTYPE|ENTITY)", data, re.IGNORECASE):
        raise ValueError("manifest contains a prohibited XML declaration")
    return ET.fromstring(data)


def _read_member(archive, info, limit):
    if info.file_size > limit:
        raise ValueError(f"archive member exceeds {limit} bytes")
    with archive.open(info) as member:
        data = member.read(limit + 1)
    if len(data) != info.file_size:
        raise ValueError("archive member size does not match ZIP metadata")
    return data


def _manifest_roots(path):
    if not zipfile.is_zipfile(path):
        with open(path, "rb") as handle:
            data = handle.read(_MANIFEST_LIMIT + 1)
        if len(data) > _MANIFEST_LIMIT:
            raise ValueError("manifest is too large")
        return [_parse_xml(data)]
    roots = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.filename == _MANIFEST:
                roots.append(_parse_xml(_read_member(archive, info, _MANIFEST_LIMIT)))
            elif re.search(r"\.\d{3}$", info.filename) and 0 < info.file_size <= _NESTED_LIMIT:
                data = _read_member(archive, info, _NESTED_LIMIT)
                if data[:2] != b"PK":
                    continue
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as nested:
                        for inner in nested.infolist():
                            if inner.filename == _MANIFEST:
                                roots.append(
                                    _parse_xml(_read_member(nested, inner, _MANIFEST_LIMIT))
                                )
                except zipfile.BadZipFile:
                    continue
    if not roots:
        raise ValueError("no BusinessObjects.xml manifest found")
    return roots


def _text(element, name):
    for child in element:
        if _local(child) == name:
            return (child.text or "").strip()
    return ""


def _relation_items(element, name):
    items = []
    for node in element.iter():
        if node.get("nameID") != name:
            continue
        for child in node:
            if child.text and child.text.strip() and not child.get("nameID", "").startswith("SI_"):
                items.append(child.text.strip())
    return items


def _file_names(element):
    names = []
    for file_node in element.iter():
        if _local(file_node) == "File":
            name = _text(file_node, "Name")
            if name:
                names.append(name)
    return names


def _parameters(element):
    parameters = []
    for node in element.iter():
        if _local(node) != "Parameters":
            continue
        name = _text(node, "ParameterName")
        if not name:
            continue
        flags = {
            _PARAMETER_FLAGS[option.text.strip()]
            for option in node.iter()
            if _local(option) == "ReportParameterOption"
            and option.text and option.text.strip() in _PARAMETER_FLAGS
        }
        parameters.append({
            "name": name,
            "prompt": _text(node, "Prompt"),
            "multiple": "multiple" in flags,
            "optional": "optional" in flags,
            "discrete": "discrete" in flags,
            "locked": "locked" in flags,
        })
    return parameters


def _providers(element):
    providers = {}
    for node in element.iter():
        if node.get("nameID") != "SI_WEBI_DOC_PROPERTIES" or not node.text:
            continue
        try:
            root = _parse_xml(node.text.encode("utf-8"))
        except (ET.ParseError, ValueError):
            continue
        for provider in root.iter():
            if _local(provider) == "WEBI_DP" and provider.get("DPID"):
                providers.setdefault(provider.get("DPID"), {
                    "id": provider.get("DPID"),
                    "name": provider.get("DPNAME", ""),
                    "declared_source_name": provider.get("DSNAME", ""),
                    "declared_source_id": provider.get("DSID", ""),
                })
    return list(providers.values())


def read_lcm_manifest(path):
    """Return the lineage inventory declared by an LCM BIAR manifest."""
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()

    objects = {}
    for root in _manifest_roots(path):
        for element in root:
            cuid = _text(element, "CUID")
            if cuid:
                objects.setdefault(cuid, element)

    connections, universes, documents = {}, {}, []
    for cuid, element in objects.items():
        object_type = element.get(_XSI_TYPE, "")
        name = _text(element, "Name")
        if object_type == _CONNECTION_TYPE:
            connections[cuid] = {
                "cuid": cuid,
                "name": name,
                "network_layer": _text(element, "ConnectionNetworklayer"),
                "database_type": _text(element, "ConnectionDatabase"),
            }
        elif object_type in _UNIVERSE_TYPES:
            linked = {
                node.text.strip() for node in element.iter()
                if _local(node) in ("ConnectionChildren", "DataConnection")
                and node.text and node.text.strip()
            }
            universes[cuid] = {
                "cuid": cuid,
                "name": name,
                "kind": _UNIVERSE_TYPES[object_type],
                "connection_cuids": sorted(linked),
            }
        elif object_type in _DOCUMENT_TYPES:
            kind = _DOCUMENT_TYPES[object_type]
            documents.append({
                "cuid": cuid,
                "kind": kind,
                "name": name,
                "description": _text(element, "Description"),
                "keywords": _text(element, "Keywords"),
                "files": _file_names(element),
                "universe_cuids": sorted(set(_relation_items(element, "SI_DSL_UNIVERSE"))),
                "parameters": _parameters(element) if kind == "crystal" else [],
                "providers": _providers(element) if kind == "webi" else [],
            })

    unresolved = []
    for document in documents:
        document["universes"] = []
        for universe_cuid in document["universe_cuids"]:
            universe = universes.get(universe_cuid)
            if universe is None:
                unresolved.append({"document": document["name"], "universe_cuid": universe_cuid})
            else:
                document["universes"].append(universe["name"])
    for universe in universes.values():
        universe["connections"] = [
            connections[c] for c in universe["connection_cuids"] if c in connections
        ]

    groups = []
    for universe in sorted(universes.values(), key=lambda item: item["name"].casefold()):
        members = sorted(
            document["name"] for document in documents
            if universe["cuid"] in document["universe_cuids"]
        )
        if members:
            groups.append({
                "universe": universe["name"],
                "universe_kind": universe["kind"],
                "connections": [
                    {key: c[key] for key in ("name", "network_layer", "database_type")}
                    for c in universe["connections"]
                ],
                "documents": members,
            })

    return {
        "schema_version": "1.0",
        "evidence_boundary": "cms_manifest_metadata_only",
        "source": {"sha256": digest},
        "connections": sorted(connections.values(), key=lambda item: item["name"].casefold()),
        "universes": sorted(universes.values(), key=lambda item: item["name"].casefold()),
        "documents": sorted(documents, key=lambda item: item["name"].casefold()),
        "groups": groups,
        "unresolved_universe_links": unresolved,
        "not_extracted": [
            "connection strings and credentials",
            "universe business layers and data foundations",
            "report layouts, queries, SQL and result columns",
            "parameter data types and values",
        ],
    }
