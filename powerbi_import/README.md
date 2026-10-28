# powerbi_import — Power BI Generation

Generates Power BI projects (`.pbip`) or Fabric artifact bundles from adapted
SAP BusinessObjects metadata. Use the root CLI so extraction's 15 raw collections
pass through the BO adapter before generation. Local generation is not proof of
Desktop openability, visual equivalence, refresh, or deployed execution.

## Core Modules

### `import_to_powerbi.py`

Main orchestrator. Reads extracted JSON and generates the `.pbip` project.

```bash
# Run from the repository root with an explicit BO source
python migrate.py examples/Enterprise_Sales.wid --assess
python migrate.py examples/Enterprise_Sales.wid --output-dir artifacts/bo-sales
python migrate.py --validate-project artifacts/bo-sales
```

Do not run the importer file as a standalone script. Source extraction and output
paths are controlled by the root CLI. Review [known gaps](../docs/GAP_ANALYSIS.md)
and treat extracted connection metadata as sensitive: JSON export is not guaranteed
to redact source-embedded credentials.

### `pbip_generator.py`

Generates the complete `.pbip` file structure:

- `.pbip` file (entry point)
- SemanticModel (TMDL via `tmdl_generator.py`)
- Report (PBIR v4.0: `report.json`, `pages.json`, `visual.json`)
- `.platform` files and metadata

### `tmdl_generator.py`

Converts extracted data into TMDL (Tabular Model Definition Language) files:

- `database.tmdl` — compatibility
- `model.tmdl` — culture, data source version
- `relationships.tmdl` — relationships between tables
- `tables/{Table}.tmdl` — columns, measures, and Import/M or Direct Lake entity partitions

Direct Lake uses upstream Delta tables; automatic Import Calendar/date-part
enrichments are deferred when absent upstream. Local Fabric quality blockers
return exit 6 and preserve generated findings/artifacts for diagnosis.

### `visual_generator.py`

Generates JSON visual definitions for reports from the adapted BO worksheet/chart
metadata. Conversion mappings do not establish visual fidelity without rendering checks.

### `m_query_generator.py`

Generates Power Query M queries for the different data source types.

### `validator.py`

Validates `.pbip` projects (JSON, TMDL, report structure) before opening in PBI Desktop.

### `migration_report.py`

Per-item fidelity tracking and migration status reporting.

### `api_server.py`

REST API server (stdlib `http.server`). Endpoints: `POST /migrate`, `GET /status/{id}`, `GET /download/{id}`, `GET /health`, `GET /jobs`.

### `schema_drift.py`

Schema drift detection — compares extraction snapshots. Detects added/removed/changed tables, columns, calculations, worksheets, relationships, parameters, filters.

## Deployment Subpackage (`deploy/`)

Fabric deployment is in the `deploy/` subpackage:

These modules are separate from proven CLI integration. Single-file hooks require
environment validation; shared-model CLI generation does not invoke deployment,
and standalone `--deploy-bundle` is not wired. See [Fabric/MCP setup](../docs/FABRIC_MCP_SETUP.md)
before separately authorized remote operations. No cloud execution was performed
for this documentation update.

| Module | Responsibility |
|--------|---------------|
| `auth.py` | Azure AD authentication (Service Principal + Managed Identity) |
| `client.py` | Fabric REST API client with retry logic |
| `deployer.py` | Fabric deployment orchestrator |
| `utils.py` | DeploymentReport, ArtifactCache |
| `config/settings.py` | Centralized config via env vars |
| `config/environments.py` | Per-environment configs (dev/staging/production) |

## Output Format

**PBIR v4.0** with schemas:
- `report/2.0.0`
- `page/2.0.0`
- `visualContainer/2.5.0`
- `pbipProperties/1.0.0`
- `definitionProperties/2.0.0`
