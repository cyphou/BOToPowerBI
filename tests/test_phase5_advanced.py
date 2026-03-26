"""Phase 5 tests — Fabric-Native & Advanced features (Sprints 27-33).

Tests for:
  Sprint 28: @Aggregate_Aware conversion
  Sprint 29: Context operator deep conversion (Where, ForAll with dims, multi-dim ForEach)
  Sprint 30: Security profile → RLS mapping
  Sprint 31: Schedule migration (refresh config)
  Sprint 32: Multi-tenant CLI wiring
  Sprint 33: Incremental migration CLI wiring
"""

import json
import os
import tempfile
import unittest

from bo_export.dax_converter import convert_bo_formula_to_dax, get_supported_functions


# ══════════════════════════════════════════════════════════════════════════════
# Sprint 28: @Aggregate_Aware
# ══════════════════════════════════════════════════════════════════════════════

class TestAggregateAware(unittest.TestCase):
    """@Aggregate_Aware(expr1, expr2, ...) → SWITCH(TRUE(), ...)."""

    def test_single_expression_unwraps(self):
        formula = "@Aggregate_Aware(SUM([Revenue]))"
        result = convert_bo_formula_to_dax(formula, table_name="Sales")
        self.assertNotIn("SWITCH", result)
        self.assertIn("SUM", result)

    def test_two_expressions(self):
        formula = "@Aggregate_Aware(SUM([Revenue]), SUM([Revenue_Agg]))"
        result = convert_bo_formula_to_dax(formula, table_name="Sales")
        self.assertIn("SWITCH(TRUE()", result)

    def test_three_expressions_last_is_default(self):
        formula = "@Aggregate_Aware(SUM([Rev_Detail]), SUM([Rev_Month]), SUM([Rev_Year]))"
        result = convert_bo_formula_to_dax(formula, table_name="Sales")
        self.assertIn("SWITCH(TRUE()", result)
        # The last expression should be the default (after the last comma)
        self.assertTrue(result.endswith(")"))

    def test_nested_parens_in_args(self):
        formula = "@Aggregate_Aware(SUM(IF([X]>0,[X],0)), SUM([Y]))"
        result = convert_bo_formula_to_dax(formula, table_name="Sales")
        self.assertIn("SWITCH(TRUE()", result)

    def test_function_in_supported_list(self):
        supported = get_supported_functions()
        self.assertIn("@aggregate_aware", supported)


# ══════════════════════════════════════════════════════════════════════════════
# Sprint 29: Context operators deep conversion
# ══════════════════════════════════════════════════════════════════════════════

class TestContextOperatorsDeep(unittest.TestCase):
    """Enhanced context operator conversions."""

    def test_where_clause(self):
        formula = "=SUM([Revenue]) Where ([Region] = \"EMEA\")"
        result = convert_bo_formula_to_dax(formula, table_name="Sales")
        self.assertIn("CALCULATE", result)
        self.assertIn("FILTER", result)

    def test_forall_with_dimensions(self):
        formula = "=SUM([Revenue]) ForAll ([Region]; [Country])"
        result = convert_bo_formula_to_dax(formula, table_name="Sales")
        self.assertIn("CALCULATE", result)
        self.assertIn("ALL(", result)

    def test_forall_no_args(self):
        formula = "=SUM([Revenue]) ForAll"
        result = convert_bo_formula_to_dax(formula, table_name="Sales")
        self.assertIn("CALCULATE", result)
        self.assertIn("ALL('Sales')", result)

    def test_foreach_single_dim(self):
        formula = "=SUM([Revenue]) ForEach ([Product])"
        result = convert_bo_formula_to_dax(formula, table_name="Sales")
        self.assertIn("SUMX", result)
        self.assertIn("VALUES", result)

    def test_foreach_multi_dim(self):
        formula = "=SUM([Revenue]) ForEach ([Region]; [Year])"
        result = convert_bo_formula_to_dax(formula, table_name="Sales")
        self.assertIn("SUMX", result)
        self.assertIn("CROSSJOIN", result)

    def test_foreach_average_picks_averagex(self):
        formula = "=AVERAGE([Price]) ForEach ([Category])"
        result = convert_bo_formula_to_dax(formula, table_name="Products")
        self.assertIn("AVERAGEX", result)

    def test_in_single_dim(self):
        formula = "=SUM([Revenue]) In ([Region])"
        result = convert_bo_formula_to_dax(formula, table_name="Sales")
        self.assertIn("CALCULATE", result)
        self.assertIn("ALLEXCEPT", result)

    def test_in_multi_dim(self):
        formula = "=SUM([Revenue]) In ([Region]; [Year])"
        result = convert_bo_formula_to_dax(formula, table_name="Sales")
        self.assertIn("ALLEXCEPT", result)
        self.assertIn("'Sales'[Region]", result)
        self.assertIn("'Sales'[Year]", result)

    def test_where_in_supported_list(self):
        supported = get_supported_functions()
        self.assertIn("where", supported)


