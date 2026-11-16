"""Convert a bounded normalized BW transformation to a Fabric notebook.

The plan is an explicit declaration, not a parser for SAP metadata or ABAP.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn

from .bw_bronze_generator import (
    _BRONZE_COLUMNS,
    _DECIMAL_TYPE,
    _TARGET_NAME,
    _valid_plan_text,
    _valid_spark_type,
)
from .bw_inventory import (
    BWInventoryError,
    _load_json_document,
    sanitize_snapshot,
    validate_snapshot,
)
from .notebook_generator import _code_cell, _make_notebook, _markdown_cell


class BWTransformConversionError(ValueError):
    """Raised when a BW transformation cannot be converted safely."""


_PLAN_FIELDS = {
    "schema_version", "inventory_run_id", "source_object_id",
    "transformation_object_id", "dtp_object_id", "target_object_id",
    "definition_reference", "definition_sha256", "source_table", "target_table",
    "source_snapshot_id", "source_snapshot_cutoff_utc", "expected_rows",
    "rule_coverage", "input_columns", "rules",
}
_PROVENANCE_TYPES = {
    "_bw_source_system_id": "string",
    "_bw_object_id": "string",
    "_bw_snapshot_id": "string",
    "_bw_snapshot_cutoff_utc": "string",
    "_bw_source_file": "string",
    "_bw_ingested_at": "timestamp",
}
_CONVERSION_PROVENANCE_TYPES = {
    "_bw_transformation_id": "string",
    "_bw_transformation_definition_sha256": "string",
    "_bw_target_object_id": "string",
}
_DELTA_INVALID_COLUMN_CHARACTERS = set(" ,;{}()\n\t=")
_PROVIDER_TYPES = {"adso", "infocube", "infoprovider"}
_OBJECT_UNKNOWN_PATH = re.compile(r"^(?:\$\.)?objects\[([^\[\]]+)\](?=$|[.\[])")
_RULE_FIELDS = {
    "transfer": {"kind", "source", "target", "spark_type"},
    "constant": {"kind", "target", "spark_type", "value"},
    "decimal_add": {"kind", "left", "right", "target", "spark_type", "null_policy"},
    "decimal_subtract": {"kind", "left", "right", "target", "spark_type", "null_policy"},
}
_DECIMAL_LITERAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_SOURCE_LEDGER_FIELDS = {
    "schema_version", "inventory_run_id", "transformation_object_id",
    "definition_reference", "definition_sha256", "rule_coverage",
    "input_columns", "rules",
}


def _conversion_fail(path: str, reason: str) -> NoReturn:
    raise BWTransformConversionError(f"BW conversion contract error at {path}: {reason}")


def _conversion_object(value: Any, path: str, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        _conversion_fail(path, "must contain exactly the supported fields")
    return value


def _conversion_text(value: Any, path: str) -> str:
    if not _valid_plan_text(value):
        _conversion_fail(path, "must be a non-empty string without control characters")
    return value


def _constant_is_supported(value: Any, spark_type: str) -> bool:
    decimal_type = _DECIMAL_TYPE.fullmatch(spark_type)
    if value is None:
        return spark_type in {"string", "boolean", "int", "bigint"} or decimal_type is not None
    if spark_type == "string":
        return isinstance(value, str)
    if spark_type == "boolean":
        return type(value) is bool
    if decimal_type is not None:
        if not isinstance(value, str) or not _DECIMAL_LITERAL.fullmatch(value):
            return False
        precision, scale = map(int, decimal_type.groups())
        number = Decimal(value)
        decimal_tuple = number.as_tuple()
        exponent = decimal_tuple.exponent
        if type(exponent) is not int:
            return False
        digits = list(decimal_tuple.digits)
        fractional_digits = max(-exponent, 0)
        while fractional_digits > scale and (not digits or digits[-1] == 0):
            if digits:
                digits.pop()
            fractional_digits -= 1
        integer_digits = max(len(digits) - fractional_digits, 0)
        if number.is_zero():
            integer_digits = 0
        return (
            fractional_digits <= scale
            and integer_digits <= precision - scale
        )
    if type(value) is not int:
        return False
    if spark_type == "int":
        return -(2**31) <= value < 2**31
    if spark_type == "bigint":
        return -(2**63) <= value < 2**63
    return False


def _validate_conversion_rules(plan: dict) -> None:
    columns = plan["input_columns"]
    if not isinstance(columns, list) or not columns:
        _conversion_fail("$.input_columns", "must describe every business input column")
    if set(_PROVENANCE_TYPES) != _BRONZE_COLUMNS:
        _conversion_fail("$.input_columns", "the Bronze lineage contract is inconsistent")
    input_types = {}
    seen_inputs = {name.casefold() for name in _PROVENANCE_TYPES}
    for index, value in enumerate(columns):
        path = f"$.input_columns[{index}]"
        column = _conversion_object(value, path, {"name", "spark_type"})
        name = _conversion_text(column["name"], f"{path}.name")
        if name.casefold() in seen_inputs:
            _conversion_fail(path, "input columns must be unique and not use Bronze lineage names")
        if not _valid_spark_type(column["spark_type"]):
            _conversion_fail(f"{path}.spark_type", "is not a supported canonical Spark type")
        seen_inputs.add(name.casefold())
        input_types[name] = column["spark_type"]

    rules = plan["rules"]
    if not isinstance(rules, list) or not rules:
        _conversion_fail("$.rules", "must contain at least one supported rule")
    seen_targets = {
        name.casefold()
        for name in (*_PROVENANCE_TYPES, *_CONVERSION_PROVENANCE_TYPES)
    }
    seen_source_ids = set()
    for index, value in enumerate(rules):
        path = f"$.rules[{index}]"
        if not isinstance(value, dict):
            _conversion_fail(path, "must be a rule object")
        kind = value.get("kind")
        if not isinstance(kind, str) or kind not in _RULE_FIELDS:
            _conversion_fail(path, "rule kind is unsupported; no partial conversion is generated")
        fields = _RULE_FIELDS[kind] | ({"source_rule_id"} if "source_rule_id" in value else set())
        rule = _conversion_object(value, path, fields)
        if "source_rule_id" in rule:
            source_id = _conversion_text(rule["source_rule_id"], f"{path}.source_rule_id")
            if source_id.casefold() in seen_source_ids:
                _conversion_fail(f"{path}.source_rule_id", "must be unique ignoring case")
            seen_source_ids.add(source_id.casefold())
        target = _conversion_text(rule["target"], f"{path}.target")
        if any(character in _DELTA_INVALID_COLUMN_CHARACTERS for character in target):
            _conversion_fail(f"{path}.target", "is not a supported default Delta column name")
        if target.casefold() in seen_targets:
            _conversion_fail(f"{path}.target", "must be unique and not use BW lineage names")
        seen_targets.add(target.casefold())
        result_type = rule["spark_type"]
        if not _valid_spark_type(result_type):
            _conversion_fail(f"{path}.spark_type", "is not a supported canonical Spark type")

        if kind == "transfer":
            source = _conversion_text(rule["source"], f"{path}.source")
            if source not in input_types or input_types[source] != result_type:
                _conversion_fail(path, "a transfer requires an existing input of the exact result type")
        elif kind == "constant":
            if not _constant_is_supported(rule["value"], result_type):
                _conversion_fail(path, "the constant does not fit its supported explicit type")
        else:
            left = _conversion_text(rule["left"], f"{path}.left")
            right = _conversion_text(rule["right"], f"{path}.right")
            if left not in input_types or right not in input_types:
                _conversion_fail(path, "decimal operands must be declared input columns")
            left_type = _DECIMAL_TYPE.fullmatch(input_types[left])
            right_type = _DECIMAL_TYPE.fullmatch(input_types[right])
            if not left_type or not right_type:
                _conversion_fail(path, "decimal operands must have explicit decimal types")
            left_precision, left_scale = map(int, left_type.groups())
            right_precision, right_scale = map(int, right_type.groups())
            precision = max(left_precision, right_precision) + 1
            if (
                left_scale != right_scale
                or precision > 38
                or result_type != f"decimal({precision},{left_scale})"
            ):
                _conversion_fail(path, "decimal result must preserve equal scales without precision loss")
            if rule["null_policy"] != "propagate":
                _conversion_fail(path, "decimal null_policy must explicitly be propagate")


def _require_conversion_edge(inventory: dict, source: str, target: str, kind: str) -> None:
    edge = next(
        (
            item for item in inventory["dependencies"]
            if item["source_id"] == source and item["target_id"] == target
            and item["kind"] == kind
        ),
        None,
    )
    if (
        edge is None
        or edge["evidence_status"] != "observed"
        or edge["resolution_status"] != "resolved"
    ):
        _conversion_fail("$.dependencies", "the declared lineage must have observed, resolved edges")


def _check_conversion_unknowns(inventory: dict, selected_ids: set[str]) -> None:
    if inventory["errors"]:
        _conversion_fail("$.errors", "inventory errors require resolution before conversion")
    all_ids = {item["id"] for item in inventory["objects"]}
    for unknown in inventory["unknowns"]:
        match = _OBJECT_UNKNOWN_PATH.match(unknown["path"])
        if not match:
            _conversion_fail("$.unknowns", "an unknown has no unambiguous object scope")
        token = match.group(1)
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
            token = token[1:-1]
        candidates = set()
        if token in all_ids:
            candidates.add(token)
        if token.isascii() and token.isdecimal():
            normalized = token.lstrip("0") or "0"
            if len(normalized) <= len(str(len(inventory["objects"]) - 1)):
                index = int(normalized)
                if index < len(inventory["objects"]):
                    candidates.add(inventory["objects"][index]["id"])
        if len(candidates) != 1 or candidates & selected_ids:
            _conversion_fail("$.unknowns", "unknown or ambiguous selected-object behavior blocks conversion")


def _resolve_conversion_lineage(plan: dict, inventory: dict) -> dict:
    objects = {item["id"]: item for item in inventory["objects"]}
    selected = {}
    types = {
        "source_object_id": _PROVIDER_TYPES,
        "transformation_object_id": {"transformation"},
        "target_object_id": _PROVIDER_TYPES,
    }
    if plan["dtp_object_id"] is not None:
        types["dtp_object_id"] = {"dtp"}
    for field, allowed in types.items():
        object_id = _conversion_text(plan[field], f"$.{field}")
        item = objects.get(object_id)
        if (
            item is None
            or item["type"] not in allowed
            or item["discovery_status"] != "observed"
            or item["disposition"] != "in_scope"
            or item["migration_decision"]["classification"] == "blocked"
        ):
            _conversion_fail(f"$.{field}", "must identify an observed, in-scope, unblocked object")
        selected[field] = item
    if len({item["id"] for item in selected.values()}) != len(selected):
        _conversion_fail("$", "source, transformation, DTP and target objects must be distinct")
    for field, item in selected.items():
        if item["semantics"]["functions"]:
            _conversion_fail(f"$.{field}", "declared functions require manual review")

    transformation = selected["transformation_object_id"]
    if transformation["migration_decision"]["classification"] not in {
        "automatic_candidate", "manual_redesign",
    }:
        _conversion_fail("$.transformation_object_id", "requires an assessed migration classification")
    if (
        transformation["metadata_status"] != "observed"
        or transformation["semantics"]["status"] != "observed"
        or any(
            item["status"] != "observed"
            for category in ("measures", "dimensions")
            for item in transformation["semantics"][category]
        )
    ):
        _conversion_fail("$.transformation_object_id", "unobserved semantics or routines require manual review")
    definition = transformation["definition"]
    if (
        definition["status"] != "observed"
        or definition["hash_algorithm"] != "sha256"
        or not definition["reference"]
        or not definition["hash"]
        or definition["reference"] != plan["definition_reference"]
        or definition["hash"].lower() != plan["definition_sha256"].lower()
    ):
        _conversion_fail("$.definition_reference", "must match the observed inventory definition and SHA-256")
    selected_ids = {item["id"] for item in selected.values()}
    _check_conversion_unknowns(inventory, selected_ids)
    if any(
        feature["object_id"] in selected_ids
        and (
            feature["support_status"] != "supported"
            or feature["category"] in {"abap_routine", "custom_function"}
        )
        for feature in inventory["unsupported_features"]
    ):
        _conversion_fail("$.unsupported_features", "unknown, unsupported or routine behavior blocks conversion")

    source_id = plan["source_object_id"]
    transformation_id = plan["transformation_object_id"]
    target_id = plan["target_object_id"]
    _require_conversion_edge(inventory, source_id, transformation_id, "transforms")
    if any(
        edge["target_id"] == transformation_id
        and (edge["source_id"], edge["kind"]) != (source_id, "transforms")
        for edge in inventory["dependencies"]
    ):
        _conversion_fail("$.dependencies", "additional incoming transformation dependencies are unsupported")
    if plan["dtp_object_id"] is None:
        _require_conversion_edge(inventory, transformation_id, target_id, "transforms")
    else:
        dtp_id = plan["dtp_object_id"]
        _require_conversion_edge(inventory, transformation_id, dtp_id, "transforms")
        _require_conversion_edge(inventory, dtp_id, target_id, "feeds")
    return transformation


def _validate_conversion_plan(plan: Any, inventory: dict) -> tuple[dict, dict]:
    _conversion_object(plan, "$", _PLAN_FIELDS)
    try:
        clean = sanitize_snapshot(plan)
    except BWInventoryError:
        _conversion_fail("$", "contains unsafe or non-JSON values")
    if clean != plan:
        _conversion_fail("$", "must not contain credentials")
    if clean["schema_version"] != "1.0":
        _conversion_fail("$.schema_version", "expected version 1.0")
    for field in (
        "inventory_run_id", "definition_reference", "definition_sha256",
        "source_snapshot_id", "source_snapshot_cutoff_utc",
    ):
        _conversion_text(clean[field], f"$.{field}")
    if clean["inventory_run_id"] != inventory["run_id"]:
        _conversion_fail("$.inventory_run_id", "must match the BW inventory run")
    if clean["rule_coverage"] != "complete":
        _conversion_fail("$.rule_coverage", "must explicitly declare complete normalized rules")
    if type(clean["expected_rows"]) is not int or clean["expected_rows"] < 0:
        _conversion_fail("$.expected_rows", "must be a non-negative integer")
    for field in ("source_table", "target_table"):
        if not isinstance(clean[field], str) or not _TARGET_NAME.fullmatch(clean[field]):
            _conversion_fail(f"$.{field}", "must be a lower-case table or schema.table name")
    if clean["source_table"] == clean["target_table"]:
        _conversion_fail("$.target_table", "must differ from the source table")
    try:
        cutoff_text = clean["source_snapshot_cutoff_utc"]
        if "T" not in cutoff_text:
            raise ValueError
        cutoff = datetime.fromisoformat(cutoff_text.replace("Z", "+00:00"))
        if cutoff.utcoffset() != timedelta(0):
            raise ValueError
    except ValueError:
        _conversion_fail("$.source_snapshot_cutoff_utc", "must be an ISO-8601 UTC timestamp")
    _validate_conversion_rules(clean)
    transformation = _resolve_conversion_lineage(clean, inventory)
    return clean, transformation


def load_bw_conversion_plan(path: str | Path) -> Any:
    """Load strict local JSON; validate against the inventory when generating."""
    try:
        return _load_json_document(path)
    except (OSError, UnicodeError, ValueError):
        raise BWTransformConversionError("Unable to load local BW conversion plan JSON.") from None


def _reconcile_conversion_ledger(plan: dict, ledger: Any) -> dict:
    _conversion_object(ledger, "$.rule_ledger", _SOURCE_LEDGER_FIELDS)
    try:
        clean = sanitize_snapshot(ledger)
    except BWInventoryError:
        _conversion_fail("$.rule_ledger", "contains unsafe or non-JSON values")
    if clean != ledger:
        _conversion_fail("$.rule_ledger", "must not contain credentials")
    if clean["schema_version"] != "1.0":
        _conversion_fail("$.rule_ledger.schema_version", "expected version 1.0")
    if clean["rule_coverage"] != "complete":
        _conversion_fail("$.rule_ledger.rule_coverage", "must explicitly declare complete rules")
    for field in (
        "inventory_run_id", "transformation_object_id",
        "definition_reference", "definition_sha256",
    ):
        value = _conversion_text(clean[field], f"$.rule_ledger.{field}")
        expected = plan[field]
        if (value.lower() if field == "definition_sha256" else value) != (
            expected.lower() if field == "definition_sha256" else expected
        ):
            _conversion_fail(f"$.rule_ledger.{field}", "must match the conversion plan")

    entries = clean["rules"]
    if not isinstance(entries, list) or not entries:
        _conversion_fail("$.rule_ledger.rules", "must contain source-rule mappings")
    seen_ids = set()
    mappings = []
    for index, value in enumerate(entries):
        path = f"$.rule_ledger.rules[{index}]"
        entry = _conversion_object(value, path, {"source_rule_id", "mapping"})
        source_id = _conversion_text(entry["source_rule_id"], f"{path}.source_rule_id")
        if source_id.casefold() in seen_ids:
            _conversion_fail(f"{path}.source_rule_id", "must be unique ignoring case")
        seen_ids.add(source_id.casefold())
        if isinstance(entry["mapping"], dict) and "source_rule_id" in entry["mapping"]:
            _conversion_fail(f"{path}.mapping", "source_rule_id belongs to the ledger entry")
        mappings.append(entry["mapping"])

    _validate_conversion_rules({"input_columns": clean["input_columns"], "rules": mappings})
    source_columns = {item["name"]: item["spark_type"] for item in clean["input_columns"]}
    plan_columns = {item["name"]: item["spark_type"] for item in plan["input_columns"]}
    if source_columns != plan_columns:
        _conversion_fail("$.rule_ledger.input_columns", "must match the plan input schema")
    if any("source_rule_id" not in rule for rule in plan["rules"]):
        _conversion_fail("$.rules", "each plan rule requires a source_rule_id for ledger reconciliation")
    source_rules = {entry["source_rule_id"]: entry["mapping"] for entry in entries}
    plan_rules = {
        rule["source_rule_id"]: {key: value for key, value in rule.items() if key != "source_rule_id"}
        for rule in plan["rules"]
    }
    if set(source_rules) - set(plan_rules):
        _conversion_fail("$.rule_ledger.rules", "declared source rules are missing from the plan")
    if set(plan_rules) - set(source_rules):
        _conversion_fail("$.rule_ledger.rules", "plan rules are missing from the source-rule ledger")
    if any(source_rules[source_id] != plan_rules[source_id] for source_id in source_rules):
        _conversion_fail("$.rule_ledger.rules", "source-rule mappings differ from the plan")

    canonical = json.dumps(clean, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        "definition_sha256_check": "pass",
        "plan_vs_declared_ledger": "pass",
        "ledger_canonical_sha256": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "ledger_rule_count": len(entries),
        "source_definition_authenticity": "not_verified",
        "ledger_source_correspondence": "not_verified",
        "source_owner_approval": "not_run",
    }


def _hash_conversion_definition(path: str | Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except (OSError, ValueError, TypeError):
        _conversion_fail("$.source_evidence.definition_file", "cannot read local definition bytes")
    return digest.hexdigest()


def build_bw_conversion_notebook(
    snapshot: Any,
    plan: Any,
    *,
    definition_file: str | Path | None = None,
    rule_ledger: str | Path | None = None,
) -> dict:
    """Generate an unbound notebook for one declared, bounded transformation."""
    inventory = validate_snapshot(snapshot)
    plan, transformation = _validate_conversion_plan(plan, inventory)
    if (definition_file is None) != (rule_ledger is None):
        _conversion_fail("$.source_evidence", "requires both a definition file and a source-rule ledger")
    source_evidence = {
        "definition_sha256_check": "not_run",
        "plan_vs_declared_ledger": "not_run",
        "ledger_canonical_sha256": None,
        "ledger_rule_count": None,
        "source_definition_authenticity": "not_verified",
        "ledger_source_correspondence": "not_verified",
        "source_owner_approval": "not_run",
    }
    if definition_file is not None and rule_ledger is not None:
        try:
            ledger = _load_json_document(rule_ledger)
        except (OSError, UnicodeError, ValueError, TypeError):
            _conversion_fail("$.source_evidence.rule_ledger", "cannot load strict local JSON")
        source_evidence = _reconcile_conversion_ledger(plan, ledger)
        if _hash_conversion_definition(definition_file) != plan["definition_sha256"].lower():
            _conversion_fail("$.source_evidence.definition_file", "SHA-256 differs from the declared definition")
    config = {
        **plan,
        "source_system_id": inventory["source_system"]["id"],
        "provenance_types": _PROVENANCE_TYPES,
        "conversion_provenance_types": _CONVERSION_PROVENANCE_TYPES,
    }
    source = f"BW_TRANSFORM = {config!r}\n\n" + """\
