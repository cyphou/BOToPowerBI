"""Compare declared BW transformation golden vectors with target outputs offline."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, NoReturn

from .security_validator import scan_for_credentials


class BWTransformValidationError(ValueError):
    """Raised when a local BW transformation-vector manifest is invalid."""


_ROOT_FIELDS = {"schema_version", "suite_id", "transformation", "rules", "cases"}
_TRANSFORMATION_FIELDS = {"object_id", "definition_reference", "definition_sha256"}
_CASE_FIELDS = {"case_id", "input", "expected_output", "target_output"}
_DECIMAL_TEXT = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


def _fail(path: str, reason: str) -> NoReturn:
    raise BWTransformValidationError(
        f"BW transformation-vector contract error at {path}: {reason}"
    )


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


def _json_value(value: Any, path: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if type(value) is int or isinstance(value, Decimal):
        if isinstance(value, Decimal) and not value.is_finite():
            _fail(path, "must be a finite JSON number")
        return
    if isinstance(value, float):
        _fail(path, "binary floating-point values are not accepted; use a decimal string")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(path, "object keys must be strings")
            _json_value(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _json_value(item, f"{path}[{index}]")
        return
    _fail(path, "must contain only JSON-compatible values")


def _decimal(value: Any, path: str) -> Decimal:
    if type(value) is int:
        return Decimal(value)
    if isinstance(value, Decimal) and value.is_finite():
        return value
    if isinstance(value, str) and _DECIMAL_TEXT.fullmatch(value):
        try:
            return Decimal(value)
        except InvalidOperation:
            _fail(path, "must be a finite decimal value")
    _fail(path, "must be an integer or a decimal string")


def _decimal_kind(value: Any, path: str) -> str:
    if type(value) is int:
        return "integer"
    if isinstance(value, Decimal) and value.is_finite():
        return "decimal"
    if isinstance(value, str) and _DECIMAL_TEXT.fullmatch(value):
        return "decimal_string"
    _fail(path, "must be an integer or a decimal string")


def _rules(value: Any) -> dict:
    if not isinstance(value, dict) or not value:
        _fail("$.rules", "must define at least one output field")
    rules = {}
    for field, raw_rule in value.items():
        _text(field, "$.rules field")
        if not isinstance(raw_rule, dict) or "mode" not in raw_rule:
            _fail(f"$.rules.{field}", "must be an object with a supported mode")
        if raw_rule["mode"] == "exact" and set(raw_rule) == {"mode"}:
            rules[field] = {"mode": "exact"}
        elif raw_rule["mode"] == "tolerance" and set(raw_rule) == {
            "mode", "absolute_tolerance", "relative_tolerance",
        }:
            absolute = _decimal(
                raw_rule["absolute_tolerance"],
                f"$.rules.{field}.absolute_tolerance",
            )
            relative = _decimal(
                raw_rule["relative_tolerance"],
                f"$.rules.{field}.relative_tolerance",
            )
            if absolute < 0 or relative < 0:
                _fail(f"$.rules.{field}", "tolerances must be non-negative")
            rules[field] = {
                "mode": "tolerance",
                "absolute_tolerance": absolute,
                "relative_tolerance": relative,
            }
        else:
            _fail(f"$.rules.{field}", "has an unsupported mode or field set")
    return rules


def _case(value: Any, path: str, rule_fields: set[str]) -> dict:
    case = _object(value, path, _CASE_FIELDS)
    case_id = _text(case["case_id"], f"{path}.case_id")
    inputs = case["input"]
    expected = case["expected_output"]
    actual = case["target_output"]
    if not isinstance(inputs, dict) or not inputs:
        _fail(f"{path}.input", "must be a non-empty object")
    if not isinstance(expected, dict) or set(expected) != rule_fields:
        _fail(f"{path}.expected_output", "must contain exactly the ruled output fields")
    if not isinstance(actual, dict):
        _fail(f"{path}.target_output", "must be an object")
    _json_value(inputs, f"{path}.input")
    _json_value(expected, f"{path}.expected_output")
    _json_value(actual, f"{path}.target_output")
    return {
        "case_id": case_id,
        "expected": expected,
        "actual": actual,
    }


def compare_transform_vectors(manifest: Any) -> dict:
    """Compare supplied expected and target vectors; do not execute either routine."""
    root = _object(manifest, "$", _ROOT_FIELDS)
    if root["schema_version"] != "1.0":
        _fail("$.schema_version", "expected version 1.0")
    suite_id = _text(root["suite_id"], "$.suite_id")
    try:
        encoded = json.dumps(manifest, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        _fail("$", "must contain only JSON-compatible values")
    if scan_for_credentials(encoded):
        _fail("$", "credential-like content is not allowed")

    transformation = _object(
        root["transformation"], "$.transformation", _TRANSFORMATION_FIELDS
    )
    object_id = _text(transformation["object_id"], "$.transformation.object_id")
    definition_reference = _text(
        transformation["definition_reference"],
        "$.transformation.definition_reference",
    )
    definition_hash = _text(
        transformation["definition_sha256"],
        "$.transformation.definition_sha256",
    )
    if not re.fullmatch(r"[0-9a-f]{64}", definition_hash, re.IGNORECASE):
        _fail(
            "$.transformation.definition_sha256",
            "must be a 64-character SHA-256 digest",
        )

    rules = _rules(root["rules"])
    if not isinstance(root["cases"], list) or not root["cases"]:
        _fail("$.cases", "must contain at least one test vector")
    case_ids = set()
    cases = []
    for index, raw_case in enumerate(root["cases"]):
        case = _case(raw_case, f"$.cases[{index}]", set(rules))
        if case["case_id"] in case_ids:
            _fail(f"$.cases[{index}].case_id", "must be unique")
        case_ids.add(case["case_id"])
        cases.append(case)

    checks = []
    failed_cases = set()
    for case in cases:
        expected = case["expected"]
        actual = case["actual"]
        for field in sorted(rules):
            rule = rules[field]
            if field not in actual:
                status = "fail"
                reason = "missing_target_field"
                difference = None
                allowed_difference = None
            elif rule["mode"] == "exact":
                expected_value = expected[field]
                actual_value = actual[field]
                same_type = type(expected_value) is type(actual_value)
                status = "pass" if same_type and expected_value == actual_value else "fail"
                reason = None if status == "pass" else (
                    "type_mismatch" if not same_type else "value_mismatch"
                )
                difference = None
                allowed_difference = None
            else:
                expected_value = expected[field]
                actual_value = actual[field]
                expected_kind = _decimal_kind(
                    expected_value,
                    f"$.cases.{case['case_id']}.expected_output.{field}",
                )
                actual_kind = _decimal_kind(
                    actual_value,
                    f"$.cases.{case['case_id']}.target_output.{field}",
                )
                if expected_kind != actual_kind:
                    status = "fail"
                    reason = "type_mismatch"
                    difference = None
                    allowed_difference = None
                else:
                    expected_number = _decimal(
                        expected_value,
                        f"$.cases.{case['case_id']}.expected_output.{field}",
                    )
                    actual_number = _decimal(
                        actual_value,
                        f"$.cases.{case['case_id']}.target_output.{field}",
                    )
                    difference = abs(actual_number - expected_number)
                    allowed_difference = max(
                        rule["absolute_tolerance"],
                        abs(expected_number) * rule["relative_tolerance"],
                    )
                    status = "pass" if difference <= allowed_difference else "fail"
                    reason = None if status == "pass" else "tolerance_exceeded"
            if status == "fail":
                failed_cases.add(case["case_id"])
            checks.append({
                "case_id": case["case_id"],
                "field": field,
                "mode": rule["mode"],
                "status": status,
                "failure_reason": reason,
                "absolute_difference": (
                    str(difference) if difference is not None else None
                ),
                "allowed_difference": (
                    str(allowed_difference)
                    if allowed_difference is not None
                    else None
                ),
            })
        for field in sorted(set(actual) - set(rules)):
            failed_cases.add(case["case_id"])
            checks.append({
                "case_id": case["case_id"],
                "field": field,
                "mode": "unexpected",
                "status": "fail",
                "failure_reason": "unexpected_target_field",
                "absolute_difference": None,
                "allowed_difference": None,
            })

    failed_checks = sum(check["status"] == "fail" for check in checks)
    return {
        "schema_version": "1.0",
        "suite_id": suite_id,
        "transformation": {
            "object_id": object_id,
            "definition_reference": definition_reference,
            "definition_sha256": definition_hash.lower(),
        },
        "comparison_status": "fail" if failed_checks else "pass",
        "evidence_boundary": "declared_local_test_vectors_only",
        "summary": {
            "cases_compared": len(cases),
            "field_checks": len(checks),
            "failed_checks": failed_checks,
            "cases_failed": len(failed_cases),
        },
        "checks": checks,
        "runtime_evidence": {
            "source_golden_case_execution": "not_run",
            "target_transformation_execution": "not_run",
            "business_approval": "not_run",
        },
    }


def load_transform_vectors(path: str | Path) -> dict:
    """Load local JSON vectors while rejecting duplicate keys and non-JSON numbers."""
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
        raise BWTransformValidationError(
            "Unable to load local BW transformation-vector JSON."
        ) from None
    return document


__all__ = [
    "BWTransformValidationError",
    "compare_transform_vectors",
    "load_transform_vectors",
]
