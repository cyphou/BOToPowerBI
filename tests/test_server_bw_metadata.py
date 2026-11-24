"""Mock-only tests of bounded SAP BO BW metadata access."""

import io
import unittest
import urllib.error
import urllib.request
import urllib.response
import xml.etree.ElementTree as ET
from email.message import Message
from unittest.mock import Mock, patch

from bo_export.server_client import BOServerClient


class _Response:
    def __init__(self, body):
        self.body = body
        self.read_size = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        self.read_size = size
        return self.body[:size]


class TestServerBWMetadata(unittest.TestCase):
    def setUp(self):
        sockets = patch("socket.create_connection", side_effect=AssertionError("Network access forbidden"))
        sockets.start()
        self.addCleanup(sockets.stop)
        self.client = BOServerClient("https://bo.example.invalid:6405", token="secret-token")
        self.client.logon()

    def test_list_and_details_requests_preserve_xml(self):
        responses = [
            _Response(b'<bwconnections><bwconnection type="System"><id>7</id></bwconnection></bwconnections>'),
            _Response('<bwconnection><name>Résumé</name></bwconnection>'.encode()),
        ]
        opener = Mock()
        opener.open.side_effect = responses
        with patch("bo_export.server_client.urllib.request.build_opener", return_value=opener) as build:
            page = self.client.list_bw_connections(offset=12, limit=20)
            detail = self.client.get_bw_connection("Café 100%'(A)")
        self.assertEqual(page.find("bwconnection/id").text, "7")
        self.assertEqual(detail.find("name").text, "Résumé")
        list_request = opener.open.call_args_list[0].args[0]
        detail_request = opener.open.call_args_list[1].args[0]
        self.assertEqual(list_request.full_url, "https://bo.example.invalid:6405/biprws/raylight/v1/bwconnections?offset=12&limit=20")
        self.assertTrue(detail_request.full_url.endswith("/bwconnections/Caf%C3%A9%20100%25%27%28A%29"))
        for call, response in zip(opener.open.call_args_list, responses):
            req = call.args[0]
            self.assertEqual(req.get_method(), "GET")
            self.assertEqual(req.get_header("Accept"), "application/xml")
            self.assertEqual(req.get_header("X-sap-logontoken"), "secret-token")
            self.assertEqual(call.kwargs["timeout"], 30)
            self.assertEqual(response.read_size, 16 * 1024 * 1024 + 1)
        self.assertEqual(build.call_count, 2)

    def test_browse_and_outline_put_xml_preserve_values(self):
        opener = Mock()
        opener.open.side_effect = [
            _Response(b'<bwconnection><bwnodes/></bwconnection>'),
            _Response(b'<bwconnection/>'),
            _Response(b'<outline><item type="Measure"><id>M</id></item></outline>'),
        ]
        path = "/Région/日 & <Nord>/'100%'"
        pattern = "*Ventes & <2026>*"
        query_id = "  11990;日/é & <Q> '100%'  "
        with patch("bo_export.server_client.urllib.request.build_opener", return_value=opener):
            self.client.browse_bw_connection(11990, path=path)
            self.client.browse_bw_connection(11990, pattern=pattern)
            outline = self.client.get_bw_query_outline(11990, query_id)
        self.assertEqual(outline.find("item/id").text, "M")
        for call, tag, value in zip(opener.open.call_args_list,
                                    ("path", "pattern", "id"), (path, pattern, query_id)):
            req = call.args[0]
            self.assertEqual(req.get_method(), "PUT")
            self.assertEqual(req.get_header("Accept"), "application/xml")
            self.assertEqual(req.get_header("Content-type"), "application/xml; charset=utf-8")
            self.assertEqual(req.get_header("X-sap-logontoken"), "secret-token")
            node = ET.fromstring(req.data)
            self.assertEqual(node.tag, "bwnode")
            self.assertEqual(len(node), 1)
            self.assertEqual(node[0].tag, tag)
            self.assertEqual(node[0].text, value)
            self.assertNotIn(b"secret-token", req.data)
        self.assertTrue(opener.open.call_args_list[0].args[0].full_url.endswith("/bwconnections/11990"))
        self.assertTrue(opener.open.call_args_list[2].args[0].full_url.endswith("/bwconnections/11990/outline"))

    def test_invalid_inputs_and_missing_session_never_open(self):
        with patch("bo_export.server_client.urllib.request.build_opener") as build:
            for value in (None, True, "", " ", ".", "..", "a/b", "a\\b", "x\n"):
                with self.subTest(connection_id=value), self.assertRaises(ValueError):
                    self.client.get_bw_connection(value)
            for offset, limit in ((-1, 10), (True, 10), (0, 0), (0, 51), (0, True), (0, "1")):
                with self.subTest(offset=offset, limit=limit), self.assertRaises(ValueError):
                    self.client.list_bw_connections(offset, limit)
            for kwargs in ({}, {"path": "a", "pattern": "b"}, {"path": ""}, {"pattern": "\x00"}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    self.client.browse_bw_connection("7", **kwargs)
            for value in (None, " ", "x\r", "x\x00", "\ud800", "\uffff"):
                with self.subTest(query_id=value), self.assertRaises(ValueError):
                    self.client.get_bw_query_outline("7", value)
            self.client._session_id = None
            for action in (lambda: self.client.list_bw_connections(),
                           lambda: self.client.get_bw_connection("7"),
                           lambda: self.client.browse_bw_connection("7", path="/a"),
                           lambda: self.client.get_bw_query_outline("7", "7;Q")):
                with self.assertRaises(RuntimeError):
                    action()
            build.assert_not_called()

    def test_invalid_server_url_is_rejected_before_token_use(self):
        for url in ("file:///tmp", "https://user:pass@host", "https://host?q=x",
                    "https://host/#frag", "https://host:bad", "https://bad\nhost"):
            client = BOServerClient(url, token="secret-token")
            client.logon()
            with self.subTest(url=url), patch("bo_export.server_client.urllib.request.build_opener") as build:
                with self.assertRaises(ValueError):
                    client.list_bw_connections()
                build.assert_not_called()

    def test_http_server_url_is_rejected_before_authenticated_bw_requests(self):
        client = BOServerClient("http://bo.example.invalid:6405", token="secret-token")
        client.logon()
        actions = (lambda: client.list_bw_connections(),
                   lambda: client.get_bw_connection("7"),
                   lambda: client.browse_bw_connection("7", path="/a"),
                   lambda: client.get_bw_query_outline("7", "7;Q"))
        with patch.object(client, "_make_request") as make_request, patch(
                "bo_export.server_client.urllib.request.build_opener") as build:
            for action in actions:
                with self.subTest(action=action), self.assertRaisesRegex(ValueError, "HTTPS"):
                    action()
            make_request.assert_not_called()
            build.assert_not_called()

    def test_malformed_wrong_root_and_xml_declarations_rejected(self):
        cases = [
            b'<error/>', b'<bwconnections>', b'{"bwconnections":{}}',
            b'<!DOCTYPE bwconnections><bwconnections/>',
            b'<!DOCTYPE bwconnections [<!ENTITY x "hello">]><bwconnections>&x;</bwconnections>',
            b'<!DOCTYPE bwconnections SYSTEM "https://example.invalid/a"><bwconnections/>',
            '<!DOCTYPE bwconnections [<!ENTITY x "hello">]><bwconnections>&x;</bwconnections>'.encode('utf-16'),
        ]
        for payload in cases:
            opener = Mock()
            opener.open.return_value = _Response(payload)
            with self.subTest(payload=payload), patch("bo_export.server_client.urllib.request.build_opener", return_value=opener):
                with self.assertRaises(ValueError):
                    self.client.list_bw_connections()
        for action in (lambda: self.client.get_bw_connection("7"),
                       lambda: self.client.browse_bw_connection("7", path="/a"),
                       lambda: self.client.get_bw_query_outline("7", "7;Q")):
            opener = Mock()
            opener.open.return_value = _Response(b'<bwconnections/>')
            with patch("bo_export.server_client.urllib.request.build_opener", return_value=opener):
                with self.assertRaisesRegex(ValueError, "root"):
                    action()

    def test_valid_utf16_response_is_accepted(self):
        opener = Mock()
        opener.open.return_value = _Response(
            '<?xml version="1.0" encoding="UTF-16"?><bwconnection><name>東京</name></bwconnection>'.encode("utf-16")
        )
        with patch("bo_export.server_client.urllib.request.build_opener", return_value=opener):
            self.assertEqual(self.client.get_bw_connection("7").find("name").text, "東京")

    def test_response_and_request_size_limits(self):
        opener = Mock()
        response = _Response(b'<outline/>')
        opener.open.return_value = response
        with patch("bo_export.server_client._BW_RESPONSE_LIMIT", 4), patch(
                "bo_export.server_client.urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(ValueError, "response exceeds"):
                self.client.get_bw_connection("7")
            self.assertEqual(response.read_size, 5)
            opener.reset_mock()
            with self.assertRaisesRegex(ValueError, "request exceeds"):
                self.client.get_bw_query_outline("7", "q")
            opener.open.assert_not_called()

    def test_http_and_timeout_errors_propagate_without_retry_or_logging_token(self):
        error = urllib.error.HTTPError("https://bo.example.invalid", 403, "Forbidden", Message(), None)
        for failure in (error, TimeoutError("timed out")):
            opener = Mock()
            opener.open.side_effect = failure
            with self.subTest(failure=type(failure)), patch(
                    "bo_export.server_client.urllib.request.build_opener", return_value=opener), patch(
                    "bo_export.server_client.logger") as logger:
                with self.assertRaises(type(failure)) as caught:
                    self.client.get_bw_query_outline("7", "7;Q")
                self.assertIs(caught.exception, failure)
                self.assertNotIn("secret-token", str(caught.exception))
                opener.open.assert_called_once()
                logger.assert_not_called()

    def test_redirect_is_blocked_by_actual_opener_without_second_request(self):
        class FakeTransport(urllib.request.BaseHandler):
            handler_order = 100

            def __init__(self, status, location):
                self.requests = []
                self.status = status
                self.location = location

            def https_open(self, request):
                self.requests.append(request)
                headers = Message()
                headers["Location"] = self.location
                response = urllib.response.addinfourl(io.BytesIO(b""), headers, request.full_url, self.status)
                response.msg = "Found"
                return response

        build_opener = urllib.request.build_opener
        for status in (301, 302, 303, 307, 308):
            for location in ("https://other.example.invalid/steal", "/same-origin"):
                for method in ("GET", "PUT"):
                    with self.subTest(status=status, location=location, method=method):
                        transport = FakeTransport(status, location)
                        with patch("bo_export.server_client.urllib.request.build_opener",
                                   side_effect=lambda handler: build_opener(handler, transport)):
                            with self.assertRaises(urllib.error.HTTPError) as caught:
                                if method == "GET":
                                    self.client.list_bw_connections()
                                else:
                                    self.client.get_bw_query_outline("7", "7;Q")
                        self.assertEqual(caught.exception.code, status)
                        self.assertEqual(len(transport.requests), 1)
                        self.assertEqual(transport.requests[0].get_header("X-sap-logontoken"), "secret-token")


if __name__ == "__main__":
    unittest.main()
