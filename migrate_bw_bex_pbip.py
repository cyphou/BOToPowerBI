"""Generate a local Import PBIP from an explicitly authored SAP BW cube plan."""

import argparse
import json
import sys
from pathlib import Path


class BWBExPBIPPlanError(ValueError):
    """Raised when an SAP BW PBIP plan is incomplete or ambiguous."""


_PLAN_FIELDS = {"schema_version", "project_name", "datasource"}
_PLAN_OPTIONAL_FIELDS = {"bex_linkage", "review_report"}
_DATASOURCE_FIELDS = {"name", "connection", "tables"}
_CONNECTION_FIELDS = {"type", "server", "system_number", "client_id"}
_TABLE_FIELDS = {"name", "columns", "sap_bw_navigation"}
_COLUMN_TYPES = {"string", "integer", "decimal", "boolean", "datetime"}
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_BW_CAPABILITY_BOUNDARY = {
    "schema_version": "1.0",
    "scope": "repository_capability_boundary_not_generated_target_functionality",
    "functional_capabilities": [
        {
            "capability": "copy_version",
            "target_direction": "Power Apps or Talend with a controlled SQL procedure",
            "status": "not_implemented",
            "boundary": "No BW copy-version executor or SAP write-back path.",
        },
        {
            "capability": "upload_file",
            "target_direction": "Power Apps",
            "status": "not_implemented",
            "boundary": "File intake and validation are separate application concerns.",
        },
        {
            "capability": "activate_cube_data_or_data_processing",
            "target_direction": "ETL and a governed stored procedure",
            "status": "not_implemented",
            "boundary": "No SAP activation, process-chain or cube-management executor.",
        },
        {
            "capability": "planning_reporting",
            "target_direction": "Power BI and a planning-capable application",
            "status": "partial",
            "boundary": "Reporting drafts exist; planning, locking and write-back do not.",
        },
        {
            "capability": "forecast_update",
            "target_direction": "Power Apps Forms and a governed planning write",
            "status": "not_implemented",
            "boundary": "No authenticated planning update, audit or rollback workflow.",
        },
        {
            "capability": "consolidation_aggregation",
            "target_direction": "Materialized facts or a Power BI semantic model",
            "status": "partial",
            "boundary": "Explicit models exist; BEx exception, unit and currency semantics are not converted.",
        },
    ],
    "technical_objects": [
        {
            "object": "master_data_infoobjects",
            "target_direction": "Governed conformed dimensions",
            "status": "partial",
            "boundary": "Selected dimensions can be declared and assessed; SAP discovery is not implemented.",
        },
        {
            "object": "transactional_dso",
            "target_direction": "Curated fact tables",
            "status": "partial",
            "boundary": "Bounded declared transformations exist; DSO, ABAP and DTP parsing do not.",
        },
        {
            "object": "infocube",
            "target_direction": "Aggregated facts and/or a semantic model",
            "status": "partial",
            "boundary": "One declared cube can produce a local Import PBIP review draft.",
        },
        {
            "object": "multiprovider",
            "target_direction": "Materialized or semantic consolidation layer",
            "status": "not_implemented",
            "boundary": "Provider union, harmonization and precedence are not inferred.",
        },
        {
            "object": "bex_query_fiori_dashboard",
            "target_direction": "Power BI dashboard or report",
            "status": "assessment_and_review_only",
            "boundary": "BEx declarations can be assessed; calculations, prompts and layout are not converted.",
        },
    ],
    "runtime_evidence": {
        "sap_access": "not_run",
        "source_query_execution": "not_run",
        "target_query_execution": "not_run",
        "desktop_rendering": "not_run",
        "refresh": "not_run",
        "consumer_acceptance": "not_run",
        "equivalence": "not_run",
        "cutover": "not_run",
        "retirement": "not_run",
    },
}


def _require_object(value, expected_fields, path):
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise BWBExPBIPPlanError(
            f"{path} must contain exactly: {', '.join(sorted(expected_fields))}"
        )
    return value


def _require_text(value, path):
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise BWBExPBIPPlanError(f"{path} must be non-empty text without control characters")
    return value


def _validate_project_name(value):
    name = _require_text(value, "$.project_name")
    if (
        name != name.strip()
        or name.endswith((".", " "))
        or any(char in name for char in '<>:"/\\|?*')
        or name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
    ):
        raise BWBExPBIPPlanError("$.project_name is not a safe Windows file name")
    return name


