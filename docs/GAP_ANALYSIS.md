# Gap Analysis — BO to Power BI Migration

## Desktop Intelligence — experimental REP inventory and VBA handoff

The standalone `migrate_deski_inspect.py` inventory is under implementation.
It reads local REP ZIP, including prefixed ZIP, or OLE via Windows Structured
Storage on Windows, with partial candidates for sheets, providers, objects,
SQL, formulas, literal prompt/variable arguments found in SQL and structural
markers. Unsupported containers are rejected; encountered non-UTF-8 strings
and unsupported internal formats are flagged. A recognized `Query;` header may
expose a source name as a possible universe, not a verified universe or
connection. BO variables remain unresolved.

The reader opens selected metadata streams, not data-cache or macro streams,
but hashes the entire source as raw bytes. It executes no macros and performs
no refresh. It requires a new JSON file, which may contain sensitive SQL and
metadata and must stay local and protected. The inventory command does not
generate PBIP or verify report-to-provider links, and
its JSON object is not the VBA handoff's selector list. The separate
inspection CLI can optionally produce JSON and/or HTML pre-migration reports.
They show candidate counts, unverified SQL selectors, stream-local references
for detected formula candidates, design/prompt review actions and checks
`not_run` by that inspection. Formula references locate candidates only within
the inspected stream; they do not establish source identity, completeness or
formula semantics. The reports do not score fidelity or establish that a zero
count means absence. They omit SQL text, literal prompt/variable arguments and
formula expressions, but source and other names remain potentially sensitive
and sanitization is not guaranteed. The raw inventory is still written
separately. All outputs must be new; failed writes attempt to remove files
created by the command and report cleanup failures.

The main CLI's `report.rep --assess` prints the same partial report as JSON
without writing an inventory. Optional `-o DIR` requests exclusive creation of
`<stem>_deski_assessment.json`; `--dry-run` writes nothing and non-applicable
flags are rejected. An empty `-o` value is rejected. Existing output files and
final-path symlinks are refused; use a trusted directory. The report still
contains potentially sensitive metadata and does not establish completeness
or equivalence.

A user-reported local REP smoke returned `review_required` with runtime checks
`not_run`; the sample's provenance was not independently verified here.

The separate
`migrate_paginated.py` can now select one SQL candidate using its possible
provider ID or `unresolved` plus stream offset, but only when
`--accept-unverified-rep-sql` is explicitly supplied. The main CLI now routes
the same single-source operation using `--rdl-accept-unverified-rep-sql`;
folder workflows also accept per-source REP mappings with an exact SQL selector
and `accept_unverified_rep_sql: true`. They record the candidate as unverified
in the batch manifest. In combined PBIP and RDL mode, a per-source `pbip`
declaration can additionally generate a basic PBIP table draft from the same
selected SQL candidate. It requires declared `connection_name`, `query_name`,
`schema` and typed `columns` matching the RDL field list; it does not recover
or verify these fields. Recognized BO SQL function markers block the PBIP
target. Without that declaration, the PBIP target fails explicitly while the
paginated target can still succeed. This does not enable automatic REP-to-PBIP
conversion or REP-to-Fabric generation. The paginated target generates an RDL from a
manually declared SQL Server connection and field list. The mapping can also
declare page dimensions/margins, column widths, font/colors, and SQL
report-parameter prompt labels including multi-value selection after the BO
filter has been reviewed and rewritten as SQL Server parameter syntax. The
generator applies a styled title/table and alternating detail rows. None of
these settings are recovered from REP: coordinates, groups, sorts, page breaks,
filter-value lists, dependent prompts, and original prompt-dialog behavior
remain unsupported. PBIP is one generated table page and semantic table from
the declared SQL/columns, not the source layout or full BO semantics. The SQL,
association and mappings are not validated, and the original report layout is
not automatically restored. SQL, bindings, completeness and equivalence still
require independent review.
Desktop/Report Builder rendering, query execution, refresh, deployment, Fabric
execution and source equivalence remain `not_run`.

