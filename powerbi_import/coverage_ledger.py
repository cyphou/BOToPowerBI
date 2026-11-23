"""Offline cross-source feature declarations, not a feature registry or verifier.

``build_coverage_ledger(manifest)`` validates a JSON-shaped manifest and returns
a detached, deterministic report. References are opaque labels: this module
never opens them, executes declared commands, or authenticates their contents.
Identifiers are case-sensitive and preserved verbatim. Null means unknown,
except where an explicit ``not_applicable`` or ``none`` declaration says
otherwise. The manifest schema describes fields; cross-entry uniqueness is
enforced by this module.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, NoReturn

from .security_validator import scan_for_credentials

CURRENT_SCHEMA_VERSION = "1.0"
STAGES = ("extraction", "conversion", "target_generation", "reporting", "remote_operations")
DECLARED_STATUSES = ("implemented", "partial", "unsupported", "planned", "unverified")
EVIDENCE_STATUSES = ("pass", "fail", "not_run", "unknown")
MAX_ENTRIES = 10000
_REFERENCE = re.compile(r"[^\x00-\x20\x7f]{1,256}\Z")
_ENTRY_FIELDS = {
    "source", "feature_id", "stage", "declared_status", "owner",
    "scope", "target", "dependency", "manual_action", "disposition",
    "local_evidence", "runtime_evidence",
}


class CoverageLedgerError(ValueError):
    """A declaration does not satisfy the coverage ledger contract."""


def _ledger_fail(path: str, reason: str) -> NoReturn:
    raise CoverageLedgerError(f"Coverage ledger contract error at {path}: {reason}")


def _ledger_object(value: Any, path: str, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        _ledger_fail(path, "must contain exactly the supported fields")
    return value


def _ledger_text(value: Any, path: str, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if (
        not isinstance(value, str) or not value.strip() or len(value) > 512
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        _ledger_fail(path, "must be non-blank text of at most 512 characters without controls")
    if scan_for_credentials(value):
        _ledger_fail(path, "credential-like content is not allowed")


def _ledger_reference(value: Any, path: str, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        _ledger_fail(path, "must be an opaque reference of 1 to 256 characters without ASCII whitespace or controls")
    if scan_for_credentials(value):
        _ledger_fail(path, "credential-like content is not allowed")


def _ledger_choice(value: Any, path: str, choices: tuple[str, ...]) -> None:
    if not isinstance(value, str) or value not in choices:
        _ledger_fail(path, "has an unsupported value")


def _ledger_evidence(value: Any, path: str) -> None:
    evidence = _ledger_object(value, path, {"status", "reference", "check", "command"})
    _ledger_choice(evidence["status"], f"{path}.status", EVIDENCE_STATUSES)
    _ledger_reference(evidence["reference"], f"{path}.reference", nullable=True)
    _ledger_text(evidence["check"], f"{path}.check", nullable=True)
    _ledger_text(evidence["command"], f"{path}.command", nullable=True)
    if evidence["status"] in ("pass", "fail") and (
        evidence["reference"] is None or evidence["check"] is None
    ):
        _ledger_fail(path, "declared pass or fail requires a reference and check description")


def validate_coverage_ledger(manifest: Any) -> dict:
    """Validate declarations only; raise CoverageLedgerError for invalid input.

    Duplicate keys in a serialized JSON document must be rejected by the caller
    while parsing; they cannot be detected after conversion to a Python dict.
    """
    root = _ledger_object(manifest, "$", {"schema_version", "wave_id", "entries"})
    if root["schema_version"] != CURRENT_SCHEMA_VERSION:
        _ledger_fail("$.schema_version", "expected version 1.0")
    _ledger_text(root["wave_id"], "$.wave_id")
    entries = root["entries"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
        _ledger_fail("$.entries", f"must contain 1 to {MAX_ENTRIES} entries")
    seen = set()
    for index, raw in enumerate(entries):
        path = f"$.entries[{index}]"
        item = _ledger_object(raw, path, _ENTRY_FIELDS)
        source = _ledger_object(item["source"], f"{path}.source", {
            "artifact_kind", "version", "document_id", "provenance", "evidence_reference",
        })
        _ledger_text(source["artifact_kind"], f"{path}.source.artifact_kind")
        for field in ("version", "document_id", "provenance"):
            _ledger_text(source[field], f"{path}.source.{field}", nullable=True)
        _ledger_reference(source["evidence_reference"], f"{path}.source.evidence_reference", nullable=True)
        _ledger_text(item["feature_id"], f"{path}.feature_id")
        _ledger_choice(item["stage"], f"{path}.stage", STAGES)
        _ledger_choice(item["declared_status"], f"{path}.declared_status", DECLARED_STATUSES)
        _ledger_text(item["owner"], f"{path}.owner")
        _ledger_text(item["scope"], f"{path}.scope", nullable=True)
        key = (source["artifact_kind"], source["version"], source["document_id"],
               item["feature_id"], item["stage"])
        if key in seen:
            _ledger_fail(path, "duplicate source artifact kind/version/document ID and feature ID/stage")
        seen.add(key)

        target = _ledger_object(item["target"], f"{path}.target", {
            "applicability", "choice", "object_binding",
        })
        _ledger_choice(target["applicability"], f"{path}.target.applicability",
                       ("applicable", "not_applicable", "unknown"))
        for field in ("choice", "object_binding"):
            _ledger_text(target[field], f"{path}.target.{field}", nullable=True)
        if target["applicability"] != "applicable" and (
            target["choice"] is not None or target["object_binding"] is not None
        ):
            _ledger_fail(f"{path}.target", "unknown or not-applicable target must not specify a choice or binding")

        dependency = _ledger_object(item["dependency"], f"{path}.dependency", {"status", "description"})
        _ledger_choice(dependency["status"], f"{path}.dependency.status", ("identified", "none", "unknown"))
        _ledger_text(dependency["description"], f"{path}.dependency.description", nullable=True)
        if (dependency["status"] == "identified") != (dependency["description"] is not None):
            _ledger_fail(f"{path}.dependency", "description is required only for an identified dependency")

        _ledger_text(item["manual_action"], f"{path}.manual_action", nullable=True)
        _ledger_choice(item["disposition"], f"{path}.disposition",
                       ("unresolved", "resolved", "accepted", "not_applicable", "unknown"))
        if item["disposition"] == "not_applicable" and item["manual_action"] is not None:
            _ledger_fail(path, "not-applicable manual action must be null")
        if item["disposition"] in ("unresolved", "resolved", "accepted") and item["manual_action"] is None:
            _ledger_fail(path, "declared manual-action disposition requires an action")
        for field in ("local_evidence", "runtime_evidence"):
            _ledger_evidence(item[field], f"{path}.{field}")

        if item["declared_status"] == "implemented":
            if any(source[field] is None for field in ("version", "document_id", "provenance", "evidence_reference")):
                _ledger_fail(path, "implemented requires declared source identity, provenance and evidence reference")
            if item["scope"] is None or item["local_evidence"]["status"] != "pass":
                _ledger_fail(path, "implemented requires a stated scope and declared passing local check")
            if item["stage"] in ("target_generation", "remote_operations") and target["applicability"] != "applicable":
                _ledger_fail(f"{path}.target.applicability", "implemented target generation and remote operations require an applicable target")
            if target["applicability"] == "unknown" or (
                target["applicability"] == "applicable"
                and (target["choice"] is None or target["object_binding"] is None)
            ):
                _ledger_fail(path, "implemented requires an explicit target and binding if applicable")
            if item["runtime_evidence"]["status"] == "fail":
                _ledger_fail(path, "implemented contradicts a declared runtime failure")
            if item["stage"] == "remote_operations" and item["runtime_evidence"]["status"] != "pass":
                _ledger_fail(path, "implemented remote operations require a declared passing runtime check")
    return root


def build_coverage_ledger(manifest: Any) -> dict:
    """Return a declaration-only report without mutating input or accessing files."""
    root = validate_coverage_ledger(manifest)
    entries = deepcopy(root["entries"])
    # None and strings cannot be directly compared. Keep unknowns distinct from
    # all text, without normalizing source identifiers.
    def sort_key(item: dict) -> tuple:
        source = item["source"]
        return tuple((value is not None, value or "") for value in (
            source["artifact_kind"], source["version"], source["document_id"],
            item["feature_id"], item["stage"],
        ))

    entries.sort(key=sort_key)
    status_counts = {status: 0 for status in DECLARED_STATUSES}
    stage_counts = {stage: 0 for stage in STAGES}
    findings = []
    for item in entries:
        status_counts[item["declared_status"]] += 1
        stage_counts[item["stage"]] += 1
        reasons = []
        if item["declared_status"] != "implemented":
            reasons.append("declared_" + item["declared_status"])
        source = item["source"]
        if any(source[field] is None for field in ("version", "document_id", "provenance", "evidence_reference")):
            reasons.append("source_declaration_incomplete")
        target = item["target"]
        if target["applicability"] == "unknown" or (
            target["applicability"] == "applicable"
            and (target["choice"] is None or target["object_binding"] is None)
        ):
            reasons.append("target_declaration_incomplete")
        if item["dependency"]["status"] == "unknown":
            reasons.append("dependency_unknown")
        if item["disposition"] in ("unknown", "unresolved"):
            reasons.append("manual_disposition_" + item["disposition"])
        for level in ("local_evidence", "runtime_evidence"):
            if item[level]["status"] != "pass":
                reasons.append(level + "_declared_" + item[level]["status"])
        if reasons:
            findings.append({
                "source": deepcopy(source),
                "feature_id": item["feature_id"],
                "stage": item["stage"],
                "owner": item["owner"],
                "reasons": reasons,
                "declared_manual_action": item["manual_action"],
                "action": "Review declarations and obtain independent evidence for the stated scope.",
            })
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "wave_id": root["wave_id"],
        "report_kind": "offline_feature_coverage_declarations",
        "declared_entries": entries,
        "declared_status_counts": status_counts,
        "declared_stage_counts": stage_counts,
        "findings": findings,
        "checks_performed": [
            {"check": "manifest_contract_validation", "status": "pass", "command": None},
            {"check": "duplicate_source_feature_stage_check", "status": "pass", "command": None},
        ],
        "verification": {
            "evidence_authenticity": "not_verified",
            "evidence_freshness_and_correctness": "not_verified",
            "source_identity_and_coverage": "not_verified",
            "feature_coverage": "not_verified",
            "semantic_equivalence": "not_verified",
            "approvals": "not_verified",
            "local_evidence_execution": "not_run",
            "desktop_rendering": "not_run",
            "refresh": "not_run",
            "remote_execution": "not_run",
        },
        "limitations": [
            "All entries, statuses, checks, commands and references are declarations, not observations by this API.",
            "References are not opened or authenticated; declared checks and commands are not executed.",
            "Counts describe supplied rows only; they do not establish completeness, coverage, parity or readiness.",
            "Accepted or resolved dispositions are declarations and do not authenticate approvals or authorize action.",
            "Metadata may be sensitive; credential detection is not a guarantee of sanitization.",
        ],
    }


__all__ = [
    "CoverageLedgerError", "CURRENT_SCHEMA_VERSION", "STAGES", "DECLARED_STATUSES",
    "EVIDENCE_STATUSES", "MAX_ENTRIES", "validate_coverage_ledger", "build_coverage_ledger",
]
