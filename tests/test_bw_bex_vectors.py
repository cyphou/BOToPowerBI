"""Regression tests for local BEx CSV result-vector packaging."""

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from migrate_bw_bex_vectors import main as package_main
from migrate_bw_reconcile import main as reconcile_main
from powerbi_import.bw_reconciliation import build_bex_csv_result_vectors, load_bex_csv_mapping

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "docs" / "fixtures"
PILOT_MAPPING = FIXTURES / "sap_bw_bex_pilot_csv_mapping.example.json"
PILOT_SOURCE = FIXTURES / "sap_bw_bex_pilot_source.example.csv"
PILOT_TARGET = FIXTURES / "sap_bw_bex_pilot_target.example.csv"
MEASURE = "synthetic-billed-quantity"
SOURCE_HEADER = b"ZPILOT_DAY,ZPILOT_QTY\n"
TARGET_HEADER = "Quantité facturée,Clé du jour\n".encode("utf-8")


def _read_pilot_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_day_rows(pairs):
    return [{"key": {"day_key": key}, "measures": {MEASURE: measure}} for key, measure in pairs]


class TestBExCSVResultVectors(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.mapping = self.directory / "mapping.json"
        self.source = self.directory / "source.csv"
        self.target = self.directory / "target.csv"
        self.vectors = self.directory / "vectors.json"
        self.report = self.directory / "report.json"
        self.direct_report = self.directory / "direct-report.json"

    def _packaging_args(self, mapping=PILOT_MAPPING, source=PILOT_SOURCE, target=PILOT_TARGET, *, output=None):
        return [
            "--mapping", str(mapping), "--source-csv", str(source),
            "--target-csv", str(target), "--output", str(output or self.vectors),
        ]

    def _reconciliation_linkage_args(self):
        return [
            "--plan", str(FIXTURES / "sap_bw_bex_pilot_plan.example.json"),
            "--inventory", str(FIXTURES / "sap_bw_bex_pilot_inventory.example.json"),
            "--semantics", str(FIXTURES / "sap_bw_bex_pilot_semantics.example.json"),
        ]

    def _linked_reconciliation_args(self):
        return [
            "--bex-result-vectors", str(self.vectors), *self._reconciliation_linkage_args(),
            "--output", str(self.report),
        ]

    def _direct_reconciliation_args(self, mapping=PILOT_MAPPING, source=PILOT_SOURCE, target=PILOT_TARGET):
        return [
            "--bex-csv-mapping", str(mapping), "--source-csv", str(source), "--target-csv", str(target),
            *self._reconciliation_linkage_args(), "--output", str(self.direct_report),
        ]

    def _run_cli(self, script, args, expected_exit):
        completed = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(ROOT / script), *args],
            cwd=self.directory, capture_output=True, encoding="utf-8", check=False, timeout=60,
        )
        self.assertEqual(completed.returncode, expected_exit, completed.stdout + completed.stderr)
        return completed

    def _linked_pilot_report(self, expected_exit):
        self._run_cli("migrate_bw_reconcile.py", self._linked_reconciliation_args(), expected_exit)
        report = _read_pilot_json(self.report)
        linkage = report["plan_linkage"]
        self.assertEqual(report["schema_version"], "1.1")
        self.assertEqual(linkage["status"], "pass")
        self.assertEqual(report["observation_requirement"], {"status": "pass", "minimum_measure_observations": 1})
        self.assertEqual(report["verification_status"]["provenance"], "not_verified")
        self.assertEqual(linkage["native_infocube_identity_verification"], "not_verified")
        self.assertIs(linkage["gate_closed"], False)
        self.assertEqual(report["summary"]["measures_compared"], 2)
        return report

    def _assert_packaging_rejected(self, diagnostic, *, redacted=None, **inputs):
        with tempfile.TemporaryDirectory(dir=self.directory) as directory:
            output = Path(directory) / "vectors.json"
            with redirect_stdout(StringIO()) as stdout, redirect_stderr(StringIO()) as stderr:
                result = package_main(self._packaging_args(output=output, **inputs))
            if redacted is not None:
                self.assertNotIn(redacted, stdout.getvalue() + stderr.getvalue())
            self.assertEqual(result, 2, stderr.getvalue())
            self.assertIn(diagnostic, stderr.getvalue())
            self.assertFalse(output.exists())

    def _assert_reconciliation_rejected(self, args, diagnostic, *, argparse_error=False):
        result = self._run_cli("migrate_bw_reconcile.py", args, 2)
        self.assertIn(diagnostic, result.stderr)
        if argparse_error:
            self.assertIn("usage:", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(self.direct_report, self.directory.iterdir())

    def test_pilot_csv_round_trip(self):
        direct_args = self._direct_reconciliation_args()
        self._run_cli("migrate_bw_reconcile.py", direct_args, 0)
        self.assertEqual(set(self.directory.iterdir()), {self.direct_report})

        self._run_cli("migrate_bw_bex_vectors.py", self._packaging_args(), 0)
        vectors, mapping = _read_pilot_json(self.vectors), _read_pilot_json(PILOT_MAPPING)
        self.assertEqual(vectors["schema_version"], "1.0")
        self.assertEqual(vectors["comparison_id"], mapping["comparison_id"])
        self.assertEqual(vectors["scope"], mapping["scope"])
        self.assertEqual(vectors["key_fields"], ["day_key"])
        self.assertEqual(vectors["rules"], {MEASURE: {"mode": "exact"}})
        for side, pairs in (
            ("source", [("2026-11-23", "7"), ("2026-11-24", "11")]),
            ("target", [("2026-11-24", "11.00"), ("2026-11-23", "7")]),
        ):
            with self.subTest(side=side):
                self.assertEqual(vectors[side]["scope"], mapping["scope"])
                for field in ("run_id", "evidence_ref", "role", "prompt_context_ref", "grain"):
                    self.assertEqual(vectors[side][field], mapping[side][field], f"{side}.{field}")
                self.assertEqual(vectors[side]["rows"], _expected_day_rows(pairs))
        for field in ("run_id", "evidence_ref"):
            self.assertNotEqual(vectors["source"][field], vectors["target"][field])
        report = self._linked_pilot_report(0)
        self.assertEqual(report["comparison_status"], "pass")
        self.assertEqual(report["measure_mismatches"], [])
        self.assertIn(
            ("11", "11.00", "pass"),
            [(check["source_value"], check["target_value"], check["status"]) for check in report["checks"]],
        )
        original = self.direct_report.read_bytes()
        self.assertEqual(original, self.report.read_bytes())
        retry = self._run_cli("migrate_bw_reconcile.py", direct_args, 2)
        self.assertIn("while writing the report", retry.stderr)
        self.assertEqual(self.direct_report.read_bytes(), original)

    def test_changed_target_packages_but_does_not_reconcile(self):
        mapping = _read_pilot_json(PILOT_MAPPING)
        mapping["comparison_id"] += "-counterfactual"
        for field in ("run_id", "evidence_ref"):
            mapping["target"][field] += "-counterfactual"
        self.mapping.write_text(json.dumps(mapping), encoding="utf-8")
        self.target.write_bytes(PILOT_TARGET.read_bytes().replace(b"11.00,2026-11-24", b"12.00,2026-11-24", 1))
        self._run_cli("migrate_bw_bex_vectors.py", self._packaging_args(mapping=self.mapping, target=self.target), 0)
        report = self._linked_pilot_report(1)
        self.assertEqual(report["comparison_status"], "fail")
        self.assertEqual(report["summary"]["measure_mismatches"], 1)
        self.assertEqual(
            [(check["key"], check["measure"], check["source_value"], check["target_value"])
             for check in report["measure_mismatches"]],
            [({"day_key": "2026-11-24"}, MEASURE, "11", "12.00")],
        )
        args = self._direct_reconciliation_args(mapping=self.mapping, target=self.target)
        self._run_cli("migrate_bw_reconcile.py", args, 1)
        self.assertEqual(self.direct_report.read_bytes(), self.report.read_bytes())

    def test_preserves_csv_text_order_and_duplicates(self):
        key = '  Été,"01"  '
        escaped_key = key.replace('"', '""')
        source = f'ZPILOT_DAY,ZPILOT_QTY\r\n"{escaped_key}",-0.00\r\n"001",11.00\r\n"{escaped_key}",-0.00'
        self.source.write_bytes(source.encode("utf-8-sig"))
        self.target.write_bytes(TARGET_HEADER + f'11,"001"\n-0.00,"{escaped_key}"\n12.00,"001"\n'.encode("utf-8"))

        vectors = build_bex_csv_result_vectors(load_bex_csv_mapping(PILOT_MAPPING), self.source, self.target)
        self.assertEqual(vectors["source"]["rows"], _expected_day_rows([(key, "-0.00"), ("001", "11.00"), (key, "-0.00")]))
        self.assertEqual(vectors["target"]["rows"], _expected_day_rows([("001", "11"), (key, "-0.00"), ("001", "12.00")]))

    def test_header_only_csv_has_no_observations(self):
        self.source.write_bytes(SOURCE_HEADER)
        self.target.write_bytes(TARGET_HEADER)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as stderr:
            self.assertEqual(package_main(self._packaging_args(source=self.source, target=self.target)), 0, stderr.getvalue())
            vectors = _read_pilot_json(self.vectors)
            self.assertEqual([vectors[side]["rows"] for side in ("source", "target")], [[], []])
            self.assertEqual(reconcile_main(self._linked_reconciliation_args()), 1, stderr.getvalue())
        report = _read_pilot_json(self.report)
        self.assertEqual(report["plan_linkage"]["status"], "pass")
        self.assertEqual(report["observation_requirement"]["status"], "fail")
        self.assertEqual(report["summary"]["measures_compared"], 0)
        args = self._direct_reconciliation_args(source=self.source, target=self.target)
        self._run_cli("migrate_bw_reconcile.py", args, 1)
        self.assertEqual(self.direct_report.read_bytes(), self.report.read_bytes())
        self.assertEqual(report["schema_version"], "1.1")
        self.assertEqual(report["comparison_status"], "pass")

    def test_direct_csv_rejects_invalid_flags(self):
        args = self._direct_reconciliation_args()
        pairs = tuple(zip(args[::2], args[1::2], strict=True))
        for missing in (
            ("--source-csv",), ("--target-csv",), ("--plan",), ("--inventory",), ("--semantics",),
            ("--plan", "--inventory", "--semantics"),
        ):
            with self.subTest(missing=missing):
                self._assert_reconciliation_rejected(
                    [part for pair in pairs if pair[0] not in missing for part in pair],
                    "--bex-csv-mapping requires", argparse_error=True,
                )

        vector_selector = ["--bex-result-vectors", str(FIXTURES / "sap_bw_bex_pilot_result_vectors.example.json")]
        for selector in (
            ["--comparison", str(FIXTURES / "sap_bw_reconciliation.example.json")], vector_selector,
        ):
            with self.subTest(selector=selector[0]):
                self._assert_reconciliation_rejected(
                    [
                        *selector, "--source-csv", str(PILOT_SOURCE), "--target-csv", str(PILOT_TARGET),
                        "--output", str(self.direct_report),
                    ],
                    "require --bex-csv-mapping", argparse_error=True,
                )
        self._assert_reconciliation_rejected(
            [*args, *vector_selector], "not allowed with argument", argparse_error=True,
        )

    def test_direct_csv_rejects_empty_paths(self):
        for flag in (
            "--bex-csv-mapping", "--source-csv", "--target-csv", "--plan",
            "--inventory", "--semantics", "--output",
        ):
            with self.subTest(flag=flag), patch("migrate_bw_reconcile.load_bex_csv_mapping") as load_mapping:
                args = self._direct_reconciliation_args()
                args[args.index(flag) + 1] = ""
                with (
                    redirect_stdout(StringIO()) as stdout,
                    redirect_stderr(StringIO()) as stderr,
                    self.assertRaises(SystemExit) as error,
                ):
                    reconcile_main(args)
                self.assertEqual(error.exception.code, 2)
                self.assertIn("non-empty", stderr.getvalue())
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(list(self.directory.iterdir()), [])
                load_mapping.assert_not_called()

    def test_invalid_csv_refused(self):
        for case, content, diagnostic in (
            ("mismatched header", b"WRONG_DAY,ZPILOT_QTY\n001,11\n", "declared columns"),
            ("duplicate header", b"ZPILOT_DAY,ZPILOT_DAY\n001,11\n", "declared columns"),
            ("extra header", b"ZPILOT_DAY,ZPILOT_QTY,EXTRA\n001,11,x\n", "declared columns"),
            ("semicolon delimiter", b"ZPILOT_DAY;ZPILOT_QTY\n001;11\n", "declared columns"),
            ("malformed quoting", SOURCE_HEADER + b'"001,11\n', "well-formed UTF-8 CSV"),
            ("ragged record", SOURCE_HEADER + b"001\n", "two fields"),
            ("blank key", SOURCE_HEADER + b'" ",11\n', "non-empty string"),
            ("empty measure", SOURCE_HEADER + b"001,\n", "decimal"),
            ("null measure", SOURCE_HEADER + b"001,null\n", "decimal"),
            ("locale number", SOURCE_HEADER + b'001,"11,00"\n', "decimal"),
            ("exponent notation", SOURCE_HEADER + b"001,1.1e1\n", "decimal"),
            ("bad UTF-8", SOURCE_HEADER + b"00\xff1,11\n", "UTF-8 CSV"),
        ):
            with self.subTest(case=case):
                self.source.write_bytes(content)
                self._assert_packaging_rejected(diagnostic, source=self.source)

    def test_unquoted_target_quote_refused(self):
        self.target.write_bytes(TARGET_HEADER + b'11,AB"CD\n')
        self._assert_packaging_rejected("well-formed UTF-8 CSV", target=self.target)
        self._assert_reconciliation_rejected(
            self._direct_reconciliation_args(target=self.target), "well-formed UTF-8 CSV",
        )

    def test_direct_csv_rejects_target_project_mismatch(self):
        mapping = _read_pilot_json(PILOT_MAPPING)
        mapping["target"]["object_id"] = "Different Synthetic BEx Project"
        self.mapping.write_text(json.dumps(mapping), encoding="utf-8")
        self._assert_reconciliation_rejected(
            self._direct_reconciliation_args(mapping=self.mapping),
            "$.target.object_id: must match the plan's project name",
        )

    def test_invalid_mapping_refused(self):
        mapping = _read_pilot_json(PILOT_MAPPING)
        valid = json.dumps(mapping)
        for case, content, diagnostic in (
            ("duplicate JSON key", '{"schema_version":"1.0",' + valid[1:], "mapping JSON"),
            ("malformed JSON", valid[:-1], "mapping JSON"),
            ("unexpected field", json.dumps({**mapping, "unexpected": True}), "supported fields"),
            (
                "conflicting source object",
                json.dumps({**mapping, "source": {**mapping["source"], "object_id": "different-synthetic-query"}}),
                "$.source.object_id: must match $.scope.query_id",
            ),
        ):
            with self.subTest(case=case):
                self.mapping.write_text(content, encoding="utf-8")
                self._assert_packaging_rejected(diagnostic, mapping=self.mapping)
        for field in ("role", "prompt_context_ref", "grain", "run_id", "evidence_ref"):
            with self.subTest(field=field):
                reused = field in ("run_id", "evidence_ref")
                value = mapping["source"][field] if reused else "different synthetic context"
                target = {**mapping["target"], field: value}
                self.mapping.write_text(json.dumps({**mapping, "target": target}), encoding="utf-8")
                self._assert_packaging_rejected("must differ" if reused else "must match", mapping=self.mapping)

    def test_reused_capture_file_refused(self):
        mapping = _read_pilot_json(PILOT_MAPPING)
        for column in ("key_column", "measure_column"):
            mapping["target"][column] = mapping["source"][column]
        self.mapping.write_text(json.dumps(mapping), encoding="utf-8")
        self.source.write_bytes(PILOT_SOURCE.read_bytes())
        inputs = {"mapping": self.mapping, "source": self.source}
        self._assert_packaging_rejected("same file", target=self.source, **inputs)
        try:
            self.target.hardlink_to(self.source)
        except (OSError, NotImplementedError):
            return  # The identical-path case is covered even without hard-link support.
        self._assert_packaging_rejected("same file", target=self.target, **inputs)

    def test_credential_like_inputs_are_redacted(self):
        mapping = _read_pilot_json(PILOT_MAPPING)
        for case, ref, sentinel in (
            ("assignment", "password=MAPFAKE", "MAPFAKE"),
            ("URL userinfo", "https://fake:CREDFAKE@example.invalid/evidence", "CREDFAKE"),
            ("signed URL", "https://example.invalid/evidence?sig=SIGFAKE", "SIGFAKE"),
        ):
            with self.subTest(input="mapping", case=case):
                mapping["target"]["evidence_ref"] = ref
                self.mapping.write_text(json.dumps(mapping), encoding="utf-8")
                self._assert_packaging_rejected("credential-like", redacted=sentinel, mapping=self.mapping)
        self.source.write_bytes(SOURCE_HEADER + b"token=KEYFAKE,11\n")
        self._assert_packaging_rejected("credential-like", redacted="KEYFAKE", source=self.source)

    def test_existing_vector_file_is_not_overwritten(self):
        original = b"existing vector file\r\n"
        self.vectors.write_bytes(original)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as stderr:
            result = package_main(self._packaging_args())
        self.assertEqual(result, 2, stderr.getvalue())
        self.assertIn("new vector file", stderr.getvalue())
        self.assertEqual(self.vectors.read_bytes(), original)

    def test_direct_csv_refuses_dangling_output_symlink(self):
        victim = self.directory / "missing-report.json"
        try:
            self.direct_report.symlink_to(victim.name)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Creating a file symlink is unavailable: {error}")
        self.assertTrue(self.direct_report.is_symlink())
        self.assertFalse(self.direct_report.exists())

        result = self._run_cli("migrate_bw_reconcile.py", self._direct_reconciliation_args(), 2)
        self.assertIn("while writing the report", result.stderr)
        self.assertTrue(self.direct_report.is_symlink())
        self.assertFalse(victim.exists())
