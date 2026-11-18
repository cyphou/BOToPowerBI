# Changelog

## [Unreleased]

### Fixed
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
  report-to-provider links; generation yields a semantic-model-only PBIP.
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
