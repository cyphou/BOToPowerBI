"""Compare explicitly supplied SAP BW and Fabric snapshot controls offline."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .security_validator import scan_for_credentials


class BWReconciliationError(ValueError):
    """Raised when an offline BW reconciliation manifest is invalid."""


_ROOT_FIELDS = {
    "schema_version", "comparison_id", "scope", "source", "target", "rules",
}
_SCOPE_FIELDS = {"snapshot_id", "snapshot_cutoff_utc", "grain", "filter_id"}
_SIDE_FIELDS = {"system_id", "object_id", "run_id", "evidence_ref", "scope", "metrics"}
_METRIC_FIELDS = {"value", "unit"}
_METRIC_NAME = re.compile(r"[^\x00-\x20\x7f]{1,128}\Z")
_DECIMAL_TEXT = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_UTC_SUFFIX = re.compile(r"(?:Z|\+00:00)\Z")


def _fail(path: str, reason: str) -> None:
    raise BWReconciliationError(f"BW reconciliation contract error at {path}: {reason}")


def _object(value: Any, path: str, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(path, "must contain exactly the supported fields")
    return value


def _text(value: Any, path: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        _fail(path, "must be a non-empty string without control characters")
    return value


def _decimal(value: Any, path: str) -> Decimal:
    if type(value) is int:
        number = Decimal(value)
    elif isinstance(value, str) and _DECIMAL_TEXT.fullmatch(value):
        try:
            number = Decimal(value)
        except InvalidOperation:
            _fail(path, "must be a finite decimal value")
    elif isinstance(value, Decimal):
        try:
            number = Decimal(value)
        except (InvalidOperation, ValueError):
            _fail(path, "must be a finite decimal value")
    else:
        _fail(path, "must be an integer or a decimal string")
    if not number.is_finite():
        _fail(path, "must be a finite decimal value")
    return number


def _utc_datetime(value: Any, path: str) -> datetime:
    text = _text(value, path)
    if "T" not in text or not _UTC_SUFFIX.search(text):
        _fail(path, "must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail(path, "must be an ISO-8601 UTC timestamp")
    if parsed.utcoffset() != timedelta(0):
        _fail(path, "must be an ISO-8601 UTC timestamp")
    return parsed


def _scope(value: Any, path: str) -> dict:
    scope = _object(value, path, _SCOPE_FIELDS)
    for field in ("snapshot_id", "grain", "filter_id"):
        _text(scope[field], f"{path}.{field}")
    cutoff = _utc_datetime(scope["snapshot_cutoff_utc"], f"{path}.snapshot_cutoff_utc")
    return {
        "snapshot_id": scope["snapshot_id"],
        "snapshot_cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
        "grain": scope["grain"],
        "filter_id": scope["filter_id"],
    }


def _metrics(value: Any, path: str) -> dict:
    if not isinstance(value, dict) or not value:
        _fail(path, "must be a non-empty object of named controls")
    result = {}
    for name, metric_value in value.items():
        if not isinstance(name, str) or not _METRIC_NAME.fullmatch(name):
            _fail(path, "control names must be non-empty and contain no control characters")
        metric = _object(metric_value, f"{path}.{name}", _METRIC_FIELDS)
        number = _decimal(metric["value"], f"{path}.{name}.value")
        unit = _text(metric["unit"], f"{path}.{name}.unit")
        if name in {"row_count", "distinct_key_count"}:
            if type(metric["value"]) is not int or metric["value"] < 0:
                _fail(f"{path}.{name}.value", "must be a non-negative integer")
        result[name] = {"value": number, "unit": unit}
    for name, unit in (("row_count", "rows"), ("distinct_key_count", "keys")):
        if name not in result or result[name]["unit"] != unit:
            _fail(path, f"must include {name} with unit {unit!r}")
    return result


def _side(value: Any, path: str, expected_scope: dict) -> dict:
    side = _object(value, path, _SIDE_FIELDS)
    for field in ("system_id", "object_id", "run_id", "evidence_ref"):
        _text(side[field], f"{path}.{field}")
    side_scope = _scope(side["scope"], f"{path}.scope")
    if side_scope != expected_scope:
        _fail(f"{path}.scope", "does not match the declared comparison snapshot and scope")
    return {
        "system_id": side["system_id"],
        "object_id": side["object_id"],
        "run_id": side["run_id"],
        "evidence_ref": side["evidence_ref"],
        "metrics": _metrics(side["metrics"], f"{path}.metrics"),
    }


def _rules(value: Any, metrics: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != metrics:
        _fail("$.rules", "must define exactly one rule for every compared control")
    result = {}
    for name, rule_value in value.items():
        if not isinstance(rule_value, dict) or "mode" not in rule_value:
            _fail(f"$.rules.{name}", "must be an object with a supported mode")
        mode = rule_value["mode"]
        if mode == "exact" and set(rule_value) == {"mode"}:
            result[name] = {"mode": "exact"}
        elif mode == "tolerance" and set(rule_value) == {
            "mode", "absolute_tolerance", "relative_tolerance",
        }:
            absolute = _decimal(
                rule_value["absolute_tolerance"], f"$.rules.{name}.absolute_tolerance"
            )
            relative = _decimal(
                rule_value["relative_tolerance"], f"$.rules.{name}.relative_tolerance"
            )
            if absolute < 0 or relative < 0:
                _fail(f"$.rules.{name}", "tolerances must be non-negative")
            result[name] = {
                "mode": "tolerance",
                "absolute_tolerance": absolute,
                "relative_tolerance": relative,
            }
        else:
            _fail(f"$.rules.{name}", "has an unsupported mode or field set")
    for required in ("row_count", "distinct_key_count"):
        if result[required]["mode"] != "exact":
            _fail(f"$.rules.{required}", "must use exact comparison")
    return result


def compare_controls(manifest: Any) -> dict:
    """Compare local control declarations; this does not verify how they were measured."""
    root = _object(manifest, "$", _ROOT_FIELDS)
    if root["schema_version"] != "1.0":
        _fail("$.schema_version", "expected version 1.0")
    _text(root["comparison_id"], "$.comparison_id")
    try:
        encoded = json.dumps(manifest, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        _fail("$", "must contain only JSON-compatible values")
    if scan_for_credentials(encoded):
        _fail("$", "credential-like content is not allowed")

    scope = _scope(root["scope"], "$.scope")
    source = _side(root["source"], "$.source", scope)
    target = _side(root["target"], "$.target", scope)
    source_names = set(source["metrics"])
    if source_names != set(target["metrics"]):
        _fail("$.target.metrics", "must contain the same controls as the source")
    rules = _rules(root["rules"], source_names)

    checks = []
    for name in sorted(source_names):
        source_metric = source["metrics"][name]
        target_metric = target["metrics"][name]
        if source_metric["unit"] != target_metric["unit"]:
            _fail(f"$.target.metrics.{name}.unit", "must match the source unit")
        difference = target_metric["value"] - source_metric["value"]
        rule = rules[name]
        tolerance = Decimal(0)
        if rule["mode"] == "tolerance":
            tolerance = max(
                rule["absolute_tolerance"],
                abs(source_metric["value"]) * rule["relative_tolerance"],
            )
        checks.append({
            "metric": name,
            "unit": source_metric["unit"],
            "source_value": str(source_metric["value"]),
            "target_value": str(target_metric["value"]),
            "difference": str(difference),
            "allowed_difference": str(tolerance),
            "status": "pass" if abs(difference) <= tolerance else "fail",
        })

    failed = sum(check["status"] == "fail" for check in checks)
    return {
        "schema_version": "1.0",
        "comparison_id": root["comparison_id"],
        "comparison_status": "fail" if failed else "pass",
        "evidence_boundary": "declared_local_controls_only",
        "scope": scope,
        "source": {key: source[key] for key in ("system_id", "object_id", "run_id", "evidence_ref")},
        "target": {key: target[key] for key in ("system_id", "object_id", "run_id", "evidence_ref")},
        "summary": {"controls_compared": len(checks), "controls_failed": failed},
        "checks": checks,
        "runtime_evidence": {
            "sap_extraction": "not_run",
            "fabric_execution": "not_run",
            "business_approval": "not_run",
        },
    }


def load_comparison(path: str | Path) -> dict:
    """Load a local JSON manifest while rejecting duplicate keys and non-JSON numbers."""
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
                handle,
                object_pairs_hook=unique_object,
                parse_float=Decimal,
                parse_constant=reject_constant,
            )
    except (OSError, UnicodeError, ValueError):
        raise BWReconciliationError("Unable to load local BW reconciliation JSON.") from None
    return document


__all__ = [
    "BWReconciliationError",
    "compare_controls",
    "load_comparison",
]
