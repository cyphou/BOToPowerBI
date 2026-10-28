"""
Standalone Semantic Model generator for Microsoft Fabric.

Generates a Fabric SemanticModel item definition using DirectLake
mode with entity partitions referencing a Lakehouse.

Output structure:
    {model_name}.SemanticModel/
    ├── definition/
    │   ├── model.tmdl
    │   ├── database.tmdl
    │   ├── expressions.tmdl
    │   ├── relationships.tmdl
    │   ├── roles/
    │   │   └── *.tmdl
    │   └── tables/
    │       └── *.tmdl
    └── .platform
"""

import os
import json
import sys

# Import the existing tmdl_generator from the same package
from . import tmdl_generator
from .fabric_item import write_platform


class FabricSemanticModelGenerator:
    """Generate a standalone Fabric SemanticModel artifact with DirectLake mode."""

    def __init__(self, project_dir, model_name, lakehouse_name=None,
                 workspace_id=None, lakehouse_id=None):
        self.project_dir = project_dir
        self.model_name = model_name
        self.lakehouse_name = lakehouse_name or f'{model_name}_Lakehouse'
        self.workspace_id = workspace_id or '{{WORKSPACE_ID}}'
        self.lakehouse_id = lakehouse_id or '{{LAKEHOUSE_ID}}'
        self.sm_dir = os.path.join(project_dir, f'{model_name}.SemanticModel')
        os.makedirs(self.sm_dir, exist_ok=True)

    def generate(self, extracted, calendar_start=None, calendar_end=None,
                 culture=None, languages=None):
        """Generate semantic-model files from extracted BO objects.

        Delegates TMDL generation to the existing tmdl_generator, then
        wraps the output in a Fabric SemanticModel item structure with
        DirectLake metadata.

        Args:
            extracted: dict with keys like 'datasources', 'calculations',
                       'hierarchies', 'parameters', 'user_filters', etc.
            calendar_start: Start year for Calendar table (default: 2020)
            calendar_end: End year for Calendar table (default: 2030)
            culture: Override culture/locale for semantic model (e.g., fr-FR)
            languages: Comma-separated additional locales

        Returns:
            dict with generation statistics.
        """
        datasources = extracted.get('datasources', [])
        unsupported_groups = [group for group in extracted.get('groups', []) if not group.get('members')]
        extra_objects = {
            'sets': extracted.get('sets', []),
            'groups': [group for group in extracted.get('groups', []) if group.get('members')],
            'bins': extracted.get('bins', []),
            'hierarchies': extracted.get('hierarchies', []),
            'parameters': extracted.get('parameters', []),
            'user_filters': extracted.get('user_filters', []),
            'sort_orders': extracted.get('sort_orders', []),
            'aliases': extracted.get('aliases', {}),
            'data_blending': extracted.get('data_blending', []),
            '_direct_lake': {'workspace_id': self.workspace_id, 'lakehouse_id': self.lakehouse_id},
        }

        stats = tmdl_generator.generate_tmdl(
            datasources=datasources,
            report_name=self.model_name,
            extra_objects=extra_objects,
            output_dir=self.sm_dir,
            calendar_start=calendar_start,
            calendar_end=calendar_end,
            culture=culture,
            model_mode='directLake',
            languages=languages,
        )
        stats['unsupported_features'] = [
            {'kind': 'group', 'name': group.get('name', 'Unnamed'),
             'reason': 'No source members available; group was not materialized'}
            for group in unsupported_groups
        ]

        # Create .platform manifest
        self._write_platform_file()
        definition = {
            '$schema': 'https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json',
            'version': '4.2',
            'settings': {'qnaEnabled': True},
        }
        with open(os.path.join(self.sm_dir, 'definition.pbism'), 'w', encoding='utf-8') as handle:
            json.dump(definition, handle, indent=2)

        # Create item metadata with DirectLake indicator
        self._write_item_metadata(stats)

        return stats

    def _write_platform_file(self):
        """Write the .platform manifest for the SemanticModel item."""
        write_platform(self.sm_dir, 'SemanticModel', self.model_name, self.model_name)

    def _write_item_metadata(self, stats):
        """Write a metadata JSON for the semantic model."""
        # Make stats JSON-serializable (convert sets to lists)
        safe_stats = {}
        for k, v in stats.items():
            if isinstance(v, set):
                safe_stats[k] = list(v)
            elif isinstance(v, dict):
                safe_stats[k] = {
                    sk: list(sv) if isinstance(sv, set) else sv
                    for sk, sv in v.items()
                }
            else:
                safe_stats[k] = v

        meta = {
            "displayName": self.model_name,
            "type": "SemanticModel",
            "mode": "DirectLake",
            "lakehouse": self.lakehouse_name,
            "stats": safe_stats,
        }
        path = os.path.join(self.sm_dir, 'semantic_model_metadata.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
