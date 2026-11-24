# Development Plan — BO to Power BI Migration

> **Last reviewed**: 2026-11-24
> The March 2026 version 3.0 plan is retained below as historical planning evidence,
> not a current release or a certification that every phase exit criterion passed.

## Evidence dashboard — 2026-11-24

| Result | Verified locally | Still open |
|---|---|---|
| 🟢 Python suite | 1 294 passed, 1 skipped, 1 547 subtests; 80.73% coverage | Hosted CI matrix |
| 🟢 BEx / InfoCube | Strict PBIP: 0 errors, 0 warnings; 2 synthetic observations, 0 mismatches | Real SAP/Power BI execution and approval |
| 🟠 WebI synthetic | Batch generated; 13 static review warnings | Visual bindings and runtime rendering |
| 🟠 Static quality | Critical Flake8 passed; coverage gate passed | Ruff 387 findings; Pyright 71 errors, 2 warnings |

These results are local and synthetic. They do not prove identity, provenance,
equivalence, refresh, deployment or retirement readiness.

## Review and current priorities — 2026-11-24

**Review basis before the linked pilot:** the initial code/evidence review
used a clean `main` worktree. The manifest v1.2 change was verified in
`powerbi_import/bw_bex_assessment.py`,
`docs/schemas/sap_bw_bex_semantics.schema.json` and
`tests/test_bw_bex_assessment.py`: BEx semantic manifest v1.2 requires provider
key-figure bindings and a declared kind (`basic`, `restricted`, `calculated` or
`unknown`); its assessment adds kind summaries and marks identity, provenance
and equivalence `unverified`. Manifests v1.0/v1.1 retain prior acceptance and
report shape. This is local declaration/assessment behavior only: no kind
converts semantics or generates measures, the gate stays open, and runtime is
`not_run`. The initial local CI-equivalent baseline on Windows/Python 3.12.16
passed critical Flake8 and all pytest assertions, but the CI test command failed
its coverage gate: 55.79% against the unchanged 80% threshold. Ruff 0.17.6
reported 404 diagnostics, and Pyright 1.1.414 reported 74 errors and 2 warnings.
A first run using the machine's default
temporary path had eight Windows short/long-path mismatches; rerunning under a
non-aliased temporary root removed those test failures. This is one local matrix
leg only: other OS/Python jobs and hosted CI were not run. SAP, Desktop and
Fabric runtime remain `not_run`; these measurements do not establish parity.
Other recorded local slices remain bounded: WebI snapshot checks validate
declared query-plan links, the synthetic WebI PBIP retains unresolved visual
references, and the BW vector comparator compares only supplied rows. None
verifies native source identity or parity. See the
[local BO, BEx and InfoCube review](GAP_ANALYSIS.md#local-bo-bex-and-infocube-review--2026-11-24)
for the migration findings and the
[linked pilot](#delivered-local-bex-and-infocube-pilot--2026-11-24) for the
subsequent implementation and local validation.

**Historical CI trail (not current):** the early coverage baseline was 55.78%;
owner-scoped cleanup reduced Ruff from 404 to 395 findings and Pyright from
74 errors to 72 errors / 2 warnings. A later shared test bootstrap fixed
console collection locally. Detailed per-increment results remain in the
coverage recovery section below; the dashboard above is the latest snapshot.

**Ordered next work** (detail and historical evidence are retained in the
sections below):

The dashboard and linked gap review remain the numeric evidence baseline; the
work packages below add no new measurements.

1. **Delivered locally — repair the two observed semantic corruptions.**
  **Outcome/evidence:** duplicate-table repair in
  [powerbi_import/tmdl_generator.py](../powerbi_import/tmdl_generator.py)
  can redirect both relationship endpoints by table name without checking
  whether the renamed target contains each endpoint column; the `SUBSTITUTE`
  rewrite incorrectly maps a fourth `instance_num` argument to all-occurrence
  `Text.Replace`. **First change:** `Semantic` leads a bounded TMDL repair;
  coordinate `Healing`, `Dax` and `Wiring` under the ownership collaboration,
  with `Tester` adding focused TMDL and generated-relationship end-to-end
  regressions in [tests/test_tmdl_generator.py](../tests/test_tmdl_generator.py).
  `Semantic` now resolves relationship endpoints by table/column membership;
  ambiguous or missing endpoints fail closed and are recorded for review.
  Four-argument `SUBSTITUTE` with an `instance_num`
  must be rejected/left unsupported until its semantics can be preserved, not
  emitted as all-occurrence `Text.Replace`. Revise the erroneous existing
  expectation. **Local exit:**
  in the generated model, every `fromTable`/`fromColumn` and
  `toTable`/`toColumn` endpoint resolves to an existing table and column; a
  duplicate-name repair never redirects an endpoint to a table lacking that
  column. Add a negative regression proving unsupported four-argument
  `SUBSTITUTE` fails closed, and preserve the three-argument behavior.
  Focused TMDL, Semantic Intelligence and E2E tests pass: **144 tests and
  53 subtests**. **Risk/non-goal:**
  do not redirect by name alone or imply general formula parity; no unrelated
  TMDL/DAX cleanup. The repository Ruff gate remains open independently.
2. **Restore repository static CI gates — parallel local work.**
  **Outcome/evidence:** the dashboard records local suite and critical Flake8
  success. The owner-scoped slices reduced Ruff from 392 to 387 diagnostics;
  Pyright moved from 72 to 71 errors. Both gates remain open and hosted CI is
  `not_run`.
  **First change:** `Tester` coordinates; each primary owner fixes only its
  Ruff/Pyright findings and records a per-owner before/after diagnostic
  snapshot. **Dependencies/acceptance:** may proceed alongside item 1; use
  focused owner tests, `pytest tests/ --tb=short -q` and whole CI-equivalent
  checks. No blanket `--fix`, suppressions, lowered thresholds or weakened
  assertions. Only passing hosted CI closes this gate. **Risk/non-goal:** local
  success is not hosted-CI evidence or migration parity.
3. **Unblock native InfoCube identity and one BEx query — externally blocked.**
  **Outcome/evidence (existing pilot, not a new result):** linked Import PBIP
  strict PASS (0 errors/0 warnings); direct CSV comparison has 2 observations
  and 0 mismatches, limited to one text key and one exact measure. Identity,
  provenance and equivalence remain `not_verified`; runtime and approval remain
  `not_run`. **First change:** until the source owner supplies the approved
  evidence package, do documentation/request work only. It must include a
  sanitized native InfoCube identity sample with provenance and field mapping;
  the approved BEx query ID and definition/provider link; selected key-figure
  formula or restriction, unit/currency and aggregation/exception-aggregation
  semantics; and agreed authorization, prompt/filter, hierarchy/time context
  and grain. `Assessor` leads identity review with `Orchestrator`, `Evidence`
  and `Tester`, plus the external BW source owner. Do not infer a SAP API or
  native mapping. After identity and query semantics are approved, capture
  independent source/target results and compare them at the same grain, role
  and prompt context. **Exit:** matched, missing, mismatched, ambiguous and
  wrong-client declarations are covered; reviewed source/target captures and
  business-owner discrepancy disposition exist before conversion is considered.
  **Risk/non-goal:** synthetic PBIP validation and vectors are not real-source
  identity, parity or approval.
4. **Resolve WebI source-backed bindings before schema/generator changes —
  externally blocked.** **Outcome/evidence:** the synthetic batch exits `0`,
  but its 13 static warnings are a baseline, not 13 identical acceptance
  issues; source bindings remain unresolved. **First change:** request a
  sanitized, source-owner-approved CMS/API report-element-to-provider link
  and typed output evidence; until received, document/request only. `WebI
  Migration` coordinates; `BusinessObjects`, `Extractor`, `Wiring`,
  `Semantic`, `Visual`, `Assessor` and `Tester` own their respective slices.
  **Dependencies/acceptance:** source evidence precedes schema or generator
  changes; test matched, missing and ambiguous bindings and typed outputs,
  then re-evaluate actual static findings. Preserve the existing gate and run
  focused tests plus the full suite. **Risk/non-goal:** do not equate every
  baseline warning or claim visual/runtime parity.
5. **Run an explicitly authorized runtime pilot — downstream gate.**
  **Outcome:** determine source/target behavior and acceptance independently
  of local artifacts. **Owners:** `Deployer` executes only separately
  authorized operations; `Evidence` captures/reconciles results and `Reviewer`
  reviews acceptance. **Dependencies/acceptance:** wait for applicable local
  gates (items 1–2), source evidence (items 3–4 as relevant), separate named
  source/SAP, Desktop and target identities and permissions, safe
  non-destructive SAP scope, explicit target
  authorization, and security/business acceptance. Validate Desktop refresh
  and the authorized Power BI/Fabric target separately; record every unrun
  runtime check as `not_run`. **Risk/non-goal:** never infer authorization or
  perform implicit cloud writes, refresh, deployment, cutover or retirement.

**Wave order:** item 2 is the next implementation focus. Items 3 and 4 remain
external evidence blocks, with documentation
and requests as the only work before approved source evidence arrives. Item 5
waits on the applicable local and source gates plus explicit authorization.
Historical counts and phase labels below do not supersede this priority order.

## Test-coverage recovery roadmap — 2026-11-23

**Historical planning baseline:** the goal was to raise meaningful automated
statement coverage to the unchanged CI gate of 80%, with a planning target of
80.5% for a small margin. The earliest Python 3.12.16 coverage JSON used for
this roadmap recorded 14,982 of 26,860 statements covered (55.78%), leaving
11,878 missed. At that baseline denominator, 6,506 additional covered
statements would reach the 80% gate and 6,641 would reach 80.5%. These are
arithmetic planning values, not forecasts; recalculate after each increment if
the measured denominator changes. The earlier 55.79% value remains the separate
initial-run measurement above.

**Prioritization basis:** the historical plan used missed-statement counts,
behavioral risk and existing test leverage, not low percentage alone. The
largest opportunities at baseline included `pbip_generator.py` (1,184 missed,
44.0%), `tmdl_generator.py` (1,097, 60.0%), `shared_model.py` (984, 46.5%),
`visual_generator.py` (414, 32.6%), and `validator.py` (383, 57.1%). High-risk
modules with zero measured coverage at baseline included `global_assessment.py`
(508), `api_server.py` (284), `governance.py` (258), and
`telemetry_dashboard.py` (241). These percentages and counts come from the same
historical Python 3.12.16 coverage JSON; use a fresh profile to rank any further
work.

### Incremental delivery gates

| Increment | Primary owners | Target scope and test leverage | Minimum cumulative gain from baseline | Project checkpoint* |
|---|---|---|---:|---:|
| 1. PBIP and visuals | `Visual`; `Tester` owns tests | `pbip_generator.py`, `visual_generator.py`; expand `tests/test_cli.py`, `tests/test_e2e_pipeline.py`, and `tests/test_visual_fidelity.py` around successful generation, fallback, malformed inputs, and local validation outcomes. | +1,100 statements | 59.9% |
| 2. Semantic and merge | `Semantic` for `tmdl_generator.py`; `Merger` for `shared_model.py` and `thin_report_generator.py` | Extend `tests/test_shared_model.py`, `tests/test_semantic_intelligence.py`, and `tests/test_e2e_pipeline.py`; cover model modes, schema/source identity, collisions, and preservation of declared metadata. | +2,550 statements | 65.3% |
| 3. Assessment and validation | `Assessor` | `global_assessment.py`, `validator.py`, `schema_drift.py`, `strategy_advisor.py`; extend `tests/test_assessment.py` and `tests/test_migration_quality.py`, adding focused suites where a module contract is not covered. Assert findings for invalid, incomplete, ambiguous, and supported inputs. | +3,450 statements | 68.6% |
| 4. Local orchestration | `Orchestrator`; `Tester` owns tests | `api_server.py`, `wizard.py`, `incremental.py`, `notebook_api.py`; add isolated tests for request validation, error paths, and state transitions with temporary files and mocked boundaries. Reuse CLI/E2E suites only where they exercise these contracts. | +4,100 statements | 71.0% |
| 5. Deployment guards | `Deployer`; `Tester` owns tests | `deploy/bundle_deployer.py`, `deploy/multi_tenant.py`, `governance.py`, `telemetry_dashboard.py`; extend `tests/test_phase5_advanced.py` and add focused tests for fail-closed validation, payload construction, and local reports. Mock every client boundary and verify forbidden paths make no calls. | +4,900 statements | 74.0% |
| 6. Evidence and optional integrations | `Evidence` for comparison/report/diff modules; `AI` for `llm_client.py` and `marketplace.py`; `Tester` owns tests | `comparison_report.py`, `migration_report.py`, `visual_diff.py`, `llm_client.py`, `marketplace.py`, then re-rank remaining misses using the refreshed profile. Extend existing report tests or add focused `tests/test_evidence_reports.py` and `tests/test_ai_advisory.py`; use deterministic fixtures and fake providers, without network access. | +6,641 statements | 80.5% |

**Increment 1 progress — checkpoint achieved; CI gate remains open:** Four local behavior-test
slices now cover (1) PBIR decorations through public `create_visual_container()`,
(2) PBIP visual query roles, analytics, fallback, filters, and layout, and
(3) report-level slicers, rich text, actions, tooltip/drillthrough, mobile
positions, and report filters through generated artifacts. Six further
query-path tests cover color/category and series roles, date-aware series
selection, measure-only card fallbacks, and scatter placeholders; the latest
slice adds specialty query roles, script visuals, report metadata/theme,
asset handling, styling, paginated output, review tables, and thin-report shell
preservation. All **41 tests** in `TestPBIPGeneratorCoverageSlices` pass (24
subtests). The full Python 3.12.16 rerun reports **1,002 passed, 1 skipped,
1,382 subtests, no test failures**; its coverage-gated command still fails only
because total coverage is below 80%.

Against the original coverage JSON, project statement coverage is now
**16,129/26,860 (60.05%)**, up from **14,982/26,860 (55.78%)**: a cumulative
gain of **1,147 statements** (+4.27 percentage points from the exact profile),
meeting the increment's **+1,100** checkpoint by **47 statements**.
`pbip_generator.py` rose from **930/2,114 (43.99%)** to **1,896/2,114
(89.69%)** (+966); `visual_generator.py` rose from **200/614 (32.57%)** to
**363/614 (59.12%)** (+163). The two module gains account for 1,129 of the
project gain; the refreshed full-suite profile includes 18 additional
statements in other measured code. Focused-suite coverage is not added
separately.

The coverage-gated command exits nonzero: **60.05%** remains below the
unchanged **80%** threshold. Increment 1's statement-gain checkpoint is
achieved, but the repository-wide CI coverage gate remains open. This test-only
work made no product-code change and does not establish Desktop rendering,
cloud behavior, source equivalence, or runtime acceptance; those remain
separate evidence and authorization gates.

**Increment 2 progress — started:** **31 behavior-focused test methods** were
added across four modules: 14 in `tests/test_shared_model.py`, 10 in
`tests/test_tmdl_generator.py`, 6 in `tests/test_thin_report_generator.py`, and
1 in `tests/test_semantic_intelligence.py`. They cover calculation
deduplication/conflict namespacing, Unicode hierarchy selection,
field-parameter union, calculation-group conflict provenance, culture/type
history, TMDL round-tripping, incremental add/remove, validation, RLS, goals,
and thin-report references. The combined four-suite focused run passes
**66 tests**. Test files remain `Tester`-owned; the source modules remain owned
by `Semantic` (`tmdl_generator.py`) and `Merger` (`shared_model.py` and
`thin_report_generator.py`). Against the Python 3.12.16 Increment 1 profile of
**16,129/26,860 (60.05%)**, the latest full profile is **17,583/26,860
(65.46%)**, a net gain of **1,454 statements** (+5.41 percentage points from
the exact profile). `tmdl_generator.py` is now **2,190/2,743 (79.84%)**,
`shared_model.py` **1,594/1,840 (86.63%)**, and `thin_report_generator.py`
**240/254 (94.49%)**. Per-module changes and whole-project changes are measured
independently in the same full-suite profile; test-only gains can be offset by
platform-specific paths not exercised in this Windows run. Against the original
baseline of 14,982 statements, the cumulative gain is **+2,601**, exceeding
Increment 2's **+2,550** checkpoint by **51 statements**.

The full coverage run associated with this checkpoint records **17,583/26,860
(65.46%)** and exits nonzero against the unchanged 80% gate. Later full-suite
counts are recorded with their corresponding increments. No assessment,
production code, or coverage assertions were weakened.

**Increment 3 progress — checkpoint achieved; CI gate remains open:** the
Assessor slices added 21 portfolio/schema-drift/strategy tests and 12 public
validator behavior tests. A local snapshot round-trip defect was fixed:
`schema_drift.py` now saves and loads the same six supported collections,
including dashboards. The focused Assessor suites pass. Against the Increment 2
checkpoint profile of **17,583/26,860 (65.46%)**, coverage is now
**18,444/26,860 (68.67%)**, a net gain of **861 statements** (+3.21 percentage
points). Against the original baseline of 14,982, cumulative gain is **+3,462**,
exceeding Increment 3's **+3,450 checkpoint by 12 statements**. Module results:
`global_assessment.py` **398/508 (78.35%)**, `validator.py` **641/892 (71.86%)**,
`schema_drift.py` **229/232 (98.71%)**, and `strategy_advisor.py` **125/153
(81.70%)**.

The latest full Python 3.12.16 run reports **1,077 passed, 1 skipped, 1,401
subtests, no test failures**. Its coverage command exits nonzero at **68.67%**;
the 80% CI coverage gate remains open.
Continue into Increment 4 (local orchestration) while retaining the unchanged
80% gate; no hosted CI, cloud, Desktop, or runtime acceptance is claimed.

**Increment 4 progress — checkpoint achieved; CI gate remains open:**
`Tester` added 38 behavior-focused test methods in
[tests/test_orchestration_surfaces.py](../tests/test_orchestration_surfaces.py)
for local API, wizard, incremental merge, and notebook-session contracts. The
new suite passes **38 tests and 9
subtests**. Against the Increment 3 profile of **18,444/26,860 (68.67%)**,
coverage is now **19,084/26,860 (71.05%)**, a net gain of **640 statements**
(+2.38 percentage points). `api_server.py` is **239/284 (84.15%)**,
`wizard.py` **127/146 (86.99%)**, `incremental.py` **219/226 (96.90%)**, and
`notebook_api.py` **172/178 (96.63%)**. Against the original 14,982 baseline,
the cumulative gain is **+4,102**, two statements above Increment 4's **+4,100**
checkpoint.

The latest full Python 3.12.16 run reports **1,115 passed, 1 skipped, 1,410
subtests, no test failures**. Coverage-gated execution still exits nonzero at
**71.05%**, below the unchanged 80% CI threshold. This test-only increment does
not exercise live API/network service, deploy cloud resources, launch Desktop,
or establish runtime success; those evidence gates remain `not_run`.

**Increment 5 progress — checkpoint achieved; CI gate remains open:** `Tester`
added **40 behavior-focused tests** in
[tests/test_deployer_governance.py](../tests/test_deployer_governance.py), using
local files and mocked clients for tenant configuration and placeholder
safety, governance/PII/audit, dashboard inputs and escaping, and bundle
permission/conflict/failure/rollback/refresh behavior. The focused suite passes
**40 tests and 6 subtests**; the existing deployment suite passes **83 tests
and 265 subtests**. Compared with the Increment 4 profile
**19,084/26,860 (71.05%)**, the full profile is **19,928/26,860 (74.19%)**, a
gain of **844 statements** (+3.14 percentage points). Module coverage rose to
`bundle_deployer.py` **250/313 (79.87%)**, `multi_tenant.py` **172/185
(92.97%)**, `governance.py` **235/258 (91.09%)**, and `telemetry_dashboard.py`
**224/241 (92.95%)**. From the original baseline of 14,982, cumulative gain is
**+4,946**, exceeding Increment 5's **+4,900 checkpoint by 46 statements**.

The full Python 3.12.16 run reports **1,155 passed, 1 skipped, 1,416
subtests, no test failures**. The unchanged 80% coverage gate remains open at
74.19%; all test assertions pass. Deployment-related tests are mocked and do
not verify or authorize cloud deployment, refresh, workspace permissions, or
target acceptance; those runtime checks remain `not_run`.

**Increment 6 progress — checkpoint achieved; hosted CI remains unverified:** `Tester` added 36 behavior-focused methods in [tests/test_evidence_reports.py](../tests/test_evidence_reports.py) and [tests/test_ai_advisory.py](../tests/test_ai_advisory.py), then 22 tests for configuration, alert extraction and monitoring, and 44 tests for SLA tracking, merge config, progress, plugins, DAX recipes, scorecards and geo passthrough. The three follow-up suites and seven-suite tranche pass locally; together with the original 36 focused cases, these are 102 tests. The tests use synthetic fixtures, temporary paths and mocked provider/monitoring clients; they make no network or cloud calls.

Against Increment 5's **19,928/26,860 (74.19%)**, the pre-cleanup full-suite
profile was **21,668/26,860 (80.67%)**, a gain of **1,740 statements** (+6.48
percentage points), with **1,257 passed, 1 skipped, 1,422 subtests**. That
local measurement passed the unchanged 80% threshold. Against the initial
14,982 covered statements, the cumulative gain was **+6,686**, exceeding
the **+6,641 checkpoint** and the corresponding 80.5% planning target by
**45 statements**. After the two unused-import removals, the same test scope
measured **21,666/26,858 (80.67%)**.

The previously uncovered follow-up modules measured: `migration_config.py`
**135/136 (99.26%)**, `alerts_generator.py` **132/135 (97.78%)**,
`monitoring.py` **116/120 (96.67%)**, `sla_tracker.py` **79/79 (100%)**,
`merge_config.py` **76/79 (96.20%)**, `progress.py` **78/78 (100%)**,
`plugins.py` **81/87 (93.10%)**, `dax_recipes.py` **42/44 (95.45%)**,
`goals_generator.py` **57/57 (100%)**, and `geo_passthrough.py` **97/100
(97%)**. The full-suite project profile determines the checkpoint.

The post-cleanup local Windows/Python 3.12.16 `python -m pytest` run passed
the coverage threshold; the workflow console replay failed collection as
recorded in the historical CI trail above. Hosted CI across the supported OS/Python
matrix, Desktop/Fabric behavior, source equivalence and runtime acceptance
were not run and remain unverified; local tests do not establish those separate
evidence gates.

\* Checkpoints estimate project coverage from the measured baseline of 26,860
statements and the stated cumulative gain; they are not per-module promises.
Exit each increment only when focused behavior tests pass, the full
`pytest tests/ --tb=short -q` suite passes, and a fresh coverage JSON confirms
the cumulative gain. The last increment must also pass the existing CI coverage
command with the 80% gate; retain 80.5% as the planning target, not a new CI
threshold. Keep coverage configuration and exclusions unchanged. Do not count
trivial accessors, exercise private implementation solely for line hits, weaken
assertions, or add `pragma: no cover`/omissions to improve the percentage.

**Evidence boundaries:** zero coverage in the planning baseline identified
candidate areas, not an instruction to test every line indiscriminately. Cover
observable contracts, error handling, privacy and safe failure behavior first.
Deployment tests remain mocked and do not authorize or verify cloud writes,
refresh, rollback, or target acceptance. Local model generation and validation
do not establish Desktop rendering, source equivalence, or deployed execution;
those remain separate evidence gates and `not_run` until performed.

## Dated local evidence record — 2026-11-22

- The SAP BW capability mapping now distinguishes repository behavior from
  the target architecture. `migrate_bw_bex_pbip.py` writes a versioned
  `sap_bw_capability_boundary` into each generated project's
  `migration_metadata.json`, recording functional and technical object status
  plus fixed `not_run` runtime evidence. This is disclosure and scope control,
  not implementation of Power Apps, Talend, write-back, planning, Fiori or
  Multiprovider conversion.
- BW-6 controls 1.1 now declares dispositions for external operational
  capabilities while preserving fixed `not_run` execution evidence. Additive
  key-figure conversion depends on sufficient identity and linkage evidence.
  A bounded local BEx result-vector comparator is now delivered as a separate
  BW-5 evidence slice; it compares declared rows only. SAP/Fabric runtime and
  approval remain `not_run`; authenticity, provenance, source coverage and
  semantic equivalence remain `not_verified`. Native InfoCube identity remains
  the next BW P1 and is blocked on a sanitized, source-owner-approved identity
  sample and agreed field mapping. WebI snapshot query-plan linkage validation
  and the offline declaration-only coverage ledger are bounded local slices,
  as recorded below.
- `migrate_bw_reconcile.py --bex-result-vectors <manifest> --output
  <new-report.json>` compares declared source/target row vectors using
  composite keys and exact or decimal-tolerance measure rules, reporting key
  and measure discrepancies. A pass means only that the declarations satisfy
  the configured comparison; it does not authenticate the vectors or prove
  coverage or equivalence.
- Earlier local validation for the WebI and BW slices:
  `python -m pytest tests/test_bw_reconciliation.py --tb=short -q` =>
  **16 passed**; `python -m pytest tests/test_webi_snapshot_adapter.py
  tests/test_businessobjects_server_client.py --tb=short -q` =>
  **27 passed**; required full suite `python -m pytest tests/ --tb=short -q`
  completed with exit 0 after the WebI changes (the captured runner output
  contained no summary line, so totals are not recorded); `git diff --check`
  passed. This is local code/test evidence only. No SAP or Fabric execution,
  approval, Desktop rendering, refresh, or external acceptance was performed.
- The next WebI source-coverage P1 remains blocked: the repository has no
  sanitized, source-owner-approved CMS response or verified API contract that
  maps a report element to a provider. The snapshot's report and provider
  records, query-plan ID checks, and synthetic fixture do not establish that
  relationship. Obtain the approved example/contract before changing the
  snapshot schema or implementing bindings; do not infer a mapping from
  generic field names.
- Local one-file folder migration of synthetic
  `examples/Enterprise_Sales.wid` produced one PBIP/model and exited 0.
  Two local smoke replays and independent reproduction by `WebI Migration`
  observed static validation exit 0 with warnings, not clean bindings.
  The specialist reported 23 warning occurrences, including 11 unknown
  `Entity "Table"` visual references; the separately parsed CI-equivalent
  report contained 13 distinct warning findings, including four unknown-Table
  findings. These observations do not prove source-to-target equivalence.
- The locally changed CI sample job now generates that synthetic PBIP,
  checks the PBIP and model exist, and runs default static validation;
  warnings are displayed but do not fail it. The local equivalent passed.
  GitHub-hosted CI is `not_run`; the validation job depends
  on lint and tests, and repository-wide lint/type findings remain open below.
- Earlier recorded local tests: after the import-order fix, ledger, operations
  and agent-contract focused tests passed **86 tests and 548 subtests**. The
  subsequent full `python -m pytest -o 'addopts=' tests\ --tb=short -q` rerun
  passed **920 tests and 1232 subtests**, with **1 skipped**, in 204.42s.
  These are local test results, not hosted CI or target runtime evidence.
- **P1 WebI regression delivered / fresh local baseline — 2026-11-22:** before
  the regression, `Tester` ran the CI-equivalent checks against the already
  dirty worktree: critical Flake8 passed (exit 0, with an invalid-escape
  `SyntaxWarning`); Ruff 0.15.7 failed with 421 errors; Pyright 1.1.414 failed
  with 74 errors and 2 warnings; coverage failed at 55.57% against the
  unchanged 80% threshold. Environment mismatch: `python` is Python 3.13.15
  with pytest 9.1.1 / pytest-cov 7.1.0, while the `pytest` executable is
  Python 3.14.2 with pytest 9.0.2 / pytest-cov 7.0.0. This is a local,
  dirty-worktree baseline—not hosted CI or fully environment-equivalent proof;
  it does not establish zero additions or a CI pass.
- `Tester` added the focused synthetic WebI regression in
  `tests/test_cli.py:405`. It compares actual visual references with model
  columns/measures and retains unresolved `Entity "Table"` findings even when
  default static validation exits 0. The focused regression and required
  `python -m pytest tests/ --tb=short -q` passed. Hosted CI and runtime checks
  remain `not_run`; this does not prove source linkage or feature parity.

### Historical local CI baseline and deployment packaging — 2026-11-22

- **Historical CI evidence / gate:** before the rolling guard below, the
  comparison used the same local Windows Python 3.13.15, Ruff 0.16.7 and
  Pyright 1.1.414 for committed HEAD `df1542c`, extracted by `git archive`
  in the session workspace, and the then-worktree. Ruff reported **428**
  baseline and **421** worktree diagnostics; Pyright reported **77** findings
  in each (worktree: **75 errors, 2 warnings**). A multiset comparison
  normalized by filename, rule and diagnostic message found Ruff **0 added,
  7 removed** and Pyright **0 added, 0 removed**. These counts have since
  changed and are historical, not current; they do not prove individual
  historical provenance.
- The same local CI coverage command,
  `python -m pytest -o 'addopts=' tests\ --tb=short -q --cov=bo_export --cov=powerbi_import --cov-report=term --cov-fail-under=80`,
  reported baseline **52.38%, 788 passed, 1 skipped, 859 subtests** and
  then-worktree **55.33%, 929 passed, 1 skipped, 1232 subtests**; both failed
  the **80%** gate at that time. These are historical pre-guard measurements,
  not current results. The required full suite passes locally without a
  coverage threshold. Hosted CI is `not_run`; do not lower gates or infer
  feature parity from these counts. `Tester` coordinates remaining lint, type
  and coverage work with the relevant module owners; exit requires the
  unchanged CI checks and coverage gate to pass and hosted CI to be run.
- **Local packaging outcome / first change delivered:** `Deployer` isolated
  `PBIWorkspaceDeployer.deploy_project`'s temporary PBIX from the shared
  temp root in a unique directory with fixed name `project.pbix`; when
  packaging or upload and cleanup both fail, the original error is retained
  alongside the cleanup error. `Tester`'s nine focused mocked tests passed
  without network access (`tests/test_phase5_advanced.py::TestDeployerTemporaryPackage`).
  The local hypothesis is that collisions or dataset names cannot redirect
  the package outside its owned directory and simultaneous cleanup failures
  cannot erase the original error; a contrary regression falsifies it.
  This is local packaging for a remote-operation path, not source extraction,
  conversion, target generation or deployment proof.
- **Dependencies / exit and non-goals:** rerun the focused class and required
  `python -m pytest tests/ --tb=short -q` for local changes. PBIX compatibility
  is `not_verified`; target deployment and refresh are `not_run` and require
  separate authorization. No source evidence or runtime gate is changed by
  this local packaging fix.

### Delivered local P1 — refresh schedule deployment guard — 2026-11-22

- **Outcome / first change:** `Deployer` updated
  `PBIWorkspaceDeployer.deploy_refresh_schedule` to skip `None` with a note
  and skip disabled dictionaries; malformed configurations and missing or
  non-boolean `enabled` fail before client calls. Enabled schedules require
  an explicit nonempty list of unique valid weekdays, nonempty valid `HH:MM`
  times and a nonempty time-zone string. Optional notification must be valid;
  optional frequency must be `Daily` or `Weekly`, and `Daily` requires all
  seven weekdays.
- **Hypothesis / cohesive scope:** invalid enabled input must not reach the
  client, and a valid request must contain only supplied target fields, never
  guessed `UTC`, `06:00` or `MailOnFailure`; frequency metadata is omitted
  from the request. A mock call for invalid input or an invented payload field
  falsifies this local remote-operation guard. `Deployer` owns the deployer;
  `Tester` owns regressions. Source extraction, conversion, target generation
  and reporting are outside this slice.
- **Local validation:** reported mock request and error cases in
  `tests/test_phase5_advanced.py` passed **83 tests and 265 subtests**;
  `python -m pytest -o 'addopts=' tests\ --tb=short -q` passed **941 tests,
  1 skipped and 1329 subtests**. Focused Pyright and Ruff passed. These checks
  establish neither target acceptance nor time-zone validity.
- **Next priority / dependencies / exit:** `Deployer` should obtain reviewed
  schedule and target requirements and explicit separate authorization before
  any target validation or service call. Then validate an approved schedule,
  read back the target configuration and observe refresh timing; rejection,
  differing readback or incorrect timing falsifies the target hypothesis.
  `Tester` maintains mock regressions and the required full suite. Target
  validation, service call and refresh are `not_run`; owner review and target
  time-zone validity are `not_verified`. Target validation, service calls,
  refresh and owner review require separate authorization. No real deployment,
  source schedule parity or operational equivalence is claimed.

### Rolling deployment guard and future design — 2026-11-22

- **Outcome / evidence:** `Deployer` changed `deploy_rolling` to fail closed
  before any remote call, returning `status: failed`, `phase: blocked` and
  `rolled_back: false`. The former flow could overwrite an existing canary and
  falsely report rollback; it also relied on nonexistent
  `PBIServiceClient.delete_dataset` for cleanup. The guard leaves previous
  remote artifacts untouched; no remote operation was performed.
- **Local validation:** two mocked rolling guard regressions and nine mocked
  packaging tests passed (`tests/test_phase5_advanced.py::TestDeployerRollingBlocked`
  and `tests/test_phase5_advanced.py::TestDeployerTemporaryPackage`). The
  required full `python -m pytest tests\ --tb=short -q` passed; focused-file
  Ruff and Pyright passed. These checks do not establish remote behavior.
- **Next increment / hypothesis / scope:** rolling deployment, cleanup and
  rollback remain unimplemented and unverified. `Deployer` owns a future
  bounded design and implementation; `Tester` owns mocked regressions. First
  obtain an approved design with explicit destructive-operation authorization,
  safe canary identity, failure/status propagation and verified refresh. The
  hypothesis is that such a design can protect existing artifacts and report
  failures accurately; a collision, unconfirmed cleanup or false status in a
  regression falsifies it. Do not remove the guard before these controls are
  designed and tested.
- **Validation / exit / risks:** require mocked success, collision, refresh,
  cleanup and failure-propagation tests plus the full
  `python -m pytest tests\ --tb=short -q` suite. A separately authorized
  runtime rollback rehearsal is required for operational exit and is
  `not_run`; deployment and refresh are also `not_run`. The guard does not
  clean up or restore earlier artifacts. Source extraction, conversion, target
  generation and quality metrics are outside this remote-operation slice.

## Next BEx, InfoCube and SAP BW roadmap — 2026-11-23

**Planning only; no implementation or release authorization.** This sequence
refines BW-0–BW-8 below without replacing their dated evidence, open gates or
the parallel CI recovery work. Priorities order dependencies and risk, not
dates. Local declaration work can proceed independently of blocked native
source evidence; neither is proof of SAP identity or feature parity.

### Baseline and decision boundaries

- **Implemented locally, partial:** [BW inventory](schemas/sap_bw_inventory.schema.json)
  1.0 records declared objects and edges; [BEx semantic capture](schemas/sap_bw_bex_semantics.schema.json)
  1.0/1.1 records query, variables, filters, hierarchies, key-figure and
  authorization declarations. The [synthetic BEx fixture](fixtures/sap_bw_bex_semantics.partial.example.json)
  is an existing manifest v1.1 example retained for backward compatibility,
  not a v1.2 example; it has a filter but incomplete hierarchy and
  exception-aggregation evidence. The assessor checks direct query/provider
  and consumer edges, not transitive provider composition or SAP origin.
  Versions 1.0/1.1 do not distinguish restricted from calculated key figures;
  v1.2 adds declaration-only key-figure kind and requires direct provider
  bindings. Neither the v1.1 fixture declarations nor v1.2 declarations verify
  native InfoCube identity. Identity remains blocked pending a sanitized,
  source-owner-approved sample and agreed field mapping.
- **Implemented locally, partial:** the [PBIP plan](schemas/sap_bw_bex_pbip_plan.schema.json)
  1.0–1.6 describes one manually navigated BW cube, Import columns, optional
  local BEx linkage, explicit parameters/member properties and an optional
  column-only review table. Linked output reports selected key figures and
  variables plus counts, coverage and declared filter and hierarchy IDs and
  statuses for unconverted semantics. BW columns suppress implicit
  summarization; no BEx DAX measure is generated. This is a BW-connected
  transition draft, not an independent replacement.
- **Implemented locally, partial:** the [BEx vector contract](schemas/sap_bw_bex_result_vectors.schema.json)
  compares declared rows, keys, measures and matching context strings. Its
  [synthetic example](fixtures/sap_bw_bex_result_vectors.example.json) is not
  an independent SAP capture. References, `complete` declarations, matching
  hashes and a comparison pass do not authenticate evidence or establish
  coverage. Zero observations carry a limitation, not measure agreement.
- **Unsupported / unverified:** native SAP discovery and InfoCube identity,
  general BEx/ABAP conversion, automatic provider composition, BW analysis
  authorization equivalence and BW-independent ingestion are not established.
  The inventory has `infocube`, `adso`, `infoprovider` and
  `composite_provider` types, but no dedicated `multiprovider` type. Do not
  silently equate generic `infoprovider` with MultiProvider; MultiProvider-specific
  typed assessment is planned, not current coverage. A direct CompositeProvider
  edge is a declaration, not its joins or unions.
- **Connector evidence gate:** `bo_export/m_query_builder.py` already emits
  `Implementation="2.0"`. Microsoft Learn's
  [implementation details](https://learn.microsoft.com/en-us/power-query/connectors/sap-bw/implementation-details)
  say `ScaleMeasures` is deprecated and values are unscaled; scaling and
  reversed-sign display behavior must not be assumed equivalent. Check actual
  units, currency, dates/times and execution settings against the selected
  source and target. The
  [Fabric SAP BW application-server connector guidance](https://learn.microsoft.com/en-us/fabric/data-factory/connector-sap-bw-application-server)
  distinguishes Dataflow Gen2 prerequisites and Copy authentication support.
  Confirm supported versions, drivers, gateway and authentication for the
  chosen route rather than assuming them. Connectivity is coexistence, not
  a BW-independent replacement; these links are not runtime evidence.
- **Common implementation gate:** `Tester` runs the focused tests named below,
  `tests/test_agent_contracts.py` when contracts/ownership are affected, and
  `python -m pytest tests/ --tb=short -q` for every implementation slice.
  Preserve old contract versions, exact Unicode identifiers and negative
  cases; run relevant schema/fixture and CLI tests. Do not lower assertions,
  lint/type checks or the unchanged 80% CI coverage gate. Historical CI
  baselines above are not current measurements; hosted CI is `not_run`.
  `Documentation Guardian` reviews capability and documentation claims before
  and after any authorized implementation.

### P1-A delivered — identify unconverted filter and hierarchy declarations

- **Outcome / evidence:** the linked PBIP's `bex_linkage_assessment.json`
  now includes
  `bex_semantics_not_converted.unconverted_filter_declarations` and
  `bex_semantics_not_converted.unconverted_hierarchy_declarations`. Each
  list contains only `{id, status}` from the validated local manifest, in
  manifest order. Previously the summary exposed counts and coverage but
  not these individual IDs.
- **Hypothesis / delivered change:** additive report-only lists make declared
  omissions traceable without converting them; a missing/duplicated ID,
  changed order or list suggesting conversion falsifies that hypothesis.
  Existing counts, coverage, warning, gate, report schema version and
  `native_infocube_identity_verification: not_verified` remain unchanged.
- **Owner / scope:** `Orchestrator` owns
  `migrate_bw_bex_pbip.py` and its linkage evidence; `Tester` owns
  `tests/test_migrate_bw_bex_pbip.py`. This changes reporting only: no new
  input schema, M, DAX, model, visual, extraction, comparison or remote
  behavior. The new lists exclude names, selectors, evidence references and
  literals; identifiers themselves still require appropriate data handling.
- **Dependencies:** existing valid linked plan and local manifest only;
  **no native identity sample or SAP access required**. The additive report
  fields may affect consumers that reject unknown fields; existing plan
  versions and report fields remain supported.
- **Local validation / exit:** `Tester`'s regression checks Unicode, order,
  statuses, empty lists, absence of names/selectors/evidence/literals, and
  existing counts, coverage, warning, native identity and schema compatibility.
  The parent reports focused
  `python -m pytest tests\test_migrate_bw_bex_pbip.py --tb=short -q` exit 0
  (31 tests in `Tester`'s run); full
  `python -m pytest -o 'addopts=' tests\ --tb=short -q` passed 945 tests,
  1 skipped and 1333 subtests; required
  `python -m pytest tests\ --tb=short -q` exited 0; `git diff --check` passed.
  This is local report traceability, not BW-5 closure.
- **Risk / non-goal:** declarations do not establish source completeness,
  native SAP identity or filter/hierarchy semantics; zero items do not prove
  absence in SAP. Native InfoCube identity remains `not_verified`; SAP,
  Desktop/Power BI and Fabric runtime checks remain `not_run`.

### P1-B — owner-approved native InfoCube identity (blocked)

- **Outcome / evidence:** distinguish the declared provider from the actual
  native InfoCube before source-backed linkage or measure generation. Current
  plan cube ID, inventory `id`/`name`/`source_reference`, client and direct
  edge do not define a verified native identity mapping.
- **Hypothesis / first change:** a sanitized sample, provenance and field
  mapping explicitly approved by the BW source owner can support a bounded
  local consistency check; absent or ambiguous evidence cannot. First request
  that sample and mapping; if it does not fit the existing contract, stop for
  contract review rather than guessing an SAP API or identifier.
- **Owners / dependencies:** `Assessor` owns offline identity assessment;
  `Orchestrator` owns any approved linked-PBIP gate/plan changes; `Tester` owns
  regressions. Source-owner approval and meaning of the native field are
  **blocking external dependencies**, not dependencies of P1-A or P1-C.
  Live SAP discovery and direct-feed ownership remain unassigned.
- **Validation / exit:** after approval, exercise unique match, mismatch,
  missing, ambiguous and wrong-client cases, before-output refusal where
  applicable, and v1.0–1.6 compatibility; any new mandatory evidence gate
  needs an explicitly versioned opt-in so existing plans retain their prior
  behavior and unverified disclosure. Run
  `tests/test_bw_inventory_contract.py`, `tests/test_bw_bex_assessment.py`,
  `tests/test_migrate_bw_bex_pbip.py` and the common suite. Local exit requires
  traceability to the approved mapping and an honest distinction between a
  declaration check and live verification. SAP confirmation is `not_run`
  until separately authorized and performed.
- **Risk / non-goal:** this does not prove query membership, business grain,
  selectors or BEx equivalence; no source access or semantic conversion is
  authorized by obtaining a sample.

### P1-C delivered — declare key-figure kinds without converting them

- **Outcome / verified contract:** semantic manifest schema/validator v1.2
  supports a per-key-figure `kind` of `basic`, `restricted`, `calculated` or
  `unknown`; it continues to require the v1.1 provider bindings. Schema
  versions 1.0 and 1.1 retain legacy acceptance. CLI help now identifies
  manifest versions 1.0/1.1/1.2. Assessment report shape/schema remains 1.0
  for manifest 1.0/1.1; manifest 1.2 produces assessment output schema 1.1
  with `key_figure_kinds` entries containing `key_figure_id`, `declared_kind`,
  `declaration_boundary` and `assessment`. Its `verification` records
  identity/provenance and equivalence as `unverified`.
- **First change / evidence:** the versioned addition is declaration-only and
  exposes kind review without interpreting expressions or asserting source
  truth. `Dax` reviewed the vocabulary. The labels are bounded: `basic` does
  not imply additive, `SUM`, or aggregation-safe; `restricted` and
  `calculated` do not capture restriction/formula/dependencies and are not
  converted; `unknown` is explicitly unresolved. No kind changes gates,
  `gate_closed` remains false, and runtime status remains `not_run`.
- **Owners / dependencies / scope:** `Assessor` owns the offline manifest and
  assessment contract; `Tester` owns regressions; `Dax` reviewed terminology,
  not conversion. Local declarations only; independent of P1-B. P1-B native
  InfoCube identity remains blocked. No parser, expression evaluation, target
  generation, semantic conversion or SAP access is included.
- **Validation / exit:** focused
  `python -m pytest tests\test_bw_bex_assessment.py --tb=short -q` passed:
  20 passed, 49 subtests. Parent validation:
  `python -m pytest -o 'addopts=' tests\ --tb=short -q` passed 948 tests,
  1 skipped and 1352 subtests; required
  `python -m pytest tests\ --tb=short -q` exited 0. `py_compile`, JSON parse
  and `git diff --check` passed. This closes the local declaration contract
  only; it does not establish that any real SAP key figure has its declared
  kind or semantics.
- **Risk / non-goal:** kind alone omits formulas, nested restrictions,
  dependencies, units, exception aggregation and context. It establishes no
  aggregation safety, conversion, source identity, provenance or equivalence;
  no measures are generated from it.

### Delivered local BEx and InfoCube pilot — 2026-11-24

- **Outcome:** The [reproducible linked pilot](MIGRATION_REFERENCE.md#linked-bex-and-infocube-pilot)
  replays inventory 1.0, manifest 1.2 and plan 1.6 against one fictional query
  and its directly declared InfoCube. Local assessment reports no blockers
  and one review item; generation writes one Import table with three typed
  physical columns, a review visual, M exports and linkage evidence. It
  writes no DAX measures and does not change input contract versions.
- **Output gate:** The BW CLI checks the generated table reference, table,
  physical columns/types/aliases, lack of implicit summarization and one
  Import partition with the declared M query before producing exports or a
  linkage report. `Semantic` preserves explicit BW names such as `Unknown`,
  writes TMDL source aliases as text properties and uses the `Wiring` M
  encoder for the shared server expression. `Orchestrator` owns the CLI and
  pilot plan, `Assessor` the inventory/manifest fixtures, and `Tester` the
  regressions.
- **Local validation:** Windows/Python 3.12.16. The pilot passed strict
  static project validation with zero errors and warnings. Focused suites
  passed **93 tests and 451 subtests**. The full `python -m pytest` run with
  the unchanged 80% threshold passed **1,262 tests, 1 skipped and 1,434
  subtests** at **21,675/26,868 (80.67%)** coverage. At this milestone, the
  console collection issue had not yet been fixed and hosted CI had not run.
- **Standalone synthetic reconciliation (1.0):** The original offline replay
  compared two observations per case with no key discrepancies. It returned
  `pass`/0 for matching vectors and `fail`/1 for the changed target quantity
  (`12` vs `11` on `2026-11-24`). The full local suite passed **1,263 tests**
  with **1 skipped, 1,438 subtests and 80.67% coverage**. The comparator and
  schema were unchanged in that slice; the values were supplied, not queried
  from the PBIP.
- **Linked reconciliation follow-up:** `Orchestrator` and `Evidence` added the
  [opt-in plan check](SAP_BW_TO_FABRIC_DESIGN.md#link-the-vectors-to-one-declared-infocube-plan)
  for query, source system, project and selected key-figure declarations.
  Linked reports 1.1 distinguish row comparison from plan linkage and the
  requirement for a nonzero observation count. `Tester` covers agreement,
  mismatches, empty/duplicate-only vectors, bad declarations and old modes.
  No input schema, PBIP generator or BW-5 gate changed; the check is local.
  The documented replay produced `pass`/0 and `fail`/1 with two observations
  each; strict static PBIP validation passed without errors or warnings.
  Focused suites passed **86 tests and 478 subtests**. The full local console
  suite passed **1,268 tests, 1 skipped and 1,454 subtests** at **80.67%**
  coverage with the unchanged 80% threshold. Hosted CI was not verified.
- **Two-CSV preparation follow-up:** `Evidence` and `Orchestrator` added a
  [local packager](MIGRATION_REFERENCE.md#prepare-vectors-from-two-csv-captures)
  for independently prepared two-column CSVs, with one mapped text key and
  one numeric key figure using an exact rule. It writes the existing format
  for linked comparison without hand-entering JSON rows. The synthetic CSV
  replay compared two observations with no mismatch; a counterfactual change
  from `11.00` to `12.00` still packaged but failed linked comparison.
  Focused suites passed **96 tests and 509 subtests**. The full local console
  suite passed **1,278 tests, 1 skipped and 1,485 subtests** at **80.72%**
  coverage with the unchanged 80% threshold. This does not capture real
  results, verify provenance or change P1-B, P1-D or the BW-5 gate.
- **Direct CSV comparison follow-up:** `Orchestrator` added an
  [opt-in CSV mode](MIGRATION_REFERENCE.md#compare-two-csv-captures-directly)
  on the reconciliation CLI. It requires the complete plan/inventory/semantics
  trio and writes only the final linked report 1.1. The two-step mode remains
  available for vector review. The documented direct replay produced one
  report with two compared observations and no mismatch. Regression tests
  verify identical direct and two-step reports for matching, mismatched and
  header-only inputs. Focused suites passed **100 tests and 524 subtests**;
  the full local suite passed **1,282 tests, 1 skipped and 1,500 subtests**
  at **80.72%** coverage against the unchanged 80% threshold. This does not
  change the source-evidence or approval requirements; hosted CI was not verified.
- **Local pilot orchestration:** `Orchestrator` now assembles assessment,
  linked PBIP generation, strict static quality and direct CSV reconciliation
  in `migrate_bw_bex_pilot.py --bundle <bundle.json>`. A portable JSON bundle
  replaces seven repeated command-line paths; the explicit form remains for
  diagnostics. It snapshots inputs, stages outputs privately
  and publishes only a new final directory. `Tester` covers pass, mismatch,
  empty captures, invalid declarations and destination safety. This is a local
  review workflow only; SAP execution, Power BI refresh, Fabric deployment,
  native identity and business approval remain outside its scope.
- **Next real pilot:** The [owner handoff](MIGRATION_REFERENCE.md#collect-evidence-for-an-authorized-pilot)
  records the prerequisites for comparing real results. P1-B and P1-D remain
  blocked on a sanitized, source-owner-approved native InfoCube sample, query
  definition and agreed field mapping. Then compare independently captured
  source and target results for one selected key figure at the same grain,
  role and prompt context. The synthetic fixture is not SAP evidence: `gate_closed`
  is false, native identity is `not_verified`, and SAP, Desktop, refresh,
  Fabric and equivalence checks remain `not_run`.

### P1-D — query semantics and source-backed mapping (blocked for conversion)

- **Outcome / evidence:** map one selected BEx query's variables, filters,
  hierarchy and key figures to an agreed target design, without confusing a
  selector or variable-ID association with source behavior. Plan 1.5 links
  variable IDs to manually specified parameter selectors and literal lists;
  it does not establish prompt defaults, range/exclusion semantics or results.
- **Hypothesis / first change:** one source-owner-approved, sanitized query
  definition, field mapping and independently captured cases can resolve a
  single feature's source meaning. Request these plus query/provider identity,
  formula/restriction definitions, fiscal and time-dependent hierarchy
  context, units/currency and authorization scope. Until approved, synthetic
  documentation and P1-A/P1-C declarations are safe; parser and semantic
  translation are blocked. A matching declared hash alone is insufficient.
- **Owners / dependencies:** `Assessor` owns the offline BEx contract;
  `Extractor` is a proposed local parser collaborator only after source format
  and ownership are agreed; `Wiring` owns M, `Semantic` the model, `Dax`
  formulas, `Visual` the report and `Evidence` comparisons. Assign a live
  SAP connectivity owner before any live implementation. Identity for an
  InfoCube-linked conversion depends on P1-B; use BW-0/1 scope and BW-6
  controls. Source/business-owner review is separate from repository roles.
- **Validation / exit:** plan separate feature cases for mandatory/optional
  variables, defaults and ranges/exclusions; fixed versus dynamic filters;
  hierarchy version, level, parent/child and time validity; plus query grain,
  fiscal periods, nulls and units. Include positive and negative/mismatched
  local declarations in `tests/test_bw_bex_assessment.py` and
  `tests/test_sap_bw_m_query.py`, relevant owner tests and the common suite.
  A feature exits only with approved mapping and independently obtained
  source/target results at agreed role, prompts and grain; otherwise it stays
  blocked. SAP and Power BI execution are `not_run` here.
- **Risk / non-goal:** no automatic BEx query/report translation, source
  identity, hierarchy or prompt parity follows from a static M expression.

### P2-A — bounded key-figure semantics, not general formula migration

- **Outcome / evidence:** independently validate a single selected key figure
  before considering target generation. The 1.1 manifest can record exception
  aggregation and currency, but neither a provider binding nor a `SUM` label
  proves safe aggregation; implicit BW column summarization is disabled.
- **Hypothesis / first change:** after P1-B/P1-D, an owner-approved additive
  basic figure with no exception aggregation and explicit unit/currency rules
  can be evaluated against independently captured detailed and total cases.
  First define that one case and its exclusions; only then scope any opt-in
  DAX/model measure. Restricted and calculated figures require separate
  approved selection/formula, dependency and evaluation-context mappings;
  exception aggregation additionally needs its reference characteristic,
  inner/outer grain, totals and hierarchy/time context. Unknowns block.
- **Owners / dependencies:** `Dax` owns any formula conversion, `Semantic`
  target model, `Assessor` source declarations, `Evidence` result comparison
  and `Tester` tests. Requires native identity, approved query and semantics,
  source-to-target mapping, independently captured vectors and business
  approval of units, rounding and tolerances. P1-C classification alone is not
  sufficient.
- **Validation / exit:** synthetic local tests for detail versus totals,
  nulls, duplicates, scale/sign display versus underlying values, mixed
  units/currencies, date/time typing and rejection of restriction, formula or
  exception-aggregation unknowns; run
  `tests/test_bw_bex_assessment.py`, `tests/test_sap_bw_m_query.py`,
  `tests/test_bw_reconciliation.py`, affected DAX/model tests and the common
  suite. Real-case exit additionally compares approved SAP and target results
  across grain, role, period and hierarchy levels and records discrepancies
  and owner acceptance. Runtime is `not_run`; no general RKF/CKF or exception
  aggregation conversion is promised.
- **Risk / non-goal:** matching detail rows may still yield wrong grand totals;
  do not generate a guessed measure or weaken evidence thresholds.

### P1/P2-B — provider lineage and source mapping

- **Outcome / evidence:** the bounded local declaration-trace slice is
  implemented as `trace_declared_lineage(snapshot, selected_object_id,
  scope_object_ids)` in `powerbi_import/bw_inventory.py`. It validates an
  explicit unique scope of known objects containing the selected object,
  traverses resolved declarations in either direction with cycle-safe O(V+E)
  BFS, and preserves each declaration's direction and status in the report.
  Unresolved or unknown declarations touching reached objects are reported,
  not traversed. This is report-only local evidence: BW-0/BW-5 gates are
  unchanged. The
  [partial inventory fixture](fixtures/sap_bw_inventory.partial.example.json)
  remains incomplete; MultiProvider has no dedicated inventory type and
  provider composition or transitive lineage completeness is not established.
- **Hypothesis / first change:** the bounded first change is delivered by
  `Assessor` in `powerbi_import/bw_inventory.py`, with graph tests owned by
  `Tester`. It exposes declarations within the caller's explicit scope without
  inferring composition from names or claiming that reachability proves
  dependency semantics. Keep MultiProvider as a documented unknown/generic
  declaration until a reviewed versioned contract distinguishes it; do not
  classify a generic InfoProvider automatically. Synthetic local graph work
  does not need P1-B.
- **Dependencies / later source work:** source-owner approvals remain blocked
  for actual object identities, provider membership, ADSO activation/change/
  delete and history, InfoCube identity, grain and aggregation,
  CompositeProvider joins/unions, MultiProvider harmonization/precedence,
  master data and upstream mappings. Provider composition and lineage
  completeness remain unverified. `Fabric` owns any later staged mapping;
  source-definition parsing and direct-feed owners/formats must be explicitly
  assigned before implementation.
- **Validation / exit:** focused three-file validation passed:
  `tests/test_bw_inventory_contract.py`,
  `tests/test_bw_inventory_assessment.py` and
  `tests/test_bw_bex_assessment.py`; the assessment file passed 13 tests. The
  full suite command `python -m pytest tests/ --tb=short -q` exited 0 (quiet
  output omitted the numeric summary). Source-backed exit needs an approved
  inventory and mapping per edge, identity, grain and disposition; unknown
  composition blocks its wave. Runtime is `not_run`. No generic provider
  conversion.
- **Risk / non-goal:** a reachable graph does not prove source coverage,
  join cardinality, data correctness or absence of unrecorded dependencies
  or hidden consumers.

### P1/P2-C — security and operational controls

- **Outcome / evidence:** track one role's allowed and denied access and
  planning/compliance obligations independently of a model draft. The
  [BW controls contract](schemas/sap_bw_controls.schema.json) and
  [partial fixture](fixtures/sap_bw_controls.partial.example.json) record
  declarations and fixed `not_run` scenarios, not deployed authorization.
- **Hypothesis / first change:** an owner-reviewed role-by-data matrix and
  explicit planning/write-back, audit, retention and recovery dispositions
  can reveal a missing control. First obtain sanitized owner-approved
  scenarios; local synthetic negative cases may proceed without SAP identity.
  `Assessor` owns controls assessment; `Semantic` designs applicable RLS;
  `Deployer` owns separately authorized binding/access execution; `Evidence`
  records results; `Tester` owns tests.
- **Dependencies / validation:** query/provider scope, named security,
  business and compliance owners, identity and target design. Test missing
  owners, unknown scope, both allowed/denied scenarios and undeclared planning
  obligations in `tests/test_bw_controls_assessment.py`, plus common suite.
  Exit requires separately authorized role impersonation and allow/deny tests,
  planning locks/write-back/recovery where applicable, and owner sign-off.
- **Risk / non-goal:** local RLS or a reference is not authorization proof;
  unsupported write-back or missing retention disposition blocks retirement.

### P2-D — staged Fabric versus BW-connected transition

- **Outcome / evidence:** choose and evidence two distinct routes. The Import
  PBIP still queries BW on refresh; staged Bronze reads explicitly staged
  Parquet, and the bounded conversion notebook supports declared transfers,
  typed constants and same-scale decimal add/subtract. These local artifacts
  do not extract BW, parse ABAP or create an independent upstream feed.
- **Hypothesis / first change:** a frozen source snapshot plus a separately
  sourced delta feed and reviewed transformations can sustain one target
  without BW. First obtain owner-approved snapshot grain, upstream field
  mapping, watermark, delete/replay contract and source definition; identify
  and assign the direct-feed owner. A BW connector or BW-managed queue in the
  steady state falsifies independence.
- **Owners / dependencies:** `Fabric` owns staged notebook generation and
  `Orchestrator` its CLIs; `Assessor` source declarations, `Evidence`
  snapshot/handoff/vector checks, `Deployer` authorized binding/runtime and
  `Tester` tests. Depends on P1/P2-B, BW-2/3/4 and source-owner approvals;
  source extraction and any direct-upstream connector are separate, currently
  unassigned implementation surfaces.
- **Validation / exit:** local cases cover snapshot counts and keys, duplicate,
  overlap/gap, late arrival, delete, restart and drift, rule/hash mismatch and
  no-overwrite. For any separately authorized BW-connected route, verify
  applicable connector version, driver, gateway, authentication, execution
  settings, date/time and scale/unit behavior with the actual source and
  target. Run `tests/test_bw_bronze_generator.py`,
  `tests/test_bw_handoff.py`, `tests/test_bw_transform_generator.py`,
  `tests/test_bw_transform_validation.py`, `tests/test_bw_reconciliation.py`
  and common suite. Operational exit requires authorized SAP/source and Fabric
  execution, independently captured reconciliation, recovery and an observed
  BW-unavailable period; all are `not_run` here.
- **Risk / non-goal:** a staged snapshot alone does not provide continuity,
  transformation equivalence, security or retirement.

### P2/P3-E — independent evidence, transition and cutover

- **Outcome / evidence:** accept each consumer and wave only on independently
  reviewed feature and operational evidence. BEx vector comparison checks
  supplied context strings and rows; BW-7/8 assess declarations, and BW-8
  checks direct incident edges only. Neither authenticates references or
  authorizes cutover.
- **Hypothesis / first change:** independent captures for the same query,
  prompt, access role, filter, hierarchy, period and grain expose mismatched
  values and totals. `Evidence` first prepares feature-scoped positive and
  negative synthetic comparison cases, retaining the already implemented
  zero-observation limitation; do not interpret the vector field `role` or a
  reference as authenticated identity.
  `Reviewer` reviews acceptance, `Orchestrator` coordinates the wave, and
  `Tester` owns regressions.
- **Dependencies / validation:** BW-0–BW-7, approved independent feeds,
  feature and security evidence, source/business/security/compliance and
  operations owners, tolerances, parallel-run window and rollback objectives.
  Run `tests/test_bw_reconciliation.py`, `tests/test_bw_wave_evidence_index.py`,
  `tests/test_bw_cutover_assessment.py` and the common suite. Test context
  mismatch, zero observations, duplicate/missing keys, failed evidence,
  unresolved dependencies and absent approvals; no gate closes from a local
  candidate status.
- **Exit / risks / non-goals:** independently capture and review SAP and Power
  BI/Fabric results, refresh, access and consumer acceptance; exercise
  rollback, demonstrate all feeds and consumers while BW is unavailable,
  reconcile unresolved exceptions and obtain separate go/no-go and retirement
  approvals. SAP, Desktop/Power BI, Fabric, live access, refresh, rollback,
  cutover, retirement and owner approval are all `not_run` here; source
  authenticity remains `not_verified`. No automatic decommission or broad
  equivalence claim follows.

## Detailed delivery and priority snapshot — 2026-11-22

This sequence is **planned**, not authorization to implement or release. It
extends the cross-source and BW plans below without replacing their historical
evidence or feature gates. P1 orders the next risk-reducing slices; P2 extends
them; runtime and retirement are separate approval gates, not dates. Work can
proceed locally while source owners prepare the blocked evidence.

The previously recorded full local run was **941 passed, 1 skipped and 1329
subtests**, following the schedule guard. The subsequent synthetic WebI
regression and required full suite passed locally, with no total recorded. The historical CI-equivalent
coverage was **55.33% against the unchanged 80% threshold**; the recorded
Ruff/Pyright baseline is also failing and is not a current measurement. Hosted
CI remains `not_run`. Counts and a passing local suite do not establish feature
coverage or migration equivalence.

### P1 delivered — expose a comparison with no measure observations

- **Outcome / evidence:** the original synthetic-fixture probe remains the
  historical baseline: with both `rows` lists empty, the comparison returned
  `comparison_status: pass`, `measures_compared: 0`, and zero source and target
  rows. This matched the supplied empty declarations, not evidence of query
  execution or measure agreement. The implementation now adds the report
  limitation `no_measure_observations_compared` iff summary
  `measures_compared == 0`. After a successful report write, the CLI emits:
  `No measure observations were compared; this result does not establish
  measure agreement.`
- **First change / cohesive scope:** `Evidence` updated
  `powerbi_import/bw_reconciliation.py` for the report limitation;
  `Orchestrator` updated `migrate_bw_reconcile.py` for the CLI notice; and
  `Tester` added regression coverage in `tests/test_bw_reconciliation.py`.
  This completed the local comparison/reporting slice only; extraction,
  conversion, target generation and remote operations were not changed.
- **Dependencies / compatibility:** version 1.0 schema is unchanged.
  Mathematical `comparison_status`, the empty/empty pass, and exit code 0
  remain unchanged in standalone mode. The later linked mode adds a
  separate observation requirement. Runtime evidence remains `not_run` and
  verification remains `not_verified`.
- **Validation / exit:** focused tests passed: 18 tests / 30 subtests. The
  full `python -m pytest tests\ --tb=short -q` exited 0; its output did not
  include total counts. `py_compile` and `git diff --check` passed. Tests cover
  both-empty, one-empty, disjoint-key, duplicate-only and matching nonempty
  cases, plus CLI notice/no-overwrite behavior and preserved statuses.
- **Risks / non-goals:** the limitation and notice identify that no measure
  observations were compared; they do not establish source provenance,
  completeness, query execution or source-to-target parity. No runtime
  operation or release approval is implied.

### P1 parallel — CI recovery and behavior-based coverage

- **Outcome / evidence:** recover the existing CI gates and add discriminating
  tests for real risk, not merely lines. The historical local run failed the
  80% coverage gate and had lint/type findings; `.github/workflows/ci.yml`
  runs lint before the OS/Python test matrix and synthetic validation. The
  later 941-pass run was not a hosted CI or coverage-gate pass.
- **Bounded local change — Visual:** `Visual` removed seven duplicate literal
  keys from the PBI pass-through section of
  `powerbi_import/visual_generator.py`. Each retained earlier mapping has the
  identical value, so this is intended behavior-preserving lint cleanup.
  The required `python -m pytest tests/ --tb=short -q` exited 0 (runner output
  had no totals); `ruff check bo_export/ powerbi_import/ --select F601`,
  `python -m py_compile powerbi_import/visual_generator.py`, and scoped
  `git diff --check` passed.
- **Latest bounded local cleanup — Visual:** `Visual` fixed the remaining
  import-order I001 and two needless-f-prefix F541 findings in
  `powerbi_import/visual_generator.py`. The latest
  `ruff check powerbi_import/visual_generator.py`,
  `ruff check bo_export/ powerbi_import/ --select F601`,
  `python -m py_compile powerbi_import/visual_generator.py`, scoped
  `git diff --check`, and required `python -m pytest tests/ --tb=short -q`
  passed; the full-suite runner output had no totals. These are bounded local
  results, not evidence that repository-wide Ruff or Pyright, the unchanged
  80% coverage gate, hosted CI, or overall CI passed.
- **Latest bounded local cleanup — Deployer:** `Deployer` removed redundant
  f prefixes from two literal report headings in
  `powerbi_import/deploy/utils.py`, preserving the emitted text. After the
  change, `python -m pytest tests/ --tb=short -q` exited 0 (runner output had
  no totals); `ruff check powerbi_import/deploy/utils.py --select F541`,
  `ruff check powerbi_import/visual_generator.py`,
  `python -m py_compile powerbi_import/deploy/utils.py`, and scoped
  `git diff --check` passed. That focused cleanup alone did not establish a
  repository-wide Ruff count or overall CI recovery.
- **Bounded local cleanup and fresh CI-scope evidence — Deployer:** on the
  dirty worktree, Python 3.13.15 / Ruff 0.16.7
  `python -m ruff check bo_export\ powerbi_import\ --statistics` found **409**
  issues before this cleanup: 183 W293, 71 F401, 63 I001, 45 F541, 26 F841,
  6 W291, 4 W292, 3 E402, 3 E712, 2 E741, 2 W605 and 1 E713. `Deployer`
  removed two unused `os` imports, sorted affected imports and dropped only
  the unused local assignment around `client.patch`, retaining the call and
  behavior, in `powerbi_import/deploy/deployer.py` and `utils.py`. Scoped
  Ruff passed. Afterward the same CI-scope command still failed with **404**
  findings: 183 W293, 69 F401, 61 I001, 45 F541, 25 F841, 6 W291, 4 W292,
  3 E402, 3 E712, 2 E741, 2 W605 and 1 E713.
- **Local validation and limits:** `python -m pytest tests\ --tb=short -q`
  exited 0 after the cleanup; the runner gave no totals. A fake-client smoke
  checked endorsement success, failure, endpoint and payload, plus report
  headings/output; no network calls were made. `py_compile` and scoped
  `git diff --check` passed. Before cleanup,
  `python -m pyright powerbi_import\deploy\` reported **15 errors, 0
  warnings**, including missing optional imports, `None`-inferred
  `BundleDeploymentResult` attributes and one inferred heterogeneous-dict
  error; no Pyright fixes are claimed. The coverage gate and hosted CI were
  not rerun and remain unproven; deployment and target runtime are `not_run`.
- **Earlier measured CI-gate baseline — dirty worktree, before the Deployer
  cleanup:** a consistent-interpreter run used Python 3.13.15, pytest 9.1.1,
  pytest-cov 7.1.0, Ruff 0.15.7,
  Pyright 1.1.414, and Flake8 7.4.1. The critical Flake8 command exited 0 with
  one `SyntaxWarning` for an invalid escape sequence. Full
  `ruff check bo_export/ powerbi_import/ --statistics` exited 1 with 411
  findings: 183 W293, 71 F401, 63 I001, 47 F541, 26 F841, 6 W291, 4 W292,
  3 E402, 3 E712, 2 E741, 2 W605, 1 E713. Pyright's JSON summary reported
  113 files, 74 errors and 2 warnings (exit 1). The coverage command
  `python -m pytest -o 'addopts=' tests/ --tb=short -q --cov=bo_export --cov=powerbi_import --cov-report=term-missing --cov-fail-under=80`
  used Python 3.13.15 and reported 944 passed, 1 skipped, 1333 subtests,
  and 55.71% coverage; it exited 1 against the unchanged 80% gate. This is
  an earlier local dirty-worktree baseline, not a clean-tree or overall CI
  pass. The 411/47 findings remain tied to this earlier Ruff 0.15.7 baseline,
  not the current CI-scope count; they are not a like-for-like comparison
  with Ruff 0.16.7. Earlier measurements above remain historical; hosted CI
  is `not_run`.
- **Hypothesis / first change:** this consistent-interpreter run confirms
  unresolved local Ruff, Pyright and coverage gates on the dirty worktree.
  `Tester` coordinates bounded lint/type fixes with the primary owners in
  `.github/agents/ownership.json`, without lowering thresholds. For behavior
  coverage, start with the
  zero-observation comparison above and its failure cases, not a bulk
  line-coverage exercise. No code change is authorized by this roadmap.
- **Dependencies / scope:** `Tester` coordinates; affected code owners fix
  their own files, and `Orchestrator` coordinates CI workflow changes only if
  genuinely required. Avoid broad refactors, exclusions, weaker assertions or
  changes to the required 80% gate. Report coverage and behavior as separate
  results. Protect the current rolling block and disabled schedule drafts.
- **Validation / exit:** run the unchanged flake8, Ruff and Pyright commands
  from CI, focused owner tests, and
  `python -m pytest tests/ --tb=short -q`; also run CI's
  `--cov=bo_export --cov=powerbi_import --cov-report=term-missing
  --cov-fail-under=80` coverage command. Local exit requires all unchanged
  checks to pass, with meaningful negative tests. Hosted exit additionally
  requires the actual configured OS/Python matrix and dependent validation
  job to pass when hosted CI is separately available; until then it is
  `not_run`. A local baseline failure is a finding, not a reason to weaken CI.
- **Risks / non-goals:** clean lint and a coverage percentage do not establish
  correct source semantics; a single-platform local run is not the hosted
  matrix. No release approval follows automatically.

### P1 delivered — preserve the synthetic WebI binding finding

- **Outcome / evidence:** `Tester` added the focused regression in
  `tests/test_cli.py:405`, making the existing synthetic sample's unresolved
  visual/model binding visible independently of whether default static
  validation returns zero. It checks actual generated visual references
  against model columns/measures and retains unknown `Entity "Table"`
  findings. The sample's chart/provider and physical-column relationship is
  not established.
- **Hypothesis / first change:** a focused synthetic regression that checks the
  actual generated visual references against model columns and asserts the
  unresolved finding can detect a silently lost warning without pretending
  to resolve the binding. A missing warning or a claimed resolved binding
  without a real model column falsifies this test hypothesis.
- **Owner / dependencies / scope:** `WebI Migration` coordinates; `Tester`
  owns the regression, `Visual` owns PBIR generation and `Assessor` owns
  static validation. Use the existing synthetic sample and local artifacts
  in temporary directories. If investigation identifies a generation defect,
  return it to `Visual`; do not change the validator, warning severity or a
  metric merely to make the sample green. This is target/static-reporting
  evidence, not proof of source extraction or provider linkage.
- **Validation / exit:** the focused regression and required
  `python -m pytest tests/ --tb=short -q` passed. The regression preserves the
  unresolved finding despite default static-validation exit 0. A clean feature
  gate additionally requires the source-backed binding slice below, not
  warning suppression.
- **Risks / non-goals:** sample shape and validator wording may evolve, so
  assert structured facts where available rather than historical warning
  counts. Synthetic data does not establish source identity, rendering or
  visual equivalence; Desktop and service execution remain `not_run`.

### P1 blocked — source-backed feature linkage

- **Outcome / evidence:** trace one real source feature to the correct
  generated binding. The WebI snapshot validates document/provider IDs for a
  selected query plan, but no approved report-element/provider linkage is
  available. BW native InfoCube identity is likewise `not_verified` pending a
  sanitized source-owner-approved sample and agreed field mapping. These are
  independent blockers; neither synthetic fixture proves either relation.
- **Hypothesis / first change:** for each source, an approved, versioned,
  sanitized example or verified source contract plus a reviewed field mapping
  can support a unique binding. Ask the respective source owner for that
  evidence before contract or generator changes; missing or ambiguous identity
  must stay unresolved. No CMS/SAP access is authorized by this plan.
- **Owners / dependencies / scope:** `WebI Migration` coordinates
  `BusinessObjects` for the CMS contract, `Extractor` for local metadata,
  `Wiring` for query mapping, `Semantic` for model columns and `Visual` for
  PBIR; `Assessor` validates generated artifacts. For BW, `Assessor` owns the
  local inventory/identity assessment and `Evidence` comparisons; assign
  any new live SAP connector owner explicitly before implementation. Apply
  analogous family-specific evidence gates to Crystal, universes, BIAR, Lumira
  and DeskI rather than assuming WebI evidence generalizes.
- **Validation / exit:** after approval, test matching, missing, mismatched
  and ambiguous identities and preserve source IDs across each applicable
  stage. Verify a generated binding points to an actual model column, retain
  unresolved findings, and run focused tests plus
  `python -m pytest tests/ --tb=short -q`. Source-owner review of provenance
  and completeness is a separate gate; local tests alone cannot close it.
- **Risks / non-goals:** do not infer relationships from generic names,
  decrypt protected content, claim archive completeness, or implement an
  additive BW key figure before its separate identity and semantics gates.
  Local generation does not establish data or visual equivalence.

### P2 — independently reviewed, feature-scoped comparison

- **Outcome / evidence:** progress from declaration-only reports to a
  reviewable, bounded source-to-target evidence chain. The feature ledger
  does not dereference or authenticate evidence; the BEx comparator compares
  declared rows and validates declared context, not source origin or
  completeness.
- **Hypothesis / first change:** after an approved source/target pair exists,
  `Evidence` can record one explicit feature identity, target object, query
  context, comparison results and unresolved findings for independent review.
  First prepare a synthetic local positive and negative review case using the
  existing ledger and comparator; treat references as declarations, not
  authenticated links. Do not invent a real wave or automatically convert a
  comparator pass into an `implemented` ledger status.
- **Owners / dependencies / scope:** `Evidence` owns comparison and ledger
  behavior; `Orchestrator` owns their CLIs; `Tester` owns tests; `Reviewer`
  reviews fidelity. Real feature linkage depends on the relevant approved
  source and target artifacts, common role, filters, prompts, grain and
  agreed tolerances. Extraction, conversion, generation, reporting and
  operations stay separately identified in the ledger.
- **Validation / exit:** local tests must preserve failed/missing evidence,
  mismatched context, zero-observation limitations and unverified references,
  then run the relevant focused suites and
  `python -m pytest tests/ --tb=short -q`. Real-case exit additionally
  requires independently captured source and target results, discrepancy
  disposition and source/business owner review. Synthetic success alone
  never closes a feature or wave.
- **Risks / non-goals:** row agreement at a declared grain is not proof of
  visual, security, operational or fleet-wide parity. No automatic evidence
  authentication, deployment or business sign-off is planned in this slice.

### Separately authorized runtime and cutover gates

- **Outcome / evidence:** validate a reviewed feature in its actual target
  only after local and source-evidence gates. Schedule deployment now rejects
  incomplete enabled declarations, generated schedules remain disabled
  drafts, and rolling deployment is blocked; none proves runtime behavior.
- **Hypothesis / first change:** a specifically authorized target check can
  reproduce the reviewed source result and required access/operation behavior;
  discrepancies or missing authorization keep the feature open. First obtain
  named source, business, security and target owners, approved scope,
  credentials handling, non-destructive test plan and explicit permission for
  each read or write. Do not remove the rolling guard as a prerequisite.
- **Owners / dependencies / scope:** `Deployer` owns separately authorized
  deployment, readback, refresh and access checks; `Evidence` owns result
  reconciliation, `Reviewer` the acceptance review, and `Visual`/`Fabric` or
  `Semantic` own any resulting local fixes. A BW wave additionally requires
  its BW-0–BW-8 dependencies and independent upstream handoff before retirement.
- **Validation / exit:** for the agreed case, capture source and target query
  context and results, authorized Desktop/Report Builder rendering where
  applicable, allow/deny security checks, approved schedule readback and
  observed refresh, with discrepancy and owner sign-off. Cutover additionally
  requires approved rollback rehearsal, operational readiness and business
  acceptance. All such runtime checks, deployment and cutover are `not_run`
  here; no cloud writes, Desktop launch or release approval are authorized.
- **Risks / non-goals:** target validation is not blanket source-family
  parity. Publications, planning/write-back and unsupported source features
  require separately owned dispositions rather than silent replacement.

## Cross-source roadmap snapshot — 2026-11-22

**Goal:** work toward comprehensive, equivalent migration of each inventoried
source feature to an appropriate Power BI, Fabric or paginated RDL target.
This is a feature-by-feature program, not a universal parity claim. The
[gap analysis](GAP_ANALYSIS.md) and the dated evidence above describe current
behavior; historical phase labels and aggregate counts do not close these
gates. The separate BW program and its identity blocker remain in force below.

**Coverage ledger for each migration wave:** the offline declaration API and
standalone CLI are implemented for the bounded contract below; collecting and
independently reviewing real wave evidence remains open. Record each source
version, document and feature instance, declared source evidence and
provenance, target choice and object/binding, owner, dependency, status,
manual action and disposition, and local and runtime evidence references.
The validator checks the required declarations for `implemented`; it does not
verify that the declared scope or tests are true. Use `partial` for narrower
coverage and `unverified` when identity, completeness or target behavior
lacks evidence. Track extraction, conversion, target generation, reporting and
remote operations separately. Do not treat a placeholder, successful artifact
generation, declared mapping or count as parity. The following baseline is a
planning summary, not a populated wave ledger.

| Source feature / domain | Current bounded status and target direction | Dependency / primary owner |
|---|---|---|
| WebI providers, prompts and report bindings | Partial: WID structure and `PARAMSERVER` are not SQL, prompt semantics or bindings; snapshot-to-model can leave an empty report. PBIP/RDL/Fabric are target options, not verified equivalents. | Authorized source evidence or verified export; `Extractor`, `BusinessObjects`; `WebI Migration` coordinates. |
| Crystal fields, formulas, sections, groups, subreports and prompts | Partial recognized metadata/mappings; real `.rpt` streams in the dated replay were opaque. PBIP or RDL requires trustworthy exports and feature review. | Versioned source export/SDK evidence; `Extractor`, then `Dax`, `Visual`. |
| UNX/UNV objects, tables, joins, contexts, derived SQL, LOV and security | Partial and format-dependent; sampled protected UNX components were unreadable and sampled UNV exposed names only. Model/M/Fabric mappings require verified metadata. | Authorized readable exports, query and connection lineage; `Extractor`, `Wiring`, `Semantic`. |
| BIAR/LCMBIAR contents and CMS lineage | Partial: direct entries and readable manifest are not a complete archive; manifest-derived RDLs are unbound skeletons. | Inventory/provenance and source coverage review; `Extractor`, `Orchestrator`, `Visual`. |
| Lumira data bindings, charts, interactions and apps | Partial format-dependent extraction; Designer app conversion is unsupported. PBIP/Fabric/RDL suitability is feature-specific; custom interactions may require a separate rebuild. | Representative authorized exports and target design; `Extractor`, `Visual`, `Fabric`. |
| DeskI REP providers, formulas, prompts and layout | Experimental partial candidates; explicitly acknowledged RDL and manually declared PBIP drafts are not automatic conversion. Fabric conversion is unsupported. | Reviewed SQL, bindings, fields and source design; `Extractor`, `Visual`, `Wiring`. |
| BW/BW/4HANA inventory, transformations, BEx, security and retirement | Separate partial offline declarations, assessments and bounded generators; no automatic SAP extraction or general BEx conversion. BW identity is `not_verified`. | BW-0–BW-8 evidence and native identity gate below; `Assessor`, `Fabric`, `Evidence`. |
| Queries, formulas, relationships, grain, filters and prompts across sources | Partial metadata-dependent M/DAX/model candidates, not proven semantic equivalence. | Verified source expressions, bindings, types and query context; `Wiring`, `Dax`, `Semantic`. |
| Visuals, pagination, interaction and accessibility | Partial PBIP/RDL mappings or manual declarations; native report layouts are not generally reconstructed. | Source element bindings and target-specific design; `Visual`. |
| Security, schedules, publications, monitoring and deployment | Partial: newly generated RLS assignment scripts block for manual review; refresh and subscription drafts are disabled. Automatic RLS assignment and direct conversion of full BO scheduling/publications are unsupported. CLI deployment is guarded; target runtime is unverified. | Source policy and operational inventory, explicit separate deployment authorization and owner decisions; `Deployer`, `Assessor`. |
| Comparison, reconciliation and cutover | Partial local static and declared-vector evidence; no blanket source-to-target or retirement proof. | Trusted source/target results and approved scope, roles and tolerances; `Evidence`, `Reviewer`, `Deployer`. |

### Delivered local P1 — offline feature coverage declarations (2026-11-22)

- **Outcome / evidence:** `powerbi_import/coverage_ledger.py` validates a
  version 1.0 manifest and produces a deterministic, detached report with
  declared rows, status/stage counts and review findings. The
  [schema](schemas/feature_coverage_ledger.schema.json) and
  [synthetic fixture](fixtures/feature_coverage_ledger.synthetic.example.json)
  describe the contract; the fixture is fictional, not source evidence.
  `migrate_coverage_ledger.py --manifest <local.json> --output <new.json>`
  reads a local manifest and writes a new report without overwriting an
  existing file. Invalid JSON, duplicate JSON keys and invalid declarations
  are rejected.
- **Hypothesis / cohesive scope:** inconsistent or duplicate
  source-kind/version/document/feature/stage declarations must be rejected,
  while missing evidence and non-implemented statuses remain visible as
  findings. A rejected input producing a report or a declaration changing a
  verification status would falsify this local contract. This is reporting
  over supplied declarations, not extraction, conversion, target generation
  or remote operations. `Evidence` owns the API, schema and fixture;
  `Orchestrator` owns the CLI; `Tester` owns regressions.
- **Dependencies / first change delivered:** callers supply the manifest and
  a new local output path. The validator preserves unknowns, checks
  case-sensitive composite uniqueness and enforces conditional fields. An
  `implemented` row requires declared source identity/provenance, scope and
  passing local check; applicable targets require a choice and binding, and
  implemented remote operations require a declared runtime pass. These are
  declarations, including any pass or approval, not independent evidence.
- **Validation / exit gate:** `tests/test_coverage_ledger.py` exercises
  contract failures, duplicate identities and JSON keys, deterministic output,
  non-execution of references and commands, and CLI output boundaries. Run
  `python -m pytest tests/test_coverage_ledger.py --tb=short -q` and the
  required `python -m pytest tests/ --tb=short -q`; local tests establish only
  the bounded contract. Per-wave exit additionally requires independently
  reviewed source identity, coverage, target behavior and business evidence.
- **Risks / non-goals:** the ledger never authenticates or dereferences
  references or executes declared checks or commands. Credential-like content
  is screened, but credential detection and sanitization are not guaranteed;
  manifests and reports may contain sensitive metadata. Counts cover only
  supplied rows and neither completeness nor semantic equivalence. Evidence
  authenticity, freshness, source coverage, feature coverage, equivalence and
  approvals remain `not_verified`; declared-check execution, Desktop rendering,
  refresh and remote execution remain `not_run` by the ledger. It cannot
  authorize deployment or establish source-to-target parity.

### Bounded local P1 — block misleading RLS assignment script (2026-11-22)

- **Outcome / evidence:** the previous generated `assign_rls_roles.ps1`
  targeted dataset-user permissions without specifying an RLS role, despite
  claiming role assignment. For newly generated scripts when roles exist,
  `powerbi_import/permission_mapper.py::generate_rls_powershell` now emits a
  deliberate terminating throw and guidance to review restrictions and
  identities, configure role membership manually with authorized administration
  tools, and verify allowed and denied access in an authorized target.
  Automatic RLS assignment is unsupported.
- **Hypothesis / cohesive scope:** a script containing only a literal
  terminating throw and review comments cannot itself assign membership or
  grant dataset permissions; executable commands or interpolated input would
  falsify this local safety property. This is target-side guidance generation,
  not source extraction, role conversion, reporting or remote operations.
  `Deployer` owns the generator; `Tester` owns regressions. The existing
  `dataset_name` argument remains compatible and no roles produce no file.
- **Dependencies / validation:** manual membership depends on reviewed source
  restrictions, owner-approved identities and target design. Reported final
  local validation: `python -m pytest tests/test_phase5_advanced.py --tb=short
  -q -o addopts=''` yielded **35 passed, 6 subtests passed**; the required
  `python -m pytest tests/ --tb=short -q -o addopts=''` yielded **876 passed,
  1 skipped, 998 subtests passed**. Local PowerShell execution confirmed the
  reminder exits nonzero. The local exit gate is inert guidance, terminating
  behavior and no generated file for absent roles; actual access verification
  requires separate target authorization.
- **Risks / non-goals:** old generated artifacts remain unchanged and must not
  be run without review. This does not assign roles, verify security or prove
  source-to-target parity. Target membership and allow/deny checks are
  `not_run`; the broader P1 security and operations gate remains **open**.

### Bounded local P1 — reject unsafe security profile mappings (2026-11-22)

- **Outcome / evidence:** the standalone
  `powerbi_import/permission_mapper.py::map_bo_security_profiles` now rejects
  unresolved or ambiguous case-insensitive column matches, missing
  restrictions or operator, unsupported operators, and invalid string-list
  values or operator arity. It escapes candidate DAX identifiers and literals
  and surfaces `ValueError` rather than guessing or silently dropping a
  restriction. Previously, resolution could fall back to `Table`, an operator
  could default to equality, or an unrepresentable restriction could be lost.
- **Hypothesis / cohesive scope:** invalid or ambiguous declarations must not
  produce a candidate role; a returned role for such input would falsify this
  bounded conversion safeguard. `Deployer` owns the mapper and `Tester` owns
  regressions. This is standalone candidate metadata conversion, not source
  extraction, target generation, reporting or remote operations; the normal
  BO adapter does not wire this mapper into end-to-end migration.
- **Dependencies / validation:** callers must provide reviewed restrictions and
  table/column metadata. Reported final local validation:
  `python -m pytest tests/test_phase5_advanced.py --tb=short -q -o addopts=''`
  yielded **41 passed, 68 subtests passed**; the required
  `python -m pytest tests/ --tb=short -q -o addopts=''` yielded **882 passed,
  1 skipped, 1060 subtests passed**. The local exit gate is rejection of
  invalid or ambiguous input and correct escaping for supported candidate
  expressions, without silently omitting restrictions.
- **Risks / non-goals:** these checks do not verify data types, source policy,
  interactions between multiple roles, deployment or actual access, and do not
  prove RLS equivalence. Deployment and authorized allow/deny checks remain
  `not_run`; the broader P1 security and operations gate remains **open**.

### Bounded local P1 — disabled schedule review drafts (2026-11-22)

- **Outcome / evidence:** `powerbi_import/refresh_generator.py` now emits
  disabled local review drafts for a single declared schedule and for
  subscriptions. Missing or unsupported frequency, invalid or missing time,
  missing or invalid time-zone values and missing or invalid weekly days are
  not replaced with invented defaults. For mixed valid and invalid days, the
  known subset may be retained as a partial candidate with a review warning.
  Nonempty time-zone declarations are preserved but not verified against the
  target. Multiple schedules are never merged into one schedule. Referenced
  schedule lookups with malformed collections or items produce a disabled
  draft with an explicit invalid-lookup note. Subscription input must be a
  list or `None`; non-list inputs, including falsy malformed values, are
  rejected rather than treated as empty.
- **Hypothesis / cohesive scope:** a draft enabled by default, an invented
  missing schedule field, a silently partial day list or merged multiple
  schedules would falsify this local safeguard. `Deployer` owns draft
  generation and `Tester` owns regressions. This is local operations guidance,
  not source extraction, verified conversion, deployment or execution.
- **Dependencies / validation:** review depends on source schedule and
  subscription declarations, identities, target semantics, time zone,
  licensing and gateway decisions. The draft flags extra interval dictionary
  keys and nonempty weekday intervals for non-weekly frequencies for review.
  Earlier reported local validation, before the lookup/subscription follow-up:
  `python -m pytest tests/test_phase5_advanced.py --tb=short -q -o addopts=''`
  yielded **55 passed, 125 subtests passed**; the required
  `python -m pytest tests/ --tb=short -q -o addopts=''` yielded **896 passed,
  1 skipped, 1117 subtests passed**. The local exit gate covers disabled
  drafts, missing and malformed fields, warned partial days, unverified
  recipients, non-merging multiple schedules, malformed referenced lookups
  and non-list subscriptions. Focused follow-up coverage is in
  `tests/test_phase5_advanced.py`; run it and the required full suite for the
  current revision.
- **Risks / non-goals:** previously generated files remain unchanged and need
  review. These drafts do not establish source authenticity, identity or
  target semantics, automatic schedule conversion or operational equivalence.
  Deployment and schedule execution remain `not_run`; the broader P1 security
  and operations gate remains **open**.

### Delivered local P1 — validate WebI snapshot query-plan linkage (2026-11-22)

- **Outcome:** prevent inconsistent saved query-plan declarations from being
  attributed to a different document or provider during the local,
  Python-only snapshot-to-model handoff.
- **Current evidence:** the version 1.0
  [snapshot contract](schemas/webi_document_snapshot.schema.json) carries a
  document ID, provider summary ID and query-plan document/provider IDs.
  Previously, `bo_export/webi_snapshot_adapter.py::extract_webi_snapshot`
  consumed declared SQL without validating those linkages or the statement
  shape. The local adapter now validates the snapshot document ID. For plans
  declared single, it requires matching plan document/provider IDs, available
  status, exactly one statement object, nonempty SQL and empty operators.
  Duplicate normalized provider summary IDs fail. Missing and non-single plans
  retain warning/skip behavior.
- **First change / cohesive scope delivered:** `Extractor` updated
  `bo_export/webi_snapshot_adapter.py`; `Tester` added regressions in
  `tests/test_webi_snapshot_adapter.py` for matching and mismatched IDs, missing
  IDs, malformed plans, duplicates, numeric-ID normalization, skip behavior
  and errors that do not disclose SQL. `docs/MIGRATION_REFERENCE.md` documents
  the check.
- **Dependencies:** existing version 1.0 snapshot contract and fixture; no
  live CMS, new schema, new dependency or target runtime. `BusinessObjects`
  owns the snapshot contract/client; no contract change is implied.
- **Validation / exit:** focused command
  `python -m pytest tests/test_webi_snapshot_adapter.py
  tests/test_businessobjects_server_client.py --tb=short -q` passed **27
  tests**. Required suite `python -m pytest tests/ --tb=short -q` completed
  with exit code 0; totals are not recorded here. These are local test results,
  not runtime validation.
- **Risk / non-goals:** this checks local consistency of declarations only.
  Matching IDs do not authenticate provenance, prove source completeness or
  connection validity, establish report-to-provider linkage, execute SQL,
  recover layout or prove equivalence. CMS access, Desktop rendering, refresh
  and acceptance remain `not_run`; runtime validation was not performed. The
  BW native InfoCube identity blocker remains unchanged.

### Open local P1 — source-backed WebI visual bindings (2026-11-22)

- **Outcome / evidence:** `WebI Migration` reports that the sample contains
  four charts and 12 provider result objects, but no physical column bindings.
  Its SQL projects six expressions and the generated `Sales_Query` table has
  no columns. The agent traced the visual fallback to absent explicit
  report/provider and physical output-column bindings; no code was changed.
  Unknown `Entity "Table"` warnings remain unresolved, and static-validation
  exit 0 does not mean warnings are clean.
- **Hypothesis / first change:** source-owner-approved, document-scoped
  chart/provider links and typed query-output mappings could support a
  deterministic visual-to-model binding; missing or ambiguous mappings must
  remain unresolved. Obtain that source evidence before designing the
  smallest extraction, query/model and visual slice. Names or this synthetic
  example alone cannot establish the mappings.
- **Owners / dependencies:** `WebI Migration` coordinates; `BusinessObjects`
  owns the CMS contract, `Extractor` local metadata, `Wiring` query mapping,
  `Visual` visual generation and `Assessor` static validation. Reviewed source
  evidence is required before contract or generator changes. Keep extraction,
  conversion, target generation and reporting distinct.
- **Validation / exit:** after the evidence gate, add focused positive,
  missing, ambiguous and mismatched binding regressions, and run them plus
  `python -m pytest tests/ --tb=short -q`. Compare generated visual references
  with actual model columns and retain warnings for unresolved cases. The
  locally updated CI sample job exercises generation and default static
  validation but permits warnings; hosted execution and a clean, meaningful
  sample-quality gate remain open. Do not suppress warnings or weaken metrics
  to conceal a generator bug.
- **Risks / non-goals:** static checks and synthetic examples do not prove
  source bindings, Desktop rendering or semantic/visual equivalence. Desktop
  and runtime execution remain `not_run`; deployment requires separate
  authorization.

### Delivered local P2 disclosure follow-up (2026-11-22)

- **Outcome / first change:** `Visual` updated
  `powerbi_import/paginated_generator.py::generate_unbound_rdl` to add a visible
  `MigrationNote` sentence only when parameters exist. It says generated types
  default to `String`, source types are unverified/unavailable, and must be
  reviewed.
- **Evidence / validation:** `tests/test_lcm_manifest.py` covers both
  with-parameter and no-parameter cases and preserves the existing
  String/prompt/flags/no-data behavior. `docs/MIGRATION_REFERENCE.md` documents
  the disclosure. Focused
  `python -m pytest tests/test_lcm_manifest.py tests/test_paginated_rdl.py --tb=short -q`
  and required full `python -m pytest tests/ --tb=short -q` both completed
  exit 0; totals are not recorded.
- **Scope / limits:** visible disclosure only; no type recovery/inference, RDL
  equivalence or rendering evidence. Report Builder rendering/execution remain
  `not_run`.

### Prioritized delivery sequence and feature gates

Each increment is planned, not a promise of implementation. `Tester` owns
regressions; `Documentation Guardian` reviews capability documentation after
implementation. The required suite for each is `pytest tests/ --tb=short -q`
in addition to the owner-selected focused tests. Source-owner approval and
runtime checks are separate from local automation.

| Priority / outcome and first change | Evidence, dependencies and exact owners | Focused validation and exit gate | Risk / non-goal |
|---|---|---|---|
| P1 — **Source coverage:** obtain a sanitized, source-owner-approved WebI report-element/provider binding response or verified API contract before designing the binding slice. | WID replay lacked datasource and links; BIAR manifest is incomplete. `BusinessObjects` for CMS contract/client, `Extractor` for local adapters, `WebI Migration` coordinates; independently apply to Crystal, universes, BIAR, Lumira and DeskI only with family-specific evidence. | After the evidence gate, test positive, missing, ambiguous and malformed bindings; preserve unknowns and source IDs through extraction. Local pass is not source completeness; source owner must review actual exports. | Blocked without approved evidence; synthetic examples test behavior but are not source evidence. No inferred links, decryption, archive completeness or universal parser. |
| P1 — **Query and model semantics:** carry one verified provider query, typed fields, filters and relationship grain to M and TMDL; then address formulas and prompt behavior by feature. | Depends on trusted source binding/connection metadata above. `Wiring` owns M, `Dax` formulas, `Semantic` model, `Extractor` source metadata. | Golden source expression → M/DAX/TMDL mapping plus ambiguity, unsupported syntax, null/type and identifier tests; compare scoped source and target results under identical filters, grain, roles and parameters. | Reject or disclose unknowns; do not infer credentials, aggregation or equivalence from valid syntax. |
| P1 — **Reports:** preserve one evidence-backed WebI table binding into PBIP, then separately scope Crystal sections/groups to RDL and Lumira interactions to suitable targets. | Requires verified query/model and report-element bindings; existing native structures and RDL labels do not establish layout. `Visual`; `Extractor` supplies source evidence. | Synthetic source element → target binding/layout assertions and unsupported-element tests; authorized Desktop/Report Builder rendering, data and owner review are separate gates. | Do not fabricate visuals or claim pixel/interaction parity; manual rebuild where no native equivalent exists. |
| P1 — **Security and operations:** inventory one source authorization and schedule/publication rule with an explicit target disposition; review the target schedule contract before separately authorized validation. | `Assessor` assesses source declarations; `Deployer` owns permissions, gateway, refresh and deployment; `Semantic` owns model RLS. The local refresh deployment guard is implemented; target acceptance and owner review remain open. Depends on owner-approved identity and target design. | Deny-by-default, missing identity and conflicting-role tests; compare allowed and denied access and operational behavior in authorized environments. Schedule readback and refresh require separate authorization. | Publications, complex schedules and write-back may need external/manual solutions; never assume one-to-one mapping or grant access from incomplete metadata. |
| P2 — **Fabric and shared models:** map one verified source table/query to a governed ingestion and semantic path, then address shared-source identity. | Requires physical schema, source lineage and approved grain. `Fabric` owns Fabric generation, `Merger` shared identity, `Wiring` queries, `Semantic` models. | Local artifact, binding and ambiguity tests; separately reconcile authorized Fabric data/refresh and model results against source. | No force-merge of ambiguous queries; local bundle is not execution or deployment evidence. |
| P2 — **Evidence and remediation:** use the implemented declaration-only ledger to record per-feature unsupported and manual dispositions; separately start one evidence-backed source-to-target case joining extracted evidence to a generated object and comparison finding. | Depends on stable feature identity and independently reviewed source/target artifacts. `Evidence` owns the ledger and comparisons, `Orchestrator` its CLI; `Assessor` owns static checks and `Reviewer` reviews fidelity. No automatic artifact linkage is implied. | Test missing evidence, mismatches and negative findings; compare rows, aggregates, filters, visuals and security at declared grain/context. Never weaken a metric to conceal a generator bug. | Ledger references and passes are unverified declarations. A passing sample is not fleet-wide parity; missing evidence remains open. |
| P3 — **Deployment and cutover:** prepare one approved wave with rollback and reconciliation, then stage, publish and retire only under separate authorization. | Prior feature, security and operations gates plus named business and platform owners. `Deployer` owns remote operations, `Evidence` reconciliation, `Reviewer` acceptance review. | Dry-run and failure-propagation tests locally; authorized target publication, refresh, access, parallel run, business sign-off and rollback rehearsal required before cutover. | Local success is not deployment; no implicit cloud writes or automatic release approval. |

**Release and disposition rule:** for each source version and scoped feature,
retain source artifact/export provenance, extracted value and binding, mapping
decision, generated target object and local test, and independently captured
source/target results with query context, tolerances and discrepancies.
Explicitly record unsupported and non-native behavior, manual remediation,
owner, due decision and acceptance rather than counting it as automated.
Feature readiness requires source-owner confirmation, relevant data/semantic,
visual, security and operational comparisons, approved runtime evidence and
business acceptance. A wave additionally needs deployment, refresh, rollback
and cutover approval; BW retirement has its own gates below. Until performed
against explicitly authorized systems, CMS/SAP queries, Desktop and Report
Builder rendering, Fabric execution, refresh, deployment and cutover are
`not_run`; authenticity and equivalence without supporting evidence are
`not_verified`.

## Previous Evidence - 2026-11-20

- Current focused BW PBIP validation at that date:
  `python -m pytest tests/test_migrate_bw_bex_pbip.py --tb=short -q
  -o addopts=''` => **30 passed, 55 subtests passed**.
- Full local suite on Windows at that date:
  `python -m pytest tests/ --tb=short -q -o addopts=''` =>
  **858 passed, 1 skipped, 959 subtests passed**. This is local test evidence;
  SAP/Fabric execution, Desktop rendering, refresh, equivalence and business
  acceptance remained `not_run`.

## Previous Evidence - 2026-11-19

- Final full local suite on Windows:
        `python -m pytest tests/ --tb=short -q -o addopts=''` =>
        **825 passed, 1 skipped, 924 subtests passed**. This is local test
        evidence; SAP metadata discovery, SAP query execution, Desktop opening,
        refresh and source-to-target equivalence remain `not_run`.

## Previous Evidence - 2026-11-18

- Full local suite on Windows: `python -m pytest tests --tb=short -q -o addopts=''`:
        **755 passed, 1 skipped, 791 subtests passed** after the generated REP
        PBIP static quality check. The preceding DeskI report update had 736
        passed, 1 skipped and 770 subtests; the earlier RDL layout/prompt run
        had 728 passed, 1 skipped and 767 subtests. Coverage/hosted CI was not
        measured.
- Focused `tests/test_desktop_intelligence_extractor.py`: **24 passed,
        1 skipped, 7 subtests passed**. These local tests do not establish SQL
        execution, Desktop rendering, refresh or equivalence.
- DeskI, RDL, paginated and agent-contract focused tests:
        **68 passed, 1 skipped, 414 subtests passed**. The earlier three-file
        RDL-focused run had 53 passed, 1 skipped and 115 subtests passed.
        The skipped test covers
        the non-Windows OLE error path; the Windows OLE test passed with
        synthetic input. Ruff, Python compilation and `git diff --check` passed
        for the changed DeskI/RDL implementation and tests. These checks do
        not establish source type, Report Builder rendering, runtime behavior
        or equivalence.
- Desktop Intelligence XI 3.1: an experimental VBA provider-SQL capture and
        synthetic RDL/M handoff were added. The macro has not been run on a
        Desktop Intelligence client or real `.rep`; source extraction and parity
        remain unverified.
- Real-sample replay on four public LCM BIAR exports kept outside the repository
        (3 UNX, 2 UNV, 39 Crystal reports, 1 WebI): all 45 PBIP migrations failed
        with no datasource. The three UNX `.dfx`/`.blx`/`.cns` components carry a
        `Cipher` member and are not read (no decryption is attempted); Crystal
        contents are opaque; the UNVs expose only table/column names. Together with
        the 13 downloaded WIDs, 58 real sources produced no PBIP.
- What the readable CMS manifest does give is now extracted by
        `migrate_lcm_inventory.py`: document → universe → connection type links,
        Crystal prompts and WebI provider IDs, plus 40 unbound RDL skeletons
        (title, description, parameters as `String`). A one-time local check
        validated them against the official RDL 2016/01 schema (no schema-backed
        test is in the repository). They contain no data source or layout.
- `extract_webi_snapshot()` turns a saved CMS snapshot into extraction input
        (verbatim single-statement SQL plus a declared SQL Server connection); on the
        synthetic fixture it yields a model with an empty report shell. Not tested
        against a live CMS. The remaining blocker for real parity is an authorized CMS or
        verified exports (columns, connections, report-provider links, layouts).

## Previous Evidence - 2026-11-17

- Full local suite at that date: **703 passed, 730 subtests passed**.
- Local native WebI DOCSPEC extraction now records partial section and
        table-like element structure. On 13 downloaded WIDs kept outside the
        repository, it found 29 report tabs, 6 sections, and 61 recognized
        containers (56 `VTABLE`, 2 `HTABLE`, 3 `XTABLE`). SQL, connections,
        report-provider linkage and source completeness remain unverified;
        PBIP generation and RDL mapping remain blocked for these samples.
- A subsequent folder replay persisted 12 native provider records and 18
        structural `PARAMSERVER` entries across those WIDs. All 13 PBIP
        migrations failed; no datasource or SQL was recovered. These entries
        are not converted prompts or evidence of source completeness.
- Earlier local measurement on 2026-11-12: **558 passed, 518 subtests passed
        in 20.36s**.
- BW-0 through BW-8 local contracts and synthetic assessments are present;
        they do not prove SAP discovery, Fabric execution, cutover, or retirement.
- BW-4 also generates an unbound notebook for one explicitly declared mapping
        with an opt-in definition-byte / declared-ledger preflight; SAP origin,
        source-to-ledger correspondence/completeness and source-owner approval
        remain unverified, and equivalence remains `not_run`.
- BW-4's optional source-declaration preflight in
        `migrate_bw_transform_validate.py` requires the existing inventory /
        transformation pair and the definition-file / rule-ledger pair. It
        reuses complete plan/inventory validation and local SHA-256 / declared-
        ledger checks, reports independent deterministic
        `source_declaration_preflight` evidence, and does not write or execute
        a notebook. SAP authenticity, ledger completeness/correspondence, vector
        provenance, execution, equivalence and approval remain unverified or
        `not_run`.
- BW-4 plan-linked vectors also support local evaluation of normalized
        transfers, typed constants and same-scale decimal addition/subtraction.
        Its status is separate from vector comparison, plan linkage and source
        declaration; exit 0 alone does not prove a `not_run` evaluation passed.
        Only rule-referenced input values are type-checked; unused input values
        are not. This evaluation does not execute SAP, Spark or Fabric.
- 23 specialist development roles with an ownership contract; not runtime CLI stages.
- Local assessment, dry-run, file/batch/BIAR/shared generation, six-tool guarded
        MCP, and PBIP/Fabric quality reporting are exercised by local tests.
- `BOServerClient` has a bounded, read-only WebI CMS snapshot slice: report
        lists/details/elements and data-provider lists/details, with the
        optional SAP `allInfo` element option (BI 4.2 SP04+). An explicit option
        also captures provider plans/specifications. Its versioned JSON contract
        and synthetic fixture do not establish live CMS behavior; report-to-
        provider links, generation integration, and parity remain unverified or
        out of scope.
- Forced eFashion/HR shared generation: 11 Fabric ingestion tables, quality WARN,
        exit 0; PBIP emits a model and two thin-report descriptors. Without explicit
        force approval this low-overlap pair is declined. Distinct same-named source
        queries still reject instead of merging unsafely.
- Direct Lake source entities, unique ingestion ownership, physical metadata
        retention, and unsupported-semantics findings are local artifact contracts.
- Desktop opening/rendering, semantic equivalence, deployed refresh, Fabric
        execution, cutover and retirement remain `not_run`; historical phase
        completion labels do not waive them.

### Open Gates And Owners

| Priority | Status | Gate | Owner |
|----------|--------|------|-------|
| P1 | Delivered — bounded local behavior | Sanitize recognized credential-named datasource properties and recognized authentication components in `connectionString` at extraction return, JSON persistence, and legacy JSON load boundaries. Coverage is pattern-bounded; exhaustive secret removal is not established, and unrecognized or out-of-scope values may remain. | Extractor / Deployer / Tester |
| P1 | Delivered — bounded rejection | With `--server`, reject `--assess`, `--global-assess`, and `--dry-run` before server migration starts. Server portfolio assessment and target generation remain unsupported; CMS download mode still downloads/extracts. | Orchestrator |
| P1 | Delivered — bounded rejection | Main CLI rejects `--deploy`, `--deploy-refresh`, and `--deploy-bundle` before migration in batch, shared, and single-file contexts. Standard CLI deployment is not reliably wired; deployment and remote publication remain unsupported/unverified. The separate `--multi-tenant` path was not changed or verified. | Orchestrator |
| P1 | Open | If standard CLI deployment is reintroduced, wire remote failure propagation and prove publication outcomes rather than equating local exit 0 with publication. | Orchestrator / Deployer |
| P2 | Open | Explicit source-qualified mapping for ambiguous shared queries; never bypass identity checks with force-merge. | Merger |
| P2 | Open | The locally updated final CI job generates a synthetic sample, checks PBIP/model presence and runs default static validation; warnings do not fail. Hosted CI is `not_run`; sample quality and any planned staging/production gates remain open. | Tester / Deployer |
| P2 | Open | Local baseline comparison and the unchanged 80% coverage gate are recorded above. Targeted Ruff/Flake8 and Pyright passed for `coverage_ledger.py`, `refresh_generator.py`, `permission_mapper.py` and the ledger CLI; repository-wide critical-selection Flake8 passed with one `SyntaxWarning`. The hosted sample job depends on lint and tests. | Tester |
| P2 | Not run | Validate clean-environment developer installation, Desktop rendering, refresh, security semantics, and deployed workload execution in approved environments. | Tester / Semantic / Visual / Deployer |

See [current gaps](GAP_ANALYSIS.md), [workflow boundaries](ENTERPRISE_GUIDE.md),
and [unreleased changes](../CHANGELOG.md). Keep this document canonical; do not
copy Tableau release numbers or create a competing roadmap.

### Local increment — WebI coordination and prompt evidence (2026-11-17; bounded slice)

- **Outcome / scope:** the user-invocable `WebI Migration` coordinator routes
  source, query, model, visual and evidence work without changing engine
  ownership. Native provider extraction retains recognized `PARAMSERVER`
  structure and member provenance, without prompt labels, IDs or values.
- **Evidence:** synthetic tests cover both provider variants, malformed and
  unknown records, provider ambiguity and JSON persistence. The 13-WID folder
  replay retained 12 provider records and 18 structural prompt entries; all 13
  PBIP targets failed with no datasource or SQL recovered.
- **Owners:** `Extractor` for local parsing and adapter behavior, `Tester` for
  regressions; `WebI Migration` coordinates cross-cutting work. The agent's
  actual invocation and nested delegation are not verified.
- **Open gate:** obtain and verify source queries, connections and
  report-to-provider bindings before generation can be evaluated. Native
  structure does not generate prompts, prove source completeness or establish
  semantic/visual parity. CMS access, query execution, Desktop rendering and
  refresh remain `not_run`.

### Local increment — Read-only WebI CMS snapshot (2026-11-17; delivered bounded slice)

- **Outcome / scope:** `BOServerClient` reads, without modifying CMS content,
  the WebI report list, report details, report elements (with optional SAP
  `allInfo` from BI 4.2 SP04), and data-provider lists and details. It produces
  a versioned JSON snapshot containing `reports` summary/details/elements and
  `data_providers` summary/details. An explicit opt-in adds each provider's
  raw query plan and query specification to the snapshot.
- **Current evidence:** the snapshot contract is
  `docs/schemas/webi_document_snapshot.schema.json`, with a synthetic fixture.
  No CMS-real test evidence was provided; CMS runtime behavior is `not_run`.
- **First change / cohesive scope:** a read-only CMS metadata retrieval path
  and its versioned snapshot contract/fixture. This remains source inspection:
  it does not convert the metadata, generate target artifacts, or report
  source-to-target fidelity.
- **Owner:** `BusinessObjects` for the CMS client and read-only retrieval.
- **Dependencies:** an authorized CMS session and compatible SAP Business
 Objects version for runtime verification; the optional `allInfo` behavior
  requires BI 4.2 SP04 or later. No runtime target was authorized or tested
  for this increment.
- **Validation / exit:** delivered only for the stated local snapshot contract
  and synthetic fixture. A real-CMS check is `not_run`; the WebI P1 gate and
  source/target parity evidence remain open.
- **Risks / non-goals:** query plans/specifications are opt-in and may contain
  sensitive SQL. The snapshot does not connect reports to providers, feed
  the CLI, or establish completeness, semantic fidelity, or parity (the later
  Python-only `extract_webi_snapshot()` can use it, see 2026-11-18). No
  write operation or live CMS behavior is claimed.

### Local increment — Native WebI structure extraction (2026-11-17; delivered bounded slice)

- **Outcome / scope:** native WebI document specification v2.5 extraction now
  retains `SECTION` IDs and a partial inventory of `VTABLE`, `HTABLE` and
  `XTABLE` report elements. When present, element IDs are copied from `BID`;
  `row_info_count` and `column_info_count` count descendant `ROWINFO` and
  `COLINFO` descriptors, not data rows or converted layout.
- **Current evidence:** extraction of 13 downloaded WIDs stored outside the
  repository yielded 29 report tabs, 6 sections and 61 recognized elements
  (56 `VTABLE`, 2 `HTABLE`, 3 `XTABLE`). All recovered structures are marked
  `native_wid_partial`. Focused WebI validation passed **17 tests and 15
  subtests**; the full local suite passed **697 tests and 720 subtests in
  27.57s**. These are local parser/test results, not customer or CMS evidence.
- **First change / cohesive scope:** bounded structure extraction in
  `bo_export/webi_extractor.py`, with synthetic regression tests in
  `tests/test_webi_extractor.py` and corresponding README/Changelog updates.
- **Owner:** `Extractor` for local WID parsing.
- **Dependencies:** none for local parsing; the existing 15 collection
  contract is preserved. No CMS access or external runtime was used.
- **Validation / exit:** parser results were checked across all 13 sample
  files; report count remains 29 and all extracted sections/elements are marked
  partial. PBIP generation failed for all 13 files with `No datasources found`.
  The RDL batch attempt failed for all 13 with the error
  `No RDL mapping configured for this source`; its `sources` mapping was empty.
  Zero `.rdl` and zero `.m` files were produced. SQL execution is `not_run`.
- **Risks / non-goals:** this does not reconstruct full report layouts, cell
  content, expressions, formatting or object bindings; infer SQL, datasource
  connections or report-to-provider links; or prove source completeness,
  rendering or source-target equivalence.

### Local increment — CMS inspection-flags gate (2026-11-16; delivered bounded slice)

- **Outcome / scope:** when `--server` is combined with any of `--assess`,
  `--global-assess`, or `--dry-run`, the CLI raises a clear `ValueError` before
  `_run_server_migration`. No CMS connection, download, or extraction starts
  for these unsupported combinations.
- **Current evidence:** `tests/test_cli.py::test_server_rejects_inspection_modes_before_download`
  passed **1 test with 3 subtests**, covering all three flags and verifying
  server migration is not called. The full local suite
  `python -m pytest tests\ --tb=short -q -o addopts=''` passed
  **630 tests and 636 subtests in 11.52s**. This is local test evidence only.
- **First change / cohesive scope:** the pre-dispatch rejection in `migrate.py`
  and its CLI regression in `tests/test_cli.py`; no source extraction,
  conversion, target generation, reporting, or remote-operation behavior is
  added or changed.
- **Owner:** `Orchestrator`.
- **Dependencies:** existing `--server` and inspection-mode CLI flags and the
  server migration dispatch boundary (`_run_server_migration`); no CMS
  connection or other external dependency is needed to validate rejection.
- **Validation / exit:** the focused regression and full local suite passed.
  The gate is delivered only for rejecting these unsupported flag
  combinations. Desktop and runtime checks remain `not_run`.
- **Limits / non-goals:** server portfolio assessment and target generation
  remain unsupported. CMS download mode still downloads and extracts.
  This increment does not establish CMS runtime behavior, Desktop behavior,
  or target parity.

### Local increment — Main CLI deployment-flag rejection (2026-11-16; delivered bounded slice)

- **Outcome / scope:** the main CLI rejects `--deploy`, `--deploy-refresh`,
  and `--deploy-bundle` before migration because standard CLI deployment is
  not reliably wired and could otherwise appear successful without proving
  publication. The rejection covers batch, shared, and single-file contexts.
  Migration dispatch does not start for these flagged invocations.
- **Current evidence:** focused validation
  `python -m pytest tests\test_cli.py -k "main_rejects_unwired_deployment_flags_before_migration or single_file_migration_requires_directory" --tb=short -q -o addopts=''`
  passed **2 tests / 7 subtests**. The regressions verify the three options
  across the stated CLI contexts and verify migration dispatch is not started.
  The full local suite
  `python -m pytest tests\ --tb=short -q -o addopts=''` passed
  **631 tests / 640 subtests in 12.97s**. This is local test evidence only.
- **First change / cohesive scope:** reject only the three named deployment
  options at the main CLI boundary in `migrate.py`, before migration dispatch,
  with corresponding CLI regression coverage in `tests/test_cli.py`. No
  extraction, conversion, target generation, reporting, deployment, or remote
  operation is implemented by this increment.
- **Owner:** `Orchestrator`.
- **Dependencies:** the main CLI argument and dispatch paths, including batch,
  shared, and single-file invocation contexts; no remote service is required
  to validate the pre-migration rejection.
- **Validation / exit:** the focused and full local suites passed as stated.
  The bounded main-CLI rejection is delivered for `--deploy`,
  `--deploy-refresh`, and `--deploy-bundle` only. Desktop and remote checks
  remain `not_run`.
- **Limits / non-goals:** do not claim deployment or remote publication was
  implemented or occurred. The separate `--multi-tenant` path was not changed
  or verified. This increment does not establish remote failure propagation,
  publication, Desktop behavior, or runtime results; those checks remain
  `not_run`.

### Local increment — Bounded datasource credential redaction (2026-11-16; delivered bounded slice)

- **Outcome / implementation scope:** sanitize recognized credential-named
  properties in datasource records and recognized authentication components
  in `connectionString` at extraction return, JSON persistence, and legacy
  JSON load boundaries. The load path sanitizes returned data without
  rewriting the legacy file. The `powerbi_import/security_validator.py` helper
  is pattern-based and explicitly is not a complete parser.
- **Current evidence:** the full local suite
  `python -m pytest tests\ --tb=short -q -o addopts=''` passed
  **629 tests and 633 subtests, with no failures**. The focused
  `python -m pytest tests\test_extraction.py --tb=short -q -o addopts=''`
  passed **12 tests**. Synthetic regressions in `tests/test_extraction.py`
  cover returned data, persistence, quoted/braced/URI connection-string
  credentials, and legacy JSON loading. Loading sanitizes returned data; it
  does not rewrite the legacy file. This is local test evidence only.
- **First change / cohesive scope:** the bounded sanitization behavior in
  `bo_export/extract_bo_data.py`, the pattern-based helper in
  `powerbi_import/security_validator.py`, and its synthetic extraction
  regressions. Keep extraction-boundary behavior distinct from conversion,
  target generation, reporting, and remote operations.
- **Owner:** `Extractor` owns `bo_export/extract_bo_data.py`;
  `Deployer` owns `powerbi_import/security_validator.py`; `Tester` owns the
  regression tests in `tests/test_extraction.py`.
- **Dependencies:** existing datasource record extraction, JSON persistence,
  and legacy JSON loading paths, plus the helper's recognized credential and
  authentication patterns. No external service or new dependency is required
  for this local slice.
- **Validation / exit:** the focused and full local suites passed with
  12 extraction tests and 629 total tests / 633 subtests. The bounded behavior
  at the named extraction boundaries is delivered. Desktop and runtime checks
  are `not_run`; this increment does not establish exhaustive secret handling.
- **Remaining risks / non-goals:** pattern matching is not a complete parser
  or exhaustive secret detector. This does not establish that all artifacts,
  arbitrary SQL or text, or values outside the named datasource boundaries
  are secret-free. No claim is made about unrecognized credential forms,
  other artifact types, Desktop behavior, deployed execution, or remote
  validation.

### Increment — Consolidated HTML report for BO batch targets (P1; local slice delivered)

- **Outcome / delivered scope:** a local HTML summary for a completed
  directory batch, driven by `batch_manifest.json`, covers each source and its
  PBIP/Fabric and optional paginated RDL target. It reports per-source and
  per-target outcomes, available generation/quality diagnostics, skipped
  inputs, and contained local artifact links without rerunning migration.
- **Evidence:** targeted validation
  `python -m pytest tests/test_agent_contracts.py tests/test_cli.py tests/test_crystal_pipeline.py --tb=short -q -o addopts=''`
  passed **75 tests**; the full local suite passed **621 tests** with
  `python -m pytest tests\ --tb=short -q -o addopts=''`; `git diff --check`
  was clean. This delivers the bounded local batch-reporting slice, not
  complete TableauToPowerBI parity. The folder CLI now uses the manifest-driven
  report path in `migrate.py`'s `_run_batch_migration` workflow to produce
  `batch_report.html` and attempts to create it outside dry-run. Known report
  generation errors are logged as warnings and do not modify source statuses.
  The separate `generate_report.py` workflow remains autonomous and unchanged.
- **Implementation scope delivered:** `Extractor` owns the batch-report module
  `bo_export/batch_report.py`; `Orchestrator` integrated it into the folder CLI
  workflow in `migrate.py` (`_run_batch_migration`). The existing standalone
  `generate_report.py` workflow was not changed. Manifest compatibility is
  preserved; missing metadata and unresolved local artifacts remain explicit
  rather than being inferred or linked outside their expected roots.
- **Owner:** `Extractor` (primary for `bo_export/batch_report.py`);
  `Orchestrator` (primary for `migrate.py` and CLI report integration;
  existing primary owner of unchanged `generate_report.py`); `Evidence`
  (collaborator for status and evidence interpretation); `Web Designer`
  (collaborator for HTML presentation).
- **Validation / exit:** delivered for the stated local scope based on the
  targeted tests, full suite, and clean diff-check above. No remote target or
  service validation was part of this increment.
- **Evidence limits / risks:** classify generation and static-quality results
  only from manifest evidence; absent checks remain `not_run`. HTML presence,
  successful generation, links, or aggregate counts do not imply visual
  equivalence, Desktop/Report Builder rendering, semantic correctness, refresh,
  or runtime execution. Desktop/Report Builder, refresh, runtime, and
  equivalence remain `not_run`; those checks are separate and require
  authorized execution and explicit evidence. Avoid stale links and path
  traversal when resolving local artifacts.
- **Non-goals:** alter extraction, conversion, target generation, RDL feature
  support, quality metrics, deployment, or remote operations; replace the
  existing comparison/quality reports; or claim parity beyond this bounded
  batch-reporting capability.

### Paginated reports: source-family preparation

The local RDL generator accepts explicit source labels and SQL Server or
semantic-model DAX mappings. SQL mappings can declare base page/table styling
and report prompts; the output is still a manual starting point, not automatic
migration of every BO report.

| Priority | Work required | Exit evidence |
|----------|---------------|---------------|
| P0 | Inventory actual versions, source dependencies and report features by family; retain unknowns as blockers. | Representative, authorized fixtures and source-owner review per family. |
| P1 | WebI: preserve report-to-query links and supported tabs, tables, filters and prompts; validate universe dependencies. The snapshot can opt in to provider plans/specifications but does not link reports to providers. | Source/target query and layout comparisons for representative reports; unresolved items remain explicit. The snapshot is not generation or parity evidence. |
| P1 | Crystal: replace heuristic-only extraction with a trustworthy source export; capture sections, grouping, formulas, parameters and subreports. | Version-specific fixtures, extraction checks and Report Builder result comparisons. |
| P2 | Lumira Discovery/Designer: inventory data bindings, charts and interactions; define paginated equivalents or manual dispositions. | Representative fixtures and reviewed feature-by-feature dispositions, including non-paginated interactions. |
| P2 | Desktop Intelligence, Xcelsius and Analysis for OLAP: establish supported export contracts and classify incompatible interactions/OLAP semantics. Desktop Intelligence has an unverified SDK capture prototype, a standalone REP inventory with pre-migration reports, and a gated candidate-to-basic-RDL draft route requiring manual SQL Server mappings. | Version-specific source evidence and reproducible extraction/conversion tests, or explicit unsupported findings. For the inventory, check format, encoding and existing-output boundaries and independently review candidates against authorized source evidence. |
| P2 | Grouping, automatic BO layout/prompt extraction, and broader RDL data-source coverage; explicit SQL prompt labels, multi-value bindings and base page/table styling are available as manual declarations only. | RDL schema checks plus Report Builder open/render, data and security tests in an authorized environment; source-derived layout and prompts need representative BO evidence. |
| P3 | Validate each migration wave against its BO source. | Reconciled results, visual/functional review, security and owner approval; deployment is separately authorized. |

BIAR/LCMBIAR unpacking and CMS exports need separate source coverage: direct
archive entries are not proof of complete contents. No gate above is closed
by successful local RDL generation.

The standalone DeskI `.rep` candidate inventory is under implementation. Its
command and security boundaries are described in the [migration reference](MIGRATION_REFERENCE.md#desktop-intelligence-experimental-local-rep-inventory-in-progress).
It is not automatic report conversion: candidate SQL, bindings, completeness
and equivalence need independent review, and BO variables remain unresolved. A
separate paginated CLI can create a basic RDL from one explicitly selected
candidate only with an unverified-SQL acknowledgement and manually declared
connection/fields plus optional manually declared layout/prompts; it does not
create PBIP, recover the source design or validate query execution. A
`Query;` source name is only a possible universe, not a verified universe or
connection. The [reported 2026-11-18 observations](GAP_ANALYSIS.md) and
one-sample draft do not close this gate; broad corpus replay and source
equivalence remain `not_run` for this update.

### Local increment — Manually declared SQL Server RDL scalar parameters (2026-11-16; delivered)

- **Outcome / delivered scope:** explicit SQL Server RDL mappings may include
  an optional `parameters` list. Each entry must contain exactly `name` and
  `data_type`; supported scalar types are `Boolean`, `DateTime`, `Float`,
  `Integer`, and `String`. Declared SQL `@Name` references bind to RDL
  `QueryParameters` and corresponding report parameters/prompts. Parameterized
  mappings are rejected for Power Query output.
- **Evidence:** focused validation
  `python -m pytest tests/test_sql_server_rdl.py tests/test_webi_sql_binding.py tests/test_paginated_rdl.py --tb=short -q -o addopts=''`
  passed **42 tests / 89 subtests**. Full local validation
  `python -m pytest tests\ --tb=short -q -o addopts=''` passed
  **625 tests / 633 subtests**.
- **First change / cohesive scope:** add the optional parameter declaration
  and SQL-to-RDL bindings for explicit SQL Server mappings, while rejecting
  parameterized mappings on the Power Query output path. Keep source extraction
  and conversion separate.
- **Owner:** `Visual` owns local RDL generation; `Orchestrator` owns the CLI
  and output-path integration; `Tester` owns the focused regression tests.
- **Dependencies:** the existing explicit SQL Server RDL mapping and its output
  selection path; no BO prompt extraction, DAX conversion, or remote service.
- **Validation / exit:** the stated local test gates passed for this slice.
  Automatic BusinessObjects prompt extraction or DAX prompt conversion is
  not implemented. Report Builder validation, broader RDL schema checks,
  rendering, data execution and runtime verification remain open or
  `not_run`; this increment does not close the paginated-report gates above.
- **Risks / non-goals:** a generated RDL and passing local tests do not prove
  query correctness, source/target equivalence, Report Builder acceptance,
  or runtime behavior. No automatic BO prompt/DAX conversion, broader
  parameter semantics, layout work, or remote validation is claimed.

### Local increment — Declared REP-to-RDL prompts and presentation (2026-11-18; bounded)

- **Outcome / delivered scope:** explicit SQL Server RDL mappings now support
  literal report-prompt labels and opt-in multi-value parameters, declared
  page dimensions/margins, per-column widths, and selected font/color tokens.
  The generated table uses a styled title/header and alternating detail rows.
- **Evidence:** synthetic RDL/CLI regression tests cover scalar and multi-value
  parameter bindings, prompt labels, page dimensions, widths, style output, and
  invalid declarations. The current full-suite result is recorded in
  `docs/GAP_ANALYSIS.md`.
- **Owner:** `Visual` owns the RDL generator; `Orchestrator` owns direct source
  SQL selection; `Tester` owns the contract tests.
- **Dependencies:** explicit SQL Server connection, reviewed SQL and fields,
  and caller-declared page/layout/prompt metadata. No CMS or remote service.
- **Validation / exit:** generated XML is parsed locally and contract tests
  pass. REP extraction still records only broad sheet/structure markers and
  literal SQL macro arguments; it does not recover coordinates, formatting,
  grouping, sorts, page breaks, prompt value lists or dependencies. BO SQL
  macros must be reviewed and rewritten before they can bind to SQL parameters.
- **Risks / non-goals:** this is a manually configured approximation, not an
  identical visual or prompt-dialog conversion. Report Builder schema/open,
  rendering, data execution, security and source/target equivalence remain
  `not_run`.

### Local increment — DeskI pre-migration reports (2026-11-18; bounded)

- **Outcome / delivered scope:** the standalone REP inspection can optionally
  write deterministic JSON and HTML reports with partial candidates, unverified
  SQL selectors, stream-local references for detected formula candidates,
  review actions and checks scoped to the current inspection.
- **Evidence:** synthetic tests cover candidates, missing SQL/markers, escaped
  metadata, sensitive-content omission, unresolved selectors, overwrite and
  write-cleanup failures. Eight locally retained REP examples produced reports;
  source hashes and candidate counts were checked as described in the gap analysis.
- **Owner:** `Evidence` owns the report module; `Orchestrator` owns the CLI;
  `Extractor` owns the inventory and SQL-selector contract.
- **Dependencies:** a locally readable REP and new output paths. The original
  inventory may contain SQL; all outputs may contain sensitive metadata.
- **Validation / exit:** inspection reports do not generate or validate a
  target. Formula references do not expose expressions or establish source
  identity, coverage or semantics. Zero candidates do not prove absence; source
  authenticity, prompt behavior, layout, data, runtime security and equivalence
  remain unverified.
- **Risks / non-goals:** no fidelity score or automatic layout/prompt recovery;
  RDL/PBIP rendering, query execution, refresh, deployment and Fabric execution
  remain `not_run` by this inspection.

### Local increment — Static quality check for REP PBIP draft (2026-11-18; bounded)

- **Outcome / delivered scope:** run the existing static `ArtifactValidator`
  after generating the REP PBIP draft. Validator errors fail only the PBIP
  target and appear in the manifest; warnings are non-blocking. The independent
  RDL target is unaffected, and a failed generated PBIP may remain for diagnosis.
- **Evidence:** focused `tests/test_desktop_intelligence_extractor.py`:
  **24 passed, 1 skipped, 7 subtests**. Full local suite:
  **755 passed, 1 skipped, 791 subtests**.
- **First change / cohesive scope:** validate the generated PBIP draft and
  report errors at the PBIP target boundary without coupling the independent
  RDL target.
- **Owners:** `Visual` owns PBIP generation; `Assessor` owns static validation;
  `Orchestrator` owns target/manifest integration; `Tester` owns regression
  coverage.
- **Dependencies:** the generated REP PBIP draft, existing `ArtifactValidator`,
  and migration manifest. No remote service.
- **Validation / exit:** the stated local tests pass. Static validation does
  not execute SQL or establish Desktop opening/rendering, refresh, or
  source/target equivalence; those checks remain `not_run`.
- **Risks / non-goals:** this check is not readiness, full migration, or parity
  evidence. It does not validate query results or establish runtime behavior.

## Separate roadmap: SAP BW/BW/4HANA to Fabric and BW retirement

**Planning baseline, 2026-11-10; offline BW-0 through BW-8 slices added
2026-11-11.** End-to-end migration capabilities and runtime validation remain
planned.
This is a distinct source migration and retirement program, not an extension of
the BO extraction contract or a claim that the BO pipeline migrates BW. The
historical SAP BW plugin entry below is a limited idea, not this program or
evidence of delivery. The cross-source sequence above complements rather
than replaces the existing BO and BW gates.

### Capability-map increments — 2026-11-20

- **Delivered disclosure increment:** the new
  [SAP BW capability mapping](GAP_ANALYSIS.md#sap-bw-capability-mapping-to-target-architecture)
  is reflected in generated BW PBIP metadata. Functional capabilities and
  technical objects are classified as `partial`, `assessment_and_review_only`,
  or `not_implemented`; every runtime and retirement check is fixed to
  `not_run`. The record is repository evidence, not a target-service
  implementation.
- **Delivered P1 — operational capability disposition:** BW-6 controls 1.1
  declares Copy Version, Upload File, Forecast Update, cube activation,
  planning reporting and consolidation/aggregation with an external owner,
  target solution, evidence, disposition and fixed `not_run` execution status.
  Complete coverage requires all six capability dispositions; missing,
  blocked or unowned targets keep the gate open. Version 1.0 remains
  compatible. This does not build Power Apps, Talend jobs or SQL procedures.
- **Next BW P1 — native InfoCube identity:** require one sanitized,
  source-owner-approved native identity sample before adding a local identity
  check. Matching, missing, mismatching and ambiguous evidence must produce
  distinct outcomes. Without that sample, linked cube identity remains
  `not_verified`.
- **Next BW P1/P2 — one additive key figure:** only after identity and linkage
  evidence are sufficient, consider one opt-in key figure whose declared
  aggregation is additive, exception aggregation is not applicable, and
  unit/currency handling is owner-approved. Unsupported or ambiguous semantics
  remain fail-closed. No general BEx formula converter is implied.
- **Delivered bounded local BW-5 slice — BEx result-vector comparison
  (2026-11-22):** `migrate_bw_reconcile.py --bex-result-vectors <manifest>
  --output <new-report.json>` compares declared source/target row vectors by
  composite key, using exact or decimal-tolerance measure rules, and reports
  key and measure discrepancies. A pass establishes only that the supplied
  declarations satisfy the configured comparison. It does not execute SAP or
  Fabric, authenticate vectors or references, prove source coverage or
  semantic equivalence, or constitute approval. SAP/Fabric runtime and
  approval remain `not_run`; authenticity, provenance, coverage and
  equivalence remain `not_verified`. This does not close BW-5.
- **Deferred:** automatic SAP/BW discovery, DSO/ABAP/DTP conversion,
  Multiprovider inference, full variables/hierarchies/exceptions/layout
  conversion, Power Apps or Talend implementation, planning write-back,
  deployment, cutover and retirement.

- **Local increment — BW-5 offline BEx result-vector comparator
  (2026-11-22; bounded, does not close BW-5):**
  - **Outcome:** the `migrate_bw_reconcile.py --bex-result-vectors <manifest>
    --output <new-report.json>` path locally compares declared source and
    target rows. It matches declared composite keys, applies exact or decimal
    tolerance rules to measures, and reports missing, extra or duplicate keys
    and measure mismatches. Passing means only that these declarations meet
    the configured comparison.
  - **Current evidence / falsifiable hypothesis:** the version 1.0 contract is
    defined in `docs/schemas/sap_bw_bex_result_vectors.schema.json` with a
    synthetic fixture and focused CLI/comparison regressions in
    `tests/test_bw_reconciliation.py`. Local validation is **16 passed** for
    `pytest tests/test_bw_reconciliation.py --tb=short -q`, and
    **865 passed, 1 skipped (866 collected)** for `pytest tests/ --tb=short
    -q`; `git diff --check` passed. This is local code/test evidence only.
    Hypothesis: the comparator reports key/measure differences and returns
    pass only when declared vectors satisfy the declared rules; local tests
    cover both discrepancy and passing declarations.
  - **First change / cohesive scope:** the offline manifest loader, vector
    comparison/report, CLI option, versioned schema and synthetic fixture,
    plus focused regressions. No source extraction, target generation,
    external execution or remote operation is included.
  - **Owner:** `Evidence` owns the comparison logic, schema and fixture;
    `Orchestrator` owns the CLI; `Tester` owns regression coverage.
  - **Dependencies:** a locally supplied version 1.0 manifest with source and
    target row declarations, matching query scope/role/prompt-context/grain,
    composite key fields and one rule per measure; a new report path is
    required and existing reports are not overwritten. No SAP or Fabric
    access is needed for local comparison.
  - **Validation / exit gate:** the validations above establish local code and
    test behavior only. SAP/Fabric runtime and business approval are
    `not_run`; vector/reference authenticity, provenance, source coverage and
    semantic equivalence are `not_verified`. Native InfoCube identity remains
    blocked pending sanitized, source-owner-approved evidence. BW-5 remains
    open.
  - **Risks / non-goals:** a pass does not execute SAP/Fabric, authenticate
    vectors or evidence references, establish source coverage, prove semantic
    equivalence, demonstrate consumer acceptance or authorize retirement.
    This comparator does not resolve native InfoCube identity or BW-5.

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
- **Evidence / hypothesis:** BO DAX/M conversion is not BW/ABAP conversion.
  The local converter below cannot substantiate its supplied rules against a BW
  definition. Hypothesis: a separately supplied source-rule ledger and local
  definition bytes can expose discrepancies among those declarations in one
  bounded mapping; generating under such a mismatch would falsify that slice.
  This does not establish source truth or the ledger's authority and coverage.
- **Local conversion slice delivered — partial:** `Orchestrator` owns
  `migrate_bw_convert.py`, and `Fabric` owns
  `powerbi_import/bw_transform_generator.py`. The CLI accepts `--inventory`
  and `--transformation` plus a new `--output` `.ipynb` path, and generates
  one unbound notebook without overwriting an existing file. The normalized 1.0
  plan is described by
  [`docs/schemas/sap_bw_conversion_plan.schema.json`](schemas/sap_bw_conversion_plan.schema.json).
  Synthetic JSON fixtures provide the
  [inventory](fixtures/sap_bw_conversion_inventory.example.json),
  [conversion plan](fixtures/sap_bw_conversion_plan.example.json) and
  [Bronze plan](fixtures/sap_bw_conversion_bronze_plan.example.json); they
  do not provide actual staged Parquet data.
- **Selection and rule boundary:** the plan declares one complete mapping;
  selected source, transformation, target and optional DTP must be observed,
  in scope and unblocked in the supplied inventory. The declared lineage must
  have observed, resolved edges either directly or via the DTP; any additional
  incoming transformation edge blocks generation, including operational edges.
  The transformation requires observed metadata and semantics, and a definition
  reference and SHA-256 matching the supplied inventory fields. Unknown or
  unsupported features and declared semantic functions of selected objects
  block generation. These are checks of declarations: the reference is not
  dereferenced; without the optional preflight, the hash is not computed from
  definition bytes. A `complete` declaration is not an independent completeness
  or authenticity attestation.
- **Local preflight delivered — partial (2026-11-11):** the opt-in
  `--definition-file` and `--rule-ledger` options must be supplied together.
  The preflight computes SHA-256 of the provided local definition bytes and
  requires a match with the conversion plan and the inventory's observed
  definition hash. Every plan rule must have a unique `source_rule_id`; its ID
  and normalized mapping must match the separately declared ledger, with
  identical rule-ID sets and input column name/type schemas. Missing, extra,
  changed or unsupported rules, missing/duplicate IDs, schema/hash mismatches,
  malformed ledger JSON, or an unpaired option block generation. The
  [ledger schema](schemas/sap_bw_source_rules.schema.json), synthetic
  [definition bytes](fixtures/sap_bw_conversion_definition.example.txt) and
  [ledger](fixtures/sap_bw_source_rules.example.json) describe local evidence
  only. Successful checks record `definition_sha256_check: pass` and
  `plan_vs_declared_ledger: pass`; with neither option, both are `not_run`.
  Existing 1.0 plans without source IDs remain supported in declaration-only
  mode when neither option is supplied. The preflight does not parse the
  definition: authentic SAP origin and actual source-to-ledger correspondence
  and completeness remain unverified; source-owner approval has not been run.
  Notebook metadata records `source_definition_authenticity` and
  `ledger_source_correspondence` as `not_verified`, and
  `source_owner_approval` as `not_run`.
- **Supported target rules and execution:** exact-type transfers; typed
  `string`, `boolean`, `int`, `bigint` and exactly representable decimal-string
  constants, including null; and same-scale decimal addition/subtraction with
  explicit null propagation. Decimal constants reject binary floats, excess
  fractional precision that would round, and values beyond the target range.
  Decimal result precision must be `max(left_precision, right_precision) + 1`,
  at most 38, to avoid declared precision loss. Only when manually bound to an
  authorized lakehouse and run does the notebook read the declared Bronze
  snapshot, check its schema, count and lineage, preserve Bronze provenance,
  add transformation/definition-hash/target provenance, and create the new
  Silver Delta target with `errorifexists`. It checks the output schema before
  writing and the target count afterward; a post-write mismatch may leave the
  new table for investigation. Counts and lineage checks do not prove source
  completeness or source-to-target equality.
- **Local validation evidence:** the coordinator reports that local fake-Spark
  and CLI tests were run; `tests/test_bw_transform_generator.py` exercises
  supported rules, paired preflight success and rejection paths, 1.0
  declaration-only compatibility, provenance and no-overwrite behavior.
  Fake-Spark execution is not real Spark or Fabric execution.
- **Existing vector-comparison slice (2026-11-11):** `migrate_bw_transform_validate.py`
  and `powerbi_import/bw_transform_validation.py` compare supplied expected
  outputs and target outputs for explicit vectors, with exact type/value checks
  or declared decimal tolerances. The synthetic suite covers rounding, nulls,
  missing/extra fields and mismatches. It neither parses ABAP nor executes
  either the source routine or a target transformation; source vector
  provenance, target runtime, semantic equivalence and business acceptance
  remain `not_run`. This comparator does not generate notebooks or close BW-4.
- **Optional conversion-plan linkage delivered — partial (2026-11-11):** the
  vector comparator accepts paired inventory and normalized-plan CLI options.
  When supplied, it validates the declared transformation ID, definition
  reference and definition hash match; the exact input-field set for each
  vector; and the exact rule-target set. The report records
  `conversion_plan_linkage` separately from value `comparison_status`.
  Omitting both options preserves legacy standalone comparison. This linkage
  validates declarations only and does not establish Spark runtime behavior,
  vector provenance, BW/Fabric execution, equivalence or owner approval.
  The independent local rule evaluation is described below. This slice does not
  parse source definitions or close BW-4.
- **Optional source-declaration preflight delivered — partial (2026-11-11):**
  `migrate_bw_transform_validate.py` requires both the existing
  `--inventory` / `--transformation` pair and the `--definition-file` /
  `--rule-ledger` pair. It reuses complete plan/inventory validation, computes
  SHA-256 from the supplied local definition bytes, and reuses the declared
  plan-versus-ledger rule and input-schema checks. The report records separate
  deterministic `source_declaration_preflight` evidence; it does not write or
  execute a notebook. The full local suite reports **550 passed, 515 subtests
  passed**. This evidence does not establish SAP authenticity, independent
  source-to-ledger correspondence or completeness, vector provenance, runtime
  execution, semantic equivalence or owner approval; those remain unverified
  or `not_run`.
- **Normalized-rule vector evaluation delivered — partial (2026-11-12):**
  with a linked plan, the vector validator locally evaluates `transfer`, typed
  constants, and same-scale decimal add/subtract rules against declared inputs
  and checks results against expected outputs. Decimal strings must fit the
  declared precision and scale without rounding; null decimal operands
  propagate as null. Plan-valid Spark types outside the evaluator subset remain
  `not_run`; invalid conversion-plan types are rejected by the CLI. Invalid
  values referenced by a rule or used as expected outputs fail local evaluation
  when invalid; unused input values are not type-checked. No SAP, Spark, or Fabric runtime,
  vector-provenance, semantic-equivalence, or BW-4 closure evidence is
  established by this slice. CLI exit 0 does not imply a `not_run` evaluation
  ran or passed.
- **Next change and scope (blocked/planned):** source-owner-approved
  source-definition format selection and parser work, and independently
  obtained, source-owner-approved golden vectors, are explicitly blocked and
  not delivered. First, the BW source owner must agree on source-definition
  format, authority, access, ownership and coverage before a bounded parser
  slice is selected; vector provenance must be established independently and
  accepted by the owner.
  `Assessor` owns the offline source-definition/rule contract; `Extractor` is
  a proposed collaborator only after parser format and ownership are assigned.
  `Evidence` owns comparison of independently obtained vectors; `Fabric` and
  `Orchestrator` own any necessary generator and CLI changes; `Tester` owns
  tests. Live BW discovery remains unassigned. No parser capability or
  source/vector provenance is assumed by this plan.
- **Further conversion work:** source owners must inventory and review
  start/end/expert and field routines, lookups, ordering, state, errors and
  side effects. Any future conditional, lookup or routine conversion requires
  an explicitly supported semantic contract and source-derived test vectors;
  otherwise use an accepted manual redesign or retain a blocker. Do not infer
  ABAP behavior from Spark/SQL or silently accept unknown features.
- **Dependencies:** BW-1 inventory and version policy, BW-2 snapshot baseline,
  and BW-3 source mapping before retirement; an assigned BW source owner, an
  agreed source-definition format, approved access and business test cases.
  The local fixture is not a source-owner baseline or an SAP extraction.
- **Validation / exit:** `Tester` should retain focused coverage of matching and
  mismatched definition bytes, missing/extra/changed or unsupported rules,
  missing/duplicate source IDs, changed input schema, unpaired options, lineage,
  no-overwrite and 1.0 declaration-only compatibility. Run the focused
  `python -m pytest tests/test_bw_transform_generator.py tests/test_bw_transform_validation.py tests/test_bw_inventory_contract.py tests/test_agent_contracts.py --tb=short -q`
  and required `python -m pytest tests/ --tb=short -q` suites. For the BW-4
  gate, independently obtained source and target golden cases must cover nulls,
  types, rounding, date/fiscal logic, ordering, duplicates, lookups and
  failure paths, with agreed tolerances and owner acceptance. Every routine
  must be evidenced, manually accepted or block the wave; generator defects
  must be fixed at source, not hidden by metrics.
- **Risks / non-goals:** a matching hash or rule ledger cannot establish its
  own authenticity or completeness; undocumented dependencies and side
  effects remain risks. Actual Spark/Delta, Fabric and SAP execution, source
  and target golden-case execution, semantic equivalence and business approval
  are `not_run`. No ABAP parsing, completeness attestation, BW-4 gate closure,
  cutover or retirement approval is implied.

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
- **Local paginated target:** `migrate.py --output-format rdl` and
  `migrate_paginated.py` create a basic RDL table
  from an explicit DAX/field mapping and semantic-model reference, for declared
  Crystal/WebI or BW/BEx sources. The source kind is a label, not a parser or
  adapter; BO prompts, formulas, layouts and security are not automatically
  converted. Manually declared SQL Server scalar parameters are a separate
  local slice; see the 2026-11-16 increment above. Model binding, Report Builder
  rendering, execution and equivalence remain `not_run`. The future
  consumer-replacement gate still requires the source-to-target evidence
  described above.
- **BO visual fidelity next steps:** obtain representative non-sensitive Crystal
  and WebI examples and supported source renderers; extract page dimensions,
  positioned objects and styles with traceable provenance; map supported elements
  to RDL with explicit unsupported-item diagnostics. Then implement opt-in,
  document-bound local captures for BO and Power BI Desktop or Report Builder,
  explicit page pairing and bounded pixel diagnostics. Captures, query execution
  and business equivalence remain separate evidence; no pixel-perfect claim
  follows from static metadata or a generated RDL.
- **Local slice delivered (2026-11-11):** the separate versioned BEx semantic
  contract, synthetic partial example and `migrate_bw_bex_assess.py` capture
  declarations for variables/prompts, filters, hierarchies, master-data
  validity, key-figure aggregation, exception aggregation, units/currencies,
  authorization contexts and inventory-linked consumers. The local report
  flags incomplete or unknown semantics, unresolved query-to-consumer coverage
  and BW inventory BEx blockers; an open BW-0 inventory review also blocks
  the BW-5 candidate. That initial semantic-capture slice did not itself parse
  a BW query, generate a target model/report, execute source or target queries,
  compare result vectors, measure performance, or establish consumer
  acceptance. A separate local comparator is now delivered as described above;
  it compares declared vectors only and does not establish runtime or parity.
  The sample is synthetic, and neither slice closes BW-5 or authorizes
  retirement.
- **Provider linkage (2026-11-19):** BW-5 now lists direct BEx `queries`
  edges and blocks missing or unverified links, blocked queries and providers,
  invalid providers,
  unresolved provider features, and unobserved InfoCube metadata, keys or
  semantics. This is a local declaration review, not native discovery,
  transitive lineage, cube conversion, or source-to-target validation.
- **Definition linkage (2026-11-19):** the BEx query definition in the BW
  inventory must be observed and carry a SHA-256 digest matching the semantic
  manifest. Missing/unobserved digests block owner review. This compares local
  declarations only; it does not verify definition bytes or SAP origin.
- **InfoCube keys (2026-11-19):** directly linked InfoCubes must declare a
  non-empty key list with no unknown key roles. This checks declaration
  completeness for grain design, not that the declared grain is correct.
- **BEx key-figure bindings (2026-11-19):** manifest 1.1 can explicitly map
  each BEx key figure to one measure on a directly linked provider. The
  assessor verifies declared linkage, evidence and a unique observed
  provider-measure name; unresolved mappings block owner review. The report
  carries per-key-figure mapping status. This does not evaluate
  calculated/restricted key figures or generate DAX/model objects.
- **Explicit BW Power Query selection (2026-11-19):** the Python M builder
  accepts a manually declared InfoArea, cube ID and dimension/measure selectors
  with application-server parameters. It emits connector implementation 2.0,
  but does not extract selectors or convert BEx variables, formulas or security.
  SAP connection, refresh and result reconciliation remain `not_run`.
- **Local increment — declaration-based BW cube PBIP (2026-11-19; bounded,
  does not close BW-5):**
  - **Outcome:** `migrate_bw_bex_pbip.py` generates an Import PBIP and empty
    report shell from a strict version 1.0 local plan that manually maps
    exactly one SAP BW cube. This is a local target-generation slice, not
    automatic BEx or semantic conversion.
  - **Current evidence:** the plan schema and runtime reject credential
    fields, server values using `@` or `://` syntax, unsafe Windows project
    names, and output-column mismatches. Generation requires a new, empty
    output directory and runs the static `ArtifactValidator`; static warnings
    do not fail the generation. The final full local suite is recorded above.
  - **Falsifiable hypothesis:** a valid, manually mapped one-cube plan can
    produce a statically checked local Import PBIP while invalid plan fields
    and output-column mismatches are rejected; successful generation does
    not establish that the declarations match SAP.
  - **First change / cohesive scope:** the bounded `migrate_bw_bex_pbip.py`
    local generation path, strict plan contract and corresponding regression
    coverage. No source extraction, BEx conversion, or remote operation is
    part of this slice.
  - **Owner:** `Orchestrator` owns the CLI and plan/fixture contract;
    `Assessor` owns static validation; `Tester` owns regression coverage.
  - **Dependencies:** a manually authored version 1.0 plan, the existing
    Import PBIP generation path and static `ArtifactValidator`, plus a new,
    empty local output directory. No SAP or cloud access is required for
    local generation.
  - **Validation / exit gate:** final full-suite validation:
    `python -m pytest tests/ --tb=short -q -o addopts=''` =>
    **811 passed, 1 skipped, 909 subtests passed**. This verifies local tests
    only; it does not close the BW-5 semantic or consumer-replacement gate.
  - **Risks / non-goals:** the plan's declarations do not establish that the
    selected cube, selectors, metadata or output columns match SAP. This does
    not extract or verify SAP metadata, execute SAP queries, convert BEx
    semantics, or establish Desktop opening/rendering, refresh, result
    reconciliation, equivalence or consumer acceptance; those checks remain
    `not_run`. BW-5 remains open.

- **Local increment — optional BW-5 linkage for cube PBIP (2026-11-19; bounded,
    does not close BW-5):**
    - **Outcome:** plan version 1.1 optionally declares the BEx query, its BW
      inventory provider, selected cube ID and selected key-figure mappings.
      With the paired local inventory and BEx manifest, PBIP generation runs
      the existing BW-5 assessment and requires `candidate_for_owner_review`,
      an observed direct InfoCube dependency and observed key-figure/provider
      measure links matching the declared selectors.
    - **Evidence:** successful local generation writes
      `bex_linkage_assessment.json` with the plan linkage and offline assessment.
      Tests cover the candidate path, open semantic coverage, wrong provider,
      selector mismatch, and missing paired inputs. Version 1.0 generation
      without linkage remains supported.
    - **Owners:** `Orchestrator` owns the plan/CLI; `Assessor` owns the reused
      offline assessment; `Tester` owns regression coverage.
    - **Dependencies:** local BW inventory and BEx semantic-capture declarations,
      the existing BW-5 assessment, and an explicitly authored v1.1 plan.
      No SAP or cloud access is used.
    - **Validation / exit:** focused
      `tests/test_migrate_bw_bex_pbip.py`: **11 passed, 25 subtests passed**.
      Final full local suite: `python -m pytest tests\ --tb=short -q -o addopts=''`
      => **813 passed, 1 skipped, 913 subtests passed**. Ruff and
      `git diff --check` passed after the final formatting correction. These
      verify local declaration consistency only; `candidate_for_owner_review`
      does not close BW-5.
    - **Risks / non-goals:** the declared cube ID is not verified against SAP or
      the inventory object's native metadata. The CLI does not extract a BEx
      definition, convert variables/formulas/security, execute queries, validate
      Desktop rendering, or establish source-to-target parity. Those checks
      remain `not_run`.

- **Local increment — suppress implicit BW aggregation (2026-11-19; bounded,
  does not add BEx measures):**
  - **Outcome:** TMDL generation sets `summarizeBy: none` for every SAP BW
    source column, including numeric dimensions and key figures. SQL and other
    non-BW sources retain the prior numeric `sum` default.
  - **Reason:** this Import draft has no generated explicit DAX measures, and
    a numeric BW field must not be re-aggregated by Power BI before its BEx
    aggregation or exception-aggregation semantics are reviewed.
  - **Owners:** `Semantic` owns `powerbi_import/tmdl_generator.py`;
    `Tester` owns the focused BW TMDL regression; documentation was updated
    locally.
  - **Dependencies:** the existing explicit SAP BW connection/type and the
    table's Import model columns. No new source metadata or runtime access is
    required.
  - **Validation / exit:** focused `tests/test_sap_bw_m_query.py`: **8 passed,
    8 subtests passed**. Final full local suite:
    `python -m pytest tests\ --tb=short -q -o addopts=''` =>
    **814 passed, 1 skipped, 913 subtests passed**. A focused Ruff rule set
    still reports five pre-existing diagnostics elsewhere in
    `tmdl_generator.py`; none is on the changed lines. This tests static
    model metadata only, not query execution, Desktop behavior or BEx
    equivalence.
  - **Risks / non-goals:** disabling implicit aggregation does not reproduce
    BEx calculations or provide replacement measures. It intentionally
    prevents guessed totals until explicit semantics and suitable DAX are
    approved.

- **Local increment — match linked PBIP to BW source client (2026-11-19;
  bounded, does not close BW-5):**
  - **Outcome:** a plan using optional BEx linkage is rejected before output
    creation when its SAP `client_id` differs from the client declared by the
    linked BW inventory. Standalone plans remain unchanged.
  - **Reason:** a BEx assessment for one SAP client must not be presented as
    linkage evidence for a PBIP draft targeting another client.
  - **Owners:** `Orchestrator` owns `migrate_bw_bex_pbip.py`; `Tester` owns the
    CLI regression; the BW design and changelog were updated.
  - **Dependencies:** the existing BW inventory source-client declaration and
    the PBIP plan connection. This does not add inventory fields or infer
    server, system-number or native InfoCube identity.
  - **Validation / exit:** focused
    `tests/test_migrate_bw_bex_pbip.py`: **11 passed, 26 subtests passed**.
    Full local suite: `python -m pytest tests/ --tb=short -q -o addopts=''`
    => **814 passed, 1 skipped, 914 subtests passed**. `git diff --check`
    passed. These checks cover local declarations only.
  - **Risks / non-goals:** client equality does not authenticate either
    declaration, verify the host/system number or cube ID, connect to SAP,
    execute a query, establish BEx parity, or close BW-5. Runtime checks remain
    `not_run`.

- **Local increment — link selected dimensions to InfoCube declarations
  (2026-11-19; bounded, does not close BW-5):**
  - **Outcome:** optional `bex_linkage.dimension_bindings` maps each selected
    Power Query dimension selector exactly once to an observed dimension name
    in the selected InfoCube's inventory semantics. Mismatched, duplicate or
    unobserved bindings fail before PBIP output creation. Existing linked 1.1
    plans may omit this optional check.
  - **Owners:** `Orchestrator` owns the plan schema and CLI; `Tester` owns the
    positive, negative and compatibility regressions.
  - **Dependencies:** selected BW navigation dimensions, the linked InfoCube's
    declared semantic dimensions and the existing BW-5 assessment. No SAP or
    cloud access is used.
  - **Validation / exit:** focused
    `tests/test_migrate_bw_bex_pbip.py`: **11 passed, 29 subtests passed**.
    Full local suite: `python -m pytest tests/ --tb=short -q -o addopts=''`
    => **814 passed, 1 skipped, 917 subtests passed**. Ruff, `py_compile` and
    `git diff --check` passed.
  - **Risks / non-goals:** this binds plan declarations to provider inventory
    declarations only; it does not prove that the BEx query uses a selected
    dimension or that its selector is valid in SAP. It does not convert query
    filters, hierarchies or master data, establish equivalence, or close BW-5.
    Runtime checks remain `not_run`.

- **Local increment — require dimension bindings in BEx plan 1.2
  (2026-11-19; bounded, does not close BW-5):**
  - **Outcome:** plan version 1.2 requires `dimension_bindings` whenever
    `bex_linkage` is declared, and the CLI verifies complete selector coverage.
    Version 1.1 remains compatible with its prior optional linkage shape.
  - **Owners:** `Orchestrator` owns the plan schema and CLI; `Tester` owns
    version and compatibility regressions.
  - **Dependencies:** the existing provider-dimension declaration check and
    explicit selected navigation dimensions. No SAP or cloud access is used.
  - **Validation / exit:** focused
    `tests/test_migrate_bw_bex_pbip.py`: **11 passed, 30 subtests passed**.
    Full local suite: `python -m pytest tests/ --tb=short -q -o addopts=''`
    => **814 passed, 1 skipped, 918 subtests passed**.
  - **Risks / non-goals:** required plan declarations do not establish BEx
    query membership or selector correctness in SAP. Query filters, hierarchies
    and master data remain unmapped; BW-5 and runtime checks remain `not_run`.

- **Delivered local increment — disclose unverified native InfoCube identity
  (2026-11-19; bounded, does not close BW-5):**
  - **Outcome:** linked PBIP generation records the root field
    `native_infocube_identity_verification: "not_verified"` in
    `bex_linkage_assessment.json`. The positive linked v1.2 regression checks
    this status. It makes the limit of local linkage evidence explicit; it is
    not native identity verification or the P1 identity control.
  - **Current evidence / hypothesis:** local query, provider, cube, client and
    dimension declarations can cross-check without proving that the declared
    InfoCube is the native SAP object. The BW design document and changelog
    explain this limitation. Hypothesis: an explicit fixed status in the
    generated assessment prevents a local cross-check from being mistaken for
    native verification without changing the plan contract or source data.
  - **First change / cohesive scope:** add the constant status to the root of
    the existing linkage assessment JSON and assert it on the successful
    linked v1.2 path. No plan/schema change, source-data addition or inferred
    identity mapping is part of this transparency slice.
  - **Owners:** `Orchestrator` owns the CLI evidence output; `Tester` owns the
    positive linked v1.2 assertion; the design document and changelog record
    the limitation. `Roadmap Planner` records this increment here.
  - **Dependencies:** the existing linked v1.2 plan and local linkage
    assessment. No sanitized identity sample is available or required for
    this status-only increment.
  - **Validation / exit:** the focused positive linked v1.2 regression asserts
    the root status. The current recorded full local suite is
    `python -m pytest tests/ --tb=short -q -o addopts=''` =>
    **814 passed, 1 skipped, 918 subtests passed**. These are local checks only;
    no runtime or source-to-target evidence is implied.
  - **Risks / non-goals:** this is a transparency measure, not the native
    InfoCube identity check. The plan and contract remain unchanged; no source
    data is invented and no SAP access, query execution, or equivalence check
    is performed. Native identity evidence, SAP/runtime checks and
    source-to-target equivalence remain `not_run`; BW-5 remains open.

- **Local increment — disclose selected BEx key figures and ambiguous dimensions
  (2026-11-19; bounded, does not close BW-5):**
  - **Outcome:** linked PBIP evidence lists the selected and unselected
    key-figure IDs from the local manifest. A partial selection warns without
    blocking the draft; an empty manifest is reported separately. A supplied
    InfoCube dimension binding must resolve to one observed local declaration.
  - **Dependencies / compatibility:** the existing linked plan, BW inventory
    and BEx semantic manifest; no plan schema change or inferred SAP mapping.
    Version 1.1 plans without dimension bindings remain supported. The added
    report field may require closed-schema consumers to accept it.
  - **Validation:** focused BEx/PBIP/M tests passed with **39 passed, 70
    subtests passed**; the required full test suite also passed. These checks
    exercise synthetic declarations, not SAP or Power BI runtime behavior.
  - **Risks / non-goals:** selected IDs and unique names do not prove SAP
    identity, query membership, business grain, formula conversion or BEx
    parity. Runtime and business acceptance remain `not_run`.

- **Next proposed increment — establish native InfoCube identity evidence
  (P1; planned, not implemented; blocked on sanitized, source-owner-approved
  identity evidence):**
  - **Outcome:** determine whether the InfoCube named by a linked PBIP plan is
    the same native source object as its declared BW inventory provider, and
    prevent a local declaration match from being described as native identity
    verification. Keep the PBIP an Import draft; this increment does not close
    BW-5.
  - **Current evidence / hypothesis:** plan v1.2 cross-checks local query,
    provider, cube, client, dimension and key-figure declarations. The current
    design explicitly says these checks do not verify the native InfoCube ID.
    The inventory has generic object `id`, `name` and optional
    `source_reference` fields, but the available contract does not define any
    of them as the SAP-native identity corresponding to `cube_id`. Hypothesis:
    one source-owner-approved identity evidence sample and an explicitly
    reviewed field mapping can support a deterministic local mismatch check;
    without that evidence, no identity-verification behavior can be claimed.
  - **First change / cohesive scope:** obtain one sanitized, non-sensitive,
    source-owner-approved InfoCube identity evidence sample and provenance;
    document which observed field, if any, maps to the existing inventory and
    plan declarations. Do not infer this mapping from field names or introduce
    a SAP extraction/API contract. If the evidence does not fit the existing
    contract, stop and return the smallest proposed contract change for review
    before implementation. Once approved, implement only the local identity
    cross-check and its assessment evidence; do not broaden semantic mapping or
    target generation.
  - **Owners:** `Assessor` owns offline inventory/BEx identity assessment;
    `Orchestrator` owns linked PBIP gating and any approved plan contract
    changes; `Tester` owns positive, mismatch, missing-evidence and
    compatibility regressions.
  - **Dependencies:** currently blocked pending sanitized, source-owner-approved
    identity evidence and confirmation of its meaning; then the current BW
    inventory, BEx semantic manifest and linked v1.2 plan. No SAP connection
    or remote target is required for the local check.
  - **Validation / exit gate:** first show that the agreed mapping distinguishes
    a matching object from a mismatched, absent or ambiguous identity in local
    fixtures, and that mismatch/insufficient evidence cannot produce a linked
    PBIP. Preserve v1.0/v1.1 behavior and existing v1.2 declaration checks.
    Run the focused BEx assessment and
    `tests/test_migrate_bw_bex_pbip.py`, then the required full suite
    `python -m pytest tests/ --tb=short -q`. Exit only when the mapping is
    traceable to approved evidence, regressions pass, and reports still
    distinguish local cross-checks from SAP verification. Live SAP identity
    confirmation, query execution, Desktop rendering, refresh and equivalence
    stay `not_run` unless separately authorized and performed.
  - **Risks / non-goals:** a hash, matching client, inventory dependency,
    matching plan strings or synthetic fixture alone cannot prove SAP object
    identity. Do not invent the missing source contract or claim source
    provenance from local declarations. Filters, variables, hierarchies, master
    data, authorizations, formulas and exception aggregation remain
    unconverted; semantic conversion and consumer parity are later work.

- **Local increment — expose selected BEx key-figure declarations
  (2026-11-19; bounded, does not close BW-5):**
  - **Outcome:** linked PBIP evidence includes each selected key figure's
    target selector/column, manifest status, declared aggregation,
    exception-aggregation and unit/currency fields. The scope is explicitly
    `local_bex_manifest_declarations_only`; no DAX measure or interpreted
    semantics is generated.
  - **Reason:** the prior evidence listed selected/unselected IDs but did not
    put the selected figures' declared numeric semantics alongside their
    target mapping for owner review. Native InfoCube identity remains blocked
    pending source-owner-approved evidence; this local report enhancement does
    not resolve that dependency.
  - **Owners:** `Orchestrator` owns `migrate_bw_bex_pbip.py`; `Tester` owns the
    positive, partial-selection and empty-selection regressions. The BW design
    and changelog record the additive report detail.
  - **Dependencies:** the existing linked plan and validated local BEx
    manifest. No source contract, SAP access, or runtime input is added.
  - **Validation / exit:** the focused
    `tests/test_migrate_bw_bex_pbip.py` passes. Full local suite:
    `python -m pytest tests/ --tb=short -q -o addopts=''` =>
    **817 passed, 1 skipped, 920 subtests passed**. Ruff, `py_compile` and
    `git diff --check` pass. These validate declaration reporting only.
  - **Risks / non-goals:** manifest values may be incomplete or unverified
    relative to SAP. This report does not determine aggregation safety, convert
    exception aggregation/units, create DAX measures, run source/target queries
    or close BW-5; those checks remain `not_run`.

- **Local increment — surface BW-5 review findings during PBIP generation
  (2026-11-19; bounded, does not close BW-5):**
  - **Outcome:** when a linked PBIP passes the BW-5 blocker gate but the
    assessment retains review findings, the CLI prints their count and the
    `bex_linkage_assessment.json` path. Generation remains successful and the
    report remains the source of finding details.
  - **Reason:** `candidate_for_owner_review` can coexist with unresolved
    review-level evidence. A success-only status line did not surface that
    remaining work at the point of generation.
  - **Owners:** `Orchestrator` owns the CLI warning; `Tester` owns the positive
    regression that asserts both the finding count and report path.
  - **Dependencies:** the existing BW-5 report summary and the linked PBIP
    evidence file. The warning is absent when the report has zero review items.
  - **Validation / exit:** the focused
    `tests/test_migrate_bw_bex_pbip.py` passes. Full local suite:
    `python -m pytest tests/ --tb=short -q -o addopts=''` =>
    **817 passed, 1 skipped, 920 subtests passed**. Ruff, `py_compile` and
    `git diff --check` pass.
  - **Risks / non-goals:** the warning is informational; it does not prevent
    generation, resolve the findings, close BW-5, verify SAP declarations or
    establish runtime/equivalence evidence.

- **Local increment — report BW-5 blockers when linked PBIP is refused
  (2026-11-19; bounded, does not close BW-5):**
  - **Outcome:** failed linked-plan gating reports the total blocker count, up
    to three finding codes and JSON paths, and an additional-blocker count
    when applicable. It still rejects before creating PBIP output.
  - **Reason:** the prior error exposed blocker codes without their manifest
    paths or count, making it harder to locate incomplete BW-5 declarations.
  - **Owners:** `Orchestrator` owns the CLI error; `Tester` owns regressions for
    a single blocker and for bounded diagnostics with multiple blockers.
  - **Dependencies:** the existing BW-5 finding records. No schema, source
    evidence or runtime behavior changes.
  - **Validation / exit:** focused
    `tests/test_migrate_bw_bex_pbip.py` passes. Full local suite:
    `python -m pytest tests/ --tb=short -q -o addopts=''` =>
    **819 passed, 1 skipped, 920 subtests passed**. Ruff, `py_compile` and
    `git diff --check` pass.
  - **Risks / non-goals:** diagnostics expose only local finding codes and
    declaration paths. They do not resolve blockers, verify SAP metadata,
    generate a report on refusal, or close BW-5.

- **Local increment — disclose declared BEx semantics not reproduced
  (2026-11-19; bounded, does not close BW-5):**
  - **Outcome:** linked evidence counts manifest declarations for variables,
    filters, hierarchies, master data, key-figure semantics and authorization
    contexts. Any positive count emits a non-blocking warning pointing to the
    evidence file; the output marks the scope as
    `declared_local_manifest_counts_only`.
  - **Reason:** a statically valid PBIP draft can still omit declared BEx
    behavior. A summary warning and persisted counts make this limitation
    visible without pretending that an unsupported translation exists.
  - **Owners:** `Orchestrator` owns the PBIP evidence and CLI warning;
    `Tester` owns regressions for populated and empty manifest sections.
  - **Dependencies:** the existing BW-5 manifest contract. No source fields,
    SAP access, schema changes or runtime checks are added.
  - **Validation / exit:** focused
    `tests/test_migrate_bw_bex_pbip.py` passes. Full local suite:
    `python -m pytest tests/ --tb=short -q -o addopts=''` =>
    **820 passed, 1 skipped, 920 subtests passed**. Ruff, `py_compile` and
    `git diff --check` pass.
  - **Risks / non-goals:** counts cover only local declarations; zero does not
    prove the SAP query lacks those semantics. No variables, filters,
    hierarchies, master data, key-figure calculations/aggregation or
    authorizations are reproduced, and BW-5 remains open.

- **Local increment — explicitly selected BW dimension member properties
  (2026-11-19; bounded, does not close BW-5):**
  - **Outcome:** plan 1.3 optionally maps declared dimension member-property
    selectors to Import-model columns. The M generator emits
    `Cube.AttributeMemberProperty` after expanding the corresponding dimension.
    Version 1.3 retains the 1.2 linked-plan dimension-binding requirement;
    versions 1.0-1.2 keep their previous shapes. BW-only models no longer
    generate automatic Calendar tables, date relationships or date-part
    hierarchies from these declared dates; non-BW behavior remains unchanged.
  - **Evidence:** synthetic regressions exercise standalone and linked PBIP,
    Unicode/quoting, source-column matching, duplicate names, invalid
    selectors, older-version rejection, date-enrichment safeguards and empty
    report preservation.
  - **Validation:** focused BW M and PBIP tests and full suite
    **825 passed, 1 skipped, 924 subtests**. Local validation does
    not execute Power Query or verify SAP metadata.
  - **Boundaries:** member keys and data types are manually declared, not
    discovered or validated. A typed date requires connector prerequisites
    and authorized SAP testing. No report visual, BEx variable, formula,
    aggregation or security logic is inferred; runtime and parity remain
    `not_run`.

- **Local increment — explicit BW cube parameter arguments
  (bounded, does not close BW-5):**
  - **Outcome:** plan 1.4 optionally emits manually declared parameter
    selectors and literal text argument lists with `Cube.ApplyParameter`,
    before dimensions and measures. Earlier plan shapes are preserved.
  - **Validation / exit:** focused tests cover quoting, list shapes, invalid
    declarations, standalone/linked PBIP and retained linkage requirements.
    Local checks do not execute Power Query.
  - **Boundaries:** no BEx prompt mapping, automatic parameter discovery,
    range interpretation or runtime equivalence. SAP compatibility, query
    folding, refresh and parity remain `not_run`. Literal values are present
    in the plan and generated model and require protection.

- **Local increment — BEx variable ID to cube-parameter declaration
  (plan 1.5; bounded, does not close BW-5):**
  - **Outcome:** a parameter can explicitly cite one variable ID from the
    linked BEx manifest. The linkage report shows mapped/unmapped variable
    declarations and selector metadata but excludes literal values.
  - **Validation / exit:** local checks require one-to-one IDs, an exact
    manifest reference and the existing BW-5 linkage inputs; generated M
    retains the declared `Cube.ApplyParameter` call.
  - **Boundaries:** this is a manually asserted association, not SAP discovery
    or evidence that defaults, prompt behavior, range logic, authorization,
    folding or results match. Variables remain in the unconverted count;
    runtime and parity remain `not_run`.

- **Local increment — expose declared BEx coverage in PBIP evidence
  (bounded, does not close BW-5):**
  - **Outcome:** `bex_linkage_assessment.json` carries the validated local
    manifest's category coverage declarations beside the counts of semantic
    items not reproduced. Empty sections explicitly marked `not_applicable`
    are distinguishable from counts alone.
  - **Reason:** a zero item count does not explain whether a category was
    declared not applicable or merely has no listed items. The report now
    preserves the local manifest's separate coverage claim.
  - **Owners:** `Orchestrator` owns the linked PBIP evidence payload;
    `Tester` owns the regression checking the additive coverage field.
  - **Dependencies:** the existing validated BW-5 manifest and linked PBIP
    flow. No schema, SAP access, or runtime behavior changes.
  - **Validation / exit:** focused
    `tests/test_migrate_bw_bex_pbip.py` => **25 passed, 43 subtests**.
    Full suite `python -m pytest tests/ --tb=short -q -o addopts=''` =>
    **832 passed, 1 skipped, 941 subtests**. No SAP, Desktop, Fabric
    execution or parity evidence is inferred.
  - **Boundaries:** coverage values are copied local declarations, not
    independently verified SAP facts. `not_applicable` and zero counts do
    not establish that SAP lacks the corresponding semantics; BW-5 remains
    open.

- **Local increment — generated-model M and DAX review files
  (bounded, does not close BW-5):**
  - **Outcome / first change (delivered):** `powerbi_import.expression_export`
    creates review copies from expressions already written in generated TMDL
    and Dataflow files, without translating source objects again. Export is
    integrated into model generation, not a manual prerequisite.
  - **Evidence / hypothesis:** the exporter tests compare copies with generated
    expressions and check missing expressions and conflicts. The non-archive
    BO folder regression changes a generated measure during optional
    optimization and checks that the later copy reflects that change. A copy
    without a corresponding generated expression, or one retaining the
    earlier expression, would falsify this behavior.
  - **Routes:** automatic export covers generated PBIP/Fabric models from BO
    folders and supported BIAR entries; the merged shared model, once rather
    than per thin report; the Python importer for PBIP, TMDL or Fabric unless
    explicitly deferred; and the confirmed local MCP migration and shared-model
    routes. A declared REP PBIP draft uses its per-source mapping and accepted
    SQL candidate, then exports automatically. `migrate_bw_bex_pbip.py`
    exports the generated BW cube model. For non-archive BO folder items,
    export follows optional DAX optimization; the separate exporter command
    remains available for an existing model.
  - **Copies / provenance:** M partitions and shared expressions or parameters
    become `.pq` files. Actual DAX measures, calculated columns, calculated
    tables' partitions, calculation-group items and role filters become `.dax`
    review listings when present. Fabric also copies each generated Dataflow
    query from `.m` to `PowerQuery/Dataflow/*.pq`, as well as any exportable
    TMDL expressions. `expression_export.json` version `1.1` records each
    output path, source and kind: TMDL sources are relative to the model
    definition, while Dataflow sources are project-relative and marked
    `"source_scope": "project"`.
  - **Boundaries:** no DAX is invented when a generated model has none; the BW
    cube fixture contains M but no DAX, and cube selectors do not imply DAX
    measures. A project with no exportable model or Dataflow expressions has
    an empty `exports` list. RDL alone has no model expression export, although
    it can have a separate optional `.m`; extraction or assessment without a
    model likewise has no such export. BW Bronze and transformation notebook-only
    paths (`migrate_bw.py`, `migrate_bw_convert.py`) produce notebooks rather
    than a model expression export.
  - **Owners:** `Wiring` owns the exporter; `Orchestrator` owns CLI, importer
    and cube integration; `Fabric` owns Dataflow generation; `AgentTools` owns
    the MCP surface; `Tester` owns regression coverage.
  - **Dependencies / conflicts:** a generated model in this project's TMDL
    form, plus generated Dataflow queries where applicable. Name collisions,
    including case-insensitive collisions, and existing `PowerQuery`, `DAX`
    or `expression_export.json` targets are refused rather than overwritten.
    The standalone command requires a new or empty directory separate from
    the model.
  - **Validation / exit:** check the exporter, folder/BIAR, shared-model, MCP,
    declared REP and BW cube regressions, including
    `tests/test_expression_export.py`, `tests/test_cli.py`,
    `tests/test_shared_model.py`, `tests/test_mcp_server.py` and
    `tests/test_migrate_bw_bex_pbip.py`; then require
    `python -m pytest tests/ --tb=short -q`. Copies must reflect the written
    expressions, retain versioned provenance, omit absent DAX and reject
    conflicts without replacing existing output.
  - **Risks / non-goals:** these are snapshots, not changes to extraction,
    conversion or the generated model. The exporter is not a general TMDL
    parser, and other I/O failures can leave partial output. Copies can contain
    sensitive SQL, connection or parameter values; protect them and use a new
    directory after model edits.

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
- Controls 1.1 adds declared dispositions for Copy Version, Upload File,
  cube activation, planning reporting, Forecast Update and
  consolidation/aggregation. Complete coverage requires all six; in-scope
  entries need an external owner, target and evidence. Version 1.0 remains
  compatible, and all execution remains `not_run`.
- Validation is limited to local declarations and source-inventory references.
  It does not execute target access tests, verify runtime identity/binding, run
  planning/write-back, certify compliance, close a gate or authorize retirement.
  `candidate_for_owner_review` is not acceptance; `gate_closed` remains `false`.
  All unperformed runtime evidence, including SAP BW and Fabric runtime checks,
  remains `not_run`.
- **Focused validation (2026-11-20):**
  `python -m pytest tests/test_bw_controls_assessment.py --tb=short -q
  -o addopts=''` passed 12 tests and 7 subtests.
- **Historical focused validation (2026-11-11):**
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

- **Outcome:** establish a controlled cutover and retirement process for all
  approved waves; actual switching and decommissioning remain separately
  authorized customer operations.
- **Evidence / hypothesis:** no cutover or retirement is established by local
  generation. Hypothesis: consumers and feeds remain correct and recoverable
  during an agreed parallel-run and a BW-independent observation period.
- **Local slice delivered:** `migrate_bw_cutover_assess.py` evaluates one
  versioned BW-8 declaration set against the BW inventory and BW-7 wave
  manifest. It requires explicit dependency coverage/dispositions, plan and
  checkpoint references, declared parallel-run and independent-observation
  durations, operational upstream-feed and reconciliation declarations,
  planning/retention sign-off, rollback objectives/exercise status, and
  owner/evidence/approval references, including explicit owner acceptance of
  BW-0 through BW-7. It
  reports blockers or
  `declarations_complete_for_owner_review`; that status does not establish
  acceptance. The assessment always leaves `gate_closed`, `cutover_authorized`
  and `retirement_authorized` false. It checks inventory edges directly incident
  to the wave and their endpoint consumers, not transitive dependencies;
  coverage completeness is not independently verified.
- **Remaining change and scope:** `Orchestrator` coordinates an authorized
  wave runbook with `Evidence`, `Fabric`, `Deployer` and named customer owners:
  freeze and watermarks, parallel run, consumer switching, communications,
  go/no-go, rollback triggers and time limit, escalation and post-cutover
  monitoring. Maintain an explicit register of BO and non-BO consumers,
  upstream queues, jobs, accounts, integrations and retained audit/legal records.
- **Dependencies:** all BW-0 through BW-7 wave gates; every consumer and
  upstream dependency migrated or dispositioned, planning and retention signed
  off, operational ownership and rollback funded. Enterprise retirement follows
  completion of all waves, not just the pilot.
- **Validation / exit:** agree and record parallel-run duration, observation
  window, reconciliation thresholds and rollback/recovery objectives before
  cutover. The local declaration assessor must reject BW-0/BW-7 review
  statuses of `open`,
  missing consumers/dependencies, incomplete periods, and absent/failed
  approvals or checks. It does not authenticate evidence references or execute
  a drill. The operational exit still requires exercising rollback before the
  irreversible step; verifying consumers, feeds and controls while BW is
  unavailable; explicit business, source, security, compliance and operations
  go/no-go and separate decommission approval; archive restore; no remaining
  live dependencies; and recorded deactivation evidence.
- **Risks / non-goals:** rollback may become impossible after source shutdown
  or data divergence; local declaration completeness is not operational
  readiness. No implicit cloud writes, switch, deletion, license cancellation,
  cutover approval or retirement authorization follows from this roadmap.

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

### Historical Test Table (2026-03-26)

The original rows total 246 tests (245 passing), while the historical summary
above reports 244 tests (243 passing). This discrepancy is not reconciled and
neither figure describes the current suite.

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
