"""Phase 5 tests — Fabric-Native & Advanced features (Sprints 27-33).

Tests for:
  Sprint 28: @Aggregate_Aware conversion
  Sprint 29: Context operator deep conversion (Where, ForAll with dims, multi-dim ForEach)
  Sprint 30: Security profile → RLS mapping
  Sprint 31: Schedule migration (refresh config)
  Sprint 32: Multi-tenant CLI wiring
  Sprint 33: Incremental migration CLI wiring
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, call, patch

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

    def test_map_supported_operators(self):
        from powerbi_import.permission_mapper import map_bo_security_profiles

        ref = "'Sales'[Region]"
        cases = [
            (('=', 'equal', 'EQUALS'), ['EMEA'], f'{ref} = "EMEA"'),
            (('=',), ['EMEA', 'APAC'], f'{ref} = "EMEA" || {ref} = "APAC"'),
            (('InList', 'in'), ['EMEA', 'APAC'],
             f'{ref} = "EMEA" || {ref} = "APAC"'),
            (('<>', 'notequal', 'not equal'), ['EMEA'], f'{ref} <> "EMEA"'),
            (('<>', 'notequal', 'not equal'), ['EMEA', 'APAC'],
             f'{ref} <> "EMEA" && {ref} <> "APAC"'),
            (('Between',), ['A', 'Z'], f'{ref} >= "A" && {ref} <= "Z"'),
            (('>', 'greater'), ['A'], f'{ref} > "A"'),
            (('<', 'less'), ['Z'], f'{ref} < "Z"'),
            (('>=', 'greaterorequal'), ['A'], f'{ref} >= "A"'),
            (('<=', 'lessorequal'), ['Z'], f'{ref} <= "Z"'),
            (('like', 'matches pattern'), ['A%'], f'CONTAINSSTRING({ref}, "A*")'),
        ]
        tables = [{'name': 'Sales', 'columns': [{'name': 'Region'}]}]
        for operators, values, expected in cases:
            for operator in operators:
                with self.subTest(operator=operator):
                    profiles = [{'name': 'Sales EMEA', 'members': ['jdoe'],
                                 'restrictions': [{'object': 'region',
                                                   'operator': operator,
                                                   'values': values}]}]
                    roles = map_bo_security_profiles(profiles, tables)
                    self.assertEqual(roles[0]['name'], 'Sales EMEA')
                    self.assertEqual(roles[0]['members'], ['jdoe'])
                    self.assertEqual(roles[0]['tablePermissions'], [
                        {'table': 'Sales', 'filterExpression': expected},
                    ])
                    self.assertEqual(len(roles), 1)

    def test_map_escapes_identifiers_and_values_with_actual_column_case(self):
        from powerbi_import.permission_mapper import map_bo_security_profiles

        tables = [{'name': "Ventes d'été", 'columns': [{'name': 'RéGion]Code'}]},
                  {'name': 'Calendar', 'columns': ['Year']}]
        profiles = [{'name': 'Équipe!', 'members': ['utilisateur'],
                     'restrictions': [
                         {'object': 'région]code', 'operator': '=',
                          'values': ['été "Nord"']},
                         {'object': 'year', 'operator': 'Between',
                          'values': ['2020', '2023']},
                     ]}]
        roles = map_bo_security_profiles(profiles, tables)
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0]['name'], 'Équipe')
        self.assertEqual(roles[0]['members'], ['utilisateur'])
        self.assertEqual(roles[0]['tablePermissions'], [
            {'table': "Ventes d'été",
             'filterExpression': '\'Ventes d\'\'été\'[RéGion]]Code] = "été ""Nord"""'},
            {'table': 'Calendar',
             'filterExpression': '\'Calendar\'[Year] >= "2020" && '
                                 '\'Calendar\'[Year] <= "2023"'},
        ])

    def test_map_unicode_casefold_and_escapes_list_values(self):
        from powerbi_import.permission_mapper import map_bo_security_profiles

        tables = [{'name': "Länder's", 'columns': ['Straße']}]
        profiles = [{'restrictions': [{'object': 'STRASSE', 'operator': 'InList',
                                       'values': ['一"二', '"trois"']}]}]
        roles = map_bo_security_profiles(profiles, tables)
        self.assertEqual(roles[0]['tablePermissions'], [{
            'table': "Länder's",
            'filterExpression': '\'Länder\'\'s\'[Straße] = "一""二" || '
                                '\'Länder\'\'s\'[Straße] = """trois"""',
        }])

    def test_map_rejects_missing_or_ambiguous_columns(self):
        from powerbi_import.permission_mapper import map_bo_security_profiles

        secret = 'RESTRICTION_VALUE_SENTINEL'
        restriction = {'object': 'region', 'operator': '=', 'values': [secret]}
        cases = [
            (restriction, []),
            ({'operator': '=', 'values': [secret]},
             [{'name': 'Sales', 'columns': ['Region']}]),
            (restriction, [{'name': 'Sales', 'columns': ['Other']}]),
            (restriction, [{'name': 'Sales', 'columns': ['Region']},
                           {'name': 'Other', 'columns': ['REGION']}]),
            (restriction, [{'name': 'Sales', 'columns': ['Region']},
                           {'name': 'Sales', 'columns': ['region']}]),
            (restriction, [{'name': 'Sales', 'columns': ['Region', 'region']}]),
            (restriction, [{'name': 'Sales', 'columns': ['Region', 'Region']}]),
            ({**restriction, 'object': 'STRASSE'},
             [{'name': 'Sales', 'columns': ['Straße', 'STRASSE']}]),
        ]
        for restriction, tables in cases:
            with self.subTest(restriction=restriction, tables=tables):
                with self.assertRaises(ValueError) as error:
                    map_bo_security_profiles([{'restrictions': [restriction]}], tables)
                self.assertNotIn(secret, str(error.exception))

    def test_map_rejects_invalid_operators_and_values(self):
        from powerbi_import.permission_mapper import map_bo_security_profiles

        secret = 'RESTRICTION_VALUE_SENTINEL'
        tables = [{'name': 'Sales', 'columns': ['Region']}]
        base = {'object': 'Region', 'operator': '=', 'values': [secret]}
        cases = [
            {key: value for key, value in base.items() if key != 'operator'},
            {**base, 'operator': ''}, {**base, 'operator': '   '},
            {**base, 'operator': None},
            {**base, 'operator': 'unsupported'},
            {key: value for key, value in base.items() if key != 'values'},
            *({**base, 'values': value} for value in
              (None, [], '', secret, (secret,), 42, [secret, 42], [secret, None])),
            *({**base, 'operator': operator, 'values': [secret, 'extra']}
              for operator in ('>', '<', '>=', '<=', 'greater', 'less',
                               'greaterorequal', 'lessorequal', 'like',
                               'matches pattern', 'equal', 'equals')),
            *({**base, 'operator': 'Between', 'values': values}
              for values in ([secret], [secret, 'second', 'third'])),
        ]
        for restriction in cases:
            with self.subTest(restriction=restriction):
                with self.assertRaises(ValueError) as error:
                    map_bo_security_profiles([{'restrictions': [restriction]}], tables)
                self.assertNotIn(secret, str(error.exception))

    def test_map_rejects_profiles_without_restrictions(self):
        from powerbi_import.permission_mapper import map_bo_security_profiles

        secret = 'RESTRICTION_VALUE_SENTINEL'
        tables = [{'name': 'Sales', 'columns': ['Region']}]
        valid = {'restrictions': [{'object': 'Region', 'operator': '=',
                                   'values': [secret]}]}
        for profile in ({}, {'restrictions': []}, {'restrictions': None}):
            with self.subTest(profile=profile):
                with self.assertRaises(ValueError) as error:
                    map_bo_security_profiles([valid, profile], tables)
                self.assertNotIn(secret, str(error.exception))

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

    def assert_inert_rls_guidance(self, content, supplied_emails=()):
        """Only a literal terminating throw may be executable."""
        lower = content.lower()
        self.assertNotIn('invoke-powerbirestmethod', lower)
        self.assertNotIn('connect-powerbiserviceaccount', lower)
        self.assertNotIn('datasetuseraccessright', lower)

        self.assertLessEqual(
            set(re.findall(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', content, re.I)),
            set(supplied_emails),
        )
        executable = [
            line.strip() for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith('#')
        ]
        self.assertEqual(len(executable), 1, executable)
        statement = executable[0]
        # A literal prevents command substitution, interpolation and extra
        # commands even if untrusted input is embedded in the throw.
        self.assertRegex(
            statement,
            r'''(?i)^throw\s+(?:'(?:[^'\r\n]|'')*'|"[^"$`\r\n]*")\s*;?\s*$'''
        )
        for word in ('automatic', 'rls', 'role', 'assign'):
            self.assertIn(word, statement.lower())
        self.assertRegex(statement.lower(), r'unsupported|not supported')
        return statement

    def test_rls_powershell_is_inert_guidance(self):
        from powerbi_import.permission_mapper import generate_rls_powershell

        sentinels = (
            'ROLE_EXECUTION_SENTINEL', 'MEMBER_EXECUTION_SENTINEL',
            'SUBEXPRESSION_SENTINEL', 'DATASET_EXECUTION_SENTINEL',
        )
        role, member, subexpression, dataset = sentinels
        cases = [
            ([{'name': 'Viewer', 'members': ['unmapped_bo_user'],
               'tablePermissions': []}], 'TestDS', ()),
            ([{
                'name': f"Finance\r\nWrite-Output '{role}'; #",
                'members': [
                    f"unmapped_bo_user\nWrite-Output '{member}'; #",
                    'actual.member@contoso.example',
                    f'$(Write-Output "{subexpression}")',
                ],
                'tablePermissions': [],
            }],
             f'Sales";\n$(Write-Output "{dataset}"); #',
             ('actual.member@contoso.example',)),
            ([{'name': 'Empty role', 'members': [], 'tablePermissions': []}],
             'TestDS', ()),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            for index, (roles, dataset_name, supplied_emails) in enumerate(cases):
                with self.subTest(case=index):
                    path = os.path.join(tmpdir, f'rls_{index}.ps1')
                    self.assertEqual(
                        generate_rls_powershell(roles, path, dataset_name), path
                    )
                    with open(path, encoding='utf-8') as script:
                        content = script.read()
                    statement = self.assert_inert_rls_guidance(content, supplied_emails)
                    for sentinel in (*sentinels, 'unmapped_bo_user'):
                        self.assertNotIn(sentinel, statement)

                    if index == 1:
                        with self.subTest(runtime='PowerShell'):
                            powershell = shutil.which('powershell') or shutil.which('pwsh')
                            if not powershell:
                                self.skipTest('PowerShell is not installed')
                            command = [powershell, '-NoProfile', '-NonInteractive']
                            if os.name == 'nt':
                                command.extend(['-ExecutionPolicy', 'Bypass'])
                            result = subprocess.run(
                                command + ['-File', path], capture_output=True,
                                text=True, errors='replace', timeout=30
                            )
                            self.assertNotEqual(result.returncode, 0)
                            output = result.stdout + result.stderr
                            self.assertIn('automatic rls role assignment', output.lower())
                            self.assertRegex(output.lower(), r'unsupported|not supported')
                            for sentinel in sentinels:
                                self.assertNotIn(sentinel, output)

    def test_rls_powershell_no_roles_creates_no_file(self):
        from powerbi_import.permission_mapper import generate_rls_powershell

        with tempfile.TemporaryDirectory() as tmpdir:
            for index, roles in enumerate(([], None)):
                with self.subTest(roles=roles):
                    directory = os.path.join(tmpdir, str(index))
                    path = os.path.join(directory, 'rls.ps1')
                    self.assertIsNone(generate_rls_powershell(roles, path))
                    self.assertFalse(os.path.exists(path))
                    self.assertFalse(os.path.exists(directory))

    def test_project_automation_artifacts_report_rls_manual_review(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            generator = PowerBIProjectGenerator(tmpdir)
            project_dir = os.path.join(tmpdir, 'with_filters')
            empty_dir = os.path.join(tmpdir, 'without_filters')
            os.makedirs(project_dir)
            os.makedirs(empty_dir)

            output = io.StringIO()
            with redirect_stdout(output):
                generator._generate_automation_artifacts(project_dir, 'Sales Report', {
                    'user_filters': [{
                        'role_name': "Reviewer\nWrite-Output 'ROLE_SENTINEL'; #",
                        'users': ['legacy_user'],
                    }],
                })
            path = os.path.join(project_dir, 'assign_rls_roles.ps1')
            self.assertTrue(os.path.isfile(path))
            with open(path, encoding='utf-8') as script:
                statement = self.assert_inert_rls_guidance(script.read())
            self.assertNotIn('ROLE_SENTINEL', statement)
            self.assertNotIn('legacy_user', statement)

            reported = output.getvalue().lower()
            self.assertIn(path.lower(), reported)
            for word in ('rls', 'manual', 'review', 'assignment'):
                self.assertIn(word, reported)
            self.assertRegex(reported, r'\bautomat(?:ic|ed)\b')
            self.assertRegex(reported, r'unsupported|not supported')

            empty_output = io.StringIO()
            with redirect_stdout(empty_output):
                generator._generate_automation_artifacts(
                    empty_dir, 'Sales Report', {'user_filters': []}
                )
            self.assertFalse(os.path.exists(
                os.path.join(empty_dir, 'assign_rls_roles.ps1')
            ))
            self.assertNotIn('rls', empty_output.getvalue().lower())


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


class TestRefreshCandidates(unittest.TestCase):
    """Schedule migration must produce reviewable, non-executable candidates."""

    def assert_review_candidate(self, candidate):
        self.assertIs(candidate['enabled'], False)
        notes = ' '.join(candidate['notes']).lower()
        self.assertIn('manual', notes)
        self.assertIn('review', notes)
        self.assertRegex(notes, r'\brequir\w*|\bmust\b|\bneed\w*')
        return notes

    def assert_unavailable(self, candidate, field):
        self.assertIn(candidate.get(field), (None, '', []), (field, candidate))

    def test_no_bo_schedule_is_disabled_and_explained(self):
        from powerbi_import.refresh_generator import generate_refresh_config

        for tasks in ([], None):
            with self.subTest(tasks=tasks):
                result = generate_refresh_config(tasks)
                notes = self.assert_review_candidate(result)
                self.assertIn('schedule', notes)
                for field in ('frequency', 'times', 'days', 'localTimeZoneId'):
                    self.assert_unavailable(result, field)

    def assert_invalid_tasks(self, tasks):
        from powerbi_import.refresh_generator import generate_refresh_config

        with self.assertLogs('powerbi_import.refresh_generator', level='WARNING') as logs:
            result = generate_refresh_config(tasks)
        notes = self.assert_review_candidate(result)
        self.assertRegex(notes, r'scheduled instances?.*invalid')
        self.assertRegex(' '.join(logs.output).lower(), r'scheduled instances?.*invalid')
        for field in ('frequency', 'times', 'days', 'localTimeZoneId'):
            self.assert_unavailable(result, field)

    def test_non_list_tasks_are_invalid(self):
        for tasks in ({'frequency': 'Daily', 'time': '09:15', 'timezone': 'UTC'},
                      ('task',), 'task'):
            with self.subTest(tasks=tasks):
                self.assert_invalid_tasks(tasks)

    def test_single_non_dict_task_is_invalid(self):
        for task in (None, 'task', 42, ['nested']):
            with self.subTest(task=task):
                self.assert_invalid_tasks([task])

    def test_single_daily_and_weekly_preserve_explicit_values(self):
        from powerbi_import.refresh_generator import generate_refresh_config

        for frequency, time, days in (
            ('Daily', '00:00', []),
            ('Weekly', '23:59', ['Monday', 'Friday']),
        ):
            schedule = {
                'frequency': frequency, 'timezone': 'Europe/Paris',
                'frequencyDetails': {
                    'start': time, 'intervals': {'weekDay': days},
                },
            }
            for task in (schedule, {'schedule': schedule}):
                with self.subTest(frequency=frequency, task=task):
                    result = generate_refresh_config([task])
                    self.assert_review_candidate(result)
                    self.assertEqual(result['frequency'], frequency)
                    self.assertEqual(result['times'], [time])
                    self.assertEqual(result['localTimeZoneId'], 'Europe/Paris')
                    if days:
                        self.assertCountEqual(result['days'], days)
                    else:
                        self.assert_unavailable(result, 'days')

    def test_single_referenced_schedule_preserves_values(self):
        from powerbi_import.refresh_generator import generate_refresh_config

        result = generate_refresh_config(
            [{'schedule_id': 'schedule-1'}],
            [{'id': 'schedule-1', 'frequency': 'Daily',
              'time': '09:15', 'timezone': 'Asia/Tokyo'}],
        )
        self.assert_review_candidate(result)
        self.assertEqual(result['frequency'], 'Daily')
        self.assertEqual(result['times'], ['09:15'])
        self.assertEqual(result['localTimeZoneId'], 'Asia/Tokyo')

    def test_invalid_schedule_lookup_collections_and_items(self):
        from powerbi_import.refresh_generator import generate_refresh_config

        valid = {'id': 'schedule-1', 'frequency': 'Daily',
                 'time': '09:15', 'timezone': 'UTC'}
        for schedules in ({}, '', 0, False, {'schedule-1': valid}, 'invalid',
                          42, (), (valid,), [None], ['invalid'], [valid, 42]):
            with self.subTest(schedules=schedules):
                result = generate_refresh_config(
                    [{'schedule_id': 'schedule-1'}], schedules
                )
                self.assert_review_candidate(result)
                self.assertTrue(any(
                    'invalid' in note.lower()
                    and ('schedule' in note.lower() or 'lookup' in note.lower())
                    for note in result['notes']
                ), result['notes'])

    def test_absent_schedule_lookup_reports_missing_reference(self):
        from powerbi_import.refresh_generator import generate_refresh_config

        for schedules in (None, []):
            with self.subTest(schedules=schedules):
                result = generate_refresh_config(
                    [{'schedule_id': 'schedule-1'}], schedules
                )
                notes = self.assert_review_candidate(result)
                self.assertRegex(notes, r'(?:missing|not found|unavailable)')

    def test_missing_and_invalid_times_are_not_defaulted(self):
        from powerbi_import.refresh_generator import generate_refresh_config

        for time in (None, '', 'not-a-time', '09:15junk', '24:00', '12:60'):
            with self.subTest(time=time):
                schedule = {'frequency': 'Daily', 'timezone': 'Europe/Paris'}
                if time is not None:
                    schedule['time'] = time
                result = generate_refresh_config([{'schedule': schedule}])
                notes = self.assert_review_candidate(result)
                self.assertIn('time', notes)
                self.assert_unavailable(result, 'times')
                self.assertEqual(result['frequency'], 'Daily')
                self.assertEqual(result['localTimeZoneId'], 'Europe/Paris')

    def test_missing_and_unsupported_frequencies_are_not_defaulted(self):
        from powerbi_import.refresh_generator import generate_refresh_config

        for frequency in (None, '', 'unknown', 'Hourly', 'Monthly', 42):
            with self.subTest(frequency=frequency):
                schedule = {'time': '09:15', 'timezone': 'Europe/Paris'}
                if frequency is not None:
                    schedule['frequency'] = frequency
                result = generate_refresh_config([{'schedule': schedule}])
                notes = self.assert_review_candidate(result)
                self.assertIn('frequen', notes)
                self.assert_unavailable(result, 'frequency')
                self.assertEqual(result['times'], ['09:15'])
                self.assertEqual(result['localTimeZoneId'], 'Europe/Paris')

    def test_weekly_days_are_not_invented_or_accepted_unvalidated(self):
        from powerbi_import.refresh_generator import generate_refresh_config

        for declared, expected in (([], []), (['Funday'], []),
                                   (['Monday', 'Funday'], ['Monday'])):
            with self.subTest(declared=declared):
                schedule = {
                    'frequency': 'Weekly', 'time': '09:15',
                    'timezone': 'Europe/Paris',
                    'intervals': {'weekDay': declared},
                }
                result = generate_refresh_config([{'schedule': schedule}])
                notes = self.assert_review_candidate(result)
                self.assertIn('day', notes)
                self.assertCountEqual(result.get('days') or [], expected)
                self.assertEqual(result['frequency'], 'Weekly')
                self.assertEqual(result['times'], ['09:15'])

    def test_additional_intervals_are_flagged_for_manual_review(self):
        from powerbi_import.refresh_generator import generate_refresh_config

        cases = (
            ('Weekly', {'weekDay': ['Monday'], 'minutes': [15]},
             r'minute|(?:additional|extra|unsupported).*interval'),
            ('Daily', {'hours': [8]},
             r'hour|(?:additional|extra|unsupported).*interval'),
            ('Daily', {'weekDay': ['Monday']}, r'week\s*day|\bdays?\b'),
        )
        for frequency, intervals, reason in cases:
            with self.subTest(frequency=frequency, intervals=intervals):
                result = generate_refresh_config([{'schedule': {
                    'frequency': frequency, 'timezone': 'Europe/Paris',
                    'frequencyDetails': {'start': '09:15', 'intervals': intervals},
                }}])
                self.assert_review_candidate(result)
                review_notes = [
                    note.lower() for note in result['notes']
                    if 'manual' in note.lower() and 'review' in note.lower()
                ]
                self.assertRegex('\n'.join(review_notes), reason)
                self.assertEqual(result['times'], ['09:15'])
                if frequency == 'Weekly' and result.get('days'):
                    self.assertEqual(result['days'], ['Monday'])

    def test_missing_timezone_is_not_defaulted(self):
        from powerbi_import.refresh_generator import generate_refresh_config

        for timezone in (None, ''):
            with self.subTest(timezone=timezone):
                schedule = {'frequency': 'Daily', 'time': '09:15'}
                if timezone is not None:
                    schedule['timezone'] = timezone
                result = generate_refresh_config([{'schedule': schedule}])
                notes = self.assert_review_candidate(result)
                self.assertRegex(notes, r'time\s*zone')
                self.assert_unavailable(result, 'localTimeZoneId')
                self.assertEqual(result['frequency'], 'Daily')
                self.assertEqual(result['times'], ['09:15'])

    def test_multiple_schedules_are_not_aggregated(self):
        from powerbi_import.refresh_generator import generate_refresh_config

        schedules = [
            {'frequency': 'Weekly', 'time': '09:15', 'timezone': 'Europe/Paris',
             'intervals': {'weekDay': ['Monday']}},
            {'frequency': 'Weekly', 'time': '17:45', 'timezone': 'Asia/Tokyo',
             'intervals': {'weekDay': ['Friday']}},
        ]
        for tasks in (schedules, [{'schedule': schedule} for schedule in schedules]):
            with self.subTest(tasks=tasks):
                result = generate_refresh_config(tasks)
                notes = self.assert_review_candidate(result)
                self.assertRegex(notes, r'multiple|more than one|ambiguous')
                self.assertFalse({'09:15', '17:45'} <= set(result.get('times') or []))
                self.assertFalse({'Monday', 'Friday'} <= set(result.get('days') or []))

    def test_empty_subscription_inputs_remain_empty(self):
        from powerbi_import.refresh_generator import (
            generate_refresh_json, generate_subscription_config,
        )

        for subscriptions in (None, []):
            with self.subTest(subscriptions=subscriptions):
                self.assertEqual(generate_subscription_config(subscriptions), [])
                self.assertEqual(
                    generate_refresh_json([], subscriptions)['subscriptions'], []
                )

    def assert_invalid_subscription_containers(self, generate):
        for subscriptions in ({}, '', 0, False, {'subject': 'Report'}, 'invalid',
                              42, True, (), ({'subject': 'Report'},)):
            with self.subTest(subscriptions=subscriptions):
                with self.assertRaises(ValueError):
                    generate(subscriptions)

    def test_subscription_config_rejects_non_list_containers(self):
        from powerbi_import.refresh_generator import generate_subscription_config

        self.assert_invalid_subscription_containers(generate_subscription_config)

    def test_refresh_json_rejects_non_list_subscription_containers(self):
        from powerbi_import.refresh_generator import generate_refresh_json

        self.assert_invalid_subscription_containers(
            lambda subscriptions: generate_refresh_json([], subscriptions)
        )

    def test_subscription_preserves_explicit_email_as_unverified(self):
        from powerbi_import.refresh_generator import generate_subscription_config

        for sub in (
            {'subject': 'Report', 'user': {'email': 'reader@example.test'},
             'schedule': {'frequency': 'Weekly', 'time': '09:15'}},
            {'subject': 'Report', 'recipients': ['reader@example.test'],
             'frequency': 'Weekly', 'time': '09:15'},
        ):
            with self.subTest(sub=sub):
                result = generate_subscription_config([sub])
                self.assertEqual(len(result), 1)
                candidate = result[0]
                notes = self.assert_review_candidate(candidate)
                self.assertRegex(notes, r'unverified|not verified|verify')
                self.assertEqual(candidate['recipients'], ['reader@example.test'])
                self.assertEqual(candidate['frequency'], 'Weekly')
                self.assertEqual(candidate['time'], '09:15')

    def test_subscription_missing_recipient_time_and_frequency(self):
        from powerbi_import.refresh_generator import generate_subscription_config

        result = generate_subscription_config([{
            'subject': 'Report', 'user': {'name': 'legacy-user'},
        }])
        self.assertEqual(len(result), 1)
        candidate = result[0]
        notes = self.assert_review_candidate(candidate)
        self.assertRegex(notes, r'recipient|email')
        self.assertIn('time', notes)
        self.assertIn('frequen', notes)
        for field in ('recipients', 'time', 'frequency'):
            self.assert_unavailable(candidate, field)

    def test_subscription_invalid_time_and_frequency_are_not_defaulted(self):
        from powerbi_import.refresh_generator import generate_subscription_config

        for frequency in (None, '', 'unknown', 'Hourly', 'Monthly'):
            for time in (None, 'bad-time', '24:00', '12:60', '09:15junk'):
                with self.subTest(frequency=frequency, time=time):
                    schedule = {}
                    if frequency is not None:
                        schedule['frequency'] = frequency
                    if time is not None:
                        schedule['time'] = time
                    candidate = generate_subscription_config([{
                        'user': {'email': 'reader@example.test'},
                        'schedule': schedule,
                    }])[0]
                    notes = self.assert_review_candidate(candidate)
                    self.assertIn('frequen', notes)
                    self.assertIn('time', notes)
                    self.assertRegex(notes, r'unverified|not verified|verify')
                    self.assert_unavailable(candidate, 'frequency')
                    self.assert_unavailable(candidate, 'time')
                    self.assertEqual(candidate['recipients'], ['reader@example.test'])

    def test_deployer_skips_generated_candidates_without_calling_client(self):
        from unittest.mock import Mock

        from powerbi_import.deploy.pbi_deployer import PBIWorkspaceDeployer
        from powerbi_import.refresh_generator import generate_refresh_config

        client = Mock()
        deployer = PBIWorkspaceDeployer('workspace', client=client)
        for tasks in ([], [{
            'schedule': {'frequency': 'Daily', 'time': '09:15',
                         'timezone': 'Europe/Paris'},
        }]):
            with self.subTest(tasks=tasks):
                candidate = generate_refresh_config(tasks)
                result = deployer.deploy_refresh_schedule('dataset', candidate)
                self.assertIs(candidate['enabled'], False)
                self.assertEqual(result['status'], 'skipped')
                self.assertEqual(result['dataset_id'], 'dataset')
                self.assertEqual(result['notes'], candidate['notes'])
                self.assertEqual(client.mock_calls, [])

    def test_combined_artifact_keeps_both_candidates_disabled(self):
        from powerbi_import.refresh_generator import generate_refresh_json

        result = generate_refresh_json(
            [{'schedule': {'frequency': 'Daily', 'time': '09:15',
                           'timezone': 'Europe/Paris'}}],
            [{'user': {'email': 'reader@example.test'},
              'schedule': {'frequency': 'Daily', 'time': '09:15'}}],
        )
        self.assert_review_candidate(result['refresh'])
        self.assertEqual(len(result['subscriptions']), 1)
        self.assert_review_candidate(result['subscriptions'][0])
        self.assertEqual(result['subscriptions'][0]['recipients'],
                         ['reader@example.test'])


class TestDeployerRefreshSchedule(unittest.TestCase):
    """Only complete schedule declarations may reach the mocked service client."""

    DAYS = [
        'Monday', 'Tuesday', 'Wednesday', 'Thursday',
        'Friday', 'Saturday', 'Sunday',
    ]

    def setUp(self):
        from powerbi_import.deploy.pbi_deployer import PBIWorkspaceDeployer

        self.client = Mock()
        self.deployer = PBIWorkspaceDeployer('workspace-id', client=self.client)
        self.valid = {
            'enabled': True,
            'days': ['Friday', 'Monday'],
            'times': ['00:00', '09:15', '23:59'],
            'localTimeZoneId': 'Europe/Paris',
        }
        self.url = (
            'https://api.powerbi.com/v1.0/myorg/groups/workspace-id/'
            'datasets/dataset-id/refreshSchedule'
        )

    def assert_invalid(self, config):
        self.client.reset_mock()
        result = self.deployer.deploy_refresh_schedule('dataset-id', config)
        self.assertEqual(self.client.mock_calls, [])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['dataset_id'], 'dataset-id')
        self.assertIsInstance(result['error'], str)
        self.assertTrue(result['error'].strip())

    def assert_patch(self, config, value):
        self.client.reset_mock()
        result = self.deployer.deploy_refresh_schedule('dataset-id', config)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['dataset_id'], 'dataset-id')
        self.assertEqual(
            self.client.mock_calls,
            [call._request('PATCH', self.url, data={'value': value})],
        )

    def test_none_is_skipped_with_explicit_note(self):
        result = self.deployer.deploy_refresh_schedule('dataset-id', None)
        self.assertEqual(self.client.mock_calls, [])
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['dataset_id'], 'dataset-id')
        notes = result['notes']
        self.assertIsInstance(notes, (list, str))
        if isinstance(notes, list):
            self.assertTrue(all(isinstance(note, str) for note in notes))
            notes = ' '.join(notes)
        self.assertRegex(notes.lower(), r'schedule|config')
        self.assertRegex(notes.lower(), r'no\b|not\b|absent|missing')

    def test_non_dictionary_and_missing_or_nonboolean_enabled_fail(self):
        nonbooleans = (None, 0, 1, 0.0, 1.0, '', 'false', 'true', [], {})
        for config in (
            [], (), '', 'schedule', 0, 1, False, True,
            {}, {'days': ['Monday']},
            *({'enabled': value} for value in nonbooleans),
            *({**self.valid, 'enabled': value} for value in nonbooleans),
        ):
            with self.subTest(config=config):
                self.assert_invalid(config)

    def test_disabled_drafts_skip_even_with_incomplete_or_invalid_fields(self):
        for config in (
            {'enabled': False, 'notes': ['Review this draft', 'No timezone']},
            {'enabled': False, 'days': 'invalid', 'times': [],
             'localTimeZoneId': None, 'frequency': 'Hourly',
             'notifyOption': 'invalid', 'notes': ['Unverified']},
        ):
            with self.subTest(config=config):
                self.client.reset_mock()
                result = self.deployer.deploy_refresh_schedule('dataset-id', config)
                self.assertEqual(self.client.mock_calls, [])
                self.assertEqual(result['status'], 'skipped')
                self.assertEqual(result['dataset_id'], 'dataset-id')
                self.assertEqual(result['notes'], config['notes'])

    def test_days_must_be_a_nonempty_list_of_unique_case_sensitive_names(self):
        configs = [{key: value for key, value in self.valid.items() if key != 'days'}]
        configs.extend(
            {**self.valid, 'days': days}
            for days in (
                None, [], 'Monday', ('Monday',), {}, [None], [1], [['Monday']],
                ['monday'], ['MONDAY'], ['Monday '], ['Funday'],
                ['Monday', 'Monday'], ['Monday', 'monday'],
            )
        )
        for config in configs:
            with self.subTest(days=config.get('days', '<missing>')):
                self.assert_invalid(config)

    def test_times_must_be_a_nonempty_list_of_valid_hh_mm_values(self):
        configs = [{key: value for key, value in self.valid.items() if key != 'times'}]
        configs.extend(
            {**self.valid, 'times': times}
            for times in (
                None, [], '09:15', ('09:15',), {}, [None], [915], [['09:15']],
                ['9:15'], ['09:5'], ['24:00'], ['23:60'], ['-1:00'],
                [' 09:15'], ['09:15Z'], ['09:15:00'], ['09:15', '25:00'],
            )
        )
        for config in configs:
            with self.subTest(times=config.get('times', '<missing>')):
                self.assert_invalid(config)

    def test_timezone_must_be_a_nonempty_string(self):
        configs = [
            {key: value for key, value in self.valid.items() if key != 'localTimeZoneId'}
        ]
        configs.extend(
            {**self.valid, 'localTimeZoneId': timezone}
            for timezone in (None, '', '  ', 0, False, [], {})
        )
        for config in configs:
            with self.subTest(timezone=config.get('localTimeZoneId', '<missing>')):
                self.assert_invalid(config)

    def test_optional_notification_must_be_one_of_the_explicit_values(self):
        for notify in (None, '', 'mailonfailure', 'MailOnSuccess', 0, False, [], {}):
            with self.subTest(notify=notify):
                self.assert_invalid({**self.valid, 'notifyOption': notify})

    def test_optional_frequency_is_declared_daily_or_weekly(self):
        for frequency in (None, '', 'daily', 'WEEKLY', 'Hourly', 1, False, [], {}):
            with self.subTest(frequency=frequency):
                self.assert_invalid({**self.valid, 'frequency': frequency})
        for days in (['Monday'], self.DAYS[:-1]):
            with self.subTest(daily_days=days):
                self.assert_invalid({**self.valid, 'frequency': 'Daily', 'days': days})

    def test_valid_schedules_patch_exact_values_without_defaults_or_metadata(self):
        # Frequencies are manually declared; these mock-only tests do not verify
        # Power BI's target-side acceptance or scheduling semantics.
        cases = (
            (self.valid, dict(self.valid)),
            ({**self.valid, 'frequency': 'Weekly', 'notifyOption': 'NoNotification',
              'notes': ['Manually reviewed']},
             {**self.valid, 'notifyOption': 'NoNotification'}),
            ({**self.valid, 'frequency': 'Daily', 'days': list(reversed(self.DAYS)),
              'notifyOption': 'MailOnFailure'},
             {**self.valid, 'days': list(reversed(self.DAYS)),
              'notifyOption': 'MailOnFailure'}),
            ({**self.valid, 'frequency': 'Weekly', 'days': list(self.DAYS)},
             {**self.valid, 'days': list(self.DAYS)}),
            ({**self.valid, 'frequency': 'Weekly', 'days': ['Sunday'],
              'times': ['06:00', '06:00'], 'localTimeZoneId': 'UTC'},
             {**self.valid, 'days': ['Sunday'], 'times': ['06:00', '06:00'],
              'localTimeZoneId': 'UTC'}),
        )
        for config, value in cases:
            with self.subTest(config=config):
                self.assert_patch(config, value)

    def test_api_exception_returns_failed(self):
        self.client._request.side_effect = RuntimeError('simulated API failure')
        result = self.deployer.deploy_refresh_schedule('dataset-id', self.valid)
        self.assertEqual(
            self.client.mock_calls,
            [call._request('PATCH', self.url, data={'value': self.valid})],
        )
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['dataset_id'], 'dataset-id')
        self.assertIn('simulated API failure', result['error'])


