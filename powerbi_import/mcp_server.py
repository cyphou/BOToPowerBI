"""Local, root-scoped MCP tools over newline-delimited JSON-RPC stdio."""

import argparse
import contextlib
import json
import sys
import tempfile
from pathlib import Path

PROTOCOL_VERSION = '2025-06-18'


def _tool_catalogue():
    string = {'type': 'string', 'minLength': 1}
    definitions = [
        ('inventory', 'List supported BO source files without extracting them.',
         {'directory': string}, ['directory'], True),
        ('assess', 'Assess one BO artifact without persisting extraction or generating a project.',
         {'file': string}, ['file'], True),
        ('migrate', 'Generate local projects. Requires server --allow-write, confirm=true and an empty output directory.',
         {'source': string, 'output_dir': string, 'output_format': {'type': 'string', 'enum': ['pbip', 'fabric']},
          'confirm': {'type': 'boolean'}}, ['source', 'output_dir', 'confirm'], False),
        ('shared_model', 'Generate a shared model and thin reports from at least two BO sources. Local writes only.',
         {'files': {'type': 'array', 'items': string, 'minItems': 2}, 'model_name': string,
          'output_dir': string, 'force_merge': {'type': 'boolean'}, 'confirm': {'type': 'boolean'}},
         ['files', 'model_name', 'output_dir', 'confirm'], False),
        ('quality_report', 'Read-only local PBIP/Fabric validation. Does not launch Desktop or execute cloud work.',
         {'project_dir': string}, ['project_dir'], True),
        ('agent_handoff', 'Return findings for an owner from the latest quality report in this process; never apply fixes.',
         {'agent': string}, ['agent'], True),
    ]
    return [{'name': name, 'description': description,
             'inputSchema': {'type': 'object', 'properties': properties, 'required': required,
                             'additionalProperties': False},
             'annotations': {'readOnlyHint': read_only, 'destructiveHint': False, 'openWorldHint': False}}
            for name, description, properties, required, read_only in definitions]


class MigrationTools:
    def __init__(self, root, allow_write=False):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise FileNotFoundError('MCP root must be an existing directory')
        self.allow_write = allow_write
        self.latest_quality = None

    def _path(self, value):
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Path is outside the configured MCP root')
        return path

    def _source(self, value):
        from bo_export.extract_bo_data import SUPPORTED_EXTENSIONS
        path = self._path(value)
        if not path.is_file():
            raise FileNotFoundError(f'BO source file not found: {path.name}')
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError('Unsupported BO source extension')
        if SUPPORTED_EXTENSIONS[path.suffix.lower()] == 'biar':
            raise ValueError('Use the --biar CLI workflow for archives; MCP assess/migrate accepts report or universe files')
        return path

    def _output(self, arguments):
        if not self.allow_write or arguments.get('confirm') is not True:
            raise PermissionError('Local writes require server --allow-write and confirm=true')
        output = self._path(arguments['output_dir'])
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError('Output must be a new or empty directory; overwriting is disabled')
        return output

    def call(self, name, arguments):
        from bo_export.extract_bo_data import SUPPORTED_EXTENSIONS

        if name == 'inventory':
            directory = self._path(arguments['directory'])
            if not directory.is_dir():
                raise FileNotFoundError('Source directory not found')
            files = [{'path': path.relative_to(self.root).as_posix(),
                      'format': SUPPORTED_EXTENSIONS[path.suffix.lower()]}
                     for path in sorted(directory.rglob('*'))
                     if path.is_file() and path.resolve().is_relative_to(self.root)
                     and path.suffix.lower() in SUPPORTED_EXTENSIONS]
            return {'files': files, 'count': len(files), 'read_only': True}
        if name == 'assess':
            from bo_export.extract_bo_data import extract_bo_data
            from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
            from .assessment import run_assessment
            source = self._source(arguments['file'])
            with tempfile.TemporaryDirectory(prefix='bo_mcp_assess_') as temporary:
                data = extract_bo_data(str(source), output_dir=temporary)
                report = run_assessment(adapt_bo_to_converted_objects(data), workbook_name=source.stem)
            return {'assessment': report.to_dict(), 'read_only': True}
        if name == 'quality_report':
            from .migration_quality import build_quality_report
            directory = self._path(arguments['project_dir'])
            if any(path.is_symlink() for path in directory.rglob('*')):
                raise ValueError('Symlink entries are not supported in MCP project trees')
            report = build_quality_report(directory)
            self.latest_quality = report
            return report
        if name == 'agent_handoff':
            if self.latest_quality is None:
                raise ValueError('Run quality_report in this MCP session first')
            owner = arguments['agent'].lstrip('@').casefold()
            findings = [item for item in self.latest_quality['priorities'] if item['owner'].casefold() == owner]
            return {'read_only': True, 'project_dir': self.latest_quality['project_dir'],
                    'agent': arguments['agent'], 'findings': findings,
                    'completion': 'not_run; an external agent must apply fixes and revalidate'}
        if name in ('migrate', 'shared_model'):
            from migrate import main
            output = self._output(arguments)
            if name == 'migrate':
                source = self._path(arguments['source'])
                if source.is_dir():
                    if any(path.is_symlink() for path in source.rglob('*')):
                        raise ValueError('Symlink entries are not supported in MCP source trees')
                    command = ['--batch', str(source)]
                else:
                    command = [str(self._source(arguments['source']))]
                command.extend(['--output-format', arguments.get('output_format', 'pbip')])
            else:
                model_name = arguments['model_name']
                if model_name in ('.', '..') or any(char in model_name for char in '/\\:'):
                    raise ValueError('Model name must be a single safe path component')
                sources = [str(self._source(value)) for value in arguments['files']]
                command = ['--shared-model', *sources, '--model-name', model_name]
                if arguments.get('force_merge'):
                    command.append('--force-merge')
            command.extend(['--output-dir', str(output)])
            status = main(command)
            result = {'ok': status == 0, 'exit_code': status, 'output_dir': str(output),
                      'remote_execution': 'not_run'}
            if arguments.get('output_format') == 'fabric' and output.is_dir():
                from .migration_quality import build_quality_report
                report = build_quality_report(output)
                self.latest_quality = report
                result['quality_report'] = report
                if report['status'] == 'FAIL':
                    from migrate import EXIT_VALIDATION_ERROR
                    result['ok'] = False
                    result['exit_code'] = status or EXIT_VALIDATION_ERROR
            return result
        raise ValueError('Unknown tool')


