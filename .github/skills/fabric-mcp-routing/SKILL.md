---
name: fabric-mcp-routing
description: "Use when: BO or SAP BW migration needs Fabric or Power BI guidance, workload skills, MCP tools, local semantic model connections, PBIP publishing, Dataflow Gen2, Spark notebooks, workspace discovery, or deployment evidence. Routes to installed workload skills without inventing server IDs or authorizing cloud writes."
---

# Fabric Skills And MCP Routing

## Select The Workload

Load the named skill from the current session's installed skills before acting.
These are external prerequisites, not skills bundled or implemented by this repository.
Skill provider prefixes can vary by installation; select the available semantic-model
authoring provider and use one model-authoring MCP server per task.

| Task | Installed Skill | Repository Owner |
|------|-----------------|------------------|
| Plan Bronze/Silver/Gold ingestion and analytics architecture | `e2e-medallion-architecture` | Fabric / Assessor |
| Estimate Fabric capacity and cost before migration | `e2e-fabric-cost-estimation` | Assessor |
| Tables, relationships, DAX, RLS, Direct Lake, model refresh | `fabric-skills:semantic-model-authoring` (or `powerbi-authoring:semantic-model-authoring`) | Semantic (Fabric for its wrapper) |
| PBIR pages/visuals, report design, PBIP publishing/rebind | `powerbi-report-cli` | Visual; Deployer for publishing |
| Natural-language business questions over existing reports/models | `fabriciq` | Read-only analysis; not a model edit |
| Dataflow Gen2 and Power Query M definitions | `dataflows-cli` | Fabric / Wiring |
| PySpark notebooks, notebook `%%sql` cells, named notebook runs, MLV | `spark-cli` | Fabric |
| Plain T-SQL against a Warehouse or Lakehouse SQL endpoint, not notebook cells | `sqldw-cli` | Fabric; Deployer for remote writes |
| Fabric SQL database (OLTP) | `sqldb-cli` | Deployer |
| Find an item when its workspace is unknown | `search-consumption-cli` | Deployer |
| OneLake catalog governance and protection | `onelake-catalog-govern-cli` | Deployer |
| Environment-specific variables and value sets | `variable-library-cli` | Fabric / Deployer |
| Git synchronization | `git-integration-operations-cli` | Deployer |
| ALM stage promotion | `deployment-pipelines-authoring-cli` | Deployer |

## Full SAP BW Warehouse Migration

Replacing an entire BW warehouse is a different scope from migrating BO reports
that query BW. This repository does not implement full BW warehouse migration.
The separate `migrate_bw.py` entry point can generate an unbound Bronze notebook
for an explicitly staged Parquet snapshot; it does not extract SAP data,
replace transformations or reconcile BW. It is not part of the BO CLI/MCP
bundle or its quality gate. Use the `spark-cli` authoring procedure before
working on the notebook and obtain separate authorization for remote execution.
`migrate_bw_handoff.py` only evaluates local declarations for a normalized
snapshot-to-delta sequence; it does not prove that a source provides its declared
position semantics or that a Fabric pipeline runs correctly.
Before proposing a target or claiming coverage:

- Inventory BW/BW/4HANA versions, historical data, InfoObjects, providers,
  transformations and ABAP routines, BEx semantics, process chains, security,
  planning, upstream sources, and all downstream consumers.
- Design historical extraction and reconciliation from BW separately from the
  durable feeds from SAP and other upstream systems. A target that continues to
  depend on BW cannot support BW retirement.
- Assess a Fabric Bronze/Silver/Gold design, Delta tables, SQL/Warehouse serving,
  semantic models, orchestration, governance, and operational recovery using the
  applicable skills above. These mappings are designs, not automatic equivalents.