class TestDeployerRollingBlocked(unittest.TestCase):
    """Rolling deployment is blocked before any remote or validation work."""

    def setUp(self):
        from powerbi_import.deploy.pbi_deployer import (
            DeploymentResult, PBIWorkspaceDeployer,
        )

        self.client = Mock()
        self.deployer = PBIWorkspaceDeployer('workspace-id', client=self.client)
        # If the old implementation runs, let it reach the refresh and cleanup
        # paths without packaging, polling, or making network requests.
        self.deploy = self.enterContext(patch.object(
            self.deployer, 'deploy_project',
            return_value=DeploymentResult(
                'Sales__canary', status='succeeded', dataset_id='canary-id',
            ),
        ))
        self.validate = self.enterContext(patch.object(
            self.deployer, 'validate_deployment',
            return_value={'overall': 'passed'},
        ))
        self.wait = self.enterContext(patch.object(
            self.deployer, '_wait_for_refresh', create=True,
        ))
        self.cleanup = self.enterContext(patch.object(
            self.deployer, '_cleanup_dataset', create=True,
        ))

    def assert_blocked_without_operations(self, result):
        self.deploy.assert_not_called()
        self.validate.assert_not_called()
        self.wait.assert_not_called()
        self.cleanup.assert_not_called()
        self.assertEqual(self.client.mock_calls, [])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['phase'], 'blocked')
        self.assertIsNone(result['canary_id'])
        self.assertIsNone(result['production_id'])
        self.assertIsNone(result['validation'])
        self.assertIs(result['rolled_back'], False)
        self.assertIsInstance(result['error'], str)
        self.assertTrue(result['error'].strip(), 'blocked rollout must explain why')

    def test_default_arguments_fail_closed(self):
        self.wait.return_value = False
        result = self.deployer.deploy_rolling('Sales')
        self.assert_blocked_without_operations(result)

    def test_explicit_arguments_fail_closed(self):
        self.wait.return_value = True
        result = self.deployer.deploy_rolling(
            'Sales', dataset_name='Existing Dataset',
            max_wait_seconds=1, poll_interval=0,
        )
        self.assert_blocked_without_operations(result)


