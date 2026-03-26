# Multi-Agent Architecture — Business Objects to Power BI Migration

This project uses an **8-agent specialization model** (identical to TableauToPowerBI).
Each agent has scoped domain knowledge, file ownership, and clear boundaries.

## Quick Reference

| Agent | Invoke When | Owns |
|-------|-------------|------|
| **@orchestrator** | Pipeline coordination, CLI, batch, wizard | `migrate.py`, `import_to_powerbi.py`, `wizard.py`, `progress.py`, `incremental.py`, `plugins.py`, `notebook_api.py`, `api_server.py` |
| **@extractor** | Parsing BO artifacts (WID/RPT/UNX/BIAR/LUMX) | `bo_export/*.py` (extract, webi, crystal, universe, lumira, biar, server) |
| **@converter** | BO formulas → DAX, Power Query M generation | `dax_converter.py`, `m_query_builder.py`, `dax_optimizer.py` |
| **@generator** | TMDL semantic model, PBIR report, visuals, Fabric generators | `tmdl_generator.py`, `pbip_generator.py`, `visual_generator.py`, `fabric_*.py` |
| **@assessor** | Migration readiness, scoring, strategy, diff reports | `assessment.py`, `server_assessment.py`, `global_assessment.py`, `validator.py` |
| **@merger** | Shared semantic model, multi-report merge | `shared_model.py`, `merge_config.py` |
| **@deployer** | Fabric/PBI deployment, auth, gateway, telemetry | `deploy/*.py`, `gateway_config.py`, `telemetry.py` |
| **@tester** | Tests, coverage, fixtures, regression | `tests/*.py` |

## Architecture Diagram

```
                    ┌──────────────┐
                    │ Orchestrator │  ← CLI entry, pipeline coordination
                    └──────┬───────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
    │ Extractor  │   │ Converter │   │ Generator  │
    │ (BO)       │   │ (DAX/M)   │   │ (PBI)      │
    └────────────┘   └───────────┘   └────────────┘
                                           │
                    ┌──────────────────┬────┴────┐
                    │                  │         │
              ┌─────▼─────┐    ┌──────▼──┐  ┌───▼────┐
              │  Assessor  │    │ Merger  │  │Deployer│
              │ (Analysis) │    │ (Merge) │  │(Fabric)│
              └────────────┘    └─────────┘  └────────┘

              ┌────────────────────────────────────────┐
              │              Tester                     │
              │    (Cross-cutting — reads all, writes   │
              │     only to tests/)                     │
              └────────────────────────────────────────┘
```

## Data Flow

```
1. Orchestrator receives CLI command (migrate.py)
2. Orchestrator delegates to Extractor → 15 JSON files
3. Orchestrator delegates to Converter → DAX/M formulas
4. Orchestrator delegates to Generator:
   a. Default (--output-format pbip) → .pbip (TMDL + PBIR)
   b. Fabric (--output-format fabric) → Lakehouse + Dataflow + Notebook + SemanticModel + Pipeline
5. Generator runs self-healing (TMDL self-repair, visual fallback, M query repair)
6. (Optional) Orchestrator delegates to Assessor → readiness report
7. (Optional) Orchestrator delegates to Merger → shared semantic model
8. (Optional) Orchestrator delegates to Deployer → Fabric/PBI workspace
9. Tester validates all steps
```

## Handoff Protocol

When an agent encounters work outside its domain:

1. **Complete your part** — finish everything within your file scope
2. **State the handoff** — clearly describe what needs to happen next
3. **Name the target agent** — e.g., "Hand off to @generator for TMDL updates"
4. **List artifacts** — specify files, functions, and data structures involved
5. **Include context** — provide any intermediate results the next agent needs

## File Ownership Rules

- **One owner per file** — each source file has exactly one owning agent
- **Read access is universal** — any agent can read any file for context
- **Write access is restricted** — only the owning agent modifies a file
- **Tester is special** — reads all source files, writes only to `tests/`
- **Co-owned files** — `thin_report_generator.py` (Generator + Merger), `merge_assessment.py` + `merge_report_html.py` (Assessor + Merger)

## Reused from TableauToPowerBI

The following modules are **directly reused** from the TableauToPowerBI project (source-agnostic):

### Generation Layer (`powerbi_import/`)
- `tmdl_generator.py` — TMDL semantic model generation
- `pbip_generator.py` — .pbip project structure
- `visual_generator.py` — Visual container generator
- `import_to_powerbi.py` — Pipeline orchestrator
- `thin_report_generator.py` — Thin report generator
- `m_query_generator.py` — Sample data M query generator
- `shared_model.py` — Multi-workbook merge engine
- `dax_optimizer.py` — DAX optimization engine
- `recovery_report.py` — Self-healing recovery tracker

### Assessment & Reporting
- `assessment.py` — Readiness assessment framework
- `server_assessment.py` — Portfolio assessment
- `global_assessment.py` — Cross-report assessment
- `strategy_advisor.py` — Import/DirectQuery/Composite advisor
- `validator.py` — Artifact validator
- `html_template.py` — Shared CSS/JS for HTML reports
- `telemetry.py` — Event-level telemetry
- `telemetry_dashboard.py` — Observability dashboard

### Deployment & Security
- `deploy/` — Complete Fabric/PBI deployment framework
- `security_validator.py` — Path/XXE/credential safety
- `governance.py` — Enterprise governance framework

### Fabric-Native
- `fabric_project_generator.py` — 5-artifact orchestrator
- `lakehouse_generator.py`, `dataflow_generator.py`, `notebook_generator.py`
- `pipeline_generator.py`, `fabric_semantic_model_generator.py`

## Agent Files

All agent definitions are in `.github/agents/`:
- `shared.instructions.md` — Base rules inherited by all agents
- `orchestrator.agent.md` — Pipeline coordination
- `extractor.agent.md` — BO artifact parsing
- `converter.agent.md` — Formula translation
- `generator.agent.md` — PBI artifact generation
- `assessor.agent.md` — Migration analysis
- `merger.agent.md` — Multi-report merge
- `deployer.agent.md` — Fabric/PBI deployment
- `tester.agent.md` — Test creation and validation
