"""Offline behavioral tests for optional AI advisory and pattern marketplace."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from powerbi_import.llm_client import (
    LLMClient,
    estimate_tokens,
    generate_llm_report,
    refine_approximated_measures,
)
from powerbi_import.marketplace import PatternRegistry


def _response(payload):
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps(payload).encode('utf-8')
    return response


def _pattern(name, version='1.0.0', category='dax_recipe', tags=None, payload=None):
    return {
        'metadata': {
            'name': name, 'version': version, 'author': 'Synthetic',
            'description': 'Local test pattern', 'tags': tags or [], 'category': category,
        },
        'payload': payload or {},
    }


class TestLLMClient(unittest.TestCase):
    def test_dry_run_returns_estimate_without_opening_a_network_connection(self):
        client = LLMClient(api_key='synthetic-key', dry_run=True)
        with patch('powerbi_import.llm_client.urlopen') as urlopen:
            result = client.call('system prompt', 'user prompt')
        urlopen.assert_not_called()
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['input_tokens'], estimate_tokens('system promptuser prompt'))
        self.assertEqual(client.calls_remaining, 99)
        self.assertEqual(client.total_cost, 0)

    def test_openai_request_body_usage_and_cost_are_accounted(self):
        payload = {'choices': [{'message': {'content': '  SUM(Sales[Amount])  '}}],
                   'usage': {'prompt_tokens': 1000, 'completion_tokens': 500}}
        client = LLMClient(api_key='local-key')
        with patch('powerbi_import.llm_client.urlopen', return_value=_response(payload)) as urlopen:
            result = client.call('system', 'user')
        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode('utf-8'))
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer local-key')
        self.assertEqual([message['role'] for message in body['messages']], ['system', 'user'])
        self.assertEqual(result['text'], 'SUM(Sales[Amount])')
        self.assertEqual(result['cost'], 0.0075)
        self.assertEqual(client.total_cost, 0.0075)
        self.assertEqual(client.calls_remaining, 99)

    def test_anthropic_request_and_usage_use_provider_specific_contract(self):
        payload = {'content': [{'type': 'text', 'text': '  DIVIDE(A, B)  '}],
                   'usage': {'input_tokens': 200, 'output_tokens': 50}}
        client = LLMClient(provider='anthropic', api_key='local-key')
        with patch('powerbi_import.llm_client.urlopen', return_value=_response(payload)) as urlopen:
            result = client.call('system text', 'user text')
        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode('utf-8'))
        self.assertEqual(request.full_url, 'https://api.anthropic.com/v1/messages')
        self.assertEqual(request.get_header('X-api-key'), 'local-key')
        self.assertEqual(request.get_header('Anthropic-version'), '2023-06-01')
        self.assertEqual(body['system'], 'system text')
        self.assertEqual(body['messages'][0]['content'], 'user text')
        self.assertEqual((result['input_tokens'], result['output_tokens']), (200, 50))
        self.assertEqual(result['text'], 'DIVIDE(A, B)')

    def test_azure_openai_url_auth_and_model_override_are_applied(self):
        client = LLMClient(provider='azure_openai', api_key='local-key', model='deployment-x',
                           endpoint='https://example.invalid/custom/')
        with patch('powerbi_import.llm_client.urlopen', return_value=_response(
                {'choices': [{'message': {'content': '1'}}], 'usage': {}})) as urlopen:
            result = client.call('system', 'user')
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url,
                         'https://example.invalid/custom/openai/deployments/deployment-x/chat/completions?api-version=2024-02-01')
        self.assertEqual(request.get_header('Api-key'), 'local-key')
        self.assertEqual(json.loads(request.data.decode('utf-8'))['model'], 'deployment-x')
        self.assertEqual(result['text'], '1')

    def test_rate_limit_retries_once_using_retry_after_then_succeeds(self):
        throttled = HTTPError('https://api.openai.com', 429, 'busy', {'Retry-After': '4'}, None)
        client = LLMClient(api_key='local-key', max_retries=1)
        with patch('powerbi_import.llm_client.urlopen', side_effect=[throttled, _response(
                {'choices': [{'message': {'content': 'ok'}}], 'usage': {'prompt_tokens': 3, 'completion_tokens': 2}})]) as urlopen, \
             patch('powerbi_import.llm_client.time.sleep') as sleep:
            result = client.call('s', 'u')
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(4)
        self.assertEqual(result['text'], 'ok')
        self.assertEqual(client.calls_remaining, 99)

    def test_non_retryable_http_and_url_failures_return_errors_without_consuming_call(self):
        client = LLMClient(api_key='local-key', max_retries=3)
        forbidden = HTTPError('https://api.openai.com', 403, 'denied', {}, None)
        with patch('powerbi_import.llm_client.urlopen', side_effect=forbidden) as urlopen, \
             patch('powerbi_import.llm_client.time.sleep') as sleep:
            http_result = client.call('s', 'u')
        self.assertEqual(http_result['error'], 'http_403')
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

        with patch('powerbi_import.llm_client.urlopen', side_effect=URLError('offline')):
            url_result = client.call('s', 'u')
        self.assertIn('offline', url_result['error'])
        self.assertEqual(client.calls_remaining, 100)

    def test_exhausted_rate_limit_does_not_exceed_retry_budget(self):
        throttled = HTTPError('https://api.openai.com', 429, 'busy', {'Retry-After': '0'}, None)
        client = LLMClient(api_key='local-key', max_retries=2)
        with patch('powerbi_import.llm_client.urlopen', side_effect=throttled) as urlopen, \
             patch('powerbi_import.llm_client.time.sleep') as sleep:
            result = client.call('s', 'u')
        self.assertEqual(result['error'], 'http_429')
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_call_limit_blocks_provider_and_returns_explicit_status(self):
        client = LLMClient(api_key='local-key', max_calls=1, dry_run=True)
        self.assertTrue(client.call('s', 'u')['dry_run'])
        with patch('powerbi_import.llm_client.urlopen') as urlopen:
            blocked = client.call('s', 'u')
        urlopen.assert_not_called()
        self.assertEqual(blocked['error'], 'call_limit_reached')
        self.assertEqual(client.calls_remaining, 0)


class TestLLMRefinement(unittest.TestCase):
    def test_refinement_skips_exact_dax_and_strips_fenced_response_with_schema_context(self):
        client = MagicMock()
        client.calls_remaining = 1
        client.call.return_value = {'text': '```dax\nSUM(Orders[Total])\n```',
                                    'input_tokens': 80, 'output_tokens': 12, 'cost': 0.001}
        results = refine_approximated_measures(client, [
            {'name': 'Exact', 'expression': 'SUM(Orders[Total])'},
            {'name': 'Approx', 'expression': 'SUM(Orders[Total]) /* approximate */',
             'annotations': [{'name': 'MigrationNote', 'value': 'Approximate aggregation'}]},
        ], tables=[{'name': 'Orders', 'columns': [{'name': 'Total', 'dataType': 'decimal'}]}],
            source_formulas={'Approx': '=Sum([Total])'})
        self.assertEqual([result['status'] for result in results], ['skipped', 'refined'])
        self.assertEqual(results[1]['refined_dax'], 'SUM(Orders[Total])')
        self.assertEqual(results[1]['confidence'], 0.85)
        self.assertEqual(results[1]['tokens'], {'input': 80, 'output': 12})
        prompt = client.call.call_args.args[1]
        self.assertIn("'Orders':", prompt)
        self.assertIn('[Total] decimal', prompt)
        self.assertIn('=Sum([Total])', prompt)

    def test_refinement_handles_unchanged_empty_and_provider_error_responses(self):
        client = MagicMock()
        client.calls_remaining = 3
        client.call.side_effect = [
            {'text': 'Current DAX', 'input_tokens': 10, 'output_tokens': 5, 'cost': 0.0},
            {'text': '  ', 'input_tokens': 10, 'output_tokens': 0, 'cost': 0.0},
            {'text': '', 'input_tokens': 0, 'output_tokens': 0, 'cost': 0,
             'error': 'http_500'},
        ]
        measures = [
            {'name': name, 'expression': 'Current DAX',
             'migration_note': 'approximate conversion'}
            for name in ('Same', 'Empty', 'Failed')
        ]
        results = refine_approximated_measures(client, measures)
        self.assertEqual([result['status'] for result in results], ['unchanged', 'error', 'error'])
        self.assertEqual([result['confidence'] for result in results], [1.0, 0.0, 0])
        self.assertEqual(results[1]['refined_dax'], 'Current DAX')
        self.assertEqual(results[2]['error'], 'http_500')

    def test_refinement_reports_call_limit_and_schema_context_without_network(self):
        client = LLMClient(api_key='local-key', max_calls=0)
        with patch('powerbi_import.llm_client.urlopen') as urlopen:
            result = refine_approximated_measures(client, [
                {'name': 'Ratio', 'expression': 'DIVIDE(A,B)', 'migration_note': 'approximate'}
            ], tables=[{'name': 'T', 'columns': ['A', 'B']}])
        urlopen.assert_not_called()
        self.assertEqual(result[0]['status'], 'error')
        self.assertEqual(result[0]['error'], 'call_limit_reached')
        self.assertEqual(client.calls_remaining, 0)

    def test_llm_report_writes_local_json_summary_and_measure_results(self):
        client = LLMClient(provider='openai', model='offline-model', dry_run=True)
        results = refine_approximated_measures(client, [
            {'name': 'Ratio', 'expression': 'DIVIDE(A,B)', 'migration_note': 'approximate'}
        ])
        with tempfile.TemporaryDirectory() as temporary:
            report = generate_llm_report(client, results, temporary)
            saved = json.loads((Path(temporary) / 'llm_refinement_report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['provider'], 'openai')
        self.assertEqual(report['model'], 'offline-model')
        self.assertTrue(report['dry_run'])
        self.assertEqual(saved['summary']['total_measures'], 1)
        self.assertEqual(saved['summary']['api_calls'], 1)
        self.assertEqual(saved['measures'][0]['status'], 'refined')


class TestPatternRegistry(unittest.TestCase):
    def test_local_catalogue_loading_search_latest_version_and_export_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entries = [
                _pattern('revenue', '1.2.0', tags=['Finance']),
                _pattern('revenue', '1.10.0', tags=['finance']),
                _pattern('visual-bars', '2.0', 'visual_mapping', ['charts']),
            ]
            for index, entry in enumerate(entries):
                (root / f'{index}.json').write_text(json.dumps(entry), encoding='utf-8')
            registry = PatternRegistry(str(root))
            self.assertEqual(registry.load(), 3)
            self.assertEqual(registry.count, 2)
            self.assertEqual(registry.get('revenue').version, '1.10.0')
            self.assertEqual(registry.get('revenue', '1.2.0').version, '1.2.0')
            self.assertEqual([pattern.name for pattern in registry.search(tags=['FINANCE'])], ['revenue'])
            self.assertEqual([pattern.name for pattern in registry.search(category='visual_mapping')], ['visual-bars'])
            exported = root / 'export' / 'patterns.json'
            self.assertEqual(registry.export(str(exported)), 3)
            self.assertEqual(len(json.loads(exported.read_text(encoding='utf-8'))), 3)

    def test_invalid_json_and_missing_metadata_are_ignored_without_losing_valid_patterns(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'broken.json').write_text('{', encoding='utf-8')
            (root / 'nameless.json').write_text(json.dumps({'metadata': {}, 'payload': {}}), encoding='utf-8')
            (root / 'valid.json').write_text(json.dumps(_pattern('valid')), encoding='utf-8')
            registry = PatternRegistry(str(root))
            self.assertEqual(registry.load(), 1)
            self.assertEqual(registry.count, 1)
            self.assertIsNone(registry.get('nameless'))
            self.assertEqual(registry.get('valid').name, 'valid')

    def test_search_filters_name_category_and_tags_case_insensitively(self):
        registry = PatternRegistry()
        registry.register(_pattern('revenue-ytd', tags=['Finance']))
        registry.register(_pattern('margin', tags=['finance', 'sales']))
        registry.register(_pattern('bar-chart', category='visual_mapping', tags=['Charts']))
        found = registry.search(tags=['SALES'], name_pattern='mar', category='dax_recipe')
        self.assertEqual([pattern.name for pattern in found], ['margin'])
        self.assertEqual(registry.to_dict()['pattern_count'], 3)
        self.assertEqual(len(registry.list_all()), 3)

    def test_dax_recipes_replace_matching_formulas_and_inject_new_measures(self):
        registry = PatternRegistry()
        registry.register(_pattern('safe-divide', payload={
            'match': r'\[Profit\] / \[Revenue\]',
            'replacement': 'DIVIDE([Profit], [Revenue])',
        }))
        registry.register(_pattern('margin-inject', payload={
            'inject': {'name': 'Margin %', 'dax': 'DIVIDE([Profit], [Revenue])'},
        }))
        measures = {'Margin': '[Profit] / [Revenue]', 'Other': 'SUM(Orders[Id])'}
        changes = registry.apply_dax_recipes(measures)
        self.assertEqual(measures['Margin'], 'DIVIDE([Profit], [Revenue])')
        self.assertEqual(measures['Margin %'], 'DIVIDE([Profit], [Revenue])')
        self.assertEqual(changes['Margin']['action'], 'replaced')
        self.assertEqual(changes['Margin %']['action'], 'injected')
        self.assertNotIn('Other', changes)

    def test_visual_overrides_normalize_chart_keys_and_update_existing_mapping(self):
        registry = PatternRegistry()
        registry.register(_pattern('custom-bars', category='visual_mapping', payload={
            'overrides': {'BAR': 'clusteredBarChart', 'Heatmap': 'matrix'},
        }))
        mapping = {'bar': 'tableEx'}
        count = registry.apply_visual_overrides(mapping)
        self.assertEqual(count, 2)
        self.assertEqual(mapping, {'bar': 'clusteredBarChart', 'heatmap': 'matrix'})


if __name__ == '__main__':
    unittest.main()