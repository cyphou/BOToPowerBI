# Development Plan — BO to Power BI Migration

> **Last updated**: 2026-03-25
> **Version**: 2.0 — Grounded in actual implementation audit

## Current State Assessment

### What's Done (Extraction Layer — ~85% complete)

| Module | LOC | Status | Notes |
|--------|-----|--------|-------|
| `migrate.py` | ~350 | **SKELETON** | CLI routes to 5 extraction modes; generation/assess/deploy commented out |
| `bo_export/extract_bo_data.py` | ~250 | **COMPLETE** | Orchestrator → 15 JSON files |
| `bo_export/webi_extractor.py` | ~400 | **COMPLETE** | 14 sub-extractors, ZIP+XML, XXE-safe |
| `bo_export/crystal_extractor.py` | ~300 | **SKELETON** | 10/15 extractors work; joins/groups/sorts/charts/cond-format return `[]` |
| `bo_export/universe_extractor.py` | ~350 | **COMPLETE** | UNX+UNV, business layer, joins, contexts |
| `bo_export/lumira_extractor.py` | ~200 | **COMPLETE** | Discovery+Designer, JSON/XML |
| `bo_export/biar_reader.py` | ~150 | **COMPLETE** | ZIP slip defense, manifest parsing |
| `bo_export/dax_converter.py` | ~400 | **COMPLETE** | 150+ mappings, 87% coverage (107/123) |
| `bo_export/m_query_builder.py` | ~300 | **COMPLETE** | 15 connectors, 13 transforms |
| `bo_export/server_client.py` | ~350 | **COMPLETE** | 13 REST endpoints, stdlib only |
| `generate_report.py` | ~200 | **COMPLETE** | HTML migration dashboard |
| Tests (6 files) | ~600 | **COMPLETE** | 65+ tests, all pass today |

### What's Missing (Generation Layer — 0% complete)

The `powerbi_import/` directory contains only `__init__.py`. No Power BI output can be produced.

### Critical Gap: The Bridge Layer

BO extraction produces **15 JSON files** with BO-native structure. The generation layer (from TableauToPowerBI) consumes a `converted_objects` dict with **17 keys** in a different schema. A **mapping/adapter layer** is the #1 priority.

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
| **34** | Performance optimization | Parallel extraction (`concurrent.futures`), batch generation, memory profiling | Orchestrator |
| **35** | Port comparison/visual-diff reports | Adapt `comparison_report.py`, `visual_diff.py`, `migration_report.py` for BO→PBI side-by-side | Tester |
| **36** | REST API server | Adapt `api_server.py` — multipart upload, async job queue, BO extensions in `ALLOWED_EXTENSIONS` | Orchestrator |
| **37** | Web UI wizard | Adapt `wizard.py` (CLI) + add Streamlit/web version; 6-step: upload → assess → configure → migrate → validate → deploy | Orchestrator |
| **38** | Plugin system | Port `plugins.py` + `marketplace.py` (both source-agnostic); custom BO visual mapping hooks; DAX post-processing | Orchestrator |
| **39** | LLM-assisted refinement | Port `llm_client.py`; change system prompt from Tableau→BO; LLM DAX review, measure naming, visual suggestions | Converter |
| **40** | Documentation & examples | Enterprise guide finalization, FAQ, sample BO artifacts (.wid/.rpt/.unx), real-world migration examples, video walkthroughs | Tester |

**Exit criteria**: REST API + Web UI operational. Plugin system documented. 95% test coverage. Enterprise guide complete.

---

## Dependency Graph

```
Phase 1 (Foundation)
├── Sprint 1: Copy agnostic modules ──────────────────┐
├── Sprint 2: Bridge adapter ─────────────────────────┤
├── Sprint 3: tmdl_generator adaptation ──────────────┤
├── Sprint 4: pbip_generator adaptation ──────────────┤
├── Sprint 5: Wire full pipeline ─────────────────────┤
└── Sprint 6: E2E validation ─────────────────────────┘
        │
        ▼
Phase 2 (Fidelity)                Phase 3 (Crystal & BIAR)
├── Sprint 7-8: Visuals/Prompts   ├── Sprint 13: Crystal stubs
├── Sprint 9-10: DAX depth        ├── Sprint 14-16: Crystal→PBI
├── Sprint 11: Relationships      ├── Sprint 17: BIAR batch
└── Sprint 12: Cond. formatting   └── Sprint 18: Batch validation
        │                                  │
        ▼                                  ▼
Phase 4 (Enterprise) ─────────────────────────────────┐
├── Sprint 19-20: Assessment                           │
├── Sprint 21: Shared model                            │
├── Sprint 22-23: Validation + DAX optimizer           │
├── Sprint 24: Deployment                              │
├── Sprint 25: Governance                              │
└── Sprint 26: --assess E2E                            │
        │                                              │
        ▼                                              │
Phase 5 (Advanced) ◄──────────────────────────────────┘
├── Sprint 27: Fabric-native
├── Sprint 28-29: @AggAware + Contexts
├── Sprint 30-31: Security + Schedules
├── Sprint 32-33: Multi-tenant + Incremental
        │
        ▼
Phase 6 (Polish)
├── Sprint 34: Perf optimization
├── Sprint 35-37: Reports + API + Web UI
├── Sprint 38-39: Plugins + LLM
└── Sprint 40: Docs & examples
```

