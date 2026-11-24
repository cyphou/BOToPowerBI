"""Behavioral contracts for generated semantic-model TMDL."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from powerbi_import.tmdl_generator import (
    _build_table,
    _collect_semantic_context,
    _create_parameter_tables,
    _create_calculation_groups,
    _create_quick_table_calc_measures,
    _dax_to_m_expression,
    _infer_cross_table_relationships,
    _process_sets_groups_bins,
    _self_heal_model,
    generate_tmdl,
)
from powerbi_import.recovery_report import RecoveryReport


class TestTmdlGeneratorOutput(unittest.TestCase):
    def test_rls_roles_preserve_unicode_filters_and_fail_closed_for_empty_mappings(self):
        datasource = {
            'name': 'Source',
            'tables': [{'name': 'Ventes été', 'columns': [
                {'name': 'Région', 'datatype': 'string'},
            ]}],
        }
        extra_objects = {'user_filters': [
            {'type': 'user_filter', 'name': 'Équipe régionale', 'column': 'Région',
             'user_mappings': [
                 {'user': 'ana@example.invalid', 'value': 'Montréal'},
                 {'user': 'ana@example.invalid', 'value': 'Québec'},
             ]},
            {'type': 'user_filter', 'name': 'Empty access', 'column': 'Région',
             'user_mappings': [{'user': '', 'value': 'ignored'}]},
        ]}

        with tempfile.TemporaryDirectory() as temporary:
            stats = generate_tmdl([datasource], 'Sales', extra_objects, temporary)
            definition = Path(temporary) / 'definition'
            roles = (definition / 'roles.tmdl').read_text(encoding='utf-8')
            model = (definition / 'model.tmdl').read_text(encoding='utf-8')

        self.assertEqual(stats['roles'], 2)
        self.assertIn("role 'Équipe régionale'", roles)
        self.assertIn("tablePermission 'Ventes été'", roles)
        self.assertIn(
            'filterExpression = (USERPRINCIPALNAME() = "ana@example.invalid" && '
            '[Région] IN {"Montréal", "Québec"})',
            roles,
        )
        self.assertIn('filterExpression = FALSE()', roles)
        self.assertIn("ref role 'Équipe régionale'", model)
        self.assertIn("ref role 'Empty access'", model)

    def test_hierarchy_and_non_default_culture_are_written_as_real_tmdl_artifacts(self):
        datasource = {
            'name': 'Source',
            'tables': [{'name': 'Orders', 'columns': [
                {'name': 'Year', 'datatype': 'integer'},
                {'name': 'Région', 'datatype': 'string'},
            ]}],
        }
        extra_objects = {'hierarchies': [{
            'name': '年度 / Geography',
            'levels': ['Year', 'Région', 'Missing level'],
        }]}

        with tempfile.TemporaryDirectory() as temporary:
            generate_tmdl([datasource], 'Sales', extra_objects, temporary, culture='fr-FR')
            definition = Path(temporary) / 'definition'
            table = (definition / 'tables' / 'Orders.tmdl').read_text(encoding='utf-8')
            model = (definition / 'model.tmdl').read_text(encoding='utf-8')
            culture = (definition / 'cultures' / 'fr-FR.tmdl').read_text(encoding='utf-8')

        self.assertIn("hierarchy '年度 / Geography'", table)
        self.assertIn('level Year', table)
        self.assertIn('column Year', table)
        self.assertIn("level 'Région'", table)
        self.assertNotIn('Missing level', table)
        self.assertIn("ref culture 'fr-FR'", model)
        self.assertIn("culture 'fr-FR'", culture)

    def test_calculation_and_field_parameters_write_expected_artifacts(self):
        datasource = {
            'name': 'Source',
            'tables': [{'name': 'Sales', 'columns': [
                {'name': 'Region', 'datatype': 'string'},
                {'name': 'Category', 'datatype': 'string'},
                {'name': 'Amount', 'datatype': 'real'},
            ]}],
            'calculations': [
                {'name': 'Revenue', 'caption': 'Revenue', 'formula': 'SUM([Amount])',
                 'role': 'measure'},
                {'name': 'Cost', 'caption': 'Cost', 'formula': 'SUM([Amount])',
                 'role': 'measure'},
            ],
        }
        extra_objects = {'parameters': [
            {'caption': 'View as', 'datatype': 'string', 'domain_type': 'list',
             'allowable_values': [{'value': 'Revenue'}, {'value': 'Cost'}]},
            {'caption': 'Choose field', 'datatype': 'string', 'domain_type': 'list',
             'allowable_values': [{'value': 'Region'}, {'value': 'Category'}]},
        ]}

        with tempfile.TemporaryDirectory() as temporary:
            stats = generate_tmdl([datasource], 'Sales', extra_objects, temporary)
            tables = Path(temporary) / 'definition' / 'tables'
            calc_group = (tables / 'View as CalcGroup.tmdl').read_text(encoding='utf-8')
            field_parameter = (tables / 'Choose field FieldParam.tmdl').read_text(encoding='utf-8')
            model = (Path(temporary) / 'definition' / 'model.tmdl').read_text(encoding='utf-8')

        self.assertIn('calculationGroup', calc_group)
        self.assertIn('calculationItem Revenue', calc_group)
        self.assertIn('calculationItem Cost', calc_group)
        self.assertIn('CALCULATE(SELECTEDMEASURE())', calc_group)
        self.assertIn("NAMEOF('Sales'[Region])", field_parameter)
        self.assertIn("NAMEOF('Sales'[Category])", field_parameter)
        self.assertIn('discourageImplicitMeasures', model)
        self.assertGreaterEqual(stats['tables'], 4)

    def test_relationship_output_drops_invalid_edges_and_aligns_key_types(self):
        datasource = {
            'name': 'Source',
            'tables': [
                {'name': 'Orders', 'columns': [
                    {'name': 'CustomerKey', 'datatype': 'string'},
                    {'name': 'Amount', 'datatype': 'real'},
                ]},
                {'name': 'Customers', 'columns': [
                    {'name': 'CustomerKey', 'datatype': 'integer'},
                    {'name': 'CustomerName', 'datatype': 'string'},
                ]},
            ],
            'relationships': [
                {'left': {'table': 'Orders', 'column': 'CustomerKey'},
                 'right': {'table': 'Customers', 'column': 'CustomerKey'}, 'type': 'left'},
                {'left': {'table': 'Orders', 'column': 'Missing'},
                 'right': {'table': 'Customers', 'column': 'CustomerKey'}, 'type': 'left'},
                {'left': {'table': 'Orders', 'column': 'Amount'},
                 'right': {'table': 'Orders', 'column': 'CustomerKey'}, 'type': 'left'},
            ],
        }

        with tempfile.TemporaryDirectory() as temporary:
            stats = generate_tmdl([datasource], 'Sales', {}, temporary)
            definition = Path(temporary) / 'definition'
            relationships = (definition / 'relationships.tmdl').read_text(encoding='utf-8')
            customers = (definition / 'tables' / 'Customers.tmdl').read_text(encoding='utf-8')

        self.assertEqual(stats['relationships'], 1)
        self.assertIn('fromColumn: Orders.CustomerKey', relationships)
        self.assertIn('toColumn: Customers.CustomerKey', relationships)
        self.assertNotIn('Missing', relationships)
        self.assertIn('column CustomerKey', customers)
        self.assertIn('dataType: string', customers)

    def test_sets_groups_and_bins_add_partition_columns_with_unicode_metadata(self):
        model = {'model': {'tables': [{
            'name': 'Commandes',
            'columns': [
                {'name': 'Montant', 'dataType': 'Double'},
                {'name': 'Catégorie', 'dataType': 'String'},
            ],
            'partitions': [{'source': {'type': 'm', 'expression': 'let\n    Source = Input\nin\n    Source'}}],
        }]}}
        extras = {
            'sets': [{'name': 'Positif', 'formula': 'IF([Montant] > 0, TRUE(), FALSE())'}],
            'groups': [{'name': 'Segment', 'source_field': 'Catégorie',
                        'members': {'Élevé': ['A', 'B']}}],
            'bins': [{'name': 'Tranche', 'source_field': 'Montant', 'size': 25}],
        }

        _process_sets_groups_bins(model, extras, 'Commandes',
                                  {'Montant': 'Commandes', 'Catégorie': 'Commandes'})

        table = model['model']['tables'][0]
        columns = {column['name']: column for column in table['columns']}
        expression = table['partitions'][0]['source']['expression']
        self.assertEqual(columns['Positif']['dataType'], 'Boolean')
        self.assertEqual(columns['Positif']['displayFolder'], 'Sets')
        self.assertEqual(columns['Segment']['displayFolder'], 'Groups')
        self.assertEqual(columns['Tranche']['displayFolder'], 'Bins')
        self.assertIn('Table.AddColumn', expression)
        self.assertIn('Positif', expression)
        self.assertIn('Élevé', expression)
        self.assertIn('Number.RoundDown', expression)

    def test_combined_group_resolves_date_parts_and_unicode_column_names(self):
        model = {'model': {'tables': [{
            'name': 'Orders',
            'columns': [{'name': 'Order Date'}, {'name': 'Région'}],
            'partitions': [{'source': {'type': 'm', 'expression': 'let\n    Source = Input\nin\n    Source'}}],
        }]}}
        extras = {'groups': [{
            'name': 'Période (YEAR(Order Date),Région)',
            'group_type': 'combined',
            'source_fields': ['yr:Order Date', 'Région'],
        }]}

        _process_sets_groups_bins(model, extras, 'Orders',
                                  {'Order Date': 'Orders', 'Région': 'Orders'})

        table = model['model']['tables'][0]
        generated = next(column for column in table['columns']
                         if column['name'] == 'Période (YEAR(Order Date),Région)')
        expression = table['partitions'][0]['source']['expression']
        self.assertEqual(generated['sourceColumn'], generated['name'])
        self.assertIn('Date.Year([#"Order Date"])', expression)
        self.assertIn('[#"Région"]', expression)
        self.assertIn(' & " | " & ', expression)

    def test_dax_to_m_translation_handles_nested_calls_quotes_and_rejects_cross_table_logic(self):
        translated = _dax_to_m_expression(
            'IF(\'Ventes été\'[Pays/Région] = "Québec", UPPER("été"), "autre")',
            'Ventes été',
        )

        self.assertEqual(
            translated,
            'if [#"Pays/Région"] = "Québec" then Text.Upper("été") else "autre"',
        )
        self.assertEqual(_dax_to_m_expression('DATEDIFF([Début], [Fin], DAY)'),
                         'Duration.Days([Fin] - [Début])')
        self.assertEqual(_dax_to_m_expression('[Catégorie] IN {"A", "B"}'),
                         'List.Contains({"A", "B"}, [Catégorie])')
        self.assertIsNone(_dax_to_m_expression("RELATED('Clients'[Nom])", 'Orders'))
        self.assertIsNone(_dax_to_m_expression("'Clients'[Nom]", 'Orders'))

    def test_quick_table_calculations_use_aggregations_and_deduplicate_measures(self):
        model = {'model': {'tables': [
            {'name': 'Orders', 'measures': [{
                'name': '% of Total Amount',
                'expression': "DIVIDE(SUM('Orders'[Amount]), CALCULATE(SUM('Orders'[Amount]), ALL('Orders')))",
            }]},
            {'name': 'Products', 'columns': [{'name': 'Profit'}]},
        ]}}
        worksheets = [{
            'fields': [
                {'name': 'Amount', 'table_calc': 'pcto', 'table_calc_agg': 'sum'},
                {'name': 'Amount', 'table_calc': 'pctd', 'table_calc_agg': 'sum'},
                {'name': 'Profit', 'table_calc': 'running_avg', 'table_calc_agg': 'avg'},
                {'name': 'Amount', 'table_calc': 'rank_dense', 'table_calc_agg': 'sum'},
                {'name': 'Amount', 'table_calc': 'diff', 'table_calc_agg': 'sum'},
                {'name': 'Amount', 'table_calc': 'pcto', 'table_calc_agg': 'sum'},
            ],
        }]

        _create_quick_table_calc_measures(
            model, worksheets, 'Orders', {'Amount': 'Orders', 'Profit': 'Products'})

        measures = {measure['name']: measure.get('expression', '')
                    for measure in model['model']['tables'][0]['measures']}
        self.assertEqual(len(measures), 5)
        self.assertIn("ALL('Orders')", measures['% of Total Amount'])
        self.assertIn("PREVIOUSDAY('Calendar'[Date])", measures['% Difference Amount'])
        self.assertIn("AVERAGE('Products'[Profit])", measures['Running Avg Profit'])
        self.assertIn(', DENSE)', measures['Rank Amount'])
        self.assertIn(' - CALCULATE(', measures['Difference Amount'])

    def test_parameter_tables_cover_ranges_aliases_database_and_scalar_defaults(self):
        model = {'model': {'tables': [{'name': 'Sales', 'measures': []}]}}
        parameters = [
            {'caption': 'Taille', 'datatype': 'integer', 'domain_type': 'range',
             'allowable_values': [{'type': 'range', 'min': '0', 'max': '100', 'step': '5'}]},
            {'caption': 'Priorité', 'datatype': 'integer', 'domain_type': 'list',
             'allowable_values': [{'value': '1', 'alias': 'Élevée'}, {'value': '2', 'alias': 'Basse'}]},
            {'caption': "Vue d'été", 'datatype': 'string', 'domain_type': 'database',
             'query': 'SELECT "été"', 'refresh_on_open': True},
            {'caption': 'Seuil', 'datatype': 'real', 'domain_type': 'any', 'value': '2.5'},
        ]

        _create_parameter_tables(model, parameters, 'Sales')

        tables = {table['name']: table for table in model['model']['tables']}
        self.assertEqual(tables['Taille']['partitions'][0]['source']['expression'],
                         'GENERATESERIES(0, 100, 5)')
        self.assertIn('Élevée', tables['Priorité']['partitions'][0]['source']['expression'])
        self.assertEqual(tables['Priorité']['columns'][1]['name'], 'Name')
        database = tables["Vue d'été"]
        self.assertIn('SELECT ""été""', database['partitions'][0]['source']['expression'])
        self.assertEqual(database['refreshPolicy'], {'type': 'automatic'})
        self.assertEqual(model['model']['tables'][0]['measures'][0]['expression'], '2.5')

    def test_cross_table_dax_reference_infers_best_matching_relationship(self):
        model = {'model': {
            'tables': [
                {'name': 'Orders', 'columns': [
                    {'name': 'CustomerKey'}, {'name': 'Amount'}, {'name': 'OrderDate'},
                ], 'measures': [{'name': 'Customer Name',
                                 'expression': "MAX('Customers'[CustomerKey])"}]},
                {'name': 'Customers', 'columns': [
                    {'name': 'CustomerKey'}, {'name': 'CustomerName'},
                ]},
            ],
            'relationships': [],
        }}

        _infer_cross_table_relationships(model)

        self.assertEqual(model['model']['relationships'], [{
            'name': 'inferred_Orders_Customers',
            'fromTable': 'Orders',
            'fromColumn': 'CustomerKey',
            'toTable': 'Customers',
            'toColumn': 'CustomerKey',
            'crossFilteringBehavior': 'oneDirection',
        }])

    def test_dax_to_m_supported_function_families_and_fail_closed_cases(self):
        cases = {
            'SWITCH([Status], "A", "Actif", "B", "Bloqué", "Autre")':
                'if [Status] = "A" then "Actif" else if [Status] = "B" then "Bloqué" else "Autre"',
            'FLOOR([Montant], 25)': 'Number.RoundDown([Montant] / 25) * 25',
            'ISBLANK([Valeur])': '([Valeur] = null)',
            'NOT([Actif] = FALSE())': 'not ([Actif] = false)',
            'LEFT([Nom], 2)': 'Text.Start([Nom], 2)',
            'MID([Nom], 2, 3)': 'Text.Middle([Nom], 2 - 1, 3)',
            'SUBSTITUTE([Nom], "a", "é")': 'Text.Replace([Nom], "a", "é")',
            'DATEDIFF([Début], [Fin], MONTH)':
                '(Date.Year([Fin])*12 + Date.Month([Fin])) - (Date.Year([Début])*12 + Date.Month([Début]))',
            'DATEDIFF([Début], [Fin], YEAR)': 'Date.Year([Fin]) - Date.Year([Début])',
            'DATE(2024, 2, 29)': '#date(2024, 2, 29)',
            "[État] IN {'Québec', 'Ontario'}": 'List.Contains({"Québec", "Ontario"}, [État])',
            '[Flag] && TRUE() || FALSE()': '[Flag]  and  true  or  false',
        }
        for dax, expected in cases.items():
            with self.subTest(dax=dax):
                self.assertEqual(_dax_to_m_expression(dax), expected)

        for unsupported in (
            'LOOKUPVALUE([Nom], [Id], [Id])',
            'CALCULATE(SUM([Montant]))',
            'DATEDIFF([Début], [Fin], WEEK)',
            'CONCATENATEX([Rows], [Name])',
            'SUBSTITUTE([Nom], "a", "é", 1)',
            'SUBSTITUTE([Nom], "a")',
        ):
            with self.subTest(unsupported=unsupported):
                self.assertIsNone(_dax_to_m_expression(unsupported))

    def test_semantic_context_preserves_datasource_routing_and_parameter_provenance(self):
        datasources = [
            {'name': 'Sales DS', 'connection': {'server': 'sales.example.invalid'},
             'tables': [{'name': 'Commandes', 'columns': [{'name': 'Montant'}]},
                        {'name': 'Lignes', 'columns': [{'name': 'Quantité'}]}],
             'calculations': [{'name': '[Net brut]', 'caption': 'Net', 'formula': 'SUM([Montant])',
                               'datasource_name': 'Sales DS'}],
             'm_query_overrides': {'Commandes': 'let Source = Csv.Document(\"orders\") in Source'}},
            {'name': 'Parameters', 'calculations': [
                {'name': '[Seuil brut]', 'caption': 'Seuil', 'formula': '25'}]},
            {'name': 'Sales DS copy', 'tables': [
                {'name': 'Commandes', 'columns': [{'name': 'Région'}]}]},
        ]
        extras = {
            'parameters': [{'name': '[Parameters].[Période]', 'caption': 'Période',
                            'datatype': 'string', 'value': 'été'}],
            'worksheets': [{'table_calcs': [{'field': 'Croissance',
                                             'compute_using': ['Région', 'Mois']}]}],
        }

        context = _collect_semantic_context(datasources, extras)

        self.assertEqual(context['main_table_name'], 'Commandes')
        self.assertEqual({col['name'] for col in context['best_tables']['Commandes'][0]['columns']},
                         {'Montant', 'Région'})
        self.assertEqual(context['m_query_overrides']['Commandes'],
                         'let Source = Csv.Document("orders") in Source')
        self.assertEqual(context['column_table_map']['Quantité'], 'Lignes')
        self.assertEqual(context['dax_context']['calc_map']['Net brut'], 'Net')
        self.assertEqual(context['dax_context']['param_map']['Période'], 'Période')
        self.assertEqual(context['dax_context']['param_values']['Période'], '"été"')
        self.assertEqual(context['dax_context']['compute_using_map']['Croissance'],
                         ['Région', 'Mois'])
        self.assertEqual(context['table_datasource_set']['Commandes'],
                         {'Sales DS', 'Sales DS copy'})

    def test_calculation_groups_require_valid_numeric_switch_mapping(self):
        model = {'model': {'tables': [
            {'name': 'Ventes', 'columns': [], 'measures': [{
                'name': 'Choix',
                'expression': 'SWITCH([Agrégation], 1, SUM([Montant]), 2.0, AVERAGE([Montant]), BLANK())',
            }]},
        ]}}
        parameters = [
            {'caption': 'Agrégation', 'datatype': 'integer', 'domain_type': 'list',
             'allowable_values': [{'value': '1', 'alias': 'Somme'},
                                  {'value': '2', 'alias': 'Moyenne'}]},
            {'caption': 'Non sûr', 'datatype': 'integer', 'domain_type': 'list',
             'allowable_values': [{'value': '1', 'alias': 'Un'},
                                  {'value': '3', 'alias': 'Trois'}]},
            {'caption': 'Sans alias', 'datatype': 'integer', 'domain_type': 'list',
             'allowable_values': [{'value': '1', 'alias': 'Un'}, {'value': '2'}]},
        ]

        _create_calculation_groups(model, parameters, 'Ventes')

        groups = [table for table in model['model']['tables']
                  if table.get('calculationGroup')]
        self.assertEqual([table['name'] for table in groups], ['Agrégation CalcGroup'])
        items = groups[0]['calculationGroup']['calculationItems']
        self.assertEqual([item['name'] for item in items], ['Somme', 'Moyenne'])
        self.assertEqual([item['ordinal'] for item in items], [0, 1])
        self.assertEqual(items[0]['expression'], 'CALCULATE(SUM([Montant]))')
        self.assertEqual(items[1]['expression'], 'CALCULATE(AVERAGE([Montant]))')

    def test_table_builder_emits_metadata_and_keeps_unsupported_calc_in_dax(self):
        table = {
            'name': 'Ventes été',
            '_source_workbooks': ['Nord'],
            '_merge_action': 'retained',
            'columns': [
                {'name': 'Région', 'datatype': 'string'},
                {'name': 'Région', 'datatype': 'string'},
                {'name': 'Montant', 'datatype': 'real'},
            ],
        }
        calculations = [
            {'name': '[Étiquette]', 'caption': 'Étiquette', 'formula': 'UPPER([Région])',
             'role': 'dimension', 'datatype': 'string'},
            {'name': '[Autre table]', 'caption': 'Autre table',
             'formula': "RELATED('Clients'[Nom])", 'role': 'dimension', 'datatype': 'string'},
            {'name': '[Total]', 'caption': 'Total', 'formula': 'SUM([Montant])',
             'role': 'measure', 'datatype': 'real', 'description': 'Somme vérifiée'},
        ]
        metadata = {'Région': {'hidden': True, 'description': 'Zone de vente'},
                    'Montant': {'default_format': '€#,##0.00'}}

        built = _build_table(
            table, {}, calculations, [],
            dax_context={'column_table_map': {'Région': 'Ventes été', 'Montant': 'Ventes été'}},
            col_metadata_map=metadata,
            m_query_override='let\n    Source = Input\nin\n    Source',
            model_mode='composite', composite_threshold=2,
        )

        self.assertEqual(built['name'], 'Ventes été')
        self.assertEqual([col['name'] for col in built['columns']],
                         ['Région', 'Région_1', 'Montant', 'Étiquette', 'Autre table'])
        self.assertTrue(built['columns'][0]['isHidden'])
        self.assertEqual(built['columns'][0]['description'], 'Zone de vente')
        self.assertIn('RELATED(', built['columns'][-1]['expression'])
        self.assertEqual(built['partitions'][0]['mode'], 'directQuery')
        self.assertIn('Table.AddColumn', built['partitions'][0]['source']['expression'])
        self.assertEqual(built['measures'][0]['description'], 'Somme vérifiée')
        self.assertEqual(built['_source_workbooks'], ['Nord'])
        self.assertEqual(built['_merge_action'], 'retained')

    def test_self_healing_marks_broken_measures_and_repairs_duplicate_or_orphan_tables(self):
        model = {'model': {
            'tables': [
                {'name': 'Orders', 'columns': [{'name': 'Id'}],
                 'measures': [{'name': 'Broken', 'expression': 'SUM([Missing])'}]},
                {'name': 'Orders', 'columns': [{'name': 'Amount'}], 'measures': []},
                {'name': '', 'columns': [], 'measures': [{'name': 'Orphan', 'expression': '1'}]},
                {'name': '   ', 'columns': [], 'measures': []},
            ],
            'relationships': [{'fromTable': 'Orders', 'fromColumn': 'Id',
                               'toTable': 'Orders', 'toColumn': 'Amount'}],
        }}

        with contextlib.redirect_stdout(io.StringIO()):
            repairs = _self_heal_model(model)

        tables = model['model']['tables']
        self.assertEqual(repairs, 5)
        self.assertEqual([table['name'] for table in tables], ['Orders', 'Orders_2'])
        self.assertTrue(tables[0]['measures'][0]['isHidden'])
        self.assertIn('MigrationNote', [item['name'] for item in tables[0]['measures'][0]['annotations']])
        self.assertEqual(tables[0]['measures'][1]['name'], 'Orphan')
        self.assertEqual(model['model']['relationships'][0]['fromTable'], 'Orders')
        self.assertEqual(model['model']['relationships'][0]['toTable'], 'Orders_2')

    def test_self_healing_drops_ambiguous_and_missing_duplicate_endpoints_with_recovery(self):
        cases = (
            ('ambiguous', [
                {'name': 'Orders', 'columns': [{'name': 'Id'}]},
                {'name': 'Orders', 'columns': [{'name': 'Id'}]},
                {'name': 'Customers', 'columns': [{'name': 'Id'}]},
            ], {'fromTable': 'Orders', 'fromColumn': 'Id',
                'toTable': 'Customers', 'toColumn': 'Id'}),
            ('missing', [
                {'name': 'Orders', 'columns': [{'name': 'Id'}]},
                {'name': 'Orders', 'columns': [{'name': 'Amount'}]},
            ], {'fromTable': 'Orders', 'fromColumn': 'Missing',
                'toTable': 'Orders', 'toColumn': 'Amount'}),
        )

        for reason, tables, relationship in cases:
            with self.subTest(reason=reason):
                model = {'model': {'tables': tables, 'relationships': [relationship]}}
                recovery = RecoveryReport(f'{reason}_endpoint')

                with contextlib.redirect_stdout(io.StringIO()):
                    repairs = _self_heal_model(model, recovery=recovery)

                self.assertEqual(repairs, 2)
                self.assertEqual(model['model']['relationships'], [])
                self.assertEqual([table['name'] for table in model['model']['tables']],
                                 ['Orders', 'Orders_2'] + (['Customers'] if reason == 'ambiguous' else []))
                self.assertEqual(recovery.get_summary()['by_type'],
                                 {'duplicate_table': 1, 'unresolved_endpoint': 1})
                unresolved = recovery.repairs[-1]
                self.assertEqual(unresolved['category'], 'relationship')
                self.assertEqual(unresolved['repair_type'], 'unresolved_endpoint')
                self.assertIn(f'({reason})', unresolved['description'])


if __name__ == '__main__':
    unittest.main()