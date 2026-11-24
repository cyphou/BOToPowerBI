import json
import os
import tempfile
import unittest
from unittest.mock import patch

from powerbi_import.sla_tracker import (
    DEFAULT_SLA_CONFIG,
    SLAReport,
    SLAResult,
    SLATracker,
)


class SLATrackerTests(unittest.TestCase):
    def test_default_result_and_report_properties(self):
        result = SLAResult(workbook="Sales.wid")
        self.assertTrue(result.compliant)
        self.assertEqual(result.to_dict()["migration_seconds"], 0.0)

        empty = SLAReport()
        self.assertEqual(empty.compliance_rate, 100.0)
        mixed = SLAReport(total_workbooks=4, compliant_count=3, breach_count=1)
        self.assertEqual(mixed.compliance_rate, 75.0)

    def test_tracker_merges_config_and_compliant_record(self):
        tracker = SLATracker({"max_migration_seconds": 0,
                              "min_fidelity_score": 0,
                              "require_validation_pass": False,
                              "alert_on_breach": False})
        self.assertEqual(tracker.config["max_migration_seconds"], 0)
        with patch("powerbi_import.sla_tracker.time.monotonic", side_effect=[10.0, 12.5]):
            tracker.start("NoLimit.wid")
            result = tracker.record_result("NoLimit.wid", fidelity=10.0, validation_passed=False)
        self.assertTrue(result.compliant)
        self.assertEqual(result.migration_seconds, 2.5)
        self.assertEqual(result.breaches, [])

    def test_all_breach_branches_alert_and_report(self):
        tracker = SLATracker({"max_migration_seconds": 5,
                              "min_fidelity_score": 80,
                              "require_validation_pass": True,
                              "alert_on_breach": True})
        with patch("powerbi_import.sla_tracker.time.monotonic", side_effect=[100.0, 106.5]):
            tracker.start("Breaching.wid")
            with self.assertLogs("powerbi_import.sla_tracker", level="WARNING") as captured:
                result = tracker.record_result("Breaching.wid", fidelity=79.0, validation_passed=False)

        self.assertFalse(result.compliant)
        self.assertFalse(result.time_compliant)
        self.assertFalse(result.fidelity_compliant)
        self.assertFalse(result.validation_compliant)
        self.assertEqual(len(result.breaches), 3)
        self.assertIn("Migration took", result.breaches[0])
        self.assertIn("Fidelity", result.breaches[1])
        self.assertIn("validation failed", result.breaches[2])
        self.assertEqual(len(captured.records), 3)

        report = tracker.get_report()
        self.assertTrue(report.timestamp)
        self.assertEqual(report.total_workbooks, 1)
        self.assertEqual(report.compliant_count, 0)
        self.assertEqual(report.breach_count, 1)
        self.assertEqual(report.compliance_rate, 0.0)
        serialized = report.to_dict()
        self.assertEqual(serialized["results"][0]["workbook"], "Breaching.wid")

    def test_unstarted_record_uses_zero_elapsed_and_reset(self):
        tracker = SLATracker()
        result = tracker.record_result("NotTracked.wid", fidelity=100.0, validation_passed=True)
        self.assertTrue(result.compliant)
        self.assertEqual(result.migration_seconds, 0.0)
        tracker.start("Later.wid")
        tracker.record_result("Later.wid", fidelity=100.0, validation_passed=True)
        tracker.reset()
        self.assertEqual(tracker.get_report().total_workbooks, 0)
        self.assertEqual(tracker._timers, {})

    def test_save_report_creates_parent_and_round_trips_json(self):
        tracker = SLATracker()
        tracker.record_result("Sales.wid", fidelity=95.5, validation_passed=True)
        report = tracker.get_report()
        with tempfile.TemporaryDirectory() as directory:
            nested = os.path.join(directory, "evidence", "sla.json")
            report.save(nested)
            self.assertTrue(os.path.isfile(nested))
            with open(nested, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["total_workbooks"], 1)
            self.assertEqual(payload["results"][0]["fidelity_score"], 95.5)
            self.assertEqual(payload["sla_config"], tracker.config)

    def test_default_config_is_not_mutated_by_overrides(self):
        tracker = SLATracker({"max_migration_seconds": 1})
        self.assertEqual(tracker.config["max_migration_seconds"], 1)
        self.assertEqual(DEFAULT_SLA_CONFIG["max_migration_seconds"], 60)


if __name__ == "__main__":
    unittest.main()
