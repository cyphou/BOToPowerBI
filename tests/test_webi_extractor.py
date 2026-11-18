"""Tests for WebI extractor."""

import hashlib
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import patch

from bo_export.webi_extractor import extract_webi, _safe_parse_xml
from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
from bo_export.extract_bo_data import extract_bo_data, load_extracted_data


class TestSafeParseXml(unittest.TestCase):
    """Test XXE protection in XML parsing."""

    def test_valid_xml(self):
        result = _safe_parse_xml("<root><item name='test'/></root>")
        self.assertIsNotNone(result)

    def test_empty_string(self):
        result = _safe_parse_xml("")
        self.assertIsNone(result)

    def test_none(self):
        result = _safe_parse_xml(None)
        self.assertIsNone(result)

    def test_invalid_xml(self):
        result = _safe_parse_xml("not xml at all")
        self.assertIsNone(result)

    def test_xxe_blocked(self):
        xxe = '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><root/>'
        result = _safe_parse_xml(xxe)
        self.assertIsNone(result)


class TestWebiExtraction(unittest.TestCase):
    """Test Web Intelligence document extraction."""

    def test_extract_from_xml_content(self):
        """Test extraction from pre-parsed XML metadata."""
        metadata = {
            "document.xml": """<document>
                <dataprovider name="Query1" type="universe" universe="Sales">
                    <resultobject name="Revenue" qualification="measure"/>
                    <resultobject name="Country" qualification="dimension"/>
                </dataprovider>
                <variable name="Total" formula="=Sum([Revenue])" qualification="measure"/>
                <prompt name="SelectCountry" type="text" required="true"/>
                <chart name="Revenue Chart" type="bar"/>
            </document>"""
        }

        extracted = extract_webi("dummy.wid", artifact_data=metadata)

        self.assertIsInstance(extracted, dict)
        self.assertIn("queries", extracted)
        self.assertIn("formulas", extracted)
        self.assertIn("prompts", extracted)
        self.assertIn("charts", extracted)
        self.assertEqual(len(extracted["formulas"]), 1)
        self.assertEqual(extracted["formulas"][0]["formula"], "=Sum([Revenue])")

    def test_extract_nested_variable_formula_with_parent_metadata(self):
        formula_text = "=([Revenue]-[Cost])/[Revenue]"
        extracted = extract_webi("dummy.wid", artifact_data={
            "document.xml": (
                '<document><variable name="Margin" qualification="measure" '
                'dataType="decimal"><formula>'
                f'{formula_text}'
                '</formula></variable></document>'
            ),
        })

        self.assertEqual(len(extracted["formulas"]), 1)
        self.assertEqual(extracted["formulas"][0]["name"], "Margin")
        self.assertEqual(extracted["formulas"][0]["formula"], formula_text)
        self.assertEqual(extracted["formulas"][0]["qualification"], "measure")
        converted = adapt_bo_to_converted_objects(extracted)
        self.assertEqual(converted["calculations"][0]["name"], "Margin")
        self.assertEqual(converted["calculations"][0]["formula"], formula_text)

    def test_extract_empty_metadata(self):
        """Test extraction with empty metadata."""
        extracted = extract_webi("dummy.wid", artifact_data={})
        # Should return structure with all keys
        self.assertEqual(len(extracted), 15)
        for key in extracted:
            self.assertIsInstance(extracted[key], list)

    def test_extract_from_zip(self):
        """Test extraction from a ZIP-based .wid file."""
        with tempfile.NamedTemporaryFile(suffix=".wid", delete=False) as f:
            wid_path = f.name

        try:
            with zipfile.ZipFile(wid_path, "w") as zf:
                zf.writestr("content.xml", """<report>
                    <variable name="Total Revenue" formula="=Sum([Revenue])" qualification="measure"/>
                    <table name="Sales"/>
                </report>""")

            extracted = extract_webi(wid_path)
            self.assertIsInstance(extracted, dict)
        finally:
            os.unlink(wid_path)