The generated REP PBIP is checked with the existing local static
`ArtifactValidator`. Structural errors fail only the PBIP target and appear in
the manifest; warnings do not block it, and the independent paginated target
can still succeed. This validator does not execute SQL, validate declared
columns against query results, or prove Desktop opening/rendering or
source/target equivalence. A failed generated PBIP may remain in the output
for diagnosis.

The generated empty RDL skeletons use a consistent title and review-note
style, but it is a target-side placeholder, not a reconstruction of DeskI
formatting. A bounded inspection of the eight sample `Data ReportFmt` streams
found binary payloads with a few generic text markers and no decoded
coordinates, widths, font/color assignments, pagination, or report-element
bindings. That probe is not a format parser and does not prove those properties
are absent from the source.

An optional VBA macro is intended to capture provider SQL from an active
Desktop Intelligence document. Synthetic inventory and mapping fixtures pass
through the existing exact-name SQL selector into a basic RDL and M expression;
empty, duplicate, inconsistent capture status and BO-prompt SQL cases are
rejected. Status consistency does not authenticate the inventory. The macro, SDK property
availability and real `.rep` behavior have not been tested on a Desktop
Intelligence client. Neither the macro nor the synthetic handoff parses `.rep`,
converts a complete report, or proves connection, layout, data, rendering or
semantic equivalence.

### Reported DeskI sample observation — 2026-11-18

A local replay of 8 examples kept outside the repository (5 ZIP and 3 OLE)
generated 8 inventories, 8 JSON reports and 8 HTML reports. Independent
SHA-256 reads matched the recorded source hashes. It recorded 11 sheet, 9
provider, 34 object, 8 SQL and 46 formula candidates; the SQL candidates came
from 7 files, and 3 SQL candidates contained BO function markers. An earlier
observation reported that all 8 SQL slices matched their length-delimited source bytes;
that byte-level check was not independently replayed. It would check framing,
not SQL validity, execution or report/provider linkage. Seven `Query;` headers
named `eFashion` as a candidate source, not a verified universe or connection.
These observations do not prove completeness or representativeness; public
provenance was not independently checked and the examples were not redistributed.

A separate RDL/M illustration was generated using a manually declared SQL
Server connection and two manually declared fields, with fictitious values. It
did not verify the original source type or execute SQL. Generation does not
establish field bindings, layout, rendering or source/target equivalence.

### Direct REP-to-RDL pilot — 2026-11-18

The new paginated route was run against the local `efashion_911.rep` sample.
It selected the `#DP#1@1419` candidate and wrote an RDL plus an M expression.
The RDL query text exactly matched the candidate read from that REP. The mapping
used explicit placeholder server/database values and manually declared
`Yr`, `State` and `Expr1002` fields; their connection and binding are not
verified. No query was executed. The outputs remain local draft artifacts;
Report Builder/Power BI rendering, refresh and source/target equivalence are
`not_run`.

The gated RDL route's integration test uses a stub inventory to verify exact
candidate selection, required acknowledgement, and refusal to overwrite.
The RDL-only folder-batch test also verifies per-source acknowledgement,
dry-run behavior, generated RDL/Power Query outputs, and the manifest's
unverified-candidate warning.
Additional direct-selection sample coverage, Desktop/Report Builder rendering,
query execution and source/target equivalence remain `not_run`.

### Manual prompt illustration — 2026-11-18

For `replace_semi-colons_in_userresponse.rep`, the partial scan found an
unverified SQL candidate with one `@variable` literal. A local illustration
manually replaced that expression with a SQL Server RDL parameter, declared a
multi-value string prompt and three fields, and used a placeholder connection.
The RDL was generated from the manual mapping, not through the direct REP
selector; the multi-value behavior, fields, source dialect and connection
remain unverified. Default styling and layout are not source-derived.

