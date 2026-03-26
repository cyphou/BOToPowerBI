"""Tests for Phase 10: Semantic Model Intelligence.

Tests star/snowflake detection, lineage mapping, impact analysis,
measure deduplication, relationship optimization, and model quality scoring.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from powerbi_import.semantic_intelligence import (
    detect_star_schema,
    optimize_relationships,
    build_lineage_map,
    analyze_impact,
    find_duplicate_measures,
    score_model_quality,
)


# ── Sample data fixtures ────────────────────────────────────────────

@pytest.fixture
def star_schema_data():
    """Classic star schema: 1 fact table + 3 dimension tables."""
    return {
        "tables": [
            {"name": "FactSales"},
            {"name": "DimProduct"},
            {"name": "DimCustomer"},
            {"name": "DimDate"},
        ],
        "columns": [
            {"name": "Amount", "table": "FactSales", "qualification": "measure", "data_type": "number"},
            {"name": "Quantity", "table": "FactSales", "qualification": "measure", "data_type": "number"},
            {"name": "ProductKey", "table": "FactSales", "qualification": "dimension", "data_type": "int"},
            {"name": "CustomerKey", "table": "FactSales", "qualification": "dimension", "data_type": "int"},
            {"name": "DateKey", "table": "FactSales", "qualification": "dimension", "data_type": "int"},
            {"name": "ProductKey", "table": "DimProduct", "qualification": "dimension", "data_type": "int"},
            {"name": "ProductName", "table": "DimProduct", "qualification": "dimension", "data_type": "string"},
            {"name": "CustomerKey", "table": "DimCustomer", "qualification": "dimension", "data_type": "int"},
            {"name": "CustomerName", "table": "DimCustomer", "qualification": "dimension", "data_type": "string"},
            {"name": "DateKey", "table": "DimDate", "qualification": "dimension", "data_type": "int"},
            {"name": "Year", "table": "DimDate", "qualification": "dimension", "data_type": "int"},
        ],
        "joins": [
            {"left_table": "FactSales", "right_table": "DimProduct", "left_column": "ProductKey", "right_column": "ProductKey"},
            {"left_table": "FactSales", "right_table": "DimCustomer", "left_column": "CustomerKey", "right_column": "CustomerKey"},
            {"left_table": "FactSales", "right_table": "DimDate", "left_column": "DateKey", "right_column": "DateKey"},
        ],
        "formulas": [
            {"name": "Total Sales", "formula": "SUM(Amount)", "dax": "SUM('FactSales'[Amount])"},
            {"name": "Avg Qty", "formula": "AVG(Quantity)", "dax": "AVERAGE('FactSales'[Quantity])"},
        ],
        "charts": [
            {"name": "Sales by Product", "type": "bar", "dimensions": ["ProductName"], "measures": ["Amount"]},
        ],
        "filters": [],
        "prompts": [],
        "subreports": [],
        "reports": [{"name": "Sales Dashboard"}],
    }


@pytest.fixture
def flat_table_data():
    """Single flat table with no joins."""
    return {
        "tables": [{"name": "FlatData"}],
        "columns": [
            {"name": "Name", "table": "FlatData", "qualification": "dimension", "data_type": "string"},
            {"name": "Value", "table": "FlatData", "qualification": "measure", "data_type": "number"},
        ],
        "joins": [],
        "formulas": [],
        "charts": [],
        "filters": [],
        "prompts": [],
        "subreports": [],
        "reports": [],
    }


# ── Star Schema Detection ────────────────────────────────────────

class TestStarSchemaDetection:
    def test_detects_star_schema(self, star_schema_data):
        result = detect_star_schema(star_schema_data)
        assert result["schema_type"] == "star"
        assert len(result["fact_tables"]) >= 1
        assert len(result["dimension_tables"]) >= 2

    def test_detects_flat_schema(self, flat_table_data):
        result = detect_star_schema(flat_table_data)
        assert result["schema_type"] == "flat"

    def test_empty_data(self):
        result = detect_star_schema({"tables": [], "columns": [], "joins": []})
        assert result["schema_type"] == "unknown"
        assert result["fact_tables"] == []
        assert result["dimension_tables"] == []

    def test_fact_table_has_measures(self, star_schema_data):
        result = detect_star_schema(star_schema_data)
        fact_names = {f["name"] for f in result["fact_tables"]}
        assert "FactSales" in fact_names

    def test_dimension_tables_have_keys(self, star_schema_data):
        result = detect_star_schema(star_schema_data)
        dim_names = {d["name"] for d in result["dimension_tables"]}
        for expected in ("DimProduct", "DimCustomer", "DimDate"):
            assert expected in dim_names

    def test_relationships_have_cardinality(self, star_schema_data):
        result = detect_star_schema(star_schema_data)
        for rel in result["relationships"]:
            assert rel["cardinality"] in ("manyToOne", "oneToMany", "manyToMany")


# ── Relationship Optimization ────────────────────────────────────

class TestOptimizeRelationships:
    def test_detects_redundant_joins(self):
        data = {
            "joins": [
                {"left_table": "A", "right_table": "B", "left_column": "id", "right_column": "id"},
                {"left_table": "A", "right_table": "B", "left_column": "id2", "right_column": "id2"},
            ]
        }
        result = optimize_relationships(data)
        assert len(result["redundant"]) == 1

    def test_no_redundant_joins(self, star_schema_data):
        result = optimize_relationships(star_schema_data)
        assert len(result["redundant"]) == 0

    def test_empty_joins(self):
        result = optimize_relationships({"joins": []})
        assert result["redundant"] == []
        assert result["conflicting"] == []


# ── Lineage Map ──────────────────────────────────────────────────

class TestLineageMap:
    def test_builds_nodes_and_edges(self, star_schema_data):
        result = build_lineage_map(star_schema_data)
        assert len(result["nodes"]) > 0
        assert len(result["edges"]) > 0

    def test_node_types(self, star_schema_data):
        result = build_lineage_map(star_schema_data)
        types = {n["type"] for n in result["nodes"]}
        assert "source_table" in types
        assert "column" in types

    def test_measure_nodes(self, star_schema_data):
        result = build_lineage_map(star_schema_data)
        measure_nodes = [n for n in result["nodes"] if n["type"] == "measure"]
        assert len(measure_nodes) == 2  # Total Sales, Avg Qty

    def test_empty_data(self):
        result = build_lineage_map({"tables": [], "columns": [], "formulas": [], "charts": []})
        assert result["nodes"] == []
        assert result["edges"] == []


# ── Impact Analysis ──────────────────────────────────────────────

class TestImpactAnalysis:
    def test_column_removal_affects_formulas(self, star_schema_data):
        changes = [
            {"type": "remove", "category": "column", "name": "Amount", "table": "FactSales"},
        ]
        result = analyze_impact(changes, star_schema_data)
        assert result["total_affected"] > 0
        assert len(result["affected_formulas"]) >= 1
        assert result["risk_level"] in ("medium", "high", "critical")

    def test_no_impact_from_unused_column(self, star_schema_data):
        changes = [
            {"type": "remove", "category": "column", "name": "UnusedField", "table": "Other"},
        ]
        result = analyze_impact(changes, star_schema_data)
        assert result["total_affected"] == 0
        assert result["risk_level"] == "low"

    def test_table_removal(self, star_schema_data):
        star_schema_data["queries"] = [{"name": "Q1", "tables": [{"name": "FactSales"}]}]
        changes = [{"type": "remove", "category": "table", "name": "FactSales"}]
        result = analyze_impact(changes, star_schema_data)
        assert len(result["affected_queries"]) >= 1

    def test_empty_changes(self, star_schema_data):
        result = analyze_impact([], star_schema_data)
        assert result["total_affected"] == 0
        assert result["risk_level"] == "low"


# ── Measure Deduplication ────────────────────────────────────────

class TestMeasureDedup:
    def test_finds_duplicates(self):
        extractions = [
            ("Report1", {"formulas": [
                {"name": "Total Sales", "formula": "SUM(Amount)"},
                {"name": "Count", "formula": "COUNT(*)"},
            ]}),
            ("Report2", {"formulas": [
                {"name": "Total Sales", "formula": "SUM(Amount)"},
                {"name": "Avg Price", "formula": "AVG(Price)"},
            ]}),
        ]
        result = find_duplicate_measures(extractions)
        assert len(result["duplicates"]) == 1
        assert result["duplicates"][0]["name"] == "Total Sales"
        assert result["duplicates"][0]["identical"] is True
        assert result["dedup_savings"] > 0

    def test_no_duplicates(self):
        extractions = [
            ("R1", {"formulas": [{"name": "A", "formula": "1"}]}),
            ("R2", {"formulas": [{"name": "B", "formula": "2"}]}),
        ]
        result = find_duplicate_measures(extractions)
        assert len(result["duplicates"]) == 0


# ── Model Quality Scorecard ──────────────────────────────────────

class TestModelQuality:
    def test_good_model_scores_high(self, star_schema_data):
        result = score_model_quality(star_schema_data)
        assert result["overall_score"] >= 40
        assert result["grade"] in ("A", "B", "C", "D", "F")
        assert "relationship_coverage" in result["categories"]

    def test_empty_model(self):
        result = score_model_quality({
            "tables": [], "columns": [], "formulas": [],
            "joins": [], "charts": [],
        })
        assert result["overall_score"] >= 0
        assert result["grade"] in ("A", "B", "C", "D", "F")

    def test_has_all_categories(self, star_schema_data):
        result = score_model_quality(star_schema_data)
        expected = {"relationship_coverage", "naming_consistency",
                    "column_utilization", "measure_simplicity", "description_coverage"}
        assert expected == set(result["categories"].keys())

    def test_counts_correct(self, star_schema_data):
        result = score_model_quality(star_schema_data)
        assert result["table_count"] == 4
        assert result["column_count"] == 11
        assert result["measure_count"] == 2
        assert result["relationship_count"] == 3
