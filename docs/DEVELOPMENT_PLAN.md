# Development Plan — BO to Power BI Migration

> **Last updated**: 2026-03-26
> **Version**: 3.0 — Phases 1–5 complete; Phases 6–15 roadmap defined

## Current State Assessment

### Completed: Phases 1–5 (Sprints 1–33) ✅

| Metric | Value |
|--------|-------|
| Python files | 95 (72 powerbi_import + 13 bo_export + 10 tests) |
| Total LOC | ~50,450 |
| Tests | 244 (243 passing) |
| BO formula → DAX mappings | 150+ |
| Power Query M connectors | 15+ |
| Example artifacts | 11 (3 WebI, 2 Crystal, 2 UNX, 1 UNV, 1 Lumira, 1 BIAR, 1 config) |

### Project Modules

### Project Modules

| Module | LOC | Status | Notes |
|--------|-----|--------|-------|
| `migrate.py` | ~350 | **COMPLETE** | CLI routes to 5 extraction modes + generation + assess + deploy |
| `generate_report.py` | ~470 | **COMPLETE** | Batch migration + rich HTML report (Fluent/PBI design) |
| `bo_export/extract_bo_data.py` | ~250 | **COMPLETE** | Orchestrator → 15 JSON files |
| `bo_export/webi_extractor.py` | ~400 | **COMPLETE** | 14 sub-extractors, ZIP+XML, XXE-safe |
| `bo_export/crystal_extractor.py` | ~300 | **COMPLETE** | Groups, sorts, charts, subreports, conditional formatting |
| `bo_export/universe_extractor.py` | ~350 | **COMPLETE** | UNX+UNV, business layer, joins, contexts |
| `bo_export/lumira_extractor.py` | ~200 | **COMPLETE** | Discovery+Designer, JSON/XML |
| `bo_export/biar_reader.py` | ~150 | **COMPLETE** | ZIP slip defense, manifest parsing |
| `bo_export/dax_converter.py` | ~400 | **COMPLETE** | 150+ mappings, 87% coverage (107/123) |
| `bo_export/m_query_builder.py` | ~300 | **COMPLETE** | 15 connectors, 13 transforms |
| `bo_export/server_client.py` | ~350 | **COMPLETE** | 13 REST endpoints, stdlib only |
| `bo_export/converted_objects_adapter.py` | ~200 | **COMPLETE** | Bridge: 15 JSON types → converted_objects (17 keys) |
| `powerbi_import/` (72 files) | ~40,000 | **COMPLETE** | Full generation layer (TMDL, PBIR, visuals, deploy, Fabric) |
| `tests/` (10 files) | ~3,500 | **COMPLETE** | 244 tests covering all phases |

---

## Reuse Analysis: TableauToPowerBI → BOToPowerBI

**Source**: `../TableauToPowerBI/powerbi_import/` — 72 modules, 35,279 LOC

### Reuse Tiers

| Tier | Modules | LOC | Effort | Action |
|------|---------|-----|--------|--------|
| **Copy as-is** (source-agnostic) | 33 | ~10,200 | Zero | `deploy/`, `html_template`, `governance`, `dax_optimizer`, `dax_recipes`, `monitoring`, `plugins`, `progress`, `incremental`, `permission_mapper`, `thin_report_generator`, `merge_assessment`, `merge_config`, `merge_report_html`, `regression_suite`, `equivalence_tester`, `sla_tracker`, `recovery_report` |
| **Light adaptation** (rename/config) | 27 | ~12,500 | Low | `visual_generator`, `m_query_generator`, `shared_model`, `strategy_advisor`, `server_assessment`, `global_assessment`, `validator`, `security_validator`, `telemetry`, `schema_drift`, `wizard`, `fabric_*` generators, `alerts_generator`, `refresh_generator`, `llm_client` |
| **Heavy adaptation** (core logic) | 10 | ~12,600 | High | `tmdl_generator`, `pbip_generator`, `import_to_powerbi`, `assessment`, `comparison_report`, `visual_diff`, `migration_report`, `notebook_api`, `api_server`, `calc_column_utils` |

### Key Adaptation Work

**`tmdl_generator.py`** (4,774 LOC): Replace `tableau_export.datasource_extractor` imports → `bo_export.dax_converter` + `bo_export.m_query_builder`. Remove Tableau derivation-prefix regex. Core TMDL writing (80%) is source-agnostic.

**`pbip_generator.py`** (4,040 LOC): Remove Tableau shelf-aggregation prefix regex. Replace field-name cleaning functions. 80% of PBIR/visual JSON generation is reusable.

**`import_to_powerbi.py`** (484 LOC): Change source_dir from `tableau_export/` → `bo_export/`. Build mapping from BO's 15 JSON files → `converted_objects` dict with 17 keys.

**`assessment.py`** (1,296 LOC): Replace Tableau connector tiers/unsupported patterns with BO equivalents. Framework is reusable.

---

## `converted_objects` Schema Mapping

The central data contract between extraction and generation:

