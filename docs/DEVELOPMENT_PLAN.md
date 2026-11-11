# Development Plan — BO to Power BI Migration

> **Last reviewed**: 2026-10-28
> The March 2026 version 3.0 plan is retained below as historical planning evidence,
> not a current release or a certification that every phase exit criterion passed.

## Current Evidence - 2026-10-28

- Full local suite: `python -m pytest tests/ --tb=short -o addopts="" -q`:
        **419 passed, 242 subtests passed**. Coverage/hosted CI was not measured by this run.
- 22 specialist development roles with an ownership contract; not runtime CLI stages.
- Local assessment, dry-run, file/batch/BIAR/shared generation, six-tool guarded
        MCP, and PBIP/Fabric quality reporting are exercised by local tests.
- Forced eFashion/HR shared generation: 11 Fabric ingestion tables, quality WARN,
        exit 0; PBIP emits a model and two thin-report descriptors. Without explicit
        force approval this low-overlap pair is declined. Distinct same-named source
        queries still reject instead of merging unsafely.
- Direct Lake source entities, unique ingestion ownership, physical metadata
        retention, and unsupported-semantics findings are local artifact contracts.
- Desktop opening/rendering, semantic equivalence, deployed refresh, and Fabric
        execution remain `not_run`; historical phase completion labels do not waive them.

### Open Gates And Owners

| Priority | Status | Gate | Owner |
|----------|--------|------|-------|
| P1 | Open | Redact source-embedded credentials before persistence; prove with export regression tests. Current output can contain secrets. | Extractor |
| P1 | Open | Server assessment/dry-run must not download/extract unexpectedly; wire portfolio assessment and generation or reject unsupported flag combinations. | Orchestrator / BusinessObjects / Assessor |
| P1 | Open | Wire or reject shared deployment flags; propagate remote failures rather than equating local exit 0 with publication. | Orchestrator / Deployer |
| P2 | Open | Explicit source-qualified mapping for ambiguous shared queries; never bypass identity checks with force-merge. | Merger |
| P2 | Open | Prove sample generation and any planned staging/production gates in CI; current final job checks only help. | Tester / Deployer |
| P2 | Not run | Validate clean-environment developer installation, Desktop rendering, refresh, security semantics, and deployed workload execution in approved environments. | Tester / Semantic / Visual / Deployer |

See [current gaps](GAP_ANALYSIS.md), [workflow boundaries](ENTERPRISE_GUIDE.md),
and [unreleased changes](../CHANGELOG.md). Keep this document canonical; do not
copy Tableau release numbers or create a competing roadmap.

## Separate roadmap: SAP BW/BW/4HANA to Fabric and BW retirement

**Planning baseline, 2026-11-10; local BW-1 and limited BW-2 slices added
2026-11-11.** Remaining capabilities and runtime validation are planned.
This is a distinct source migration and retirement program, not an extension of
the BO extraction contract or a claim that the BO pipeline migrates BW. The
historical SAP BW plugin entry below is a limited idea, not this program or
evidence of delivery. The existing BO backlog and gates remain unchanged.

### Evidence, boundary and decision rules

- The concrete source-feature gap is end-to-end BW retirement: no evidence in
  the current plan or gap analysis establishes BW inventory, historical
  extraction, direct upstream replacement, BEx conversion, or retirement.
  `bo_export/m_query_builder.py` contains a `sap_bw` M connector template;
  `powerbi_import/assessment.py` classifies it as partial, with a corresponding
  local test in `tests/test_assessment.py`. That is not BW metadata extraction
  or a retirement path. `GAP_ANALYSIS.md` lists BW OLAP universes as unsupported
  and suggests a direct BW connector; it is at best a transitional dependency
  on BW, not a way to turn BW off. Existing Fabric artifact checks are local BO
  evidence only, not evidence of BW behavior in Fabric.
- Outcome: for an **approved, bounded BW estate**, reproduce agreed data,
  semantics, security, planning and operational obligations in accepted target
  services; switch all in-scope consumers to independently sustained upstream
  feeds; then retire BW only after explicit business, technical and compliance
  approval. Full retirement is blocked by any unaddressed dependency, including
  consumers, source feeds, write-back, audit and retention obligations.
- Falsifiable program hypothesis: a representative vertical slice can capture
  its BW dependencies and semantics, reconcile a frozen historical baseline,
  continue from independently sourced incremental changes, and serve authorized
  consumers within agreed tolerances without querying BW. A missing dependency,
  irreconcilable result, or unproven incremental handoff falsifies the slice;
  no object-count or static-artifact score overrides that result.
- Priorities below order risk reduction, not calendar commitments. **P0** is a
  prerequisite for a credible scope; **P1** proves a representative end-to-end
  slice; **P2** expands by wave; **P3** authorizes transition and retirement.
  Inventory, governance and security start early and are refined each wave.
- The source-of-truth boundary is a **new, versioned BW source contract**,
  separate from BO's 15 raw collections and `converted_objects`. Define its
  own schema, versioning, lineage, provenance, redaction, unsupported features
  and evolution rules. Any explicit adapter to shared target generators must
  preserve both contracts and existing BO behavior; it cannot silently coerce
  BW semantics into BO defaults. `Assessor` is the assigned owner in
  `ownership.json` of the draft inventory schema, synthetic fixture and local
  offline contract module. This ownership does not imply ownership of live
  SAP/BW discovery, SAP connectivity or durable upstream-feed components;
  those remain **unassigned**. Assign owners and update that contract before
  implementing those components. `BusinessObjects` owns BO CMS, not SAP BW
  connectivity; `Extractor` is a proposed local parsing collaborator, not an
  implicit owner of live BW access.
- The customer program must designate a BW/source-system owner, business data
  owners, security/privacy and retention authorities, and operations and
  application owners. Repository role names below are implementation
  coordinators/collaborators, not substitutes for those approvals. Unsupported
  or unknown behavior is recorded and blocks the relevant gate; manual
  replacements require owners and acceptance evidence.
- The [BW-to-Fabric design](SAP_BW_TO_FABRIC_DESIGN.md) is an input to review,
  not evidence of delivered capability. This roadmap does not prescribe an
  unverified SAP connector, entitlement, licensing position, API, or Fabric workload. Select
  supported extraction and upstream patterns per source and version with SAP
  and Microsoft documentation, source owners and explicit authorization.

### Increment BW-0 — inventory and scope (P0)

- **Outcome:** a complete, reviewable baseline of the scoped estate and its
  upstream/downstream dependencies, including a retirement disposition.
- **Evidence / hypothesis:** BO assessment and BW connector labels are not a BW
  inventory. Hypothesis: source-owner exports and usage evidence can be joined
  to a dependency graph without inferring identity from names.
- **First change and scope:** `Assessor` coordinates an inventory schema and
  one representative, read-only fixture; proposed BW source owner plus
  `Extractor` provide local input parsing. Include systems/versions, clients,
  InfoProviders/ADSOs, transformations, process chains, sources and delta
  mechanisms, BEx queries, consumers and schedules, data volumes/retention,
  authorizations, planning/write-back, owners and criticality. Distinguish
  observed, inferred and unknown relationships; record extraction permissions.
  Live SAP discovery ownership and interfaces must be agreed first.
- **Dependencies:** approved scope, source-owner-provided metadata and access;
  BW source ownership decision. No remote scan is implied.
- **Validation / exit:** fixture covers one connected chain and an orphan or
  unknown consumer; identifiers and lineage remain stable and unknowns visible.
  For each wave, reconcile the inventory against source-owner baselines; 100%
  of in-scope objects and known consumers have owner and disposition or a
  documented blocker. Agree freshness and usage-observation windows with
  owners before closure; sign off coverage rather than infer it from counts.
- **Risks / non-goals:** stale metadata and unobserved periodic consumers;
  no source changes, deployment or assumption that inactive means disposable.
- **Local increment delivered (2026-11-11):** Assessor owns a draft snapshot
  schema and synthetic partial fixture in `docs/schemas/` and `docs/fixtures/`.
  The schema explicitly captures discovery method, extraction-access status,
  scope coverage, object location/owner/criticality, usage windows, volume and
  history/retention, delta/delete behavior, and preliminary migration
  disposition. It is a minimal draft, not the full BW-1 source/evidence
  contract. The fixture leaves customer-dependent measures unknown, shows an
  observed dependency chain and an unresolved orphan candidate without
  inventing edges, and contains no customer data. No SAP export parser, live discovery,
  owner attestation, source baseline, completeness proof, or retirement
  disposition has been delivered; the BW-0 exit gate remains open. The
  `assess_bw0` function and `migrate_bw_assess.py` now report declared coverage,
  ownership, unknowns, and unresolved edges as blockers or review items. A
  `candidate_for_owner_review` is not an exit approval; live SAP discovery,
  source-owner evidence and attestation remain `not_run`.

### Increment BW-1 — isolated source contract and assessment (P0; local contract slice delivered)

- **Outcome:** loss-aware BW metadata and evidence contract, independently
  versioned and testable without BO input.
