"""Tests for read-only WebI metadata requests."""

import json
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch

from bo_export.server_client import BOServerClient


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.body[:limit]


class TestWebiServerClient(unittest.TestCase):
    def setUp(self):
        self.client = BOServerClient("https://bo.example.invalid:6405", token="test-token")
        self.client.logon()

    def test_lists_providers_and_reads_details(self):
        listed = {"dataproviders": {"dataprovider": [
            {"id": "DP0", "name": "Sales", "dataSourceId": 15, "dataSourceType": "unx"},
            {"id": "DP1", "name": "Budget", "dataSourceType": "excel"},
        ]}}
        details = {"dataprovider": {"id": "DP0", "name": "Sales", "dictionary": {}}}
        singleton = {"dataproviders": {"dataprovider": {"id": "DP0", "name": "Sales"}}}
        empty = {"dataproviders": {}}
        responses = [_Response(json.dumps(item).encode("utf-8"))
                     for item in (listed, details, singleton, empty)]

        with patch("bo_export.server_client.urllib.request.urlopen", side_effect=responses) as urlopen:
            self.assertEqual(self.client.list_webi_data_providers(12345), listed["dataproviders"]["dataprovider"])
            self.assertEqual(self.client.get_webi_data_provider(12345, "DP0"), details["dataprovider"])
            self.assertEqual(self.client.list_webi_data_providers(12345), [singleton["dataproviders"]["dataprovider"]])
            self.assertEqual(self.client.list_webi_data_providers(12345), [])

        request = urlopen.call_args_list[1].args[0]
        self.assertEqual(
            request.full_url,
            "https://bo.example.invalid:6405/biprws/raylight/v1/documents/12345/dataproviders/DP0",
        )
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(request.get_header("X-sap-logontoken"), "test-token")
        self.assertEqual(urlopen.call_args_list[1].kwargs["timeout"], 30)

    def test_lists_reports_and_reads_details_without_losing_metadata(self):
        reports = [
            {"id": 0, "name": "Résumé", "extra": {"kind": "report"}},
            {"id": "onglet 2", "name": "Détails"},
        ]
        detail = {"id": 0, "name": "Résumé", "extra": {"format": "A4"}}
        responses = [
            {"reports": {"report": reports}}, {"report": detail},
            {"reports": {"report": reports[1]}}, {"reports": {}},
        ]
        with patch("bo_export.server_client.urllib.request.urlopen",
                   side_effect=[_Response(json.dumps(item).encode("utf-8"))
                                for item in responses]) as urlopen:
            self.assertEqual(self.client.list_webi_reports("42"), reports)
            self.assertEqual(self.client.get_webi_report("42", "0"), detail)
            self.assertEqual(self.client.list_webi_reports("42"), [reports[1]])
            self.assertEqual(self.client.list_webi_reports("42"), [])
        request = urlopen.call_args_list[1].args[0]
        self.assertTrue(request.full_url.endswith("/documents/42/reports/0"))
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(request.get_header("X-sap-logontoken"), "test-token")
        self.assertEqual(urlopen.call_args_list[1].kwargs["timeout"], 30)

    def test_report_metadata_rejects_bad_identity_and_inconsistent_responses(self):
        cases = [
            (b'{"reports":{"report":[{"id":1},{"id":"1"}]}}', self.client.list_webi_reports, ("42",)),
            (b'{"reports":{"report":[{"id":true}]}}', self.client.list_webi_reports, ("42",)),
            (b'{"reports":{"report":[{"id":"../x"}]}}', self.client.list_webi_reports, ("42",)),
            (b'{"report":{"id":"other"}}', self.client.get_webi_report, ("42", "1")),
            (b'{"report":{"name":"missing ID"}}', self.client.get_webi_report, ("42", "1")),
            (b'{"unexpected":[]}', self.client.list_webi_reports, ("42",)),
        ]
        for body, method, args in cases:
            with self.subTest(body=body), patch(
                "bo_export.server_client.urllib.request.urlopen", return_value=_Response(body)
            ):
                with self.assertRaises(ValueError):
                    method(*args)
        with patch("bo_export.server_client.urllib.request.urlopen") as urlopen:
            for args in (("42", "../x"), ("..", "1"), ("42", None)):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    self.client.get_webi_report(*args)
            self.client._session_id = None
            with self.assertRaises(RuntimeError):
                self.client.list_webi_reports("42")
            urlopen.assert_not_called()

    def test_lists_report_elements_with_original_layout_and_parent_ids(self):
        elements = [
            {"id": 1, "@type": "PageZone", "name": "Header"},
            {"id": 19, "@type": "Cell", "reference": "1.J", "parentId": 1,
             "position": {"@x": "15.322", "@y": "0.104"}},
        ]
        responses = [
            {"elements": {"element": elements}},
            {"elements": {"element": elements[1]}},
            {"elements": {}},
        ]
        with patch("bo_export.server_client.urllib.request.urlopen",
                   side_effect=[_Response(json.dumps(item).encode("utf-8"))
                                for item in responses]) as urlopen:
            self.assertEqual(self.client.list_webi_report_elements("42", "onglet 2", True),
                             elements)
            self.assertEqual(self.client.list_webi_report_elements("42", 1), [elements[1]])
            self.assertEqual(self.client.list_webi_report_elements("42", 1), [])
        self.assertTrue(urlopen.call_args_list[0].args[0].full_url.endswith(
            "/documents/42/reports/onglet%202/elements?allInfo=true"))
        self.assertTrue(urlopen.call_args_list[1].args[0].full_url.endswith(
            "/documents/42/reports/1/elements"))

    def test_report_elements_reject_ambiguous_data_and_invalid_options(self):
        for body in (b'{"elements":{"element":[{"id":1},{"id":"1"}]}}',
                     b'{"elements":{"element":[{"id":null}]}}',
                     b'{"elements":{"element":"invalid"}}', b'{"error":"forbidden"}'):
            with self.subTest(body=body), patch(
                "bo_export.server_client.urllib.request.urlopen", return_value=_Response(body)
            ):
                with self.assertRaises(ValueError):
                    self.client.list_webi_report_elements("42", "1")
        with patch("bo_export.server_client.urllib.request.urlopen") as urlopen:
            for args in (("42", "../x", False), ("42", "1", 1)):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    self.client.list_webi_report_elements(*args)
            urlopen.assert_not_called()
        with patch("bo_export.server_client._WEBI_RESPONSE_LIMIT", 4), patch(
            "bo_export.server_client.urllib.request.urlopen", return_value=_Response(b"12345")
        ):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                self.client.list_webi_report_elements("42", "1")
        error = urllib.error.HTTPError("https://bo.example.invalid", 403, "Forbidden", Message(), None)
        with patch("bo_export.server_client.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                self.client.list_webi_report_elements("42", "1")

    def test_document_snapshot_preserves_reports_elements_and_providers(self):
        reports = [{"id": "1", "name": "Overview"}]
        report_details = {"id": "1", "name": "Overview", "pageSettings": {"width": "10"}}
        elements = [{"id": "19", "@type": "Cell", "reference": "1.J", "parentId": "1"}]
        providers = [{"id": "DP0", "name": "Sales", "dataSourceType": "unx"}]
        provider_details = {"id": "DP0", "name": "Sales", "dictionary": {}}
        responses = [
            {"reports": {"report": reports}},
            {"report": report_details},
            {"elements": {"element": elements}},
            {"dataproviders": {"dataprovider": providers}},
            {"dataprovider": provider_details},
        ]
        with patch("bo_export.server_client.urllib.request.urlopen",
                   side_effect=[_Response(json.dumps(item).encode("utf-8"))
                                for item in responses]) as urlopen:
            snapshot = self.client.get_webi_document_snapshot("42", True)

        self.assertEqual(snapshot, {
            "schema_version": "1.0",
            "document_id": "42",
            "reports": [{
                "summary": reports[0], "details": report_details, "elements": elements,
            }],
            "data_providers": [{
                "summary": providers[0], "details": provider_details,
            }],
        })
        self.assertIn("allInfo=true", urlopen.call_args_list[2].args[0].full_url)

    def test_document_snapshot_surfaces_http_failures_and_rejects_bad_options(self):
        with patch("bo_export.server_client.urllib.request.urlopen") as urlopen:
            for args in (("42", 1), ("../42", False), ("42", False, 1)):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    self.client.get_webi_document_snapshot(*args)
            urlopen.assert_not_called()
        error = urllib.error.HTTPError("https://bo.example.invalid", 403, "Forbidden", Message(), None)
        with patch("bo_export.server_client.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                self.client.get_webi_document_snapshot("42")

    def test_document_snapshot_option_captures_provider_plan_and_specification(self):
        responses = [
            {"reports": {}},
            {"dataproviders": {"dataprovider": {"id": "DP0", "name": "Sales"}}},
            {"dataprovider": {"id": "DP0", "name": "Sales"}},
        ]
        payloads = [json.dumps(item).encode("utf-8") for item in responses]
        payloads.extend([
            b'<queryplan><statement index="1">SELECT 1</statement></queryplan>',
            b'<QuerySpec dataProviderId="DP0"/>',
        ])
        with patch("bo_export.server_client.urllib.request.urlopen",
                   side_effect=[_Response(item) for item in payloads]) as urlopen:
            snapshot = self.client.get_webi_document_snapshot(
                "42", include_provider_query_metadata=True,
            )

        provider = snapshot["data_providers"][0]
        self.assertEqual(provider["query_plan"]["provider_id"], "DP0")
        self.assertEqual(provider["query_plan"]["statements"][0]["sql"], "SELECT 1")
        self.assertEqual(provider["query_specification_xml"],
                         '<QuerySpec dataProviderId="DP0"/>')
        self.assertTrue(urlopen.call_args_list[3].args[0].full_url.endswith("/DP0/queryplan"))
        self.assertTrue(urlopen.call_args_list[4].args[0].full_url.endswith("/DP0/specification"))

    def test_query_plan_preserves_composition_and_sql(self):
        xml = (
            '<queryplan custom="false"><union><fullOuterJoin>'
            '<statement index="1">SELECT Region FROM Sales</statement>'
            '<statement index="2">SELECT Region FROM Budget</statement>'
            '</fullOuterJoin></union></queryplan>'
        )
        with patch("bo_export.server_client.urllib.request.urlopen",
                   return_value=_Response(xml.encode("utf-8"))) as urlopen:
            plan = self.client.get_webi_query_plan("12345", "DP 0")

        self.assertEqual(plan["xml"], xml)
        self.assertEqual(plan["status"], "available")
        self.assertFalse(plan["single_statement"])
        self.assertEqual(plan["statements"], [
            {"index": "1", "sql": "SELECT Region FROM Sales", "operators": ["union", "fullOuterJoin"]},
            {"index": "2", "sql": "SELECT Region FROM Budget", "operators": ["union", "fullOuterJoin"]},
        ])
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/documents/12345/dataproviders/DP%200/queryplan"))
        self.assertEqual(request.get_header("Accept"), "application/xml")

    def test_single_and_empty_query_plans_are_distinguished(self):
        responses = [
            _Response(b'<queryplan><statement index="1">SELECT 1</statement></queryplan>'),
            _Response(b'<queryplan/>'),
        ]
        with patch("bo_export.server_client.urllib.request.urlopen", side_effect=responses):
            plan = self.client.get_webi_query_plan("42", "DP0")
            with self.assertLogs("bo_export.server_client", level="WARNING") as logged:
                empty = self.client.get_webi_query_plan("42", "DP1")
        self.assertTrue(plan["single_statement"])
        self.assertEqual(plan["statements"][0]["sql"], "SELECT 1")
        self.assertEqual(empty["status"], "empty")
        self.assertFalse(empty["single_statement"])
        self.assertEqual(empty["statements"], [])
        self.assertIn("no SQL statements", " ".join(logged.output))

    def test_query_specification_returns_original_xml(self):
        xml = (
            '<queryspec:QuerySpec xmlns:queryspec="http://com.sap.sl.queryspec" '
            'dataProviderId="DP0"><queriesTree/></queryspec:QuerySpec>'
        )
        with patch("bo_export.server_client.urllib.request.urlopen",
                   return_value=_Response(xml.encode("utf-8"))) as urlopen:
            self.assertEqual(self.client.get_webi_query_specification("42", "DP0"), xml)
        self.assertTrue(urlopen.call_args.args[0].full_url.endswith("/DP0/specification"))

    def test_http_and_invalid_response_errors_are_not_hidden(self):
        error = urllib.error.HTTPError("https://bo.example.invalid", 403, "Forbidden", Message(), None)
        with patch("bo_export.server_client.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                self.client.get_webi_query_plan("42", "DP0")

        cases = [
            (b'{"unexpected": []}', self.client.list_webi_data_providers, ("42",)),
            (b'{"dataproviders": {"dataprovider": [{"id":"DP0"},{"id":"DP0"}]}}',
             self.client.list_webi_data_providers, ("42",)),
            (b'{"dataprovider": {"id":"DP1"}}', self.client.get_webi_data_provider, ("42", "DP0")),
            (b'<error/>', self.client.get_webi_query_plan, ("42", "DP0")),
            (b'<queryplan><statement><nested/></statement></queryplan>',
             self.client.get_webi_query_plan, ("42", "DP0")),
            (b'<!DOCTYPE queryplan [<!ENTITY x "x">]><queryplan>&x;</queryplan>',
             self.client.get_webi_query_plan, ("42", "DP0")),
            (b'<QuerySpec dataProviderId="DP1"/>',
             self.client.get_webi_query_specification, ("42", "DP0")),
        ]
        for body, method, args in cases:
            with self.subTest(body=body), patch(
                "bo_export.server_client.urllib.request.urlopen", return_value=_Response(body)
            ):
                with self.assertRaises(ValueError):
                    method(*args)

    def test_invalid_ids_and_missing_session_do_not_make_requests(self):
        with patch("bo_export.server_client.urllib.request.urlopen") as urlopen:
            for document_id, provider_id in (("..", "DP0"), ("42", "../DP0"), ("42", "DP\\0")):
                with self.subTest(document_id=document_id, provider_id=provider_id):
                    with self.assertRaises(ValueError):
                        self.client.get_webi_query_plan(document_id, provider_id)
            for method in (self.client.get_webi_data_provider,
                           self.client.get_webi_query_plan,
                           self.client.get_webi_query_specification):
                with self.subTest(method=method.__name__), self.assertRaises(ValueError):
                    method("42", None)
            self.client._session_id = None
            with self.assertRaises(RuntimeError):
                self.client.list_webi_data_providers("42")
            urlopen.assert_not_called()

    def test_oversized_response_is_rejected(self):
        with patch("bo_export.server_client._WEBI_RESPONSE_LIMIT", 4), \
             patch("bo_export.server_client.urllib.request.urlopen",
                   return_value=_Response(b"12345")):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                self.client.get_webi_query_plan("42", "DP0")

    def test_query_plan_nesting_limit_is_reported(self):
        xml = (
            "<queryplan>" + "<wrapper>" * 257 + "<statement>SELECT 1</statement>"
            + "</wrapper>" * 257 + "</queryplan>"
        )
        with patch("bo_export.server_client.urllib.request.urlopen",
                   return_value=_Response(xml.encode("utf-8"))):
            with self.assertRaisesRegex(ValueError, "nesting depth"):
                self.client.get_webi_query_plan("42", "DP0")


if __name__ == "__main__":
    unittest.main()
