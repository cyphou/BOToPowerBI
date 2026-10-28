---
name: fabric-mcp-routing
description: "Use when: BO migration needs Fabric or Power BI MCP tools, workload skills, local semantic model connections, PBIP publishing, Dataflow Gen2, Spark notebooks, workspace discovery, or deployment evidence. Routes to installed official workload skills without inventing server IDs or authorizing cloud writes."
---

# Fabric Skills And MCP Routing

## Select The Workload

Load the named skill from the current session's installed skills before acting.
These are external prerequisites, not skills bundled or implemented by this repository.

| Task | Installed Skill | Repository Owner |
|------|-----------------|------------------|
| Tables, relationships, DAX, RLS, Direct Lake, model refresh | `semantic-model-authoring` | Semantic (Fabric for its wrapper) |
| PBIR pages/visuals, report design, PBIP publishing/rebind | `powerbi-report-cli` | Visual; Deployer for publishing |
| Natural-language business questions over existing reports/models | `fabriciq` | Read-only analysis; not a model edit |
| Dataflow Gen2 and Power Query M definitions | `dataflows-cli` | Fabric / Wiring |
| PySpark notebooks, notebook `%%sql` cells, named notebook runs, MLV | `spark-cli` | Fabric |
| Plain T-SQL against a Warehouse or Lakehouse SQL endpoint, not notebook cells | `sqldw-cli` | Fabric; Deployer for remote writes |
| Fabric SQL database (OLTP) | `sqldb-cli` | Deployer |
| Find an item when its workspace is unknown | `search-consumption-cli` | Deployer |
| Git synchronization | `git-integration-operations-cli` | Deployer |
| ALM stage promotion | `deployment-pipelines-authoring-cli` | Deployer |

## Read The Workload Procedure

- `semantic-model-authoring`: load modeling guidelines before model work, Direct Lake guidelines for OneLake, and TMDL guidelines for generator-format changes. Tables sourced from OneLake use entity partitions and a shared named expression, not M partitions with a Direct Lake label.
- `dataflows-cli`: select `authoring`, `consumption`, or `upgrade` and read that mode's reference end to end before commands. Definition authoring needs `mashup.pq`, `queryMetadata.json`, and `.platform`; destination helper queries must be hidden with `loadEnabled: false`. Source/destination connections and first-refresh `ApplyChangesIfNeeded` are separately authorized environment work.
- `spark-cli`: notebook code and named notebook runs use `authoring`; ad-hoc Livy is `consumption`; failed-run triage is `operations`; existing MLV schedules/history use `mlv`. Read the mode and notebook-authoring core before code generation. Use persistent `metadata.dependencies.lakehouse` bindings and newline-terminated cell sources.
- `deployment-pipelines-authoring-cli` is for ALM promotion, not the generated Data Pipeline ETL definition. Do not confuse these two pipeline concepts.

Repository generator changes are offline source-code work, not permission to
connect to or change a customer artifact. Use the extracted BO schema as the
local generation contract. Missing workspace, lakehouse, or connection IDs stay
explicitly unbound until an authorized environment workflow resolves them.
Logical item UUIDs in `.platform` are not physical service item IDs.

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