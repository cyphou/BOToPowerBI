"""Index offline BW wave evidence declarations; this module does not verify evidence.

The evaluator indexes local declarations only. It does not dereference or verify
report bytes, establish freshness or correctness, execute SAP/Fabric controls,
certify operations, or approve retirement. SAP/Fabric runtime evidence remains
``not_run``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, NoReturn

from .bw_inventory import assess_bw0, validate_snapshot
from .security_validator import scan_for_credentials


CURRENT_SCHEMA_VERSION = "1.0"
LAYERS = ("bw2_reconciliation", "bw3_handoff", "bw4_transform", "bw5_bex", "bw6_controls")
OPERATIONAL_KINDS = (
    "freshness_target", "latency_target", "availability_target", "cost_target",
    "monitoring_alerting", "failure_replay", "schema_drift", "restore", "rpo_rto",
)
_LAYER_SET = set(LAYERS)
_OPERATIONAL_SET = set(OPERATIONAL_KINDS)
_APPLICABILITY = {"applicable", "not_applicable"}
_LAYER_STATUS = {"pass", "fail", "not_run", "not_applicable"}
_OPERATIONAL_STATUS = {"pass", "fail", "not_run"}
_DISPOSITIONS = {"unresolved", "resolved", "accepted"}
_REFERENCE = re.compile(r"[^\x00-\x20\x7f]{1,256}\Z")

_ROOT_FIELDS = {
    "schema_version", "wave_id", "inventory_scope", "traceability",
    "object_evidence", "operational_evidence", "exceptions",
}


class BWWaveEvidenceError(ValueError):
    """Raised when an offline BW wave evidence index violates its contract."""


def _fail(path: str, reason: str) -> NoReturn:
    raise BWWaveEvidenceError(f"BW wave evidence contract error at {path}: {reason}")


def _object(value: Any, path: str, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(path, "must contain exactly the supported fields")
    return value


def _reference(value: Any, path: str, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        _fail(path, "must be a well-formed opaque reference")


def _identifier(value: Any, path: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        _fail(path, "must be a non-empty identifier without control characters")


def _choice(value: Any, choices: set[str], path: str, reason: str) -> None:
    if not isinstance(value, str) or value not in choices:
        _fail(path, reason)


def _safe_content(manifest: Any) -> None:
    try:
        encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        _fail("$", "must contain only standard JSON values")
    if scan_for_credentials(encoded):
        _fail("$", "credential-like content is not allowed")


def validate_wave_evidence(manifest: Any) -> dict:
    """Validate a versioned declaration index without opening referenced evidence."""
    _object(manifest, "$", _ROOT_FIELDS)
    _safe_content(manifest)
    if manifest["schema_version"] != CURRENT_SCHEMA_VERSION:
        _fail("$.schema_version", "expected version 1.0")
    _reference(manifest["wave_id"], "$.wave_id")

    scope = _object(
        manifest["inventory_scope"], "$.inventory_scope",
        {"inventory_id", "inventory_run_id", "object_ids"},
    )
    _identifier(scope["inventory_id"], "$.inventory_scope.inventory_id")
    _identifier(scope["inventory_run_id"], "$.inventory_scope.inventory_run_id")
    object_ids = scope["object_ids"]
    if not isinstance(object_ids, list) or not object_ids:
        _fail("$.inventory_scope.object_ids", "must be a non-empty array")
    if any(
        not isinstance(item, str) or not item.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in item)
        for item in object_ids
    ):
        _fail("$.inventory_scope.object_ids", "must contain non-empty inventory object IDs")
    if len(object_ids) != len(set(object_ids)):
        _fail("$.inventory_scope.object_ids", "must not contain duplicate IDs")

    trace = _object(
        manifest["traceability"], "$.traceability",
        {
            "source_version_reference", "target_version_reference",
            "extract_boundary_reference", "grain_reference",
        },
    )
    for field, value in trace.items():
        _reference(value, f"$.traceability.{field}")

    exceptions = manifest["exceptions"]
    if not isinstance(exceptions, list):
        _fail("$.exceptions", "must be an array")
    exception_by_id = {}
    for index, raw in enumerate(exceptions):
        path = f"$.exceptions[{index}]"
        item = _object(
            raw, path,
            {"id", "object_id", "layer", "owner_reference", "disposition", "approval_reference"},
        )
        _reference(item["id"], f"{path}.id")
        if item["id"] in exception_by_id:
            _fail(f"{path}.id", "exception IDs must be unique")
        if not isinstance(item["object_id"], str) or item["object_id"] not in object_ids:
            _fail(f"{path}.object_id", "must reference an object in the declared wave scope")
        _choice(item["layer"], _LAYER_SET, f"{path}.layer", "must identify a BW-2..6 evidence layer")
        _reference(item["owner_reference"], f"{path}.owner_reference")
        _choice(item["disposition"], _DISPOSITIONS, f"{path}.disposition", "has an unsupported disposition")
        _reference(item["approval_reference"], f"{path}.approval_reference", nullable=True)
        if item["disposition"] == "accepted" and item["approval_reference"] is None:
            _fail(f"{path}.approval_reference", "is required for an accepted exception")
        exception_by_id[item["id"]] = item

    records = manifest["object_evidence"]
    if not isinstance(records, list):
        _fail("$.object_evidence", "must be an array")
    seen_objects = set()
    referenced_exceptions = set()
    for index, raw in enumerate(records):
        path = f"$.object_evidence[{index}]"
        item = _object(raw, path, {"object_id", "layers"})
        object_id = item["object_id"]
        if object_id not in object_ids:
            _fail(f"{path}.object_id", "must reference an object in the declared wave scope")
        if object_id in seen_objects:
            _fail(f"{path}.object_id", "must occur exactly once")
        seen_objects.add(object_id)
        layers = item["layers"]
        if not isinstance(layers, list):
            _fail(f"{path}.layers", "must be an array")
        seen_layers = set()
        for layer_index, raw_layer in enumerate(layers):
            layer_path = f"{path}.layers[{layer_index}]"
            layer = _object(
                raw_layer, layer_path,
                {"kind", "applicability", "status", "evidence_reference", "owner_reference", "exception_ids"},
            )
            kind = layer["kind"]
            if not isinstance(kind, str) or kind not in _LAYER_SET or kind in seen_layers:
                _fail(f"{layer_path}.kind", "must uniquely identify a BW-2..6 evidence layer")
            seen_layers.add(kind)
            applicability = layer["applicability"]
            status = layer["status"]
            _choice(applicability, _APPLICABILITY, f"{layer_path}.applicability", "must be explicit")
            _choice(status, _LAYER_STATUS, f"{layer_path}.status", "has an unsupported status")
            if applicability == "not_applicable":
                if status != "not_applicable" or layer["evidence_reference"] is not None:
                    _fail(layer_path, "not-applicable evidence must have not_applicable status and no evidence reference")
                _reference(layer["owner_reference"], f"{layer_path}.owner_reference", nullable=True)
            else:
                if status == "not_applicable":
                    _fail(f"{layer_path}.status", "applicable evidence cannot be not_applicable")
                _reference(layer["evidence_reference"], f"{layer_path}.evidence_reference")
                _reference(layer["owner_reference"], f"{layer_path}.owner_reference")
            exception_ids = layer["exception_ids"]
            if not isinstance(exception_ids, list):
                _fail(f"{layer_path}.exception_ids", "must be an array")
            for exception_index, exception_id in enumerate(exception_ids):
                _reference(exception_id, f"{layer_path}.exception_ids[{exception_index}]")
            if len(exception_ids) != len(set(exception_ids)):
                _fail(f"{layer_path}.exception_ids", "must not contain duplicates")
            for exception_id in exception_ids:
                exception = exception_by_id.get(exception_id)
                if exception is None or exception["object_id"] != object_id or exception["layer"] != kind:
                    _fail(f"{layer_path}.exception_ids", "must reference a matching declared exception")
                referenced_exceptions.add(exception_id)
        if seen_layers != _LAYER_SET:
            _fail(f"{path}.layers", "must declare each BW-2..6 layer exactly once")
    if seen_objects != set(object_ids):
        _fail("$.object_evidence", "must cover every declared inventory object exactly once")
    if referenced_exceptions != set(exception_by_id):
        _fail("$.exceptions", "each exception must be linked from its object and layer evidence")

    operational = manifest["operational_evidence"]
    if not isinstance(operational, list):
        _fail("$.operational_evidence", "must be an array")
    seen_kinds = set()
    for index, raw in enumerate(operational):
        path = f"$.operational_evidence[{index}]"
        item = _object(raw, path, {"kind", "status", "evidence_reference", "owner_reference"})
        kind = item["kind"]
        if not isinstance(kind, str) or kind not in _OPERATIONAL_SET or kind in seen_kinds:
            _fail(f"{path}.kind", "must uniquely identify a required operational evidence kind")
        seen_kinds.add(kind)
        _choice(item["status"], _OPERATIONAL_STATUS, f"{path}.status", "has an unsupported status")
        _reference(item["evidence_reference"], f"{path}.evidence_reference")
        _reference(item["owner_reference"], f"{path}.owner_reference")
    if seen_kinds != _OPERATIONAL_SET:
        _fail("$.operational_evidence", "must cover each required operational evidence kind exactly once")
    return manifest


def load_wave_evidence(path: str | Path) -> dict:
    """Load and validate UTF-8 JSON, rejecting duplicate keys and non-JSON constants."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("non-standard JSON constant")

    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            document = json.load(
                handle, object_pairs_hook=unique_object, parse_constant=reject_constant
            )
    except (OSError, UnicodeError, ValueError):
        raise BWWaveEvidenceError("Unable to load local BW wave evidence JSON.") from None
    return validate_wave_evidence(document)


