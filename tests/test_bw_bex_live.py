"""Offline tests for the live BO BEx metadata and PBIP draft workflow."""

import copy
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import migrate_bw_bex_live as live

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "docs" / "fixtures"
TOKEN = "synthetic-session-token-93e6"
CONNECTION = "Connexion é & %"
QUERY = "Requête 中文 & <Q>"
OUTLINE = ("<outline><item type='Measure' caption='private-caption'/>"
           "<item type='Dimension'/><group><item type='Measure'/>"
           "<item type='Unknown-private-type'/><item/></group>"
           "<item type='measure'/><x:item xmlns:x='urn:test' type='Filter'/>"
           "</outline>").encode("utf-8")


class TestBWBExLive(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.output = self.root / "draft"
        self.plan_path = self.root / "plan.json"
        self.plan = json.loads(
            (FIXTURES / "sap_bw_bex_pbip_plan.example.json").read_text(encoding="utf-8")
        )
        self._write_plan(self.plan)
        self.requests = []
        self.responses = [b"<bwconnection><name>private-connection</name></bwconnection>", OUTLINE]
        self.enterContext(patch.dict(os.environ, {"BO_LOGON_TOKEN": TOKEN}))
        self.enterContext(patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("socket.socket.connect", side_effect=AssertionError("network forbidden")))
        self.opener = self.enterContext(patch("urllib.request.build_opener"))
        self.opener.return_value.open.side_effect = self._fake_open

    def _write_plan(self, value):
        self.plan_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def _fake_open(self, request, timeout):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("unexpected network request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(response)

    def _args(self):
        return ["--server-url", "https://synthetic-bo.invalid", "--connection-id", CONNECTION,
                "--bex-id", QUERY, "--plan", str(self.plan_path), "--output-dir", str(self.output)]

    def _run(self, args=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = live.main(self._args() if args is None else args)
        self.assertNotIn(TOKEN, stdout.getvalue() + stderr.getvalue())
        return result, stdout.getvalue(), stderr.getvalue()

    def _report(self):
        return json.loads((self.output / "migration_report.json").read_text(encoding="utf-8"))

    def _assert_no_staging(self):
        self.assertEqual(list(self.root.glob(".bex-live-*")), [])

    def _assert_no_token_in_output(self):
        for path in self.output.rglob("*"):
            self.assertNotIn(TOKEN, str(path))
            if path.is_file():
                self.assertNotIn(TOKEN.encode("utf-8"), path.read_bytes(), str(path))

    def test_real_generation_reports_metadata_not_identity_or_runtime_evidence(self):
        # Non-ASCII names exercise UTF-8 plan snapshots and generated artifacts.
        self.plan["datasource"]["name"] = "Données synthétiques"
        self.plan["datasource"]["tables"][0]["name"] = "Ventes é 中文"
        self._write_plan(self.plan)
        real_run = subprocess.run
        with patch.object(live.subprocess, "run", wraps=real_run) as generation:
            result, stdout, stderr = self._run()
        self.assertEqual((result, stderr), (0, ""))
        self.assertIn("unverified", stdout)
        self.assertEqual(len(self.requests), 2)
        connection_request, outline_request = (entry[0] for entry in self.requests)
        self.assertEqual(connection_request.get_method(), "GET")
        self.assertEqual(outline_request.get_method(), "PUT")
        self.assertTrue(connection_request.full_url.endswith("/bwconnections/Connexion%20%C3%A9%20%26%20%25"))
        self.assertTrue(outline_request.full_url.endswith("/outline"))
        self.assertEqual(ET.fromstring(outline_request.data).findtext("id"), QUERY)
        for request, timeout in self.requests:
            self.assertEqual(request.get_header("X-sap-logontoken"), TOKEN)
            self.assertEqual(timeout, 30)
        self.assertNotIn("BO_LOGON_TOKEN", generation.call_args.kwargs["env"])

        project = self.output / "pbip" / self.plan["project_name"]
        self.assertTrue((project / (self.plan["project_name"] + ".pbip")).is_file())
        tables = list(project.rglob("Ventes é 中文.tmdl"))
        self.assertEqual(len(tables), 1)
        self.assertIn("Ventes é 中文", tables[0].read_text(encoding="utf-8"))
        report = self._report()
        self.assertEqual(report["workflow_status"], "partial_needs_review")
        self.assertEqual(report["metadata"]["connection_fetch"], "completed")
        self.assertEqual(report["metadata"]["outline_fetch"], "completed")
        self.assertEqual(report["metadata"]["outline_item_counts"], {
            "Measure": 2, "Dimension": 1, "Characteristic": 0, "Hierarchy": 0,
            "Level": 0, "Variable": 0, "Filter": 0, "Attribute": 0,
            "KeyFigure": 0, "other_or_missing": 3,
        })
        self.assertEqual(report["generation"], {
            "exit_code": 0, "status": "completed", "partial_artifacts_may_exist": False,
        })
        self.assertEqual(report["static_validation"], "pass")
        self.assertIn("non-strict", report["static_validation_scope"])
        self.assertEqual(report["linkage"], "not_proven; the plan and outline are independent")
        self.assertEqual(report["verification"], dict.fromkeys(
            ("native_query_identity", "provider_identity", "cube_identity", "selector_correspondence",
             "bex_semantics", "equivalence"), "not_verified"))
        self.assertEqual(report["runtime_evidence"], dict.fromkeys(
            ("source_data_execution", "target_data_execution", "desktop_rendering", "refresh",
             "deployment", "business_approval"), "not_run"))
        report_text = json.dumps(report, ensure_ascii=False)
        for secret in (CONNECTION, QUERY, "private-caption", "private-connection", "Unknown-private-type"):
            self.assertNotIn(secret, report_text)
        self._assert_no_token_in_output()
        self._assert_no_staging()

    def test_invalid_xml_or_metadata_failure_never_publishes(self):
        cases = [
            (b"<bwconnection>", OUTLINE),
            (b"<wrong/>", OUTLINE),
            (b"<bwconnection/>", b"<outline><item></outline>"),
            (b"<bwconnection/>", b"<!DOCTYPE outline [<!ENTITY x 'bad'>]><outline>&x;</outline>"),
            (b"<bwconnection/>", b"<wrong/>"),
            (b"<bwconnection/>", urllib.error.URLError("failure " + TOKEN)),
        ]
        for connection, outline in cases:
            with self.subTest(connection=connection, outline=type(outline).__name__):
                self.responses = [connection, outline]
                self.requests.clear()
                with patch.object(live.subprocess, "run") as generation:
                    result, _, stderr = self._run()
                self.assertEqual(result, 2)
                self.assertIn("before publication", stderr)
                self.assertFalse(self.output.exists())
                generation.assert_not_called()
                self._assert_no_staging()

    def test_existing_output_is_never_overwritten_or_network_accessed(self):
        for kind in ("file", "directory"):
            with self.subTest(kind=kind):
                if kind == "file":
                    self.output.write_bytes(b"keep existing file")
                    marker = self.output
                else:
                    self.output.mkdir()
                    marker = self.output / "existing.txt"
                    marker.write_bytes(b"keep existing directory")
                before = marker.read_bytes()
                result, _, _ = self._run()
                self.assertEqual(result, 2)
                self.assertEqual(marker.read_bytes(), before)
                self.assertEqual(self.requests, [])
                if kind == "file":
                    self.output.unlink()
                else:
                    marker.unlink()
                    self.output.rmdir()
                self._assert_no_staging()

    def test_invalid_preflight_rejects_before_metadata(self):
        for label, change in (
            ("http", lambda args: args.__setitem__(1, "http://synthetic-bo.invalid")),
            ("userinfo", lambda args: args.__setitem__(1, "https://user@synthetic-bo.invalid")),
            ("query", lambda args: args.__setitem__(1, "https://synthetic-bo.invalid/?x=1")),
            ("invalid port", lambda args: args.__setitem__(1, "https://synthetic-bo.invalid:bad")),
            ("invalid connection", lambda args: args.__setitem__(3, "../bad")),
            ("blank query", lambda args: args.__setitem__(5, "  ")),
            ("token in argument", lambda args: args.__setitem__(5, TOKEN)),
            ("missing parent", lambda args: args.__setitem__(-1, str(self.root / "missing" / "out"))),
        ):
            with self.subTest(label=label):
                args = self._args()
                change(args)
                result, _, _ = self._run(args)
                self.assertEqual(result, 2)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.requests, [])
        with patch.dict(os.environ, {"BO_LOGON_TOKEN": "  "}):
            self.assertEqual(self._run()[0], 2)
        self.assertEqual(self.requests, [])

    def test_cleanup_failure_after_publication_is_reported_without_secrets(self):
        original_cleanup = tempfile.TemporaryDirectory.cleanup

        def cleanup_then_fail(instance):
            original_cleanup(instance)
            raise OSError("private error " + TOKEN)

        with patch.object(tempfile.TemporaryDirectory, "cleanup", cleanup_then_fail):
            result, _, stderr = self._run()
        self.assertEqual(result, 2)
        self.assertIn("phase=cleanup", stderr)
        self.assertIn("cleanup=failed", stderr)
        self.assertIn("publication completed", stderr)
        self.assertNotIn("private error", stderr)
        self.assertTrue((self.output / "migration_report.json").is_file())
        self._assert_no_token_in_output()

    def test_invalid_and_linked_plans_are_rejected_before_metadata(self):
        linked = json.loads((FIXTURES / "sap_bw_bex_pilot_plan.example.json").read_text(encoding="utf-8"))
        self.assertIn("bex_linkage", live.validate_plan(linked))
        invalid = copy.deepcopy(self.plan)
        invalid["datasource"]["tables"] = []
        for label, content in (("malformed", "{"), ("invalid", json.dumps(invalid)),
                               ("linked", json.dumps(linked))):
            with self.subTest(label=label):
                self.plan_path.write_text(content, encoding="utf-8")
                self.assertEqual(self._run()[0], 2)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.requests, [])

    def test_token_in_decoded_plan_values_and_keys_is_rejected(self):
        for in_key in (False, True):
            with self.subTest(in_key=in_key):
                plan = copy.deepcopy(self.plan)
                if in_key:
                    plan[TOKEN] = "unexpected"
                else:
                    plan["datasource"]["name"] = TOKEN
                # Escaping the first character ensures the raw byte scan cannot detect it.
                encoded = json.dumps(plan).replace(TOKEN, "\\u0073" + TOKEN[1:])
                self.assertNotIn(TOKEN.encode(), encoded.encode())
                self.plan_path.write_text(encoded, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Token occurs in plan"):
                    live._live_snapshot_plan(self.plan_path, self.output, TOKEN)
                self.assertEqual(self._run()[0], 2)
                self.assertEqual(self.requests, [])
                self.assertFalse(self.output.exists())

    def test_generation_failure_publishes_partial_report_and_sanitizes_environment(self):
        for code, static in ((1, "fail"), (2, "unknown")):
            with self.subTest(code=code):
                self.responses = [b"<bwconnection/>", OUTLINE]
                def fail_generation(command, **kwargs):
                    self.assertNotIn("BO_LOGON_TOKEN", kwargs["env"])
                    pbip = Path(command[command.index("--output-dir") + 1])
                    pbip.mkdir()
                    (pbip / "partial.txt").write_text("partial", encoding="utf-8")
                    return SimpleNamespace(returncode=code)
                with patch.object(live.subprocess, "run", side_effect=fail_generation):
                    result, _, stderr = self._run()
                self.assertEqual(result, 1)
                self.assertIn("incomplete", stderr)
                report = self._report()
                self.assertEqual(report["generation"], {"exit_code": code,
                    "status": "failed_or_incomplete", "partial_artifacts_may_exist": True})
                self.assertEqual(report["static_validation"], static)
                self.assertEqual(set(report["verification"].values()), {"not_verified"})
                self.assertEqual(set(report["runtime_evidence"].values()), {"not_run"})
                self.assertEqual((self.output / "pbip" / "partial.txt").read_text(), "partial")
                self._assert_no_token_in_output()
                self._assert_no_staging()
                shutil.rmtree(self.output)

    def test_success_exit_without_project_and_subprocess_exception_clean_staging(self):
        for outcome in (SimpleNamespace(returncode=0), RuntimeError("failure " + TOKEN)):
            with self.subTest(outcome=type(outcome).__name__):
                self.responses = [b"<bwconnection/>", OUTLINE]
                with patch.object(live.subprocess, "run", side_effect=outcome if isinstance(outcome, Exception) else None,
                                  return_value=outcome):
                    result, _, stderr = self._run()
                self.assertEqual(result, 2)
                self.assertIn("before publication", stderr)
                self.assertFalse(self.output.exists())
                self._assert_no_staging()

    def test_publication_race_preserves_existing_destination(self):
        original_publish = live._live_publish
        def race(stage, destination):
            destination.mkdir()
            (destination / "keep.txt").write_text("existing", encoding="utf-8")
            original_publish(stage, destination)
        with patch.object(live, "_live_publish", side_effect=race):
            result, _, stderr = self._run()
        self.assertEqual(result, 2)
        self.assertIn("before publication", stderr)
        self.assertEqual((self.output / "keep.txt").read_text(encoding="utf-8"), "existing")
        self.assertEqual(list(self.output.iterdir()), [self.output / "keep.txt"])
        self._assert_no_staging()

    def test_check_tree_exception_does_not_publish_or_expose_error(self):
        with patch.object(live.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            with patch.object(live, "_live_check_tree", side_effect=OSError("sensitive " + TOKEN)):
                result, _, stderr = self._run()
        self.assertEqual(result, 2)
        self.assertIn("before publication", stderr)
        self.assertNotIn("sensitive", stderr)
        self.assertFalse(self.output.exists())
        self._assert_no_staging()

    def test_invalid_arguments_exit_without_leaking_or_contacting_server(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            live.main(["--server-url", TOKEN, "--unknown-option"])
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn(TOKEN, stderr.getvalue())
        self.assertIn("invalid arguments", stderr.getvalue())
        self.assertEqual(self.requests, [])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
