import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from powerbi_import.merge_config import (
    apply_merge_config,
    get_measure_action,
    load_merge_config,
    save_merge_config,
)


class MergeConfigTests(unittest.TestCase):
    def _assessment(self):
        fingerprint = object()
        candidate = SimpleNamespace(
            table_name="Sales",
            sources=[("A", {"name": "Sales"}, {}), ("B", {"name": "Sales"}, {})],
            column_overlap=0.756,
            conflicts=["Region dtype differs"],
        )
        measure = SimpleNamespace(name="Revenue", variants={"A": "SUM(A)", "B": "SUM(B)"})
        return SimpleNamespace(
            merge_score=72,
            recommendation="partial",
            merge_candidates=[candidate],
            unique_tables={"A": ["Customers", "Audit"], "B": ["Products"]},
            measure_conflicts=[measure],
            parameter_conflicts=[{"name": "Region", "variants": {"A": "EMEA", "B": "APAC"}}],
        )

    def test_save_load_and_unicode_round_trip(self):
        assessment = self._assessment()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "nested", "Ventés merge.json")
            returned = save_merge_config(assessment, ["A", "B"], path)
            self.assertEqual(returned, path)
            self.assertTrue(os.path.isfile(path))

            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            self.assertEqual(raw["version"], "1.0")
            self.assertEqual(raw["workbooks"], ["A", "B"])
            self.assertEqual(raw["merge_score"], 72)
            self.assertEqual(raw["options"]["calendar_merge_strategy"], "widest_range")
            self.assertEqual(raw["table_decisions"][0]["table_name"], "Sales")
            self.assertEqual(raw["table_decisions"][0]["column_overlap"], 0.756)
            self.assertEqual(raw["table_decisions"][0]["workbooks"], ["A", "B"])
            self.assertEqual(raw["table_decisions"][1]["action"], "include")
            self.assertEqual(raw["measure_decisions"][0]["action"], "namespace")
            self.assertEqual(raw["parameter_decisions"][0]["parameter_name"], "Region")

            loaded = load_merge_config(path)
            self.assertEqual(loaded, raw)

    def test_load_missing_and_bad_version(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "missing.json")
            with self.assertRaises(FileNotFoundError):
                load_merge_config(missing)

            bad = os.path.join(directory, "bad.json")
            with open(bad, "w", encoding="utf-8") as handle:
                json.dump({"version": "9.9"}, handle)
            with self.assertRaisesRegex(ValueError, "Unsupported merge config version"):
                load_merge_config(bad)

    def test_apply_skip_exclude_force_and_rls_config(self):
        assessment = self._assessment()
        config = {
            "table_decisions": [
                {"table_name": "Sales", "action": "skip"},
                {"table_name": "Audit", "action": "exclude"},
            ],
            "measure_decisions": [{"measure_name": "Revenue", "action": "keep_last"}],
            "rls_rules": [{"role_name": "Region EMEA", "action": "merge"}],
            "options": {"force_merge": True},
        }
        result = apply_merge_config(assessment, config)
        self.assertIs(result, assessment)
        self.assertEqual(result.merge_candidates, [])
        self.assertIn("Sales", result.unique_tables["A"])
        self.assertIn("Sales", result.unique_tables["B"])
        self.assertNotIn("Audit", result.unique_tables["A"])
        self.assertEqual(result.recommendation, "merge")
        self.assertEqual(result.unique_table_count, 4)
        self.assertIs(result._merge_config, config)
        self.assertEqual(set(result._rls_rules), {"Region EMEA"})

    def test_apply_preserves_defaults_and_measure_lookup(self):
        assessment = self._assessment()
        config = {"table_decisions": [], "measure_decisions": [], "rls_rules": []}
        apply_merge_config(assessment, config)
        self.assertEqual(len(assessment.merge_candidates), 1)
        self.assertEqual(assessment.unique_table_count, 4)
        self.assertEqual(get_measure_action(config, "Revenue"), "namespace")

        config["measure_decisions"] = [
            {"measure_name": "Revenue", "action": "keep_first"},
            {"measure_name": "Margin", "action": "custom"},
        ]
        self.assertEqual(get_measure_action(config, "Revenue"), "keep_first")
        self.assertEqual(get_measure_action(config, "Margin"), "custom")
        self.assertEqual(get_measure_action(config, "Unknown"), "namespace")
        self.assertEqual(get_measure_action({"measure_decisions": [{"measure_name": "X"}]}, "X"), "namespace")

    def test_save_rls_consolidations_with_merged_object(self):
        rls = SimpleNamespace(role_name="All Regions", action="merge",
                              source_workbooks=["A", "B"], tables_affected=["Sales"],
                              merged_expression="[Region] <> \"Blocked\"")
        assessment = self._assessment()
        assessment.rls_consolidations = [rls]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "merge.json")
            save_merge_config(assessment, ["A", "B"], path, merged={"tables": []})
            config = load_merge_config(path)
            self.assertEqual(config["rls_rules"][0]["role_name"], "All Regions")
            self.assertEqual(config["rls_rules"][0]["strategy"], "or")


if __name__ == "__main__":
    unittest.main()