def validate_plan(plan):
    """Validate the strict single-cube PBIP plan without accessing SAP."""
    if (
        not isinstance(plan, dict)
        or not _PLAN_FIELDS <= set(plan)
        or set(plan) - _PLAN_FIELDS - _PLAN_OPTIONAL_FIELDS
    ):
        raise BWBExPBIPPlanError(
            "$ must contain exactly the required plan fields and supported optional fields"
        )
    if (
        not isinstance(plan["schema_version"], str)
        or plan["schema_version"] not in {"1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"}
    ):
        raise BWBExPBIPPlanError(
            "$.schema_version must be '1.0', '1.1', '1.2', '1.3', '1.4', '1.5' or '1.6'"
        )
    if "bex_linkage" in plan and plan["schema_version"] == "1.0":
        raise BWBExPBIPPlanError(
            "$.bex_linkage requires schema_version '1.1' or later"
        )
    if "review_report" in plan and plan["schema_version"] != "1.6":
        raise BWBExPBIPPlanError(
            "$.review_report requires schema_version '1.6' or later"
        )
    project_name = _validate_project_name(plan["project_name"])

    datasource = _require_object(plan["datasource"], _DATASOURCE_FIELDS, "$.datasource")
    datasource_name = _require_text(datasource["name"], "$.datasource.name")
    connection = _require_object(
        datasource["connection"], _CONNECTION_FIELDS, "$.datasource.connection"
    )
    if connection["type"] != "sap_bw":
        raise BWBExPBIPPlanError("$.datasource.connection.type must be 'sap_bw'")
    server = _require_text(connection["server"], "$.datasource.connection.server")
    if "@" in server or "://" in server:
        raise BWBExPBIPPlanError(
            "$.datasource.connection.server must be a server identifier, not a URL or userinfo"
        )
    for field in ("system_number", "client_id"):
        _require_text(connection[field], f"$.datasource.connection.{field}")

    tables = datasource["tables"]
    if not isinstance(tables, list) or len(tables) != 1:
        raise BWBExPBIPPlanError("$.datasource.tables must contain exactly one selected cube")
    table = _require_object(tables[0], _TABLE_FIELDS, "$.datasource.tables[0]")
    _require_text(table["name"], "$.datasource.tables[0].name")

    columns = table["columns"]
    if not isinstance(columns, list) or not columns:
        raise BWBExPBIPPlanError("$.datasource.tables[0].columns must not be empty")
    column_names = set()
    folded_column_names = set()
    for index, column in enumerate(columns):
        path = f"$.datasource.tables[0].columns[{index}]"
        _require_object(column, {"name", "datatype"}, path)
        name = _require_text(column["name"], f"{path}.name")
        if name.casefold() in folded_column_names:
            raise BWBExPBIPPlanError(f"{path}.name must be unique ignoring case")
        column_names.add(name)
        folded_column_names.add(name.casefold())
        if (
            not isinstance(column["datatype"], str)
            or column["datatype"] not in _COLUMN_TYPES
        ):
            raise BWBExPBIPPlanError(
                f"{path}.datatype must be one of: {', '.join(sorted(_COLUMN_TYPES))}"
            )

    navigation = table["sap_bw_navigation"]
    required_navigation = {"info_area", "cube_id", "dimensions", "measures"}
    if (
        not isinstance(navigation, dict)
        or not required_navigation <= set(navigation)
        or set(navigation) - required_navigation - {"parameters"}
    ):
        raise BWBExPBIPPlanError(
            "$.datasource.tables[0].sap_bw_navigation must declare "
            "info_area, cube_id, dimensions and measures"
        )
    if "parameters" in navigation and plan["schema_version"] not in {"1.4", "1.5", "1.6"}:
        raise BWBExPBIPPlanError("BW cube parameters require schema_version '1.4' or later")
    dimensions = navigation["dimensions"]
    measures = navigation["measures"]
    if not isinstance(dimensions, list) or not isinstance(measures, list):
        raise BWBExPBIPPlanError("BW dimensions and measures must be lists")
    output_names = []
    for dimension in dimensions:
        if not isinstance(dimension, dict) or not isinstance(dimension.get("columns"), list):
            raise BWBExPBIPPlanError("Each BW dimension must declare output columns")
        output_names.extend(dimension["columns"])
        if "properties" in dimension:
            if plan["schema_version"] not in {"1.3", "1.4", "1.5", "1.6"}:
                raise BWBExPBIPPlanError("BW dimension properties require schema_version '1.3' or later")
            properties = dimension["properties"]
            if not isinstance(properties, list):
                raise BWBExPBIPPlanError("BW dimension properties must be a list")
            for item in properties:
                _require_object(
                    item, {"source_column", "selector", "column"}, "BW dimension property"
                )
                for field in ("source_column", "selector", "column"):
                    _require_text(item[field], f"BW dimension property.{field}")
                output_names.append(item["column"])
    for measure in measures:
        if not isinstance(measure, dict) or "column" not in measure:
            raise BWBExPBIPPlanError("Each BW measure must declare an output column")
        output_names.append(measure["column"])
    if any(not isinstance(name, str) for name in output_names):
        raise BWBExPBIPPlanError("BW output column names must be text")
    if set(output_names) != column_names:
        raise BWBExPBIPPlanError(
            "Declared model columns must exactly match the BW navigation output columns"
        )

    try:
        from bo_export.compat import generate_power_query_m

        generate_power_query_m(connection, table)
    except ValueError as error:
        raise BWBExPBIPPlanError(str(error)) from error

    for parameter in navigation.get("parameters", []):
        _require_text(parameter["selector"], "BW parameter.selector")
        if "bex_variable_id" in parameter:
            if plan["schema_version"] not in {"1.5", "1.6"}:
                raise BWBExPBIPPlanError(
                    "BW BEx variable bindings require schema_version '1.5' or later"
                )
            _require_text(parameter["bex_variable_id"], "BW parameter.bex_variable_id")
        for argument in parameter["arguments"]:
            for value in argument if isinstance(argument, list) else [argument]:
                _require_text(value, "BW parameter argument")

    variable_parameter_ids = {
        parameter["bex_variable_id"]
        for parameter in navigation.get("parameters", [])
        if "bex_variable_id" in parameter
    }
    if variable_parameter_ids and "bex_linkage" not in plan:
        raise BWBExPBIPPlanError(
            "BW BEx variable bindings require $.bex_linkage and BW-5 inputs"
        )

    if "review_report" in plan:
        review = _require_object(
            plan["review_report"], {"page_name", "columns"}, "$.review_report"
        )
        _require_text(review["page_name"], "$.review_report.page_name")
        review_columns = review["columns"]
        if not isinstance(review_columns, list) or not review_columns:
            raise BWBExPBIPPlanError("$.review_report.columns must be a non-empty list")
        seen_review_columns = set()
        for index, value in enumerate(review_columns):
            name = _require_text(value, f"$.review_report.columns[{index}]")
            if name not in column_names:
                raise BWBExPBIPPlanError(
                    f"$.review_report.columns[{index}] must exactly match a model column"
                )
            if name.casefold() in seen_review_columns:
                raise BWBExPBIPPlanError("$.review_report.columns must be unique")
            seen_review_columns.add(name.casefold())

    validated = {
        "project_name": project_name,
        "datasource": {
            "name": datasource_name,
            "connection": dict(connection),
            "tables": [table],
        },
    }
    if "review_report" in plan:
        validated["review_report"] = {
            "page_name": review["page_name"],
            "columns": list(review_columns),
        }
    if "bex_linkage" in plan:
        linkage_fields = {
            "query_id", "provider_id", "cube_id", "key_figure_bindings",
        }
        linkage = plan["bex_linkage"]
        if (
            not isinstance(linkage, dict)
            or frozenset(linkage) not in {
                frozenset(linkage_fields),
                frozenset(linkage_fields | {"dimension_bindings"}),
            }
        ):
            raise BWBExPBIPPlanError(
                "$.bex_linkage must contain exactly the required fields and "
                "optional dimension_bindings"
            )
        if (
            plan["schema_version"] in {"1.2", "1.3", "1.4", "1.5", "1.6"}
            and "dimension_bindings" not in linkage
        ):
            raise BWBExPBIPPlanError(
                f"$.schema_version '{plan['schema_version']}' requires "
                "$.bex_linkage.dimension_bindings"
            )
        if "dimension_bindings" in linkage:
            if not isinstance(linkage["dimension_bindings"], list):
                raise BWBExPBIPPlanError(
                    "$.bex_linkage.dimension_bindings must be a list"
                )
            dimension_bindings = []
            seen_dimension_selectors = set()
            for index, binding in enumerate(linkage["dimension_bindings"]):
                path = f"$.bex_linkage.dimension_bindings[{index}]"
                _require_object(
                    binding,
                    {"selector", "provider_dimension_name"},
                    path,
                )
                for field in ("selector", "provider_dimension_name"):
                    _require_text(binding[field], f"{path}.{field}")
                if binding["selector"] in seen_dimension_selectors:
                    raise BWBExPBIPPlanError(
                        f"{path}.selector must be unique"
                    )
                seen_dimension_selectors.add(binding["selector"])
                dimension_bindings.append(binding)
            selected_dimension_selectors = {
                dimension["selector"] for dimension in navigation["dimensions"]
            }
            if seen_dimension_selectors != selected_dimension_selectors:
                raise BWBExPBIPPlanError(
                    "$.bex_linkage.dimension_bindings must map every selected "
                    "BW dimension exactly once"
                )
        for field in ("query_id", "provider_id", "cube_id"):
            _require_text(linkage[field], f"$.bex_linkage.{field}")
        if linkage["cube_id"] != navigation["cube_id"]:
            raise BWBExPBIPPlanError(
                "$.bex_linkage.cube_id must match the selected BW cube_id"
            )
        bindings = linkage["key_figure_bindings"]
        if not isinstance(bindings, list):
            raise BWBExPBIPPlanError(
                "$.bex_linkage.key_figure_bindings must be a list"
            )
        binding_keys = set()
        key_figure_ids = set()
        for index, binding in enumerate(bindings):
            path = f"$.bex_linkage.key_figure_bindings[{index}]"
            _require_object(
                binding,
                {"key_figure_id", "selector", "column"},
                path,
            )
            for field in ("key_figure_id", "selector", "column"):
                _require_text(binding[field], f"{path}.{field}")
            binding_key = (binding["selector"], binding["column"])
            if binding_key in binding_keys:
                raise BWBExPBIPPlanError(f"{path} duplicates a measure mapping")
            binding_keys.add(binding_key)
            if binding["key_figure_id"] in key_figure_ids:
                raise BWBExPBIPPlanError(
                    f"{path}.key_figure_id must be unique"
                )
            key_figure_ids.add(binding["key_figure_id"])
        selected_measures = {
            (measure["selector"], measure["column"])
            for measure in navigation["measures"]
        }
        if binding_keys != selected_measures:
            raise BWBExPBIPPlanError(
                "$.bex_linkage.key_figure_bindings must map every selected BW measure exactly once"
            )
        validated["bex_linkage"] = linkage
    return validated


