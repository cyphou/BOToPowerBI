"""Validate an offline cross-source declaration ledger and write a JSON report."""

import argparse
import json
import sys
from pathlib import Path

from powerbi_import.coverage_ledger import CoverageLedgerError, build_coverage_ledger
from powerbi_import.file_io import open_new_text


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # Argument values can themselves contain sensitive data.
        self.exit(2, "Coverage ledger failed: invalid command-line arguments; use --help.\n")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonfinite_constant(value):
    raise ValueError("non-finite JSON number")


def main(argv=None):
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Local declaration manifest JSON")
    parser.add_argument("--output", required=True, help="New JSON report file; never overwritten")
    args = parser.parse_args(argv)

    try:
        with Path(args.manifest).open("r", encoding="utf-8") as handle:
            manifest = json.load(
                handle,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite_constant,
            )
    except (OSError, UnicodeError, ValueError, RecursionError):
        print("Coverage ledger failed: manifest unreadable or invalid JSON.", file=sys.stderr)
        return 2

    try:
        report = build_coverage_ledger(manifest)
    except CoverageLedgerError:
        print("Coverage ledger failed: invalid declaration manifest.", file=sys.stderr)
        return 2

    try:
        content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        content.encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        print("Coverage ledger failed: report could not be serialized as UTF-8.", file=sys.stderr)
        return 2

    try:
        with open_new_text(Path(args.output)) as handle:
            handle.write(content)
    except (OSError, ValueError, UnicodeError):
        print("Coverage ledger failed: output could not be created or written; check for a partial file.",
              file=sys.stderr)
        return 2

    print(
        "Declaration validation ran; this does not prove provenance, source coverage, "
        "equivalence, or business approval."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
