# Full SAP BW to Fabric Migration — Design Baseline

**Status:** proposed end-to-end migration design, with an offline BW inventory
contract and a limited staged-history notebook generator. No SAP or Fabric
runtime validation, customer-estate inventory, or business-result comparison has
been performed. The canonical delivery
sequence and acceptance gates are in the [development plan](DEVELOPMENT_PLAN.md).

## Outcome and boundaries

Replace the complete in-scope BW/BW/4HANA warehouse and its operational
dependencies, not just BusinessObjects reports connected to BW. The intended
end state is an approved set of Fabric data products and consumers fed directly
from supported upstream sources, with historical data, behavior, security and
operations reconciled before BW retirement. SAP source systems may still be
required; retirement of those systems is not implied.

The existing BO extraction contract and its 15 collections remain unchanged.
Existing local Fabric artifact generators consume BO-derived inputs; they do
not currently extract a BW estate, translate ABAP or BEx, or prove BW parity.
The repository has a versioned offline BW inventory contract, local snapshot
validator/upgrader and BW-0 gap assessment, plus a separate staged-history
Bronze notebook generator and offline control comparator. These are separate
from the BO contract and are not SAP discovery, source connectivity, BEx/ABAP
conversion or proof of BW parity. Any future adapter to shared BO generators
must be designed and tested separately.

## Decisions and discovery inputs

Before selecting a route or committing dates, the migration team must collect:

| Area | Required input |
|---|---|
| Estate | BW/BW/4HANA and SAP source versions, deployment, support and access restrictions; landscapes and transports |
| Scope | Business domains, object inventory, owners, usage, lifecycle, exclusions, criticality and consumers, including non-BO interfaces |
| Data | Volumes by object and history period, retention/legal holds, keys, grain, change/delete semantics, latency, throughput and peak load |
| Logic | Transformations, DTPs, ABAP routines and dependencies, InfoObjects, time-dependent texts/hierarchies, currencies, units and fiscal variants |
| Consumption | BEx queries, variables, authorizations, aggregates/exception aggregation, exports, APIs, downstream jobs and business acceptance cases |
| Planning | BW-IP/BPC, writeback, locks, workflows, audit and reconciliation needs |
| Operations | Process chains, calendars, monitoring, recovery, RPO/RTO, SLAs, security, cost and approved maintenance windows |
| Target | Fabric region, tenant policy, capacity, network/gateway, identities, governance, workload isolation and environment approvals |

Unknowns must be recorded with an owner and due date, not treated as absent.
The inventory needs an explicit completeness declaration by the SAP and business
owners; automated discovery alone cannot establish that undocumented consumers
or custom code do not exist.

### BW-0 local inventory review

Run `migrate_bw_assess.py` against a validated local 1.0 inventory snapshot to
produce a report of incomplete coverage, missing ownership or criticality,
unknown dispositions, unresolved dependencies, provenance gaps and other
review items. The assessment uses only declarations in that file and never
contacts SAP. `gate_status: candidate_for_owner_review` means only that no
blocking declaration was found; `gate_closed` remains false and owner
attestation, live discovery and program approval remain `not_run`. The sample
inventory is intentionally partial.

## Reference architecture and transition

```text
SAP and non-SAP upstream systems ----> durable ingestion ----+
                                                            |
BW historical extraction (temporary) --> controlled landing |  coexistence only
                                                            v
OneLake Bronze: source snapshots/change events + provenance + replay
       -> Silver: validation, deduplication, conformance, history and transformations
       -> Gold: governed domain facts/dimensions and business calculations
       -> Lakehouse / Warehouse SQL, Power BI semantic models and other consumers

Cross-cutting: catalog/lineage, identity/security, scheduling, observability,
quality, ALM, cost, recovery, reconciliation and cutover evidence.
```

Choose lakehouse schemas versus separate lakehouses/workspaces using actual
isolation, lifecycle, capacity and access requirements. Gold may use a
Warehouse, a Lakehouse, or both according to workload and governance. Direct
Lake is a candidate for compatible OneLake models, not a universal requirement;
validate security, latency, scale and unsupported behavior in the target.
Medallion layers express responsibilities, not a requirement to duplicate
every dataset or an automatic performance or cost guarantee.

