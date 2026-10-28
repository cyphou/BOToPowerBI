---
description: "Shared rules for all agents in the BusinessObjects to Power BI migration project. USE FOR: enforcing project-wide constraints, coding standards, and safety rules."
---

# Shared Project Rules — BusinessObjects to Power BI Migration

All agents MUST follow these rules. They apply to every file in the project.

This file is a shared reference, not an automatically applied path instruction.
Read it explicitly when entering a specialist role; always-on routing is in
`.github/copilot-instructions.md`.

## Pipeline Architecture

```
BusinessObjects source → [bo_export] → Extraction → [migration_output, powerbi_import] → Power BI
```

- **Source**: `bo_export/`
- **Target**: `migration_output/`, `powerbi_import/`
- **Tests**: `tests/`
- **Docs**: `docs/`

## Hard Constraints

1. **No duplicate functions** — always search for an existing name before creating one
2. **Read before write** — never assume file contents from memory
3. **Test after every change** — run `pytest tests/ --tb=short -q`
4. **Git hygiene** — commit only when tests pass, conventional messages (`feat:`, `fix:`, `test:`, `docs:`)
5. **Identifier safety** - preserve and test BO names with Unicode, spaces, apostrophes, percent signs, slashes, and parentheses; normalize only at the target contract boundary.
6. **Generic behavior** - derive conversion from metadata, types, expressions, and structure, never from matching a customer's report, field, or datasource name.
7. **Privacy and provenance** - never add secrets, customer defaults, personal paths, or unverified third-party content. Before an explicitly requested push, audit the exact publication scope and resolve sensitive/provenance findings; do not commit or push without authorization.
8. **Dependencies** - preserve standard-library-only core migration; optional deployment/provider dependencies remain optional. New dependencies need explicit approval.

## Ownership And Documentation Gate

- `.github/agents/ownership.json` is the authoritative primary-owner and collaboration contract. Every Python module under `bo_export/` and `powerbi_import/` has one primary owner; coordinators and Reviewer own no generator modules.
- Read this contract and the owning role before editing. The collaboration entries permit a coordinated slice, not unrestricted edits to a whole shared file.
- `tests/test_agent_contracts.py` checks discovery, paths, exact delegation names, and complete/nonoverlapping engine ownership. Update the contract when adding or moving a module.
- Consult **Documentation Guardian** before and after a task that changes capabilities, ownership, CLI behavior, or release claims. Review the affected documentation locally if that role is not available in the session; do not fabricate an agent invocation.
- **Roadmap Planner** maintains `docs/DEVELOPMENT_PLAN.md`, the existing canonical plan. Historical measurements there remain dated evidence; do not invent a separate roadmap or copy Tableau release numbers.
- The BO adapter's 15 raw collections and target generation contract remain authoritative. The source reference's Hyper/Prep workflows, 23-object schema, error classes, and unimplemented executors are not BO capabilities.

## Skills, MCP, And Handoffs

- Start with `.github/skills/bo-to-powerbi/SKILL.md` for migration operations and `.github/skills/fabric-mcp-routing/SKILL.md` for Fabric/Power BI platform work.
- Load the installed workload skill before platform-specific authoring. If unavailable, state that explicitly and consult official documentation rather than inventing a tool or command.
- A coordinating agent needs the `agent` tool and must call agents by exact frontmatter name. Specialists return out-of-scope work to the coordinator instead of assuming they can delegate.
- Read access does not imply write ownership. Keep source changes with the owning specialist and tests with Tester.
- Preserve BO names, Unicode, formula semantics, and source metadata. Never introduce Tableau-specific behavior or customer-specific heuristics as generic rules.
- Do not copy personal MCP configuration, absolute user paths, secrets, or customer data. Discover tools in the current session; do not assume the reference project's MCP server exists here.
- Local artifact generation, static tests, Desktop checks, and deployed execution are separate evidence. Report unperformed checks as `not_run`.

## Cross-Agent Handoff

Provide the concrete source/target, observed failure, exact files/symbols, owning
role, authorized scope, smallest proposed change, discriminating test, required
suite, and expected return evidence. Coordinators must combine results and verify
the integration; delegation is not proof of completion.

The local MCP `agent_handoff` is a read-only findings packet, not automatic
dispatch or resolution. Run a fresh `quality_report` after artifact changes.
Do not invent acknowledgement tools, persistent ledgers, a Python preceptor, or
runtime evidence that the BO implementation does not supply.

## Python Conventions

- Python 3.12+ compatible
- `unittest.TestCase` for all test classes
- No type annotations on code you didn't write
- No docstrings on code you didn't write
- Prefer smallest change that solves the problem

## Learned Pitfalls (Global)

- Use `elem is not None` instead of `if elem` (Python 3.14 `Element.__bool__()` change)
- `replace_string_in_file` fails on duplicate matches — use unique surrounding context
- Never weaken test assertions to make tests pass
- Stage only files related to the current task
