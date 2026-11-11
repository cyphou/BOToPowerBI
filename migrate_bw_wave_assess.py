"""Assess a local BW wave evidence index against an inventory snapshot."""

import argparse
import json
import sys
from pathlib import Path

from powerbi_import.bw_inventory import BWInventoryError, load_snapshot
from powerbi_import.bw_wave_evidence_index import (
    BWWaveEvidenceError,
    assess_wave_evidence,
    load_wave_evidence,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, help="Local BW inventory snapshot JSON (1.0)")
    parser.add_argument("--evidence", required=True, help="Local BW wave evidence index JSON (1.0)")
    parser.add_argument("--output", required=True, help="New JSON report path; existing files are not overwritten")
    args = parser.parse_args(argv)

    try:
        report = assess_wave_evidence(
            load_snapshot(args.inventory),
            load_wave_evidence(args.evidence),
        )
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        content.encode("utf-8")
        with Path(args.output).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except (BWWaveEvidenceError, BWInventoryError) as error:
        print(f"BW wave evidence assessment failed: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print(
            "BW wave evidence assessment failed while writing the report; "
            "check the output path and any partial file.",
            file=sys.stderr,
        )
        return 2

    print(
        f"BW wave {report['wave_id']}: {report['status']}; "
        f"{report['summary']['blockers']} blockers. "
        "SAP/Fabric runtime checks and operational certification remain not_run."
    )
    return 0 if report["status"] == "candidate_for_owner_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
