---
name: bo-to-powerbi
description: "Use when: migrating SAP BusinessObjects Web Intelligence .wid, Crystal .rpt, universes .unx/.unv, BIAR archives, or Lumira .lumx/.lums to Power BI PBIP or Fabric; inspecting experimental Desktop Intelligence .rep inventories; preparing staged SAP BW history for Fabric; assessing readiness, batch migration, shared models, debugging BO formulas, or preparing deployment. Not for Tableau workbooks or Power BI authoring unrelated to BO/BW."
---

# BusinessObjects To Power BI

Use this repository's migration engine. Prefer the CLI over manually recreating generated artifacts.

## BO Procedure

1. Read `.github/copilot-instructions.md`, `.github/agents/shared.instructions.md`, and `docs/AGENTS.md`.
2. Identify the source artifact, required universe metadata, output format (`pbip`, `fabric`, or separately declared `rdl`), and output directory. Use `python migrate.py --help` for common workflows and `--help-all` for all options.
3. Assess or dry-run first when the source's compatibility is unknown. Use a separate output directory and do not overwrite customer artifacts without confirmation.
4. Run the existing CLI workflow. Keep BO's 15 extracted object types and adapter contract intact; do not substitute Tableau's schema or subcommands.
5. Inspect produced artifacts and available validation reports. Fix defects in the owning extractor/converter/generator, not only in output files.
6. After implementation changes, run a focused test, then `pytest tests/ --tb=short -q`. Report any failures without weakening assertions.
7. Deployment is separate authorization. Read `.github/skills/fabric-mcp-routing/SKILL.md` and hand off to Deployer before remote writes.

For an authorized CMS, `BOServerClient` can read WebI report tabs, their
details and elements alongside provider metadata. `get_webi_document_snapshot`
captures report/provider summaries and details plus each report's elements in
one local snapshot; opt in to provider query plans/specifications with
`include_provider_query_metadata=True`. See the advanced migration reference
linked from the README for the schema/example.
Captured plans may contain sensitive SQL. The CLI does not import the snapshot
and it does not establish report-to-provider links; the Python-only
`bo_export.webi_snapshot_adapter.extract_webi_snapshot(snapshot, connection)`
maps verbatim single-statement SQL plus one explicitly declared SQL Server
connection (name, server, database; no credentials) to the 15 collections,
inferring no columns or layout, so generation produces a model with an empty
report shell, not source visuals.
`include_element_details=True` requests SAP's `allInfo` option, available from
BI 4.2 SP04; live version and permission compatibility remain unverified.

For an `.lcmbiar` export, `python migrate_lcm_inventory.py --manifest <file>
--output-dir <new dir>` reads only the readable `BusinessObjects.xml` metadata:
document → universe → connection-type links, Crystal prompts, WebI provider
IDs, and one unbound RDL skeleton per document (parameters default to `String`,
no data source or layout). It never reads connection strings, owners or values.
UNX components with an embedded `Cipher` member are CMS-protected: the extractor
warns and does not decrypt them. Data-bound output needs an authorized CMS or
verified exports.

For Desktop Intelligence, `python migrate.py report.rep --assess` prints the
existing partial pre-migration report as JSON without writing an inventory.
Optional `-o assessment` requests exclusive creation of a new
`<stem>_deski_assessment.json`; empty directory values are rejected.
`--dry-run` writes nothing. Only applicable assessment options are accepted.
SQL text, formula expressions and literal prompt/variable arguments are omitted,
but names and other metadata can still be sensitive. Runtime checks remain
`not_run`.

For Desktop Intelligence, the experimental local `python migrate_deski_inspect.py
--source <report.rep> --output <new.json>` inventory is under implementation.
It reads REP ZIP, including prefixed ZIP, or OLE via Windows Structured Storage
on Windows. It inventories partial candidates for sheets, providers, objects,
SQL, formulas, literal prompt/variable arguments in SQL and structural markers.
Unsupported containers are rejected; encountered non-UTF-8 strings and
unsupported internal formats are flagged. A recognized `Query;` header may name
a possible universe, not a verified universe or connection. The output must be
a new JSON file.

