"""Compare local BW transformation golden vectors with declared target outputs."""

import argparse
import json
import sys
from pathlib import Path

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
    args = parser.parse_args(argv)

    try:
        report = compare_transform_vectors(load_transform_vectors(args.vectors))
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        content.encode("utf-8")
        with Path(args.output).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
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
        "and business approval remain not_run."
    )
    return 0 if report["comparison_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
