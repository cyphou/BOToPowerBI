# Changelog

## [Unreleased]

### In progress
- **2026-11-24 evidence snapshot:** 1 294 tests passed, 1 skipped and
  1 547 subtests passed; coverage reached 80.73%. The synthetic linked
  BEx/InfoCube PBIP passed strict static validation with 0 errors and 0
  warnings, and direct CSV reconciliation found 0 mismatches across 2
  synthetic observations. The synthetic Enterprise Sales WebI batch generated
  successfully with 13 static warnings. Hosted CI, SAP/CMS, Desktop, refresh,
  Fabric runtime and business acceptance remain `not_run`; native identity
  and equivalence remain `not_verified`.
- Semantic safety fixes now resolve duplicate-table relationship endpoints by
  actual table/column membership and fail closed for ambiguous or missing
  columns. Four-argument DAX `SUBSTITUTE` is rejected instead of being
  silently converted to all-occurrence `Text.Replace`; three-argument behavior
  remains unchanged. Focused semantic and E2E tests pass; repository-wide
  Ruff/Pyright gates remain separate open work.
- Owner-scoped static cleanup removed dead compatibility imports, corrected an
  optional-parameter annotation and cleaned the conversion adapter: Ruff moved
  from 392 to 387 diagnostics and Pyright from 72 to 71 errors. The full local
  suite remains green; hosted CI is still not run.