- **Evidence / hypothesis:** the existing BO adapter is BO-specific. Hypothesis:
  a source-neutral boundary with explicit BW types can preserve a small BW
  graph and round-trip unsupported semantics without changing BO output.
- **First change and scope:** the assigned `Assessor` owner delivered the
  offline contract module `powerbi_import/bw_inventory.py`, schema
  `docs/schemas/sap_bw_inventory.schema.json`, and sanitized synthetic partial
  fixture `docs/fixtures/sap_bw_inventory.partial.example.json`. The module
  sanitizes/redacts, validates, and loads local JSON snapshots under schema
  **1.0**; it deterministically upgrades the documented draft **0.1 → 1.0**,
  retaining known fields and marking absent information unknown or
  not-assessed rather than inferring it. Local checks cover version/malformed
  input rejection, Unicode identifiers and dependency lineage, credential
  redaction, and unsupported-feature findings. `Extractor` remains a proposed
  collaborator on future local parsing; `Assessor` owns this contract and
  readiness/blocker work. `Orchestrator` owns the separate local BW-2 CLI below;
  broader BW pipeline dispatch remains future work. `Fabric`, `Semantic` and
  `Evidence` may review consumer requirements.
- **Dependencies:** BW-0 representative metadata and source owner; design
  review and compatibility/version policy remain program dependencies. The
  local module was validated against a synthetic partial snapshot; this does
  not close BW-0 or substitute for source-owner evidence.
- **Validation / local exit evidence (2026-11-11):** `pytest
  tests/test_bw_inventory_contract.py --tb=short -q` — **8 passed**;
  `pytest tests/test_e2e_pipeline.py tests/test_crystal_pipeline.py
  tests/test_shared_model.py --tb=short -q` — **79 passed**;
  `python -m pytest tests\ --tb=short -q` — **exit 0** (full suite);
  `git diff --check` — **OK**. These are local contract/regression checks,
  not runtime evidence. Unsupported features remain findings and cannot be
  represented as converted or passing.
- **Limitations / remaining gate:** BW-0 remains open: there is no complete
  source-owner inventory, attestation, authoritative baseline, coverage proof
  or retirement disposition. BW-1 itself performs no SAP/Fabric scan, live
  parsing, BW conversion, target generation, source-to-target reconciliation
  or retirement. The separate BW-2 slice below generates a local notebook only;
  runtime checks remain `not_run`. BW-1 is not BW readiness assessment or
  end-to-end BW-1 completion.
- **Risks / non-goals:** lossy type or identity normalization; no direct
  import into the BO contract, no claims of live extraction, conversion,
  parity or retirement.

### Increment BW-2 — frozen history and reconciled landing (P1)

- **Outcome:** reproducible extraction and loading of the agreed historical
  horizon, separately from future direct-source feeds.
- **Evidence / hypothesis:** the M template does not demonstrate historical
  extraction, snapshot consistency or Fabric loading. Hypothesis: an approved
  snapshot with source-side controls can land one provider and reconcile at its
  business grain, including changes and deleted records where applicable.
- **First change and scope:** proposed BW source owner specifies a supported,
  authorized extraction method for one provider; `Extractor` handles only
  agreed local metadata/file parsing; `Fabric` designs a local landing artifact
  slice with lineage, partitioning and replay metadata. `Evidence` specifies
  independent source/target controls. Record snapshot watermark/time zone,
  fiscal calendar, keys, units/currency, duplicates, nulls, history/SCD,
  deletion and late-arrival handling, and privacy/retention requirements.
- **Dependencies:** BW-0/1, source snapshot and access permissions, target
  design, business-approved history horizon and source extraction capacity.
- **Validation / exit:** synthetic fixtures exercise replay, duplicates, empty
  partitions and failure recovery; source/target row and distinct-key counts,
  totals by period and relevant dimensions, and sampled records reconcile at
  agreed tolerances and snapshot boundary. Exceptions have owned dispositions;
  no unexplained differences at gate. Authorized source and Fabric execution
  are separate evidence and otherwise `not_run`.
- **Risks / non-goals:** source load, restricted access, incompatible snapshot
  or unavailable history; a successful snapshot is not a sustainable feed.
- **Local slice delivered (2026-11-11):** `migrate_bw.py` and
  `powerbi_import/bw_bronze_generator.py` take the BW 1.0 inventory plus a
  separate explicit plan and generate one unbound notebook for an observed,
  in-scope, unblocked provider. It reads specified pre-staged Parquet files,
  checks each declared schema and the declared total, preserves rows and
  lineage metadata in the generated logic, and requests creation of a new Delta
  table with `errorifexists`. Existing targets are refused; automatic replay,
  partition management and cleanup are not implemented. The synthetic plan
  does not include Parquet data. Local tests exercise generation, CLI safety
  and simulated notebook branches, including duplicate/empty input and write
  failures; the full pytest suite exits 0. No Spark/Delta or Fabric runtime,
  source-side reconciliation, SAP extraction or customer approval has been
  performed. A declared count is not evidence that the BW export is complete.
  A separate offline comparator now evaluates supplied source/target controls
  under an explicit snapshot scope and per-metric rules. It does not collect or
  attest to measurements, sample rows, execute on SAP/Fabric, or establish
  business acceptance. This partial slice does not close BW-0 or the BW-2 exit
  gate. Focused comparator and CLI tests, the agent ownership contract, the
  full `python -m pytest tests\ --tb=short -q` suite, and `git diff --check`
  pass locally; these remain static/test evidence only.

### Increment BW-3 — durable direct upstream feeds and handoff (P1)

- **Outcome:** continuously maintained target data after the snapshot, without
  a production dependency on BW.
- **Evidence / hypothesis:** querying BW is transitional only. Hypothesis: for
  one selected source, a supported direct upstream feed plus a controlled
  snapshot-to-delta handoff reproduces inserts, updates and deletes without gaps
  or duplicates and can recover after interruption.
- **First change and scope:** source-system owner and newly assigned integration
  owner select and document a supported source-specific interface, permissions,
  subscription/CDC semantics and operational limits; `Fabric` plans the target
  ingestion artifact, `Deployer` only authorized bindings/operations, and
  `Evidence` the handoff proof. Specify cutover watermark, overlap/deduplication,
  ordering, replay, deletes, schema drift and monitoring. Source systems may
  include SAP and non-SAP; interfaces and availability are to be verified.
- **Dependencies:** BW-2 snapshot controls, BW-0 upstream lineage, source-system
  access and business-approved latency, recovery and retention objectives.
- **Validation / exit:** synthetic snapshot-plus-delta tests cover overlap,
  gaps, out-of-order and late changes, duplicates, delete, restart and drift;
  authorized integration must demonstrate these against the chosen source and
  target. Reconcile the handoff and demonstrate operation with BW unavailable;
  agree measurable freshness, RPO/RTO and reconciliation thresholds before
  running. No BW connector or BW-managed delta queue may remain a hidden
  steady-state dependency.
- **Risks / non-goals:** upstream data may not contain BW-only enrichments,
  history, deletes or licensed interfaces; no claim that a particular CDC
  technology is supported until verified.
- **Local slice delivered (2026-11-11):** `migrate_bw_handoff.py` and
  `powerbi_import/bw_handoff.py` evaluate a synthetic, normalized feed with an
  explicit contiguous-integer position contract. The local evaluator exercises
  snapshot overlap, duplicate replay, out-of-order and late events, deletes,
  sequence gaps, schema drift, deterministic re-evaluation and final-state
  comparison. It rejects conflicting event IDs/positions and records source
  extraction, Fabric execution, business approval and BW-unavailable operation
  as `not_run`. The sample proves only local evaluator behavior; source owners
  have not established that an actual feed offers these semantics. This does
  not close BW-0/2/3, provide a connector or durable checkpoint, or establish
  production recovery, feed freshness, Fabric operation, or BW independence.

### Increment BW-4 — transformation and ABAP semantics (P1, then P2)

- **Outcome:** lineage-backed recreation of the selected transformation chain
  with explicit handling of ABAP routines and unsupported semantics.
- **Evidence / hypothesis:** no BW/ABAP conversion is established by the BO
  DAX/M converters. Hypothesis: one bounded deterministic routine can be
  reimplemented from approved source and test vectors without assuming ABAP
  and Spark/SQL semantics are identical.
- **First change and scope:** proposed BW source owner inventories routine
  versions and inputs/outputs; `Fabric` builds a local target transformation
  slice, with `Wiring` and `Dax` only where their actual M/DAX ownership
  applies. Classify start/end/expert and field routines, lookup dependencies,
  state, errors and side effects; use manual redesign or explicit blockers for
  dynamic code, external calls or unsupported behavior, not invented output.
- **Dependencies:** BW-1 contract, BW-2 baseline and BW-3 source mapping;
  approved access to code and business test cases.