def assess_wave_evidence(inventory: Any, manifest: Any) -> dict:
    """Index declared evidence against BW-0 inventory scope; never verify evidence bytes."""
    bw_inventory = validate_snapshot(inventory)
    index = validate_wave_evidence(manifest)
    scope = index["inventory_scope"]
    if scope["inventory_id"] != bw_inventory["source_system"]["id"]:
        _fail("$.inventory_scope.inventory_id", "must match the BW inventory source-system ID")
    if scope["inventory_run_id"] != bw_inventory["run_id"]:
        _fail("$.inventory_scope.inventory_run_id", "must match the BW inventory run ID")
    in_scope = {
        item["id"] for item in bw_inventory["objects"]
        if item["disposition"] == "in_scope"
    }
    if not set(scope["object_ids"]) <= in_scope:
        _fail("$.inventory_scope.object_ids", "must reference only in-scope BW inventory objects")

    findings = []
    actions = []
    inventory_review = assess_bw0(bw_inventory)

    if inventory_review["gate_status"] == "open":
        findings.append({"code": "inventory_scope_gate_open", "path": "$.inventory"})

    def record(code: str, path: str, owner: str) -> None:
        findings.append({"code": code, "path": path})
        actions.append({"owner_reference": owner, "action": code})

    for object_index, item in enumerate(index["object_evidence"]):
        for layer_index, layer in enumerate(item["layers"]):
            if layer["applicability"] == "applicable" and layer["status"] != "pass":
                record(
                    f"{layer['kind']}_{layer['status']}",
                    f"$.object_evidence[{object_index}].layers[{layer_index}]",
                    layer["owner_reference"],
                )
    for index_in_list, item in enumerate(index["operational_evidence"]):
        if item["status"] != "pass":
            record(
                f"operational_{item['kind']}_{item['status']}",
                f"$.operational_evidence[{index_in_list}]",
                item["owner_reference"],
            )
    for exception_index, item in enumerate(index["exceptions"]):
        if item["disposition"] == "unresolved":
            record(
                "exception_unresolved",
                f"$.exceptions[{exception_index}]",
                item["owner_reference"],
            )

    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "wave_id": index["wave_id"],
        "status": "open" if findings else "candidate_for_owner_review",
        "gate_closed": False,
        "evidence_boundary": "validated_local_inventory_and_declared_evidence_references_only",
        "inventory_gate_status": inventory_review["gate_status"],
        "inventory_scope": scope,
        "traceability": index["traceability"],
        "object_evidence": index["object_evidence"],
        "operational_evidence": index["operational_evidence"],
        "exceptions": index["exceptions"],
        "findings": findings,
        "owner_actions": actions,
        "summary": {
            "blockers": len(findings),
            "owner_actions": len(actions),
            "inventory_objects": len(scope["object_ids"]),
        },
        "coverage": {
            "inventory_objects": len(scope["object_ids"]),
            "object_layers": len(scope["object_ids"]) * len(LAYERS),
            "operational_evidence_kinds": len(OPERATIONAL_KINDS),
        },
        "runtime_evidence": {
            "sap_execution": "not_run",
            "fabric_execution": "not_run",
            "operational_certification": "not_run",
            "retirement_approval": "not_run",
        },
        "limitations": [
            "Indexes local declarations only; referenced report bytes are not dereferenced or verified.",
            "Does not establish evidence freshness or correctness, execute SAP/Fabric controls, certify operations, or approve retirement.",
        ],
    }


__all__ = [
    "BWWaveEvidenceError", "CURRENT_SCHEMA_VERSION", "LAYERS",
    "OPERATIONAL_KINDS", "assess_wave_evidence", "load_wave_evidence",
    "validate_wave_evidence",
]