Local XML parsing confirmed the rewritten query, fields and parameter binding.
This is not Report Builder schema/open/render validation, query execution or
proof that the original BO prompt behaves the same. No parameterized Power
Query output was generated; it is unsupported by this path.

### Local test evidence — 2026-11-18

On Windows, the full local suite reported **726 passed, 1 skipped, 762
subtests passed** before the declared RDL layout/prompt update. After that
update, `python -m pytest tests --tb=short -q -o addopts=''` reported
**728 passed, 1 skipped, 767 subtests passed**. After the pre-migration report
update the same command reported **736 passed, 1 skipped, 770 subtests passed**.
The focused selection
`tests/test_sql_server_rdl.py`, `tests/test_paginated_rdl.py` and
`tests/test_desktop_intelligence_extractor.py`, together with
`tests/test_agent_contracts.py`, reported **68 passed, 1 skipped,
414 subtests passed**. Ruff passed for the changed DeskI, RDL and CLI
implementation/tests.

The skipped test covers the non-Windows OLE error path; the Windows Structured
Storage OLE test passed with synthetic input. These local tests do not establish
sample provenance, source type, Desktop execution or source/target equivalence.

After the opt-in REP PBIP/RDL batch draft update, the focused DeskI selection
reported **24 passed, 1 skipped, 7 subtests passed**. The full suite reported
**755 passed, 1 skipped, 791 subtests passed**. These are local code tests only; they do not
validate PBIP opening/rendering in Desktop, RDL rendering in Report Builder,
query execution, refresh, Fabric execution or source/target equivalence.

## Real-sample findings and CMS metadata — 2026-11-18

Four public LCM BIAR exports (3 UNX, 2 UNV, 39 Crystal reports, 1 WebI) and
the 13 earlier WIDs were migrated locally. None generated a PBIP: no SQL,
datasource or column metadata was readable. The UNX components are marked with
a `Cipher` member and the extractor now says so instead of returning nothing;
Crystal `.rpt` streams are opaque and the UNVs expose only names. Decryption
is not attempted, and these samples are not redistributed.

The CMS `BusinessObjects.xml` manifest is readable and gives bounded lineage:
which document declares which universe, which connection type (network layer
and database type) a universe uses, Crystal prompt names and flags, and WebI
provider IDs. `migrate_lcm_inventory.py` exports it with one unbound RDL
skeleton per document. In a one-time local check (no schema-backed test is in
the repository) the skeletons validated against the RDL 2016/01 schema,
declare parameters as `String` (types are not in the metadata) and contain no
data source, query or layout. A saved CMS snapshot can additionally feed
`extract_webi_snapshot()` for a model with an empty report shell. Data-bound
reports, columns and layouts still require an authorized CMS or verified exports;
Report Builder rendering, Desktop opening and refresh remain `not_run`.

## Native WebI prompt evidence — 2026-11-17

The local WID parser inventories recognized `PARAMSERVER` structure with
provider/member provenance, excluding prompt labels, IDs and values. It does
not convert these records into prompts or infer a query, connection or
report-provider link. A replay of 13 downloaded WIDs persisted 12 provider
records and 18 structural prompt entries, but recovered no SQL or datasource;
all 13 PBIP migrations failed. Source completeness, runtime behavior and
equivalence remain unverified.

## Bounded datasource credential redaction — 2026-11-16

The local extraction path now masks recognized credential-named properties in
datasource records and recognized authentication components in `connectionString`
values before returning extracted data or writing JSON. Loading earlier
extraction JSON also masks returned datasource data without modifying the
existing files. Synthetic regression tests cover direct datasource fields,
semicolon-delimited SQL/ODBC strings, quoted/braced values, and JDBC URI
credentials.

This is pattern-based, not a complete parser or secret scanner. Credentials in
arbitrary SQL/text, unsupported connection-string dialects, unrecognized keys,
or encodings may remain. It does not certify every generated artifact as
secret-free; review and restrict extracted/generated outputs before sharing.

