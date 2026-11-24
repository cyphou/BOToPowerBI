"""Behavioral tests for cross-workbook portfolio assessment and reports."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from powerbi_import.global_assessment import (
    build_data_lineage,
    generate_global_html_report,
    generate_governance_report,
    recommend_consolidation,
    run_global_assessment,
    save_global_assessment_json,
)


def _workbook(table_name="Orders", *, columns=None, server="warehouse.example.invalid",
              worksheets=None, calculations=None):
    return {
        "datasources": [{
            "name": "BO source",
            "connection": {
                "type": "SQL Server",
                "details": {"server": server, "database": "Sales"},
            },
            "tables": [{
                "name": table_name,
                "columns": columns or [
                    {"name": "Order ID", "datatype": "integer"},
                    {"name": "Amount", "datatype": "decimal"},
                ],
            }],
            "calculations": [],
            "relationships": [],
        }],
        "calculations": calculations or [],
        "worksheets": worksheets or [],
        "dashboards": [],
        "parameters": [],
    }


class TestGlobalAssessmentPortfolio(unittest.TestCase):
    def test_profiles_count_bo_metadata_and_aggregate_portfolio_totals(self):
        workbook = _workbook(
            columns=[
                {"name": "Order ID", "datatype": "integer"},
                {"name": "Amount", "datatype": "decimal"},
            ],
            worksheets=[{"name": "Overview"}, {"name": "Details"}],
            calculations=[
                {"name": "Revenue", "role": "measure"},
                {"name": "Margin", "role": "dimension"},
            ],
        )
        workbook["datasources"][0]["calculations"] = [
            {"name": "Datasource measure", "role": "measure"},
        ]
        workbook["datasources"][0]["relationships"] = [{"from_table": "Orders"}]
        workbook["dashboards"] = [{"name": "Executive"}]
        workbook["parameters"] = [{"name": "Fiscal Year"}]

        result = run_global_assessment([workbook], ["Finance 2026"])

        self.assertEqual((result.total_workbooks, result.total_tables, result.total_measures),
                         (1, 1, 2))
        profile = result.workbook_profiles[0]
        self.assertEqual(profile.to_dict(), {
            "name": "Finance 2026", "tables": 1, "columns": 2, "measures": 2,
            "calc_columns": 1, "relationships": 1, "worksheets": 2,
            "dashboards": 1, "parameters": 1,
            "connection_types": ["SQL Server"], "table_names": ["Orders"],
        })
        self.assertEqual(result.to_dict()["workbook_profiles"][0]["name"], "Finance 2026")

    def test_pairwise_scores_form_shared_cluster_and_keep_unrelated_workbook_isolated(self):
        workbooks = [
            _workbook(),
            _workbook(),
            _workbook("Products", server="products.example.invalid"),
        ]
        names = ["Sales North", "Sales South", "Product Catalog"]

        result = run_global_assessment(workbooks, names)

        self.assertEqual(len(result.pairwise_scores), 3)
        pair = next(score for score in result.pairwise_scores
                    if (score.wb_a, score.wb_b) == ("Sales North", "Sales South"))
        self.assertEqual(pair.shared_tables, 1)
        self.assertGreaterEqual(pair.merge_score, 30)
        self.assertEqual(pair.recommendation, "merge")
        self.assertEqual([cluster.workbooks for cluster in result.merge_clusters],
                         [["Sales North", "Sales South"]])
        self.assertEqual(result.merge_clusters[0].shared_tables, ["Orders"])
        self.assertEqual(result.isolated_workbooks, ["Product Catalog"])

    def test_same_table_name_from_different_physical_sources_is_not_a_shared_fingerprint(self):
        result = run_global_assessment(
            [_workbook(server="north.example.invalid"),
             _workbook(server="south.example.invalid")],
            ["North", "South"],
        )

        self.assertEqual(len(result.pairwise_scores), 1)
        self.assertEqual(result.pairwise_scores[0].shared_tables, 0)
        self.assertEqual(result.merge_clusters, [])
        self.assertEqual(result.isolated_workbooks, ["North", "South"])

    def test_lineage_graph_links_datasource_tables_calculations_and_visuals(self):
        workbook_a = _workbook(
            calculations=[{"name": "Net Sales", "formula": "[Sales] - [Returns]"}],
            worksheets=[{"name": "Sales View", "fields": ["Net Sales", {"name": "Orders"}]}],
        )
        workbook_a["datasources"][0]["calculations"] = [
            {"name": "Net Sales", "formula": "[Sales] - [Returns]"},
        ]
        workbook_b = _workbook(worksheets=[{"name": "Order View", "fields": ["Orders"]}])

        graph = build_data_lineage([workbook_a, workbook_b], ["North", "South"])
        nodes = {(node["type"], node["name"]): node for node in graph["nodes"]}
        edges = {(edge["type"], edge["source"], edge["target"])
                 for edge in graph["edges"]}
        node_ids = {(kind, name): node["id"] for (kind, name), node in nodes.items()}

        self.assertEqual(nodes[("table", "Orders")]["workbooks"], ["North", "South"])
        self.assertIn(("datasource", "BO source"), nodes)
        self.assertIn(("calculation", "Net Sales"), nodes)
        self.assertIn(("visual", "Sales View"), nodes)
        self.assertIn(("contains", node_ids[("datasource", "BO source")],
                       node_ids[("table", "Orders")]), edges)
        self.assertIn(("computes", node_ids[("table", "Orders")],
                       node_ids[("calculation", "Net Sales")]), edges)
        self.assertIn(("displays", node_ids[("calculation", "Net Sales")],
                       node_ids[("visual", "Sales View")]), edges)
        self.assertIn(("displays", node_ids[("table", "Orders")],
                       node_ids[("visual", "Order View")]), edges)

    def test_consolidation_recommendations_distinguish_cluster_and_standalone(self):
        result = run_global_assessment(
            [_workbook(), _workbook(), _workbook("Products")],
            ["Sales A", "Sales B", "Products"],
        )

        recommendations = recommend_consolidation(result)

        self.assertEqual([item["action"] for item in recommendations],
                         ["shared_model", "standalone"])
        self.assertEqual(recommendations[0]["workbooks"], ["Sales A", "Sales B"])
        self.assertEqual(recommendations[0]["shared_tables"], ["Orders"])
        self.assertIn("Consolidate into a single shared semantic model",
                      recommendations[0]["reason"])
        self.assertEqual(recommendations[1]["workbooks"], ["Products"])
        self.assertEqual(recommendations[1]["score"], 0)

    def test_global_html_report_escapes_unicode_workbook_and_table_metadata(self):
        hostile_name = 'Ventes & <été> "Q4" \'26'
        hostile_table = '<Orders & returns>'
        result = run_global_assessment(
            [_workbook(hostile_table), _workbook(hostile_table)],
            [hostile_name, "R&D/Orders (北)"],
        )

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "reports" / "portfolio.html"
            returned_path = generate_global_html_report(result, str(output))
            html = output.read_text(encoding="utf-8")

        self.assertEqual(returned_path, str(output))
        self.assertIn("2 workbooks analyzed", html)
        self.assertIn("Merge Clusters", html)
        self.assertIn("Recommended Actions", html)
        self.assertIn("&lt;Orders &amp; returns&gt;", html)
        self.assertIn("Ventes &amp; &lt;été&gt; &quot;Q4&quot; &#39;26", html)
        self.assertIn("R&amp;D/Orders (北)", html)
        self.assertNotIn(hostile_name, html)
        self.assertNotIn(hostile_table, html)

    def test_governance_report_escapes_wave_and_cluster_values_and_reports_effort(self):
        hostile_name = '<Finance & Risk>'
        result = run_global_assessment(
            [_workbook(), _workbook()], [hostile_name, "Finance B"]
        )
        server_assessment = SimpleNamespace(
            waves=[SimpleNamespace(wave_number=2, label='<complex & urgent>',
                                   workbooks=["A", "B"], total_effort=12.5)],
            green_count=1, yellow_count=1, red_count=0,
        )

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "governance.html"
            returned_path = generate_governance_report(
                result, server_assessment, str(output)
            )
            html = output.read_text(encoding="utf-8")

        self.assertEqual(returned_path, str(output))
        self.assertIn("Migration Governance Report", html)
        self.assertIn("12.5h", html)
        self.assertIn("&lt;complex &amp; urgent&gt;", html)
        self.assertIn("&lt;Finance &amp; Risk&gt;", html)
        self.assertNotIn(hostile_name, html)

    def test_global_json_artifact_preserves_unicode_counts_and_recommendations(self):
        result = run_global_assessment(
            [_workbook("注文"), _workbook("注文")], ["東京 A", "東京 B"]
        )

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested" / "assessment.json"
            returned_path = save_global_assessment_json(result, str(output))
            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(returned_path, str(output))
        self.assertEqual(data["total_workbooks"], 2)
        self.assertEqual(data["total_tables"], 2)
        self.assertEqual(data["merge_clusters"][0]["shared_tables"], ["注文"])
        self.assertEqual(data["workbook_profiles"][0]["name"], "東京 A")
        self.assertIn("timestamp", data)


if __name__ == "__main__":
    unittest.main()