# ══════════════════════════════════════════════════════════════════════════════
# Sprint 30: Security profile migration
# ══════════════════════════════════════════════════════════════════════════════

class TestSecurityProfileMapping(unittest.TestCase):
    """BO security profiles → PBI RLS roles."""

    def test_map_single_profile(self):
        from powerbi_import.permission_mapper import map_bo_security_profiles
        profiles = [{
            'name': 'Sales EMEA',
            'restrictions': [
                {'object': 'Region', 'operator': '=', 'values': ['EMEA']},
            ],
            'members': ['jdoe', 'asmith'],
        }]
        tables = [{'name': 'Sales', 'columns': [{'name': 'Region'}, {'name': 'Revenue'}]}]
        roles = map_bo_security_profiles(profiles, tables)
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0]['name'], 'Sales EMEA')
        self.assertEqual(len(roles[0]['tablePermissions']), 1)
        self.assertIn('Region', roles[0]['tablePermissions'][0]['filterExpression'])

    def test_map_inlist_operator(self):
        from powerbi_import.permission_mapper import map_bo_security_profiles
        profiles = [{
            'name': 'Multi Region',
            'restrictions': [
                {'object': 'Region', 'operator': 'InList', 'values': ['EMEA', 'APAC']},
            ],
            'members': [],
        }]
        tables = [{'name': 'Sales', 'columns': [{'name': 'Region'}]}]
        roles = map_bo_security_profiles(profiles, tables)
        # Should produce OR-ed filter
        filt = roles[0]['tablePermissions'][0]['filterExpression']
        self.assertIn('EMEA', filt)
        self.assertIn('APAC', filt)
        self.assertIn('||', filt)

    def test_map_between_operator(self):
        from powerbi_import.permission_mapper import map_bo_security_profiles
        profiles = [{
            'name': 'Date Range',
            'restrictions': [
                {'object': 'Year', 'operator': 'Between', 'values': ['2020', '2023']},
            ],
            'members': [],
        }]
        tables = [{'name': 'Calendar', 'columns': [{'name': 'Year'}]}]
        roles = map_bo_security_profiles(profiles, tables)
        filt = roles[0]['tablePermissions'][0]['filterExpression']
        self.assertIn('>=', filt)
        self.assertIn('<=', filt)

    def test_empty_profiles_returns_empty(self):
        from powerbi_import.permission_mapper import map_bo_security_profiles
        self.assertEqual(map_bo_security_profiles([], []), [])
        self.assertEqual(map_bo_security_profiles(None, []), [])

    def test_rls_powershell_generation(self):
        from powerbi_import.permission_mapper import generate_rls_powershell
        roles = [
            {'name': 'Viewer', 'members': ['user1@co.com'], 'tablePermissions': []},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'rls.ps1')
            result = generate_rls_powershell(roles, path, dataset_name="TestDS")
            self.assertIsNotNone(result)
            self.assertTrue(os.path.isfile(path))
            content = open(path, encoding='utf-8').read()
            self.assertIn("BO-to-Power-BI", content)
            self.assertNotIn("Tableau", content)


# ══════════════════════════════════════════════════════════════════════════════
# Sprint 31: Schedule migration
# ══════════════════════════════════════════════════════════════════════════════

class TestRefreshConfig(unittest.TestCase):
    """BO scheduled instances → PBI refresh config."""

    def test_generate_refresh_no_schedules(self):
        from powerbi_import.refresh_generator import generate_refresh_config
        result = generate_refresh_config([])
        self.assertIn('notes', result)

    def test_generate_refresh_daily(self):
        from powerbi_import.refresh_generator import generate_refresh_config
        schedules = [{
            'type': 'daily',
            'frequency': 'daily',
            'time': '06:00',
            'timezone': 'UTC',
        }]
        result = generate_refresh_config(schedules)
        self.assertIn('enabled', result)
        self.assertEqual(result['frequency'], 'Daily')

    def test_generate_subscription(self):
        from powerbi_import.refresh_generator import generate_subscription_config
        subscriptions = [{
            'type': 'email',
            'frequency': 'daily',
            'recipients': ['user@co.com'],
            'subject': 'Daily Report',
        }]
        result = generate_subscription_config(subscriptions)
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 1)


