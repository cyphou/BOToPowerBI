"""Behavior-focused tests for deployment safety and governance reporting."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from powerbi_import.deploy.bundle_deployer import (
    BundleDeployer,
    BundleDeploymentResult,
)
from powerbi_import.deploy.multi_tenant import (
    MultiTenantConfig,
    MultiTenantDeploymentResult,
    TenantConfig,
    TenantDeploymentResult,
    _apply_connection_overrides,
    deploy_multi_tenant,
)
from powerbi_import.governance import (
    AuditTrail,
    GovernanceEngine,
    run_governance,
)
from powerbi_import import telemetry_dashboard as dashboard


VALID_WORKSPACE = "12345678-1234-1234-1234-123456789abc"


class TestMultiTenantConfiguration(unittest.TestCase):
    def test_empty_configuration_is_invalid(self):
        self.assertEqual(MultiTenantConfig().validate(), ["No tenants configured"])

    def test_tenant_requires_name_and_guid_workspace(self):
        config = MultiTenantConfig([TenantConfig("", "not-a-guid")])
        errors = config.validate()
        self.assertTrue(any("Tenant name is required" in error for error in errors))
        self.assertTrue(any("not a valid GUID" in error for error in errors))

    def test_duplicate_names_and_workspaces_are_reported(self):
        config = MultiTenantConfig([
            TenantConfig("North", VALID_WORKSPACE),
            TenantConfig("North", VALID_WORKSPACE),
        ])
        errors = config.validate()
        self.assertTrue(any("Duplicate tenant name" in error for error in errors))
        self.assertTrue(any("Duplicate workspace_id" in error for error in errors))

    def test_load_and_save_round_trip_preserves_overrides_and_rls(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "tenants.json"
            config = MultiTenantConfig([TenantConfig(
                "North", VALID_WORKSPACE,
                {"${TENANT_SERVER}": "north.example"},
                {"RegionManager": ["analyst@example.test"]},
            )])
            config.save(str(path))
            loaded = MultiTenantConfig.load(str(path))
        self.assertEqual(loaded.tenants[0].name, "North")
        self.assertEqual(loaded.tenants[0].connection_overrides,
                         {"${TENANT_SERVER}": "north.example"})
        self.assertEqual(loaded.tenants[0].rls_mappings,
                         {"RegionManager": ["analyst@example.test"]})
        self.assertEqual(loaded.validate(), [])

    def test_load_rejects_missing_file_and_invalid_structures(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.json"
            with self.assertRaises(FileNotFoundError):
                MultiTenantConfig.load(str(missing))
            for raw in ("[]", "{}", '{"tenants": {}}', '{"tenants": [3]}'):
                path = Path(temporary) / "config.json"
                path.write_text(raw, encoding="utf-8")
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    MultiTenantConfig.load(str(path))

    def test_load_rejects_files_over_one_megabyte(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "large.json"
            path.write_text(" " * 1_048_577, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "1 MB"):
                MultiTenantConfig.load(str(path))

    def test_connection_overrides_apply_to_supported_local_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            target = Path(temporary) / "target"
            source.mkdir()
            (source / "model.tmdl").write_text("server = '${SERVER}'", encoding="utf-8")
            (source / "query.m").write_text('Source="${SERVER}"', encoding="utf-8")
            (source / "settings.json").write_text('{"server":"${SERVER}"}', encoding="utf-8")
            (source / "ignored.txt").write_text("${SERVER}", encoding="utf-8")
            _apply_connection_overrides(str(source), {"${SERVER}": "tenant"}, str(target))
            self.assertIn("tenant", (target / "model.tmdl").read_text(encoding="utf-8"))
            self.assertIn("tenant", (target / "query.m").read_text(encoding="utf-8"))
            self.assertIn("tenant", (target / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual((target / "ignored.txt").read_text(encoding="utf-8"), "${SERVER}")
            self.assertTrue((source / "model.tmdl").read_text(encoding="utf-8").find("${SERVER}") >= 0)

    def test_connection_overrides_escape_values_for_json_m_and_tmdl(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            target = Path(temporary) / "target"
            source.mkdir()
            (source / "a.json").write_text('{"v":"${VALUE}"}', encoding="utf-8")
            (source / "a.m").write_text('v="${VALUE}"', encoding="utf-8")
            (source / "a.tmdl").write_text("v = '${VALUE}'", encoding="utf-8")
            _apply_connection_overrides(
                str(source), {"${VALUE}": 'a"b\\c'}, str(target))
            self.assertEqual(json.loads((target / "a.json").read_text(encoding="utf-8")),
                             {"v": 'a"b\\c'})
            self.assertIn('a""b\\c', (target / "a.m").read_text(encoding="utf-8"))
            self.assertIn("a\"b\\c", (target / "a.tmdl").read_text(encoding="utf-8"))

    def test_invalid_placeholders_are_not_substituted(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            target = Path(temporary) / "target"
            source.mkdir()
            (source / "model.tmdl").write_text("${bad_name} ${GOOD}", encoding="utf-8")
            _apply_connection_overrides(
                str(source), {"${bad_name}": "unsafe", "${GOOD}": "ok"}, str(target))
            self.assertEqual((target / "model.tmdl").read_text(encoding="utf-8"),
                             "${bad_name} ok")

    def test_control_characters_in_override_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            target = Path(temporary) / "target"
            source.mkdir()
            (source / "model.m").write_text("${SERVER}", encoding="utf-8")
            for value in ("bad\x00value", "bad\x01value"):
                with self.subTest(value=repr(value)), self.assertRaisesRegex(ValueError, "control"):
                    _apply_connection_overrides(
                        str(source), {"${SERVER}": value}, str(target))

    def test_deploy_rejects_invalid_config_before_creating_deployments(self):
        with patch("powerbi_import.deploy.bundle_deployer.BundleDeployer") as factory:
            result = deploy_multi_tenant("missing", MultiTenantConfig())
        factory.assert_not_called()
        self.assertEqual(result.total_count, 0)

    def test_deploy_isolates_tenant_failures_and_summarizes_results(self):
        class FakeBundle:
            def __init__(self, workspace_id):
                self.workspace_id = workspace_id

            def deploy_bundle(self, **kwargs):
                if self.workspace_id.endswith("abc"):
                    raise RuntimeError("local deploy failed")
                return Mock(success=True, model_id="model-2", deployed_count=2,
                            model_error=None)

        config = MultiTenantConfig([
            TenantConfig("First", VALID_WORKSPACE),
            TenantConfig("Second", "abcdefab-cdef-abcd-efab-cdefabcdefab"),
        ])
        with tempfile.TemporaryDirectory() as temporary, \
                patch("powerbi_import.deploy.bundle_deployer.BundleDeployer", FakeBundle):
            model = Path(temporary) / "Model.SemanticModel"
            model.mkdir()
            result = deploy_multi_tenant(str(model), config, refresh=True)
        self.assertEqual((result.success_count, result.failed_count, result.total_count), (1, 1, 2))
        self.assertIn("local deploy failed", result.results[0].error)
        self.assertEqual(result.results[1].model_id, "model-2")
        self.assertEqual(result.to_dict()["succeeded"], 1)
        self.assertIn('"failed": 1', result.to_json())

    def test_result_serialization_and_summary_cover_success_and_failure(self):
        result = MultiTenantDeploymentResult([
            TenantDeploymentResult("North", VALID_WORKSPACE, success=True, model_id="m1"),
            TenantDeploymentResult("South", "abcdefab-cdef-abcd-efab-cdefabcdefab",
                                  error="blocked"),
        ])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "result.json"
            result.save(str(path))
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["total"], 2)
        self.assertEqual(saved["tenants"][1]["error"], "blocked")
        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.failed_count, 1)


class TestGovernanceEngine(unittest.TestCase):
    def test_warn_mode_reports_naming_and_pii_without_renaming(self):
        tables = [{"name": "sales table", "columns": [{"name": "Email Address"}],
                   "measures": [{"name": "Total Sales"}]}]
        report = run_governance(tables, {
            "mode": "warn",
            "naming": {"table_style": "PascalCase", "column_style": "snake_case",
                       "measure_prefix": "m_"},
        })
        self.assertGreaterEqual(report.warn_count, 3)
        self.assertEqual(tables[0]["name"], "sales table")
        self.assertEqual(tables[0]["measures"][0]["name"], "Total Sales")
        self.assertEqual(report.classifications["sales table.Email Address"], "email")
        engine = GovernanceEngine({"mode": "warn", "naming": {"measure_prefix": "m_"}})
        tables = [{"name": "Facts", "measures": [{"name": "Sales"}]}]
        warn_report = engine.check(tables)
        self.assertEqual(engine.apply_renames(tables, warn_report), 0)
        self.assertEqual(tables[0]["measures"][0]["name"], "Sales")

    def test_enforce_mode_applies_table_column_and_measure_renames(self):
        tables = [{"name": "sales table", "columns": [{"name": "Customer Email"}],
                   "measures": [{"name": "Total Sales"}]}]
        report = run_governance(tables, {
            "mode": "enforce",
            "naming": {"table_style": "PascalCase", "column_style": "snake_case",
                       "measure_prefix": "m_"},
        })
        self.assertEqual(tables[0]["name"], "SalesTable")
        self.assertEqual(tables[0]["columns"][0]["name"], "customer_email")
        self.assertEqual(tables[0]["measures"][0]["name"], "m_Total Sales")
        self.assertGreaterEqual(report.fail_count, 2)
        self.assertEqual(report.classifications["sales table.Customer Email"], "email")

    def test_pii_detection_classifies_first_matching_pattern(self):
        report = GovernanceEngine().check([{"name": "People", "columns": [
            "email", "SSN", "phone_number", "date_of_birth", "credit_card_number",
            "ip_address", "passport_number", "postal_code",
        ]}])
        expected = {"People.email": "email", "People.SSN": "ssn",
                    "People.phone_number": "phone", "People.date_of_birth": "dateOfBirth",
                    "People.credit_card_number": "creditCard",
                    "People.ip_address": "ipAddress", "People.passport_number": "passport",
                    "People.postal_code": "address"}
        self.assertEqual(report.classifications, expected)
        self.assertEqual(report.issue_count, len(expected))

    def test_disabled_pii_detection_does_not_add_classifications(self):
        report = GovernanceEngine({"pii_detection": False}).check([
            {"name": "People", "columns": ["email"]}])
        self.assertEqual(report.classifications, {})
        self.assertEqual(report.issues, [])

    def test_enforce_annotations_preserve_existing_annotations(self):
        tables = [{"name": "People", "columns": [{"name": "email", "annotations": [
            {"name": "existing", "value": "kept"}]}]}]
        report = run_governance(tables, {"mode": "enforce"})
        self.assertEqual([a["name"] for a in tables[0]["columns"][0]["annotations"]],
                         ["existing", "dataClassification"])
        self.assertEqual(report.classifications["People.email"], "email")

    def test_sensitivity_label_uses_highest_known_precedence(self):
        engine = GovernanceEngine()
        self.assertEqual(engine.map_sensitivity_label(["Viewer", "Editor"]), "Confidential")
        self.assertEqual(engine.map_sensitivity_label(["Editor", "Project Leader"]),
                         "Highly Confidential")
        self.assertEqual(engine.map_sensitivity_label(["unknown"]), "General")
        self.assertEqual(engine.map_sensitivity_label([]), "General")

    def test_run_governance_applies_sensitivity_label_and_report_counts(self):
        report = run_governance([], source_permissions=["Viewer", "Project Leader"])
        self.assertEqual(report.sensitivity_label, "Highly Confidential")
        self.assertEqual(report.to_dict()["issue_count"], 0)
        self.assertTrue(report.timestamp)

    def test_audit_trail_appends_reads_limits_and_skips_corrupt_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "audit.jsonl"
            trail = AuditTrail(str(path))
            first = trail.record(source_file="/local/private/report.wid", user="tester",
                                 workbook_name="Report", governance_summary={"issues": 1})
            trail.record(workbook_name="Second")
            self.assertEqual(trail.save(), 2)
            with path.open("a", encoding="utf-8") as stream:
                stream.write("not-json\n")
            entries = trail.read(limit=1)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["workbook"], "Second")
        self.assertEqual(first["source_file"], "report.wid")
        self.assertEqual(first["governance"], {"issues": 1})

    def test_audit_trail_hashes_files_and_directories_deterministically(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file_path = root / "a.txt"
            file_path.write_bytes(b"abc")
            first_dir_hash = AuditTrail.compute_dir_hash(str(root))
            self.assertEqual(AuditTrail.compute_file_hash(str(file_path)),
                             "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
            self.assertEqual(AuditTrail.compute_dir_hash(str(root)), first_dir_hash)
            self.assertEqual(AuditTrail.compute_file_hash(str(root / "missing")), "")
            self.assertEqual(AuditTrail.compute_dir_hash(str(root / "missing")), "")


class TestTelemetryDashboard(unittest.TestCase):
    def test_load_reports_skips_malformed_json_and_loads_nested_reports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = root / "nested" / "migration_report_1.json"
            good.parent.mkdir()
            good.write_text('{"workbook_name":"Sales"}', encoding="utf-8")
            (root / "migration_report_bad.json").write_text("{", encoding="utf-8")
            reports = dashboard._load_reports(str(root))
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["workbook_name"], "Sales")
        self.assertTrue(reports[0]["_file"].endswith("migration_report_1.json"))

    def test_load_telemetry_skips_corrupt_jsonl_and_missing_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_text('{"session_id":"one"}\ninvalid\n\n{"session_id":"two"}\n',
                            encoding="utf-8")
            entries = dashboard._load_telemetry_events(str(path))
            missing = dashboard._load_telemetry_events(str(Path(temporary) / "missing"))
        self.assertEqual([entry["session_id"] for entry in entries], ["one", "two"])
        self.assertEqual(missing, [])

    def test_portfolio_progress_classifies_completed_partial_pending_and_invalid(self):
        progress = dashboard._compute_portfolio_progress([
            {"fidelity_score": 80}, {"overall_fidelity": "42"},
            {"fidelity_score": 0}, {"fidelity_score": "bad"},
        ])
        self.assertEqual(progress, {"total": 4, "completed": 1, "partial": 1,
                                    "pending": 2, "pct_complete": 25.0})
        self.assertEqual(dashboard._compute_portfolio_progress([])["pct_complete"], 0)

    def test_bottlenecks_aggregate_failed_items_and_telemetry_errors(self):
        results = dashboard._analyze_bottlenecks(
            [{"items": [{"type": "visual", "status": "failed", "notes": "bad visual"},
                        {"kind": "query", "status": "partial"}]}],
            [{"errors": [{"category": "auth", "message": "denied"}]}],
        )
        self.assertEqual([(item["category"], item["count"]) for item in results],
                         [("visual", 1), ("query", 1), ("auth", 1)])
        self.assertEqual(results[-1]["status"], "error")
        self.assertEqual(results[-1]["sample_notes"], ["denied"])

    def test_generate_dashboard_writes_artifact_with_summary_and_escaped_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "migration_report_1.json").write_text(json.dumps({
                "workbook_name": '<img src=x onerror="alert(1)">',
                "fidelity_score": 90,
                "items": [{"type": "visual", "status": "failed", "notes": "unsupported feature"}],
            }), encoding="utf-8")
            log = root / "telemetry.jsonl"
            log.write_text(json.dumps({"session_id": "<session>", "duration_seconds": 4,
                                      "events": [{"name": "run"}], "errors": []}) + "\n",
                           encoding="utf-8")
            output = root / "reports" / "dashboard.html"
            returned = dashboard.generate_dashboard(str(root), str(output), str(log))
            html = output.read_text(encoding="utf-8")
        self.assertEqual(returned, str(output))
        self.assertIn("Migration Observability Dashboard", html)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", html)
        self.assertNotIn('<img src=x onerror="alert(1)">', html)
        self.assertIn("Portfolio Progress", html)
        self.assertIn("Bottleneck Analysis", html)
        self.assertIn("&lt;session&gt;", html)
        self.assertEqual(dashboard._esc('<script "x">'), "&lt;script &quot;x&quot;&gt;")
        self.assertEqual(dashboard._esc(""), "")
        self.assertEqual(dashboard._esc(None), "")

    def test_generate_empty_dashboard_uses_default_output_and_empty_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = dashboard.generate_dashboard(temporary, telemetry_log=str(Path(temporary) / "none"))
            html = Path(output).read_text(encoding="utf-8")
        self.assertTrue(output.endswith("telemetry_dashboard.html"))
        self.assertIn("No bottlenecks detected", html)
        self.assertIn("No telemetry data found", html)


class TestBundleDeployer(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.get.side_effect = lambda path: (
            {"role": "Contributor"} if path.endswith("/workspaces/ws") else [])
        self.deployer = BundleDeployer("ws", client=self.client)
        self.item_deployer = Mock()
        self.deployer._deployer = self.item_deployer

    @staticmethod
    def _project(root, model=True, reports=("Alpha", "Beta")):
        if model:
            definition = root / "Model.SemanticModel" / "definition"
            definition.mkdir(parents=True)
            (definition / "model.tmdl").write_text("model body", encoding="utf-8")
            (definition / "binary.bin").write_bytes(b"\x00\xff")
        for name in reports:
            definition = root / f"{name}.Report" / "definition"
            definition.mkdir(parents=True)
            (definition / "report.json").write_text('{"name":"report"}', encoding="utf-8")

    def test_discovery_and_definition_reading_use_local_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            model, model_name, reports = self.deployer.discover_artifacts(root)
            model_config = self.deployer._read_artifact_definition(model)
            report_config = self.deployer._read_artifact_definition(reports[0][1])
        self.assertEqual(model_name, "Model")
        self.assertEqual([name for name, _ in reports], ["Alpha", "Beta"])
        self.assertEqual(model_config["definition"]["model.tmdl"], "model body")
        self.assertEqual(model_config["definition"]["binary.bin"], "00ff")
        self.assertEqual(report_config["displayName"], "Alpha")

    def test_missing_project_raises_and_missing_model_returns_without_client_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):
                self.deployer.deploy_bundle(str(Path(temporary) / "missing"))
            result = self.deployer.deploy_bundle(temporary)
        self.assertEqual(result.model_status, "not_found")
        self.client.get.assert_not_called()
        self.item_deployer.deploy_dataset.assert_not_called()
        self.client.post.assert_not_called()
        self.client.delete.assert_not_called()

    def test_permission_gate_prevents_all_deployment_or_mutating_calls(self):
        self.client.get.side_effect = lambda path: {"role": "Viewer"} if path.endswith("/ws") else []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            result = self.deployer.deploy_bundle(str(root))
        self.assertEqual(result.model_status, "failed")
        self.assertIn("Permission check failed", result.model_error)
        self.item_deployer.deploy_dataset.assert_not_called()
        self.client.post.assert_not_called()
        self.client.delete.assert_not_called()

    def test_conflict_gate_prevents_deployment_unless_overwrite_is_enabled(self):
        self.client.get.side_effect = lambda path: (
            {"role": "Member"} if path.endswith("/ws") else
            [{"displayName": "Model", "id": "existing", "type": "SemanticModel"}])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            result = self.deployer.deploy_bundle(str(root))
        self.assertEqual(result.model_status, "failed")
        self.assertEqual(result.conflicts[0]["existing_id"], "existing")
        self.assertIn("overwrite=True", result.model_error)
        self.item_deployer.deploy_dataset.assert_not_called()
        self.client.post.assert_not_called()
        self.client.delete.assert_not_called()

    def test_report_filter_deploys_only_requested_report_and_rebinds(self):
        self.item_deployer.deploy_dataset.return_value = {"id": "model-id"}
        self.item_deployer.deploy_report.return_value = {"id": "report-id"}
        self.item_deployer.get_deployment_status.return_value = {"status": "Succeeded"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            result = self.deployer.deploy_bundle(str(root), report_filter=["Beta"])
        self.assertTrue(result.success)
        self.item_deployer.deploy_report.assert_called_once()
        self.assertEqual(self.item_deployer.deploy_report.call_args.args[1], "Beta")
        self.client.post.assert_called_once_with(
            "/workspaces/ws/reports/report-id/Rebind", data={"datasetId": "model-id"})
        self.assertEqual(result.refresh_status, "skipped")
        self.assertEqual(result.validation[0]["status"], "ok")

    def test_report_deployment_failure_isolated_from_other_reports(self):
        self.item_deployer.deploy_dataset.return_value = {"id": "model-id"}
        self.item_deployer.deploy_report.side_effect = [RuntimeError("bad report"), {"id": "good-id"}]
        self.item_deployer.get_deployment_status.return_value = {"status": "Succeeded"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            result = self.deployer.deploy_bundle(str(root))
        self.assertEqual([report["status"] for report in result.reports], ["failed", "deployed"])
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(result.deployed_count, 1)
        self.assertEqual(self.client.post.call_count, 1)
        self.assertTrue(result.success)

    def test_model_failure_stops_report_deployment(self):
        self.item_deployer.deploy_dataset.side_effect = RuntimeError("model blocked")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            result = self.deployer.deploy_bundle(str(root))
        self.assertEqual(result.model_status, "failed")
        self.assertEqual(result.model_error, "model blocked")
        self.item_deployer.deploy_report.assert_not_called()
        self.client.post.assert_not_called()

    def test_rebind_failure_marks_report_unbound_without_claiming_success(self):
        self.item_deployer.deploy_dataset.return_value = {"id": "model-id"}
        self.item_deployer.deploy_report.return_value = {"id": "report-id"}
        self.client.post.side_effect = RuntimeError("rebind denied")
        self.item_deployer.get_deployment_status.return_value = {"status": "Succeeded"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, reports=("Alpha",))
            result = self.deployer.deploy_bundle(str(root))
        self.assertEqual(result.reports[0]["status"], "deployed_unbound")
        self.assertEqual(result.reports[0]["rebind"], "failed")
        self.assertFalse(result.success)
        self.assertEqual(result.validation, [{"check": "model_status", "status": "ok",
                             "detail": "Succeeded"}])

    def test_rollback_deletes_only_successfully_deployed_items_after_report_failure(self):
        self.item_deployer.deploy_dataset.return_value = {"id": "model-id"}
        self.item_deployer.deploy_report.side_effect = [{"id": "report-id"}, RuntimeError("failed")]
        self.item_deployer.get_deployment_status.return_value = {"status": "Succeeded"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            result = self.deployer.deploy_bundle(str(root), enable_rollback=True)
        self.assertEqual(self.client.delete.call_args_list, [
            call("/workspaces/ws/items/model-id"),
            call("/workspaces/ws/items/report-id"),
        ])
        self.assertEqual([entry["status"] for entry in result.rollback_actions],
                         ["success", "success"])

    def test_refresh_trigger_and_poll_status_are_mocked_and_recorded(self):
        self.item_deployer.deploy_dataset.return_value = {"id": "model-id"}
        self.item_deployer.get_deployment_status.return_value = {"status": "Succeeded"}
        self.client.get.side_effect = lambda path: (
            {"role": "Contributor"} if path.endswith("/ws") else
            [] if path.endswith("/items") else
            {"value": [{"status": "Completed"}]})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, reports=())
            result = self.deployer.deploy_bundle(str(root), refresh=True)
        self.assertEqual(result.refresh_status, "completed")
        self.assertEqual(self.client.post.call_args,
                         call("/workspaces/ws/datasets/model-id/refreshes", data={"type": "Full"}))
        self.assertEqual(self.client.delete.call_count, 0)

    def test_refresh_trigger_failure_is_reported_without_real_refresh(self):
        self.item_deployer.deploy_dataset.return_value = {"id": "model-id"}
        self.item_deployer.get_deployment_status.return_value = {"status": "Succeeded"}
        self.client.post.side_effect = RuntimeError("refresh denied")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, reports=())
            result = self.deployer.deploy_bundle(str(root), refresh=True)
        self.assertEqual(result.refresh_status, "failed")
        self.assertEqual(result.refresh_error, "refresh denied")
        self.client.delete.assert_not_called()

    def test_result_report_save_and_summary_reflect_deployment_state(self):
        result = BundleDeploymentResult("project", "ws")
        result.model_status = "deployed"
        result.model_name = "Model"
        result.model_id = "model-id"
        result.reports = [{"name": "Alpha", "status": "deployed", "id": "report-id"}]
        result.end_time = result.start_time
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "result.json"
            result.save(path)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(result.success)
        self.assertEqual(saved["reports_deployed"], 1)
        self.assertEqual(saved["duration_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
