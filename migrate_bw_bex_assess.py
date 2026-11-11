"""Assess a local BEx semantic capture against a BW inventory snapshot."""

import argparse
import json
import sys
from pathlib import Path

from powerbi_import.bw_bex_assessment import (
    BWBExAssessmentError,
    assess_bex_semantics,
    load_bex_semantics,
)
from powerbi_import.bw_inventory import BWInventoryError, load_snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, help="Local BW inventory snapshot JSON (1.0)")
    parser.add_argument("--semantics", required=True, help="Local BEx semantic manifest JSON (1.0)")
    parser.add_argument("--output", required=True, help="New JSON report path; existing files are not overwritten")
    args = parser.parse_args(argv)

    try:
        report = assess_bex_semantics(
            load_snapshot(args.inventory),
            load_bex_semantics(args.semantics),
        )
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        content.encode("utf-8")
        with Path(args.output).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except (BWBExAssessmentError, BWInventoryError) as error:
        print(f"BW-5 BEx assessment failed: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print(
            "BW-5 BEx assessment failed while writing the report; "
            "check the output path and any partial file.",
            file=sys.stderr,
        )
        return 2

    review_count = report["summary"]["review_items"]
    review_label = "review item" if review_count == 1 else "review items"
    print(
        f"BW-5 BEx semantic capture: {report['gate_status']}; "
        f"{report['summary']['blockers']} blockers, "
        f"{review_count} {review_label}. "
        "Query execution, result comparison and consumer acceptance remain not_run."
    )
    return 0 if report["gate_status"] == "candidate_for_owner_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
