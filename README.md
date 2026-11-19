# BusinessObjects to Power BI Migration

Generate local Power BI, Fabric or paginated-report artifacts from supported
SAP BusinessObjects metadata. Extraction and conversion are partial: generated
files still require source, data, security and report validation.

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
| WebI `.wid`, Crystal `.rpt`, universes `.unx`/`.unv`, Lumira `.lumx`/`.lums` | Local extraction and generation are format-dependent and incomplete. |
| `.biar`/`.lcmbiar` | Directly recognized archive entries only; embedded or segmented contents are not fully decoded. |
| Desktop Intelligence `.rep` | Partial inventory, explicitly acknowledged RDL drafts and an opt-in manually declared PBIP table draft; no automatic PBIP/Fabric conversion. |
| Power BI Desktop | PBIP is intended for standard Desktop; open and verify the project separately. |
| Power BI Report Server | Desktop for Report Server does not support PBIP. An optional SQL-based M query is a manual reconstruction aid; RDL is a separate paginated target. |
| SAP BW | Separate offline assessment and bounded staged-data tools, not full BW extraction or warehouse replacement. See the [BW design](docs/SAP_BW_TO_FABRIC_DESIGN.md). |

When no source visuals are converted, PBIP generation creates an empty report
shell for the model; it does not reconstruct the source report. An existing
report is not overwritten by an empty shell; use a new output directory.

## Advanced commands and documentation

For specialized entry points and advanced options, use the built-in help:

```powershell
python migrate.py --help
python migrate.py --help-all
python migrate_deski_inspect.py --help
python migrate_paginated.py --help
```

| Topic | Documentation |
|---|---|
| RDL, SQL, REP, CMS, batch, shared models, full CLI flags and advanced examples | [Advanced migration reference](docs/MIGRATION_REFERENCE.md) |
| BW assessment and staged historical migration | [SAP BW to Fabric design](docs/SAP_BW_TO_FABRIC_DESIGN.md) |
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
