<p align="center">
  <img src="https://img.shields.io/badge/SAP%20BusinessObjects-0FAAFF?style=for-the-badge&logo=sap&logoColor=white" alt="SAP BO"/>
  <img src="https://img.shields.io/badge/%E2%86%92-gray?style=for-the-badge" alt="arrow"/>
  <img src="https://img.shields.io/badge/Power%20BI-F2C811?style=for-the-badge&logo=powerbi&logoColor=black" alt="Power BI"/>
</p>

<h1 align="center">Business Objects to Power BI Migration</h1>

<p align="center">
  <strong>Migrate SAP BusinessObjects reports to Power BI in seconds — fully automated, zero manual rework.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-244%20passed-brightgreen?style=flat-square" alt="Tests"/>
  <img src="https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License"/>
  <img src="https://img.shields.io/badge/deps-zero-orange?style=flat-square" alt="Zero Dependencies"/>
  <img src="https://img.shields.io/badge/DAX%20mappings-150%2B-blue?style=flat-square" alt="DAX Mappings"/>
  <img src="https://img.shields.io/badge/source%20formats-8-purple?style=flat-square" alt="Source Formats"/>
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-key-features">Features</a> •
  <a href="#-how-it-works">How It Works</a> •
  <a href="#-dax-conversions-150-functions">DAX Mappings</a> •
  <a href="#-deployment">Deployment</a> •
  <a href="#-documentation">Docs</a>
</p>

---

## ⚡ Quick Start

```bash
# That's it. One command.
python migrate.py report.wid
```

> [!TIP]
> The output is a `.pbip` project — just double-click to open in **Power BI Desktop** (December 2025+).

<details>
<summary><b>📦 Installation</b></summary>

```bash
git clone <repo-url>
cd BOToPowerBI
python migrate.py report.wid
```

**Requirements:** Python 3.12+ • No `pip install` needed — pure standard library.

Optional dependencies:
```bash
pip install azure-identity requests   # Fabric/PBI Service deployment
```
</details>

### More ways to migrate

```bash
# 📝 Crystal Report
python migrate.py report.rpt --output-dir /tmp/output

# 📦 Batch migration from BIAR archive
python migrate.py --biar export.biar --output-dir /tmp/batch

# ☁️ Directly from BO Server (CMS)
python migrate.py --server https://bo-server:6405 --folder "/Public/Sales" \
    --user admin --auth enterprise

# 🔍 Pre-migration readiness check
python migrate.py report.wid --assess

# 🏭 Fabric-native output
python migrate.py report.wid --output-format fabric

# 🔗 Shared Semantic Model — merge multiple reports
python migrate.py --shared-model r1.wid r2.wid --model-name "Shared Sales"

# 🚀 Migrate + deploy to Fabric in one shot
python migrate.py report.wid --deploy WORKSPACE_ID --deploy-refresh

# 📅 Generate refresh config from BO schedules
python migrate.py report.wid --refresh-config

# 🏢 Multi-tenant deployment
python migrate.py report.wid --multi-tenant tenants.json

# 🔄 Incremental migration (skip unchanged artifacts)
python migrate.py report.wid --incremental

# 📊 Schema drift detection against previous extraction
python migrate.py report.wid --schema-drift /prev/extraction/

# 🧙 Dry run (no output files)
python migrate.py report.wid --dry-run
```

---

## 🎯 Key Features

<table>
<tr>
<td width="50%">

### 🔍 Complete Extraction
Parses **15 object types** from `.wid`/`.rpt`/`.unx`/`.biar`:
reports, queries, datasources, formulas, prompts, filters, tables, columns, joins, groups, sorts, alerts, subreports, charts, custom SQL

**8 source formats:** WebI, Crystal Reports, Universe UNX/UNV, BIAR, LCMBIAR, Lumira Discovery, Lumira Designer

</td>
<td width="50%">

### 🧮 150+ DAX Conversions
Translates BO formulas to DAX:
aggregation, text, date, math, null handling, running calculations, context operators (In/ForEach/ForAll/Where), @Aggregate_Aware, security functions, Crystal syntax