from pyspark import StorageLevel
from pyspark.sql import functions as F


def _bw_column(name):
    return F.col("`" + name.replace("`", "``") + "`")


target_table = BW_TRANSFORM["target_table"]
if spark.catalog.tableExists(target_table):
    raise RuntimeError("BW conversion target already exists; no write was attempted.")

source = spark.table(BW_TRANSFORM["source_table"])
expected_source_schema = {
    column["name"]: column["spark_type"] for column in BW_TRANSFORM["input_columns"]
}
expected_source_schema.update(BW_TRANSFORM["provenance_types"])
source_fields = [(field.name, field.dataType.simpleString()) for field in source.schema.fields]
if (
    len(source_fields) != len(expected_source_schema)
    or len({name.casefold() for name, _ in source_fields}) != len(source_fields)
    or dict(source_fields) != expected_source_schema
):
    raise ValueError("BW Bronze source schema differs from the declared schema; no table was written.")

source = source.persist(StorageLevel.DISK_ONLY)
try:
    source_rows = source.count()
    if source_rows != BW_TRANSFORM["expected_rows"]:
        raise RuntimeError("BW source row count differs from the declared snapshot; no table was written.")
    expected_lineage = {
        "_bw_source_system_id": BW_TRANSFORM["source_system_id"],
        "_bw_object_id": BW_TRANSFORM["source_object_id"],
        "_bw_snapshot_id": BW_TRANSFORM["source_snapshot_id"],
        "_bw_snapshot_cutoff_utc": BW_TRANSFORM["source_snapshot_cutoff_utc"],
    }
    mismatch = F.lit(False)
    for name, expected in expected_lineage.items():
        mismatch = mismatch | ~_bw_column(name).eqNullSafe(F.lit(expected))
    if source.filter(mismatch).limit(1).count():
        raise RuntimeError("BW source lineage differs from the declared snapshot; no table was written.")

    expressions = []
    for rule in BW_TRANSFORM["rules"]:
        kind = rule["kind"]
        if kind == "transfer":
            expression = _bw_column(rule["source"])
        elif kind == "constant":
            expression = F.lit(rule["value"]).cast(rule["spark_type"])
        elif kind == "decimal_add":
            expression = _bw_column(rule["left"]) + _bw_column(rule["right"])
        elif kind == "decimal_subtract":
            expression = _bw_column(rule["left"]) - _bw_column(rule["right"])
        else:
            raise ValueError("Unsupported BW rule; no table was written.")
        expressions.append(expression.alias(rule["target"]))
    expressions.extend(_bw_column(name).alias(name) for name in BW_TRANSFORM["provenance_types"])
    expressions.extend([
        F.lit(BW_TRANSFORM["transformation_object_id"]).alias("_bw_transformation_id"),
        F.lit(BW_TRANSFORM["definition_sha256"]).alias("_bw_transformation_definition_sha256"),
        F.lit(BW_TRANSFORM["target_object_id"]).alias("_bw_target_object_id"),
    ])
    converted = source.select(*expressions)
    expected_output_schema = [
        (rule["target"], rule["spark_type"]) for rule in BW_TRANSFORM["rules"]
    ]
    expected_output_schema.extend(BW_TRANSFORM["provenance_types"].items())
    expected_output_schema.extend(BW_TRANSFORM["conversion_provenance_types"].items())
    output_fields = [(field.name, field.dataType.simpleString()) for field in converted.schema.fields]
    if output_fields != expected_output_schema:
        raise ValueError("BW conversion output schema differs from the declaration; no table was written.")

    converted.write.format("delta").mode("errorifexists").saveAsTable(target_table)
    target_rows = spark.table(target_table).count()
    if target_rows != source_rows:
        raise RuntimeError("BW target row count differs after writing; investigate the existing table.")
    print(f"BW transformation wrote {target_rows} rows. Independent reconciliation remains required.")
