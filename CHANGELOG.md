# Changelog

## [Unreleased]

### Added
- Six-tool local stdio MCP server with root-scoped paths, read-only startup,
	explicit generation confirmation, and no deployment/refresh tools.
- Unified local PBIP/Fabric quality reports, strict warning validation, owner
	handoffs, and persisted per-project findings.
- Tested specialist ownership and BO/Fabric workload-skill routing: 22 development
	roles adapted from the reference project, not CLI runtime stages.
- Fabric artifact manifests, Gen2 query metadata/destinations, notebook lakehouse
	dependencies, and cross-artifact ingestion/materialization checks.

### Changed
- Fabric source tables use Direct Lake entity partitions with parameterized
	OneLake bindings; optional automatic Calendar/date-part enrichments absent
	upstream are deferred. Import date behavior remains available.
- File ingestion belongs to the primary Notebook; connected/custom SQL ingestion
	belongs to Dataflow. The primary Notebook alone materializes calculated columns.
- Documentation now separates current local evidence from the historical roadmap,
	reports the actual CI workflow, and qualifies server/deployment limitations.

### Fixed
- Local assessment and dry-run no longer generate persistent migration outputs;
	directory batch and BIAR routes perform generation with per-source failure status.
- Comparison and DAX optimization opt-outs are honored on local file/batch paths.
- Blocking Fabric quality findings return exit 6 through CLI/MCP workflows instead
	of treating emitted artifacts as success.
- Shared merging retains isolated physical tables, source connections, schema,
	datatypes, and workbook provenance. Ambiguous physical names reject before
	generation rather than collapsing sources. Universe connection extraction
	ignores empty containers and deduplicates exact repeated records only.
- Supported simple BO row expressions generate syntactically checked PySpark;
	unsupported/order-dependent expressions remain explicit failures.

### Known Limitations
- Extracted connection strings can retain credentials; automatic export redaction
	is not implemented. Review/restrict outputs before sharing.
- Server mode downloads/extracts and does not honor local assessment/dry-run
	contracts. Shared CLI deployment and standalone `--deploy-bundle` are not wired.
- Single-file deployment exceptions can be logged without a nonzero migration
	exit; local success does not prove service-side publication.
- Unsupported BO semantics and missing bindings still need action. Desktop,
	refresh, deployment, and Fabric execution remain `not_run`.

Local verification on 2026-10-28: 419 tests and 242 subtests passed. These are
unreleased changes and local measurements, not a shipped-release or runtime claim.
---

_This changelog follows [Keep a Changelog](https://keepachangelog.com/) format._
