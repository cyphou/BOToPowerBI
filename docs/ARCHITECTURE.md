# Architecture — Business Objects to Power BI Migration

## System Overview

This system performs automated migration of SAP BusinessObjects (BO) reports to Power BI projects (.pbip) in PBIR v4.0 format with TMDL semantic model.

## Two-Step Pipeline

```
┌───────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  BO Artifacts  │ ──► │  Extraction      │ ──► │  15 JSON Files   │
│  (.wid/.rpt/   │     │  (bo_export/)    │     │  (intermediate   │
│   .unx/.biar)  │     │                  │     │   format)        │
└───────────────┘     └──────────────────┘     └────────┬─────────┘
                                                         │
                                                         ▼
                                               ┌──────────────────┐
                                               │  Generation      │
                                               │  (powerbi_import/)│
                                               └────────┬─────────┘
                                                         │
                                            ┌────────────┼────────────┐
                                            ▼            ▼            ▼
                                      ┌──────────┐ ┌──────────┐ ┌──────────┐
                                      │  .pbip   │ │  Fabric  │ │  Deploy  │
                                      │  (TMDL + │ │  Native  │ │  (REST   │
                                      │   PBIR)  │ │  (5 art) │ │   API)   │
                                      └──────────┘ └──────────┘ └──────────┘
```

## Extraction Layer (bo_export/)

### Supported Source Types

| Source | Module | Parsing Strategy |
|--------|--------|-----------------|
| Web Intelligence (.wid) | `webi_extractor.py` | ZIP → XML metadata, data providers, variables, report tabs |
| Crystal Reports (.rpt) | `crystal_extractor.py` | Binary → text segment extraction, formula/field pattern matching |
| Universe UNX (.unx) | `universe_extractor.py` | ZIP → XML (business layer + data foundation) |
| Universe UNV (.unv) | `universe_extractor.py` | Binary → embedded XML blocks |
| Lumira (.lumx/.lums) | `lumira_extractor.py` | ZIP → JSON/XML datasets and visualizations |
| BIAR Archive (.biar) | `biar_reader.py` | ZIP → artifact inventory → per-artifact extraction |

### Intermediate JSON Format

15 JSON files serve as the contract between extraction and generation:
```
reports.json     — Report tab/section definitions
queries.json     — Data provider/query definitions
datasources.json — Connection information
formulas.json    — Variables/formulas with DAX conversion
prompts.json     — Prompt/parameter definitions
filters.json     — Filter expressions
tables.json      — Table/class definitions
columns.json     — Column/object definitions (dim/measure/detail)
joins.json       — Join/relationship definitions
groups.json      — Group/break definitions
sorts.json       — Sort specifications
alerts.json      — Alerter/conditional formatting rules
subreports.json  — Subreport/document link definitions
charts.json      — Chart/visualization definitions
custom_sql.json  — Freehand SQL / derived table queries
```

## Generation Layer (powerbi_import/)

**Reused from TableauToPowerBI** — the generation layer is source-agnostic and consumes
the intermediate JSON format to produce Power BI artifacts.

### Output: PBIP (Default)
```
<name>.pbip
├── <name>.SemanticModel/
│   └── definition/
│       ├── model.tmdl          — Semantic model definition
│       ├── tables/             — Table TMDL files
│       ├── relationships.tmdl  — Relationship definitions
│       └── cultures/           — Locale files
├── <name>.Report/
│   └── definition/
│       ├── report.json         — PBIR v4.0 report definition
│       └── pages/              — Page and visual definitions
└── <name>.pbip                 — Project descriptor
```

### Output: Fabric-Native
```
<name>.Lakehouse/           — Delta table schemas + DDL
<name>.Dataflow/            — Power Query M ingestion
<name>.Notebook/            — PySpark ETL pipeline
<name>.SemanticModel/       — DirectLake semantic model
<name>.Pipeline/            — 3-stage orchestration
```

## Formula Conversion (bo_export/dax_converter.py)

Maps 150+ BO functions to DAX equivalents:
- **WebI syntax**: `=FunctionName([Object])` → `FUNCTION('Table'[Column])`
- **Crystal syntax**: `{Table.Field}`, `{@Formula}`, `{?Param}` → DAX references
- **Context operators**: `In`, `ForEach`, `ForAll` → CALCULATE + filter modifiers
- **Running calculations**: `RunningSum`, `RunningCount` → window CALCULATE patterns
- **@Aggregate_Aware**: Universe-level → measure granularity patterns

## BO ↔ Power BI Concept Mapping

| BO Concept | Power BI Equivalent |
|------------|-------------------|
| Universe | Semantic Model (TMDL) |
| Business Layer Class | Table |
| Dimension Object | Column |
| Measure Object | DAX Measure |
| Detail Object | Column (associated) |
| Universe Join | Relationship |
| Universe Context | ALLEXCEPT/USERELATIONSHIP |
| Derived Table | M Custom SQL Step |
| WebI Data Provider | M Partition |
| WebI Variable (Measure) | DAX Measure |
| WebI Variable (Dimension) | Calculated Column |
| WebI Prompt | Slicer + Parameter Table |
| WebI Input Control | Slicer |
| WebI Report Tab | Report Page |
| WebI Section | Group in Matrix |
| WebI Break | Group in Visual |
| WebI Alerter | Conditional Formatting Rule |
| Crystal Formula | DAX Measure/Calculated Column |
| Crystal Parameter | Power BI Parameter |
| Crystal Group | Group in Visual |
| Crystal Subreport | Drill-through Page |
| Crystal Running Total | CALCULATE Window Pattern |
| BO Scheduled Instance | PBI Refresh Schedule |
| BO Security Profile | RLS Role |
| BO Folder/Category | Workspace / App |

## Security Architecture

- **ZIP slip defense**: All ZIP extraction validates entry paths
- **XXE protection**: XML parsing blocks DOCTYPE with ENTITY declarations
- **Credential handling limitation**: Extracted connection strings are serialized
      without guaranteed redaction and can contain credentials. Restrict access to
      sources/outputs and review them before sharing. Automatic export redaction is
      an open Extractor task, not an implemented security guarantee.
- **Path validation**: Null byte blocking, traversal detection, extension whitelist
- **Authentication boundaries**: Cloud authentication and BO CMS sessions are
      separate. The CLI accepts BO credentials/tokens; avoid putting secrets in
      command history. JSON extraction can persist source-embedded credentials, so
      environment-based authentication alone does not make outputs secret-free.
