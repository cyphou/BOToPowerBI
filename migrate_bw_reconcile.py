"""Compare local SAP BW and Fabric snapshot control declarations."""

import argparse
import json
import sys
from pathlib import Path

from powerbi_import.bw_reconciliation import (
    BWReconciliationError,
    compare_controls,
    load_comparison,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", required=True, help="Local BW reconciliation manifest JSON (1.0)")
    parser.add_argument("--output", required=True, help="New JSON report path; existing files are not overwritten")
    args = parser.parse_args(argv)

    try:
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

    print(
        f"Local BW controls compared: {report['comparison_status']}; "
        "SAP extraction, Fabric execution and business approval remain not_run."
    )
    return 0 if report["comparison_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
