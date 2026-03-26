<!-- Copilot instructions for the Business Objects to Power BI migration project -->

# Project: Business Objects to Power BI Migration

Automated migration of SAP BusinessObjects reports (WebI, Crystal, Universes, Lumira) to Power BI projects (.pbip) in PBIR v4.0 format with TMDL semantic model.

## Architecture — 2-Step Pipeline

```
.wid/.rpt/.unx/.biar → [Extraction] → 15 JSON files → [Generation] → .pbip (PBIR + TMDL)
                                                                     → Fabric-native
```

1. **Extraction** (`bo_export/`): Parses BO artifacts, extracts reports/queries/datasources/formulas/prompts/filters/tables/columns/joins/groups/sorts/alerts/subreports/charts/custom_sql
2. **Generation** (`powerbi_import/`): Produces the complete .pbip project (TMDL, PBIR v4.0, visuals, M queries)

## Project Structure

- **bo_export/**: BO artifact extraction and parsing + DAX formula conversion
  - `extract_bo_data.py`: Main orchestrator, routes .wid/.rpt/.unx/.biar to extractors
  - `webi_extractor.py`: Web Intelligence document extraction (queries, variables, prompts, tabs)
  - `crystal_extractor.py`: Crystal Reports extraction (formulas, parameters, subreports, groups)
  - `universe_extractor.py`: Universe (UNX/UNV) extraction (business layer, data foundation, joins, contexts)
  - `lumira_extractor.py`: Lumira Discovery/Designer extraction
  - `biar_reader.py`: BIAR/LCMBIAR archive reader with ZIP slip protection
  - `dax_converter.py`: 150+ BO formula → DAX conversions (WebI + Crystal syntax)
  - `m_query_builder.py`: Power Query M generator (15+ connectors, transforms, custom SQL)
  - `server_client.py`: BO CMS REST API client (auth, documents, universes, download, schedules)
- **powerbi_import/**: Power BI project generation (reused from TableauToPowerBI)
  - `tmdl_generator.py`, `pbip_generator.py`, `visual_generator.py`, etc.
  - `deploy/`: Fabric/PBI Service deployment
- **tests/**: Unit and integration tests
- **docs/**: Architecture, dev plan, gap analysis, enterprise guide
- **.github/agents/**: 8 specialized agents (Orchestrator, Extractor, Converter, Generator, Assessor, Merger, Deployer, Tester)

## Multi-Agent Architecture

See `docs/AGENTS.md` for the 8-agent model with scoped file ownership.

## Technologies

- Python 3.12+ (standard library only for core)
- Optional: `azure-identity`, `requests`
- Output: PBIR v4.0 + TMDL (default), or Fabric-native

## Main Commands

```bash
python migrate.py report.wid
python migrate.py report.rpt --output-dir /tmp/output
python migrate.py --biar archive.biar --output-dir /tmp/batch
python migrate.py --server https://bo:6405 --folder /Public/Sales --user admin --auth enterprise
python migrate.py report.wid --assess
python migrate.py report.wid --output-format fabric
python migrate.py --shared-model r1.wid r2.wid --model-name "Shared Sales"
python migrate.py report.wid --deploy WORKSPACE_ID
```

## Extracted Objects (15 types)

| Type | JSON File | Source |
|------|-----------|--------|
| reports | reports.json | WebI tabs, Crystal sections |
| queries | queries.json | Data providers, record sources |
| datasources | datasources.json | Universe connections, direct DB |
| formulas | formulas.json | WebI variables, Crystal formulas |
| prompts | prompts.json | WebI prompts, Crystal parameters |
| filters | filters.json | Query/report/section filters |
| tables | tables.json | Universe tables, derived tables |
| columns | columns.json | Universe objects (dim/measure/detail) |
| joins | joins.json | Universe joins, contexts |
| groups | groups.json | Crystal groups, WebI breaks |
| sorts | sorts.json | Sort definitions |
| alerts | alerts.json | Alerters, conditional formatting |
| subreports | subreports.json | Crystal subreports, doc links |
| charts | charts.json | Chart definitions |
| custom_sql | custom_sql.json | Freehand SQL, derived tables |
