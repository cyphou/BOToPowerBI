"""Behavioral tests for public PBIR, M, and TMDL validator contracts."""

import tempfile
import unittest
from pathlib import Path

from powerbi_import.validator import ArtifactValidator


class TestValidatorStructure(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def _write(self, relative_path, content=""):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_m_expression_reports_let_without_in_with_context(self):
        self.assertEqual(
            ArtifactValidator.validate_m_expression("let Value = 1", "Orders query"),
            [{
                "severity": "ERROR",
                "message": 'M expression has "let" without matching "in" in Orders query',
                "line": 0,
            }],
        )

    def test_m_expression_reports_each_unmatched_delimiter(self):
        for expression, delimiter in (
            ("(value", "parentheses"),
            ("{value", "braces"),
            ("[value", "brackets"),
        ):
            with self.subTest(delimiter=delimiter):
                self.assertEqual(
                    ArtifactValidator.validate_m_expression(expression, "Source step"),
                    [{
                        "severity": "ERROR",
                        "message": f"Unmatched {delimiter} in M expression in Source step",
                        "line": 0,
                    }],
                )

    def test_m_expression_reports_dangling_previous_step_placeholder(self):
        self.assertEqual(
            ArtifactValidator.validate_m_expression("{prev}", "Orders query"),
            [{
                "severity": "ERROR",
                "message": "Dangling {prev} placeholder in M expression in Orders query",
                "line": 0,
            }],
        )

    def test_balanced_m_expression_has_no_issues(self):
        self.assertEqual(
            ArtifactValidator.validate_m_expression(
                'let Source = #table({"Value"}, {{1}}) in Source'
            ),
            [],
        )
        self.assertEqual(ArtifactValidator.validate_m_expression("  "), [])

    def test_visual_completeness_reports_missing_type_and_invalid_position(self):
        self.assertEqual(
            ArtifactValidator.validate_visual_completeness(
                {"visual": {}, "position": {"width": 0, "height": -1}},
                "pages/page1/visuals/visual1/visual.json",
            ),
            [
                {
                    "severity": "WARNING",
                    "message": "Visual missing visualType in pages/page1/visuals/visual1/visual.json",
                    "line": 0,
                },
                {
                    "severity": "WARNING",
                    "message": "Visual has zero or negative size (0x-1) in pages/page1/visuals/visual1/visual.json",
                    "line": 0,
                },
            ],
        )

    def test_cross_references_reports_missing_pages_directory(self):
        report_dir = self.root / "Sales.Report"
        report_dir.mkdir()
        self.assertEqual(
            ArtifactValidator.validate_cross_references(self.root),
            [{
                "severity": "ERROR",
                "message": f"pages/ directory missing in {report_dir}",
                "line": 0,
            }],
        )

    def test_cross_references_reports_missing_page_and_visual_json(self):
        self._write("Sales.Report/pages/page1/visuals/visual1/.keep")
        self.assertEqual(
            ArtifactValidator.validate_cross_references(self.root),
            [
                {"severity": "ERROR", "message": "page.json missing in page1", "line": 0},
                {"severity": "WARNING", "message": "visual.json missing in visual1", "line": 0},
            ],
        )
        (self.root / "NoReport").mkdir()
        self.assertEqual(ArtifactValidator.validate_cross_references(self.root / "NoReport"), [])

    def test_tmdl_structure_warns_for_empty_table_and_role(self):
        self.assertEqual(
            ArtifactValidator.validate_tmdl_structure(
                "table Empty\ntable Populated\ncolumn Id\nrole EmptyRole\n"
                "role Restricted\ntablePermission Orders",
                "definition/roles.tmdl",
            ),
            [
                {
                    "severity": "WARNING",
                    "message": 'Table "Empty" has no columns or partitions in definition/roles.tmdl',
                    "line": 0,
                },
                {
                    "severity": "WARNING",
                    "message": 'Role "EmptyRole" has no tablePermission in definition/roles.tmdl',
                    "line": 0,
                },
            ],
        )
        self.assertEqual(
            ArtifactValidator.validate_tmdl_indentation(
                " \tcolumn Id\n   ", "definition/tables/Orders.tmdl"
            ),
            [{
                "severity": "WARNING",
                "message": "Mixed tabs and spaces at line 1 in definition/tables/Orders.tmdl",
                "line": 1,
            }],
        )

    def test_detect_circular_relationships_returns_cycle_path(self):
        self._write(
            "Sales.SemanticModel/definition/model.tmdl",
            "relationship R1\n\tfromTable: 'Orders'\n\ttoTable: 'Customers'\n"
            "relationship R2\n\tfromTable: 'Customers'\n\ttoTable: 'Orders'\n",
        )
        self.assertEqual(
            ArtifactValidator.detect_circular_relationships(
                self.root / "Sales.SemanticModel"
            ),
            ["Orders → Customers → Orders"],
        )
        (self.root / "Empty.SemanticModel").mkdir()
        self.assertEqual(
            ArtifactValidator.detect_circular_relationships(
                self.root / "Empty.SemanticModel"
            ),
            [],
        )

    def test_detect_orphan_tables_excludes_relationship_endpoints(self):
        self._write("Sales.SemanticModel/definition/tables/Orders.tmdl", "table Orders\ncolumn Id\n")
        self._write("Sales.SemanticModel/definition/tables/Customers.tmdl", "table Customers\ncolumn Id\n")
        self._write("Sales.SemanticModel/definition/tables/Notes.tmdl", "table Notes\ncolumn Text\nmeasure LookupId = 'Lookup'[Id]\n")
        self._write("Sales.SemanticModel/definition/tables/Lookup.tmdl", "table Lookup\ncolumn Id\n")
        self._write("Sales.SemanticModel/definition/tables/Calendar.tmdl", "table Calendar\ncolumn Date\n")
        self._write(
            "Sales.SemanticModel/definition/model.tmdl",
            "relationship R1\n\tfromTable: 'Orders'\n\ttoTable: 'Customers'\n",
        )
        self.assertEqual(
            ArtifactValidator.detect_orphan_tables(self.root / "Sales.SemanticModel"),
            ["Notes"],
        )
        self._write("Single.SemanticModel/definition/tables/Only.tmdl", "table Only\ncolumn Id\n")
        self.assertEqual(
            ArtifactValidator.detect_orphan_tables(self.root / "Single.SemanticModel"),
            [],
        )

    def test_detect_unused_parameters_returns_only_unreferenced_parameter_tables(self):
        definition = "Sales.SemanticModel/definition/tables"
        self._write(
            f"{definition}/Unused Parameter.tmdl",
            "table 'Unused Parameter'\nmeasure 'Unused Choice' = 1\n",
        )
        self._write(
            f"{definition}/Used Parameter.tmdl",
            "table 'Used Parameter'\nmeasure 'Selected Choice' = 1\n",
        )
        self._write(
            f"{definition}/Consumer.tmdl",
            "table Consumer\nmeasure Current Choice = [Selected Choice]\n",
        )
        self._write(
            f"{definition}/Range.tmdl",
            "table Range\npartition Range = GENERATESERIES(1, 5)\n",
        )
        self._write(
            "Sales.SemanticModel/definition/model.tmdl",
            "model Model\nmeasure Current = [Unused Choice]\n",
        )
        self.assertCountEqual(
            ArtifactValidator.detect_unused_parameters(self.root / "Sales.SemanticModel"),
            ["Range"],
        )
        self.assertEqual(ArtifactValidator.detect_unused_parameters(self.root / "NoModel"), [])

    def test_complete_artifact_structures_have_no_findings(self):
        self._write("Sales.Report/pages/page1/page.json", "{}")
        self._write("Sales.Report/pages/page1/visuals/visual1/visual.json", "{}")
        self._write(
            "Sales.SemanticModel/definition/model.tmdl",
            "relationship R1\n\tfromTable: 'Orders'\n\ttoTable: 'Customers'\n",
        )

        self.assertEqual(
            ArtifactValidator.validate_visual_completeness(
                {"visual": {"visualType": "table"}}
            ),
            [],
        )
        self.assertEqual(ArtifactValidator.validate_cross_references(self.root), [])
        self.assertEqual(
            ArtifactValidator.validate_tmdl_structure(
                "table Orders\ncolumn Id\nrole Sales\ntablePermission Orders"
            ),
            [],
        )
        self.assertEqual(
            ArtifactValidator.detect_circular_relationships(
                self.root / "Sales.SemanticModel"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()