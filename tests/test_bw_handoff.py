"""Tests for the offline BW snapshot-to-delta handoff evaluator."""

import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from migrate_bw_handoff import main
from powerbi_import.bw_handoff import BWHandoffError, evaluate_handoff, load_handoff

ROOT = Path(__file__).resolve().parents[1]


class TestBWHandoff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (ROOT / "docs" / "fixtures" / "sap_bw_handoff.example.json")
            .read_text(encoding="utf-8")
        )

    def test_synthetic_snapshot_and_feed_reconcile_with_limits_explicit(self):
        original = copy.deepcopy(self.manifest)
        report = evaluate_handoff(self.manifest)

        self.assertEqual(report["handoff_status"], "pass")
        self.assertEqual(report["evidence_boundary"], "declared_local_feed_events_only")
        self.assertEqual(report["checks"], {
            "stream_contiguous": "pass",
            "schema_stable": "pass",
            "target_state_matches": "pass",
        })
        self.assertEqual(report["summary"], {
            "snapshot_records": 2,
            "events_observed": 6,
            "unique_events": 5,
            "replay_duplicates_ignored": 1,
            "overlap_events_ignored": 1,
            "applied_upserts": 3,
            "applied_deletes": 1,
            "out_of_order_events": 1,
            "late_events": 1,
            "missing_positions": [],
            "missing_position_ranges": [],
            "missing_position_count": 0,
            "missing_positions_truncated": False,
            "unexpected_positions": [],
            "schema_drift_events": [],
            "target_missing_records": 0,
            "target_extra_records": 0,
            "target_differing_records": 0,
        })
        self.assertEqual(report["runtime_evidence"], {
            "source_extraction": "not_run",
            "fabric_execution": "not_run",
            "business_approval": "not_run",
            "bw_unavailable_operation": "not_run",
        })
        self.assertEqual(self.manifest, original)
        self.assertEqual(evaluate_handoff(self.manifest), report)

    def test_gap_is_reported_as_failure(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["events"] = [
            event for event in manifest["events"] if event["position"] != 13
        ]
        report = evaluate_handoff(manifest)
        self.assertEqual(report["handoff_status"], "fail")
        self.assertEqual(report["checks"]["stream_contiguous"], "fail")
        self.assertEqual(report["summary"]["missing_positions"], [13])
        self.assertEqual(report["summary"]["missing_position_ranges"], [[13, 13]])

    def test_large_gap_is_reported_compactly(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["target"]["watermark"] = 10 ** 12
        report = evaluate_handoff(manifest)
        self.assertEqual(report["handoff_status"], "fail")
        self.assertEqual(report["summary"]["missing_positions"], [])
        self.assertEqual(
            report["summary"]["missing_position_ranges"],
            [[15, 10 ** 12]],
        )
        self.assertTrue(report["summary"]["missing_positions_truncated"])

    def test_schema_drift_blocks_event_and_handoff(self):
        manifest = copy.deepcopy(self.manifest)
        event = next(event for event in manifest["events"] if event["position"] == 13)
        event["schema_version"] = "sales-v2"
        report = evaluate_handoff(manifest)
        self.assertEqual(report["handoff_status"], "fail")
        self.assertEqual(report["checks"]["schema_stable"], "fail")
        self.assertEqual(report["summary"]["schema_drift_events"], ["event-13"])

    def test_target_difference_fails_even_with_a_contiguous_stream(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["target"]["records"][0]["values"]["amount"] = 999
        report = evaluate_handoff(manifest)
        self.assertEqual(report["handoff_status"], "fail")
        self.assertEqual(report["checks"]["target_state_matches"], "fail")
        self.assertEqual(report["summary"]["target_differing_records"], 1)

    def test_target_comparison_distinguishes_nested_booleans_from_numbers(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["events"][-1]["values"]["amount"] = {"flag": True}
        manifest["target"]["records"][0]["values"]["amount"] = {"flag": 1}
        report = evaluate_handoff(manifest)
        self.assertEqual(report["handoff_status"], "fail")
        self.assertEqual(report["checks"]["target_state_matches"], "fail")
        self.assertEqual(report["summary"]["target_differing_records"], 1)

    def test_rejects_conflicting_replay_position_and_contract(self):
        mutations = []
        conflict = copy.deepcopy(self.manifest)
        conflicting_event = copy.deepcopy(conflict["events"][0])
        conflicting_event["values"]["amount"] = 999
        conflict["events"].append(conflicting_event)
        mutations.append(conflict)

        conflict = copy.deepcopy(self.manifest)
        conflicting_event = copy.deepcopy(conflict["events"][0])
        conflicting_event["event_id"] = "different-event"
        conflict["events"].append(conflicting_event)
        mutations.append(conflict)

        conflict = copy.deepcopy(self.manifest)
        conflict["source_contract"]["position_semantics"] = "opaque"
        mutations.append(conflict)

        for manifest in mutations:
            with self.subTest(manifest=manifest):
                with self.assertRaises(BWHandoffError):
                    evaluate_handoff(manifest)

    def test_rejects_replay_with_boolean_number_type_conflict(self):
        manifest = copy.deepcopy(self.manifest)
        event = next(event for event in manifest["events"] if event["position"] == 13)
        event["values"]["amount"] = {"flag": 1}
        target_record = next(
            record for record in manifest["target"]["records"]
            if record["key"] == "sale-3"
        )
        target_record["values"]["amount"] = {"flag": 1}
        conflicting_replay = copy.deepcopy(event)
        conflicting_replay["values"]["amount"] = {"flag": True}
        manifest["events"].append(conflicting_replay)

        with self.assertRaisesRegex(BWHandoffError, "conflicting replay"):
            evaluate_handoff(manifest)

    def test_rejects_invalid_scope_credentials_and_duplicate_snapshot_keys(self):
        mutations = []
        invalid = copy.deepcopy(self.manifest)
        invalid["target"]["watermark"] = 9
        mutations.append(invalid)
        invalid = copy.deepcopy(self.manifest)
        invalid["source_contract"]["evidence_ref"] = "token=do-not-store"
        mutations.append(invalid)
        invalid = copy.deepcopy(self.manifest)
        invalid["snapshot"]["records"].append(copy.deepcopy(invalid["snapshot"]["records"][0]))
        mutations.append(invalid)
        invalid = copy.deepcopy(self.manifest)
        invalid["events"][0]["event_time_utc"] = "2026-10-31T12:05:00+01:00"
        mutations.append(invalid)

        for manifest in mutations:
            with self.subTest(manifest=manifest):
                with self.assertRaises(BWHandoffError):
                    evaluate_handoff(manifest)

    def test_loader_rejects_duplicate_keys_and_non_json_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            for content in (
                '{"schema_version":"1.0","schema_version":"1.0"}',
                '{"value":NaN}',
                '{"value":Infinity}',
            ):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content):
                    with self.assertRaises(BWHandoffError):
                        load_handoff(path)

    def test_cli_writes_new_report_and_returns_failure_on_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            report_path = Path(directory) / "report.json"
            failed_path = Path(directory) / "failed.json"
            manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
            self.assertEqual(main(["--handoff", str(manifest_path), "--output", str(report_path)]), 0)
            self.assertEqual(
                json.loads(report_path.read_text(encoding="utf-8"))["handoff_status"],
                "pass",
            )
            self.assertEqual(main(["--handoff", str(manifest_path), "--output", str(report_path)]), 2)

            failed = copy.deepcopy(self.manifest)
            failed["events"] = [
                event for event in failed["events"] if event["position"] != 13
            ]
            failed_path_manifest = Path(directory) / "failed-manifest.json"
            failed_path_manifest.write_text(json.dumps(failed), encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(["--handoff", str(failed_path_manifest), "--output", str(failed_path)]),
                    1,
                )
            self.assertEqual(
                json.loads(failed_path.read_text(encoding="utf-8"))["handoff_status"],
                "fail",
            )

    def test_cli_rejects_non_string_event_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, operation in enumerate(([], {})):
                manifest = copy.deepcopy(self.manifest)
                manifest["events"][0]["operation"] = operation
                manifest_path = root / f"manifest-{index}.json"
                report_path = root / f"report-{index}.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                stdout, stderr = StringIO(), StringIO()

                with self.subTest(operation=operation):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = main([
                            "--handoff", str(manifest_path),
                            "--output", str(report_path),
                        ])

                    self.assertEqual(result, 2)
                    self.assertFalse(report_path.exists())
                    self.assertIn("BW handoff evaluation failed:", stderr.getvalue())

    def test_cli_removes_partial_output_after_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            report_path = root / "report.json"
            manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
            original_open = Path.open
            test_case = self

            class FailingWriter:
                def __init__(self, handle):
                    self.handle = handle

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc_value, traceback):
                    self.handle.close()
                    return False

                def write(self, content):
                    self.handle.write(content[:10])
                    self.handle.flush()
                    test_case.assertTrue(report_path.exists())
                    test_case.assertGreater(report_path.stat().st_size, 0)
                    raise OSError("simulated write failure")

            def open_with_write_failure(path, *args, **kwargs):
                if path == report_path and args and args[0] == "x":
                    return FailingWriter(original_open(path, *args, **kwargs))
                return original_open(path, *args, **kwargs)

            stdout, stderr = StringIO(), StringIO()
            with patch.object(Path, "open", open_with_write_failure):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = main([
                        "--handoff", str(manifest_path),
                        "--output", str(report_path),
                    ])

            self.assertEqual(result, 2)
            self.assertFalse(report_path.exists())

    def test_cli_removes_partial_output_after_keyboard_interrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            report_path = root / "report.json"
            manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
            original_open = Path.open

            class InterruptingWriter:
                def __init__(self, handle):
                    self.handle = handle

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc_value, traceback):
                    self.handle.close()
                    return False

                def write(self, content):
                    self.handle.write(content[:10])
                    self.handle.flush()
                    raise KeyboardInterrupt

            def open_with_interrupt(path, *args, **kwargs):
                if path == report_path and args and args[0] == "x":
                    return InterruptingWriter(original_open(path, *args, **kwargs))
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", open_with_interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    main([
                        "--handoff", str(manifest_path),
                        "--output", str(report_path),
                    ])

            self.assertFalse(report_path.exists())


if __name__ == "__main__":
    unittest.main()
