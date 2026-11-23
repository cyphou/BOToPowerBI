"""Tests for the CMS manifest reader and unbound RDL skeletons."""

import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from bo_export.lcm_manifest import read_lcm_manifest
from migrate_lcm_inventory import main
from powerbi_import.paginated_generator import generate_unbound_rdl

SECRET = "ENCODED-CONNECT-STRING-DO-NOT-LEAK"
MANIFEST = f"""<?xml version="1.0" encoding="UTF-8"?>
<io:InfoObjects xmlns:io="http://enterprise.businessobjects.com/4.0/infoobject"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xmlns:cr="http://enterprise.businessobjects.com/4.0/crystalreport"
 xmlns:wi="http://enterprise.businessobjects.com/4.0/webi"
 xmlns:dsl.unx="urn:unx" xmlns:ccis.dc="urn:dc">
<io:InfoObject xsi:type="ccis.dc:CCIS.DataConnection"><io:Name>Sales DB</io:Name>
<io:CUID>CONN1</io:CUID><ccis.dc:ConnectionNetworklayer>ODBC</ccis.dc:ConnectionNetworklayer>
<ccis.dc:ConnectionDatabase>MS SQL Server 2008</ccis.dc:ConnectionDatabase>
<ccis.dc:ConnectionConnectstring>{SECRET}</ccis.dc:ConnectionConnectstring></io:InfoObject>
<io:InfoObject xsi:type="dsl.unx:DSL.Universe"><io:Name>Sales.unx</io:Name><io:CUID>UNI1</io:CUID>
<dsl.unx:ConnectionChildren><dsl.unx:ConnectionChildren>CONN1</dsl.unx:ConnectionChildren>
</dsl.unx:ConnectionChildren></io:InfoObject>
<io:InfoObject xsi:type="cr:CrystalReport"><io:Name>R\u00e9sum\u00e9 / 100% (O'Brien)</io:Name>
<io:CUID>REP1ABCDEFG</io:CUID><io:Description>Monthly sales</io:Description>
<io:Owner>private-owner</io:Owner>
<cr:FileProperties><io:Files><io:File><io:Name>sales.rpt</io:Name></io:File></io:Files></cr:FileProperties>
<cr:ReportParameters>
<cr:Parameters><cr:ParameterName>Select Region(s)</cr:ParameterName>
<cr:DefaultValues><io:Item>PRIVATE-DEFAULT</io:Item></cr:DefaultValues>
<cr:ReportParameterOptions><cr:ReportParameterOption>ALLOW_MULTIPLE_VALUE</cr:ReportParameterOption>
<cr:ReportParameterOption>IS_OPTIONAL</cr:ReportParameterOption></cr:ReportParameterOptions>
<cr:Prompt>Choose regions</cr:Prompt></cr:Parameters>
<cr:Parameters><cr:ParameterName>Select Region(s)</cr:ParameterName><cr:Prompt></cr:Prompt></cr:Parameters>
</cr:ReportParameters>
<io:CustomRelation nameID="SI_DSL_UNIVERSE"><io:Item>UNI1</io:Item></io:CustomRelation>
</io:InfoObject>
<io:InfoObject xsi:type="wi:Webi"><io:Name>Web doc</io:Name><io:CUID>WEB1</io:CUID>
<io:CustomRelation nameID="SI_DSL_UNIVERSE"><io:Item>MISSING-UNIVERSE</io:Item></io:CustomRelation>
<io:String nameID="SI_WEBI_DOC_PROPERTIES">&lt;WEBI_DOC_PROPS&gt;&lt;WEBI_DP DPNAME="Query 1" DPID="DP0" DSNAME="Sales" DSID="DS0"/&gt;&lt;WEBI_DP DPNAME="Dup" DPID="DP0" DSNAME="x" DSID="DS9"/&gt;&lt;/WEBI_DOC_PROPS&gt;</io:String>
</io:InfoObject>
</io:InfoObjects>"""


def _archive(path, manifest=MANIFEST, nested=True):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as nested_zip:
        nested_zip.writestr("BusinessObjects.xml", manifest)
    with zipfile.ZipFile(path, "w") as outer:
        if nested:
            outer.writestr("ABC.005", inner.getvalue())
            outer.writestr("ABC.001", b"#properties")
        else:
            outer.writestr("BusinessObjects.xml", manifest)