</td>
</tr>
<tr>
<td>

### 📊 50+ Visual Types
Maps BO chart types to Power BI:
bar, line, area, pie, scatter, map, treemap, waterfall, funnel, gauge, KPI, box plot, word cloud, matrix, combo charts, and more

</td>
<td>

### 🔌 15+ Data Connectors
Generates Power Query M for:
SQL Server, PostgreSQL, Oracle, MySQL, SAP HANA, BigQuery, Snowflake, Databricks, Excel, CSV, OData, SharePoint, Azure SQL, and more

</td>
</tr>
<tr>
<td>

### 🧠 Smart Semantic Model
Auto-generates Calendar table, date hierarchies, relationships, RLS roles from BO security profiles, display folders, number formats, What-If parameters from prompts

</td>
<td>

### 🚀 Deploy Anywhere
One-command deploy to **Power BI Service** or **Microsoft Fabric** with Azure AD auth. Multi-tenant deployment with per-tenant connection overrides.

</td>
</tr>
<tr>
<td>

### 🏭 Fabric-Native Output
Generate **Lakehouse + Dataflow Gen2 + PySpark Notebook + DirectLake Semantic Model + Data Pipeline** with `--output-format fabric`. Full Fabric project from a single BO report.

</td>
<td>

### ⚡ DAX Optimizer
Auto-rewrites verbose DAX: nested IF→SWITCH, IF(ISBLANK)→COALESCE, constant folding, SUMX simplification

</td>
</tr>
<tr>
<td>

### 🔗 Shared Semantic Model
Merge multiple BO reports into **one shared semantic model** with thin reports. Fingerprint-based table matching, Jaccard column overlap scoring, conflict resolution, and merge assessment.

</td>
<td>

### 🔒 Security Profile Migration
BO security profiles → PBI RLS roles with DAX filter expressions. Supports =, InList, Between, <>, Like operators. Generates PowerShell scripts for Azure AD group assignment.

</td>
</tr>
<tr>
<td colspan="2">

### 🔄 Enterprise-Grade Pipeline
Assessment engine (9-category readiness scoring) • Schedule migration (BO instances → PBI refresh config) • Incremental migration (skip unchanged artifacts) • Schema drift detection • Multi-tenant deployment • Governance & telemetry

</td>
</tr>
</table>

> [!NOTE]
> **Zero external dependencies** for core migration. The entire engine runs on Python's standard library.

---

## 🔧 How It Works

```mermaid
flowchart LR
    A["📝 .wid/.rpt\nBO Report"] --> B["🔍 EXTRACT\n15 JSON files"]
    U["📐 .unx/.unv\nUniverse"] -.-> B
    K["📦 .biar\nArchive"] -.-> B
    S["☁️ BO Server\n(CMS API)"] -.-> B
    B --> C["⚙️ GENERATE\n.pbip project"]
    B --> F["🏭 GENERATE\nFabric artifacts"]
    C --> D["📊 Power BI Desktop\nOpen & validate"]
    C -.-> E["🚀 DEPLOY\nPBI Service / Fabric"]
    F -.-> E

    style A fill:#0FAAFF,color:#fff,stroke:#0FAAFF
    style U fill:#0FAAFF,color:#fff,stroke:#0FAAFF
    style K fill:#0FAAFF,color:#fff,stroke:#0FAAFF
    style S fill:#0FAAFF,color:#fff,stroke:#0FAAFF
    style D fill:#F2C811,color:#000,stroke:#F2C811
    style E fill:#F2C811,color:#000,stroke:#F2C811
    style B fill:#4B8BBE,color:#fff,stroke:#4B8BBE
    style C fill:#4B8BBE,color:#fff,stroke:#4B8BBE
    style F fill:#0078D4,color:#fff,stroke:#0078D4
```

**Step 1 — Extract:** Parses BO artifacts into 15 structured JSON files (reports, queries, formulas, etc.)