class TestWebiPathTraversal(unittest.TestCase):
    """Test ZIP entry path traversal protection."""

    def test_traversal_entries_skipped(self):
        with tempfile.NamedTemporaryFile(suffix=".wid", delete=False) as f:
            wid_path = f.name

        try:
            with zipfile.ZipFile(wid_path, "w") as zf:
                zf.writestr("../../../etc/passwd", b"malicious")
                zf.writestr("content.xml", "<report/>")

            # Should not raise, traversal entries silently skipped
            extracted = extract_webi(wid_path)
            self.assertIsInstance(extracted, dict)
        finally:
            os.unlink(wid_path)


class TestNativeWidExtraction(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = os.path.join(self.temporary.name, "native.wid")

    @staticmethod
    def _record(signature, body):
        length = len(body) + 8
        return length.to_bytes(4, "little") + signature + body

    @classmethod
    def _docspec(cls, reports, version="2.5", include_layout=False):
        root = ET.Element("DOCUMENT", RSVERSION=version)
        for report_id, name in reports:
            report = ET.SubElement(root, "REPORT", RID=report_id)
            plist = ET.SubElement(report, "PLIST")
            value = ET.SubElement(plist, "PVAL", NAME="name")
            value.text = json.dumps({"l": name}, ensure_ascii=False)
            if include_layout:
                page = ET.SubElement(report, "PAGE_BODY", BID="page-1")
                section = ET.SubElement(page, "SECTION", BID="section-1")
                zone = ET.SubElement(section, "ZONE", BID="zone-1")
                table = ET.SubElement(zone, "VTABLE", BID="table-1")
                ET.SubElement(table, "COLINFO", COL="0")
                ET.SubElement(table, "COLINFO", COL="1")
                ET.SubElement(table, "ROWINFO", ROW="0")
                ET.SubElement(zone, "HTABLE", BID="table-2")
                ET.SubElement(zone, "XTABLE", BID="table-3")
        return cls._record(b"\x05\x00\x02\x00", ET.tostring(root, encoding="utf-8"))

    @classmethod
    def _provider(cls, name, provider_id="DP0", modern=True, parameter_record=None):
        name_bytes = name.encode("utf-16le")
        if modern:
            signature = b"\x02\x00\x03\x00"
            xml = (
                '<queryspec:QuerySpec xmlns:queryspec="http://com.sap.sl.queryspec" '
                f'dataProviderId="{provider_id}"><queriesTree><bOQuery>'
                '<resultObjects identifier="obj-1" name="R&#233;gion / %"/>'
                '<resultObjects identifier="obj-2" name="Revenue"/>'
                '</bOQuery></queriesTree></queryspec:QuerySpec>'
            ).encode("utf-16le")
        else:
            signature = b"\x00\x00\x03\x00"
            xml = (
                '<QuerySpecification><CombinedQuery><Query>'
                '<QueryResult Key="DS1.DObc"><Name>R&#233;gion / %</Name></QueryResult>'
                '<QueryResult Key="DS1.DOc2"><Name>Revenue</Name></QueryResult>'
                '<Property name="SELECT">not a SQL statement</Property>'
                '</Query></CombinedQuery></QuerySpecification>'
            ).encode("utf-8")
        body = (len(name_bytes) // 2).to_bytes(4, "little") + name_bytes + b"\x01\x00"
        tail = b"\x00binary-tail"
        if parameter_record is not None:
            tail = "\n".encode("utf-16le" if modern else "utf-8") + parameter_record + tail
        return cls._record(signature, body + xml + tail)

    @classmethod
    def _parameter_server(cls, xml):
        return cls._record(b"\x01\x00\x01\x00", xml.encode("utf-8"))

    def _write(self, records):
        with zipfile.ZipFile(self.path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in records:
                zf.writestr(name, data)

    def test_native_reports_and_both_provider_variants_are_metadata_only(self):
        provider_name = "Requ\u00eate \U0001f310 / O'Brien"
        report_name = "R\u00e9sum\u00e9 / 100% (ventes)"
        for modern in (True, False):
            with self.subTest(modern=modern):
                self._write([
                    ("Data/RE/DOCSPEC", self._docspec([("831", report_name)])),
                    ("Data/C3/DATAPROVIDERS/DP0/DP_Generic",
                     self._provider(provider_name, modern=modern)),
                ])
                extracted = extract_webi(self.path)
                self.assertEqual(len(extracted), 15)
                self.assertEqual([(r["id"], r["name"]) for r in extracted["reports"]],
                                 [("831", report_name)])
                query = extracted["queries"][0]
                self.assertEqual((query["id"], query["name"]), ("DP0", provider_name))
                identifiers = ["obj-1", "obj-2"] if modern else ["DS1.DObc", "DS1.DOc2"]
                self.assertEqual(query["objects"], [
                    {"identifier": identifiers[0], "name": "R\u00e9gion / %"},
                    {"identifier": identifiers[1], "name": "Revenue"},
                ])
                self.assertEqual(query["type"], "")
                self.assertEqual(query["sql"], "")
                self.assertEqual(query["datasource"], "")
                self.assertTrue(query["native_wid_partial"])
                self.assertEqual(query["native_prompt_metadata"]["status"], "not_observed")
                self.assertTrue(extracted["reports"][0]["native_wid_partial"])
                for category, items in extracted.items():
                    if category not in ("reports", "queries"):
                        self.assertEqual(items, [], category)
                converted = adapt_bo_to_converted_objects(extracted)
                self.assertEqual(converted["datasources"], [])
                self.assertEqual(converted["custom_sql"], [])
                self.assertEqual(converted["calculations"], [])
                self.assertEqual(converted["worksheets"], [])
                self.assertEqual(converted["dashboards"], [])

                output = os.path.join(self.temporary.name, "extracted")
                persisted = extract_bo_data(self.path, output_dir=output)
                self.assertEqual(load_extracted_data(output), persisted)
                self.assertEqual(persisted["queries"][0]["objects"], query["objects"])

    def test_native_docspec_extracts_partial_sections_and_table_structure(self):
        self._write([
            ("Data/RE/DOCSPEC", self._docspec(
                [("1", "Report")], include_layout=True,
            )),
        ])

        extracted = extract_webi(self.path)
        report = extracted["reports"][0]

        self.assertEqual(report["sections"], [{
            "type": "section",
            "native_wid_partial": True,
            "id": "section-1",
        }])
        self.assertEqual(report["elements"], [
            {
                "type": "vtable",
                "native_wid_partial": True,
                "id": "table-1",
                "row_info_count": 1,
                "column_info_count": 2,
            },
            {
                "type": "htable",
                "native_wid_partial": True,
                "id": "table-2",
            },
            {
                "type": "xtable",
                "native_wid_partial": True,
                "id": "table-3",
            },
        ])
        with self.assertLogs("bo_export.converted_objects_adapter", level="WARNING") as logged:
            converted = adapt_bo_to_converted_objects(extracted)
        self.assertEqual(converted["worksheets"], [])
        self.assertEqual(converted["dashboards"], [])
        self.assertIn("visual layout was not fully extracted", " ".join(logged.output))

    def test_native_prompt_metadata_omits_labels_and_values_in_both_variants(self):
        server = self._parameter_server(
            '<PARAMSERVER><PARAMETER TYPE="prompt" NAME="PRIVATE_NAME" ID="PRIVATE_ID" '
            'VALUETYPE="string" KIND="multivalue" MULTI="multi" ANSWERTYPE="monovalue">'
            '<PROMPTINFO OPTIONAL="yes" CONSTRAINED="FreeLov" PERSISTENT="yes" ORDER="2">'
            '<QUESTION>PRIVATE_QUESTION</QUESTION><LISTOFVALUE TYPELOV="static">'
            '<VALUE>PRIVATE_LIST_VALUE</VALUE></LISTOFVALUE></PROMPTINFO>'
            '<CURRENTVALUE>PRIVATE_CURRENT</CURRENTVALUE>'
            '<PREVIOUSVALUE>PRIVATE_PREVIOUS</PREVIOUSVALUE>'
            '<DEFAULTVALUE>PRIVATE_DEFAULT</DEFAULTVALUE></PARAMETER>'
            '<PARAMETER TYPE="prompt" VALUETYPE="date" KIND="monovalue">'
            '<PROMPTINFO><LISTOFVALUE TYPELOV="dynamic"/></PROMPTINFO></PARAMETER>'
            '<PARAMETER TYPE="other" NAME="PRIVATE_OTHER"/>'
            '</PARAMSERVER>'
        )
        member = "Data/C3/DATAPROVIDERS/DP0/DP_Generic"
        for modern in (True, False):
            with self.subTest(modern=modern):
                provider = self._provider("Query 1", modern=modern, parameter_record=server)
                self._write([(member, provider)])
                extracted = extract_webi(self.path)
                query = extracted["queries"][0]
                metadata = query["native_prompt_metadata"]
                self.assertEqual(metadata["status"], "available")
                self.assertEqual(metadata["provider_id"], "DP0")
                self.assertEqual(metadata["source_member"], member)
                self.assertEqual(metadata["source_member_sha256"], hashlib.sha256(provider).hexdigest())
                self.assertEqual(metadata["record_offset"], provider.index(server))
                self.assertEqual(metadata["parameters"], [
                    {
                        "position": 1, "value_type": "string", "kind": "multivalue",
                        "multi": "multi", "answer_type": "monovalue", "optional": "yes",
                        "constrained": "FreeLov", "persistent": "yes", "order": 2,
                        "list_type": "static",
                    },
                    {"position": 2, "value_type": "date", "kind": "monovalue",
                     "list_type": "dynamic"},
                ])
                self.assertNotIn("PRIVATE_", json.dumps(extracted))
                self.assertEqual(extracted["prompts"], [])
                converted = adapt_bo_to_converted_objects(extracted)
                self.assertEqual(converted["parameters"], [])
                self.assertEqual(converted["datasources"], [])

                output = os.path.join(self.temporary.name, f"prompt-{modern}")
                persisted = extract_bo_data(self.path, output_dir=output)
                self.assertEqual(persisted["queries"][0]["native_prompt_metadata"], metadata)
                loaded = load_extracted_data(output)
                self.assertEqual(loaded["queries"][0]["native_prompt_metadata"], metadata)
                self.assertEqual(loaded["prompts"], [])
                with open(os.path.join(output, "queries.json"), encoding="utf-8") as saved:
                    self.assertNotIn("PRIVATE_", saved.read())

    def test_invalid_prompt_record_preserves_the_provider_and_reports_failure(self):
        valid = self._parameter_server('<PARAMSERVER><PARAMETER TYPE="prompt"/></PARAMSERVER>')
        cases = {
            "signature": valid[:4] + b"\x00\x00\x00\x00" + valid[8:],
            "length": (0x7fffffff).to_bytes(4, "little") + valid[4:],
            "xml": self._parameter_server("<PARAMSERVER>"),
            "root": self._parameter_server("<OTHER/>"),
            "entity": self._parameter_server(
                '<!DOCTYPE PARAMSERVER [<!ENTITY x "x">]><PARAMSERVER>&x;</PARAMSERVER>'
            ),
            "duplicate info": self._parameter_server(
                '<PARAMSERVER><PARAMETER TYPE="prompt"><PROMPTINFO/><PROMPTINFO/>'
                '</PARAMETER></PARAMSERVER>'
            ),
            "duplicate lists": self._parameter_server(
                '<PARAMSERVER><PARAMETER TYPE="prompt"><PROMPTINFO>'
                '<LISTOFVALUE/><LISTOFVALUE/></PROMPTINFO></PARAMETER></PARAMSERVER>'
            ),
        }
        for label, record in cases.items():
            with self.subTest(label=label):
                provider = self._provider("Query 1", parameter_record=record)
                self._write([("Data/C3/DATAPROVIDERS/DP0/DP_Generic", provider)])
                with self.assertLogs("bo_export.webi_extractor", level="WARNING") as logged:
                    extracted = extract_webi(self.path)
                self.assertEqual(len(extracted["queries"]), 1)
                self.assertEqual(extracted["queries"][0]["id"], "DP0")
                self.assertEqual(extracted["queries"][0]["native_prompt_metadata"]["status"], "invalid")
                self.assertIn("PARAMSERVER", " ".join(logged.output))
                self.assertEqual(extracted["prompts"], [])

    def test_unknown_prompt_attributes_are_omitted_without_exposing_values(self):
        server = self._parameter_server(
            '<PARAMSERVER><PARAMETER TYPE="prompt" VALUETYPE="PRIVATE_VALUE" '
            'KIND="monovalue"><PROMPTINFO OPTIONAL="PRIVATE_OPTION" '
            'ORDER="PRIVATE_ORDER"><LISTOFVALUE TYPELOV="PRIVATE_LIST"/>'
            '</PROMPTINFO></PARAMETER></PARAMSERVER>'
        )
        self._write([
            ("Data/C3/DATAPROVIDERS/DP0/DP_Generic",
             self._provider("Query 1", parameter_record=server)),
        ])
        with self.assertLogs("bo_export.webi_extractor", level="WARNING") as logged:
            extracted = extract_webi(self.path)
        metadata = extracted["queries"][0]["native_prompt_metadata"]
        self.assertEqual(metadata["parameters"], [{"position": 1, "kind": "monovalue"}])
        self.assertNotIn("PRIVATE_", json.dumps(extracted))
        self.assertNotIn("PRIVATE_", " ".join(logged.output))
        self.assertIn("Omitting unsupported PARAMSERVER", " ".join(logged.output))

    def test_native_prompt_evidence_does_not_infer_a_generic_provider_by_name(self):
        server = self._parameter_server(
            '<PARAMSERVER><PARAMETER TYPE="prompt" VALUETYPE="numeric" KIND="monovalue"/>'
            '</PARAMSERVER>'
        )
        generic = (
            '<document><connection id="sales" name="Sales" type="SQL Server"/>'
            '<dataprovider name="Query 1" connectionId="sales">'
            '<resultObject name="Revenue" table="Query 1" dataType="number"/>'
            '<SQL>SELECT Revenue FROM Sales</SQL></dataprovider></document>'
        )
        self._write([
            ("Data/C3/DATAPROVIDERS/DP0/DP_Generic",
             self._provider("Query 1", parameter_record=server)),
            ("document.xml", generic),
        ])
        extracted = extract_webi(self.path)
        self.assertEqual(len(extracted["queries"]), 2)
        generic_query, evidence = extracted["queries"]
        self.assertNotIn("native_prompt_metadata", generic_query)
        self.assertTrue(evidence["native_wid_evidence_only"])
        self.assertEqual(evidence["native_prompt_metadata"]["status"], "available")
        converted = adapt_bo_to_converted_objects(extracted)
        table = converted["datasources"][0]["tables"][0]
        self.assertEqual(table["sql"], "SELECT Revenue FROM Sales")
        self.assertEqual([column["name"] for column in table["columns"]], ["Revenue"])
        self.assertEqual(converted["parameters"], [])

    def test_native_prompt_metadata_merges_only_on_a_unique_provider_id(self):
        server = self._parameter_server('<PARAMSERVER><PARAMETER TYPE="prompt"/></PARAMSERVER>')
        self._write([
            ("Data/C3/DATAPROVIDERS/DP0/DP_Generic",
             self._provider("Query 1", parameter_record=server)),
            ("document.xml", '<document><dataprovider id="DP0" name="Query 1"/>'
                             '</document>'),
        ])
        queries = extract_webi(self.path)["queries"]
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]["native_prompt_metadata"]["parameters"], [{"position": 1}])
        self.assertNotIn("native_wid_evidence_only", queries[0])

        self._write([
            ("Data/C3/DATAPROVIDERS/DP0/DP_Generic",
             self._provider("Query 1", parameter_record=server)),
            ("document.xml", '<document><dataprovider id="DP0" name="Query 1"/>'
                             '<dataprovider id="DP0" name="Query 1"/></document>'),
        ])
        queries = extract_webi(self.path)["queries"]
        self.assertEqual(len(queries), 3)
        self.assertTrue(all("native_prompt_metadata" not in query for query in queries[:2]))
        self.assertTrue(queries[2]["native_wid_evidence_only"])
        self.assertEqual(queries[2]["native_prompt_metadata"]["status"], "available")

    def test_rejects_invalid_document_records_and_ambiguous_reports(self):
        valid = self._docspec([("1", "Report")])
        xml = (
            '<DOCUMENT RSVERSION="2.5">'
            '<REPORT RID="1"><PLIST><PVAL NAME="name">{"l":"A"}</PVAL></PLIST></REPORT>'
            '<REPORT RID="1"><PLIST><PVAL NAME="name">{"l":"B"}</PVAL></PLIST></REPORT>'
            '</DOCUMENT>'
        )
        ambiguous_name = (
            '<DOCUMENT RSVERSION="2.5"><REPORT RID="1"><PLIST>'
            '<PVAL NAME="name">{"l":"A"}</PVAL><PVAL NAME="name">{"l":"B"}</PVAL>'
            '</PLIST></REPORT></DOCUMENT>'
        )
        invalid_json = (
            '<DOCUMENT RSVERSION="2.5"><REPORT RID="1"><PLIST>'
            '<PVAL NAME="name">not-json</PVAL></PLIST></REPORT></DOCUMENT>'
        )
        cases = {
            "truncated": valid[:-1],
            "header": self._record(b"\x01\x00\x02\x00", b"<DOCUMENT/>"),
            "version": self._docspec([("1", "Report")], version="3.0"),
            "duplicate IDs": self._record(b"\x05\x00\x02\x00", xml.encode()),
            "duplicate names": self._record(b"\x05\x00\x02\x00", ambiguous_name.encode()),
            "bad JSON": self._record(b"\x05\x00\x02\x00", invalid_json.encode()),
            "XML declaration": self._record(
                b"\x05\x00\x02\x00",
                b'<!DOCTYPE DOCUMENT [<!ENTITY x "x">]><DOCUMENT RSVERSION="2.5"/>',
            ),
        }
        for label, record in cases.items():
            with self.subTest(label=label):
                self._write([("Data/RE/DOCSPEC", record)])
                with self.assertLogs("bo_export.webi_extractor", level="WARNING") as logged:
                    extracted = extract_webi(self.path)
                self.assertEqual(extracted["reports"], [])
                self.assertIn("native wid", " ".join(logged.output).lower())

    def test_rejects_ambiguous_or_corrupt_provider_records(self):
        valid = self._provider("Query 1")
        bad_name_length = valid[:8] + b"\xff\xff\xff\xff" + valid[12:]
        invalid_utf16 = valid[:12] + b"\x00\xd8" + valid[14:]
        duplicate_xml = valid + "<queryspec:QuerySpec".encode("utf-16le")
        duplicate_xml = len(duplicate_xml).to_bytes(4, "little") + duplicate_xml[4:]
        cases = {
            "truncated": valid[:-1],
            "name length": bad_name_length,
            "invalid UTF-16": invalid_utf16,
            "provider ID": self._provider("Query 1", provider_id="DP1"),
            "duplicate XML": duplicate_xml,
            "missing closing tag": self._record(
                b"\x02\x00\x03\x00",
                valid[8:].replace("</queryspec:QuerySpec>".encode("utf-16le"), b""),
            ),
        }
        for label, record in cases.items():
            with self.subTest(label=label):
                self._write([
                    ("Data/RE/DOCSPEC", self._docspec([("1", "Report")])),
                    ("Data/C3/DATAPROVIDERS/DP0/DP_Generic", record),
                ])
                with self.assertLogs("bo_export.webi_extractor", level="WARNING") as logged:
                    extracted = extract_webi(self.path)
                self.assertEqual(extracted["queries"], [])
                self.assertEqual(extracted["reports"][0]["name"], "Report")
                self.assertIn("Cannot parse native WID member", " ".join(logged.output))

    def test_duplicate_members_and_size_limits_do_not_pick_an_arbitrary_record(self):
        provider = self._provider("Query 1")
        self._write([
            ("Data/RE/DOCSPEC", self._docspec([("1", "Report")])),
            ("Data/C3/DATAPROVIDERS/DP0/DP_Generic", provider),
            ("data/c3/dataproviders/dp0/dp_generic", provider),
        ])
        with self.assertLogs("bo_export.webi_extractor", level="WARNING") as logged:
            extracted = extract_webi(self.path)
        self.assertEqual(extracted["queries"], [])
        self.assertEqual(extracted["reports"][0]["name"], "Report")
        self.assertIn("ambiguous duplicate", " ".join(logged.output))

        self._write([
            ("Data/RE/DOCSPEC", self._docspec([("1", "Report")])),
            ("Data/C3/DATAPROVIDERS/DP0/DP_Generic", provider + b"x" * 512),
        ])
        with patch("bo_export.webi_extractor._NATIVE_WID_RECORD_LIMIT", 512), \
             self.assertLogs("bo_export.webi_extractor", level="WARNING") as logged:
            extracted = extract_webi(self.path)
        self.assertEqual(extracted["queries"], [])
        self.assertEqual(extracted["reports"][0]["name"], "Report")
        self.assertIn("exceeding size limits", " ".join(logged.output))

    def test_native_total_size_limit_includes_the_exact_boundary(self):
        docspec = self._docspec([("1", "Report")])
        provider = self._provider("Query 1")
        self._write([
            ("Data/RE/DOCSPEC", docspec),
            ("Data/C3/DATAPROVIDERS/DP0/DP_Generic", provider),
        ])
        limit = len(docspec) + len(provider)
        with patch("bo_export.webi_extractor._NATIVE_WID_TOTAL_LIMIT", limit):
            self.assertEqual(len(extract_webi(self.path)["queries"]), 1)
        with patch("bo_export.webi_extractor._NATIVE_WID_TOTAL_LIMIT", limit - 1), \
             self.assertLogs("bo_export.webi_extractor", level="WARNING") as logged:
            extracted = extract_webi(self.path)
        self.assertEqual(len(extracted["reports"]), 1)
        self.assertEqual(extracted["queries"], [])
        self.assertIn("exceeding size limits", " ".join(logged.output))

    def test_generic_and_native_representations_do_not_duplicate_same_identity(self):
        self._write([
            ("Data/RE/DOCSPEC", self._docspec(
                [("1", "Overview"), ("2", "Second")], include_layout=True,
            )),
            ("Data/C3/DATAPROVIDERS/DP0/DP_Generic", self._provider("Query 1")),
            ("document.xml", (
                '<document><report id="1" name="Overview"/>'
                '<dataprovider id="DP0" name="Query 1"><SQL>SELECT 1</SQL>'
                '</dataprovider></document>'
            )),
        ])
        extracted = extract_webi(self.path)
        self.assertEqual([report["name"] for report in extracted["reports"]],
                         ["Overview", "Second"])
        self.assertEqual(len(extracted["reports"][0]["sections"]), 1)
        self.assertEqual(len(extracted["reports"][0]["elements"]), 3)
        self.assertEqual(len(extracted["reports"][1]["sections"]), 1)
        self.assertEqual(len(extracted["reports"][1]["elements"]), 3)
        self.assertEqual(len(extracted["queries"]), 1)
        self.assertEqual(extracted["queries"][0]["sql"], "SELECT 1")
        self.assertTrue(extracted["queries"][0]["native_wid_partial"])
        self.assertTrue(extracted["reports"][0]["native_wid_partial"])


if __name__ == "__main__":
    unittest.main()
