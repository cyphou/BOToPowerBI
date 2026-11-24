"""Behavioral tests for local orchestration APIs and interactive surfaces."""

import argparse
import base64
import io
import json
import os
import tempfile
import unittest
import zipfile
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from powerbi_import import api_server, incremental, notebook_api, wizard


class ApiServerTests(unittest.TestCase):
    def setUp(self):
        api_server._jobs.clear()
        api_server._rate_tracker.clear()

    def tearDown(self):
        api_server._jobs.clear()
        api_server._rate_tracker.clear()

    def _handler(self, path='/', body=b'', headers=None, client_ip='127.0.0.1'):
        handler = object.__new__(api_server.MigrationHandler)
        handler.path = path
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.headers = headers or {}
        handler.client_address = (client_ip, 12345)
        handler.response_status = None
        handler.response_headers = {}
        handler.send_response = lambda status: setattr(handler, 'response_status', status)
        handler.send_header = lambda key, value: handler.response_headers.__setitem__(key, value)
        handler.end_headers = lambda: None
        return handler

    def _json_body(self, handler):
        return json.loads(handler.wfile.getvalue().decode('utf-8'))

    def _post(self, path='/migrate', body=b'upload', content_type='application/octet-stream'):
        return self._handler(path, body, {
            'Content-Length': str(len(body)),
            'Content-Type': content_type,
        })

    def test_parse_multipart_removes_traversal_and_preserves_safe_basename(self):
        body = (b'--boundary\r\nContent-Disposition: form-data; name="file"; '
                b'filename="../../safe report.wid"\r\n\r\npayload\r\n--boundary--\r\n')
        self.assertEqual(api_server._parse_multipart(body, b'boundary'),
                         ('safe report.wid', b'payload'))

    def test_parse_multipart_replaces_unsafe_filename_and_rejects_invalid_body(self):
        body = (b'--b\r\nContent-Disposition: form-data; name="file"; '
                b'filename="bad?.wid"\r\n\r\ndata\r\n--b--')
        filename, data = api_server._parse_multipart(body, b'b')
        self.assertRegex(filename, r'^upload_[0-9a-f]{8}\.wid$')
        self.assertEqual(data, b'data')
        self.assertIsNone(api_server._parse_multipart(b'not multipart', b'b'))
        self.assertIsNone(api_server._parse_multipart(b'filename="x.wid"', b'b'))

    def test_integer_query_parameter_accepts_first_value_and_ignores_invalid(self):
        self.assertEqual(api_server._int_param({'year': ['2024', '2025']}, 'year'), 2024)
        self.assertIsNone(api_server._int_param({'year': ['bad']}, 'year'))
        self.assertIsNone(api_server._int_param({}, 'year'))

    def test_rate_limit_caps_requests_and_expires_old_entries_without_sleep(self):
        with patch.object(api_server.time, 'time', side_effect=[100] * api_server._RATE_LIMIT_MAX + [100, 161]):
            for _ in range(api_server._RATE_LIMIT_MAX):
                self.assertTrue(api_server._check_rate_limit('client'))
            self.assertFalse(api_server._check_rate_limit('client'))
            self.assertTrue(api_server._check_rate_limit('client'))

    def test_new_job_purges_stale_terminal_jobs_but_keeps_active_jobs(self):
        api_server._jobs.update({
            'old-done': {'status': 'completed', 'created': 0},
            'old-active': {'status': 'running', 'created': 0},
        })
        with patch.object(api_server.time, 'time', return_value=api_server.JOB_TTL_SECONDS + 1):
            job_id = api_server._new_job('local.wid')
        self.assertNotIn('old-done', api_server._jobs)
        self.assertIn('old-active', api_server._jobs)
        self.assertEqual(api_server._get_job(job_id)['status'], 'queued')
        api_server._update_job(job_id, status='failed', error='local failure')
        self.assertEqual(api_server._get_job(job_id)['error'], 'local failure')
        api_server._update_job('missing', status='completed')

    def test_get_health_jobs_status_and_not_found_responses(self):
        with patch.object(api_server, '_get_version', return_value='test-version'):
            health = self._handler('/health')
            health.do_GET()
        self.assertEqual(self._json_body(health), {'status': 'ok', 'version': 'test-version'})

        api_server._jobs['known'] = {
            'status': 'failed', 'created': 123, 'error': 'bad input',
            'input_path': 'local', 'output_dir': None, 'stats': None,
        }
        status = self._handler('/status/known?ignored=1')
        status.do_GET()
        self.assertEqual(self._json_body(status)['error'], 'bad input')
        self.assertEqual(status.response_status, 200)

        jobs = self._handler('/jobs/')
        jobs.do_GET()
        self.assertEqual(self._json_body(jobs)['jobs'][0]['job_id'], 'known')

        missing_status = self._handler('/status/nope')
        missing_status.do_GET()
        self.assertEqual(missing_status.response_status, 404)
        self.assertIn('not found', self._json_body(missing_status)['error'])
        unknown = self._handler('/unknown')
        unknown.do_GET()
        self.assertEqual(unknown.response_status, 404)

    def test_get_download_reports_incomplete_missing_and_unsafe_output(self):
        api_server._jobs['queued'] = {'status': 'running', 'created': 1}
        handler = self._handler('/download/queued')
        handler.do_GET()
        self.assertEqual(handler.response_status, 400)

        api_server._jobs['missing-output'] = {
            'status': 'completed', 'created': 1, 'output_dir': 'no-such-local-dir',
        }
        handler = self._handler('/download/missing-output')
        handler.do_GET()
        self.assertEqual(handler.response_status, 500)

        with tempfile.TemporaryDirectory() as outside:
            api_server._jobs['unsafe'] = {'status': 'completed', 'created': 1, 'output_dir': outside}
            with patch.object(api_server.tempfile, 'gettempdir', return_value=str(Path(outside, 'expected-root'))):
                handler = self._handler('/download/unsafe')
                handler.do_GET()
        self.assertEqual(handler.response_status, 400)

    def test_get_download_returns_zip_for_completed_local_output(self):
        with tempfile.TemporaryDirectory(prefix='api-output-', dir=tempfile.gettempdir()) as output_dir:
            Path(output_dir, 'result.txt').write_text('artifact', encoding='utf-8')
            api_server._jobs['ready'] = {'status': 'completed', 'created': 1, 'output_dir': output_dir}
            handler = self._handler('/download/ready')
            handler.do_GET()
        self.assertEqual(handler.response_status, 200)
        self.assertEqual(handler.response_headers['Content-Type'], 'application/zip')
        with zipfile.ZipFile(io.BytesIO(handler.wfile.getvalue())) as archive:
            self.assertEqual(archive.read('result.txt'), b'artifact')

    def test_post_rejects_oversize_empty_missing_boundary_and_missing_file(self):
        handler = self._handler('/migrate', b'x', {'Content-Length': str(api_server.MAX_UPLOAD_SIZE + 1)})
        handler.do_POST()
        self.assertEqual(handler.response_status, 413)

        handler = self._handler('/migrate', b'', {'Content-Length': '0'})
        handler.do_POST()
        self.assertEqual(handler.response_status, 400)

        handler = self._post(body=b'x', content_type='multipart/form-data')
        handler.do_POST()
        self.assertIn('boundary', self._json_body(handler)['error'])

        handler = self._post(body=b'x', content_type='multipart/form-data; boundary=b')
        with patch.object(api_server, '_parse_multipart', return_value=None):
            handler.do_POST()
        self.assertEqual(handler.response_status, 400)

    def test_post_rejects_invalid_json_and_unsupported_file_types(self):
        handler = self._post(body=b'{', content_type='application/json')
        handler.do_POST()
        self.assertEqual(handler.response_status, 400)
        self.assertIn('Invalid JSON payload', self._json_body(handler)['error'])

        payload = json.dumps({'filename': 'source.txt', 'file': base64.b64encode(b'data').decode()}).encode()
        handler = self._post(body=payload, content_type='application/json')
        handler.do_POST()
        self.assertIn('Unsupported file type', self._json_body(handler)['error'])

    def test_post_validates_calendar_culture_and_model_mode_and_cleans_temp_path(self):
        cases = [
            ('?calendar_start=1899', 'calendar_start'),
            ('?calendar_end=2101', 'calendar_end'),
            ('?culture=invalid_tag', 'Invalid culture'),
            ('?model_mode=unknown', 'model_mode'),
        ]
        for query, expected in cases:
            with self.subTest(query=query), patch.object(api_server.os, 'unlink', wraps=os.unlink) as unlink:
                handler = self._post(path='/migrate' + query)
                handler.do_POST()
                self.assertEqual(handler.response_status, 400)
                self.assertIn(expected, self._json_body(handler)['error'])
                unlink.assert_called_once()

    def test_post_rate_and_concurrency_limits_reject_without_starting_worker(self):
        with patch.object(api_server, '_check_rate_limit', return_value=False), \
             patch.object(api_server.os, 'unlink', wraps=os.unlink):
            handler = self._post()
            handler.do_POST()
        self.assertEqual(handler.response_status, 429)

        api_server._jobs['busy'] = {'status': 'running'}
        with patch.object(api_server, 'MAX_CONCURRENT_JOBS', 1), \
             patch.object(api_server.os, 'unlink', wraps=os.unlink):
            handler = self._post()
            handler.do_POST()
        self.assertIn('Server busy', self._json_body(handler)['error'])

    def test_post_queues_supported_upload_and_passes_options_to_worker(self):
        started = []

        class FakeThread:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def start(self):
                started.append(self.kwargs)

        payload = json.dumps({
            'filename': 'report.WID', 'file': base64.b64encode(b'local').decode(),
        }).encode()
        with patch.object(api_server.threading, 'Thread', FakeThread):
            handler = self._post('/migrate?calendar_start=2000&calendar_end=2040&culture=en-US&model_mode=composite',
                                 payload, 'application/json')
            handler.do_POST()
        response = self._json_body(handler)
        self.assertEqual(handler.response_status, 202)
        self.assertEqual(response['filename'], 'report.WID')
        self.assertEqual(api_server._get_job(response['job_id'])['status'], 'queued')
        self.assertEqual(started[0]['args'][2], {
            'calendar_start': 2000, 'calendar_end': 2040,
            'culture': 'en-US', 'model_mode': 'composite',
        })
        path = api_server._get_job(response['job_id'])['input_path']
        if os.path.exists(path):
            os.unlink(path)


