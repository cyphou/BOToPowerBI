"""Compare local BW transformation golden vectors with declared target outputs."""

import argparse
import json
import sys
from pathlib import Path

from powerbi_import.bw_inventory import BWInventoryError, load_snapshot
from powerbi_import.bw_transform_generator import (
    BWTransformConversionError,
    build_bw_conversion_notebook,
    load_bw_conversion_plan,
)
from powerbi_import.bw_transform_validation import (
    BWTransformValidationError,
    compare_transform_vectors,
    load_transform_vectors,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vectors", required=True, help="Local transformation vectors JSON (1.0)"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="New JSON report path; existing files are not overwritten",
    )
    parser.add_argument(
        "--inventory",
        help="Local BW inventory snapshot JSON for conversion-plan linkage",
    )
    parser.add_argument(
        "--transformation",
        help="Local normalized BW transformation conversion-plan JSON",
    )
    parser.add_argument(
        "--definition-file",
        help="Local transformation definition bytes for source-declaration preflight",
    )
    parser.add_argument(
        "--rule-ledger",
        help="Local declared source-rule ledger JSON for source-declaration preflight",
    )
    args = parser.parse_args(argv)
    if (args.inventory is None) != (args.transformation is None):
        parser.error("--inventory and --transformation must be supplied together.")
    if (args.definition_file is None) != (args.rule_ledger is None):
        parser.error("--definition-file and --rule-ledger must be supplied together.")
    if args.definition_file is not None and args.inventory is None:
        parser.error(
            "--definition-file and --rule-ledger require both --inventory "
            "and --transformation."
        )

    try:
        conversion_plan = None
        source_declaration_preflight = None
        if args.inventory is not None:
            inventory = load_snapshot(args.inventory)
            conversion_plan = load_bw_conversion_plan(args.transformation)
            # Validate the complete plan against the inventory, without
            # writing or executing the generated notebook.
            if args.definition_file is None:
                build_bw_conversion_notebook(inventory, conversion_plan)
            else:
                notebook = build_bw_conversion_notebook(
                    inventory,
                    conversion_plan,
                    definition_file=args.definition_file,
                    rule_ledger=args.rule_ledger,
                )
                source_declaration_preflight = (
                    notebook["metadata"]["bw_migration"]["source_evidence"]
                )
        vectors = load_transform_vectors(args.vectors)
        if conversion_plan is None and source_declaration_preflight is None:
            report = compare_transform_vectors(vectors)
        else:
            report = compare_transform_vectors(
                vectors,
                conversion_plan=conversion_plan,
                source_declaration_preflight=source_declaration_preflight,
            )
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        content.encode("utf-8")
        with Path(args.output).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except BWInventoryError as error:
        print(f"BW transformation validation failed: BW inventory contract error: {error}", file=sys.stderr)
        return 2
    except BWTransformConversionError as error:
        print(f"BW transformation validation failed: BW conversion-plan contract error: {error}", file=sys.stderr)
        return 2
    except BWTransformValidationError as error:
        print(f"BW transformation validation failed: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print(
            "BW transformation validation failed while writing the report; "
            "check the output path and any partial file.",
            file=sys.stderr,
        )
        return 2

    print(
        "Local BW transformation vectors compared: "
        f"{report['comparison_status']}; source execution, target execution "
        "and business approval remain not_run. "
        "Local normalized-rule evaluation: "
        f"{report['normalized_rule_evaluation']['status']}."
    )
    return (
        0
        if report["comparison_status"] == "pass"
        and report["normalized_rule_evaluation"]["status"] != "fail"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
