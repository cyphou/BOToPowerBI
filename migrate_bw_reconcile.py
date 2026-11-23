"""Compare local SAP BW and Fabric snapshot control declarations."""

import argparse
import json
import sys
from pathlib import Path

from powerbi_import.bw_reconciliation import (
    BWReconciliationError,
    compare_bex_result_vectors,
    compare_controls,
    load_bex_result_vectors,
    load_comparison,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--comparison", help="Local BW reconciliation manifest JSON (1.0)")
    inputs.add_argument(
        "--bex-result-vectors",
        help="Local BEx result-vector manifest JSON (1.0); compares declared rows only",
    )
    parser.add_argument("--output", required=True, help="New JSON report path; existing files are not overwritten")
    args = parser.parse_args(argv)

    try:
        if args.bex_result_vectors:
            report = compare_bex_result_vectors(
                load_bex_result_vectors(args.bex_result_vectors)
            )
        else:
            report = compare_controls(load_comparison(args.comparison))
        output = Path(args.output)
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        content.encode("utf-8")
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except BWReconciliationError as error:
        print(f"BW reconciliation failed: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print(
            "BW reconciliation failed while writing the report; "
            "check the output path and any partial file.",
            file=sys.stderr,
        )
        return 2

    if args.bex_result_vectors:
        print(
            f"Local BEx result vectors compared: {report['comparison_status']}; "
            "SAP execution, Fabric execution and business approval remain not_run; "
            "semantic equivalence is not verified."
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
    return 0 if report["comparison_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
