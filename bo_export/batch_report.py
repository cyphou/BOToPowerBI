"""Batch validation and HTML report generation for BIAR migrations.

Reads batch_summary.json from a BIAR batch run and produces an HTML
report with per-artifact pass/fail status, error details, and effort estimates.
"""

import html
import json
import logging
import os

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
        issues_text = html.escape("; ".join(art["validation"].get("issues", [])))

        rows.append(f"""        <tr class="{status_class}">
            <td>{html.escape(art["name"])}</td>
            <td>{html.escape(art["type"])}</td>
            <td>{html.escape(art.get("migration_status", ""))}</td>
            <td>{status_icon}</td>
            <td>{error_text}</td>
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
