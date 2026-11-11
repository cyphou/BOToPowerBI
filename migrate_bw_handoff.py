"""Evaluate a local, normalized SAP BW snapshot-to-delta handoff manifest."""

import argparse
import json
import sys
from pathlib import Path

from powerbi_import.bw_handoff import BWHandoffError, evaluate_handoff, load_handoff


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--handoff", required=True, help="Local handoff manifest JSON (1.0)"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="New JSON report path; existing files are not overwritten",
    )
    args = parser.parse_args(argv)

    try:
        report = evaluate_handoff(load_handoff(args.handoff))
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        content.encode("utf-8")
        with Path(args.output).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except BWHandoffError as error:
        print(f"BW handoff evaluation failed: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print(
            "BW handoff evaluation failed while writing the report; "
            "check the output path and any partial file.",
            file=sys.stderr,
        )
        return 2

    print(
        f"Local BW handoff evaluation: {report['handoff_status']}; "
        "source extraction, Fabric execution and approval remain not_run."
    )
    return 0 if report["handoff_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
