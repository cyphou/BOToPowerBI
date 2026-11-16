"""Assess local BW cutover and retirement declarations without authorization."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, NoReturn

from .bw_inventory import assess_bw0, validate_snapshot
from .bw_wave_evidence_index import (
    assess_wave_evidence,
)
from .security_validator import scan_for_credentials

CURRENT_SCHEMA_VERSION = "1.0"
DEPENDENCY_CATEGORIES = {
    "bo_consumer", "non_bo_consumer", "upstream_feed", "queue", "job",
    "account", "integration", "audit_record", "legal_record", "other",
}
DEPENDENCY_DISPOSITIONS = {
    "migrated", "removed", "retained_outside_bw", "accepted_residual",
    "unresolved", "not_run",
}
CHECK_KINDS = (
    "bw0_to_bw7_owner_acceptance",
    "upstream_feeds_operational",
    "planning_retention_signed_off",
    "reconciliation_thresholds_met",
    "consumer_security_tests",
    "post_cutover_monitoring",
    "business_go_no_go",
    "source_owner_go_no_go",
    "security_go_no_go",
    "compliance_go_no_go",
    "operations_go_no_go",
    "archives_and_restore",
    "bw_unavailable_independence",
    "no_remaining_live_dependencies",
    "decommission_approval",
    "deactivation_evidence",
)
_APPROVAL_CHECKS = {
    "bw0_to_bw7_owner_acceptance", "planning_retention_signed_off",
    "business_go_no_go",
    "source_owner_go_no_go", "security_go_no_go",
    "compliance_go_no_go", "operations_go_no_go", "decommission_approval",
}
_CHECK_STATUS = {"pass", "fail", "not_run"}
_ROLLBACK_STATUS = {"pass", "fail", "not_run"}
_REFERENCE = re.compile(r"[^\x00-\x20\x7f]{1,256}\Z")
_ROOT_FIELDS = {
    "schema_version", "wave_id", "inventory_scope", "dependency_dispositions",
    "cutover_plan", "parallel_run", "independent_observation", "rollback", "checks",
}


class BWCutoverAssessmentError(ValueError):
    """Raised when a local BW cutover declaration is invalid."""


def _fail(path: str, reason: str) -> NoReturn:
    raise BWCutoverAssessmentError(f"BW cutover manifest error at {path}: {reason}")


def _object(value: Any, path: str, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(path, "must contain exactly the supported fields")
    return value


def _identifier(value: Any, path: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        _fail(path, "must be a non-empty identifier without control characters")


def _reference(value: Any, path: str, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        _fail(path, "must be a well-formed opaque reference")


def _integer(value: Any, path: str, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(path, f"must be an integer greater than or equal to {minimum}")


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


def validate_cutover_manifest(manifest: Any) -> dict:
    """Validate a strict BW-8 declaration set; no operation is executed."""
    root = _object(manifest, "$", _ROOT_FIELDS)
    _safe_content(root)
    if root["schema_version"] != CURRENT_SCHEMA_VERSION:
        _fail("$.schema_version", "expected version 1.0")
    _reference(root["wave_id"], "$.wave_id")

    scope = _object(
        root["inventory_scope"], "$.inventory_scope",
        {"inventory_id", "inventory_run_id", "dependency_coverage"},
    )
    _identifier(scope["inventory_id"], "$.inventory_scope.inventory_id")
    _identifier(scope["inventory_run_id"], "$.inventory_scope.inventory_run_id")
    _choice(
        scope["dependency_coverage"], {"complete", "partial", "not_assessed"},
        "$.inventory_scope.dependency_coverage", "has an unsupported coverage status",
    )

    dependencies = root["dependency_dispositions"]
    if not isinstance(dependencies, list):
        _fail("$.dependency_dispositions", "must be an array")
    seen_dependency_ids = set()
    seen_edges = set()
    for index, raw in enumerate(dependencies):
        path = f"$.dependency_dispositions[{index}]"
        item = _object(
            raw, path,
            {
                "id", "category", "inventory_object_id", "inventory_edge",
                "disposition", "owner_reference", "evidence_reference",
                "approval_reference",
            },
        )
        _reference(item["id"], f"{path}.id")
        if item["id"] in seen_dependency_ids:
            _fail(f"{path}.id", "must be unique")
        seen_dependency_ids.add(item["id"])
        _choice(
            item["category"], DEPENDENCY_CATEGORIES, f"{path}.category",
            "has an unsupported dependency category",
        )
        _reference(item["inventory_object_id"], f"{path}.inventory_object_id", nullable=True)
        edge = item["inventory_edge"]
        if edge is not None:
            edge = _object(edge, f"{path}.inventory_edge", {"source_id", "target_id", "kind"})
            for field in ("source_id", "target_id", "kind"):
                _identifier(edge[field], f"{path}.inventory_edge.{field}")
            edge_key = (edge["source_id"], edge["target_id"], edge["kind"])
            if edge_key in seen_edges:
                _fail(f"{path}.inventory_edge", "must not duplicate an inventory dependency")
            seen_edges.add(edge_key)
        elif item["category"] == "bo_consumer" and item["inventory_object_id"] is None:
            _fail(path, "a BO consumer must link to an inventory object")

        _choice(
            item["disposition"], DEPENDENCY_DISPOSITIONS, f"{path}.disposition",
            "has an unsupported dependency disposition",
        )
        for field in ("owner_reference", "evidence_reference", "approval_reference"):
            _reference(item[field], f"{path}.{field}", nullable=True)

    plan = _object(
        root["cutover_plan"], "$.cutover_plan",
        {
            "runbook_reference", "freeze_checkpoint_reference",
            "watermark_catchup_reference", "reconciliation_threshold_reference",
            "consumer_switch_plan_reference", "communications_plan_reference",
            "monitoring_plan_reference", "escalation_plan_reference",
        },
    )
    for field, value in plan.items():
        _reference(value, f"$.cutover_plan.{field}", nullable=True)

    for section in ("parallel_run", "independent_observation"):
        period = _object(
            root[section], f"$.{section}",
            {"minimum_days", "completed_days", "evidence_reference", "owner_reference"},
        )
        _integer(period["minimum_days"], f"$.{section}.minimum_days", 1)
        _integer(period["completed_days"], f"$.{section}.completed_days", 0)
        _reference(period["evidence_reference"], f"$.{section}.evidence_reference", nullable=True)
        _reference(period["owner_reference"], f"$.{section}.owner_reference", nullable=True)

    rollback = _object(
        root["rollback"], "$.rollback",
        {
            "trigger_reference", "time_limit_minutes", "recovery_objective_reference",
            "divergence_handling_reference", "runbook_reference", "exercise_status",
            "exercise_evidence_reference", "owner_reference",
        },
    )
    for field in (
        "trigger_reference", "recovery_objective_reference", "divergence_handling_reference",
        "runbook_reference", "exercise_evidence_reference", "owner_reference",
    ):
        _reference(rollback[field], f"$.rollback.{field}", nullable=True)
    _integer(rollback["time_limit_minutes"], "$.rollback.time_limit_minutes", 1)
    _choice(
        rollback["exercise_status"], _ROLLBACK_STATUS,
        "$.rollback.exercise_status", "has an unsupported exercise status",
    )

    checks = root["checks"]
    if not isinstance(checks, list):
        _fail("$.checks", "must be an array")
    seen_checks = set()
    for index, raw in enumerate(checks):
        path = f"$.checks[{index}]"
        item = _object(
            raw, path,
            {"kind", "status", "evidence_reference", "owner_reference", "approval_reference"},
        )
        kind = item["kind"]
        if not isinstance(kind, str) or kind not in CHECK_KINDS or kind in seen_checks:
            _fail(f"{path}.kind", "must uniquely identify a required BW-8 check")
        seen_checks.add(kind)
        _choice(item["status"], _CHECK_STATUS, f"{path}.status", "has an unsupported status")
        for field in ("evidence_reference", "owner_reference", "approval_reference"):
            _reference(item[field], f"{path}.{field}", nullable=True)
    if seen_checks != set(CHECK_KINDS):
        _fail("$.checks", "must declare every required BW-8 check exactly once")
    return root


def load_cutover_manifest(path: str | Path) -> dict:
    """Load UTF-8 JSON with duplicate-key and non-standard-constant rejection."""
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
        raise BWCutoverAssessmentError("Unable to load local BW cutover declaration JSON.") from None
    return validate_cutover_manifest(document)


def assess_bw_cutover(inventory: Any, wave_manifest: Any, manifest: Any) -> dict:
    """Assess declared cutover prerequisites without verifying evidence or authorizing action."""
    bw_inventory = validate_snapshot(inventory)
    wave_review = assess_wave_evidence(bw_inventory, wave_manifest)
    cutover = validate_cutover_manifest(manifest)
    source_id = bw_inventory["source_system"]["id"]
    inventory_run_id = bw_inventory["run_id"]
    if cutover["wave_id"] != wave_review["wave_id"]:
        _fail("$.wave_id", "must match the BW-7 evidence wave ID")
    scope = cutover["inventory_scope"]
    if scope["inventory_id"] != source_id:
        _fail("$.inventory_scope.inventory_id", "must match the BW inventory source-system ID")
    if scope["inventory_run_id"] != inventory_run_id:
        _fail("$.inventory_scope.inventory_run_id", "must match the BW inventory run ID")

    objects = {item["id"]: item for item in bw_inventory["objects"]}
    wave_object_ids = set(wave_review["inventory_scope"]["object_ids"])
    wave_edges = {
        (edge["source_id"], edge["target_id"], edge["kind"])
        for edge in bw_inventory["dependencies"]
        if edge["source_id"] in wave_object_ids or edge["target_id"] in wave_object_ids
    }
    related_object_ids = wave_object_ids | {
        object_id for edge in wave_edges for object_id in edge[:2]
    }
    inventory_consumers = {
        item["id"] for item in bw_inventory["objects"]
        if item["type"] == "consumer" and item["id"] in related_object_ids
    }
    declared_edges = set()
    declared_consumers = set()
    for index, item in enumerate(cutover["dependency_dispositions"]):
        path = f"$.dependency_dispositions[{index}]"
        object_id = item["inventory_object_id"]
        if object_id is not None:
            source_object = objects.get(object_id)
            if source_object is None:
                _fail(f"{path}.inventory_object_id", "must reference an inventory object")
            if object_id not in related_object_ids:
                _fail(f"{path}.inventory_object_id", "must be in or connected to the declared wave scope")
            if item["category"] in {"bo_consumer", "non_bo_consumer"}:
                if source_object["type"] != "consumer":
                    _fail(f"{path}.inventory_object_id", "consumer categories must reference consumer objects")
                declared_consumers.add(object_id)
        elif item["category"] in {"bo_consumer", "non_bo_consumer"}:
            _fail(f"{path}.inventory_object_id", "consumer categories must reference an inventory consumer")
        edge = item["inventory_edge"]
        if edge is not None:
            edge_key = (edge["source_id"], edge["target_id"], edge["kind"])
            if edge_key not in wave_edges:
                _fail(f"{path}.inventory_edge", "must match a BW inventory dependency in or connected to the wave")
            declared_edges.add(edge_key)

    findings = []
    actions = []

    def record(code: str, path: str, owner: str | None = None) -> None:
        findings.append({"code": code, "severity": "blocker", "path": path})
        if owner is not None:
            actions.append({"owner_reference": owner, "action": code})

    inventory_review = assess_bw0(bw_inventory)
    if inventory_review["gate_status"] == "open":
        record("bw0_inventory_gate_open", "$.inventory")
    if wave_review["status"] == "open":
        record("bw7_wave_evidence_open", "$.bw7_wave_evidence")
    if scope["dependency_coverage"] != "complete":
        record("dependency_coverage_incomplete", "$.inventory_scope.dependency_coverage")
    for index, consumer_id in enumerate(sorted(inventory_consumers - declared_consumers)):
        record("inventory_consumer_not_dispositioned", f"$.dependency_dispositions.consumer[{index}]")
    for index, edge in enumerate(sorted(wave_edges - declared_edges)):
        record("inventory_dependency_not_dispositioned", f"$.dependency_dispositions.edge[{index}]")

    for index, item in enumerate(cutover["dependency_dispositions"]):
        path = f"$.dependency_dispositions[{index}]"
        disposition = item["disposition"]
        owner = item["owner_reference"]
        if disposition in {"unresolved", "not_run"}:
            record(f"dependency_{disposition}", f"{path}.disposition", owner)
        elif item["evidence_reference"] is None:
            record("dependency_evidence_missing", f"{path}.evidence_reference", owner)
        if owner is None:
            record("dependency_owner_missing", f"{path}.owner_reference")
        if disposition == "accepted_residual" and item["approval_reference"] is None:
            record("residual_dependency_approval_missing", f"{path}.approval_reference", owner)

    for field, value in cutover["cutover_plan"].items():
        if value is None:
            record("cutover_plan_reference_missing", f"$.cutover_plan.{field}")

    for section in ("parallel_run", "independent_observation"):
        period = cutover[section]
        if period["completed_days"] < period["minimum_days"]:
            record(f"{section}_duration_incomplete", f"$.{section}.completed_days", period["owner_reference"])
        if period["evidence_reference"] is None:
            record(f"{section}_evidence_missing", f"$.{section}.evidence_reference", period["owner_reference"])
        if period["owner_reference"] is None:
            record(f"{section}_owner_missing", f"$.{section}.owner_reference")

    rollback = cutover["rollback"]
    for field in (
        "trigger_reference", "recovery_objective_reference", "divergence_handling_reference",
        "runbook_reference",
    ):
        if rollback[field] is None:
            record(f"rollback_{field.removesuffix('_reference')}_missing", f"$.rollback.{field}")
    if rollback["exercise_status"] != "pass":
        record(
            f"rollback_exercise_{rollback['exercise_status']}",
            "$.rollback.exercise_status",
            rollback["owner_reference"],
        )
    if rollback["exercise_status"] == "pass" and rollback["exercise_evidence_reference"] is None:
        record("rollback_exercise_evidence_missing", "$.rollback.exercise_evidence_reference", rollback["owner_reference"])
    if rollback["owner_reference"] is None:
        record("rollback_owner_missing", "$.rollback.owner_reference")

    for index, check in enumerate(cutover["checks"]):
        path = f"$.checks[{index}]"
        owner = check["owner_reference"]
        if check["status"] != "pass":
            record(f"{check['kind']}_{check['status']}", f"{path}.status", owner)
        if check["status"] == "pass" and check["evidence_reference"] is None:
            record(f"{check['kind']}_evidence_missing", f"{path}.evidence_reference", owner)
        if owner is None:
            record(f"{check['kind']}_owner_missing", f"{path}.owner_reference")
        if (
            check["kind"] in _APPROVAL_CHECKS
            and check["status"] == "pass"
            and check["approval_reference"] is None
        ):
            record(f"{check['kind']}_approval_reference_missing", f"{path}.approval_reference", owner)

    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "assessment": "bw8_cutover_retirement_declarations",
        "wave_id": cutover["wave_id"],
        "status": "blocked" if findings else "declarations_complete_for_owner_review",
        "gate_closed": False,
        "cutover_authorized": False,
        "retirement_authorized": False,
        "evidence_boundary": "validated_local_inventory_and_declared_bw7_and_cutover_references_only",
        "inventory_gate_status": inventory_review["gate_status"],
        "bw7_wave_status": wave_review["status"],
        "inventory_scope": scope,
        "dependency_scope": "wave_objects_and_direct_inventory_neighbors",
        "dependency_coverage_verification": "not_verified",
        "wave_evidence": wave_manifest,
        "dependency_dispositions": cutover["dependency_dispositions"],
        "cutover_plan": cutover["cutover_plan"],
        "parallel_run": cutover["parallel_run"],
        "independent_observation": cutover["independent_observation"],
        "rollback": cutover["rollback"],
        "checks": cutover["checks"],
        "findings": findings,
        "owner_actions": actions,
        "summary": {
            "dependencies": len(cutover["dependency_dispositions"]),
            "inventory_consumers": len(inventory_consumers),
            "inventory_dependencies": len(wave_edges),
            "bw7_wave_status": wave_review["status"],
            "checks": len(cutover["checks"]),
            "blockers": len(findings),
        },
        "runtime_evidence": {
            "sap_access_or_extraction": "not_run",
            "fabric_execution_or_refresh": "not_run",
            "parallel_run": "not_run",
            "consumer_switching": "not_run",
            "rollback_execution": "not_run",
            "source_shutdown": "not_run",
            "archive_restore_execution": "not_run",
        },
        "limitations": [
            "Evaluates local declarations only; evidence references and approvals are not authenticated or dereferenced.",
            "Checks only inventory dependencies directly incident to the wave; transitive dependencies and coverage completeness are not verified.",
            "Does not execute cutover, switch consumers, run rollback or restore drills, shut down BW, or authorize retirement.",
            "declarations_complete_for_owner_review is not acceptance, cutover approval, or retirement authorization.",
        ],
    }


__all__ = [
    "BWCutoverAssessmentError", "CHECK_KINDS", "CURRENT_SCHEMA_VERSION",
    "DEPENDENCY_CATEGORIES", "DEPENDENCY_DISPOSITIONS", "assess_bw_cutover",
    "load_cutover_manifest", "validate_cutover_manifest",
]
