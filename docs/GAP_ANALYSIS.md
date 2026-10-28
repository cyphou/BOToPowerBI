# Gap Analysis — BO to Power BI Migration

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
returns 0. PBIP WebI and BIAR generation remains successful. The legacy UNV example
still has no usable datasource. A real stdio MCP subprocess test verifies that a
blocked Fabric migration returns structured failure without polluting stdout.

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

### Documentation And Operational Boundaries - 2026-10-28

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

## Supported Conversions (✅)

### Web Intelligence
| Feature | Status | Notes |
|---------|--------|-------|
| Data providers (queries) | ✅ | Universe-based and freehand SQL |
| Variables (Measure) | ✅ | → DAX measures |
| Variables (Dimension) | ✅ | → Calculated columns or columns |
| Variables (Detail) | ✅ | → Columns associated with dimension |
| Report tabs | ✅ | → Report pages |
| Prompts | ✅ | → Slicers + parameter tables |
| Query filters | ✅ | → M query filters or DAX filters |
| Report filters | ✅ | → Page/visual-level filters |
| Charts (bar, line, pie) | ✅ | → PBI chart visuals |
| Tables | ✅ | → PBI table visual |
| Cross-tabs | ✅ | → PBI matrix visual |
| Breaks | ✅ | → Groups in matrix |
| Sorts | ✅ | → Visual sort configuration |
| Input controls | ✅ | → Slicers |
| Alerters | ✅ | → Conditional formatting rules |
| Calculations (150+ functions) | ✅ | → DAX expressions |

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
| Business layer objects | ✅ | → Columns + measures |
| Data foundation tables | ✅ | → M partitions |
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
| **WebI sections** | Nested sections lose exact layout | Flatten to visual groups on page |
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
| **Crystal Page N of M** | Crystal-specific pagination | PBI handles pagination differently (paginated reports for exact) |
| **Lumira Designer apps** | Custom SDK-based applications | Rebuild as Power BI embedded / Power Apps |
| **OLAP universes (BW)** | SAP BW-specific OLAP queries | Use PBI SAP BW connector directly |

## Formula Gap Summary

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

1. **Start with WebI documents** — highest conversion fidelity
2. **Universe-first approach** — extract universe metadata to build the semantic model, then map reports
3. **Crystal Reports** — use the SDK or manual export for complex reports
4. **Lumira Designer** — rebuild as Power BI Embedded apps
5. **Validate running calculations** — BO running totals have sort-dependent behavior that may need manual DAX tuning
6. **Context review** — all context operator conversions should be manually validated
7. **@Aggregate_Aware** — review generated measures for correct granularity