## CMS inspection flags — 2026-11-16

The CLI now rejects `--assess`, `--global-assess` and `--dry-run` when combined
with `--server`, before starting the server migration path. A synthetic
regression verifies all three combinations fail without calling the download
workflow. This prevents a read-only/assessment expectation from silently
triggering CMS downloads.

Server portfolio assessment and Power BI target generation are still not
implemented in this path. Without those inspection flags, the server workflow
continues to download and extract artifacts; this guard does not change its
authorization, scope, or output-directory requirements.

## Main CLI deployment guard — 2026-11-16

The main migration CLI now rejects `--deploy`, `--deploy-refresh`, and
`--deploy-bundle` before migration. This avoids silently ignoring unsupported
shared/bundle deployment options or returning a success-shaped local result
after a failed deployment integration. The local regression suite verifies
that migration dispatch does not begin for these options.

This is a rejection, not a deployment implementation. No remote call was made
or tested; the separate `--multi-tenant` workflow was not changed or verified.
Deployment and refresh results remain `not_run`.

## Paginated RDL - 2026-11-16

The main CLI RDL choice and separate local generator accept an explicit
DAX/field mapping and emit a basic RDL table over a Power BI semantic model.
SQL Server mappings can also declare scalar parameters and bind SQL
`@Name` references to RDL report prompts. This is manual mapping, not automatic
BO prompt conversion; parameters are not supported for DAX or the Power Query
handoff. The generator does not automatically convert Crystal, WebI or BEx
report layouts or verify runtime execution. Automated screenshots and pixel
comparison are not implemented.

The explicit SQL Server and semantic-model DAX mappings accept declared
WebI, Crystal, Lumira, Desktop Intelligence, Xcelsius, Analysis for OLAP and
universe origins; DAX also accepts BW and BEx. These labels add no extraction
or report-feature conversion. Supported `.wid`, `.rpt`, `.unx`, `.unv` and
experimental `.rep` metadata/candidates can be used for direct SQL selection
(Crystal candidates are heuristic readable-text matches; REP candidates require
an explicit unverified-candidate acknowledgement);
BIAR/LCMBIAR is an archive
and cannot be passed to the RDL selector. See the README source-preparation
matrix for manual steps and remaining gaps. SQL result/field linkage, Report
Builder rendering, execution and equivalence remain unverified.
The folder RDL dispatcher applies per-source mappings and reports archive
entries as unsupported; it does not infer a report's query, convert its layout
or unpack BIAR for RDL.

## Consolidated Batch Report — 2026-11-16

Non-dry-run folder migrations now attempt to emit `batch_report.html` from the
generated `batch_manifest.json`. Known report I/O or manifest-validation errors
are logged as warnings without changing per-source target statuses. The report
summarizes per-source Power BI and paginated target statuses, errors, warnings,
skipped inputs, and contained local links to available outputs. It is local
generation evidence only: PBIP/RDL opening and rendering, refresh, runtime
execution, and semantic/visual equivalence remain separate and unverified.

## TableauToPowerBI Comparison - 2026-10-27

This is a scoped capability comparison, not a claim of full parity with the
Tableau engine. Existing BO conversion support is listed separately below.