class TestDeployerTemporaryPackage(unittest.TestCase):
    """Deployments must not write or remove files outside their own temp directory."""

    def setUp(self):
        from powerbi_import.deploy.pbi_deployer import PBIWorkspaceDeployer

        self.temp_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_root.cleanup)
        root = Path(self.temp_root.name)
        self.temp_parent = root / 'temp'
        self.temp_parent.mkdir()
        self.project = root / 'Invoice'
        self.project.mkdir()

        # All potential paths used by the old implementation stay test-owned.
        self.collision = self.temp_parent / 'Invoice.pbix'
        self.collision.write_bytes(b'pre-existing collision')
        self.unrelated = self.temp_parent / 'unrelated.txt'
        self.unrelated.write_bytes(b'unrelated file')
        self.nested = self.temp_parent / 'nested'
        self.nested.mkdir()
        self.nested_collision = self.nested / 'Quarterly.pbix'
        self.nested_collision.write_bytes(b'nested collision')
        self.outside = root / 'outside'
        self.outside.mkdir()
        self.escaped_collision = self.outside / 'escaped.pbix'
        self.escaped_collision.write_bytes(b'outside collision')

        tempdir_patch = patch(
            'powerbi_import.deploy.pbi_deployer.tempfile.gettempdir',
            return_value=str(self.temp_parent),
        )
        tempdir_patch.start()
        self.addCleanup(tempdir_patch.stop)

        self.packager_patch = patch(
            'powerbi_import.deploy.pbix_packager.PBIXPackager',
        )
        packager_class = self.packager_patch.start()
        self.addCleanup(self.packager_patch.stop)
        self.packager_class = packager_class
        self.packager = packager_class.return_value
        self.package_paths = []
        self.uploads = []
        self.package_error = False
        self.upload_error = False
        self.packager.package.side_effect = self._package

        self.client = Mock()
        self.client.import_pbix.side_effect = self._upload
        self.client.get_import_status.return_value = {
            'importState': 'Succeeded',
            'datasets': [{'id': 'dataset-id'}],
        }
        self.deployer = PBIWorkspaceDeployer('workspace-id', client=self.client)

    def _package(self, project_dir, output_path):
        path = Path(output_path)
        self.package_paths.append(path)
        path.write_bytes(b'package contents')
        # A partial sidecar also belongs to this deployment's temporary directory.
        Path(str(path) + '.partial').write_bytes(b'partial')
        if self.package_error:
            raise RuntimeError('simulated packaging error')
        return str(path)

    def _upload(self, **kwargs):
        path = Path(kwargs['pbix_path'])
        sidecar = Path(str(path) + '.partial')
        self.uploads.append((
            kwargs,
            path.read_bytes() if path.is_file() else None,
            sidecar.read_bytes() if sidecar.is_file() else None,
        ))
        if self.upload_error:
            raise RuntimeError('simulated upload error')
        return {'id': 'import-id'}

    def assert_unrelated_files_preserved(self):
        self.assertTrue(self.collision.is_file(), 'pre-existing collision was deleted')
        self.assertEqual(self.collision.read_bytes(), b'pre-existing collision')
        self.assertEqual(self.unrelated.read_bytes(), b'unrelated file')
        self.assertTrue(self.nested_collision.is_file(), 'nested collision was deleted')
        self.assertEqual(self.nested_collision.read_bytes(), b'nested collision')
        self.assertTrue(self.escaped_collision.is_file(), 'outside collision was deleted')
        self.assertEqual(self.escaped_collision.read_bytes(), b'outside collision')
        self.assertEqual(
            {path.name for path in self.temp_parent.iterdir()},
            {'Invoice.pbix', 'unrelated.txt', 'nested'},
        )
        self.assertEqual(
            {path.name for path in self.nested.iterdir()}, {'Quarterly.pbix'},
        )

    def assert_package_cleaned(self, path):
        self.assertFalse(path.exists(), 'package must be removed after upload/failure')
        self.assertFalse(
            Path(str(path) + '.partial').exists(), 'partial artifact must be removed',
        )
        self.assertEqual(path.parent.parent, self.temp_parent)
        self.assertFalse(path.parent.exists(), 'owned temp directory must be removed')

    def assert_successful_deployments(self, dataset_names, results):
        self.assertEqual(
            [result.status for result in results], ['succeeded'] * len(dataset_names),
        )
        self.assertEqual([result.project_name for result in results], list(dataset_names))
        self.assertEqual(len(self.package_paths), len(dataset_names))
        self.assertEqual(len(self.uploads), len(dataset_names))
        self.assert_unrelated_files_preserved()
        self.assertEqual(len({path.parent for path in self.package_paths}), len(dataset_names))
        self.assertEqual(len({path.name for path in self.package_paths}), 1)
        self.assertRegex(self.package_paths[0].name, r'^[A-Za-z0-9][A-Za-z0-9._-]*\.pbix$')

        expected_client_calls = []
        for name, path, (kwargs, contents, sidecar) in zip(
            dataset_names, self.package_paths, self.uploads,
        ):
            self.assertEqual(contents, b'package contents')
            self.assertEqual(sidecar, b'partial')
            self.assertEqual(kwargs, {
                'workspace_id': 'workspace-id',
                'pbix_path': str(path),
                'dataset_name': name,
                'overwrite': True,
            })
            self.assert_package_cleaned(path)
            expected_client_calls.extend([
                call.import_pbix(**kwargs),
                call.get_import_status('workspace-id', 'import-id'),
            ])
        self.assertEqual(self.client.mock_calls, expected_client_calls)
        self.assertEqual(self.packager.package.call_count, len(dataset_names))
        for package_call, path in zip(self.packager.package.call_args_list, self.package_paths):
            self.assertEqual(package_call, call(str(self.project), str(path)))

    def test_collision_is_preserved_across_unique_temporary_packages(self):
        results = [self.deployer.deploy_project(str(self.project)) for _ in range(2)]
        self.assert_successful_deployments(('Invoice', 'Invoice'), results)

    def test_separator_containing_dataset_names_never_become_paths(self):
        dataset_names = ('ordinary', '../outside/escaped', 'nested/Quarterly')
        results = [
            self.deployer.deploy_project(str(self.project), dataset_name=name)
            for name in dataset_names
        ]
        self.assert_successful_deployments(dataset_names, results)

    def test_packaging_failure_cleans_partial_artifacts_without_client_calls(self):
        self.package_error = True
        result = self.deployer.deploy_project(str(self.project), refresh=True)

        self.assertEqual(result.status, 'failed')
        self.assertIn('Packaging failed: simulated packaging error', result.error)
        self.assertEqual(self.client.mock_calls, [])
        self.assertEqual(self.packager.package.call_count, 1)
        self.assertEqual(len(self.package_paths), 1)
        self.assert_package_cleaned(self.package_paths[0])
        self.assert_unrelated_files_preserved()

    def test_upload_failure_cleans_artifacts_without_poll_or_refresh(self):
        self.upload_error = True
        result = self.deployer.deploy_project(str(self.project), refresh=True)

        self.assertEqual(result.status, 'failed')
        self.assertIn('Upload failed: simulated upload error', result.error)
        self.assertEqual(self.packager.package.call_count, 1)
        self.assertEqual(len(self.package_paths), 1)
        self.assertEqual(len(self.uploads), 1)
        kwargs, contents, sidecar = self.uploads[0]
        self.assertEqual(contents, b'package contents')
        self.assertEqual(sidecar, b'partial')
        self.assertEqual(kwargs, {
            'workspace_id': 'workspace-id',
            'pbix_path': str(self.package_paths[0]),
            'dataset_name': 'Invoice',
            'overwrite': True,
        })
        self.assertEqual(self.client.mock_calls, [call.import_pbix(**kwargs)])
        self.assert_package_cleaned(self.package_paths[0])
        self.assert_unrelated_files_preserved()

    def test_temporary_directory_creation_failure_makes_no_remote_calls(self):
        with patch(
            'powerbi_import.deploy.pbi_deployer.tempfile.TemporaryDirectory',
            side_effect=OSError('simulated directory creation error'),
        ) as temp_factory:
            result = self.deployer.deploy_project(str(self.project), refresh=True)

        temp_factory.assert_called_once()
        self.assertEqual(result.status, 'failed')
        self.assertIn('simulated directory creation error', result.error)
        self.assertIsNone(result.import_id)
        self.packager_class.assert_not_called()
        self.assertEqual(self.client.mock_calls, [])
        self.assert_unrelated_files_preserved()

    def test_temporary_directory_enter_failure_makes_no_remote_calls(self):
        context = MagicMock()
        context.__enter__.side_effect = OSError('simulated directory enter error')
        with patch(
            'powerbi_import.deploy.pbi_deployer.tempfile.TemporaryDirectory',
            return_value=context,
        ) as temp_factory:
            result = self.deployer.deploy_project(str(self.project), refresh=True)

        temp_factory.assert_called_once()
        context.__enter__.assert_called_once_with()
        context.__exit__.assert_not_called()
        self.assertEqual(result.status, 'failed')
        self.assertIn('simulated directory enter error', result.error)
        self.assertIsNone(result.import_id)
        self.packager_class.assert_not_called()
        self.assertEqual(self.client.mock_calls, [])
        self.assert_unrelated_files_preserved()

    def _cleanup_failing_context(self):
        owned_dir = self.temp_parent / 'owned'
        owned_dir.mkdir()
        context = MagicMock()
        context.__enter__.return_value = str(owned_dir)
        context.__exit__.side_effect = OSError('simulated directory cleanup error')
        return context

    def test_cleanup_failure_preserves_started_import_without_poll_or_refresh(self):
        context = self._cleanup_failing_context()
        with patch(
            'powerbi_import.deploy.pbi_deployer.tempfile.TemporaryDirectory',
            return_value=context,
        ) as temp_factory:
            result = self.deployer.deploy_project(str(self.project), refresh=True)

        temp_factory.assert_called_once()
        context.__enter__.assert_called_once_with()
        self.assertEqual(context.__exit__.call_count, 1)
        self.assertEqual(result.status, 'failed')
        self.assertIn('simulated directory cleanup error', result.error)
        self.assertEqual(result.import_id, 'import-id')
        self.assertEqual(len(self.uploads), 1)
        kwargs, contents, sidecar = self.uploads[0]
        self.assertEqual(contents, b'package contents')
        self.assertEqual(sidecar, b'partial')
        self.assertEqual(self.client.mock_calls, [call.import_pbix(**kwargs)])
        self.packager.package.assert_called_once()

    def test_cleanup_failure_after_upload_failure_surfaces_both_errors(self):
        self.upload_error = True
        context = self._cleanup_failing_context()
        with patch(
            'powerbi_import.deploy.pbi_deployer.tempfile.TemporaryDirectory',
            return_value=context,
        ) as temp_factory:
            result = self.deployer.deploy_project(str(self.project), refresh=True)

        temp_factory.assert_called_once()
        context.__enter__.assert_called_once_with()
        self.assertEqual(context.__exit__.call_count, 1)
        self.assertEqual(result.status, 'failed')
        self.assertIn('simulated upload error', result.error)
        self.assertIn('simulated directory cleanup error', result.error)
        self.assertIsNone(result.import_id)
        self.assertEqual(len(self.uploads), 1)
        kwargs, contents, sidecar = self.uploads[0]
        self.assertEqual(contents, b'package contents')
        self.assertEqual(sidecar, b'partial')
        self.assertEqual(self.client.mock_calls, [call.import_pbix(**kwargs)])
        self.packager.package.assert_called_once()

    def test_cleanup_failure_after_packaging_failure_surfaces_both_errors(self):
        self.package_error = True
        context = self._cleanup_failing_context()
        with patch(
            'powerbi_import.deploy.pbi_deployer.tempfile.TemporaryDirectory',
            return_value=context,
        ) as temp_factory:
            result = self.deployer.deploy_project(str(self.project), refresh=True)

        temp_factory.assert_called_once()
        context.__enter__.assert_called_once_with()
        self.assertEqual(context.__exit__.call_count, 1)
        self.assertEqual(result.status, 'failed')
        self.assertIn('simulated packaging error', result.error)
        self.assertIn('simulated directory cleanup error', result.error)
        self.assertIsNone(result.import_id)
        self.packager.package.assert_called_once()
        self.assertEqual(self.client.mock_calls, [])


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
