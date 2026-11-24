"""Orchestrate local declared BEx/InfoCube checks, never SAP or target execution.

Exit codes: 0 local checks pass; 1 local validation/comparison fails (including
zero observations); 2 invalid input or orchestration/write failure. Failed
static checks retain staged PBIP artifacts and evidence in a new directory.
Invalid input or orchestration failure publishes nothing. All checks use one
private input snapshot; the complete output is published once, without overwrite.
No extraction, semantic translation, deployment or business acceptance occurs.
"""

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

from migrate_bw_bex_pbip import load_plan
from powerbi_import.bw_bex_assessment import assess_bex_semantics, load_bex_semantics
from powerbi_import.bw_inventory import load_snapshot
from powerbi_import.bw_reconciliation import load_comparison
from powerbi_import.file_io import open_new_text
from powerbi_import.security_validator import scan_for_credentials


class _PilotParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default diagnostics can echo private argument values.
        self.exit(2, "Local BEx pilot: invalid arguments; use --help.\n")


def _pilot_run(script, arguments):
    """Use only repository-local scripts and discard potentially sensitive logs."""
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / script), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode


def _pilot_counts(summary, fields):
    counts = {field: summary[field] for field in fields}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("Invalid summary counts")
    return counts


def _pilot_no_links(path):
    """Reject symlinks/junctions before resolving inputs or destinations."""
    for entry in (path, *path.parents):
        if entry.is_symlink() or entry.is_junction():
            raise ValueError("Linked output destination")


def _pilot_child(root, *parts):
    _pilot_no_links(root)
    path = root.joinpath(*parts)
    _pilot_no_links(path)
    if not path.resolve().is_relative_to(root.resolve()) or path == root:
        raise ValueError("Output escapes destination")
    return path


def _pilot_check_tree(root):
    _pilot_no_links(root)
    if not root.is_dir():
        raise ValueError("Missing output tree")
    for entry in root.rglob("*"):
        _pilot_child(root, entry.relative_to(root))
        metadata = entry.lstat()
        if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
            raise ValueError("Non-regular output entry")
        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
            raise ValueError("Hard-linked output entry")