**Phase 2 and Phase 3 can run in parallel** — visual fidelity work is independent of Crystal Reports support.

---

## Test Strategy

### Coverage Targets

| Phase | Target | Tests | Focus Areas |
|-------|--------|-------|-------------|
| Phase 1 | ≥80% | 150+ | Bridge adapter, TMDL output, PBIR structure, E2E pipeline |
| Phase 2 | ≥85% | 400+ | Visual type mapping, DAX conversion accuracy, slicer generation |
| Phase 3 | ≥85% | 600+ | Crystal extraction, BIAR batch, drill-through wiring |
| Phase 4 | ≥90% | 1,200+ | Assessment scoring, merge engine, deployment, validation |
| Phase 5 | ≥92% | 2,000+ | Fabric output, security, schedules, incremental |
| Phase 6 | ≥95% | 3,000+ | API server, Web UI, plugins, regression suite |

### Test Categories

| Category | Scope | Tooling |
|----------|-------|---------|
| **Unit** | Individual functions (DAX convert, M build, visual map) | pytest + fixtures |
| **Integration** | Full pipeline: `.wid` → `.pbip` | pytest + temp dirs + TMDL parser |
| **Snapshot** | Regression: golden `.pbip` output comparison | `regression_suite.py` |
| **Equivalence** | DAX formula output matching expected values | `equivalence_tester.py` |
| **Security** | ZIP slip, XXE, path traversal, credential redaction | pytest-security fixtures |
| **BIAR Batch** | Multi-artifact archive processing | BIAR fixtures with 5+ artifact types |

### Currently Passing (65+ tests)

| File | Tests | Status |
|------|-------|--------|
| `tests/test_dax_converter.py` | 30+ | ✅ All pass |
| `tests/test_biar_reader.py` | 7 | ✅ All pass |
| `tests/test_cli.py` | 14 | ✅ All pass |
| `tests/test_extraction.py` | 7 | ✅ All pass |
| `tests/test_webi_extractor.py` | 7 | ✅ All pass |

---

## Reuse Execution Plan

### Sprint 1 Detailed: Copy Source-Agnostic Modules

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

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|
| Crystal .rpt binary format too opaque without SDK | Groups/sorts/charts remain stubs | Medium | Fallback: require Crystal-to-PDF or Crystal-to-Excel pre-export; document as manual step |
| BO context operators don't translate cleanly to DAX | Formula accuracy for complex reports | High | `ForEach`/`ForAll`/`In` generate `/* TODO */` comments; add LLM-assisted refinement in Phase 6 |
| `@Aggregate_Aware` multi-granularity logic | Incorrect aggregation in PBI | Medium | Generate `SWITCH(HASONEVALUE(...))` + doc comment flagging manual review |
| TableauToPowerBI `tmdl_generator` API drift | Port breaks after upstream updates | Low | Pin to specific commit; track upstream changes quarterly |
| BO Server REST API version differences (BI 4.x vs 4.3) | Server mode fails on older BO versions | Medium | Version detection in `server_client.py`; graceful degradation for missing endpoints |
| BIAR archives with >1000 artifacts | Memory/perf issues in batch mode | Low | Streaming extraction; per-artifact error isolation; configurable parallelism |

---

## Success Metrics

| Metric | Phase 1 | Phase 2 | Phase 4 | Phase 6 |
|--------|---------|---------|---------|---------|
| **WebI reports convertible** | Simple (1 tab, no calcs) | Multi-tab + formulas + prompts | With assessment scoring | 100% of supported scope |
| **Crystal reports convertible** | — | — | Basic (text + formulas) | With groups/subreports |
| **Formula accuracy** | Direct function mapping only | 87% (107/123) | 92%+ with optimizer | 96%+ with LLM assist |
| **Visual type fidelity** | Placeholder visuals | Correct type mapping | Full configuration | Conditional formatting |
| **Pipeline throughput** | 1 report at a time | 1 report at a time | BIAR batch | Parallel batch |
| **Deployment** | Local `.pbip` only | Local `.pbip` only | Fabric/PBI Service | Multi-tenant |
