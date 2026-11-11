"""Offline, versioned SAP BW inventory snapshots.

This module validates local JSON-shaped snapshots only. It never connects to
SAP, Fabric, or the BusinessObjects migration contract.
"""

from __future__ import annotations

import copy
import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from .security_validator import redact_credentials, scan_for_credentials
except ImportError:  # Support direct imports when powerbi_import is on sys.path.
    from security_validator import redact_credentials, scan_for_credentials


CURRENT_SCHEMA_VERSION = "1.0"
DRAFT_SCHEMA_VERSION = "0.1"
REDACTED = "***REDACTED***"


class BWInventoryError(ValueError):
    """Raised when an offline BW inventory violates its versioned contract."""


_SENSITIVE_FIELD = re.compile(
    r"(?:password|passwd|secret|token|api.?key|access.?key|account.?key|"
    r"private.?key|credential|authorization|auth.?header)",
    re.IGNORECASE,
)
_INLINE_SECRET_PATTERNS = (
    re.compile(
        r"""(?i)(["']?(?:password|passwd|secret|token|credential|api[_-]?key|"""
        r"""access[_-]?key|client[_-]?secret)["']?\s*[:=]\s*["']?)"""
        r"""([^"',;\s}]+)(["']?)"""
    ),
)
_REDACTED_ASSIGNMENT = re.compile(
    r"(?i)((?:password|passwd|secret|token|api.?key|access.?key|"
    r"account.?key|private.?key|client.?secret)\s*=\s*)"
    + re.escape(REDACTED)
)

_ENUMS = {
    "product": {"SAP BW", "SAP BW/4HANA"},
    "discovery_method": {"manual", "source_export", "metadata_api", "usage_report", "unknown"},
    "access_status": {"granted", "pending", "denied", "unknown", "not_applicable"},
    "coverage": {"complete", "partial", "not_assessed", "not_applicable"},
    "owner_signoff": {"pending", "accepted", "rejected", "not_requested"},
    "object_type": {
        "source", "datasource", "infoprovider", "adso", "infocube",
        "composite_provider", "transformation", "dtp", "process_chain",
        "bex_query", "consumer", "authorization", "planning_process",
    },
    "discovery_status": {"observed", "inferred", "unknown"},
    "disposition": {"in_scope", "out_of_scope", "unknown"},
    "criticality": {"low", "medium", "high", "critical", "unknown"},
    "assessment_status": {"observed", "inferred", "unknown", "not_assessed", "not_applicable"},
    "delta_mechanism": {"full", "watermark", "cdc", "open_hub", "other", "unknown", "not_applicable"},
    "migration_classification": {"automatic_candidate", "manual_redesign", "blocked", "unknown", "not_assessed"},
    "validation_status": {"not_run", "pass", "fail", "not_applicable"},
    "dependency_kind": {"feeds", "transforms", "scheduled_by", "queries", "consumes", "secured_by", "plans", "other"},
    "resolution_status": {"resolved", "unresolved", "unknown"},
    "key_role": {"business", "technical", "surrogate", "partition", "unknown"},
    "support_status": {"supported", "unsupported", "unknown"},
    "unsupported_category": {
        "abap_routine", "bex_semantic", "planning_writeback", "authorization",
        "bw_object_type", "custom_function", "other",
    },
    "impact": {"low", "medium", "high", "critical", "unknown"},
    "error_category": {"discovery", "permission", "parse", "coverage", "other"},
}

_ROOT_FIELDS = {
    "schema_version", "run_id", "captured_at", "source_system", "provenance",
    "discovery", "extraction_access", "scope", "objects", "dependencies", "errors",
    "unknowns", "unsupported_features",
}
_OBJECT_FIELDS = {
    "id", "type", "name", "discovery_status", "disposition", "criticality",
    "business_owner", "source_reference", "location", "usage_profile",
    "data_profile", "delta_profile", "migration_decision", "metadata_status",
    "definition", "keys_status", "keys", "semantics",
}
_OBJECT_BASE_REQUIRED = {
    "id", "type", "name", "discovery_status", "disposition", "criticality",
    "business_owner", "location", "usage_profile", "data_profile",
    "delta_profile", "migration_decision", "metadata_status", "definition",
    "keys_status", "keys", "semantics",
}
_DATE_TIME_FIELDS = {
    "captured_at", "observation_window_start", "observation_window_end",
    "last_used_at",
}


