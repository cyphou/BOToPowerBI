import json
import os
import tempfile
import unittest

from powerbi_import.alerts_generator import (
    extract_alerts,
    generate_alert_rules,
    save_alert_rules,
)


class AlertsGeneratorTests(unittest.TestCase):
    def test_extract_parameter_alerts_operator_inference_and_measure_lookup(self):
        extracted = {
            "parameters": [
                {"name": "Maximum Revenue Alert", "value": 1000},
                {"caption": "Minimum Stock Alert", "current_value": "25.5"},
                {"name": "Warning Load", "value": "not-a-number"},
                {"name": "Reporting Country", "value": 42},
                {"name": "Critical", "value": None},
            ],
            "calculations": [
                {"name": "RevenueVariance", "caption": "Revenue Variance", "formula": "Maximum Revenue Alert"},
            ],
        }

        alerts = extract_alerts(extracted)

        self.assertEqual(len(alerts), 2)
        maximum = next(item for item in alerts if item["source"] == "parameter:Maximum Revenue Alert")
        minimum = next(item for item in alerts if item["source"] == "parameter:Minimum Stock Alert")
        self.assertEqual(maximum["operator"], "greaterThan")
        self.assertEqual(maximum["threshold"], 1000.0)
        self.assertEqual(maximum["measure"], "Revenue Variance")
        self.assertEqual(minimum["operator"], "lessThan")
        self.assertEqual(minimum["threshold"], 25.5)
        self.assertEqual(minimum["frequency"], "atMostOncePerDay")

    def test_parameter_payload_dictionary_and_invalid_names(self):
        extracted = {
            "parameters": {
                "parameters": [
                    {"name": "Alert Ceiling", "value": 80},
                    {"name": "ordinary", "value": 10},
                    {"name": "Alert Floor", "value": ""},
                ]
            }
        }
        alerts = extract_alerts(extracted)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["threshold"], 80.0)
        self.assertEqual(alerts[0]["operator"], "greaterThan")

    def test_calculation_literal_operators_and_parameter_lookup(self):
        extracted = {
            "parameters": {
                "parameters": [
                    {"name": "Revenue Threshold", "value": 1500},
                    {"name": "Bad Threshold", "value": "unknown"},
                ]
            },
            "calculations": {
                "calculations": [
                    {"name": "Sales Warning", "caption": "Sales Warning", "formula": "IF [Sales] >= 100 THEN 1 ELSE 0"},
                    {"name": "Margin Alert", "formula": "IF ([Margin] <= [Parameters].[Revenue Threshold]) THEN 1 ELSE 0"},
                    {"name": "Invalid", "formula": "IF [Cost] < [Parameters].[Bad Threshold] THEN 1 ELSE 0"},
                    {"name": "Ignored", "formula": "IF [Cost] > 10 THEN 1 ELSE 0"},
                ]
            },
        }

        alerts = extract_alerts(extracted)

        by_source = {alert["source"]: alert for alert in alerts if alert["source"].startswith("calculation:")}
        self.assertEqual(set(by_source), {"calculation:Sales Warning", "calculation:Margin Alert"})
        self.assertEqual(by_source["calculation:Sales Warning"]["measure"], "Sales")
        self.assertEqual(by_source["calculation:Sales Warning"]["operator"], "greaterThanOrEqual")
        self.assertEqual(by_source["calculation:Sales Warning"]["threshold"], 100.0)
        self.assertEqual(by_source["calculation:Margin Alert"]["measure"], "Margin")
        self.assertEqual(by_source["calculation:Margin Alert"]["operator"], "lessThanOrEqual")
        self.assertEqual(by_source["calculation:Margin Alert"]["threshold"], 1500.0)

    def test_reference_line_extraction_valid_label_value_and_inference(self):
        extracted = {
            "worksheets": {
                "worksheets": [
                    {
                        "name": "Revenue sheet",
                        "fields": [
                            {"name": "Dimension", "role": "dimension"},
                            {"name": "Chiffre d'affaires", "caption": "Ventes", "role": "measure"},
                        ],
                        "reference_lines": [
                            {"label": "Critical target", "value": "250.5"},
                            {"label": "Secondary threshold", "value": "bad"},
                            {"label": "Decorative", "value": 300},
                            {"label": "Alert limit", "value": None},
                        ],
                    }
                ]
            }
        }

        alerts = extract_alerts(extracted)

        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["name"], "Alert: Critical target reference line")
        self.assertEqual(alert["measure"], "Chiffre d'affaires")
        self.assertEqual(alert["operator"], "greaterThan")
        self.assertEqual(alert["threshold"], 250.5)
        self.assertEqual(alert["source"], "reference_line:Revenue sheet")

    def test_reference_line_string_field_fallback_and_unknown_measure(self):
        extracted = {
            "worksheets": [
                {"name": "Sheet A", "fields": ["[Amount]"], "reference_lines": [{"label": "Goal", "value": 10}]},
                {"name": "Sheet B", "fields": [], "reference_lines": [{"label": "Target", "value": 20}]},
            ]
        }
        alerts = extract_alerts(extracted)
        self.assertEqual(alerts[0]["measure"], "Amount")
        self.assertEqual(alerts[1]["measure"], "Sheet B")

    def test_generate_alert_rules_defaults_and_save_unicode(self):
        alerts = [
            {"name": "Alert: Ventés", "measure": "Chiffre d'affaires", "operator": "lessThan", "threshold": 42.5, "frequency": "always", "source": "parameter:Ventés"},
            {"name": "Rule with defaults", "threshold": None},
        ]

        rules = generate_alert_rules(alerts)

        self.assertEqual(rules[0]["name"], "Alert: Ventés")
        self.assertEqual(rules[0]["condition"], {"operator": "lessThan", "threshold": 42.5})
        self.assertEqual(rules[0]["measure"], "Chiffre d'affaires")
        self.assertEqual(rules[0]["frequency"], "always")
        self.assertTrue(rules[0]["isEnabled"])
        self.assertEqual(rules[0]["migrationSource"], "parameter:Ventés")
        self.assertIn("Power BI Service", rules[0]["migrationNote"])
        self.assertEqual(rules[1]["condition"]["operator"], "greaterThan")
        self.assertIsNone(rules[1]["condition"]["threshold"])
        self.assertEqual(rules[1]["measure"], "Unknown")
        self.assertEqual(rules[1]["frequency"], "atMostOncePerDay")

        with tempfile.TemporaryDirectory() as directory:
            path = save_alert_rules(rules, directory)
            self.assertEqual(path, os.path.join(directory, "alert_rules.json"))
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["alertRules"], rules)
            self.assertIn("Ventés", payload["alertRules"][0]["name"])


if __name__ == "__main__":
    unittest.main()