class WizardTests(unittest.TestCase):
    def test_input_uses_default_and_masks_sensitive_values(self):
        with patch('builtins.input', return_value=''):
            self.assertEqual(wizard._input('Output', 'out'), 'out')
        with patch.object(wizard.getpass, 'getpass', return_value='secret') as getpass_mock:
            self.assertEqual(wizard._input('Password', sensitive=True), 'secret')
            getpass_mock.assert_called_once()

    def test_input_cancellation_exits_cleanly(self):
        with patch('builtins.input', side_effect=EOFError), patch('builtins.print') as print_mock:
            with self.assertRaises(SystemExit) as caught:
                wizard._input('Source')
        self.assertEqual(caught.exception.code, 0)
        print_mock.assert_called_once()

    def test_validate_file_path_rejects_empty_null_and_extension(self):
        self.assertEqual(wizard._validate_file_path(''), (False, 'Path is empty'))
        self.assertFalse(wizard._validate_file_path('bad\x00.wid')[0])
        self.assertEqual(wizard._validate_file_path('file.txt', {'.wid'}),
                         (False, 'Invalid file type: .txt'))
        self.assertEqual(wizard._validate_file_path('file.wid', {'.wid'}), (True, None))

    def test_choose_retries_invalid_values_then_returns_selected_option(self):
        with patch.object(wizard, '_input', side_effect=['nope', '0', '2']):
            self.assertEqual(wizard._choose('Format', ['a', 'b']), 1)

    def test_wizard_selects_discovered_report_and_collects_options(self):
        yes_no = [True, True, True, True, True, False, True, True]
        inputs = ['universe.unx', 'output', '2021', '2035', 'fr-FR']
        with patch.object(wizard.glob, 'glob', side_effect=[['examples/sales.wid']] + [[]] * 13), \
             patch.object(wizard.os.path, 'isfile', return_value=True), \
             patch.object(wizard, '_yes_no', side_effect=yes_no), \
             patch.object(wizard, '_input', side_effect=inputs), \
             patch.object(wizard, '_choose', side_effect=[0, 2, 1]):
            config = wizard.run_wizard()
        self.assertEqual(config['bo_file'], 'examples/sales.wid')
        self.assertEqual(config['universe'], 'universe.unx')
        self.assertEqual(config['output_format'], 'pbir')
        self.assertEqual(config['mode'], 'directquery')
        self.assertEqual((config['calendar_start'], config['calendar_end']), (2021, 2035))
        self.assertEqual(config['culture'], 'fr-FR')
        self.assertTrue(config['paginated'])
        self.assertTrue(config['rollback'])
        self.assertFalse(config['verbose'])
        self.assertTrue(config['assess'])

    def test_wizard_manual_source_without_calendar_and_cancellation(self):
        yes_no = [False, False, False, False, False, True, False]
        with patch.object(wizard.glob, 'glob', return_value=[]), \
             patch.object(wizard.os.path, 'isfile', return_value=True), \
             patch.object(wizard, '_yes_no', side_effect=yes_no), \
             patch.object(wizard, '_input', side_effect=['manual.lumx', 'out', 'en-US']), \
             patch.object(wizard, '_choose', side_effect=[0, 2]):
            config = wizard.run_wizard()
        self.assertIsNone(config)

    def test_wizard_rejects_missing_or_wrong_type_source(self):
        with patch.object(wizard.glob, 'glob', return_value=[]), \
             patch.object(wizard, '_input', return_value='missing.wid'), \
             patch.object(wizard.os.path, 'isfile', return_value=False):
            self.assertIsNone(wizard.run_wizard())

        with patch.object(wizard.glob, 'glob', return_value=[]), \
             patch.object(wizard, '_input', return_value='report.txt'), \
             patch.object(wizard.os.path, 'isfile', return_value=True):
            self.assertIsNone(wizard.run_wizard())

    def test_wizard_returns_configuration_when_user_proceeds(self):
        yes_no = [False, False, False, True, False, False, True]
        with patch.object(wizard.glob, 'glob', return_value=[]), \
             patch.object(wizard.os.path, 'isfile', return_value=True), \
             patch.object(wizard, '_yes_no', side_effect=yes_no), \
             patch.object(wizard, '_input', side_effect=['source.unv', 'target', 'en-US']), \
             patch.object(wizard, '_choose', side_effect=[0, 0]):
            config = wizard.run_wizard()
        self.assertEqual(config['bo_file'], 'source.unv')
        self.assertEqual(config['universe'], None)
        self.assertIsNone(config['calendar_start'])
        self.assertEqual(config['mode'], 'import')

    def test_wizard_to_args_maps_values_and_defaults(self):
        args = wizard.wizard_to_args({
            'bo_file': 'input.wid', 'mode': 'composite', 'output_format': 'tmdl',
            'paginated': True, 'verbose': True,
        })
        self.assertIsInstance(args, argparse.Namespace)
        self.assertEqual(args.bo_file, 'input.wid')
        self.assertEqual((args.mode, args.output_format), ('composite', 'tmdl'))
        self.assertTrue(args.paginated)
        self.assertTrue(args.verbose)
        self.assertFalse(args.rollback)
        self.assertIsNone(args.batch)
        self.assertFalse(args.dry_run)