**Step 2 — Generate:** Converts JSON into a complete `.pbip` project with PBIR v4.0 report and TMDL semantic model

**Step 3 — Deploy** *(optional):* Packages and uploads to Power BI Service or Microsoft Fabric

### 🏭 Fabric-Native Output Mode

Use `--output-format fabric` to generate a **full Microsoft Fabric project**:

```mermaid
flowchart LR
    A["📝 .wid/.rpt\nBO Report"] --> B["🔍 EXTRACT\n15 JSON files"]
    B --> C["⚙️ GENERATE\nFabric artifacts"]
    C --> LH["🗄️ Lakehouse\nDelta tables + DDL"]
    C --> DF["🔄 Dataflow Gen2\nPower Query M"]
    C --> NB["📓 PySpark Notebook\nETL pipeline"]
    C --> SM["📦 DirectLake\nSemantic Model"]
    C --> PL["⚡ Data Pipeline\n3-stage orchestration"]
    PL -.-> DF
    PL -.-> NB
    PL -.-> SM

    style A fill:#0FAAFF,color:#fff,stroke:#0FAAFF
    style B fill:#4B8BBE,color:#fff,stroke:#4B8BBE
    style C fill:#4B8BBE,color:#fff,stroke:#4B8BBE
    style LH fill:#0078D4,color:#fff,stroke:#0078D4
    style DF fill:#0078D4,color:#fff,stroke:#0078D4
    style NB fill:#0078D4,color:#fff,stroke:#0078D4
    style SM fill:#0078D4,color:#fff,stroke:#0078D4
    style PL fill:#0078D4,color:#fff,stroke:#0078D4
```

| Artifact | Description |
|----------|-------------|
| **Lakehouse** | Delta table schemas, Spark SQL DDL scripts, table metadata |
| **Dataflow Gen2** | Power Query M ingestion queries with Lakehouse destinations |
| **PySpark Notebook** | ETL pipeline + transformation notebook |
| **Semantic Model** | DirectLake TMDL pointing to Lakehouse Delta tables |
| **Data Pipeline** | 3-stage orchestration: Dataflow → Notebook → Semantic Model refresh |

### 🔗 Shared Semantic Model Mode

Merge multiple BO reports that share data sources into **one shared semantic model** + **N thin reports**:

```mermaid
flowchart LR
    A1["📝 Report A"] --> E["🔍 EXTRACT\n(isolated)"]
    A2["📝 Report B"] --> E
    A3["📝 Report C"] --> E
    E --> M["🔗 MERGE\nfingerprint matching"]
    M --> SM["📦 Shared\nSemanticModel"]
    M --> R1["📊 Report A\n(thin)"]
    M --> R2["📊 Report B\n(thin)"]
    M --> R3["📊 Report C\n(thin)"]
    R1 -.->|byPath| SM
    R2 -.->|byPath| SM
    R3 -.->|byPath| SM

    style SM fill:#4B8BBE,color:#fff
    style R1 fill:#F2C811,color:#000
    style R2 fill:#F2C811,color:#000
    style R3 fill:#F2C811,color:#000
```

```bash
# Assess merge feasibility
python migrate.py --shared-model r1.wid r2.wid --assess-merge

# Generate shared model + thin reports
python migrate.py --shared-model r1.wid r2.wid r3.wid --model-name "Shared Sales"

# Deploy shared model to Fabric as a bundle
python migrate.py --shared-model r1.wid r2.wid --deploy WORKSPACE_ID
```

### 📂 Generated Output

```
YourReport/
├── YourReport.pbip                     ← Double-click to open in PBI Desktop
├── migration_metadata.json             ← Stats, fidelity scores, warnings
├── credentials_template.json           ← Datasource credential placeholders
├── YourReport.SemanticModel/
│   └── definition/
│       ├── model.tmdl                  ← Tables, measures, relationships
│       ├── expressions.tmdl            ← Power Query M queries
│       ├── roles.tmdl                  ← Row-Level Security (from BO profiles)
│       └── tables/
│           ├── Sales.tmdl              ← Columns + DAX measures
│           └── Calendar.tmdl           ← Auto-generated date table
└── YourReport.Report/
    └── definition/
        ├── report.json                 ← Report config + theme
        └── pages/
            └── ReportSection/
                ├── page.json           ← Layout + filters
                └── visuals/
                    └── [id]/visual.json ← Each visual
```

