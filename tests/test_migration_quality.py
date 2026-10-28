"""Local quality reporting and CLI exit contracts."""

import json
import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from migrate import EXIT_SUCCESS, EXIT_VALIDATION_ERROR, main
from powerbi_import.fabric_validator import FabricProjectValidator
from powerbi_import.migration_quality import build_quality_report, save_quality_report
from powerbi_import.fabric_semantic_model_generator import FabricSemanticModelGenerator
from powerbi_import.dataflow_generator import DataflowGenerator
from powerbi_import.notebook_generator import NotebookGenerator
from powerbi_import.fabric_item import logical_id
from powerbi_import.fabric_project_generator import FabricProjectGenerator
from powerbi_import.pipeline_generator import PipelineGenerator
from powerbi_import.calc_column_utils import bo_formula_to_m, bo_formula_to_pyspark, classify_calculations
from powerbi_import.fabric_sources import table_connection, is_file_connection, build_ingestion_plan


class TestMigrationQuality(unittest.TestCase):
    def test_pipeline_refreshes_one_dataflow_for_multiple_datasources(self):
        with tempfile.TemporaryDirectory() as temporary:
            generator = PipelineGenerator(temporary, 'Sales')
            activities = generator._build_activities([
                {'name': 'Duplicate', 'tables': [{'name': 'Orders'}]},
                {'name': 'Duplicate', 'tables': [{'name': 'Orders'}]},
            ])
            refreshes = [activity for activity in activities if activity['type'] == 'RefreshDataflow']
            self.assertEqual(len(refreshes), 1)
            self.assertEqual(len({activity['name'] for activity in activities}), len(activities))
            notebook = next(activity for activity in activities if activity['type'] == 'TridentNotebook')
            self.assertEqual(notebook['dependsOn'][0]['activity'], refreshes[0]['name'])

    def test_bo_formula_prefix_is_removed_and_previous_is_explicitly_unsupported(self):
        code = bo_formula_to_pyspark('=[Amount] * 2', 'Doubled')
        ast.parse(code)
        self.assertIn('F.col("Amount") * 2', code)
        self.assertEqual(bo_formula_to_m('=[Amount] * 2'), '[Amount] * 2')
        previous = bo_formula_to_pyspark('=Previous([Amount])', 'Prior')
        ast.parse(previous)
        self.assertIn('raise NotImplementedError', previous)
        self.assertTrue(bo_formula_to_m('=Previous([Amount])').startswith('error '))

    def test_webi_if_without_end_and_bo_running_aggregation(self):
        for suffix in ('', ' End'):
            with self.subTest(suffix=suffix):
                code = bo_formula_to_pyspark('=If [Revenue] > 100000 Then "High" Else "Normal"' + suffix, 'Flag')
                ast.parse(code)
                self.assertIn('F.when(F.col("Revenue") > 100000, "High").otherwise("Normal")', code)
        calculation = {'name': 'Running Revenue', 'formula': '=RunningSum([Revenue])', 'role': 'measure'}
        columns, measures = classify_calculations([calculation])
        self.assertEqual(columns, [])
        self.assertEqual(measures, [calculation])
        unsupported = bo_formula_to_pyspark('UnknownBOFunction([Revenue])', 'Value')
        self.assertTrue(unsupported.startswith('raise NotImplementedError'))

    def test_conditional_spark_syntax_is_validated_and_numeric_inequality_converted(self):
        code = bo_formula_to_pyspark('=If [Budget] <> 0 Then [Amount] / [Budget] Else 0', 'Ratio')
        ast.parse(code)
        self.assertIn('F.col("Budget") != 0', code)
        nested = bo_formula_to_pyspark('=If [Salary] > 100 Then "High" ElseIf [Salary] > 50 Then "Mid" Else "Low"', 'Band')
        ast.parse(nested)
        self.assertTrue(nested.startswith('raise NotImplementedError'))
        literal = bo_formula_to_pyspark('=If [Marker] == "<>" Then 1 Else 0', 'Flag')
        self.assertIn('"<>"', literal)

    def test_calculated_columns_use_same_delta_name_in_all_fabric_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            calculation = {'name': 'Doubled Value', 'caption': 'Doubled Value', 'formula': '=[Amount] * 2',
                           'role': 'dimension', 'datatype': 'real'}
            data = {'datasources': [{'name': 'Source', 'tables': [
                {'name': 'Orders', 'columns': [{'name': 'Amount', 'datatype': 'real'}]}
            ], 'calculations': [calculation]}], 'calculations': [calculation]}
            project = Path(FabricProjectGenerator(temporary).generate_project('Sales', data)['project_path'])
            lakehouse = json.loads((project / 'Sales.Lakehouse/lakehouse_definition.json').read_text(encoding='utf-8'))
            self.assertIn('Doubled_Value', [column['name'] for column in lakehouse['tables'][0]['columns']])
            notebook = json.loads((project / 'Sales.Notebook/etl_pipeline.ipynb').read_text(encoding='utf-8'))
            code = '\n'.join(''.join(cell['source']) for cell in notebook['cells'])
            self.assertIn('withColumn("Doubled_Value"', code)
            result = FabricProjectValidator.validate(project)
            self.assertTrue(result['valid'], result['errors'])

    def test_complete_fabric_bundle_is_structurally_valid_but_unbound(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = {'datasources': [{'name': 'Source', 'tables': [
                {'name': 'Orders', 'columns': [{'name': 'Id', 'datatype': 'integer'}]}
            ]}]}
            result = FabricProjectGenerator(temporary).generate_project('Sales', data)
            self.assertTrue(result['validation']['valid'], result['validation']['errors'])
            validation = FabricProjectValidator.validate(result['project_path'])
            self.assertTrue(validation['valid'], validation['errors'])
            self.assertTrue(any('OneLake' in warning for warning in validation['warnings']))
            self.assertTrue(any('connections are not bound' in warning for warning in validation['warnings']))
            self.assertTrue(any('requires binding' in warning for warning in validation['warnings']))

    def test_group_without_members_is_recorded_not_fabricated(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = {'datasources': [{'name': 'Source', 'tables': [
                {'name': 'Orders', 'columns': [{'name': 'Id', 'datatype': 'integer'}]}
            ]}], 'groups': [{'name': 'Unknown Group', 'field': 'Id', 'members': []}]}
            result = FabricProjectGenerator(temporary).generate_project('Sales', data)
            self.assertFalse(result['validation']['valid'])
            self.assertTrue(any('Unsupported BO group: Unknown Group' in message for message in result['validation']['errors']))
            metadata = json.loads((Path(result['project_path']) / 'fabric_project_metadata.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['validation'], result['validation'])
            table = (Path(result['project_path']) / 'Sales.SemanticModel/definition/tables/Orders.tmdl').read_text(encoding='utf-8')
            self.assertNotIn('Unknown Group', table)

    def test_direct_lake_rejects_normalization_collisions_and_binary_columns(self):
        fixtures = [
            [{'name': 'A-B', 'columns': []}, {'name': 'A B', 'columns': []}],
            [{'name': 'Orders', 'columns': [{'name': 'A B'}, {'name': 'A-B'}]}],
            [{'name': 'Orders', 'columns': [{'name': 'Content', 'datatype': 'binary'}]}],
        ]
        for tables in fixtures:
            with self.subTest(tables=tables), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(ValueError):
                    FabricSemanticModelGenerator(temporary, 'Sales').generate({'datasources': [{'name': 'Source', 'tables': tables}]})

    def test_fabric_validator_detects_cross_artifact_and_destination_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = {'datasources': [{'name': 'Source', 'tables': [
                {'name': 'Orders', 'columns': [{'name': 'Id', 'datatype': 'integer'}]}
            ]}]}
            project = Path(FabricProjectGenerator(temporary).generate_project('Sales', data)['project_path'])
            table = project / 'Sales.SemanticModel/definition/tables/Orders.tmdl'
            table.write_text(table.read_text(encoding='utf-8').replace('sourceColumn: Id', 'sourceColumn: MissingColumn'), encoding='utf-8')
            metadata_file = project / 'Sales.Dataflow/queryMetadata.json'
            metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
            metadata['queriesMetadata']['Orders_DataDestination']['loadEnabled'] = True
            metadata_file.write_text(json.dumps(metadata), encoding='utf-8')
            validation = FabricProjectValidator.validate(project)
            self.assertFalse(validation['valid'])
            self.assertTrue(any('MissingColumn' in message for message in validation['errors']))
            self.assertTrue(any('loadEnabled=false' in message for message in validation['errors']))

    def test_notebook_has_persistent_binding_and_executable_cell_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = {'datasources': [{'name': 'Source', 'connection': {'type': 'CSV', 'details': {'filename': 'orders.csv'}}, 'tables': [
                {'name': 'Order Lines', 'columns': [{'name': 'Order Id', 'datatype': 'integer'}]}
            ]}]}
            NotebookGenerator(temporary, 'Sales').generate(data)
            directory = Path(temporary) / 'Sales.Notebook'
            notebook = json.loads((directory / 'etl_pipeline.ipynb').read_text(encoding='utf-8'))
            self.assertEqual(notebook['metadata']['dependencies']['lakehouse']['default_lakehouse'], '{{LAKEHOUSE_ID}}')
            for cell in notebook['cells']:
                if cell['cell_type'] == 'code':
                    self.assertTrue(all(line.endswith('\n') for line in cell['source']))
                    ast.parse(''.join(cell['source']))
            code = '\n'.join(''.join(cell['source']) for cell in notebook['cells'])
            self.assertIn('.saveAsTable("order_lines")', code)
            self.assertIn('.withColumnRenamed("Order Id", "Order_Id")', code)
            self.assertTrue((directory / '.platform').is_file())

    def test_ingestion_has_one_owner_for_file_connected_and_mixed_sources(self):
        for connection_types in [('CSV',), ('SQL Server',), ('CSV', 'SQL Server')]:
            with self.subTest(types=connection_types), tempfile.TemporaryDirectory() as temporary:
                calculation = {'name': 'Doubled', 'caption': 'Doubled', 'formula': '=[Amount] * 2',
                               'role': 'dimension', 'datatype': 'real'}
                datasources = [{'name': f'Source_{index}', 'connection': {'type': kind, 'details': {'filename': 'rows.csv'}},
                                'tables': [{'name': f'Table_{index}', 'columns': [{'name': 'Amount', 'datatype': 'real'}]}]}
                               for index, kind in enumerate(connection_types)]
                data = {'datasources': datasources, 'calculations': [calculation]}
                project = Path(FabricProjectGenerator(temporary).generate_project('Sales', data)['project_path'])
                dataflow = json.loads((project / 'Sales.Dataflow/dataflow_definition.json').read_text(encoding='utf-8'))
                notebook = json.loads((project / 'Sales.Notebook/etl_pipeline.ipynb').read_text(encoding='utf-8'))
                code = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
                pipeline = json.loads((project / 'Sales.Pipeline/pipeline_definition.json').read_text(encoding='utf-8'))
                queries = {query['destination']['tableName'] for query in dataflow['queries']}
                for index, kind in enumerate(connection_types):
                    entity = f'table_{index}'
                    if kind == 'CSV':
                        self.assertNotIn(entity, queries)
                        self.assertEqual(code.count(f'.saveAsTable("{entity}")'), 2 if index == 0 else 1)
                    else:
                        self.assertIn(entity, queries)
                        self.assertNotIn(f'df_{entity} = spark.read', code)
                self.assertNotIn('jdbc:', code)
                self.assertNotIn('Table.AddColumn', dataflow['mashupDocument'])
                self.assertEqual(code.count('withColumn("Doubled"'), 1)
                self.assertFalse((project / 'Sales.Notebook/transformations.ipynb').exists())
                refreshes = [activity for activity in pipeline['properties']['activities'] if activity['type'] == 'RefreshDataflow']
                self.assertEqual(len(refreshes), int('SQL Server' in connection_types))

    def test_table_connection_override_controls_both_ingestion_generators(self):
        datasource = {'connection': {'type': 'SQL Server'},
                      'connection_map': {'file': {'type': 'CSV'}}}
        self.assertTrue(is_file_connection(table_connection(datasource, {'connection': 'file'})))
        self.assertTrue(is_file_connection(table_connection(datasource, {'connection_details': {'type': 'Excel'}})))
        self.assertEqual(table_connection(datasource, {'connection': {'type': 'Oracle'}})['type'], 'Oracle')

    def test_ingestion_plan_rejects_conflicting_source_owners(self):
        data = {'datasources': [
            {'connection': {'type': 'CSV'}, 'tables': [{'name': 'Orders'}]},
            {'connection': {'type': 'SQL Server'}, 'tables': [{'name': 'Orders'}]},
        ]}
        with self.assertRaisesRegex(ValueError, 'Conflicting Fabric ingestion'):
            build_ingestion_plan(data)

    def test_validator_detects_duplicate_or_wrong_notebook_ingestion(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = {'datasources': [{'name': 'Source', 'connection': {'type': 'SQL Server'},
                                    'tables': [{'name': 'Orders', 'columns': [{'name': 'Id', 'datatype': 'integer'}]}]}]}
            result = FabricProjectGenerator(temporary).generate_project('Sales', data)
            self.assertTrue(result['validation']['valid'], result['validation']['errors'])
            notebook_path = Path(result['project_path']) / 'Sales.Notebook/etl_pipeline.ipynb'
            notebook = json.loads(notebook_path.read_text(encoding='utf-8'))
            notebook['cells'].append({'cell_type': 'code', 'source': ['df_wrong.write.saveAsTable("orders")\n']})
            notebook_path.write_text(json.dumps(notebook), encoding='utf-8')
            validation = FabricProjectValidator.validate(result['project_path'])
            self.assertFalse(validation['valid'])
            self.assertTrue(any('Notebook: ingestion targets' in error for error in validation['errors']))

    def test_missing_physical_schema_never_writes_to_an_invented_calculation_table(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = {'datasources': [], 'calculations': [
                {'name': 'Doubled', 'formula': '=[Amount] * 2', 'role': 'dimension'}
            ]}
            NotebookGenerator(temporary, 'Sales').generate(data)
            notebook_path = Path(temporary) / 'Sales.Notebook/etl_pipeline.ipynb'
            notebook = json.loads(notebook_path.read_text(encoding='utf-8'))
            code = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
            self.assertIn('No physical source table metadata', code)
            self.assertNotIn('.saveAsTable("main_table")', code)
            self.assertNotIn('.table("main_table")', code)

    def test_duplicate_delta_calculation_names_never_generate_overwriting_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = {'datasources': [{'tables': [{'name': 'Orders', 'columns': [{'name': 'Amount'}]}]}],
                    'calculations': [
                        {'name': name, 'formula': '=[Amount] * 2', 'role': 'dimension'}
                        for name in ['Margin', 'Margin %']
                    ]}
            NotebookGenerator(temporary, 'Sales').generate(data)
            notebook = json.loads((Path(temporary) / 'Sales.Notebook/etl_pipeline.ipynb').read_text(encoding='utf-8'))
            code = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
            self.assertIn('names collide after Delta normalization', code)
            self.assertNotIn('withColumn("Margin"', code)

    def test_item_logical_ids_are_stable_uuids_not_physical_ids(self):
        import uuid

        item_types = ['Lakehouse', 'Dataflow', 'Notebook', 'SemanticModel', 'DataPipeline']
        ids = [logical_id('Sales', item_type) for item_type in item_types]
        self.assertEqual(len(set(ids)), 5)
        for item_type, item_id in zip(item_types, ids):
            self.assertEqual(str(uuid.UUID(item_id)), item_id)
            self.assertEqual(item_id, logical_id('Sales', item_type))

    def test_dataflow_emits_gen2_definition_parts_and_hidden_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            DataflowGenerator(temporary, 'Sales').generate({'datasources': [
                {'name': 'Source', 'tables': [{'name': 'Order Lines', 'columns': [
                    {'name': 'Order Id', 'datatype': 'integer'}]}]}
            ]})
            directory = Path(temporary) / 'Sales.Dataflow'
            for name in ('mashup.pq', 'queryMetadata.json', '.platform'):
                self.assertTrue((directory / name).is_file())
            metadata = json.loads((directory / 'queryMetadata.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['formatVersion'], '202502')
            destination = metadata['queriesMetadata']['Order Lines_DataDestination']
            self.assertIs(destination['loadEnabled'], False)
            self.assertIs(destination['isHidden'], True)
            mashup = (directory / 'mashup.pq').read_text(encoding='utf-8')
            self.assertIn('[DataDestinations', mashup)
            self.assertIn('shared #"Order Lines"', mashup)
            self.assertIn('IsNewTarget = true', mashup)
            self.assertIn('?[Data]?', mashup)
            self.assertIn('Id = "order_lines"', mashup)
            self.assertIn('{"Order Id", "Order_Id"}', mashup)

    def test_fabric_semantic_model_has_one_definition_level_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            generator = FabricSemanticModelGenerator(temporary, 'Sales')
            data = {'datasources': [{'name': 'Source', 'tables': [
                {'name': 'Orders', 'columns': [{'name': 'Id', 'datatype': 'integer'}]}
            ]}]}
            generator.generate(data)
            model_dir = Path(temporary) / 'Sales.SemanticModel'
            self.assertTrue((model_dir / 'definition/model.tmdl').is_file())
            self.assertFalse((model_dir / 'definition/definition').exists())
            manifest = json.loads((model_dir / 'definition.pbism').read_text(encoding='utf-8'))
            self.assertEqual(manifest['version'], '4.2')

    def test_direct_lake_partitions_reference_shared_onelake_expression(self):
        with tempfile.TemporaryDirectory() as temporary:
            generator = FabricSemanticModelGenerator(temporary, 'Sales')
            data = {'datasources': [{'name': 'Source', 'tables': [
                {'name': 'Order Lines', 'columns': [{'name': 'Order Id', 'datatype': 'integer'}]}
            ]}]}
            generator.generate(data)
            definition = Path(temporary) / 'Sales.SemanticModel/definition'
            table = (definition / 'tables/Order Lines.tmdl').read_text(encoding='utf-8')
            self.assertIn('= entity', table)
            self.assertIn('mode: directLake', table)
            self.assertIn('entityName: order_lines', table)
            self.assertIn('expressionSource: DirectLakeSource', table)
            self.assertIn('sourceColumn: Order_Id', table)
            self.assertNotIn('= m\n', table)
            expressions = (definition / 'expressions.tmdl').read_text(encoding='utf-8')
            self.assertIn('AzureStorage.DataLake', expressions)
            self.assertIn('{{WORKSPACE_ID}}', expressions)
            self.assertIn('ref expression DirectLakeSource', (definition / 'model.tmdl').read_text(encoding='utf-8'))

    def test_import_generation_remains_import(self):
        from powerbi_import.tmdl_generator import generate_tmdl

        with tempfile.TemporaryDirectory() as temporary:
            generate_tmdl([{'name': 'Source', 'tables': [
                {'name': 'Orders', 'columns': [{'name': 'Id', 'datatype': 'integer'}]}
            ]}], 'Sales', {}, temporary)
            table = (Path(temporary) / 'definition/tables/Orders.tmdl').read_text(encoding='utf-8')
            self.assertIn('mode: import', table)
            self.assertNotIn('= entity', table)

    def test_empty_directory_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = build_quality_report(temporary)
            self.assertEqual(report['status'], 'FAIL')
            self.assertEqual(report['summary']['projects'], 0)
            self.assertEqual(list(Path(temporary).iterdir()), [])
            self.assertEqual(report['evidence']['fabric_execution'], 'not_run')

    def test_missing_directory_is_an_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):
                build_quality_report(Path(temporary) / 'missing')

    def test_report_is_stable_and_saved_explicitly(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = build_quality_report(temporary)
            self.assertEqual(first, build_quality_report(temporary))
            output = Path(temporary) / 'quality.json'
            save_quality_report(first, output)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')), first)

    def test_pbip_validator_is_reused_and_warning_fails_only_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / 'Sales'
            project.mkdir()
            (project / 'Sales.pbip').write_text('{}', encoding='utf-8')
            result = {'valid': True, 'errors': [], 'warnings': ['Review a reference'], 'files_checked': 3}
            with patch('powerbi_import.migration_quality.ArtifactValidator.validate_project', return_value=result) as validate:
                self.assertEqual(main(['--validate-project', temporary]), EXIT_SUCCESS)
                self.assertEqual(main(['--validate-project', temporary, '--quality-strict']), EXIT_VALIDATION_ERROR)
                validate.assert_called_with(project)

    def test_cli_fails_on_invalid_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(main(['--validate-project', temporary]), EXIT_VALIDATION_ERROR)

    def test_generation_quality_block_is_reported_before_any_deployment(self):
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as temporary:
            data = {'datasources': [{'name': 'Source', 'tables': [
                {'name': 'Orders', 'columns': [{'name': 'Id', 'datatype': 'integer'}]}
            ]}], 'groups': [{'name': 'MissingMembers', 'members': []}]}
            result = FabricProjectGenerator(temporary).generate_project('Sales', data)
            deployment_module = Mock()
            with patch('bo_export.extract_bo_data.extract_bo_data', return_value={}), \
                 patch('powerbi_import.import_to_powerbi.PowerBIImporter') as importer, \
                 patch.dict('sys.modules', {'powerbi_import.deploy.deployer': deployment_module}):
                importer.return_value.import_all.return_value = result['project_path']
                code = main(['source.wid', '--output-format', 'fabric', '--output-dir', temporary,
                             '--no-optimize-dax', '--deploy', 'synthetic-workspace'])
                self.assertEqual(code, EXIT_VALIDATION_ERROR)
                deployment_module.FabricDeployer.assert_not_called()
            report_path = Path(result['project_path']) / 'quality_report.json'
            self.assertTrue(report_path.is_file())
            self.assertEqual(json.loads(report_path.read_text(encoding='utf-8'))['status'], 'FAIL')

    def test_fabric_checks_required_parts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'fabric_project_metadata.json').write_text('{"project_name": "Sales"}', encoding='utf-8')
            result = FabricProjectValidator.validate(root)
            self.assertFalse(result['valid'])
            self.assertEqual(len(result['errors']), 5)
            report = build_quality_report(root)
            self.assertEqual(report['priorities'][0]['owner'], 'Fabric')

    def test_fabric_rejects_malformed_metadata_and_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for value in ('[]', '{', '{"project_name": "../outside"}'):
                with self.subTest(value=value):
                    (root / 'fabric_project_metadata.json').write_text(value, encoding='utf-8')
                    self.assertFalse(FabricProjectValidator.validate(root)['valid'])

    def test_fabric_pipeline_reports_unknown_dependencies_and_placeholders(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'fabric_project_metadata.json').write_text('{"project_name": "Sales"}', encoding='utf-8')
            pipeline = root / 'Sales.Pipeline'
            pipeline.mkdir()
            document = {'properties': {'activities': [{'name': 'Refresh', 'dependsOn': [{'activity': 'missing'}],
                                                      'typeProperties': {'workspaceId': '{{WORKSPACE_ID}}'}}]}}
            (pipeline / 'pipeline_definition.json').write_text(json.dumps(document), encoding='utf-8')
            result = FabricProjectValidator.validate(root)
            self.assertTrue(any('Unknown Pipeline dependency' in message for message in result['errors']))
            self.assertTrue(any('placeholders' in message for message in result['warnings']))