Optionally supply `--migration-report <new.json>` and/or
`--html-report <new.html>` for a local pre-migration summary. Candidate counts,
SQL selectors, review actions and `not_run` checks apply only to this
inspection; zero matches do not establish absence and no fidelity score is
assigned. The reports omit SQL text, literal prompt/variable arguments and
formula expressions, but their names and other metadata can be sensitive.
Keep every output local and protected; sanitization is not guaranteed. The
inventory is still written separately and may contain sensitive SQL. All
outputs must be new; failed writes attempt cleanup and report cleanup failures.

The reader opens selected metadata streams, not data-cache or macro streams,
but hashes the whole source as raw bytes; it executes no macros and does not
refresh. Keep the JSON local, protected and out of version control: SQL and
metadata can be sensitive, and sanitization is not guaranteed. The inventory
does not enable automatic REP-to-PBIP generation and does not verify
report-to-provider links. Its JSON object is not the VBA export's list and
cannot be passed directly to `--rdl-extracted-sql`. Separately,
`migrate_paginated.py --bo-source <report.rep> --sql-name <provider-or-unresolved@offset>`
can generate an RDL only with the explicit
`--accept-unverified-rep-sql` acknowledgement and a manually declared SQL
Server mapping. This does not authenticate or validate the candidate SQL,
provider association, source type, connection, fields or equivalence. BO
variables remain unresolved. The manual mapping may also declare page
dimensions, column widths, basic styling and SQL parameter prompts, but these
are not extracted REP layout or BO prompt semantics. Independently review SQL,
bindings, completeness and equivalence. The advanced migration reference
linked from the README describes an eight-file
local count replay and separately reported byte-framing observation; neither
establishes source authenticity, rendering or equivalence.

For Desktop Intelligence XI 3.1, the optional
`examples/desktop_intelligence_export.bas` is an experimental VBA macro for
capturing active-document provider SQL into the existing extracted-SQL list.
`python migrate_deski_inspect.py --check-sdk` checks 32-bit and 64-bit
Windows COM registry entries without activating the client; it does not
verify login, licensing, document access or SDK functionality.
The macro has not been tested with a real Desktop Intelligence client or `.rep`.
Review the macro, SQL, connection and fields, then use the advanced reference's explicit
RDL mapping and exact SQL-name selector. The macro does not parse `.rep`, recover
layout or establish report/query linkage. Capture status must be `captured`
with integer `sql_error` zero; this does not authenticate the inventory.
BO prompt conversion in the RDL handoff remains unsupported.

