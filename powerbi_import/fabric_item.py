"""Shared, deterministic Fabric item manifests; logical IDs are not service IDs."""

import json
import uuid
from pathlib import Path


def logical_id(project_name, item_type):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'bo-to-powerbi/{project_name}/{item_type}'))


def write_platform(directory, item_type, display_name, project_name):
    document = {
        '$schema': 'https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json',
        'metadata': {'type': item_type, 'displayName': display_name},
        'config': {'version': '2.0', 'logicalId': logical_id(project_name, item_type)},
    }
    destination = Path(directory) / '.platform'
    destination.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')