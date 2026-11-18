"""Batch validation and HTML report generation for BIAR migrations.

Reads batch_summary.json from a BIAR batch run and produces an HTML
report with per-artifact pass/fail status, error details, and effort estimates.
"""

import html
import json
import logging
import os
from urllib.parse import quote

logger = logging.getLogger(__name__)


def validate_batch_output(output_dir: str) -> dict:
    """Validate all artifacts in a batch output directory.

    Checks each artifact sub-directory for expected output files and
    produces a per-artifact validation result.

    Args:
        output_dir: Root batch output directory containing artifact sub-dirs.

    Returns:
        dict with 'total', 'passed', 'failed', 'artifacts' keys.
    """
    summary_path = os.path.join(output_dir, "batch_summary.json")
    if os.path.isfile(summary_path):
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        artifacts = summary.get("artifacts", [])
    else:
        # No summary — scan sub-dirs
        artifacts = []
        for entry in sorted(os.listdir(output_dir)):
            entry_path = os.path.join(output_dir, entry)
            if os.path.isdir(entry_path) and entry != "__pycache__":
                artifacts.append({
                    "name": entry,
                    "type": "unknown",
                    "status": "pending",
                    "error": None,
                    "output_dir": entry_path,
                })

    results = []
    for art in artifacts:
        art_dir = art.get("output_dir", os.path.join(output_dir, art["name"]))
        validation = _validate_artifact(art_dir)
        results.append({
            "name": art.get("name", "unknown"),
            "type": art.get("type", "unknown"),
            "migration_status": art.get("status", "unknown"),
            "migration_error": art.get("error"),
            "migration_warnings": art.get("warnings", []),
            "validation": validation,
        })

    passed = sum(1 for r in results if r["validation"]["valid"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "artifacts": results,
    }


def _validate_artifact(artifact_dir: str) -> dict:
    """Validate a single artifact's output directory.

    Checks for:
    - Extracted JSON files present
    - converted_objects.json or .pbip structure present
    - No empty output files
    """
    if not os.path.isdir(artifact_dir):
        return {"valid": False, "issues": ["Output directory not found"]}

    issues = []
    expected_jsons = [
        "reports.json", "queries.json", "datasources.json",
        "formulas.json", "tables.json", "columns.json",
    ]

    has_extraction = False
    for jf in expected_jsons:
        path = os.path.join(artifact_dir, jf)
        if os.path.isfile(path):
            has_extraction = True
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) == 0:
                    issues.append(f"{jf}: empty")
            except json.JSONDecodeError:
                issues.append(f"{jf}: invalid JSON")

    if not has_extraction:
        issues.append("No extraction JSON files found")

    # Check for generation output
    has_pbip = any(
        f.endswith(".pbip") for f in os.listdir(artifact_dir)
    ) if os.path.isdir(artifact_dir) else False
    has_converted = os.path.isfile(
        os.path.join(artifact_dir, "converted_objects.json"))

    if not has_pbip and not has_converted:
        issues.append("No .pbip or converted_objects.json found")

    return {
        "valid": len(issues) == 0,
        "has_extraction": has_extraction,
        "has_generation": has_pbip or has_converted,
        "issues": issues,
    }


def generate_batch_report(validation_result: dict, output_path: str) -> str:
    """Generate an HTML batch validation report.

    Args:
        validation_result: Output from validate_batch_output().
        output_path: Path to write the HTML report.

    Returns:
        Path to the generated HTML report.
    """
    total = validation_result["total"]
    passed = validation_result["passed"]
    failed = validation_result["failed"]
    success_rate = (passed / total * 100) if total > 0 else 0

    rows = []
    for art in validation_result["artifacts"]:
        status_class = "pass" if art["validation"]["valid"] else "fail"
        status_icon = "&#10004;" if art["validation"]["valid"] else "&#10008;"
        error_text = html.escape(art.get("migration_error") or "")
        warnings_text = html.escape("; ".join(str(w) for w in art.get("migration_warnings", [])))
        issues_text = html.escape("; ".join(art["validation"].get("issues", [])))

        rows.append(f"""        <tr class="{status_class}">
            <td>{html.escape(art["name"])}</td>
            <td>{html.escape(art["type"])}</td>
            <td>{html.escape(art.get("migration_status", ""))}</td>
            <td>{status_icon}</td>
            <td>{error_text}</td>
            <td>{warnings_text}</td>
            <td>{issues_text}</td>
        </tr>""")

    rows_html = "\n".join(rows)

    report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>BIAR Batch Migration Report</title>
