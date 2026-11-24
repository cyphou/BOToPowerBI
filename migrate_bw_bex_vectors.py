"""Package two local BEx result CSVs as vectors without comparing them."""

import argparse
import json
import sys
from pathlib import Path

from powerbi_import.bw_reconciliation import (
    BWReconciliationError,
    build_bex_csv_result_vectors,
    load_bex_csv_mapping,
)
from powerbi_import.file_io import open_new_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", required=True, help="Local BEx CSV mapping JSON (1.0)")
    parser.add_argument("--source-csv", required=True, help="Local source CSV with the two mapped columns")
    parser.add_argument("--target-csv", required=True, help="Distinct local target CSV with the two mapped columns")
    parser.add_argument("--output", required=True, help="New BEx vector JSON path; never overwritten")
    args = parser.parse_args(argv)

    try:
        vectors = build_bex_csv_result_vectors(
            load_bex_csv_mapping(args.mapping), args.source_csv, args.target_csv,
        )
    except BWReconciliationError as error:
        print(f"BEx CSV packaging failed: {error}", file=sys.stderr)
        return 2

    try:
        content = json.dumps(vectors, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        content.encode("utf-8")
        with open_new_text(Path(args.output)) as handle:
            handle.write(content)
    except (OSError, ValueError):
        print(
            "BEx CSV packaging failed: unable to create or write a new vector file; "
            "check the output path and any partial file.",
            file=sys.stderr,
        )
        return 2

    print(
        f"Packaged {len(vectors['source']['rows'])} source and "
        f"{len(vectors['target']['rows'])} target row(s) as local BEx vectors. "
        "No comparison or source/target query execution was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
