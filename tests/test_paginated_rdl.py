"""Tests for explicitly mapped Power BI semantic-model paginated reports."""

import copy
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from migrate import main as migration_main
from migrate_paginated import main
from powerbi_import.paginated_generator import generate_semantic_model_rdl

NS = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}


def _mapping(kind="crystal"):
    return {
        "title": "Ventes & Résultats",
        "source_kind": kind,
        "workspace": "Ventes",
        "semantic_model": "Modèle",
        "dax": "EVALUATE 'Ventes'",
        "columns": ["Ventes[Produit]", "Ventes[Montant]"],
    }


class PaginatedRDLTests(unittest.TestCase):
    def test_explicit_bo_and_bw_mappings_preserve_fields_and_query(self):
        for kind in ("crystal", "webi", "lumira", "desktop_intelligence",
                     "xcelsius", "analysis_olap", "universe", "bex", "bw"):
            with self.subTest(kind=kind):
                mapping = _mapping(kind)
                root = ET.fromstring(generate_semantic_model_rdl(mapping))
                self.assertEqual(root.tag, f"{{{NS['r']}}}Report")
                self.assertEqual(root.findtext(".//r:DataProvider", namespaces=NS), "OLEDB-MD")
                self.assertIn(f"Declared source: {kind}.", root.findtext("r:Description", namespaces=NS))
                self.assertEqual(root.findtext(".//r:CommandText", namespaces=NS), mapping["dax"])
                self.assertEqual(
                    [field.text for field in root.findall(".//r:Fields/r:Field/r:DataField", NS)],
                    mapping["columns"],
                )
                self.assertEqual(
                    [value.text for value in root.findall(".//r:CellContents/r:Textbox/r:Paragraphs/r:Paragraph/r:TextRuns/r:TextRun/r:Value", NS)],
                    ["Ventes[Produit]", "Ventes[Montant]", "=Fields!Field1.Value", "=Fields!Field2.Value"],
                )
                self.assertEqual(
                    root.findtext(".//r:ConnectString", namespaces=NS),
                    "Data Source=powerbi://api.powerbi.com/v1.0/myorg/Ventes; Initial Catalog=Modèle",
                )

    def test_invalid_or_unsafe_mapping_is_rejected(self):
        mutations = [
            {"columns": []},
            {"columns": ["Ventes[X]", "ventes[x]"]},
            {"workspace": "Ventes;Password=secret"},
            {"dax": 'EVALUATE FILTER(Ventes, Ventes[Nom] = "x")'},
            {"title": "=Globals!PageNumber"},
            {"source_kind": "unknown"},
        ]
        for mutation in mutations:
            with self.subTest(field=next(iter(mutation))):
                mapping = copy.deepcopy(_mapping())
                mapping.update(mutation)
                with self.assertRaises(ValueError):
                    generate_semantic_model_rdl(mapping)

    def test_cli_writes_new_rdl_and_refuses_overwrite_or_invalid_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            mapping = Path(directory) / "mapping.json"
            output = Path(directory) / "report.rdl"
            mapping.write_text(json.dumps(_mapping("bex")), encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(["--mapping", str(mapping), "--output", str(output)]), 0)
                before = output.read_bytes()
                self.assertEqual(main(["--mapping", str(mapping), "--output", str(output)]), 2)
            self.assertEqual(output.read_bytes(), before)
            ET.fromstring(before)
            mapping.write_text("{", encoding="utf-8")
            invalid_output = Path(directory) / "invalid.rdl"
            with redirect_stderr(StringIO()):
                self.assertEqual(main(["--mapping", str(mapping), "--output", str(invalid_output)]), 2)
            self.assertFalse(invalid_output.exists())

    def test_new_source_labels_with_dax_through_both_cli_entry_points(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for kind in ("lumira", "desktop_intelligence", "xcelsius", "analysis_olap", "universe"):
                with self.subTest(kind=kind):
                    mapping = folder / f"{kind}.json"
                    mapping.write_text(json.dumps(_mapping(kind)), encoding="utf-8")
                    for entry in ("main", "standalone"):
                        output = folder / f"{kind}-{entry}.rdl"
                        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                            if entry == "main":
                                result = migration_main(["--output-format", "rdl", "--rdl-mapping",
                                                         str(mapping), "--rdl-output", str(output)])
                            else:
                                result = main(["--mapping", str(mapping), "--output", str(output)])
                        self.assertEqual(result, 0)
                        root = ET.parse(output).getroot()
                        self.assertIn(f"Declared source: {kind}.", root.findtext("r:Description", namespaces=NS))
                        self.assertEqual(root.findtext(".//r:CommandText", namespaces=NS), _mapping(kind)["dax"])


if __name__ == "__main__":
    unittest.main()
