"""Browse one BO BW connection for a bounded cube inventory and generate a PBIP draft."""

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from bo_export.server_client import BOServerClient
from migrate_bw_bex_pbip import validate_plan


class _CubeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "BW cube live draft: invalid arguments; use --help.\n")


def _no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError("Linked path")


def _snapshot_plan(path, destination, token):
    path = Path(path).absolute()
    _no_links(path)
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
    _no_links(path)
    value = json.loads(data.decode("utf-8"))
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
        raise ValueError("Linked plans require the independent unlinked plan")
    return data, plan


def _node_counts(root):
    counts = dict.fromkeys(("Cube", "InfoCube", "Query", "Dimension", "Measure"), 0)
    counts["other_or_missing"] = 0
    for element in root.iter():
        if element.tag != "bwnode":
            continue
        kind = element.get("type")
        counts[kind if kind in counts and kind != "other_or_missing" else "other_or_missing"] += 1
    return counts


def _check_tree(root):
    _no_links(root)
    for item in root.rglob("*"):
        _no_links(item)
        info = item.lstat()
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError("Unexpected output entry")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("Hard-linked output")


def _publish(stage, destination):
    _no_links(stage)
    _no_links(destination)
    if os.path.lexists(destination):
        raise ValueError("Destination exists")
    os.rename(stage, destination)


@contextmanager
def _staging(parent, state):
    state["staging"] = "creation_attempted_outcome_unknown"
    temporary = tempfile.TemporaryDirectory(prefix=".bw-cube-live-", dir=parent)
    state["staging"] = "created"
    try:
        yield temporary.name
    finally:
        state["cleanup"] = "attempted"
        temporary.cleanup()
        state["cleanup"] = "completed"


def _report(counts, code):
    return {
        "schema_version": "1.0",
        "workflow_status": "partial_needs_review",
        "metadata": {
            "connection_fetch": "completed",
            "navigation_fetch": "completed",
            "counts_scope": "literal bwnode elements by exact type attribute; other types grouped; completeness unknown",
            "bwnode_counts": counts,
        },
        "generation": {
            "exit_code": code,
            "status": "completed" if code == 0 else "failed_or_incomplete",
            "partial_artifacts_may_exist": code != 0,
        },
        "verification": dict.fromkeys(
            ("cube_identity", "provider_identity", "plan_correspondence", "semantic_conversion", "equivalence"),
            "not_verified",
        ),
        "not_converted": [
            "dimensions", "measures", "types", "aggregation", "formulas", "security", "report layout",
        ],
        "runtime_evidence": dict.fromkeys(
            ("source_data_execution", "target_data_execution", "Desktop", "refresh", "deployment", "approval"),
            "not_run",
        ),
        "limitations": [
            "The response is an observed cube/navigation node inventory only.",
            "This is not physical cube data extraction and does not establish native cube identity.",
            "No source XML, names, IDs or captions are retained in this report.",
        ],
    }


def main(argv=None):
    parser = _CubeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--connection-id", required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--path")
    selector.add_argument("--pattern")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    state = {"phase": "preflight", "staging": "not_created", "cleanup": "not_attempted", "publication": "not_attempted"}
    try:
        token = os.environ.get("BO_LOGON_TOKEN", "")
        if not token or not token.strip():
            raise ValueError("Missing token")
        url = urlsplit(args.server_url)
        if (url.scheme.lower() != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment):
            raise ValueError("HTTPS without userinfo is required")
        url.port
        if any(token in value for value in (args.server_url, args.connection_id, args.path or args.pattern, args.plan, args.output_dir)):
            raise ValueError("Token present in an argument")
        destination = Path(args.output_dir).absolute()
        _no_links(destination)
        if os.path.lexists(destination) or not destination.parent.is_dir():
            raise ValueError("Output must be new with an existing parent")
        destination = destination.resolve()
        parent_info = destination.parent.stat()
        plan_bytes, plan = _snapshot_plan(args.plan, destination, token)

        state["phase"] = "metadata"
        client = BOServerClient(args.server_url, token=token)
        client.logon()
        client.get_bw_connection(args.connection_id)
        navigation = client.browse_bw_connection(args.connection_id, **({"path": args.path} if args.path is not None else {"pattern": args.pattern}))
        counts = _node_counts(navigation)

        state["phase"] = "generation"
        with _staging(destination.parent, state) as temp:
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
            _check_tree(output)
            if code == 0 and not (pbip / plan["project_name"] / (plan["project_name"] + ".pbip")).is_file():
                raise ValueError("Missing generated project")
            with (output / "migration_report.json").open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(_report(counts, code), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            _check_tree(output)
            current = destination.parent.stat()
            if (current.st_dev, current.st_ino) != (parent_info.st_dev, parent_info.st_ino):
                raise ValueError("Output parent changed")
            state["phase"] = "publication"
            state["publication"] = "attempted_outcome_unknown"
            _publish(output, destination)
            state["publication"] = "completed"
    except Exception:
        print(f"BW cube live draft: operation failed; phase={state['phase']}; "
              f"staging={state['staging']}; cleanup={state['cleanup']}; "
              f"publication={state['publication']}.", file=sys.stderr)
        return 2
    if code != 0:
        print("BW cube live draft: generation incomplete; report and possible partial artifacts retained.", file=sys.stderr)
        return 1
    print("BW cube live draft generated; cube identity, conversion and equivalence remain unverified and require review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())