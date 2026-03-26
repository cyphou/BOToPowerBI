---
description: "Shared rules for all agents in the Business Objects to Power BI migration project. USE FOR: enforcing project-wide constraints, coding standards, and safety rules."
---

# Shared Project Rules — Business Objects to Power BI Migration

All agents MUST follow these rules. They apply to every file in the project.

## Pipeline Architecture

```
.wid/.rpt/.unx/.biar → [Extraction] → 15 JSON files → [Generation] → .pbip (PBIR v4.0 + TMDL)
                                                                     → Fabric-native (Lakehouse + Dataflow + Notebook + SemanticModel + Pipeline)
```

- **Source**: `bo_export/` — extraction + DAX converter + M query builder
- **Target**: `powerbi_import/` — TMDL generator + PBIR report + visual generator + Fabric generators
- **Tests**: `tests/` — unit and integration tests
- **Docs**: `docs/` — architecture, dev plan, gap analysis, known limitations, roadmap

## Hard Constraints

1. **No external dependencies** — Python standard library only for core migration
2. **No duplicate functions** — always `grep_search` for an existing name before creating one
3. **Read before write** — never assume file contents from memory
4. **Test after every change** — run `pytest tests/ --tb=short -q`
5. **Git hygiene** — commit only when tests pass, conventional messages (`feat:`, `fix:`, `test:`, `docs:`)

## Python Conventions

- Python 3.12+ compatible
- `unittest.TestCase` for all test classes
- No type annotations on code you didn't write
- No docstrings on code you didn't write
- Prefer smallest change that solves the problem

## BO-Specific Conventions

- BO formulas use `=FunctionName([Object])` syntax — always preserve `=` prefix awareness
- Universe objects use `\Class\Subclass\Object` path notation
- WebI variables have three types: Dimension, Measure, Detail — map correctly
- Crystal formulas use `{Table.Field}` syntax for field references
- Prompts have LOV (List of Values) — map to Power BI slicer + parameter tables
- Contexts in Universe = query filter scope — map to ALLEXCEPT patterns in DAX

## Learned Pitfalls (Global)

- Use `elem is not None` instead of `if elem` (Python 3.14 `Element.__bool__()` change)
- `replace_string_in_file` fails on duplicate matches — use unique surrounding context
- Never weaken test assertions to make tests pass
- Stage only files related to the current task
- M `if...then` without `else` causes Power BI M engine error — always emit `else null`
- M single-quoted strings in `IN {…}` sets must be converted to double-quoted
- BIAR archives may contain nested ZIP structures — handle recursively
- BO Server REST API pagination uses `offset` + `limit` — not page numbers

## Cross-Agent Handoff Protocol

When your task requires work outside your domain:
1. Complete your part fully (including tests for your domain)
2. State clearly what the next agent needs to do
3. List the exact files and functions involved
4. Provide any intermediate artifacts (JSON, dict structures)

## Key References

- Project rules: `.github/copilot-instructions.md`
- Development plan: `docs/DEVELOPMENT_PLAN.md`
- Gap analysis: `docs/GAP_ANALYSIS.md`
- Known limitations: `docs/KNOWN_LIMITATIONS.md`
- Agent architecture: `docs/AGENTS.md`

## Cross-Cutting Utilities

- `powerbi_import/security_validator.py` — Shared security module (path validation, ZIP slip defense, XXE protection, credential redaction)
- `powerbi_import/recovery_report.py` — Self-healing recovery tracker
- `powerbi_import/html_template.py` — Shared HTML report template (Fluent/PBI design)
