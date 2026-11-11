"""Evaluate a declared, normalized BW snapshot-to-delta handoff offline."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

from .security_validator import scan_for_credentials


class BWHandoffError(ValueError):
    """Raised when a local BW handoff manifest violates its contract."""


_ROOT_FIELDS = {
    "schema_version", "feed_id", "source_contract", "snapshot", "events", "target",
}
_CONTRACT_FIELDS = {
    "position_semantics", "evidence_ref", "schema_version", "schema_fields",
}
_SNAPSHOT_FIELDS = {"watermark", "cutoff_utc", "records"}
_TARGET_FIELDS = {"watermark", "records"}
_EVENT_FIELDS = {
    "event_id", "position", "event_time_utc", "operation", "key",
    "schema_version", "values",
}


def _fail(path: str, reason: str) -> NoReturn:
    raise BWHandoffError(f"BW handoff contract error at {path}: {reason}")


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


def _watermark(value: Any, path: str) -> int:
    if type(value) is not int or value < 0:
        _fail(path, "must be a non-negative integer")
    return value


def _utc_datetime(value: Any, path: str) -> datetime:
    text = _text(value, path)
    if "T" not in text or not (text.endswith("Z") or text.endswith("+00:00")):
        _fail(path, "must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail(path, "must be an ISO-8601 UTC timestamp")
    if parsed.utcoffset() != timedelta(0):
        _fail(path, "must be an ISO-8601 UTC timestamp")
    return parsed


def _json_value(value: Any, path: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        _fail(path, "must be a finite JSON number")
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


def _fields(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        _fail(path, "must be a non-empty list of field names")
    fields = [_text(field, f"{path}[{index}]") for index, field in enumerate(value)]
    if len(fields) != len(set(fields)):
        _fail(path, "must not contain duplicate field names")
    return fields


def _record_map(value: Any, path: str, schema_fields: list[str]) -> dict[str, dict]:
    if not isinstance(value, list):
        _fail(path, "must be a list of records")
    records = {}
    for index, entry in enumerate(value):
        record_path = f"{path}[{index}]"
        record = _object(entry, record_path, {"key", "values"})
        key = _text(record["key"], f"{record_path}.key")
        values = record["values"]
        if not isinstance(values, dict) or set(values) != set(schema_fields):
            _fail(f"{record_path}.values", "must match the declared source schema")
        _json_value(values, f"{record_path}.values")
        if key in records:
            _fail(f"{record_path}.key", "must be unique within a snapshot")
        records[key] = values
    return records


def _event(value: Any, path: str) -> dict:
    event = _object(value, path, _EVENT_FIELDS)
    event_id = _text(event["event_id"], f"{path}.event_id")
    position = _watermark(event["position"], f"{path}.position")
    event_time = _utc_datetime(event["event_time_utc"], f"{path}.event_time_utc")
    operation = event["operation"]
    if operation not in {"upsert", "delete"}:
        _fail(f"{path}.operation", "must be 'upsert' or 'delete'")
    key = _text(event["key"], f"{path}.key")
    schema_version = _text(event["schema_version"], f"{path}.schema_version")
    values = event["values"]
    if operation == "delete":
        if values is not None:
            _fail(f"{path}.values", "must be null for a delete")
    elif not isinstance(values, dict):
        _fail(f"{path}.values", "must be an object for an upsert")
    else:
        _json_value(values, f"{path}.values")
    return {
        "event_id": event_id,
        "position": position,
        "event_time": event_time,
        "operation": operation,
        "key": key,
        "schema_version": schema_version,
        "values": values,
    }


def evaluate_handoff(manifest: Any) -> dict:
    """Evaluate local snapshot and event declarations, without verifying their origin."""
    root = _object(manifest, "$", _ROOT_FIELDS)
    if root["schema_version"] != "1.0":
        _fail("$.schema_version", "expected version 1.0")
    feed_id = _text(root["feed_id"], "$.feed_id")
    try:
        encoded = json.dumps(manifest, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        _fail("$", "must contain only JSON-compatible values")
    if scan_for_credentials(encoded):
        _fail("$", "credential-like content is not allowed")

    source_contract = _object(root["source_contract"], "$.source_contract", _CONTRACT_FIELDS)
    if source_contract["position_semantics"] != "contiguous_integer":
        _fail("$.source_contract.position_semantics", "expected 'contiguous_integer'")
    evidence_ref = _text(source_contract["evidence_ref"], "$.source_contract.evidence_ref")
    schema_version = _text(source_contract["schema_version"], "$.source_contract.schema_version")
    schema_fields = _fields(source_contract["schema_fields"], "$.source_contract.schema_fields")

    snapshot = _object(root["snapshot"], "$.snapshot", _SNAPSHOT_FIELDS)
    snapshot_watermark = _watermark(snapshot["watermark"], "$.snapshot.watermark")
    snapshot_cutoff = _utc_datetime(snapshot["cutoff_utc"], "$.snapshot.cutoff_utc")
    state = _record_map(snapshot["records"], "$.snapshot.records", schema_fields)
    snapshot_record_count = len(state)

    target = _object(root["target"], "$.target", _TARGET_FIELDS)
    target_watermark = _watermark(target["watermark"], "$.target.watermark")
    expected_state = _record_map(target["records"], "$.target.records", schema_fields)
    if target_watermark < snapshot_watermark:
        _fail("$.target.watermark", "must not precede the snapshot watermark")

    if not isinstance(root["events"], list):
        _fail("$.events", "must be a list")
    events_by_id = {}
    events_by_position = {}
    for index, raw_event in enumerate(root["events"]):
        event = _event(raw_event, f"$.events[{index}]")
        prior = events_by_id.get(event["event_id"])
        if prior is not None:
            if prior != event:
                _fail(f"$.events[{index}].event_id", "conflicting replay for event ID")
            continue
        at_position = events_by_position.get(event["position"])
        if at_position is not None and at_position["event_id"] != event["event_id"]:
            _fail(f"$.events[{index}].position", "multiple event IDs use the same position")
        events_by_id[event["event_id"]] = event
        events_by_position[event["position"]] = event

    sequenced_events = sorted(events_by_position.values(), key=lambda event: event["position"])
    delivered_positions = [
        event["position"]
        for event in events_by_id.values()
        if snapshot_watermark < event["position"] <= target_watermark
    ]
    highest_delivered_position = snapshot_watermark
    out_of_order_events = 0
    for position in delivered_positions:
        if position < highest_delivered_position:
            out_of_order_events += 1
        highest_delivered_position = max(highest_delivered_position, position)

    overlap_events = [
        event for event in sequenced_events if event["position"] <= snapshot_watermark
    ]
    post_snapshot = [
        event for event in sequenced_events
        if snapshot_watermark < event["position"] <= target_watermark
    ]
    unexpected_positions = [
        event["position"] for event in sequenced_events if event["position"] > target_watermark
    ]
    actual_positions = {event["position"] for event in post_snapshot}
    missing_position_ranges = []
    next_position = snapshot_watermark + 1
    for position in sorted(actual_positions):
        if position > next_position:
            missing_position_ranges.append([next_position, position - 1])
        next_position = position + 1
    if next_position <= target_watermark:
        missing_position_ranges.append([next_position, target_watermark])
    missing_position_count = sum(end - start + 1 for start, end in missing_position_ranges)
    missing_positions = (
        [
            position
            for start, end in missing_position_ranges
            for position in range(start, end + 1)
        ]
        if missing_position_count <= 1000
        else []
    )
    stream_contiguous = not missing_position_count and not unexpected_positions

    schema_drift_events = []
    applied_upserts = 0
    applied_deletes = 0
    late_events = 0
    latest_event_time = snapshot_cutoff
    for event in post_snapshot:
        values_match = (
            event["operation"] == "delete"
            or set(event["values"]) == set(schema_fields)
        )
        if event["schema_version"] != schema_version or not values_match:
            schema_drift_events.append(event["event_id"])
            continue
        if event["event_time"] < snapshot_cutoff or event["event_time"] < latest_event_time:
            late_events += 1
        latest_event_time = max(latest_event_time, event["event_time"])
        if event["operation"] == "upsert":
            state[event["key"]] = event["values"]
            applied_upserts += 1
        else:
            state.pop(event["key"], None)
            applied_deletes += 1

    missing_keys = set(expected_state) - set(state)
    extra_keys = set(state) - set(expected_state)
    differing_values = sum(
        state[key] != expected_state[key]
        for key in set(state).intersection(expected_state)
    )
    target_matches = not missing_keys and not extra_keys and not differing_values
    checks = {
        "stream_contiguous": "pass" if stream_contiguous else "fail",
        "schema_stable": "pass" if not schema_drift_events else "fail",
        "target_state_matches": "pass" if target_matches else "fail",
    }
    status = "pass" if all(value == "pass" for value in checks.values()) else "fail"

    return {
        "schema_version": "1.0",
        "feed_id": feed_id,
        "handoff_status": status,
        "evidence_boundary": "declared_local_feed_events_only",
        "source_contract": {
            "position_semantics": source_contract["position_semantics"],
            "evidence_ref": evidence_ref,
            "schema_version": schema_version,
        },
        "watermarks": {
            "snapshot": snapshot_watermark,
            "target": target_watermark,
        },
        "checks": checks,
        "summary": {
            "snapshot_records": snapshot_record_count,
            "events_observed": len(root["events"]),
            "unique_events": len(events_by_id),
            "replay_duplicates_ignored": len(root["events"]) - len(events_by_id),
            "overlap_events_ignored": len(overlap_events),
            "applied_upserts": applied_upserts,
            "applied_deletes": applied_deletes,
            "out_of_order_events": out_of_order_events,
            "late_events": late_events,
            "missing_positions": missing_positions,
            "missing_position_ranges": missing_position_ranges,
            "missing_position_count": missing_position_count,
            "missing_positions_truncated": missing_position_count > 1000,
            "unexpected_positions": unexpected_positions,
            "schema_drift_events": schema_drift_events,
            "target_missing_records": len(missing_keys),
            "target_extra_records": len(extra_keys),
            "target_differing_records": differing_values,
        },
        "runtime_evidence": {
            "source_extraction": "not_run",
            "fabric_execution": "not_run",
            "business_approval": "not_run",
            "bw_unavailable_operation": "not_run",
        },
    }


def load_handoff(path: str | Path) -> dict:
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
                parse_constant=reject_constant,
            )
    except (OSError, UnicodeError, ValueError):
        raise BWHandoffError("Unable to load local BW handoff JSON.") from None
    return document


__all__ = ["BWHandoffError", "evaluate_handoff", "load_handoff"]