- Added a reproducible [linked BEx and InfoCube pilot](docs/MIGRATION_REFERENCE.md#linked-bex-and-infocube-pilot)
  using a synthetic BW inventory 1.0, BEx manifest 1.2 and plan 1.6. It produces
  a local single-cube Import PBIP with typed physical columns, a review table,
  M copies and linkage evidence; it does not translate BEx semantics.
- The pilot now includes a [synthetic reconciliation replay](docs/MIGRATION_REFERENCE.md#replay-the-synthetic-result-comparison)
  for two day-level observations and one deliberately changed quantity.
  It uses the existing offline comparator and does not query SAP or Power BI.
- BEx reconciliation can now verify vector declarations against a linked
  InfoCube plan, BW inventory and BEx manifest. Linked reports use version 1.1;
  mismatched declarations are rejected, and zero observations fail the linked
  CLI without changing `comparison_status`. Vector input and standalone
  report 1.0 are unchanged. This does not verify native SAP
  identity or a generated PBIP.
- A [BEx CSV packager](docs/MIGRATION_REFERENCE.md#prepare-vectors-from-two-csv-captures)
  maps two prepared UTF-8 CSVs to the existing vector schema with one text key
  and one exact key-figure rule. Packaging is separate from comparison and
  does not execute queries or verify where exports came from.
- [Direct CSV reconciliation](docs/MIGRATION_REFERENCE.md#compare-two-csv-captures-directly)
  reuses that mapping and the linked InfoCube checks in one command. It writes
  only the existing linked report 1.1, without a separate vector JSON file.
- Added `migrate_bw_bex_pilot.py`, a local one-command orchestrator for the
  declared BEx/InfoCube pilot: it snapshots inputs, generates the PBIP in
  staging, validates static quality, compares CSV captures and publishes a new
  evidence directory. A single `--bundle` JSON now supplies those paths for the
  simple invocation; individual flags remain for diagnostics. It performs no
  SAP, Power BI or Fabric runtime operation.
- Added the [live BO BEx metadata and independent PBIP draft](docs/MIGRATION_REFERENCE.md#live-bo-bex-metadata-and-independent-pbip-draft)
  workflow. It uses an externally provisioned preauthenticated token, fetches
  connection and outline metadata, and generates a review-only PBIP from an
  unlinked plan. The report counts literal unnamespaced outline items; it does
  not retain the outline or verify plan correspondence, provenance or BEx
  equivalence. It does not extract source data or run the target.
- Console `pytest` now collects local packages without requiring an installed
  checkout or `PYTHONPATH`. The test-only change leaves assertions and the
  80% coverage threshold unchanged.
- BW cube PBIP generation now preserves explicitly named `Unknown` tables,
  writes physical source aliases as TMDL text properties and escapes the shared
  BW server expression. Before exporting M or writing linkage evidence, it
  rejects a missing or mismatched table reference, physical columns or Import
  partition. No plan versions or manifest versions changed. Native identity
  remains `not_verified`; SAP and Desktop execution, refresh and equivalence
  remain `not_run`.
- BEx semantic manifest 1.2 now requires `provider_key_figure_bindings` and a
  `kind` (`basic`, `restricted`, `calculated` or `unknown`) on every key
  figure. Assessment report schema 1.1 adds `key_figure_kinds` entries
  (`key_figure_id`, `declared_kind`, `declaration_boundary`, `assessment`) and
  verification identity, provenance and equivalence fields set to
  `unverified`. Manifests 1.0/1.1 retain their prior acceptance and report
  schema/output shape 1.0; CLI help lists all three manifest versions. Kinds
  are local declarations only: `basic` does not prove additive/`SUM` or
  aggregation-safe behavior, `restricted` records no restrictions,
  `calculated` records no formula/dependencies, and `unknown` remains
  unresolved. No kind generates DAX or measures; gates are unchanged,
  `gate_closed` remains false and runtime statuses remain `not_run`. SAP
  source truth, provenance and equivalence remain unverified; no SAP execution
  is claimed.
- The offline BEx result-vector comparator now adds
  `no_measure_observations_compared` when `summary.measures_compared` is zero.
  After a successful report write, the CLI prints
  “No measure observations were compared; this result does not establish
  measure agreement.” This notice does not alter `comparison_status` or
  standalone exit behavior (two empty vectors remain `pass`/0). Runtime evidence
  `not_run` and verification `not_verified` are unchanged.
- `PBIWorkspaceDeployer.deploy_rolling` is intentionally disabled and returns
  `status: failed`, `phase: blocked` and `rolled_back: false` without remote
  operations. The previous implementation could overwrite canaries and falsely
  claim rollback while calling the nonexistent `PBIServiceClient.delete_dataset`.
  This change implements neither deployment nor rollback and leaves previously
  created remote artifacts untouched. Mocked tests verify the local guard; the
  ordinary `deploy_project` path remains separate, requires explicit
  authorization and is unverified.
- `PBIWorkspaceDeployer.deploy_refresh_schedule` now skips `None` with a note
  and disabled drafts, and rejects non-dictionaries, missing or non-boolean
  `enabled`, and invalid enabled declarations before the client call. Enabled
  schedules require explicit unique valid weekdays, nonempty valid `HH:MM`
  times and a nonempty time zone. Optional `frequency` is `Daily` or `Weekly`;
  `Daily` requires all seven days. Optional `notifyOption` is
  `NoNotification` or `MailOnFailure`. The request forwards only schedule
  fields and a supplied notification, not frequency metadata. Previously,
  incomplete enabled configurations could send invented `UTC`, `06:00` and
  `MailOnFailure` values, and `None` raised `AttributeError`.
  Local format validation and mocked requests do not establish owner review,
  policy or permissions, service or time-zone acceptance, refreshed data, or
  source/target equivalence. A remote operation requires separate
  authorization; Desktop rendering, deployment, refresh and Fabric execution
  remain `not_run` without separate evidence.
- The CI validation job now migrates a synthetic `Enterprise_Sales.wid`
  folder, checks PBIP and semantic-model existence, and runs local static
  validation. Errors fail the job; warnings are displayed but permitted. A
  local equivalent on 2026-11-22 passed with 13 warnings, including four
  unknown visual Entity `"Table"` references. On that date the configured
  repository-wide Ruff and Pyright checks on the dirty worktree failed with
  422 errors and 75 errors/two warnings respectively. A later baseline
  comparison is recorded in the development plan. Targeted
  ledger/refresh/permission checks passed. GitHub-hosted CI
  for this change, Desktop rendering, refresh and Fabric execution remain
  `not_run`; this does not establish visual binding or parity.
- Added a standalone offline feature-coverage declaration ledger. It validates
  supplied declarations and reports counts and review findings; exit `0`
  means only declaration validation ran, and output must be new. It does not
  open references, execute declared checks, extract sources, compare runtime
  results or integrate with cloud or `quality_report`. Declared statuses are not
  observations; source identity and completeness, provenance, evidence
  authenticity, equivalence and approvals remain unverified. Runtime remains
  `not_run`. Manifests and reports can contain sensitive metadata.
- Schedule and subscription generation now produces disabled review drafts,
  not verified Power BI payloads. Missing times, days, time zones and
  frequencies are not defaulted; invalid times or days and unsupported
  frequencies are not guessed. Declared time zones are not target-validated;
  multiple schedules are not combined.
  Non-list scheduled-instance inputs other than `None`, and a single non-object
  task, log a warning and return a disabled draft with an invalid-input note
  instead of raising into the CLI's debug-only catch.
  Malformed referenced schedule collections or items likewise produce a
  disabled draft with an invalid-lookup note. Non-list subscription inputs
  other than `None`, including falsy malformed values, raise `ValueError` in
  both subscription and combined refresh generation.
  In the selected schedule details, non-dictionary `intervals` and additional
  keys in that dictionary are noted for review; so are nonempty weekday
  declarations for non-Weekly frequencies. Recipients, identities and Power BI
  equivalence require manual review. `deploy_refresh_schedule` skips disabled
  drafts. Previously generated files are not retroactively updated; reusing
  the output directory can overwrite `refresh_config.json`. No live execution
  or deployment is established.
- The standalone security profile mapper now requires nonempty restrictions,
  a unique case-insensitive match to a declared column, and an explicit
  supported operator with a nonempty list of strings of the required arity. It
  escapes names and literals in candidate DAX. Empty restrictions, missing
  or ambiguous columns, unsupported operators, and invalid value lists or
  arities raise `ValueError` instead of being guessed or dropped. The returned
  shape and legacy operator mappings for accepted inputs remain; this is not
  proven semantic conversion, target RLS assignment or end-to-end migration.
- The RLS PowerShell generator now writes a terminating manual-review reminder,
  not an assignment script. The previous script called the dataset users
  endpoint without a role and did not assign RLS membership. Previously
  generated scripts are not retroactively replaced and should not be run.
  Review source restrictions, identities and target roles with the security
  owner; assign membership manually and test allowed and denied access in an
  authorized environment. Generated metadata does not prove security
  equivalence.
- BW-6 controls 1.1 can declare owned target dispositions for Copy Version,
  Upload File, cube activation, planning reporting, Forecast Update and
  consolidation/aggregation. Complete 1.1 coverage requires all six entries;
  in-scope records need owner, target and evidence, and execution remains
  `not_run`. Controls 1.0 manifests remain compatible, and no Power Apps,
  Talend, SQL or planning workflow is generated.
- BW cube plan 1.6 optionally creates one manually declared PBIR review table
  from exact model columns, in the specified order and within the page. The
  default remains an empty report; earlier plans reject the option. The table
  projects columns without new DAX measures or totals, and Power BI may group
  identical values. It is not a BEx report conversion or parity evidence.
  BW `migration_metadata.json` now identifies the declared cube plan as its
  source rather than Tableau and records a versioned
  `sap_bw_capability_boundary` that distinguishes local partial support from
  external Power Apps, Talend/SQL, planning and runtime/equivalence work.
- BO generation now automatically attempts expression review exports for
  folder/BIAR, shared-model, Python importer, local MCP and opt-in REP PBIP
  workflows. The BW cube PBIP CLI does so after static validation. M
  partitions, shared/refresh expressions and Fabric Dataflow `.m` queries
  are copied to `.pq`; only TMDL measures, calculated columns/partitions,
  calculation items and RLS filters actually written are listed in `.dax`.
  Manifest 1.1 has an empty `exports` list when nothing is exportable.
  Ordinary folder items other than BIAR or REP export after the optional DAX
  optimizer and, for Fabric, the quality check; BIAR/shared exports precede
  their Fabric quality check. A blocked bundle is not deployment-ready.
  `python -m powerbi_import.expression_export` remains available for an
  existing generated model, with optional `--include-dataflow`. Existing
  targets, collisions and unsupported recognized syntax fail; errors can
  leave partial files. SQL and parameter values can be sensitive. The export
  does not invent BEx calculations or prove static validation, execution or
  parity.
- The BW-5 BEx assessment now reports direct query-to-provider dependencies
  and blocks missing or unverified links, blocked queries and providers,
  unsupported provider features,
  and unobserved InfoCube metadata, keys or semantics. It does not discover
  SAP lineage, convert BEx/InfoCubes, or establish source-to-target parity.
- The BW-5 BEx assessment now requires an observed inventory definition with a
  matching SHA-256 digest; this checks local declarations, not SAP authenticity.
- The BW-5 BEx assessment now blocks directly linked InfoCubes with no
  declared keys or keys whose roles remain unknown; this does not validate
  business grain.
- BEx manifest 1.1 adds explicit key-figure-to-provider-measure bindings;
  unresolved or unobserved links block the assessment. Formula conversion is
  still unsupported. Legacy v1.0 manifests remain accepted and report that
  their provider-measure bindings were not assessed. The report now exposes
  per-key-figure binding resolution status.
- The SAP BW Power Query builder now uses all required connection arguments
  and supports explicitly declared InfoArea, cube, dimension and measure
  navigation. A synthetic end-to-end PBIP test covers the Import model and
  empty report shell; invalid BW query declarations now propagate as errors
  rather than being reported as successful generation. It does not discover
  SAP metadata or convert BEx semantics.
- BW cube plan 1.4 optionally emits explicitly declared text arguments as
  `Cube.ApplyParameter` operations after cube navigation and before dimension
  and measure projection. It preserves argument order and list shape, but
  does not map BEx variables or verify SAP semantics, parameter compatibility,
  folding or results. Literal arguments are present
  in the plan and generated model; protect them and never include secrets.
- BW cube plan 1.5 can associate an explicitly declared cube parameter with a
  BEx variable ID from the linked local manifest. The linkage report records
  selected/unselected variable declarations but omits values. It does not
  translate prompt defaults or selection behavior, verify SAP selectors, or
  establish parameter equivalence; BEx counts remain reported as unconverted.
- BW cube plan version 1.3 optionally selects explicitly declared dimension
  member properties, including manually specified key properties, via
  `Cube.AttributeMemberProperty`. Each property is mapped to a declared
  Import-model column; selectors, types and results are not verified in SAP.
  Versions 1.0-1.2 retain their previous plan shapes. BW-only models no longer
  receive inferred automatic Calendar tables, date relationships or Gregorian
  date-part hierarchies; non-BW models retain existing date enrichments.
- `migrate_bw_bex_pbip.py` generates a statically validated Import PBIP draft
  from a strict plan for one manually declared BW cube. The plan rejects
  unknown/credential fields, server URLs/userinfo, unsafe project names and
  mismatched output columns; validation warnings remain non-blocking. The
  synthetic example is not SAP extraction, BEx conversion or runtime evidence.
- Plan version 1.1 can optionally link that PBIP draft to a local BW inventory
  and BEx semantic manifest. Generation then requires a BW-5
  `candidate_for_owner_review`, an observed direct InfoCube dependency and
  matching declared key-figure/provider-measure selectors; an optional
  dimension binding can also tie selected navigation selectors to observed
  InfoCube dimensions. Plan version 1.2 requires these bindings whenever BEx
  linkage is supplied; version 1.1 remains compatible when they are omitted.
  Generation writes the offline assessment to `bex_linkage_assessment.json`.
  The declared SAP client must also match the inventory source client. Version
  1.0 remains supported without linkage. These checks do not verify SAP
  metadata or close BW-5. The linkage evidence explicitly reports native
  InfoCube identity verification as `not_verified`.
- Linked cube PBIP evidence now lists selected and unselected declared BEx
  key-figure IDs and copies each selected figure's declared aggregation,
  exception-aggregation and unit/currency fields alongside its target selector
  and column. Omitted figures produce a non-blocking warning. This is a
  manifest-only review aid; it does not interpret semantics or generate DAX.
  When dimension bindings are supplied, a bound InfoCube dimension name must
  resolve uniquely in the local inventory. These checks do not verify SAP
  metadata or convert BEx semantics.
- Linked PBIP generation now prints a non-blocking warning with the number of
  BW-5 review findings and the assessment report path when the assessment is
  `candidate_for_owner_review` but still contains review items. The findings
  remain owner-review work; the warning does not close BW-5 or authorize a
  source/runtime check.
- When BW-5 blockers prevent linked PBIP generation, the CLI error now includes
  the blocker count and up to three finding codes with JSON paths, plus a count
  of any remaining blockers. Refusal still occurs before PBIP output creation.
- Linked PBIP evidence now counts declared variables, filters, hierarchies,
  master-data items, key-figure semantics and authorization contexts that this
  draft does not reproduce. Non-zero counts produce a non-blocking warning.
  Counts describe only the local manifest; zero does not establish absence in
  SAP and no BEx behavior is converted by this report.
- Linked PBIP evidence now also copies the BEx manifest's declared coverage
  statuses beside those counts, distinguishing local `not_applicable`
  declarations from empty lists without treating either as verified SAP state.
- The TMDL generator now disables implicit summarization for all SAP BW
  source columns, including numeric dimensions and key figures. It does not
  infer DAX measures or BEx aggregation behavior; non-BW summarization defaults
  remain unchanged.
- Universe physical-table navigation now preserves a table's declared schema
  and escapes its schema and table names in generated Power Query M.
- PBIP generation without source visuals now creates an empty report shell
  referencing the semantic model instead of pointing the report descriptor at
  the model. Batch results warn that source visuals were not converted; an
  existing report is not overwritten by an empty shell.
- `migrate.py --help` shows common workflows; `--help-all` shows all options.
- Without an explicit `--output-format`, `--rdl-mapping map.json` infers RDL
  and defaults to a new sibling `map.rdl`. Explicit `--output-format rdl`
  still requires `--rdl-output`; the REP SQL acknowledgement remains mandatory.
- `migrate.py report.rep --assess` prints the existing partial pre-migration
  report as JSON. Optional `-o DIR` requests exclusive creation of
  `<stem>_deski_assessment.json`; `--dry-run` writes nothing, and empty
  directory values and non-applicable flags are rejected. SQL text, formula
  expressions and literal prompt/variable arguments are omitted, but metadata
  may be sensitive; runtime checks remain `not_run`.
- RDL and DeskI report outputs use exclusive creation: existing files and
  final-path symlinks, including dangling links on Windows, are rejected.
  Links in parent directories may still be followed.
- `migrate.py` switches stdout and stderr to UTF-8 when their known encoding
  differs and the streams support reconfiguration, covering output and
  diagnostics.
- `migrate_deski_inspect.py --check-sdk` checks 32-bit and 64-bit Windows COM
  registration without starting DeskI or connecting. It does not validate
  activation, licensing, CMS login, document access or extraction.
- Simplified the README around common workflows and parameters; detailed
  migration procedures and the full CLI reference remain available in
  `docs/MIGRATION_REFERENCE.md`. This documentation simplification did not
  change existing commands or options.
- The main CLI now routes a single `.rep` SQL candidate to the existing
  paginated generator with explicit `--rdl-accept-unverified-rep-sql`.
  This reuses the existing partial inspection and manual SQL Server mapping;
  it does not recover report layout or establish source/target equivalence.
- Folder batches can select a REP SQL candidate per source when its config
  explicitly sets `accept_unverified_rep_sql: true`. Combined PBIP and RDL
  batches can also generate a basic PBIP table draft when an exact per-source
  `pbip` declaration supplies connection, query, schema and typed columns.
  Recognized BO SQL function markers block the PBIP target. Both target
  outcomes remain separate in the manifest. The generated PBIP now runs
  through the local static artifact validator; errors fail only the PBIP
  target, while RDL retains its independent result. These drafts do not recover
  REP layout, prompts, formulas or source equivalence. Fabric output does not
  support this PBIP declaration.
- The local MCP `inventory` discovers DeskI `.rep` files, and `assess` returns
  their partial pre-migration summary without writing files or returning raw
  SQL, formula expressions or literal prompt arguments. DeskI generation
  remains outside the MCP workflow.
- `migrate_deski_inspect.py` can optionally write deterministic JSON and/or HTML
  pre-migration reports, alongside the required inventory. They identify
  partial candidates, unverified SQL selectors, stream-local references for
  detected formula candidates, design/prompt review actions and checks not run
  by this inspection, without a fidelity score. SQL text, literal prompt/variable
  arguments and formula expressions are omitted from the reports, but metadata
  may still be sensitive. Formula references do not establish completeness,
  source identity or formula semantics. All outputs must be new; failed writes
  attempt to clean up newly created files and report cleanup failures. This is
  not RDL/PBIP generation or source/target equivalence.
- `migrate_deski_inspect.py` provides an experimental standalone local DeskI
  `.rep` inventory, still under implementation. It reads ZIP, including
  prefixed ZIP, and OLE via Windows Structured Storage on Windows. It returns
  partial sheet, provider, object, SQL, formula, SQL literal-prompt/variable
  and structural candidates. Unsupported containers are rejected; encountered
  non-UTF-8 strings and unsupported internal formats are flagged. BO variables
  remain unresolved. A recognized `Query;` header may expose a source name as
  a possible universe, not a verified universe or connection.
- The reader opens selected metadata streams, not data-cache or macro streams,
  but hashes the whole source as raw bytes. It executes no macros, performs no
  refresh and generates no PBIP. A separate, gated
  paginated route can generate an RDL from one explicitly selected
  candidate and a manual SQL Server mapping. Declared styling and report
  parameters do not reconstruct REP layout or BO prompt semantics. The JSON
  must be a new file, kept local and protected because it may contain sensitive
  SQL and metadata. SQL, bindings, completeness and equivalence require
  independent review.
- The combined-folder PBIP option is an explicit table-report draft from one
  selected REP SQL candidate and caller-declared result columns. It is not
  automatic REP conversion; BO function markers block PBIP generation and
  report-to-provider links, layout, prompts, formulas and equivalence remain
  unverified.
- The 2026-11-18 eight-sample candidate counts were replayed locally for the
  report update; the prior byte-framing observation was not independently
  replayed. A separate manually declared RDL/M illustration and a one-sample
  direct REP-to-RDL pilot are described in the
  [gap analysis](docs/GAP_ANALYSIS.md); the pilot uses placeholder connection
  values and does not execute SQL.
- A second local RDL illustration manually rewrites one observed REP
  `@variable` to a declared multi-value SQL parameter; its connection, fields,
  prompt semantics and default layout remain unverified.
- SQL Server RDL descriptions no longer claim all credentials are absent:
  authentication is not configured, but query text may contain sensitive data.
- Local Windows tests passed for synthetic ZIP and OLE inputs; the
  non-Windows-only OLE error-path test was skipped. Full and focused test
  results and the three-file Ruff check are recorded in the gap analysis;
  they do not establish source type, runtime behavior or equivalence.

### Fixed
- Legacy notebook sessions now isolate and clean up their intermediate BO
  extraction instead of overwriting JSON in the repository source tree.
  Notebook assessment and preview limitations remain; use the supported CLI.
- PBIR visual resolution now preserves native stacked line-and-column combo
  charts instead of falling back to a table. Combo bindings use the PBIR
  `Y`/`Y2` roles, and visual projections include native query references.
- BO chart field qualifications and explicit aggregations are used even
  when universe column metadata is missing. This does not create missing
  semantic-model columns or establish that a visual can be rendered.
  The alternate visual generator warns and skips unsupported inline
  aggregations instead of silently substituting another calculation.
- Migration report DAX classification no longer crashes on ordinary formulas;
  its existing leaked-function checks still mark matching formulas approximate.
- SQL Server RDL generation now reports missing or inconsistent intermediate
  table structure explicitly instead of failing with an opaque Python error.
- SQL Server RDL tables now fit within their declared body and distribute
  automatically sized columns without rounding beyond the page width. This is
  a static geometry fix; opening and rendering in Report Builder remain
  unverified.
- Unbound RDL starting points now give the title and migration note a
  consistent, readable target style; this is not source-derived REP layout.
- UNX extraction now names `.dfx`, `.blx` and `.cns` components that carry a
  `Cipher` member as CMS-protected instead of silently returning nothing. No
  decryption is attempted; their metadata needs an authorized CMS or a
  SAP-supported export. Observed on three public UNX samples (all protected).
- Partial native WebI report tabs without extracted charts no longer receive a
  synthetic `tableEx` worksheet. The adapter logs the missing visual-layout
  evidence; generic reports without charts retain their existing fallback.
- WebI variables now keep nested formula expressions attached to the named
  variable and its qualification instead of emitting a blank duplicate.
- Crystal field, formula, parameter, group and sort parsing now preserves spaces
  and punctuation; already-decoded Unicode names are retained as well.
- `extract_bo_data()` now rejects BIAR/LCMBIAR inputs with guidance to use
  `extract_from_biar()`, instead of writing 15 empty extraction files.
- `extract_from_biar()` now materializes each archive entry before parsing it,
  so extractors process artifact contents instead of archive descriptors.
- `extract_from_biar()` rejects case-insensitive duplicate artifact output names
  before creating output folders, preventing one artifact's JSON from replacing
  another's.
- Exclude WebI query filters and conditions from extracted data-provider
  queries, avoiding false SQL column-binding conflicts when names overlap.
- The BW handoff CLI attempts to remove a report it created if writing fails
  and reports cleanup failures; existing output files remain protected by
  exclusive creation.
- Batch migration now warns when extraction returns no BusinessObjects objects,
  so unsupported or unrecognized source metadata is explicit in per-source
  diagnostics.

### Added
- An experimental Desktop Intelligence VBA macro is intended to capture provider
  names and SQL from the active document into the existing extracted-SQL list shape, with
  explicit unavailable/empty statuses. Synthetic fixtures exercise selection
  into a manually mapped RDL and optional Power Query; neither the macro nor
  the synthetic handoff parses `.rep`, and client execution has not been
  verified. SQL, connection, fields, layout and source equivalence still
  require independent review.
- Extracted SQL selection rejects inconsistent capture status and error fields
  when present, without requiring them in existing SQL-only inventories.
- `migrate_paginated.py` can read a `.rep` through the experimental static
  inventory and select one SQL candidate by provider-ID/stream-offset name.
  Generation requires `--accept-unverified-rep-sql`; the generated RDL still
  labels the candidate unverified. SQL mappings can additionally declare
  page dimensions/margins, column widths, basic title/table styling, prompt
  labels and multi-value report parameters for explicitly reviewed SQL Server
  parameters. These are manual declarations, not REP layout or BO prompt
  extraction; groups, sorts, page breaks, available values, dependent prompts,
  exact prompt UI, SQL execution, PBIP generation and source equivalence remain
  unsupported or unverified.
- `migrate_lcm_inventory.py` reads the readable `BusinessObjects.xml` manifest of
  an LCM BIAR and writes a lineage inventory (document → universe → connection
  type, prompts, WebI provider IDs, universe groups) plus an unbound RDL
  skeleton per document (`generate_unbound_rdl`: title, description and report
  parameters; no data source or dataset; parameter types default to `String`).
  Connection strings, owners and values are never read. It converts no data,
  SQL or layout; Report Builder rendering is `not_run`.
- `extract_webi_snapshot()` adapts a saved WebI CMS snapshot to the 15 BO
  collections: verbatim single-statement SQL plus one explicitly declared SQL
  Server connection (no credentials). It infers no columns, layout or
  report-to-provider links; generation yields a model with an empty report shell.
- A user-invocable WebI Migration development agent coordinates WebI source,
  query, model, visual and evidence work through existing module owners. It is
  not a CLI runtime stage and does not by itself add extraction or parity.
- Experimental native WID extraction inventories recognized `PARAMSERVER`
  prompt structure with provider/member provenance, while excluding prompt
  labels, IDs and values. Detected records with ambiguous generic-provider
  matches remain separate evidence and do not generate datasources. These
  records do not generate prompts, SQL, connections, or report-provider links.
- A read-only WebI document snapshot now captures report summaries/details and
  their elements alongside data-provider summaries/details under a versioned
  schema. Opt-in provider query metadata adds raw query plans and query
  specifications; no report-to-provider links are inferred. A Python-only
  adapter (see above) can turn it into extraction input; the CLI does not.
- Read-only WebI CMS calls list report tabs and their elements and retrieve
  report details, preserving supplied element IDs, hierarchy and layout
  metadata. The CLI does not use the responses, and they are not proof of
  report-to-provider links (only the Python-only `extract_webi_snapshot()` can
  consume a snapshot); real CMS compatibility remains unverified.
- A saved WebI API query plan with one direct SQL statement can now feed an
  explicitly mapped SQL Server RDL and optional Power Query M file. The
  optional native WID check compares provider IDs only; it does not authenticate
  the document or connect a query to a report tab. Added a plan schema and
  synthetic examples; live CMS, SQL execution and rendering remain unverified.
- Experimental native WID extraction reads version 2.5 report-tab names and IDs,
  section IDs, and a partial structural inventory of `VTABLE`, `HTABLE` and
  `XTABLE` elements with `BID` identifiers and `ROWINFO`/`COLINFO` descriptor
  counts when present. It also reads two observed data-provider
  query-specification variants. Result objects are descriptive metadata, not
  inferred SQL columns; this is not visual reconstruction. Parsing is bounded
  and partial; SQL, connections, full layouts, formulas and completeness remain
  unverified and are flagged in migration warnings.
- Read-only WebI CMS client methods list data providers and retrieve provider
  details, query-plan XML and query specifications. SQL statements retain their
  enclosing operators; complex plans are not flattened or automatically migrated.
  Live CMS behavior and SQL execution remain unverified.
- Preserve explicitly associated columns on uniquely named custom SQL tables;
	ambiguous names are not used to infer bindings. Fabric Dataflow checks the
	expected result names at runtime. Migration reports warn that result schemas
	and SQL execution remain unverified.
- Preserve explicit simple universe physical-column bindings in Import models
	and Fabric ingestion. Fabric validates declared source columns before
	renaming them to the Lakehouse/Direct Lake names and rejects ambiguous
	mappings. Unassociated WebI columns and untranslated universe expressions or
	filters remain migration warnings, not verified conversions.
- A positional BO folder routes recognized extensions to the existing artifact
	or archive pipeline, records skipped files and per-source results, and requires
	a new or empty output. RDL folder mode uses explicit per-source mappings and
	refuses BIAR inputs; it does not infer queries or convert report layouts.
- Non-dry-run folder migration now attempts to emit `batch_report.html` from `batch_manifest.json`,
	with per-source Power BI/Fabric and paginated statuses, warnings, errors,
	skipped inputs, and safe local links to available generated artifacts. This
	local summary does not establish Desktop/Report Builder rendering, refresh,
	runtime execution, or semantic/visual equivalence. Known I/O or manifest
	validation errors are logged as warnings without changing per-source statuses.
- Main CLI and local MCP migration now require a source folder instead of an
	individual BO file. Single-file assessment/dry-run, archives, shared models,
	declared RDL and legacy REST/notebook interfaces remain separate.
- Positional BIAR/LCMBIAR files use the archive pipeline; duplicate internal
	output names are rejected before generation to prevent overwrites.
- Explicit RDL SQL and semantic-model DAX mappings accept declared BO report
	families including Lumira, Desktop Intelligence, Xcelsius and Analysis for
	OLAP. This adds source labels only, not parsers, layout conversion or
	runtime/source-equivalence validation.
- Main CLI RDL choice routes an explicit mapping to the existing local RDL
	generator. It accepts a named SQL selection from supported local BO metadata
	including heuristic Crystal `.rpt` SQL candidates or extracted JSON, but not
	a positional BO file or unrelated migration options in single-mapping mode;
	automatic BO layout conversion, screenshot capture and pixel comparison are not implemented.
- Optional Power Query `.m` handoff alongside a SQL Server RDL, using the same
	explicit mapping and SQL selection. Desktop/Report Server reconstruction and
	runtime compatibility remain unverified; no PBIX is generated.
- Explicit scalar SQL Server RDL parameters can be declared in a manual mapping
	and bind SQL `@Name` references to report prompts. This does not convert BO
	prompts, support DAX or Power Query parameters, or verify Report Builder
	rendering or query execution.
- Separate local paginated RDL generator for a declared Crystal, WebI, BW or
	BEx source label, explicit DAX and an existing Power BI semantic model. This
	is a bounded table template, not automatic report/BEx conversion; rendering,
	query execution, publication and source equivalence are `not_run`.
- Separate offline BW inventory validation and a staged-history Bronze notebook
	generator with an explicit plan, schema/count checks, provenance and refusal
	of existing targets. SAP extraction, Fabric execution and BW equivalence are
	not provided.
- Separate offline BW-0 inventory gap assessment that reports blockers and
	review items without verifying live SAP discovery, source-owner attestations,
	or closing the BW-0 gate.
- Separate offline BW snapshot control comparator with explicit scope identity,
	exact count checks, declared numeric tolerances, and runtime evidence marked
	`not_run`; it does not collect or attest to source or target measurements.
- Separate offline BW snapshot-to-delta handoff evaluator for a normalized,
	declared contiguous-position feed, covering replay, overlap, ordering,
	deletes, schema drift and final-state comparison; no source or Fabric runtime
	evidence is implied.
- Separate offline BW transformation-vector comparator with strict field
	coverage, exact type/value checks and declared decimal tolerances; it does not
	parse or execute ABAP or authenticate supplied source/target outputs. An
	optional inventory/plan mode links vector identity and field sets to the
	normalized conversion plan and locally evaluates supported normalized rules
	against declared inputs and expected outputs; plan-valid Spark types outside
	the evaluator subset remain `not_run`, while invalid conversion-plan types
	are rejected by the CLI. Local evaluation is not Spark/Fabric execution or
	proof of equivalence; CLI exit 0 does not imply a `not_run` evaluation ran or
	passed.
	An additional source-declaration preflight requires local definition/ledger
	and inventory/transformation pairs, hashes supplied definition bytes, and
	reconciles declarations only; its `source_declaration_preflight.status` is
	separate from plan linkage, normalized-rule evaluation and vector comparison.
	It does not
	authenticate SAP origin, prove source-rule completeness/correspondence or
	vector provenance, execute SAP/Spark/Fabric, establish equivalence, or approve
	business results.
- Separate bounded BW transformation converter generating an unbound PySpark
	notebook from declared field transfers, typed string/boolean/integer constants,
	exact decimal-string constants and same-scale decimal addition/subtraction.
	Decimal literals reject rounding and overflow. It checks selected inventory lineage and rejects
	selected-object or ambiguously scoped unknowns, declared selected-object
	functions, unsupported selected features and additional incoming transformation
	dependencies; SAP extraction, ABAP parsing, source completeness verification,
	Fabric execution and equivalence remain out of scope.
- Optional BW conversion preflight hashes supplied local definition bytes and
	compares explicit source-rule IDs, mappings and input schema with a separate
	declared ledger. Mismatches block notebook generation; SAP origin, the ledger's
	actual source coverage and owner approval remain unverified.
- Separate offline BW-5 BEx semantic-capture contract and gap assessment for
	variables, filters, hierarchies, key figures, authorization contexts and
	inventory-linked consumers; it does not parse, convert or execute BEx queries.
- Separate offline BW-6 security, planning and compliance controls assessment
	with inventory-linked authorization declarations, allow/deny test scenarios,
	planning-control coverage, and audit/retention/privacy/legal-hold references.
	It does not execute target controls or certify compliance; runtime evidence
	remains `not_run`.
- Separate offline BW-7 wave evidence index for BW-2 through BW-6 per-object
	declarations and wave-level operational references. It checks inventory
	scope/linkage and declared statuses, preserves referenced evidence metadata,
	and does not verify report bytes, freshness/correctness, runtime execution,
	operational certification, or retirement approval.
- Separate offline BW-8 cutover/retirement declaration assessment for one wave.
	It checks BW-0/BW-7 local scope/owner acceptance, dependency dispositions,
	upstream feeds, planning/retention, reconciliation, declared run/observation
	durations, rollback planning and owner decisions. It does not authenticate or
	dereference references, execute operations, close a gate, or authorize
	cutover/retirement; runtime evidence remains `not_run`.
	Its report identifies the direct-neighbor dependency scope and marks coverage
	verification `not_verified`; transitive dependencies are not checked.
- Six-tool local stdio MCP server with root-scoped paths, read-only startup,
	explicit generation confirmation, and no deployment/refresh tools.
- Unified local PBIP/Fabric quality reports, strict warning validation, owner
	handoffs, and persisted per-project findings.
- Tested specialist ownership and BO/Fabric workload-skill routing: 23 development
	roles, including the WebI coordinator, not CLI runtime stages.
- Fabric artifact manifests, Gen2 query metadata/destinations, notebook lakehouse
	dependencies, and cross-artifact ingestion/materialization checks.

### Changed
- Fabric source tables use Direct Lake entity partitions with parameterized
	OneLake bindings; optional automatic Calendar/date-part enrichments absent
	upstream are deferred. Import date behavior remains available.
- File ingestion belongs to the primary Notebook; connected/custom SQL ingestion
	belongs to Dataflow. The primary Notebook alone materializes calculated columns.
- Documentation now separates current local evidence from the historical roadmap,
	reports the actual CI workflow, and qualifies server/deployment limitations.

### Fixed
- Lumira Discovery preserves explicit table and chart references. Extracted
	charts without a matching report/tab are retained on a separate synthetic
	page rather than discarded; original placement and missing bindings remain
	unverified.
- Folder manifests and BIAR reports now surface synthetic datasource
	placeholders and SQL entries without matching SQL-bearing datasource tables.
	Generation success still does not establish object fidelity or query execution.
- Readiness now marks a missing adapted datasource as a folder-import blocker,
	distinguishes inferred ODBC placeholders from extracted connectors, and flags
	SQL with no matching datasource table. These checks do not prove source
	completeness, correct SQL binding, or Power Query generation.
- Power Query literals preserve Windows backslashes, literal `#(` sequences,
	quotes and line breaks. Generated model partitions no longer add the invalid
	Python-list error fallback, so source errors are not automatically hidden.
- BIAR/LCMBIAR inputs with no directly recognized artifacts now fail explicitly
	without creating an empty migration output; segmented content is not decoded.
- BW control and transformation-vector tolerance comparisons use exact decimal
	arithmetic regardless of caller context, and exact vector comparisons preserve
	nested JSON types. Representable decimal-zero constants are accepted at full
	scale. These remain local checks, not Spark or Fabric runtime evidence.
- Local assessment and dry-run no longer generate persistent migration outputs;
	directory batch and BIAR routes perform generation with per-source failure status.
- Comparison and DAX optimization opt-outs are honored on local file/batch paths.
- Blocking Fabric quality findings return exit 6 through CLI/MCP workflows instead
	of treating emitted artifacts as success.
- Shared merging retains isolated physical tables, source connections, schema,
	datatypes, and workbook provenance. Ambiguous physical names reject before
	generation rather than collapsing sources. Universe connection extraction
	ignores empty containers and deduplicates exact repeated records only.
- Supported simple BO row expressions generate syntactically checked PySpark;
	unsupported/order-dependent expressions remain explicit failures.
- Extraction masks recognized credential-named datasource properties and
	recognized authentication components in `connectionString` values before
	returning or persisting extracted JSON, and when loading earlier JSON files.
	This pattern-based masking does not guarantee removal of credentials in
	arbitrary SQL/text, unrecognized formats, or encodings.
- Server mode now rejects `--assess`, `--global-assess`, and `--dry-run`
	before CMS connection or download. Server portfolio assessment and target
	generation remain unsupported; ordinary server migration still downloads
	and extracts artifacts.
- The main migration CLI now rejects `--deploy`, `--deploy-refresh`, and
	`--deploy-bundle` before migration instead of silently ignoring unwired
	deployment paths or reporting local success as publication. This does not
	change or verify the separate `--multi-tenant` workflow.

### Known Limitations
- Full BW warehouse migration remains incomplete: staged Parquet is supplied
	externally; durable upstream feeds, ABAP/BEx conversion, independently
	verified reconciliation, security and retirement still need implementation
	and runtime evidence. Offline control comparisons are not runtime evidence.
- Pattern-based extraction redaction covers recognized datasource fields and
	connection-string authentication components only; credentials in arbitrary
	SQL/text or unrecognized formats may remain. Review/restrict outputs before
	sharing.
- Server mode still downloads/extracts only; portfolio assessment and target
	generation are unsupported. Inspection-only flags are rejected before CMS
	connection. Main CLI deployment flags are rejected; `--multi-tenant` remains
	separate and unverified.
- The separate `--multi-tenant` path is unchanged and unverified; its deployment
	results require independent review and are not covered by the standard CLI
	flag guard.
- Unsupported BO semantics and missing bindings still need action. Desktop,
	refresh, deployment, and Fabric execution remain `not_run`.
- A local smoke test of the [MIT Crystal sample](https://github.com/devistic-dotnet-projects/Crystal-Report-Sample/blob/df77c741e1672ca9d0b031c386ffc36a498d8c6f/CReport/CrystalReport/ReportCustomer.rpt)
	and [SAP LCMBIAR sample](https://github.com/SAP-archive/boe-custom-cms-data-access-driver/blob/main/deploy/content/content.lcmbiar)
	produced no PBIP: the Crystal datasource was not extracted, and segmented
	archive contents were not decoded. RDL batch produced no reports without a
	Crystal mapping and cannot select inside the archive. These results do not
	establish that the source reports or connections are absent.

Local verification on 2026-11-16: 636 tests and 643 subtests passed. Earlier
runs recorded 558 tests and 518 subtests on 2026-11-12, and 537 tests and 495
subtests on 2026-11-11. These are unreleased changes and local measurements,
not a shipped-release or runtime claim.
---

_This changelog follows [Keep a Changelog](https://keepachangelog.com/) format._
