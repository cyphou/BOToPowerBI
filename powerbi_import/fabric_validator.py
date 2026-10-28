"""Read-only checks for the five artifacts emitted by the BO Fabric generator."""

import json
import re
import ast
import uuid
from pathlib import Path

from .validator import ArtifactValidator


class FabricProjectValidator:
    ITEM_TYPES = {'Lakehouse': 'Lakehouse', 'Dataflow': 'Dataflow', 'Notebook': 'Notebook',
                  'SemanticModel': 'SemanticModel', 'Pipeline': 'DataPipeline'}
    REQUIRED_PARTS = {
        'Lakehouse': 'lakehouse_definition.json',
        'Dataflow': 'dataflow_definition.json',
        'Notebook': 'etl_pipeline.ipynb',
        'SemanticModel': 'definition/model.tmdl',
        'Pipeline': 'pipeline_definition.json',
    }

    @classmethod
    def validate(cls, project_dir):
        root = Path(project_dir)
        errors = []
        warnings = []
        files_checked = 0
        logical_ids = set()
        lakehouse_tables = {}
        dataflow_targets = []
        notebook_targets = []
        calculated_writes = []
        refresh_activities = []
        if not root.is_dir():
            return {'valid': False, 'errors': ['Fabric project directory does not exist'],
                    'warnings': [], 'files_checked': 0}
        metadata_path = root / 'fabric_project_metadata.json'
        try:
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            name = metadata['project_name']
            if not isinstance(name, str) or not name or Path(name).name != name or '/' in name or '\\' in name:
                raise ValueError('Invalid Fabric project name')
        except (OSError, ValueError, KeyError, TypeError) as error:
            return {'valid': False, 'errors': [f'Invalid Fabric metadata: {error}'],
                    'warnings': [], 'files_checked': 0}

        for suffix, relative_part in cls.REQUIRED_PARTS.items():
            part = root / f'{name}.{suffix}' / relative_part
            if not part.is_file():
                errors.append(f'Missing {suffix} part: {relative_part}')
                continue
            files_checked += 1
            item_directory = root / f'{name}.{suffix}'
            try:
                platform = json.loads((item_directory / '.platform').read_text(encoding='utf-8'))
                if platform.get('metadata', {}).get('type') != cls.ITEM_TYPES[suffix]:
                    errors.append(f'{suffix}: incorrect .platform item type')
                item_id = str(uuid.UUID(platform.get('config', {}).get('logicalId')))
                if item_id in logical_ids:
                    errors.append(f'{suffix}: duplicate logicalId')
                logical_ids.add(item_id)
                files_checked += 1
            except (OSError, ValueError, TypeError, AttributeError) as error:
                errors.append(f'{suffix}: invalid or missing .platform: {error}')
            try:
                if part.suffix == '.tmdl':
                    model_metadata = json.loads((item_directory / 'semantic_model_metadata.json').read_text(encoding='utf-8'))
                    for feature in model_metadata.get('stats', {}).get('unsupported_features', []):
                        errors.append(f'Unsupported BO {feature.get("kind")}: {feature.get("name")}; {feature.get("reason")}')
                    for feature in model_metadata.get('stats', {}).get('deferred_features', []):
                        warnings.append(f'Deferred {feature.get("kind")}: {feature.get("reason")}')
                    if not (item_directory / 'definition.pbism').is_file():
                        errors.append('SemanticModel: missing definition.pbism')
                    expressions = (part.parent / 'expressions.tmdl').read_text(encoding='utf-8')
                    if 'AzureStorage.DataLake(' not in expressions or 'expression DirectLakeSource' not in expressions:
                        errors.append('SemanticModel: missing shared OneLake expression')
                    if re.search(r'\{\{[^{}]+\}\}', expressions):
                        warnings.append('SemanticModel has unbound OneLake workspace/lakehouse parameters')
                    if 'defaultMode: directLake' not in part.read_text(encoding='utf-8'):
                        errors.append('SemanticModel: defaultMode is not directLake')
                    valid, issues = ArtifactValidator.validate_tmdl_file(part)
                    errors.extend(issues)
                    if valid:
                        warnings.extend(ArtifactValidator.validate_tmdl_dax(part))
                    for table in sorted((part.parent / 'tables').glob('*.tmdl')):
                        files_checked += 1
                        content = table.read_text(encoding='utf-8')
                        errors.extend(ArtifactValidator.validate_tmdl_file(table)[1])
                        warnings.extend(ArtifactValidator.validate_tmdl_dax(table))
                        if re.search(r'^\s*partition\s+.+?=\s*m\s*$', content, re.MULTILINE):
                            errors.append(f'{table.name}: M partition remains in the Fabric semantic model')
                        if '= calculated' in content and 'mode: import' in content:
                            warnings.append(f'{table.name}: calculated auxiliary table remains Import; review Direct Lake compatibility')
                        for entity in re.findall(r'^\s*entityName:\s*(\S+)\s*$', content, re.MULTILINE):
                            if entity not in lakehouse_tables:
                                errors.append(f'{table.name}: entity {entity} is missing from the Lakehouse')
                            else:
                                for column in re.findall(r'^\s*sourceColumn:\s*(\S+)\s*$', content, re.MULTILINE):
                                    if column not in lakehouse_tables[entity]:
                                        errors.append(f'{table.name}: sourceColumn {column} is missing from Lakehouse entity {entity}')
                            if 'mode: directLake' not in content or 'expressionSource: DirectLakeSource' not in content:
                                errors.append(f'{table.name}: invalid Direct Lake partition contract')
                else:
                    document = json.loads(part.read_text(encoding='utf-8'))
                    if not isinstance(document, dict):
                        raise ValueError('Artifact must be a JSON object')
                    if suffix == 'Lakehouse':
                        tables = document.get('tables', [])
                        names = [table['name'] for table in tables]
                        if len(names) != len(set(names)):
                            errors.append('Lakehouse: duplicate normalized table names')
                        lakehouse_tables = {table['name']: {column['name'] for column in table.get('columns', [])}
                                            for table in tables}
                    if suffix == 'Dataflow':
                        query_metadata = json.loads((item_directory / 'queryMetadata.json').read_text(encoding='utf-8'))
                        if query_metadata.get('formatVersion') != '202502':
                            errors.append('Dataflow: queryMetadata.json formatVersion must be 202502')
                        if query_metadata.get('name') != document.get('properties', {}).get('displayName'):
                            errors.append('Dataflow: queryMetadata.json name differs from displayName')
                        if document.get('queries') and not query_metadata.get('connections'):
                            warnings.append('Dataflow: source and destination connections are not bound')
                        mashup = (item_directory / 'mashup.pq').read_text(encoding='utf-8')
                        if mashup != document.get('mashupDocument'):
                            errors.append('Dataflow: mashup.pq differs from the local definition')
                        queries = document.get('queries', [])
                        if mashup.count('[DataDestinations = {') != len(queries):
                            errors.append('Dataflow: destination annotations do not match source queries')
                        for query in queries:
                            dataflow_targets.append(query.get('destination', {}).get('tableName'))
                            helper_name = query['name'] + '_DataDestination'
                            helper = query_metadata.get('queriesMetadata', {}).get(helper_name, {})
                            if helper.get('loadEnabled') is not False or helper.get('isHidden') is not True:
                                errors.append(f'Dataflow: {helper_name} must be hidden with loadEnabled=false')
                            if query.get('destination', {}).get('tableName') not in lakehouse_tables:
                                errors.append(f'Dataflow: destination for {query["name"]} is missing from the Lakehouse')
                            if re.search(r'\bTable\.AddColumn\s*\(', mashup):
                                errors.append('Dataflow: calculated-column materialization belongs to Notebook only')
                        if '{{' in mashup:
                            warnings.append('Dataflow: destination workspace/lakehouse placeholders require binding')
                    if suffix == 'Notebook':
                        if (item_directory / 'transformations.ipynb').exists():
                            errors.append('Notebook: duplicate transformations artifact; use the primary ETL notebook only')
                        if document.get('nbformat') != 4 or not isinstance(document.get('cells'), list):
                            errors.append('Invalid notebook format or cells')
                        binding = document.get('metadata', {}).get('dependencies', {}).get('lakehouse', {})
                        if not binding.get('default_lakehouse') or not binding.get('default_lakehouse_workspace_id'):
                            errors.append('Notebook: missing persistent lakehouse dependency')
                        elif '{{' in json.dumps(binding):
                            warnings.append('Notebook: default lakehouse dependency requires binding')
                        for cell in document.get('cells', []):
                            if cell.get('cell_type') == 'code':
                                source = cell.get('source', [])
                                if isinstance(source, list) and any(not line.endswith('\n') for line in source):
                                    errors.append('Notebook: source lines must end with newline')
                                code = ''.join(source) if isinstance(source, list) else source
                                if not code.lstrip().startswith('%%'):
                                    try:
                                        tree = ast.parse(code)
                                        for node in ast.walk(tree):
                                            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                                                continue
                                            if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                                                continue
                                            if node.func.attr == 'saveAsTable' and any(
                                                isinstance(item, ast.Name) and item.id.startswith('df_')
                                                for item in ast.walk(node.func.value)
                                            ):
                                                notebook_targets.append(node.args[0].value)
                                            if node.func.attr == 'withColumn':
                                                calculated_writes.append(node.args[0].value)
                                    except SyntaxError as error:
                                        errors.append(f'Notebook: invalid Python cell: {error}')
                                if '<username>' in code or '<password>' in code or 'TODO:' in code:
                                    warnings.append('Notebook: source configuration or credentials still require setup')
                                if 'raise NotImplementedError(' in code:
                                    errors.append('Notebook: unsupported BO calculation requires source ordering or manual materialization')
                    if suffix == 'Pipeline':
                        activities = document.get('properties', {}).get('activities', [])
                        refresh_activities = [activity for activity in activities if activity.get('type') == 'RefreshDataflow']
                        notebook_activities = [activity for activity in activities if activity.get('type') == 'TridentNotebook']
                        if len(notebook_activities) != 1:
                            errors.append('Pipeline must execute the primary ETL notebook exactly once')
                        elif {dependency.get('activity') for dependency in notebook_activities[0].get('dependsOn', [])} != {
                            activity.get('name') for activity in refresh_activities
                        }:
                            errors.append('Pipeline: ETL notebook must depend on every Dataflow refresh')
                        names = [activity.get('name') for activity in activities]
                        if not names or None in names or len(names) != len(set(names)):
                            errors.append('Pipeline activity names must be nonempty and unique')
                        for activity in activities:
                            for dependency in activity.get('dependsOn', []):
                                if dependency.get('activity') not in names:
                                    errors.append(f'Unknown Pipeline dependency: {dependency.get("activity")}')
                        pending = {activity['name']: {dependency.get('activity') for dependency in activity.get('dependsOn', [])}
                                   for activity in activities if activity.get('name')}
                        while pending:
                            ready = {activity for activity, dependencies in pending.items() if not dependencies.intersection(pending)}
                            if not ready:
                                errors.append('Pipeline contains a dependency cycle')
                                break
                            pending = {activity: dependencies for activity, dependencies in pending.items() if activity not in ready}
                        if re.search(r'\{\{[^{}]+\}\}', json.dumps(document)):
                            warnings.append('Pipeline contains unbound workspace/item placeholders')
            except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
                errors.append(f'{suffix}: {error}')
        if 'ingestion_plan' in metadata:
            try:
                expected = {'Dataflow': set(), 'Notebook': set()}
                assigned = set()
                for source in metadata['ingestion_plan']:
                    entity = source['entity']
                    owner = source['owner']
                    if entity in assigned or owner not in expected:
                        errors.append('Ingestion plan has duplicate entities or unknown owners')
                        continue
                    assigned.add(entity)
                    expected[owner].add(entity)
                for owner, actual in [('Dataflow', dataflow_targets), ('Notebook', notebook_targets)]:
                    if set(actual) != expected[owner] or len(actual) != len(set(actual)):
                        errors.append(f'{owner}: ingestion targets do not match the unique-owner plan')
                if len(refresh_activities) != int(bool(expected['Dataflow'])):
                    errors.append('Pipeline: refresh count does not match connected-source ingestion')
                materialization = metadata.get('materialization', {})
                if materialization.get('owner') != 'Notebook':
                    errors.append('Calculated columns must be owned by Notebook')
                columns = materialization.get('columns', [])
                if len(columns) != len(set(columns)) or any(calculated_writes.count(column) != 1 for column in columns):
                    errors.append('Notebook: each calculated column must be materialized exactly once')
                entity = materialization.get('entity')
                if columns and entity is None:
                    errors.append('Notebook: unsupported BO calculation target; physical source table metadata is unavailable')
                elif columns and (entity not in lakehouse_tables or not set(columns).issubset(lakehouse_tables[entity])):
                    errors.append('Materialized columns are missing from the target Lakehouse schema')
            except (KeyError, TypeError) as error:
                errors.append(f'Invalid ingestion plan: {error}')
        return {'valid': not errors, 'errors': errors, 'warnings': warnings,
                'files_checked': files_checked}