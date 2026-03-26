"""Compatibility shim: provides the same API that powerbi_import modules
expect from the old ``tableau_export`` package, backed by BO-specific
implementations.

Functions exported here mirror the signatures used by:
    - tmdl_generator.py (from datasource_extractor import ...)
    - tmdl_generator.py (from m_query_builder import ...)
    - dataflow_generator.py, notebook_api.py, etc.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from bo_export.dax_converter import convert_bo_formula_to_dax
from bo_export.m_query_builder import (
    build_m_query,
    build_m_query_for_universe,
    inject_m_steps,
)

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────
# Type mapping: generic / BO types → Power BI data types
# ───────────────────────────────────────────────────────────────

_TYPE_MAP = {
    # BO / generic types   → PBI
    "string": "string",
    "varchar": "string",
    "char": "string",
    "nvarchar": "string",
    "text": "string",
    "integer": "int64",
    "int": "int64",
    "smallint": "int64",
    "bigint": "int64",
    "long": "int64",
    "tinyint": "int64",
    "float": "double",
    "double": "double",
    "real": "double",
    "decimal": "decimal",
    "numeric": "decimal",
    "number": "double",
    "currency": "decimal",
    "money": "decimal",
    "boolean": "boolean",
    "bool": "boolean",
    "date": "dateTime",
    "datetime": "dateTime",
    "timestamp": "dateTime",
    "time": "dateTime",
    "blob": "binary",
    "binary": "binary",
    "image": "binary",
}


def map_bo_to_powerbi_type(bo_type: str) -> str:
    """Map a BO / generic data type to a Power BI TMDL data type string."""
    if not bo_type:
        return "string"
    return _TYPE_MAP.get(bo_type.lower().strip(), "string")


# ── Aliases expected by tmdl_generator (same signature) ──────

def convert_tableau_formula_to_dax(
    formula: str,
    tables: Optional[list] = None,
    columns: Optional[list] = None,
    column_name: str = "",
    table_name: str = "",
    calc_map: Optional[dict] = None,
    param_map: Optional[dict] = None,
    column_table_map: Optional[dict] = None,
    measure_names: Optional[set] = None,
    is_calc_column: bool = False,
    param_values: Optional[dict] = None,
    calc_datatype: str = "",
    **kwargs,
) -> str:
    """Compatibility wrapper — delegates to BO DAX converter.

    Accepts all kwargs used by tmdl_generator (column_name, table_name,
    calc_map, param_map, column_table_map, measure_names, etc.) and
    passes compatible ones through to the BO converter.
    """
    return convert_bo_formula_to_dax(
        formula,
        column_name=column_name,
        table_name=table_name,
        formula_map=calc_map,
        param_map=param_map,
    )


def map_tableau_to_powerbi_type(source_type: str) -> str:
    """Compatibility wrapper — delegates to BO type mapper."""
    return map_bo_to_powerbi_type(source_type)


def generate_power_query_m(datasource_or_connection: dict, table: dict = None, **kwargs) -> str:
    """Generate an M expression from a datasource/connection dict.

    Called by tmdl_generator as ``generate_power_query_m(connection, table)``
    where ``connection`` has keys like type/server/database and ``table``
    has keys like name/columns.
    """
    # Merge connection + table info into one datasource dict for build_m_query
    ds = dict(datasource_or_connection)

    table_names = None
    custom_sql = None

    if table is not None:
        # tmdl_generator passes the table dict as 2nd arg
        tname = table.get("name", "")
        if tname:
            table_names = [tname]
        custom_sql = table.get("sql") or table.get("customSQL")
        # Copy table-level connection details if present
        for k in ("server", "database", "schema", "type"):
            if k in table and k not in ds:
                ds[k] = table[k]
    else:
        table_names = ds.get("tables") or ds.get("table")
        if isinstance(table_names, str):
            table_names = [table_names]
        custom_sql = ds.get("custom_sql") or ds.get("customSQL")

    return build_m_query(ds, tables=table_names, custom_sql=custom_sql)


# ── M transform helpers (stubs matching bo_export.m_query_builder) ──

def m_transform_rename(renames):
    """Rename columns. renames: dict {old_name: new_name}"""
    pairs = ', '.join([f'{{"{old}", "{new}"}}' for old, new in renames.items()])
    return ('#"Renamed Columns"', f'Table.RenameColumns({{prev}}, {{{pairs}}})')


def m_transform_remove_columns(columns):
    """Remove specified columns."""
    cols = ', '.join([f'"{c}"' for c in columns])
    return ('#"Removed Columns"', f'Table.RemoveColumns({{prev}}, {{{cols}}})')


def m_transform_filter_values(column, keep_values):
    """Keep only rows where column matches specified values."""
    if not keep_values:
        return ('#"Filtered Rows"', '{prev}')
    if len(keep_values) == 1:
        condition = f'each [#"{column}"] = "{keep_values[0]}"'
    else:
        vals = ', '.join([f'"{v}"' for v in keep_values])
        condition = f'each List.Contains({{{vals}}}, [#"{column}"])'
    return ('#"Filtered Rows"', f'Table.SelectRows({{prev}}, {condition})')


def m_transform_filter_nulls(column, keep_nulls=False):
    """Filter null or non-null values."""
    op = '=' if keep_nulls else '<>'
    return ('#"Filtered Nulls"', f'Table.SelectRows({{prev}}, each [#"{column}"] {op} null)')


def m_transform_add_column(new_col_name, expression, col_type=None):
    """Add a calculated column."""
    type_arg = f', {col_type}' if col_type else ''
    return (f'#"Added {new_col_name}"',
            f'Table.AddColumn({{prev}}, "{new_col_name}", {expression}{type_arg})')


def wrap_source_with_try_otherwise(m_expr: str, fallback: str = "#table({}, {})") -> str:
    """Wrap an M expression in try/otherwise for resilience."""
    return f"try {m_expr} otherwise {fallback}"


def generate_m_from_hyper(hyper_tables: list, table_name: str = "") -> Optional[str]:
    """Placeholder — BO has no .hyper equivalent. Returns None."""
    return None