| Generation Key | BO Source(s) | Mapping Complexity |
|---------------|-------------|-------------------|
| `datasources` | datasources.json + tables.json + columns.json | Medium — restructure |
| `worksheets` | reports.json + charts.json | Medium — BO tabs/sections → visual defs |
| `dashboards` | reports.json (page layout) | Low — BO report → PBI page |
| `calculations` | formulas.json (DAX already converted) | Low — rename fields |
| `parameters` | prompts.json | Medium — prompt types → what-if params |
| `filters` | filters.json | Low — direct mapping |
| `stories` | — (no BO equivalent) | None |
| `actions` | — (no BO equivalent) | None |
| `sets` | — (no BO equivalent) | None |
| `groups` | groups.json | Low — break groups → PBI groups |
| `bins` | — (no BO equivalent) | None |
| `hierarchies` | columns.json (dimension hierarchies) | Medium |
| `sort_orders` | sorts.json | Low |
| `aliases` | columns.json (display names) | Low |
| `custom_sql` | custom_sql.json | Low — direct pass-through |
| `relationships` | joins.json | Medium — context resolution needed |
| `user_filters` | — (security profiles, Phase 4) | Deferred |

---

## Sprint Roadmap

### Phase 1: End-to-End Pipeline (Sprints 1–6)

**Goal**: Produce a valid `.pbip` from a simple WebI report.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **1** | Port `powerbi_import/` source-agnostic modules | Copy 33 modules from TableauToPowerBI as-is; verify imports | Generator |
| **2** | Build the bridge: `bo_converted_objects_adapter.py` | Map BO's 15 JSON types → `converted_objects` dict (17 keys) | Converter |
| **3** | Port & adapt `tmdl_generator.py` | Replace Tableau imports → BO imports; remove derivation-prefix cleaning; test with sample BO data | Generator |
| **4** | Port & adapt `pbip_generator.py` | Replace field-name cleaning; wire BO visual type mapping; generate first .pbip | Generator |
| **5** | Port & adapt `import_to_powerbi.py` | Wire full pipeline: BO extraction → adapter → generation → .pbip output; uncomment `migrate.py` generation | Orchestrator |
| **6** | End-to-end validation | Test: `.wid` → extract → adapt → generate → valid `.pbip` opens in PBI Desktop; fix issues | Tester |

**Exit criteria**: `python migrate.py sample.wid` produces a `.pbip` that opens in Power BI Desktop.

### Phase 2: Visual Fidelity & Formula Depth (Sprints 7–12)

**Goal**: Accurate visual mapping, complete formula conversion, prompt→slicer wiring.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **7** | BO visual type mapping table | Map all BO chart types (bar, line, pie, crosstab, gauge, waterfall, scatter, treemap, geo, funnel) → 118 PBI visual types in `visual_generator.py` | Generator |
| **8** | Prompt → Slicer/Parameter | Convert BO prompts (text, date, LOV, numeric, multi-value) → PBI slicers + parameter tables + TMDL `What-If` params | Converter |
| **9** | DAX depth: context operators | Convert `In()` → `CALCULATE + FILTER`, `ForEach` → `SUMX/AVERAGEX`, `ForAll` → `CALCULATE + ALLEXCEPT`; replace placeholder comments with real DAX | Converter |
| **10** | DAX depth: running calculations | `RunningSum/Count/Average` → sort-aware `CALCULATE + FILTER(ALLSELECTED, ...)` patterns; nested `If/ElseIf/Else` → `SWITCH(TRUE(), ...)` | Converter |
| **11** | Universe join → relationship | Context-aware join resolution: detect star/snowflake, resolve BO contexts to disambiguate paths, generate TMDL relationships with correct cardinality | Generator |
| **12** | Alerter → conditional formatting | WebI alerters (color/icon/font rules) → PBI conditional formatting JSON rules in visual definitions | Generator |

**Exit criteria**: Multi-tab WebI report with formulas, prompts, and charts produces a PBI report with correct visuals, working slicers, and valid DAX.

### Phase 3: Crystal Reports & BIAR Batch (Sprints 13–18)

**Goal**: Support Crystal Reports binary format and enterprise batch migration from BIAR archives.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **13** | Crystal extractor: groups, sorts, charts | Implement 5 stub extractors in `crystal_extractor.py` (binary section parsing or regex heuristics) | Extractor |
| **14** | Crystal formula → DAX deep support | `{Table.Field}` qualified refs, `{@Formula}` cross-references, `WhilePrintingRecords`/`WhileReadingRecords` evaluation timing → DAX | Converter |
| **15** | Crystal subreport → drill-through page | Detect subreport links + parameter binding → PBI drill-through pages with filter context | Generator |
| **16** | Crystal cross-tab → matrix visual | Row/column groups + summary fields → PBI matrix configuration with row/column/value wells | Generator |
| **17** | BIAR batch generation pipeline | Wire `extract_from_biar()` → adapter → generation for each artifact; progress tracking; error isolation per artifact | Orchestrator |
| **18** | Batch validation & error reporting | Per-artifact pass/fail scoring; HTML batch report with success rate, error detail, estimated manual effort | Tester |

**Exit criteria**: `python migrate.py --biar archive.biar --output-dir /tmp/batch` produces valid `.pbip` for each artifact; Crystal Reports with groups/subreports generate drill-through pages.

### Phase 4: Assessment & Enterprise (Sprints 19–26)