def _pilot_snapshot_inputs(args, root, destination):
    """Open six distinct regular inputs once and copy their bytes before checks."""
    fields = ("plan", "inventory", "semantics", "csv_mapping", "source_csv", "target_csv")
    paths = {field: Path(getattr(args, field)).absolute() for field in fields}
    metadata = {}
    for field, path in paths.items():
        _pilot_no_links(path)
        metadata[field] = path.lstat()
        if not stat.S_ISREG(metadata[field].st_mode):
            raise ValueError("Non-regular input")
        resolved = path.resolve(strict=True)
        if resolved.is_relative_to(destination) or destination.is_relative_to(resolved):
            raise ValueError("Input overlaps output")
    # In particular, hard-link aliases must not turn the CSV comparison into self-comparison.
    if paths["source_csv"].samefile(paths["target_csv"]):
        raise ValueError("CSV inputs are the same file")
    for index, field in enumerate(fields):
        if any(paths[field].samefile(paths[other]) for other in fields[:index]):
            raise ValueError("Inputs are not distinct")

    snapshots = {}
    with ExitStack() as handles:
        sources = {}
        identities = set()
        for field, path in paths.items():
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            source = handles.enter_context(os.fdopen(os.open(path, flags), "rb"))
            opened = os.fstat(source.fileno())
            identity = (opened.st_dev, opened.st_ino)
            _pilot_no_links(path)
            if (
                not stat.S_ISREG(opened.st_mode) or identity in identities
                or identity != (metadata[field].st_dev, metadata[field].st_ino)
            ):
                raise ValueError("Input changed before snapshot")
            identities.add(identity)
            sources[field] = (source, opened)
        for field, (source, opened) in sources.items():
            suffix = ".csv" if field in ("source_csv", "target_csv") else ".json"
            snapshot = _pilot_child(root, field + suffix)
            with snapshot.open("xb") as target:
                shutil.copyfileobj(source, target)
            after = os.fstat(source.fileno())
            if (
                (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or snapshot.stat().st_size != opened.st_size
            ):
                raise ValueError("Input changed during snapshot")
            snapshots[field] = str(snapshot)
    return argparse.Namespace(**snapshots)


def _pilot_publish(staging, destination):
    """Atomically rename on the same filesystem, never replacing any target entry."""
    _pilot_no_links(staging)
    _pilot_no_links(destination)
    if (
        staging.parent != destination.parent or not staging.is_dir()
        or not destination.parent.is_dir() or os.path.lexists(destination)
    ):
        raise ValueError("Publication destination is not new")
    if os.name == "nt":
        # Windows rename fails even if a competing target is an empty directory.
        staging.rename(destination)
        return

    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        arguments = (os.fsencode(staging), os.fsencode(destination), 4)  # RENAME_EXCL
    else:
        # Plain POSIX rename could overwrite a raced empty directory; fail closed
        # if this platform/filesystem lacks a no-replace rename operation.
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        arguments = (-100, os.fsencode(staging), -100, os.fsencode(destination), 1)  # RENAME_NOREPLACE
    rename.restype = ctypes.c_int
    if rename(*arguments) != 0:
        raise OSError(ctypes.get_errno(), "Atomic publication failed")


def _pilot_write(root, name, report):
    content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    content.encode("utf-8")
    with open_new_text(_pilot_child(root, name)) as handle:
        handle.write(content)


def _pilot_bundle(path):
    """Resolve one portable input bundle without echoing paths or values."""
    bundle_path = Path(path).absolute()
    _pilot_no_links(bundle_path)
    if not stat.S_ISREG(bundle_path.lstat().st_mode):
        raise ValueError("Invalid pilot bundle")
    try:
        bundle = load_comparison(bundle_path)
    except Exception:
        raise ValueError("Invalid pilot bundle") from None
    required = {
        "schema_version", "plan", "inventory", "semantics", "csv_mapping",
        "source_csv", "target_csv", "output_dir",
    }
    if not isinstance(bundle, dict) or set(bundle) != required or bundle["schema_version"] != "1.0":
        raise ValueError("Invalid pilot bundle")
    if scan_for_credentials(json.dumps(bundle, ensure_ascii=False, default=str)):
        raise ValueError("Invalid pilot bundle")

    base = bundle_path.parent
    paths = {}
    for field in required - {"schema_version"}:
        value = bundle[field]
        if (
            not isinstance(value, str) or not value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("Invalid pilot bundle")
        candidate = Path(value)
        paths[field] = candidate if candidate.is_absolute() else base / candidate
    destination = paths["output_dir"].absolute()
    _pilot_no_links(destination)
    if destination == bundle_path or destination in bundle_path.parents:
        raise ValueError("Pilot bundle overlaps output")
    return argparse.Namespace(
        plan=str(paths["plan"]),
        inventory=str(paths["inventory"]),
        semantics=str(paths["semantics"]),
        csv_mapping=str(paths["csv_mapping"]),
        source_csv=str(paths["source_csv"]),
        target_csv=str(paths["target_csv"]),
        output_dir=str(destination),
    )


def _pilot_preflight(args, output):
    # Only private snapshots are read; retain the complete detailed report.
    report_path = _pilot_child(output, "reconciliation.json")
    code = _pilot_run("migrate_bw_reconcile.py", [
        "--plan", args.plan, "--inventory", args.inventory,
        "--semantics", args.semantics, "--bex-csv-mapping", args.csv_mapping,
        "--source-csv", args.source_csv, "--target-csv", args.target_csv,
        "--output", str(report_path),
    ])
    _pilot_check_tree(output)
    if code not in (0, 1):
        raise ValueError("Invalid linked preflight")
    report = load_comparison(report_path)
    counts = _pilot_counts(report["summary"], (
        "source_rows", "target_rows", "source_distinct_keys", "target_distinct_keys",
        "missing_keys", "extra_keys", "duplicate_keys", "measures_compared",
        "measure_mismatches",
    ))
    if report["plan_linkage"]["status"] != "pass":
        raise ValueError("Preflight linkage missing")
    observation = "pass" if counts["measures_compared"] > 0 else "fail"
    if report["observation_requirement"]["status"] != observation:
        raise ValueError("Invalid observation evidence")
    if report["comparison_status"] not in ("pass", "fail"):
        raise ValueError("Invalid comparison status")
    passed = report["comparison_status"] == "pass" and observation == "pass"
    if code != (0 if passed else 1):
        raise ValueError("Inconsistent comparison evidence")
    return report, counts, code


def _pilot_assessment(inventory, semantics):
    report = assess_bex_semantics(inventory, semantics)
    if report["gate_status"] not in ("open", "candidate_for_owner_review"):
        raise ValueError("Invalid assessment status")
    return {
        "schema_version": "1.0",
        "assessment": "local_bex_semantic_capture_summary",
        "gate_status": report["gate_status"],
        "gate_closed": False,
        "evidence_boundary": "declared_local_inventory_and_bex_semantics_only",
        "summary": _pilot_counts(report["summary"], (
            "semantic_items", "consumers_linked", "consumers_captured",
            "provider_dependencies", "provider_key_figure_bindings",
            "blockers", "review_items",
        )),
        "verification": dict.fromkeys(("identity", "provenance", "equivalence"), "not_verified"),
        "runtime_evidence": dict.fromkeys((
            "sap_execution", "powerbi_execution", "fabric_execution", "refresh", "business_approval",
        ), "not_run"),
    }


def _pilot_quality(output, project):
    quality_path = _pilot_child(output, "static-quality.json")
    # Reserve a new entry before the legacy quality writer writes this owned file.
    with open_new_text(quality_path):
        pass
    code = _pilot_run("migrate.py", [
        "--validate-project", str(project), "--quality-strict",
        "--quality-output", str(quality_path),
    ])
    _pilot_check_tree(output)
    report = load_comparison(quality_path)
    counts = _pilot_counts(report["summary"], ("projects", "errors", "warnings", "files_checked"))
    status = report["status"]
    if status not in ("PASS", "WARN", "FAIL") or code not in (0, 6):
        raise ValueError("Invalid static quality evidence")
    expected = "FAIL" if counts["errors"] else "WARN" if counts["warnings"] else "PASS"
    if status != expected or code != (0 if status == "PASS" else 6):
        raise ValueError("Inconsistent static quality evidence")
    projects = report["projects"]
    if (
        counts["projects"] != 1 or set(projects) != {"."}
        or projects["."]["output_format"] != "pbip"
        or counts["files_checked"] == 0
        or report["evidence"]["static_validation"] != "completed"
    ):
        raise ValueError("Missing named project quality evidence")
    return {"status": status, "strict": True, "exit_code": code, "summary": counts}, report


def main(argv=None):
    parser = _PilotParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--bundle", help="One JSON file containing local input paths and output directory")
    for flag in ("plan", "inventory", "semantics", "csv-mapping", "source-csv", "target-csv", "output-dir"):
        parser.add_argument("--" + flag, help="Local declaration/input or new directory destination")
    args = parser.parse_args(argv)

    stage = "preflight"
    try:
        direct_fields = ("plan", "inventory", "semantics", "csv_mapping", "source_csv", "target_csv", "output_dir")
        if args.bundle is not None:
            if any(getattr(args, field) is not None for field in direct_fields):
                raise ValueError("Bundle mode cannot be combined with direct paths")
            args = _pilot_bundle(args.bundle)
        elif any(getattr(args, field) is None for field in direct_fields):
            parser.error("Supply --bundle or all seven direct input/output paths.")
        values = (args.plan, args.inventory, args.semantics, args.csv_mapping,
                  args.source_csv, args.target_csv, args.output_dir)
        if any(not value.strip() for value in values):
            raise ValueError("Empty argument")
        destination = Path(args.output_dir).absolute()
        _pilot_no_links(destination)
        if os.path.lexists(destination) or not destination.parent.is_dir():
            raise ValueError("Destination must be new with an existing parent")
        destination = destination.resolve()
        parent_identity = destination.parent.stat()
        # Both workspaces are owned and private. No subprocess sees the final path.
        # Context cleanup also removes all staged artifacts on invalid input/error.
        with tempfile.TemporaryDirectory(prefix=".bw-bex-pilot-", dir=destination.parent) as temporary:
            output = Path(temporary)
            with tempfile.TemporaryDirectory(prefix=".inputs-", dir=output) as temporary_inputs:
                snapshots = _pilot_snapshot_inputs(args, Path(temporary_inputs), destination)
                reconciliation, comparison_counts, comparison_code = _pilot_preflight(snapshots, output)
                plan = load_plan(snapshots.plan)
                inventory = load_snapshot(snapshots.inventory)
                semantics = load_bex_semantics(snapshots.semantics)
                assessment = _pilot_assessment(inventory, semantics)
                if reconciliation["plan_linkage"]["project_name"] != plan["project_name"]:
                    raise ValueError("Inconsistent project declaration")
                evidence = {"reconciliation.json": reconciliation}
                quality = {"status": "not_run", "strict": True}
                pbip = _pilot_child(output, "pbip")
                pbip.mkdir()
                project = _pilot_child(output, "pbip", plan["project_name"])
                stage = "generation"
                generation_code = _pilot_run("migrate_bw_bex_pbip.py", [
                    "--plan", snapshots.plan, "--inventory", snapshots.inventory,
                    "--semantics", snapshots.semantics, "--output-dir", str(pbip),
                ])
                _pilot_check_tree(output)
                if generation_code not in (0, 1):
                    raise ValueError("Generation orchestration failed")
                generation = {
                    "status": "pass" if generation_code == 0 else "fail",
                    "exit_code": generation_code,
                }
                linkage_path = _pilot_child(output, "pbip", "bex_linkage_assessment.json")
                if generation_code == 0 or linkage_path.exists():
                    linkage = load_comparison(linkage_path)
                    if (
                        linkage["assessment"] != "local_bw_bex_pbip_linkage"
                        or linkage["plan_linkage"] != plan["bex_linkage"]
                        or linkage["native_infocube_identity_verification"] != "not_verified"
                        or linkage["bw5_assessment"]["gate_status"] != assessment["gate_status"]
                        or _pilot_counts(linkage["bw5_assessment"]["summary"], assessment["summary"])
                        != assessment["summary"]
                    ):
                        raise ValueError("Inconsistent generation linkage evidence")
                    evidence["pbip/bex_linkage_assessment.json"] = linkage
                if generation_code == 0:
                    if not project.is_dir() or not (project / (plan["project_name"] + ".pbip")).is_file():
                        raise ValueError("Missing named project")
                    stage = "static_quality"
                    quality, quality_evidence = _pilot_quality(output, project)
                    evidence["static-quality.json"] = quality_evidence
                    result_code = 0 if quality["status"] == "PASS" and comparison_code == 0 else 1
                else:
                    # A static PBIP failure is valid diagnostic evidence, not bad input.
                    result_code = 1
                _pilot_check_tree(output)
            # Snapshots are removed before validation/publication of final evidence.
            passed = (
                result_code == 0 and assessment["gate_status"] == "candidate_for_owner_review"
                and assessment["summary"]["blockers"] == 0
                and quality.get("status") == "PASS"
                and reconciliation["comparison_status"] == "pass"
                and reconciliation["observation_requirement"]["status"] == "pass"
            )
            if result_code == 0 and not passed:
                result_code = 1
            manifest = {
                "schema_version": "1.0",
                "assessment": "local_bex_infocube_pilot",
                "workflow_status": "pass" if passed else "fail",
                "exit_code": result_code,
                "gate_closed": False,
                "project_path": (Path("pbip") / plan["project_name"]).as_posix(),
                "bex_assessment": {"gate_status": assessment["gate_status"], "summary": assessment["summary"]},
                "generation": generation,
                "static_quality": quality,
                "reconciliation": {
                    "comparison_status": reconciliation["comparison_status"],
                    "summary": comparison_counts,
                    "plan_linkage": {"status": "pass", "evidence_boundary": "declared_local_plan_inventory_and_bex_only"},
                    "observation_requirement": {"status": reconciliation["observation_requirement"]["status"]},
                },
                "partial_output": not passed,
                "failure_stage": None if passed else stage if generation["status"] != "pass" else "local_checks",
                "verification": dict.fromkeys(("identity", "provenance", "equivalence"), "not_verified"),
                "native_infocube_identity_verification": "not_verified",
                "runtime_evidence": dict.fromkeys((
                    "sap_extraction", "sap_execution", "source_query_execution", "target_query_execution",
                    "powerbi_execution", "fabric_execution", "desktop_rendering", "refresh",
                    "deployment", "business_approval", "consumer_acceptance",
                ), "not_run"),
                "declared_boundary": {
                    "local_plan_inventory_bex_linkage": "pass",
                    "local_csv_comparison": reconciliation["comparison_status"],
                    "bex_semantic_translation": "not_performed",
                    "business_acceptance": "not_run",
                },
            }
            stage = "evidence_write"
            _pilot_check_tree(output)
            _pilot_write(output, "assessment.json", assessment)
            _pilot_write(output, "pilot_report.json", manifest)
            evidence.update({"assessment.json": assessment, "pilot_report.json": manifest})
            _pilot_check_tree(output)
            for name, expected in evidence.items():
                if load_comparison(_pilot_child(output, name)) != expected:
                    raise ValueError("Changed or invalid persisted evidence")
            _pilot_check_tree(output)
            stage = "publication"
            parent_now = destination.parent.stat()
            if (parent_now.st_dev, parent_now.st_ino) != (parent_identity.st_dev, parent_identity.st_ino):
                raise ValueError("Publication parent changed")
            _pilot_publish(output, destination)
    except Exception:
        if stage == "preflight":
            print("Local BEx pilot: invalid preflight or destination; no persistent output created.", file=sys.stderr)
        else:
            print("Local BEx pilot: evidence write/orchestration failed; no pilot output published.", file=sys.stderr)
        return 2
    if result_code:
        print("Local BEx pilot: local checks failed; evidence and possible partial artifacts retained.", file=sys.stderr)
    else:
        print("Local BEx pilot: local checks pass; identity, provenance and equivalence not_verified; runtime and approval not_run.")
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