- **Validation / exit:** golden input/output cases compare source and target,
  including nulls, types, rounding, date/fiscal logic, ordering, duplicates,
  lookups and failure paths. Reconcile all critical calculations at agreed
  tolerances; every routine is converted with evidence, manually accepted or
  blocks the wave. Generator errors are fixed at source, not hidden by metrics.
- **Risks / non-goals:** side effects and undocumented dependencies; no promise
  of automatic or complete ABAP translation.
- **Local slice delivered (2026-11-11):** `migrate_bw_transform_validate.py`
  and `powerbi_import/bw_transform_validation.py` compare supplied expected
  outputs and target outputs for explicit vectors, with exact type/value checks
  or declared decimal tolerances. The synthetic suite covers rounding, nulls,
  missing/extra fields and mismatches. It neither parses ABAP nor executes
  either the source routine or a target transformation; source vector
  provenance, target runtime, semantic equivalence and business acceptance
  remain `not_run`. This does not close BW-4 or provide an automatic converter.

### Increment BW-5 — BEx semantics and consumer replacement (P1, then P2)

- **Outcome:** replace selected BEx/OLAP consumer behavior with accepted target
  models and reports, without treating connectivity as semantic migration.
- **Evidence / hypothesis:** BW OLAP universes are listed as unsupported; no
  BEx converter is evidenced. Hypothesis: a query with agreed restrictions,
  variables and hierarchy can be recreated and independently reconciled.
- **First change and scope:** source owner supplies one BEx query definition
  and result vectors; `Semantic` owns target model design, `Dax` formulas,
  `Visual` report behavior where applicable, `Evidence` comparisons, and
  `Extractor` local parsing of an approved fixture. Inventory variables,
  filters, hierarchies, key figures, exception aggregation, units/currencies,
  time-dependent master data, prompts and authorization context.
- **Dependencies:** BW-1, BW-2 and BW-4; BW-3 before retirement; business
  owners and representative consumers.
- **Validation / exit:** compare query results by role, prompt, hierarchy level,
  period and aggregation at agreed tolerances, including edge cases and
  performance budgets agreed per query. Consumers accept replacement and
  lineage; each unmapped semantic or consumer is an explicit wave blocker.
  Desktop/Service rendering and refresh are `not_run` until actually tested.
- **Risks / non-goals:** totals, exception aggregation and authorization can
  differ despite matching detail rows; no blanket claim of BEx parity.
- **Local slice delivered (2026-11-11):** the separate versioned BEx semantic
  contract, synthetic partial example and `migrate_bw_bex_assess.py` capture
  declarations for variables/prompts, filters, hierarchies, master-data
  validity, key-figure aggregation, exception aggregation, units/currencies,
  authorization contexts and inventory-linked consumers. The local report
  flags incomplete or unknown semantics, unresolved query-to-consumer coverage
  and BW inventory BEx blockers; an open BW-0 inventory review also blocks
  the BW-5 candidate. It does not parse a BW query, generate a target
  model/report, execute source or target queries, compare result vectors,
  measure performance, or establish consumer acceptance; those checks remain
  `not_run`. The sample is synthetic, and this slice does not close BW-5 or
  authorize retirement.

### Increment BW-6 — security, planning and compliance (P1, then P2)

#### Local slice delivered

- `powerbi_import/bw_controls_assessment.py` and
  `migrate_bw_controls_assess.py` provide an offline controls manifest
  assessment. It captures inventory-linked authorization contexts and declared
  allow/deny scenarios whose `execution_status` is fixed to `not_run`; BW
  planning/write-back dispositions and coverage for write-back, locking,
  approvals, separation of duties, audit and recovery; and audit, retention,
  privacy and legal-hold obligations. The versioned [controls schema](schemas/sap_bw_controls.schema.json)
  and synthetic partial [example](fixtures/sap_bw_controls.partial.example.json)
  define the offline declaration contract.
- Validation is limited to local declarations and source-inventory references.
  It does not execute target access tests, verify runtime identity/binding, run
  planning/write-back, certify compliance, close a gate or authorize retirement.
  `candidate_for_owner_review` is not acceptance; `gate_closed` remains `false`.
  All unperformed runtime evidence, including SAP BW and Fabric runtime checks,
  remains `not_run`.
- **Focused validation (2026-11-11):**
  `pytest tests/test_bw_controls_assessment.py --tb=short -q -o addopts=''`
  passed 10 tests and 6 subtests. This is focused validation, not the full suite.

- **Outcome:** accepted replacement of data access, planning and compliance
  obligations, or a documented retirement blocker.
- **Evidence / hypothesis:** local BO security or model artifacts do not prove
  BW analysis authorization equivalence or planning/write-back capability.
  Hypothesis: one role and one planning process can be mapped to an approved
  target control/workflow and tested for both permitted and denied actions.
- **First change and scope:** security and business owners inventory BW
  analysis authorizations, identities, row/column restrictions, separation of
  duties, planning functions, locks, write-back, audit and retention.
  `Semantic` designs applicable model restrictions; `Deployer` coordinates
  authorized identity/binding controls; `Evidence` captures results. Planning
  replacement product and responsible owner are **to be decided**; do not
  assume a Fabric semantic model provides transactional planning/write-back.
- **Dependencies:** BW-0/1, BW-5 semantics, identity and privacy design,
  chosen planning solution and regulatory decisions.
- **Validation / exit:** role-by-data positive and negative access matrix,
  impersonation/identity checks and leak tests; planning scenario tests include
  concurrency, locks, approvals, write-back and recovery where applicable.
  Security, business and compliance owners sign off coverage and retained
  records; missing controls or undecided planning block retirement.
- **Risks / non-goals:** overprivilege, lost audit/retention and unsupported
  write-back; local RLS definitions are not deployed security proof.

### Increment BW-7 — reconciliation, operations and scaled waves (P2)

- **Outcome:** independently auditable functional and operational acceptance
  for each wave, not a single aggregate parity score.
- **Evidence / hypothesis:** existing BO quality reports are local checks, not
  BW runtime equivalence. Hypothesis: independent controls at snapshot, delta,
  transformation and consumer layers expose loss and semantic discrepancies.
- **Local slice delivered — 2026-11-11:** `powerbi_import/bw_wave_evidence_index.py`
  and `migrate_bw_wave_assess.py` index per-object BW-2..6 references/statuses,
  explicit applicability, traceability, wave operational checks and exceptions.
  The index gates on BW-0 and applicable `not_run`/`fail` evidence or unresolved
  exceptions; `candidate_for_owner_review` never closes the gate. See the
  [schema](schemas/sap_bw_wave_evidence.schema.json) and
  [partial example](fixtures/sap_bw_wave_evidence.partial.example.json).
  It preserves declarations but does not dereference or verify report bytes,
  freshness/correctness, SAP/Fabric runtime, operations certification or
  retirement. Focused validation: `pytest tests/test_bw_wave_evidence_index.py --tb=short -q -o addopts=''`
  passed 9 tests and 3 subtests on 2026-11-11.
- **First change and scope:** `Evidence` defines a per-object control ledger:
  source/target versions, extract boundaries, grain, counts, totals, sampled
  rows, query results, authorization cases, exceptions and approvals.
  `Fabric` designs operational artifacts; `Deployer` coordinates authorized
  scheduling, alerts, access, capacity, backup/restore and runbooks.
  `Assessor` prioritizes subsequent waves by criticality and dependencies.
- **Dependencies:** BW-2 through BW-6 for the wave; agreed data-quality,
  performance, freshness, availability, cost, recovery and retention targets.
- **Validation / exit:** repeatable independent reconciliations with agreed
  per-measure absolute/relative tolerances and ownership for exceptions; zero
  unexplained critical discrepancies; failure, replay, drift, alerting and
  restore drills meet agreed RPO/RTO and latency. Record evidence per layer and
  consumer; unrun runtime checks and open operational risks remain visible.
- **Risks / non-goals:** counts can match while amounts, access or semantics
  differ; no waiver by lowering a fidelity metric or ignoring missing records.

### Increment BW-8 — cutover and controlled retirement (P3)

- **Outcome:** switch the approved estate, demonstrate independent operation,
  then retire BW under separately authorized change control.
- **Evidence / hypothesis:** no cutover or retirement is established by local
  generation. Hypothesis: consumers and feeds remain correct and recoverable
  during an agreed parallel-run and a BW-independent observation period.
- **First change and scope:** `Orchestrator` coordinates a wave runbook with
  `Evidence`, `Fabric`, `Deployer` and named customer owners: freeze and
  watermarks, parallel run, consumer switching, communications, go/no-go,
  rollback triggers and time limit, escalation and post-cutover monitoring.
  Maintain an explicit register of BO and non-BO consumers, upstream queues,
  jobs, accounts, integrations and retained audit/legal records.
- **Dependencies:** all BW-0 through BW-7 wave gates; every consumer and
  upstream dependency migrated or dispositioned, planning and retention signed
  off, operational ownership and rollback funded. Enterprise retirement follows
  completion of all waves, not just the pilot.