| Capability | BO Status After This Update | Evidence Or Remaining Gap |
|------------|-----------------------------|---------------------------|
| Specialist agents and workload-skill routing | Adapted | Fabric and AgentTools ownership; explicit remote-write boundaries |
| Pre-migration assessment | Implemented | Uses adapted BO objects without running generation |
| Dry-run | Repaired for file, batch, BIAR, and shared-model workflows | Temporary extraction; no persistent migration outputs |
| Full directory batch | Implemented | Per-source outputs, structured manifest, partial-failure exit code |
| Shared semantic model CLI | Connected to existing merge engine; physical metadata preserved | Shared model plus thin reports; isolated tables retained with source connections/provenance; ambiguous physical names rejected |
| Fabric CLI output | Connected to five existing generators | Actual Fabric bundles, rather than an empty PBIP-style project |
| BIAR generation | Repaired | Archive entries become real temporary source files; no silent JSON-only success |
| Comparison report | Connected | BO extraction is adapted; `--no-compare` is honored |
| DAX optimizer opt-out | Repaired | `--no-optimize-dax` is honored on single-file and directory workflows |
| Local MCP server | Implemented, six tools | Read-only startup; explicit local write guards; subprocess tests |
| Unified quality report | Implemented, local only | Deterministic JSON, priorities, CI exit code, strict warning policy |
| Fabric validation | Cross-artifact local checks | Part/manifests, logical UUIDs, entity/column mapping, Gen2 destinations, notebook syntax, dependency cycles; persisted in bundle metadata |
| Direct Lake generation | Implemented for source tables | Entity partitions and shared OneLake expression; parameterized workspace/lakehouse binding; Import-mode utilities are explicitly flagged |
| Direct Lake execution | Not verified | Bindings, credentials, refresh, and Fabric execution require an authorized environment |
| Dataflow Gen2 definition parts | Implemented locally | Mashup with destinations, queryMetadata format 202502, platform manifest; real connections remain unbound |
| Notebook bindings and calculated columns | Improved locally | Persistent dependencies, newline-safe cells, normalized Delta names; one primary ETL notebook owns calculated-column materialization |
| Fabric ingestion ownership | Implemented and checked locally | CSV/Excel to Notebook, connected sources/custom SQL to Dataflow; per-table plan, emitted writes, and conditional pipeline dependencies are validated |
| Generation-time quality gate | Implemented for Fabric CLI/MCP | Blocking findings preserve artifacts/reports but return code 6 before single-project deployment; archive/batch/shared paths retain failure status |
| Automatic healing and rollback | Not ported | No Tableau-specific repair rules copied into BO |
| Feature parity registry and runtime equivalence | Not ported | No invented feature score or assertion of runtime parity |
| Desktop launch/rendering evidence | Not implemented | Always `not_run` in local quality reports |
| LLM gateway, budgets, advisory contracts | Not ported | Existing BO LLM client is not equivalent to Tableau's gateway |
| External Fabric deployment verification | Environment work | Requires approved target, identity, authorization, and actual execution |

The example BIAR is exercised with all three contained artifacts in PBIP and
Fabric modes. Directory smoke testing identifies `Legacy_Sales.unv` as nonmigrable
with the current extractor because no datasource is recovered; the batch now
returns failure and records the cause rather than reporting false success.
PBIP quality checks reuse existing structural/semantic heuristics, not the full
Microsoft schema or Desktop runtime. Shared-model and datasource-only layouts
need richer binding-aware validation before static results can certify openability.

### Fabric Skill Review

The installed `semantic-model-authoring`, `dataflows-cli` (authoring), and
`spark-cli` (authoring + notebook core) references guided the local artifact
changes. No workspace was changed and no notebook, Dataflow, or semantic model
was refreshed or executed remotely.

The stricter checks deliberately expose unsupported BO semantics: `Previous`
without explicit source ordering is not translated into an arbitrary window;
groups with no source members are recorded as unsupported instead of fabricated
empty-string columns. These remain blocking local quality findings. Binary
columns and Delta name collisions are rejected explicitly. Source credentials,
connection binding, and notebook/pipeline IDs still need environment setup.
The Dataflow and Notebook ingestion paths now use a common connection resolver
and a persisted unique-owner ingestion plan. Dataflow no longer injects the
migration's calculated columns; only the primary ETL notebook materializes them.
The duplicate transformations notebook is no longer emitted. File-only pipelines
skip Dataflow refresh; connected and mixed pipelines wait for that refresh before
the Notebook. None of these local contracts proves deployed execution or OneLake
file availability; files still need to be provided in the configured lakehouse.

