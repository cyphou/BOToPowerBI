"""Deterministic local quality reports; no Desktop or cloud execution."""

import json
from pathlib import Path

from .fabric_validator import FabricProjectValidator
from .validator import ArtifactValidator


def build_quality_report(project_dir):
    root = Path(project_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f'Project directory not found: {root}')
    projects = {}
    fabric_roots = {path.parent for path in root.rglob('fabric_project_metadata.json')}
    pbip_roots = {path.parent for path in root.rglob('*.pbip')}
    for project in sorted(fabric_roots | pbip_roots):
        if project in fabric_roots:
            result = FabricProjectValidator.validate(project)
            output_format = 'fabric'
        else:
            result = ArtifactValidator.validate_project(project)
            output_format = 'pbip'
        projects[project.relative_to(root).as_posix()] = dict(result, output_format=output_format)
    priorities = []
    for name, result in projects.items():
        owner = 'Fabric' if result['output_format'] == 'fabric' else 'Generator'
        for severity, key in [('error', 'errors'), ('warning', 'warnings')]:
            for message in sorted(set(result[key])):
                priorities.append({'project': name, 'severity': severity,
                                   'owner': owner, 'message': message})
    if not projects:
        priorities.append({'project': '.', 'severity': 'error', 'owner': 'Generator',
                           'message': 'No PBIP projects or Fabric bundles found'})
    errors = sum(item['severity'] == 'error' for item in priorities)
    warnings = sum(item['severity'] == 'warning' for item in priorities)
    return {
        'schema_version': '1.0', 'project_dir': str(root),
        'status': 'FAIL' if errors else 'WARN' if warnings else 'PASS',
        'summary': {'projects': len(projects), 'errors': errors, 'warnings': warnings,
                    'files_checked': sum(result['files_checked'] for result in projects.values())},
        'projects': projects, 'priorities': priorities,
        'evidence': {'static_validation': 'completed', 'desktop_rendering': 'not_run',
                     'data_refresh': 'not_run', 'fabric_execution': 'not_run'},
    }


def save_quality_report(report, output_path):
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return str(destination)