"""Generate a limited Fabric Bronze notebook from a staged BW snapshot.

The inputs describe an already extracted, immutable Parquet snapshot. This
module does not connect to SAP or Fabric and does not convert BW semantics.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .bw_inventory import (
    BWInventoryError,
    _load_json_document,
    sanitize_snapshot,
    validate_snapshot,
)
from .notebook_generator import _code_cell, _make_notebook, _markdown_cell


class BWBronzeError(ValueError):
    """Raised when a BW historical landing plan cannot be used safely."""


_PLAN_FIELDS = {
    "schema_version", "source_object_id", "source_files", "snapshot_id",
    "snapshot_cutoff_utc", "expected_rows", "expected_columns", "target_table",
}
_BRONZE_COLUMNS = {
    "_bw_source_system_id", "_bw_object_id", "_bw_snapshot_id",
    "_bw_snapshot_cutoff_utc", "_bw_source_file", "_bw_ingested_at",
}
_SIMPLE_TYPES = {
    "string", "boolean", "tinyint", "smallint", "int", "bigint",
    "float", "double", "date", "timestamp", "binary",
}
_TARGET_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?\Z")
_DECIMAL_TYPE = re.compile(r"decimal\(([1-9][0-9]?),([0-9]+)\)\Z")


def _valid_plan_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _valid_spark_type(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if value in _SIMPLE_TYPES:
        return True
    match = _DECIMAL_TYPE.fullmatch(value)
    if not match:
        return False
    precision, scale = (int(part) for part in match.groups())
    return (
        1 <= precision <= 38
        and 0 <= scale <= precision
        and value == f"decimal({precision},{scale})"
    )


def _validate_bronze_plan(plan: Any, inventory: dict) -> tuple[dict, dict]:
    if not isinstance(plan, dict) or set(plan) != _PLAN_FIELDS:
        raise BWBronzeError("BW Bronze plan has missing or unsupported fields.")
    try:
        sanitized = sanitize_snapshot(plan)
    except BWInventoryError:
        raise BWBronzeError("BW Bronze plan contains unsafe or non-JSON values.") from None
    if sanitized != plan:
        raise BWBronzeError("BW Bronze plan must not contain credentials.")

    if plan["schema_version"] != "1.0":
        raise BWBronzeError("Unsupported BW Bronze plan version; expected 1.0.")
    for field in ("source_object_id", "snapshot_id", "snapshot_cutoff_utc"):
        if not _valid_plan_text(plan[field]):
            raise BWBronzeError(f"BW Bronze plan field {field} must be a non-empty string.")
    try:
        cutoff_text = plan["snapshot_cutoff_utc"]
        if "T" not in cutoff_text:
            raise ValueError
        cutoff = datetime.fromisoformat(cutoff_text.replace("Z", "+00:00"))
        if cutoff.utcoffset() != timedelta(0):
            raise ValueError
    except ValueError:
        raise BWBronzeError("snapshot_cutoff_utc must be an ISO-8601 UTC timestamp.") from None

    if type(plan["expected_rows"]) is not int or plan["expected_rows"] < 0:
        raise BWBronzeError("expected_rows must be a non-negative integer.")
    target = plan["target_table"]
    if not isinstance(target, str) or not _TARGET_NAME.fullmatch(target):
        raise BWBronzeError("target_table must be an explicit lower-case table or schema.table name.")

    files = plan["source_files"]
    if not isinstance(files, list) or not files:
        raise BWBronzeError("source_files must contain explicit staged Parquet files.")
    for source in files:
        if not _valid_plan_text(source):
            raise BWBronzeError("Each source file must be a non-empty path.")
        parts = source.split("/")
        if (
            len(parts) < 2
            or parts[0] != "Files"
            or any(part in ("", ".", "..") for part in parts)
            or any(character in source for character in "\\:*?[]{}#%")
            or not source.lower().endswith(".parquet")
        ):
            raise BWBronzeError("Each source file must be a relative Files/ Parquet path without wildcards.")
    if len(files) != len(set(files)):
        raise BWBronzeError("source_files must not contain duplicate paths.")

    columns = plan["expected_columns"]
    if not isinstance(columns, list) or not columns:
        raise BWBronzeError("expected_columns must describe every Parquet column.")
    column_names = set()
    for column in columns:
        if not isinstance(column, dict) or set(column) != {"name", "spark_type"}:
            raise BWBronzeError("Each expected column needs only name and spark_type.")
        name = column["name"]
        if not _valid_plan_text(name) or not _valid_spark_type(column["spark_type"]):
            raise BWBronzeError("An expected column name or Spark type is invalid or unsupported.")
        folded = name.casefold()
        if folded in column_names or folded in _BRONZE_COLUMNS:
            raise BWBronzeError("Expected column names must be distinct and not use reserved BW names.")
        column_names.add(folded)

    source = next(
        (item for item in inventory["objects"] if item["id"] == plan["source_object_id"]),
        None,
    )
    if source is None or source["type"] not in {"adso", "infocube", "infoprovider"}:
        raise BWBronzeError("source_object_id must identify an inventoried BW provider.")
    if source["disposition"] != "in_scope" or source["discovery_status"] != "observed":
        raise BWBronzeError("The BW provider must be observed and in scope.")
    if source["migration_decision"]["classification"] == "blocked":
        raise BWBronzeError("The BW provider is marked blocked in the inventory.")
    if any(
        feature["object_id"] == source["id"] and feature["support_status"] == "unsupported"
        for feature in inventory["unsupported_features"]
    ):
        raise BWBronzeError("The BW provider has explicitly unsupported inventory features.")
    return sanitized, source


def load_bronze_plan(path: str | Path) -> Any:
    """Load strict local JSON; validation against the inventory occurs at generation."""
    try:
        return _load_json_document(path)
    except (OSError, UnicodeError, ValueError):
        raise BWBronzeError("Unable to load local BW Bronze plan JSON.") from None


def build_bw_bronze_notebook(snapshot: Any, plan: Any) -> dict:
    """Build an unbound notebook for one staged provider snapshot, without writing files."""
    inventory = validate_snapshot(snapshot)
    plan, provider = _validate_bronze_plan(plan, inventory)
    config = {
        "source_system_id": inventory["source_system"]["id"],
        "source_object_id": provider["id"],
        "source_files": plan["source_files"],
        "snapshot_id": plan["snapshot_id"],
        "snapshot_cutoff_utc": plan["snapshot_cutoff_utc"],
        "expected_rows": plan["expected_rows"],
        "expected_columns": plan["expected_columns"],
        "target_table": plan["target_table"],
    }

    source = f"BW_LANDING = {config!r}\n\n" + """\