**Goal**: Portfolio assessment, shared models, deployment, governance.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **19** | Port & adapt `assessment.py` | BO-specific connector tiers, formula gap patterns, complexity scoring (9 categories) | Assessor |
| **20** | Port `server_assessment.py` + `global_assessment.py` | Portfolio-level complexity scoring, wave planning, cross-report merge opportunities | Assessor |
| **21** | Port `shared_model.py` + merge engine | Table fingerprinting from BO universe metadata; multi-report deduplication; thin report generation | Merger |
| **22** | Port `validator.py` + `security_validator.py` | TMDL/PBIR validation; BO function leak detection (replace Tableau leak patterns: `COUNTD/ZN/DATETRUNC` → BO patterns: `=Sum/=Count/NoFilter/Previous`) | Tester |
| **23** | DAX optimizer integration | Port `dax_optimizer.py` (already source-agnostic) + wire into pipeline; `IF→SWITCH`, `ISBLANK→COALESCE`, Time Intelligence measures | Converter |
| **24** | Port deployment framework | Copy `deploy/` (100% agnostic); wire `--deploy WORKSPACE_ID` in `migrate.py`; test with Fabric REST API | Deployer |
| **25** | Governance & telemetry | Port `governance.py`, `telemetry.py`, `monitoring.py`; BO naming convention enforcement; PII detection | Deployer |
| **26** | `--assess` mode end-to-end | Wire assessment into CLI; generate HTML assessment report with readiness score, effort estimate, wave plan | Assessor |

**Exit criteria**: `python migrate.py --server https://bo:6405 --folder /Public --assess` produces portfolio assessment with wave plan. `python migrate.py report.wid --deploy WORKSPACE_ID` deploys to Fabric.

### Phase 5: Fabric-Native & Advanced (Sprints 27–33)

**Goal**: Fabric-native output, @Aggregate_Aware, security profiles, schedule migration.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **27** | Port Fabric generators | Adapt 8 Fabric modules (`lakehouse_generator`, `dataflow_generator`, `notebook_generator`, `pipeline_generator`, `fabric_semantic_model_generator`, etc.); replace `tableau_export` imports → `bo_export` | Generator |
| **28** | `@Aggregate_Aware` conversion | Universe multi-granularity measures → DAX `SUMMARIZE` + `SWITCH(HASONEVALUE(...))` patterns | Converter |
| **29** | BO context operator deep conversion | `In(dimension; context)` → `CALCULATE + FILTER`; `ForEach` → `SUMX`; `ForAll` → `CALCULATE + ALLEXCEPT + USERELATIONSHIP` | Converter |
| **30** | Security profile migration | BO security profiles/access levels → RLS roles + workspace permissions + `permission_mapper.py` PowerShell scripts | Generator |
| **31** | Schedule migration | BO scheduled instances → PBI scheduled refresh + email subscriptions; port `refresh_generator.py` | Deployer |
| **32** | Multi-tenant deployment | Port `multi_tenant.py`; per-tenant connection overrides; template substitution | Deployer |
| **33** | Incremental migration | Port `incremental.py` + `schema_drift.py`; change tracking; skip unchanged artifacts; schema drift alerts | Orchestrator |

**Exit criteria**: `python migrate.py report.wid --output-format fabric` produces Lakehouse + Dataflow + Semantic Model + Pipeline. Security profiles mapped to RLS.

### Phase 6: Polish & Tooling (Sprints 34–40)

**Goal**: Performance, API server, Web UI, plugin system, documentation.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **34** | Performance optimization | Parallel extraction (`concurrent.futures`), batch generation, memory profiling; target 10× throughput for BIAR batches | Orchestrator |
| **35** | Port comparison/visual-diff reports | Adapt `comparison_report.py`, `visual_diff.py`, `migration_report.py` for BO→PBI side-by-side; screenshot comparison | Tester |
| **36** | REST API server | Adapt `api_server.py` — multipart upload, async job queue, BO extensions in `ALLOWED_EXTENSIONS`; OpenAPI spec | Orchestrator |
| **37** | Web UI wizard | Adapt `wizard.py` (CLI) + add Streamlit/web version; 6-step: upload → assess → configure → migrate → validate → deploy | Orchestrator |
| **38** | Plugin system | Port `plugins.py` + `marketplace.py` (both source-agnostic); custom BO visual mapping hooks; DAX post-processing | Orchestrator |
| **39** | LLM-assisted refinement | Port `llm_client.py`; change system prompt from Tableau→BO; LLM DAX review, measure naming, visual suggestions | Converter |
| **40** | Documentation & examples | Enterprise guide finalization, FAQ, sample BO artifacts (.wid/.rpt/.unx), real-world migration examples, video walkthroughs | Tester |

**Exit criteria**: REST API + Web UI operational. Plugin system documented. 95% test coverage. Enterprise guide complete.

---

### Phase 7: Real-World Validation & Test Hardening (Sprints 41–46)

**Goal**: Validate against production BO content; harden edge cases; build regression corpus.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **41** | Golden corpus — WebI | Collect 50+ real-world WebI documents across industries (finance, retail, HR, logistics); run pipeline; score conversion fidelity | Tester |
| **42** | Golden corpus — Crystal & Universe | Collect 30+ Crystal Reports + 20+ Universe files; run pipeline; catalog extraction + generation gaps | Tester |
| **43** | Edge-case fix sprint | Fix top-20 failures from golden corpus: encoding issues, nested formulas, unusual XML structures, large file handling | Extractor |
| **44** | Regression suite build | Generate snapshot `.pbip` golden outputs for 100 artifacts; wire `regression_suite.py` into CI; fail on drift | Tester |
| **45** | Equivalence testing | Run `equivalence_tester.py` on all DAX conversions; compare against BO formula results from sample data; catalog mismatches | Converter |
| **46** | Fidelity benchmark report | Publish fidelity scorecard: % of WebI/Crystal/Universe features accurately converted; per-category pass rates; gap heat-map | Assessor |

