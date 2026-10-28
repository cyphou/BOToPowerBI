# Fabric Skills And MCP Setup

This repository adapts TableauToPowerBI's specialist ownership, migration-skill,
and evidence boundaries to BusinessObjects. It does not import the Tableau engine,
its local MCP server, or its user-specific configuration.

## Prerequisites

- VS Code with GitHub Copilot agents enabled.
- The applicable official Fabric workload skills listed in
  [the routing skill](../.github/skills/fabric-mcp-routing/SKILL.md).
- An approved Fabric MCP server for workspace/item operations, and a Power BI
  model MCP server for semantic-model work when those operations are required.
- Microsoft Learn MCP is useful for documentation, but optional for offline generation.

Local CLI migration and tests do not require a live MCP connection. Repository
skills provide instructions; they do not install the external workload skills or servers.

## Local Migration MCP Server

The repository now implements its own stdlib MCP server, independently of the
Tableau server. It uses newline-delimited JSON-RPC over stdio, without HTTP or
cloud access. Review the workspace launch configuration in
[.vscode/mcp.json](../.vscode/mcp.json) before starting it in VS Code. The command
uses `python` from PATH; select your project interpreter or adjust the command if needed.

```powershell
python -m powerbi_import.mcp_server --list
python -m powerbi_import.mcp_server --root .
```

The server is launched by the MCP client; interactive startup is not required.
The default workspace configuration does **not** enable writes.

| Tool | Purpose | Persistent Writes |
|------|---------|-------------------|
| `inventory` | Recursively list supported BO files | None |
| `assess` | Assess a report/universe using temporary extraction | None |
| `quality_report` | Static PBIP/Fabric report with actionable priorities | None |
| `agent_handoff` | Filter the latest report's findings by owner | None |
| `migrate` | Generate a single source or directory batch | Explicit opt-in |
| `shared_model` | Merge two or more sources into a model and thin reports | Explicit opt-in |

Generation requires **both** startup `--allow-write` and tool argument
`confirm=true`. All supplied paths must resolve within `--root`; existing nonempty
outputs and symlink source/project trees are rejected. There are no deployment,
refresh, credential, or arbitrary-command tools. Direct archive-file tool calls are
not exposed; use the BIAR CLI or a batch directory for archives.
`agent_handoff` is advisory and does not apply or acknowledge fixes.

For `migrate` with `output_format: "fabric"`, generation is followed by local
quality validation. Blocking findings return `isError: true` and structured
`ok: false`, `exit_code: 6`, `output_dir`, and `quality_report`. Artifacts and the
per-project `quality_report.json` are preserved; the current findings are also
available to `agent_handoff`. A failed batch may have another nonzero exit code
for source/extraction errors; it is never reported as a successful migration.
Shared-source ambiguity can be rejected before generation with exit code 3,
including same-named queries from different physical sources; no generated quality
report is implied in that case. The merge path retains isolated physical tables
instead of deleting them, but does not infer a relationship or fabricate a schema.
The MCP transport process can still exit normally: a failed tool operation is a
JSON-RPC tool result, not a transport crash. The `shared_model` MCP tool retains
its existing PBIP interface; the shared Fabric quality gate is exposed through
the CLI. Warnings alone do not imply a failed migration, nor deployment readiness.

External Fabric/Power BI MCP servers below remain separate prerequisites for
remote platform work. The local server's startup tests do not prove a VS Code
client connection, Desktop rendering, or access to a Fabric workspace.

## Configure Safely

1. Inspect existing MCP servers and the session tool picker first. Reuse an approved
   installation instead of creating duplicate servers with different IDs.
2. If a capability is missing, obtain the publisher's documented endpoint or launch
   command and review its permissions. Use **MCP: Add Server** in VS Code; do not
   guess package names, binaries, or Fabric endpoints.
3. Select the intended scope. A personal setup belongs outside the repository.
   For a shared configuration, follow the current VS Code format documentation:
   portable `.mcp.json` uses `mcpServers`, while VS Code `.vscode/mcp.json` uses
   `servers`. Do not interchange formats or commit secrets or personal paths.
4. Complete trust and authentication prompts yourself. Never send secrets in chat.
5. Enable only the tools needed for the task. Semantic, Visual, and Deployer inherit
   session-configured tools so MCP tools are not accidentally excluded by a fixed
   local-tool allowlist. Their written ownership and authorization limits still apply.

The committed configuration contains only this repository's local engine. External
server installation and identity remain environment-specific; no personal paths,
tenant/workspace defaults, tokens, or remote server configuration are copied.

## Verify Before Authoring

Local Fabric bundles now contain source-table Direct Lake partitions, three-part
Gen2 definitions, persistent notebook lakehouse dependencies, and UUID-based item
manifests. These are format contracts, not live bindings. Inspect `validation`
inside the generated `fabric_project_metadata.json`; the quality tool also
rechecks the current files rather than trusting that saved result.

`ingestion_plan` assigns every source table to exactly one writer: CSV/Excel to
Notebook, connected sources/custom SQL to Dataflow. `materialization` assigns the
calculated columns to the primary ETL notebook. Validation checks actual emitted
targets and column writes; a file-only pipeline has no Dataflow refresh. File
contents, credentials, real item IDs, and external execution remain environment
prerequisites, not effects of these local tests.

Mode-specific workload references must be loaded before operations. In particular,
Dataflow destination helpers must be hidden with `loadEnabled: false`, and the
first authorized refresh after a definition change needs `ApplyChangesIfNeeded`.
The local generator does not discover connections, create credentials, refresh
items, or execute notebooks. `Previous` without source ordering and groups without
members remain explicit quality blockers rather than invented transformations.

| Capability | Low-impact verification | What It Does Not Prove |
|------------|-------------------------|------------------------|
| Official documentation | Retrieve a relevant page through Microsoft Learn MCP | Fabric authentication |
| Workspace access | Read the explicitly selected workspace or list its items | Write permissions or deployment |
| Semantic model | Connect to the explicit target, then read model metadata | Valid DAX execution or refresh |
| Local report | Run the report skill's supported PBIR validation | Desktop rendering or visual parity |
| Deployment | After confirmation, publish then read the operation/item status | Refresh or Pipeline completion |

Do not perform writes as connection smoke tests. Keep semantic-model authoring on
one MCP server per task; do not combine local-model and hosted authoring servers.
If access or authentication is unavailable, report the blocker and mark remote
verification `not_run` rather than claiming success.

## Entry Points

- [BO migration skill](../.github/skills/bo-to-powerbi/SKILL.md)
- [Fabric agent](../.github/agents/fabric.agent.md)
- [Agent architecture](AGENTS.md)
- [VS Code MCP setup](https://code.visualstudio.com/docs/copilot/customization/mcp-servers)
- [VS Code MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)