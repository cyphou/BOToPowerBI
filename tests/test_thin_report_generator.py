"""Binding validation contracts for local thin-report references."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from powerbi_import.thin_report_generator import (
    ThinReportGenerator,
    generate_thin_report_validation,
    validate_cross_report_navigation,
    validate_drillthrough_targets,
    validate_field_references,
    validate_filter_references,
    validate_parameter_references,
)


class TestThinReportBindingValidation(unittest.TestCase):
    def setUp(self):
        self.model = {
            'tables': [
                {'name': 'Orders', 'columns': [
                    {'name': 'Order Amount'}, {'name': 'Région'},
                ], 'measures': [{'name': 'Net Sales'}]},
                {'name': 'View as Parameter', 'is_parameter': True,
                 'columns': [{'name': 'Value'}]},
                {'name': 'Calendar', 'columns': [{'name': 'Date'}]},
            ],
        }

    def test_field_validation_resolves_qualified_fields_and_suggests_near_matches(self):
        visuals = [{
            'visual_id': 'visual-1',
            'page': 'Résumé',
            'fields': [
                "'Orders'[Order Amount]",
                {'table': 'Orders', 'column': 'Order Am'},
                {'table': 'Order', 'column': 'Région'},
            ],
        }]

        findings = validate_field_references(visuals, self.model)

        self.assertEqual([finding['status'] for finding in findings], [
            'resolved', 'unresolved_field', 'unresolved_table',
        ])
        self.assertEqual(findings[1]['suggestion'], 'Order Amount')
        self.assertEqual(findings[2]['suggestion'], 'Orders')
        self.assertEqual(findings[0]['page'], 'Résumé')

    def test_filter_validation_checks_table_scope_and_returns_field_suggestions(self):
        filters = [
            {'table': 'Orders', 'column': 'Région'},
            {'table': 'Calendar', 'field': 'Order Am'},
            {'field': 'Missing'},
        ]

        findings = validate_filter_references(filters, self.model)

        self.assertEqual([finding['status'] for finding in findings], [
            'resolved', 'unresolved_field', 'unresolved_field',
        ])
        self.assertEqual(findings[1]['suggestion'], 'Order Amount')
        self.assertEqual(findings[2]['filter_field'], 'Missing')

    def test_drillthrough_targets_resolve_local_and_bundle_pages_only(self):
        pages = [
            {'name': 'Overview', 'drillthrough_target': 'Detail'},
            {'name': 'Detail', 'page_type': 'drillthrough'},
            {'name': 'Orders', 'drillthrough_target': 'Customer Detail'},
        ]
        bundle_pages = [[{'name': 'Customer Detail'}]]

        findings = validate_drillthrough_targets(pages, bundle_pages)

        self.assertEqual(findings, [
            {'source_page': 'Overview', 'target_page': 'Detail', 'status': 'found'},
            {'source_page': 'Orders', 'target_page': 'Customer Detail', 'status': 'found'},
        ])
        missing = validate_drillthrough_targets(
            [{'name': 'Overview', 'drillthrough_target': 'Absent'}])
        self.assertEqual(missing[0]['status'], 'missing')

    def test_parameter_validation_recognizes_parameter_tables_and_suggests_names(self):
        findings = validate_parameter_references(
            ['View as Parameter', 'View as Param', 'Missing'], self.model)

        self.assertEqual([finding['status'] for finding in findings], [
            'resolved', 'unresolved', 'unresolved',
        ])
        self.assertEqual(findings[1]['suggestion'], 'View as Parameter')
        self.assertEqual(findings[2]['suggestion'], '')

    def test_cross_report_navigation_ignores_non_navigation_actions(self):
        actions = [
            {'name': 'to-sales', 'type': 'navigate', 'target_report': 'Sales'},
            {'name': 'to-missing', 'type': 'navigate_to_report', 'target_report': 'Absent'},
            {'name': 'open-help', 'type': 'open_url', 'target_report': 'Help'},
            {'name': 'empty', 'type': 'navigation', 'target_report': ''},
        ]

        findings = validate_cross_report_navigation(actions, ['Sales', 'Finance'])

        self.assertEqual(findings, [
            {'action': 'to-sales', 'target_report': 'Sales', 'status': 'found'},
            {'action': 'to-missing', 'target_report': 'Absent', 'status': 'missing'},
        ])

    def test_validation_summary_aggregates_field_filter_drillthrough_parameter_and_navigation_gaps(self):
        report = {
            'visuals': [{'visual_id': 'v1', 'fields': [
                {'table': 'Orders', 'column': 'Order Amount'},
                {'table': 'Orders', 'column': 'Absent'},
            ]}],
            'pages': [
                {'name': 'Overview', 'drillthrough_target': 'Detail'},
                {'name': 'Detail'},
            ],
            'filters': [{'table': 'Orders', 'column': 'Absent'}],
            'slicer_params': ['View as Parameter', 'Missing Parameter'],
            'actions': [{'name': 'jump', 'type': 'navigate', 'target_report': 'Missing Report'}],
        }

        summary = generate_thin_report_validation(
            report, self.model,
            bundle_reports=[[{'name': 'Detail'}]],
            bundle_report_names=['Current Report'],
        )

        self.assertEqual(summary['total_fields_checked'], 2)
        self.assertEqual(summary['resolved_fields'], 1)
        self.assertEqual(summary['unresolved_fields'], 1)
        self.assertEqual(summary['drillthrough_gaps'], 0)
        self.assertEqual(summary['filter_gaps'], 1)
        self.assertEqual(summary['navigation_gaps'], 1)
        self.assertEqual(summary['parameter_results'][0]['status'], 'resolved')
        self.assertEqual(summary['parameter_results'][1]['status'], 'unresolved')


class TestThinReportGenerationContracts(unittest.TestCase):
    def test_remap_fields_updates_exact_references_only_and_preserves_input(self):
        source = {
            'worksheets': [{
                'columns': [{'name': 'Margin'}, {'name': 'Margin (West)'}, {'name': 'margin'}],
                'filters': [{'field': 'Margin'}],
                'mark_encoding': {
                    'color': {'field': 'Margin'},
                    'detail': [{'field': 'Région'}, {'field': 'Region'}],
                },
                'sort_fields': [{'field': 'Région'}],
            }],
            'calculations': [{'caption': 'Margin', 'formula': '[Amount] * 2'}],
            'filters': [{'field': 'Région'}],
            'actions': [{'source_field': 'Margin', 'target_field': 'Région', 'field': 'Region'}],
            'dashboards': [{'zones': [{'field': 'Margin'}]}],
        }
        original = copy.deepcopy(source)
        generator = ThinReportGenerator('Shared', '.')

        remapped = generator._remap_fields(source, {
            'Margin': 'Margin (West)', 'Région': 'Région (Nord)',
        })

        self.assertEqual(source, original)
        self.assertIsNot(remapped, source)
        worksheet = remapped['worksheets'][0]
        self.assertEqual([col['name'] for col in worksheet['columns']],
                         ['Margin (West)', 'Margin (West)', 'margin'])
        self.assertEqual(worksheet['filters'][0]['field'], 'Margin (West)')
        self.assertEqual(worksheet['mark_encoding']['color']['field'], 'Margin (West)')
        self.assertEqual([item['field'] for item in worksheet['mark_encoding']['detail']],
                         ['Région (Nord)', 'Region'])
        self.assertEqual(worksheet['sort_fields'][0]['field'], 'Région (Nord)')
        self.assertEqual(remapped['calculations'][0]['caption'], 'Margin (West)')
        self.assertEqual(remapped['filters'][0]['field'], 'Région (Nord)')
        self.assertEqual(remapped['actions'][0], {
            'source_field': 'Margin (West)', 'target_field': 'Région (Nord)', 'field': 'Region',
        })
        self.assertEqual(remapped['dashboards'], source['dashboards'])

    def test_definition_pbir_persists_local_and_live_semantic_model_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local_report = root / 'Local.Report'
            local_report.mkdir()
            ThinReportGenerator('Modèle partagé', temporary)._write_definition_pbir(str(local_report))
            local = json.loads((local_report / 'definition.pbir').read_text(encoding='utf-8'))

            live_report = root / 'Live.Report'
            live_report.mkdir()
            ThinReportGenerator(
                'Fallback Model', temporary,
                live_connection='workspace-123/Modèle partagé',
            )._write_definition_pbir(str(live_report))
            live = json.loads((live_report / 'definition.pbir').read_text(encoding='utf-8'))

            fallback_report = root / 'Fallback.Report'
            fallback_report.mkdir()
            ThinReportGenerator(
                'Fallback Model', temporary, live_connection='workspace-only',
            )._write_definition_pbir(str(fallback_report))
            fallback = json.loads((fallback_report / 'definition.pbir').read_text(encoding='utf-8'))

        self.assertEqual(local['version'], '4.0')
        self.assertEqual(local['datasetReference'], {
            'byPath': {'path': '../Modèle partagé.SemanticModel'},
        })
        by_connection = live['datasetReference']['byConnection']
        self.assertEqual(by_connection['connectionString'],
                         'Data Source=powerbi://api.powerbi.com/v1.0/myorg/workspace-123;'
                         'Initial Catalog=Modèle partagé')
        self.assertEqual(by_connection['pbiModelDatabaseName'], 'Modèle partagé')
        self.assertIsNone(by_connection['pbiServiceModelId'])
        self.assertEqual(fallback['datasetReference']['byConnection']['pbiModelDatabaseName'],
                         'Fallback Model')


if __name__ == '__main__':
    unittest.main()
