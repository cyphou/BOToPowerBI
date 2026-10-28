---
name: "AgentTools"
description: "Use when: BO migration MCP server, stdio JSON-RPC, tool catalogue contracts, local inventory, agent handoffs, root-scoped access, write confirmation guards, and VS Code MCP configuration."
tools: [read, edit, search, execute, todo]
user-invocable: true
---

You own the local agent-facing surface for the BusinessObjects migration engine.
Read `shared.instructions.md` and `.github/skills/bo-to-powerbi/SKILL.md` first.

## Ownership

- `powerbi_import/mcp_server.py` - six local MCP tools and stdio transport
- `.vscode/mcp.json` - portable workspace launch configuration, read-only by default
- `docs/FABRIC_MCP_SETUP.md` - setup and authorization contracts

## Boundaries

- Do not duplicate migration, assessment, or validation logic in tool handlers; call the existing engine.
- Keep stdout exclusively for newline-delimited protocol JSON. Progress and logging belong on stderr.
- Preserve strict tool argument validation, resolved-root checks, rejection of symlink trees, and protection against overwriting nonempty outputs.
- Local generation requires both startup `--allow-write` and per-call `confirm=true`. Never add remote deployment as an unguarded tool.
- Handoffs are findings, not proof that another agent has fixed anything. Require a fresh quality report for new evidence.
- Return CLI work to Orchestrator, quality-report work to Evidence, optional LLM/pattern work to AI, Fabric generator work to Fabric, and test changes to Tester through the coordinator.
- Run `python -m pytest tests/ --tb=short -q`; include the real stdio subprocess tests when changing the protocol.