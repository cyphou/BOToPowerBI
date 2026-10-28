"""Physical schema preservation across shared-model merging."""

import copy
import contextlib
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from powerbi_import.shared_model import assess_merge, merge_semantic_models, build_table_fingerprints
from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
from powerbi_import.fabric_project_generator import FabricProjectGenerator
from bo_export.universe_extractor import _extract_connections
from migrate import main, EXIT_SUCCESS, EXIT_UNSUPPORTED_FORMAT
from powerbi_import.merge_assessment import print_merge_summary


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

    def test_real_report_shared_cli_rejects_ambiguous_custom_sql_before_generation(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            code = main(['--shared-model', str(repository / 'examples/Enterprise_Sales.wid'),
                         str(repository / 'examples/Financial_Report.wid'), '--force-merge',
                         '--output-format', 'fabric', '--output-dir', temporary])
            self.assertEqual(code, EXIT_UNSUPPORTED_FORMAT)
            self.assertEqual(list(Path(temporary).rglob('fabric_project_metadata.json')), [])

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