---

## 📋 Supported Source Formats

| Format | Extension | Description |
|--------|-----------|-------------|
| Web Intelligence | `.wid` | WebI documents (reports, queries, variables, prompts) |
| Crystal Reports | `.rpt` | Crystal report files (formulas, subreports, parameters) |
| Universe (UNX) | `.unx` | Information Design Tool universes (business layer + data foundation) |
| Universe (UNV) | `.unv` | Designer universes (legacy) |
| BIAR Archive | `.biar` | BO content archive (batch export) |
| LCMBIAR | `.lcmbiar` | Lifecycle Management archive |
| Lumira Discovery | `.lumx` | SAP Lumira discovery documents |
| Lumira Designer | `.lums` | SAP Lumira Designer applications |

---

## 🧮 DAX Conversions (150+ functions)

<details>
<summary><b>📋 Complete conversion table</b> (click to expand)</summary>

| Category | BO Formula | DAX Equivalent |
|----------|-----------|----------------|
| Aggregation | `=Sum([Revenue])` | `SUM('Table'[Revenue])` |
| Aggregation | `=Count([OrderID])` | `COUNT('Table'[OrderID])` |
| Aggregation | `=Average([Price])` | `AVERAGE('Table'[Price])` |
| Aggregation | `=DistinctCount([Customer])` | `DISTINCTCOUNT('Table'[Customer])` |
| Text | `=Substr([Name],1,3)` | `MID('Table'[Name], 1, 3)` |
| Text | `=Pos([Name],"A")` | `SEARCH("A", 'Table'[Name])` |
| Text | `=Length([Name])` | `LEN('Table'[Name])` |
| Text | `=Upper([Name])` | `UPPER('Table'[Name])` |
| Date | `=Year([Date])` | `YEAR('Table'[Date])` |
| Date | `=Month([Date])` | `MONTH('Table'[Date])` |
| Date | `=DaysBetween([Start],[End])` | `DATEDIFF('Table'[Start], 'Table'[End], DAY)` |
| Logic | `=If [X]>0 Then "Y" Else "N"` | `IF('Table'[X] > 0, "Y", "N")` |
| Logic | `=If ... ElseIf ...` | `SWITCH(TRUE(), ...)` |
| Math | `=Round([Value],2)` | `ROUND('Table'[Value], 2)` |
| Math | `=Truncate([Value],2)` | `TRUNC('Table'[Value], 2)` |
| Running | `=RunningSum([Revenue])` | `CALCULATE(SUM(...), FILTER(ALLSELECTED(...)))` |
| Running | `=RunningCount([OrderID])` | `CALCULATE(COUNT(...), FILTER(ALLSELECTED(...)))` |
| Context | `=Sum([Rev]) In ([Region])` | `CALCULATE(SUM(...), ALLEXCEPT('T', 'T'[Region]))` |
| Context | `=Sum([Rev]) ForEach ([Product])` | `SUMX(VALUES('T'[Product]), SUM(...))` |
| Context | `=Sum([Rev]) ForAll` | `CALCULATE(SUM(...), ALL('T'))` |
| Context | `=Sum([Rev]) Where ([X]>0)` | `CALCULATE(SUM(...), FILTER('T', [X]>0))` |
| Universe | `@Aggregate_Aware(e1, e2, e3)` | `SWITCH(TRUE(), HASONEVALUE(...), e1, ...)` |
| Security | `=CurrentUser()` | `USERPRINCIPALNAME()` |
| Null | `=IsNull([X])` | `ISBLANK('Table'[X])` |
| Null | `=IfNull([X],0)` | `IF(ISBLANK('Table'[X]), 0, 'Table'[X])` |
| Crystal | `{Table.Field}` | `'Table'[Field]` |
| Crystal | `{@FormulaName}` | `[FormulaName]` |
| Crystal | `{?Parameter}` | `[Parameter]` |
| Crystal | `CStr(expr)` | `FORMAT(expr)` |
| Crystal | `DateAdd("m",1,{Date})` | `DATEADD([Date], 1, MONTH)` |