**Exit criteria**: 100-artifact regression corpus. Automated golden snapshot tests in CI. Published fidelity benchmarks: ≥90% WebI, ≥75% Crystal, ≥85% Universe.

---

### Phase 8: Crystal Reports Deep Support (Sprints 47–53)

**Goal**: Native Crystal binary parsing; full group/subreport/chart conversion without SAP SDK dependency.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **47** | Crystal binary format reverse engineering | Document `.rpt` binary structure: header, sections, object-record layout; build hex-to-structure parser for fields, formulas, groups | Extractor |
| **48** | Crystal group hierarchy extraction | Parse multi-level group trees (Group 1 → Group 2 → Detail); header/footer slot detection; group sort extraction | Extractor |
| **49** | Crystal chart extraction | Parse chart definitions: chart type, data fields, axes, legends, series; support bar/line/pie/scatter/area | Extractor |
| **50** | Crystal cross-tab → Matrix | Row groups + column groups + summary fields → PBI matrix visual with row/column/value wells; subtotals + grand totals | Generator |
| **51** | Crystal subreport linking | Detect subreport insertion points; parameter binding between main and sub; generate PBI drill-through pages with filter context | Generator |
| **52** | Crystal page layout → Paginated Report | Map Crystal's banded layout (Report/Page/Group Header-Footer-Detail) → PBI Paginated Report RDL when layout fidelity is critical | Generator |
| **53** | Crystal integration tests | End-to-end tests: 20 Crystal fixtures covering groups, subreports, cross-tabs, charts, running totals; snapshot golden outputs | Tester |

**Exit criteria**: Crystal binary parser extracts groups/charts/subreports without SAP SDK. Crystal fidelity ≥85%. Paginated Report output option for layout-critical reports.

---

### Phase 9: BO Server Live Integration (Sprints 54–60)

**Goal**: Live migration from BO CMS/RESTful Web Services; schedule inventory; user mapping; incremental sync.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **54** | BO server discovery & inventory | `server_client.py` — enumerate all folders, documents, universes, connections, users, groups; export full inventory JSON | Extractor |
| **55** | Live document download pipeline | Stream `.wid`/`.rpt`/`.unx` from BO server via REST API; queue-based download with retry and rate-limiting (`429` handling) | Orchestrator |
| **56** | Schedule inventory & mapping | Extract BO scheduled instances (frequency, recipients, format, destination); generate PBI refresh schedule + subscription matrix | Deployer |
| **57** | User & group mapping | Map BO users/groups/access levels → Entra ID users/security groups; generate `permission_mapper.py` PowerShell scripts for workspace RBAC | Deployer |
| **58** | Incremental server sync | Track last-sync timestamp per artifact; only re-migrate changed documents; schema-drift detection between runs | Orchestrator |
| **59** | BO server → Fabric direct pipeline | End-to-end: BO CMS → extract → generate → deploy to Fabric workspace; single CLI command with `--server` + `--deploy` flags | Deployer |
| **60** | Server mode integration tests | Mock BO REST API responses; test discovery, download, incremental sync, error handling; test with BI 4.2 + 4.3 response formats | Tester |

**Exit criteria**: `python migrate.py --server https://bo:6405 --folder /Public --deploy WORKSPACE_ID` runs end-to-end. Incremental sync only processes changed artifacts. User/group mapping generates Entra ID scripts.

---

### Phase 10: Semantic Model Intelligence (Sprints 61–67)

**Goal**: Auto-detect star schemas, optimize relationships, generate lineage maps, impact analysis.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **61** | Star/snowflake schema detection | Analyze universe joins + table cardinalities → classify fact/dimension tables; auto-generate optimal TMDL relationships with correct cardinality (1:M, M:1) | Generator |
| **62** | Relationship optimizer | Detect redundant/conflicting joins; resolve BO contexts to inactive relationships with `USERELATIONSHIP`; eliminate bridge tables when possible | Generator |
| **63** | Auto Calendar table | Detect date columns across all tables; generate shared Calendar/Date table with fiscal year support; auto-create time intelligence measures (YTD, QTD, MTD, YoY) | Converter |
| **64** | Lineage map generation | Build column-level lineage: BO universe object → extracted column → DAX measure → visual binding; output SVG flow diagram + interactive HTML | Assessor |
| **65** | Impact analysis engine | Given a universe change (table rename, column removal, join change), predict which reports/measures/visuals are affected; output impact report | Assessor |
| **66** | Measure optimization engine | Detect duplicate measures across reports; consolidate into shared calculation groups; apply `dax_optimizer.py` auto-simplification patterns | Converter |
| **67** | Model quality scorecard | Score generated semantic models: relationship coverage, measure complexity, naming consistency, unused columns, circular dependencies; HTML report | Assessor |

**Exit criteria**: Auto-generated star schemas with correct cardinality. Calendar table with 6 time intelligence measures. Column-level lineage SVG. Impact analysis for universe changes.

---

### Phase 11: Advanced Visual Fidelity (Sprints 68–74)