For a separately declared paginated target with a reviewed mapping,
`python migrate.py --rdl-mapping mapping.json` infers RDL only when
`--output-format` is omitted and defaults to a new sibling `mapping.rdl`;
`--rdl-output` can select another new file. Use trusted output directories.
Single-mapping `migrate.py --output-format rdl`
requires `--rdl-mapping` and `--rdl-output`, and accepts no positional BO file
or other migration options. It generates the same basic table as `migrate_paginated.py`;
optionally `--rdl-sql-name` selects one SQL entry from a previously extracted
`custom_sql.json` via `--rdl-extracted-sql`, or supported local `.wid`, `.unx`
or `.unv` metadata via `--rdl-bo-source`. Crystal `.rpt` input is scanned
heuristically for SQL-shaped readable text and exposes the synthetic name
`CommandSQL`; this is not proof of a Crystal Command object or complete query.
The explicit SQL Server mapping
omits `sql` and may declare literal business labels separately from SQL fields.
Alternatively, `--rdl-webi-plan` accepts a saved WebI API plan with exactly
one direct SQL statement and a `webi` mapping without `sql`; it cannot be
combined with `--rdl-extracted-sql` or `--rdl-sql-name`. The optional
`--rdl-bo-source` in this mode checks only that the WID contains one matching
provider ID, not document identity or report-to-query linkage. Review the SQL,
connection and fields independently. See the advanced reference's schema, synthetic
examples and reproducible command.
Manual SQL and DAX mappings also accept declared BO source labels `crystal`,
`lumira`, `desktop_intelligence`, `xcelsius`, and `analysis_olap`; this does
not add parsers or automatic report conversion. Direct source selection accepts
`.wid`, `.rpt`, `.unx`, `.unv` and experimental `.rep`. A `.rep` candidate
requires `--rdl-accept-unverified-rep-sql`, an exact selector and a manual
SQL Server mapping; that single-source flag is not accepted in folder mode.
For RDL-only or combined PBIP/RDL folder mode, each `.rep` entry selecting a
candidate must set `"accept_unverified_rep_sql": true`.
Crystal selection uses heuristic readable-text SQL candidates; inspect the exact
selected query before using it.
`--rdl-power-query-output` can additionally write a new `.m` expression for the
same validated SQL Server query; it does not apply the RDL column labels.
Both outputs are local and must be new. Review native SQL and configure
credentials separately. PBIP is for standard Desktop; Desktop for Report Server
does not support PBIP and requires manual reconstruction from the M query and
an RS-compatible PBIX. RDL remains a separate Report Builder/SSDT path.
The source type must match the mapping. This does not convert BO report layout or business
semantics, or verify extraction completeness or report-to-query linkage.
Screenshots, rendering, query execution and source equivalence are not verified.
For a folder target, use `python migrate.py <folder> --output-format rdl
--rdl-batch-config <config.json>` instead. Supply a mapping per source, with
an optional exact SQL name and optional SQL-only Power Query output. A `.rep`
entry with `sql_name` must additionally declare
`"accept_unverified_rep_sql": true`; the batch manifest retains an explicit
unverified-candidate warning. A combined PBIP and RDL folder run can also
generate a basic PBIP table draft when the REP entry includes a `pbip`
declaration with a connection name, query name, schema and typed columns
matching the RDL field list. This remains a manual review draft; recognized BO
SQL function markers block its PBIP target, and source layout, prompts,
formulas, provider links and equivalence are not recovered. The declaration is
not supported for Fabric output. Generated PBIP drafts receive a local static
artifact check: validation errors fail only the PBIP target, while RDL remains
independent; warnings do not block. This does not execute SQL or prove Desktop
rendering or equivalence, and failed generated files may remain for diagnosis.
Without the declaration, the REP PBIP target fails explicitly. RDL batch does
not convert BIAR contents and fails archive entries explicitly. See the
advanced reference for the config contract; the positional output directory
must be new or empty.

## CLI Examples

Run from the repository root using the selected project interpreter:

```powershell
python migrate.py --help
python migrate.py --help-all
python migrate.py examples/Enterprise_Sales.wid --assess
python migrate.py examples/Enterprise_Sales.wid --dry-run
python migrate.py sources --output-dir artifacts/bo-sales
python migrate.py sources --output-format fabric --output-dir artifacts/bo-fabric
python migrate.py examples --output-dir artifacts/bo-folder
python migrate.py --batch examples --output-dir artifacts/bo-batch
python migrate.py --biar examples/Enterprise_Export.biar --output-dir artifacts/bo-biar
python migrate.py --shared-model examples/Enterprise_Sales.wid examples/Financial_Report.wid --model-name Sales
python migrate.py --validate-project artifacts/bo-sales --quality-output artifacts/quality.json
python migrate.py --validate-project artifacts/bo-fabric --quality-strict
python -m powerbi_import.mcp_server --list
```

These are BO flag-based entry points. Do not copy Tableau's `batch`, `fabric`, `quality`, or `parity` subcommands.
`--assess` is assessment-only; an explicit output directory saves the assessment JSON.
`--dry-run` performs inspection using temporary extraction and leaves no persistent outputs.
BO generation through the main CLI and local MCP `migrate` requires a directory;
individual report files remain valid for assessment, not generation. Archive,
shared-model and separately declared RDL paths remain distinct.
Batch outputs are isolated by relative source filename and include `batch_manifest.json`;
partial failures return a nonzero exit code with per-source diagnostics. Unsupported
extensions and symbolic links are logged and listed as skipped, not migrated.
Positional folder/BIAR outputs must be new or empty; legacy PBIP/Fabric `--batch`
can reuse an output and may overwrite existing artifacts. Duplicate archive entry
base names are rejected before generation.
Shared-model merging retains isolated source tables and their known schema,
connection, and provenance. Same-named distinct physical sources require explicit
mapping and are rejected before generation; do not override this by assuming a
connection or dropping a source. Direct Lake date enrichments need upstream
materialization, unlike the Import path's automatic Calendar/date parts.
BIAR uses temporary file extraction and the same generation API as individual sources.
Only directly named supported artifact entries are recognized; an archive with
no recognized entries returns an error without creating a migration output.
Embedded/segmented content and archive completeness remain unverified.
Fabric outputs are quality-gated after generation. Blocking findings return code
6 for file/BIAR/batch/shared-model CLI workflows and preserve per-project
`quality_report.json`; warnings alone do not block unless a separate strict
validation is requested. A generated directory is not sufficient success evidence.
CSV/Excel ingestion belongs to Notebook, connected sources/custom SQL to Dataflow,
and calculated-column materialization to the single primary ETL notebook. Inspect
the persisted ingestion/materialization plan and the actual validation findings.
Do not pass credentials in command examples or chat; use the supported secure authentication mechanism after reading the relevant client.

