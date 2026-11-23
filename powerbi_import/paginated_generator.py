"""Paginated layouts and explicitly mapped RDL for Power BI.

Extends the existing paginated layout generation in PBIPGenerator with:
- Multi-page layouts with page breaks
- Table/matrix visual rendering with row groups and column groups
- Charts as embedded visuals (image placeholders)
- Page headers/footers with dynamic fields (page number, date, report name)
- JSON layout placeholders (not RDL files)
- Subreport linking for drill-through patterns
- Expression-based formatting (conditional row colors)

Legacy JSON layout usage:
    from powerbi_import.paginated_generator import PaginatedReportGenerator

    gen = PaginatedReportGenerator(project_dir, report_name)
    gen.generate(worksheets, datasources, calculations)

``generate_semantic_model_rdl`` separately creates RDL from an explicit mapping.
"""

import json
import os
import re
import uuid
from datetime import datetime
from xml.etree import ElementTree as ET

# ════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ════════════════════════════════════════════════════════════════════

_PAGE_WIDTH_INCHES = 11.0
_PAGE_HEIGHT_INCHES = 8.5
_MARGIN_INCHES = 0.5
_BODY_WIDTH = _PAGE_WIDTH_INCHES - 2 * _MARGIN_INCHES
_BODY_HEIGHT = _PAGE_HEIGHT_INCHES - 2 * _MARGIN_INCHES - 1.0  # Reserve for header/footer

_HEADER_HEIGHT_INCHES = 0.75
_FOOTER_HEIGHT_INCHES = 0.5

_RDL_BO_SOURCE_KINDS = frozenset({
    'webi', 'crystal', 'lumira', 'desktop_intelligence', 'xcelsius',
    'analysis_olap', 'universe',
})
_RDL_SQL_PARAMETER_TYPES = frozenset({
    'Boolean', 'DateTime', 'Float', 'Integer', 'String',
})

# Visual type → paginated element mapping
_VISUAL_TO_PAGINATED = {
    'table': 'Tablix',
    'tableEx': 'Tablix',
    'pivot-table': 'Tablix',
    'pivotTable': 'Tablix',
    'crosstab': 'Tablix',
    'matrix': 'Tablix',
    'barchart': 'Chart',
    'linechart': 'Chart',
    'piechart': 'Chart',
    'scatter': 'Chart',
    'combo': 'Chart',
    'area': 'Chart',
    'clusteredBarChart': 'Chart',
    'clusteredColumnChart': 'Chart',
    'lineChart': 'Chart',
    'pieChart': 'Chart',
    'scatterChart': 'Chart',
    'kpi': 'Textbox',
    'card': 'Textbox',
    'text-image': 'Textbox',
    'gauge': 'Chart',
    'map': 'Image',
}


def _new_guid():
    return str(uuid.uuid4())


def _inches(val):
    """Format a float value as an inches string."""
    return f"{val:.4f}in"


