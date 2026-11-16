"""Convert a normalized BW transformation into a local Fabric notebook."""

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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, help="Local BW inventory snapshot JSON (1.0)")
    parser.add_argument("--transformation", required=True, help="Normalized BW conversion plan JSON (1.0)")
    parser.add_argument("--definition-file", help="Local definition bytes; requires --rule-ledger")
    parser.add_argument("--rule-ledger", help="Declared source-rule ledger JSON; requires --definition-file")
    parser.add_argument("--output", required=True, help="New .ipynb file; existing files are not overwritten")
    args = parser.parse_args(argv)

    try:
        output = Path(args.output)
        if output.suffix.lower() != ".ipynb":
            raise BWTransformConversionError("Output must be a new .ipynb file.")
        notebook = build_bw_conversion_notebook(
            load_snapshot(args.inventory),
            load_bw_conversion_plan(args.transformation),
            definition_file=args.definition_file,
            rule_ledger=args.rule_ledger,
        )
        content = json.dumps(notebook, ensure_ascii=False, indent=2) + "\n"
        content.encode("utf-8")
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except (BWInventoryError, BWTransformConversionError) as error:
        print(f"BW transformation conversion failed: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print(
            "BW transformation conversion failed while writing the notebook; "
            "check the output path and any partial file.",
            file=sys.stderr,
        )
        return 2

    if args.definition_file is not None:
        print(
            "Definition SHA-256 and plan-to-declared-ledger checks passed; "
            "SAP origin and source-rule completeness remain unverified."
        )
    print("Local BW transformation notebook generated; binding, execution and equivalence are not_run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