Historical BW extraction and durable upstream feeds are independent workstreams.
For each dataset define the initial snapshot boundary, incremental start point,
overlap/deduplication keys, deletes, late arrivals, corrections and replay.
Prove no gap or double counting across the boundary and rehearse restart after
failure. If delete-aware CDC is unavailable, explicitly design and test a
reconciliation/reload alternative; a watermark alone does not capture deletes.
A persistent BW-fed target remains a coexistence state, not a retirement-ready
architecture.

### Mapping is a design hypothesis, not a conversion guarantee

| BW concept | Candidate Fabric treatment | Required decision or evidence |
|---|---|---|
| DataSources, PSA and source extracts | Ingestion and Bronze landing | Supported connector, source permissions, delta/delete/recovery behavior |
| ADSO, DSO, InfoCube | Delta tables and/or Warehouse facts | Grain, keys, history, activation, aggregation and reload semantics |
| InfoObjects, master data | Conformed dimensions and reference data | Attributes, language, texts, validity dates and hierarchies |
| Transformations, DTP, ABAP | Spark, SQL, Dataflow or controlled manual rewrite | Routine logic, dependencies, ordering, error handling and source/target tests |
| CompositeProvider, BEx query | Gold models and semantic models | Joins/unions, variables, restrictions, calculated/restricted key figures and exception aggregation |
| Process chains | Data pipelines and operational controls | Dependency graph, schedule, retry, restart, alerting and ownership |
| Analysis authorizations | Entra/Fabric access plus appropriate model/data security | Identity mapping and positive/negative access tests at every consumption path |
| BW-IP/BPC | Separate planning/writeback solution | Input, locking, workflow, security and audit requirements; no assumed equivalence |

Currency and unit conversion, non-additive measures, fiscal periods, hierarchy
versions, nulls and rounding require explicit business cases; neither copying
tables nor generating a semantic model establishes equivalence.

### Worked example: synthetic Sales domain

This example shows how one dependency slice could be prepared end to end. All
names and relationships below are fictitious; they are not evidence about a
customer estate, a supported BW version, or a completed migration.

| Synthetic BW element | Fabric-side work item | Acceptance evidence |
|---|---|---|
| `ZSALES_ADSO`, with `0CUSTOMER` and `0MATERIAL` master data | Freeze and land a one-time history snapshot in Bronze; preserve source keys, snapshot boundary, source file and run metadata | Provider counts, distinct business keys, nulls and amount totals by fiscal period/company reconcile to independently captured BW controls |
| `ZTR_SALES` transformation and `DTP_SALES_DAILY` | Reimplement the approved rules in Silver; retain source-to-target lineage and explicit currency, unit, hierarchy and correction behavior | Approved golden input/output cases, including duplicates, late corrections, nulls and rounding |
| `PC_SALES_DAILY` process chain | Map real dependencies, retry/restart behavior, calendar and alert ownership to a Fabric Data Factory pipeline | Failure/restart and freshness checks meet owner-approved targets |
| `Q_SALES_MTD` BEx query and a report consumer | Recreate its filters, variables, hierarchy, totals and exception aggregation in a Gold data product and Power BI semantic model | Compare BEx and target results for representative prompts, periods and roles; obtain consumer and business-owner sign-off |
| BW analysis authorizations and any planning/write-back process | Define and test target access separately; identify a supported planning replacement or keep it as an explicit retirement blocker | Positive and negative persona tests, audit/retention checks and planning-workflow acceptance |
| SAP source feeding the BW provider | Establish the steady-state feed directly from that upstream source, independent of BW | Demonstrate a gap-free snapshot-to-delta handoff, including updates, deletes, replay and operation while BW is unavailable |

For the historic landing, a configured BW Open Hub export is one candidate for a
full snapshot. For ongoing data, evaluate a direct feed from the actual upstream
system. For example, SAP Datasphere Outbound can be evaluated where its SAP
source support, Premium Outbound Integration, cloud-storage staging and
commercial terms are acceptable; a feed whose source is still BW is not
independent and does not permit BW retirement. The SAP ABAP Add-On Copy Job can
be evaluated for supported SAP tables, views or CDS views and watermark-based
incremental copying, but a watermark must not be treated as delete-aware CDC.
Select the route per object only after checking the exact BW/source release,
object access, extraction semantics and owner approvals.

The slice passes only if history and ongoing changes join without gaps or
double-counting, all data and semantic checks meet thresholds set by the
business/data owners, security and consumers are accepted, and the target runs
without BW. Apply the same dependency-led process to every in-scope domain;
this single example is not a template that proves complete warehouse coverage.