## Separate BW Historical Landing

`migrate_bw_assess.py` evaluates declared BW 1.0 inventory coverage against the
BW-0 review gate. It emits blockers and review items from a local snapshot; it
does not discover SAP objects, verify owner attestation, or close the gate.
The resulting `candidate_for_owner_review` status is not migration readiness.
The partial BW-0, BW-5, BW-6, BW-7 and BW-8 assessments write reports and exit
`1` while blockers remain; `0` means declarations are ready for owner review,
not approved, and `2` indicates an input or output error. Use new output paths.

`migrate_bw.py` generates an unbound Bronze notebook from a BW 1.0 inventory
and an explicit plan for already-staged Parquet files; it does not invoke the
BO CLI or the local MCP server. See `docs/SAP_BW_TO_FABRIC_DESIGN.md` for the
plan, checks, restrictions, and synthetic example. This local slice is not SAP
extraction, a full BW warehouse migration, runtime reconciliation, or retirement.
Use `fabric-mcp-routing` and the installed `spark-cli` authoring procedure for
notebook work; binding, deployment and execution need separate authorization.

`migrate_bw_handoff.py` evaluates a local, normalized snapshot-to-delta manifest
against its explicitly declared contiguous-integer position semantics. It is
not a connector or proof of source guarantees, production restart recovery,
Fabric operation, or BW retirement; see the design's BW-3 boundaries.

`migrate_bw_convert.py` generates an unbound Fabric notebook for an explicitly
normalized, declared-complete BW transformation:

```powershell
python migrate_bw_convert.py `
    --inventory "docs\fixtures\sap_bw_conversion_inventory.example.json" `
    --transformation "docs\fixtures\sap_bw_conversion_plan.example.json" `
    --output "bw_transform.ipynb"
```

The bounded rules are exact-type field transfer, typed string/boolean/integer
and exact decimal-string constants, and same-scale decimal add/subtract with
explicit null propagation. Decimal constants reject rounding or overflow.
Selected-object or
ambiguously scoped unknowns, unsupported selected features, selected-object
functions and additional incoming transformation dependencies block generation.
An optional paired `--definition-file` and `--rule-ledger` preflight checks
the supplied file's SHA-256 and matches plan source-rule IDs and mappings
against the declared ledger. Existing plans without IDs work in declaration-only
mode. Neither mode authenticates SAP origin or proves the ledger's source
coverage. It does not parse SAP metadata or ABAP, execute a DTP, establish
equivalence, or run Spark. Read the BW-4 contract in
`docs/SAP_BW_TO_FABRIC_DESIGN.md`; use `fabric-mcp-routing` and `spark-cli`
authoring for notebook work. Deployment and execution require separate approval.

`migrate_bw_transform_validate.py` compares declared source golden vectors and
target output vectors with explicit exact or decimal-tolerance rules. It does
not parse ABAP, execute generated Spark transformations, verify how either set
of values was produced, or prove semantic equivalence. Optional paired
`--inventory` and `--transformation` arguments bind the vector suite's
transformation identity, input field names and business output targets to the
normalized conversion plan. In linked mode, it locally evaluates only the
supported normalized transfer, typed constant and same-scale decimal
add/subtract rules against declared inputs and checks the computed values
against `expected_output`. Plan-valid Spark types outside the local evaluator
subset remain `not_run`; the CLI rejects invalid conversion-plan types before
report generation. When evaluation runs, `input_validation_scope` is
`referenced_rule_inputs_only`: unused input values are not type-checked.
Otherwise the scope is `not_run`. This does not authenticate vector provenance
or establish source/Fabric execution. A successful CLI exit does not imply that a
`not_run` evaluation ran or passed.
The CLI can also run the source-declaration preflight with vectors, both
plan-linkage inputs, and both source-declaration inputs:

```powershell
python migrate_bw_transform_validate.py `
    --vectors "docs\fixtures\sap_bw_conversion_vectors.example.json" `
    --output "bw_conversion_preflight_report.json" `
    --inventory "docs\fixtures\sap_bw_conversion_inventory.example.json" `
    --transformation "docs\fixtures\sap_bw_conversion_plan.example.json" `
    --definition-file "docs\fixtures\sap_bw_conversion_definition.example.txt" `
    --rule-ledger "docs\fixtures\sap_bw_source_rules.example.json"