from pyspark import StorageLevel
from pyspark.sql import functions as F

target_table = BW_LANDING["target_table"]
if spark.catalog.tableExists(target_table):
    raise RuntimeError("BW Bronze target already exists; no write was attempted.")

expected_schema = {
    column["name"]: column["spark_type"]
    for column in BW_LANDING["expected_columns"]
}
frames = []
resolved_sources = set()
for source_file in BW_LANDING["source_files"]:
    frame = spark.read.format("parquet").load(source_file)
    resolved_files = frame.inputFiles()
    if len(resolved_files) != 1 or resolved_files[0] in resolved_sources:
        raise ValueError("Each BW source path must resolve to one distinct Parquet file.")
    resolved_sources.add(resolved_files[0])
    fields = [(field.name, field.dataType.simpleString()) for field in frame.schema.fields]
    if (
        len(fields) != len(expected_schema)
        or len({name.casefold() for name, _ in fields}) != len(fields)
        or dict(fields) != expected_schema
    ):
        raise ValueError("A staged Parquet file does not match the declared BW schema.")
    frames.append(frame.withColumn("_bw_source_file", F.lit(resolved_files[0])))

landed = frames[0]
for frame in frames[1:]:
    landed = landed.unionByName(frame)
landed = (
    landed
    .withColumn("_bw_source_system_id", F.lit(BW_LANDING["source_system_id"]))
    .withColumn("_bw_object_id", F.lit(BW_LANDING["source_object_id"]))
    .withColumn("_bw_snapshot_id", F.lit(BW_LANDING["snapshot_id"]))
    .withColumn("_bw_snapshot_cutoff_utc", F.lit(BW_LANDING["snapshot_cutoff_utc"]))
    .withColumn("_bw_ingested_at", F.current_timestamp())
)
expected_landing_schema = {
    **expected_schema,
    "_bw_source_file": "string",
    "_bw_source_system_id": "string",
    "_bw_object_id": "string",
    "_bw_snapshot_id": "string",
    "_bw_snapshot_cutoff_utc": "string",
    "_bw_ingested_at": "timestamp",
}
landing_fields = [(field.name, field.dataType.simpleString()) for field in landed.schema.fields]
if len(landing_fields) != len(expected_landing_schema) or dict(landing_fields) != expected_landing_schema:
    raise ValueError("BW provenance columns collide with the source schema; no table was written.")
landed = landed.persist(StorageLevel.DISK_ONLY)
try:
    source_rows = landed.count()
    if source_rows != BW_LANDING["expected_rows"]:
        raise RuntimeError("Staged BW row count differs from the declared count; no table was written.")
    landed.write.format("delta").mode("errorifexists").saveAsTable(target_table)
    target_rows = spark.table(target_table).count()
    if target_rows != source_rows:
        raise RuntimeError("BW Bronze row count differs after writing; investigate the existing table.")
    print(f"BW Bronze snapshot loaded: {source_rows} rows. Independent reconciliation remains required.")
finally:
    landed.unpersist()
"""
    notebook = _make_notebook([
        _markdown_cell(
            "# BW historical snapshot to Fabric Bronze\n\n"
            "Bind an authorized default lakehouse and stage the immutable Parquet files "
            "before running. This notebook creates one new Delta table; it does not "
            "extract SAP data or establish BW-to-Fabric equivalence.\n",
            "bw-bronze-intro",
        ),
        _code_cell(source, "bw-bronze-load"),
    ])
    notebook["metadata"]["bw_migration"] = {
        "inventory_schema_version": inventory["schema_version"],
        "inventory_run_id": inventory["run_id"],
        "source_object_id": provider["id"],
        "source_classification": provider["migration_decision"]["classification"],
        "inventory_completeness": inventory["scope"]["completeness"],
        "inventory_unknowns": len(inventory["unknowns"]),
        "unresolved_features": sum(
            feature["support_status"] != "supported"
            for feature in inventory["unsupported_features"]
        ),
        "lakehouse_binding": "unbound",
        "execution_status": "not_run",
        "bw_reconciliation_status": "not_run",
    }
    return notebook


__all__ = ["BWBronzeError", "build_bw_bronze_notebook", "load_bronze_plan"]
