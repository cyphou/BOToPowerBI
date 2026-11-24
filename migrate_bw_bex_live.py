"""Fetch one BO BW outline and generate an independently declared PBIP review draft.

Use a trusted output parent, inaccessible to untrusted writers. The output must
not exist. BO_LOGON_TOKEN is an externally owned preauthenticated token; this
command does not log it off. A successful exit means only that local generation
and static checks completed, not that the BEx query was migrated or verified.
Only unlinked plans are accepted; linked plans need the separate BW-5 workflow.
"""

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from bo_export.server_client import BOServerClient, _bw_node_xml, _webi_path_segment
from migrate_bw_bex_pbip import validate_plan


class _LiveParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "BEx live draft: invalid arguments; use --help.\n")


def _live_no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError("Linked path")


def _live_snapshot_plan(path, destination, token):
    path = Path(path).absolute()
    _live_no_links(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or path.resolve().is_relative_to(destination):
        raise ValueError("Invalid plan path")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        opened = os.fstat(source.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("Plan changed")
        data = source.read(4 * 1024 * 1024 + 1)
        after = os.fstat(source.fileno())
        if len(data) > 4 * 1024 * 1024 or len(data) != opened.st_size or (
            opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns
        ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Plan changed or too large")
    _live_no_links(path)
    value = json.loads(data.decode("utf-8"))
    # Check every decoded string, including keys: JSON may escape token characters.
    pending = [value]
    contains_token = token.encode("utf-8") in data
    while pending and not contains_token:
        item = pending.pop()
        if isinstance(item, str):
            contains_token = token in item
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    if contains_token:
        raise ValueError("Token occurs in plan")
    plan = validate_plan(value)
    if "bex_linkage" in plan:
        raise ValueError("Linked plans require the separate BW-5 workflow")
    return data, plan


def _live_outline_counts(outline):
    # Literal XML item/type counts only, not inferred semantic classifications.
    # Unknown type strings are never persisted: they are untrusted metadata.
    categories = ("Measure", "Dimension", "Characteristic", "Hierarchy", "Level", "Variable", "Filter", "Attribute", "KeyFigure")
    counts = dict.fromkeys(categories, 0)
    counts["other_or_missing"] = 0
    for item in outline.iter("item"):
        kind = item.get("type")
        counts[kind if kind in categories else "other_or_missing"] += 1
    return counts


def _live_check_tree(root):
    _live_no_links(root)
    for item in root.rglob("*"):
        _live_no_links(item)
        info = item.lstat()
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError("Unexpected output entry")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("Hard-linked output")


def _live_publish(stage, destination):
    _live_no_links(stage)
    _live_no_links(destination)
    if os.path.lexists(destination):
        raise ValueError("Destination exists")
    if os.name == "nt":
        os.rename(stage, destination)
        return
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        arguments = (os.fsencode(stage), os.fsencode(destination), 4)
    else:
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        arguments = (-100, os.fsencode(stage), -100, os.fsencode(destination), 1)
    rename.restype = ctypes.c_int
    if rename(*arguments) != 0:
        raise OSError(ctypes.get_errno(), "Publication failed")


@contextmanager
def _live_staging(parent, state):
    state["staging"] = "creation_attempted_outcome_unknown"
    temporary = tempfile.TemporaryDirectory(prefix=".bex-live-", dir=parent)
    state["staging"] = "created"
    try:
        yield temporary.name
    finally:
        state["cleanup"] = "attempted"
        try:
            temporary.cleanup()
        except Exception:
            state["cleanup"] = "failed"
            state["phase"] = "cleanup"
            raise
        else:
            state["cleanup"] = "completed"


def main(argv=None):
    parser = _LiveParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--server-url", required=True, help="HTTPS BO server base URL")
    parser.add_argument("--connection-id", required=True, help="BO BW connection ID")
    parser.add_argument("--bex-id", required=True, help="Exact BEx outline ID")
    parser.add_argument("--plan", required=True, help="Reviewed, unlinked local BW PBIP plan")
    parser.add_argument("--output-dir", required=True, help="New directory under a trusted existing parent")
    args = parser.parse_args(argv)
    state = {"phase": "preflight", "staging": "not_created", "cleanup": "not_attempted",
             "publication": "not_attempted"}
    try:
        token = os.environ.get("BO_LOGON_TOKEN", "")
        if not token or not token.strip():
            raise ValueError("Missing token")
        url = urlsplit(args.server_url)
        if (url.scheme.lower() != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment):
            raise ValueError("HTTPS without userinfo is required")
        url.port
        if any(token in value for value in (args.server_url, args.connection_id, args.bex_id, args.plan, args.output_dir)):
            raise ValueError("Token present in an argument")
        _webi_path_segment(args.connection_id, "BW connection ID")
        _bw_node_xml("id", args.bex_id)
        destination = Path(args.output_dir).absolute()
        _live_no_links(destination)
        if os.path.lexists(destination) or not destination.parent.is_dir():
            raise ValueError("Output must be new with an existing parent")
        destination = destination.resolve()
        parent_info = destination.parent.stat()
        plan_bytes, plan = _live_snapshot_plan(args.plan, destination, token)

        state["phase"] = "metadata"
        client = BOServerClient(args.server_url, token=token)
        client.logon()
        client.get_bw_connection(args.connection_id)
        outline = client.get_bw_query_outline(args.connection_id, args.bex_id)
        counts = _live_outline_counts(outline)

        state["phase"] = "generation"
        with _live_staging(destination.parent, state) as temp:
            root = Path(temp)
            snapshot = root / "plan.json"
            snapshot.write_bytes(plan_bytes)
            output = root / "output"
            output.mkdir()
            pbip = output / "pbip"
            env = os.environ.copy()
            env.pop("BO_LOGON_TOKEN", None)
            code = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().with_name("migrate_bw_bex_pbip.py")),
                 "--plan", str(snapshot), "--output-dir", str(pbip)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env, check=False,
            ).returncode
            _live_check_tree(output)
            project = pbip / plan["project_name"]
            if code == 0 and not (project / (plan["project_name"] + ".pbip")).is_file():
                raise ValueError("Missing generated project")
            report = {
                "schema_version": "1.0",
                "workflow_status": "partial_needs_review",
                "metadata": {
                    "connection_fetch": "completed", "outline_fetch": "completed",
                    "counts_scope": "literal unnamespaced item elements by exact type attribute; other types grouped; completeness unknown",
                    "outline_item_counts": counts,
                },
                "generation": {"exit_code": code, "status": "completed" if code == 0 else "failed_or_incomplete", "partial_artifacts_may_exist": code != 0},
                "static_validation": "pass" if code == 0 else "fail" if code == 1 else "unknown",
                "static_validation_scope": "generator non-strict check; warnings and details are not captured",
                "linkage": "not_proven; the plan and outline are independent",
                "verification": dict.fromkeys(("native_query_identity", "provider_identity", "cube_identity", "selector_correspondence", "bex_semantics", "equivalence"), "not_verified"),
                "not_converted": ["outline items into plan selectors or types", "BEx formulas and calculations", "variables and prompts", "filters", "hierarchies", "exception aggregation", "units and currencies", "authorization semantics", "source report layout"],
                "runtime_evidence": dict.fromkeys(("source_data_execution", "target_data_execution", "desktop_rendering", "refresh", "deployment", "business_approval"), "not_run"),
                "limitations": ["Outline counts do not establish completeness or semantic correspondence.", "The PBIP is a manually declared cube draft, not a migrated or verified BEx query.", "No source XML, connection details, query identifiers or captions are retained in this report."],
            }
            with (output / "migration_report.json").open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            _live_check_tree(output)
            current = destination.parent.stat()
            if (current.st_dev, current.st_ino) != (parent_info.st_dev, parent_info.st_ino):
                raise ValueError("Output parent changed")
            state["phase"] = "publication"
            state["publication"] = "attempted_outcome_unknown"
            _live_publish(output, destination)
            state["publication"] = "completed"
    except Exception as error:
        category = ("validation" if isinstance(error, ValueError) else
                    "subprocess" if isinstance(error, subprocess.SubprocessError) else
                    "io" if isinstance(error, OSError) else "unexpected")
        publication = ("publication completed" if state["publication"] == "completed" else
                       "before publication confirmation; publication outcome unknown"
                       if state["publication"] == "attempted_outcome_unknown" else
                       "before publication; publication not attempted")
        print(f"BEx live draft: operation failed; phase={state['phase']}; category={category}; "
              f"staging={state['staging']}; cleanup={state['cleanup']}; {publication}.", file=sys.stderr)
        return 2
    if code != 0:
        print("BEx live draft: generation incomplete; report and possible partial artifacts retained.", file=sys.stderr)
        return 1
    print("BEx live draft generated and statically checked; linkage and migration remain unverified and require review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
