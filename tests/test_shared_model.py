"""Physical schema preservation across shared-model merging."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
from bo_export.universe_extractor import _extract_connections
from migrate import EXIT_SUCCESS, EXIT_UNSUPPORTED_FORMAT, main
from powerbi_import.fabric_project_generator import FabricProjectGenerator
from powerbi_import.merge_assessment import print_merge_summary
from powerbi_import.shared_model import (
    MergeManifest,
    MeasureConflict,
    add_to_model,
    analyze_measure_risk,
    assess_merge,
    build_table_fingerprints,
    consolidate_rls_roles,
    detect_isolated_tables,
    detect_rls_conflicts,
    generate_merge_validation_report,
    load_existing_model,
    merge_rls_roles,
    merge_semantic_models,
    remove_from_model,
    suggest_cross_workbook_relationships,
    validate_rls_principals,
    validate_rls_propagation,
    validate_thin_report_fields,
)
from powerbi_import.tmdl_generator import generate_tmdl


class TestSharedModelMetadata(unittest.TestCase):
    def test_real_universe_shared_fabric_cli_preserves_physical_tables(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            code = main(['--shared-model', str(repository / 'examples/eFashion_Universe.unx'),
                         str(repository / 'examples/HR_Universe.unx'), '--force-merge',
                         '--output-format', 'fabric', '--output-dir', temporary])
            self.assertEqual(code, EXIT_SUCCESS)
            project = Path(temporary) / 'SharedModel'
            metadata = json.loads((project / 'fabric_project_metadata.json').read_text(encoding='utf-8'))
            self.assertEqual(len(metadata['ingestion_plan']), 11)
            self.assertEqual(metadata['materialization']['entity'], 'fact_sales')
            self.assertTrue(metadata['validation']['valid'], metadata['validation']['errors'])
            self.assertTrue((project / 'quality_report.json').is_file())
            self.assertNotEqual(json.loads((project / 'quality_report.json').read_text(encoding='utf-8'))['status'], 'FAIL')
            exported = json.loads((project / 'expression_export.json').read_text(encoding='utf-8'))
            queries = [item for item in exported['exports'] if item['kind'] == 'dataflow_m_query']
            self.assertTrue(queries)
            for item in queries:
                self.assertEqual(
                    (project / item['path']).read_text(encoding='utf-8'),
                    (project / item['source']).read_text(encoding='utf-8'),
                )

    def test_shared_pbip_exports_one_merged_model(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            code = main(['--shared-model', str(repository / 'examples/eFashion_Universe.unx'),
                         str(repository / 'examples/HR_Universe.unx'), '--force-merge',
                         '--output-dir', temporary])
            self.assertEqual(code, EXIT_SUCCESS)
            project = Path(temporary) / 'SharedModel'
            manifests = list(project.rglob('expression_export.json'))
            self.assertEqual(manifests, [project / 'expression_export.json'])
            exported = json.loads(manifests[0].read_text(encoding='utf-8'))
            self.assertTrue(any(item['kind'] == 'm_partition' for item in exported['exports']))
            self.assertTrue(any(item['kind'] == 'dax_measures' for item in exported['exports']))
            self.assertEqual(len(list(project.glob('*.Report'))), 3)

    def test_real_report_shared_cli_rejects_ambiguous_custom_sql_before_generation(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            temporary = Path(temporary)
            input_dir = temporary / "inputs"
            input_dir.mkdir()
            output_dir = temporary / "output"
            sources = [
                (
                    input_dir / "Sales.wid",
                    """<document>
                      <connection id="sales-source" name="Sales DB" type="SQL Server"
                                  server="sales.example.invalid" database="Sales"/>
                      <dataProvider id="sales-query" name="Same SQL Query" type="sql"
                                    connectionId="sales-source">
                        <sql>SELECT 1 AS Value</sql>
                      </dataProvider>
                    </document>""",
                ),
                (
                    input_dir / "Finance.wid",
                    """<document>
                      <connection id="finance-source" name="Finance DB" type="SQL Server"
                                  server="finance.example.invalid" database="Finance"/>
                      <dataProvider id="finance-query" name="Same SQL Query" type="sql"
                                    connectionId="finance-source">
                        <sql>SELECT 2 AS Value</sql>
                      </dataProvider>
                    </document>""",
                ),
            ]
            for path, xml in sources:
                path.write_text(xml, encoding="utf-8")

            code = main(['--shared-model', *(str(path) for path, _ in sources),
                         '--force-merge', '--output-format', 'fabric',
                         '--output-dir', str(output_dir)])

            self.assertEqual(code, EXIT_UNSUPPORTED_FORMAT)
            self.assertFalse(output_dir.exists(), "Ambiguous SQL must be rejected before project generation")

    def test_universe_connection_container_is_not_a_datasource_and_duplicates_are_exact(self):
        connections = ET.fromstring('<Connections><Connection name="Warehouse" type="sqlserver" server="db.example.invalid" database="Sales" /></Connections>')
        foundation = ET.fromstring('<DataFoundation><Connection name="Warehouse" type="sqlserver" server="db.example.invalid" database="Sales" />'
                                   '<Connection name="Warehouse" type="sqlserver" server="other.example.invalid" database="Sales" /></DataFoundation>')
        sources = _extract_connections({'connections': [connections], 'data_foundation': foundation})
        self.assertEqual(len(sources), 2)
        self.assertEqual({source['server'] for source in sources}, {'db.example.invalid', 'other.example.invalid'})
        self.assertTrue(all(source['name'] == 'Warehouse' for source in sources))

    def test_explicit_bo_table_schema_is_preserved_in_physical_fingerprint(self):
        raw = {'datasources': [{'name': 'Source', 'type': 'SQL Server', 'server': 'db.example.invalid'}],
               'tables': [{'name': 'Orders', 'schema': 'reporting'}],
               'columns': [{'table': 'Orders', 'name': 'Id', 'data_type': 'integer'}]}
        converted = adapt_bo_to_converted_objects(raw)
        self.assertEqual(converted['datasources'][0]['tables'][0]['schema'], 'reporting')
        self.assertEqual(build_table_fingerprints(converted['datasources'])['Orders'][0].schema, 'reporting')

    def test_bo_adapter_merge_and_fabric_keep_source_backed_schema_and_types(self):
        raw_sources = [
            {'datasources': [{'name': 'SalesSource', 'type': 'SQL Server', 'server': 'sales.example.invalid', 'database': 'Sales'}],
             'tables': [{'name': 'Orders'}],
             'columns': [{'table': 'Orders', 'name': 'OrderId', 'data_type': 'integer'},
                         {'table': 'Orders', 'name': 'Amount', 'data_type': 'real'},
                         {'table': 'Orders', 'name': 'OrderDate', 'data_type': 'date'}],
             'formulas': [{'name': 'Doubled', 'formula': '=[Amount] * 2', 'qualification': 'dimension', 'data_type': 'real'}]},
            {'datasources': [{'name': 'PeopleSource', 'type': 'PostgreSQL', 'server': 'people.example.invalid', 'database': 'People'}],
             'tables': [{'name': 'People'}],
             'columns': [{'table': 'People', 'name': 'PersonId', 'data_type': 'integer'}]},
        ]
        sources = [adapt_bo_to_converted_objects(source) for source in raw_sources]
        assessment = assess_merge(sources, ['SalesReport', 'PeopleReport'])
        merged = merge_semantic_models(sources, assessment, 'Shared')
        with tempfile.TemporaryDirectory() as temporary:
            result = FabricProjectGenerator(temporary).generate_project('Shared', merged)
            self.assertTrue(result['validation']['valid'], result['validation']['errors'])
            project = Path(result['project_path'])
            lakehouse = json.loads((project / 'Shared.Lakehouse/lakehouse_definition.json').read_text(encoding='utf-8'))
            tables = {table['name']: table for table in lakehouse['tables']}
            self.assertEqual(set(tables), {'orders', 'people'})
            columns = {column['name']: column['datatype'] for column in tables['orders']['columns']}
            self.assertEqual(columns['OrderId'], 'INT')
            self.assertEqual(columns['Amount'], 'DOUBLE')
            self.assertEqual(columns['OrderDate'], 'DATE')
            self.assertEqual(columns['Doubled'], 'DOUBLE')
            metadata = json.loads((project / 'fabric_project_metadata.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['materialization']['entity'], 'orders')
            self.assertEqual({source['entity'] for source in metadata['ingestion_plan']}, {'orders', 'people'})
            orders_tmdl = (project / 'Shared.SemanticModel/definition/tables/Orders.tmdl').read_text(encoding='utf-8')
            self.assertIn('dataType: int64', orders_tmdl)
            self.assertIn('entityName: orders', orders_tmdl)
            self.assertNotIn('sourceColumn: OrderDate_Year', orders_tmdl)
            self.assertFalse((project / 'Shared.SemanticModel/definition/tables/Calendar.tmdl').exists())
            self.assertTrue(any('Deferred automatic_calendar' in warning for warning in result['validation']['warnings']))

    def test_import_mode_keeps_automatic_calendar_and_date_hierarchies(self):
        from powerbi_import.tmdl_generator import _build_semantic_model

        datasource = {'name': 'Source', 'tables': [{'name': 'Orders', 'columns': [
            {'name': 'OrderDate', 'datatype': 'date'}, {'name': 'Amount', 'datatype': 'real'}
        ]}]}
        model = _build_semantic_model([datasource], 'Sales', {}, model_mode='import')
        tables = {table['name']: table for table in model['model']['tables']}
        self.assertIn('Calendar', tables)
        self.assertTrue(any(column['name'].startswith('OrderDate ') for column in tables['Orders']['columns']))
        self.assertEqual(tables['Calendar']['partitions'][0]['source']['type'], 'm')

    def test_isolated_tables_keep_schema_connection_and_provenance(self):
        sources = [
            {'datasources': [{'name': 'SalesSource',
                              'connection': {'type': 'SQL Server', 'details': {'server': 'sales.example.invalid', 'database': 'Sales'}},
                              'tables': [{'name': 'Sales', 'columns': [{'name': 'Amount', 'datatype': 'real'}]}]}]},
            {'datasources': [{'name': 'PeopleSource',
                              'connection': {'type': 'PostgreSQL', 'details': {'server': 'people.example.invalid', 'database': 'People'}},
                              'tables': [{'name': 'People', 'columns': [{'name': 'PersonId', 'datatype': 'integer'}]}]}]},
        ]
        original = copy.deepcopy(sources)
        assessment = assess_merge(sources, ['SalesReport', 'PeopleReport'])
        self.assertEqual(assessment.isolated_tables, {'SalesReport': ['Sales'], 'PeopleReport': ['People']})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            print_merge_summary(assessment)
        self.assertIn('retained with source provenance', output.getvalue())
        self.assertNotIn('excluded from shared model', output.getvalue())
        merged = merge_semantic_models(sources, assessment, 'Shared')
        tables = {table['name']: table for table in merged['datasources'][0]['tables']}
        self.assertEqual(set(tables), {'Sales', 'People'})
        self.assertEqual(tables['Sales']['columns'], original[0]['datasources'][0]['tables'][0]['columns'])
        self.assertEqual(tables['People']['columns'], original[1]['datasources'][0]['tables'][0]['columns'])
        self.assertEqual(tables['Sales']['connection_details'], original[0]['datasources'][0]['connection'])
        self.assertEqual(tables['People']['connection_details'], original[1]['datasources'][0]['connection'])
        self.assertEqual(tables['Sales']['_source_workbooks'], ['SalesReport'])
        self.assertEqual(tables['People']['_source_workbooks'], ['PeopleReport'])
        self.assertEqual(sources, original)

    def test_connections_resolve_per_table_and_flat_bo_metadata(self):
        datasource = {'name': 'Sources', 'connection': {'type': 'SQL Server', 'server': 'default.example.invalid', 'database': 'Default'},
                      'connection_map': {'people': {'type': 'PostgreSQL', 'server': 'people.example.invalid', 'database': 'People'}},
                      'tables': [
                          {'name': 'Orders', 'columns': [{'name': 'Id', 'datatype': 'integer'}]},
                          {'name': 'People', 'connection': 'people', 'columns': [{'name': 'PersonId', 'datatype': 'integer'}]},
                          {'name': 'Inventory', 'connection_details': {'type': 'SQL Server', 'details': {'server': 'inventory.example.invalid', 'database': 'Inventory'}},
                           'columns': [{'name': 'StockId', 'datatype': 'integer'}]},
                      ]}
        fingerprints = build_table_fingerprints([datasource])
        self.assertEqual(fingerprints['Orders'][0].server, 'default.example.invalid')
        self.assertEqual(fingerprints['People'][0].server, 'people.example.invalid')
        self.assertEqual(fingerprints['Inventory'][0].server, 'inventory.example.invalid')
        extracted = [{'datasources': [datasource]}]
        merged = merge_semantic_models(extracted, assess_merge(extracted, ['Report']), 'Shared')
        tables = {table['name']: table for table in merged['datasources'][0]['tables']}
        self.assertEqual(tables['People']['connection_details'], datasource['connection_map']['people'])
        self.assertEqual(tables['Inventory']['connection_details'], datasource['tables'][2]['connection_details'])

    def test_same_physical_table_unions_columns_without_mutating_sources(self):
        connection = {'type': 'SQL Server', 'server': 'sales.example.invalid', 'database': 'Sales'}
        sources = [{'datasources': [{'name': name, 'connection': connection,
                                    'tables': [{'name': 'Orders', 'columns': columns}]}]}
                   for name, columns in [('A', [{'name': 'Id', 'datatype': 'integer'}]),
                                         ('B', [{'name': 'Id', 'datatype': 'integer'}, {'name': 'Amount', 'datatype': 'real'}])]]
        original = copy.deepcopy(sources)
        merged = merge_semantic_models(sources, assess_merge(sources, ['A', 'B']), 'Shared')
        tables = merged['datasources'][0]['tables']
        self.assertEqual(len(tables), 1)
        self.assertEqual({column['name'] for column in tables[0]['columns']}, {'Id', 'Amount'})
        self.assertEqual(tables[0]['_source_workbooks'], ['A', 'B'])
        self.assertEqual(sources, original)

    def test_same_name_different_physical_sources_are_not_silently_merged(self):
        sources = [{'datasources': [{'connection': {'type': 'SQL Server', 'server': server, 'database': 'Sales'},
                                    'tables': [{'name': 'Orders', 'columns': [{'name': 'Id'}]}]}]}
                   for server in ['first.example.invalid', 'second.example.invalid']]
        assessment = assess_merge(sources, ['A', 'B'])
        self.assertEqual(assessment.merge_candidates, [])
        with self.assertRaisesRegex(ValueError, 'Ambiguous merged table name'):
            merge_semantic_models(sources, assessment, 'Shared')
        with self.assertRaisesRegex(ValueError, 'Ambiguous physical table name'):
            build_table_fingerprints([source['datasources'][0] for source in sources])

    def test_file_paths_and_bo_custom_sql_are_part_of_physical_identity(self):
        file_fingerprints = [build_table_fingerprints([{'connection': {'type': 'CSV', 'details': {'filename': filename}},
                                                      'tables': [{'name': 'Orders'}]}])['Orders'][0]
                             for filename in ['first.csv', 'second.csv']]
        self.assertNotEqual(file_fingerprints[0], file_fingerprints[1])
        sql_fingerprints = [build_table_fingerprints([{'connection': {'type': 'SQL Server', 'server': 'db.example.invalid'},
                                                     'tables': [{'name': 'Query', 'type': 'custom_sql', 'sql': sql}]}])['Query'][0]
                            for sql in ['SELECT Id FROM Orders', 'SELECT Id FROM People']]
        self.assertNotEqual(sql_fingerprints[0], sql_fingerprints[1])

    def test_merge_calculations_deduplicates_and_namespaces_conflicts_without_mutating_sources(self):
        sources = [
            {'calculations': [
                {'caption': 'Total Sales', 'formula': 'SUM([Amount])', 'role': 'measure'},
                {'caption': 'Margin', 'formula': 'SUM([Profit])', 'role': 'measure'},
            ]},
            {'calculations': [
                {'caption': 'Total Sales', 'formula': 'SUM([Amount])', 'role': 'measure'},
                {'caption': 'Margin', 'formula': 'SUM([Net Profit])', 'role': 'measure'},
            ]},
        ]
        original = copy.deepcopy(sources)

        assessment = assess_merge(sources, ['North', 'South'])
        merged = merge_semantic_models(sources, assessment, 'Shared')

        calculations = {item['caption']: item for item in merged['calculations']}
        self.assertEqual(calculations['Total Sales']['_merge_action'], 'deduplicated')
        self.assertEqual(calculations['Total Sales']['_source_workbooks'], ['North', 'South'])
        self.assertEqual(calculations['Margin (North)']['formula'], 'SUM([Profit])')
        self.assertEqual(calculations['Margin (South)']['formula'], 'SUM([Net Profit])')
        self.assertEqual(calculations['Margin (North)']['_source_workbooks'], ['North'])
        self.assertEqual(calculations['Margin (South)']['_source_workbooks'], ['South'])
        self.assertEqual(sources, original)

    def test_merge_hierarchies_prefers_more_levels_and_tracks_both_sources(self):
        sources = [
            {'hierarchies': [{'name': 'География', 'levels': [
                {'name': 'Country'}, {'name': 'Region'},
            ]}]},
            {'hierarchies': [{'name': 'География', 'levels': [
                {'name': 'Country'}, {'name': 'Region'}, {'name': 'City'},
            ]}]},
        ]
        original = copy.deepcopy(sources)

        merged = merge_semantic_models(sources, assess_merge(sources, ['A', 'B']), 'Shared')

        self.assertEqual(len(merged['hierarchies']), 1)
        hierarchy = merged['hierarchies'][0]
        self.assertEqual([level['name'] for level in hierarchy['levels']],
                         ['Country', 'Region', 'City'])
        self.assertEqual(hierarchy['_source_workbooks'], ['A', 'B'])
        self.assertEqual(hierarchy['_merge_action'], 'deduplicated')
        self.assertEqual(sources, original)

    def test_merge_field_parameters_unions_values_in_source_order(self):
        sources = [
            {'parameters': [{'caption': 'Choose dimension', 'datatype': 'string',
                             'domain_type': 'list', 'allowable_values': [
                                 {'value': 'Region'}, {'value': 'Product'},
                             ]}]},
            {'parameters': [{'caption': 'Choose dimension', 'datatype': 'string',
                             'domain_type': 'list', 'allowable_values': [
                                 {'value': 'Product'}, {'value': 'City'},
                             ]}]},
        ]
        original = copy.deepcopy(sources)

        merged = merge_semantic_models(sources, assess_merge(sources, ['A', 'B']), 'Shared')

        self.assertEqual(len(merged['_field_parameters']), 1)
        field_parameter = merged['_field_parameters'][0]
        self.assertEqual(field_parameter['values'], ['Region', 'Product', 'City'])
        self.assertEqual(field_parameter['_source_workbooks'], ['A', 'B'])
        self.assertEqual(field_parameter['_merge_action'], 'unioned')
        self.assertEqual(sources, original)

    def test_merge_calculation_groups_namespaces_conflicting_items_with_provenance(self):
        sources = [
            {'parameters': [{'caption': 'View as', 'datatype': 'string', 'domain_type': 'list',
                             'allowable_values': [{'value': 'Revenue'}, {'value': 'Cost'}]}]},
            {'parameters': [{'caption': 'View as', 'datatype': 'string', 'domain_type': 'list',
                             'allowable_values': [{'value': 'Revenue'}, {'value': 'Margin'}]}]},
        ]
        original = copy.deepcopy(sources)

        merged = merge_semantic_models(sources, assess_merge(sources, ['A', 'B']), 'Shared')

        groups = {item['caption']: item for item in merged['_calculation_groups']}
        self.assertEqual(set(groups), {'View as (A)', 'View as (B)'})
        self.assertEqual(groups['View as (A)']['values'], ['Revenue', 'Cost'])
        self.assertEqual(groups['View as (B)']['values'], ['Revenue', 'Margin'])
        self.assertEqual(groups['View as (A)']['_source_workbooks'], ['A'])
        self.assertEqual(groups['View as (B)']['_merge_action'], 'namespaced')
        self.assertEqual(sources, original)

    def test_merge_cultures_keeps_first_translation_and_combines_locale_provenance(self):
        sources = [
            {'culture': 'fr-FR', '_cultures': [{'locale': 'fr-FR', 'translations': {
                'Sales': 'Ventes', 'Amount': 'Montant',
            }}]},
            {'culture': 'fr-FR', '_cultures': [{'locale': 'fr-FR', 'translations': {
                'Sales': 'Chiffre d’affaires', 'Region': 'Région',
            }}], '_languages': 'ja-JP'},
        ]
        original = copy.deepcopy(sources)

        merged = merge_semantic_models(sources, assess_merge(sources, ['A', 'B']), 'Shared')

        cultures = {culture['locale']: culture for culture in merged['_cultures']}
        self.assertEqual(cultures['fr-FR']['translations'], {
            'Sales': 'Ventes', 'Amount': 'Montant', 'Region': 'Région',
        })
        self.assertCountEqual(cultures['fr-FR']['_source_workbooks'], ['A', 'A', 'B', 'B'])
        self.assertIn('ja-JP', cultures)
        self.assertEqual(cultures['ja-JP']['_source_workbooks'], ['B'])
        self.assertEqual(sources, original)

    def test_merged_physical_column_promotes_type_and_retains_type_history(self):
        connection = {'type': 'SQL Server', 'server': 'db.example.invalid', 'database': 'Sales'}
        sources = [
            {'datasources': [{'name': 'A', 'connection': connection,
                              'tables': [{'name': 'Orders', 'columns': [
                                  {'name': 'Amount', 'datatype': 'integer'},
                              ]}]}]},
            {'datasources': [{'name': 'B', 'connection': connection,
                              'tables': [{'name': 'Orders', 'columns': [
                                  {'name': 'Amount', 'datatype': 'real'},
                              ]}]}]},
        ]
        original = copy.deepcopy(sources)

        merged = merge_semantic_models(sources, assess_merge(sources, ['A', 'B']), 'Shared')

        table = merged['datasources'][0]['tables'][0]
        self.assertEqual(table['columns'][0]['datatype'], 'real')
        self.assertEqual(table['_column_type_history']['amount'], ['integer', 'real'])
        self.assertEqual(table['_source_workbooks'], ['A', 'B'])
        self.assertEqual(sources, original)

    def test_generated_tmdl_round_trips_tables_relationships_measures_and_rls(self):
        datasource = {
            'name': 'Local source',
            'tables': [
                {'name': 'Orders', 'columns': [
                    {'name': 'CustomerKey', 'datatype': 'integer'},
                    {'name': 'Montant', 'datatype': 'real'},
                ]},
                {'name': 'Customers', 'columns': [
                    {'name': 'CustomerKey', 'datatype': 'integer'},
                    {'name': 'Nom', 'datatype': 'string'},
                ]},
            ],
            'calculations': [{'name': '[Total]', 'caption': 'Total',
                              'formula': 'SUM([Montant])', 'role': 'measure'}],
            'relationships': [{
                'left': {'table': 'Orders', 'column': 'CustomerKey'},
                'right': {'table': 'Customers', 'column': 'CustomerKey'},
                'type': 'left',
            }],
        }
        extras = {'user_filters': [{
            'type': 'user_filter', 'name': 'Région', 'column': 'Nom',
            'user_mappings': [{'user': 'ana@example.invalid', 'value': 'Montréal'}],
        }]}

        with tempfile.TemporaryDirectory() as temporary:
            generate_tmdl([datasource], 'Shared', extras, temporary)
            loaded = load_existing_model(temporary)

        datasource_loaded = loaded['datasources'][0]
        self.assertEqual({table['name'] for table in datasource_loaded['tables']},
                         {'Orders', 'Customers'})
        self.assertEqual(datasource_loaded['relationships'][0]['fromTable'], 'Orders')
        self.assertEqual(datasource_loaded['relationships'][0]['toTable'], 'Customers')
        total = next(calc for calc in loaded['calculations'] if calc['caption'] == 'Total')
        self.assertEqual(total['_classification'], 'measure')
        self.assertIn('SUM(', total['formula'])
        self.assertEqual(loaded['user_filters'][0]['name'], 'Région')
        self.assertIn('ana@example.invalid', loaded['user_filters'][0]['filter_expression'])

    def test_add_to_model_loads_local_tmdl_and_updates_manifest_without_mutating_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            model_dir = Path(temporary)
            generate_tmdl([{'name': 'Existing', 'tables': [{
                'name': 'Orders', 'columns': [{'name': 'OrderId', 'datatype': 'integer'}],
                'calculations': [{'caption': 'Order Count', 'formula': 'COUNT([OrderId])',
                                  'role': 'measure'}],
            }]}], 'Shared', {}, str(model_dir))
            manifest = MergeManifest(
                model_name='Shared',
                workbooks=[{'name': 'Existing', 'tables': ['Orders'],
                            'measures': ['Order Count'], 'exclusive_tables': ['Orders']}],
            )
            manifest.save(str(model_dir))
            new_source = {'datasources': [{'name': 'People', 'tables': [{
                'name': 'People', 'columns': [{'name': 'PersonId', 'datatype': 'integer'}],
            }]}], 'calculations': []}
            original_source = copy.deepcopy(new_source)

            with self.assertRaisesRegex(ValueError, 'already exists'):
                add_to_model(str(model_dir), new_source, 'Existing')
            result = add_to_model(str(model_dir), new_source, 'PeopleReport', force=True)

        self.assertEqual(result['status'], 'added')
        self.assertEqual({table['name'] for table in result['merged']['datasources'][0]['tables']},
                         {'Orders', 'People'})
        self.assertEqual([wb['name'] for wb in result['manifest'].workbooks],
                         ['Existing', 'PeopleReport'])
        self.assertEqual(new_source, original_source)

    def test_remove_from_model_preserves_shared_tables_and_drops_exclusive_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            model_dir = Path(temporary)
            datasource = {'name': 'Shared source', 'tables': [
                {'name': 'Orders', 'columns': [{'name': 'OrderId', 'datatype': 'integer'}]},
                {'name': 'People', 'columns': [{'name': 'PersonId', 'datatype': 'integer'}]},
            ], 'relationships': [{
                'left': {'table': 'Orders', 'column': 'OrderId'},
                'right': {'table': 'People', 'column': 'PersonId'}, 'type': 'left',
            }]}
            generate_tmdl([datasource], 'Shared', {}, str(model_dir))
            manifest = MergeManifest(
                model_name='Shared',
                workbooks=[
                    {'name': 'OrdersReport', 'tables': ['Orders'], 'measures': [],
                     'exclusive_tables': ['Orders']},
                    {'name': 'PeopleReport', 'tables': ['Orders', 'People'], 'measures': [],
                     'exclusive_tables': ['People']},
                ],
                table_fingerprints={'Orders': 'orders-hash', 'People': 'people-hash'},
            )
            manifest.save(str(model_dir))

            result = remove_from_model(str(model_dir), 'PeopleReport')

        self.assertEqual(result['status'], 'removed')
        self.assertEqual(result['removed_tables'], ['People'])
        self.assertEqual(result['shared_tables_kept'], ['Orders'])
        self.assertEqual({table['name'] for table in result['merged']['datasources'][0]['tables']},
                         {'Orders'})
        self.assertEqual(result['merged']['datasources'][0]['relationships'], [])
        self.assertNotIn('People', result['manifest'].table_fingerprints)
        self.assertEqual(result['manifest'].artifact_counts['tables'], 1)

    def test_merge_validation_reports_cycles_type_and_dax_reference_findings(self):
        merged = {
            'datasources': [{'tables': [{
                'name': 'A', '_column_type_history': {'When': ['datetime', 'integer']},
                'columns': [{'name': 'Id'}],
            }, {'name': 'B', 'columns': [{'name': 'Id'}]},
                {'name': 'C', 'columns': [{'name': 'Id'}]}],
                'relationships': [
                    {'from_table': 'A', 'to_table': 'B', 'cardinality': 'manyToMany'},
                    {'from_table': 'B', 'to_table': 'C', 'cardinality': 'manyToMany'},
                    {'from_table': 'C', 'to_table': 'A', 'cardinality': 'manyToMany'},
                ]}],
            'calculations': [
                {'caption': 'Broken', 'formula': "SUM('Missing'[Nope])", 'role': 'measure'},
                {'caption': 'Related', 'formula': "RELATED('C'[Id])", 'role': 'dimension'},
            ],
        }

        report = generate_merge_validation_report(merged)

        self.assertEqual(report['counts']['cycles'], 1)
        self.assertEqual(report['counts']['type_errors'], 1)
        self.assertEqual(report['counts']['dax_errors'], 1)
        self.assertEqual(report['counts']['cardinality_mismatches'], 1)
        self.assertEqual(report['dax_errors'][0]['status'], 'error_table')
        self.assertEqual(report['cardinality_mismatches'][0]['status'], 'warning')
        self.assertFalse(report['passed'])

    def test_rls_consolidation_supports_and_or_and_namespaced_conflicts(self):
        extracted = [
            {'user_filters': [{'name': 'Région', 'table': 'Orders',
                               'filter_expression': "[Country] = \"CA\""}]},
            {'user_filters': [{'name': 'Région', 'table': 'Orders',
                               'filter_expression': "[Country] = \"FR\""}]},
        ]

        and_result = consolidate_rls_roles(extracted, ['North', 'South'], strategy='and')
        namespace_result = consolidate_rls_roles(extracted, ['North', 'South'], strategy='namespace')
        merged_roles = merge_rls_roles(extracted, ['North', 'South'])

        self.assertEqual(and_result[0].action, 'merge')
        self.assertIn(' && ', and_result[0].merged_expression)
        self.assertEqual({item.role_name for item in namespace_result},
                         {'Région (North)', 'Région (South)'})
        self.assertEqual(merged_roles[0]['_consolidation'], 'merged')
        self.assertIn(' || ', merged_roles[0]['filter_expression'])

    def test_rls_propagation_principal_formats_and_isolated_table_findings(self):
        merged = {
            'tables': [{'name': 'Orders'}, {'name': 'Customers'}, {'name': 'Notes'}],
            'relationships': [{'fromTable': 'Orders', 'toTable': 'Customers'}],
            'user_filters': [
                {'name': 'Valid', 'table': 'Orders',
                 'filter_expression': 'USERPRINCIPALNAME() = [Email]'},
                {'name': 'Missing', 'table': 'Unknown', 'formula': 'USERNAME()'},
                {'name': 'Isolated', 'table': 'Notes'},
                {'name': 'Unscoped', 'filter_expression': 'USERNAME()'},
            ],
        }

        propagation = validate_rls_propagation(merged)
        principals = validate_rls_principals(merged)
        isolated = detect_isolated_tables(merged)

        self.assertEqual([item['status'] for item in propagation],
                         ['ok', 'error', 'warning', 'warning'])
        self.assertEqual(principals[0]['format_detected'], 'UPN (user@domain.com)')
        self.assertEqual(principals[1]['format_detected'], 'USERNAME (DOMAIN\\user)')
        self.assertEqual({item['table'] for item in isolated}, {'Notes'})

    def test_goal_merge_namespaces_conflicts_and_deduplicates_matching_metrics(self):
        extracted = [
            {'_goals': [
                {'name': 'Revenue', 'measure': 'Sales'},
                {'name': 'Margin', 'measure': 'Margin A'},
            ]},
            {'_goals': [
                {'name': 'Revenue', 'measure': 'Sales'},
                {'name': 'Margin', 'measure': 'Margin B'},
            ]},
        ]

        merged = merge_semantic_models(extracted, assess_merge(extracted, ['A', 'B']), 'Shared')
        goals = {goal['name']: goal for goal in merged['_goals']}

        self.assertEqual(goals['Revenue']['_merge_action'], 'deduplicated')
        self.assertEqual(goals['Revenue']['_source_workbooks'], ['A', 'B'])
        self.assertEqual(goals['Margin (A)']['measure'], 'Margin A')
        self.assertEqual(goals['Margin (B)']['_source_workbook'], 'B')

    def test_legacy_thin_report_field_validation_applies_namespaced_mapping(self):
        converted = {'worksheets': [{
            'name': 'Résumé',
            'columns': [{'name': 'Region'}, {'name': 'Margin'}],
            'filters': [{'field': 'Missing Filter'}],
            'mark_encoding': {'color': {'field': 'Missing Color'}},
        }]}
        merged = {
            'datasources': [{'tables': [{'name': 'Orders', 'columns': [
                {'name': 'Region'},
            ]}]}],
            'calculations': [{'caption': 'Margin (North)'}],
        }

        issues = validate_thin_report_fields(
            converted, merged, {'Margin': 'Margin (North)'})

        self.assertEqual([(issue['field'], issue['issue']) for issue in issues], [
            ('Missing Filter', 'orphaned_filter'),
            ('Missing Color', 'orphaned_encoding'),
        ])

    def test_cross_workbook_relationship_suggestions_respect_existing_edges_and_key_confidence(self):
        merged = {'datasources': [
            {'name': 'Sales', 'tables': [
                {'name': 'Commandes', 'columns': [
                    {'name': 'client_id'}, {'name': 'sku_code'}, {'name': 'Description'}]},
                {'name': 'Clients', 'columns': [
                    {'name': 'CLIENT_ID'}, {'name': 'Nom'}]},
            ], 'relationships': []},
            {'name': 'Catalog', 'tables': [
                {'name': 'Produits', 'columns': [{'name': 'sku_code'}, {'name': 'Libellé'}]}],
             'relationships': []},
        ]}

        suggestions = suggest_cross_workbook_relationships(merged)

        self.assertEqual(suggestions, [
            {'from_table': 'Commandes', 'from_column': 'client_id',
             'to_table': 'Clients', 'to_column': 'client_id', 'confidence': 'high'},
            {'from_table': 'Commandes', 'from_column': 'sku_code',
             'to_table': 'Produits', 'to_column': 'sku_code', 'confidence': 'medium'},
        ])

        merged['datasources'][0]['relationships'] = [{
            'left': {'table': 'Commandes', 'column': 'client_id'},
            'right': {'table': 'Clients', 'column': 'CLIENT_ID'},
        }]
        self.assertEqual(suggest_cross_workbook_relationships(merged), [
            {'from_table': 'Commandes', 'from_column': 'sku_code',
             'to_table': 'Produits', 'to_column': 'sku_code', 'confidence': 'medium'},
        ])

    def test_rls_conflicts_compare_same_role_and_table_without_reporting_identical_rules(self):
        extracted = [
            {'user_filters': [
                {'table': 'Orders', 'name': 'Région', 'formula': '[Pays] = "CA"'},
                {'table': 'Orders', 'name': 'Shared rule', 'values': ['CA', 'FR']},
            ]},
            {'user_filters': [
                {'table': 'orders', 'name': 'Région', 'formula': '[Pays] = "FR"'},
                {'table': 'orders', 'name': 'Shared rule', 'values': ['CA', 'FR']},
            ]},
            {'user_filters': [{'table': 'Customers', 'name': 'Région',
                               'formula': '[Pays] = "US"'}]},
        ]

        conflicts = detect_rls_conflicts(extracted, ['Nord', 'Sud', 'Ouest'])

        self.assertEqual(conflicts, [{
            'table': 'orders', 'role_name': 'Région',
            'variants': {'Nord': '[Pays] = "CA"', 'Sud': '[Pays] = "FR"'},
        }])

    def test_measure_risk_distinguishes_same_semantics_column_drift_and_aggregation_drift(self):
        conflicts = [
            MeasureConflict('Chiffre', 'Orders', {
                'Nord': 'SUM(Orders[Montant])', 'Sud': 'SUM([Montant])'}),
            MeasureConflict('Volume', 'Orders', {
                'Nord': 'COUNT([OrderId])', 'Sud': 'COUNT([CustomerId])'}),
            MeasureConflict('Valeur', 'Orders', {
                'Nord': 'SUM([Montant])', 'Sud': 'AVERAGE([Montant])'}),
            MeasureConflict('Opaque', 'Orders', {'Nord': '[Montant]', 'Sud': '1'}),
        ]

        risks = analyze_measure_risk(conflicts)

        self.assertEqual([(item.measure_name, item.risk_level) for item in risks], [
            ('Chiffre', 'low'), ('Volume', 'medium'), ('Valeur', 'high'), ('Opaque', 'low'),
        ])
        self.assertEqual(risks[0].aggregation_types, {'Nord': 'SUM', 'Sud': 'SUM'})
        self.assertIn('different columns', risks[1].reason)
        self.assertEqual(set(risks[2].reason.partition(': ')[2].split(', ')),
                 {'SUM', 'AVERAGE'})
        self.assertEqual(risks[3].aggregation_types, {'Nord': 'unknown', 'Sud': 'unknown'})

    def test_existing_tmdl_loader_restores_escaped_names_multiline_expressions_and_security(self):
        with tempfile.TemporaryDirectory() as temporary:
            definition = Path(temporary) / 'Shared.SemanticModel' / 'definition'
            tables_dir = definition / 'tables'
            tables_dir.mkdir(parents=True)
            (tables_dir / "Ventes.tmdl").write_text(
                "table 'Ventes d''été'\n"
                "\tmeasure 'Total d''été' = ```\n"
                "\t\tSUM('Ventes d''été'[Montant])\n"
                "\t\t+ 1\n"
                "\t```\n"
                "\tdescription: Résultat fidèle\n"
                "\tcolumn Montant\n"
                "\t\tdataType: double\n"
                "\tcolumn 'Montant net' = ```\n"
                "\t\t[Ventes d''été] - 1\n"
                "\t```\n"
                "\tdataType: double\n"
                "\thierarchy 'Géographie'\n"
                "\t\tlevel Région\n"
                "\t\t\tcolumn: Région\n"
                "\tpartition 'Ventes d''été' = m\n"
                "\t\tmode: import\n"
                "\t\tsource =\n"
                "\t\t\texpression = ```\n"
                "\t\t\tlet\n"
                "\t\t\t    Source = Input\n"
                "\t\t\tin\n"
                "\t\t\t    Source\n"
                "\t\t```\n", encoding='utf-8')
            (definition / 'relationships.tmdl').write_text(
                "relationship 'Rel 1'\n"
                "\tfromColumn: 'Ventes d''été'.'Montant net'\n"
                "\ttoColumn: Clients.Id\n"
                "\tfromCardinality: many\n"
                "\ttoCardinality: one\n"
                "\tcrossFilteringBehavior: bothDirections\n"
                "\tisActive: false\n", encoding='utf-8')
            (definition / 'roles.tmdl').write_text(
                "role 'Équipe d''été'\n"
                "\tmodelPermission: read\n"
                "\ttablePermission 'Ventes d''été'\n"
                "\t\tfilterExpression = [Région] = \"Québec\"\n"
                "\tannotation MigrationNote = \"Règle d''accès\"\n", encoding='utf-8')

            loaded = load_existing_model(temporary)

        datasource = loaded['datasources'][0]
        self.assertEqual(datasource['tables'][0]['name'], "Ventes d'été")
        self.assertEqual(datasource['relationships'][0]['fromTable'], "Ventes d'été")
        self.assertEqual(datasource['relationships'][0]['fromColumn'], 'Montant net')
        self.assertFalse(datasource['relationships'][0]['isActive'])
        self.assertEqual(datasource['relationships'][0]['crossFilteringBehavior'], 'bothDirections')
        calculations = {item['caption']: item for item in loaded['calculations']}
        self.assertEqual(calculations["Total d'été"]['formula'],
                         "SUM('Ventes d''été'[Montant])\n+ 1")
        self.assertEqual(calculations['Montant net']['_classification'], 'calculated_column')
        self.assertEqual(loaded['user_filters'][0]['name'], "Équipe d'été")
        self.assertEqual(loaded['user_filters'][0]['filter_expression'], '[Région] = "Québec"')
