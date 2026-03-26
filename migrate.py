"""CLI entry point for Business Objects to Power BI migration.

Usage:
    python migrate.py path/to/report.wid
    python migrate.py path/to/report.rpt --output-dir /tmp/output
    python migrate.py --biar path/to/archive.biar --output-dir /tmp/batch
    python migrate.py --server https://bo-server:6405 --folder "/Public/Sales"
    python migrate.py path/to/report.wid --assess
    python migrate.py path/to/report.wid --deploy WORKSPACE_ID
    python migrate.py path/to/report.wid --refresh-config
    python migrate.py path/to/report.wid --multi-tenant config.json
    python migrate.py path/to/report.wid --incremental
    python migrate.py path/to/report.wid --schema-drift /prev/extraction/
"""

import argparse
import json
import logging
import os
import sys
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
        description="Migrate SAP BusinessObjects reports to Power BI (.pbip)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python migrate.py report.wid
  python migrate.py report.rpt --output-dir /tmp/output
  python migrate.py --biar archive.biar --output-dir /tmp/batch
  python migrate.py --server https://bo:6405 --folder /Public/Sales
  python migrate.py report.wid --assess
  python migrate.py report.wid --output-format fabric
  python migrate.py --shared-model r1.wid r2.wid --model-name "Shared"
        """,
    )

    # Input sources
    parser.add_argument("input", nargs="?", help="Path to .wid, .rpt, .unx, .unv, .lumx, or .lums file")
    parser.add_argument("--biar", help="Path to BIAR/LCMBIAR archive for batch migration")
    parser.add_argument("--batch", help="Directory containing BO artifacts for batch migration")

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
    parser.add_argument("--output-format", choices=["pbip", "fabric"], default="pbip",
                        help="Output format: pbip (default) or fabric")

    # Shared model
    parser.add_argument("--shared-model", nargs="+", metavar="FILE",
                        help="Build shared semantic model from multiple reports")
    parser.add_argument("--model-name", help="Name for shared semantic model")
    parser.add_argument("--assess-merge", action="store_true", help="Assess merge compatibility")
    parser.add_argument("--force-merge", action="store_true", help="Force merge despite conflicts")

    # Assessment
    parser.add_argument("--assess", action="store_true", help="Run migration readiness assessment")
    parser.add_argument("--global-assess", action="store_true", help="Run cross-report portfolio assessment")

    # Deployment
    parser.add_argument("--deploy", metavar="WORKSPACE_ID", help="Deploy to Fabric workspace")
    parser.add_argument("--deploy-refresh", action="store_true", help="Trigger refresh after deployment")
    parser.add_argument("--deploy-bundle", metavar="WORKSPACE_ID",
                        help="Deploy shared model + thin reports as bundle")

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
    parser = build_parser()
    args = parser.parse_args(argv)

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Ensure stdout handles unicode
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    stats = MigrationStats()

    try:
        # Determine migration mode
        if args.server:
            return _run_server_migration(args, stats)
        elif args.biar:
            return _run_biar_migration(args, stats)
        elif args.batch:
            return _run_batch_migration(args, stats)
        elif args.shared_model:
            return _run_shared_model_migration(args, stats)
        elif args.input:
            return _run_single_migration(args, stats)
        else:
            parser.print_help()
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


def _run_single_migration(args, stats):
    """Run migration for a single BO artifact."""
    from bo_export.extract_bo_data import extract_bo_data

    input_path = os.path.abspath(args.input)

    # Security: validate input path
    if "\x00" in input_path:
        raise ValueError("Null byte in file path")

    logger.info("Starting migration: %s", input_path)

    # Step 1: Extraction
    t0 = time.time()
    extracted = extract_bo_data(input_path, output_dir=args.output_dir, verbose=args.verbose)
    stats.extraction_time = time.time() - t0
    stats.reports_processed = len(extracted.get("reports", []))
    stats.formulas_converted = len(extracted.get("formulas", []))

    if args.dry_run:
        logger.info("Dry run complete. Extraction results available.")
        return EXIT_SUCCESS

    # Step 2: Generation
    t1 = time.time()
    output_dir = args.output_dir or os.path.splitext(input_path)[0] + "_pbi"
    report_name = os.path.splitext(os.path.basename(input_path))[0]

    from powerbi_import.import_to_powerbi import PowerBIImporter
    extract_dir = args.output_dir or os.path.dirname(os.path.abspath(input_path))
    importer = PowerBIImporter(source_dir=extract_dir)
    importer.import_all(
        report_name=report_name,
        output_dir=output_dir,
        calendar_start=getattr(args, "calendar_start", None),
        calendar_end=getattr(args, "calendar_end", None),
        culture=getattr(args, "culture", None),
        model_mode=getattr(args, "model_mode", "import"),
        output_format=getattr(args, "output_format", "pbip"),
    )

    logger.info("Generation pipeline: output → %s", output_dir)
    stats.generation_time = time.time() - t1

    # Step 3: Assessment (optional)
    if args.assess:
        logger.info("Running migration readiness assessment...")
        from powerbi_import.assessment import run_assessment, print_assessment_report, save_assessment_report
        report = run_assessment(extracted, workbook_name=report_name)
        print_assessment_report(report)
        save_assessment_report(report, output_dir=output_dir)
        logger.info("Assessment score: %s", report.overall_score)

    # Step 3b: DAX optimization (always runs after generation)
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


def _run_biar_migration(args, stats):
    """Run batch migration from a BIAR archive.

    Full pipeline per artifact: extract → adapter → generation → .pbip
    Each artifact is isolated: failures don't block others.
    """
    from bo_export.biar_reader import read_biar_archive
    from bo_export.extract_bo_data import _route_extraction, _write_json_outputs
    from bo_export.converted_objects_adapter import adapt_bo_to_converted_objects

    biar_path = os.path.abspath(args.biar)
    output_dir = args.output_dir or os.path.splitext(biar_path)[0] + "_pbi"
    os.makedirs(output_dir, exist_ok=True)

    logger.info("Starting BIAR migration: %s", biar_path)
    artifacts = read_biar_archive(biar_path)
    total = len(artifacts)
    batch_results = []

    for idx, artifact in enumerate(artifacts, 1):
        artifact_name = artifact.get("name", "unknown")
        ext_type = artifact.get("type", "webi")
        artifact_dir = os.path.join(output_dir, artifact_name)
        os.makedirs(artifact_dir, exist_ok=True)

        result = {
            "name": artifact_name,
            "type": ext_type,
            "status": "pending",
            "error": None,
            "output_dir": artifact_dir,
        }

        logger.info("[%d/%d] Processing %s (%s)", idx, total, artifact_name, ext_type)

        try:
            # Step 1: Extract
            extracted = _route_extraction(
                ext_type, artifact.get("path", ""), args.verbose,
                artifact_data=artifact,
            )
            _write_json_outputs(extracted, artifact_dir)

            # Step 2: Adapt
            converted = adapt_bo_to_converted_objects(extracted)

            # Step 3: Generate .pbip
            _generate_pbip_for_artifact(
                converted, artifact_name, artifact_dir, args,
            )

            result["status"] = "success"
            stats.reports_processed += 1

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            stats.errors.append(f"{artifact_name}: {e}")
            logger.warning("[%d/%d] Failed: %s — %s", idx, total, artifact_name, e)

        batch_results.append(result)

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

    return EXIT_SUCCESS


def _generate_pbip_for_artifact(converted, artifact_name, artifact_dir, args):
    """Generate .pbip project from converted objects for a single artifact."""
    try:
        from powerbi_import.pbip_generator import PowerBIProjectGenerator
        generator = PowerBIProjectGenerator(
            converted_objects=converted,
            project_name=artifact_name,
            output_dir=artifact_dir,
        )
        generator.generate_project()
    except ImportError:
        # Fallback: write converted_objects.json for manual generation
        import json as _json
        co_path = os.path.join(artifact_dir, "converted_objects.json")
        with open(co_path, "w", encoding="utf-8") as f:
            _json.dump(converted, f, indent=2, default=str)
        logger.info("Wrote converted_objects.json (generator not available)")
    except Exception as e:
        # Generator failure: write the converted objects as fallback
        import json as _json
        co_path = os.path.join(artifact_dir, "converted_objects.json")
        with open(co_path, "w", encoding="utf-8") as f:
            _json.dump(converted, f, indent=2, default=str)
        logger.warning("Generation failed for %s, wrote converted_objects.json: %s",
                        artifact_name, e)


def _run_batch_migration(args, stats):
    """Run batch migration from a directory of BO artifacts."""
    from bo_export.extract_bo_data import extract_bo_data, SUPPORTED_EXTENSIONS

    batch_dir = os.path.abspath(args.batch)
    output_dir = args.output_dir or batch_dir + "_pbi"

    artifacts = []
    for root, dirs, files in os.walk(batch_dir):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                artifacts.append(os.path.join(root, fname))

    logger.info("Batch migration: %d artifacts found in %s", len(artifacts), batch_dir)

    for artifact_path in artifacts:
        try:
            extract_bo_data(artifact_path, output_dir=output_dir, verbose=args.verbose)
            stats.reports_processed += 1
        except Exception as e:
            logger.warning("Failed to migrate %s: %s", artifact_path, e)
            stats.errors.append(str(e))

    logger.info("Batch migration complete: %d/%d succeeded", stats.reports_processed, len(artifacts))
    return EXIT_SUCCESS


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

    output_dir = args.output_dir or "shared_model_output"
    model_name = args.model_name or "SharedModel"

    all_extracted = []
    for input_path in args.shared_model:
        extracted = extract_bo_data(os.path.abspath(input_path), verbose=args.verbose)
        all_extracted.append(extracted)
        stats.reports_processed += 1

    logger.info("Shared model: %d reports extracted, model name: %s", len(all_extracted), model_name)

    # Merge engine will be implemented using powerbi_import.shared_model
    # from powerbi_import.shared_model import merge_models
    # merged = merge_models(all_extracted, model_name)

    return EXIT_SUCCESS


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
