# Multi-Agent Architecture — BusinessObjects to Power BI Migration

This project uses a **specialized agent model**. Each agent has scoped domain knowledge,
file ownership, and clear boundaries.

The TableauToPowerBI roles are reapplied to the BO implementation, preserving
the additional BO coordinator roles and the separate AgentTools MCP owner.
The authoritative, machine-checked ownership map is
[ownership.json](../.github/agents/ownership.json), validated by
[test_agent_contracts.py](../tests/test_agent_contracts.py).

## Quick Reference

| Agent | Invoke When | Owns |
|-------|-------------|------|
| **@orchestrator** | Pipeline coordination, CLI, batch | `migrate.py`, orchestration modules |
| **@extractor** | Parsing BusinessObjects source artifacts | `bo_export/` extraction modules |
| **BusinessObjects** | Live CMS/BI platform client, auth, inventory, download | `bo_export/server_client.py` |
| **@converter** | Formula/expression conversion (coordination layer) | Delegates to @dax and @wiring |
| **@dax** | DAX/formula correctness, conversion, optimization | DAX conversion modules |
| **@wiring** | DAX↔M bridge, query generation, classification | M query modules |
| **@semantic** | Semantic model (TMDL), relationships, RLS | Semantic model generators |
| **@visual** | Report layout, visual containers, filters | Report/visual generators |
| **@generator** | Cross-cutting generation coordination | Delegates to Semantic, Visual, and Fabric; no blanket module ownership |
| **@fabric** | Local Fabric artifacts: Lakehouse, Dataflow Gen2, Notebook, Direct Lake, Pipeline | `fabric_project_generator.py`, its five sub-generators, `fabric_constants.py`, `fabric_naming.py` |
| **@agent-tools** (`AgentTools`) | Local MCP tools, protocol, write guards, workspace launch | `powerbi_import/mcp_server.py`, `.vscode/mcp.json` |
| **@assessor** | Migration readiness, scoring, strategy, validation | Assessment modules |
| **Evidence** | Deterministic quality/comparison reports and fidelity evidence | `migration_quality.py`, report/comparison/equivalence/regression modules |
| **Healing** | Bounded repairs and recovery ledger | `recovery_report.py`; repair-only collaboration with Semantic/Assessor |
| **AI** | Optional LLM advisory and migration patterns | `llm_client.py`, `marketplace.py`; not MCP transport |
| **Web Designer** | HTML presentation, theme, readability, accessibility | `html_template.py`; presentation-only collaboration with report owners |
| **@merger** | Shared model, multi-source merge | Merge modules |
| **@deployer** | Deployment, auth, gateway, telemetry | Deployment modules |
| **@reviewer** | Read-only artifact review and coaching | No implementation files; returns findings to the coordinator |
| **@tester** | Tests, coverage, fixtures, regression | `tests/` |
| **Documentation Guardian** | Pre/post-update claims, links, counts, docs gate | Documentation only; source defects go to the owning specialist |
| **Roadmap Planner** | Priorities, dependency sequencing, measurable exit gates | `docs/DEVELOPMENT_PLAN.md`; no generator code |

## Reference Adaptation

| TableauToPowerBI Role | BO Role | Adaptation |
|----------------------|---------|------------|
| Tableau | BusinessObjects | BO CMS client, not Tableau Server/Cloud, GraphQL, Hyper, or Prep |
| DAX | Dax | Preserve the existing BO name and formula converter |
| AI | AI + existing AgentTools | Separate advisory/provider work from the six-tool local MCP protocol |
| Evidence | Evidence | Existing BO quality/fidelity/comparison modules; no invented parity registry |
| Healing | Healing | Existing recovery/repair surfaces; no claim of rollback or Desktop probes |
| Documentation Guardian | Documentation Guardian | BO docs and existing development plan, not a new roadmap |
| Roadmap Planner | Roadmap Planner | BO scope, dependencies, and evidence-based increments |
| Web Designer | Web Designer | Existing HTML reports, not a nonexistent local browser app |

All other reference specialist roles retain their BO implementation scope.
Converter and Generator remain BO coordination layers. Azure application-scaffold
agent bundles from the reference are not migration-engine roles and are not
copied as part of this adaptation. No global/profile customization is changed.

## Skills And MCP Routing

