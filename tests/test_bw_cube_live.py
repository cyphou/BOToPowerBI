"""Offline tests for the bounded live BO cube navigation workflow."""

import io
import json
import os
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import migrate_bw_cube_live as live

ROOT = Path(__file__).resolve().parents[1]
PLAN_SOURCE = ROOT / "docs" / "fixtures" / "sap_bw_bex_pbip_plan.example.json"
TOKEN = "cube-session-token-93e6"
CONNECTION = "Connexion é & %"
PATH = "/Région/日 & <Nord>/"
PATTERN = "*Ventes 中文 & <2026>*"
NAVIGATION = (
    b'<bwconnection><bwnode type="Cube" name="private-cube"/>'
    b'<bwnode type="InfoCube" id="private-id"/><x:bwnode xmlns:x="urn:x" type="Query"/>'
    b'<bwnode type="Dimension"/><bwnode type="Measure"/><bwnode type="Other-private"/>'
    b'<bwnode/><item type="Measure"/></bwconnection>'
)


class TestBWCubeLive(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.output = self.root / "draft"
        self.plan = self.root / "plan.json"
        self.plan.write_bytes(PLAN_SOURCE.read_bytes())
        self.requests = []
        self.responses = [b'<bwconnection><name>private-connection</name></bwconnection>', NAVIGATION]
        self.enterContext(patch.dict(os.environ, {"BO_LOGON_TOKEN": TOKEN}))
        self.enterContext(patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")))
        self.opener = self.enterContext(patch("urllib.request.build_opener"))
        self.opener.return_value.open.side_effect = self._open

    def _open(self, request, timeout):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("unexpected network request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(response)

    def _args(self, selector=("--path", PATH)):
        return ["--server-url", "https://synthetic-bo.invalid", "--connection-id", CONNECTION,
                *selector, "--plan", str(self.plan), "--output-dir", str(self.output)]

    def _run(self, args=None, generation=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(live.subprocess, "run", side_effect=generation) if generation else patch.object(
            live.subprocess, "run", side_effect=self._generate
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = live.main(self._args() if args is None else args)
        self.assertNotIn(TOKEN, stdout.getvalue() + stderr.getvalue())
        return result, stdout.getvalue(), stderr.getvalue()

    def _generate(self, command, **kwargs):
        self.assertNotIn("BO_LOGON_TOKEN", kwargs["env"])
        output = Path(command[command.index("--output-dir") + 1])
        project = json.loads(self.plan.read_text(encoding="utf-8"))["project_name"]
        target = output / project
        target.mkdir(parents=True)
        (target / f"{project}.pbip").write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    def test_unicode_path_exact_request_and_sanitized_report(self):
        result, _, stderr = self._run()
        self.assertEqual((result, stderr), (0, ""))
        self.assertEqual(len(self.requests), 2)
        connection_request, browse_request = (item[0] for item in self.requests)
        self.assertEqual(connection_request.get_method(), "GET")
        self.assertEqual(browse_request.get_method(), "PUT")
        self.assertTrue(browse_request.full_url.endswith("/bwconnections/Connexion%20%C3%A9%20%26%20%25"))
        body = ET.fromstring(browse_request.data)
        self.assertEqual(body.tag, "bwnode")
        self.assertEqual(body[0].tag, "path")
        self.assertEqual(body[0].text, PATH)
        self.assertEqual(browse_request.get_header("X-sap-logontoken"), TOKEN)
        report = json.loads((self.output / "migration_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["metadata"]["bwnode_counts"], {
            "Cube": 1, "InfoCube": 1, "Query": 0, "Dimension": 1, "Measure": 1, "other_or_missing": 2,
        })
        self.assertEqual(report["workflow_status"], "partial_needs_review")
        self.assertEqual(set(report["verification"].values()), {"not_verified"})
        self.assertEqual(set(report["runtime_evidence"].values()), {"not_run"})
        text = json.dumps(report, ensure_ascii=False)
        for secret in ("private-cube", "private-id", "private-connection", "Other-private", "<bwconnection>", TOKEN):
            self.assertNotIn(secret, text)

    def test_unicode_pattern_exact_request(self):
        self.responses = [b"<bwconnection/>", NAVIGATION]
        result, _, _ = self._run(self._args(selector=("--pattern", PATTERN)))
        self.assertEqual(result, 0)
        body = ET.fromstring(self.requests[1][0].data)
        self.assertEqual(body[0].tag, "pattern")
        self.assertEqual(body[0].text, PATTERN)

    def test_neither_and_both_selectors_are_invalid(self):
        base = ["--server-url", "https://synthetic-bo.invalid", "--connection-id", CONNECTION,
                "--plan", str(self.plan), "--output-dir", str(self.output)]
        for args in (base, [*base, "--path", PATH, "--pattern", PATTERN]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as caught, redirect_stderr(io.StringIO()):
                live.main(args)
            self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.requests, [])

    def test_bad_xml_does_not_generate_or_publish(self):
        for response in (b"<bwconnection>", b"<wrong/>", b"<!DOCTYPE bwconnection><bwconnection/>"):
            with self.subTest(response=response):
                self.responses = [b"<bwconnection/>", response]
                with patch.object(live.subprocess, "run") as generation:
                    result, _, _ = self._run()
                self.assertEqual(result, 2)
                generation.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_existing_output_fails_before_network(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        result, _, _ = self._run()
        self.assertEqual(result, 2)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertEqual(self.requests, [])

    def test_generation_failure_publishes_sanitized_partial_report(self):
        def fail(command, **kwargs):
            self.assertNotIn("BO_LOGON_TOKEN", kwargs["env"])
            output = Path(command[command.index("--output-dir") + 1])
            output.mkdir(parents=True)
            (output / "partial.txt").write_text("partial", encoding="utf-8")
            return SimpleNamespace(returncode=1)

        result, _, stderr = self._run(generation=fail)
        self.assertEqual(result, 1)
        self.assertIn("incomplete", stderr)
        report = json.loads((self.output / "migration_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["generation"]["status"], "failed_or_incomplete")
        self.assertTrue((self.output / "pbip" / "partial.txt").is_file())
        self.assertNotIn(TOKEN, (self.output / "migration_report.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