- **Validation / exit:** agree and record parallel-run duration, observation
  window, reconciliation thresholds and rollback/recovery objectives before
  cutover. Exercise rollback before the irreversible step; verify consumers,
  feeds and controls while BW is unavailable. Business, source, security,
  compliance and operations owners explicitly approve go/no-go and separately
  approve decommission; preserve required archives and demonstrate restore.
  Verify no remaining live dependencies and record deactivation evidence.
- **Risks / non-goals:** rollback may become impossible after source shutdown
  or data divergence; no implicit cloud writes, switch, deletion, license
  cancellation or release approval follows from this roadmap.

### Cross-cutting validation and evidence gates

- Each increment starts with a minimal synthetic fixture and focused local
  tests for its contract, failure paths and compatibility. Future implementation
  requires its owning specialist and `Tester` to run focused tests plus
  `python -m pytest tests/ --tb=short -q`; report commands, results and any
  failures. Preserve the existing BO suites and do not weaken assertions.
- Test coverage, object counts and generated artifacts are not proof of
  completeness, semantic equivalence, security, recoverability or retirement
  readiness. Store evidence and exception dispositions per source, version,
  wave, layer and consumer; business owners agree thresholds before execution.
- **Fabric runtime: `not_run`** for BW ingestion, authentication/binding,
  orchestration, transformations, semantic refresh/query, security, recovery
  and cutover. SAP source access/extraction, upstream CDC, Desktop/Service
  rendering, operational drills and BW shutdown are also **`not_run`**.
  Only an explicitly authorized target and performed check can change a status;
  local static validation and existing BO tests cannot do so.

## Historical State Assessment - 2026-03-26

The remaining reuse analysis and sprint roadmap are the original planning
snapshot. `COMPLETE` labels and exit criteria below describe that snapshot's
claims or goals, not newly verified runtime evidence. Consult the current gates above.

### Historically Reported Complete: Phases 1–5 (Sprints 1–33)

| Metric | Value |
|--------|-------|
| Python files | 95 (72 powerbi_import + 13 bo_export + 10 tests) |
| Total LOC | ~50,450 |
| Tests | 244 (243 passing) |
| BO formula → DAX mappings | 150+ |
| Power Query M connectors | 15+ |
| Example artifacts | 11 (3 WebI, 2 Crystal, 2 UNX, 1 UNV, 1 Lumira, 1 BIAR, 1 config) |

### Project Modules

| Module | LOC | Status | Notes |
|--------|-----|--------|-------|
| `migrate.py` | ~350 | **COMPLETE** | CLI routes to 5 extraction modes + generation + assess + deploy |
| `generate_report.py` | ~470 | **COMPLETE** | Batch migration + rich HTML report (Fluent/PBI design) |
| `bo_export/extract_bo_data.py` | ~250 | **COMPLETE** | Orchestrator → 15 JSON files |
| `bo_export/webi_extractor.py` | ~400 | **COMPLETE** | 14 sub-extractors, ZIP+XML, XXE-safe |
| `bo_export/crystal_extractor.py` | ~300 | **COMPLETE** | Groups, sorts, charts, subreports, conditional formatting |
| `bo_export/universe_extractor.py` | ~350 | **COMPLETE** | UNX+UNV, business layer, joins, contexts |
| `bo_export/lumira_extractor.py` | ~200 | **COMPLETE** | Discovery+Designer, JSON/XML |
| `bo_export/biar_reader.py` | ~150 | **COMPLETE** | ZIP slip defense, manifest parsing |
| `bo_export/dax_converter.py` | ~400 | **COMPLETE** | 150+ mappings, 87% coverage (107/123) |
| `bo_export/m_query_builder.py` | ~300 | **COMPLETE** | 15 connectors, 13 transforms |
| `bo_export/server_client.py` | ~350 | **COMPLETE** | 13 REST endpoints, stdlib only |
| `bo_export/converted_objects_adapter.py` | ~200 | **COMPLETE** | Bridge: 15 JSON types → converted_objects (17 keys) |
| `powerbi_import/` (72 files) | ~40,000 | **COMPLETE** | Full generation layer (TMDL, PBIR, visuals, deploy, Fabric) |
| `tests/` (10 files) | ~3,500 | **COMPLETE** | 244 tests covering all phases |

---

## Reuse Analysis: TableauToPowerBI → BOToPowerBI

**Source**: `../TableauToPowerBI/powerbi_import/` — 72 modules, 35,279 LOC

### Reuse Tiers

| Tier | Modules | LOC | Effort | Action |
|------|---------|-----|--------|--------|
| **Copy as-is** (source-agnostic) | 33 | ~10,200 | Zero | `deploy/`, `html_template`, `governance`, `dax_optimizer`, `dax_recipes`, `monitoring`, `plugins`, `progress`, `incremental`, `permission_mapper`, `thin_report_generator`, `merge_assessment`, `merge_config`, `merge_report_html`, `regression_suite`, `equivalence_tester`, `sla_tracker`, `recovery_report` |
| **Light adaptation** (rename/config) | 27 | ~12,500 | Low | `visual_generator`, `m_query_generator`, `shared_model`, `strategy_advisor`, `server_assessment`, `global_assessment`, `validator`, `security_validator`, `telemetry`, `schema_drift`, `wizard`, `fabric_*` generators, `alerts_generator`, `refresh_generator`, `llm_client` |
| **Heavy adaptation** (core logic) | 10 | ~12,600 | High | `tmdl_generator`, `pbip_generator`, `import_to_powerbi`, `assessment`, `comparison_report`, `visual_diff`, `migration_report`, `notebook_api`, `api_server`, `calc_column_utils` |

### Key Adaptation Work

**`tmdl_generator.py`** (4,774 LOC): Replace `tableau_export.datasource_extractor` imports → `bo_export.dax_converter` + `bo_export.m_query_builder`. Remove Tableau derivation-prefix regex. Core TMDL writing (80%) is source-agnostic.

**`pbip_generator.py`** (4,040 LOC): Remove Tableau shelf-aggregation prefix regex. Replace field-name cleaning functions. 80% of PBIR/visual JSON generation is reusable.

**`import_to_powerbi.py`** (484 LOC): Change source_dir from `tableau_export/` → `bo_export/`. Build mapping from BO's 15 JSON files → `converted_objects` dict with 17 keys.

**`assessment.py`** (1,296 LOC): Replace Tableau connector tiers/unsupported patterns with BO equivalents. Framework is reusable.

---

## `converted_objects` Schema Mapping

The central data contract between extraction and generation:

| Generation Key | BO Source(s) | Mapping Complexity |
|---------------|-------------|-------------------|
| `datasources` | datasources.json + tables.json + columns.json | Medium — restructure |
| `worksheets` | reports.json + charts.json | Medium — BO tabs/sections → visual defs |
| `dashboards` | reports.json (page layout) | Low — BO report → PBI page |
| `calculations` | formulas.json (DAX already converted) | Low — rename fields |
| `parameters` | prompts.json | Medium — prompt types → what-if params |
| `filters` | filters.json | Low — direct mapping |
| `stories` | — (no BO equivalent) | None |
| `actions` | — (no BO equivalent) | None |
| `sets` | — (no BO equivalent) | None |
| `groups` | groups.json | Low — break groups → PBI groups |
| `bins` | — (no BO equivalent) | None |
| `hierarchies` | columns.json (dimension hierarchies) | Medium |
| `sort_orders` | sorts.json | Low |
| `aliases` | columns.json (display names) | Low |
| `custom_sql` | custom_sql.json | Low — direct pass-through |
| `relationships` | joins.json | Medium — context resolution needed |
| `user_filters` | — (security profiles, Phase 4) | Deferred |

---

## Sprint Roadmap

### Phase 1: End-to-End Pipeline (Sprints 1–6)

**Goal**: Produce a valid `.pbip` from a simple WebI report.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **1** | Port `powerbi_import/` source-agnostic modules | Copy 33 modules from TableauToPowerBI as-is; verify imports | Generator |
| **2** | Build the bridge: `bo_converted_objects_adapter.py` | Map BO's 15 JSON types → `converted_objects` dict (17 keys) | Converter |
| **3** | Port & adapt `tmdl_generator.py` | Replace Tableau imports → BO imports; remove derivation-prefix cleaning; test with sample BO data | Generator |
| **4** | Port & adapt `pbip_generator.py` | Replace field-name cleaning; wire BO visual type mapping; generate first .pbip | Generator |
| **5** | Port & adapt `import_to_powerbi.py` | Wire full pipeline: BO extraction → adapter → generation → .pbip output; uncomment `migrate.py` generation | Orchestrator |
| **6** | End-to-end validation | Test: `.wid` → extract → adapt → generate → valid `.pbip` opens in PBI Desktop; fix issues | Tester |

**Exit criteria**: `python migrate.py sample.wid` produces a `.pbip` that opens in Power BI Desktop.

### Phase 2: Visual Fidelity & Formula Depth (Sprints 7–12)

