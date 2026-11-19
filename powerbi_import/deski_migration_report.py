"""Evidence-bounded pre-migration reports for Desktop Intelligence inventories."""

from bo_export.desktop_intelligence_extractor import (
    desktop_intelligence_formula_selector,
    desktop_intelligence_sql_selector,
)
from powerbi_import.html_template import data_table, esc, get_report_css, stat_card, stat_grid


def build_deski_migration_report(inventory):
    """Summarize one partial REP inventory without copying SQL or formulas."""
    if (inventory.get('schema_version') != 1
            or inventory.get('evidence_boundary') != 'experimental_partial_static_inventory'):
        raise ValueError('unsupported Desktop Intelligence inventory')

    sheets = [
        {'name': item['name'], 'structure_markers': list(item['structure_markers'])}
        for item in inventory['sheets']['candidates']
    ]
    providers = [
        {
            'id': item['id'],
            'name': item['name'],
            'source_name_candidate': (
                item.get('query_metadata_candidate', {}).get('source_name_candidate')
            ),
        }
        for item in inventory['providers']['candidates']
    ]
    queries = [
        {
            'selector': desktop_intelligence_sql_selector(item),
            'sql_status': item['sql_status'],
            'provider_association': item['provider_association'],
            'bo_function_markers': list(item['bo_function_markers']),
            'literal_argument_count': len(item['literal_arguments']),
        }
        for item in inventory['sql_candidates']
    ]
    formulas = [
        {
            'selector': desktop_intelligence_formula_selector(item),
            'formula_status': 'unverified',
        }
        for item in inventory['formula_candidates']
    ]
    counts = {
        'sheet_candidates': len(sheets),
        'provider_candidates': len(providers),
        'object_candidates': len(inventory['object_candidates']),
        'sql_candidates': len(queries),
        'formula_candidates': len(inventory['formula_candidates']),
        'inventory_warnings': len(inventory['warnings']),
    }
    if queries:
        sql_observation = 'SQL candidates were recovered; their content and associations are unverified.'
        sql_action = (
            'Review SQL in the protected inventory, validate its source and dialect, '
            'and verify provider, report and result-field bindings.'
        )
    else:
        sql_observation = 'No SQL candidate was recovered by this partial scan.'
        sql_action = 'Obtain and review source SQL through an authorized source or supported export.'

    findings = [
        {
            'area': 'Inventory coverage',
            'status': 'not_verified',
            'observation': (
                'Candidates and associations are incomplete and unverified; zero matches '
                'do not establish that an element is absent.'
            ),
            'action': 'Compare the inventory and its warnings with the source in Desktop Intelligence.',
        },
        {
            'area': 'SQL, providers and connection',
            'status': 'not_verified',
            'observation': sql_observation,
            'action': sql_action,
        },
        {
            'area': 'Prompts and filters',
            'status': 'not_verified',
            'observation': (
                'SQL function markers and literal-argument counts do not establish prompt '
                'labels, types, value lists, dependencies or filter behavior.'
            ),
            'action': (
                'Capture and review source prompts and filters; rewrite BO SQL functions '
                'and declare supported RDL parameters manually.'
            ),
        },
        {
            'area': 'Layout and design',
            'status': 'not_verified',
            'observation': (
                'Sheet and table/chart markers do not recover positions, styles, groups, '
                'sorts or page breaks.'
            ),
            'action': (
                'Capture source layouts and reconstruct and compare each page in '
                'Report Builder or Power BI.'
            ),
        },
        {
            'area': 'Business logic',
            'status': 'not_verified',
            'observation': (
                'Object and formula candidates are partial; formula expressions are omitted, '
                'and this inspection does not convert them.'
            ),
            'action': (
                'Use the stream-local formula selectors to locate expressions in the protected '
                'inventory, then review formulas, aggregations, filters and calculations against '
                'the source.'
            ),
        },
        {
            'area': 'Target generation',
            'status': 'not_run',
            'observation': (
                'This inspection does not generate an RDL or PBIP. Automatic REP-to-PBIP '
                'conversion is not supported.'
            ),
            'action': (
                'For an RDL draft, review the candidate and explicitly declare the SQL Server '
                'mapping, fields, layout and parameters before using the gated paginated CLI.'
            ),
        },
        {
            'area': 'Validation and deployment',
            'status': 'not_run',
            'observation': (
                'This inspection does not execute queries, render reports, compare source and '
                'target, test security, refresh or deploy.'
            ),
            'action': 'Plan source/target data, layout, prompt and security tests with report owners.',
        },
    ]
    checks = {
        name: 'not_run'
        for name in (
            'desktop_intelligence_open', 'rdl_generation', 'pbip_generation',
            'report_builder_open', 'power_bi_open', 'query_execution', 'refresh',
            'visual_comparison', 'prompt_comparison', 'source_target_equivalence',
            'security_validation', 'deployment', 'fabric_execution',
        )
    }
    return {
        'schema_version': 1,
        'report_type': 'desktop_intelligence_pre_migration',
        'scope': 'current_inspection_only',
        'status': 'review_required',
        'evidence_boundary': inventory['evidence_boundary'],
        'source': {
            key: inventory['source'][key]
            for key in ('file_name', 'size_bytes', 'sha256', 'container')
        },
        'source_authenticity': 'not_verified',
        'format_version': inventory['format_version'],
        'earliest_compatible_format_version': inventory['earliest_compatible_format_version'],
        'counts': counts,
        'sheet_candidates': sheets,
        'provider_candidates': providers,
        'sql_candidates': queries,
        'formula_candidates': formulas,
        'findings': findings,
        'checks': checks,
    }


