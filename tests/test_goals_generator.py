import json
import os
import tempfile
import unittest
from unittest.mock import patch

from powerbi_import.goals_generator import (
    _build_goal,
    generate_goals_json,
    write_goals_artifact,
)


class GoalsGeneratorTests(unittest.TestCase):
    def test_empty_metrics_returns_none_and_write_returns_none(self):
        self.assertIsNone(generate_goals_json([]))
        self.assertIsNone(write_goals_artifact(None, "unused"))

    def test_build_full_goal_and_unknown_cadence(self):
        metric = {
            "name": "Net Sales",
            "description": "Sales target",
            "time_grain": "Biweekly",
            "target_value": 125000,
            "target_label": "$125K",
            "measure_field": "Measures[Net Sales]",
            "aggregation": "SUM",
            "time_dimension": "Calendar[Date]",
            "filters": [{"field": "Region", "operator": "In", "values": ["EMEA", "APAC"]}],
            "number_format": "Currency",
        }
        goal = _build_goal(metric, 2, "scorecard-1")
        self.assertEqual(goal["ordinal"], 2)
        self.assertEqual(goal["scorecardId"], "scorecard-1")
        self.assertEqual(goal["refreshSchedule"], "P1M")
        self.assertEqual(goal["target"]["value"], 125000)
        self.assertEqual(goal["target"]["label"], "$125K")
        self.assertEqual(goal["connectedMeasure"]["aggregation"], "SUM")
        self.assertEqual(goal["timeDimension"], "Calendar[Date]")
        self.assertEqual(goal["filters"][0]["values"], ["EMEA", "APAC"])
        self.assertEqual(goal["numberFormat"], "Currency")

    def test_build_goal_missing_name_and_defaults(self):
        self.assertIsNone(_build_goal({"name": ""}, 0, "score"))
        goal = _build_goal({"name": "Count"}, 0, "score")
        self.assertEqual(goal["cadence"], "Monthly")
        self.assertEqual(goal["refreshSchedule"], "P1M")
        self.assertNotIn("target", goal)
        self.assertNotIn("connectedMeasure", goal)
        self.assertNotIn("timeDimension", goal)
        self.assertNotIn("filters", goal)
        self.assertNotIn("numberFormat", goal)

    def test_generate_all_cadences_and_workspace(self):
        cadences = {"Daily": "P1D", "Weekly": "P7D", "Monthly": "P1M", "Quarterly": "P3M", "Yearly": "P1Y"}
        metrics = [{"name": name, "time_grain": name} for name in cadences]
        with patch("powerbi_import.goals_generator.uuid.uuid4", side_effect=["scorecard"] + [f"goal-{i}" for i in range(5)]):
            scorecard = generate_goals_json(metrics, "Véntes", "workspace-1")
        self.assertEqual(scorecard["id"], "scorecard")
        self.assertEqual(scorecard["name"], "Véntes Scorecard")
        self.assertEqual(scorecard["workspaceId"], "workspace-1")
        self.assertEqual(scorecard["description"], "Migrated from BO report — 5 goals")
        self.assertTrue(scorecard["createdTime"].endswith("Z"))
        self.assertEqual({g["cadence"]: g["refreshSchedule"] for g in scorecard["goals"]}, cadences)

    def test_generate_skips_empty_named_metrics_preserving_ordinals(self):
        scorecard = generate_goals_json([{"name": ""}, {"name": "Margin"}], "Report")
        self.assertEqual(len(scorecard["goals"]), 1)
        self.assertEqual(scorecard["goals"][0]["ordinal"], 1)
        self.assertNotIn("workspaceId", scorecard)

    def test_write_goals_artifact_json(self):
        scorecard = generate_goals_json([{"name": "Revenue", "target_value": 100}], "Sales")
        with tempfile.TemporaryDirectory() as directory:
            path = write_goals_artifact(scorecard, directory)
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(os.path.basename(os.path.dirname(path)), "goals")
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["name"], "Sales Scorecard")
            self.assertEqual(payload["goals"][0]["target"]["value"], 100)


if __name__ == "__main__":
    unittest.main()
