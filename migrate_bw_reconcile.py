"""Compare local SAP BW snapshot controls or BEx result vectors."""

import argparse
import json
import sys
from pathlib import Path

from migrate_bw_bex_pbip import BWBExPBIPPlanError, validate_bex_linkage, validate_plan
from powerbi_import.bw_bex_assessment import BWBExAssessmentError, load_bex_semantics
from powerbi_import.bw_inventory import BWInventoryError, load_snapshot
from powerbi_import.bw_reconciliation import (
    BWReconciliationError,
    build_bex_csv_result_vectors,
    compare_bex_result_vectors,
    compare_controls,
    load_bex_csv_mapping,
    load_bex_result_vectors,
    load_comparison,
)
from powerbi_import.file_io import open_new_text
from powerbi_import.security_validator import scan_for_credentials


def _compare_linked_bex_vectors(
    vectors: dict, plan_path: str, inventory_path: str, semantics_path: str,
) -> dict:
    """Compare vectors and report linkage only after checking all local declarations."""
    try:
        raw_plan = load_comparison(plan_path)  # Reject duplicate keys and non-JSON constants.
    except BWReconciliationError:
        raise BWReconciliationError("Unable to load valid local linked BW cube plan JSON.") from None
    if scan_for_credentials(json.dumps(raw_plan, ensure_ascii=False, default=str)):
        raise BWReconciliationError("Credential-like content is not allowed in the linked BW cube plan.")
    plan = validate_plan(raw_plan)
    inventory = load_snapshot(inventory_path)
    semantics = load_bex_semantics(semantics_path)
    validate_bex_linkage(plan, inventory, semantics)

    report = compare_bex_result_vectors(vectors)
    linkage = plan["bex_linkage"]
    query_id = linkage["query_id"]
    project_name = plan["project_name"]
    exact_matches = (
        ("$.scope.query_id", report["scope"]["query_id"], query_id, "the plan's BEx query ID"),
        ("$.source.object_id", report["source"]["object_id"], query_id, "the plan's BEx query ID"),
        ("$.source.system_id", report["source"]["system_id"], inventory["source_system"]["id"],
         "the inventory source system ID"),
        ("$.target.object_id", report["target"]["object_id"], project_name, "the plan's project name"),
    )
    for path, declared, expected, description in exact_matches:
        if declared != expected:
            raise BWReconciliationError(f"BW reconciliation contract error at {path}: must match {description}")

    measure_names = set(vectors["rules"])
    bindings = [
        dict(binding) for binding in linkage["key_figure_bindings"]
        if binding["key_figure_id"] in measure_names
    ]
    if {binding["key_figure_id"] for binding in bindings} != measure_names:
        raise BWReconciliationError(
            "BW reconciliation contract error at $.rules: must name only BEx key figure IDs selected by the plan"
        )

    return {
        **report,
        "schema_version": "1.1",
        "plan_linkage": {
            "status": "pass",
            "evidence_boundary": "declared_local_plan_inventory_and_bex_only",
            "query_id": query_id,
            "provider_id": linkage["provider_id"],
            "cube_id": linkage["cube_id"],
            "project_name": project_name,
            "table_name": plan["datasource"]["tables"][0]["name"],
            "vector_measure_bindings": bindings,
            "native_infocube_identity_verification": "not_verified",
            "gate_closed": False,
        },
        "observation_requirement": {
            "status": "pass" if report["summary"]["measures_compared"] > 0 else "fail",
            "minimum_measure_observations": 1,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--comparison", help="Local BW reconciliation manifest JSON (1.0)")
    inputs.add_argument(
        "--bex-result-vectors",
        help="Local BEx result-vector manifest JSON (1.0); compares declared rows only",
    )
    inputs.add_argument(
        "--bex-csv-mapping",
        help="Local BEx CSV mapping JSON (1.0); requires both CSVs and all three linkage inputs",
    )
    parser.add_argument("--source-csv", help="Source CSV for --bex-csv-mapping")
    parser.add_argument("--target-csv", help="Target CSV for --bex-csv-mapping")
    parser.add_argument("--plan", help="Local linked BW cube PBIP plan for BEx reconciliation")
    parser.add_argument("--inventory", help="Local BW inventory; requires --plan and --semantics")
    parser.add_argument("--semantics", help="Local BEx manifest; requires --plan and --inventory")
    parser.add_argument("--output", required=True, help="New JSON report path; existing files are not overwritten")
    args = parser.parse_args(argv)
    csv_mode = args.bex_csv_mapping is not None
    bex_mode = csv_mode or args.bex_result_vectors is not None
    linkage_paths = (args.plan, args.inventory, args.semantics)
    if not csv_mode:
        if args.source_csv is not None or args.target_csv is not None:
            parser.error("--source-csv and --target-csv require --bex-csv-mapping.")
        if any(path is not None for path in linkage_paths):
            if not bex_mode:
                parser.error("--plan, --inventory and --semantics require --bex-result-vectors.")
            if not all(path is not None for path in linkage_paths):
                parser.error("--plan, --inventory and --semantics must be supplied together.")

    try:
        if args.bex_csv_mapping is not None:
            if not args.bex_csv_mapping or not args.output:
                parser.error("--bex-csv-mapping requires non-empty mapping and output paths.")
            if not args.source_csv or not args.target_csv:
                parser.error("--bex-csv-mapping requires non-empty --source-csv and --target-csv paths.")
            if not args.plan or not args.inventory or not args.semantics:
                parser.error("--bex-csv-mapping requires non-empty --plan, --inventory and --semantics paths.")
            vectors = build_bex_csv_result_vectors(
                load_bex_csv_mapping(args.bex_csv_mapping), args.source_csv, args.target_csv,
            )
            report = _compare_linked_bex_vectors(vectors, args.plan, args.inventory, args.semantics)
        elif args.bex_result_vectors is not None:
            vectors = load_bex_result_vectors(args.bex_result_vectors)
            if args.plan is None:
                report = compare_bex_result_vectors(vectors)
            else:
                report = _compare_linked_bex_vectors(
                    vectors, args.plan, args.inventory, args.semantics,
                )
        else:
            report = compare_controls(load_comparison(args.comparison))
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        content.encode("utf-8")
        with open_new_text(Path(args.output)) as handle:
            handle.write(content)
    except (BWBExPBIPPlanError, BWBExAssessmentError, BWInventoryError, BWReconciliationError) as error:
        print(f"BW reconciliation failed: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print(
            "BW reconciliation failed while writing the report; "
            "check the output path and any partial file.",
            file=sys.stderr,
        )
        return 2

    observations_met = True
    if bex_mode:
        print(
            f"Local BEx result vectors compared: {report['comparison_status']}; "
            "SAP execution, Fabric execution and business approval remain not_run; "
            "semantic equivalence is not verified."
        )
        if "observation_requirement" in report:
            observation_status = report["observation_requirement"]["status"]
            observations_met = observation_status == "pass"
            print(
                "Local BEx/InfoCube plan linkage: pass; "
                f"required measure observations: {observation_status}. "
                "Native InfoCube identity is not verified; Power BI execution remains not_run."
            )
        if report["summary"]["measures_compared"] == 0:
            print(
                "No measure observations were compared; "
                "this result does not establish measure agreement."
            )
    else:
        print(
            f"Local BW controls compared: {report['comparison_status']}; "
            "SAP extraction, Fabric execution and business approval remain not_run."
        )
    return 0 if report["comparison_status"] == "pass" and observations_met else 1


if __name__ == "__main__":
    raise SystemExit(main())
