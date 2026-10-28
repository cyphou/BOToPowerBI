"""MCP protocol, safe defaults, source assessment, and local write guards."""

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from powerbi_import.mcp_server import MigrationTools, _tool_catalogue, handle_request, serve


class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.tools = MigrationTools(self.root)

    def request(self, name, arguments):
        return handle_request({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                               'params': {'name': name, 'arguments': arguments}}, self.tools)

    def test_catalogue_contract(self):
        catalogue = _tool_catalogue()
        self.assertEqual([tool['name'] for tool in catalogue],
                         ['inventory', 'assess', 'migrate', 'shared_model', 'quality_report', 'agent_handoff'])
        self.assertTrue(all(tool['inputSchema']['additionalProperties'] is False for tool in catalogue))

    def test_workspace_configuration_is_read_only_by_default(self):
        repository = Path(__file__).resolve().parents[1]
        configuration = json.loads((repository / '.vscode/mcp.json').read_text(encoding='utf-8'))
        server = configuration['servers']['bo-to-powerbi']
        self.assertEqual(server['type'], 'stdio')
        self.assertIn('powerbi_import.mcp_server', server['args'])
        self.assertNotIn('--allow-write', server['args'])

    def test_directory_migration_rejects_symlink_entries(self):
        self.tools.allow_write = True
        (self.root / 'sources').mkdir()
        with patch('pathlib.Path.is_symlink', return_value=True), \
             patch('pathlib.Path.rglob', return_value=[self.root / 'sources/link.wid']), \
             patch('migrate.main') as migrate:
            response = self.request('migrate', {'source': 'sources', 'output_dir': 'output', 'confirm': True})
            self.assertTrue(response['result']['isError'])
            migrate.assert_not_called()

    def test_inventory_does_not_extract(self):
        (self.root / 'Sales.wid').write_bytes(b'fixture')
        (self.root / 'ignore.txt').write_bytes(b'fixture')
        response = self.request('inventory', {'directory': '.'})['result']
        self.assertFalse(response['isError'])
        self.assertEqual(response['structuredContent']['files'], [{'path': 'Sales.wid', 'format': 'webi'}])

    def test_outside_root_is_rejected(self):
        self.assertTrue(self.request('inventory', {'directory': '..'})['result']['isError'])

    def test_writes_are_disabled_by_default(self):
        response = self.request('migrate', {'source': 'Sales.wid', 'output_dir': 'output', 'confirm': True})
        self.assertTrue(response['result']['isError'])
        self.assertFalse((self.root / 'output').exists())

    def test_write_requires_confirmation_even_when_enabled(self):
        self.tools.allow_write = True
        response = self.request('migrate', {'source': 'Sales.wid', 'output_dir': 'output', 'confirm': False})
        self.assertTrue(response['result']['isError'])

    def test_nonempty_output_is_never_overwritten(self):
        self.tools.allow_write = True
        (self.root / 'output').mkdir()
        original = self.root / 'output/keep.txt'
        original.write_text('keep', encoding='utf-8')
        response = self.request('migrate', {'source': 'Sales.wid', 'output_dir': 'output', 'confirm': True})
        self.assertTrue(response['result']['isError'])
        self.assertEqual(original.read_text(encoding='utf-8'), 'keep')

    def test_unknown_arguments_and_incorrect_types_are_protocol_errors(self):
        for arguments in ({'directory': '.', 'token': 'not-accepted'}, {'directory': True}, {}):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.request('inventory', arguments)['error']['code'], -32602)
        response = self.request('shared_model', {'files': ['one.wid'], 'model_name': 'Shared',
                                               'output_dir': 'output', 'confirm': True})
        self.assertEqual(response['error']['code'], -32602)

    def test_handoff_requires_report_and_never_claims_completion(self):
        self.assertTrue(self.request('agent_handoff', {'agent': 'Fabric'})['result']['isError'])
        self.request('quality_report', {'project_dir': '.'})
        result = self.request('agent_handoff', {'agent': '@Generator'})['result']['structuredContent']
        self.assertTrue(result['read_only'])
        self.assertEqual(len(result['findings']), 1)
        self.assertIn('not_run', result['completion'])

    def test_protocol_and_parse_errors_do_not_break_stream(self):
        messages = [
            '{bad json',
            json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}),
            json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}),
        ]
        output = io.StringIO()
        serve(self.tools, io.StringIO('\n'.join(messages)), output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]['error']['code'], -32700)
        self.assertEqual(responses[1]['result'], {})

    def test_initialization_and_invalid_requests(self):
        response = handle_request({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                   'params': {'protocolVersion': '2024-11-05'}}, self.tools)
        self.assertEqual(response['result']['protocolVersion'], '2024-11-05')
        self.assertEqual(handle_request([], self.tools)['error']['code'], -32600)
        self.assertEqual(handle_request({'jsonrpc': '2.0', 'id': 2, 'method': 'unknown'}, self.tools)['error']['code'], -32601)

    def test_tool_stdout_is_redirected_away_from_protocol(self):
        def noisy_call(name, arguments):
            print('not a protocol message')
            return {'ok': True}

        protocol_output = io.StringIO()
        with patch.object(self.tools, 'call', side_effect=noisy_call), patch('sys.stderr', io.StringIO()):
            serve(self.tools, io.StringIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                                    'params': {'name': 'inventory', 'arguments': {'directory': '.'}}})), protocol_output)
        self.assertFalse(json.loads(protocol_output.getvalue())['result']['isError'])

    def test_confirmed_generation_uses_local_cli_only(self):
        self.tools.allow_write = True
        (self.root / 'Sales.wid').write_bytes(b'fixture')
        with patch('migrate.main', return_value=0) as migrate:
            result = self.request('migrate', {'source': 'Sales.wid', 'output_dir': 'output', 'confirm': True})['result']
            self.assertFalse(result['isError'])
            self.assertNotIn('--deploy', migrate.call_args.args[0])
            self.assertEqual(result['structuredContent']['remote_execution'], 'not_run')

    def test_fabric_migration_exposes_quality_block_and_findings(self):
        self.tools.allow_write = True
        (self.root / 'Sales.wid').write_bytes(b'fixture')
        (self.root / 'output').mkdir()
        report = {'status': 'FAIL', 'priorities': [{'owner': 'Fabric', 'message': 'Unsupported BO semantics'}]}
        with patch('migrate.main', return_value=6), \
             patch('powerbi_import.migration_quality.build_quality_report', return_value=report):
            result = self.request('migrate', {'source': 'Sales.wid', 'output_dir': 'output',
                                              'output_format': 'fabric', 'confirm': True})['result']
            self.assertTrue(result['isError'])
            self.assertFalse(result['structuredContent']['ok'])
            self.assertEqual(result['structuredContent']['exit_code'], 6)
            self.assertEqual(result['structuredContent']['quality_report'], report)
            self.assertEqual(self.tools.latest_quality, report)

    def test_real_stdio_assessment_has_only_json_on_stdout(self):
        repository = Path(__file__).resolve().parents[1]
        shutil.copyfile(repository / 'examples/Enterprise_Sales.wid', self.root / 'Sales.wid')
        requests = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'assess', 'arguments': {'file': 'Sales.wid'}}},
        ]
        process = subprocess.run([sys.executable, '-m', 'powerbi_import.mcp_server', '--root', str(self.root)],
                                 input='\n'.join(json.dumps(request) for request in requests) + '\n',
                                 text=True, encoding='utf-8', capture_output=True, cwd=repository, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([response['id'] for response in responses], [1, 2, 3])
        self.assertEqual(len(responses[1]['result']['tools']), 6)
        self.assertFalse(responses[2]['result']['isError'], responses[2])
        self.assertIn('assessment', responses[2]['result']['structuredContent'])
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['Sales.wid'])

    def test_real_stdio_generation_and_quality_report(self):
        repository = Path(__file__).resolve().parents[1]
        shutil.copyfile(repository / 'examples/Enterprise_Sales.wid', self.root / 'Sales.wid')
        requests = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'migrate', 'arguments': {
                'source': 'Sales.wid', 'output_dir': 'output', 'confirm': True}}},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'quality_report', 'arguments': {
                'project_dir': 'output'}}},
        ]
        process = subprocess.run([sys.executable, '-m', 'powerbi_import.mcp_server', '--root', str(self.root), '--allow-write'],
                                 input='\n'.join(json.dumps(request) for request in requests) + '\n',
                                 text=True, encoding='utf-8', capture_output=True, cwd=repository, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertFalse(responses[1]['result']['isError'], responses[1])
        self.assertFalse(responses[2]['result']['isError'], responses[2])
        report = responses[2]['result']['structuredContent']
        self.assertEqual(report['summary']['projects'], 1)
        self.assertEqual(report['evidence']['data_refresh'], 'not_run')
        self.assertEqual(len(list((self.root / 'output').rglob('*.pbip'))), 1)
        self.assertTrue((self.root / 'output/comparison_report.html').is_file())

    def test_real_stdio_fabric_generation_returns_blockers_not_success(self):
        repository = Path(__file__).resolve().parents[1]
        shutil.copyfile(repository / 'examples/Enterprise_Sales.wid', self.root / 'Sales.wid')
        requests = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'migrate', 'arguments': {
                'source': 'Sales.wid', 'output_dir': 'output', 'output_format': 'fabric', 'confirm': True}}},
        ]
        process = subprocess.run([sys.executable, '-m', 'powerbi_import.mcp_server', '--root', str(self.root), '--allow-write'],
                                 input='\n'.join(json.dumps(request) for request in requests) + '\n',
                                 text=True, encoding='utf-8', capture_output=True, cwd=repository, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([response['id'] for response in responses], [1, 2])
        result = responses[1]['result']
        self.assertTrue(result['isError'])
        payload = result['structuredContent']
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['exit_code'], 6)
        self.assertEqual(payload['quality_report']['status'], 'FAIL')
        self.assertTrue(any('Unsupported BO group' in finding['message']
                            for finding in payload['quality_report']['priorities']))
        self.assertEqual(payload['remote_execution'], 'not_run')
        report_file = self.root / 'output/Sales/quality_report.json'
        self.assertTrue(report_file.is_file())