"""Shared test fixtures for BO to Power BI migration tests."""

import json
import os
import tempfile
import unittest


def make_temp_dir():
    """Create a temporary directory for test output."""
    return tempfile.mkdtemp(prefix="bo_migrate_test_")


def make_sample_extracted_data():
    """Create sample extracted data matching the 15-type JSON format."""
    return {
        "reports": [
            {"name": "Sales Report", "type": "report", "sections": []}
        ],
        "queries": [
            {"name": "Query1", "type": "universe", "universe": "Sales Universe",
             "sql": "", "objects": [
                 {"name": "Revenue", "qualification": "measure", "path": "\\Sales\\Revenue"},
                 {"name": "Country", "qualification": "dimension", "path": "\\Geography\\Country"},
             ]}
        ],
        "datasources": [
            {"name": "SalesDB", "type": "sql_server", "server": "sql-server.company.com",
             "database": "SalesDB", "universe": "Sales Universe"}
        ],
        "formulas": [
            {"name": "Total Revenue", "formula": "=Sum([Revenue])", "qualification": "measure", "data_type": "number"},
            {"name": "Revenue Per Unit", "formula": "=[Revenue]/[Quantity]", "qualification": "measure", "data_type": "number"},
            {"name": "Is High Value", "formula": "=If [Revenue]>1000 Then \"Yes\" Else \"No\"", "qualification": "dimension", "data_type": "string"},
        ],
        "prompts": [
            {"name": "Select Country", "type": "text", "required": True, "multi_value": True,
             "default_values": ["USA", "UK"], "lov_type": "dynamic", "associated_dimension": "Country"}
        ],
        "filters": [
            {"name": "Active Only", "type": "query", "operator": "Equal To",
             "object": "Status", "values": ["Active"]}
        ],
        "tables": [
            {"name": "Sales", "schema": "dbo", "type": "table", "source": "universe"},
            {"name": "Geography", "schema": "dbo", "type": "table", "source": "universe"},
        ],
        "columns": [
            {"name": "Revenue", "table": "Sales", "data_type": "number", "qualification": "measure"},
            {"name": "Quantity", "table": "Sales", "data_type": "number", "qualification": "measure"},
            {"name": "Country", "table": "Geography", "data_type": "string", "qualification": "dimension"},
            {"name": "City", "table": "Geography", "data_type": "string", "qualification": "dimension"},
        ],
        "joins": [
            {"left_table": "Sales", "right_table": "Geography",
             "left_column": "GeoID", "right_column": "GeoID",
             "type": "inner", "cardinality": "many-to-one"}
        ],
        "groups": [
            {"name": "Country Group", "object": "Country", "sort_order": "ascending"}
        ],
        "sorts": [
            {"object": "Revenue", "order": "descending", "type": "value"}
        ],
        "alerts": [
            {"name": "High Revenue Alert", "condition": "[Revenue] > 10000", "format": "red_bold"}
        ],
        "subreports": [],
        "charts": [
            {"name": "Revenue by Country", "type": "bar", "title": "Revenue by Country"}
        ],
        "custom_sql": [],
    }


def write_extracted_data(output_dir, data=None):
    """Write sample extracted data to JSON files."""
    if data is None:
        data = make_sample_extracted_data()
    os.makedirs(output_dir, exist_ok=True)
    for key, value in data.items():
        with open(os.path.join(output_dir, f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2)
    return data
