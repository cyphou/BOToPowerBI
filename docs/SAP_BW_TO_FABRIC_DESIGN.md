# Full SAP BW to Fabric Migration — Design Baseline

**Status:** proposed end-to-end migration design, with an offline BW inventory
contract, limited staged-history and normalized-transformation notebook
generators, and local comparison/assessment helpers. No SAP or Fabric runtime
validation, customer-estate inventory, or owner-approved business-result
reconciliation has been performed. A local BEx result-vector comparator is
available, but evaluates only declared values and does not establish runtime
results or equivalence. The canonical delivery
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
validator/upgrader and BW-0 gap assessment, plus separate staged-history Bronze
and bounded normalized-transformation notebook generators and offline
comparison helpers. These are separate from the BO contract and are not SAP
discovery, source connectivity, BEx/ABAP conversion or proof of BW parity. Any
future adapter to shared BO generators must be designed and tested separately.

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

The BW-0, BW-5, BW-6, BW-7 and BW-8 assessment CLIs write a report and return
`1` when their partial examples have blockers. Exit `0` indicates declarations
ready for owner review, not approval; `2` indicates an input or output error.
They require a new output path and do not overwrite existing reports.

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
| MultiProvider, CompositeProvider | Gold views and/or semantic models | Explicit provider joins/unions, grain and query behavior; no automatic equivalence |
| BEx query, Fiori report | Power BI reports and semantic models | Variables, restrictions, calculated/restricted key figures, exception aggregation and consumer acceptance |
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

### Declared-lineage trace (local Python API)

`powerbi_import.bw_inventory.trace_declared_lineage(snapshot,
selected_object_id, scope_object_ids)` traces dependencies from a selected
known object inside an explicit list of unique, known object IDs that must
include the selection. Only resolved dependencies with both endpoints in that
scope expand reachability. Each resolved declaration is treated as a
cycle-safe traversal connection in either direction, while reported records
keep their original source-to-target direction and all declared statuses.
`traversed_dependencies` contains resolved declarations between reached
objects; `unresolved_dependencies` contains non-resolved declarations touching
any reached object, without traversing them. The output also records
`reached_object_ids` and the supplied scope.

