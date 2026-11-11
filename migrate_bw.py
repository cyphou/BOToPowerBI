"""Generate a local Fabric Bronze notebook for an explicitly staged BW snapshot."""

import argparse
import json
import sys
from pathlib import Path

from powerbi_import.bw_bronze_generator import (
    BWBronzeError,
    build_bw_bronze_notebook,
    load_bronze_plan,
)
from powerbi_import.bw_inventory import BWInventoryError, load_snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, help="Local BW inventory snapshot JSON (1.0)")
    parser.add_argument("--plan", required=True, help="Local BW Bronze landing plan JSON (1.0)")
    parser.add_argument("--output", required=True, help="New .ipynb file; existing files are not overwritten")
    args = parser.parse_args(argv)

    try:
        output = Path(args.output)
        if output.suffix.lower() != ".ipynb":
            raise BWBronzeError("Output must be a new .ipynb file.")
        notebook = build_bw_bronze_notebook(
            load_snapshot(args.inventory), load_bronze_plan(args.plan)
        )
        content = json.dumps(notebook, ensure_ascii=False, indent=2) + "\n"
        content.encode("utf-8")
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except (BWInventoryError, BWBronzeError) as error:
        print(f"BW Bronze generation failed: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print(
            "BW Bronze generation failed while writing the notebook; "
            "check the output path and any partial file.",
            file=sys.stderr,
        )
        return 2

    print("Local BW Bronze notebook generated; lakehouse binding and execution are not_run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
