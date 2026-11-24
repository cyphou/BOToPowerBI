"""Behavioral tests for BO migration data-loading strategy recommendations."""

import unittest

from powerbi_import.strategy_advisor import recommend_strategy


def _table(name="Orders", column_count=2):
    return {
        "name": name,
        "columns": [{"name": f"Column {index}"} for index in range(column_count)],
    }


class TestStrategyAdvisor(unittest.TestCase):
    def test_small_power_query_friendly_workbook_recommends_import(self):
        extracted = {
            "datasources": [{
                "connection": {"type": "SQL Server"},
                "tables": [_table()],
            }],
            "calculations": [{"name": "Double Amount", "formula": "[Amount] * 2"}],
            "custom_sql": [],
        }

        recommendation = recommend_strategy(extracted)

        self.assertEqual(recommendation.strategy, "import")
        self.assertEqual(recommendation.connection_mode, "Import")
        self.assertGreater(recommendation.import_score, recommendation.directquery_score)
        self.assertIn("Recommended strategy: Import Mode (Power Query M)",
                      recommendation.summary)
        self.assertIn("connectors_simple", {signal.name for signal in recommendation.signals})

    def test_complex_connector_and_workbook_signals_recommend_directquery(self):
        extracted = {
            "datasources": [{
                "connection": {"type": "Snowflake"},
                "tables": [_table(f"Table {index}", column_count=10) for index in range(6)],
            }],
            "calculations": [
                {"name": "Regional Sales", "formula": "{FIXED [Region] : SUM([Sales])}"},
                {"name": "Code Match", "formula": "REGEXP_MATCH([Code], 'A.*')"},
            ],
            "custom_sql": [{"name": "Sales query", "sql": "SELECT 1"}],
        }

        recommendation = recommend_strategy(extracted)

        self.assertEqual(recommendation.strategy, "directquery")
        self.assertEqual(recommendation.connection_mode, "DirectQuery")
        self.assertGreater(recommendation.directquery_score, recommendation.import_score)
        signals = {signal.name: signal for signal in recommendation.signals}
        self.assertEqual(signals["connectors_complex"].favours, "directquery")
        self.assertEqual(signals["many_tables"].favours, "directquery")
        self.assertEqual(signals["many_columns"].favours, "directquery")
        self.assertEqual(signals["custom_sql"].weight, 2)
        self.assertEqual(signals["complex_calcs"].favours, "directquery")

    def test_close_signal_scores_recommend_composite_and_include_prep_flow(self):
        extracted = {
            "datasources": [{
                "connection": {"type": "SQL Server"},
                "tables": [_table(f"Table {index}", 9) for index in range(6)],
            }],
            "calculations": [],
            "custom_sql": [{"name": "BO query", "sql": "SELECT 1"}],
        }

        recommendation = recommend_strategy(extracted, prep_flow=True)

        self.assertEqual(recommendation.strategy, "composite")
        self.assertEqual(recommendation.connection_mode, "Composite (Import + DirectQuery)")
        self.assertLessEqual(abs(recommendation.import_score - recommendation.directquery_score), 2)
        prep_signal = next(signal for signal in recommendation.signals
                           if signal.name == "prep_flow")
        self.assertEqual(prep_signal.favours, "directquery")
        self.assertEqual(prep_signal.weight, 2)
        self.assertIn("Composite Model (Import + DirectQuery)", recommendation.summary)


if __name__ == "__main__":
    unittest.main()