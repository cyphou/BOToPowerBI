import unittest

from powerbi_import.dax_recipes import (
    apply_recipes,
    get_all_recipes,
    get_industry_recipes,
    list_industries,
    recipes_to_marketplace_format,
)


class DAXRecipesTests(unittest.TestCase):
    def test_industry_lists_are_isolated_copies(self):
        self.assertEqual(list_industries(), ["healthcare", "finance", "retail"])
        healthcare = get_industry_recipes("HEALTHCARE")
        self.assertTrue(healthcare)
        self.assertEqual(healthcare[0]["name"], "Average Length of Stay")
        healthcare.clear()
        self.assertTrue(get_industry_recipes("healthcare"))
        self.assertEqual(get_industry_recipes("unknown"), [])

    def test_all_recipes_and_marketplace_format(self):
        all_recipes = get_all_recipes()
        self.assertGreater(len(all_recipes), 20)
        patterns = recipes_to_marketplace_format("finance")
        self.assertTrue(patterns)
        first = patterns[0]
        self.assertEqual(first["metadata"]["author"], "Finance Template Library")
        self.assertEqual(first["metadata"]["category"], "dax_recipe")
        self.assertEqual(first["payload"]["inject"]["name"], "Net Revenue")

    def test_marketplace_unknown_industry(self):
        self.assertEqual(recipes_to_marketplace_format("unknown"), [])

    def test_apply_injection_skip_and_overwrite(self):
        measures = {"Revenue": "SUM(Sales[Revenue])"}
        recipes = [{"name": "Revenue", "dax": "SUM(Sales[NetRevenue])"},
                   {"name": "Margin", "dax": "DIVIDE([Profit],[Revenue])"},
                   {"name": "", "dax": "ignored"}]
        changes = apply_recipes(measures, recipes)
        self.assertEqual(measures["Revenue"], "SUM(Sales[Revenue])")
        self.assertEqual(measures["Margin"], "DIVIDE([Profit],[Revenue])")
        self.assertEqual(changes["Revenue"], {"action": "skipped", "reason": "exists"})
        self.assertEqual(changes["Margin"]["action"], "injected")

        changes = apply_recipes(measures, [{"name": "Revenue", "dax": "SUM(Sales[Net])"}], overwrite=True)
        self.assertEqual(measures["Revenue"], "SUM(Sales[Net])")
        self.assertEqual(changes["Revenue"]["action"], "injected")

    def test_apply_regex_replacement_is_case_insensitive(self):
        measures = {"Margin %": "DIVIDE(SUM(Sales[Profit]), SUM(Sales[REVENUE]))",
                    "Revenue": "SUM(Sales[Revenue])"}
        recipe = {"name": "Normalize Revenue",
                  "match": r"Sales\[Revenue\]",
                  "replacement": "Sales[NetRevenue]"}
        changes = apply_recipes(measures, [recipe])
        self.assertIn("Sales[NetRevenue]", measures["Margin %"])
        self.assertEqual(measures["Revenue"], "SUM(Sales[NetRevenue])")
        self.assertEqual(changes["Margin %"], {"action": "replaced", "recipe": "Normalize Revenue"})
        self.assertEqual(changes["Revenue"], {"action": "replaced", "recipe": "Normalize Revenue"})

    def test_apply_empty_recipe_and_empty_measures(self):
        measures = {}
        changes = apply_recipes(measures, [])
        self.assertEqual(changes, {})
        changes = apply_recipes(measures, [{"name": "Valid", "dax": ""}, {"name": "", "dax": "1"}])
        self.assertEqual(measures, {})
        self.assertEqual(changes, {})


if __name__ == "__main__":
    unittest.main()