class TestLcmManifest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_lineage_parameters_and_providers_come_only_from_readable_metadata(self):
        for nested in (True, False):
            with self.subTest(nested=nested):
                path = self.root / f"sample-{nested}.lcmbiar"
                _archive(path, nested=nested)
                inventory = read_lcm_manifest(path)

                self.assertEqual(inventory["evidence_boundary"], "cms_manifest_metadata_only")
                encoded = json.dumps(inventory, ensure_ascii=False)
                for private in (SECRET, "private-owner", "PRIVATE-DEFAULT"):
                    self.assertNotIn(private, encoded)
                self.assertEqual(inventory["connections"], [{
                    "cuid": "CONN1", "name": "Sales DB",
                    "network_layer": "ODBC", "database_type": "MS SQL Server 2008",
                }])
                report = next(d for d in inventory["documents"] if d["kind"] == "crystal")
                self.assertEqual(report["name"], "R\u00e9sum\u00e9 / 100% (O'Brien)")
                self.assertEqual(report["files"], ["sales.rpt"])
                self.assertEqual(report["universes"], ["Sales.unx"])
                self.assertEqual(report["parameters"][0], {
                    "name": "Select Region(s)", "prompt": "Choose regions",
                    "multiple": True, "optional": True, "discrete": False, "locked": False,
                })
                self.assertEqual(inventory["groups"], [{
                    "universe": "Sales.unx", "universe_kind": "unx",
                    "connections": [{"name": "Sales DB", "network_layer": "ODBC",
                                     "database_type": "MS SQL Server 2008"}],
                    "documents": [report["name"]],
                }])
                webi = next(d for d in inventory["documents"] if d["kind"] == "webi")
                self.assertEqual([p["id"] for p in webi["providers"]], ["DP0"])
                self.assertEqual(webi["providers"][0]["declared_source_name"], "Sales")
                self.assertEqual(webi["universes"], [])
                self.assertEqual(inventory["unresolved_universe_links"],
                                 [{"document": "Web doc", "universe_cuid": "MISSING-UNIVERSE"}])

    def test_rejects_entity_declarations_and_archives_without_a_manifest(self):
        path = self.root / "entity.lcmbiar"
        _archive(path, manifest='<!DOCTYPE x [<!ENTITY e "v">]><x/>', nested=False)
        with self.assertRaises(ValueError):
            read_lcm_manifest(path)
        empty = self.root / "empty.lcmbiar"
        with zipfile.ZipFile(empty, "w") as archive:
            archive.writestr("meta-info.properties", b"#x")
        with self.assertRaises(ValueError):
            read_lcm_manifest(empty)