**Goal**: Pixel-level visual matching; theme extraction; conditional formatting; custom visuals.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **68** | BO theme → PBI theme.json | Extract BO document colors, fonts, chart palettes → generate PBI `theme.json` (Fluent tokens); auto-detect corporate palette | Generator |
| **69** | Visual layout engine | Preserve BO tab/section spatial layout → PBI page canvas positioning; handle free-form placement, overlapping, header/footer zones | Generator |
| **70** | Conditional formatting deep | Multi-condition alerters → PBI conditional formatting rules (background, font color, icons, data bars); range-based + top-N + field-based rules | Generator |
| **71** | Drill-through & tooltip pages | BO document links + subreport navigation → PBI drill-through pages; detail context fields auto-detected; tooltip pages for hover detail | Generator |
| **72** | Bookmarks & navigation | BO input controls + tab navigation → PBI bookmarks + button navigation; section visibility states → bookmark groups | Generator |
| **73** | Custom visual mapping | Map BO chart types with no native PBI equivalent → certified custom visuals (Deneb/Vega-Lite for complex charts, Charticulator for custom layouts) | Generator |
| **74** | Visual fidelity scoring | Screenshot comparison: BO report vs generated PBI report; compute pixel-diff SSIM score per visual; aggregate fidelity percentage | Tester |

**Exit criteria**: Theme extraction produces valid `theme.json`. Layout spatial accuracy ≥80%. Conditional formatting covers 3+ rule types. Visual SSIM fidelity ≥70%.

---

### Phase 12: Enterprise Scale & Performance (Sprints 75–81)

