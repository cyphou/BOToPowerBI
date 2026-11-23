"""CLI entry point for Business Objects to Power BI migration.

Usage:
    python migrate.py reports
    python migrate.py report.rep --assess
    python migrate.py --rdl-mapping mapping.json
"""

import argparse
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import logging
import os
import sys
import tempfile
import time

# Exit codes
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_FILE_NOT_FOUND = 2
EXIT_UNSUPPORTED_FORMAT = 3
EXIT_EXTRACTION_ERROR = 4
EXIT_GENERATION_ERROR = 5
EXIT_VALIDATION_ERROR = 6

logger = logging.getLogger("bo_migrate")

_QUICK_HELP = """\
BusinessObjects to Power BI - common workflows

  python migrate.py reports                  Generate PBIP from a BO folder
  python migrate.py reports --dry-run        Inspect without writing output
  python migrate.py report.wid --assess      Assess one report
  python migrate.py report.rep --assess      Inspect a DeskI report (partial)
  python migrate.py --rdl-mapping map.json   Generate map.rdl from a reviewed SQL/DAX mapping
  python migrate.py --validate-project path  Validate a generated project

For PBIP, Fabric, or DeskI assessment, -o DIRECTORY selects an output folder.
For RDL, --rdl-output FILE overrides the default path next to the mapping.
Use --output-format fabric to select Fabric.
Use --help-all for all options. See docs/MIGRATION_REFERENCE.md for advanced workflows.
Generated artifacts need independent source, data and rendering validation.
Protect outputs: SQL and metadata may be sensitive.
"""


class _QuickHelpAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        print(_QUICK_HELP, end="")
        parser.exit()


class MigrationStats:
    """Track migration timing and counts."""

    def __init__(self):
        self.start_time = time.time()
        self.extraction_time = 0.0
        self.generation_time = 0.0
        self.reports_processed = 0
        self.formulas_converted = 0
        self.visuals_mapped = 0
        self.warnings = []
        self.errors = []

    def elapsed(self):
        return time.time() - self.start_time

    def summary(self):
        return {
            "elapsed_seconds": round(self.elapsed(), 2),
            "extraction_seconds": round(self.extraction_time, 2),
            "generation_seconds": round(self.generation_time, 2),
            "reports_processed": self.reports_processed,
            "formulas_converted": self.formulas_converted,
            "visuals_mapped": self.visuals_mapped,
            "warnings": len(self.warnings),
            "errors": len(self.errors),
        }