def _validate_tool_arguments(tool, arguments):
    if not isinstance(arguments, dict):
        raise ValueError('Tool arguments must be an object')
    schema = tool['inputSchema']
    if set(arguments) - set(schema['properties']):
        raise ValueError('Unknown tool argument')
    if set(schema['required']) - set(arguments):
        raise ValueError('Missing required tool argument')
    for name, value in arguments.items():
        rule = schema['properties'][name]
        expected = rule['type']
        if expected == 'boolean' and not isinstance(value, bool):
            raise ValueError(f'{name} must be a boolean')
        if expected == 'string' and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f'{name} must be a nonempty string')
        if expected == 'array' and (not isinstance(value, list) or len(value) < rule['minItems']
                                    or any(not isinstance(item, str) or not item.strip() for item in value)):
            raise ValueError(f'{name} must contain at least two nonempty paths')
        if 'enum' in rule and value not in rule['enum']:
            raise ValueError(f'Unsupported value for {name}')


def handle_request(request, tools):
    request_id = request.get('id') if isinstance(request, dict) else None

    def failure(code, message):
        return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}

    if not isinstance(request, dict) or request.get('jsonrpc') != '2.0' or not isinstance(request.get('method'), str):
        return failure(-32600, 'Invalid JSON-RPC request')
    if request_id is not None and (isinstance(request_id, bool) or not isinstance(request_id, (str, int))):
        request_id = None
        return failure(-32600, 'Invalid request id')
    if 'id' not in request:
        return None
    params = request.get('params', {})
    if not isinstance(params, dict):
        return failure(-32602, 'Parameters must be an object')
    method = request['method']
    if method == 'initialize':
        supported = ('2024-11-05', '2025-03-26', PROTOCOL_VERSION)
        version = params.get('protocolVersion')
        result = {'protocolVersion': version if version in supported else PROTOCOL_VERSION,
                  'capabilities': {'tools': {'listChanged': False}},
                  'serverInfo': {'name': 'bo-to-powerbi', 'version': '1.0.0'}}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': _tool_catalogue()}
    elif method == 'tools/call':
        catalogue = {tool['name']: tool for tool in _tool_catalogue()}
        name = params.get('name')
        if not isinstance(name, str) or name not in catalogue:
            return failure(-32602, 'Unknown tool')
        arguments = params.get('arguments', {})
        try:
            _validate_tool_arguments(catalogue[name], arguments)
        except ValueError as error:
            return failure(-32602, str(error))
        try:
            with contextlib.redirect_stdout(sys.stderr):
                payload = tools.call(name, arguments)
            failed = payload.get('ok') is False
        except Exception as error:
            payload = {'ok': False, 'error': str(error)}
            failed = True
        result = {'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)}],
                  'structuredContent': payload, 'isError': failed}
    else:
        return failure(-32601, 'Method not found')
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def serve(tools, input_stream=None, output_stream=None):
    source = input_stream if input_stream is not None else sys.stdin
    destination = output_stream if output_stream is not None else sys.stdout
    for line in source:
        try:
            request = json.loads(line)
        except ValueError:
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Invalid JSON'}}
        else:
            response = handle_request(request, tools)
        if response is not None:
            destination.write(json.dumps(response, ensure_ascii=False) + '\n')
            destination.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.', help='Allowed source and output root (default: current directory)')
    parser.add_argument('--allow-write', action='store_true', help='Enable explicitly confirmed local generation')
    parser.add_argument('--list', action='store_true', help='Print the tool catalogue and exit')
    args = parser.parse_args(argv)
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    if args.list:
        print(json.dumps({'tools': _tool_catalogue()}, indent=2))
    else:
        serve(MigrationTools(args.root, allow_write=args.allow_write))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())