def _fail(path: str, reason: str) -> None:
    # Never include the rejected value or source payload in a contract error.
    raise BWInventoryError(f"BW inventory contract error at {path}: {reason}")


def _redact_embedded(text: str) -> str:
    result = redact_credentials(text)
    for pattern in _INLINE_SECRET_PATTERNS:
        # Drop the sensitive key/value expression altogether; leaving the key
        # beside a marker would still trigger the central credential scanner.
        result = pattern.sub(REDACTED, result)
    return result


def _sanitize(value: Any, path: str = "$") -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(path, "JSON object keys must be strings")
            if key == "credential_material_included":
                clean[key] = _sanitize(item, f"{path}.{key}")
            elif not (
                key == "authorizations" and path.endswith(".scope.coverage")
            ) and _SENSITIVE_FIELD.search(key):
                clean[key] = REDACTED
            else:
                clean[key] = _sanitize(item, f"{path}.{key}")
        return clean
    if isinstance(value, list):
        return [_sanitize(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, str):
        return _redact_embedded(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    _fail(path, "value is not JSON-compatible")


def _credential_findings(value: Any) -> bool:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    # The helper's scanner correctly reports assignments, including a deliberate
    # redaction marker. Remove only those markers before checking for residue.
    encoded = _REDACTED_ASSIGNMENT.sub(r"\1", encoded)
    return bool(scan_for_credentials(encoded))


def sanitize_snapshot(snapshot: Any) -> dict:
    """Return a recursively redacted copy; the supplied object is not mutated."""
    sanitized = _sanitize(snapshot)
    if not isinstance(sanitized, dict):
        _fail("$", "snapshot must be a JSON object")
    if _credential_findings(sanitized):
        _fail("$", "credential-like content remains after redaction")
    return sanitized


def _object(value: Any, path: str, required: set[str], allowed: set[str]) -> dict:
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    missing = required - value.keys()
    extra = value.keys() - allowed
    if missing:
        _fail(path, "missing required fields")
    if extra:
        _fail(path, "contains unsupported fields")
    return value


def _string(value: Any, path: str, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be a non-empty string" if not nullable else "must be a string or null")


def _enum(value: Any, name: str, path: str) -> None:
    if not isinstance(value, str) or value not in _ENUMS[name]:
        _fail(path, "has an unsupported status or enumeration value")


def _timestamp(value: Any, path: str, date_only: bool = False, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    _string(value, path)
    try:
        if date_only:
            date.fromisoformat(value)
        else:
            if "T" not in value:
                raise ValueError
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        _fail(path, "must be an ISO-8601 date or date-time")


def _validate_profile(value: Any, path: str, kind: str) -> None:
    fields = {
        "usage": {
            "status", "observation_window_start", "observation_window_end",
            "last_used_at", "access_count",
        },
        "data": {
            "status", "estimated_rows", "estimated_bytes", "history_start",
            "history_end", "retention_policy",
        },
        "delta": {"status", "mechanism", "delete_capture"},
    }[kind]
    profile = _object(value, path, fields, fields)
    _enum(profile["status"], "assessment_status", f"{path}.status")
    if kind == "usage":
        for field in ("observation_window_start", "observation_window_end", "last_used_at"):
            _timestamp(profile[field], f"{path}.{field}", nullable=True)
        count = profile["access_count"]
        if count is not None and (type(count) is not int or count < 0):
            _fail(f"{path}.access_count", "must be a non-negative integer or null")
    elif kind == "data":
        for field in ("estimated_rows", "estimated_bytes"):
            amount = profile[field]
            if amount is not None and (type(amount) is not int or amount < 0):
                _fail(f"{path}.{field}", "must be a non-negative integer or null")
        for field in ("history_start", "history_end"):
            _timestamp(profile[field], f"{path}.{field}", date_only=True, nullable=True)
        _string(profile["retention_policy"], f"{path}.retention_policy", nullable=True)
    else:
        _enum(profile["mechanism"], "delta_mechanism", f"{path}.mechanism")
        if profile["delete_capture"] is not None and type(profile["delete_capture"]) is not bool:
            _fail(f"{path}.delete_capture", "must be a boolean or null")


def _validate_object(item: Any, path: str) -> None:
    obj = _object(item, path, _OBJECT_BASE_REQUIRED, _OBJECT_FIELDS)
    for field in ("id", "type", "name"):
        _string(obj[field], f"{path}.{field}")
    _enum(obj["type"], "object_type", f"{path}.type")
    _enum(obj["discovery_status"], "discovery_status", f"{path}.discovery_status")
    _enum(obj["disposition"], "disposition", f"{path}.disposition")
    _enum(obj["criticality"], "criticality", f"{path}.criticality")
    _string(obj["business_owner"], f"{path}.business_owner", nullable=True)
    for field in ("source_reference", "location"):
        if field in obj:
            _string(obj[field], f"{path}.{field}", nullable=True)
    for key, kind in (("usage_profile", "usage"), ("data_profile", "data"), ("delta_profile", "delta")):
        _validate_profile(obj[key], f"{path}.{key}", kind)
    _enum(obj["metadata_status"], "assessment_status", f"{path}.metadata_status")

    definition = _object(
        obj["definition"], f"{path}.definition",
        {"status", "reference", "hash_algorithm", "hash"},
        {"status", "reference", "hash_algorithm", "hash"},
    )
    _enum(definition["status"], "assessment_status", f"{path}.definition.status")
    _string(definition["reference"], f"{path}.definition.reference", nullable=True)
    _string(definition["hash_algorithm"], f"{path}.definition.hash_algorithm", nullable=True)
    _string(definition["hash"], f"{path}.definition.hash", nullable=True)
    if (definition["hash"] is None) != (definition["hash_algorithm"] is None):
        _fail(f"{path}.definition", "hash and hash_algorithm must be supplied together")
    if definition["hash"] is not None and definition["hash_algorithm"] != "sha256":
        _fail(f"{path}.definition.hash_algorithm", "only sha256 is supported")
    if definition["hash"] is not None and not re.fullmatch(r"[0-9a-f]{64}", definition["hash"], re.IGNORECASE):
        _fail(f"{path}.definition.hash", "must be a 64-character SHA-256 digest")

    _enum(obj["keys_status"], "assessment_status", f"{path}.keys_status")
    if not isinstance(obj["keys"], list):
        _fail(f"{path}.keys", "must be an array")
    seen_keys = set()
    for index, key in enumerate(obj["keys"]):
        kpath = f"{path}.keys[{index}]"
        key_obj = _object(
            key, kpath, {"name", "data_type", "nullable", "role"},
            {"name", "data_type", "nullable", "role"},
        )
        _string(key_obj["name"], f"{kpath}.name")
        _string(key_obj["data_type"], f"{kpath}.data_type")
        if key_obj["name"] in seen_keys:
            _fail(f"{kpath}.name", "key names must be unique within an object")
        seen_keys.add(key_obj["name"])
        if type(key_obj["nullable"]) is not bool:
            _fail(f"{kpath}.nullable", "must be a boolean")
        _enum(key_obj["role"], "key_role", f"{kpath}.role")

    semantics = _object(
        obj["semantics"], f"{path}.semantics",
        {"status", "measures", "dimensions", "functions"},
        {"status", "measures", "dimensions", "functions"},
    )
    _enum(semantics["status"], "assessment_status", f"{path}.semantics.status")
    for field in ("measures", "dimensions", "functions"):
        if not isinstance(semantics[field], list):
            _fail(f"{path}.semantics.{field}", "must be an array")
        for index, entry in enumerate(semantics[field]):
            entry_path = f"{path}.semantics.{field}[{index}]"
            entry_obj = _object(
                entry, entry_path, {"name", "data_type", "status", "details"},
                {"name", "data_type", "status", "details"},
            )
            _string(entry_obj["name"], f"{entry_path}.name")
            _string(entry_obj["data_type"], f"{entry_path}.data_type")
            _enum(entry_obj["status"], "assessment_status", f"{entry_path}.status")
            _string(entry_obj["details"], f"{entry_path}.details", nullable=True)

    decision = _object(
        obj["migration_decision"], f"{path}.migration_decision",
        {"classification", "target_candidate", "rationale", "decision_owner", "route", "prerequisites", "validation"},
        {"classification", "target_candidate", "rationale", "decision_owner", "route", "prerequisites", "validation"},
    )
    _enum(decision["classification"], "migration_classification", f"{path}.migration_decision.classification")
    for field in ("target_candidate", "rationale", "decision_owner", "route"):
        _string(decision[field], f"{path}.migration_decision.{field}", nullable=True)
    if not isinstance(decision["prerequisites"], list):
        _fail(f"{path}.migration_decision.prerequisites", "must be an array")
    for index, precondition in enumerate(decision["prerequisites"]):
        _string(precondition, f"{path}.migration_decision.prerequisites[{index}]")
    validation = _object(
        decision["validation"], f"{path}.migration_decision.validation",
        {"status", "justification"}, {"status", "justification"},
    )
    _enum(validation["status"], "validation_status", f"{path}.migration_decision.validation.status")
    _string(validation["justification"], f"{path}.migration_decision.validation.justification", nullable=True)


def _validate_feature(feature: Any, path: str, object_ids: set[str], *, root: bool) -> None:
    fields = {
        "id", "object_id", "category", "name", "support_status",
        "impact", "description", "conversion_status", "evidence_reference",
    }
    item = _object(feature, path, fields, fields)
    _string(item["id"], f"{path}.id")
    _string(item["object_id"], f"{path}.object_id")
    if item["object_id"] not in object_ids:
        _fail(f"{path}.object_id", "must reference an inventory object")
    _enum(item["category"], "unsupported_category", f"{path}.category")
    _string(item["name"], f"{path}.name")
    _enum(item["support_status"], "support_status", f"{path}.support_status")
    _enum(item["impact"], "impact", f"{path}.impact")
    _string(item["description"], f"{path}.description", nullable=True)
    _enum(item["conversion_status"], "validation_status", f"{path}.conversion_status")
    if item["support_status"] == "unsupported" and item["conversion_status"] == "pass":
        _fail(f"{path}.conversion_status", "unsupported behavior cannot be marked successful")
    _string(item["evidence_reference"], f"{path}.evidence_reference", nullable=True)


def validate_snapshot(snapshot: Any) -> dict:
    """Sanitize, validate and return a safe copy of a BW 1.0 snapshot.

    The source is not modified. A snapshot containing a supported but
    explicitly unsupported BW feature remains an inventory, not a conversion
    success; unsupported features cannot carry a passing conversion status.
    """
    doc = sanitize_snapshot(snapshot)
    if not isinstance(doc, dict):
        _fail("$", "snapshot must be a JSON object")
    if "schema_version" in doc and doc["schema_version"] != CURRENT_SCHEMA_VERSION:
        _fail("$.schema_version", "unsupported schema version; expected 1.0")
    root = _object(doc, "$", _ROOT_FIELDS, _ROOT_FIELDS)
    _string(root["run_id"], "$.run_id")
    _timestamp(root["captured_at"], "$.captured_at")

    source = _object(
        root["source_system"], "$.source_system",
        {"id", "product", "version", "client", "landscape"},
        {"id", "product", "version", "client", "landscape"},
    )
    for field in ("id", "version", "client"):
        _string(source[field], f"$.source_system.{field}")
    _enum(source["product"], "product", "$.source_system.product")
    landscape = _object(
        source["landscape"], "$.source_system.landscape",
        {"id", "name", "status"}, {"id", "name", "status"},
    )
    _string(landscape["id"], "$.source_system.landscape.id", nullable=True)
    _string(landscape["name"], "$.source_system.landscape.name", nullable=True)
    _enum(landscape["status"], "assessment_status", "$.source_system.landscape.status")

    provenance = _object(
        root["provenance"], "$.provenance",
        {"discovery_method", "extraction_method", "extractor_name", "extractor_version", "evidence_reference"},
        {"discovery_method", "extraction_method", "extractor_name", "extractor_version", "evidence_reference"},
    )
    _enum(provenance["discovery_method"], "discovery_method", "$.provenance.discovery_method")
    _enum(provenance["extraction_method"], "discovery_method", "$.provenance.extraction_method")
    for field in ("extractor_name", "extractor_version", "evidence_reference"):
        _string(provenance[field], f"$.provenance.{field}", nullable=True)

    discovery = _object(
        root["discovery"], "$.discovery", {"method", "evidence_reference"},
        {"method", "evidence_reference"},
    )
    _enum(discovery["method"], "discovery_method", "$.discovery.method")
    _string(discovery["evidence_reference"], "$.discovery.evidence_reference", nullable=True)

    access = _object(
        root["extraction_access"], "$.extraction_access",
        {"status", "approval_reference", "credential_material_included"},
        {"status", "approval_reference", "credential_material_included"},
    )
    _enum(access["status"], "access_status", "$.extraction_access.status")
    _string(access["approval_reference"], "$.extraction_access.approval_reference", nullable=True)
    if access["credential_material_included"] is not False:
        _fail("$.extraction_access.credential_material_included", "must be false")

    scope = _object(
        root["scope"], "$.scope",
        {"included_domains", "excluded_domains", "completeness", "owner_signoff", "coverage", "known_gaps"},
        {"included_domains", "excluded_domains", "completeness", "owner_signoff", "coverage", "known_gaps"},
    )
    for field in ("included_domains", "excluded_domains", "known_gaps"):
        if not isinstance(scope[field], list):
            _fail(f"$.scope.{field}", "must be an array")
        for index, value in enumerate(scope[field]):
            _string(value, f"$.scope.{field}[{index}]")
    _enum(scope["completeness"], "coverage", "$.scope.completeness")
    _enum(scope["owner_signoff"], "owner_signoff", "$.scope.owner_signoff")
    coverage_fields = {
        "systems", "sources", "providers", "transformations", "process_chains",
        "consumers", "usage", "data_volume_history_retention", "delta_mechanisms",
        "authorizations", "planning_writeback",
    }
    coverage = _object(scope["coverage"], "$.scope.coverage", coverage_fields, coverage_fields)
    for field, status in coverage.items():
        _enum(status, "coverage", f"$.scope.coverage.{field}")

    if not isinstance(root["objects"], list):
        _fail("$.objects", "must be an array")
    if not root["objects"]:
        _fail("$.objects", "must contain at least one object")
    object_ids = set()
    for index, item in enumerate(root["objects"]):
        _validate_object(item, f"$.objects[{index}]")
        if item["id"] in object_ids:
            _fail(f"$.objects[{index}].id", "object identifiers must be unique")
        object_ids.add(item["id"])

    if not isinstance(root["dependencies"], list):
        _fail("$.dependencies", "must be an array")
    dependency_keys = set()
    for index, edge in enumerate(root["dependencies"]):
        path = f"$.dependencies[{index}]"
        edge = _object(
            edge, path,
            {"source_id", "target_id", "kind", "evidence_status", "resolution_status", "evidence_reference"},
            {"source_id", "target_id", "kind", "evidence_status", "resolution_status", "evidence_reference"},
        )
        for field in ("source_id", "target_id"):
            _string(edge[field], f"{path}.{field}")
        _enum(edge["kind"], "dependency_kind", f"{path}.kind")
        _enum(edge["evidence_status"], "assessment_status", f"{path}.evidence_status")
        _enum(edge["resolution_status"], "resolution_status", f"{path}.resolution_status")
        _string(edge["evidence_reference"], f"{path}.evidence_reference", nullable=True)
        if edge["resolution_status"] == "resolved":
            if edge["source_id"] not in object_ids or edge["target_id"] not in object_ids:
                _fail(path, "resolved dependencies must reference existing objects")
        identity = (edge["source_id"], edge["target_id"], edge["kind"])
        if identity in dependency_keys:
            _fail(path, "dependency edges must be unique")
        dependency_keys.add(identity)

    for collection in ("errors", "unknowns", "unsupported_features"):
        if not isinstance(root[collection], list):
            _fail(f"$.{collection}", "must be an array")
    for index, error in enumerate(root["errors"]):
        path = f"$.errors[{index}]"
        error = _object(
            error, path, {"code", "category", "status", "message", "evidence_reference"},
            {"code", "category", "status", "message", "evidence_reference"},
        )
        for field in ("code", "message"):
            _string(error[field], f"{path}.{field}")
        _enum(error["category"], "error_category", f"{path}.category")
        _enum(error["status"], "assessment_status", f"{path}.status")
        _string(error["evidence_reference"], f"{path}.evidence_reference", nullable=True)

    unknown_ids = set()
    for index, unknown in enumerate(root["unknowns"]):
        path = f"$.unknowns[{index}]"
        unknown = _object(
            unknown, path, {"id", "path", "reason", "status", "owner"},
            {"id", "path", "reason", "status", "owner"},
        )
        for field in ("id", "path", "reason"):
            _string(unknown[field], f"{path}.{field}")
        _enum(unknown["status"], "assessment_status", f"{path}.status")
        _string(unknown["owner"], f"{path}.owner", nullable=True)
        if unknown["id"] in unknown_ids:
            _fail(f"{path}.id", "unknown identifiers must be unique")
        unknown_ids.add(unknown["id"])

    feature_ids = set()
    for index, feature in enumerate(root["unsupported_features"]):
        _validate_feature(feature, f"$.unsupported_features[{index}]", object_ids, root=True)
        if feature["id"] in feature_ids:
            _fail(f"$.unsupported_features[{index}].id", "unsupported feature identifiers must be unique")
        feature_ids.add(feature["id"])
        if feature["support_status"] == "unsupported":
            parent = next(obj for obj in root["objects"] if obj["id"] == feature["object_id"])
            if parent["migration_decision"]["classification"] == "automatic_candidate":
                _fail("$.unsupported_features", "unsupported behavior blocks automatic-candidate classification")
            if parent["migration_decision"]["validation"]["status"] == "pass":
                _fail("$.unsupported_features", "unsupported behavior prevents a passing conversion validation")
    return doc


def assess_bw0(snapshot: Any) -> dict:
    """Report BW-0 inventory blockers without closing the gate or attesting evidence."""
    inventory = validate_snapshot(snapshot)
    findings = []

    def add(code: str, severity: str, path: str) -> None:
        findings.append({"code": code, "severity": severity, "path": path})

    scope = inventory["scope"]
    if scope["completeness"] != "complete":
        add("scope_not_complete", "blocker", "$.scope.completeness")
    if scope["owner_signoff"] != "accepted":
        add("scope_not_signed_off", "blocker", "$.scope.owner_signoff")
    if not any(item["disposition"] == "in_scope" for item in inventory["objects"]):
        add("no_in_scope_objects", "blocker", "$.objects")
    for field, status in scope["coverage"].items():
        if status not in {"complete", "not_applicable"}:
            add("coverage_incomplete", "blocker", f"$.scope.coverage.{field}")
    for index, _gap in enumerate(scope["known_gaps"]):
        add("known_gap_requires_review", "review", f"$.scope.known_gaps[{index}]")

    if inventory["discovery"]["method"] == "unknown":
        add("discovery_method_unknown", "blocker", "$.discovery.method")
    if inventory["discovery"]["evidence_reference"] is None:
        add("discovery_evidence_missing", "blocker", "$.discovery.evidence_reference")
    if inventory["provenance"]["discovery_method"] == "unknown":
        add("provenance_method_unknown", "blocker", "$.provenance.discovery_method")
    if inventory["provenance"]["extraction_method"] == "unknown":
        add("extraction_method_unknown", "blocker", "$.provenance.extraction_method")
    if inventory["provenance"]["evidence_reference"] is None:
        add("provenance_evidence_missing", "blocker", "$.provenance.evidence_reference")
    if inventory["source_system"]["landscape"]["status"] in {"unknown", "not_assessed"}:
        add("landscape_requires_review", "review", "$.source_system.landscape.status")
    if inventory["extraction_access"]["status"] != "granted":
        add("extraction_access_requires_review", "review", "$.extraction_access.status")

    in_scope_count = 0
    consumer_count = 0
    for index, item in enumerate(inventory["objects"]):
        path = f"$.objects[{index}]"
        in_scope = item["disposition"] == "in_scope"
        is_consumer = item["type"] == "consumer"
        in_scope_count += in_scope
        consumer_count += is_consumer
        if item["disposition"] == "unknown":
            add("object_disposition_unknown", "blocker", f"{path}.disposition")
        if item["discovery_status"] == "unknown" and (in_scope or is_consumer):
            add("object_discovery_unknown", "blocker", f"{path}.discovery_status")
        elif item["discovery_status"] == "inferred" and (in_scope or is_consumer):
            add("object_discovery_inferred", "review", f"{path}.discovery_status")
        if (in_scope or is_consumer) and item["business_owner"] is None:
            add("object_owner_missing", "blocker", f"{path}.business_owner")
        if in_scope and item["criticality"] == "unknown":
            add("object_criticality_unknown", "blocker", f"{path}.criticality")

    for index, edge in enumerate(inventory["dependencies"]):
        if edge["resolution_status"] != "resolved":
            add("dependency_unresolved", "blocker", f"$.dependencies[{index}]")
    for index, unknown in enumerate(inventory["unknowns"]):
        if unknown["owner"] is None:
            add("unknown_without_owner", "blocker", f"$.unknowns[{index}].owner")
        else:
            add("unknown_requires_review", "review", f"$.unknowns[{index}]")
    for index, _error in enumerate(inventory["errors"]):
        add("inventory_error_requires_resolution", "blocker", f"$.errors[{index}]")

    blockers = sum(item["severity"] == "blocker" for item in findings)
    reviews = sum(item["severity"] == "review" for item in findings)
    return {
        "schema_version": "1.0",
        "assessment": "bw0_inventory_exit",
        "gate_status": "open" if blockers else "candidate_for_owner_review",
        "gate_closed": False,
        "evidence_boundary": "validated_local_inventory_declarations_only",
        "runtime_evidence": {
            "live_sap_discovery": "not_run",
            "source_owner_attestation_verification": "not_run",
            "bw0_exit_approval": "not_run",
        },
        "summary": {
            "objects_total": len(inventory["objects"]),
            "objects_in_scope": in_scope_count,
            "known_consumers": consumer_count,
            "dependencies_total": len(inventory["dependencies"]),
            "unsupported_features": len(inventory["unsupported_features"]),
            "blockers": blockers,
            "review_items": reviews,
        },
        "findings": findings,
    }


def _draft_01_shape(snapshot: Any) -> dict:
    if not isinstance(snapshot, dict):
        _fail("$", "draft snapshot must be an object")
    if snapshot.get("schema_version") != DRAFT_SCHEMA_VERSION:
        _fail("$.schema_version", "only the known draft version 0.1 can be upgraded")
    # The draft is sanitized before any checks or transformation.
    doc = sanitize_snapshot(snapshot)
    expected = {
        "schema_version", "captured_at", "source_system", "discovery",
        "extraction_access", "scope", "objects", "dependencies",
    }
    if set(doc) != expected:
        _fail("$", "document does not match the known 0.1 draft shape")
    _object(
        doc["source_system"], "$.source_system",
        {"id", "product", "version", "client"},
        {"id", "product", "version", "client"},
    )
    _object(
        doc["discovery"], "$.discovery", {"method", "evidence_reference"},
        {"method", "evidence_reference"},
    )
    _object(
        doc["extraction_access"], "$.extraction_access",
        {"status", "approval_reference", "credential_material_included"},
        {"status", "approval_reference", "credential_material_included"},
    )
    scope_fields = {
        "included_domains", "excluded_domains", "completeness", "owner_signoff",
        "coverage", "known_gaps",
    }
    _object(doc["scope"], "$.scope", scope_fields, scope_fields)
    coverage_fields = {
        "systems", "sources", "providers", "transformations", "process_chains",
        "consumers", "usage", "data_volume_history_retention", "delta_mechanisms",
        "authorizations", "planning_writeback",
    }
    _object(doc["scope"]["coverage"], "$.scope.coverage", coverage_fields, coverage_fields)
    if not isinstance(doc["objects"], list) or not isinstance(doc["dependencies"], list):
        _fail("$", "draft objects and dependencies must be arrays")
    old_object_fields = {
        "id", "type", "name", "discovery_status", "disposition", "criticality",
        "business_owner", "location", "usage_profile", "data_profile",
        "delta_profile", "migration_decision",
    }
    for index, obj in enumerate(doc["objects"]):
        required = set(old_object_fields)
        allowed = set(old_object_fields) | {"source_reference"}
        _object(obj, f"$.objects[{index}]", required, allowed)
        _object(
            obj["migration_decision"], f"$.objects[{index}].migration_decision",
            {"classification", "target_candidate", "rationale", "decision_owner"},
            {"classification", "target_candidate", "rationale", "decision_owner"},
        )
    for index, edge in enumerate(doc["dependencies"]):
        _object(
            edge, f"$.dependencies[{index}]",
            {"source_id", "target_id", "kind", "evidence_status"},
            {"source_id", "target_id", "kind", "evidence_status", "evidence_reference"},
        )
    return doc


def upgrade_snapshot(snapshot: Any) -> dict:
    """Deterministically upgrade the known BW draft 0.1 to strict BW 1.0.

    Every 0.1 field and value is retained. New fields are marked unknown or
    not_assessed; this function does not infer metadata or dependency resolution.
    """
    old = _draft_01_shape(snapshot)
    source = copy.deepcopy(old["source_system"])
    source["landscape"] = {"id": None, "name": None, "status": "not_assessed"}

    provenance = {
        "discovery_method": old["discovery"]["method"],
        "extraction_method": "unknown",
        "extractor_name": None,
        "extractor_version": None,
        "evidence_reference": old["discovery"]["evidence_reference"],
    }
    objects = []
    for old_obj in old["objects"]:
        obj = copy.deepcopy(old_obj)
        obj["metadata_status"] = "not_assessed"
        obj["definition"] = {
            "status": "not_assessed", "reference": None,
            "hash_algorithm": None, "hash": None,
        }
        obj["keys_status"] = "not_assessed"
        obj["keys"] = []
        obj["semantics"] = {
            "status": "not_assessed", "measures": [], "dimensions": [], "functions": [],
        }
        decision = obj["migration_decision"]
        decision.update({
            "route": None,
            "prerequisites": [],
            "validation": {"status": "not_run", "justification": None},
        })
        objects.append(obj)

    dependencies = []
    for old_edge in old["dependencies"]:
        edge = copy.deepcopy(old_edge)
        edge["resolution_status"] = "unknown"
        edge["evidence_reference"] = edge.get("evidence_reference")
        dependencies.append(edge)

    doc = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "run_id": "upgraded-0.1",
        "captured_at": old["captured_at"],
        "source_system": source,
        "provenance": provenance,
        "discovery": copy.deepcopy(old["discovery"]),
        "extraction_access": copy.deepcopy(old["extraction_access"]),
        "scope": copy.deepcopy(old["scope"]),
        "objects": objects,
        "dependencies": dependencies,
        "errors": [],
        "unknowns": [
            {
                "id": "upgrade:run-id", "path": "$.run_id",
                "reason": "BW 0.1 did not provide a snapshot run identifier.",
                "status": "unknown", "owner": None,
            },
            {
                "id": "upgrade:landscape", "path": "$.source_system.landscape",
                "reason": "BW 0.1 did not provide landscape identifiers.",
                "status": "not_assessed", "owner": None,
            },
            {
                "id": "upgrade:extraction-method", "path": "$.provenance.extraction_method",
                "reason": "Discovery method does not establish how metadata was extracted.",
                "status": "unknown", "owner": None,
            },
            {
                "id": "upgrade:dependency-resolution", "path": "$.dependencies[*].resolution_status",
                "reason": "BW 0.1 did not record dependency resolution state.",
                "status": "unknown", "owner": None,
            },
        ],
        "unsupported_features": [],
    }
    # Retain the optional 0.1 discovery evidence without losing its original
    # location/value; the provenance envelope also carries it in a typed field.
    result = validate_snapshot(doc)
    return result


def _load_json_document(path: str | Path) -> Any:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_non_json_constant(_constant):
        raise ValueError("non-standard JSON constant")

    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(
            handle,
            object_pairs_hook=unique_object,
            parse_constant=reject_non_json_constant,
        )


def load_snapshot(path: str | Path) -> dict:
    """Load a local JSON file, sanitize it and validate only the current 1.0 contract."""
    try:
        parsed = _load_json_document(path)
    except (OSError, UnicodeError, ValueError):
        raise BWInventoryError("Unable to load local BW inventory JSON.") from None
    return validate_snapshot(parsed)


__all__ = [
    "BWInventoryError", "CURRENT_SCHEMA_VERSION", "DRAFT_SCHEMA_VERSION",
    "sanitize_snapshot", "validate_snapshot", "assess_bw0", "load_snapshot",
    "upgrade_snapshot",
]
