"""Assess declared SAP BW inventory coverage against the BW-0 review gate."""

import argparse
import json
import sys
from pathlib import Path

from powerbi_import.bw_inventory import BWInventoryError, assess_bw0, load_snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, help="Local BW inventory snapshot JSON (1.0)")
    parser.add_argument("--output", required=True, help="New JSON report path; existing files are not overwritten")
    args = parser.parse_args(argv)

    try:
        report = assess_bw0(load_snapshot(args.inventory))
        output = Path(args.output)
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        content.encode("utf-8")
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except BWInventoryError as error:
        print(f"BW-0 assessment failed: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print(
            "BW-0 assessment failed while writing the report; "
            "check the output path and any partial file.",
            file=sys.stderr,
        )
        return 2

    print(
        f"BW-0 inventory gate: {report['gate_status']}; "
        f"{report['summary']['blockers']} blockers, "
        f"{report['summary']['review_items']} review items. "
        "The gate is not closed; live SAP discovery and owner verification remain not_run."
    )
    return 0 if report["gate_status"] == "candidate_for_owner_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