def validate_bex_linkage(plan, inventory, semantics):
    """Cross-check explicit plan links against local BW and BEx declarations."""
    linkage = plan.get("bex_linkage")
    if linkage is None:
        raise BWBExPBIPPlanError("BEx linkage is required when BW-5 inputs are supplied")
    if plan["datasource"]["connection"]["client_id"] != inventory["source_system"]["client"]:
        raise BWBExPBIPPlanError(
            "$.datasource.connection.client_id does not match the BW inventory source client"
        )

    from powerbi_import.bw_bex_assessment import assess_bex_semantics

    assessment = assess_bex_semantics(inventory, semantics)
    if assessment["gate_status"] != "candidate_for_owner_review":
        blockers = [
            finding
            for finding in assessment["findings"]
            if finding["severity"] == "blocker"
        ]
        blocker_details = [
            f'{finding["code"]} at {finding["path"]}'
            for finding in blockers[:3]
        ]
        if len(blockers) > len(blocker_details):
            blocker_details.append(
                f"{len(blockers) - len(blocker_details)} additional blocker(s)"
            )
        raise BWBExPBIPPlanError(
            f"BW-5 declarations contain {len(blockers)} blocker(s): "
            + "; ".join(blocker_details)
        )

    query_id = semantics["query"]["object_id"]
    if linkage["query_id"] != query_id:
        raise BWBExPBIPPlanError(
            "$.bex_linkage.query_id does not match the BEx semantic manifest"
        )
    provider = next(
        (item for item in inventory["objects"] if item["id"] == linkage["provider_id"]),
        None,
    )
    if provider is None or provider["type"] != "infocube":
        raise BWBExPBIPPlanError(
            "$.bex_linkage.provider_id must identify an InfoCube in the BW inventory"
        )
    provider_link = next(
        (
            item for item in assessment["provider_links"]
            if item["provider_id"] == linkage["provider_id"]
            and item["provider_type"] == "infocube"
            and item["resolution_status"] == "resolved"
            and item["evidence_status"] == "observed"
        ),
        None,
    )
    if provider_link is None:
        raise BWBExPBIPPlanError(
            "$.bex_linkage.provider_id must be an observed direct provider of the BEx query"
        )

    if "dimension_bindings" in linkage:
        for binding in linkage["dimension_bindings"]:
            matches = [
                item for item in provider["semantics"]["dimensions"]
                if item["name"] == binding["provider_dimension_name"]
            ]
            if len(matches) > 1:
                raise BWBExPBIPPlanError(
                    "BEx PBIP dimension binding matches multiple InfoCube dimensions: "
                    + binding["provider_dimension_name"]
                )
            if not matches or matches[0]["status"] != "observed":
                raise BWBExPBIPPlanError(
                    "BEx PBIP dimension binding is not an observed dimension of "
                    "the selected InfoCube: "
                    + binding["provider_dimension_name"]
                )

    navigation = plan["datasource"]["tables"][0]["sap_bw_navigation"]
    variable_ids = {
        item["id"] for item in semantics["variables"]
    }
    for parameter in navigation.get("parameters", []):
        variable_id = parameter.get("bex_variable_id")
        if variable_id is not None and variable_id not in variable_ids:
            raise BWBExPBIPPlanError(
                "BW parameter references an undeclared BEx variable: " + variable_id
            )
    provider_measure_links = {
        item["key_figure_id"]: item
        for item in assessment["key_figure_provider_links"]
        if item["binding_status"] == "resolved"
    }
    manifest_key_figures = {
        item["id"] for item in semantics["key_figures"]
    }
    measures_by_selector = {
        (item["selector"], item["column"]): item
        for item in navigation["measures"]
    }
    for binding in linkage["key_figure_bindings"]:
        if binding["key_figure_id"] not in manifest_key_figures:
            raise BWBExPBIPPlanError(
                "BEx linkage references an undeclared key figure: "
                + binding["key_figure_id"]
            )
        provider_binding = provider_measure_links.get(binding["key_figure_id"])
        if (
            provider_binding is None
            or provider_binding["provider_id"] != linkage["provider_id"]
        ):
            raise BWBExPBIPPlanError(
                "BEx key figure is not resolved to the selected InfoCube: "
                + binding["key_figure_id"]
            )
        measure = measures_by_selector[(binding["selector"], binding["column"])]
        expected_selector = (
            f'[Measures].[{provider_binding["provider_measure_name"]}]'
        )
        if measure["selector"] != expected_selector:
            raise BWBExPBIPPlanError(
                "BW measure selector does not match the declared provider measure "
                f"for BEx key figure {binding['key_figure_id']}"
            )

    return assessment


