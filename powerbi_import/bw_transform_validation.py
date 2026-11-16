"""Compare BW vectors and locally evaluate supported normalized plans offline."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, NoReturn

from .bw_reconciliation import _exact_decimal_comparison
from .security_validator import scan_for_credentials


class BWTransformValidationError(ValueError):
    """Raised when a local BW transformation-vector manifest is invalid."""


_ROOT_FIELDS = {"schema_version", "suite_id", "transformation", "rules", "cases"}
_TRANSFORMATION_FIELDS = {"object_id", "definition_reference", "definition_sha256"}
_CASE_FIELDS = {"case_id", "input", "expected_output", "target_output"}
_DECIMAL_TEXT = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_SOURCE_PREFLIGHT_FIELDS = {
    "definition_sha256_check",
    "plan_vs_declared_ledger",
    "source_definition_authenticity",
    "ledger_source_correspondence",
    "source_owner_approval",
}
_SOURCE_PREFLIGHT_OPTIONAL_FIELDS = {"ledger_canonical_sha256", "ledger_rule_count"}
_DECIMAL_SPARK_TYPE = re.compile(r"decimal\(([1-9][0-9]?),([0-9]+)\)\Z")
_PLAN_EVALUATION_TYPES = {
    "string", "boolean", "tinyint", "smallint", "int", "bigint",
}
_KNOWN_SPARK_TYPES = _PLAN_EVALUATION_TYPES | {
    "float", "double", "date", "timestamp", "binary",
}
_INTEGER_BOUNDS = {
    "tinyint": (-(2**7), 2**7),
    "smallint": (-(2**15), 2**15),
    "int": (-(2**31), 2**31),
    "bigint": (-(2**63), 2**63),
}


class _PlanVectorValueError(ValueError):
    pass


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


def _same_json_types(expected: Any, actual: Any) -> bool:
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, dict):
        return all(
            _same_json_types(expected[key], actual[key])
            for key in expected.keys() & actual.keys()
        )
    if isinstance(expected, list):
        return all(_same_json_types(left, right) for left, right in zip(expected, actual))
    return True


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
        "input_fields": set(inputs),
        "expected": expected,
        "actual": actual,
    }


def _validate_conversion_plan_linkage(
    plan: Any,
    *,
    object_id: str,
    definition_reference: str,
    definition_hash: str,
    cases: list[dict],
    rule_fields: set[str],
) -> None:
    if not isinstance(plan, dict):
        _fail("$.conversion_plan", "must be an object")

    plan_object_id = _text(
        plan.get("transformation_object_id"),
        "$.conversion_plan.transformation_object_id",
    )
    plan_reference = _text(
        plan.get("definition_reference"),
        "$.conversion_plan.definition_reference",
    )
    plan_hash = _text(
        plan.get("definition_sha256"),
        "$.conversion_plan.definition_sha256",
    )
    if not re.fullmatch(r"[0-9a-f]{64}", plan_hash, re.IGNORECASE):
        _fail(
            "$.conversion_plan.definition_sha256",
            "must be a 64-character SHA-256 digest",
        )
    if object_id != plan_object_id:
        _fail("$.conversion_plan.transformation_object_id", "does not match manifest")
    if definition_reference != plan_reference:
        _fail("$.conversion_plan.definition_reference", "does not match manifest")
    if definition_hash.lower() != plan_hash.lower():
        _fail("$.conversion_plan.definition_sha256", "does not match manifest")

    input_columns = plan.get("input_columns")
    if not isinstance(input_columns, list) or not input_columns:
        _fail("$.conversion_plan.input_columns", "must be a non-empty array")
    input_names = set()
    folded_input_names = set()
    for index, column in enumerate(input_columns):
        if not isinstance(column, dict):
            _fail(f"$.conversion_plan.input_columns[{index}]", "must be an object")
        name = _text(
            column.get("name"),
            f"$.conversion_plan.input_columns[{index}].name",
        )
        folded_name = name.casefold()
        if folded_name in folded_input_names:
            _fail(
                f"$.conversion_plan.input_columns[{index}].name",
                "must be unique",
            )
        input_names.add(name)
        folded_input_names.add(folded_name)

    plan_rules = plan.get("rules")
    if not isinstance(plan_rules, list) or not plan_rules:
        _fail("$.conversion_plan.rules", "must be a non-empty array")
    targets = set()
    folded_targets = set()
    for index, rule in enumerate(plan_rules):
        if not isinstance(rule, dict):
            _fail(f"$.conversion_plan.rules[{index}]", "must be an object")
        target = _text(
            rule.get("target"),
            f"$.conversion_plan.rules[{index}].target",
        )
        folded_target = target.casefold()
        if folded_target in folded_targets:
            _fail(
                f"$.conversion_plan.rules[{index}].target",
                "must be unique",
            )
        targets.add(target)
        folded_targets.add(folded_target)

    if rule_fields != targets:
        _fail("$.rules", "keys must exactly match conversion-plan rule targets")
    for index, case in enumerate(cases):
        if case["input_fields"] != input_names:
            _fail(
                f"$.cases[{index}].input",
                "keys must exactly match conversion-plan input column names",
            )


def _decimal_spark_type(value: Any, path: str) -> tuple[int, int]:
    match = _DECIMAL_SPARK_TYPE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        _fail(path, "must be a canonical decimal Spark type")
    precision, scale = map(int, match.groups())
    if precision > 38 or scale > precision or value != f"decimal({precision},{scale})":
        _fail(path, "must be a canonical decimal Spark type")
    return precision, scale


def _plan_evaluation_type_supported(value: Any, path: str) -> bool:
    if not isinstance(value, str):
        _fail(path, "must be a Spark type string")
    if value in _PLAN_EVALUATION_TYPES:
        return True
    if value in _KNOWN_SPARK_TYPES:
        return False
    if _DECIMAL_SPARK_TYPE.fullmatch(value):
        _decimal_spark_type(value, path)
        return True
    if value.startswith("decimal"):
        _fail(path, "must be a canonical decimal Spark type")
    return False


def _normalize_plan_value(value: Any, spark_type: str) -> Any:
    if value is None:
        return None
    if spark_type == "string":
        if isinstance(value, str):
            return value
        raise _PlanVectorValueError
    if spark_type == "boolean":
        if type(value) is bool:
            return value
        raise _PlanVectorValueError
    if spark_type in _INTEGER_BOUNDS:
        if type(value) is int and _INTEGER_BOUNDS[spark_type][0] <= value < _INTEGER_BOUNDS[spark_type][1]:
            return value
        raise _PlanVectorValueError

    precision, scale = _decimal_spark_type(spark_type, "$.conversion_plan.spark_type")
    if not isinstance(value, str) or not _DECIMAL_TEXT.fullmatch(value):
        raise _PlanVectorValueError
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise _PlanVectorValueError from None
    if not number.is_finite():
        raise _PlanVectorValueError
    decimal_tuple = number.as_tuple()
    exponent = decimal_tuple.exponent
    if type(exponent) is not int:
        raise _PlanVectorValueError
    fractional_digits = max(-exponent, 0)
    digits = list(decimal_tuple.digits)
    while fractional_digits > scale and (not digits or digits[-1] == 0):
        if digits:
            digits.pop()
        fractional_digits -= 1
    integer_digits = max(len(digits) - fractional_digits, 0)
    if number.is_zero():
        integer_digits = 0
    if fractional_digits > scale or integer_digits > precision - scale:
        raise _PlanVectorValueError
    if number.is_zero():
        return "0" if scale == 0 else "0." + "0" * scale
    return format(number, f".{scale}f")


def _not_run_plan_evaluation(reason: str) -> dict:
    return {
        "status": "not_run",
        "reason": reason,
        "evaluation_boundary": "local_normalized_rules_and_declared_vectors",
        "input_validation_scope": "not_run",
        "summary": {
            "cases_evaluated": 0,
            "field_checks": 0,
            "failed_checks": 0,
        },
        "checks": [],
    }


def _evaluate_normalized_plan(plan: dict, cases: list[dict]) -> dict:
    input_types = {
        column["name"]: column["spark_type"]
        for column in plan["input_columns"]
    }
    evaluation_supported = True
    for index, column in enumerate(plan["input_columns"]):
        evaluation_supported &= _plan_evaluation_type_supported(
            column["spark_type"],
            f"$.conversion_plan.input_columns[{index}].spark_type",
        )

    plan_rules = plan["rules"]
    for index, rule in enumerate(plan_rules):
        if rule.get("kind") not in {
            "transfer", "constant", "decimal_add", "decimal_subtract",
        }:
            _fail(
                f"$.conversion_plan.rules[{index}].kind",
                "is not a supported normalized rule",
            )
        evaluation_supported &= _plan_evaluation_type_supported(
            rule.get("spark_type"),
            f"$.conversion_plan.rules[{index}].spark_type",
        )

    if not evaluation_supported:
        return _not_run_plan_evaluation("unsupported_spark_type")

    checks = []
    for case in cases:
        for index, rule in enumerate(plan_rules):
            kind = rule.get("kind")
            target = _text(rule.get("target"), f"$.conversion_plan.rules[{index}].target")
            result_type = _text(
                rule.get("spark_type"),
                f"$.conversion_plan.rules[{index}].spark_type",
            )
            try:
                if kind == "transfer":
                    source = _text(
                        rule.get("source"),
                        f"$.conversion_plan.rules[{index}].source",
                    )
                    source_type = input_types.get(source)
                    if source_type is None or source_type != result_type:
                        _fail(
                            f"$.conversion_plan.rules[{index}]",
                            "transfer source must exist and exactly match its result type",
                        )
                    computed = _normalize_plan_value(
                        case["inputs"][source],
                        source_type,
                    )
                elif kind == "constant":
                    computed = _normalize_plan_value(rule.get("value"), result_type)
                elif kind in {"decimal_add", "decimal_subtract"}:
                    left_name = _text(
                        rule.get("left"),
                        f"$.conversion_plan.rules[{index}].left",
                    )
                    right_name = _text(
                        rule.get("right"),
                        f"$.conversion_plan.rules[{index}].right",
                    )
                    left_type = input_types.get(left_name)
                    right_type = input_types.get(right_name)
                    if (
                        left_type is None
                        or right_type is None
                        or not _DECIMAL_SPARK_TYPE.fullmatch(left_type)
                        or not _DECIMAL_SPARK_TYPE.fullmatch(right_type)
                        or rule.get("null_policy") != "propagate"
                    ):
                        _fail(
                            f"$.conversion_plan.rules[{index}]",
                            "decimal rules require declared decimal inputs and null propagation",
                        )
                    left_precision, left_scale = _decimal_spark_type(
                        left_type,
                        f"$.conversion_plan.input_columns.{left_name}.spark_type",
                    )
                    right_precision, right_scale = _decimal_spark_type(
                        right_type,
                        f"$.conversion_plan.input_columns.{right_name}.spark_type",
                    )
                    result_precision, result_scale = _decimal_spark_type(
                        result_type,
                        f"$.conversion_plan.rules[{index}].spark_type",
                    )
                    if (
                        left_scale != right_scale
                        or result_scale != left_scale
                        or result_precision != max(left_precision, right_precision) + 1
                    ):
                        _fail(
                            f"$.conversion_plan.rules[{index}]",
                            "decimal result must preserve equal scales and declared precision",
                        )
                    left_value = _normalize_plan_value(
                        case["inputs"][left_name],
                        left_type,
                    )
                    right_value = _normalize_plan_value(
                        case["inputs"][right_name],
                        right_type,
                    )
                    if left_value is None or right_value is None:
                        computed = None
                    else:
                        with localcontext() as context:
                            context.prec = 80
                            operation = (
                                Decimal(left_value) + Decimal(right_value)
                                if kind == "decimal_add"
                                else Decimal(left_value) - Decimal(right_value)
                            )
                        computed = _normalize_plan_value(str(operation), result_type)
                else:
                    _fail(
                        f"$.conversion_plan.rules[{index}].kind",
                        "is not a supported normalized rule",
                    )
            except _PlanVectorValueError:
                checks.append({
                    "case_id": case["case_id"],
                    "field": target,
                    "status": "fail",
                    "failure_reason": "input_type_or_range_mismatch",
                })
                continue

            try:
                expected = _normalize_plan_value(
                    case["expected"][target],
                    result_type,
                )
            except _PlanVectorValueError:
                checks.append({
                    "case_id": case["case_id"],
                    "field": target,
                    "status": "fail",
                    "failure_reason": "expected_output_type_or_range_mismatch",
                })
                continue
            matches = type(computed) is type(expected) and computed == expected
            checks.append({
                "case_id": case["case_id"],
                "field": target,
                "status": "pass" if matches else "fail",
                "failure_reason": None if matches else "plan_output_mismatch",
            })

    failed_checks = sum(check["status"] == "fail" for check in checks)
    return {
        "status": "fail" if failed_checks else "pass",
        "reason": None,
        "evaluation_boundary": "local_normalized_rules_and_declared_vectors",
        "input_validation_scope": "referenced_rule_inputs_only",
        "summary": {
            "cases_evaluated": len(cases),
            "field_checks": len(checks),
            "failed_checks": failed_checks,
        },
        "checks": checks,
    }


def _source_declaration_preflight(evidence: Any) -> dict:
    if not isinstance(evidence, dict):
        _fail("$.source_declaration_preflight", "must be an object")
    if (
        not _SOURCE_PREFLIGHT_FIELDS.issubset(evidence)
        or set(evidence) - _SOURCE_PREFLIGHT_FIELDS - _SOURCE_PREFLIGHT_OPTIONAL_FIELDS
    ):
        _fail(
            "$.source_declaration_preflight",
            "must contain only supported source-evidence statuses and generator metadata",
        )
    expected_statuses = {
        "definition_sha256_check": "pass",
        "plan_vs_declared_ledger": "pass",
        "source_definition_authenticity": "not_verified",
        "ledger_source_correspondence": "not_verified",
        "source_owner_approval": "not_run",
    }
    source_evidence = {}
    for field in expected_statuses:
        value = evidence[field]
        if value != expected_statuses[field]:
            _fail(
                f"$.source_declaration_preflight.{field}",
                "has an unsupported or non-successful generator status",
            )
        source_evidence[field] = value
    return {"status": "pass", "source_evidence": source_evidence}


def compare_transform_vectors(
    manifest: Any,
    *,
    conversion_plan: Any = None,
    source_declaration_preflight: Any = None,
) -> dict:
    """Compare vectors and optionally evaluate plan rules and source preflight."""
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
        case["inputs"] = raw_case["input"]
        cases.append(case)

    normalized_rule_evaluation = _not_run_plan_evaluation(
        "conversion_plan_not_supplied"
    )
    if conversion_plan is not None:
        _validate_conversion_plan_linkage(
            conversion_plan,
            object_id=object_id,
            definition_reference=definition_reference,
            definition_hash=definition_hash,
            cases=cases,
            rule_fields=set(rules),
        )
        normalized_rule_evaluation = _evaluate_normalized_plan(
            conversion_plan,
            cases,
        )

    preflight = (
        _source_declaration_preflight(source_declaration_preflight)
        if source_declaration_preflight is not None
        else {
            "status": "not_run",
            "source_evidence": {
                "definition_sha256_check": "not_run",
                "plan_vs_declared_ledger": "not_run",
                "source_definition_authenticity": "not_verified",
                "ledger_source_correspondence": "not_verified",
                "source_owner_approval": "not_run",
            },
        }
    )

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
                same_type = _same_json_types(expected_value, actual_value)
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
                    signed_difference, allowed_difference = _exact_decimal_comparison(
                        expected_number,
                        actual_number,
                        rule["absolute_tolerance"],
                        rule["relative_tolerance"],
                    )
                    difference = signed_difference.copy_abs()
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
        "conversion_plan_linkage": (
            "pass" if conversion_plan is not None else "not_run"
        ),
        "normalized_rule_evaluation": normalized_rule_evaluation,
        "source_declaration_preflight": preflight,
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