def build_parser():
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Migrate SAP BusinessObjects reports to Power BI or generate a declared RDL",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python migrate.py reports --output-dir reports_pbi
  python migrate.py reports --rdl-batch-config rdl-batch.json
  python migrate.py reports --output-format rdl --rdl-batch-config rdl-batch.json
  python migrate.py --biar archive.biar --output-dir /tmp/batch
  python migrate.py --server https://bo:6405 --folder /Public/Sales
  python migrate.py report.wid --assess
  python migrate.py reports --output-format fabric
  python migrate.py --output-format rdl --rdl-mapping mapping.json --rdl-output report.rdl
  python migrate.py --shared-model r1.wid r2.wid --model-name "Shared"
        """,
    )
    parser.add_argument("-h", "--help", action=_QuickHelpAction, nargs=0,
                        help="Show common workflows")
    parser.add_argument("--help-all", action="help", help="Show all options")

    # Input sources
    parser.add_argument("input", nargs="?", help="Directory of BO artifacts, BIAR/LCMBIAR archive, or file to assess")
    parser.add_argument("--biar", help="Path to BIAR/LCMBIAR archive for batch migration")
    parser.add_argument(
        "--batch",
        help="Directory of BO artifacts; writes batch_manifest.json and batch_report.html",
    )

    # Server connection
    parser.add_argument("--server", help="BO CMS server URL (e.g., https://bo-server:6405)")
    parser.add_argument("--folder", help="Server folder to migrate (e.g., /Public/Sales)")
    parser.add_argument("--user", help="BO server username")
    parser.add_argument("--password", help="BO server password")
    parser.add_argument("--auth", default="enterprise", choices=["enterprise", "ldap", "windows", "sap"],
                        help="Authentication type (default: enterprise)")
    parser.add_argument("--token", help="Pre-authenticated session token")

    # Output options
    parser.add_argument("--output-dir", "-o", help="Output directory (default: <input>_pbi/)")
    parser.add_argument("--output-format", choices=["pbip", "fabric", "rdl"], default="pbip",
                        help="Output: pbip (default), fabric, or rdl from an explicit mapping")
    parser.add_argument("--rdl-mapping",
                        help="Explicit credential-free RDL mapping JSON; implies RDL if format omitted")
    parser.add_argument("--rdl-output",
                        help="RDL mode: new .rdl file (defaults to mapping name when format omitted)")
    parser.add_argument("--rdl-power-query-output",
                        help="RDL SQL mode: optional new .m file for Desktop or Desktop RS")
    parser.add_argument("--rdl-extracted-sql", help="RDL mode: previously extracted custom_sql.json")
    parser.add_argument("--rdl-bo-source", help="RDL mode: local .wid, .rpt, .rep, .unx or .unv SQL source")
    parser.add_argument("--rdl-webi-plan", help="RDL mode: saved WebI API query-plan JSON")
    parser.add_argument("--rdl-sql-name", help="RDL mode: exact name of one extracted SQL entry")
    parser.add_argument("--rdl-accept-unverified-rep-sql", action="store_true",
                        help="RDL mode: acknowledge unverified REP SQL for a local draft")
    parser.add_argument("--rdl-batch-config",
                        help="Folder mode: add paginated RDL outputs from per-source mappings")

    # Shared model
    parser.add_argument("--shared-model", nargs="+", metavar="FILE",
                        help="Build shared semantic model from multiple reports")
    parser.add_argument("--model-name", help="Name for shared semantic model")
    parser.add_argument("--assess-merge", action="store_true", help="Assess merge compatibility")
    parser.add_argument("--force-merge", action="store_true", help="Force merge despite conflicts")

    # Assessment
    parser.add_argument("--assess", action="store_true",
                        help="Run readiness assessment or partial DeskI inspection")
    parser.add_argument("--global-assess", action="store_true", help="Run cross-report portfolio assessment")
    parser.add_argument("--validate-project", metavar="DIRECTORY",
                        help="Read-only local validation of generated PBIP projects or Fabric bundles")
    parser.add_argument("--quality-output", metavar="JSON_FILE",
                        help="Save the local quality report (requires --validate-project)")
    parser.add_argument("--quality-strict", action="store_true",
                        help="Fail project validation on warnings as well as errors")

    # Deployment
    parser.add_argument("--deploy", metavar="WORKSPACE_ID",
                        help="Unsupported: CLI deployment is not wired")
    parser.add_argument("--deploy-refresh", action="store_true",
                        help="Unsupported: CLI deployment is not wired")
    parser.add_argument("--deploy-bundle", metavar="WORKSPACE_ID",
                        help="Unsupported: CLI bundle deployment is not wired")

    # Calendar
    parser.add_argument("--calendar-start", type=int, default=2020, help="Calendar start year")
    parser.add_argument("--calendar-end", type=int, default=2030, help="Calendar end year")
    parser.add_argument("--culture", default="en-US", help="Locale for date formatting")

    # Behavior
    parser.add_argument("--dry-run", action="store_true", help="Parse and analyze without writing output")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    parser.add_argument("--no-optimize-dax", action="store_true", help="Skip DAX optimization pass")
    parser.add_argument("--no-compare", action="store_true", help="Skip comparison report generation")

    # Universe options
    parser.add_argument("--universe", help="Path to universe file (.unx/.unv) for additional metadata")
    parser.add_argument("--no-universe", action="store_true", help="Skip universe extraction")

    # Schedule migration (Sprint 31)
    parser.add_argument("--refresh-config", action="store_true",
                        help="Generate PBI scheduled refresh config from BO schedules")

    # Multi-tenant deployment (Sprint 32)
    parser.add_argument("--multi-tenant", metavar="CONFIG",
                        help="Path to multi-tenant config JSON for per-tenant deployment")

    # Incremental migration (Sprint 33)
    parser.add_argument("--incremental", action="store_true",
                        help="Incremental migration: skip unchanged artifacts")
    parser.add_argument("--schema-drift", metavar="PREVIOUS",
                        help="Detect schema drift against a previous extraction directory")

    return parser


def main(argv=None):
    """Main entry point."""
    # Keep redirected output and diagnostics consistent for Unicode paths.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if stream.encoding and stream.encoding.lower() != "utf-8" and callable(reconfigure):
            reconfigure(encoding="utf-8")

    parser = build_parser()
    raw_args = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(raw_args)

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stats = MigrationStats()

    try:
        if args.deploy_bundle:
            raise ValueError("--deploy-bundle is not supported by this CLI")
        if args.deploy or args.deploy_refresh:
            raise ValueError(
                "--deploy and --deploy-refresh are not supported by this CLI; "
                "no remote deployment was attempted"
            )

        inferred_rdl = False
        if args.rdl_mapping is not None:
            format_parser = argparse.ArgumentParser(add_help=False)
            format_parser.add_argument("--output-format")
            format_args, _ = format_parser.parse_known_args(raw_args)
            if format_args.output_format is None:
                inferred_rdl = True
                args.output_format = "rdl"
                if args.rdl_output is None:
                    args.rdl_output = os.path.splitext(args.rdl_mapping)[0] + ".rdl"

        if args.output_format == "rdl":
            folder_mode = bool(args.batch or (
                args.input and (os.path.isdir(args.input) or args.rdl_batch_config)))
            if folder_mode:
                folder_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
                folder_parser.add_argument("input", nargs="?")
                folder_parser.add_argument("--batch")
                folder_parser.add_argument("--output-format")
                folder_parser.add_argument("--output-dir", "-o")
                folder_parser.add_argument("--rdl-batch-config")
                folder_parser.add_argument("--dry-run", action="store_true")
                folder_parser.add_argument("--verbose", "-v", action="store_true")
                _, unsupported = folder_parser.parse_known_args(raw_args)
                if unsupported or (args.input and args.batch) or not args.rdl_batch_config:
                    raise ValueError(
                        "RDL folder mode requires one folder and --rdl-batch-config; "
                        "other migration options are not supported"
                    )
                args.batch = args.batch or args.input
                args._positional_directory = bool(args.input)
                return _run_batch_migration(args, stats)
            rdl_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
            rdl_parser.add_argument("--output-format")
            rdl_parser.add_argument("--rdl-mapping")
            rdl_parser.add_argument("--rdl-output")
            rdl_parser.add_argument("--rdl-power-query-output")
            rdl_parser.add_argument("--rdl-extracted-sql")
            rdl_parser.add_argument("--rdl-bo-source")
            rdl_parser.add_argument("--rdl-webi-plan")
            rdl_parser.add_argument("--rdl-sql-name")
            rdl_parser.add_argument("--rdl-accept-unverified-rep-sql", action="store_true")
            rdl_parser.add_argument("--verbose", "-v", action="store_true")
            _, unsupported = rdl_parser.parse_known_args(raw_args)
            if unsupported or not args.rdl_mapping or not args.rdl_output:
                raise ValueError(
                    "RDL mode requires --rdl-mapping and --rdl-output and does not "
                    "accept positional input or other migration options"
                )
            from migrate_paginated import main as generate_paginated
            rdl_args = ["--mapping", args.rdl_mapping, "--output", args.rdl_output]
            if args.rdl_power_query_output is not None:
                rdl_args.extend(["--power-query-output", args.rdl_power_query_output])
            if args.rdl_extracted_sql is not None:
                rdl_args.extend(["--extracted-sql", args.rdl_extracted_sql])
            if args.rdl_bo_source is not None:
                rdl_args.extend(["--bo-source", args.rdl_bo_source])
            if args.rdl_webi_plan is not None:
                rdl_args.extend(["--webi-plan", args.rdl_webi_plan])
            if args.rdl_sql_name is not None:
                rdl_args.extend(["--sql-name", args.rdl_sql_name])
            if args.rdl_accept_unverified_rep_sql:
                rdl_args.append("--accept-unverified-rep-sql")
            if inferred_rdl:
                logger.info("RDL destination (new file only): %s", args.rdl_output)
            return generate_paginated(rdl_args)
        if any(value is not None for value in (
                args.rdl_mapping, args.rdl_output, args.rdl_power_query_output,
                args.rdl_extracted_sql, args.rdl_bo_source, args.rdl_webi_plan,
                args.rdl_sql_name)) or args.rdl_accept_unverified_rep_sql:
            raise ValueError("RDL options require --output-format rdl")
        if args.rdl_batch_config and not (
                args.batch or (args.input and os.path.isdir(args.input))):
            raise ValueError("--rdl-batch-config requires a source directory")

        # Determine migration mode
        if args.validate_project:
            from powerbi_import.migration_quality import build_quality_report, save_quality_report
            if args.input or args.batch or args.biar or args.server or args.shared_model:
                raise ValueError("Project validation cannot be combined with a migration source")
            report = build_quality_report(args.validate_project)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            if args.quality_output:
                save_quality_report(report, args.quality_output)
            failed = report['status'] == 'FAIL' or (args.quality_strict and report['status'] == 'WARN')
            return EXIT_VALIDATION_ERROR if failed else EXIT_SUCCESS
        if args.quality_output or args.quality_strict:
            raise ValueError("Quality options require --validate-project")
        if (args.input and not os.path.isdir(args.input)
                and os.path.splitext(args.input)[1].lower() == ".rep"
                and (args.assess or args.dry_run)):
            deski_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
            deski_parser.add_argument("input")
            deski_parser.add_argument("--assess", action="store_true")
            deski_parser.add_argument("--dry-run", action="store_true")
            deski_parser.add_argument("--output-dir", "-o")
            deski_parser.add_argument("--verbose", "-v", action="store_true")
            _, unsupported = deski_parser.parse_known_args(raw_args)
            if unsupported:
                raise ValueError(
                    "REP assessment accepts only --assess, --dry-run, "
                    "--output-dir and --verbose"
                )
            return _run_deski_assessment(args, stats)
        if args.input and os.path.isdir(args.input) and (
                args.server or args.biar or args.batch or args.shared_model):
            raise ValueError("A directory input cannot be combined with another migration source")
        if args.server:
            if args.assess or args.global_assess or args.dry_run:
                raise ValueError(
                    "Server mode downloads and extracts CMS artifacts; "
                    "--assess, --global-assess, and --dry-run are not supported with --server"
                )
            return _run_server_migration(args, stats)
        elif args.biar:
            return _run_biar_migration(args, stats)
        elif args.batch:
            return _run_batch_migration(args, stats)
        elif args.shared_model:
            return _run_shared_model_migration(args, stats)
        elif args.input:
            if os.path.isdir(args.input):
                args.batch = args.input
                args._positional_directory = True
                return _run_batch_migration(args, stats)
            if os.path.splitext(args.input)[1].lower() in (".biar", ".lcmbiar"):
                args.biar = args.input
                args._positional_archive = True
                return _run_biar_migration(args, stats)
            if args.assess or args.dry_run:
                return _run_single_migration(args, stats)
            raise ValueError(
                "Individual BO file migration is no longer supported; "
                "place the file in a directory and migrate the directory"
            )
        else:
            print(_QUICK_HELP, end="")
            return EXIT_GENERAL_ERROR

    except FileNotFoundError as e:
        logger.error("File not found: %s", e)
        return EXIT_FILE_NOT_FOUND
    except ValueError as e:
        logger.error("Invalid input: %s", e)
        return EXIT_UNSUPPORTED_FORMAT
    except Exception as e:
        logger.exception("Migration failed: %s", e)
        return EXIT_GENERAL_ERROR
    finally:
        logger.info("Migration stats: %s", json.dumps(stats.summary(), indent=2))


def _run_deski_assessment(args, stats):
    """Inspect one REP and report partial evidence without generating targets."""
    from pathlib import Path

    from bo_export.desktop_intelligence_extractor import inspect_desktop_intelligence
    from powerbi_import.deski_migration_report import build_deski_migration_report

    if args.output_dir is not None and not args.output_dir.strip():
        raise ValueError("--output-dir must not be empty")
    start = time.time()
    report = build_deski_migration_report(inspect_desktop_intelligence(args.input))
    stats.extraction_time = time.time() - start
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.assess and args.output_dir and not args.dry_run:
        from migrate_deski_inspect import _write_new_deski_outputs

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / (Path(args.input).stem + "_deski_assessment.json")
        _write_new_deski_outputs([(output, content)])
        logger.info("Partial REP assessment written: %s", output)
    print(content, end="")
    return EXIT_SUCCESS


def _record_migration_object_warnings(extracted, converted, stats, artifact_name=""):
    """Record incomplete source bindings without implying migration fidelity."""
    from powerbi_import.assessment import _SQL_BINDING_CHECK, _check_datasources, WARN

    if not any(
        isinstance(objects, list) and objects
        for objects in extracted.values()
    ):
        warnings = [
            "No BusinessObjects objects were extracted; verify the source format "
            "and parser support before relying on migration results."
        ]
    else:
        warnings = []

    if any(
        isinstance(item, dict) and item.get("native_wid_partial")
        for category in ("reports", "queries")
        for item in extracted.get(category, [])
    ):
        warnings.append(
            "Native WID extraction is partial: report layout, SQL, connections, "
            "formulas and source completeness are not established."
        )

    if (converted.get("datasources")
            and not (converted.get("worksheets") or converted.get("dashboards"))):
        warnings.append(
            "No source report visuals were converted; a PBIP report, if generated, "
            "is an empty shell and needs manual reconstruction."
        )

    checks = _check_datasources(converted).checks
    warnings.extend(
        f"{check.name}: {check.detail}"
        for check in checks
        if check.severity == WARN
        and (check.name == _SQL_BINDING_CHECK or check.name.startswith("Placeholder datasource:"))
    )
    tables = [
        table
        for datasource in converted.get("datasources", [])
        for table in datasource.get("tables", [])
    ]
    bound_columns = {
        (table["name"].casefold(), column["name"].casefold())
        for table in tables
        for column in table.get("columns", [])
        if isinstance(table.get("name"), str) and isinstance(column.get("name"), str)
    }
    unbound_columns = 0
    for column in extracted.get("columns", []):
        table, name = column.get("table"), column.get("name")
        if (not isinstance(table, str) or not table
                or not isinstance(name, str) or not name
                or (table.casefold(), name.casefold()) not in bound_columns):
            unbound_columns += 1
    if unbound_columns:
        warnings.append(
            f"{unbound_columns} extracted column(s) have no matching generated "
            "table/column; their source table binding requires review."
        )
    sql_columns = sum(
        1
        for table in tables
        if table.get("type") == "custom_sql" and table.get("sql")
        for column in table.get("columns", [])
        if column.get("name")
    )
    if sql_columns:
        warnings.append(
            f"{sql_columns} SQL result column(s) are present on generated tables, "
            "but the SQL result schema has not been verified. Review column names, "
            "types and bindings before refresh."
        )
    untranslated = {
        (table.get("name", ""), column.get("name", ""))
        for table in tables
        for column in table.get("columns", [])
        if column.get("source_expression_untranslated")
    }
    if untranslated:
        warnings.append(
            f"{len(untranslated)} BO column(s) have SQL expressions or filters that "
            "were not converted to semantic mappings; generated fields require review."
        )
    unlinked = sum(
        bool(worksheet.get("source_chart_unlinked"))
        for worksheet in converted.get("worksheets", [])
    )
    if unlinked:
        warnings.append(
            f"{unlinked} chart(s) have no matching source report/tab and were retained "
            "on the synthetic BO_Unassigned_Charts page. Review page placement, "
            "visual types and field bindings."
        )
    for warning in warnings:
        message = f"{artifact_name}: {warning}" if artifact_name else warning
        stats.warnings.append(message)
        logger.warning("%s", message)
    return warnings


def _run_single_migration(args, stats):
    """Run migration for a single BO artifact."""
    from bo_export.extract_bo_data import extract_bo_data

    input_path = os.path.abspath(args.input)

    # Security: validate input path
    if "\x00" in input_path:
        raise ValueError("Null byte in file path")

    logger.info("Starting migration: %s", input_path)

    report_name = os.path.splitext(os.path.basename(input_path))[0]
    if args.dry_run or args.assess:
        from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
        from powerbi_import.assessment import run_assessment, print_assessment_report, save_assessment_report

        t0 = time.time()
        with tempfile.TemporaryDirectory(prefix="bo_inspect_") as temporary_dir:
            extracted = extract_bo_data(input_path, output_dir=temporary_dir, verbose=args.verbose)
            converted = adapt_bo_to_converted_objects(extracted)
            report = run_assessment(converted, workbook_name=report_name)
        stats.extraction_time = time.time() - t0
        stats.reports_processed = len(extracted.get("reports", []))
        stats.formulas_converted = len(extracted.get("formulas", []))
        print_assessment_report(report)
        if args.assess and args.output_dir and not args.dry_run:
            save_assessment_report(report, output_dir=args.output_dir)
        return EXIT_SUCCESS

    # Step 1: Extraction
    t0 = time.time()
    output_dir = args.output_dir or os.path.splitext(input_path)[0] + "_pbi"
    extracted = extract_bo_data(input_path, output_dir=output_dir, verbose=args.verbose)
    stats.extraction_time = time.time() - t0
    stats.reports_processed = len(extracted.get("reports", []))
    stats.formulas_converted = len(extracted.get("formulas", []))

    # Step 2: Generation
    t1 = time.time()
    from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
    _record_migration_object_warnings(extracted, adapt_bo_to_converted_objects(extracted), stats)

    from powerbi_import.import_to_powerbi import PowerBIImporter
    importer = PowerBIImporter(source_dir=output_dir)
    project_path = importer.import_all(
        report_name=report_name,
        output_dir=output_dir,
        calendar_start=getattr(args, "calendar_start", None),
        calendar_end=getattr(args, "calendar_end", None),
        culture=getattr(args, "culture", None),
        model_mode=getattr(args, "model_mode", "import"),
        output_format=getattr(args, "output_format", "pbip"),
        defer_expression_export=True,
    )

    logger.info("Generation pipeline: output → %s", output_dir)
    stats.generation_time = time.time() - t1

    if not args.no_compare and args.output_format == 'pbip':
        from powerbi_import.comparison_report import generate_comparison_report
        generate_comparison_report(output_dir, project_path,
                                   output_path=os.path.join(output_dir, 'comparison_report.html'))

    # Step 3b: DAX optimization (always runs after generation)
    if not args.no_optimize_dax:
        try:
            from powerbi_import.dax_optimizer import optimize_dax_project
            opt_result = optimize_dax_project(output_dir)
            if opt_result.get("total_optimizations", 0) > 0:
                logger.info("DAX optimizer: %d optimization(s) applied",
                            opt_result["total_optimizations"])
        except (ImportError, Exception) as e:
            logger.debug("DAX optimization skipped: %s", e)

    # Step 3c: Refresh config from BO schedules (Sprint 31)
    if getattr(args, 'refresh_config', False):
        try:
            from powerbi_import.refresh_generator import generate_refresh_config
            schedules = extracted.get('schedules', [])
            refresh_result = generate_refresh_config(schedules)
            refresh_path = os.path.join(output_dir, "refresh_config.json")
            with open(refresh_path, 'w', encoding='utf-8') as f:
                json.dump(refresh_result, f, indent=2)
            logger.info("Refresh config written: %s", refresh_path)
        except (ImportError, Exception) as e:
            logger.debug("Refresh config generation skipped: %s", e)

    # Step 3d: Schema drift detection (Sprint 33)
    if getattr(args, 'schema_drift', None):
        try:
            from powerbi_import.schema_drift import detect_schema_drift
            prev_dir = os.path.abspath(args.schema_drift)
            prev_extracted = _load_previous_extraction(prev_dir)
            drift_report = detect_schema_drift(extracted, prev_extracted)
            drift_path = os.path.join(output_dir, "schema_drift_report.json")
            with open(drift_path, 'w', encoding='utf-8') as f:
                json.dump(drift_report.to_dict() if hasattr(drift_report, 'to_dict') else str(drift_report),
                          f, indent=2, default=str)
            logger.info("Schema drift report: %s", drift_path)
        except (ImportError, Exception) as e:
            logger.debug("Schema drift detection skipped: %s", e)

    quality_code = _validate_fabric_output(project_path, args.output_format, stats)
    if quality_code != EXIT_SUCCESS:
        return quality_code

    if args.output_format in ('pbip', 'fabric'):
        from powerbi_import.expression_export import export_generated_project
        expression_manifest = export_generated_project(
            os.path.join(project_path, f"{report_name}.SemanticModel"),
            include_dataflow=args.output_format == 'fabric',
        )
        logger.info("Exported %d expression review file(s)", len(expression_manifest['exports']))

    # Step 4: Deployment (optional)
    if args.deploy:
        logger.info("Deploying to workspace: %s", args.deploy)
        try:
            from powerbi_import.deploy.deployer import FabricDeployer
            deployer = FabricDeployer()
            deploy_result = deployer.deploy_shared_model(
                workspace_id=args.deploy,
                project_dir=output_dir,
                refresh=getattr(args, "deploy_refresh", False),
            )
            logger.info("Deployment result: %s", deploy_result.get("status", "unknown"))
        except ImportError:
            logger.warning("Deployment modules not available (azure-identity required)")
        except Exception as e:
            logger.error("Deployment failed: %s", e)

    # Step 5: Multi-tenant deployment (Sprint 32)
    if getattr(args, 'multi_tenant', None):
        logger.info("Multi-tenant deployment from config: %s", args.multi_tenant)
        try:
            from powerbi_import.deploy.multi_tenant import deploy_multi_tenant, MultiTenantConfig
            config_path = os.path.abspath(args.multi_tenant)
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            mt_config = MultiTenantConfig.from_dict(config_data)
            mt_result = deploy_multi_tenant(mt_config, output_dir)
            mt_summary_path = os.path.join(output_dir, "multi_tenant_results.json")
            with open(mt_summary_path, 'w', encoding='utf-8') as f:
                json.dump(mt_result, f, indent=2, default=str)
            logger.info("Multi-tenant deployment complete: %s", mt_summary_path)
        except FileNotFoundError:
            logger.error("Multi-tenant config not found: %s", args.multi_tenant)
        except (ImportError, Exception) as e:
            logger.error("Multi-tenant deployment failed: %s", e)

    logger.info("Migration complete: %s", input_path)
    return EXIT_SUCCESS


def _validate_fabric_output(project_path, output_format, stats):
    if output_format != 'fabric':
        return EXIT_SUCCESS
    from powerbi_import.migration_quality import build_quality_report, save_quality_report

    report = build_quality_report(project_path)
    report_path = os.path.join(project_path, 'quality_report.json')
    save_quality_report(report, report_path)
    if report['status'] != 'FAIL':
        return EXIT_SUCCESS
    findings = [item['message'] for item in report['priorities'] if item['severity'] == 'error']
    stats.errors.extend(findings)
    logger.error('Fabric generation blocked by %d quality finding(s); report: %s', len(findings), report_path)
    return EXIT_VALIDATION_ERROR


def _run_biar_migration(args, stats):
    """Run batch migration from a BIAR archive.

    Full pipeline per artifact: extract → adapter → generation → .pbip
    Each artifact is isolated: failures don't block others.
    """
    from bo_export.biar_reader import read_biar_archive, extract_artifact_from_biar
    from bo_export.extract_bo_data import extract_bo_data, _write_json_outputs
    from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects

    biar_path = os.path.abspath(args.biar)
    output_dir = args.output_dir or os.path.splitext(biar_path)[0] + "_pbi"
    inspect_only = args.dry_run or args.assess
    if (getattr(args, "_positional_archive", False) and not inspect_only
            and os.path.exists(output_dir)
            and (not os.path.isdir(output_dir) or os.listdir(output_dir))):
        raise ValueError("Archive output directory must be new or empty")
    logger.info("Starting BIAR migration: %s", biar_path)
    artifacts = read_biar_archive(biar_path)
    if not artifacts:
        message = (
            "No supported standalone artifacts (.wid, .rpt, .unx, .unv, .lumx or .lums) "
            "were found. The archive may contain embedded or segmented content; "
            "this does not establish that it has no BO reports. Export individual "
            "artifacts from BO or use a supported archive."
        )
        stats.errors.append(message)
        logger.error("%s", message)
        return EXIT_GENERAL_ERROR

    names = set()
    for artifact in artifacts:
        name = artifact.get("name", "unknown")
        key = name.casefold()
        if key in names:
            message = f"BIAR contains artifacts with the same output name: {name}"
            stats.errors.append(message)
            logger.error("%s", message)
            return EXIT_GENERAL_ERROR
        names.add(key)

    if not inspect_only:
        os.makedirs(output_dir, exist_ok=True)
    total = len(artifacts)
    batch_results = []

    for idx, artifact in enumerate(artifacts, 1):
        artifact_name = artifact.get("name", "unknown")
        ext_type = artifact.get("type", "webi")
        artifact_dir = os.path.join(output_dir, artifact_name)
        if not inspect_only:
            os.makedirs(artifact_dir, exist_ok=True)

        result = {
            "name": artifact_name,
            "type": ext_type,
            "status": "pending",
            "error": None,
            "output_dir": artifact_dir,
            "exit_code": EXIT_SUCCESS,
        }

        logger.info("[%d/%d] Processing %s (%s)", idx, total, artifact_name, ext_type)

        try:
            # Step 1: Extract
            with tempfile.TemporaryDirectory(prefix="bo_biar_") as temporary_dir:
                source = extract_artifact_from_biar(biar_path, artifact['path'], temporary_dir)
                extracted = extract_bo_data(source, output_dir=os.path.join(temporary_dir, "extracted"),
                                            verbose=args.verbose)
            # Step 2: Adapt
            converted = adapt_bo_to_converted_objects(extracted)

            if inspect_only:
                from powerbi_import.assessment import run_assessment, print_assessment_report
                print_assessment_report(run_assessment(converted, workbook_name=artifact_name))
            else:
                result["warnings"] = _record_migration_object_warnings(
                    extracted, converted, stats, artifact_name=artifact_name,
                )
                _write_json_outputs(extracted, artifact_dir)
                project_path = _generate_pbip_for_artifact(converted, artifact_name, artifact_dir, args)
                quality_code = _validate_fabric_output(project_path, args.output_format, stats)
                if quality_code != EXIT_SUCCESS:
                    result['exit_code'] = quality_code
                    result['status'] = 'failed'
                    result['error'] = 'Blocking Fabric quality findings; see the generated quality_report.json'
                    batch_results.append(result)
                    continue

            result["status"] = "success"
            stats.reports_processed += 1

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            result['exit_code'] = EXIT_GENERAL_ERROR
            stats.errors.append(f"{artifact_name}: {e}")
            logger.warning("[%d/%d] Failed: %s — %s", idx, total, artifact_name, e)

        batch_results.append(result)

    if inspect_only:
        return EXIT_SUCCESS if batch_results and not any(result['status'] == 'failed' for result in batch_results) else EXIT_GENERAL_ERROR

    # Write batch summary
    summary_path = os.path.join(output_dir, "batch_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "total": total,
            "succeeded": sum(1 for r in batch_results if r["status"] == "success"),
            "failed": sum(1 for r in batch_results if r["status"] == "failed"),
            "artifacts": batch_results,
        }, f, indent=2)

    succeeded = sum(1 for r in batch_results if r["status"] == "success")
    logger.info(
        "BIAR migration complete: %d/%d succeeded (summary: %s)",
        succeeded, total, summary_path,
    )

    # Generate HTML batch report
    try:
        from bo_export.batch_report import validate_batch_output, generate_batch_report
        validation = validate_batch_output(output_dir)
        report_path = os.path.join(output_dir, "batch_report.html")
        generate_batch_report(validation, report_path)
        logger.info("Batch report: %s", report_path)
    except Exception as e:
        logger.warning("Could not generate batch report: %s", e)

    if any(result['exit_code'] == EXIT_VALIDATION_ERROR for result in batch_results):
        return EXIT_VALIDATION_ERROR
    return EXIT_SUCCESS if total and succeeded == total else EXIT_GENERAL_ERROR


def _generate_pbip_for_artifact(converted, artifact_name, artifact_dir, args):
    """Generate .pbip project from converted objects for a single artifact."""
    from powerbi_import.import_to_powerbi import PowerBIImporter
    return PowerBIImporter().generate_powerbi_project(
        artifact_name, converted, output_dir=artifact_dir,
        calendar_start=args.calendar_start, calendar_end=args.calendar_end,
        culture=args.culture, output_format=args.output_format,
    )


def _load_rdl_batch_config(path):
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict) or set(config) != {"sources"} or not isinstance(config["sources"], dict):
        raise ValueError("RDL batch config must contain only a sources object")
    sources = {}
    for name, entry in config["sources"].items():
        if not isinstance(name, str):
            raise ValueError("RDL batch source paths must be strings")
        parts = name.replace("\\", "/").split("/")
        if any(part in ("", ".", "..") or ":" in part for part in parts):
            raise ValueError("RDL batch source paths must be relative to the source directory")
        normalized = "/".join(parts)
        if normalized in sources:
            raise ValueError(f"Duplicate RDL batch source path: {normalized}")
        if (not isinstance(entry, dict) or "mapping" not in entry
                or set(entry) - {"mapping", "sql_name", "power_query",
                                 "accept_unverified_rep_sql", "pbip"}):
            raise ValueError(f"Invalid RDL batch entry for {normalized}")
        if not isinstance(entry["mapping"], str) or not entry["mapping"].strip():
            raise ValueError(f"RDL mapping path is required for {normalized}")
        if "sql_name" in entry and (not isinstance(entry["sql_name"], str)
                                    or not entry["sql_name"].strip()):
            raise ValueError(f"RDL SQL name must be nonempty for {normalized}")
        if "power_query" in entry and not isinstance(entry["power_query"], bool):
            raise ValueError(f"RDL power_query must be a boolean for {normalized}")
        if ("accept_unverified_rep_sql" in entry
                and not isinstance(entry["accept_unverified_rep_sql"], bool)):
            raise ValueError(
                f"RDL accept_unverified_rep_sql must be a boolean for {normalized}"
            )
        if "pbip" in entry and not isinstance(entry["pbip"], dict):
            raise ValueError(f"RDL batch PBIP declaration must be an object for {normalized}")
        sources[normalized] = entry
    return sources


def _load_rdl_batch_mapping(mapping_name, config_dir, source_kind):
    if os.path.isabs(mapping_name):
        raise ValueError("RDL mapping paths must be relative to the batch config directory")
    mapping_path = os.path.realpath(os.path.join(config_dir, mapping_name))
    if os.path.normcase(os.path.commonpath([config_dir, mapping_path])) != os.path.normcase(config_dir):
        raise ValueError("RDL mapping path must stay within the batch config directory")
    with open(mapping_path, encoding="utf-8") as handle:
        mapping = json.load(handle)
    if not isinstance(mapping, dict) or mapping.get("source_kind") != source_kind:
        raise ValueError("RDL mapping source_kind must match the source extension")
    return mapping_path, mapping


def _run_rdl_batch_item(source_path, item_output, source_kind, entry, config_dir, dry_run):
    if source_kind == "biar":
        raise ValueError("RDL batch cannot select reports inside BIAR/LCMBIAR; export individual files")
    if entry is None:
        raise ValueError("No RDL mapping configured for this source")

    mapping_path, mapping = _load_rdl_batch_mapping(
        entry["mapping"], config_dir, source_kind,
    )
    if "pbip" in entry and source_kind != "desktop_intelligence":
        raise ValueError("The per-source PBIP declaration is currently only supported for .rep")

    sql_name = entry.get("sql_name")
    accept_unverified_rep_sql = entry.get("accept_unverified_rep_sql", False)
    if source_kind == "desktop_intelligence":
        if sql_name is not None and not accept_unverified_rep_sql:
            raise ValueError(
                "REP SQL batch selection requires accept_unverified_rep_sql: true"
            )
        if accept_unverified_rep_sql and sql_name is None:
            raise ValueError(
                "accept_unverified_rep_sql requires an exact REP sql_name"
            )
    elif accept_unverified_rep_sql:
        raise ValueError("accept_unverified_rep_sql is only valid for a .rep source")
    if sql_name is not None and source_kind not in {
        "webi", "crystal", "universe", "desktop_intelligence"
    }:
        raise ValueError("Direct SQL selection is not supported for this source type")
    if sql_name is not None and source_kind == "crystal":
        logger.warning("Crystal SQL is a heuristic text candidate; review its completeness and provenance")

    from migrate_paginated import main as generate_paginated

    def generate(directory):
        arguments = ["--mapping", mapping_path, "--output", os.path.join(directory, "report.rdl")]
        if sql_name is not None:
            arguments.extend(["--bo-source", source_path, "--sql-name", sql_name])
        if accept_unverified_rep_sql:
            arguments.append("--accept-unverified-rep-sql")
        if entry.get("power_query", False):
            arguments.extend(["--power-query-output", os.path.join(directory, "query.m")])
        errors = StringIO()
        with redirect_stderr(errors):
            exit_code = generate_paginated(arguments)
        message = errors.getvalue().strip() if exit_code else None
        if message:
            logger.error("RDL generation failed for %s: %s", source_path, message)
        return exit_code, message

    if dry_run:
        with tempfile.TemporaryDirectory(prefix="bo_rdl_batch_") as temporary_dir:
            return generate(temporary_dir)
    os.makedirs(item_output, exist_ok=True)
    return generate(item_output)


def _run_deski_pbip_target(source_path, item_output, entry, config_dir, dry_run, item_stats):
    if not isinstance(entry, dict) or entry.get("pbip") is None:
        raise ValueError(
            "Automatic REP-to-PBIP migration is not supported; declare a per-source "
            "pbip mapping for a manual SQL table draft"
        )
    if not entry.get("accept_unverified_rep_sql"):
        raise ValueError("REP PBIP generation requires accept_unverified_rep_sql: true")
    sql_name = entry.get("sql_name")
    if not isinstance(sql_name, str) or not sql_name.strip():
        raise ValueError("REP PBIP generation requires an exact sql_name selector")

    mapping_path, rdl_mapping = _load_rdl_batch_mapping(
        entry.get("mapping"), config_dir, "desktop_intelligence",
    )
    pbip_mapping = entry["pbip"]
    expected_keys = {"connection_name", "query_name", "schema", "columns"}
    if not isinstance(pbip_mapping, dict) or set(pbip_mapping) != expected_keys:
        raise ValueError(
            "REP pbip declaration must contain exactly connection_name, query_name, "
            "schema and columns"
        )
    for key in ("connection_name", "query_name", "schema"):
        value = pbip_mapping[key]
        if (not isinstance(value, str) or not value.strip()
                or any(ord(character) < 32 or ord(character) == 127 for character in value)):
            raise ValueError(f"REP PBIP {key} must be a non-empty string without control characters")
    if (not isinstance(rdl_mapping.get("server"), str) or not rdl_mapping["server"].strip()
            or not isinstance(rdl_mapping.get("database"), str)
            or not rdl_mapping["database"].strip()
            or not isinstance(rdl_mapping.get("title"), str)
            or not rdl_mapping["title"].strip()):
        raise ValueError("REP PBIP requires declared RDL title, SQL Server and database mappings")
    declared_rdl_columns = rdl_mapping.get("columns")
    if (not isinstance(declared_rdl_columns, list) or not declared_rdl_columns
            or not all(isinstance(name, str) and name.strip() for name in declared_rdl_columns)):
        raise ValueError("REP PBIP requires non-empty declared RDL result columns")

    columns = pbip_mapping["columns"]
    if not isinstance(columns, list) or not columns:
        raise ValueError("REP pbip columns must be a non-empty list")
    supported_types = {
        "string", "integer", "float", "decimal", "boolean", "date", "datetime",
    }
    column_names = []
    for column in columns:
        if not isinstance(column, dict) or set(column) != {"name", "data_type", "role"}:
            raise ValueError(
                "Each REP PBIP column must contain exactly name, data_type and role"
            )
        name, data_type, role = (
            column["name"], column["data_type"], column["role"],
        )
        if (not isinstance(name, str) or not name.strip()
                or any(ord(character) < 32 or ord(character) == 127 for character in name)):
            raise ValueError("REP PBIP column names must be non-empty strings without control characters")
        if not isinstance(data_type, str) or data_type not in supported_types:
            raise ValueError(
                "REP PBIP data_type must be one of string, integer, float, decimal, "
                "boolean, date or datetime"
            )
        if not isinstance(role, str) or role not in {"dimension", "measure"}:
            raise ValueError("REP PBIP column role must be dimension or measure")
        if role == "measure" and data_type not in {"integer", "float", "decimal"}:
            raise ValueError("REP PBIP measure columns must have a numeric data_type")
        column_names.append(name)
    if len({name.casefold() for name in column_names}) != len(column_names):
        raise ValueError("REP PBIP column names must be unique")
    if column_names != declared_rdl_columns:
        raise ValueError("REP PBIP columns must match the RDL mapping columns in order")

    from bo_export.desktop_intelligence_extractor import (
        desktop_intelligence_sql_selector,
        inspect_desktop_intelligence,
    )

    extraction_started = time.time()
    inventory = inspect_desktop_intelligence(source_path)
    item_stats.extraction_time += time.time() - extraction_started
    candidates = [
        candidate for candidate in inventory["sql_candidates"]
        if desktop_intelligence_sql_selector(candidate) == sql_name
    ]
    if len(candidates) != 1:
        raise ValueError("REP sql_name must match exactly one SQL candidate in this source")
    candidate = candidates[0]
    if candidate["bo_function_markers"]:
        markers = ", ".join(f"@{marker}" for marker in candidate["bo_function_markers"])
        raise ValueError(
            f"REP SQL contains unresolved BO function markers ({markers}); "
            "rewrite and review them before PBIP generation"
        )

    extracted = {
        "reports": [{
            "name": rdl_mapping["title"],
            "title": rdl_mapping["title"],
            "type": "desktop_intelligence",
        }],
        "queries": [{
            "id": sql_name,
            "name": pbip_mapping["query_name"],
            "type": "sql_server",
            "datasource": pbip_mapping["connection_name"],
            "sql": candidate["sql"],
            "objects": [],
        }],
        "datasources": [{
            "name": pbip_mapping["connection_name"],
            "type": "sql_server",
            "server": rdl_mapping["server"],
            "database": rdl_mapping["database"],
            "schema": pbip_mapping["schema"],
        }],
        "formulas": [],
        "prompts": [],
        "filters": [],
        "tables": [],
        "columns": [{
            "name": column["name"],
            "table": pbip_mapping["query_name"],
            "data_type": column["data_type"],
            "qualification": column["role"],
        } for column in columns],
        "joins": [],
        "groups": [],
        "sorts": [],
        "alerts": [],
        "subreports": [],
        "charts": [{
            "name": rdl_mapping["title"],
            "title": rdl_mapping["title"],
            "report": rdl_mapping["title"],
            "type": "table",
            "dimensions": [
                column["name"] for column in columns if column["role"] == "dimension"
            ],
            "measures": [
                column["name"] for column in columns if column["role"] == "measure"
            ],
        }],
        "custom_sql": [{
            "name": pbip_mapping["query_name"],
            "sql": candidate["sql"],
            "datasource": pbip_mapping["connection_name"],
        }],
    }

    from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
    from bo_export.extract_bo_data import _write_json_outputs
    from powerbi_import.import_to_powerbi import PowerBIImporter

    report_name = os.path.splitext(os.path.basename(source_path))[0]

    def generate(source_dir, target_dir):
        os.makedirs(source_dir, exist_ok=True)
        os.makedirs(target_dir, exist_ok=True)
        if os.listdir(target_dir):
            raise ValueError(f"REP PBIP target directory is not empty: {target_dir}")
        _write_json_outputs(extracted, source_dir)
        converted = adapt_bo_to_converted_objects(extracted)
        _record_migration_object_warnings(
            extracted, converted, item_stats, os.path.basename(source_path),
        )
        generation_started = time.time()
        with redirect_stdout(StringIO()):
            project_path = PowerBIImporter(source_dir=source_dir).import_all(
                report_name=report_name, output_dir=target_dir,
            )
        item_stats.generation_time += time.time() - generation_started
        if not project_path or not os.path.isfile(
                os.path.join(project_path, f"{report_name}.pbip")):
            raise ValueError("REP PBIP generator did not create the expected project file")
        from powerbi_import.validator import ArtifactValidator

        validation = ArtifactValidator.validate_project(project_path)
        if not validation["valid"]:
            findings = "; ".join(validation["errors"]) or "validator returned invalid"
            raise ValueError(
                f"REP PBIP draft failed local static validation: {findings}"
            )
        item_stats.warnings.extend(
            f"REP PBIP static validation: {warning}"
            for warning in validation["warnings"]
        )

    if dry_run:
        with tempfile.TemporaryDirectory(prefix="bo_rep_pbip_dry_") as temporary_dir:
            generate(
                os.path.join(temporary_dir, "source"),
                os.path.join(temporary_dir, "target"),
            )
    else:
        pbip_output = os.path.join(item_output, "PowerBI")
        if os.path.exists(pbip_output):
            raise ValueError(f"REP PBIP target already exists: {pbip_output}")
        os.makedirs(item_output, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="bo_rep_pbip_source_") as source_dir:
            generate(source_dir, pbip_output)
        item_stats.warnings.append(
            "REP PBIP is a manually declared table draft; source layout, formulas, prompts, "
            "provider/report links and equivalence remain unverified"
        )
        logger.info("Generated REP PBIP draft: %s", pbip_output)
    item_stats.reports_processed += 1
    return EXIT_SUCCESS


def _run_rdl_batch_target(source_path, item_output, source_kind, entry,
                          config_dir, dry_run, item_stats):
    try:
        exit_code, error_message = _run_rdl_batch_item(
            source_path, item_output, source_kind, entry, config_dir, dry_run,
        )
    except Exception as error:
        logger.warning("Paginated report generation failed for %s: %s", source_path, error)
        exit_code, error_message = EXIT_GENERAL_ERROR, str(error)
    if exit_code == EXIT_SUCCESS:
        item_stats.reports_processed += 1
    elif not error_message:
        error_message = "RDL generation failed; see logs"
    if source_kind == "crystal" and entry and entry.get("sql_name") is not None:
        item_stats.warnings.append("Crystal SQL extraction is heuristic")
    if (source_kind == "desktop_intelligence" and entry
            and entry.get("accept_unverified_rep_sql")):
        item_stats.warnings.append(
            "Selected REP SQL remains an unverified candidate; review its SQL, "
            "provider association, connection and result fields"
        )
    return {
        "status": "success" if exit_code == EXIT_SUCCESS else "failed",
        "exit_code": exit_code,
        "error": error_message,
        "output_dir": item_output,
    }


def _run_batch_migration(args, stats):
    """Run batch migration from a directory of BO artifacts."""
    from bo_export.extract_bo_data import SUPPORTED_EXTENSIONS

    batch_dir = os.path.abspath(args.batch)
    if not os.path.isdir(batch_dir):
        raise FileNotFoundError(f"Batch directory not found: {batch_dir}")
    rdl_mode = args.output_format == "rdl"
    rdl_sidecar = not rdl_mode and args.rdl_batch_config is not None
    output_dir = os.path.abspath(args.output_dir or batch_dir + ("_rdl" if rdl_mode else "_pbi"))
    source_real = os.path.normcase(os.path.realpath(batch_dir))
    output_real = os.path.normcase(os.path.realpath(output_dir))
    try:
        output_is_ancestor = os.path.commonpath([source_real, output_real]) == output_real
    except ValueError:
        output_is_ancestor = False  # Different Windows drives.
    if output_is_ancestor:
        raise ValueError("Batch output cannot be the source directory or its ancestor")
    if (rdl_mode or getattr(args, "_positional_directory", False)) and os.path.exists(output_dir):
        if not os.path.isdir(output_dir) or os.listdir(output_dir):
            raise ValueError("Folder output directory must be new or empty")

    config_dir = ""
    rdl_sources = {}
    if rdl_mode or rdl_sidecar:
        config_path = os.path.realpath(args.rdl_batch_config)
        config_dir = os.path.dirname(config_path)
        rdl_sources = _load_rdl_batch_config(config_path)
        if rdl_mode and any("pbip" in entry for entry in rdl_sources.values()):
            raise ValueError("Per-source pbip declarations require combined PBIP and RDL mode")

    artifacts = []
    skipped = []

    def walk_error(error):
        raise error

    for root, dirs, files in os.walk(batch_dir, onerror=walk_error):
        kept_dirs = []
        for directory in sorted(dirs):
            path = os.path.join(root, directory)
            if os.path.normcase(os.path.realpath(path)) == output_real:
                continue
            if os.path.islink(path):
                skipped.append({"source": os.path.relpath(path, batch_dir).replace("\\", "/"),
                                "reason": "Symbolic-link directory not followed"})
            else:
                kept_dirs.append(directory)
        dirs[:] = kept_dirs
        for fname in sorted(files):
            path = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()
            if os.path.islink(path):
                skipped.append({"source": os.path.relpath(path, batch_dir).replace("\\", "/"),
                                "reason": "Symbolic-link file not followed"})
            elif ext in SUPPORTED_EXTENSIONS or ((rdl_mode or rdl_sidecar) and ext == ".rep"):
                artifacts.append(path)
            else:
                relative = os.path.relpath(path, batch_dir)
                skipped.append({"source": relative.replace("\\", "/"),
                                "reason": "Unsupported file extension"})

    logger.info("Batch migration: %d artifacts found in %s", len(artifacts), batch_dir)
    if skipped:
        for item in skipped:
            logger.warning("Skipped %s: %s", item["source"], item["reason"])
            stats.warnings.append(f'{item["source"]}: {item["reason"]}')
    if not artifacts:
        raise ValueError("No supported BO artifacts found in the batch directory")
    if rdl_mode or rdl_sidecar:
        discovered = {os.path.relpath(path, batch_dir).replace("\\", "/") for path in artifacts}
        unused = sorted(set(rdl_sources) - discovered)
        if unused:
            raise ValueError(f"RDL batch config references undiscovered source: {unused[0]}")

    results = []
    for artifact_path in artifacts:
        relative_path = os.path.relpath(artifact_path, batch_dir)
        source_key = relative_path.replace("\\", "/")
        extension = os.path.splitext(artifact_path)[1].lower()
        source_kind = (
            "desktop_intelligence" if extension == ".rep"
            else SUPPORTED_EXTENSIONS[extension]
        )
        item_output = os.path.join(output_dir, relative_path)
        item_args = argparse.Namespace(**vars(args))
        item_args.input = artifact_path
        item_args.output_dir = item_output
        item_stats = MigrationStats()
        target_results = {}
        if rdl_mode:
            target_results["paginated"] = _run_rdl_batch_target(
                artifact_path, item_output, source_kind, rdl_sources.get(source_key),
                config_dir, args.dry_run, item_stats,
            )
        else:
            try:
                if source_kind == 'desktop_intelligence':
                    if args.output_format != "pbip":
                        raise ValueError(
                            "Declared REP Power BI drafts currently require --output-format pbip; "
                            "REP-to-Fabric generation is not supported"
                        )
                    target_exit = _run_deski_pbip_target(
                        artifact_path, item_output, rdl_sources.get(source_key),
                        config_dir, args.dry_run, item_stats,
                    )
                elif source_kind == 'biar':
                    item_args.biar = artifact_path
                    target_exit = _run_biar_migration(item_args, item_stats)
                else:
                    target_exit = _run_single_migration(item_args, item_stats)
                target_error = None
                if target_exit == EXIT_VALIDATION_ERROR:
                    target_error = (
                        "Blocking Fabric quality findings; see per-project quality_report.json"
                    )
                elif target_exit != EXIT_SUCCESS:
                    target_error = "; ".join(item_stats.errors) or "Migration failed; see logs"
                target_results["powerbi"] = {
                    "status": "success" if target_exit == EXIT_SUCCESS else "failed",
                    "exit_code": target_exit,
                    "error": target_error,
                    "output_dir": (
                        os.path.join(item_output, "PowerBI")
                        if source_kind == "desktop_intelligence" else item_output
                    ),
                }
            except Exception as error:
                logger.warning("Power BI migration failed for %s: %s", artifact_path, error)
                target_results["powerbi"] = {
                    "status": "failed", "exit_code": EXIT_GENERAL_ERROR,
                    "error": str(error), "output_dir": item_output,
                }

            if rdl_sidecar:
                target_results["paginated"] = _run_rdl_batch_target(
                    artifact_path, os.path.join(item_output, "PaginatedReport"),
                    source_kind, rdl_sources.get(source_key), config_dir,
                    args.dry_run, item_stats,
                )

        stats.reports_processed += item_stats.reports_processed
        stats.formulas_converted += item_stats.formulas_converted
        stats.extraction_time += item_stats.extraction_time
        stats.generation_time += item_stats.generation_time
        stats.errors.extend(item_stats.errors)
        stats.warnings.extend(item_stats.warnings)
        target_codes = [target["exit_code"] for target in target_results.values()]
        if any(code == EXIT_VALIDATION_ERROR for code in target_codes):
            exit_code = EXIT_VALIDATION_ERROR
        else:
            exit_code = EXIT_SUCCESS if target_codes and all(
                code == EXIT_SUCCESS for code in target_codes
            ) else EXIT_GENERAL_ERROR
        error_message = "; ".join(
            f'{target_name}: {target["error"]}'
            for target_name, target in target_results.items()
            if target["error"]
        ) or None
        for target_name, target in target_results.items():
            if target["error"] and target["error"] not in item_stats.errors:
                stats.errors.append(f'{source_key}: {target_name}: {target["error"]}')
        results.append({"source": relative_path, "source_kind": source_kind, "output_dir": item_output,
                        "exit_code": exit_code,
                        "error": error_message,
                        "status": "success" if exit_code == EXIT_SUCCESS else "failed",
                        "warnings": item_stats.warnings,
                        "targets": target_results})

    if not args.dry_run:
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "batch_manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"artifacts": results, "skipped": skipped}, handle, indent=2, ensure_ascii=False)
        try:
            from bo_export.batch_report import generate_migration_batch_report
            report_path = generate_migration_batch_report(output_dir)
            logger.info("Batch migration report: %s", report_path)
        except (OSError, ValueError, TypeError) as error:
            logger.warning("Could not generate batch migration report: %s", error)
            stats.warnings.append(f"Could not generate batch migration report: {error}")
    succeeded = sum(result["exit_code"] == EXIT_SUCCESS for result in results)
    logger.info("Batch migration complete: %d/%d succeeded", succeeded, len(artifacts))
    if any(result['exit_code'] == EXIT_VALIDATION_ERROR for result in results):
        return EXIT_VALIDATION_ERROR
    return EXIT_SUCCESS if succeeded == len(artifacts) else EXIT_GENERAL_ERROR


def _run_server_migration(args, stats):
    """Run migration from BO CMS server."""
    from bo_export.server_client import BOServerClient

    output_dir = args.output_dir or "server_migration_output"

    with BOServerClient(args.server, args.user, args.password, args.auth, args.token) as client:
        paths = client.batch_download(args.folder, output_dir)
        logger.info("Downloaded %d artifacts from server", len(paths))

        from bo_export.extract_bo_data import extract_bo_data
        for path in paths:
            try:
                extract_bo_data(path, output_dir=output_dir, verbose=args.verbose)
                stats.reports_processed += 1
            except Exception as e:
                logger.warning("Failed to migrate %s: %s", path, e)

    return EXIT_SUCCESS


def _run_shared_model_migration(args, stats):
    """Run shared semantic model migration from multiple reports."""
    from bo_export.extract_bo_data import extract_bo_data
    from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects
    from powerbi_import.import_to_powerbi import PowerBIImporter
    from powerbi_import.shared_model import assess_merge

    output_dir = args.output_dir or "shared_model_output"
    model_name = args.model_name or "SharedModel"
    if len(args.shared_model) < 2:
        raise ValueError("A shared model requires at least two source files")

    all_converted = []
    report_names = []
    with tempfile.TemporaryDirectory(prefix="bo_merge_") as temporary_dir:
        for index, input_path in enumerate(args.shared_model):
            extracted = extract_bo_data(os.path.abspath(input_path),
                                        output_dir=os.path.join(temporary_dir, str(index)),
                                        verbose=args.verbose)
            all_converted.append(adapt_bo_to_converted_objects(extracted))
            report_names.append(os.path.splitext(os.path.basename(input_path))[0])
            stats.reports_processed += 1

    if args.assess_merge or args.assess or args.dry_run:
        from powerbi_import.merge_assessment import print_merge_summary
        print_merge_summary(assess_merge(all_converted, report_names))
        return EXIT_SUCCESS

    result = PowerBIImporter().import_shared_model(
        model_name, all_converted, report_names, output_dir=output_dir,
        calendar_start=args.calendar_start, calendar_end=args.calendar_end,
        culture=args.culture, force_merge=args.force_merge,
        workbook_paths=[os.path.abspath(path) for path in args.shared_model],
        output_format=args.output_format,
    )
    if not result.get('model_path'):
        return EXIT_GENERATION_ERROR
    return _validate_fabric_output(os.path.dirname(result['model_path']), args.output_format, stats)


def _load_previous_extraction(prev_dir):
    """Load a previous extraction from a directory of JSON files."""
    extracted = {}
    json_types = [
        "reports", "queries", "datasources", "formulas", "prompts",
        "filters", "tables", "columns", "joins", "groups", "sorts",
        "alerts", "subreports", "charts", "custom_sql",
    ]
    for jtype in json_types:
        path = os.path.join(prev_dir, f"{jtype}.json")
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                extracted[jtype] = json.load(f)
    return extracted


if __name__ == "__main__":
    sys.exit(main())