Local smoke runs cover WebI, BIAR, directory batch, shared Fabric models, a
Universe, and PBIP nonregression. WebI/BIAR/batch examples with unsupported
semantics return 6 with saved quality reports; the eFashion Universe with warnings
returns 0. PBIP WebI and BIAR generation succeeded for those repository examples;
this does not extend to the downloaded native WIDs described above. The legacy
UNV example still has no usable datasource. A real stdio MCP subprocess test
verifies that a blocked Fabric migration returns structured failure without
polluting stdout.

### Shared Physical Schema Repair - 2026-10-28

The merger now retains tables classified as isolated rather than silently
dropping them. Their physical columns, effective per-table connection, and source
workbook provenance survive; no relationship is invented. Fingerprints resolve
per-table overrides/connection maps, flat BO server/database metadata, file paths,
explicit source schemas, and BO custom-SQL definitions. Equal physical identities
can union columns; same-named distinct physical sources are rejected rather than
collapsed or implicitly renamed. Reassess sources after this change: corrected
physical identities can differ from earlier incomplete fingerprints.

Universe extraction no longer treats an empty Connections XML container as a
datasource and removes only identical repeated connection records. Distinct real
connections remain distinct. The BO adapter also supplies the source datatype
expected by downstream writers, preserving existing `dataType` metadata.

Synthetic BO-to-adapter-to-merge-to-Fabric tests verify types, connection binding
metadata, lineage, and a materialization target backed by an actual source table.
A real eFashion/HR Universe shared CLI run retains 11 tables with local quality
`WARN` and exit 0 using `--force-merge`; its PBIP counterpart creates the model and two thin-report
manifests. The Enterprise Sales/Financial Report pair is now rejected before
generation with exit 3 even when forced because its distinct `FreehandSQL` queries require explicit
source-qualified mapping. This replaces the earlier generated-but-blocked result;
unsupported formula/group semantics have not been declared fixed.

Without `--force-merge`, these low-overlap pairs are declined before generation
with exit 5. Force approval bypasses a recommendation, not source identity checks.

### Historical Documentation And Operational Boundaries - 2026-10-28

This dated snapshot is not the current status. The redaction, CMS inspection
flag and CLI deployment statements below have been superseded by the bounded
changes documented at the start of this file; their remaining limitations
still apply.

- Exported connection strings are not guaranteed redacted and can contain source
	credentials. Treat extraction JSON and generated artifacts as sensitive. Automatic
	masking before persistence is an open Extractor task, not a completed security feature.
- The CMS CLI path downloads/extracts; `--global-assess` is not dispatched there,
	and `--dry-run` does not enforce the local no-output contract on server mode.
- Shared generation ignores `--deploy`; standalone `--deploy-bundle` does not
	provide a working publish path. Single-file hooks need service-side checks:
	deployment errors may be logged without a nonzero migration exit code.
- CI currently runs lint/type checks, tests/coverage on Python 3.12/3.13 across
	three OSes, then CLI help. No sample-generation, staging, or production gate is
	implemented in that workflow; hosted CI itself was not executed in this review.
- Documentation corrections do not implement these missing runtime behaviors.
	Track their owners and evidence gates in the [development plan](DEVELOPMENT_PLAN.md).

Direct Lake no longer adds automatic Import/M Calendar tables or date-part
columns absent from the Lakehouse. Those optional enrichments are reported as
deferred; physical source dates and explicit hierarchies are preserved. Import
mode keeps its existing automatic date behavior. Missing schemas, calculation
collisions, and unsupported semantics still block when applicable; cloud/runtime
evidence remains `not_run`.

Nested BO `ElseIf` and expressions outside the supported row-level subset remain
explicitly unsupported instead of being emitted as invalid Python. Simple numeric
`<>` conditions are converted without replacing operators inside strings. A merged
model without physical source-table metadata, or with colliding normalized
calculated-column names, is blocked rather than written to an invented table or
overwriting a column. Warnings and missing runtime evidence remain distinct from
blocking source/model findings.