class TestUnboundRdl(unittest.TestCase):
    CONTRACT = {
        "title": "Sales", "source_kind": "crystal", "description": "Line 1\r\nLine 2",
        "parameters": [
            {"name": "Select Region(s)", "prompt": "", "multiple": True, "optional": True},
            {"name": "select region s", "prompt": "Again", "multiple": False, "optional": False},
            {"name": "1st-year", "prompt": "Year", "multiple": False, "optional": False},
        ],
    }

    def test_skeleton_has_parameters_but_no_data_and_unique_identifiers(self):
        rdl = generate_unbound_rdl(self.CONTRACT)
        root = ET.fromstring(rdl)
        ns = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
        self.assertIsNone(root.find("r:DataSources", ns))
        self.assertIsNone(root.find("r:DataSets", ns))
        parameters = root.findall(".//r:ReportParameter", ns)
        names = [p.get("Name") for p in parameters]
        self.assertEqual(names, ["Select_Region_s", "select_region_s_2", "P_1st_year"])
        first = parameters[0]
        self.assertEqual(first.find("r:Prompt", ns).text, "Select Region(s)")
        self.assertEqual(first.find("r:DataType", ns).text, "String")
        self.assertEqual(first.find("r:MultiValue", ns).text, "true")
        self.assertEqual(first.find("r:Nullable", ns).text, "true")
        self.assertEqual(parameters[1].find("r:Prompt", ns).text, "Again")
        self.assertEqual(parameters[1].find("r:DataType", ns).text, "String")
        self.assertIsNone(parameters[1].find("r:MultiValue", ns))
        self.assertIsNone(parameters[1].find("r:Nullable", ns))
        self.assertEqual(parameters[2].find("r:Prompt", ns).text, "Year")
        self.assertEqual(parameters[2].find("r:DataType", ns).text, "String")
        self.assertIsNone(parameters[2].find("r:MultiValue", ns))
        self.assertIsNone(parameters[2].find("r:Nullable", ns))
        note = root.findtext(
            './/r:Body//r:Textbox[@Name="MigrationNote"]'
            '/r:Paragraphs/r:Paragraph/r:TextRuns/r:TextRun/r:Value',
            namespaces=ns,
        )
        self.assertIsNotNone(note)
        note_lower = note.lower()
        self.assertIn("parameter types default to string", note_lower)
        self.assertIn("source types", note_lower)
        self.assertIn("unverified", note_lower)
        self.assertIn("unavailable", note_lower)
        self.assertIn("must be reviewed", note_lower)
        self.assertIn("Not migrated: data source, query, layout and formulas.", note)
        self.assertEqual(
            root.findtext('.//r:Textbox[@Name="ReportTitle"]/r:Style/r:FontFamily',
                          namespaces=ns),
            "Segoe UI",
        )
        self.assertEqual(
            root.findtext('.//r:Textbox[@Name="ReportTitle"]/r:Style/r:Color',
                          namespaces=ns),
            "#1F4E78",
        )
        self.assertEqual(
            root.findtext('.//r:Textbox[@Name="MigrationNote"]/r:Style/r:BackgroundColor',
                          namespaces=ns),
            "#F2F6FA",
        )
        self.assertEqual(
            root.findtext('.//r:Textbox[@Name="MigrationNote"]/r:Style/r:PaddingLeft',
                          namespaces=ns),
            "8pt",
        )
        self.assertIsNone(root.find("r:DataSources", ns))
        self.assertIsNone(root.find("r:DataSets", ns))
        self.assertIn("Not migrated", rdl)

    def test_skeleton_without_parameters_omits_parameter_note(self):
        contract = {**self.CONTRACT, "parameters": []}
        root = ET.fromstring(generate_unbound_rdl(contract))
        ns = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
        note = root.findtext(
            './/r:Body//r:Textbox[@Name="MigrationNote"]'
            '/r:Paragraphs/r:Paragraph/r:TextRuns/r:TextRun/r:Value',
            namespaces=ns,
        )
        self.assertIsNotNone(note)
        note_lower = note.lower()
        self.assertNotIn("parameter extraction", note_lower)
        self.assertNotIn("parameter types default to string", note_lower)
        self.assertNotIn("parameter review", note_lower)
        self.assertNotIn("must be reviewed", note_lower)
        self.assertIn("Not migrated: data source, query, layout and formulas.", note)

    def test_rejects_expressions_credentials_and_malformed_contracts(self):
        for change in (
            {"title": "=Cmd"}, {"title": "A\nB"}, {"description": "=1+1"},
            {"description": "password: hunter2"}, {"source_kind": "tableau"},
            {"parameters": [{"name": "x"}]},
            {"parameters": [{"name": "x", "prompt": "", "multiple": 1, "optional": False}]},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    generate_unbound_rdl({**self.CONTRACT, **change})
        with self.assertRaises(ValueError):
            generate_unbound_rdl({"title": "x"})


class TestLcmInventoryCli(unittest.TestCase):
    def test_writes_inventory_and_skeletons_and_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "sample.lcmbiar"
            _archive(archive)
            output = root / "out"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--manifest", str(archive), "--output-dir", str(output)]), 0)
            skeletons = json.loads((output / "skeletons.json").read_text(encoding="utf-8"))
            self.assertEqual([s["status"] for s in skeletons], ["generated", "generated"])
            generated = [(output / s["file"]) for s in skeletons]
            self.assertTrue(all(path.is_file() for path in generated))
            self.assertTrue((output / "inventory.json").is_file())
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--manifest", str(archive), "--output-dir", str(output)]), 2)

    def test_unsafe_document_is_skipped_and_reported_with_a_nonzero_exit(self):
        manifest = MANIFEST.replace("<io:Description>Monthly sales</io:Description>",
                                    "<io:Description>=EXPR</io:Description>")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "sample.lcmbiar"
            _archive(archive, manifest=manifest)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(["--manifest", str(archive), "--output-dir", str(root / "out")]), 1)
            skeletons = json.loads((root / "out" / "skeletons.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(s["status"] for s in skeletons), ["generated", "skipped"])


if __name__ == "__main__":
    unittest.main()