Import it from `powerbi_import.bw_inventory`; there is intentionally no new
CLI. The result validates local declarations only. It does not establish SAP
identity or source truth, inventory completeness, semantic provider
composition, or runtime evidence (`source` and `completeness` are
`unverified`; `runtime` is `not_run`). A usage example with the synthetic
inventory is in the [README](../README.md#offline-bw-declared-lineage-api).

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
permitted difference is the greater of those two calculated limits, computed
with exact decimal arithmetic. Specify
dimension/period controls as separate named metrics where those comparisons
are required, and agree every threshold with the data owner before use.

The JSON report says `pass` or `fail` only for the declared metric comparison.
It permanently records SAP extraction, Fabric execution and business approval
as `not_run`. The tool does not verify evidence references, confirm how values
were measured, compare rows or samples, prove complete extraction, or infer
business equivalence. Exit codes are 0 for matching controls, 1 for a produced
report with differences outside the declared rules, and 2 for invalid input or
report-write failure. This is local comparison logic, not the BW-2 exit gate.
The CLI has mutually exclusive `--comparison <manifest>` (the controls mode
above) and `--bex-result-vectors <manifest>` inputs, each used with
`--output <new-report.json>`. The BEx flag selects a separate row-vector
comparison mode, not another BW-2 control comparison; existing `--comparison`
controls behavior is unchanged. Its contract and limits are described under
BW-5 below.

## BW-3 offline handoff evaluation

`migrate_bw_handoff.py` evaluates the local, synthetic
[snapshot-to-delta manifest](fixtures/sap_bw_handoff.example.json), described by
the [version 1.0 JSON Schema](schemas/sap_bw_handoff.schema.json):

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
The JSON Schema describes the structural contract. The evaluator additionally
checks cross-field rules that the schema cannot express, including matching
record fields to the declared source schema, unique record keys, conflicting
event IDs or positions, exact replay consistency, and watermark ordering.

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

## BW-4 local conversion: normalized rules to Silver

`migrate_bw_convert.py` converts one manually normalized, explicitly declared
BW transformation into a new, unbound PySpark notebook. This original
invocation is declaration-only:

```powershell
python migrate_bw_convert.py `
    --inventory "docs\fixtures\sap_bw_conversion_inventory.example.json" `
    --transformation "docs\fixtures\sap_bw_conversion_plan.example.json" `
    --output "bw_transform.ipynb"
```

The [plan schema](schemas/sap_bw_conversion_plan.schema.json),
[conversion plan](fixtures/sap_bw_conversion_plan.example.json),
[inventory](fixtures/sap_bw_conversion_inventory.example.json) and compatible
[Bronze plan](fixtures/sap_bw_conversion_bronze_plan.example.json) are
synthetic. To generate the upstream notebook locally, pass that inventory and
Bronze plan to `migrate_bw.py`. The named Parquet file is not included; neither
example performs a Spark run. Both source and target tables require an
appropriately prepared default lakehouse, and any `bronze`/`silver` namespaces
must already exist in a schema-enabled lakehouse. The generator performs
additional cross-field and inventory checks beyond the schema; no independent
JSON Schema validator has been run against the conversion schema.

The converter accepts only version 1.0, exact field sets, and a plan whose
`rule_coverage` explicitly says `complete`. The source and target must be
distinct observed, in-scope, unblocked BW providers. The observed, in-scope
transformation must have assessed classification, observed metadata/semantics,
no declared routines or functions, and a definition reference and SHA-256
matching the inventory. An optional DTP must also be observed, in scope and
unblocked. Source-to-transformation and transformation-to-target edges must
be observed and resolved, either directly or through that DTP. Any additional
incoming edge to the transformation blocks generation, including operational
or ambiguously classified edges, rather than assuming it is not another input.

Inventory errors block generation. An inventory unknown is allowed only when
its path unambiguously identifies an existing object outside the selected
chain, such as `objects[object-id].semantics` or `$.objects[4].semantics`.
Selected-object, global, wildcard or otherwise ambiguous unknowns block.
Unknown/unsupported features attached to selected objects block. Any semantic
functions declared on selected objects also block, as do `abap_routine` or
`custom_function` features on those objects even when labelled `supported`.
These checks use supplied declarations. In declaration-only mode, the
definition reference is not dereferenced and its hash is not recomputed from
source bytes. Neither mode independently verifies source-rule completeness.

### Optional source-definition and rule-ledger preflight

The paired inputs enable a stricter local preflight before writing the notebook:

```powershell
python migrate_bw_convert.py `
    --inventory "docs\fixtures\sap_bw_conversion_inventory.example.json" `
    --transformation "docs\fixtures\sap_bw_conversion_plan.example.json" `
    --definition-file "docs\fixtures\sap_bw_conversion_definition.example.txt" `
    --rule-ledger "docs\fixtures\sap_bw_source_rules.example.json" `
    --output "bw_transform_ledger_checked.ipynb"
```

The independently versioned [ledger schema](schemas/sap_bw_source_rules.schema.json),
[ledger](fixtures/sap_bw_source_rules.example.json) and opaque
[definition bytes](fixtures/sap_bw_conversion_definition.example.txt) are
synthetic, not SAP exports. The fixture's Git attributes preserve its exact
bytes across checkouts. The plan and ledger both declare the inventory run,
transformation, definition reference and SHA-256. The converter reads the
provided file as opaque bytes and compares its SHA-256 with the plan and
inventory; it does not dereference the logical definition reference.

Each ledger entry declares a `source_rule_id` and a supported normalized
mapping. In this mode every plan rule must also declare that ID. IDs must be
unique ignoring case and match exactly, with a one-to-one match of all IDs and
mapping fields; the declared input column names and Spark types must also
match. Ordering of the rules and input columns is immaterial for comparison.
Missing, extra, changed or unsupported mappings, mismatched definition bytes,
invalid JSON, or supplying only one of the paired arguments block generation
before the output is opened. Existing 1.0 plans without source IDs remain
supported in declaration-only mode.

Notebook `source_evidence` metadata records `pass` for the byte-hash and
plan-to-declared-ledger checks only when both succeed. It records
`ledger_canonical_sha256` over the parsed ledger serialized as
`json.dumps(ledger, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")`
and the ledger rule count. In declaration-only mode both checks are `not_run`
and the ledger digest/count are null. In either mode source authenticity and
ledger-to-source correspondence remain `not_verified`, and source-owner approval
remains `not_run`. The file bytes and the two optional input paths are not
embedded in the notebook; the plan's `definition_reference` is retained, so
do not place secrets or sensitive local paths in it. The ledger and its
`complete` flag are supplied declarations: a matching hash
does not authenticate SAP origin, and matching IDs and mappings cannot prove
that the ledger contains every real BW rule or accurately describes the bytes.
No independent JSON Schema validator has been run against the ledger schema;
the generator applies its own strict validation and cross-field checks.

| Rule kind | Conversion and restrictions |
|---|---|
| `transfer` | Copy one declared source field without a cast; the result type must exactly match the input Spark `simpleString` type. |
| `constant` | Add a typed `string`, `boolean`, `int`, `bigint` or decimal literal, including null. Integers must fit their declared type. Decimal constants must be strings in plain decimal notation and fit the declared precision/scale without rounding; redundant trailing fractional zeros are allowed. |
| `decimal_add`, `decimal_subtract` | Combine two declared decimal inputs with identical scale; explicitly declare `null_policy: "propagate"`. The result must be `decimal(max(p1,p2)+1,s)` with precision at most 38. No rounding, scale change, overflow workaround or ABAP null/initial-value semantics are inferred. |

The decimal precision guard follows
[Apache Spark 3.5 arithmetic type inference](https://github.com/apache/spark/blob/v3.5.5/sql/catalyst/src/main/scala/org/apache/spark/sql/catalyst/expressions/arithmetic.scala);
the actual Fabric runtime's output schema is still checked before writing.

Other rule kinds or extra fields block the entire notebook, not just one
column. Input names are preserved and quoted as Spark identifiers; explicit
target names must be distinct, avoid reserved lineage names and default Delta
invalid column characters. The generator does not automatically rename
identifiers. The plan declares the exact business input schema, source snapshot
ID and UTC cutoff, expected row count, and lower-case source and target table
names. Bronze provenance columns are required in addition to business fields.

When separately bound and executed, the notebook checks the source schema, row
count and row-level system/provider/snapshot/cutoff lineage, preserves Bronze
provenance, adds transformation/definition-hash/target identifiers, validates
the output schema, and creates a new Delta table with `errorifexists`. It checks
the target count after writing. A write failure or post-write mismatch may leave
a table requiring investigation; no automatic deletion, overwrite or replay is
performed. Empty input contains no row-level lineage evidence. Counts and
declared identifiers do not verify source values, immutable history or BW
parity.

The DTP reference establishes declared lineage only: it does not reproduce DTP
filters, activation, aggregation, update/delete, process-chain or restart
behavior. This slice does not parse SAP metadata or ABAP, resolve lookups,
dates/fiscal logic or currencies, perform source extraction, create a complete
BW replacement, or establish semantic equivalence. The BO bundle and local MCP
quality gate do not dispatch it. Tests execute the generated code against a
simulated Spark interface; actual Spark/Fabric and SAP execution, source and
target golden cases, business approval and BW retirement remain `not_run`.

## BW-4 offline transformation-vector comparison

`migrate_bw_transform_validate.py` compares declared expected source outputs
with declared target outputs for a versioned set of test vectors:

```powershell
python migrate_bw_transform_validate.py `
    --vectors "docs\fixtures\sap_bw_transform_vectors.example.json" `
    --output "bw_transform_report.json"
```

For an optional plan-linked comparison, supply both `--inventory` and
`--transformation` with the matching synthetic suite:

```powershell
python migrate_bw_transform_validate.py `
    --vectors "docs\fixtures\sap_bw_conversion_vectors.example.json" `
    --inventory "docs\fixtures\sap_bw_conversion_inventory.example.json" `
    --transformation "docs\fixtures\sap_bw_conversion_plan.example.json" `
    --output "bw_conversion_vector_report.json"
```

The CLI validates the normalized plan against the local inventory before
comparing. Linkage requires the transformation object ID, definition reference
and SHA-256 to match; every case must provide exactly the plan's input field
names, and the vector rule fields must exactly match the plan's business output
targets. The plan's runtime provenance columns are not business rule targets.
The report records `conversion_plan_linkage` independently of
`comparison_status`; standalone comparisons leave linkage `not_run`. Supplying
only one plan argument is an error.

### Optional source-declaration preflight for vector comparison

The vector CLI can also perform the BW transformation source-declaration
preflight while linking the vectors to the normalized plan. Supply vectors,
both plan-linkage inputs, and both source-declaration inputs together, plus
the output report:

```powershell
python migrate_bw_transform_validate.py `
    --vectors "docs\fixtures\sap_bw_conversion_vectors.example.json" `
    --output "bw_conversion_preflight_report.json" `
    --inventory "docs\fixtures\sap_bw_conversion_inventory.example.json" `
    --transformation "docs\fixtures\sap_bw_conversion_plan.example.json" `
    --definition-file "docs\fixtures\sap_bw_conversion_definition.example.txt" `
    --rule-ledger "docs\fixtures\sap_bw_source_rules.example.json"
```

`--inventory` and `--transformation` are a required pair for plan linkage;
`--definition-file` and `--rule-ledger` are another required pair and require
the plan-linkage pair. Supplying only one member of either pair, or the source
declarations without both plan inputs, is rejected.

The report keeps `source_declaration_preflight.status` separate from
`conversion_plan_linkage`, `normalized_rule_evaluation` and
`comparison_status`. With a linked plan, the validator locally evaluates only
the supported normalized transfer, typed constant and same-scale decimal
add/subtract rules over the declared vector inputs, then compares those results
with `expected_output`. Decimal strings are checked against declared precision
and scale; null decimal operands propagate. This is not execution of source
BW logic or generated Spark code. Unsupported vector Spark types produce an
explicit `not_run` evaluation when they are valid under the conversion-plan
contract but outside the local evaluator subset; invalid plan types are
rejected by the CLI before report generation. Malformed rule-referenced input
values or expected outputs produce a failed local evaluation. When evaluation
runs, unused input values are not type-checked and `input_validation_scope`
reports `referenced_rule_inputs_only`; otherwise the scope is `not_run`.
Without a linked plan, evaluation is `not_run`.

When all source-declaration inputs are supplied, preflight `pass` means the
definition-byte check and plan-to-declared-ledger check passed. Granular
`source_evidence` still reports source-definition authenticity and
ledger-to-source correspondence as `not_verified`, and source owner approval
as `not_run`. In standalone vector mode and plan-linked-only mode, preflight
status is `not_run`; its definition and plan-versus-ledger checks are also
`not_run`, authenticity and correspondence are `not_verified`, and owner
approval is `not_run`. Plan linkage and normalized-rule evaluation can report
their own statuses independently.

For source-declaration preflight the CLI reuses
`build_bw_conversion_notebook` to validate the normalized conversion inputs
and read the declared evidence. It does not write or execute a notebook.
Results are deterministic only for the supplied local declarations, definition
bytes and vector values; no source, Spark or Fabric execution is part of these
checks. Matching statuses do not prove SAP authenticity, rule completeness,
source-to-ledger correspondence, vector provenance, source or target execution,
Spark/Fabric behavior, semantic equivalence, or business approval.

Each suite identifies one transformation definition by object ID, reference
and SHA-256 digest. Every vector carries its input, expected output and target
output. Output fields must have explicit `exact` or `tolerance` rules; exact
checks preserve nested JSON types as well as values, while tolerance checks accept
integers, decimal JSON numbers or decimal strings only when both sides use the
same representation type. They use the greater of declared absolute or
relative tolerance, computed with exact decimal arithmetic. Missing or extra
target fields fail the comparison.

With a linked plan, `normalized_rule_evaluation` separately applies the
supported normalized rules locally and compares their results with the
declared expected outputs. This catches disagreement between a declared plan
and vectors even when expected and target outputs agree with each other.
`comparison_status` still compares the supplied expected and target outputs
under their exact/tolerance rules. A linked report or successful local
evaluation **does not execute or translate the BW routine or generated Fabric
transformation**. It does not attest that source vectors are owner-approved or
that target values came from an actual Fabric run. Unsupported Spark types
remain `not_run` only when valid under the plan contract but outside the local
evaluator subset; source-vector provenance, source/Spark/Fabric execution,
semantic equivalence and business approval are not established. The synthetic
examples are test data only; a passing declaration is not retirement approval.
With linked inputs, the CLI returns a nonzero exit code if either the
expected-versus-target comparison or normalized-rule evaluation fails.
It can return 0 when comparison passes but evaluation is `not_run`; exit 0 does
not imply that the local normalized-rule evaluation ran or passed.

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
Manifest version 1.1 adds `provider_key_figure_bindings`: each captured BEx
key figure must explicitly name one measure in a directly linked provider.
The assessor requires an observed dependency and evidence, an observed provider
measure, and a unique exact-name match in the provider inventory; missing,
unlinked, ambiguous or unobserved bindings block the candidate. Version 1.0
remains accepted for semantic capture but reports a review item because it has
no provider-measure binding check. This declaration does not evaluate formulas
or prove the BEx-to-provider association or business equivalence;
calculated/restricted key figures still need a separately reviewed conversion.
The CLI help lists supported manifest versions 1.0, 1.1 and 1.2. Versions 1.0
and 1.1 retain their prior acceptance and assessment report schema/output
shape 1.0. Manifest 1.2 requires `provider_key_figure_bindings` and requires
every `key_figures` entry to declare `kind` as `basic`, `restricted`,
`calculated` or `unknown`. Only this manifest version produces assessment
report schema 1.1, which adds `key_figure_kinds` entries containing
`key_figure_id`, `declared_kind`, `declaration_boundary` and `assessment`, plus
a `verification` object whose `identity`, `provenance` and `equivalence` are
`unverified`.

The kind declaration is a local manifest label, not evidence of SAP source
truth, identity, provenance or semantic equivalence. `basic` does not prove
additive, `SUM` or aggregation-safe behavior; `restricted` captures no
restrictions; `calculated` captures no formula or dependencies; and `unknown`
remains unresolved. No kind generates DAX or measures. Kind reporting does not
change assessment gates: `gate_closed` remains false, and runtime statuses
remain `not_run`. These declarations do not execute SAP or Fabric or establish
production readiness.

The assessment report includes one `key_figure_provider_links` row per captured
key figure, with `resolved`, `blocked`, `missing` or `not_assessed` status.
`resolved` means only that the local declarations cross-reference successfully.
An unobserved inventory query definition or a missing digest is a blocker.
If an inventory digest is present but differs from the manifest digest, the
CLI rejects the inputs (exit `2`) before writing a report. These checks compare
local declarations; they do not read or authenticate the referenced definition
bytes or prove their SAP origin.
The assessment also lists direct `queries` dependencies from the BEx query to
declared InfoCubes, ADSOs, InfoProviders or CompositeProviders. A missing,
unresolved or unobserved dependency, an unknown or out-of-scope provider, a
blocked query or provider, or a provider feature marked unsupported or unknown
blocks the candidate. For directly linked InfoCubes, unobserved metadata, keys,
semantics or listed semantic items also block it. The key list must be
non-empty, and each key must have a known role; this records declared grain
inputs but does not prove the grain is correct. These are checks of local
declarations only: they do not prove lineage completeness, inspect transitive
CompositeProvider dependencies, or validate the cube's data or aggregation.
Unsupported or unknown BEx semantics already recorded against the query remain
blockers. An open BW-0 inventory review is also a blocker for this BW-5
candidate assessment.

The [synthetic example](fixtures/sap_bw_bex_semantics.partial.example.json)
is intentionally manifest version 1.1: it remains a compatibility example and
does not demonstrate the v1.2 `kind` declaration. It leaves coverage open and
its empty provider-binding list is not evidence that a key figure is mapped.
The example produces a blocker report (exit `1`); exit `0` indicates that the
report is ready for owner review, not accepted. Use a new report path.
Use a separately reviewed v1.2 manifest to exercise declaration-only key-figure
kinds and explicit provider bindings. The report's
`candidate_for_owner_review` status means only that the declared BEx capture
and local BW-0 inventory review have no reported blocker; `gate_closed`
remains false. It is not owner approval. The assessor does not parse a BW
query, check source provenance, create a target semantic model or report, run
source or target queries, validate performance, or approve consumer acceptance.
The local vector comparator below does not change those assessment limits.
Neither a BEx declaration nor its local provider binding verifies native
InfoCube identity. That remains blocked on a sanitized, source-owner-approved
sample and agreed field mapping. Query execution, runtime/source-target
reconciliation, consumer acceptance and Desktop/Service rendering remain
`not_run`. This is a contract and gap report, not a BEx converter or BW-5 exit
gate.

### Offline BEx result-vector comparison

The separate `migrate_bw_reconcile.py` BEx mode compares locally declared
source and target vectors:

```powershell
python migrate_bw_reconcile.py `
    --bex-result-vectors "docs\fixtures\sap_bw_bex_result_vectors.example.json" `
    --output "bex_result_vector_report.json"
```

The strict [schema](schemas/sap_bw_bex_result_vectors.schema.json) declares
query scope, role, prompt-context reference and grain on each side; those
declarations must agree between source and target. Rows are matched by the
exact composite key declared in `key_fields`. The report identifies missing,
extra and duplicate keys, and measure mismatches. Each measure has an explicit
`exact` rule or a decimal tolerance rule with absolute and relative tolerances.
The [synthetic fixture](fixtures/sap_bw_bex_result_vectors.example.json) is
deliberately mismatched. For the linked InfoCube pilot, the
[synthetic replay](MIGRATION_REFERENCE.md#replay-the-synthetic-result-comparison)
exercises nonempty matching and mismatched day-level quantities without
running the PBIP. The [authorized pilot handoff](MIGRATION_REFERENCE.md#collect-evidence-for-an-authorized-pilot)
describes what to collect before comparing real results.

A `pass` means only that the supplied local vectors satisfy those declared
rules. It does not authenticate SAP source or Fabric target values or prompt-
context references, establish source coverage or native InfoCube identity,
execute SAP or Fabric, prove semantic equivalence, or constitute owner/business
approval. SAP/Fabric execution and approval are `not_run`; authenticity,
provenance, source coverage and semantic equivalence are `not_verified`.
When the report's `summary.measures_compared` is zero, it adds the
`no_measure_observations_compared` limitation. After successfully writing the
report, the CLI prints “No measure observations were compared; this result does
not establish measure agreement.” This is a notice, not a status override:
`comparison_status` and exit behavior are unchanged. For example, two empty
vectors still produce `pass`/0; that does not establish measure agreement.
The report schema remains 1.0, runtime evidence remains `not_run`, and
verification remains `not_verified`.
Therefore this comparator does not close BW-5, which remains open. Native
InfoCube identity remains blocked on a sanitized, source-owner-approved sample
and agreed field mapping. It is a static local comparator, not runtime or
source-target reconciliation.

### Explicit SAP BW Power Query selection

For an explicitly prepared converted datasource, the Python
`bo_export.compat.generate_power_query_m(connection, table)` path can generate
an Import/coexistence Power Query using `SapBusinessWarehouse.Cubes` implementation
2.0. Supply `connection` with `type: "sap_bw"` and non-empty text `server`,
`system_number` and `client_id`. Leading zeroes must be kept. The `table`
must contain a `name` and an explicit `sap_bw_navigation` object, for example:

```python
from bo_export.compat import generate_power_query_m

connection = {"type": "sap_bw", "server": "synthetic-bw",
              "system_number": "00", "client_id": "001"}
table = {"name": "Sales", "sap_bw_navigation": {
    "info_area": "$INFOCUBE", "cube_id": "$0D_DECU",
    "dimensions": [{"selector": "[0CALDAY]",
                    "attributes": ["[0CALDAY].[LEVEL01]"],
                    "columns": ["Calendar day"]}],
    "measures": [{"selector": "[Measures].[0D_INV_QTY]",
                  "column": "Quantity"}],
}}
expression = generate_power_query_m(connection, table)
```

Identifiers and output names are explicit declarations, not extracted or
validated against SAP. The same converted-table metadata is usable by the
existing Import model and Dataflow generators, with matching declared columns
and data types; the BO extractor and CLI do not populate it.
Generic SQL/table navigation and automatic BEx variable, formula and security
conversion are not implemented for this path. Missing connection settings or
cube selection raise an error instead of guessing. The connector needs separately
configured credentials, SAP prerequisites and potentially a gateway. Desktop
and Fabric execution/refresh and BEx result parity are `not_run`.
The [connector documentation](https://learn.microsoft.com/en-us/power-query/connectors/sap-bw/implementation-details)
also documents differences for BEx local calculations and aggregations.

To prepare a **PBIP draft** from a JSON plan, use the local CLI:

```powershell
python migrate_bw_bex_pbip.py `
    --plan "docs\fixtures\sap_bw_bex_pbip_plan.example.json" `
    --output-dir "artifacts\bw-bex"
```

The [plan schema](schemas/sap_bw_bex_pbip_plan.schema.json) and
[synthetic example](fixtures/sap_bw_bex_pbip_plan.example.json) describe one
cube and its explicitly mapped columns. Version 1.0 plans remain supported;
version 1.1 can optionally add `bex_linkage` with a BEx `query_id`, BW
inventory `provider_id`, the declared `cube_id`, and a `key_figure_bindings`
entry for each selected measure (`key_figure_id`, exact M `selector`, and
output `column`). Version 1.2 retains that linkage and requires
`dimension_bindings` when `bex_linkage` is present; versions 1.3 through 1.6
retain the same requirement. The list maps every selected
navigation dimension selector exactly once to an observed InfoCube dimension
name that occurs exactly once in the provider's dimension declarations.
Ambiguous selected names are rejected; version 1.1 linked plans may omit this
list for compatibility. For a linked plan, pass both `--inventory` and
`--semantics`; omit both for an unlinked plan. Plan and manifest versions are
independent. Linked generation requires the offline BW-5 assessment to reach
`candidate_for_owner_review`. After generation and expression export, the CLI
writes `bex_linkage_assessment.json` at the root of `--output-dir`; the PBIP is
in the child directory named by `project_name`. The linkage report schema is
1.0; its nested `bw5_assessment` uses schema 1.1 for manifest v1.2.
The check requires the selected provider to be an observed direct InfoCube
dependency and each selected key figure to resolve to that provider's observed
measure name. Exact selector comparisons check declarations against each other;
they do not verify that a selector or cube ID is correct in SAP. For linked
plans, the SAP client in the connection must exactly match the BW inventory's
source client; this does not verify the server, system number or InfoCube ID.
The dimension binding checks
provider declarations only; they do not prove that the BEx query uses a
dimension. Replace sample selectors, types and connection metadata only with
independently verified values. The output is an Import model with an empty
report shell by default; plan 1.6 can explicitly add a review table. Neither
option converts a BEx report. The output does not create an aggregated
Warehouse fact, MultiProvider joins, or a Fiori dashboard. The linkage evidence
JSON sets
`native_infocube_identity_verification` to `not_verified`: matching local
declarations do not establish native SAP object identity.

Version 1.3 optionally allows a dimension's `properties` to select explicitly
declared member properties, for example:

```json
{
  "selector": "[0CALDAY]",
  "attributes": ["[0CALDAY].[LEVEL01]"],
  "columns": ["Calendar day"],
  "properties": [{
    "source_column": "Calendar day",
    "selector": "[20CALDAY]",
    "column": "Calendar day key"
  }]
}
```

Declare `{"name": "Calendar day key", "datatype": "datetime"}` in the
same table's model `columns` as well. The `source_column` must exactly match a
column selected by that dimension; property output names must be unique across
all selected dimensions and measures. The generated `Cube.Transform` uses
`Table.AddColumn` and `Cube.AttributeMemberProperty`. This is a manually
declared selector and type, not automatically discovered metadata: the plan
does not validate the property against SAP. The documented BW connector
requires implementation 2.0, Import mode and suitable SAP permissions for typed
date keys. Verify the selector, type, permissions and results in the intended
environment. Versions 1.0-1.2 cannot contain `properties`.
For BW-only models, the generator also suppresses its automatic Calendar table,
date relationships and Gregorian date-part hierarchies. These cannot be
assumed to reproduce BW fiscal calendars or BEx hierarchies. The existing
automatic date behavior for non-BW models is unchanged.

A complete [synthetic 1.3 example](fixtures/sap_bw_bex_pbip_properties.example.json)
can be supplied with `--plan` in the command above. It cannot connect to SAP
without independently reviewed real connection and navigation declarations.

Version 1.4 optionally accepts `parameters` within `sap_bw_navigation`:

```json
"parameters": [
  {"selector": "[!SYNTHETIC_PARAMETER]", "arguments": [["synthetic-a", "synthetic-b"]]}
]
```

Each unique, explicit `selector` and non-empty `arguments` list is emitted in
order as `Cube.ApplyParameter` before dimension and measure selection. Arguments
may contain non-empty text values and/or non-empty lists of text values; further
nesting, non-text values and M expressions are rejected. The example produces
the M argument list `{{"synthetic-a", "synthetic-b"}}`. Versions 1.0-1.3
reject `parameters`; version 1.4 retains the 1.3 property support and 1.2
linkage requirements.

These are literal user declarations, not automatically mapped BEx variables,
prompts, range semantics, defaults or filters. The shape and values are not
validated against SAP: obtain the exact parameter selector and argument shape
from an authorized source, and verify folding and results in the intended
environment. A manually selected value may restrict the data loaded. The plan
and generated model contain literal values in clear text, so never use secrets
and protect both artifacts; generated model access may reveal business values.
This option does not change the linkage report's counts of BEx semantics not
converted. See Microsoft's
[`Cube.ApplyParameter` reference](https://learn.microsoft.com/en-us/powerquery-m/cube-applyparameter)
and [SAP BW query transformation guidance](https://learn.microsoft.com/en-us/power-query/connectors/sap-bw/transform-filter-sap-bw-data).

Version 1.5 optionally associates one parameter declaration with a BEx variable
using `bex_variable_id`:

```json
{
  "selector": "[!V000001]",
  "bex_variable_id": "declared-variable-id",
  "arguments": [["2026"]]
}
```

This requires `bex_linkage` plus `--inventory` and `--semantics`. The ID must
match exactly one variable in the supplied BEx manifest, and each variable ID
may be bound once. The output's `variable_parameter_selection` records selected
and unselected manifest variable IDs, the declared M selector, and manifest
name/kind/status; it deliberately omits literal argument values.
`bex_semantics_not_converted.counts.variables` continues to count all declared
variables: associating an ID and passing values does not translate mandatory
prompt behavior, defaults, selection/range semantics, or prove that the BW
parameter represents that BEx variable. Earlier plan versions reject
`bex_variable_id`. The evidence report is additive and retains schema version
1.0; strict consumers must allow `variable_parameter_selection` and
`bex_semantics_not_converted.declared_coverage`.

The association is a manually asserted link, not discovered or verified in SAP.
An exact manifest ID does not verify selector identity, compatibility, value
shape, defaults, query folding, authorization behavior or result equivalence.
Use only reviewed, non-secret literal arguments and protect the generated model.

Version 1.6 optionally adds a top-level `review_report`:

```json
"review_report": {
  "page_name": "BW cube review",
  "columns": ["Calendar day", "Quantity"]
}
```

The page name must be non-empty, and the column list must be non-empty,
unique, and match the declared model column names exactly, including case.
Earlier plan versions reject this option. The CLI creates one `tableEx` on
the default 1280 x 720 page, with a 20-unit margin and the declared columns in
order. It projects physical columns only, including selected BW key figures;
it creates no DAX measures and disables the table total. Power BI may group
identical projected values, so this is not necessarily a row-level view.
Review the grain, aggregation, units and results independently. The table
does not reconstruct a BEx layout or convert its semantics.

A complete [synthetic 1.6 example](fixtures/sap_bw_bex_pbip_report.example.json)
can be supplied with `--plan`; its synthetic server cannot connect to SAP.
Without `review_report`, the report remains empty. The CLI does not open or
refresh Desktop, query SAP, or establish source-to-target equivalence.

The linkage report's `key_figure_selection` compares the IDs in the linked plan with the BEx
manifest's declared key figures, listing selected and unselected IDs in
manifest order. The status is `all_declared_selected`,
`some_declared_unselected` or `none_declared`. A partial selection remains
allowed but produces a CLI warning with the number omitted; an empty manifest
does not prove that the SAP query has no key figures. These results concern
local declarations only: even `all_declared_selected` does not mean formulas,
aggregations, units or BEx results have been converted. The report's
`schema_version` remains `1.0`; consumers enforcing a closed set of JSON
properties must allow the additive `key_figure_selection` field. Its
`selected_semantics` lists each selected figure's target selector and column,
manifest status, and declared aggregation, exception-aggregation and
unit/currency fields. `selected_semantics_scope` is
`local_bex_manifest_declarations_only`; the fields are copied for review, not
interpreted or translated into DAX.
If the BW-5 assessment contains review findings, the CLI prints a non-blocking
warning with their count and the assessment path. This makes remaining
owner-review work visible but does not change the generation gate or approve
the declarations. If blockers prevent generation, the CLI reports the total
count and up to three finding codes with their JSON paths, plus the number of
additional blockers; it rejects the linked plan before creating PBIP output.
The schema allows no credential fields, and the CLI rejects URL/userinfo
syntax in the server identifier. It does not scan every text value for secrets;
never embed credentials in any plan field.
The linkage report's `bex_semantics_not_converted.counts` summarizes declared
variables, filters, hierarchies, master data, key-figure semantics and
authorization contexts. A non-zero count emits a non-blocking warning with
the evidence path. `evidence_scope` is
`declared_local_manifest_counts_only`; `declared_coverage` copies each
category's coverage declaration from the local BEx manifest. Counts and
coverage are not independently verified: zero counts or `not_applicable`
do not prove absence in SAP, and neither field implies that any listed
behavior was mapped. The report also includes
`bex_semantics_not_converted.unconverted_filter_declarations` and
`bex_semantics_not_converted.unconverted_hierarchy_declarations`. Each list
contains only `id` and `status` from the corresponding local BEx manifest
declarations, in manifest order, alongside the existing `counts` and
`declared_coverage`. These declaration lists do not prove source completeness
or SAP identity, and do not convert or implement filter or hierarchy
semantics.

After generic PBIP validation, the CLI checks this generator's TMDL against
the plan: one explicitly named table and corresponding model reference, the
exact physical columns, their declared type mappings and source aliases,
no implicit summarization or DAX measures, and one Import partition with
the expected BW M query. A mismatch exits `1` before expression export or
linkage output. The check does not run the query or confirm that its SAP
objects and result types exist. Static warnings alone do not fail the command.
Invalid plans and linkage blockers exit `2` before generation. The output
directory must be new or empty; failures can leave partial project files.

The [linked BEx and InfoCube pilot](MIGRATION_REFERENCE.md#linked-bex-and-infocube-pilot)
replays a synthetic inventory 1.0, manifest 1.2, and plan 1.6 together. It adds
a typed date key and a column-only visual, not a converted BEx report or
proof of runtime acceptance.

After successful static validation, the BW CLI exports the generated model's
M partitions to `PowerQuery/*.pq`, shared M expressions to
`PowerQuery/Expressions/*.pq`, and any generated measures to `DAX/*.dax`.
`expression_export.json` maps each review file to its TMDL source. A BW draft
currently has no generated DAX measures, so no `DAX` directory is created.
The files copy generated expressions; they do not establish BEx conversion.
They may contain connection details and literal parameter values: protect the
files and never put secrets in the plan. Export failures return a nonzero
status and may leave partial files.

Without the optional linkage, the plan does not consume the BW inventory or
BEx semantic-capture manifest. With linkage, the local assessor cross-checks
their declarations but does not translate BEx variables, filters, formulas,
hierarchies, exception aggregation, units/currencies or authorizations.
The optional review table is not a converted BEx visual.
`candidate_for_owner_review` is not approval and does not close BW-5.
Configure credentials separately after reviewing the generated model. Protect
generated artifacts, which contain connection metadata and local assessment
references. Desktop opening, reload, rendering, query execution with source
data, refresh, BEx parity and business acceptance remain `not_run` until a
reproducible, authorized check is recorded with its artifacts and provenance.

Generated project metadata also includes a versioned
`sap_bw_capability_boundary`. It separates the illustrated Power Apps,
Talend/SQL and planning target architecture from repository behavior and keeps
SAP/Fabric runtime, cutover and retirement evidence at `not_run`.

The generated semantic model disables implicit aggregation
(`summarizeBy: none`) for all SAP BW source columns, including numeric
dimensions and key figures. It does not create DAX measures: BEx aggregation
and exception-aggregation behavior must be explicitly understood and validated
before adding target measures. Other datasource types retain their existing
column summarization defaults.

Planning, forecast updates, version locks, write-back and BW authorization are
separate functions and are not implemented by this read-only Import draft.
Cube aggregation and BEx measures cannot safely be assumed additive in the
model. Obtain query definitions, selected fields, variables, units, security
and business validation evidence before reproducing reports or decisions.

For a print-oriented consumer, `migrate.py --output-format rdl` or the separate
`migrate_paginated.py` can create
a basic RDL table from an explicitly supplied semantic-model connection, DAX
query and field mapping; see the [migration reference example](MIGRATION_REFERENCE.md#local-paginated-rdl-from-a-declared-mapping).
The `bex` source kind is a declaration, not a BEx parser or semantic
conversion. Report Builder rendering, query execution, permissions and
source-to-target equivalence are `not_run`; this does not close BW-5.

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
recovery), plus audit, retention, privacy and legal-hold obligations. Version
1.1 additionally declares dispositions for Copy Version, Upload File, cube
activation, planning reporting, forecast update and consolidation/aggregation.
Each capability requires an external owner, target solution and evidence when
in scope; version 1.0 remains readable for compatibility. The
[synthetic partial example](fixtures/sap_bw_controls.partial.example.json)
intentionally leaves coverage incomplete. Role and owner fields are references,
not user lists; credentials and identity payloads are not accepted.

The assessor reports gaps in the local declarations and source-inventory
references only. Its `candidate_for_owner_review` result is not acceptance;
`gate_closed` remains false. It does not execute positive or negative access
tests, verify identity/binding, exercise planning/write-back, certify audit or
retention, validate compliance, or deploy/execute Fabric items. All such
runtime evidence remains `not_run`; this manifest is neither a security proof
nor an authorization to retire BW. Capability records do not implement Power
Apps, Talend jobs, SQL procedures, target planning workflows or BW write-back.

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

## BW-8 offline cutover and retirement declaration assessment

`migrate_bw_cutover_assess.py` evaluates one BW-8 declaration set against a
local BW inventory and its BW-7 wave evidence manifest:

```powershell
python migrate_bw_cutover_assess.py `
    --inventory "docs\fixtures\sap_bw_inventory.partial.example.json" `
    --wave-evidence "docs\fixtures\sap_bw_wave_evidence.partial.example.json" `
    --cutover "docs\fixtures\sap_bw_cutover.partial.example.json" `
    --output "bw_cutover_assessment.json"
```

The [strict schema](schemas/sap_bw_cutover.schema.json) records dependency
coverage and disposition, cutover plans and checkpoints, declared parallel-run
and BW-independent observation durations, rollback time limits/recovery
objectives/exercise status, upstream-feed operation, planning/retention
sign-off, reconciliation thresholds, owner decisions, archive/restore and
decommission/deactivation references. It requires an explicit owner-acceptance
declaration for BW-0 through BW-7; the local BW-7 candidate status is not that
approval. The assessor checks inventory edges directly incident to wave objects
and consumers at their endpoints, not transitive dependencies. The declared
coverage is not independently verified and the report marks
`dependency_coverage_verification` as `not_verified`. The
[synthetic partial fixture](fixtures/sap_bw_cutover.partial.example.json)
intentionally remains blocked.

The assessor validates only local declarations and linkage to the supplied
BW-0 inventory and BW-7 manifest. It does not authenticate approvers, open or
verify linked reports, establish that a declared duration elapsed, or execute
cutover, consumer switching, monitoring, rollback, restore, shutdown or
decommissioning. A complete declaration set is reported only as
`declarations_complete_for_owner_review`; `gate_closed`,
`cutover_authorized` and `retirement_authorized` always remain false.
SAP/Fabric runtime evidence, including the parallel run and rollback exercise,
remains `not_run`.

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