finally:
    source.unpersist()
"""
    notebook = _make_notebook([
        _markdown_cell(
            "# Declared BW transformation to Fabric Silver\n\n"
            "Bind an authorized default lakehouse containing the declared Bronze table "
            "before running. This notebook creates one new Delta table. The rules and "
            "their completeness are supplied declarations, not proof of BW equivalence.\n",
            "bw-transform-intro",
        ),
        _code_cell(source, "bw-transform-convert"),
    ])
    notebook["metadata"]["bw_migration"] = {
        "inventory_schema_version": inventory["schema_version"],
        "inventory_run_id": inventory["run_id"],
        "source_system_id": inventory["source_system"]["id"],
        "source_object_id": plan["source_object_id"],
        "transformation_object_id": plan["transformation_object_id"],
        "dtp_object_id": plan["dtp_object_id"],
        "target_object_id": plan["target_object_id"],
        "definition_reference": plan["definition_reference"],
        "definition_sha256": plan["definition_sha256"],
        "transformation_classification": transformation["migration_decision"]["classification"],
        "rule_coverage": "declared_complete",
        "source_evidence": source_evidence,
        "rule_counts": {
            kind: sum(rule["kind"] == kind for rule in plan["rules"])
            for kind in _RULE_FIELDS
        },
        "inventory_completeness": inventory["scope"]["completeness"],
        "inventory_unknowns": len(inventory["unknowns"]),
        "lakehouse_binding": "unbound",
        "execution_status": "not_run",
        "source_golden_case_execution": "not_run",
        "target_golden_case_execution": "not_run",
        "semantic_equivalence": "not_run",
        "business_approval": "not_run",
    }
    return notebook


__all__ = [
    "BWTransformConversionError", "build_bw_conversion_notebook",
    "load_bw_conversion_plan",
]