Start migrations with [the BO skill](../.github/skills/bo-to-powerbi/SKILL.md).
For platform work, load [the Fabric/MCP routing skill](../.github/skills/fabric-mcp-routing/SKILL.md),
then the installed workload skill (`semantic-model-authoring`, `powerbi-report-cli`,
`dataflows-cli`, `spark-cli`, or the other task-specific skill).
See [setup and verification](FABRIC_MCP_SETUP.md) for external prerequisites.

**Generator** coordinates Semantic, Visual, and Fabric; it does not own every file
in `powerbi_import/`. **Fabric** owns local Fabric artifact generation, while
**Deployer** owns authorized remote delivery. Local file extraction stays with
Extractor; the CMS client belongs to BusinessObjects.
**AgentTools** owns the six-tool local MCP surface; **Evidence** owns the unified
local quality report. The MCP server does not invoke Copilot agents: handoffs
return findings for an external operator/agent to act on.
Coordinators enable the `agent` tool and use exact frontmatter names such as
`Dax`, `Semantic`, and `Fabric`, not their lowercase documentation shorthand.
Specialists without delegation tools return out-of-scope recommendations to the coordinator.
Reviewer has no edit or execution tools and returns findings instead of applying fixes.

Copilot agent roles are development workflows, not runtime stages invoked by the
CLI. Generated artifacts, passing tests, Desktop rendering, refresh, and Fabric
Pipeline completion are separate evidence levels. Remote checks require an
authorized target and explicit confirmation for writes; otherwise they remain `not_run`.

## Core Pipeline Diagram

This diagram shows the original migration spine. The complete specialist,
governance, server, evidence, and presentation roles are listed above; the diagram
does not imply automatic runtime agent execution.

```
                        ┌──────────────┐
                        │ Orchestrator │  ← CLI entry, pipeline coordination
                        └──────┬───────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
        ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
        │ Extractor  │   │ Converter │   │ Generator  │
        │(BusinessObjects parse)│  │ (coord.)  │   │ (coord.)   │
        └──────┬─────┘   └─────┬─────┘   └─────┬──────┘
               │          ┌────┴────┐     ┌─────┴──────┐
               │          │         │     │            │
               │     ┌────▼───┐ ┌───▼───┐ ┌▼────────┐ ┌▼──────┐
               │     │  DAX   │ │Wiring │ │Semantic │ │Visual │
               │     │(formula)│ │(DAX↔M)│ │(model)  │ │(report)│
               │     └────────┘ └───────┘ └─────────┘ └───────┘
               │                              │
               │        ┌────────────────┬────┴────┐
               │        │                │         │
               │  ┌─────▼─────┐   ┌─────▼───┐  ┌──▼─────┐
               │  │  Assessor  │   │ Merger  │  │Deployer│
               │  │ (Analysis) │   │ (Merge) │  │(Deploy)│
               │  └────────────┘   └─────────┘  └────────┘
               │
              ┌┴───────────────────────────────────────────┐
              │                 Reviewer                    │
              │    (Preceptorship loop — reviews artifacts  │
              │     from Semantic + Visual + DAX + Wiring)  │
              └────────────────────────────────────────────┘

              ┌────────────────────────────────────────────┐
              │                  Tester                     │
              │    (Cross-cutting — reads all, writes       │
              │     only to tests/)    │
              └────────────────────────────────────────────┘
```

## The Preceptorship Loop

The recommended agent review workflow uses a **quality gate** before artifacts
are finalized. This is not a claim that the CLI automatically invokes Reviewer:

```
DRAFT (Agent)  ──→  REVIEW (@reviewer)  ──→  APPROVE? (≥ 4★?)
     ↑                                           │
     │                  YES ─────────────────────→ DONE (artifacts ready)
     │                   NO ─────────────────────→ COACH (structured feedback)
     │                                                │
     └────────────────────────────────────────────────┘
                       (max 3 cycles, then escalate)
```

### Review Dimensions (5-star scoring)

| Dimension | What @reviewer Checks |
|-----------|----------------------|
| **Completeness** | All source objects have corresponding output |
| **Formula Correctness** | Valid syntax, correct conversion from BusinessObjects formulas |
| **Query Validity** | Proper quoting, valid expressions |
| **Model Structure** | Valid relationships, proper cardinality |
| **Report Fidelity** | Visual types mapped correctly, filters at right level |

### Scoring Rules

- **≥ 4★ average** across all dimensions → **APPROVE**
- **< 4★ average** → **COACH** — @reviewer provides specific feedback per dimension
- **After 3 failed cycles** → **ESCALATE** to user