</details>

### Highlights

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  BO Context Operators              →  Power BI DAX                         │
├─────────────────────────────────────────────────────────────────────────────┤
│  =Sum([Revenue]) In ([Region];[Year])                                      │
│  → CALCULATE(SUM('Sales'[Revenue]), ALLEXCEPT('Sales', 'Sales'[Region],    │
│      'Sales'[Year]))                                                        │
│                                                                             │
│  =Sum([Revenue]) ForEach ([Product];[Category])                             │
│  → SUMX(CROSSJOIN(VALUES('T'[Product]), VALUES('T'[Category])),            │
│      SUM('T'[Revenue]))                                                     │
│                                                                             │
│  @Aggregate_Aware(SUM([Rev_Detail]), SUM([Rev_Month]), SUM([Rev_Year]))     │
│  → SWITCH(TRUE(), HASONEVALUE('T'[Detail]), SUM('T'[Rev_Detail]),          │
│      HASONEVALUE('T'[Month]), SUM('T'[Rev_Month]), SUM('T'[Rev_Year]))     │
│                                                                             │
│  =RunningSum([Revenue])                                                     │
│  → CALCULATE(SUM('T'[Revenue]), FILTER(ALLSELECTED('T'), TRUE()))          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Extracted Objects (15 types)

| Type | JSON File | Source |
|------|-----------|--------|
| reports | `reports.json` | WebI report tabs, Crystal report sections |
| queries | `queries.json` | WebI data providers, Crystal record sources |
| datasources | `datasources.json` | Universe connections, direct DB connections |
| formulas | `formulas.json` | WebI variables, Crystal formulas |
| prompts | `prompts.json` | WebI prompts, Crystal parameters |
| filters | `filters.json` | Query filters, report filters, section filters |
| tables | `tables.json` | Universe tables/classes, derived tables |
| columns | `columns.json` | Universe objects, dimensions, measures, details |
| joins | `joins.json` | Universe joins, contexts, loops |
| groups | `groups.json` | Crystal groups, WebI breaks, sections |
| sorts | `sorts.json` | Sort definitions |
| alerts | `alerts.json` | WebI alerters, Crystal conditional formatting |
| subreports | `subreports.json` | Crystal subreports, WebI report linking |
| charts | `charts.json` | Chart definitions (type, axes, series) |
| custom_sql | `custom_sql.json` | Freehand SQL, derived tables |

---

## 🏗️ Architecture

> 8-agent multi-agent model — see [docs/AGENTS.md](docs/AGENTS.md) for details.

<details>
<summary><b>📁 Project structure</b> (click to expand)</summary>

