"""Tests for export of expressions from generated TMDL."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from powerbi_import.expression_export import export_model_expressions
from powerbi_import.tmdl_generator import _write_roles_tmdl, _write_table_tmdl

ROOT = Path(__file__).resolve().parents[1]


class TestExpressionExport(unittest.TestCase):
    def _model(self, directory):
        model = Path(directory) / "Example.SemanticModel"
        definition = model / "definition"
        tables = definition / "tables"
        tables.mkdir(parents=True)
        (definition / "model.tmdl").write_text("model Model\n", encoding="utf-8")
        return model, tables

    def test_exports_written_tmdl_measures_and_m_without_inventing_expressions(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, tables = self._model(temporary)
            output = Path(temporary) / "exports"
            output.mkdir()
            first = 'let\n    Source = "été\u2028suite"\nin\n    Source'
            second = "let\n    Source = 2\nin\n    Source"
            multiline = 'VAR x = "a\u2028b"\nRETURN\n    x'
            _write_table_tmdl(str(tables), {
                "name": "Équipe",
                "columns": [],
                "measures": [
                    {"name": "Profit = d'A", "expression": "SUM('Équipe'[Valeur])"},
                    {"name": "Multiline", "expression": multiline},
                ],
                "partitions": [
                    {"source": {"type": "m", "expression": first}},
                    {"source": {"type": "m", "expression": second}},
                    {"source": {"type": "calculated", "expression": "ROW(\"X\", 1)"}},
                ],
            })
            (model / "definition" / "expressions.tmdl").write_text(
                'expression ServerName = "synthetic\u2028server" meta [IsParameterQuery=true]\n\n'
                'expression Shared =\n\t\tlet\n\t\t    Source = 1\n\t\tin\n\t\t    Source\n',
                encoding="utf-8",
            )
            manifest = export_model_expressions(model, output)
            self.assertEqual((output / "PowerQuery" / "Équipe__1.pq").read_text(
                encoding="utf-8"), first + "\n")
            self.assertEqual((output / "PowerQuery" / "Équipe__2.pq").read_text(
                encoding="utf-8"), second + "\n")
            self.assertEqual((output / "PowerQuery" / "Expressions" / "Shared.pq").read_text(
                encoding="utf-8"), "let\n    Source = 1\nin\n    Source\n")
            self.assertEqual((output / "PowerQuery" / "Expressions" / "ServerName.pq").read_text(
                encoding="utf-8"), '"synthetic\u2028server" meta [IsParameterQuery=true]\n')
            self.assertEqual((output / "DAX" / "Équipe.dax").read_text(encoding="utf-8"),
                             "'Profit = d''A' =\nSUM('Équipe'[Valeur])\n\n"
                             f"Multiline =\n{multiline}\n")
            calculated = (output / "DAX" / "CalculatedTables" / "Équipe.dax").read_text(
                encoding="utf-8"
            )
            self.assertIn('ROW("X", 1)', calculated)
            self.assertEqual(len(manifest["exports"]), 6)
            self.assertEqual(
                json.loads((output / "expression_export.json").read_text(encoding="utf-8")),
                manifest,
            )

    def test_exports_actual_calculations_roles_and_refresh_expressions(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, tables = self._model(temporary)
            output = Path(temporary) / "exports"
            output.mkdir()
            _write_table_tmdl(str(tables), {
                "name": "Sales",
                "columns": [
                    {"name": "Region", "dataType": "string"},
                    {"name": "Margin", "isCalculated": True,
                     "expression": "[Revenue] - [Cost]"},
                    {"name": "Label", "isCalculated": True,
                     "expression": 'VAR label = "a\u2028b"\nRETURN\n    label'},
                ],
                "measures": [],
                "calculationGroup": {"calculationItems": [
                    {"name": "Actual", "expression": "SELECTEDMEASURE()"},
                    {"name": "Prior Year", "expression": "VAR x = 1\nRETURN\n    x"},
                ]},
                "partitions": [
                    {"source": {"type": "calculated", "expression": "ROW(\"X\", 1)"}},
                    {"source": {"type": "calculated", "expression": "UNION(\n    ROW(\"X\", 1),\n    ROW(\"X\", 2)\n)"}},
                ],
                "refreshPolicy": {
                    "pollingExpression": "let\n    Source = 1\nin\n    Source",
                    "sourceExpression": "let Source = 2 in Source",
                },
            })
            _write_roles_tmdl(str(model / "definition"), [
                {"name": "Restricted West", "tablePermissions": [
                    {"name": "Sales", "filterExpression": '[Region] = "West"'},
                    {"name": "Other", "filterExpression": ""},
                ]},
            ])
            manifest = export_model_expressions(model, output)
            self.assertEqual(
                (output / "DAX" / "CalculatedColumns" / "Sales.dax").read_text(encoding="utf-8"),
                'Margin =\n[Revenue] - [Cost]\n\nLabel =\nVAR label = "a\u2028b"\nRETURN\n    label\n',
            )
            tables_dax = (output / "DAX" / "CalculatedTables" / "Sales.dax").read_text(
                encoding="utf-8"
            )
            self.assertIn('ROW("X", 1)', tables_dax)
            self.assertIn('UNION(\n    ROW("X", 1),\n    ROW("X", 2)\n)', tables_dax)
            self.assertEqual(
                (output / "DAX" / "CalculationGroups" / "Sales.dax").read_text(encoding="utf-8"),
                "Actual =\nSELECTEDMEASURE()\n\n'Prior Year' =\nVAR x = 1\nRETURN\n    x\n",
            )
            self.assertEqual(
                (output / "DAX" / "Roles" / "Restricted West.dax").read_text(encoding="utf-8"),
                '-- Table permission: Sales\n[Region] = "West"\n',
            )
            self.assertEqual(
                (output / "PowerQuery" / "RefreshPolicies" / "Sales__Polling.pq").read_text(
                    encoding="utf-8"
                ),
                "let\n    Source = 1\nin\n    Source\n",
            )
            self.assertEqual(
                (output / "PowerQuery" / "RefreshPolicies" / "Sales__Source.pq").read_text(
                    encoding="utf-8"
                ),
                "let Source = 2 in Source\n",
            )
            self.assertEqual(
                {entry["kind"] for entry in manifest["exports"]},
                {"dax_calculated_columns", "dax_calculated_partitions",
                 "dax_calculation_items", "dax_role_filters", "m_refresh_policy"},
            )
            self.assertFalse((output / "DAX" / "Sales.dax").exists())

    def test_fabric_dataflow_queries_are_copied_with_project_relative_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, _ = self._model(temporary)
            queries = model.parent / "Example.Dataflow" / "queries"
            queries.mkdir(parents=True)
            source = queries / "Orders.m"
            source.write_text('// Query: Orders\nlet Source = "a\u2028b" in Source\n', encoding="utf-8")
            output = model.parent / "exports"
            output.mkdir()
            manifest = export_model_expressions(model, output, dataflow_query_dir=queries)
            self.assertEqual(
                (output / "PowerQuery" / "Dataflow" / "Orders.pq").read_text(encoding="utf-8"),
                source.read_text(encoding="utf-8"),
            )
            self.assertEqual(manifest["exports"], [{
                "path": "PowerQuery/Dataflow/Orders.pq",
                "source": "Example.Dataflow/queries/Orders.m",
                "kind": "dataflow_m_query",
                "source_scope": "project",
            }])
            self.assertEqual(manifest["scope"], "generated_tmdl_and_dataflow_expressions_only")
            cli_output = model.parent / "cli-exports"
            command = [sys.executable, "-m", "powerbi_import.expression_export",
                       "--semantic-model", str(model), "--output-dir", str(cli_output),
                       "--include-dataflow"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (cli_output / "PowerQuery" / "Dataflow" / "Orders.pq").read_text(
                    encoding="utf-8"
                ),
                source.read_text(encoding="utf-8"),
            )

    def test_dataflow_rejects_external_and_symlinked_queries_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            model, _ = self._model(temporary)
            output = model.parent / "exports"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "within the model project"):
                export_model_expressions(model, output, dataflow_query_dir=outside)
            self.assertEqual(list(output.iterdir()), [])

            queries = model.parent / "Example.Dataflow" / "queries"
            queries.mkdir(parents=True)
            query = queries / "Orders.m"
            query.write_text("let Source = 1 in Source\n", encoding="utf-8")
            actual_is_symlink = Path.is_symlink
            with patch.object(Path, "is_symlink",
                              lambda path: path == query or actual_is_symlink(path)):
                with self.assertRaisesRegex(ValueError, "Invalid Dataflow query file"):
                    export_model_expressions(model, output, dataflow_query_dir=queries)
            self.assertEqual(list(output.iterdir()), [])
            actual_is_junction = Path.is_junction
            with patch.object(Path, "is_junction",
                              lambda path: path == queries or actual_is_junction(path)):
                with self.assertRaisesRegex(ValueError, "junction"):
                    export_model_expressions(model, output, dataflow_query_dir=queries)
            self.assertEqual(list(output.iterdir()), [])

    def test_junction_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, _ = self._model(temporary)
            output = model.parent / "exports"
            output.mkdir()
            actual_is_junction = Path.is_junction
            with patch.object(Path, "is_junction",
                              lambda path: path == output or actual_is_junction(path)):
                with self.assertRaisesRegex(ValueError, "junction"):
                    export_model_expressions(model, output)
            self.assertEqual(list(output.iterdir()), [])

    def test_model_without_exportable_expressions_has_empty_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, _ = self._model(temporary)
            output = model.parent / "exports"
            output.mkdir()
            manifest = export_model_expressions(model, output)
            self.assertEqual(manifest["exports"], [])
            self.assertFalse((output / "PowerQuery").exists())
            self.assertFalse((output / "DAX").exists())
            self.assertTrue((output / "expression_export.json").is_file())

    def test_collision_and_existing_outputs_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, tables = self._model(temporary)
            output = Path(temporary) / "exports"
            output.mkdir()
            for name, count in (("Sales", 2), ("Sales__1", 1)):
                _write_table_tmdl(str(tables), {
                    "name": name, "columns": [], "measures": [],
                    "partitions": [
                        {"source": {"type": "m", "expression": "let Source = 1 in Source"}}
                        for _ in range(count)
                    ],
                })
            with self.assertRaisesRegex(ValueError, "collision"):
                export_model_expressions(model, output)
            self.assertEqual(list(output.iterdir()), [])
            (tables / "Sales__1.tmdl").unlink()
            (output / "PowerQuery").mkdir()
            sentinel = output / "PowerQuery" / "Sales__1.pq"
            sentinel.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already exists"):
                export_model_expressions(model, output)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_windows_reserved_names_remain_safe_with_extensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, _ = self._model(temporary)
            output = model.parent / "exports"
            output.mkdir()
            names = ("CON", "con.foo", "LPT1 .bar", "COM\u00b9.data", "CONIN$.val")
            (model / "definition" / "expressions.tmdl").write_text(
                "".join(f"expression '{name}' = 1\n" for name in names), encoding="utf-8"
            )
            manifest = export_model_expressions(model, output)
            self.assertEqual(
                {entry["path"] for entry in manifest["exports"]},
                {"PowerQuery/Expressions/CON_.pq",
                 "PowerQuery/Expressions/con_.foo.pq",
                 "PowerQuery/Expressions/LPT1 _.bar.pq",
                 "PowerQuery/Expressions/COM\u00b9_.data.pq",
                 "PowerQuery/Expressions/CONIN$_.val.pq"},
            )
            (model / "definition" / "expressions.tmdl").write_text(
                "expression 'CON.foo' = 1\nexpression 'CON_.foo' = 2\n", encoding="utf-8"
            )
            collision_output = model.parent / "collision"
            collision_output.mkdir()
            with self.assertRaisesRegex(ValueError, "collision"):
                export_model_expressions(model, collision_output)
            self.assertEqual(list(collision_output.iterdir()), [])

    def test_invalid_multiline_measure_fails_without_partial_exports(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, tables = self._model(temporary)
            (tables / "Sales.tmdl").write_text(
                "table Sales\n\tmeasure Broken = ```\n\t\t\tSUM(1)\n",
                encoding="utf-8",
            )
            output = Path(temporary) / "exports"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "Unterminated"):
                export_model_expressions(model, output)
            self.assertEqual(list(output.iterdir()), [])

    def test_cli_exports_existing_model_and_rejects_source_or_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            model, tables = self._model(temporary)
            _write_table_tmdl(str(tables), {
                "name": "Sales", "columns": [],
                "measures": [{"name": "Revenue", "expression": "SUM(Sales[Amount])"}],
                "partitions": [{"source": {"type": "m", "expression": "let Source = 1 in Source"}}],
            })
            output = Path(temporary) / "exports"
            command = [sys.executable, "-m", "powerbi_import.expression_export",
                       "--semantic-model", str(model), "--output-dir", str(output)]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((output / "DAX" / "Sales.dax").read_text(encoding="utf-8"),
                             "Revenue =\nSUM(Sales[Amount])\n")
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("new or empty", result.stderr)
            command[-1] = str(model / "output")
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("separate from the semantic model", result.stderr)
            self.assertFalse((model / "output").exists())