**Goal**: Accurate visual mapping, complete formula conversion, prompt→slicer wiring.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **7** | BO visual type mapping table | Map all BO chart types (bar, line, pie, crosstab, gauge, waterfall, scatter, treemap, geo, funnel) → 118 PBI visual types in `visual_generator.py` | Generator |
| **8** | Prompt → Slicer/Parameter | Convert BO prompts (text, date, LOV, numeric, multi-value) → PBI slicers + parameter tables + TMDL `What-If` params | Converter |
| **9** | DAX depth: context operators | Convert `In()` → `CALCULATE + FILTER`, `ForEach` → `SUMX/AVERAGEX`, `ForAll` → `CALCULATE + ALLEXCEPT`; replace placeholder comments with real DAX | Converter |
| **10** | DAX depth: running calculations | `RunningSum/Count/Average` → sort-aware `CALCULATE + FILTER(ALLSELECTED, ...)` patterns; nested `If/ElseIf/Else` → `SWITCH(TRUE(), ...)` | Converter |
| **11** | Universe join → relationship | Context-aware join resolution: detect star/snowflake, resolve BO contexts to disambiguate paths, generate TMDL relationships with correct cardinality | Generator |
| **12** | Alerter → conditional formatting | WebI alerters (color/icon/font rules) → PBI conditional formatting JSON rules in visual definitions | Generator |

**Exit criteria**: Multi-tab WebI report with formulas, prompts, and charts produces a PBI report with correct visuals, working slicers, and valid DAX.

### Phase 3: Crystal Reports & BIAR Batch (Sprints 13–18)

**Goal**: Support Crystal Reports binary format and enterprise batch migration from BIAR archives.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **13** | Crystal extractor: groups, sorts, charts | Implement 5 stub extractors in `crystal_extractor.py` (binary section parsing or regex heuristics) | Extractor |
| **14** | Crystal formula → DAX deep support | `{Table.Field}` qualified refs, `{@Formula}` cross-references, `WhilePrintingRecords`/`WhileReadingRecords` evaluation timing → DAX | Converter |
| **15** | Crystal subreport → drill-through page | Detect subreport links + parameter binding → PBI drill-through pages with filter context | Generator |
| **16** | Crystal cross-tab → matrix visual | Row/column groups + summary fields → PBI matrix configuration with row/column/value wells | Generator |
| **17** | BIAR batch generation pipeline | Wire `extract_from_biar()` → adapter → generation for each artifact; progress tracking; error isolation per artifact | Orchestrator |
| **18** | Batch validation & error reporting | Per-artifact pass/fail scoring; HTML batch report with success rate, error detail, estimated manual effort | Tester |

**Exit criteria**: `python migrate.py --biar archive.biar --output-dir /tmp/batch` produces valid `.pbip` for each artifact; Crystal Reports with groups/subreports generate drill-through pages.

### Phase 4: Assessment & Enterprise (Sprints 19–26)

**Goal**: Portfolio assessment, shared models, deployment, governance.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **19** | Port & adapt `assessment.py` | BO-specific connector tiers, formula gap patterns, complexity scoring (9 categories) | Assessor |
| **20** | Port `server_assessment.py` + `global_assessment.py` | Portfolio-level complexity scoring, wave planning, cross-report merge opportunities | Assessor |
| **21** | Port `shared_model.py` + merge engine | Table fingerprinting from BO universe metadata; multi-report deduplication; thin report generation | Merger |
| **22** | Port `validator.py` + `security_validator.py` | TMDL/PBIR validation; BO function leak detection (replace Tableau leak patterns: `COUNTD/ZN/DATETRUNC` → BO patterns: `=Sum/=Count/NoFilter/Previous`) | Tester |
| **23** | DAX optimizer integration | Port `dax_optimizer.py` (already source-agnostic) + wire into pipeline; `IF→SWITCH`, `ISBLANK→COALESCE`, Time Intelligence measures | Converter |
| **24** | Port deployment framework | Copy `deploy/` (100% agnostic); wire `--deploy WORKSPACE_ID` in `migrate.py`; test with Fabric REST API | Deployer |
| **25** | Governance & telemetry | Port `governance.py`, `telemetry.py`, `monitoring.py`; BO naming convention enforcement; PII detection | Deployer |
| **26** | `--assess` mode end-to-end | Wire assessment into CLI; generate HTML assessment report with readiness score, effort estimate, wave plan | Assessor |

**Exit criteria**: `python migrate.py --server https://bo:6405 --folder /Public --assess` produces portfolio assessment with wave plan. `python migrate.py report.wid --deploy WORKSPACE_ID` deploys to Fabric.

### Phase 5: Fabric-Native & Advanced (Sprints 27–33)

**Goal**: Fabric-native output, @Aggregate_Aware, security profiles, schedule migration.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **27** | Port Fabric generators | Adapt 8 Fabric modules (`lakehouse_generator`, `dataflow_generator`, `notebook_generator`, `pipeline_generator`, `fabric_semantic_model_generator`, etc.); replace `tableau_export` imports → `bo_export` | Generator |
| **28** | `@Aggregate_Aware` conversion | Universe multi-granularity measures → DAX `SUMMARIZE` + `SWITCH(HASONEVALUE(...))` patterns | Converter |
| **29** | BO context operator deep conversion | `In(dimension; context)` → `CALCULATE + FILTER`; `ForEach` → `SUMX`; `ForAll` → `CALCULATE + ALLEXCEPT + USERELATIONSHIP` | Converter |
| **30** | Security profile migration | BO security profiles/access levels → RLS roles + workspace permissions + `permission_mapper.py` PowerShell scripts | Generator |
| **31** | Schedule migration | BO scheduled instances → PBI scheduled refresh + email subscriptions; port `refresh_generator.py` | Deployer |
| **32** | Multi-tenant deployment | Port `multi_tenant.py`; per-tenant connection overrides; template substitution | Deployer |
| **33** | Incremental migration | Port `incremental.py` + `schema_drift.py`; change tracking; skip unchanged artifacts; schema drift alerts | Orchestrator |

**Exit criteria**: `python migrate.py report.wid --output-format fabric` produces Lakehouse + Dataflow + Semantic Model + Pipeline. Security profiles mapped to RLS.

### Phase 6: Polish & Tooling (Sprints 34–40)

**Goal**: Performance, API server, Web UI, plugin system, documentation.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **34** | Performance optimization | Parallel extraction (`concurrent.futures`), batch generation, memory profiling; target 10× throughput for BIAR batches | Orchestrator |
| **35** | Port comparison/visual-diff reports | Adapt `comparison_report.py`, `visual_diff.py`, `migration_report.py` for BO→PBI side-by-side; screenshot comparison | Tester |
| **36** | REST API server | Adapt `api_server.py` — multipart upload, async job queue, BO extensions in `ALLOWED_EXTENSIONS`; OpenAPI spec | Orchestrator |
| **37** | Web UI wizard | Adapt `wizard.py` (CLI) + add Streamlit/web version; 6-step: upload → assess → configure → migrate → validate → deploy | Orchestrator |
| **38** | Plugin system | Port `plugins.py` + `marketplace.py` (both source-agnostic); custom BO visual mapping hooks; DAX post-processing | Orchestrator |
| **39** | LLM-assisted refinement | Port `llm_client.py`; change system prompt from Tableau→BO; LLM DAX review, measure naming, visual suggestions | Converter |
| **40** | Documentation & examples | Enterprise guide finalization, FAQ, sample BO artifacts (.wid/.rpt/.unx), real-world migration examples, video walkthroughs | Tester |

**Exit criteria**: REST API + Web UI operational. Plugin system documented. 95% test coverage. Enterprise guide complete.

---

### Phase 7: Real-World Validation & Test Hardening (Sprints 41–46)

**Goal**: Validate against production BO content; harden edge cases; build regression corpus.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **41** | Golden corpus — WebI | Collect 50+ real-world WebI documents across industries (finance, retail, HR, logistics); run pipeline; score conversion fidelity | Tester |
| **42** | Golden corpus — Crystal & Universe | Collect 30+ Crystal Reports + 20+ Universe files; run pipeline; catalog extraction + generation gaps | Tester |
| **43** | Edge-case fix sprint | Fix top-20 failures from golden corpus: encoding issues, nested formulas, unusual XML structures, large file handling | Extractor |
| **44** | Regression suite build | Generate snapshot `.pbip` golden outputs for 100 artifacts; wire `regression_suite.py` into CI; fail on drift | Tester |
| **45** | Equivalence testing | Run `equivalence_tester.py` on all DAX conversions; compare against BO formula results from sample data; catalog mismatches | Converter |
| **46** | Fidelity benchmark report | Publish fidelity scorecard: % of WebI/Crystal/Universe features accurately converted; per-category pass rates; gap heat-map | Assessor |

**Exit criteria**: 100-artifact regression corpus. Automated golden snapshot tests in CI. Published fidelity benchmarks: ≥90% WebI, ≥75% Crystal, ≥85% Universe.

---

### Phase 8: Crystal Reports Deep Support (Sprints 47–53)

