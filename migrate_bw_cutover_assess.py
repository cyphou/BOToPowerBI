"""Assess local BW-8 cutover and retirement declarations without authorization."""

import argparse
import json
import sys
from pathlib import Path

from powerbi_import.bw_cutover_assessment import (
    BWCutoverAssessmentError,
    assess_bw_cutover,
    load_cutover_manifest,
)
from powerbi_import.bw_inventory import BWInventoryError, load_snapshot
from powerbi_import.bw_wave_evidence_index import BWWaveEvidenceError, load_wave_evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, help="Local BW inventory snapshot JSON (1.0)")
    parser.add_argument("--wave-evidence", required=True, help="Local BW-7 wave evidence index JSON (1.0)")
    parser.add_argument("--cutover", required=True, help="Local BW-8 cutover declarations JSON (1.0)")
    parser.add_argument("--output", required=True, help="New JSON report path; existing files are not overwritten")
    args = parser.parse_args(argv)

    try:
        report = assess_bw_cutover(
            load_snapshot(args.inventory),
            load_wave_evidence(args.wave_evidence),
            load_cutover_manifest(args.cutover),
        )
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        content.encode("utf-8")
        with Path(args.output).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except (BWCutoverAssessmentError, BWInventoryError, BWWaveEvidenceError) as error:
        print(f"BW-8 cutover assessment failed: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print(
            "BW-8 cutover assessment failed while writing the report; "
            "check the output path and any partial file.",
            file=sys.stderr,
        )
        return 2

    print(
        f"BW-8 cutover declarations: {report['status']}; "
        f"{report['summary']['blockers']} blockers. "
        "Cutover/retirement are not authorized; SAP/Fabric runtime checks remain not_run."
    )
    return 0 if report["status"] == "declarations_complete_for_owner_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