**Goal**: Handle 10,000+ artifact portfolios; parallel processing; streaming; caching; resilience.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **75** | Parallel extraction engine | `concurrent.futures.ProcessPoolExecutor` for CPU-bound XML/binary parsing; configurable worker count; per-file timeout with graceful kill | Orchestrator |
| **76** | Parallel generation engine | Multi-process TMDL/PBIR generation; shared progress bar; artifact-level error isolation (one failure doesn't block batch) | Orchestrator |
| **77** | Streaming BIAR processing | Stream-extract artifacts from BIAR without loading full archive in memory; process artifacts as they're extracted; memory cap enforcement | Extractor |
| **78** | Result caching layer | Hash-based cache for extraction + generation results; skip re-processing unchanged inputs; configurable cache dir with TTL | Orchestrator |
| **79** | Large-file handling | Chunk processing for WebI documents >100 MB; streaming XML parsing (`iterparse`); configurable memory limits per artifact | Extractor |
| **80** | Resilience & retry framework | Transient failure retry with exponential backoff; checkpoint/resume for interrupted batch migrations; dead-letter queue for failed artifacts | Orchestrator |
| **81** | Performance benchmarks | Benchmark suite: 100/500/1000/5000 artifacts; measure throughput (artifacts/min), memory peak, CPU utilization; publish results | Tester |

**Exit criteria**: Process 1,000 artifacts in <30 min (8 cores). Memory stays <4 GB for any single artifact. Interrupted batches resume from checkpoint.

---

### Phase 13: AI-Assisted Migration (Sprints 82–89)

**Goal**: LLM-powered formula repair, visual suggestions, naming standardization, documentation generation.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **82** | LLM DAX repair | Send failed/placeholder DAX formulas to Azure OpenAI; LLM corrects syntax, resolves broken references, explains changes; human-in-the-loop approval | Converter |
| **83** | LLM measure naming | Standardize measure names using LLM: remove BO prefixes, apply business-friendly naming conventions, detect duplicates across reports | Converter |
| **84** | LLM visual suggestion | Analyze data shape + measure types → LLM suggests optimal PBI visual type and configuration; override default mapping when LLM confidence is high | Generator |
| **85** | LLM schema optimization | Analyze generated TMDL → suggest denormalization, column removal, relationship changes; output optimization report with rationale | Generator |
| **86** | RAG-based formula knowledge | Build vector index of BO→DAX conversion examples; retrieve similar conversions for context; improve accuracy on rare/complex formulas | Converter |
| **87** | Auto-documentation generation | LLM generates: measure descriptions, table annotations, report purpose summary, data dictionary; populate TMDL `description` fields | Generator |
| **88** | Migration copilot chat | Interactive chat interface: user describes BO report behavior → copilot explains equivalent PBI pattern; suggests manual adjustments | Orchestrator |
| **89** | AI confidence scoring | Per-conversion confidence score (0–100) based on formula complexity, LLM agreement, pattern-match coverage; flag low-confidence conversions for review | Assessor |

**Exit criteria**: LLM repairs 80%+ of placeholder DAX formulas. Auto-documentation populates descriptions for all measures/tables. Confidence scoring flags ≤10% for manual review.

---

### Phase 14: Multi-Platform Output (Sprints 90–96)

**Goal**: Generate Paginated Reports (RDL), Power Apps, Excel templates, and Fabric Real-Time Analytics outputs.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **90** | Paginated Report (RDL) generator | Crystal banded layout → SSRS/PBI Paginated Report `.rdl`; precise page breaks, headers/footers, subreport embedding | Generator |
| **91** | RDL expression converter | BO/Crystal formulas → RDL expressions (VB.NET syntax); shared dataset references; parameter wiring for paginated reports | Converter |
| **92** | Excel template generator | Simple BO tabular reports → Excel `.xlsx` with Power Query connections, PivotTables, conditional formatting; data refresh via PBI dataset | Generator |
| **93** | Power Apps screen generator | BO input-heavy reports (forms, data entry) → Power Apps canvas app screens with gallery/form controls connected to Dataverse or PBI dataset | Generator |
| **94** | Fabric Real-Time Analytics | BO real-time dashboards → KQL database + Eventstream + Real-Time Dashboard; streaming ingestion configuration | Generator |
| **95** | Fabric notebook ETL | Complex BO custom SQL + stored procedures → PySpark notebooks; Delta table output; scheduled pipeline execution via Fabric Data Factory | Generator |
| **96** | Output format router | `--output-format` flag: `pbip` (default), `fabric`, `rdl`, `excel`, `powerapp`, `realtime`; format-specific validation; multi-format in single run | Orchestrator |

**Exit criteria**: `--output-format rdl` produces valid Paginated Reports for Crystal sources. Excel templates connect to PBI datasets. Output router supports 6 formats.

---

### Phase 15: Marketplace & Ecosystem (Sprints 97–104)

**Goal**: Plugin marketplace, community connectors, VS Code extension, partner integrations.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **97** | VS Code extension | Dedicated VS Code extension: right-click `.wid`/`.rpt` → Migrate; inline assessment results; migration status panel; integrated report viewer | Orchestrator |
| **98** | Plugin SDK & registry | Formal plugin API: `register_extractor()`, `register_visual_mapper()`, `register_dax_postprocessor()`; plugin discovery from local dir + remote registry | Orchestrator |
| **99** | Community connector framework | Extensible connector architecture: add new BO sources (e.g., Analysis for OLAP, Web Applications Designer) via plugin without core changes | Extractor |
| **100** | SAP BW connector plugin | Plugin: SAP BW BEx queries/InfoProviders → PBI semantic model; map BW hierarchies → PBI parent-child hierarchies; variable mapping | Extractor |
| **101** | Partner API & webhooks | REST API for partners: submit migration jobs, receive webhook callbacks on completion, download results; API key authentication; rate limiting | Orchestrator |
| **102** | Migration-as-a-Service | Docker Compose stack: API server + worker pool + Redis queue + PostgreSQL state store; Kubernetes Helm chart for cloud deployment | Deployer |
| **103** | Telemetry dashboard (Fabric) | Aggregate telemetry → Fabric Lakehouse; Real-Time Dashboard showing: migrations/day, success rate, avg fidelity, formula gap trends, top errors | Deployer |
| **104** | GA release & launch | Final QA pass; security audit; OSS license review; PyPI package (`pip install bo2pbi`); documentation site (MkDocs); launch blog post | Tester |

**Exit criteria**: VS Code extension published. Plugin SDK documented with 2+ community plugins. Docker MaaS stack operational. Published on PyPI with ≥95% test coverage.

---

## Dependency Graph

```
Phase 1 (Foundation) ✅ DONE
├── Sprint 1: Copy agnostic modules ──────────────────┐
├── Sprint 2: Bridge adapter ─────────────────────────┤
├── Sprint 3: tmdl_generator adaptation ──────────────┤
├── Sprint 4: pbip_generator adaptation ──────────────┤
├── Sprint 5: Wire full pipeline ─────────────────────┤
└── Sprint 6: E2E validation ─────────────────────────┘
        │
        ▼
Phase 2 (Fidelity) ✅ DONE          Phase 3 (Crystal & BIAR) ✅ DONE
├── Sprint 7-8: Visuals/Prompts     ├── Sprint 13: Crystal stubs
├── Sprint 9-10: DAX depth          ├── Sprint 14-16: Crystal→PBI
├── Sprint 11: Relationships        ├── Sprint 17: BIAR batch
└── Sprint 12: Cond. formatting     └── Sprint 18: Batch validation
        │                                  │
        ▼                                  ▼
Phase 4 (Enterprise) ✅ DONE ─────────────────────────┐
├── Sprint 19-20: Assessment                           │
├── Sprint 21: Shared model                            │
├── Sprint 22-23: Validation + DAX optimizer           │
├── Sprint 24: Deployment                              │
├── Sprint 25: Governance                              │
└── Sprint 26: --assess E2E                            │
        │                                              │
        ▼                                              │
Phase 5 (Advanced) ✅ DONE ◄──────────────────────────┘
├── Sprint 27: Fabric-native
├── Sprint 28-29: @AggAware + Contexts
├── Sprint 30-31: Security + Schedules
├── Sprint 32-33: Multi-tenant + Incremental
        │
        ▼
Phase 6 (Polish & Tooling)
├── Sprint 34: Perf optimization
├── Sprint 35: Comparison reports
├── Sprint 36-37: API + Web UI
├── Sprint 38-39: Plugins + LLM
└── Sprint 40: Docs & examples
        │
        ▼
Phase 7 (Real-World Validation) ◄─────── feedback loop
├── Sprint 41-42: Golden corpus (50+ WebI, 30+ Crystal)
├── Sprint 43: Edge-case fix sprint
├── Sprint 44-45: Regression + equivalence
└── Sprint 46: Fidelity benchmarks
        │
        ├──────────────────────────┐
        ▼                          ▼
Phase 8 (Crystal Deep)     Phase 9 (BO Server Live)
├── Sprint 47-49: Binary    ├── Sprint 54-55: Discovery
│   parser + groups/charts  ├── Sprint 56-57: Schedules/Users
├── Sprint 50-52: Matrix/   ├── Sprint 58-59: Incr. sync
│   Subreport/Paginated     └── Sprint 60: Server tests
└── Sprint 53: Integration
        │                          │
        ▼                          ▼
Phase 10 (Semantic Intelligence) ◄─────────────────────┐
├── Sprint 61-62: Star schema + relationship optimizer  │
├── Sprint 63: Auto Calendar + time intelligence        │
├── Sprint 64-65: Lineage + impact analysis             │
└── Sprint 66-67: Measure optimization + quality score  │
        │                                               │
        ▼                                               │
Phase 11 (Visual Fidelity)                              │
├── Sprint 68: Theme extraction                         │
├── Sprint 69-70: Layout + conditional formatting       │
├── Sprint 71-72: Drill-through + bookmarks             │
└── Sprint 73-74: Custom visuals + SSIM scoring         │
        │                                               │
        ▼                                               │
Phase 12 (Enterprise Scale) ◄──────────────────────────┘
├── Sprint 75-76: Parallel extract + generate
├── Sprint 77-79: Streaming + caching + large files
└── Sprint 80-81: Resilience + benchmarks
        │
        ├──────────────────────────┐
        ▼                          ▼
Phase 13 (AI-Assisted)     Phase 14 (Multi-Platform)
├── Sprint 82-83: LLM DAX  ├── Sprint 90-91: RDL/Paginated
│   repair + naming         ├── Sprint 92-93: Excel + PowerApps
├── Sprint 84-86: Visual    ├── Sprint 94-95: RT Analytics
│   AI + RAG knowledge      └── Sprint 96: Output router
├── Sprint 87-88: Auto-docs
│   + migration copilot
└── Sprint 89: Confidence
        │                          │
        ▼                          ▼
Phase 15 (Marketplace & GA) ◄─────┘
├── Sprint 97: VS Code extension
├── Sprint 98-99: Plugin SDK + connectors
├── Sprint 100: SAP BW plugin
├── Sprint 101-102: Partner API + MaaS
├── Sprint 103: Telemetry dashboard
└── Sprint 104: GA release (PyPI, docs, launch)
```

**Parallelism**: Phase 8 ‖ Phase 9, Phase 13 ‖ Phase 14.

---

## Test Strategy

### Coverage Targets

| Phase | Target | Tests | Focus Areas |
|-------|--------|-------|-------------|
| Phase 1–5 ✅ | ≥85% | 244 | Bridge adapter, TMDL, PBIR, E2E, DAX, assessment, Fabric |
| Phase 6 | ≥88% | 400+ | API server, Web UI, plugins, comparison reports |
| Phase 7 | ≥88% | 500+ | Golden corpus snapshots, regression suite, equivalence |
| Phase 8 | ≥89% | 700+ | Crystal binary parsing, groups, subreports, paginated |
| Phase 9 | ≥90% | 900+ | Server discovery, incremental sync, user mapping |
| Phase 10 | ≥90% | 1,200+ | Star schema detection, lineage, impact analysis |
| Phase 11 | ≥91% | 1,500+ | Theme extraction, layout engine, SSIM visual scoring |
| Phase 12 | ≥92% | 2,000+ | Parallel processing, caching, resilience, benchmarks |
| Phase 13 | ≥93% | 2,500+ | LLM integration, RAG, confidence scoring |
| Phase 14 | ≥94% | 3,000+ | RDL, Excel, Power Apps, Real-Time output |
| Phase 15 | ≥95% | 3,500+ | VS Code extension, plugin SDK, MaaS, PyPI package |

### Test Categories

| Category | Scope | Tooling |
|----------|-------|---------|
| **Unit** | Individual functions (DAX convert, M build, visual map) | pytest + fixtures |
| **Integration** | Full pipeline: `.wid` → `.pbip` | pytest + temp dirs + TMDL parser |
| **Snapshot** | Regression: golden `.pbip` output comparison | `regression_suite.py` |
| **Equivalence** | DAX formula output matching expected values | `equivalence_tester.py` |
| **Security** | ZIP slip, XXE, path traversal, credential redaction | pytest-security fixtures |
| **BIAR Batch** | Multi-artifact archive processing | BIAR fixtures with 5+ artifact types |
| **Performance** | Throughput benchmarks, memory profiling | pytest-benchmark + custom harness |
| **Visual** | Screenshot comparison, SSIM scoring | Playwright + Pillow/scikit-image |
| **LLM** | Prompt quality, hallucination detection | Mock LLM + golden response comparison |

### Currently Passing (244 tests)

| File | Tests | Status |
|------|-------|--------|
| `tests/test_dax_converter.py` | 56 | ✅ All pass |
| `tests/test_biar_reader.py` | 12 | ✅ All pass |
| `tests/test_cli.py` | 13 | ✅ All pass |
| `tests/test_crystal_pipeline.py` | 21 | ✅ All pass |
| `tests/test_extraction.py` | 8 | ✅ 7/8 (1 Windows PermissionError) |
| `tests/test_webi_extractor.py` | 9 | ✅ All pass |
| `tests/test_e2e_pipeline.py` | 49 | ✅ All pass |
| `tests/test_assessment.py` | 46 | ✅ All pass |
| `tests/test_phase5_advanced.py` | 32 | ✅ All pass |

---

## Reuse Execution Plan

### Sprint 1 Detailed: Copy Source-Agnostic Modules ✅ DONE

**From `../TableauToPowerBI/powerbi_import/`** — copy these 33 modules unchanged:

```
# Deploy (100% agnostic — 11 files, 2,665 LOC)
deploy/auth.py, deploy/client.py, deploy/deployer.py, deploy/pbi_client.py,
deploy/pbi_deployer.py, deploy/bundle_deployer.py, deploy/multi_tenant.py,
deploy/pbix_packager.py, deploy/utils.py, deploy/config/settings.py,
deploy/config/environments.py

# Governance & Quality (6 files, ~1,800 LOC)
governance.py, permission_mapper.py, monitoring.py, sla_tracker.py,
recovery_report.py, plugins.py

# DAX & Templates (3 files, ~770 LOC)
dax_optimizer.py, dax_recipes.py, model_templates.py

# Merge Engine (4 files, ~1,750 LOC)
thin_report_generator.py, merge_assessment.py, merge_config.py, merge_report_html.py

# Testing Utilities (2 files, ~290 LOC)
regression_suite.py, equivalence_tester.py

# Reporting & UI (5 files, ~1,800 LOC)
html_template.py, progress.py, marketplace.py, incremental.py, paginated_generator.py
```

**Verify**: All imports resolve; no `tableau_export` references in these modules.

### Sprint 2 Detailed: Bridge Adapter

Create `bo_export/converted_objects_adapter.py`:

```python
def adapt_bo_to_converted_objects(extracted_data: dict) -> dict:
    """Map BO's 15 extracted JSON types → generation's converted_objects schema."""
    return {
        "datasources": _adapt_datasources(extracted_data),      # datasources + tables + columns
        "worksheets": _adapt_worksheets(extracted_data),         # reports + charts
        "dashboards": _adapt_dashboards(extracted_data),         # reports (page layout)
        "calculations": _adapt_calculations(extracted_data),     # formulas (DAX already converted)
        "parameters": _adapt_parameters(extracted_data),         # prompts
        "filters": _adapt_filters(extracted_data),               # filters
        "stories": [],                                           # no BO equivalent
        "actions": [],                                           # no BO equivalent
        "sets": [],                                              # no BO equivalent
        "groups": _adapt_groups(extracted_data),                 # groups
        "bins": [],                                              # no BO equivalent
        "hierarchies": _adapt_hierarchies(extracted_data),       # columns (dimension hierarchies)
        "sort_orders": _adapt_sorts(extracted_data),             # sorts
        "aliases": _adapt_aliases(extracted_data),               # columns (display names)
        "custom_sql": extracted_data.get("custom_sql", []),      # pass-through
        "relationships": _adapt_relationships(extracted_data),   # joins
        "user_filters": [],                                      # deferred to Phase 5
    }
```

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation | Phase |
|------|--------|-----------|------------|-------|
| Crystal .rpt binary format too opaque without SDK | Groups/sorts/charts remain stubs | Medium | Fallback: require Crystal-to-PDF or Crystal-to-Excel pre-export; document as manual step | 8 |
| BO context operators don't translate cleanly to DAX | Formula accuracy for complex reports | High | `ForEach`/`ForAll`/`In` generate `/* TODO */` comments; add LLM-assisted refinement in Phase 13 | 5, 13 |
| `@Aggregate_Aware` multi-granularity logic | Incorrect aggregation in PBI | Medium | Generate `SWITCH(HASONEVALUE(...))` + doc comment flagging manual review | 5, 10 |
| TableauToPowerBI `tmdl_generator` API drift | Port breaks after upstream updates | Low | Pin to specific commit; track upstream changes quarterly | 6 |
| BO Server REST API version differences (BI 4.x vs 4.3) | Server mode fails on older BO versions | Medium | Version detection in `server_client.py`; graceful degradation for missing endpoints | 9 |
| BIAR archives with >1000 artifacts | Memory/perf issues in batch mode | Medium | Streaming extraction; per-artifact error isolation; configurable parallelism | 12 |
| LLM hallucination in DAX repair | Incorrect formulas introduced silently | High | Human-in-the-loop approval; confidence scoring; equivalence testing against known results | 13 |
| Paginated Report RDL format complexity | Incomplete layout mapping for complex Crystal reports | Medium | Focus on 80% common patterns; fallback to manual RDL editing for edge cases | 14 |
| Plugin security (untrusted code execution) | Malicious plugins execute arbitrary code | Medium | Plugin sandboxing; code signing; permission model for file/network access | 15 |
| PyPI package size with all dependencies | Large install footprint | Low | Core package minimal (stdlib only); optional extras `[fabric]`, `[ai]`, `[server]` | 15 |

---

## Success Metrics

| Metric | Phase 5 ✅ | Phase 7 | Phase 10 | Phase 13 | Phase 15 |
|--------|-----------|---------|----------|----------|----------|
| **WebI conversion fidelity** | ≥85% | ≥90% | ≥93% | ≥97% | ≥98% |
| **Crystal conversion fidelity** | ≥60% | ≥75% | ≥85% | ≥90% | ≥93% |
| **Universe conversion fidelity** | ≥80% | ≥85% | ≥92% | ≥95% | ≥97% |
| **Formula accuracy** | 87% (107/123) | 90% | 93% | 97% (LLM) | 98% |
| **Visual type coverage** | 15 types | 25 types | 35 types | 40+ types | 45+ types |
| **Pipeline throughput** | 1 artifact/10s | 1 artifact/5s | 1 artifact/2s | 1 artifact/2s | 1 artifact/1s |
| **Batch capacity** | 50 artifacts | 500 artifacts | 2,000 artifacts | 5,000 artifacts | 10,000+ |
| **Test count** | 244 | 500+ | 1,500+ | 2,500+ | 3,500+ |
| **Test coverage** | ≥85% | ≥88% | ≥90% | ≥93% | ≥95% |
| **Output formats** | 2 (pbip, fabric) | 2 | 2 | 2 | 6 |
| **Deployment targets** | Local + Fabric | Local + Fabric | Local + Fabric | + PBI Service | + MaaS (K8s) |
| **AI features** | — | — | Lineage | LLM + RAG + docs | + copilot chat |
