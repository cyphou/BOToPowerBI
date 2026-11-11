# Changelog

## [Unreleased]

### Added
- Separate offline BW inventory validation and a staged-history Bronze notebook
	generator with an explicit plan, schema/count checks, provenance and refusal
	of existing targets. SAP extraction, Fabric execution and BW equivalence are
	not provided.
- Separate offline BW-0 inventory gap assessment that reports blockers and
	review items without verifying live SAP discovery, source-owner attestations,
	or closing the BW-0 gate.
- Separate offline BW snapshot control comparator with explicit scope identity,
	exact count checks, declared numeric tolerances, and runtime evidence marked
	`not_run`; it does not collect or attest to source or target measurements.
- Separate offline BW snapshot-to-delta handoff evaluator for a normalized,
	declared contiguous-position feed, covering replay, overlap, ordering,
	deletes, schema drift and final-state comparison; no source or Fabric runtime
	evidence is implied.
- Separate offline BW transformation-vector comparator with strict field
	coverage, exact type/value checks and declared decimal tolerances; it does not
	execute or translate ABAP or verify supplied source/target outputs.
- Separate offline BW-5 BEx semantic-capture contract and gap assessment for
	variables, filters, hierarchies, key figures, authorization contexts and
	inventory-linked consumers; it does not parse, convert or execute BEx queries.
- Separate offline BW-6 security, planning and compliance controls assessment
	with inventory-linked authorization declarations, allow/deny test scenarios,
	planning-control coverage, and audit/retention/privacy/legal-hold references.
	It does not execute target controls or certify compliance; runtime evidence
	remains `not_run`.
- Separate offline BW-7 wave evidence index for BW-2 through BW-6 per-object
	declarations and wave-level operational references. It checks inventory
	scope/linkage and declared statuses, preserves referenced evidence metadata,
	and does not verify report bytes, freshness/correctness, runtime execution,
	operational certification, or retirement approval.
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
- Full BW warehouse migration remains incomplete: staged Parquet is supplied
	externally; durable upstream feeds, ABAP/BEx conversion, reconciliation,
	security and retirement still need implementation and runtime evidence.
- Extracted connection strings can retain credentials; automatic export redaction
	is not implemented. Review/restrict outputs before sharing.
- Server mode downloads/extracts and does not honor local assessment/dry-run
	contracts. Shared CLI deployment and standalone `--deploy-bundle` are not wired.
- Single-file deployment exceptions can be logged without a nonzero migration
	exit; local success does not prove service-side publication.
- Unsupported BO semantics and missing bindings still need action. Desktop,
	refresh, deployment, and Fabric execution remain `not_run`.

Local verification on 2026-11-11: 497 tests and 365 subtests passed. These are
unreleased changes and local measurements, not a shipped-release or runtime claim.
---

_This changelog follows [Keep a Changelog](https://keepachangelog.com/) format._
