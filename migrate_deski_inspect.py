"""Write a partial REP inventory and optional pre-migration reports."""

import argparse
import json
import sys
import zipfile
import zlib
from contextlib import ExitStack
from pathlib import Path

from bo_export.desktop_intelligence_extractor import inspect_desktop_intelligence


def _write_new_deski_outputs(outputs):
    """Create all outputs exclusively, removing newly created files on failure."""
    created = []
    try:
        with ExitStack() as stack:
            handles = []
            for path, content in outputs:
                handle = stack.enter_context(path.open("x", encoding="utf-8", newline="\n"))
                created.append(path)
                handles.append((handle, content))
            for handle, content in handles:
                handle.write(content)
    except (OSError, UnicodeError, KeyboardInterrupt) as error:
        cleanup_errors = []
        for path in reversed(created):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                cleanup_errors.append(f"{path}: {cleanup_error}")
        if cleanup_errors:
            raise OSError(
                f"{error}; could not remove partial outputs: {'; '.join(cleanup_errors)}"
            ) from error
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Local Desktop Intelligence .rep file")
    parser.add_argument("--output", required=True, help="New JSON file; may contain sensitive SQL")
    parser.add_argument(
        "--migration-report", help="Optional new JSON pre-migration report; protect metadata"
    )
    parser.add_argument(
        "--html-report", help="Optional new HTML pre-migration report; protect metadata"
    )
    args = parser.parse_args(argv)
    try:
        output = Path(args.output)
        if output.suffix.lower() != ".json":
            raise ValueError("output must be a new .json file")
        json_report = Path(args.migration_report) if args.migration_report is not None else None
        html_report = Path(args.html_report) if args.html_report is not None else None
        if json_report is not None and json_report.suffix.lower() != ".json":
            raise ValueError("migration report must be a new .json file")
        if html_report is not None and html_report.suffix.lower() != ".html":
            raise ValueError("HTML report must be a new .html file")
        inventory = inspect_desktop_intelligence(args.source)
        content = json.dumps(inventory, ensure_ascii=False, indent=2) + "\n"
        outputs = [(output, content)]
        if json_report is not None or html_report is not None:
            from powerbi_import.deski_migration_report import (
                build_deski_migration_report,
                render_deski_migration_report,
            )
            report = build_deski_migration_report(inventory)
            if json_report is not None:
                outputs.append((json_report, json.dumps(report, ensure_ascii=False, indent=2) + "\n"))
            if html_report is not None:
                outputs.append((html_report, render_deski_migration_report(report)))
        _write_new_deski_outputs(outputs)
    except (OSError, ValueError, zipfile.BadZipFile, zlib.error, NotImplementedError) as error:
        print(f"DeskI inspection failed: {error}", file=sys.stderr)
        return 2
    print(
        f"Partial REP inventory written: {len(inventory['sheets']['candidates'])} sheet(s), "
        f"{len(inventory['providers']['candidates'])} provider candidate(s), "
        f"{len(inventory['sql_candidates'])} SQL candidate(s), "
        f"{len(inventory['object_candidates'])} object candidate(s), "
        f"{len(inventory['formula_candidates'])} formula candidate(s). "
        "Review warnings and protect the output; no query or macro was executed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
