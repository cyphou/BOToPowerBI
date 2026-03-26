"""Power Query M expression builder for BO datasource connections.

Generates Power Query M expressions for connecting to data sources
referenced by BusinessObjects universes and reports.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Connector templates for M query generation
CONNECTOR_TEMPLATES = {
    "sql_server": 'Sql.Database("{server}", "{database}")',
    "oracle": 'Oracle.Database("{server}")',
    "sap_hana": 'SapHana.Database("{server}")',
    "sap_bw": 'SapBusinessWarehouse.Cubes("{server}")',
    "postgresql": 'PostgreSQL.Database("{server}", "{database}")',
    "mysql": 'MySQL.Database("{server}", "{database}")',
    "db2": 'DB2.Database("{server}", "{database}")',
    "teradata": 'Teradata.Database("{server}")',
    "snowflake": 'Snowflake.Databases("{server}", "{warehouse}")',
    "odbc": 'Odbc.DataSource("{connection_string}")',
    "oledb": 'OleDb.DataSource("{connection_string}")',
    "excel": 'Excel.Workbook(File.Contents("{file_path}"))',
    "csv": 'Csv.Document(File.Contents("{file_path}"))',
    "sharepoint": 'SharePoint.Tables("{site_url}")',
    "web": 'Web.Contents("{url}")',
}

# TRANSFORM_GENERATORS is defined at the bottom of the file after all
# generator functions are declared. See _init_transform_generators().


def build_m_query(datasource, tables=None, transforms=None, custom_sql=None):
    """Build a complete Power Query M expression for a datasource.

    Args:
        datasource: Dict with connection info (type, server, database, etc.).
        tables: List of table names to include.
        transforms: List of transform dicts (type, params).
        custom_sql: Optional SQL query to use instead of table navigation.

    Returns:
        str: Complete M query expression.
    """
    ds_type = _normalize_datasource_type(datasource.get("type", ""))
    template = CONNECTOR_TEMPLATES.get(ds_type, CONNECTOR_TEMPLATES.get("odbc"))

    if template is None:
        logger.warning("Unsupported datasource type: %s", ds_type)
        return f'// Unsupported datasource type: {ds_type}\n#table(type table [], {{}})'

    # Build connection step
    connection_m = _build_connection(template, datasource)

    # Build steps
    steps = [("Source", connection_m)]

    if custom_sql:
        # Use Value.NativeQuery for custom SQL
        escaped_sql = _m_escape_string(custom_sql)
        steps.append(("CustomSQL", f'Value.NativeQuery(Source, "{escaped_sql}")'))
    elif tables:
        # Navigate to specific table
        table_name = tables[0] if isinstance(tables, list) else tables
        schema = datasource.get("schema", "dbo")
        steps.append(("Navigation", f'Source{{[Schema="{schema}", Item="{table_name}"]}}[Data]'))

    # Apply transforms
    if transforms:
        for transform in transforms:
            t_type = transform.get("type", "")
            generator = TRANSFORM_GENERATORS.get(t_type)
            if generator:
                step_name, step_expr = generator(transform, len(steps))
                steps.append((step_name, step_expr))

    return _assemble_m_query(steps)


def build_m_query_for_universe(datasource, universe_tables, columns, joins):
    """Build M query from universe metadata (tables, columns, joins).

    Args:
        datasource: Connection info dict.
        universe_tables: List of table dicts from universe extraction.
        columns: List of column dicts.
        joins: List of join dicts.

    Returns:
        dict: Table name → M query mapping.
    """
    queries = {}

    for table in universe_tables:
        table_name = table.get("name", "")
        if not table_name:
            continue

        if table.get("type") == "derived" and table.get("sql"):
            # Derived table → Value.NativeQuery
            queries[table_name] = build_m_query(
                datasource, custom_sql=table["sql"]
            )
        else:
            # Regular table → navigation
            queries[table_name] = build_m_query(
                datasource, tables=[table_name]
            )

    return queries


def inject_m_steps(base_query, steps):
    """Inject additional transformation steps into an existing M query.

    Args:
        base_query: Existing M query string.
        steps: List of (step_name, step_expression) tuples.

    Returns:
        str: Modified M query with injected steps.
    """
    if not steps:
        return base_query

    # Find the last step name before "in"
    in_match = re.search(r"\bin\b\s*$", base_query, re.MULTILINE | re.IGNORECASE)
    if not in_match:
        return base_query

    # Deduplicate step names
    existing_names = set(re.findall(r'#?"(\w+)"\s*=', base_query))
    deduped_steps = []
    for name, expr in steps:
        original = name
        counter = 2
        while name in existing_names:
            name = f"{original}_{counter}"
            counter += 1
        existing_names.add(name)
        deduped_steps.append((name, expr))

    # Insert steps before "in"
    insert_point = in_match.start()
    prev_step = _get_last_step_name(base_query[:insert_point])

    new_lines = []
    for name, expr in deduped_steps:
        expr = expr.replace("{prev}", f'#"{prev_step}"' if " " in prev_step else prev_step)
        new_lines.append(f'    #"{name}" = {expr}')
        prev_step = name

    injected = ",\n".join(new_lines)
    result = base_query[:insert_point].rstrip(",\n") + ",\n" + injected + "\nin\n    " + f'#"{prev_step}"'
    return result


def _build_connection(template, datasource):
    """Fill connection template with datasource parameters."""
    params = {
        "server": _m_escape_string(datasource.get("server", "")),
        "database": _m_escape_string(datasource.get("database", "")),
        "warehouse": _m_escape_string(datasource.get("warehouse", "")),
        "connection_string": _m_escape_string(datasource.get("connection_string", "")),
        "file_path": _m_escape_string(datasource.get("file_path", "")),
        "site_url": _m_escape_string(datasource.get("site_url", "")),
        "url": _m_escape_string(datasource.get("url", "")),
    }
    return template.format(**params)


def _assemble_m_query(steps):
    """Assemble steps into a complete M let/in expression."""
    if not steps:
        return '#table(type table [], {{}})'

    lines = ["let"]
    for i, (name, expr) in enumerate(steps):
        comma = "," if i < len(steps) - 1 else ""
        lines.append(f'    #"{name}" = {expr}{comma}')

    last_name = steps[-1][0]
    lines.append("in")
    lines.append(f'    #"{last_name}"')

    return "\n".join(lines)


def _normalize_datasource_type(ds_type):
    """Normalize datasource type string to connector key."""
    # Normalize to lowercase, collapse separators
    ds_lower = ds_type.lower().replace("_", " ").replace("-", " ").strip()

    type_map = {
        "sql server": "sql_server",
        "sqlserver": "sql_server",
        "mssql": "sql_server",
        "oracle": "oracle",
        "sap hana": "sap_hana",
        "hana": "sap_hana",
        "sap bw": "sap_bw",
        "bw": "sap_bw",
        "postgresql": "postgresql",
        "postgres": "postgresql",
        "mysql": "mysql",
        "db2": "db2",
        "teradata": "teradata",
        "snowflake": "snowflake",
        "odbc": "odbc",
        "oledb": "oledb",
        "excel": "excel",
        "csv": "csv",
        "sharepoint": "sharepoint",
        "web": "web",
    }

    for key, value in type_map.items():
        if key in ds_lower:
            return value

    return "odbc"  # fallback


def _m_escape_string(value):
    """Escape a string for use in M query literals."""
    if not value:
        return ""
    return value.replace('"', '""').replace("\\", "\\\\")


def _get_last_step_name(m_text):
    """Get the name of the last defined step in M query text."""
    matches = re.findall(r'#?"(\w+)"\s*=', m_text)
    return matches[-1] if matches else "Source"


# ===============================================================
# Transform step generators
# ===============================================================

def _generate_rename_step(transform, step_index):
    renames = transform.get("renames", {})
    pairs = ", ".join(f'{{"{old}", "{new}"}}' for old, new in renames.items())
    return (f"Renamed_{step_index}", f"Table.RenameColumns({{prev}}, {{{pairs}}})")


def _generate_filter_step(transform, step_index):
    column = transform.get("column", "")
    operator = transform.get("operator", "=")
    value = transform.get("value", "")
    return (f"Filtered_{step_index}", f'Table.SelectRows({{prev}}, each [#{column}] {operator} "{value}")')


def _generate_aggregate_step(transform, step_index):
    group_cols = transform.get("group_by", [])
    agg_col = transform.get("column", "")
    agg_func = transform.get("function", "List.Sum")
    groups = ", ".join(f'"{c}"' for c in group_cols)
    return (f"Aggregated_{step_index}", f'Table.Group({{prev}}, {{{groups}}}, {{{{"{agg_col}", each {agg_func}([{agg_col}])}}}})')


def _generate_sort_step(transform, step_index):
    column = transform.get("column", "")
    order = "Order.Ascending" if transform.get("order", "asc") == "asc" else "Order.Descending"
    return (f"Sorted_{step_index}", f'Table.Sort({{prev}}, {{{{"{column}", {order}}}}})')


def _generate_select_columns_step(transform, step_index):
    columns = transform.get("columns", [])
    cols = ", ".join(f'"{c}"' for c in columns)
    return (f"Selected_{step_index}", f"Table.SelectColumns({{prev}}, {{{cols}}})")


def _generate_change_type_step(transform, step_index):
    column = transform.get("column", "")
    target_type = transform.get("target_type", "type text")
    return (f"ChangedType_{step_index}", f'Table.TransformColumnTypes({{prev}}, {{{{"{column}", {target_type}}}}})')


def _generate_add_column_step(transform, step_index):
    name = transform.get("name", "NewColumn")
    expression = transform.get("expression", "null")
    return (f"Added_{step_index}", f'Table.AddColumn({{prev}}, "{name}", each {expression})')


def _generate_group_by_step(transform, step_index):
    return _generate_aggregate_step(transform, step_index)


def _generate_merge_step(transform, step_index):
    right_table = transform.get("right_table", "")
    left_key = transform.get("left_key", "")
    right_key = transform.get("right_key", "")
    join_kind = transform.get("join_kind", "JoinKind.LeftOuter")
    return (f"Merged_{step_index}", f'Table.NestedJoin({{prev}}, "{left_key}", {right_table}, "{right_key}", "Merged", {join_kind})')


def _generate_append_step(transform, step_index):
    other_table = transform.get("other_table", "")
    return (f"Appended_{step_index}", f"Table.Combine({{{{prev}}, {other_table}}})")


def _generate_pivot_step(transform, step_index):
    column = transform.get("column", "")
    value_column = transform.get("value_column", "")
    return (f"Pivoted_{step_index}", f'Table.Pivot({{prev}}, List.Distinct({{prev}}[{column}]), "{column}", "{value_column}")')


def _generate_unpivot_step(transform, step_index):
    columns = transform.get("columns", [])
    cols = ", ".join(f'"{c}"' for c in columns)
    return (f"Unpivoted_{step_index}", f"Table.UnpivotOtherColumns({{prev}}, {{{cols}}}, \"Attribute\", \"Value\")")


def _generate_custom_sql_step(transform, step_index):
    sql = _m_escape_string(transform.get("sql", ""))
    return (f"CustomSQL_{step_index}", f'Value.NativeQuery({{prev}}, "{sql}")')


# M transformation step generators — defined after all functions
TRANSFORM_GENERATORS = {
    "rename": _generate_rename_step,
    "filter": _generate_filter_step,
    "aggregate": _generate_aggregate_step,
    "sort": _generate_sort_step,
    "select_columns": _generate_select_columns_step,
    "change_type": _generate_change_type_step,
    "add_column": _generate_add_column_step,
    "group_by": _generate_group_by_step,
    "merge": _generate_merge_step,
    "append": _generate_append_step,
    "pivot": _generate_pivot_step,
    "unpivot": _generate_unpivot_step,
    "custom_sql": _generate_custom_sql_step,
}
