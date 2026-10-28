---
name: bo-to-powerbi
description: "Use when: migrating SAP BusinessObjects Web Intelligence .wid, Crystal .rpt, universes .unx/.unv, BIAR archives, or Lumira .lumx/.lums to Power BI PBIP or Fabric; assessing readiness, batch migration, shared models, debugging BO formulas, or preparing deployment. Not for Tableau workbooks or Power BI authoring unrelated to BO."
---

# BusinessObjects To Power BI

Use this repository's migration engine. Prefer the CLI over manually recreating generated artifacts.

## Procedure

1. Read `.github/copilot-instructions.md`, `.github/agents/shared.instructions.md`, and `docs/AGENTS.md`.
2. Identify the source artifact, required universe metadata, output format (`pbip` or `fabric`), and output directory. Read `python migrate.py --help` before choosing flags.
3. Assess or dry-run first when the source's compatibility is unknown. Use a separate output directory and do not overwrite customer artifacts without confirmation.
4. Run the existing CLI workflow. Keep BO's 15 extracted object types and adapter contract intact; do not substitute Tableau's schema or subcommands.
5. Inspect produced artifacts and available validation reports. Fix defects in the owning extractor/converter/generator, not only in output files.
6. After implementation changes, run a focused test, then `pytest tests/ --tb=short -q`. Report any failures without weakening assertions.
7. Deployment is separate authorization. Read `.github/skills/fabric-mcp-routing/SKILL.md` and hand off to Deployer before remote writes.

## CLI Examples

Run from the repository root using the selected project interpreter:

```powershell
python migrate.py --help
python migrate.py examples/Enterprise_Sales.wid --assess
python migrate.py examples/Enterprise_Sales.wid --dry-run
python migrate.py examples/Enterprise_Sales.wid --output-dir artifacts/bo-sales
python migrate.py examples/Enterprise_Sales.wid --output-format fabric --output-dir artifacts/bo-fabric
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
Batch outputs are isolated by relative source filename and include `batch_manifest.json`;
partial failures return a nonzero exit code with per-source diagnostics.
Shared-model merging retains isolated source tables and their known schema,
connection, and provenance. Same-named distinct physical sources require explicit
mapping and are rejected before generation; do not override this by assuming a
connection or dropping a source. Direct Lake date enrichments need upstream
materialization, unlike the Import path's automatic Calendar/date parts.
BIAR uses temporary file extraction and the same generation API as individual sources.
Fabric outputs are quality-gated after generation. Blocking findings return code
6 for file/BIAR/batch/shared-model CLI workflows and preserve per-project
`quality_report.json`; warnings alone do not block unless a separate strict
validation is requested. A generated directory is not sufficient success evidence.
CSV/Excel ingestion belongs to Notebook, connected sources/custom SQL to Dataflow,
and calculated-column materialization to the single primary ETL notebook. Inspect
the persisted ingestion/materialization plan and the actual validation findings.
Do not pass credentials in command examples or chat; use the supported secure authentication mechanism after reading the relevant client.

## Ownership

| Surface | Agent | Source |
|---------|-------|--------|
| CLI, batch, pipeline coordination | Orchestrator | `migrate.py` |
| Local BO extraction and adapter | Extractor | `bo_export/` parsing modules |
| BO CMS/server client | BusinessObjects | `bo_export/server_client.py` |
| BO formulas to DAX | Dax | `bo_export/dax_converter.py`, `powerbi_import/dax_optimizer.py` |
| Power Query and column classification | Wiring | `bo_export/m_query_builder.py`, `powerbi_import/m_query_generator.py`, `powerbi_import/calc_column_utils.py` |
| Semantic model | Semantic | TMDL generator modules |
| PBIR report | Visual | `powerbi_import/pbip_generator.py` and visual generators |
| Fabric bundle | Fabric | `powerbi_import/fabric_project_generator.py` and its five sub-generators |
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
Local `migrate` and `shared_model` require server `--allow-write`, per-call
`confirm=true`, and a new or empty output directory within the configured root.
This server never deploys to Fabric. Read `docs/FABRIC_MCP_SETUP.md` before enabling writes.

## Evidence

Successful generation is not Desktop openability, visual parity, refreshed data, or successful Fabric execution.
Record what ran, against which source/target, its status, and what remains `not_run`.
Copilot agents are development roles; do not claim the CLI automatically invokes them.