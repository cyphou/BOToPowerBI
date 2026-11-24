"""Behavioral tests for deterministic comparison and migration reports."""

import json
import tempfile
import unittest
from pathlib import Path

from powerbi_import import comparison_report, visual_diff
from powerbi_import.migration_report import MigrationReport


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


def _comparison_visual(path, fields, visual_type='tableEx'):
    projections = [
        {'field': {'Column': {'Property': field}}}
        for field in fields
    ]
    _write_json(path, {
        'visual': {
            'visualType': visual_type,
            'visualContainerObjects': {
                'title': [{'properties': {'text': {'expr': {'Literal': {'Value': "'Synthetic'"}}}}}]
            },
            'query': {'queryState': {'Values': {'projections': projections}}},
        }
    })


def _visual_diff_visual(path, title, visual_type, fields):
    select = []
    for field in fields:
        select.append({'Column': {
            'Expression': {'SourceRef': {'Entity': 'Sales'}},
            'Property': field,
        }})
    _write_json(path, {
        'visual': {'visualType': visual_type},
        'title': {'text': title},
        'query': {'Commands': [{
            'SemanticQueryDataShapeCommand': {'Query': {'Select': select}}
        }]},
    })


class TestComparisonReport(unittest.TestCase):
    def test_json_loaders_handle_missing_and_malformed_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            malformed = root / 'broken.json'
            malformed.write_text('{no json', encoding='utf-8')
            self.assertEqual(comparison_report._load_json(root / 'missing.json'), {})
            self.assertEqual(comparison_report._load_json(malformed), {})

            extracted = comparison_report._load_extracted(str(root))
            self.assertEqual(extracted['worksheets'], {})
            self.assertEqual(len(extracted), 16)

    def test_pbip_loader_finds_report_pages_visuals_and_sibling_migration_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            migrated = root / 'migrated' / 'Sales'
            _write_json(migrated / 'report.json', {'name': 'Sales report'})
            _write_json(migrated / 'definition' / 'pages' / 'page.json', {'page': 'Summary'})
            _write_json(migrated / 'definition' / 'visuals' / 'visual.json', {'visualType': 'card'})
            _write_json(root / 'reports' / 'migration_report_20261123.json', {'items': []})

            loaded = comparison_report._load_pbip(str(migrated))
            self.assertEqual(loaded['report']['name'], 'Sales report')
            self.assertEqual(len(loaded['pages']), 1)
            self.assertEqual(len(loaded['visuals']), 1)
            self.assertEqual(loaded['migration_report']['items'], [])

    def test_worksheet_comparison_matches_titles_and_counts_fields_and_filters(self):
        results = comparison_report._compare_worksheets(
            {'worksheets': {'worksheets': [{
                'name': 'Revenue', 'mark_type': 'bar',
                'fields': [{'name': 'Amount'}, {'name': 'Region'}],
                'filters': [{'field': 'Region'}],
            }]}},
            {'visuals': [{'data': {'title': {'text': 'FY Revenue by Region'},
                                  'visualType': 'clusteredBarChart'}}]},
        )
        self.assertEqual(results[0]['status'], 'pass')
        self.assertEqual(results[0]['tableau']['field_count'], 2)
        self.assertEqual(results[0]['tableau']['filter_count'], 1)
        self.assertEqual(results[0]['powerbi']['visual_type'], 'clusteredBarChart')

    def test_calculation_limit_and_datasource_column_totals_are_reported(self):
        extracted = {
            'calculations': [{'name': f'Calc {i}', 'formula': f'=[{i}]', 'role': 'measure'} for i in range(55)],
            'datasources': {'datasources': [{
                'caption': 'Orders', 'connection': {'type': 'SQL'},
                'tables': [{'columns': [1, 2]}, {'columns': [3]}],
            }]},
        }
        calculations = comparison_report._compare_calculations(extracted, {})
        datasources = comparison_report._compare_datasources(extracted)
        self.assertEqual(len(calculations), 50)
        self.assertEqual(calculations[-1]['name'], 'Calc 49')
        self.assertEqual(datasources, [{'name': 'Orders', 'type': 'SQL', 'table_count': 2, 'column_count': 3}])

    def test_field_binding_classifies_ok_empty_extra_missing_partial_and_no_visual(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            visuals = project / 'visuals'
            _comparison_visual(visuals / '01-ok' / 'visual.json', ['A'], 'tableEx')
            _comparison_visual(visuals / '02-extra' / 'visual.json', ['B', 'B-extra'])
            _comparison_visual(visuals / '03-missing' / 'visual.json', ['C'])
            _comparison_visual(visuals / '04-partial' / 'visual.json', ['D', 'D-extra'])
            _comparison_visual(visuals / '05-empty' / 'visual.json', [])
            worksheets = {'worksheets': [
                {'name': 'ok', 'fields': ['A']},
                {'name': 'extra', 'fields': ['B']},
                {'name': 'missing', 'fields': ['C', 'C-missing']},
                {'name': 'partial', 'fields': ['D', 'D-missing']},
                {'name': 'empty', 'fields': []},
                {'name': 'no visual', 'fields': ['Z']},
            ]}

            bindings = comparison_report._compare_field_bindings(worksheets, str(project))
            self.assertEqual([entry['status'] for entry in bindings],
                             ['OK', 'EXTRA', 'MISSING', 'PARTIAL', 'EMPTY', 'NO_VISUAL'])
            self.assertEqual(bindings[3]['matched'], ['D'])
            self.assertEqual(bindings[3]['missing'], ['D-missing'])
            self.assertEqual(bindings[3]['extra'], ['D-extra'])

    def test_field_binding_reads_aggregation_fields_and_ignores_generated_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            visual = project / 'definition' / 'visual.json'
            _write_json(visual, {'visual': {'visualType': 'lineChart',
                'query': {'queryState': {'Values': {'projections': [
                    {'field': {'Aggregation': {'Expression': {'Column': {'Property': 'Revenue'}}}}}
                ]}}}}})
            result = comparison_report._compare_field_bindings(
                {'worksheets': [{'name': 'Trend', 'fields': [
                    {'name': 'Revenue'}, {'name': 'Latitude (generated)'}]}]}, str(project)
            )[0]
            self.assertEqual(result['status'], 'OK')
            self.assertEqual(result['matched'], ['Revenue'])
            self.assertEqual(result['tab_count'], 1)

    def test_comparison_html_escapes_metadata_and_includes_migration_items(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = root / 'extract'
            _write_json(extracted / 'worksheets.json', [{'name': '<Sales & Ops>', 'fields': ['Revenue']}])
            _write_json(extracted / 'calculations.json', [{'name': '<Total>', 'formula': '=[Revenue] & 1', 'role': 'measure'}])
            _write_json(extracted / 'datasources.json', [{'name': 'Warehouse', 'connection': {'class': 'SQL'},
                                                           'tables': [{'columns': [{'name': 'Revenue'}]}]}])
            pbip = root / 'migrated'
            _comparison_visual(pbip / 'definition' / 'visual.json', ['Revenue'])
            _write_json(root / 'migration_report_20261123.json', {
                'overall_fidelity': 87,
                'items': [{'name': '<Measure>', 'type': 'calculation', 'status': 'partial', 'notes': '<review>'}],
            })
            output = root / 'reports' / 'comparison.html'

            result_path = comparison_report.generate_comparison_report(str(extracted), str(pbip), str(output))
            html = Path(result_path).read_text(encoding='utf-8')
            self.assertIn('&lt;Sales &amp; Ops&gt;', html)
            self.assertIn('&lt;Total&gt;', html)
            self.assertIn('&lt;Measure&gt;', html)
            self.assertIn('87', html)
            self.assertIn('Field Binding Verification', html)


class TestVisualDiff(unittest.TestCase):
    def test_visual_type_matching_distinguishes_exact_approximate_and_unmapped(self):
        visuals = [
            {'visual': {'visualType': 'clusteredBarChart'}, 'title': {'text': ''}, 'query': {}},
            {'visual': {'visualType': 'pieChart'}, 'title': {'text': 'Monthly line'}, 'query': {}},
        ]
        exact = visual_diff._diff_worksheet({'name': 'Revenue', 'mark_type': 'bar'}, visuals)
        approx = visual_diff._diff_worksheet({'name': 'Monthly', 'mark_type': 'line'}, visuals)
        unmapped = visual_diff._diff_worksheet({'name': 'Unknown', 'mark_type': 'bar'}, [])
        self.assertEqual(exact['status'], 'exact')
        self.assertEqual(approx['status'], 'approx')
        self.assertEqual(approx['actual_pbi_type'], 'pieChart')
        self.assertEqual(unmapped['status'], 'unmapped')

    def test_visual_diff_extracts_aggregation_field_reference(self):
        visual = {'visual': {'visualType': 'lineChart'}, 'query': {'Commands': [{
            'SemanticQueryDataShapeCommand': {'Query': {'Select': [{
                'Aggregation': {'Expression': {'Column': {
                    'Expression': {'SourceRef': {'Entity': 'Orders'}}, 'Property': 'Amount'
                }}}
            }]}}
        }]}}
        info = visual_diff._extract_pbi_visual_info(visual)
        self.assertEqual(info['fields'], ['Orders[Amount]'])

    def test_field_matching_encodings_and_filter_counts_are_reflected(self):
        result = visual_diff._diff_worksheet({
            'name': 'Revenue', 'mark_type': {'type': 'line'},
            'fields': [{'name': '[Amount]'}, {'caption': 'Region'}, 'Unmapped'],
            'mark_encoding': {'color': 'Region', 'tooltip': ['Amount']},
            'filters': [{'field': 'Year'}],
        }, [{'visual': {'visualType': 'lineChart'}, 'title': {'text': 'Revenue'},
             'query': {'Commands': [{'SemanticQueryDataShapeCommand': {'Query': {'Select': [
                 {'Column': {'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Amount'}},
                 {'Column': {'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Region'}},
             ]}}}]}}])
        self.assertEqual(result['status'], 'exact')
        self.assertEqual(result['mapped_fields'], ['[Amount]', 'Region'])
        self.assertEqual(result['unmapped_fields'], ['Unmapped'])
        self.assertEqual(result['field_coverage'], 67)
        self.assertTrue(result['bo_encodings']['color'])
        self.assertTrue(result['bo_encodings']['tooltip'])
        self.assertEqual(result['bo_filter_count'], 1)

    def test_json_and_html_outputs_include_summary_and_escape_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _visual_diff_visual(root / 'definition' / 'visual.json', '<Revenue>', 'lineChart', ['Amount'])
            extracted = {'worksheets': {'worksheets': [
                {'name': '<Revenue>', 'mark_type': 'line', 'fields': ['Amount'], 'mark_encoding': {'color': 'Amount'}},
                {'name': 'Missing', 'mark_type': 'funnel', 'fields': ['Absent']},
            ]}}
            summary = visual_diff.generate_visual_diff_json(extracted, str(root))
            self.assertEqual((summary['total'], summary['exact'], summary['unmapped']), (2, 1, 1))
            self.assertEqual(summary['avg_field_coverage'], 50)
            output = root / 'diff' / 'visual-diff.html'
            visual_diff.generate_visual_diff(extracted, str(root), str(output))
            html = output.read_text(encoding='utf-8')
            self.assertIn('&lt;Revenue&gt;', html)
            self.assertIn('Exact Match', html)
            self.assertIn('Unmapped', html)

    def test_empty_visual_diff_has_perfect_vacuous_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary = visual_diff.generate_visual_diff_json({'worksheets': []}, temporary)
        self.assertEqual(summary['total'], 0)
        self.assertEqual(summary['avg_field_coverage'], 100)
        self.assertEqual(summary['visuals'], [])


class TestMigrationReportBehaviors(unittest.TestCase):
    def test_dax_classification_prioritizes_unsupported_then_approximate_markers(self):
        cases = [
            ('SUM(Orders[Amount])', MigrationReport.EXACT),
            ('/* approximate */ SUM(Orders[Amount])', MigrationReport.APPROXIMATE),
            ('COUNTD(Orders[Id])', MigrationReport.APPROXIMATE),
            ('/* MAKEPOINT unsupported */ BLANK()', MigrationReport.UNSUPPORTED),
            ('/* placeholder */ BLANK()', MigrationReport.APPROXIMATE),
            ('', MigrationReport.SKIPPED),
        ]
        for dax, expected in cases:
            with self.subTest(dax=dax):
                self.assertEqual(MigrationReport._classify_dax(dax), expected)

    def test_calculation_bulk_add_uses_caption_and_lookup_fallbacks(self):
        report = MigrationReport('Calculations')
        report.add_calculations([
            {'name': '[Net]', 'caption': 'Net Sales', 'formula': '=Sum([Net])'},
            {'name': '[Ratio]', 'formula': '=A/B'},
            {'name': 'No output', 'formula': '=Unknown()'},
        ], {'Net Sales': 'SUM(Sales[Net])', 'Ratio': '/* approximate */ DIVIDE(A,B)'})
        self.assertEqual([item['name'] for item in report.items], ['Net Sales', '[Ratio]', 'No output'])
        self.assertEqual([item['status'] for item in report.items],
                         [MigrationReport.EXACT, MigrationReport.APPROXIMATE, MigrationReport.SKIPPED])
        self.assertEqual(report.items[0]['source_formula'], '=Sum([Net])')

    def test_visual_bulk_add_marks_unknown_chart_fallback_as_approximate(self):
        report = MigrationReport('Visuals')
        report.add_visuals([
            {'name': 'Known', 'mark_type': 'bar'},
            {'name': 'Unknown', 'mark_type': 'custom'},
            {'name': 'Auto', 'mark_type': 'automatic'},
        ], {'bar': 'clusteredBarChart'})
        self.assertEqual([item['status'] for item in report.items],
                         [MigrationReport.EXACT, MigrationReport.APPROXIMATE, MigrationReport.EXACT])
        self.assertIn('fallback', report.items[1]['note'])

    def test_bulk_add_methods_record_conversion_categories_and_counts(self):
        report = MigrationReport('Bulk')
        report.add_parameters([{'name': 'Year', 'domain_type': 'range'}])
        report.add_relationships([{'fromTable': 'Orders', 'toTable': 'Customers', 'cardinality': 'many-to-one'}])
        report.add_hierarchies([{'name': 'Date', 'levels': ['Year', 'Month']}])
        report.add_sets([{'name': 'Top Customers'}])
        report.add_groups([{'name': 'Regions'}])
        report.add_bins([{'name': 'Age Bands'}])
        report.add_stories([{'name': 'Quarterly', 'story_points': [1, 2]}])
        report.add_user_filters([
            {'name': 'Region role', 'user_mappings': [{'user': 'a'}]},
            {'name': 'Security', 'type': 'calculated_security', 'ismemberof_groups': ['Finance']},
        ])
        self.assertEqual({item['category'] for item in report.items},
                         {'parameter', 'relationship', 'hierarchy', 'set', 'group', 'bin', 'bookmark', 'rls_role'})
        self.assertTrue(any('2 bookmark' in item.get('note', '') for item in report.items))
        self.assertTrue(any('Finance' in item.get('note', '') for item in report.items))
        self.assertEqual(len(report.items), 9)

    def test_datasource_tables_map_to_generated_names_and_missing_tables_are_marked(self):
        report = MigrationReport('Sources')
        report.add_datasources([{'name': 'Primary', 'caption': 'Orders Source',
            'connection': {'class': 'SQL Server'}, 'tables': [
                {'name': 'Orders', 'columns': ['Id', 'Total']},
                {'name': 'Unknown', 'columns': []}, 'invalid row',
            ]}])
        report.add_table_mapping_from_tmdl({'Renamed Orders'})
        self.assertEqual(report.items[0]['note'], 'SQL Server, 3 table(s)')
        self.assertEqual(report.table_mapping, [{
            'source_datasource': 'Orders Source', 'source_table': 'Orders',
            'target_table': '(deduplicated / merged)', 'connection_type': 'SQL Server', 'columns': 2,
        }])

    def test_summary_cache_invalidation_and_completeness_exclude_skipped_items(self):
        report = MigrationReport('Scoring')
        report.add_item('calculation', 'Exact', MigrationReport.EXACT)
        report.add_item('calculation', 'Approx', MigrationReport.APPROXIMATE)
        report.add_item('calculation', 'Skipped', MigrationReport.SKIPPED)
        first = report.get_summary()
        self.assertEqual(first['fidelity_score'], 75.0)
        report.add_item('visual', 'Unsupported', MigrationReport.UNSUPPORTED)
        summary = report.get_summary()
        self.assertIsNot(first, summary)
        self.assertEqual(summary['total_items'], 4)
        complete = report.get_completeness_score()
        self.assertEqual(complete['categories']['calculation']['fidelity_pct'], 75.0)
        self.assertEqual(complete['categories']['visual']['fidelity_pct'], 0.0)
        self.assertEqual(complete['grade'], 'D')

    def test_save_round_trip_and_console_summary_include_items_and_mapping(self):
        report = MigrationReport('Escaped Ω')
        report.add_item('calculation', 'Unsupported', MigrationReport.UNSUPPORTED, note='Needs review')
        report.add_datasources([{'name': 'Source', 'tables': [{'name': 'Orders', 'columns': ['Id']}]}])
        with tempfile.TemporaryDirectory() as temporary:
            filepath = Path(report.save(temporary))
            saved = json.loads(filepath.read_text(encoding='utf-8'))
            self.assertIn('Escaped Ω', filepath.name)
            self.assertEqual(saved['report_name'], 'Escaped Ω')
            self.assertEqual(saved['summary']['unsupported'], 1)
            self.assertEqual(saved['table_mapping'][0]['source_table'], 'Orders')

        from unittest.mock import patch
        with patch('builtins.print') as print_mock:
            report.print_summary()
        printed = '\n'.join(str(call.args[0]) if call.args else ''
                     for call in print_mock.call_args_list)
        self.assertIn('MIGRATION REPORT: Escaped Ω', printed)
        self.assertIn('Unsupported items (1)', printed)
        self.assertIn('Table mapping', printed)


if __name__ == '__main__':
    unittest.main()