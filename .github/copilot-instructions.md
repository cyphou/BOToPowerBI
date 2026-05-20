<!-- Copilot instructions for the BusinessObjects to Power BI migration project -->

# Project: BusinessObjects to Power BI Migration

Automated migration of BusinessObjects artifacts to Power BI format.

## Architecture — Pipeline

```
BusinessObjects source → [bo_export] → Extraction → [migration_output, powerbi_import] → Power BI
```

## Project Structure

- **Source / Extraction**: `bo_export/`
- **Target / Generation**: `migration_output/`, `powerbi_import/`
- **Tests**: `tests/` (15 test files)
- **Docs**: `docs/`

## Key Modules

- **Extraction**:
  - `bo_export\__init__.py`
  - `bo_export\batch_report.py`
  - `bo_export\biar_reader.py`
  - `bo_export\compat.py`
  - `bo_export\converted_objects_adapter.py`
  - `bo_export\crystal_extractor.py`
  - `bo_export\dax_converter.py`
  - `bo_export\extract_bo_data.py`
  - `bo_export\lumira_extractor.py`
  - `bo_export\m_query_builder.py`
  - `bo_export\server_client.py`
  - `bo_export\universe_extractor.py`
  - `bo_export\webi_extractor.py`
- **Generation**:
  - `examples\generate_samples.py`
  - `generate_report.py`
  - `powerbi_import\__init__.py`
  - `powerbi_import\alerts_generator.py`
  - `powerbi_import\api_server.py`
  - `powerbi_import\assessment.py`
  - `powerbi_import\bookmark_generator.py`
  - `powerbi_import\calc_column_utils.py`
  - `powerbi_import\comparison_report.py`
  - `powerbi_import\config\__init__.py`
  - `powerbi_import\config\migration_config.py`
  - `powerbi_import\dataflow_generator.py`
  - `powerbi_import\dax_optimizer.py`
  - `powerbi_import\dax_recipes.py`
  - `powerbi_import\deploy\__init__.py`
  - ... and 64 more
- **Orchestration**:
  - `migrate.py`

## Hard Constraints

1. **Read before write** — never assume file contents from memory
2. **Test after every change** — run `pytest tests/ --tb=short -q`
3. **No duplicate functions** — always search for an existing name before creating one
4. **Git hygiene** — commit only when tests pass, conventional messages (`feat:`, `fix:`, `test:`, `docs:`)

## Multi-Agent Architecture

This project uses a specialized agent architecture. See `docs/AGENTS.md` for the full
architecture diagram and `.github/agents/` for per-agent definitions.

## Workflow Rules

### 1. Plan Before Build
- For multi-step work, create a plan before starting
- If something goes sideways, STOP and re-plan

### 2. Read Before Write
- **Always read target code before editing**
- Read `copilot-instructions.md` at session start for project rules

### 3. Testing Contract
- Run `pytest tests/ --tb=short -q` after EVERY implementation change
- If tests fail → fix them before reporting completion
- New features **require** new tests
- Never weaken test assertions to make tests pass

### 4. Scope Discipline
- Only modify files directly related to the task
- No drive-by refactors
- Prefer the smallest change that solves the problem