```
BOToPowerBI/
├── migrate.py                          # CLI entry point (30+ flags)
├── generate_report.py                  # HTML dashboard generator
├── pyproject.toml                      # Build config
├── bo_export/                          # 🔍 Extraction layer
│   ├── extract_bo_data.py              #   Main orchestrator (.wid/.rpt/.unx/.biar)
│   ├── webi_extractor.py              #   Web Intelligence extraction
│   ├── crystal_extractor.py           #   Crystal Reports extraction
│   ├── universe_extractor.py          #   Universe (UNX/UNV) extraction
│   ├── lumira_extractor.py            #   Lumira extraction
│   ├── biar_reader.py                 #   BIAR/LCMBIAR archive reader
│   ├── dax_converter.py               #   150+ BO formula → DAX
│   ├── m_query_builder.py             #   Power Query M generator (15+ connectors)
│   ├── server_client.py               #   BO CMS REST API client
│   └── converted_objects_adapter.py   #   Bridge: 15 JSON types → generation layer
├── powerbi_import/                     # ⚙️ Generation layer
│   ├── import_to_powerbi.py           #   Orchestrator
│   ├── pbip_generator.py              #   .pbip project + visuals + filters
│   ├── tmdl_generator.py              #   Semantic model → TMDL
│   ├── visual_generator.py            #   50+ visual types, PBIR configs
│   ├── assessment.py                  #   Pre-migration assessment (9 categories)
│   ├── dax_optimizer.py               #   DAX AST optimizer
│   ├── permission_mapper.py           #   BO security profiles → RLS + PowerShell
│   ├── shared_model.py                #   Multi-report merge engine
│   ├── refresh_generator.py           #   BO schedules → PBI refresh config
│   ├── incremental.py                 #   Incremental migration
│   ├── schema_drift.py                #   Schema drift detection
│   ├── validator.py                   #   Artifact validation + auto-fix
│   ├── governance.py                  #   Governance rules
│   ├── deploy/                        #   Deploy to PBI Service / Fabric
│   │   ├── deployer.py                #     Fabric deployment
│   │   └── multi_tenant.py            #     Multi-tenant deployment
│   └── ...                            #   (50+ modules from generation engine)
├── tests/                              # 🧪 244 tests across 8 files
├── docs/                               # 📚 Architecture, dev plan, enterprise guide
└── .github/
    ├── agents/                         # 🤖 8 specialized agents
    └── copilot-instructions.md
```

</details>

---

## 📝 CLI Reference

<details>
<summary><b>🔧 All CLI flags</b> (click to expand)</summary>

| Flag | Description |
|------|-------------|
| `input` | Path to `.wid`, `.rpt`, `.unx`, `.unv`, `.lumx`, or `.lums` file |
| `--biar FILE` | Path to BIAR/LCMBIAR archive for batch migration |
| `--batch DIR` | Directory containing BO artifacts for batch migration |
| `--server URL` | BO CMS server URL |
| `--folder PATH` | Server folder to migrate |
| `--user NAME` | BO server username |
| `--password SECRET` | BO server password |
| `--auth TYPE` | Authentication type: `enterprise`, `ldap`, `windows`, `sap` |
| `--output-dir DIR` | Custom output directory |
| `--output-format FORMAT` | Output format: `pbip` (default) or `fabric` |
| `--shared-model FILE [FILE ...]` | Build shared semantic model from multiple reports |
| `--model-name NAME` | Name for shared semantic model |
| `--assess` | Run migration readiness assessment |
| `--global-assess` | Cross-report portfolio assessment |
| `--deploy WORKSPACE_ID` | Deploy to Fabric workspace |
| `--deploy-refresh` | Trigger refresh after deployment |
| `--deploy-bundle WORKSPACE_ID` | Deploy shared model + thin reports |
| `--refresh-config` | Generate PBI scheduled refresh config from BO schedules |
| `--multi-tenant CONFIG` | Multi-tenant deployment config JSON |
| `--incremental` | Incremental migration: skip unchanged artifacts |
| `--schema-drift DIR` | Schema drift detection against previous extraction |
| `--calendar-start YEAR` | Calendar table start year (default: 2020) |
| `--calendar-end YEAR` | Calendar table end year (default: 2030) |
| `--culture LOCALE` | Locale for date formatting (default: `en-US`) |
| `--dry-run` | Parse and analyze without writing output |
| `--verbose` / `-v` | Enable debug logging |
| `--no-optimize-dax` | Skip DAX optimization pass |
| `--no-compare` | Skip comparison report generation |
| `--universe FILE` | Path to universe file for additional metadata |

</details>

---

## 🚀 Deployment

<details>
<summary><b>Power BI Service</b></summary>

```bash
# Set environment variables
export PBI_TENANT_ID="your-tenant-guid"
export PBI_CLIENT_ID="your-app-client-id"
export PBI_CLIENT_SECRET="your-app-secret"

# Migrate + deploy in one command
python migrate.py report.wid --deploy WORKSPACE_ID --deploy-refresh
```
</details>