def load_plan(path):
    """Read and validate a UTF-8 local plan file."""
    try:
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BWBExPBIPPlanError(f"Unable to read plan JSON: {error}") from error
    return validate_plan(plan)


def _require_new_or_empty_directory(path):
    if path.is_symlink():
        raise BWBExPBIPPlanError("Output directory must not be a symbolic link")
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise BWBExPBIPPlanError("Output directory must be new or empty")


def _add_bw_capability_boundary(project_path):
    metadata_path = project_path / "migration_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["sap_bw_capability_boundary"] = _BW_CAPABILITY_BOUNDARY
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="Local SAP BW cube mapping plan JSON (1.0 to 1.6)")
    parser.add_argument("--output-dir", required=True, help="New or empty local output directory")
    parser.add_argument("--inventory", help="Optional local BW inventory for BEx linkage checks")
    parser.add_argument("--semantics", help="Optional local BEx semantic manifest for linkage checks")
    args = parser.parse_args(argv)

    try:
        plan = load_plan(args.plan)
        if bool(args.inventory) != bool(args.semantics):
            raise BWBExPBIPPlanError("--inventory and --semantics must be supplied together")
        if plan.get("bex_linkage") is not None and not args.inventory:
            raise BWBExPBIPPlanError(
                "A plan with bex_linkage requires --inventory and --semantics"
            )
        if args.inventory:
            from powerbi_import.bw_bex_assessment import (
                BWBExAssessmentError,
                load_bex_semantics,
            )
            from powerbi_import.bw_inventory import BWInventoryError, load_snapshot

            try:
                inventory = load_snapshot(args.inventory)
                semantics = load_bex_semantics(args.semantics)
                linkage_assessment = validate_bex_linkage(plan, inventory, semantics)
            except (BWBExAssessmentError, BWInventoryError) as error:
                raise BWBExPBIPPlanError(
                    f"Unable to validate BW-5 linkage declarations: {error}"
                ) from error
        else:
            linkage_assessment = None
        output_dir = Path(args.output_dir)
        _require_new_or_empty_directory(output_dir)
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        from powerbi_import.pbip_generator import PowerBIProjectGenerator
        from powerbi_import.validator import ArtifactValidator

        converted_objects = {"datasources": [plan["datasource"]]}
        generator = PowerBIProjectGenerator(str(output_dir))
        project_path = Path(generator.generate_project(plan["project_name"], converted_objects))
        if "review_report" in plan:
            review = plan["review_report"]
            generator.add_review_table(
                project_path,
                plan["project_name"],
                review["page_name"],
                plan["datasource"]["tables"][0]["name"],
                review["columns"],
            )
        generator.create_metadata(
            project_path,
            plan["project_name"],
            converted_objects,
            source="SAP BW declared cube plan",
        )
        _add_bw_capability_boundary(project_path)
        result = ArtifactValidator.validate_project(project_path)
    except (BWBExPBIPPlanError, OSError, UnicodeError, ValueError) as error:
        print(f"SAP BW PBIP generation failed: {error}", file=sys.stderr)
        return 2

    if not result["valid"]:
        print(
            "SAP BW PBIP static validation failed: "
            + "; ".join(result.get("errors", [])),
            file=sys.stderr,
        )
        return 1

    if "review_report" in plan:
        review = plan["review_report"]
        print(
            f"Review table created on page {review['page_name']!r} "
            f"with {len(review['columns'])} declared column(s)"
        )
        print(
            "SAP BW PBIP review warning: the manually declared table projects model "
            "columns, not a converted BEx report; Power BI may group duplicate "
            "projected values. Validate grain and results independently.",
            file=sys.stderr,
        )

    try:
        from powerbi_import.expression_export import export_model_expressions

        expression_export = export_model_expressions(
            project_path / f'{plan["project_name"]}.SemanticModel', project_path
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"SAP BW expression export failed: {error}", file=sys.stderr)
        return 2
    print(f"Exported {len(expression_export['exports'])} M/DAX expression file(s)")

    if linkage_assessment is not None:
        selected_ids = {
            binding["key_figure_id"]
            for binding in plan["bex_linkage"]["key_figure_bindings"]
        }
        selected_bindings = {
            binding["key_figure_id"]: binding
            for binding in plan["bex_linkage"]["key_figure_bindings"]
        }
        declared_ids = [item["id"] for item in semantics["key_figures"]]
        selected = [item for item in declared_ids if item in selected_ids]
        unselected = [item for item in declared_ids if item not in selected_ids]
        selected_semantics = []
        for key_figure in semantics["key_figures"]:
            key_figure_id = key_figure["id"]
            if key_figure_id not in selected_ids:
                continue
            binding = selected_bindings[key_figure_id]
            selected_semantics.append({
                "key_figure_id": key_figure_id,
                "selector": binding["selector"],
                "column": binding["column"],
                "manifest_status": key_figure["status"],
                "declared_aggregation": key_figure["aggregation"],
                "declared_exception_aggregation": key_figure[
                    "exception_aggregation"
                ],
                "declared_unit_currency": key_figure["unit_currency"],
            })
        parameters_by_variable = {
            parameter["bex_variable_id"]: parameter
            for parameter in plan["datasource"]["tables"][0]["sap_bw_navigation"].get(
                "parameters", []
            )
            if "bex_variable_id" in parameter
        }
        selected_variable_ids = set(parameters_by_variable)
        declared_variable_ids = [item["id"] for item in semantics["variables"]]
        selected_variable_ids_ordered = [
            item for item in declared_variable_ids if item in selected_variable_ids
        ]
        unselected_variable_ids = [
            item for item in declared_variable_ids if item not in selected_variable_ids
        ]
        if not declared_variable_ids:
            variable_selection_status = "none_declared"
        elif unselected_variable_ids:
            variable_selection_status = "some_declared_unselected"
        else:
            variable_selection_status = "all_declared_selected"
        selected_variable_bindings = []
        variables_by_id = {item["id"]: item for item in semantics["variables"]}
        for variable_id in selected_variable_ids_ordered:
            variable = variables_by_id[variable_id]
            selected_variable_bindings.append({
                "variable_id": variable_id,
                "variable_name": variable["name"],
                "kind": variable["kind"],
                "manifest_status": variable["status"],
                "parameter_selector": parameters_by_variable[variable_id]["selector"],
            })
        if not declared_ids:
            selection_status = "none_declared"
        elif unselected:
            selection_status = "some_declared_unselected"
        else:
            selection_status = "all_declared_selected"
        unconverted_semantic_counts = {
            "variables": len(semantics["variables"]),
            "filters": len(semantics["filters"]),
            "hierarchies": len(semantics["hierarchies"]),
            "master_data": len(semantics["master_data"]),
            "key_figure_semantics": len(semantics["key_figures"]),
            "authorization_contexts": len(
                semantics["authorization_contexts"]
            ),
        }
        evidence = {
            "schema_version": "1.0",
            "assessment": "local_bw_bex_pbip_linkage",
            "native_infocube_identity_verification": "not_verified",
            "bex_semantics_not_converted": {
                "evidence_scope": "declared_local_manifest_counts_only",
                "declared_coverage": dict(semantics["coverage"]),
                "counts": unconverted_semantic_counts,
            },
            "key_figure_selection": {
                "status": selection_status,
                "selected": selected,
                "unselected": unselected,
                "selected_semantics_scope": (
                    "local_bex_manifest_declarations_only"
                ),
                "selected_semantics": selected_semantics,
            },
            "variable_parameter_selection": {
                "status": variable_selection_status,
                "selected": selected_variable_bindings,
                "unselected": unselected_variable_ids,
                "scope": "explicit_local_variable_id_and_parameter_selector_declarations_only",
                "argument_values_included": False,
            },
            "plan_linkage": plan["bex_linkage"],
            "bw5_assessment": linkage_assessment,
        }
        evidence_path = output_dir / "bex_linkage_assessment.json"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            with evidence_path.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(evidence, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except (OSError, UnicodeError, ValueError) as error:
            print(
                f"SAP BW PBIP linkage evidence could not be written to "
                f"{evidence_path}: {error}",
                file=sys.stderr,
            )
            return 2

        review_count = linkage_assessment["summary"]["review_items"]
        if review_count:
            print(
                f"SAP BW PBIP owner-review warning: BW-5 has {review_count} "
                f"review item(s); inspect {evidence_path}.",
                file=sys.stderr,
            )

        if unselected:
            print(
                f"SAP BW PBIP selection warning: {len(unselected)} declared BEx key "
                f"figure(s) are not selected; review key_figure_selection in {evidence_path}.",
                file=sys.stderr,
            )

        unconverted_semantics = [
            f"{section}={count}"
            for section, count in unconverted_semantic_counts.items()
            if count
        ]
        if unconverted_semantics:
            print(
                "SAP BW PBIP semantic warning: declared BEx semantics are not "
                "reproduced in this PBIP draft ("
                + ", ".join(unconverted_semantics)
                + f"); inspect {evidence_path}.",
                file=sys.stderr,
            )

    warnings = result.get("warnings", [])
    for warning in warnings:
        print(f"SAP BW PBIP static validation warning: {warning}", file=sys.stderr)
    linkage_status = (
        " BW-5 declarations are candidate_for_owner_review."
        if linkage_assessment is not None else ""
    )
    print(
        f"Local PBIP generated and statically validated at {project_path}."
        f"{linkage_status} "
        "SAP access, credentials, query execution, Desktop rendering, refresh "
        "and BEx equivalence remain not_run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