## Conversion Coverage (Format-Dependent)

The mappings below apply only where the relevant metadata is recognized; they
do not establish complete source coverage or runtime equivalence.

### Web Intelligence
| Feature | Status | Notes |
|---------|--------|-------|
| Data providers (queries) | ⚠️ | Recognized metadata only; native result objects do not recover SQL or connections |
| Variables (Measure) | ⚠️ | Supported formulas can become DAX candidates |
| Variables (Dimension) | ⚠️ | Recognized variables can become calculated columns or columns |
| Variables (Detail) | ⚠️ | Association with a dimension requires available metadata |
| Report tabs | ⚠️ | Native IDs and names are partial; layout is not reconstructed, and partial native or snapshot tabs get no fallback visual |
| Prompts | ⚠️ | Generic metadata may produce parameters; native `PARAMSERVER` is structural evidence only |
| Query filters | ⚠️ | Supported mappings require recognized metadata and review |
| Report filters | ⚠️ | Supported mappings require recognized metadata and review |
| Charts (bar, line, pie) | ⚠️ | Supported visual mappings require recognized metadata and review |
| Tables | ⚠️ | Native table inventory is not a reconstructed visual |
| Cross-tabs | ⚠️ | Supported matrix mapping requires recognized metadata and review |
| Breaks | ⚠️ | Group mapping requires recognized metadata and review |
| Sorts | ⚠️ | Visual sort mapping requires recognized metadata and review |
| Input controls | ⚠️ | Slicer mapping requires recognized metadata and review |
| Alerters | ⚠️ | Conditional formatting mapping requires recognized metadata and review |
| Calculations (BO formula subset) | ⚠️ | DAX candidates require formula-level validation |

### Crystal Reports
| Feature | Status | Notes |
|---------|--------|-------|
| Formulas | ✅ | → DAX measures/calculated columns |
| Parameters | ✅ | → PBI parameters + slicers |
| Groups | ✅ | → Groups in visuals |
| Record selection | ✅ | → M query filter |
| Group selection | ✅ | → DAX filter |
| Running totals | ✅ | → CALCULATE window patterns |
| Subreports | ✅ | → Drill-through pages |
| Charts | ✅ | → PBI chart visuals |

### Universe
| Feature | Status | Notes |
|---------|--------|-------|
| Business layer objects | ⚠️ | → Columns + measures; UNX with CMS-protected (`Cipher`) components yield nothing |
| Data foundation tables | ⚠️ | → M partitions; same UNX limit |
| Joins | ✅ | → Relationships |
| Derived tables | ✅ | → M custom SQL |
| Contexts | ⚠️ | → ALLEXCEPT patterns (partial) |
| @Aggregate_Aware | ⚠️ | → Measure granularity (partial) |
| LOV (List of Values) | ✅ | → Parameter tables |

## Partial Support (⚠️)

| Feature | Gap | Workaround |
|---------|-----|-----------|
| **BO Contexts** | Complex chasm/fan trap resolution requires manual review | ALLEXCEPT template with manual column selection |
| **@Aggregate_Aware** | Multi-level aggregation routing needs per-measure DAX | Generate base measure; manual optimization for complex cases |
| **Crystal cross-tab** | Nested row/column groups partially supported | Matrix visual with manual group configuration |
| **Crystal subreport parameters** | Parameter linking partially mapped | Drill-through filter parameterization |
| **Dynamic alerters** | Multi-condition alerters simplified | Single conditional formatting rule per alerter |
| **WebI sections** | Native section inventory does not reconstruct layout | Rebuild and validate visual groups manually |
| **Input control (slider)** | Numeric range input controls | PBI numeric slicer (range mode) |
| **Linked universes** | Multi-universe linking not automated | Manual relationship setup between semantic models |

## Not Supported (❌)