<details>
<summary><b>Microsoft Fabric</b></summary>

```bash
# Fabric-native output (Lakehouse + Dataflow + Notebook + DirectLake)
python migrate.py report.wid --output-format fabric

# Deploy to Fabric workspace
python migrate.py report.wid --deploy WORKSPACE_ID
```
</details>

<details>
<summary><b>Multi-Tenant Deployment</b></summary>

```bash
# Deploy with per-tenant connection overrides
python migrate.py report.wid --multi-tenant tenants.json
```

The `tenants.json` file specifies per-tenant workspace IDs and connection string overrides (`${TENANT_SERVER}`, `${TENANT_DATABASE}`, etc.).
</details>

---

## 🧪 Testing

<p align="center">
  <img src="https://img.shields.io/badge/tests-244%20passed-brightgreen?style=for-the-badge" alt="Tests"/>
  <img src="https://img.shields.io/badge/test%20files-8-blue?style=for-the-badge" alt="Test Files"/>
</p>

```bash
python -m pytest tests/ -v               # Run all 244 tests
python -m pytest tests/ --tb=short       # Compact output
```

<details>
<summary><b>📋 Test suite breakdown</b> (click to expand)</summary>

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_dax_converter.py` | 56 | 150+ DAX formula conversions |
| `test_e2e_pipeline.py` | 47 | End-to-end .wid/.rpt → .pbip |
| `test_assessment.py` | 46 | Assessment, validator, DAX optimizer |
| `test_phase5_advanced.py` | 32 | @Aggregate_Aware, context ops, RLS, refresh, multi-tenant |
| `test_crystal_pipeline.py` | 21 | Crystal formula extraction + conversion |
| `test_cli.py` | 13 | CLI argument parsing + dispatch |
| `test_biar_reader.py` | 12 | BIAR/LCMBIAR archive reading |
| `test_webi_extractor.py` | 9 | WebI document extraction |
| `test_extraction.py` | 8 | File validation + routing |

</details>

### CI/CD Pipeline

```mermaid
flowchart LR
    L["🔍 Lint\nruff"] --> T["🧪 Test\n244 tests\nPy 3.12–3.14"]
    T --> V["✅ Validate\n.wid/.rpt migrations"]
    V --> S["📦 Staging\nFabric deploy"]
    S --> P["🚀 Production\nManual approval"]

    style L fill:#6366f1,color:#fff
    style T fill:#22c55e,color:#fff
    style V fill:#3b82f6,color:#fff
    style S fill:#f59e0b,color:#000
    style P fill:#ef4444,color:#fff
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| 🏗️ [Architecture](docs/ARCHITECTURE.md) | System design overview |
| 🤖 [Agents](docs/AGENTS.md) | 8-agent specialization model |
| 🗓️ [Development Plan](docs/DEVELOPMENT_PLAN.md) | 40-sprint development roadmap |
| 📋 [Gap Analysis](docs/GAP_ANALYSIS.md) | Known conversion gaps |
| 🏢 [Enterprise Guide](docs/ENTERPRISE_GUIDE.md) | Enterprise migration planning |

---

## ⚠️ Known Limitations

- BO **Lumira Designer** applications have limited extraction (layout → stub visuals)
- Data source connection strings must be reconfigured in Power Query after migration
- **@Aggregate_Aware** with 5+ levels generates complex SWITCH — may need manual tuning
- Crystal Reports **subreport drill-through** parameters may need manual validation
- See [docs/GAP_ANALYSIS.md](docs/GAP_ANALYSIS.md) for the full list

---

## 🤝 Contributing

Contributions are welcome! The project uses an 8-agent model — see [docs/AGENTS.md](docs/AGENTS.md) for scope ownership.

```bash
git clone <repo-url>
cd BOToPowerBI
python -m pytest tests/ -q   # Make sure tests pass
```

---

<p align="center">
  <sub>Built with ❤️ for the Power BI community</sub><br/>
  <sub>If this tool saves you time, consider giving it a ⭐</sub>
</p>

## License

MIT