- Assess planning/writeback separately; [Planning in Fabric](https://learn.microsoft.com/en-us/fabric/iq/plan/overview)
  is a candidate subject to its prerequisites, limits, and business validation,
  not an automatic replacement for BW-IP or BPC.
- Classify each object and dependency as supported, requiring manual redesign,
  or blocked. Require source-to-target data, calculation, security, and consumer
  reconciliation, then phased cutover and an approved retirement decision.

## SAP BW Source Routes

These are platform options to assess for historical extraction or durable feeds,
not implemented BW migration capabilities:

- The [SAP BW Application Server Dataflow Gen2 connector](https://learn.microsoft.com/en-us/fabric/data-factory/connector-sap-bw-application-server)
  accesses the analytical layer; a Power BI model can also retain BW as a source
  during transition. Neither option replaces the warehouse or its upstream feeds.
- The [SAP BW Open Hub pipeline connector](https://learn.microsoft.com/en-us/fabric/data-factory/connector-sap-bw-open-hub-application-server-overview)
  has different prerequisites and supported modes. Check BW version and Open Hub
  compatibility against current Fabric and SAP documentation.
- [Copy job with the Microsoft SAP ABAP Add-On](https://learn.microsoft.com/en-us/fabric/data-factory/copy-job-tutorial-sap-abap)
  supports documented BW versions and full or watermark-based incremental copying
  of supported tables and views. A watermark is not automatically delete-aware CDC;
  validate source-object semantics, SAP installation, gateway, and limits.
- [SAP Datasphere Outbound](https://learn.microsoft.com/en-us/fabric/data-factory/copy-job-tutorial-sap-datasphere)
  can provide initial plus CDC replication via cloud-storage staging for supported
  SAP sources. It requires a Datasphere environment and Premium Outbound Integration;
  verify object coverage, SAP licensing, and costs.
- Select the route per source and object. Verify supported versions, historical
  snapshots, updates and deletes, delta recovery, permissions, network, throughput,
  and contractual use. Never assume that data extraction reproduces BW semantics.
- Use `dataflows-cli` for Dataflow Gen2, `spark-cli` for Spark transformations,
  and `semantic-model-authoring` for the resulting model. The installed
  `pipeline-migration` skill addresses Synapse-to-Fabric pipelines, not generic
  SAP BW pipeline authoring. `deployment-pipelines-authoring-cli` covers ALM,
  not data-ingestion pipelines. If no applicable pipeline-authoring skill is
  available, use current official Fabric documentation and supported tools.
- Extracting BW data does not by itself migrate BEx semantics, authorization, or
  reconcile results. Record unsupported semantics and separately validate source
  and target results. Do not copy credentials or assume access to a BW system.

## Read The Workload Procedure

- `semantic-model-authoring`: load modeling guidelines before model work, Direct Lake guidelines for OneLake, and TMDL guidelines for generator-format changes. Tables sourced from OneLake use entity partitions and a shared named expression, not M partitions with a Direct Lake label.
- `dataflows-cli`: select `authoring`, `consumption`, or `upgrade` and read that mode's reference end to end before commands. Definition authoring needs `mashup.pq`, `queryMetadata.json`, and `.platform`; destination helper queries must be hidden with `loadEnabled: false`. Source/destination connections and first-refresh `ApplyChangesIfNeeded` are separately authorized environment work.
- `spark-cli`: notebook code and named notebook runs use `authoring`; ad-hoc Livy is `consumption`; failed-run triage is `operations`; existing MLV schedules/history use `mlv`. Read the mode and notebook-authoring core before code generation. Use persistent `metadata.dependencies.lakehouse` bindings and newline-terminated cell sources.
- `deployment-pipelines-authoring-cli` is for ALM promotion, not the generated Data Pipeline ETL definition. Do not confuse these two pipeline concepts.

Repository generator changes are offline source-code work, not permission to
connect to or change a customer artifact. Preserve the extracted BO schema as
the existing BO generation contract; full BW migration needs a separately
designed source contract and is not provided by the current generator. Missing
workspace, lakehouse, or connection IDs stay explicitly unbound until an
authorized environment workflow resolves them. Logical item UUIDs in `.platform`
are not physical service item IDs.

## Discover And Connect

The repository's `bo-to-powerbi` MCP server is a local migration-engine surface,
not a Fabric workspace connector. Its six tools are documented in
`docs/FABRIC_MCP_SETUP.md`; AgentTools owns their transport and security contracts.

1. Discover the tools actually available in this session. Tool names and server IDs vary by installation; never infer availability from an agent's prose.
2. For semantic-model authoring, connect to the explicit Desktop model, local PBIP/TMDL files, or workspace model first. Use the Power BI model MCP server for that task; do not combine it with the hosted Power BI Authoring server.
3. Use Fabric MCP for supported workspace/item/OneLake operations, following the workload skill's capability restrictions. Use its documented CLI fallback only when supported and available, not invented API calls.
4. Use Microsoft Learn MCP for official documentation when available. It documents APIs; it does not deploy artifacts or prove a connection to Fabric.
5. If a skill or server is missing, state the missing prerequisite and follow `docs/FABRIC_MCP_SETUP.md`. Do not silently install, start, or trust a new server.

## Permissions And Evidence

- Start remote discovery with read-only operations and explicitly identify the intended workspace/item.
- Repository edits do not authorize publish, overwrite, delete, rebind, refresh, notebook execution, or pipeline runs. Obtain confirmation of the planned remote changes first.
- Never request passwords/tokens through chat, commit credentials, or print authentication output containing secrets.
- Remote execution can incur cost or change data. Delegate to Deployer and follow the workload's authorization requirements.
- Record actual operation results. Generated JSON/TMDL and passing pytest tests are local evidence only; unperformed Desktop/runtime checks are `not_run`.