## Source-route evaluation

The following capability summary was checked against Microsoft Learn on
2026-11-11. It is an initial screening aid, not a compatibility decision for a
particular SAP installation:

| Route | Documented Fabric use and limits | Migration implication |
|---|---|---|
| [SAP BW Open Hub Application Server](https://learn.microsoft.com/en-us/fabric/data-factory/connector-sap-bw-open-hub-application-server-overview) | Data Factory pipeline Copy activity and Lookup; Copy Job source supports **full load**. On-premises gateway and Basic authentication are listed. | Candidate for a BW-managed historical export when the Open Hub objects and BW version are approved; do not assume Copy Job CDC or delete capture. |
| [SAP BW Application Server connector](https://learn.microsoft.com/en-us/fabric/data-factory/connector-sap-bw-application-server) | Power Query/Dataflow Gen2 analytical access; documented BW 7.3, BW 7.5 and BW/4HANA 2.0 support. Connector implementation 1.0 is deprecated in favor of 2.0; Data Factory pipelines do not support this connector. | Coexistence, analysis or comparison path, not a replacement for the warehouse, its process chains or its upstream feeds. |
| [Microsoft SAP ABAP Add-On Copy Job](https://learn.microsoft.com/en-us/fabric/data-factory/copy-job-tutorial-sap-abap) | Supports SAP BW 7.50 and all SAP BW/4HANA versions, plus the listed SAP S/4HANA and ECC releases. Reads tables, views and CDS views; full and watermark-based incremental copy are documented. Requires a gateway, SAP .NET Connector, Add-On transports and the documented network paths. | Potential route for supported tabular upstream objects. A date watermark can reread rows on multiple daily runs; validate keyed Merge, deletes and recovery per object. It does not itself prove delete capture, BW semantic extraction, or compatibility with every BW release. |
| [SAP Datasphere Outbound with Copy Job](https://learn.microsoft.com/en-us/fabric/data-factory/copy-job-tutorial-sap-datasphere) | Initial and delta replication to ADLS Gen2, Amazon S3 or Google Cloud Storage, followed by Copy Job to a supported destination. The article lists SAP BW and BW/4HANA among supported SAP Datasphere source types and calls out Premium Outbound Integration. | Evaluate for source-supported inserts, updates and deletes. Confirm source-object coverage, staging configuration, licensing and cost; if BW itself is the source, this remains a BW dependency. |

These are capabilities of specific connector paths, not a statement that all BW
versions or all BW objects are supported. Record the source release, object
type, route, load mode, delete/correction behavior, throughput, limits,
permissions, gateway/network requirements, licensing, owner and fallback for
each provider. Recheck the linked documentation and obtain SAP/source-owner
approval before a pilot.

For the Fabric target, Microsoft's
[medallion guidance](https://learn.microsoft.com/en-us/fabric/onelake/onelake-medallion-lakehouse-architecture)
and [modern data warehouse example](https://learn.microsoft.com/en-us/azure/architecture/databases/architecture/dataops-mdw)
are useful reference patterns, not a mandated BW design. Preserve raw
source-level history in Bronze, apply governed conformance and history in
Silver, and serve approved business products from Gold. Choose Lakehouse,
Warehouse, or a combination by transformation, SQL, governance and consumption
needs; then prove the BW transformation and consumer semantics rather than
assuming the medallion layers convert them. The linked modern data warehouse
example is specifically SQL-first and uses Warehouse layers; it is not the only
valid Fabric implementation.

## BW inventory contract — BW-1 local implementation

The offline contract is
[sap_bw_inventory.schema.json](schemas/sap_bw_inventory.schema.json), with a
[synthetic example](fixtures/sap_bw_inventory.partial.example.json).
`powerbi_import/bw_inventory.py` provides local snapshot loading, validation,
sanitization and an explicit 0.1-to-1.0 draft upgrade. It does not connect to
SAP, discover a system, dispatch a migration or provide a CLI.
Preserve original identifiers, namespaces and source locations; use separately
mapped target names and never normalize away source distinctions. Avoid
credentials and sensitive payloads; protect inventory and evidence according to
data classification.

The versioned contract records source/version/client/landscape, discovery and
extraction-access status, provenance, objects, typed keys/semantic details,
dependency references, errors, unknowns and unsupported features. The module
exposes `validate_snapshot`, `load_snapshot`, `sanitize_snapshot` and
`upgrade_snapshot` (with `BWInventoryError` for contract failures). The local
tests cover malformed/unsupported-version rejection, credential sanitization
without mutating the input, Unicode IDs/lineage, and the explicit 0.1-to-1.0
upgrade. That upgrade retains known draft fields and leaves newly introduced
information unknown or not assessed rather than inferring it.

The synthetic example is test data, not SAP output. Local tests cover contract
validation and upgrade behavior; they do not prove that a customer's export can
be parsed or that every BW concept has been modeled. No independent JSON Schema
validator has been run against the schema file.

## BW-2 local slice: staged history into Bronze

The separate `migrate_bw.py` entry point consumes an inventory 1.0 and an
explicit [synthetic landing plan](fixtures/sap_bw_bronze_plan.example.json).
It emits a new, unbound `.ipynb` file without using the BO contract:

```powershell
python migrate_bw.py --inventory "docs\fixtures\sap_bw_inventory.partial.example.json" `
    --plan "docs\fixtures\sap_bw_bronze_plan.example.json" --output "bw_history.ipynb"
```

The sample plan names a fictitious Parquet file that is **not included**. This
command generates the notebook only; do not execute the sample as if its data
or source-side controls existed.

The plan explicitly supplies:

| Field | Requirement |
|---|---|
| `schema_version` | `1.0`; unsupported or extra fields are rejected |
| `source_object_id` | Exact ID of an observed, in-scope ADSO, InfoCube or InfoProvider; blocked providers and directly unsupported features are rejected |
| `source_files` | Unique, explicit `Files/.../name.parquet` paths in the eventual default lakehouse, without wildcards or traversal; each must resolve to one distinct physical file and contain all columns rather than relying on directory-partition values |
| `snapshot_id`, `snapshot_cutoff_utc` | Explicit snapshot identifier and ISO-8601 UTC cutoff, supplied by the operator |
| `expected_rows` | Non-negative integer declared for the entire snapshot; never inferred from the inventory's estimate |
| `expected_columns` | Exact column names and Spark `simpleString` types; primitive scalar types and `decimal(p,s)` only; case-insensitive duplicates and reserved `_bw_` metadata names are rejected |
| `target_table` | Explicit lower-case `table` or `schema.table`; the lakehouse and schema must be selected and prepared separately |

The generated logic checks the distinct resolved files reported by Spark and
compares each file's schema with the plan, preserves rows including duplicates
and nulls, and adds source system, provider, resolved file path, snapshot,
cutoff and ingestion-time columns. It checks the complete output schema for
provenance-name collisions before writing. It compares the staged count
with the declared count before requesting a Delta table creation using
`errorifexists`, then compares the created table's count. A failed post-write
check leaves the table in place for investigation. An existing target is
refused; there is no automatic replay, append, overwrite, cleanup, partition
management, or concurrency guarantee.

The operator must freeze and authorize the staged files, ensure the declared
schema and count are authoritative, check aliases/duplicates between source
paths, protect potentially sensitive identifiers, and bind the intended
default lakehouse before any separately authorized execution. A count match
does not validate source values or prove a complete BW export. Empty snapshots
have no per-row metadata, so retain the plan and execution evidence separately.
Nested types and any Delta-incompatible column names need a separate design.

Local tests use synthetic inventory/plan data and a simulated Spark interface;
they are not Spark or Delta execution evidence. The standalone notebook is not
automatically included in the BO bundle quality gate or six-tool MCP server.
SAP extraction, file immutability, notebook import/binding, real Fabric writes,
independent reconciliation and downstream BW replacement remain `not_run`.

## BW-2 offline control comparison

The separate `migrate_bw_reconcile.py` command compares a local, versioned
manifest of source and target controls:

```powershell
python migrate_bw_reconcile.py `
    --comparison "docs\fixtures\sap_bw_reconciliation.example.json" `
    --output "bw_reconciliation.json"
```

The example [manifest](fixtures/sap_bw_reconciliation.example.json) is
synthetic. The [schema](schemas/sap_bw_reconciliation.schema.json) and
implementation require a common snapshot ID and UTC cutoff, grain and filter
identifier on both sides; matching control names and units; and explicit rules
for every control. `row_count` and `distinct_key_count` are required exact
checks. Other numeric controls may use an absolute and relative tolerance; the
permitted difference is the greater of those two calculated limits. Specify
dimension/period controls as separate named metrics where those comparisons
are required, and agree every threshold with the data owner before use.

The JSON report says `pass` or `fail` only for the declared metric comparison.
It permanently records SAP extraction, Fabric execution and business approval
as `not_run`. The tool does not verify evidence references, confirm how values
were measured, compare rows or samples, prove complete extraction, or infer
business equivalence. Exit codes are 0 for matching controls, 1 for a produced
report with differences outside the declared rules, and 2 for invalid input or
report-write failure. This is local comparison logic, not the BW-2 exit gate.

## BW-3 offline handoff evaluation

`migrate_bw_handoff.py` evaluates the local, synthetic
[snapshot-to-delta manifest](fixtures/sap_bw_handoff.example.json):

```powershell
python migrate_bw_handoff.py `
    --handoff "docs\fixtures\sap_bw_handoff.example.json" `
    --output "bw_handoff_report.json"
```

The manifest is version 1.0 and requires a source contract declaring
`contiguous_integer` positions, a source schema version and field list, an
evidence reference, a snapshot watermark/cutoff, events and an expected target
state. The evaluator ignores exact event replays and events at or before the
snapshot watermark, detects missing or unexpected positions, orders events by
position, applies upserts/deletes, flags schema changes, and compares the
resulting local state with the declared target. It reports late and
out-of-order events for review; their presence alone does not fail the check.
Input contract conflicts are rejected, while continuity, schema and state
mismatches produce a failing report.

This is deliberately a **normalized offline test contract**, not a universal
CDC interface. Only use it when the selected source's owner confirms that its
feed can be losslessly mapped to contiguous integer positions and provides
authoritative event IDs, delete semantics and schema versions. The evaluator
does not validate the cited evidence, source extraction, snapshot consistency,
the source's position guarantee, durable checkpoints, retry behavior after a
process failure, Fabric execution, or operation with BW unavailable. Re-running
the same local manifest demonstrates deterministic evaluation only; it is not
proof of production restart recovery. A pass is not approval for BW retirement.
All runtime statuses remain `not_run`.

## BW-4 offline transformation-vector comparison

`migrate_bw_transform_validate.py` compares declared expected source outputs
with declared target outputs for a versioned set of test vectors:

```powershell
python migrate_bw_transform_validate.py `
    --vectors "docs\fixtures\sap_bw_transform_vectors.example.json" `
    --output "bw_transform_report.json"
```

Each suite identifies one transformation definition by object ID, reference
and SHA-256 digest. Every vector carries its input, expected output and target
output. Output fields must have explicit `exact` or `tolerance` rules; exact
checks preserve JSON type as well as value, while tolerance checks accept
integers, decimal JSON numbers or decimal strings only when both sides use the
same representation type. They use the greater of declared absolute or
relative tolerance. Missing or extra target fields fail the comparison.

This helper **does not execute or translate the BW routine or Fabric
transformation**. It compares values already present in the local manifest and
does not attest that source vectors are owner-approved or target values came
from an actual Fabric run. The synthetic example is test data only. Source
golden-case execution, target execution and business approval remain `not_run`;
a passing declaration is not semantic equivalence or retirement approval.

## BW-5 offline BEx semantic capture

`migrate_bw_bex_assess.py` reviews one local BEx semantic manifest against the
BW 1.0 inventory:

```powershell
python migrate_bw_bex_assess.py `
    --inventory "docs\fixtures\sap_bw_inventory.partial.example.json" `
    --semantics "docs\fixtures\sap_bw_bex_semantics.partial.example.json" `
    --output "bw_bex_assessment.json"
```

The strict [manifest schema](schemas/sap_bw_bex_semantics.schema.json) records
the selected query definition and explicit coverage for variables/prompts,
filters, hierarchies, time-dependent master data, key figures, exception
aggregation, units/currencies, authorization contexts and consumers. Consumer
IDs must resolve to `consumer` objects linked to the query by inventory
dependencies. Selection/default behavior is referenced, not copied as literal
prompt values; role and authorization fields are references, not user lists.
Unsupported or unknown BEx semantics already recorded against the query remain
blockers. An open BW-0 inventory review is also a blocker for this BW-5
candidate assessment.

The [synthetic example](fixtures/sap_bw_bex_semantics.partial.example.json)
intentionally leaves coverage open. The report's
`candidate_for_owner_review` status means only that the declared BEx capture
and local BW-0 inventory review have no reported blocker; `gate_closed`
remains false. It is not owner approval. The tool does not parse a BW query,
check source provenance, create a target semantic model or report, run source
or target queries, compare result vectors, validate performance, or approve
consumer acceptance. Query execution, source/target result comparison,
consumer acceptance and Desktop/Service rendering remain `not_run`. This is a
contract and gap report, not a BEx converter or BW-5 exit gate.

## BW-6 offline security, planning, and compliance controls

`migrate_bw_controls_assess.py` assesses a local BW-6 controls manifest against
the BW 1.0 inventory:

```powershell
python migrate_bw_controls_assess.py `
    --inventory "docs\fixtures\sap_bw_inventory.partial.example.json" `
    --controls "docs\fixtures\sap_bw_controls.partial.example.json" `
    --output "bw_controls_assessment.json"
```

The strict [manifest schema](schemas/sap_bw_controls.schema.json) records
inventory-linked authorization contexts, role/data-scope and target-control
references, explicit allow/deny test scenarios, planning/write-back dispositions
and control coverage (locking, approvals, separation of duties, audit and
recovery), plus audit, retention, privacy and legal-hold obligations. The
[synthetic partial example](fixtures/sap_bw_controls.partial.example.json)
intentionally leaves coverage incomplete. Role and owner fields are references,
not user lists; credentials and identity payloads are not accepted.

The assessor reports gaps in the local declarations and source-inventory
references only. Its `candidate_for_owner_review` result is not acceptance;
`gate_closed` remains false. It does not execute positive or negative access
tests, verify identity/binding, exercise planning/write-back, certify audit or
retention, validate compliance, or deploy/execute Fabric items. All such
runtime evidence remains `not_run`; this manifest is neither a security proof
nor an authorization to retire BW.

## BW-7 offline wave evidence index

`migrate_bw_wave_assess.py` indexes one declared wave against its BW 1.0
inventory scope:

```powershell
python migrate_bw_wave_assess.py `
    --inventory "docs\fixtures\sap_bw_inventory.partial.example.json" `
    --evidence "docs\fixtures\sap_bw_wave_evidence.partial.example.json" `
    --output "bw_wave_assessment.json"
```

The strict [manifest schema](schemas/sap_bw_wave_evidence.schema.json) records
the inventory run and scoped object IDs, source/target version and extraction/
grain references, per-object applicability and declared status for BW-2
reconciliation, BW-3 handoff, BW-4 transformation, BW-5 BEx and BW-6 controls,
plus operational targets, monitoring/alerting, failure/replay, schema drift,
restore, RPO/RTO, and exception owners/dispositions/approval references. The
[synthetic partial fixture](fixtures/sap_bw_wave_evidence.partial.example.json)
contains only synthetic references and deliberately remains open.

The evaluator checks local scope and manifest linkage, preserves the declared
evidence references and statuses in its report, and blocks an open BW-0 review,
applicable `not_run`/failed checks, or unresolved exceptions. It does not open
referenced report bytes, verify report freshness/correctness, execute or certify
runtime controls, establish operational readiness, or approve retirement.
Even `candidate_for_owner_review` leaves `gate_closed` false; SAP/Fabric
execution and operational certification remain `not_run`.

### Remaining migration and evidence requirements

The inventory and offline comparison contracts are not a full
migration-quality or runtime-evidence system. Further work must define
business-approved target routes and prerequisites, data/semantic/security
acceptance checks, validation thresholds, reviewer sign-off, dependency-cycle
handling and operational controls. A classification of `automatic_candidate`
does not prove conversion; unsupported or unknown features remain visible and
block the applicable gate until accepted.

For each scoped object the target contract should select
`automatic_candidate`, `manual_redesign`, or
`blocked`; separately record validation status as `not_run`, `pass`, `fail`,
or `not_applicable` with justification. A candidate is not a proven automatic
conversion. A manual redesign is not accepted until its target and tests are
approved. A blocked item cannot disappear from the inventory. Where an
exception is proposed, its business impact, decision maker, expiry and
compensating control must be explicit; critical blockers cannot be waived
silently.

The tested 0.1-to-1.0 upgrade is the only version transition implemented so far;
future versions need their own explicit evolution and rejection tests. Broader
round-trip evidence, complete estate coverage, and migration/validation evidence
remain program requirements. BO generation may only be reused through an
explicit, loss-aware adapter; it must not pretend that BO's 15 collections
describe an entire BW warehouse.

## Reconciliation and release evidence

Agree thresholds, sample selection and authority with business and data owners
before execution. At minimum, the acceptance pack for each wave should include:

1. **Coverage:** all in-scope objects and downstream consumers accounted for;
   unresolved inventory/lineage and unsupported behavior explicitly listed.
2. **Data:** same snapshot/cutoff and business filters; counts, distinct keys,
   nulls, duplicates, checksums or totals by partition and business grain;
   historical balances, deltas, deletes and late-arriving corrections.
3. **Semantics:** expected BEx results versus Fabric outputs for approved
   representative queries, filters, variables, totals, currencies, units,
   fiscal periods and hierarchy versions. Define numeric tolerance and rounding
   by measure; record the source and target execution contexts.
4. **Security and operations:** positive/negative persona tests across actual
   access paths; successful scheduled loads, failure/retry/replay, freshness,
   throughput and recovery tests against agreed SLA/RPO/RTO.
5. **Consumers and business:** interfaces, reports and planning workflows tested
   with owners; sign-off, defects, risk decisions and rollback rehearsal retained.

For mandatory checks `not_run` or `fail` is not a pass. Evidence must distinguish
local/static tests from SAP extraction, Fabric deployment/execution, actual data
comparison and business acceptance. Record environment, versions, timestamps,
scope and responsible approver. No universal numeric tolerance is assumed.

## Cutover and retirement

For each wave: establish ownership and dependencies; agree freeze and checkpoint;
complete snapshot and delta catch-up; reconcile data and semantics; run parallel
operations for an agreed period; test consumers and security; obtain explicit
business/operations approval; redirect consumers; monitor; and retain a tested,
time-bounded rollback plan. Record decisions and observations, including
unexecuted steps. Migration tooling must not perform remote writes, redirect
consumers or shut down BW merely because a local plan was produced.

Retire BW only after **all** in-scope waves and consumers are accepted, direct
upstream feeds and recovery are operational, history/retention and legal
obligations are met, residual BW dependencies are resolved or formally accepted,
and authorized owners approve decommissioning. A rollback plan must specify
data divergence handling and the point beyond which reverting is unsafe.

## Implementation boundaries and Tableau reference

The adjacent TableauToPowerBI project was inspected for reusable *ideas*:
dependency-oriented inventory, evidence manifests with explicit runtime status,
and staged cutover/checklists. These are Tableau-specific implementations, not
existing BW features or proof of a supported SAP interface. Evaluate extraction
of genuinely source-independent interfaces only after comparing their behavior,
dependencies, tests and licensing; redesign graph nodes, discovery, security,
delta handling and cutover for BW. Do not copy Tableau schemas, connectors,
failure defaults or release metrics into the BO/BW contract.

Existing BO owners are starting points, not SAP access or customer-accountability
assignments. `Assessor` owns the offline BW inventory contract; `Extractor` is a
proposed collaborator for future local parsing. Assign owners for future live
SAP discovery, source interfaces, upstream feeds and remote operations, and
update the machine-checked contract before implementing them.

## Skills and platform prerequisites

Use the [Fabric routing guide](../.github/skills/fabric-mcp-routing/SKILL.md)
to discover installed skills and current documentation. Relevant skills include
`e2e-medallion-architecture`, `e2e-fabric-cost-estimation`, `dataflows-cli`,
`spark-cli`, `sqldw-cli`, `variable-library-cli`, the available
`semantic-model-authoring` provider, `onelake-catalog-govern-cli`,
`git-integration-operations-cli` and `deployment-pipelines-authoring-cli`.
These are external prerequisites, not capabilities supplied by this repository.
`pipeline-migration` targets Synapse pipelines; it is not a generic BW process
chain converter. Confirm workload availability, current limitations, cost and
environment authorization when used.

## First pilot: minimum acceptance scenario

Select one business domain with a named owner, an in-scope history slice, one
durable upstream feed, master data, an ADSO or equivalent provider, a BEx
query, a process chain, at least one consumer and representative permissions.
Include a routine and a correction/delete case if present; if absent, add
synthetic coverage and document the limitation. Inventory the entire dependency
slice; select the source routes and gap-free cutover boundary; produce and
validate target artifacts only when implemented; then run the checks above in
an authorized environment. The pilot passes only against signed-off coverage,
semantic, data, security and operational gates, not artifact generation alone.