def generate_semantic_model_rdl(contract):
    """Return a self-contained RDL 2016 XML string, without writing or connecting.

    The SQL Server mapping requires ``title``, ``source_kind``, ``server``,
    ``database``, ``sql`` and ``columns``; it may also declare scalar
    ``parameters`` for SQL ``@Name`` references.
    See ``_generate_sql_server_rdl`` for its validation and evidence boundaries.

    The exact contract is a dict with keys ``title``, ``source_kind``,
    ``workspace``, ``semantic_model``, ``dax`` and ``columns``. Source kind is
    a declared BO source label, ``bw`` or ``bex``, not parsed metadata.
    Workspace and model are non-secret names, not URLs,
    connection strings or IDs. ``dax`` is the caller's complete EVALUATE query;
    ``columns`` is a nonempty ordered list of exact returned field names.
    Names in the connection must use letters, numbers, spaces, underscores,
    hyphens or periods. For this bounded contract DAX comments, parameters,
    semicolons and string literals are unsupported. Supply no secrets in any
    field: the checks reject common credential patterns but cannot identify
    every possible secret. Field names must be distinct ignoring case.

    The output contains one dataset and a simple detail table; it does not
    convert BO/BW objects, formulas, layouts, security or BEx semantics, nor
    validate the query or its declared result fields. XMLA capability, Build
    permission, licensing, Report Builder rendering and execution are not
    verified. Authentication is not embedded. Configure/verify credentials
    separately in Report Builder (Microsoft documents "Do not use credentials"
    for this Analysis Services connection).

    Sources: MS-RDL 2016/01 schema, Microsoft Report Builder connection strings,
    and Microsoft's Reporting Services Analysis Services extension OLEDB-MD:
    https://learn.microsoft.com/en-us/openspecs/sql_server_protocols/ms-rdl/52ce3983-2bfc-4e72-9359-42aaf5fe4509
    https://learn.microsoft.com/en-us/power-bi/paginated-reports/report-data/data-connections-data-sources-connection-strings-report-builder
    https://learn.microsoft.com/en-us/sql/reporting-services/report-data/data-sources-supported-by-reporting-services-ssrs
    """
    sql_keys = {'title', 'source_kind', 'server', 'database', 'sql', 'columns'}
    sql_optional_keys = {'parameters', 'layout'}
    if (isinstance(contract, dict) and sql_keys <= set(contract)
            and set(contract) <= sql_keys | sql_optional_keys):
        return _generate_sql_server_rdl(contract)

    keys = {'title', 'source_kind', 'workspace', 'semantic_model', 'dax', 'columns'}
    if not isinstance(contract, dict) or set(contract) != keys:
        raise ValueError('contract must contain exactly the documented keys')

    def checked_text(value, name, limit):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f'{name} must be a nonempty string of at most {limit} characters')
        if any(not (c in '\t\n\r' or '\x20' <= c <= '\ud7ff'
                    or '\ue000' <= c <= '\ufffd' or '\U00010000' <= c <= '\U0010ffff')
               for c in value):
            raise ValueError(f'{name} contains invalid XML characters')
        # Refuse common credential-bearing strings without echoing their contents.
        if (re.search(r'(?i)(password|passwd|pwd|token|secret|api[_ -]?key|'
                      r'authorization|credential|private[_ -]?key)\s*[:=]', value)
                or re.search(r'(?i)\bbearer\s+[a-z0-9._~+/\-]+=*', value)
                or re.search(r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----', value)
                or re.search(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.'
                             r'[A-Za-z0-9_-]{10,}\b', value)):
            raise ValueError(f'{name} contains a possible credential')
        return value

    title = checked_text(contract['title'], 'title', 200)
    if title != title.strip() or title.startswith('=') or any(c in title for c in '\r\n\t'):
        raise ValueError('title must be a single literal line without surrounding whitespace')
    source_kind = contract['source_kind']
    if not isinstance(source_kind, str) or source_kind not in _RDL_BO_SOURCE_KINDS | {'bw', 'bex'}:
        raise ValueError('unsupported source_kind')
    workspace = checked_text(contract['workspace'], 'workspace', 200)
    model = checked_text(contract['semantic_model'], 'semantic_model', 200)
    for name, value in (('workspace', workspace), ('semantic_model', model)):
        if (value != value.strip() or any(not (c.isalnum() or c in ' _-.') for c in value)
                or value in {'.', '..'}):
            raise ValueError(f'{name} contains unsupported connection-name characters')

    dax = checked_text(contract['dax'], 'dax', 50000)
    if (not re.match(r'(?is)^\s*EVALUATE\b', dax)
            or any(part in dax for part in (';', '"', '--', '//', '/*', '*/', '@'))
            or '\r' in dax):
        raise ValueError('dax must be an unparameterized EVALUATE query without comments or string literals')
    columns = contract['columns']
    if not isinstance(columns, list) or not 1 <= len(columns) <= 10:
        raise ValueError('columns must be a list of 1 to 10 returned field names')
    columns = [checked_text(value, 'column', 200) for value in columns]
    if any(v != v.strip() or v.startswith('=') or any(c in v for c in '\r\n\t') for v in columns):
        raise ValueError('column names must be single literal lines without surrounding whitespace')
    if len({v.casefold() for v in columns}) != len(columns):
        raise ValueError('column names must be distinct ignoring case')

    ns = 'http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition'
    # Local default namespace avoids ElementTree's process-global namespace registry.
    report = ET.Element('Report', {'xmlns': ns})

    def child(parent, name, text=None, **attributes):
        elem = ET.SubElement(parent, name, attributes)
        if text is not None:
            elem.text = text
        return elem

    description = (
        f'Declared source: {source_kind}. Target: Power BI semantic model. '
        'No BO/BW parsing or conversion; source formulas, layout, parameters, '
        'security and BEx semantics are not converted. Query, field mapping, '
        'permissions, rendering and execution are not verified.'
    )
    child(report, 'Description', description)
    ds = child(child(report, 'DataSources'), 'DataSource', Name='SemanticModel')
    props = child(ds, 'ConnectionProperties')
    child(props, 'DataProvider', 'OLEDB-MD')
    child(props, 'ConnectString',
          f'Data Source=powerbi://api.powerbi.com/v1.0/myorg/{workspace}; Initial Catalog={model}')
    dataset = child(child(report, 'DataSets'), 'DataSet', Name='ReportData')
    fields = child(dataset, 'Fields')
    for index, name in enumerate(columns, 1):
        field = child(fields, 'Field', Name=f'Field{index}')
        child(field, 'DataField', name)
    query = child(dataset, 'Query')
    child(query, 'DataSourceName', 'SemanticModel')
    child(query, 'CommandText', dax)

    section = child(child(report, 'ReportSections'), 'ReportSection')
    body = child(section, 'Body')
    items = child(body, 'ReportItems')

    def textbox(parent, name, value):
        box = child(parent, 'Textbox', Name=name)
        child(box, 'CanGrow', 'true')
        run = child(child(child(box, 'Paragraphs'), 'Paragraph'), 'TextRuns')
        child(child(run, 'TextRun'), 'Value', value)
        return box

    heading = textbox(items, 'ReportTitle', title)
    child(heading, 'Top', '0in')
    child(heading, 'Left', '0in')
    child(heading, 'Height', '0.4in')
    child(heading, 'Width', '10in')
    tablix = child(items, 'Tablix', Name='ResultTable')
    tb = child(tablix, 'TablixBody')
    widths = child(tb, 'TablixColumns')
    # Exact decimals sum to 10in even when the column count does not divide 10.
    width_units = [1000 // len(columns)] * len(columns)
    for i in range(1000 % len(columns)):
        width_units[i] += 1
    for width in width_units:
        child(child(widths, 'TablixColumn'), 'Width', f'{width / 100:.2f}in')
    rows = child(tb, 'TablixRows')
    for is_header in (True, False):
        row = child(rows, 'TablixRow')
        child(row, 'Height', '0.3in')
        cells = child(row, 'TablixCells')
        for index, name in enumerate(columns, 1):
            contents = child(child(cells, 'TablixCell'), 'CellContents')
            textbox(contents, f'{"Header" if is_header else "Value"}{index}',
                    name if is_header else f'=Fields!Field{index}.Value')
    col_members = child(child(tablix, 'TablixColumnHierarchy'), 'TablixMembers')
    for _ in columns:
        child(col_members, 'TablixMember')
    row_members = child(child(tablix, 'TablixRowHierarchy'), 'TablixMembers')
    child(row_members, 'TablixMember')
    detail = child(row_members, 'TablixMember')
    child(detail, 'Group', Name='Details')
    child(tablix, 'DataSetName', 'ReportData')
    child(tablix, 'Top', '0.5in')
    child(tablix, 'Left', '0in')
    child(tablix, 'Height', '0.6in')
    child(tablix, 'Width', '10in')
    child(body, 'Height', '1.1in')
    child(section, 'Width', '10in')
    page = child(section, 'Page')
    for name, value in (('PageWidth', '11in'), ('PageHeight', '8.5in'),
                        ('LeftMargin', '0.5in'), ('RightMargin', '0.5in'),
                        ('TopMargin', '0.5in'), ('BottomMargin', '0.5in')):
        child(page, name, value)
    return ET.tostring(report, encoding='unicode', xml_declaration=True)


def _generate_sql_server_rdl(contract):
    """Generate an RDL from an explicit SQL Server mapping, without connecting.

    The caller must provide ``title``, ``source_kind``, ``server``,
    ``database``, ``sql`` and ``columns``, with optional ``parameters`` and
    ``layout``.
    Parameters bind SQL ``@Name`` references to scalar report parameters using
    one of the RDL types Boolean, DateTime, Float, Integer or String. Optional
    prompt labels and multi-value behavior are explicit declarations. Layout
    dimensions, column widths and colors are likewise caller-supplied; they are
    not extracted from BusinessObjects. This is a declared mapping only:
    it does not extract BusinessObjects metadata or automatically map a BO
    layout. Connection authentication is not configured; query text can still
    contain sensitive data. Query validity, field mapping, rendering and
    execution are not verified. The limited SQL-shape validation
    does not establish that the query is valid for SQL Server or prove that
    execution would be safe.
    """
    required_keys = {'title', 'source_kind', 'server', 'database', 'sql', 'columns'}
    allowed_keys = required_keys | {'parameters', 'layout'}
    if (not isinstance(contract, dict) or not required_keys <= set(contract)
            or not set(contract) <= allowed_keys):
        raise ValueError('SQL mapping must contain the documented keys')

    def checked_text(value, name, limit):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f'{name} must be a nonempty string of at most {limit} characters')
        if any(not (c in '\t\n\r' or '\x20' <= c <= '\ud7ff'
                    or '\ue000' <= c <= '\ufffd' or '\U00010000' <= c <= '\U0010ffff')
               for c in value):
            raise ValueError(f'{name} contains invalid XML characters')
        # Match the existing DAX contract's conservative credential checks.
        if (re.search(r'(?i)(password|passwd|pwd|token|secret|api[_ -]?key|'
                      r'authorization|credential|private[_ -]?key)\s*[:=]', value)
                or re.search(r'(?i)\bbearer\s+[a-z0-9._~+/\-]+=*', value)
                or re.search(r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----', value)
                or re.search(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.'
                             r'[A-Za-z0-9_-]{10,}\b', value)):
            raise ValueError(f'{name} contains a possible credential')
        return value

    title = checked_text(contract['title'], 'title', 200)
    if title != title.strip() or title.startswith('=') or any(c in title for c in '\r\n\t'):
        raise ValueError('title must be a single literal line without surrounding whitespace')

    source_kind = contract['source_kind']
    if not isinstance(source_kind, str) or source_kind not in _RDL_BO_SOURCE_KINDS:
        raise ValueError('unsupported source_kind')

    server = checked_text(contract['server'], 'server', 200)
    database = checked_text(contract['database'], 'database', 200)
    for name, value in (('server', server), ('database', database)):
        if (value != value.strip() or not value.isprintable()
                or any(char in value for char in ';{}')):
            raise ValueError(f'{name} contains unsupported connection-string characters')

    sql = checked_text(contract['sql'], 'sql', 50000)
    if re.search(r'(?i)@\s*(?:Prompt|Variable)\s*\(', sql):
        raise ValueError('sql must not contain unresolved BusinessObjects prompt or variable macros')

    # Permit one optional terminal delimiter only. Semicolons elsewhere are
    # rejected conservatively, including those inside literals or comments.
    statement = sql.strip()
    if statement.endswith(';'):
        statement = statement[:-1].rstrip()
    if ';' in statement:
        raise ValueError('sql must contain a single statement without internal semicolons')

    # Tokenize only enough SQL syntax to identify the leading statement and
    # SELECT INTO, ignoring quoted values/identifiers and comments. This is a
    # shape check, not a SQL parser or execution-safety proof.
    tokens = []
    sql_parameter_references = []
    index = 0
    while index < len(statement):
        if statement.startswith('--', index):
            newline = statement.find('\n', index + 2)
            index = len(statement) if newline < 0 else newline + 1
            continue
        if statement.startswith('/*', index):
            depth = 1
            index += 2
            while index < len(statement) and depth:
                if statement.startswith('/*', index):
                    depth += 1
                    index += 2
                elif statement.startswith('*/', index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
            continue
        char = statement[index]
        if char in "'\"[":
            closing = ']' if char == '[' else char
            index += 1
            while index < len(statement):
                if statement[index] == closing:
                    if index + 1 < len(statement) and statement[index + 1] == closing:
                        index += 2
                    else:
                        index += 1
                        break
                else:
                    index += 1
            continue
        if char == '@':
            if index + 1 < len(statement) and statement[index + 1] == '@':
                # SQL Server system variables use @@ and are not dataset parameters.
                index += 2
                while index < len(statement) and (
                        statement[index].isalnum() or statement[index] in '_@$#'):
                    index += 1
                continue
            if (index + 1 < len(statement)
                    and (statement[index + 1].isalpha() or statement[index + 1] == '_')):
                start = index + 1
                index = start
                while index < len(statement) and (
                        statement[index].isalnum() or statement[index] in '_@$#'):
                    index += 1
                sql_parameter_references.append(statement[start:index])
                continue
            index += 1
            continue
        if char.isalpha() or char == '_':
            start = index
            index += 1
            while index < len(statement) and (
                    statement[index].isalnum() or statement[index] in '_@$#'):
                index += 1
            tokens.append(statement[start:index].upper())
            continue
        index += 1

    if not tokens or tokens[0] != 'SELECT':
        raise ValueError('sql must be a single SELECT statement')
    if 'INTO' in tokens[1:]:
        raise ValueError('sql must not use SELECT INTO')

    parameters = contract.get('parameters', [])
    if not isinstance(parameters, list) or len(parameters) > 50:
        raise ValueError('parameters must be a list of at most 50 scalar parameter mappings')
    checked_parameters = []
    parameter_names = set()
    for parameter in parameters:
        parameter_keys = {'name', 'data_type'}
        optional_parameter_keys = {'prompt', 'multi_value'}
        if (not isinstance(parameter, dict)
                or not parameter_keys <= set(parameter)
                or not set(parameter) <= parameter_keys | optional_parameter_keys):
            raise ValueError(
                'each parameter must contain name and data_type, with optional prompt and multi_value'
            )
        name = checked_text(parameter['name'], 'parameter name', 128)
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError('parameter names must be ASCII identifiers')
        if name.casefold() in parameter_names:
            raise ValueError('parameter names must be distinct ignoring case')
        parameter_names.add(name.casefold())
        data_type = parameter['data_type']
        if not isinstance(data_type, str) or data_type not in _RDL_SQL_PARAMETER_TYPES:
            raise ValueError('parameter data_type must be a supported scalar RDL type')
        prompt = checked_text(parameter.get('prompt', name), 'parameter prompt', 200)
        if prompt != prompt.strip() or any(character in prompt for character in '\r\n\t'):
            raise ValueError('parameter prompt must be a single literal line')
        multi_value = parameter.get('multi_value', False)
        if type(multi_value) is not bool:
            raise ValueError('parameter multi_value must be a boolean')
        checked_parameters.append({
            'name': name, 'data_type': data_type, 'prompt': prompt,
            'multi_value': multi_value,
        })

    referenced_parameters = {name.casefold() for name in sql_parameter_references}
    if referenced_parameters - parameter_names:
        raise ValueError('sql contains undeclared SQL Server parameters')
    if parameter_names - referenced_parameters:
        raise ValueError('parameters contains declarations not used by sql')

    columns = contract['columns']
    if not isinstance(columns, list) or not 1 <= len(columns) <= 10:
        raise ValueError('columns must be a list of 1 to 10 fields')
    fields = []
    labels = []
    declared_widths = []
    for column in columns:
        if isinstance(column, str):
            field, label = column, column
            width = None
        elif (isinstance(column, dict)
              and {'field', 'label'} <= set(column)
              and set(column) <= {'field', 'label', 'width'}):
            field, label = column['field'], column['label']
            width = column.get('width')
        else:
            raise ValueError(
                'each column must be a field name or a field/label/optional-width mapping'
            )
        label = checked_text(label, 'column label', 200)
        if label != label.strip() or label.startswith('=') or any(c in label for c in '\r\n\t'):
            raise ValueError('column labels must be single literal lines without surrounding whitespace')
        fields.append(field)
        labels.append(label)
        if width is not None and (
                isinstance(width, bool) or not isinstance(width, (int, float))
                or not 0 < width <= 50):
            raise ValueError('column width must be a positive number of inches')
        declared_widths.append(width)

    layout_defaults = {
        'page_width': 11.0, 'page_height': 8.5,
        'margin_left': 0.5, 'margin_right': 0.5,
        'margin_top': 0.5, 'margin_bottom': 0.5,
        'font_family': 'Segoe UI',
        'title_color': '#1F4E78',
        'header_background': '#1F4E78',
        'header_color': '#FFFFFF',
        'alternate_row_background': '#F2F6FA',
    }
    layout = contract.get('layout', {})
    if (not isinstance(layout, dict)
            or not set(layout) <= set(layout_defaults)):
        raise ValueError('layout contains unsupported properties')
    layout_values = {**layout_defaults, **layout}
    for name in ('page_width', 'page_height', 'margin_left', 'margin_right',
                 'margin_top', 'margin_bottom'):
        value = layout_values[name]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not 0 <= value <= 50
                or (name.startswith('page_') and value == 0)):
            raise ValueError(f'layout {name} must be a number of inches from 0 to 50')
    body_width = (
        layout_values['page_width'] - layout_values['margin_left']
        - layout_values['margin_right']
    )
    if body_width <= 0:
        raise ValueError('layout horizontal margins must leave a positive page width')
    colors = ('title_color', 'header_background', 'header_color',
              'alternate_row_background')
    for name in colors:
        if not isinstance(layout_values[name], str) or not re.fullmatch(
                r'#[0-9A-Fa-f]{6}', layout_values[name]):
            raise ValueError(f'layout {name} must be a #RRGGBB color')
    font_family = checked_text(layout_values['font_family'], 'layout font_family', 100)
    if (font_family != font_family.strip()
            or any(character in font_family for character in '\r\n\t')):
        raise ValueError('layout font_family must be a single literal line')
    fixed_width = sum(width or 0 for width in declared_widths)
    unspecified = declared_widths.count(None)
    if fixed_width > body_width + 1e-9:
        raise ValueError('declared column widths exceed the available page width')
    rounded_widths = [
        round(width, 4) if width is not None else None
        for width in declared_widths
    ]
    if unspecified:
        fixed_units = sum(
            round(width * 10000) for width in rounded_widths if width is not None
        )
        available_units = int((body_width + 1e-9) * 10000) - fixed_units
        shared_units, remainder = divmod(available_units, unspecified)
        if shared_units < 1:
            raise ValueError('column widths must leave positive space for every column')
        for index, width in enumerate(rounded_widths):
            if width is None:
                extra = 1 if remainder else 0
                remainder -= extra
                rounded_widths[index] = (shared_units + extra) / 10000
    if any(width is None or width <= 0 for width in rounded_widths):
        raise ValueError('column widths must leave positive space for every column')
    resolved_widths = [width for width in rounded_widths if width is not None]
    tablix_width = sum(resolved_widths)
    if tablix_width > body_width + 1e-9:
        raise ValueError('rounded column widths exceed the available page width')

    # Reuse the established tablix structure, then replace its query and styling.
    rdl = generate_semantic_model_rdl({
        'title': title,
        'source_kind': 'webi',
        'workspace': 'SqlMapping',
        'semantic_model': 'SqlMapping',
        'dax': 'EVALUATE {1}',
        'columns': fields,
    })
    ns = 'http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition'

    def qname(name):
        return f'{{{ns}}}{name}'

    report = ET.fromstring(rdl)

    def add_style(parent, properties):
        style = ET.SubElement(parent, qname('Style'))
        for name, value in properties:
            ET.SubElement(style, qname(name)).text = value

    def required_element(parent: ET.Element, path: str) -> ET.Element:
        element = parent.find(path)
        if element is None:
            raise RuntimeError(f'generated RDL is missing required element: {path}')
        return element

    description = required_element(report, qname('Description'))
    description.text = (
        f'SQL mapping (source: {source_kind}). No automatic BO report layout '
        'mapping was performed. Declared page, column and style properties are '
        'not source-verified. Connection authentication is not configured; query '
        'text may contain sensitive data. SQL query, declared fields, permissions, '
        'rendering and execution are not verified.'
    )
    title_box = required_element(report, f'.//{qname("Textbox")}[@Name="ReportTitle"]')
    add_style(title_box, [
        ('Color', layout_values['title_color']),
        ('FontFamily', font_family), ('FontSize', '20pt'),
        ('FontWeight', 'Bold'),
        ('PaddingBottom', '6pt'), ('VerticalAlign', 'Middle'),
    ])
    for index, label in enumerate(labels, 1):
        header = report.find(
            f'.//{qname("Textbox")}[@Name="Header{index}"]/'
            f'{qname("Paragraphs")}/{qname("Paragraph")}/'
            f'{qname("TextRuns")}/{qname("TextRun")}/{qname("Value")}')
        if header is None:
            raise RuntimeError('generated RDL is missing a table header')
        header.text = label
        header_box = report.find(f'.//{qname("Textbox")}[@Name="Header{index}"]')
        value_box = report.find(f'.//{qname("Textbox")}[@Name="Value{index}"]')
        if header_box is None or value_box is None:
            raise RuntimeError('generated RDL is missing a table cell textbox')
        add_style(header_box, [
            ('BackgroundColor', layout_values['header_background']),
            ('Color', layout_values['header_color']),
            ('FontFamily', font_family), ('FontSize', '10pt'),
            ('FontWeight', 'Bold'),
            ('PaddingLeft', '6pt'), ('PaddingRight', '6pt'),
            ('VerticalAlign', 'Middle'),
        ])
        add_style(value_box, [
            ('BackgroundColor',
             f'=IIF(RowNumber(Nothing) Mod 2 = 0, '
             f'"{layout_values["alternate_row_background"]}", "#FFFFFF")'),
            ('Color', '#222222'),
            ('FontFamily', font_family), ('FontSize', '9pt'),
            ('PaddingBottom', '3pt'), ('PaddingLeft', '6pt'),
            ('PaddingRight', '6pt'), ('PaddingTop', '3pt'),
        ])

    tablix_body = report.find(f'.//{qname("Tablix")}[@Name="ResultTable"]/{qname("TablixBody")}')
    tablix = report.find(f'.//{qname("Tablix")}[@Name="ResultTable"]')
    if tablix_body is None or tablix is None:
        raise RuntimeError('generated RDL is missing its result table')
    tablix_columns = required_element(tablix_body, qname('TablixColumns'))
    if len(tablix_columns) != len(resolved_widths):
        raise RuntimeError('generated RDL has an unexpected number of table columns')
    for column, width in zip(tablix_columns, resolved_widths):
        required_element(column, qname('Width')).text = f'{width:.4f}in'
    required_element(tablix, qname('Width')).text = f'{tablix_width:.4f}in'
    required_element(title_box, qname('Width')).text = f'{tablix_width:.4f}in'
    body = required_element(report, f'.//{qname("ReportSection")}/{qname("Body")}')
    rows = required_element(tablix_body, qname('TablixRows'))
    if len(rows) != 2:
        raise RuntimeError('generated RDL must contain a header and a detail row')
    header_row, detail_row = rows
    table_top, header_height, detail_height = 0.55, 0.35, 0.30
    required_element(header_row, qname('Height')).text = f'{header_height:.2f}in'
    required_element(detail_row, qname('Height')).text = f'{detail_height:.2f}in'
    required_element(tablix, qname('Top')).text = f'{table_top:.2f}in'
    required_element(tablix, qname('Height')).text = f'{header_height + detail_height:.2f}in'
    required_element(body, qname('Height')).text = f'{table_top + header_height + detail_height:.2f}in'
    required_element(report, f'.//{qname("ReportSection")}/{qname("Width")}').text = f'{body_width:.4f}in'

    page = required_element(report, f'.//{qname("ReportSection")}/{qname("Page")}')
    for name, value in (
            ('PageWidth', layout_values['page_width']),
            ('PageHeight', layout_values['page_height']),
            ('LeftMargin', layout_values['margin_left']),
            ('RightMargin', layout_values['margin_right']),
            ('TopMargin', layout_values['margin_top']),
            ('BottomMargin', layout_values['margin_bottom'])):
        required_element(page, qname(name)).text = f'{value:g}in'

    connection = required_element(report,
        f'{qname("DataSources")}/{qname("DataSource")}/{qname("ConnectionProperties")}')
    required_element(connection, qname('DataProvider')).text = 'SQL'
        # Keep connection-string keys fixed; only validated values are interpolated.
    required_element(connection, qname('ConnectString')).text = (
        f'Data Source={server};Initial Catalog={database}')
    query = required_element(report, f'{qname("DataSets")}/{qname("DataSet")}/{qname("Query")}')
    command_type = ET.Element(qname('CommandType'))
    command_type.text = 'Text'
    query.insert(1, command_type)
    required_element(query, qname('CommandText')).text = sql
    if checked_parameters:
        query_parameters = ET.Element(qname('QueryParameters'))
        for parameter in checked_parameters:
            query_parameter = ET.SubElement(
                query_parameters, qname('QueryParameter'),
                {'Name': f"@{parameter['name']}"},
            )
            ET.SubElement(query_parameter, qname('Value')).text = (
                f"=Parameters!{parameter['name']}.Value"
            )
        query.insert(1, query_parameters)

        report_parameters = ET.Element(qname('ReportParameters'))
        for parameter in checked_parameters:
            report_parameter = ET.SubElement(
                report_parameters, qname('ReportParameter'),
                {'Name': parameter['name']},
            )
            ET.SubElement(report_parameter, qname('DataType')).text = parameter['data_type']
            if parameter['multi_value']:
                ET.SubElement(report_parameter, qname('MultiValue')).text = 'true'
            ET.SubElement(report_parameter, qname('Prompt')).text = parameter['prompt']
        report_sections = required_element(report, qname('ReportSections'))
        report.insert(list(report).index(report_sections), report_parameters)

    # XML parsers normalize literal CR, including inside SQL string literals.
    return ET.tostring(report, encoding='unicode', xml_declaration=True).replace('\r', '&#13;')


def _checked_rdl_text(value, name, limit, literal_line=False):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{name} must be a nonempty string of at most {limit} characters')
    if any(not (c in '\t\n\r' or '\x20' <= c <= '\ud7ff'
                or '\ue000' <= c <= '\ufffd' or '\U00010000' <= c <= '\U0010ffff')
           for c in value):
        raise ValueError(f'{name} contains invalid XML characters')
    if value.startswith('='):
        raise ValueError(f'{name} must not start with an expression marker')
    if literal_line and any(c in value for c in '\r\n\t'):
        raise ValueError(f'{name} must be a single line')
    if (re.search(r'(?i)(password|passwd|pwd|token|secret|api[_ -]?key|'
                  r'authorization|credential|private[_ -]?key)\s*[:=]', value)
            or re.search(r'(?i)\bbearer\s+[a-z0-9._~+/\-]+=*', value)
            or re.search(r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----', value)):
        raise ValueError(f'{name} contains a possible credential')
    return value


def _rdl_identifier(name, used):
    identifier = re.sub(r'[^0-9A-Za-z_]+', '_', name).strip('_')[:60] or 'Parameter'
    if identifier[0].isdigit():
        identifier = f'P_{identifier}'
    candidate, suffix = identifier, 2
    while candidate.casefold() in used:
        candidate = f'{identifier}_{suffix}'
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def generate_unbound_rdl(contract):
    """Return an RDL skeleton with a title, a note and report parameters, but no data.

    The contract has ``title``, ``source_kind``, ``description`` (may be empty)
    and ``parameters``, a list of dicts with ``name``, ``prompt``, ``multiple``
    and ``optional``. Parameter names are normalized to RDL identifiers; the
    original name is kept in the prompt when no prompt was supplied. The BO
    metadata does not give parameter data types, so every parameter is declared
    as String and must be reviewed. The output has no data source, dataset or
    table: it is a starting point, not a converted report. Rendering in Report
    Builder is not verified.
    """
    keys = {'title', 'source_kind', 'description', 'parameters'}
    if not isinstance(contract, dict) or set(contract) != keys:
        raise ValueError('contract must contain exactly the documented keys')
    title = _checked_rdl_text(contract['title'], 'title', 200, literal_line=True)
    if title != title.strip():
        raise ValueError('title must not have surrounding whitespace')
    source_kind = contract['source_kind']
    if not isinstance(source_kind, str) or source_kind not in _RDL_BO_SOURCE_KINDS:
        raise ValueError('unsupported source_kind')
    description = contract['description']
    if description:
        description = _checked_rdl_text(description, 'description', 2000)
    parameters = contract['parameters']
    if not isinstance(parameters, list) or len(parameters) > 50:
        raise ValueError('parameters must be a list of at most 50 entries')

    ns = 'http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition'
    report = ET.Element('Report', {'xmlns': ns})

    def child(parent, name, text=None, **attributes):
        elem = ET.SubElement(parent, name, attributes)
        if text is not None:
            elem.text = text
        return elem

    child(report, 'Description',
          f'Unbound skeleton (source: {source_kind}). No data source, dataset or layout '
          'was converted; parameter data types are unverified and default to String. '
          'Rendering and execution are not verified.')
    if parameters:
        report_parameters = child(report, 'ReportParameters')
        used = set()
        for parameter in parameters:
            if not isinstance(parameter, dict) or set(parameter) != {
                    'name', 'prompt', 'multiple', 'optional'}:
                raise ValueError('each parameter must contain exactly the documented keys')
            if (type(parameter['multiple']) is not bool
                    or type(parameter['optional']) is not bool):
                raise ValueError('parameter multiple and optional must be booleans')
            original = _checked_rdl_text(parameter['name'], 'parameter name', 200,
                                         literal_line=True)
            prompt = parameter['prompt'] or original
            prompt = _checked_rdl_text(prompt, 'parameter prompt', 500, literal_line=True)
            element = child(report_parameters, 'ReportParameter',
                            Name=_rdl_identifier(original, used))
            child(element, 'DataType', 'String')
            if parameter['optional']:
                child(element, 'Nullable', 'true')
            if parameter['multiple']:
                child(element, 'MultiValue', 'true')
            child(element, 'Prompt', prompt)

    section = child(child(report, 'ReportSections'), 'ReportSection')
    body = child(section, 'Body')
    items = child(body, 'ReportItems')

    def textbox(name, value, top, height, style_properties):
        box = child(items, 'Textbox', Name=name)
        child(box, 'CanGrow', 'true')
        run = child(child(child(box, 'Paragraphs'), 'Paragraph'), 'TextRuns')
        child(child(run, 'TextRun'), 'Value', value)
        child(box, 'Top', top)
        child(box, 'Left', '0in')
        child(box, 'Height', height)
        child(box, 'Width', '10in')
        style = child(box, 'Style')
        for name, value in style_properties:
            child(style, name, value)

    textbox('ReportTitle', title, '0in', '0.4in', [
        ('Color', '#1F4E78'), ('FontFamily', 'Segoe UI'),
        ('FontSize', '20pt'), ('FontWeight', 'Bold'),
        ('PaddingBottom', '6pt'), ('VerticalAlign', 'Middle'),
    ])
    note = description + '\n\n' if description else ''
    parameter_note = (
        ' Generated parameter types default to String; source types are '
        'unverified or unavailable and must be reviewed.'
        if parameters else ''
    )
    textbox('MigrationNote',
            note + 'Not migrated: data source, query, layout and formulas.'
            + parameter_note,
            '0.5in', '0.8in', [
                ('BackgroundColor', '#F2F6FA'),
                ('Color', '#323130'), ('FontFamily', 'Segoe UI'),
                ('FontSize', '9pt'), ('PaddingBottom', '6pt'),
                ('PaddingLeft', '8pt'), ('PaddingRight', '8pt'),
                ('PaddingTop', '6pt'), ('VerticalAlign', 'Top'),
            ])
    child(body, 'Height', '1.4in')
    child(section, 'Width', '10in')
    page = child(section, 'Page')
    for name, value in (('PageWidth', '11in'), ('PageHeight', '8.5in'),
                        ('LeftMargin', '0.5in'), ('RightMargin', '0.5in'),
                        ('TopMargin', '0.5in'), ('BottomMargin', '0.5in')):
        child(page, name, value)
    return ET.tostring(report, encoding='unicode', xml_declaration=True).replace('\r', '&#13;')


# ════════════════════════════════════════════════════════════════════
#  PAGINATED REPORT GENERATOR
# ════════════════════════════════════════════════════════════════════

class PaginatedReportGenerator:
    """Generates paginated (RDL-style) reports from BO report data."""

    def __init__(self, project_dir, report_name):
        self.project_dir = project_dir
        self.report_name = report_name
        self.pag_dir = os.path.join(project_dir, 'PaginatedReport')
        os.makedirs(self.pag_dir, exist_ok=True)

    def generate(self, worksheets, datasources=None, calculations=None,
                 page_size='letter', orientation='landscape'):
        """Generate paginated report from worksheets.

        Args:
            worksheets: list of worksheet dicts
            datasources: list of datasource dicts (for data source refs)
            calculations: list of calculation dicts
            page_size: 'letter' or 'a4'
            orientation: 'landscape' or 'portrait'

        Returns:
            dict with stats: {pages, tablixes, charts, textboxes}
        """
        if page_size == 'a4':
            pw, ph = 11.69, 8.27
        else:
            pw, ph = 11.0, 8.5

        if orientation == 'portrait':
            pw, ph = ph, pw

        stats = {'pages': 0, 'tablixes': 0, 'charts': 0, 'textboxes': 0}

        report = self._create_report_definition(pw, ph)
        pages = []
        pages_dir = os.path.join(self.pag_dir, 'pages')
        os.makedirs(pages_dir, exist_ok=True)

        # Create header and footer
        header = self._create_header()
        footer = self._create_footer()

        # Create one page per worksheet
        for i, ws in enumerate(worksheets or []):
            page = self._create_page(ws, i + 1, pw, ph)
            pages.append(page)
            stats['pages'] += 1

            # Count element types
            for elem in page.get('body', {}).get('items', []):
                elem_type = elem.get('type', '')
                if elem_type == 'Tablix':
                    stats['tablixes'] += 1
                elif elem_type == 'Chart':
                    stats['charts'] += 1
                elif elem_type == 'Textbox':
                    stats['textboxes'] += 1

            # Write individual page JSON
            page_path = os.path.join(pages_dir, f'page{i + 1}.json')
            with open(page_path, 'w', encoding='utf-8') as f:
                json.dump(page, f, indent=2, ensure_ascii=False)

        # Write report definition
        report['pageCount'] = stats['pages']
        report['pages'] = [f'pages/page{i + 1}.json' for i in range(stats['pages'])]
        report_path = os.path.join(self.pag_dir, 'report.json')
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # Write header and footer
        header_path = os.path.join(self.pag_dir, 'header.json')
        with open(header_path, 'w', encoding='utf-8') as f:
            json.dump(header, f, indent=2, ensure_ascii=False)

        footer_path = os.path.join(self.pag_dir, 'footer.json')
        with open(footer_path, 'w', encoding='utf-8') as f:
            json.dump(footer, f, indent=2, ensure_ascii=False)

        # Write data source references
        if datasources:
            ds_def = self._create_datasource_refs(datasources)
            ds_path = os.path.join(self.pag_dir, 'datasources.json')
            with open(ds_path, 'w', encoding='utf-8') as f:
                json.dump(ds_def, f, indent=2, ensure_ascii=False)

        return stats

    def _create_report_definition(self, page_width, page_height):
        """Create the top-level paginated report definition."""
        return {
            'name': self.report_name,
            'type': 'PaginatedReport',
            'format': 'RDL',
            'created': datetime.now().isoformat(),
            'pageWidth': _inches(page_width),
            'pageHeight': _inches(page_height),
            'marginTop': _inches(_MARGIN_INCHES),
            'marginBottom': _inches(_MARGIN_INCHES),
            'marginLeft': _inches(_MARGIN_INCHES),
            'marginRight': _inches(_MARGIN_INCHES),
            'interactiveWidth': _inches(page_width),
            'interactiveHeight': _inches(page_height),
            'pageCount': 0,
            'pages': [],
        }

    def _create_header(self):
        """Create paginated report header."""
        return {
            'type': 'PageHeader',
            'height': _inches(_HEADER_HEIGHT_INCHES),
            'printOnFirstPage': True,
            'printOnLastPage': True,
            'items': [
                {
                    'type': 'Textbox',
                    'name': 'HeaderTitle',
                    'value': self.report_name,
                    'style': {
                        'fontFamily': 'Segoe UI',
                        'fontSize': '14pt',
                        'fontWeight': 'Bold',
                        'color': '#333333',
                    },
                    'top': _inches(0.1),
                    'left': _inches(0),
                    'width': _inches(5),
                    'height': _inches(0.5),
                },
                {
                    'type': 'Textbox',
                    'name': 'HeaderDate',
                    'value': '=Globals!ExecutionTime',
                    'style': {
                        'fontFamily': 'Segoe UI',
                        'fontSize': '9pt',
                        'color': '#666666',
                        'textAlign': 'Right',
                    },
                    'top': _inches(0.1),
                    'left': _inches(6),
                    'width': _inches(4),
                    'height': _inches(0.5),
                },
            ],
        }

    def _create_footer(self):
        """Create paginated report footer with page numbers."""
        return {
            'type': 'PageFooter',
            'height': _inches(_FOOTER_HEIGHT_INCHES),
            'printOnFirstPage': True,
            'printOnLastPage': True,
            'items': [
                {
                    'type': 'Textbox',
                    'name': 'FooterPageNumber',
                    'value': '=Globals!PageNumber & " of " & Globals!TotalPages',
                    'style': {
                        'fontFamily': 'Segoe UI',
                        'fontSize': '8pt',
                        'color': '#999999',
                        'textAlign': 'Center',
                    },
                    'top': _inches(0),
                    'left': _inches(3),
                    'width': _inches(4),
                    'height': _inches(0.3),
                },
            ],
        }

    def _create_page(self, worksheet, page_num, page_width, page_height):
        """Create a single page from a worksheet."""
        ws_name = worksheet.get('name', f'Page{page_num}')
        ws_type = worksheet.get('type', 'table')
        mark_type = worksheet.get('mark_type', ws_type)

        paginated_type = _VISUAL_TO_PAGINATED.get(mark_type,
                         _VISUAL_TO_PAGINATED.get(ws_type, 'Tablix'))

        body_items = []

        # Title
        body_items.append({
            'type': 'Textbox',
            'name': f'Title_{page_num}',
            'value': ws_name,
            'style': {
                'fontFamily': 'Segoe UI Semibold',
                'fontSize': '16pt',
                'color': '#333333',
                'fontWeight': 'Bold',
            },
            'top': _inches(0),
            'left': _inches(0),
            'width': _inches(_BODY_WIDTH),
            'height': _inches(0.5),
        })

        # Main content element
        if paginated_type == 'Tablix':
            tablix = self._create_tablix(worksheet, page_num)
            tablix['top'] = _inches(0.6)
            tablix['left'] = _inches(0)
            tablix['width'] = _inches(_BODY_WIDTH)
            tablix['height'] = _inches(_BODY_HEIGHT - 0.6)
            body_items.append(tablix)

        elif paginated_type == 'Chart':
            chart = self._create_chart(worksheet, page_num, mark_type)
            chart['top'] = _inches(0.6)
            chart['left'] = _inches(0)
            chart['width'] = _inches(_BODY_WIDTH)
            chart['height'] = _inches(_BODY_HEIGHT - 0.6)
            body_items.append(chart)

        else:
            # Textbox placeholder
            body_items.append({
                'type': 'Textbox',
                'name': f'Content_{page_num}',
                'value': f'[Visual: {ws_name}]',
                'style': {'fontFamily': 'Segoe UI', 'fontSize': '11pt'},
                'top': _inches(0.6),
                'left': _inches(0),
                'width': _inches(_BODY_WIDTH),
                'height': _inches(_BODY_HEIGHT - 0.6),
            })

        return {
            'name': f'Page{page_num}',
            'displayName': ws_name,
            'pageBreak': 'End' if page_num > 0 else 'None',
            'body': {
                'height': _inches(_BODY_HEIGHT),
                'items': body_items,
            },
        }

    def _create_tablix(self, worksheet, page_num):
        """Create a Tablix (table/matrix) element from worksheet data."""
        columns = worksheet.get('columns', [])
        dimensions = worksheet.get('dimensions', [])
        measures = worksheet.get('measures', [])

        # Build columns from dimensions + measures
        col_defs = []
        for dim in dimensions:
            name = dim.get('field', dim) if isinstance(dim, dict) else str(dim)
            col_defs.append({
                'name': name,
                'type': 'RowGroup',
                'width': _inches(1.5),
            })
        for meas in measures:
            name = meas.get('field', meas) if isinstance(meas, dict) else str(meas)
            col_defs.append({
                'name': name,
                'type': 'Detail',
                'width': _inches(1.2),
                'format': meas.get('format', '') if isinstance(meas, dict) else '',
            })

        # Fallback: use generic columns
        if not col_defs and columns:
            for c in columns[:20]:
                name = c.get('name', c) if isinstance(c, dict) else str(c)
                col_defs.append({
                    'name': name,
                    'type': 'Detail',
                    'width': _inches(1.5),
                })

        return {
            'type': 'Tablix',
            'name': f'Tablix_{page_num}',
            'dataSetRef': worksheet.get('datasource', 'DataSet1'),
            'columns': col_defs,
            'rowGroups': [c['name'] for c in col_defs if c['type'] == 'RowGroup'],
            'sortExpressions': [],
            'style': {
                'fontFamily': 'Segoe UI',
                'fontSize': '9pt',
                'headerBackground': '#0078D4',
                'headerColor': '#FFFFFF',
                'headerFontWeight': 'Bold',
                'alternateRowBackground': '#F5F5F5',
                'borderColor': '#DDDDDD',
                'borderWidth': '0.5pt',
            },
            'noRowsMessage': 'No data available',
        }

    def _create_chart(self, worksheet, page_num, chart_type):
        """Create a Chart element from worksheet data."""
        chart_type_map = {
            'barchart': 'Column',
            'clusteredBarChart': 'Column',
            'clusteredColumnChart': 'Column',
            'linechart': 'Line',
            'lineChart': 'Line',
            'piechart': 'Pie',
            'pieChart': 'Pie',
            'scatter': 'Scatter',
            'scatterChart': 'Scatter',
            'area': 'Area',
            'combo': 'Column',
            'gauge': 'Gauge',
        }

        rdl_chart = chart_type_map.get(chart_type, 'Column')
        dimensions = worksheet.get('dimensions', [])
        measures = worksheet.get('measures', [])

        category_fields = []
        for d in dimensions[:2]:
            name = d.get('field', d) if isinstance(d, dict) else str(d)
            category_fields.append(name)

        value_fields = []
        for m in measures[:4]:
            name = m.get('field', m) if isinstance(m, dict) else str(m)
            value_fields.append(name)

        return {
            'type': 'Chart',
            'name': f'Chart_{page_num}',
            'chartType': rdl_chart,
            'dataSetRef': worksheet.get('datasource', 'DataSet1'),
            'categoryFields': category_fields,
            'valueFields': value_fields,
            'title': worksheet.get('name', ''),
            'style': {
                'fontFamily': 'Segoe UI',
                'titleFontSize': '12pt',
                'legendPosition': 'Bottom',
                'palette': 'BrightPastel',
            },
        }

    def _create_datasource_refs(self, datasources):
        """Create data source reference definitions for paginated report."""
        refs = []
        for ds in datasources:
            name = ds.get('name', ds.get('caption', 'DataSource'))
            conn = ds.get('connection', {})
            refs.append({
                'name': re.sub(r'[^a-zA-Z0-9_]', '_', name),
                'type': conn.get('type', 'Unknown'),
                'connectionString': conn.get('connection_string', ''),
                'credentialRetrieval': 'Prompt',
            })
        return {'dataSources': refs}