<style>
    body {{ font-family: 'Segoe UI', sans-serif; margin: 20px; background: #f5f5f5; }}
    h1 {{ color: #0078d4; }}
    .summary {{ display: flex; gap: 20px; margin-bottom: 20px; }}
    .card {{ background: #fff; padding: 16px 24px; border-radius: 8px;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
    .card .number {{ font-size: 2em; font-weight: bold; }}
    .card.success .number {{ color: #107c10; }}
    .card.fail .number {{ color: #d13438; }}
    .card.total .number {{ color: #0078d4; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff;
             border-radius: 8px; overflow: hidden;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    th {{ background: #0078d4; color: white; padding: 10px; text-align: left; }}
    td {{ padding: 8px 10px; border-bottom: 1px solid #eee; }}
    tr.pass td:nth-child(4) {{ color: #107c10; font-weight: bold; }}
    tr.fail td:nth-child(4) {{ color: #d13438; font-weight: bold; }}
    tr:hover {{ background: #f0f7ff; }}
</style>
</head>
<body>
<h1>BIAR Batch Migration Report</h1>
<div class="summary">
    <div class="card total"><div class="number">{total}</div>Total Artifacts</div>
    <div class="card success"><div class="number">{passed}</div>Passed</div>
    <div class="card fail"><div class="number">{failed}</div>Failed</div>
    <div class="card"><div class="number">{success_rate:.0f}%</div>Success Rate</div>
</div>
<table>
    <thead>
        <tr>
            <th>Artifact</th>
            <th>Type</th>
            <th>Migration</th>
            <th>Valid</th>
            <th>Error</th>
            <th>Warnings</th>
            <th>Issues</th>
        </tr>
    </thead>
    <tbody>
{rows_html}
    </tbody>
</table>
</body>
</html>"""

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_html)

    logger.info("Batch report written to %s", output_path)
    return output_path


def generate_migration_batch_report(output_dir: str, output_path: str | None = None) -> str:
    """Render a batch manifest as a consolidated, local migration report."""
    manifest_path = os.path.join(output_dir, "batch_manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), list):
        raise ValueError("Batch manifest must contain an artifacts array")
    skipped = manifest.get("skipped", [])
    if not isinstance(skipped, list):
        raise ValueError("Batch manifest skipped value must be an array")
    artifacts = manifest["artifacts"]
    if any(not isinstance(artifact, dict) for artifact in artifacts):
        raise ValueError("Batch manifest artifacts must be objects")
    if any(not isinstance(item, dict) for item in skipped):
        raise ValueError("Batch manifest skipped entries must be objects")
    for artifact in artifacts:
        warnings = artifact.get("warnings", [])
        if not isinstance(warnings, list):
            raise ValueError("Batch manifest artifact warnings must be an array")

    root = os.path.realpath(output_dir)
    if output_path is not None:
        report_path = os.fspath(output_path)
        if not isinstance(report_path, str) or not report_path:
            raise ValueError("Report output path must be a non-empty text path")
    else:
        report_path = os.path.join(output_dir, "batch_report.html")
    report_dir = os.path.realpath(os.path.dirname(os.path.abspath(report_path)) or ".")

    def get_target(artifact: dict, name: str) -> dict:
        targets = artifact.get("targets")
        if isinstance(targets, dict) and isinstance(targets.get(name), dict):
            return targets[name]
        return {}

    target_names = ("powerbi", "paginated")
    target_counts = {
        name: {
            "success": sum(
                get_target(artifact, name).get("status") == "success"
                for artifact in artifacts
            ),
            "failed": sum(
                get_target(artifact, name).get("status") == "failed"
                for artifact in artifacts
            ),
        }
        for name in target_names
    }

    def safe_links(target_name: str, target: dict) -> str:
        target_dir = target.get("output_dir")
        if not isinstance(target_dir, str) or not target_dir:
            return ""
        try:
            if not os.path.isabs(target_dir):
                target_dir = os.path.join(root, target_dir)
            target_real = os.path.realpath(target_dir)
            if os.path.normcase(os.path.commonpath([root, target_real])) != os.path.normcase(root):
                return ""
        except (OSError, ValueError):
            return ""
        if not os.path.isdir(target_real):
            return ""

        wanted = {"PBIP", "Comparison", "Quality JSON"} if target_name == "powerbi" else {
            "RDL", "Power Query M"
        }
        found = {}
        for current, dirs, files in os.walk(target_real, followlinks=False):
            dirs[:] = [
                directory for directory in sorted(dirs)
                if not os.path.islink(os.path.join(current, directory))
            ]
            for filename in sorted(files):
                lowered = filename.lower()
                if target_name == "powerbi":
                    label = (
                        "PBIP" if lowered.endswith(".pbip") else
                        "Comparison" if lowered == "comparison_report.html" else
                        "Quality JSON" if lowered == "quality_report.json" else None
                    )
                else:
                    label = (
                        "RDL" if lowered == "report.rdl" else
                        "Power Query M" if lowered == "query.m" else None
                    )
                if label and label not in found:
                    candidate = os.path.join(current, filename)
                    try:
                        candidate_real = os.path.realpath(candidate)
                        if (os.path.normcase(os.path.commonpath([root, candidate_real]))
                                == os.path.normcase(root) and os.path.isfile(candidate_real)):
                            found[label] = candidate_real
                    except (OSError, ValueError):
                        continue
            if len(found) == len(wanted):
                break

        links = []
        for label in ("PBIP", "RDL", "Power Query M", "Comparison", "Quality JSON"):
            path = found.get(label)
            if path:
                try:
                    relative = os.path.relpath(path, report_dir).replace(os.sep, "/")
                except ValueError:
                    continue
                links.append(
                    f'<a href="{html.escape(quote(relative, safe="/"), quote=True)}">'
                    f"{html.escape(label)}</a>"
                )
        return " · ".join(links)

    def render_target(artifact: dict, name: str) -> str:
        targets = artifact.get("targets")
        target = targets.get(name) if isinstance(targets, dict) else None
        if not isinstance(target, dict):
            status = "Not requested" if isinstance(targets, dict) and name not in targets else "Unknown"
            status_class = "not-requested" if status == "Not requested" else "unknown"
            return f'<span class="status {status_class}">{status}</span>'
        status_value = target.get("status", "unknown")
        status = str(status_value)
        status_class = (
            status_value
            if isinstance(status_value, str) and status_value in {"success", "failed"}
            else "unknown"
        )
        parts = [
            f'<span class="status {status_class}">{html.escape(status)}</span>',
            safe_links(name, target),
        ]
        if target.get("error"):
            parts.append(
                f'<details><summary>Error details</summary>'
                f'<pre>{html.escape(str(target["error"]))}</pre></details>'
            )
        return "<br>".join(part for part in parts if part)

    rows = []
    for artifact in artifacts:
        source = html.escape(str(artifact.get("source", "unknown")), quote=True)
        source_kind = html.escape(str(artifact.get("source_kind", "unknown")), quote=True)
        warnings = artifact.get("warnings", [])
        warning_details = ""
        if warnings:
            warning_details = (
                "<details><summary>Warnings</summary><ul>"
                + "".join(f"<li>{html.escape(str(warning), quote=True)}</li>" for warning in warnings)
                + "</ul></details>"
            )
        artifact_status_value = artifact.get("status", "unknown")
        artifact_status = str(artifact_status_value)
        artifact_status_class = (
            artifact_status
            if isinstance(artifact_status_value, str) and artifact_status_value in {"success", "failed"}
            else "unknown"
        )
        artifact_error = artifact.get("error")
        error_details = (
            f'<details><summary>Error details</summary>'
            f'<pre>{html.escape(str(artifact_error), quote=True)}</pre></details>'
            if artifact_error else ""
        )
        rows.append(
            "<tr>"
            f"<td>{source}</td><td>{source_kind}</td>"
            f'<td><span class="status {artifact_status_class}">{html.escape(artifact_status)}</span>'
            f"{error_details}</td>"
            f"<td>{render_target(artifact, 'powerbi')}</td>"
            f"<td>{render_target(artifact, 'paginated')}</td>"
            f"<td>{warning_details}</td>"
            "</tr>"
        )

    skipped_rows = []
    for item in skipped:
        skipped_rows.append(
            "<tr>"
            f'<td>{html.escape(str(item.get("source", "unknown")), quote=True)}</td>'
            f'<td>{html.escape(str(item.get("reason", "Not migrated")), quote=True)}</td>'
            "</tr>"
        )

    report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BusinessObjects Batch Migration Report</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 0; background: #f5f7fa; color: #242424; }}
main {{ max-width: 1440px; margin: auto; padding: 28px; }}
h1 {{ color: #004578; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 20px 0; }}
.card {{ background: white; border-radius: 8px; padding: 16px 20px; min-width: 150px;
         box-shadow: 0 1px 4px #0002; }}
.card strong {{ display: block; font-size: 1.6em; }}
.table-wrap {{ overflow-x: auto; margin: 12px 0 28px; }}
table {{ width: 100%; min-width: 760px; border-collapse: collapse; background: white; }}
th, td {{ text-align: left; vertical-align: top; border-bottom: 1px solid #e5e5e5; padding: 10px;
          overflow-wrap: anywhere; }}
th {{ background: #0078d4; color: white; }}
.status {{ display: inline-block; border-radius: 4px; padding: 2px 7px; font-weight: 600; }}
.success {{ color: #0b5a08; background: #dff6dd; }}
.failed {{ color: #8a1c22; background: #fde7e9; }}
.unknown, .not-requested {{ color: #605e5c; background: #edebe9; }}
a {{ color: #005a9e; }}
a:focus-visible {{ outline: 3px solid #004578; outline-offset: 2px; }}
details {{ margin-top: 6px; }}
pre {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
.notice {{ background: #fff4ce; padding: 14px; border-left: 4px solid #ca5010; }}
.visually-hidden {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
                   overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }}
@media (max-width: 760px) {{ main {{ padding: 14px; }} table {{ font-size: .88em; }} }}
</style>
</head>
<body><main>
<h1>BusinessObjects Batch Migration Report</h1>
<p>Local generation summary for {len(artifacts)} source artifact(s); {len(skipped)} item(s) skipped.</p>
<div class="cards">
<div class="card"><strong>{len(artifacts)}</strong>Sources</div>
<div class="card"><strong>{target_counts["powerbi"]["success"]} / {target_counts["powerbi"]["failed"]}</strong>Power BI / Fabric success / failed</div>
<div class="card"><strong>{target_counts["paginated"]["success"]} / {target_counts["paginated"]["failed"]}</strong>Paginated success / failed</div>
<div class="card"><strong>{len(skipped)}</strong>Skipped</div>
</div>
<h2>Per-source targets</h2>
<div class="table-wrap">
<table>
<caption class="visually-hidden">Migration status and available artifacts for each source</caption>
<thead><tr><th scope="col">Source</th><th scope="col">Type</th>
<th scope="col">Overall status / error</th><th scope="col">Power BI / Fabric</th>
<th scope="col">Paginated</th><th scope="col">Warnings</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="6">No source artifacts</td></tr>'}</tbody></table>
</div>
<h2>Skipped inputs</h2>
<div class="table-wrap">
<table><caption class="visually-hidden">Inputs skipped during batch migration</caption>
<thead><tr><th scope="col">Path</th><th scope="col">Reason</th></tr></thead>
<tbody>{"".join(skipped_rows) or '<tr><td colspan="2">None</td></tr>'}</tbody></table>
</div>
<div class="notice"><strong>Evidence boundary:</strong> this report summarizes local generation and linked files only.
It does not prove that PBIP opens in Desktop, RDL renders in Report Builder, data refreshes, runtime execution,
or source/target semantic or visual equivalence. Those checks remain separate.</div>
</main></body></html>"""

    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(report_html)
    logger.info("Migration batch report written to %s", report_path)
    return report_path