class IncrementalTests(unittest.TestCase):
    @staticmethod
    def _write(root, relative, content):
        path = Path(root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def test_diff_classifies_added_modified_removed_and_unchanged(self):
        with tempfile.TemporaryDirectory() as existing, tempfile.TemporaryDirectory() as incoming:
            self._write(existing, 'changed.tmdl', 'old')
            self._write(existing, 'same.txt', 'same')
            self._write(existing, 'obsolete.txt', 'gone')
            self._write(incoming, 'changed.tmdl', 'new')
            self._write(incoming, 'same.txt', 'same')
            self._write(incoming, 'new.txt', 'added')
            diffs = {entry.path: entry for entry in incremental.IncrementalMerger.diff_projects(existing, incoming)}
        self.assertEqual({key: value.kind for key, value in diffs.items()}, {
            'changed.tmdl': 'modified', 'new.txt': 'added',
            'obsolete.txt': 'removed', 'same.txt': 'unchanged',
        })
        self.assertEqual(diffs['new.txt'].to_dict()['detail'], 'new file from re-migration')

    def test_merge_adds_updates_removes_and_keeps_user_owned_and_unchanged(self):
        with tempfile.TemporaryDirectory() as existing, tempfile.TemporaryDirectory() as incoming, \
             tempfile.TemporaryDirectory() as output:
            self._write(existing, 'user.txt', 'keep?')
            self._write(existing, 'staticResources/logo.png', 'user image')
            self._write(existing, 'model.tmdl', 'old model')
            self._write(existing, 'same.txt', 'same')
            self._write(incoming, 'new.txt', 'new file')
            self._write(incoming, 'model.tmdl', 'new model')
            self._write(incoming, 'same.txt', 'same')
            stats = incremental.IncrementalMerger.merge(existing, incoming, output)
            self.assertEqual(Path(output, 'new.txt').read_text(encoding='utf-8'), 'new file')
            self.assertEqual(Path(output, 'model.tmdl').read_text(encoding='utf-8'), 'new model')
            self.assertFalse(Path(output, 'user.txt').exists())
            self.assertEqual(Path(output, 'staticResources/logo.png').read_text(encoding='utf-8'), 'user image')
            self.assertEqual(Path(output, 'same.txt').read_text(encoding='utf-8'), 'same')
            report = json.loads(Path(output, '.migration_merge_report.json').read_text(encoding='utf-8'))
        self.assertEqual((stats['added'], stats['merged'], stats['removed'], stats['preserved']), (1, 1, 1, 1))
        self.assertEqual(report['stats']['added'], 1)
        self.assertIn('added', [entry['kind'] for entry in report['diffs']])
        self.assertTrue(report['timestamp'])

    def test_json_merge_preserves_user_fields_and_records_conflicts(self):
        with tempfile.TemporaryDirectory() as existing, tempfile.TemporaryDirectory() as incoming:
            self._write(existing, 'layout.json', json.dumps({
                'title': 'My title', 'displayName': 'Edited visual', 'description': 'Notes', 'engine': 1,
            }))
            self._write(incoming, 'layout.json', json.dumps({
                'title': 'Generated title', 'displayName': 'Generated visual', 'engine': 2, 'new': True,
            }))
            stats = incremental.IncrementalMerger.merge(existing, incoming)
            result = json.loads(Path(existing, 'layout.json').read_text(encoding='utf-8'))
        self.assertEqual(result['title'], 'My title')
        self.assertEqual(result['displayName'], 'Edited visual')
        self.assertEqual(result['description'], 'Notes')
        self.assertEqual(result['engine'], 2)
        self.assertTrue(result['new'])
        self.assertEqual(stats['conflicts'], ['layout.json'])

    def test_invalid_json_and_non_object_json_fall_back_to_incoming(self):
        with tempfile.TemporaryDirectory() as existing, tempfile.TemporaryDirectory() as incoming:
            self._write(existing, 'broken.json', '{')
            self._write(incoming, 'broken.json', '{"title":"fresh"}')
            self._write(existing, 'array.json', '[]')
            self._write(incoming, 'array.json', '[1, 2]')
            stats = incremental.IncrementalMerger.merge(existing, incoming)
            self.assertEqual(json.loads(Path(existing, 'broken.json').read_text()), {'title': 'fresh'})
            self.assertEqual(json.loads(Path(existing, 'array.json').read_text()), [1, 2])
        self.assertEqual(stats['conflicts'], [])

    def test_diff_summary_and_change_detector_cover_clean_changed_and_missing_metadata(self):
        with tempfile.TemporaryDirectory() as existing, tempfile.TemporaryDirectory() as incoming:
            self._write(existing, 'same.txt', 'same')
            self._write(incoming, 'same.txt', 'same')
            clean = incremental.IncrementalDiffGenerator.generate_incremental_update(existing, incoming)
            self._write(incoming, 'extra.txt', 'new')
            changed = incremental.IncrementalDiffGenerator.generate_incremental_update(existing, incoming)
            report = incremental.IncrementalMerger.generate_diff_report(existing, incoming)
            self.assertIn('Summary: 2 files compared', report)
            self.assertIn('[   ADDED] extra.txt', report)
        self.assertFalse(clean['has_changes'])
        self.assertEqual(clean['unchanged'], ['same.txt'])
        self.assertTrue(changed['has_changes'])
        self.assertEqual(changed['added'], ['extra.txt'])

        manifest = {'known': {'updated_at': 't1', 'content_hash': 'h1'}}
        infos = [
            {'name': 'known', 'updated_at': 't1', 'content_hash': 'h1'},
            {'name': 'timestamp-change', 'updated_at': 't2'},
            {'name': 'hash-change', 'updated_at': 't1', 'content_hash': 'h2'},
            {'name': 'new'}, {'name': ''},
        ]
        self.assertEqual(incremental.SourceChangeDetector.detect_changes(infos, manifest),
                         ['timestamp-change', 'hash-change', 'new'])

    def test_manifest_load_save_update_and_invalid_json_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            manifest_path = Path(root, 'nested', '.migration_manifest.json')
            manifest = incremental.SourceChangeDetector.update_manifest({}, 'Sales', 'now', 'abc')
            incremental.SourceChangeDetector.save_manifest(str(manifest_path), manifest)
            loaded = incremental.SourceChangeDetector.load_manifest(str(manifest_path))
            self.assertEqual(loaded['Sales']['updated_at'], 'now')
            self.assertEqual(loaded['Sales']['content_hash'], 'abc')
            self.assertTrue(loaded['Sales']['last_migration_ts'])
            manifest_path.write_text('{bad json', encoding='utf-8')
            self.assertEqual(incremental.SourceChangeDetector.load_manifest(str(manifest_path)), {})
        self.assertEqual(incremental.SourceChangeDetector.load_manifest('missing-manifest.json'), {})

    def test_apply_incremental_update_delegates_to_merge_and_copy_output_directory(self):
        with tempfile.TemporaryDirectory() as existing, tempfile.TemporaryDirectory() as incoming, \
             tempfile.TemporaryDirectory() as parent:
            self._write(existing, 'a.txt', 'old')
            self._write(incoming, 'a.txt', 'new')
            output = str(Path(parent, 'copy'))
            result = incremental.IncrementalDiffGenerator.apply_incremental_update(existing, incoming, output)
            self.assertEqual(Path(output, 'a.txt').read_text(encoding='utf-8'), 'new')
            self.assertTrue(Path(output, '.migration_merge_report.json').is_file())
        self.assertEqual(result['merged'], 1)


class NotebookApiTests(unittest.TestCase):
    def setUp(self):
        self.session = notebook_api.MigrationSession()

    def test_unloaded_session_guards_analysis_and_generation(self):
        for method in (self.session.assess, self.session.preview_dax, self.session.preview_m,
                       self.session.preview_visuals, self.session.generate):
            with self.subTest(method=method.__name__), self.assertRaisesRegex(RuntimeError, 'No workbook loaded'):
                method()
        with self.assertRaisesRegex(RuntimeError, 'No project generated'):
            self.session.validate()
        with self.assertRaisesRegex(RuntimeError, 'No project generated'):
            self.session.deploy('local-workspace')

    def test_load_returns_counts_from_mocked_local_extraction(self):
        extracted = {'worksheets': [{'name': 'one'}], 'calculations': [], 'datasources': {'one': 1}, 'meta': 'x'}
        with patch('bo_export.extract_bo_data.extract_bo_data', return_value=extracted) as extract:
            summary = self.session.load('local/report.wid')
        self.assertEqual(summary, {'worksheets': 1, 'calculations': 0, 'datasources': 1, 'meta': 1})
        self.assertEqual(self.session._extracted, extracted)
        self.assertTrue(os.path.isabs(self.session._workbook_path))
        extract.assert_called_once()

    def test_dax_preview_overrides_approximations_and_clear(self):
        self.session._extracted = {'calculations': [
            {'name': 'Exact', 'formula': '[Amount] + 1'},
            {'name': 'Approx', 'formula': 'unknown'},
            {'caption': 'Caption', 'formula': 'formula'},
            {'name': 'Empty', 'formula': ''},
        ], 'datasources': [{'tables': [{'name': 'Sales', 'columns': [{'name': 'Amount'}]}]}]}

        def convert(formula, column_table_map=None):
            return {'[Amount] + 1': 'SUM(Sales[Amount])', 'unknown': 'BLANK() // TODO', 'formula': '0 /* review */'}[formula]

        with patch('bo_export.dax_converter.convert_bo_formula_to_dax', side_effect=convert):
            previews = self.session.preview_dax()
            self.session.edit_dax('Exact', 'COUNTROWS(Sales)')
            overridden = self.session.preview_dax()
            approx = self.session.list_approximated()
            self.session.clear_dax_override('Exact')
        self.assertEqual([p['name'] for p in previews], ['Exact', 'Approx', 'Caption'])
        self.assertEqual(previews[0]['status'], 'exact')
        self.assertEqual(previews[1]['status'], 'approximated')
        self.assertEqual(overridden[0]['dax_formula'], 'COUNTROWS(Sales)')
        self.assertEqual(overridden[0]['status'], 'overridden')
        self.assertEqual(len(approx), 2)
        self.assertEqual(self.session.get_dax_overrides(), {})

    def test_m_preview_returns_expression_and_contains_failures(self):
        self.session._extracted = {'datasources': [{
            'name': 'DS', 'connection': {'class': 'Local'}, 'tables': [{'name': 'Good'}, {'name': 'Bad'}],
        }]}
        with patch('bo_export.compat.generate_power_query_m', side_effect=['let Source = 1', RuntimeError('offline')]):
            previews = self.session.preview_m()
        self.assertEqual(previews[0]['m_expression'], 'let Source = 1')
        self.assertEqual(previews[0]['connection_type'], 'Local')
        self.assertEqual(previews[1]['m_expression'], '// Failed to generate M for Bad')

    def test_visual_preview_mapping_override_and_configuration(self):
        self.session._extracted = {'worksheets': [
            {'name': 'Bar', 'mark_type': 'bar', 'fields': ['x', 'y']},
            {'name': 'Manual', 'type': 'automatic'},
        ]}
        with patch('powerbi_import.visual_generator.resolve_visual_type', side_effect=['clusteredBarChart', 'table', 'clusteredBarChart']):
            before = self.session.preview_visuals()
            self.session.override_visual_type('Manual', 'lineChart')
            after = self.session.preview_visuals()
        self.assertEqual(before[0]['field_count'], 2)
        self.assertFalse(before[0]['overridden'])
        self.assertEqual(after[1]['pbi_visual_type'], 'lineChart')
        self.assertTrue(after[1]['overridden'])
        config = self.session.configure(mode='composite', languages=['fr-FR'], unknown='ignored')
        self.assertEqual(config['mode'], 'composite')
        self.assertEqual(self.session.get_config()['languages'], ['fr-FR'])
        self.assertNotIn('unknown', config)

    def test_generate_and_validate_use_mock_importer_and_validator(self):
        self.session._extracted = {'calculations': [{'name': 'Net'}], 'datasources': []}
        with tempfile.TemporaryDirectory() as output:
            with patch('bo_export.extract_bo_data._write_json_outputs') as write_outputs, \
                 patch('powerbi_import.import_to_powerbi.PowerBIImporter') as importer_class:
                importer_class.return_value.import_all.return_value = {'tables': 2, 'measures': 3, 'pages': 4}
                result = self.session.generate(output)
            self.assertEqual(result, {'output_dir': output, 'tables': 2, 'measures': 3, 'pages': 4})
            importer_class.return_value.import_all.assert_called_once()
            write_outputs.assert_called_once()
            validation_result = {'errors': [], 'warnings': ['review']}
            with patch('powerbi_import.validator.ArtifactValidator') as validator_class:
                validator_class.return_value.validate_project.return_value = validation_result
                self.assertEqual(self.session.validate(), validation_result)
            self.assertEqual(self.session._validation_result, validation_result)

    def test_generate_applies_dax_override_and_normalizes_non_dict_result(self):
        self.session._extracted = {'calculations': [{'name': 'Total'}]}
        self.session.edit_dax('Total', 'SUM(Sales[Value])')
        with patch('bo_export.extract_bo_data._write_json_outputs'), \
             patch('powerbi_import.import_to_powerbi.PowerBIImporter') as importer_class:
            importer_class.return_value.import_all.return_value = None
            result = self.session.generate('target')
        self.assertEqual(self.session._extracted['calculations'][0]['_dax_override'], 'SUM(Sales[Value])')
        self.assertEqual(result, {'output_dir': 'target', 'tables': 0, 'measures': 0, 'pages': 0})

    def test_deploy_uses_local_mock_deployer_and_requires_generation(self):
        self.session._generated_path = 'local-project'
        deploy_result = argparse.Namespace(to_dict=lambda: {'status': 'deployed locally'})
        with patch('powerbi_import.deploy.pbi_deployer.PBIWorkspaceDeployer') as deployer_class:
            deployer_class.return_value.deploy_project.return_value = deploy_result
            result = self.session.deploy('workspace', refresh=True)
        self.assertEqual(result, {'status': 'deployed locally'})
        deployer_class.assert_called_once_with(workspace_id='workspace')
        deployer_class.return_value.deploy_project.assert_called_once_with('local-project', refresh=True)

    def test_generate_notebook_writes_valid_json_and_escapes_embedded_path(self):
        with tempfile.TemporaryDirectory() as root:
            workbook = str(Path(root, "sales' report.wid"))
            output = str(Path(root, 'nested', 'migration.ipynb'))
            result_path = self.session.generate_notebook(workbook, output)
            notebook = json.loads(Path(result_path).read_text(encoding='utf-8'))
        self.assertEqual(result_path, output)
        self.assertEqual(notebook['nbformat'], 4)
        self.assertGreaterEqual(len(notebook['cells']), 10)
        code = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
        self.assertIn("sales\\' report.wid", code)
        self.assertIn('session.generate()', code)
        self.assertTrue(all('metadata' in cell for cell in notebook['cells']))


if __name__ == '__main__':
    unittest.main()