**Goal**: Native Crystal binary parsing; full group/subreport/chart conversion without SAP SDK dependency.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **47** | Crystal binary format reverse engineering | Document `.rpt` binary structure: header, sections, object-record layout; build hex-to-structure parser for fields, formulas, groups | Extractor |
| **48** | Crystal group hierarchy extraction | Parse multi-level group trees (Group 1 → Group 2 → Detail); header/footer slot detection; group sort extraction | Extractor |
| **49** | Crystal chart extraction | Parse chart definitions: chart type, data fields, axes, legends, series; support bar/line/pie/scatter/area | Extractor |
| **50** | Crystal cross-tab → Matrix | Row groups + column groups + summary fields → PBI matrix visual with row/column/value wells; subtotals + grand totals | Generator |
| **51** | Crystal subreport linking | Detect subreport insertion points; parameter binding between main and sub; generate PBI drill-through pages with filter context | Generator |
| **52** | Crystal page layout → Paginated Report | Map Crystal's banded layout (Report/Page/Group Header-Footer-Detail) → PBI Paginated Report RDL when layout fidelity is critical | Generator |
| **53** | Crystal integration tests | End-to-end tests: 20 Crystal fixtures covering groups, subreports, cross-tabs, charts, running totals; snapshot golden outputs | Tester |

**Exit criteria**: Crystal binary parser extracts groups/charts/subreports without SAP SDK. Crystal fidelity ≥85%. Paginated Report output option for layout-critical reports.

---

### Phase 9: BO Server Live Integration (Sprints 54–60)

**Goal**: Live migration from BO CMS/RESTful Web Services; schedule inventory; user mapping; incremental sync.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **54** | BO server discovery & inventory | `server_client.py` — enumerate all folders, documents, universes, connections, users, groups; export full inventory JSON | Extractor |
| **55** | Live document download pipeline | Stream `.wid`/`.rpt`/`.unx` from BO server via REST API; queue-based download with retry and rate-limiting (`429` handling) | Orchestrator |
| **56** | Schedule inventory & mapping | Extract BO scheduled instances (frequency, recipients, format, destination); generate PBI refresh schedule + subscription matrix | Deployer |
| **57** | User & group mapping | Map BO users/groups/access levels → Entra ID users/security groups; generate `permission_mapper.py` PowerShell scripts for workspace RBAC | Deployer |
| **58** | Incremental server sync | Track last-sync timestamp per artifact; only re-migrate changed documents; schema-drift detection between runs | Orchestrator |
| **59** | BO server → Fabric direct pipeline | End-to-end: BO CMS → extract → generate → deploy to Fabric workspace; single CLI command with `--server` + `--deploy` flags | Deployer |
| **60** | Server mode integration tests | Mock BO REST API responses; test discovery, download, incremental sync, error handling; test with BI 4.2 + 4.3 response formats | Tester |

**Exit criteria**: `python migrate.py --server https://bo:6405 --folder /Public --deploy WORKSPACE_ID` runs end-to-end. Incremental sync only processes changed artifacts. User/group mapping generates Entra ID scripts.

---

### Phase 10: Semantic Model Intelligence (Sprints 61–67)

**Goal**: Auto-detect star schemas, optimize relationships, generate lineage maps, impact analysis.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **61** | Star/snowflake schema detection | Analyze universe joins + table cardinalities → classify fact/dimension tables; auto-generate optimal TMDL relationships with correct cardinality (1:M, M:1) | Generator |
| **62** | Relationship optimizer | Detect redundant/conflicting joins; resolve BO contexts to inactive relationships with `USERELATIONSHIP`; eliminate bridge tables when possible | Generator |
| **63** | Auto Calendar table | Detect date columns across all tables; generate shared Calendar/Date table with fiscal year support; auto-create time intelligence measures (YTD, QTD, MTD, YoY) | Converter |
| **64** | Lineage map generation | Build column-level lineage: BO universe object → extracted column → DAX measure → visual binding; output SVG flow diagram + interactive HTML | Assessor |
| **65** | Impact analysis engine | Given a universe change (table rename, column removal, join change), predict which reports/measures/visuals are affected; output impact report | Assessor |
| **66** | Measure optimization engine | Detect duplicate measures across reports; consolidate into shared calculation groups; apply `dax_optimizer.py` auto-simplification patterns | Converter |
| **67** | Model quality scorecard | Score generated semantic models: relationship coverage, measure complexity, naming consistency, unused columns, circular dependencies; HTML report | Assessor |

**Exit criteria**: Auto-generated star schemas with correct cardinality. Calendar table with 6 time intelligence measures. Column-level lineage SVG. Impact analysis for universe changes.

---

### Phase 11: Advanced Visual Fidelity (Sprints 68–74)

**Goal**: Pixel-level visual matching; theme extraction; conditional formatting; custom visuals.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **68** | BO theme → PBI theme.json | Extract BO document colors, fonts, chart palettes → generate PBI `theme.json` (Fluent tokens); auto-detect corporate palette | Generator |
| **69** | Visual layout engine | Preserve BO tab/section spatial layout → PBI page canvas positioning; handle free-form placement, overlapping, header/footer zones | Generator |
| **70** | Conditional formatting deep | Multi-condition alerters → PBI conditional formatting rules (background, font color, icons, data bars); range-based + top-N + field-based rules | Generator |
| **71** | Drill-through & tooltip pages | BO document links + subreport navigation → PBI drill-through pages; detail context fields auto-detected; tooltip pages for hover detail | Generator |
| **72** | Bookmarks & navigation | BO input controls + tab navigation → PBI bookmarks + button navigation; section visibility states → bookmark groups | Generator |
| **73** | Custom visual mapping | Map BO chart types with no native PBI equivalent → certified custom visuals (Deneb/Vega-Lite for complex charts, Charticulator for custom layouts) | Generator |
| **74** | Visual fidelity scoring | Screenshot comparison: BO report vs generated PBI report; compute pixel-diff SSIM score per visual; aggregate fidelity percentage | Tester |

**Exit criteria**: Theme extraction produces valid `theme.json`. Layout spatial accuracy ≥80%. Conditional formatting covers 3+ rule types. Visual SSIM fidelity ≥70%.

---

### Phase 12: Enterprise Scale & Performance (Sprints 75–81)

