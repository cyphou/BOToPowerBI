"""One connection-resolution and ingestion-routing contract for Fabric generators."""

from .fabric_naming import sanitize_table_name


def table_connection(datasource, table):
    details = table.get('connection_details')
    if isinstance(details, dict) and details.get('type'):
        return details
    reference = table.get('connection')
    if isinstance(reference, dict) and reference.get('type'):
        return reference
    connections = datasource.get('connection_map', {})
    if isinstance(reference, str) and reference in connections:
        return connections[reference]
    connection = datasource.get('connection')
    if not connection and datasource.get('connections'):
        connection = datasource['connections'][0]
    return connection if isinstance(connection, dict) else {}


def is_file_connection(connection):
    return str(connection.get('type', '')).strip().lower() in {'csv', 'excel'}


def datasource_has_connected_tables(datasource):
    return any(not is_file_connection(table_connection(datasource, table))
               for table in datasource.get('tables', []) if table.get('name'))


def build_ingestion_plan(extracted):
    plan = {}
    for datasource in extracted.get('datasources', []):
        for table in datasource.get('tables', []):
            name = table.get('name', '')
            if not name:
                continue
            entity = sanitize_table_name(name)
            owner = 'Notebook' if is_file_connection(table_connection(datasource, table)) else 'Dataflow'
            if entity in plan:
                if plan[entity]['owner'] != owner or plan[entity]['source_table'] != name:
                    raise ValueError(f'Conflicting Fabric ingestion owners or normalized names for {entity}')
                continue
            plan[entity] = {'source_table': name, 'entity': entity, 'owner': owner}
    for query in extracted.get('custom_sql', []):
        name = query.get('name', 'Custom_SQL')
        entity = sanitize_table_name(name)
        if entity in plan and plan[entity]['owner'] != 'Dataflow':
            raise ValueError(f'Custom SQL conflicts with file ingestion for {entity}')
        plan.setdefault(entity, {'source_table': name, 'entity': entity, 'owner': 'Dataflow'})
    return list(plan.values())