| Feature | Reason | Recommendation |
|---------|--------|----------------|
| **Crystal .rpt binary parsing** | Proprietary binary format — full SDK needed | Use Crystal Reports SDK or manual export to XML/PDF, then re-create |
| **BO scheduling (full)** | BO scheduling model differs significantly from PBI refresh | Map basic frequency; complex patterns need manual config |
| **BO Publications** | No direct PBI equivalent (targeted distribution) | Use PBI subscriptions + RLS per audience |
| **BO Discussions** | Collaboration feature with no PBI equivalent | Use Teams integration / Power BI comments |
| **BO Categories** | BO-specific organization taxonomy | Map to PBI workspace structure + tags |
| **BO Audit trail** | Server-level audit data not migrated | PBI admin API provides equivalent monitoring |
| **Universe connection pooling** | Server-side connection management | PBI gateway handles connection pooling |
| **Crystal formula timing** | `WhilePrintingRecords` / `WhileReadingRecords` evaluation | DAX is declarative — evaluation timing handled by engine |
| **Crystal Page N of M** | Crystal-specific pagination | Paginated reports are a possible target, but automatic pagination conversion is not implemented |
| **Lumira Designer apps** | Custom SDK-based applications | Rebuild as Power BI embedded / Power Apps |
| **OLAP universes (BW)** | SAP BW-specific OLAP queries | A direct BW connector can support coexistence; it does not migrate BW semantics or enable warehouse retirement |

### Full SAP BW warehouse migration

The repository has a local, versioned BW inventory snapshot contract and
validator/upgrader (`powerbi_import/bw_inventory.py`), an unbound Bronze
notebook generator for explicitly staged Parquet, and a bounded normalized
field-rule to PySpark converter. The latter covers transfers, typed constants
and same-scale decimal addition/subtraction, not SAP metadata or ABAP parsing.
These are not a BW extractor, general transformation/BEx conversion engine,
direct-upstream ingestion pipeline, independent runtime reconciliation service,
or retirement workflow.
See the [BW-to-Fabric design](SAP_BW_TO_FABRIC_DESIGN.md) and
[development plan](DEVELOPMENT_PLAN.md#separate-roadmap-sap-bwbw4hana-to-fabric-and-bw-retirement)
for remaining scope and evidence gates. SAP/Fabric runtime checks remain
`not_run`.

## Historical Formula Gap Estimate

The following figures are historical estimates, not a measured current
coverage rate or proof of formula equivalence. In particular, current `Pos`
and `DaysBetween` outputs require manual correction and validation.

| Category | Total BO Functions | Supported | Gap |
|----------|-------------------|-----------|-----|
| Aggregation | 15 | 13 | 2 (Percentile, WeightedAvg) |
| Text | 25 | 22 | 3 (HTMLEncode, URLEncode, Multivalue) |
| Date | 30 | 26 | 4 (RelativeDate, FiscalCalendar, LastDayOfMonth complex) |
| Logic | 15 | 14 | 1 (Pattern matching with LIKE wildcards) |
| Math | 20 | 18 | 2 (Ceil with precision, Number formatting) |
| Null | 5 | 5 | 0 |
| Running | 5 | 3 | 2 (Running min/max with reset) |
| Context | 5 | 3 | 2 (Complex nested contexts) |
| Security | 3 | 3 | 0 |
| **Total** | **123** | **107** | **16 (87% coverage)** |

## Recommendations

1. **Assess each WebI document first** — verify coverage, SQL, connections and report-provider links before generation; no cross-format fidelity ranking is established
2. **Universe-first where supported** — review extracted universe metadata and unresolved bindings before mapping reports
3. **Crystal Reports** — use the SDK or manual export for complex reports
4. **Lumira Designer** — rebuild as Power BI Embedded apps
5. **Validate running calculations** — BO running totals have sort-dependent behavior that may need manual DAX tuning
6. **Context review** — all context operator conversions should be manually validated
7. **@Aggregate_Aware** — review generated measures for correct granularity