**Goal**: Handle 10,000+ artifact portfolios; parallel processing; streaming; caching; resilience.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **75** | Parallel extraction engine | `concurrent.futures.ProcessPoolExecutor` for CPU-bound XML/binary parsing; configurable worker count; per-file timeout with graceful kill | Orchestrator |
| **76** | Parallel generation engine | Multi-process TMDL/PBIR generation; shared progress bar; artifact-level error isolation (one failure doesn't block batch) | Orchestrator |
| **77** | Streaming BIAR processing | Stream-extract artifacts from BIAR without loading full archive in memory; process artifacts as they're extracted; memory cap enforcement | Extractor |
| **78** | Result caching layer | Hash-based cache for extraction + generation results; skip re-processing unchanged inputs; configurable cache dir with TTL | Orchestrator |
| **79** | Large-file handling | Chunk processing for WebI documents >100 MB; streaming XML parsing (`iterparse`); configurable memory limits per artifact | Extractor |
| **80** | Resilience & retry framework | Transient failure retry with exponential backoff; checkpoint/resume for interrupted batch migrations; dead-letter queue for failed artifacts | Orchestrator |
| **81** | Performance benchmarks | Benchmark suite: 100/500/1000/5000 artifacts; measure throughput (artifacts/min), memory peak, CPU utilization; publish results | Tester |

**Exit criteria**: Process 1,000 artifacts in <30 min (8 cores). Memory stays <4 GB for any single artifact. Interrupted batches resume from checkpoint.

---

### Phase 13: AI-Assisted Migration (Sprints 82–89)

**Goal**: LLM-powered formula repair, visual suggestions, naming standardization, documentation generation.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **82** | LLM DAX repair | Send failed/placeholder DAX formulas to Azure OpenAI; LLM corrects syntax, resolves broken references, explains changes; human-in-the-loop approval | Converter |
| **83** | LLM measure naming | Standardize measure names using LLM: remove BO prefixes, apply business-friendly naming conventions, detect duplicates across reports | Converter |
| **84** | LLM visual suggestion | Analyze data shape + measure types → LLM suggests optimal PBI visual type and configuration; override default mapping when LLM confidence is high | Generator |
| **85** | LLM schema optimization | Analyze generated TMDL → suggest denormalization, column removal, relationship changes; output optimization report with rationale | Generator |
| **86** | RAG-based formula knowledge | Build vector index of BO→DAX conversion examples; retrieve similar conversions for context; improve accuracy on rare/complex formulas | Converter |
| **87** | Auto-documentation generation | LLM generates: measure descriptions, table annotations, report purpose summary, data dictionary; populate TMDL `description` fields | Generator |
| **88** | Migration copilot chat | Interactive chat interface: user describes BO report behavior → copilot explains equivalent PBI pattern; suggests manual adjustments | Orchestrator |
| **89** | AI confidence scoring | Per-conversion confidence score (0–100) based on formula complexity, LLM agreement, pattern-match coverage; flag low-confidence conversions for review | Assessor |

**Exit criteria**: LLM repairs 80%+ of placeholder DAX formulas. Auto-documentation populates descriptions for all measures/tables. Confidence scoring flags ≤10% for manual review.

---

### Phase 14: Multi-Platform Output (Sprints 90–96)

**Goal**: Generate Paginated Reports (RDL), Power Apps, Excel templates, and Fabric Real-Time Analytics outputs.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **90** | Paginated Report (RDL) generator | Crystal banded layout → SSRS/PBI Paginated Report `.rdl`; precise page breaks, headers/footers, subreport embedding | Generator |
| **91** | RDL expression converter | BO/Crystal formulas → RDL expressions (VB.NET syntax); shared dataset references; parameter wiring for paginated reports | Converter |
| **92** | Excel template generator | Simple BO tabular reports → Excel `.xlsx` with Power Query connections, PivotTables, conditional formatting; data refresh via PBI dataset | Generator |
| **93** | Power Apps screen generator | BO input-heavy reports (forms, data entry) → Power Apps canvas app screens with gallery/form controls connected to Dataverse or PBI dataset | Generator |
| **94** | Fabric Real-Time Analytics | BO real-time dashboards → KQL database + Eventstream + Real-Time Dashboard; streaming ingestion configuration | Generator |
| **95** | Fabric notebook ETL | Complex BO custom SQL + stored procedures → PySpark notebooks; Delta table output; scheduled pipeline execution via Fabric Data Factory | Generator |
| **96** | Output format router | `--output-format` flag: `pbip` (default), `fabric`, `rdl`, `excel`, `powerapp`, `realtime`; format-specific validation; multi-format in single run | Orchestrator |

**Exit criteria**: `--output-format rdl` produces valid Paginated Reports for Crystal sources. Excel templates connect to PBI datasets. Output router supports 6 formats.

---

### Phase 15: Marketplace & Ecosystem (Sprints 97–104)

**Goal**: Plugin marketplace, community connectors, VS Code extension, partner integrations.

| Sprint | Focus | Deliverables | Agent |
|--------|-------|-------------|-------|
| **97** | VS Code extension | Dedicated VS Code extension: right-click `.wid`/`.rpt` → Migrate; inline assessment results; migration status panel; integrated report viewer | Orchestrator |
| **98** | Plugin SDK & registry | Formal plugin API: `register_extractor()`, `register_visual_mapper()`, `register_dax_postprocessor()`; plugin discovery from local dir + remote registry | Orchestrator |
| **99** | Community connector framework | Extensible connector architecture: add new BO sources (e.g., Analysis for OLAP, Web Applications Designer) via plugin without core changes | Extractor |
| **100** | SAP BW connector plugin | Plugin: SAP BW BEx queries/InfoProviders → PBI semantic model; map BW hierarchies → PBI parent-child hierarchies; variable mapping | Extractor |
| **101** | Partner API & webhooks | REST API for partners: submit migration jobs, receive webhook callbacks on completion, download results; API key authentication; rate limiting | Orchestrator |
| **102** | Migration-as-a-Service | Docker Compose stack: API server + worker pool + Redis queue + PostgreSQL state store; Kubernetes Helm chart for cloud deployment | Deployer |
| **103** | Telemetry dashboard (Fabric) | Aggregate telemetry → Fabric Lakehouse; Real-Time Dashboard showing: migrations/day, success rate, avg fidelity, formula gap trends, top errors | Deployer |
| **104** | GA release & launch | Final QA pass; security audit; OSS license review; PyPI package (`pip install bo2pbi`); documentation site (MkDocs); launch blog post | Tester |

**Exit criteria**: VS Code extension published. Plugin SDK documented with 2+ community plugins. Docker MaaS stack operational. Published on PyPI with ≥95% test coverage.

---

## Dependency Graph

```
Phase 1 (Foundation) ✅ DONE
├── Sprint 1: Copy agnostic modules ──────────────────┐
├── Sprint 2: Bridge adapter ─────────────────────────┤
├── Sprint 3: tmdl_generator adaptation ──────────────┤
├── Sprint 4: pbip_generator adaptation ──────────────┤
├── Sprint 5: Wire full pipeline ─────────────────────┤
└── Sprint 6: E2E validation ─────────────────────────┘
        │
        ▼
Phase 2 (Fidelity) ✅ DONE          Phase 3 (Crystal & BIAR) ✅ DONE
├── Sprint 7-8: Visuals/Prompts     ├── Sprint 13: Crystal stubs
├── Sprint 9-10: DAX depth          ├── Sprint 14-16: Crystal→PBI
├── Sprint 11: Relationships        ├── Sprint 17: BIAR batch
└── Sprint 12: Cond. formatting     └── Sprint 18: Batch validation
        │                                  │
        ▼                                  ▼
Phase 4 (Enterprise) ✅ DONE ─────────────────────────┐
├── Sprint 19-20: Assessment                           │
├── Sprint 21: Shared model                            │
├── Sprint 22-23: Validation + DAX optimizer           │
├── Sprint 24: Deployment                              │
├── Sprint 25: Governance                              │
└── Sprint 26: --assess E2E                            │
        │                                              │
        ▼                                              │
Phase 5 (Advanced) ✅ DONE ◄──────────────────────────┘
├── Sprint 27: Fabric-native
├── Sprint 28-29: @AggAware + Contexts
├── Sprint 30-31: Security + Schedules
├── Sprint 32-33: Multi-tenant + Incremental
        │
        ▼
Phase 6 (Polish & Tooling)
├── Sprint 34: Perf optimization
├── Sprint 35: Comparison reports
├── Sprint 36-37: API + Web UI
├── Sprint 38-39: Plugins + LLM
└── Sprint 40: Docs & examples
        │
        ▼
Phase 7 (Real-World Validation) ◄─────── feedback loop
├── Sprint 41-42: Golden corpus (50+ WebI, 30+ Crystal)
├── Sprint 43: Edge-case fix sprint
├── Sprint 44-45: Regression + equivalence
└── Sprint 46: Fidelity benchmarks
        │
        ├──────────────────────────┐
        ▼                          ▼
Phase 8 (Crystal Deep)     Phase 9 (BO Server Live)
├── Sprint 47-49: Binary    ├── Sprint 54-55: Discovery
│   parser + groups/charts  ├── Sprint 56-57: Schedules/Users
├── Sprint 50-52: Matrix/   ├── Sprint 58-59: Incr. sync
│   Subreport/Paginated     └── Sprint 60: Server tests
└── Sprint 53: Integration
        │                          │
        ▼                          ▼
Phase 10 (Semantic Intelligence) ◄─────────────────────┐
├── Sprint 61-62: Star schema + relationship optimizer  │
├── Sprint 63: Auto Calendar + time intelligence        │
├── Sprint 64-65: Lineage + impact analysis             │
└── Sprint 66-67: Measure optimization + quality score  │
        │                                               │
        ▼                                               │
Phase 11 (Visual Fidelity)                              │
├── Sprint 68: Theme extraction                         │
├── Sprint 69-70: Layout + conditional formatting       │
├── Sprint 71-72: Drill-through + bookmarks             │
└── Sprint 73-74: Custom visuals + SSIM scoring         │
        │                                               │
        ▼                                               │
Phase 12 (Enterprise Scale) ◄──────────────────────────┘
├── Sprint 75-76: Parallel extract + generate
├── Sprint 77-79: Streaming + caching + large files
└── Sprint 80-81: Resilience + benchmarks
        │
        ├──────────────────────────┐
        ▼                          ▼
Phase 13 (AI-Assisted)     Phase 14 (Multi-Platform)
├── Sprint 82-83: LLM DAX  ├── Sprint 90-91: RDL/Paginated
│   repair + naming         ├── Sprint 92-93: Excel + PowerApps
├── Sprint 84-86: Visual    ├── Sprint 94-95: RT Analytics
│   AI + RAG knowledge      └── Sprint 96: Output router
├── Sprint 87-88: Auto-docs
│   + migration copilot
└── Sprint 89: Confidence
        │                          │
        ▼                          ▼
Phase 15 (Marketplace & GA) ◄─────┘
├── Sprint 97: VS Code extension
├── Sprint 98-99: Plugin SDK + connectors
├── Sprint 100: SAP BW plugin
├── Sprint 101-102: Partner API + MaaS
├── Sprint 103: Telemetry dashboard
└── Sprint 104: GA release (PyPI, docs, launch)
```

**Parallelism**: Phase 8 ‖ Phase 9, Phase 13 ‖ Phase 14.

---

## Test Strategy

### Coverage Targets

| Phase | Target | Tests | Focus Areas |
|-------|--------|-------|-------------|
| Phase 1–5 ✅ | ≥85% | 244 | Bridge adapter, TMDL, PBIR, E2E, DAX, assessment, Fabric |
| Phase 6 | ≥88% | 400+ | API server, Web UI, plugins, comparison reports |
| Phase 7 | ≥88% | 500+ | Golden corpus snapshots, regression suite, equivalence |
| Phase 8 | ≥89% | 700+ | Crystal binary parsing, groups, subreports, paginated |
| Phase 9 | ≥90% | 900+ | Server discovery, incremental sync, user mapping |
| Phase 10 | ≥90% | 1,200+ | Star schema detection, lineage, impact analysis |
| Phase 11 | ≥91% | 1,500+ | Theme extraction, layout engine, SSIM visual scoring |
| Phase 12 | ≥92% | 2,000+ | Parallel processing, caching, resilience, benchmarks |
| Phase 13 | ≥93% | 2,500+ | LLM integration, RAG, confidence scoring |
| Phase 14 | ≥94% | 3,000+ | RDL, Excel, Power Apps, Real-Time output |
| Phase 15 | ≥95% | 3,500+ | VS Code extension, plugin SDK, MaaS, PyPI package |

### Test Categories

| Category | Scope | Tooling |
|----------|-------|---------|
| **Unit** | Individual functions (DAX convert, M build, visual map) | pytest + fixtures |
| **Integration** | Full pipeline: `.wid` → `.pbip` | pytest + temp dirs + TMDL parser |
| **Snapshot** | Regression: golden `.pbip` output comparison | `regression_suite.py` |
| **Equivalence** | DAX formula output matching expected values | `equivalence_tester.py` |
| **Security** | ZIP slip, XXE, path traversal, credential redaction | pytest-security fixtures |
| **BIAR Batch** | Multi-artifact archive processing | BIAR fixtures with 5+ artifact types |
| **Performance** | Throughput benchmarks, memory profiling | pytest-benchmark + custom harness |
| **Visual** | Screenshot comparison, SSIM scoring | Playwright + Pillow/scikit-image |
| **LLM** | Prompt quality, hallucination detection | Mock LLM + golden response comparison |

### Currently Passing (244 tests)

| File | Tests | Status |
|------|-------|--------|
| `tests/test_dax_converter.py` | 56 | ✅ All pass |
| `tests/test_biar_reader.py` | 12 | ✅ All pass |
| `tests/test_cli.py` | 13 | ✅ All pass |
| `tests/test_crystal_pipeline.py` | 21 | ✅ All pass |
| `tests/test_extraction.py` | 8 | ✅ 7/8 (1 Windows PermissionError) |
| `tests/test_webi_extractor.py` | 9 | ✅ All pass |
| `tests/test_e2e_pipeline.py` | 49 | ✅ All pass |
| `tests/test_assessment.py` | 46 | ✅ All pass |
| `tests/test_phase5_advanced.py` | 32 | ✅ All pass |

---

## Reuse Execution Plan

### Sprint 1 Detailed: Copy Source-Agnostic Modules ✅ DONE

**From `../TableauToPowerBI/powerbi_import/`** — copy these 33 modules unchanged:

```
# Deploy (100% agnostic — 11 files, 2,665 LOC)
deploy/auth.py, deploy/client.py, deploy/deployer.py, deploy/pbi_client.py,
deploy/pbi_deployer.py, deploy/bundle_deployer.py, deploy/multi_tenant.py,
deploy/pbix_packager.py, deploy/utils.py, deploy/config/settings.py,
deploy/config/environments.py

# Governance & Quality (6 files, ~1,800 LOC)
governance.py, permission_mapper.py, monitoring.py, sla_tracker.py,
recovery_report.py, plugins.py

# DAX & Templates (3 files, ~770 LOC)
dax_optimizer.py, dax_recipes.py, model_templates.py

# Merge Engine (4 files, ~1,750 LOC)
thin_report_generator.py, merge_assessment.py, merge_config.py, merge_report_html.py

# Testing Utilities (2 files, ~290 LOC)
regression_suite.py, equivalence_tester.py

# Reporting & UI (5 files, ~1,800 LOC)
html_template.py, progress.py, marketplace.py, incremental.py, paginated_generator.py
```

**Verify**: All imports resolve; no `tableau_export` references in these modules.

### Sprint 2 Detailed: Bridge Adapter

Create `bo_export/converted_objects_adapter.py`:

```python
def adapt_bo_to_converted_objects(extracted_data: dict) -> dict:
    """Map BO's 15 extracted JSON types → generation's converted_objects schema."""
    return {
        "datasources": _adapt_datasources(extracted_data),      # datasources + tables + columns
        "worksheets": _adapt_worksheets(extracted_data),         # reports + charts
        "dashboards": _adapt_dashboards(extracted_data),         # reports (page layout)
        "calculations": _adapt_calculations(extracted_data),     # formulas (DAX already converted)
        "parameters": _adapt_parameters(extracted_data),         # prompts
        "filters": _adapt_filters(extracted_data),               # filters
        "stories": [],                                           # no BO equivalent
        "actions": [],                                           # no BO equivalent
        "sets": [],                                              # no BO equivalent
        "groups": _adapt_groups(extracted_data),                 # groups
        "bins": [],                                              # no BO equivalent
        "hierarchies": _adapt_hierarchies(extracted_data),       # columns (dimension hierarchies)
        "sort_orders": _adapt_sorts(extracted_data),             # sorts
        "aliases": _adapt_aliases(extracted_data),               # columns (display names)
        "custom_sql": extracted_data.get("custom_sql", []),      # pass-through
        "relationships": _adapt_relationships(extracted_data),   # joins
        "user_filters": [],                                      # deferred to Phase 5
    }
```

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation | Phase |
|------|--------|-----------|------------|-------|
| Crystal .rpt binary format too opaque without SDK | Groups/sorts/charts remain stubs | Medium | Fallback: require Crystal-to-PDF or Crystal-to-Excel pre-export; document as manual step | 8 |
| BO context operators don't translate cleanly to DAX | Formula accuracy for complex reports | High | `ForEach`/`ForAll`/`In` generate `/* TODO */` comments; add LLM-assisted refinement in Phase 13 | 5, 13 |
| `@Aggregate_Aware` multi-granularity logic | Incorrect aggregation in PBI | Medium | Generate `SWITCH(HASONEVALUE(...))` + doc comment flagging manual review | 5, 10 |
| TableauToPowerBI `tmdl_generator` API drift | Port breaks after upstream updates | Low | Pin to specific commit; track upstream changes quarterly | 6 |
| BO Server REST API version differences (BI 4.x vs 4.3) | Server mode fails on older BO versions | Medium | Version detection in `server_client.py`; graceful degradation for missing endpoints | 9 |
| BIAR archives with >1000 artifacts | Memory/perf issues in batch mode | Medium | Streaming extraction; per-artifact error isolation; configurable parallelism | 12 |
| LLM hallucination in DAX repair | Incorrect formulas introduced silently | High | Human-in-the-loop approval; confidence scoring; equivalence testing against known results | 13 |
| Paginated Report RDL format complexity | Incomplete layout mapping for complex Crystal reports | Medium | Focus on 80% common patterns; fallback to manual RDL editing for edge cases | 14 |
| Plugin security (untrusted code execution) | Malicious plugins execute arbitrary code | Medium | Plugin sandboxing; code signing; permission model for file/network access | 15 |
| PyPI package size with all dependencies | Large install footprint | Low | Core package minimal (stdlib only); optional extras `[fabric]`, `[ai]`, `[server]` | 15 |

---

## Success Metrics

| Metric | Phase 5 ✅ | Phase 7 | Phase 10 | Phase 13 | Phase 15 |
|--------|-----------|---------|----------|----------|----------|
| **WebI conversion fidelity** | ≥85% | ≥90% | ≥93% | ≥97% | ≥98% |
| **Crystal conversion fidelity** | ≥60% | ≥75% | ≥85% | ≥90% | ≥93% |
| **Universe conversion fidelity** | ≥80% | ≥85% | ≥92% | ≥95% | ≥97% |
| **Formula accuracy** | 87% (107/123) | 90% | 93% | 97% (LLM) | 98% |
| **Visual type coverage** | 15 types | 25 types | 35 types | 40+ types | 45+ types |
| **Pipeline throughput** | 1 artifact/10s | 1 artifact/5s | 1 artifact/2s | 1 artifact/2s | 1 artifact/1s |
| **Batch capacity** | 50 artifacts | 500 artifacts | 2,000 artifacts | 5,000 artifacts | 10,000+ |
| **Test count** | 244 | 500+ | 1,500+ | 2,500+ | 3,500+ |
| **Test coverage** | ≥85% | ≥88% | ≥90% | ≥93% | ≥95% |
| **Output formats** | 2 (pbip, fabric) | 2 | 2 | 2 | 6 |
| **Deployment targets** | Local + Fabric | Local + Fabric | Local + Fabric | + PBI Service | + MaaS (K8s) |
| **AI features** | — | — | Lineage | LLM + RAG + docs | + copilot chat |