def render_deski_migration_report(report):
    """Render the local REP pre-migration report without scripts or remote assets."""
    def table(headers, rows, table_id):
        if not rows:
            return '<p>No candidates recovered by this partial scan; absence is not established.</p>'
        return data_table(headers, [[esc(cell) for cell in row] for row in rows], table_id=table_id)

    counts = report['counts']
    source = report['source']
    stats = stat_grid([
        stat_card(counts['sheet_candidates'], 'Sheet candidates'),
        stat_card(counts['provider_candidates'], 'Provider candidates'),
        stat_card(counts['sql_candidates'], 'SQL candidates'),
        stat_card(counts['formula_candidates'], 'Formula candidates'),
    ])
    findings = table(
        ['Area', 'Status', 'Observation', 'Next action'],
        [[item['area'], item['status'], item['observation'], item['action']]
         for item in report['findings']],
        'review-actions',
    )
    sheets = table(
        ['Sheet candidate', 'Observed structure markers'],
        [[item['name'], ', '.join(item['structure_markers']) or 'Not observed in partial scan']
         for item in report['sheet_candidates']],
        'sheet-candidates',
    )
    providers = table(
        ['Provider candidate', 'Name', 'Possible source name - unverified'],
        [[item['id'], item['name'], item['source_name_candidate'] or 'Not recovered']
         for item in report['provider_candidates']],
        'provider-candidates',
    )
    queries = table(
        ['Selector', 'SQL status', 'Provider association', 'BO function markers', 'Literal arguments'],
        [[item['selector'], item['sql_status'], item['provider_association'].replace('_', ' '),
          ', '.join('@' + marker for marker in item['bo_function_markers']) or 'Not observed',
          item['literal_argument_count']]
         for item in report['sql_candidates']],
        'sql-candidates',
    )
    formulas = table(
        ['Stream-local selector', 'Formula status'],
        [[item['selector'], item['formula_status']] for item in report['formula_candidates']],
        'formula-candidates',
    )
    checks = table(
        ['Check or action', 'Status for this inspection'],
        [[name.replace('_', ' '), status] for name, status in report['checks'].items()],
        'inspection-checks',
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>DeskI pre-migration - {esc(source['file_name'])}</title>
<style>{get_report_css()}
.report-header .meta {{ flex-wrap: wrap; }}
section {{ margin: 28px 0; }}
section h2 {{ margin-bottom: 12px; }}
.notice {{ background: #fff4ce; color: #323130; border-left: 4px solid #a87b00; padding: 16px; }}
.hash {{ overflow-wrap: anywhere; }}
.footnote {{ margin-top: 12px; color: var(--pbi-gray); }}
</style></head><body>
<header class="report-header"><h1>Desktop Intelligence pre-migration</h1>
<p class="subtitle">Partial static evidence - manual review required</p>
<div class="meta"><span>{esc(source['file_name'])}</span>
<span>{esc(source['container'])} container</span>
<span>Format marker: {esc(report['format_version'] or 'not recovered')} (unverified)</span>
<span>Source authenticity not verified</span></div></header>
<main class="container">
<div class="notice"><strong>Not a fidelity score or migration result.</strong>
 Counts are candidates, not coverage; zero matches do not prove absence.
 This command generated no RDL or PBIP and performed no runtime validation.</div>
{stats}
<p class="hash">Source SHA-256: <code>{esc(source['sha256'])}</code></p>
<p class="footnote">Object candidates: {esc(counts['object_candidates'])}.
 Inventory warnings: {esc(counts['inventory_warnings'])}; review details in the protected inventory.</p>
<section><h2>Review actions</h2>{findings}</section>
<section><h2>Sheet candidates</h2>{sheets}</section>
<section><h2>Provider candidates</h2>{providers}</section>
<section><h2>SQL candidates</h2><p>Selectors identify unverified candidates; SQL text and
 literal arguments are not copied into this report.</p>{queries}</section>
<section><h2>Formula candidates</h2><p>Stream-local selectors identify unverified expressions;
 formula text is not copied into this report.</p>{formulas}</section>
<section><h2>Checks for this inspection</h2>{checks}</section>
<p class="footnote">Filenames and other metadata can be sensitive. Keep this report local and
 protected; it is not guaranteed to be sanitized.</p>
</main></body></html>
"""
