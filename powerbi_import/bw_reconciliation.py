"""Compare explicitly supplied SAP BW and Fabric snapshot controls offline."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import MAX_EMAX, MIN_EMIN, Decimal, InvalidOperation, localcontext
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


def _exact_decimal_comparison(
    reference: Decimal,
    actual: Decimal,
    absolute_tolerance: Decimal,
    relative_tolerance: Decimal,
) -> tuple[Decimal, Decimal]:
    reference_tuple = reference.as_tuple()
    actual_tuple = actual.as_tuple()
    reference_exponent = reference_tuple.exponent
    actual_exponent = actual_tuple.exponent
    if not isinstance(reference_exponent, int) or not isinstance(actual_exponent, int):
        raise ValueError("Decimal comparison requires finite values")
    difference_precision = (
        max(reference.adjusted(), actual.adjusted())
        - min(reference_exponent, actual_exponent)
        + 2
    )
    product_precision = len(reference_tuple.digits) + len(relative_tolerance.as_tuple().digits)
    with localcontext() as context:
        context.prec = max(1, difference_precision, product_precision)
        context.Emax = MAX_EMAX
        context.Emin = MIN_EMIN
        difference = actual - reference
        tolerance = max(absolute_tolerance, reference.copy_abs() * relative_tolerance)
    return difference, tolerance


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
        rule = rules[name]
        difference, tolerance = _exact_decimal_comparison(
            source_metric["value"],
            target_metric["value"],
            rule["absolute_tolerance"] if rule["mode"] == "tolerance" else Decimal(0),
            rule["relative_tolerance"] if rule["mode"] == "tolerance" else Decimal(0),
        )
        checks.append({
            "metric": name,
            "unit": source_metric["unit"],
            "source_value": str(source_metric["value"]),
            "target_value": str(target_metric["value"]),
            "difference": str(difference),
            "allowed_difference": str(tolerance),
            "status": "pass" if difference.copy_abs() <= tolerance else "fail",
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


_BEX_ROOT_FIELDS = {
    "schema_version", "comparison_id", "scope", "key_fields", "source", "target", "rules",
}
_BEX_SCOPE_FIELDS = {"query_id", "query_scope_id"}
_BEX_SIDE_FIELDS = {
    "system_id", "object_id", "run_id", "evidence_ref", "scope",
    "role", "prompt_context_ref", "grain", "rows",
}
_BEX_ROW_FIELDS = {"key", "measures"}


def _bex_scope(value: Any, path: str) -> dict:
    scope = _object(value, path, _BEX_SCOPE_FIELDS)
    return {
        "query_id": _text(scope["query_id"], f"{path}.query_id"),
        "query_scope_id": _text(scope["query_scope_id"], f"{path}.query_scope_id"),
    }


def _bex_rules(value: Any) -> dict:
    if not isinstance(value, dict) or not value:
        _fail("$.rules", "must define at least one measure rule")
    if any(not isinstance(name, str) for name in value):
        _fail("$.rules", "measure names must be strings")
    for name in value:
        _text(name, "$.rules measure")
    result = {}
    for name in sorted(value):
        raw_rule = value[name]
        if not isinstance(raw_rule, dict) or "mode" not in raw_rule:
            _fail(f"$.rules.{name}", "must be an object with a supported mode")
        if raw_rule["mode"] == "exact" and set(raw_rule) == {"mode"}:
            result[name] = {"mode": "exact"}
        elif raw_rule["mode"] == "tolerance" and set(raw_rule) == {
            "mode", "absolute_tolerance", "relative_tolerance",
        }:
            absolute = _decimal(
                raw_rule["absolute_tolerance"], f"$.rules.{name}.absolute_tolerance"
            )
            relative = _decimal(
                raw_rule["relative_tolerance"], f"$.rules.{name}.relative_tolerance"
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
    return result


def _bex_key(value: Any, path: str, key_fields: list[str]) -> tuple[dict, str]:
    if not isinstance(value, dict) or set(value) != set(key_fields):
        _fail(path, "must contain exactly the declared composite key fields")
    key = {}
    for field in key_fields:
        item = value[field]
        if not (
            item is None
            or isinstance(item, str)
            or type(item) is int
            or isinstance(item, bool)
        ):
            _fail(f"{path}.{field}", "must be a string, integer, boolean, or null key value")
        if isinstance(item, str) and any(
            ord(char) < 32 or ord(char) == 127 for char in item
        ):
            _fail(f"{path}.{field}", "must not contain control characters")
        key[field] = item
    identity = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
    return key, identity


def _bex_side(
    value: Any,
    path: str,
    expected_scope: dict,
    key_fields: list[str],
    measure_names: set[str],
) -> dict:
    side = _object(value, path, _BEX_SIDE_FIELDS)
    for field in ("system_id", "object_id", "run_id", "evidence_ref"):
        _text(side[field], f"{path}.{field}")
    scope = _bex_scope(side["scope"], f"{path}.scope")
    if scope != expected_scope:
        _fail(f"{path}.scope", "does not match the declared query scope")
    role = _text(side["role"], f"{path}.role")
    prompt_context_ref = _text(
        side["prompt_context_ref"], f"{path}.prompt_context_ref"
    )
    grain = _text(side["grain"], f"{path}.grain")
    rows = side["rows"]
    if not isinstance(rows, list):
        _fail(f"{path}.rows", "must be an array of declared result rows")
    normalized_rows = []
    for index, value_row in enumerate(rows):
        row_path = f"{path}.rows[{index}]"
        row = _object(value_row, row_path, _BEX_ROW_FIELDS)
        key, key_identity = _bex_key(row["key"], f"{row_path}.key", key_fields)
        measures = row["measures"]
        if not isinstance(measures, dict) or set(measures) != measure_names:
            _fail(
                f"{row_path}.measures",
                "must contain exactly the ruled measure names",
            )
        values = {
            name: _decimal(measures[name], f"{row_path}.measures.{name}")
            for name in sorted(measure_names)
        }
        normalized_rows.append({
            "key": key,
            "key_identity": key_identity,
            "measures": values,
        })
    return {
        "system_id": side["system_id"],
        "object_id": side["object_id"],
        "run_id": side["run_id"],
        "evidence_ref": side["evidence_ref"],
        "role": role,
        "prompt_context_ref": prompt_context_ref,
        "grain": grain,
        "rows": normalized_rows,
    }


def compare_bex_result_vectors(manifest: Any) -> dict:
    """Compare declared BEx result rows locally; no source or target execution is implied."""
    root = _object(manifest, "$", _BEX_ROOT_FIELDS)
    if root["schema_version"] != "1.0":
        _fail("$.schema_version", "expected version 1.0")
    comparison_id = _text(root["comparison_id"], "$.comparison_id")
    try:
        encoded = json.dumps(manifest, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        _fail("$", "must contain only JSON-compatible values")
    if scan_for_credentials(encoded):
        _fail("$", "credential-like content is not allowed")

    scope = _bex_scope(root["scope"], "$.scope")
    key_fields = root["key_fields"]
    if (
        not isinstance(key_fields, list)
        or not key_fields
        or any(not isinstance(field, str) for field in key_fields)
    ):
        _fail("$.key_fields", "must be a non-empty array of unique field names")
    for index, field in enumerate(key_fields):
        _text(field, f"$.key_fields[{index}]")
    if len(set(key_fields)) != len(key_fields):
        _fail("$.key_fields", "must not contain duplicate field names")
    rules = _bex_rules(root["rules"])
    measure_names = set(rules)
    source = _bex_side(
        root["source"], "$.source", scope, key_fields, measure_names
    )
    target = _bex_side(
        root["target"], "$.target", scope, key_fields, measure_names
    )
    for field in ("role", "prompt_context_ref", "grain"):
        if source[field] != target[field]:
            _fail(f"$.target.{field}", f"must match $.source.{field}")

    def index_rows(rows: list[dict]) -> dict[str, list[dict]]:
        indexed: dict[str, list[dict]] = {}
        for row in rows:
            indexed.setdefault(row["key_identity"], []).append(row)
        return indexed

    source_rows = index_rows(source["rows"])
    target_rows = index_rows(target["rows"])
    source_ids = set(source_rows)
    target_ids = set(target_rows)
    missing_ids = sorted(source_ids - target_ids)
    extra_ids = sorted(target_ids - source_ids)
    duplicate_ids = sorted(
        key_id for key_id in source_ids | target_ids
        if len(source_rows.get(key_id, [])) > 1 or len(target_rows.get(key_id, [])) > 1
    )
    key_by_id = {
        row["key_identity"]: row["key"]
        for row in source["rows"] + target["rows"]
    }
    missing_keys = [key_by_id[key_id] for key_id in missing_ids]
    extra_keys = [key_by_id[key_id] for key_id in extra_ids]
    duplicate_keys = [
        {
            "key": key_by_id[key_id],
            "source_count": len(source_rows.get(key_id, [])),
            "target_count": len(target_rows.get(key_id, [])),
        }
        for key_id in duplicate_ids
    ]

    checks = []
    for key_id in sorted(source_ids & target_ids):
        if len(source_rows[key_id]) != 1 or len(target_rows[key_id]) != 1:
            continue
        source_row = source_rows[key_id][0]
        target_row = target_rows[key_id][0]
        for name in sorted(measure_names):
            rule = rules[name]
            difference, tolerance = _exact_decimal_comparison(
                source_row["measures"][name],
                target_row["measures"][name],
                rule["absolute_tolerance"] if rule["mode"] == "tolerance" else Decimal(0),
                rule["relative_tolerance"] if rule["mode"] == "tolerance" else Decimal(0),
            )
            checks.append({
                "key": source_row["key"],
                "measure": name,
                "source_value": str(source_row["measures"][name]),
                "target_value": str(target_row["measures"][name]),
                "difference": str(difference),
                "allowed_difference": str(tolerance),
                "status": "pass" if difference.copy_abs() <= tolerance else "fail",
            })

    failed_measures = sum(check["status"] == "fail" for check in checks)
    failed = bool(
        missing_keys or extra_keys or duplicate_keys or failed_measures
    )
    limitations = [
        "declared_local_vectors_only",
        "native_infocube_identity_not_inferred",
        "bex_key_figure_linkage_not_inferred",
    ]
    if not checks:
        limitations.append("no_measure_observations_compared")
    return {
        "schema_version": "1.0",
        "comparison_id": comparison_id,
        "comparison_status": "fail" if failed else "pass",
        "evidence_boundary": "declared_local_bex_result_vectors_only",
        "scope": scope,
        "source": {
            key: source[key]
            for key in ("system_id", "object_id", "run_id", "evidence_ref")
        },
        "target": {
            key: target[key]
            for key in ("system_id", "object_id", "run_id", "evidence_ref")
        },
        "declared_context": {
            "role": source["role"],
            "prompt_context_ref": source["prompt_context_ref"],
            "grain": source["grain"],
            "key_fields": key_fields,
        },
        "summary": {
            "source_rows": len(source["rows"]),
            "target_rows": len(target["rows"]),
            "source_distinct_keys": len(source_ids),
            "target_distinct_keys": len(target_ids),
            "missing_keys": len(missing_keys),
            "extra_keys": len(extra_keys),
            "duplicate_keys": len(duplicate_keys),
            "measures_compared": len(checks),
            "measure_mismatches": failed_measures,
        },
        "missing_keys": missing_keys,
        "extra_keys": extra_keys,
        "duplicate_keys": duplicate_keys,
        "measure_mismatches": [
            check for check in checks if check["status"] == "fail"
        ],
        "checks": checks,
        "runtime_evidence": {
            "sap_execution": "not_run",
            "fabric_execution": "not_run",
            "business_approval": "not_run",
        },
        "verification_status": {
            "authenticity": "not_verified",
            "provenance": "not_verified",
            "source_coverage": "not_verified",
            "semantic_equivalence": "not_verified",
        },
        "limitations": limitations,
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


def load_bex_result_vectors(path: str | Path) -> dict:
    """Load a local BEx result-vector manifest with duplicate-key rejection."""
    try:
        return load_comparison(path)
    except BWReconciliationError:
        raise BWReconciliationError(
            "Unable to load local BW BEx result-vector JSON."
        ) from None


__all__ = [
    "BWReconciliationError",
    "compare_bex_result_vectors",
    "compare_controls",
    "load_bex_result_vectors",
    "load_comparison",
]
