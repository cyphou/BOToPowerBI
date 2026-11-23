"""Validate and assess declared BW BEx semantics without executing queries."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, NoReturn

from .bw_inventory import assess_bw0, validate_snapshot
from .security_validator import scan_for_credentials


class BWBExAssessmentError(ValueError):
    """Raised when a local BEx semantic manifest is invalid."""


_ROOT_FIELDS_V1_0 = {
    "schema_version", "query", "coverage", "variables", "filters",
    "hierarchies", "master_data", "key_figures", "authorization_contexts",
    "consumers",
}
_ROOT_FIELDS_V1_1 = _ROOT_FIELDS_V1_0 | {"provider_key_figure_bindings"}
_COVERAGE_FIELDS = {
    "variables", "filters", "hierarchies", "master_data", "key_figures",
    "exception_aggregation", "units_currencies", "authorization_contexts",
    "consumers",
}
_COVERAGE = {"complete", "partial", "not_assessed", "not_applicable"}
_STATUS = {"observed", "inferred", "unknown", "not_assessed", "not_applicable"}
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.IGNORECASE)


def _fail(path: str, reason: str) -> NoReturn:
    raise BWBExAssessmentError(f"BW BEx manifest error at {path}: {reason}")


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
        _fail(path, "must be a non-empty string" if not nullable else "must be a string or null")


def _status(value: Any, path: str) -> None:
    if not isinstance(value, str) or value not in _STATUS:
        _fail(path, "has an unsupported assessment status")


def _record_list(value: Any, path: str, fields: set[str]) -> list[dict]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    seen = set()
    result = []
    for index, raw in enumerate(value):
        item_path = f"{path}[{index}]"
        item = _object(raw, item_path, fields)
        _text(item["id"], f"{item_path}.id")
        if item["id"] in seen:
            _fail(f"{item_path}.id", "must be unique within its section")
        seen.add(item["id"])
        result.append(item)
    return result


def validate_bex_semantics(manifest: Any) -> dict:
    """Validate a versioned, local BEx semantic-capture manifest."""
    if not isinstance(manifest, dict):
        _fail("$", "must contain exactly the supported fields")
    schema_version = manifest.get("schema_version")
    if not isinstance(schema_version, str) or schema_version not in {"1.0", "1.1"}:
        _fail("$.schema_version", "expected version 1.0 or 1.1")
    root = _object(
        manifest,
        "$",
        _ROOT_FIELDS_V1_0 if schema_version == "1.0" else _ROOT_FIELDS_V1_1,
    )
    try:
        encoded = json.dumps(manifest, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        _fail("$", "must contain only JSON-compatible values")
    if scan_for_credentials(encoded):
        _fail("$", "credential-like content is not allowed")

    query = _object(
        root["query"], "$.query",
        {"object_id", "definition_reference", "definition_sha256"},
    )
    for field in ("object_id", "definition_reference", "definition_sha256"):
        _text(query[field], f"$.query.{field}")
    if not _HASH.fullmatch(query["definition_sha256"]):
        _fail("$.query.definition_sha256", "must be a 64-character SHA-256 digest")

    coverage = _object(root["coverage"], "$.coverage", _COVERAGE_FIELDS)
    for field, value in coverage.items():
        if not isinstance(value, str) or value not in _COVERAGE:
            _fail(f"$.coverage.{field}", "has an unsupported coverage status")

    sections = {
        "variables": {
            "fields": {
                "id", "name", "kind", "required", "default_behavior_reference",
                "status", "evidence_reference",
            },
            "text_fields": ("name",),
        },
        "filters": {
            "fields": {
                "id", "name", "target", "operator", "selection_reference",
                "status", "evidence_reference",
            },
            "text_fields": ("name", "target", "operator"),
        },
        "hierarchies": {
            "fields": {
                "id", "characteristic", "hierarchy_reference", "versioning",
                "selection_behavior_reference", "status", "evidence_reference",
            },
            "text_fields": ("characteristic", "hierarchy_reference"),
        },
        "master_data": {
            "fields": {
                "id", "characteristic", "validity_status", "time_dependent",
                "text_languages", "evidence_reference",
            },
            "text_fields": ("characteristic",),
        },
        "key_figures": {
            "fields": {
                "id", "name", "aggregation", "exception_aggregation",
                "unit_currency", "status", "evidence_reference",
            },
            "text_fields": ("name",),
        },
        "authorization_contexts": {
            "fields": {
                "id", "authorization_reference", "role_reference",
                "data_scope_reference", "status", "evidence_reference",
            },
            "text_fields": (),
        },
        "consumers": {
            "fields": {
                "inventory_object_id", "target_candidate_reference",
                "acceptance_status", "evidence_reference",
            },
            "text_fields": (),
        },
    }

    records: dict[str, list[dict]] = {}
    for section, config in sections.items():
        raw_items = root[section]
        if section == "consumers":
            if not isinstance(raw_items, list):
                _fail("$.consumers", "must be an array")
            seen = set()
            items = []
            for index, raw in enumerate(raw_items):
                path = f"$.consumers[{index}]"
                item = _object(raw, path, config["fields"])
                _text(item["inventory_object_id"], f"{path}.inventory_object_id")
                if item["inventory_object_id"] in seen:
                    _fail(f"{path}.inventory_object_id", "must be unique")
                seen.add(item["inventory_object_id"])
                _text(item["target_candidate_reference"], f"{path}.target_candidate_reference", nullable=True)
                _text(item["evidence_reference"], f"{path}.evidence_reference", nullable=True)
                if (
                    not isinstance(item["acceptance_status"], str)
                    or item["acceptance_status"] not in {"not_run", "pass", "fail", "not_applicable"}
                ):
                    _fail(f"{path}.acceptance_status", "has an unsupported validation status")
                if item["acceptance_status"] == "pass" and item["target_candidate_reference"] is None:
                    _fail(f"{path}.target_candidate_reference", "is required for an accepted target")
                if item["acceptance_status"] == "pass" and item["evidence_reference"] is None:
                    _fail(f"{path}.evidence_reference", "is required for accepted consumer evidence")
                items.append(item)
            records[section] = items
        else:
            items = _record_list(raw_items, f"$.{section}", config["fields"])
            records[section] = items
            for index, item in enumerate(items):
                path = f"$.{section}[{index}]"
                for field in config["text_fields"]:
                    _text(item[field], f"{path}.{field}")
                status_field = "validity_status" if section == "master_data" else "status"
                _status(item[status_field], f"{path}.{status_field}")
                _text(item["evidence_reference"], f"{path}.evidence_reference", nullable=True)

    provider_bindings = []
    if schema_version == "1.1":
        raw_bindings = root["provider_key_figure_bindings"]
        if not isinstance(raw_bindings, list):
            _fail("$.provider_key_figure_bindings", "must be an array")
        seen_key_figures = set()
        binding_fields = {
            "key_figure_id", "provider_id", "provider_measure_name",
            "status", "evidence_reference",
        }
        for index, raw in enumerate(raw_bindings):
            path = f"$.provider_key_figure_bindings[{index}]"
            item = _object(raw, path, binding_fields)
            for field in ("key_figure_id", "provider_id", "provider_measure_name"):
                _text(item[field], f"{path}.{field}")
            _status(item["status"], f"{path}.status")
            _text(item["evidence_reference"], f"{path}.evidence_reference", nullable=True)
            if item["key_figure_id"] in seen_key_figures:
                _fail(f"{path}.key_figure_id", "must be unique")
            seen_key_figures.add(item["key_figure_id"])
            provider_bindings.append(item)
    records["provider_key_figure_bindings"] = provider_bindings

    for index, item in enumerate(records["variables"]):
        path = f"$.variables[{index}]"
        if not isinstance(item["kind"], str) or item["kind"] not in {
            "characteristic", "hierarchy", "key_figure", "formula_variable", "unknown",
        }:
            _fail(f"{path}.kind", "has an unsupported variable kind")
        if item["required"] is not None and type(item["required"]) is not bool:
            _fail(f"{path}.required", "must be a boolean or null")
        _text(item["default_behavior_reference"], f"{path}.default_behavior_reference", nullable=True)

    for index, item in enumerate(records["filters"]):
        _text(item["selection_reference"], f"$.filters[{index}].selection_reference", nullable=True)

    for index, item in enumerate(records["hierarchies"]):
        path = f"$.hierarchies[{index}]"
        if not isinstance(item["versioning"], str) or item["versioning"] not in {"static", "time_dependent", "unknown"}:
            _fail(f"{path}.versioning", "has an unsupported versioning value")
        _text(item["selection_behavior_reference"], f"{path}.selection_behavior_reference", nullable=True)

    for index, item in enumerate(records["master_data"]):
        path = f"$.master_data[{index}]"
        _status(item["validity_status"], f"{path}.validity_status")
        if item["time_dependent"] is not None and type(item["time_dependent"]) is not bool:
            _fail(f"{path}.time_dependent", "must be a boolean or null")
        if not isinstance(item["text_languages"], list):
            _fail(f"{path}.text_languages", "must be an array")
        languages = set()
        for language_index, language in enumerate(item["text_languages"]):
            language_path = f"{path}.text_languages[{language_index}]"
            _text(language, language_path)
            if language in languages:
                _fail(language_path, "language values must be unique")
            languages.add(language)
        _text(item["evidence_reference"], f"{path}.evidence_reference", nullable=True)

    for index, item in enumerate(records["key_figures"]):
        path = f"$.key_figures[{index}]"
        _text(item["aggregation"], f"{path}.aggregation", nullable=True)
        exception = _object(
            item["exception_aggregation"], f"{path}.exception_aggregation",
            {"status", "method", "reference_characteristic"},
        )
        units = _object(
            item["unit_currency"], f"{path}.unit_currency",
            {"status", "unit", "currency", "conversion_reference"},
        )
        _status(exception["status"], f"{path}.exception_aggregation.status")
        _status(units["status"], f"{path}.unit_currency.status")
        for field in ("method", "reference_characteristic"):
            _text(exception[field], f"{path}.exception_aggregation.{field}", nullable=True)
        if exception["status"] == "observed" and exception["method"] is None:
            _fail(f"{path}.exception_aggregation.method", "is required when observed")
        for field in ("unit", "currency", "conversion_reference"):
            _text(units[field], f"{path}.unit_currency.{field}", nullable=True)
        if units["status"] == "observed" and not any(
            units[field] is not None for field in ("unit", "currency", "conversion_reference")
        ):
            _fail(f"{path}.unit_currency", "observed unit/currency semantics require a value or reference")

    for index, item in enumerate(records["authorization_contexts"]):
        path = f"$.authorization_contexts[{index}]"
        for field in (
            "authorization_reference", "role_reference", "data_scope_reference",
            "evidence_reference",
        ):
            _text(item[field], f"{path}.{field}", nullable=True)
        _status(item["status"], f"{path}.status")

    section_for_coverage = {
        "variables": "variables",
        "filters": "filters",
        "hierarchies": "hierarchies",
        "master_data": "master_data",
        "key_figures": "key_figures",
        "authorization_contexts": "authorization_contexts",
        "consumers": "consumers",
    }
    for coverage_field, section in section_for_coverage.items():
        state = coverage[coverage_field]
        if state == "complete" and not records[section]:
            _fail(f"$.coverage.{coverage_field}", "empty sections must be marked not_applicable")
        if state == "not_applicable" and records[section]:
            _fail(f"$.coverage.{coverage_field}", "not_applicable sections must be empty")
    for field, nested_field in (
        ("exception_aggregation", "exception_aggregation"),
        ("units_currencies", "unit_currency"),
    ):
        state = coverage[field]
        if state == "complete" and not records["key_figures"]:
            _fail(f"$.coverage.{field}", "must be not_applicable when there are no key figures")
        if state == "not_applicable" and any(
            key_figure[nested_field]["status"] != "not_applicable"
            for key_figure in records["key_figures"]
        ):
            _fail(f"$.coverage.{field}", "all key figures must declare not_applicable")
        if state == "complete" and any(
            key_figure[nested_field]["status"] not in {"observed", "not_applicable"}
            for key_figure in records["key_figures"]
        ):
            _fail(f"$.coverage.{field}", "key-figure details must be observed or not_applicable")
    return root


def load_bex_semantics(path: str | Path) -> dict:
    """Load and validate a local BEx manifest, rejecting duplicate JSON keys."""
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
    except BWBExAssessmentError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail("$", "unable to read a valid UTF-8 JSON manifest")
    return validate_bex_semantics(manifest)


def assess_bex_semantics(inventory: Any, manifest: Any) -> dict:
    """Report BEx semantic capture gaps; never infer or execute query behavior."""
    bw_inventory = validate_snapshot(inventory)
    bex_manifest = validate_bex_semantics(manifest)
    query_id = bex_manifest["query"]["object_id"]
    query = next((item for item in bw_inventory["objects"] if item["id"] == query_id), None)
    if query is None or query["type"] != "bex_query":
        _fail("$.query.object_id", "must reference a BEx query in the BW inventory")
    declared_hash = query["definition"].get("hash")
    if declared_hash is not None and declared_hash.lower() != bex_manifest["query"]["definition_sha256"].lower():
        _fail("$.query.definition_sha256", "does not match the inventory query definition hash")

    inventory_objects = {item["id"]: item for item in bw_inventory["objects"]}
    inventory_object_indices = {
        item["id"]: index for index, item in enumerate(bw_inventory["objects"])
    }
    provider_edges = [
        (index, edge)
        for index, edge in enumerate(bw_inventory["dependencies"])
        if edge["kind"] == "queries" and edge["source_id"] == query_id
    ]
    observed_provider_ids = {
        edge["target_id"]
        for _index, edge in provider_edges
        if edge["resolution_status"] == "resolved" and edge["evidence_status"] == "observed"
    }
    consumer_edges = [
        (index, edge)
        for index, edge in enumerate(bw_inventory["dependencies"])
        if edge["kind"] == "consumes" and edge["target_id"] == query_id
    ]
    linked_consumers = {
        edge["source_id"]
        for _index, edge in consumer_edges
        if edge["resolution_status"] == "resolved"
        and edge["evidence_status"] == "observed"
        and inventory_objects.get(edge["source_id"], {}).get("type") == "consumer"
    }
    declared_consumers = {
        item["inventory_object_id"] for item in bex_manifest["consumers"]
    }
    for consumer_id in declared_consumers:
        consumer = inventory_objects.get(consumer_id)
        if consumer is None or consumer["type"] != "consumer":
            _fail("$.consumers", "consumer references must identify inventory consumer objects")
        if consumer_id not in linked_consumers:
            _fail("$.consumers", "each consumer must have an observed, resolved consumes dependency to this BEx query")

    findings = []

    def add(code: str, severity: str, path: str) -> None:
        findings.append({"code": code, "severity": severity, "path": path})

    inventory_review = assess_bw0(bw_inventory)
    if inventory_review["gate_status"] == "open":
        add("inventory_scope_gate_open", "blocker", "$.inventory")

    if query["disposition"] != "in_scope":
        add("bex_query_not_in_scope", "blocker", "$.query.object_id")
    if query["discovery_status"] != "observed":
        add("bex_query_not_observed", "blocker", "$.query.object_id")
    if (
        query["definition"]["status"] != "observed"
        or query["definition"]["hash_algorithm"] != "sha256"
        or query["definition"]["hash"] is None
    ):
        query_path = f"$.inventory.objects[{inventory_object_indices[query_id]}]"
        add("bex_query_definition_unverified", "blocker", f"{query_path}.definition")
    if query["migration_decision"]["classification"] == "blocked":
        add("bex_query_migration_blocked", "blocker", "$.query.object_id")
    if not provider_edges:
        add("provider_dependency_missing", "blocker", "$.inventory.dependencies")
    for index, edge in provider_edges:
        path = f"$.inventory.dependencies[{index}]"
        provider = inventory_objects.get(edge["target_id"])
        if edge["resolution_status"] != "resolved" or edge["evidence_status"] != "observed":
            add("provider_dependency_unverified", "blocker", path)
        if provider is None or provider["type"] not in {
            "infocube", "infoprovider", "adso", "composite_provider",
        }:
            add("provider_type_unverified", "blocker", path)
            continue
        provider_path = f"$.inventory.objects[{inventory_object_indices[provider['id']]}]"
        if provider["disposition"] != "in_scope":
            add("provider_not_in_scope", "blocker", f"{provider_path}.disposition")
        if provider["discovery_status"] != "observed":
            add("provider_not_observed", "blocker", f"{provider_path}.discovery_status")
        if provider["migration_decision"]["classification"] == "blocked":
            add("provider_migration_blocked", "blocker", f"{provider_path}.migration_decision.classification")
        if provider["type"] == "infocube":
            for field in ("metadata_status", "keys_status"):
                if provider[field] != "observed":
                    add("infocube_metadata_unverified", "blocker", f"{provider_path}.{field}")
            if not provider["keys"]:
                add("infocube_keys_missing", "blocker", f"{provider_path}.keys")
            for key_index, key in enumerate(provider["keys"]):
                if key["role"] == "unknown":
                    add(
                        "infocube_key_role_unverified",
                        "blocker",
                        f"{provider_path}.keys[{key_index}].role",
                    )
            if provider["semantics"]["status"] != "observed":
                add("infocube_semantics_unverified", "blocker", f"{provider_path}.semantics.status")
            for section in ("measures", "dimensions", "functions"):
                for item_index, item in enumerate(provider["semantics"][section]):
                    if item["status"] != "observed":
                        add("infocube_semantic_item_unverified", "blocker",
                            f"{provider_path}.semantics.{section}[{item_index}].status")
        for feature_index, feature in enumerate(bw_inventory["unsupported_features"]):
            if (
                feature["object_id"] == provider["id"]
                and feature["support_status"] in {"unsupported", "unknown"}
            ):
                add("provider_feature_unresolved", "blocker",
                    f"$.inventory.unsupported_features[{feature_index}]")
    for index, edge in consumer_edges:
        if (
            edge["resolution_status"] != "resolved"
            or edge["evidence_status"] != "observed"
            or inventory_objects.get(edge["source_id"], {}).get("type") != "consumer"
        ):
            add("consumer_dependency_unverified", "blocker", f"$.inventory.dependencies[{index}]")

    coverage = bex_manifest["coverage"]
    for field, state in coverage.items():
        if state not in {"complete", "not_applicable"}:
            add("semantic_coverage_incomplete", "blocker", f"$.coverage.{field}")

    key_figure_provider_links = []
    if bex_manifest["schema_version"] == "1.1":
        key_figures_by_id = {
            item["id"]: index
            for index, item in enumerate(bex_manifest["key_figures"])
        }
        bindings_by_key_figure = {
            item["key_figure_id"]: item
            for item in bex_manifest["provider_key_figure_bindings"]
        }
        for key_figure_id, index in key_figures_by_id.items():
            if key_figure_id not in bindings_by_key_figure:
                add(
                    "bex_key_figure_provider_mapping_missing",
                    "blocker",
                    f"$.key_figures[{index}]",
                )
                key_figure_provider_links.append({
                    "key_figure_id": key_figure_id,
                    "provider_id": None,
                    "provider_measure_name": None,
                    "binding_status": "missing",
                })
        for binding_index, binding in enumerate(bex_manifest["provider_key_figure_bindings"]):
            binding_path = f"$.provider_key_figure_bindings[{binding_index}]"
            if binding["key_figure_id"] not in key_figures_by_id:
                _fail(
                    f"{binding_path}.key_figure_id",
                    "must reference a declared BEx key figure",
                )
            finding_start = len(findings)
            if binding["status"] != "observed" or binding["evidence_reference"] is None:
                add("bex_key_figure_provider_mapping_unverified", "blocker", binding_path)
            provider_id = binding["provider_id"]
            if provider_id not in observed_provider_ids:
                add(
                    "key_figure_provider_unlinked",
                    "blocker",
                    f"{binding_path}.provider_id",
                )
                key_figure_provider_links.append({
                    "key_figure_id": binding["key_figure_id"],
                    "provider_id": provider_id,
                    "provider_measure_name": binding["provider_measure_name"],
                    "binding_status": "blocked",
                })
                continue
            provider = inventory_objects.get(provider_id)
            if provider is None or provider["type"] not in {
                "infocube", "infoprovider", "adso", "composite_provider",
            }:
                add(
                    "key_figure_provider_unverified",
                    "blocker",
                    f"{binding_path}.provider_id",
                )
                key_figure_provider_links.append({
                    "key_figure_id": binding["key_figure_id"],
                    "provider_id": provider_id,
                    "provider_measure_name": binding["provider_measure_name"],
                    "binding_status": "blocked",
                })
                continue
            provider_path = f"$.inventory.objects[{inventory_object_indices[provider_id]}]"
            if provider["semantics"]["status"] != "observed":
                add(
                    "key_figure_provider_semantics_unverified",
                    "blocker",
                    f"{provider_path}.semantics.status",
                )
            measure_matches = [
                (measure_index, measure)
                for measure_index, measure in enumerate(provider["semantics"]["measures"])
                if measure["name"] == binding["provider_measure_name"]
            ]
            if not measure_matches:
                add(
                    "key_figure_provider_measure_unresolved",
                    "blocker",
                    f"{binding_path}.provider_measure_name",
                )
            elif len(measure_matches) > 1:
                add(
                    "key_figure_provider_measure_ambiguous",
                    "blocker",
                    f"{binding_path}.provider_measure_name",
                )
            else:
                measure_index, measure = measure_matches[0]
                if measure["status"] != "observed":
                    add(
                        "key_figure_provider_measure_unverified",
                        "blocker",
                        f"{provider_path}.semantics.measures[{measure_index}].status",
                    )
            key_figure_provider_links.append({
                "key_figure_id": binding["key_figure_id"],
                "provider_id": provider_id,
                "provider_measure_name": binding["provider_measure_name"],
                "binding_status": "blocked" if len(findings) > finding_start else "resolved",
            })
    elif bex_manifest["key_figures"]:
        add(
            "bex_key_figure_provider_mapping_not_assessed",
            "review",
            "$.key_figures",
        )
        key_figure_provider_links = [
            {
                "key_figure_id": item["id"],
                "provider_id": None,
                "provider_measure_name": None,
                "binding_status": "not_assessed",
            }
            for item in bex_manifest["key_figures"]
        ]

    for section in (
        "variables", "filters", "hierarchies", "master_data", "key_figures",
        "authorization_contexts",
    ):
        for index, item in enumerate(bex_manifest[section]):
            status_field = "validity_status" if section == "master_data" else "status"
            status = item[status_field]
            if status in {"unknown", "not_assessed"}:
                add("semantic_item_unassessed", "blocker", f"$.{section}[{index}]")
            elif status == "inferred":
                add("semantic_item_inferred", "review", f"$.{section}[{index}]")

    for index, item in enumerate(bex_manifest["variables"]):
        if item["kind"] == "unknown" or item["required"] is None:
            add("variable_behavior_unresolved", "blocker", f"$.variables[{index}]")
        if item["default_behavior_reference"] is None:
            add("variable_default_unreferenced", "blocker", f"$.variables[{index}].default_behavior_reference")

    for index, item in enumerate(bex_manifest["filters"]):
        if item["selection_reference"] is None:
            add("filter_selection_unreferenced", "blocker", f"$.filters[{index}].selection_reference")

    for index, item in enumerate(bex_manifest["hierarchies"]):
        if item["versioning"] == "unknown":
            add("hierarchy_versioning_unknown", "blocker", f"$.hierarchies[{index}].versioning")
        if item["selection_behavior_reference"] is None:
            add("hierarchy_behavior_unreferenced", "blocker", f"$.hierarchies[{index}].selection_behavior_reference")

    for index, item in enumerate(bex_manifest["master_data"]):
        if item["time_dependent"] is None:
            add("master_data_time_dependency_unknown", "blocker", f"$.master_data[{index}].time_dependent")

    for index, item in enumerate(bex_manifest["key_figures"]):
        for field in ("exception_aggregation", "unit_currency"):
            status = item[field]["status"]
            if status in {"unknown", "not_assessed"}:
                add("semantic_detail_unassessed", "blocker", f"$.key_figures[{index}].{field}")
            elif status == "inferred":
                add("semantic_detail_inferred", "review", f"$.key_figures[{index}].{field}")
        if item["aggregation"] is None:
            add("key_figure_aggregation_missing", "blocker", f"$.key_figures[{index}].aggregation")

    for index, item in enumerate(bex_manifest["authorization_contexts"]):
        for field in ("authorization_reference", "role_reference", "data_scope_reference"):
            if item["status"] == "observed" and item[field] is None:
                add("authorization_scope_unreferenced", "blocker", f"$.authorization_contexts[{index}].{field}")

    for index, consumer in enumerate(bex_manifest["consumers"]):
        acceptance = consumer["acceptance_status"]
        if acceptance == "fail":
            add("consumer_acceptance_failed", "blocker", f"$.consumers[{index}].acceptance_status")
        elif acceptance != "pass":
            add("consumer_acceptance_not_run", "review", f"$.consumers[{index}].acceptance_status")
    for consumer_id in sorted(linked_consumers - declared_consumers):
        add("consumer_not_captured", "blocker", "$.consumers")

    for index, feature in enumerate(bw_inventory["unsupported_features"]):
        if (
            feature["object_id"] == query_id
            and feature["category"] == "bex_semantic"
            and feature["support_status"] in {"unsupported", "unknown"}
        ):
            add("unsupported_bex_semantic", "blocker", f"$.inventory.unsupported_features[{index}]")

    blockers = sum(item["severity"] == "blocker" for item in findings)
    reviews = sum(item["severity"] == "review" for item in findings)
    return {
        "schema_version": "1.0",
        "assessment": "bw5_bex_semantic_capture",
        "gate_status": "open" if blockers else "candidate_for_owner_review",
        "gate_closed": False,
        "evidence_boundary": "validated_local_inventory_and_declared_bex_semantics_only",
        "runtime_evidence": {
            "source_query_execution": "not_run",
            "target_query_execution": "not_run",
            "source_target_result_comparison": "not_run",
            "consumer_acceptance": "not_run",
            "desktop_service_rendering": "not_run",
        },
        "provider_links": [
            {
                "provider_id": edge["target_id"],
                "provider_type": inventory_objects.get(edge["target_id"], {}).get("type"),
                "resolution_status": edge["resolution_status"],
                "evidence_status": edge["evidence_status"],
            }
            for _index, edge in provider_edges
        ],
        "key_figure_provider_links": key_figure_provider_links,
        "summary": {
            "query_id": query_id,
            "inventory_gate_status": inventory_review["gate_status"],
            "semantic_items": sum(
                len(bex_manifest[section])
                for section in (
                    "variables", "filters", "hierarchies", "master_data",
                    "key_figures", "authorization_contexts",
                )
            ),
            "consumers_linked": len(linked_consumers),
            "consumers_captured": len(declared_consumers),
            "provider_dependencies": len(provider_edges),
            "provider_key_figure_bindings": len(
                bex_manifest.get("provider_key_figure_bindings", [])
            ),
            "blockers": blockers,
            "review_items": reviews,
        },
        "findings": findings,
    }
