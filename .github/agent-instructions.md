# Agent Behavior Instructions — BusinessObjects to Power BI Migration

Rules for AI coding agents working in this codebase. Read `.github/copilot-instructions.md`
for full project context.

**Multi-agent architecture**: This project uses a specialized agent model.
See `docs/AGENTS.md` for the full architecture diagram and `.github/agents/` for per-agent definitions.

---

## Project Context (Quick Reference)

- **Pipeline**: BusinessObjects source → [bo_export] → Extraction → [migration_output, powerbi_import] → Power BI
- **Source**: `bo_export/`
- **Target**: `migration_output/`, `powerbi_import/`
- **Tests**: `pytest tests/ --tb=short -q` (or `python -m pytest tests/ --tb=short -q` with the selected interpreter)
- **Agents**: See `.github/agents/` and `docs/AGENTS.md`
- **Ownership**: `.github/agents/ownership.json`; validate with `python -m pytest tests/test_agent_contracts.py -q`
- **Planning/docs gates**: Roadmap Planner uses `docs/DEVELOPMENT_PLAN.md`; Documentation Guardian checks changed claims before and after a task
- **Quality/repair/AI**: Evidence owns deterministic reports, Healing recovery behavior, AI optional provider/pattern work, AgentTools local MCP transport
- **Source server**: BusinessObjects owns the CMS client; Extractor owns local formats and the BO adapter
- **Migration skill**: `.github/skills/bo-to-powerbi/SKILL.md`
- **Fabric/MCP routing**: `.github/skills/fabric-mcp-routing/SKILL.md`; setup in `docs/FABRIC_MCP_SETUP.md`
- **Fabric ownership**: Fabric handles local generators; Deployer handles explicitly authorized remote writes. Local tests do not prove Desktop or Fabric execution.

---

## Learned Lessons (Global)

### File Edit Safety
- Use `elem is not None` instead of `if elem` (Python 3.14 `Element.__bool__()` change)
- `replace_string_in_file` fails on duplicate matches — use unique surrounding context
- Always include 3-5 lines of unchanged context before and after the target text
- Read the file FIRST, then edit — never assume content from memory

### Function Safety
- Always `grep_search` for an existing function/class name before creating a new one
- Test function signatures MUST match implementation

---

## Workflow Rules

### 1. Plan Before Build
- For multi-step work, create a plan before starting
- If something goes sideways, STOP and re-plan

### 2. Read Before Write
- **Always read target code before editing** — never assume file contents
- Check `docs/` for current project context

### 3. Testing Contract
- Run `pytest tests/ --tb=short -q` after EVERY implementation change
- If tests fail → fix them before reporting completion
- New features **require** new tests — no exceptions
- Never weaken test assertions to make tests pass

### 4. Scope Discipline
- Only modify files directly related to the task
- No drive-by refactors, no "while I'm here" improvements
- Prefer the smallest change that solves the problem
