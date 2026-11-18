"""One connection-resolution and ingestion-routing contract for Fabric generators."""

from .fabric_naming import sanitize_column_name, sanitize_table_name


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


def column_source_mappings(table):
    """Return physical, Delta, and explicit-source names for a table."""
    mappings = [
        (column.get('sourceColumn') or column['name'],
         sanitize_column_name(column['name']), bool(column.get('sourceColumn')))
        for column in table.get('columns', []) if column.get('name')
    ]
    if not any(explicit for _, _, explicit in mappings):
        return mappings

    sources = {}
    targets = {}
    for source, target, _ in mappings:
        source_key, target_key = source.casefold(), target.casefold()
        if source_key in sources and sources[source_key] != target_key:
            raise ValueError(f'Fabric source column {source!r} in {table.get("name")!r} maps to multiple Delta columns')
        if target_key in targets:
            raise ValueError(f'Fabric Delta column {target!r} in {table.get("name")!r} is duplicated')
        sources[source_key] = target_key
        targets[target_key] = source_key
    for source, target, _ in mappings:
        source_key, target_key = source.casefold(), target.casefold()
        if source_key != target_key and target_key in sources and sources[target_key] != target_key:
            raise ValueError(f'Ambiguous Fabric column rename {source!r} to {target!r} in {table.get("name")!r}')
    return mappings


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