```

`--inventory` and `--transformation` must be supplied together;
`--definition-file` and `--rule-ledger` must also be paired and require the
plan inputs. `source_declaration_preflight.status` is separate from vector
comparison, plan-linkage and normalized-rule-evaluation status. With both pairs, it is `pass` only when
the definition check and plan-versus-ledger check pass; source authenticity and
ledger-to-source correspondence remain `not_verified`, and source-owner
approval remains `not_run`. Standalone and plan-linked-only reports default
preflight status and both declaration checks to `not_run` (with authenticity
and correspondence `not_verified` and approval `not_run`).

This preflight reuses `build_bw_conversion_notebook` for local validation but
does not write or execute a notebook. Deterministic results are limited to the
supplied declarations, definition bytes and vector values. Matching statuses
do not prove SAP authenticity, rule completeness, source-to-ledger
correspondence, vector provenance, source/Spark/Fabric execution, equivalence,
or business approval.
See the BW-4 boundaries.

`migrate_bw_bex_assess.py` checks a local BEx semantic-capture manifest against
a BW inventory, including BW-0 review blockers and query-to-consumer links. It
reports only gaps found in those local declarations; it does not parse BEx,
generate target models/reports, execute queries, compare results, or approve
consumers. See the BW-5 boundaries.

`migrate_bw_controls_assess.py` checks a local BW-6 security, planning and
compliance manifest against a BW inventory:

```powershell
python migrate_bw_controls_assess.py `
    --inventory "docs\fixtures\sap_bw_inventory.partial.example.json" `
    --controls "docs\fixtures\sap_bw_controls.partial.example.json" `
    --output "bw_controls_assessment.json"
```

This is an offline declaration review only. It checks inventory-linked
authorization contexts, declared allow/deny test cases, planning/write-back
control coverage, and audit/retention/privacy/legal-hold references. Access
test execution is fixed to `not_run`; the CLI does not execute target security,
identity/binding, planning, compliance or Fabric operations. A
`candidate_for_owner_review` is not approval and does not close BW-6 or
authorize retirement.

`migrate_bw_wave_assess.py` indexes declared per-object BW-2 through BW-6
evidence and wave-level operational references against the BW inventory:

```powershell
python migrate_bw_wave_assess.py `
    --inventory "docs\fixtures\sap_bw_inventory.partial.example.json" `
    --evidence "docs\fixtures\sap_bw_wave_evidence.partial.example.json" `
    --output "bw_wave_assessment.json"
```

The evaluator checks scope, required layer/operations declarations, status
consistency and exception links. It preserves those declarations in the output
but does not open or verify referenced report bytes, establish freshness or
correctness, execute/certify runtime controls, or approve retirement. A BW-0
review status of `open` or applicable `not_run`/failed evidence keeps the wave open;
`candidate_for_owner_review` is not acceptance, and `gate_closed` remains false.
SAP/Fabric runtime checks remain `not_run`.

`migrate_bw_cutover_assess.py` evaluates one BW-8 declaration set against a
local BW inventory and BW-7 evidence manifest:

```powershell
python migrate_bw_cutover_assess.py `
    --inventory "docs\fixtures\sap_bw_inventory.partial.example.json" `
    --wave-evidence "docs\fixtures\sap_bw_wave_evidence.partial.example.json" `
    --cutover "docs\fixtures\sap_bw_cutover.partial.example.json" `
    --output "bw_cutover_assessment.json"