# ══════════════════════════════════════════════════════════════════════════════
# Sprint 32: Multi-tenant CLI wiring
# ══════════════════════════════════════════════════════════════════════════════

class TestMultiTenantCLI(unittest.TestCase):
    """Verify multi-tenant arg is parsed and config loading works."""

    def test_parser_accepts_multi_tenant(self):
        from migrate import build_parser
        parser = build_parser()
        args = parser.parse_args(['report.wid', '--multi-tenant', 'config.json'])
        self.assertEqual(args.multi_tenant, 'config.json')

    def test_parser_accepts_refresh_config(self):
        from migrate import build_parser
        parser = build_parser()
        args = parser.parse_args(['report.wid', '--refresh-config'])
        self.assertTrue(args.refresh_config)

    def test_parser_accepts_incremental(self):
        from migrate import build_parser
        parser = build_parser()
        args = parser.parse_args(['report.wid', '--incremental'])
        self.assertTrue(args.incremental)

    def test_parser_accepts_schema_drift(self):
        from migrate import build_parser
        parser = build_parser()
        args = parser.parse_args(['report.wid', '--schema-drift', '/prev/dir'])
        self.assertEqual(args.schema_drift, '/prev/dir')


# ══════════════════════════════════════════════════════════════════════════════
# Sprint 33: Incremental migration
# ══════════════════════════════════════════════════════════════════════════════

class TestIncrementalMigration(unittest.TestCase):
    """Incremental migration module imports and basic functionality."""

    def test_incremental_module_imports(self):
        from powerbi_import.incremental import IncrementalMerger
        self.assertTrue(hasattr(IncrementalMerger, 'merge'))

    def test_schema_drift_module_imports(self):
        from powerbi_import.schema_drift import detect_schema_drift, SchemaDriftEntry
        self.assertTrue(callable(detect_schema_drift))
        self.assertEqual(SchemaDriftEntry.ADDED, 'added')
        self.assertEqual(SchemaDriftEntry.REMOVED, 'removed')
        self.assertEqual(SchemaDriftEntry.MODIFIED, 'modified')

    def test_schema_drift_docstring_updated(self):
        import powerbi_import.schema_drift as sd
        self.assertNotIn('Tableau', sd.__doc__)

    def test_load_previous_extraction_empty_dir(self):
        from migrate import _load_previous_extraction
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _load_previous_extraction(tmpdir)
            self.assertEqual(result, {})

    def test_load_previous_extraction_with_json(self):
        from migrate import _load_previous_extraction
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a sample tables.json
            tables_path = os.path.join(tmpdir, 'tables.json')
            with open(tables_path, 'w') as f:
                json.dump([{'name': 'Sales'}], f)
            result = _load_previous_extraction(tmpdir)
            self.assertIn('tables', result)
            self.assertEqual(result['tables'], [{'name': 'Sales'}])


# ══════════════════════════════════════════════════════════════════════════════
# Cross-sprint: Fabric module Tableau-free verification
# ══════════════════════════════════════════════════════════════════════════════

class TestFabricModulesClean(unittest.TestCase):
    """Verify Fabric modules have no remaining Tableau references."""

    FABRIC_MODULES = [
        'powerbi_import.lakehouse_generator',
        'powerbi_import.dataflow_generator',
        'powerbi_import.pipeline_generator',
        'powerbi_import.fabric_semantic_model_generator',
        'powerbi_import.fabric_project_generator',
        'powerbi_import.fabric_constants',
        'powerbi_import.refresh_generator',
    ]

    def test_no_tableau_in_fabric_docstrings(self):
        import importlib
        for mod_name in self.FABRIC_MODULES:
            mod = importlib.import_module(mod_name)
            doc = getattr(mod, '__doc__', '') or ''
            self.assertNotIn(
                'Tableau', doc,
                f"{mod_name} docstring still contains 'Tableau'"
            )


if __name__ == '__main__':
    unittest.main()
