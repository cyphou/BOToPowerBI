"""Assess declared BW security, planning, and compliance controls offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

from .bw_inventory import assess_bw0, validate_snapshot
from .security_validator import scan_for_credentials


class BWControlsAssessmentError(ValueError):
    """Raised when a local BW controls manifest is invalid."""


_ROOT_FIELDS = {
    "schema_version", "scope_id", "coverage", "authorization_contexts",
    "access_scenarios", "planning_processes", "obligations",
}
_COVERAGE_FIELDS = {
    "authorization_contexts", "access_matrix", "planning_writeback",
    "audit", "retention", "privacy", "legal_hold",
}
_COVERAGE = {"complete", "partial", "not_assessed", "not_applicable"}
_ASSESSMENT = {"observed", "inferred", "unknown", "not_assessed"}
_CONTROL_FIELDS = {
    "write_back", "locking", "approval_workflow", "separation_of_duties",
    "audit", "recovery",
}
_OBLIGATION_CATEGORIES = {"audit", "retention", "privacy", "legal_hold"}


def _fail(path: str, reason: str) -> NoReturn:
    raise BWControlsAssessmentError(f"BW controls manifest error at {path}: {reason}")


def _object(value: Any, path: str, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(path, "must contain exactly the supported fields")
    return value


def _text(value: Any, path: str, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        _fail(
            path,
            "must be a non-empty string" if not nullable else "must be a string or null",
        )


def _status(value: Any, path: str) -> None:
    if not isinstance(value, str) or value not in _ASSESSMENT:
        _fail(path, "has an unsupported assessment status")


def _unique_records(value: Any, path: str, fields: set[str], key: str) -> list[dict]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    seen = set()
    result = []
    for index, raw in enumerate(value):
        item_path = f"{path}[{index}]"
        item = _object(raw, item_path, fields)
        _text(item[key], f"{item_path}.{key}")
        if item[key] in seen:
            _fail(f"{item_path}.{key}", "must be unique within its section")
        seen.add(item[key])
        result.append(item)
    return result


def validate_controls_manifest(manifest: Any) -> dict:
    """Validate a strict local declaration; no control is executed or approved."""
    root = _object(manifest, "$", _ROOT_FIELDS)
    if root["schema_version"] != "1.0":
        _fail("$.schema_version", "expected version 1.0")
    try:
        encoded = json.dumps(manifest, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        _fail("$", "must contain only JSON-compatible values")
    if scan_for_credentials(encoded):
        _fail("$", "credential-like content is not allowed")

    _text(root["scope_id"], "$.scope_id")
    coverage = _object(root["coverage"], "$.coverage", _COVERAGE_FIELDS)
    for field, value in coverage.items():
        if not isinstance(value, str) or value not in _COVERAGE:
            _fail(f"$.coverage.{field}", "has an unsupported coverage status")

    contexts = _unique_records(
        root["authorization_contexts"],
        "$.authorization_contexts",
        {
            "id", "inventory_object_id", "role_reference", "data_scope_reference",
            "target_control_reference", "status", "evidence_reference",
        },
        "id",
    )
    context_ids = set()
    inventory_ids = set()
    for index, item in enumerate(contexts):
        path = f"$.authorization_contexts[{index}]"
        for field in (
            "inventory_object_id", "role_reference", "data_scope_reference",
            "target_control_reference",
        ):
            _text(item[field], f"{path}.{field}")
        _status(item["status"], f"{path}.status")
        _text(item["evidence_reference"], f"{path}.evidence_reference", nullable=True)
        if item["inventory_object_id"] in inventory_ids:
            _fail(f"{path}.inventory_object_id", "must be unique")
        inventory_ids.add(item["inventory_object_id"])
        context_ids.add(item["id"])

    scenarios = _unique_records(
        root["access_scenarios"],
        "$.access_scenarios",
        {
            "id", "authorization_context_id", "expectation", "action_reference",
            "target_control_reference", "execution_status",
        },
        "id",
    )
    for index, item in enumerate(scenarios):
        path = f"$.access_scenarios[{index}]"
        _text(item["authorization_context_id"], f"{path}.authorization_context_id")
        if item["authorization_context_id"] not in context_ids:
            _fail(f"{path}.authorization_context_id", "must reference a declared authorization context")
        if not isinstance(item["expectation"], str) or item["expectation"] not in {"allow", "deny"}:
            _fail(f"{path}.expectation", "must be allow or deny")
        for field in ("action_reference", "target_control_reference"):
            _text(item[field], f"{path}.{field}")
        if item["execution_status"] != "not_run":
            _fail(f"{path}.execution_status", "must remain not_run in this offline contract")

    planning = _unique_records(
        root["planning_processes"],
        "$.planning_processes",
        {
            "inventory_object_id", "disposition", "owner_reference",
            "target_solution_reference", "control_coverage", "evidence_reference",
        },
        "inventory_object_id",
    )
    for index, item in enumerate(planning):
        path = f"$.planning_processes[{index}]"
        if not isinstance(item["disposition"], str) or item["disposition"] not in {
            "replacement_selected", "manual_redesign", "blocked",
        }:
            _fail(f"{path}.disposition", "has an unsupported planning disposition")
        _text(item["owner_reference"], f"{path}.owner_reference", nullable=True)
        _text(item["target_solution_reference"], f"{path}.target_solution_reference", nullable=True)
        _text(item["evidence_reference"], f"{path}.evidence_reference", nullable=True)
        controls = _object(item["control_coverage"], f"{path}.control_coverage", _CONTROL_FIELDS)
        for field, value in controls.items():
            if not isinstance(value, str) or value not in (_ASSESSMENT | {"not_applicable"}):
                _fail(f"{path}.control_coverage.{field}", "has an unsupported assessment status")

    obligations = _unique_records(
        root["obligations"],
        "$.obligations",
        {
            "id", "category", "inventory_object_id", "source_control_reference",
            "target_control_reference", "owner_reference", "status",
            "evidence_reference",
        },
        "id",
    )
    for index, item in enumerate(obligations):
        path = f"$.obligations[{index}]"
        if not isinstance(item["category"], str) or item["category"] not in _OBLIGATION_CATEGORIES:
            _fail(f"{path}.category", "has an unsupported obligation category")
        for field in (
            "inventory_object_id", "source_control_reference", "target_control_reference",
            "owner_reference", "evidence_reference",
        ):
            _text(item[field], f"{path}.{field}", nullable=True)
        _status(item["status"], f"{path}.status")

    sections = {
        "authorization_contexts": contexts,
        "access_matrix": scenarios,
        "planning_writeback": planning,
    }
    for field, records in sections.items():
        state = coverage[field]
        if state == "complete" and not records:
            _fail(f"$.coverage.{field}", "empty sections must be marked not_applicable")
        if state == "not_applicable" and records:
            _fail(f"$.coverage.{field}", "not_applicable sections must be empty")
    if coverage["access_matrix"] == "not_applicable" and contexts:
        _fail("$.coverage.access_matrix", "cannot be not_applicable when authorization contexts exist")
    for category in _OBLIGATION_CATEGORIES:
        matching = [item for item in obligations if item["category"] == category]
        state = coverage[category]
        if state == "complete" and not matching:
            _fail(f"$.coverage.{category}", "complete coverage requires an obligation")
        if state == "not_applicable" and matching:
            _fail(f"$.coverage.{category}", "not_applicable coverage cannot contain obligations")
    return root


def load_controls_manifest(path: str | Path) -> dict:
    """Load a local manifest, rejecting duplicate JSON keys and nonstandard constants."""
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                _fail("$", "duplicate JSON object keys are not allowed")
            value[key] = item
        return value

    def invalid_constant(_value):
        _fail("$", "non-standard JSON constants are not allowed")

    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            manifest = json.load(
                handle, object_pairs_hook=unique_object, parse_constant=invalid_constant
            )
    except BWControlsAssessmentError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail("$", "unable to read a valid UTF-8 JSON manifest")
    return validate_controls_manifest(manifest)


def assess_bw_controls(inventory: Any, manifest: Any) -> dict:
    """Report declared BW controls gaps; never infer or execute target behavior."""
    bw_inventory = validate_snapshot(inventory)
    controls = validate_controls_manifest(manifest)
    inventory_id = bw_inventory["source_system"]["id"]
    if controls["scope_id"] != inventory_id:
        _fail("$.scope_id", "must match the BW inventory source-system ID")

    objects = {item["id"]: item for item in bw_inventory["objects"]}
    auth_objects = {
        item["id"] for item in bw_inventory["objects"]
        if item["type"] == "authorization" and item["disposition"] == "in_scope"
    }
    planning_objects = {
        item["id"] for item in bw_inventory["objects"]
        if item["type"] == "planning_process" and item["disposition"] == "in_scope"
    }
    captured_auth = {
        item["inventory_object_id"] for item in controls["authorization_contexts"]
    }
    captured_planning = {
        item["inventory_object_id"] for item in controls["planning_processes"]
    }
    for section, declared_ids, expected_ids, expected_type in (
        ("authorization_contexts", captured_auth, auth_objects, "authorization"),
        ("planning_processes", captured_planning, planning_objects, "planning_process"),
    ):
        for object_id in declared_ids:
            source_object = objects.get(object_id)
            if source_object is None or source_object["type"] != expected_type:
                _fail(f"$.{section}", f"references must identify inventory {expected_type} objects")
        if declared_ids - expected_ids:
            _fail(f"$.{section}", "out-of-scope inventory objects cannot be declared as active controls")

    findings = []

    def add(code: str, severity: str, path: str) -> None:
        findings.append({"code": code, "severity": severity, "path": path})

    inventory_review = assess_bw0(bw_inventory)
    if inventory_review["gate_status"] == "open":
        add("inventory_scope_gate_open", "blocker", "$.inventory")
    for field, state in controls["coverage"].items():
        if state not in {"complete", "not_applicable"}:
            add("control_coverage_incomplete", "blocker", f"$.coverage.{field}")

    for object_id in sorted(auth_objects - captured_auth):
        add("authorization_not_captured", "blocker", "$.authorization_contexts")
    for index, item in enumerate(controls["authorization_contexts"]):
        path = f"$.authorization_contexts[{index}]"
        if item["status"] != "observed":
            add("authorization_context_unverified", "blocker", f"{path}.status")
        elif item["evidence_reference"] is None:
            add("authorization_evidence_missing", "blocker", f"{path}.evidence_reference")
    expected_by_context = {
        item["id"]: set() for item in controls["authorization_contexts"]
    }
    for index, item in enumerate(controls["access_scenarios"]):
        expected_by_context[item["authorization_context_id"]].add(item["expectation"])
    for index, context in enumerate(controls["authorization_contexts"]):
        if expected_by_context[context["id"]] != {"allow", "deny"}:
            add(
                "access_matrix_missing_allow_or_deny_case",
                "blocker",
                f"$.authorization_contexts[{index}]",
            )

    for object_id in sorted(planning_objects - captured_planning):
        add("planning_process_not_captured", "blocker", "$.planning_processes")
    for index, item in enumerate(controls["planning_processes"]):
        path = f"$.planning_processes[{index}]"
        if item["disposition"] == "blocked":
            add("planning_process_blocked", "blocker", f"{path}.disposition")
        if item["owner_reference"] is None:
            add("planning_owner_missing", "blocker", f"{path}.owner_reference")
        if item["disposition"] != "blocked" and item["target_solution_reference"] is None:
            add("planning_target_undecided", "blocker", f"{path}.target_solution_reference")
        if (
            item["disposition"] != "blocked"
            and any(status == "observed" for status in item["control_coverage"].values())
            and item["evidence_reference"] is None
        ):
            add("planning_evidence_missing", "blocker", f"{path}.evidence_reference")
        for control, status in item["control_coverage"].items():
            if status not in {"observed", "not_applicable"}:
                add("planning_control_unassessed", "blocker", f"{path}.control_coverage.{control}")

    for index, item in enumerate(controls["obligations"]):
        object_id = item["inventory_object_id"]
        if object_id is not None and object_id not in objects:
            _fail(f"$.obligations[{index}].inventory_object_id", "must reference an inventory object")

    for category in sorted(_OBLIGATION_CATEGORIES):
        entries = [
            (index, item) for index, item in enumerate(controls["obligations"])
            if item["category"] == category
        ]
        if controls["coverage"][category] == "complete" and not entries:
            add("compliance_obligation_not_captured", "blocker", f"$.obligations.{category}")
        for index, item in entries:
            path = f"$.obligations[{index}]"
            if item["status"] != "observed":
                add("compliance_obligation_unverified", "blocker", f"{path}.status")
            for field in (
                "source_control_reference", "target_control_reference", "owner_reference",
            ):
                if item[field] is None:
                    add("compliance_control_unreferenced", "blocker", f"{path}.{field}")
            if item["status"] == "observed" and item["evidence_reference"] is None:
                add("compliance_evidence_missing", "blocker", f"{path}.evidence_reference")

    for index, feature in enumerate(bw_inventory["unsupported_features"]):
        if (
            feature["category"] in {"authorization", "planning_writeback"}
            and feature["support_status"] in {"unsupported", "unknown"}
        ):
            add("unsupported_security_or_planning_feature", "blocker", f"$.inventory.unsupported_features[{index}]")

    blockers = sum(item["severity"] == "blocker" for item in findings)
    reviews = sum(item["severity"] == "review" for item in findings)
    return {
        "schema_version": "1.0",
        "assessment": "bw6_security_planning_compliance",
        "gate_status": "open" if blockers else "candidate_for_owner_review",
        "gate_closed": False,
        "evidence_boundary": "validated_local_inventory_and_declared_controls_only",
        "runtime_evidence": {
            "positive_authorization_tests": "not_run",
            "negative_authorization_tests": "not_run",
            "identity_and_binding_checks": "not_run",
            "planning_workflow_execution": "not_run",
            "audit_and_retention_verification": "not_run",
            "fabric_deployment_or_execution": "not_run",
        },
        "summary": {
            "inventory_gate_status": inventory_review["gate_status"],
            "authorization_contexts": len(controls["authorization_contexts"]),
            "access_scenarios": len(controls["access_scenarios"]),
            "planning_processes": len(controls["planning_processes"]),
            "compliance_obligations": len(controls["obligations"]),
            "blockers": blockers,
            "review_items": reviews,
        },
        "findings": findings,
    }