```

It checks declaration coverage, dependency dispositions, upstream-feed status,
planning/retention sign-off, reconciliation thresholds, parallel-run and
BW-independent observation periods, rollback plan/exercise declarations, and
explicit owner acceptance of BW-0 through BW-7. It does not authenticate or
dereference evidence. Only direct inventory edges incident to the wave and
consumers at their endpoints are checked; transitive dependencies and coverage
completeness remain unverified. It does not execute
cutover/rollback, switch consumers, shut down BW, or authorize retirement.
`declarations_complete_for_owner_review` leaves `gate_closed`,
`cutover_authorized` and `retirement_authorized` false; runtime evidence stays
`not_run`.

## Ownership

| Surface | Agent | Source |
|---------|-------|--------|
| CLI, batch, pipeline coordination | Orchestrator | `migrate.py`, BW CLIs including `migrate_bw_wave_assess.py` |
| Cross-cutting WebI-to-Power BI migration | WebI Migration | Coordination only; existing source, target and evidence owners remain responsible |
| Local BO extraction and adapter | Extractor | `bo_export/` parsing modules |
| BO CMS/server client | BusinessObjects | `bo_export/server_client.py` |
| BO formulas to DAX | Dax | `bo_export/dax_converter.py`, `powerbi_import/dax_optimizer.py` |
| Power Query and column classification | Wiring | `bo_export/m_query_builder.py`, `powerbi_import/m_query_generator.py`, `powerbi_import/calc_column_utils.py` |
| Semantic model | Semantic | TMDL generator modules |
| PBIR report | Visual | `powerbi_import/pbip_generator.py` and visual generators |
| Fabric bundle | Fabric | `powerbi_import/fabric_project_generator.py` and its five sub-generators |
| Staged BW Bronze notebook | Fabric | `powerbi_import/bw_bronze_generator.py` |
| Normalized BW transformation notebook | Fabric | `powerbi_import/bw_transform_generator.py` |
| BW-6 security, planning and compliance declarations | Assessor | `powerbi_import/bw_controls_assessment.py` |
| BW-7 wave evidence index | Evidence | `powerbi_import/bw_wave_evidence_index.py` |
| BW-8 cutover/retirement declarations | Evidence | `powerbi_import/bw_cutover_assessment.py` |
| Publishing and refresh | Deployer | `powerbi_import/deploy/` |
| Tests | Tester | `tests/` |
| Local MCP transport, contracts, handoffs | AgentTools | `powerbi_import/mcp_server.py`, `.vscode/mcp.json` |
| Quality reports and comparisons | Evidence | `powerbi_import/migration_quality.py`, comparison/evidence modules |
| Recovery ledger and bounded repair | Healing | `powerbi_import/recovery_report.py`; shared repair sections with their primary owners |
| Optional LLM and patterns | AI | `powerbi_import/llm_client.py`, `powerbi_import/marketplace.py` |
| HTML presentation | Web Designer | `powerbi_import/html_template.py` |

The complete primary-owner map and intentional collaboration boundaries are in
`.github/agents/ownership.json`. Planning belongs to **Roadmap Planner** in the
existing development plan; **Documentation Guardian** reviews changed claims.
Use the exact frontmatter names for delegation, including spaces in those names.

## Local MCP

The workspace configuration launches the six-tool local engine in read-only mode.
Use `inventory`, `assess`, and `quality_report` before considering generation.
For DeskI `.rep`, `inventory` lists local files and `assess` returns only the
partial pre-migration summary, without raw SQL, formula expressions or literal
prompt arguments. This is inspection only; keep the metadata protected.
Local `migrate` and `shared_model` require server `--allow-write`, per-call
`confirm=true`, and a new or empty output directory within the configured root.
This server never deploys to Fabric. Read `docs/FABRIC_MCP_SETUP.md` before enabling writes.

## Evidence

Successful generation is not Desktop openability, visual parity, refreshed data, or successful Fabric execution.
Record what ran, against which source/target, its status, and what remains `not_run`.
Copilot agents are development roles; do not claim the CLI automatically invokes them.

<!-- demo-studio:integration:start -->
For requested demos or presentations, follow [the Demo Studio guide](../../../docs/DEMO_STUDIO.md); this Skill's domain rules, tool restrictions and evidence gates remain authoritative.
<!-- demo-studio:integration:end -->
