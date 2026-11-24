# BusinessObjects to Power BI Migration

Generate local Power BI, Fabric or paginated-report artifacts from supported
SAP BusinessObjects metadata. Extraction and conversion are partial: generated
files still require source, data, security and report validation.

## Migration evidence — 24 Nov 2026

> [!IMPORTANT]
> **Local pilots are ready to review. Full migration approval is not established.**

| Area | Result | Boundary |
|---|---|---|
| Python tests | 🟢 **1 283 passed**, 1 skipped, 1 504 subtests | 80.74% coverage; 80% threshold passed |
| BEx / InfoCube | 🟢 Synthetic pilot strictly validated | 0 static errors, 0 warnings; 2 CSV observations, 0 mismatches |
| WebI | 🟠 Synthetic batch generated | 0 static errors, 13 review warnings |
| Hosted CI | ⚪ Not run | Ruff 387; Pyright 71 errors / 2 warnings; hosted OS/Python jobs remain open |
| SAP / Desktop / Fabric runtime | ⚪ Not run | No refresh, rendering, source query or deployment evidence |
| Identity / equivalence | ⚪ Not verified | No real owner-approved source export or business acceptance |

A PBIP, a green test suite and a static PASS do not prove a real migration.
See the [gap analysis](docs/GAP_ANALYSIS.md#local-bo-bex-and-infocube-review--2026-11-24)
and the [final verification report folder](artifacts/final-migration-verification/).

## ⚡ Quick Start

Requires Python 3.12 or later. The core migration engine uses the standard
library; no package installation is needed for these local commands.

From the repository root, put the BO files in a `sources` directory, then run:

```powershell
python migrate.py sources --dry-run
python migrate.py sources
```

The first command inspects without persistent output. The second generates
local PBIP artifacts in `sources_pbi` beside `sources` (the input folder name
plus `_pbi`). The output directory must be **new or empty**. To choose a
different new or empty destination, use `python migrate.py sources -o output`
(`-o` is shorthand for `--output-dir`). Review
`batch_manifest.json` and the `batch_report.html` when available, including
failures, skipped sources and warnings. A successful command does not prove
that the report opens, refreshes or matches the source.

<a id="more-ways-to-migrate"></a>

## Choose a workflow

| What you want | Command or next step |
|---|---|
| Assess one BO file without generating a project | `python migrate.py "report.wid" --assess` |
| Generate PBIP from a BO folder | `python migrate.py sources` |
| Generate a local Fabric bundle instead | `python migrate.py sources --output-format fabric` |
| Generate a paginated RDL from a reviewed SQL/DAX mapping | `python migrate.py --rdl-mapping mapping.json` |
| Assess an experimental Desktop Intelligence REP | `python migrate.py report.rep --assess` |
| Inspect an experimental Desktop Intelligence REP | `python migrate_deski_inspect.py --source report.rep --output inventory.json` |
| Check DeskI COM registration on Windows | `python migrate_deski_inspect.py --check-sdk` |
| Validate a generated PBIP project or Fabric bundle | `python migrate.py --validate-project "path-to-project"` |
| Review manually declared feature coverage offline | [Coverage declaration ledger](docs/MIGRATION_REFERENCE.md#offline-feature-coverage-declaration-ledger) |
| Export M and DAX review files from an existing generated model | `python -m powerbi_import.expression_export --semantic-model "path\Report.SemanticModel" --output-dir "new-output"` |

Replace example paths with your own. The Fabric folder command uses the same
`sources_pbi` default, which must also be new or empty; choose different output
directories if you run both formats. For these PBIP and Fabric commands, use a
folder rather than an individual report file. The [archive](docs/MIGRATION_REFERENCE.md#additional-bo-command-paths)
and [shared model](docs/MIGRATION_REFERENCE.md#-shared-semantic-model-mode)
workflows are separate. Validation checks local artifacts, not Desktop
rendering or cloud execution.
Fabric generation can return exit code `6` when local quality findings block
the bundle; inspect the batch manifest and per-project `quality_report.json`.
A blocked bundle is not deployment-ready.

<a id="bw-bex-infocube-workflows"></a>

> [!NOTE]
> **BO / BO XI, BEx and InfoCube: choose the path that matches your source.**
>
> - **BO reports:** assess a file, then generate a local PBIP or Fabric bundle
>   from a folder. [BO XI / DeskI REP](#bo-xi--desktop-intelligence) is experimental
>   inspection plus opt-in, manually mapped drafts, not automatic conversion.
> - **BEx query:** [assess a local BW inventory and BEx manifest](docs/SAP_BW_TO_FABRIC_DESIGN.md#bw-5-offline-bex-semantic-capture).
>   Provider bindings and v1.2 key-figure kinds are declarations; they do not
>   convert prompts, filters, hierarchies, calculations or report layout.
> - **One InfoCube:** [generate a manually mapped Import PBIP draft](docs/MIGRATION_REFERENCE.md#local-pbip-draft-from-an-explicit-bw-cube-plan).
>   The draft retains BW as its refresh source. Optional BEx linkage checks local
>   declarations only. Start with the [reproducible BEx and InfoCube pilot](docs/MIGRATION_REFERENCE.md#linked-bex-and-infocube-pilot)
>   to generate a column-only review table without an SAP system.
> - **Optional evidence:** [compare supplied BEx result vectors](docs/SAP_BW_TO_FABRIC_DESIGN.md#offline-bex-result-vector-comparison).
>   A comparison pass applies only to the supplied observations, not BEx parity.
>
> A BW-connected draft does not replace BW. Native InfoCube identity remains
> unverified pending a sanitized, source-owner-approved sample and agreed
> field mapping. See the [local review and remaining gaps](docs/GAP_ANALYSIS.md#local-bo-bex-and-infocube-review--2026-11-24).

## Parameters you will use most

PBIP is the default output. `python migrate.py --help` shows common workflows;
`python migrate.py --help-all` shows all options. The
[CLI reference](docs/MIGRATION_REFERENCE.md#-cli-reference) documents advanced
options and their limitations.

The RDL mapping declares the query, connection and fields; it does not recover
the source report layout. When `--output-format` is omitted, the command above
infers RDL and defaults to a new `mapping.rdl` beside the mapping. You may
select another new file with `--rdl-output`; explicit `--output-format rdl`
still requires that option. To select extracted SQL or generate an optional
Power Query `.m` file, see the [RDL reference](docs/MIGRATION_REFERENCE.md#local-paginated-rdl-from-a-declared-mapping).
The RDL output must be a new file. The command above generates an RDL, not a
PBIP or PBIX.

## BO XI / Desktop Intelligence

REP inspection is experimental and returns partial **candidates**. The inventory
can contain SQL and other sensitive metadata; protect it. It is not a PBIP
conversion or proof that a query belongs to a report.

The main CLI assessment prints a partial report as JSON without writing an
inventory. It omits SQL text, formula expressions and literal prompt/variable
arguments, but metadata can still be sensitive. Optional `-o DIR` requests
exclusive creation of a new `<stem>_deski_assessment.json`; empty directory
values and non-applicable flags are rejected. `--dry-run` writes nothing.

For an authorized Desktop Intelligence workstation, run
`python migrate_deski_inspect.py --check-sdk` and follow the
[client capture procedure](docs/MIGRATION_REFERENCE.md#desktop-intelligence-xi-31-experimental-sql-handoff).
The check reads COM registration only; it does not connect or prove that
the SDK, license or extraction works.

To create a draft RDL from a REP candidate, use an exact selector from that
file's inventory, an explicit SQL Server mapping and
`--rdl-accept-unverified-rep-sql`. RDL-only folder runs instead require
`accept_unverified_rep_sql: true` **per source** in the batch configuration.
Combined PBIP/RDL folder runs require that same per-source acknowledgement. An
additional per-source `pbip` declaration can produce a basic PBIP table draft
from the same SQL candidate. Its typed fields and roles are manual declarations,
not recovered source metadata; recognized BO SQL function markers block that
PBIP target. The generated PBIP is checked by the local static artifact validator;
validation errors fail only that target, while RDL retains its independent
result. This check does not execute SQL or verify Desktop rendering. Review the
SQL, connection, fields, prompts and layout independently.

See [REP inspection and single-source RDL](docs/MIGRATION_REFERENCE.md#desktop-intelligence-experimental-local-rep-inventory-in-progress)
and [RDL folder configuration](docs/MIGRATION_REFERENCE.md#rdl-from-a-mixed-source-folder).
REP still does not enter ordinary PBIP/Fabric batch migration; the combined
folder draft is opt-in and does not reconstruct the source report.

## Sources and targets

| Source or target | Scope |
|---|---|
| WebI `.wid`, Crystal `.rpt`, universes `.unx`/`.unv`, Lumira `.lumx`/`.lums` | Local extraction and generation are format-dependent and incomplete; recognition does not guarantee a usable datasource or model. |
| `.biar`/`.lcmbiar` | Directly recognized archive entries only; embedded or segmented contents are not fully decoded. |
| Desktop Intelligence `.rep` | Partial inventory, explicitly acknowledged RDL drafts and an opt-in manually declared PBIP table draft; no automatic PBIP/Fabric conversion. |
| Power BI Desktop | PBIP is intended for standard Desktop; open and verify the project separately. |
| Power BI Report Server | Desktop for Report Server does not support PBIP. An optional SQL-based M query is a manual reconstruction aid; RDL is a separate paginated target. |
| SAP BW | Offline assessments, staged-data tools, a declaration-based single-cube PBIP draft with optional local BW-5 linkage checks, and a local BEx result-vector comparator; not BW extraction, BEx conversion, or warehouse replacement. See the [BW design](docs/SAP_BW_TO_FABRIC_DESIGN.md). |

### Offline BW declared-lineage API

`powerbi_import.bw_inventory.trace_declared_lineage` is a local Python API;
there is no CLI for it. Give it a validated snapshot, a selected object ID,
and an explicit list of known object IDs that bounds traversal. Resolved
dependencies connect objects in either direction for a cycle-safe walk within
that scope. Reported dependency records retain their declared source-to-target
direction and statuses; non-resolved dependency declarations touching reached
objects are also returned, but are not traversed.

```python
from powerbi_import.bw_inventory import load_snapshot, trace_declared_lineage

snapshot = load_snapshot("docs/fixtures/sap_bw_inventory.partial.example.json")
trace = trace_declared_lineage(
    snapshot,
    selected_object_id="SYNTHETIC-BW-01:SOURCE:ERP-SALES",
    scope_object_ids=[
        "SYNTHETIC-BW-01:SOURCE:ERP-SALES",
        "SYNTHETIC-BW-01:DS:VENTES",
    ],
)
print(trace["reached_object_ids"])
```

This validates local declarations only; it does not establish SAP identity or
source truth, completeness, semantic provider composition, or runtime evidence.

For WebI, an optional CMS snapshot can capture report elements, provider
summaries and query plans. The adapter checks the IDs and statement shape of
selected single-statement plans before carrying their SQL into a model, but the
snapshot does not establish report-element-to-provider bindings. The result can
therefore have a model and an empty report shell; it is not a converted WebI
report. The synthetic `Enterprise_Sales` sample's generated PBIP currently
retains unresolved visual/model field references reported by default local
static validation; that validation can exit successfully with warnings, which
is not proof of bindings or source parity. See the
[WebI snapshot details and limitations](docs/MIGRATION_REFERENCE.md#read-webi-report-and-data-provider-metadata-from-the-cms).

When no source visuals are converted, PBIP generation defaults to an empty
report shell for the model; it does not reconstruct the source report. A BW
cube plan can instead declare an optional [review table](docs/fixtures/sap_bw_bex_pbip_report.example.json)
using selected model columns. This table is not a converted BEx report.
An existing report is not overwritten by an empty shell; use a new output
directory.

Linked BW cube PBIP evidence now lists declared filter and hierarchy IDs and
statuses, in manifest order, under
`bex_semantics_not_converted.unconverted_filter_declarations` and
`bex_semantics_not_converted.unconverted_hierarchy_declarations`, alongside
the existing count and coverage data. Each list item contains only `id` and
`status`. These are local manifest declarations: they do not prove source
completeness or SAP identity, and do not implement filter or hierarchy
semantics.

The offline BEx assessment accepts manifest versions 1.0, 1.1 and 1.2
(`python migrate_bw_bex_assess.py --help`). Versions 1.0/1.1 retain their
prior acceptance and assessment-report schema/output shape 1.0. Version 1.2
requires `provider_key_figure_bindings` and a `kind` for every key figure,
declared as `basic`, `restricted`, `calculated` or `unknown`. Its assessment
report schema 1.1 adds `key_figure_kinds` and verification fields for identity,
provenance and equivalence, all `unverified`. The kind is a local declaration,
not evidence of SAP source truth or semantics: `basic` does not prove additive,
`SUM` or aggregation-safe behavior; `restricted` records no restrictions;
`calculated` records no formula or dependencies; and `unknown` remains
unresolved. No kind generates DAX or measures. Assessment gates are unchanged,
`gate_closed` remains false and runtime statuses remain `not_run`. See the
[BEx assessment contract](docs/SAP_BW_TO_FABRIC_DESIGN.md#bw-5-offline-bex-semantic-capture).

[Compare two prepared CSV captures directly](docs/MIGRATION_REFERENCE.md#compare-two-csv-captures-directly)
using one text key and one exact numeric measure. The CLI checks declared
identifiers against the InfoCube plan, BW inventory and BEx manifest. To
retain the vectors, use the
[vector packager](docs/MIGRATION_REFERENCE.md#prepare-vectors-from-two-csv-captures).
Neither path extracts source data.

To compare locally declared BEx source and target result vectors, use a
versioned manifest and a new report path:

```powershell
python migrate_bw_reconcile.py `
    --bex-result-vectors "bex_vectors.json" `
    --output "bex_result_vector_report.json"
```

The comparator checks declared composite keys and exact or decimal-tolerance
measure rules. A pass applies only to the supplied declarations; it does not
run SAP, Power BI or Fabric, establish provenance or coverage, prove semantic
equivalence, or close BW-5. If the report's `measures_compared` is zero, it
includes `no_measure_observations_compared`, and the CLI prints
“No measure observations were compared; this result does not establish measure
agreement.” In standalone mode two empty vectors can still yield `pass`/0.
To tie the comparison to a declared InfoCube, add `--plan`, `--inventory`
and `--semantics` together. This mode refuses inconsistent query, source,
project or selected key-figure IDs, and exits `1` if no measures are compared.
See the [linked pilot replay](docs/MIGRATION_REFERENCE.md#replay-the-synthetic-result-comparison).
Native InfoCube identity remains blocked pending source-owner-approved evidence
and an agreed field mapping.
See the [BEx comparison contract and limitations](docs/SAP_BW_TO_FABRIC_DESIGN.md#offline-bex-result-vector-comparison).

BO folder and BIAR, shared-model, Python importer and local MCP generation
automatically attempt [expression export](docs/MIGRATION_REFERENCE.md#export-generated-m-and-dax-expressions),
as does the opt-in REP PBIP draft. The BW cube CLI exports after local static
validation. Export requires a generated model and can fail. For ordinary
folder items other than BIAR or REP, it follows the optional DAX optimization
step and, for Fabric, the quality check; BIAR and shared-model exports precede
their Fabric quality check.

Review `.pq` files contain generated M partitions, shared/refresh expressions
and Fabric Dataflow `.m` queries. `.dax` files list only measures, calculated
columns/partitions, calculation items and RLS filters actually written in
TMDL. If nothing is exportable, manifest `expression_export.json` version 1.1
has an empty `exports` list. Existing export targets are refused; failures
can leave partial files. SQL, connection details and values may be sensitive.
The standalone command above can re-export an existing model; add
`--include-dataflow` for a generated Fabric Dataflow. These snapshots are not
static validation, BEx conversion, execution or parity evidence.

## Advanced commands and documentation

For specialized entry points and advanced options, use the built-in help:

```powershell
python migrate.py --help
python migrate.py --help-all
python migrate_deski_inspect.py --help
python migrate_paginated.py --help
python migrate_bw_bex_pbip.py --help
python migrate_bw_reconcile.py --help
```

| Topic | Documentation |
|---|---|
| RDL, SQL, REP, CMS, batch, shared models, full CLI flags and advanced examples | [Advanced migration reference](docs/MIGRATION_REFERENCE.md) |
| BW assessment, cube PBIP draft and staged historical migration | [SAP BW to Fabric design](docs/SAP_BW_TO_FABRIC_DESIGN.md) |
| Known limitations and local evidence | [Gap analysis](docs/GAP_ANALYSIS.md) |
| Local MCP and separately authorized Fabric operations | [Fabric/MCP setup](docs/FABRIC_MCP_SETUP.md) |
| Project internals and ownership | [Architecture](docs/ARCHITECTURE.md) and [agents](docs/AGENTS.md) |
| Planning and enterprise scenarios | [Development plan](docs/DEVELOPMENT_PLAN.md) and [enterprise guide](docs/ENTERPRISE_GUIDE.md) |

## Safety and verification

- Treat source files and outputs as sensitive. Credential redaction is
  pattern-based and does not guarantee that SQL or other text is sanitized.
  Do not put credentials in mapping files or command-line examples.
- Use trusted output directories; RDL and REP assessment files must be new.
- CMS server mode downloads and extracts; it is not target generation.
  The standard CLI deployment flags are unsupported. Remote operations need
  separate authorization and evidence.
- Generated refresh/schedule configurations are disabled review drafts; they
  do not deploy. `deploy_refresh_schedule` skips `None` and disabled drafts,
  and rejects malformed or incomplete enabled declarations before a client
  call; it does not invent time, time zone or notification values. A
  valid-shaped declaration is not proof of source equivalence, policy
  compliance, Power BI time-zone acceptance or runtime behavior. See
  [reviewed refresh schedule deployment](docs/MIGRATION_REFERENCE.md#deploying-a-reviewed-refresh-schedule).
- `PBIWorkspaceDeployer.deploy_rolling` is blocked (`failed`/`blocked`,
  `rolled_back: false`), makes no remote calls and leaves previously created
  remote artifacts untouched. The separate low-level `deploy_project` path
  can initiate a remote import and requires explicit authorization.
  PBIP-to-PBIX packaging compatibility, deployment, refresh and Fabric
  execution remain unverified. See [deployment limitations](docs/MIGRATION_REFERENCE.md#-deployment).
- When generated for supplied user filters, `assign_rls_roles.ps1` is a
  terminating manual-review reminder, not an assignment script. Previously
  generated scripts are not retroactively replaced and should not be run.
  Review source restrictions and identities with the security owner; assign
  roles manually and test allowed and denied access in an authorized target.
- Generated PBIP, RDL, M and Fabric artifacts do not establish query execution,
  rendering, refresh, security equivalence or source-to-target parity.

For development setup and tests, see [Contributing](CONTRIBUTING.md). The
repository test suite can be run with:

```powershell
python -m pytest tests/ --tb=short -q
```

<details>
<summary>Previous README section links</summary>

- <a id="read-webi-report-and-data-provider-metadata-from-the-cms"></a>[Read WebI report and data-provider metadata from the CMS](docs/MIGRATION_REFERENCE.md#read-webi-report-and-data-provider-metadata-from-the-cms)
- <a id="from-a-saved-webi-plan-to-rdl-and-power-query"></a>[From a saved WebI plan to RDL and Power Query](docs/MIGRATION_REFERENCE.md#from-a-saved-webi-plan-to-rdl-and-power-query)
- <a id="experimental-native-webi-extraction"></a>[Experimental native WebI extraction](docs/MIGRATION_REFERENCE.md#experimental-native-webi-extraction)
- <a id="cms-metadata-inventory-and-unbound-rdl-skeletons"></a>[CMS metadata inventory and unbound RDL skeletons](docs/MIGRATION_REFERENCE.md#cms-metadata-inventory-and-unbound-rdl-skeletons)
- <a id="desktop-report-server-and-paginated-targets"></a>[Desktop, Report Server, and paginated targets](docs/MIGRATION_REFERENCE.md#desktop-report-server-and-paginated-targets)
- <a id="sap-bw-to-fabric-staged-historical-landing"></a>[SAP BW to Fabric: staged historical landing](docs/MIGRATION_REFERENCE.md#sap-bw-to-fabric-staged-historical-landing)
- <a id="local-paginated-rdl-from-a-declared-mapping"></a>[Local paginated RDL from a declared mapping](docs/MIGRATION_REFERENCE.md#local-paginated-rdl-from-a-declared-mapping)
- <a id="dax-query-against-a-power-bi-semantic-model"></a>[DAX query against a Power BI semantic model](docs/MIGRATION_REFERENCE.md#dax-query-against-a-power-bi-semantic-model)
- <a id="explicit-sql-server-query"></a>[Explicit SQL Server query](docs/MIGRATION_REFERENCE.md#explicit-sql-server-query)
- <a id="desktop-intelligence-experimental-local-rep-inventory-in-progress"></a>[Desktop Intelligence: experimental local REP inventory (in progress)](docs/MIGRATION_REFERENCE.md#desktop-intelligence-experimental-local-rep-inventory-in-progress)
- <a id="desktop-intelligence-xi-31-experimental-sql-handoff"></a>[Desktop Intelligence XI 3.1: experimental SQL handoff](docs/MIGRATION_REFERENCE.md#desktop-intelligence-xi-31-experimental-sql-handoff)
- <a id="bo-source-preparation-and-limitations"></a>[BO source preparation and limitations](docs/MIGRATION_REFERENCE.md#bo-source-preparation-and-limitations)
- <a id="rdl-from-a-mixed-source-folder"></a>[RDL from a mixed source folder](docs/MIGRATION_REFERENCE.md#rdl-from-a-mixed-source-folder)
- <a id="reuse-previously-extracted-webi-crystal-or-universe-sql"></a>[Reuse previously extracted WebI, Crystal or universe SQL](docs/MIGRATION_REFERENCE.md#reuse-previously-extracted-webi-crystal-or-universe-sql)
- <a id="local-quality-and-mcp"></a>[Local Quality And MCP](docs/MIGRATION_REFERENCE.md#local-quality-and-mcp)
- <a id="-key-features"></a>[🎯 Key Features](docs/MIGRATION_REFERENCE.md#-key-features)
- <a id="-extraction-across-15-object-types"></a>[🔍 Extraction Across 15 Object Types](docs/MIGRATION_REFERENCE.md#-extraction-across-15-object-types)
- <a id="-bo-to-dax-formula-conversion"></a>[🧮 BO-to-DAX Formula Conversion](docs/MIGRATION_REFERENCE.md#-bo-to-dax-formula-conversion)
- <a id="-50-visual-types"></a>[📊 50+ Visual Types](docs/MIGRATION_REFERENCE.md#-50-visual-types)
- <a id="-15-data-connectors"></a>[🔌 15+ Data Connectors](docs/MIGRATION_REFERENCE.md#-15-data-connectors)
- <a id="-smart-semantic-model"></a>[🧠 Smart Semantic Model](docs/MIGRATION_REFERENCE.md#-smart-semantic-model)
- <a id="-deployment-hooks"></a>[🚀 Deployment Hooks](docs/MIGRATION_REFERENCE.md#-deployment-hooks)
- <a id="-fabric-native-output"></a>[🏭 Fabric-Native Output](docs/MIGRATION_REFERENCE.md#-fabric-native-output)
- <a id="-dax-optimizer"></a>[⚡ DAX Optimizer](docs/MIGRATION_REFERENCE.md#-dax-optimizer)
- <a id="-shared-semantic-model"></a>[🔗 Shared Semantic Model](docs/MIGRATION_REFERENCE.md#-shared-semantic-model)
- <a id="-security-profile-migration"></a>[🔒 Security Profile Migration](docs/MIGRATION_REFERENCE.md#-security-profile-migration)
- <a id="-enterprise-grade-pipeline"></a>[🔄 Enterprise-Grade Pipeline](docs/MIGRATION_REFERENCE.md#-enterprise-grade-pipeline)
- <a id="-how-it-works"></a>[🔧 How It Works](docs/MIGRATION_REFERENCE.md#-how-it-works)
- <a id="-fabric-native-output-mode"></a>[🏭 Fabric-Native Output Mode](docs/MIGRATION_REFERENCE.md#-fabric-native-output-mode)
- <a id="-shared-semantic-model-mode"></a>[🔗 Shared Semantic Model Mode](docs/MIGRATION_REFERENCE.md#-shared-semantic-model-mode)
- <a id="-generated-output"></a>[📂 Generated Output](docs/MIGRATION_REFERENCE.md#-generated-output)
- <a id="-supported-source-formats"></a>[📋 Supported Source Formats](docs/MIGRATION_REFERENCE.md#-supported-source-formats)
- <a id="-dax-conversion-examples"></a>[🧮 DAX Conversion Examples](docs/MIGRATION_REFERENCE.md#-dax-conversion-examples)
- <a id="highlights"></a>[Highlights](docs/MIGRATION_REFERENCE.md#highlights)
- <a id="-extracted-objects-15-types"></a>[📊 Extracted Objects (15 types)](docs/MIGRATION_REFERENCE.md#-extracted-objects-15-types)
- <a id="-architecture"></a>[🏗️ Architecture](docs/MIGRATION_REFERENCE.md#-architecture)
- <a id="-cli-reference"></a>[📝 CLI Reference](docs/MIGRATION_REFERENCE.md#-cli-reference)
- <a id="-deployment"></a>[🚀 Deployment](docs/MIGRATION_REFERENCE.md#-deployment)
- <a id="-testing"></a>[🧪 Testing](docs/MIGRATION_REFERENCE.md#-testing)
- <a id="cicd-pipeline"></a>[CI/CD Pipeline](docs/MIGRATION_REFERENCE.md#cicd-pipeline)
- <a id="-documentation"></a>[📚 Documentation](docs/MIGRATION_REFERENCE.md#-documentation)
- <a id="-known-limitations"></a>[⚠️ Known Limitations](docs/MIGRATION_REFERENCE.md#-known-limitations)
- <a id="-contributing"></a>[🤝 Contributing](docs/MIGRATION_REFERENCE.md#-contributing)

</details>

## License

MIT
