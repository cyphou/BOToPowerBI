"""Subprocess and artifact tests for the local SAP BW BEx PBIP CLI."""

import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from powerbi_import.validator import ArtifactValidator

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "migrate_bw_bex_pbip.py"
FIXTURE = ROOT / "docs" / "fixtures" / "sap_bw_bex_pbip_plan.example.json"
PROPERTY_FIXTURE = ROOT / "docs" / "fixtures" / "sap_bw_bex_pbip_properties.example.json"
SCHEMA = ROOT / "docs" / "schemas" / "sap_bw_bex_pbip_plan.schema.json"


class TestMigrateBWBExPBIP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def _run_cli(self, plan, output_dir, work_dir, inventory=None, semantics=None):
        plan_path = Path(work_dir) / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        command = [
            sys.executable,
            str(CLI),
            "--plan",
            str(plan_path),
            "--output-dir",
            str(output_dir),
        ]
        if inventory is not None:
            inventory_path = Path(work_dir) / "inventory.json"
            semantics_path = Path(work_dir) / "semantics.json"
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
            semantics_path.write_text(json.dumps(semantics), encoding="utf-8")
            command.extend(["--inventory", str(inventory_path), "--semantics", str(semantics_path)])
        return subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def _linked_plan_and_evidence(self):
        plan = copy.deepcopy(self.fixture)
        navigation = plan["datasource"]["tables"][0]["sap_bw_navigation"]
        navigation["measures"][0]["selector"] = "[Measures].[Net sales amount]"
        query_id = "SYNTHETIC-BW-01:BEX:VENTES-MENSUELLES"
        provider_id = "SYNTHETIC-BW-01:ADSO:VENTES-AGRÉGÉES"
        plan["schema_version"] = "1.2"
        plan["bex_linkage"] = {
            "query_id": query_id,
            "provider_id": provider_id,
            "cube_id": navigation["cube_id"],
            "dimension_bindings": [{
                "selector": "[0CALDAY]",
                "provider_dimension_name": "Calendar day",
            }],
            "key_figure_bindings": [{
                "key_figure_id": "synthetic-net-sales",
                "selector": "[Measures].[Net sales amount]",
                "column": "Quantity",
            }],
        }

        inventory = json.loads(
            (ROOT / "docs" / "fixtures" / "sap_bw_inventory.partial.example.json")
            .read_text(encoding="utf-8")
        )
        inventory["scope"]["completeness"] = "complete"
        inventory["scope"]["owner_signoff"] = "accepted"
        inventory["scope"]["known_gaps"] = []
        inventory["scope"]["coverage"] = {
            key: "not_applicable" if key == "planning_writeback" else "complete"
            for key in inventory["scope"]["coverage"]
        }
        inventory["discovery"].update({
            "method": "source_export",
            "evidence_reference": "synthetic-owner-export",
        })
        inventory["provenance"].update({
            "discovery_method": "source_export",
            "extraction_method": "source_export",
            "evidence_reference": "synthetic-owner-export",
        })
        inventory["source_system"]["landscape"]["status"] = "observed"
        inventory["unknowns"] = []
        inventory["errors"] = []
        inventory["unsupported_features"] = []
        for item in inventory["objects"]:
            if item["disposition"] == "in_scope":
                item["discovery_status"] = "observed"
                item["business_owner"] = "synthetic-owner"
                if item["criticality"] == "unknown":
                    item["criticality"] = "medium"
        digest = hashlib.sha256(b"synthetic BEx query definition").hexdigest()
        query = next(item for item in inventory["objects"] if item["id"] == query_id)
        query["migration_decision"]["classification"] = "not_assessed"
        query["definition"].update({
            "status": "observed",
            "reference": "synthetic://definitions/bex/ventes-mensuelles",
            "hash_algorithm": "sha256",
            "hash": digest,
        })
        provider = next(item for item in inventory["objects"] if item["id"] == provider_id)
        provider["type"] = "infocube"
        provider["metadata_status"] = "observed"
        provider["keys_status"] = "observed"
        provider["keys"] = [{
            "name": "Sales document",
            "data_type": "STRING",
            "nullable": False,
            "role": "business",
        }]
        provider["semantics"] = {
            "status": "observed",
            "measures": [{
                "name": "Net sales amount",
                "data_type": "DECIMAL(15,2)",
                "status": "observed",
                "details": None,
            }],
            "dimensions": [{
                "name": "Calendar day",
                "data_type": "DATE",
                "status": "observed",
                "details": None,
            }],
            "functions": [],
        }
        semantics = {
            "schema_version": "1.1",
            "query": {
                "object_id": query_id,
                "definition_reference": "synthetic://definitions/bex/ventes-mensuelles",
                "definition_sha256": digest,
            },
            "coverage": {
                "variables": "not_applicable",
                "filters": "not_applicable",
                "hierarchies": "not_applicable",
                "master_data": "not_applicable",
                "key_figures": "complete",
                "exception_aggregation": "complete",
                "units_currencies": "complete",
                "authorization_contexts": "not_applicable",
                "consumers": "complete",
            },
            "variables": [],
            "filters": [],
            "hierarchies": [],
            "master_data": [],
            "key_figures": [{
                "id": "synthetic-net-sales",
                "name": "Net sales",
                "aggregation": "sum",
                "exception_aggregation": {
                    "status": "not_applicable",
                    "method": None,
                    "reference_characteristic": None,
                },
                "unit_currency": {
                    "status": "observed",
                    "unit": None,
                    "currency": "EUR",
                    "conversion_reference": "synthetic://currency/eur",
                },
                "status": "observed",
                "evidence_reference": "synthetic://evidence/key-figure",
            }],
            "authorization_contexts": [],
            "consumers": [{
                "inventory_object_id": "SYNTHETIC-BW-01:CONSUMER:RAPPORT-VENTES",
                "target_candidate_reference": "synthetic://target/powerbi/sales-report",
                "acceptance_status": "not_run",
                "evidence_reference": "synthetic://evidence/consumer-link",
            }],
            "provider_key_figure_bindings": [{
                "key_figure_id": "synthetic-net-sales",
                "provider_id": provider_id,
                "provider_measure_name": "Net sales amount",
                "status": "observed",
                "evidence_reference": "synthetic://evidence/key-figure-binding",
            }],
        }
        return plan, inventory, semantics

    def _assert_invalid_plan_rejected_without_output(self, plan):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(plan, output_dir, temporary)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("SAP BW PBIP generation failed:", result.stderr)
            self.assertFalse(output_dir.exists())

    def test_fixture_and_schema_declare_the_strict_single_cube_plan(self):
        schema = self.schema
        self.assertEqual(schema["$id"], "urn:bo-to-powerbi:schema:sap-bw-bex-pbip-plan:1.6")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]),
            {"schema_version", "project_name", "datasource"},
        )
        self.assertEqual(
            set(schema["properties"]),
            {"schema_version", "project_name", "datasource", "bex_linkage", "review_report"},
        )
        self.assertEqual(
            schema["properties"]["schema_version"]["enum"],
            ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"],
        )
        dimension_binding_schema = schema["$defs"]["dimensionBinding"]
        self.assertEqual(
            set(dimension_binding_schema["required"]),
            {"selector", "provider_dimension_name"},
        )
        dimension_binding_requirement = schema["allOf"][1]
        self.assertEqual(
            dimension_binding_requirement["if"]["properties"]["schema_version"]["enum"],
            ["1.2", "1.3", "1.4", "1.5", "1.6"],
        )
        self.assertEqual(
            dimension_binding_requirement["then"]["properties"]["bex_linkage"]["required"],
            ["dimension_bindings"],
        )
        self.assertEqual(
            set(schema["$defs"]["dimensionProperty"]["required"]),
            {"source_column", "selector", "column"},
        )
        self.assertEqual(
            schema["allOf"][2]["if"]["properties"]["schema_version"]["enum"],
            ["1.0", "1.1", "1.2"],
        )
        datasource_schema = schema["$defs"]["datasource"]
        self.assertFalse(datasource_schema["additionalProperties"])
        self.assertEqual(datasource_schema["properties"]["tables"]["maxItems"], 1)
        connection_schema = schema["$defs"]["connection"]
        self.assertFalse(connection_schema["additionalProperties"])
        self.assertEqual(
            connection_schema["properties"]["type"]["const"],
            "sap_bw",
        )
        project_name_schema = schema["$defs"]["projectName"]
        self.assertEqual(project_name_schema["type"], "string")
        self.assertGreaterEqual(project_name_schema["minLength"], 1)
        self.assertIsNotNone(
            re.fullmatch(project_name_schema["pattern"], self.fixture["project_name"])
        )
        self.assertEqual(self.fixture["schema_version"], "1.0")
        self.assertEqual(len(self.fixture["datasource"]["tables"]), 1)
        self.assertEqual(
            set(self.fixture["datasource"]["tables"][0]["columns"][index]["name"]
                for index in range(2)),
            {"Calendar day", "Quantity"},
        )

    def test_schema_project_name_constraints_are_rejected_before_output(self):
        project_name_schema = self.schema["$defs"]["projectName"]
        invalid_names = (
            "",
            "Synthetic/BW",
            "CON",
            "con.txt",
            "LPT9.txt",
            "Synthetic.",
            " Synthetic",
            "Synthetic ",
        )
        for invalid_name in invalid_names:
            with self.subTest(project_name=invalid_name):
                self.assertIsNone(
                    re.fullmatch(project_name_schema["pattern"], invalid_name)
                )
                plan = copy.deepcopy(self.fixture)
                plan["project_name"] = invalid_name
                self._assert_invalid_plan_rejected_without_output(plan)

    def test_server_uri_userinfo_is_rejected_before_output(self):
        server_not_pattern = self.schema["$defs"]["server"]["allOf"][1]["not"]["pattern"]
        for server in (
            "sap://synthetic-user:synthetic-secret@synthetic-bw.invalid",
            "https://synthetic-user:synthetic-secret@synthetic-bw.invalid",
        ):
            with self.subTest(server=server):
                self.assertIsNotNone(re.search(server_not_pattern, server))
                plan = copy.deepcopy(self.fixture)
                plan["datasource"]["connection"]["server"] = server
                self._assert_invalid_plan_rejected_without_output(plan)

    def test_cli_generates_valid_import_pbip_for_synthetic_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(self.fixture, output_dir, temporary)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("statically validated", result.stdout)
            self.assertIn("SAP access", result.stdout)
            project = output_dir / self.fixture["project_name"]
            semantic_model = project / f'{self.fixture["project_name"]}.SemanticModel'
            report_dir = project / f'{self.fixture["project_name"]}.Report'
            self.assertTrue((project / f'{self.fixture["project_name"]}.pbip').is_file())
            self.assertTrue((semantic_model / "definition" / "model.tmdl").is_file())
            self.assertTrue(report_dir.is_dir())
            metadata = json.loads((project / "migration_metadata.json").read_text(
                encoding="utf-8"
            ))
            self.assertEqual(metadata["source"], "SAP BW declared cube plan")
            self.assertEqual(metadata["generated_output"]["visuals"], 0)
            capability_boundary = metadata["sap_bw_capability_boundary"]
            self.assertEqual(capability_boundary["schema_version"], "1.0")
            self.assertEqual(
                capability_boundary["scope"],
                "repository_capability_boundary_not_generated_target_functionality",
            )
            functional = {
                item["capability"]: item["status"]
                for item in capability_boundary["functional_capabilities"]
            }
            technical = {
                item["object"]: item["status"]
                for item in capability_boundary["technical_objects"]
            }
            self.assertEqual(functional["copy_version"], "not_implemented")
            self.assertEqual(functional["planning_reporting"], "partial")
            self.assertEqual(technical["infocube"], "partial")
            self.assertEqual(technical["multiprovider"], "not_implemented")
            self.assertEqual(
                technical["bex_query_fiori_dashboard"],
                "assessment_and_review_only",
            )
            self.assertTrue(
                all(
                    status == "not_run"
                    for status in capability_boundary["runtime_evidence"].values()
                )
            )

            model_table = (
                semantic_model / "definition" / "tables" / "Sales.tmdl"
            ).read_text(encoding="utf-8")
            self.assertIn("mode: import", model_table)
            self.assertIn("SapBusinessWarehouse.Cubes(", model_table)
            self.assertIn('InfoArea{[Id="$0D_DECU"]}[Data]', model_table)
            self.assertIn(
                '{Cube.AddMeasureColumn, "Quantity", "[Measures].[0D_INV_QTY]"}',
                model_table,
            )
            self.assertIn("sourceColumn: 'Calendar day'", model_table)
            self.assertIn("sourceColumn: Quantity", model_table)
            query = (project / "PowerQuery" / "Sales.pq").read_text(encoding="utf-8")
            self.assertIn('InfoArea{[Id="$0D_DECU"]}[Data]', query)
            self.assertIn('{Cube.AddMeasureColumn, "Quantity", "[Measures].[0D_INV_QTY]"}', query)
            self.assertFalse((project / "DAX").exists())
            export_manifest = json.loads(
                (project / "expression_export.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                {"path": "PowerQuery/Sales.pq", "source": "tables/Sales.tmdl",
                 "kind": "m_partition"},
                export_manifest["exports"],
            )

            pbip = json.loads(
                (project / f'{self.fixture["project_name"]}.pbip').read_text(encoding="utf-8")
            )
            report_reference = pbip["artifacts"][0]["report"]["path"]
            pbir = json.loads((project / report_reference / "definition.pbir").read_text(
                encoding="utf-8"
            ))
            self.assertEqual(
                pbir["datasetReference"]["byPath"]["path"],
                f'../{self.fixture["project_name"]}.SemanticModel',
            )
            validation = ArtifactValidator.validate_project(project)
            self.assertTrue(validation["valid"], validation["errors"])

    def test_explicit_review_table_preserves_column_bindings_order_and_layout(self):
        plan = copy.deepcopy(self.fixture)
        plan["schema_version"] = "1.6"
        table = plan["datasource"]["tables"][0]
        table["name"] = "Cube d'\u00e9t\u00e9"
        special_column = "sum:R\u00e9gion [O'Brien] / 20%"
        table["columns"][0]["name"] = special_column
        dimension = table["sap_bw_navigation"]["dimensions"][0]
        dimension["columns"][0] = special_column
        extra_columns = [f"Attribute {index:02}" for index in range(10)]
        for index, name in enumerate(extra_columns):
            table["columns"].append({"name": name, "datatype": "string"})
            dimension["attributes"].append(f"[0CALDAY].[EXTRA{index:02}]")
            dimension["columns"].append(name)
        requested_columns = ["Quantity", special_column, *extra_columns]
        plan["review_report"] = {
            "page_name": "V\u00e9rification BW",
            "columns": requested_columns,
        }

        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(plan, output_dir, temporary)
            self.assertEqual(result.returncode, 0, result.stderr)
            project = output_dir / plan["project_name"]
            report = project / f'{plan["project_name"]}.Report'
            pages_dir = report / "definition" / "pages"
            pages = json.loads((pages_dir / "pages.json").read_text(encoding="utf-8"))
            self.assertEqual(len(pages["pageOrder"]), 1)
            page_id = pages["pageOrder"][0]
            self.assertEqual(pages["activePageName"], page_id)
            page_dir = pages_dir / page_id
            page = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
            self.assertEqual(page["displayName"], plan["review_report"]["page_name"])
            visuals = list((page_dir / "visuals").rglob("visual.json"))
            self.assertEqual(len(visuals), 1)
            visual = json.loads(visuals[0].read_text(encoding="utf-8"))
            self.assertEqual(visual["visual"]["visualType"], "tableEx")
            position = visual["position"]
            self.assertGreaterEqual(position["x"], 0)
            self.assertGreaterEqual(position["y"], 0)
            self.assertGreater(position["width"], 0)
            self.assertGreater(position["height"], 0)
            self.assertLessEqual(position["x"] + position["width"], page["width"])
            self.assertLessEqual(position["y"] + position["height"], page["height"])
            projections = visual["visual"]["query"]["queryState"]["Values"]["projections"]
            self.assertEqual(
                [item["field"]["Column"]["Property"] for item in projections],
                requested_columns,
            )
            for item, name in zip(projections, requested_columns):
                self.assertEqual(set(item["field"]), {"Column"})
                column = item["field"]["Column"]
                self.assertEqual(column["Expression"]["SourceRef"]["Entity"], table["name"])
                self.assertEqual(item["nativeQueryRef"], name)
            self.assertEqual(
                visual["visual"]["objects"]["total"][0]["properties"]["totals"]
                ["expr"]["Literal"]["Value"],
                "false",
            )
            metadata = json.loads((project / "migration_metadata.json").read_text(
                encoding="utf-8"
            ))
            self.assertEqual(metadata["source"], "SAP BW declared cube plan")
            self.assertEqual(metadata["generated_output"]["visuals"], 1)
            self.assertEqual(metadata["objects_converted"]["worksheets"], 0)
            self.assertEqual(ArtifactValidator.validate_visual_references(project), [])
            validation = ArtifactValidator.validate_project(project)
            self.assertTrue(validation["valid"], validation["errors"])
            self.assertIn("Review table created on page", result.stdout)
            self.assertIn("review", result.stderr.lower())

            from powerbi_import.pbip_generator import PowerBIProjectGenerator

            generator = PowerBIProjectGenerator(str(output_dir))
            with self.assertRaisesRegex(ValueError, "empty generated report page"):
                generator.add_review_table(
                    project, plan["project_name"], "Other page", table["name"],
                    requested_columns,
                )
            self.assertEqual(
                json.loads(visuals[0].read_text(encoding="utf-8")),
                visual,
            )

    def test_generic_metadata_keeps_its_existing_source_by_default(self):
        from powerbi_import.pbip_generator import PowerBIProjectGenerator

        with tempfile.TemporaryDirectory() as temporary:
            generator = PowerBIProjectGenerator(temporary)
            generator.create_metadata(temporary, "Report", {})
            metadata = json.loads(
                (Path(temporary) / "migration_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["source"], "Tableau Migration")

    def test_review_table_requires_strict_explicit_model_columns(self):
        plan = copy.deepcopy(self.fixture)
        plan["schema_version"] = "1.6"
        plan["review_report"] = {
            "page_name": "BW review",
            "columns": ["Calendar day", "Quantity"],
        }
        for mutation in (
            "old_version", "null_report", "extra_field", "missing_page", "blank_page",
            "empty_columns", "non_list", "duplicate", "unknown", "wrong_case",
            "non_text", "control_character",
        ):
            invalid = copy.deepcopy(plan)
            if mutation == "old_version":
                invalid["schema_version"] = "1.5"
            elif mutation == "null_report":
                invalid["review_report"] = None
            elif mutation == "extra_field":
                invalid["review_report"]["extra"] = "unexpected"
            elif mutation == "missing_page":
                del invalid["review_report"]["page_name"]
            elif mutation == "blank_page":
                invalid["review_report"]["page_name"] = " "
            elif mutation == "empty_columns":
                invalid["review_report"]["columns"] = []
            elif mutation == "non_list":
                invalid["review_report"]["columns"] = "Quantity"
            elif mutation == "duplicate":
                invalid["review_report"]["columns"] = ["Quantity", "Quantity"]
            elif mutation == "unknown":
                invalid["review_report"]["columns"] = ["Missing"]
            elif mutation == "wrong_case":
                invalid["review_report"]["columns"] = ["quantity"]
            elif mutation == "non_text":
                invalid["review_report"]["columns"] = [5]
            else:
                invalid["review_report"]["columns"] = ["Quantity\n"]
            with self.subTest(mutation=mutation):
                self._assert_invalid_plan_rejected_without_output(invalid)

    def test_version_1_6_without_review_table_keeps_empty_report(self):
        plan = copy.deepcopy(self.fixture)
        plan["schema_version"] = "1.6"
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(plan, output_dir, temporary)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = output_dir / plan["project_name"] / f'{plan["project_name"]}.Report'
            self.assertEqual(list(report.rglob("visual.json")), [])

    def test_version_1_6_review_table_retains_linked_bw_features(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        plan["schema_version"] = "1.6"
        table = plan["datasource"]["tables"][0]
        table["columns"].append({"name": "Calendar day key", "datatype": "datetime"})
        table["sap_bw_navigation"]["dimensions"][0]["properties"] = [{
            "source_column": "Calendar day",
            "selector": "[20CALDAY]",
            "column": "Calendar day key",
        }]
        table["sap_bw_navigation"]["parameters"] = [{
            "selector": "[!V000001]",
            "bex_variable_id": "synthetic-fiscal-year",
            "arguments": [["2026"]],
        }]
        semantics["coverage"]["variables"] = "complete"
        semantics["variables"] = [{
            "id": "synthetic-fiscal-year",
            "name": "Fiscal year",
            "kind": "characteristic",
            "required": True,
            "default_behavior_reference": "synthetic://behavior/fiscal-year",
            "status": "observed",
            "evidence_reference": "synthetic://evidence/fiscal-year",
        }]
        plan["review_report"] = {
            "page_name": "BW review",
            "columns": ["Calendar day key", "Quantity"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(
                (output_dir / "bex_linkage_assessment.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                evidence["variable_parameter_selection"]["selected"][0]["variable_id"],
                "synthetic-fiscal-year",
            )
            project = output_dir / plan["project_name"]
            report = project / f'{plan["project_name"]}.Report'
            visual_path, = report.rglob("visual.json")
            visual = json.loads(visual_path.read_text(encoding="utf-8"))
            projections = visual["visual"]["query"]["queryState"]["Values"]["projections"]
            self.assertEqual(
                [item["field"]["Column"]["Property"] for item in projections],
                ["Calendar day key", "Quantity"],
            )
            self.assertEqual(ArtifactValidator.validate_visual_references(project), [])

    def test_unknown_and_credential_fields_are_rejected(self):
        unknown = copy.deepcopy(self.fixture)
        unknown["unexpected"] = True
        credential = copy.deepcopy(self.fixture)
        credential["datasource"]["connection"]["password"] = "synthetic-only"
        invalid_version = copy.deepcopy(self.fixture)
        invalid_version["schema_version"] = []
        for plan in (unknown, credential, invalid_version):
            with self.subTest(plan=plan):
                self._assert_invalid_plan_rejected_without_output(plan)

    def test_missing_and_invalid_connection_or_navigation_are_rejected(self):
        missing_connection = copy.deepcopy(self.fixture)
        del missing_connection["datasource"]["connection"]
        invalid_connection = copy.deepcopy(self.fixture)
        invalid_connection["datasource"]["connection"]["type"] = "http"
        missing_navigation = copy.deepcopy(self.fixture)
        del missing_navigation["datasource"]["tables"][0]["sap_bw_navigation"]
        invalid_navigation = copy.deepcopy(self.fixture)
        del invalid_navigation["datasource"]["tables"][0]["sap_bw_navigation"]["measures"]

        for plan in (
            missing_connection,
            invalid_connection,
            missing_navigation,
            invalid_navigation,
        ):
            with self.subTest(plan=plan):
                self._assert_invalid_plan_rejected_without_output(plan)

    def test_navigation_output_columns_must_match_exactly_including_case(self):
        mismatch = copy.deepcopy(self.fixture)
        mismatch["datasource"]["tables"][0]["columns"][0]["name"] = "Region"
        case_mismatch = copy.deepcopy(self.fixture)
        case_mismatch["datasource"]["tables"][0]["columns"][0]["name"] = "calendar day"
        for plan in (mismatch, case_mismatch):
            with self.subTest(columns=plan["datasource"]["tables"][0]["columns"]):
                self._assert_invalid_plan_rejected_without_output(plan)

    def test_explicit_cube_attribute_property_is_generated_in_import_model(self):
        plan = json.loads(PROPERTY_FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(plan, output_dir, temporary)
            self.assertEqual(result.returncode, 0, result.stderr)
            project = output_dir / plan["project_name"]
            model = project / f'{plan["project_name"]}.SemanticModel'
            table_text = (model / "definition" / "tables" / "Sales.tmdl").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                '{Table.AddColumn, "Calendar day key", each '
                'Cube.AttributeMemberProperty([#"Calendar day"], "[20CALDAY]")}',
                table_text,
            )
            self.assertIn("sourceColumn: 'Calendar day key'", table_text)
            self.assertNotIn("Date.Year", table_text)
            self.assertNotIn("hierarchy 'Calendar day key Hierarchy'", table_text)
            self.assertFalse((model / "definition" / "tables" / "Calendar.tmdl").exists())
            self.assertTrue(ArtifactValidator.validate_project(project)["valid"])
            report = project / f'{plan["project_name"]}.Report'
            self.assertEqual(list(report.rglob("visual.json")), [])

    def test_invalid_cube_attribute_property_is_rejected_without_output(self):
        plan = copy.deepcopy(self.fixture)
        plan["schema_version"] = "1.3"
        table = plan["datasource"]["tables"][0]
        table["sap_bw_navigation"]["dimensions"][0]["properties"] = [{
            "source_column": "Calendar day",
            "selector": "[20CALDAY]",
            "column": "Calendar day key",
        }]
        table["columns"].append({"name": "Calendar day key", "datatype": "datetime"})
        for mutation in ("old_version", "unknown_source", "duplicate_column", "bad_selector"):
            invalid = copy.deepcopy(plan)
            dimension = invalid["datasource"]["tables"][0]["sap_bw_navigation"]["dimensions"][0]
            if mutation == "old_version":
                invalid["schema_version"] = "1.2"
            elif mutation == "unknown_source":
                dimension["properties"][0]["source_column"] = "Missing"
            elif mutation == "duplicate_column":
                dimension["properties"][0]["column"] = "calendar day"
                invalid["datasource"]["tables"][0]["columns"].pop()
                invalid["datasource"]["tables"][0]["columns"][0]["name"] = "calendar day"
                dimension["columns"][0] = "calendar day"
                dimension["properties"][0]["source_column"] = "calendar day"
            else:
                dimension["properties"][0]["selector"] = ""
            with self.subTest(mutation=mutation):
                self._assert_invalid_plan_rejected_without_output(invalid)

    def test_linked_version_1_3_preserves_dimension_binding_checks(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        plan["schema_version"] = "1.3"
        table = plan["datasource"]["tables"][0]
        table["sap_bw_navigation"]["dimensions"][0]["properties"] = [{
            "source_column": "Calendar day",
            "selector": "[20CALDAY]",
            "column": "Calendar day key",
        }]
        table["columns"].append({"name": "Calendar day key", "datatype": "datetime"})
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output_dir / "bex_linkage_assessment.json").is_file())
            text = (
                output_dir / plan["project_name"]
                / f'{plan["project_name"]}.SemanticModel'
                / "definition" / "tables" / "Sales.tmdl"
            ).read_text(encoding="utf-8")
            self.assertIn('Cube.AttributeMemberProperty([#"Calendar day"], "[20CALDAY]")', text)

        del plan["bex_linkage"]["dimension_bindings"]
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("schema_version '1.3' requires", result.stderr)
            self.assertFalse(output_dir.exists())

    def test_explicit_cube_parameter_is_in_generated_pbip(self):
        plan = copy.deepcopy(self.fixture)
        plan["schema_version"] = "1.4"
        plan["datasource"]["tables"][0]["sap_bw_navigation"]["parameters"] = [{
            "selector": "[!SYNTHETIC]",
            "arguments": [["synthetic-a", "synthetic-b"]],
        }]
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(plan, output_dir, temporary)
            self.assertEqual(result.returncode, 0, result.stderr)
            project = output_dir / plan["project_name"]
            model = project / f'{plan["project_name"]}.SemanticModel'
            text = (model / "definition" / "tables" / "Sales.tmdl").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                '{Cube.ApplyParameter, "[!SYNTHETIC]", {{"synthetic-a", "synthetic-b"}}}',
                text,
            )
            self.assertTrue(ArtifactValidator.validate_project(project)["valid"])
            self.assertEqual(list((project / f'{plan["project_name"]}.Report').rglob("visual.json")), [])

    def test_cube_parameter_requires_version_1_4_and_valid_arguments(self):
        plan = copy.deepcopy(self.fixture)
        plan["schema_version"] = "1.4"
        plan["datasource"]["tables"][0]["sap_bw_navigation"]["parameters"] = [{
            "selector": "[!SYNTHETIC]", "arguments": [["synthetic-a"]],
        }]
        for mutation in (
            "old_version", "empty_arguments", "invalid_value", "unknown_field", "untrimmed",
        ):
            invalid = copy.deepcopy(plan)
            parameter = invalid["datasource"]["tables"][0]["sap_bw_navigation"]["parameters"][0]
            if mutation == "old_version":
                invalid["schema_version"] = "1.3"
            elif mutation == "empty_arguments":
                parameter["arguments"] = []
            elif mutation == "invalid_value":
                parameter["arguments"] = [False]
            elif mutation == "untrimmed":
                parameter["arguments"] = [" value "]
            else:
                parameter["extra"] = "unexpected"
            with self.subTest(mutation=mutation):
                self._assert_invalid_plan_rejected_without_output(invalid)

    def test_linked_version_1_4_keeps_binding_checks_and_does_not_copy_parameter_values(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        plan["schema_version"] = "1.4"
        navigation = plan["datasource"]["tables"][0]["sap_bw_navigation"]
        navigation["parameters"] = [{
            "selector": "[!SYNTHETIC]",
            "arguments": [["synthetic-filter-value"]],
        }]
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = (output_dir / "bex_linkage_assessment.json").read_text(encoding="utf-8")
            self.assertNotIn("synthetic-filter-value", report)
            table = (
                output_dir / plan["project_name"]
                / f'{plan["project_name"]}.SemanticModel'
                / "definition" / "tables" / "Sales.tmdl"
            ).read_text(encoding="utf-8")
            self.assertIn('{{"synthetic-filter-value"}}', table)

        del plan["bex_linkage"]["dimension_bindings"]
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("dimension_bindings", result.stderr)
            self.assertFalse(output_dir.exists())

    def test_linked_version_1_5_reports_declared_variable_parameter_bindings(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        plan["schema_version"] = "1.5"
        semantics["coverage"]["variables"] = "complete"
        semantics["variables"] = [
            {
                "id": "synthetic-fiscal-year",
                "name": "Fiscal year",
                "kind": "characteristic",
                "required": True,
                "default_behavior_reference": "synthetic://behavior/fiscal-year",
                "status": "observed",
                "evidence_reference": "synthetic://evidence/fiscal-year",
            },
            {
                "id": "synthetic-region-prompt",
                "name": "Region prompt",
                "kind": "characteristic",
                "required": False,
                "default_behavior_reference": "synthetic://behavior/region",
                "status": "observed",
                "evidence_reference": "synthetic://evidence/region",
            },
        ]
        parameters = plan["datasource"]["tables"][0]["sap_bw_navigation"].setdefault(
            "parameters", []
        )
        parameters.append({
            "selector": "[!V000001]",
            "bex_variable_id": "synthetic-fiscal-year",
            "arguments": [["2026"]],
        })
        parameters.append({
            "selector": "[!V000002]",
            "arguments": [["NE"]],
        })
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(
                (output_dir / "bex_linkage_assessment.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["variable_parameter_selection"], {
                "status": "some_declared_unselected",
                "selected": [{
                    "variable_id": "synthetic-fiscal-year",
                    "variable_name": "Fiscal year",
                    "kind": "characteristic",
                    "manifest_status": "observed",
                    "parameter_selector": "[!V000001]",
                }],
                "unselected": ["synthetic-region-prompt"],
                "scope": "explicit_local_variable_id_and_parameter_selector_declarations_only",
                "argument_values_included": False,
            })
            self.assertNotIn("2026", json.dumps(report))
            self.assertNotIn('"NE"', json.dumps(report))
            model = (
                output_dir / plan["project_name"]
                / f'{plan["project_name"]}.SemanticModel'
                / "definition" / "tables" / "Sales.tmdl"
            ).read_text(encoding="utf-8")
            self.assertIn('{Cube.ApplyParameter, "[!V000001]", {{"2026"}}}', model)
            self.assertIn('{Cube.ApplyParameter, "[!V000002]", {{"NE"}}}', model)

        invalid = copy.deepcopy(plan)
        invalid["datasource"]["tables"][0]["sap_bw_navigation"]["parameters"][0][
            "bex_variable_id"
        ] = "not-in-the-manifest"
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                invalid, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("undeclared BEx variable", result.stderr)
            self.assertFalse(output_dir.exists())

    def test_bex_variable_parameter_bindings_require_version_1_5_and_linkage(self):
        plan = copy.deepcopy(self.fixture)
        plan["schema_version"] = "1.5"
        plan["datasource"]["tables"][0]["sap_bw_navigation"]["parameters"] = [{
            "selector": "[!V000001]",
            "bex_variable_id": "synthetic-variable",
            "arguments": ["2026"],
        }]
        with self.subTest(case="missing_linkage"):
            self._assert_invalid_plan_rejected_without_output(plan)
        plan["bex_linkage"] = {
            "query_id": "synthetic-query",
            "provider_id": "synthetic-provider",
            "cube_id": plan["datasource"]["tables"][0]["sap_bw_navigation"]["cube_id"],
            "key_figure_bindings": [{
                "key_figure_id": "synthetic-kf",
                "selector": "[Measures].[0D_INV_QTY]",
                "column": "Quantity",
            }],
            "dimension_bindings": [{
                "selector": "[0CALDAY]",
                "provider_dimension_name": "Calendar day",
            }],
        }
        old_version = copy.deepcopy(plan)
        old_version["schema_version"] = "1.4"
        with self.subTest(case="old_version"):
            self._assert_invalid_plan_rejected_without_output(old_version)

    def test_multiple_cubes_and_bad_project_names_or_types_are_rejected(self):
        multiple_cubes = copy.deepcopy(self.fixture)
        multiple_cubes["datasource"]["tables"].append(
            copy.deepcopy(multiple_cubes["datasource"]["tables"][0])
        )
        reserved_name = copy.deepcopy(self.fixture)
        reserved_name["project_name"] = "CON"
        nontext_name = copy.deepcopy(self.fixture)
        nontext_name["project_name"] = 17
        for plan in (multiple_cubes, reserved_name, nontext_name):
            with self.subTest(plan=plan):
                self._assert_invalid_plan_rejected_without_output(plan)

    def test_existing_file_and_nonempty_output_directory_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            existing_file = Path(temporary) / "occupied"
            existing_file.write_text("keep this file", encoding="utf-8")
            result = self._run_cli(self.fixture, existing_file, temporary)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(existing_file.read_text(encoding="utf-8"), "keep this file")

        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "occupied"
            output_dir.mkdir()
            sentinel = output_dir / "sentinel.txt"
            sentinel.write_text("keep this content", encoding="utf-8")
            result = self._run_cli(self.fixture, output_dir, temporary)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep this content")
            self.assertEqual(list(output_dir.iterdir()), [sentinel])

    def test_bex_linkage_checks_query_provider_and_selected_key_figure_before_generation(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("candidate_for_owner_review", result.stdout)
            evidence = json.loads(
                (output_dir / "bex_linkage_assessment.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                evidence["bex_semantics_not_converted"],
                {
                    "evidence_scope": "declared_local_manifest_counts_only",
                    "declared_coverage": semantics["coverage"],
                    "counts": {
                        "variables": 0,
                        "filters": 0,
                        "hierarchies": 0,
                        "master_data": 0,
                        "key_figure_semantics": 1,
                        "authorization_contexts": 0,
                    },
                    "unconverted_filter_declarations": [],
                    "unconverted_hierarchy_declarations": [],
                },
            )
            self.assertEqual(
                evidence["bex_semantics_not_converted"]["declared_coverage"]["filters"],
                "not_applicable",
            )
            self.assertIn(
                "declared BEx semantics are not reproduced",
                result.stderr,
            )
            self.assertIn("key_figure_semantics=1", result.stderr)
            review_items = evidence["bw5_assessment"]["summary"]["review_items"]
            self.assertGreater(review_items, 0)
            self.assertIn(f"BW-5 has {review_items} review item(s)", result.stderr)
            self.assertIn("bex_linkage_assessment.json", result.stderr)
            self.assertEqual(
                evidence["native_infocube_identity_verification"],
                "not_verified",
            )
            self.assertEqual(
                evidence["key_figure_selection"],
                {
                    "status": "all_declared_selected",
                    "selected": ["synthetic-net-sales"],
                    "unselected": [],
                    "selected_semantics_scope": (
                        "local_bex_manifest_declarations_only"
                    ),
                    "selected_semantics": [{
                        "key_figure_id": "synthetic-net-sales",
                        "selector": "[Measures].[Net sales amount]",
                        "column": "Quantity",
                        "manifest_status": "observed",
                        "declared_aggregation": "sum",
                        "declared_exception_aggregation": {
                            "status": "not_applicable",
                            "method": None,
                            "reference_characteristic": None,
                        },
                        "declared_unit_currency": {
                            "status": "observed",
                            "unit": None,
                            "currency": "EUR",
                            "conversion_reference": "synthetic://currency/eur",
                        },
                    }],
                },
            )
            self.assertEqual(
                evidence["plan_linkage"]["provider_id"],
                plan["bex_linkage"]["provider_id"],
            )
            self.assertFalse(evidence["bw5_assessment"]["gate_closed"])
            self.assertEqual(
                evidence["bw5_assessment"]["runtime_evidence"]["source_target_result_comparison"],
                "not_run",
            )
            model_table = (
                output_dir / plan["project_name"] / f'{plan["project_name"]}.SemanticModel'
                / "definition" / "tables" / "Sales.tmdl"
            ).read_text(encoding="utf-8")
            self.assertIn(
                '{Cube.AddMeasureColumn, "Quantity", "[Measures].[Net sales amount]"}',
                model_table,
            )
            self.assertIn(
                '{Cube.AddAndExpandDimensionColumn, "[0CALDAY]", '
                '{"[0CALDAY].[LEVEL01]"}, {"Calendar day"}}',
                model_table,
            )

        mismatches = []
        wrong_provider = copy.deepcopy(plan)
        wrong_provider["bex_linkage"]["provider_id"] = "SYNTHETIC-BW-01:ADSO:VENTES-BRUTES"
        mismatches.append((wrong_provider, inventory, semantics, "must identify an InfoCube"))
        wrong_selector = copy.deepcopy(plan)
        wrong_selector["datasource"]["tables"][0]["sap_bw_navigation"]["measures"][0][
            "selector"
        ] = "[Measures].[Different measure]"
        wrong_selector["bex_linkage"]["key_figure_bindings"][0]["selector"] = (
            "[Measures].[Different measure]"
        )
        mismatches.append((wrong_selector, inventory, semantics, "does not match"))
        wrong_dimension = copy.deepcopy(plan)
        wrong_dimension["bex_linkage"]["dimension_bindings"][0][
            "provider_dimension_name"
        ] = "Unobserved dimension"
        mismatches.append((
            wrong_dimension,
            inventory,
            semantics,
            "is not an observed dimension of the selected InfoCube",
        ))
        incomplete_dimension_binding = copy.deepcopy(plan)
        incomplete_dimension_binding["bex_linkage"]["dimension_bindings"][0][
            "selector"
        ] = "[0COUNTRY]"
        mismatches.append((
            incomplete_dimension_binding,
            inventory,
            semantics,
            "must map every selected BW dimension exactly once",
        ))
        duplicate_dimension_binding = copy.deepcopy(plan)
        duplicate_dimension_binding["bex_linkage"]["dimension_bindings"].append(
            copy.deepcopy(
                duplicate_dimension_binding["bex_linkage"]["dimension_bindings"][0]
            )
        )
        mismatches.append((
            duplicate_dimension_binding,
            inventory,
            semantics,
            "selector must be unique",
        ))
        missing_dimension_bindings = copy.deepcopy(plan)
        missing_dimension_bindings["bex_linkage"].pop("dimension_bindings")
        mismatches.append((
            missing_dimension_bindings,
            inventory,
            semantics,
            "schema_version '1.2' requires",
        ))
        wrong_client = copy.deepcopy(plan)
        wrong_client["datasource"]["connection"]["client_id"] = "001"
        mismatches.append((
            wrong_client,
            inventory,
            semantics,
            "does not match the BW inventory source client",
        ))
        incomplete_semantics = copy.deepcopy(semantics)
        incomplete_semantics["coverage"]["filters"] = "partial"
        mismatches.append((
            plan,
            inventory,
            incomplete_semantics,
            "semantic_coverage_incomplete",
        ))
        for invalid_plan, invalid_inventory, invalid_semantics, message in mismatches:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                output_dir = Path(temporary) / "generated"
                result = self._run_cli(
                    invalid_plan,
                    output_dir,
                    temporary,
                    inventory=invalid_inventory,
                    semantics=invalid_semantics,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertFalse(output_dir.exists())

    def test_bw5_blocker_error_includes_count_and_finding_path(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        semantics["coverage"]["filters"] = "partial"

        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("BW-5 declarations contain 1 blocker(s)", result.stderr)
            self.assertIn("semantic_coverage_incomplete", result.stderr)
            self.assertIn("$.coverage.filters", result.stderr)
            self.assertFalse(output_dir.exists())

    def test_bw5_blocker_error_bounds_reported_paths(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        for field in ("variables", "filters", "hierarchies", "master_data"):
            semantics["coverage"][field] = "partial"

        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("BW-5 declarations contain 4 blocker(s)", result.stderr)
            self.assertIn("$.coverage.variables", result.stderr)
            self.assertIn("$.coverage.filters", result.stderr)
            self.assertIn("$.coverage.hierarchies", result.stderr)
            self.assertIn("1 additional blocker(s)", result.stderr)
            self.assertFalse(output_dir.exists())

    def test_declared_bex_filters_are_counted_as_unconverted(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        semantics["coverage"]["filters"] = "complete"
        semantics["filters"] = [{
            "id": "synthetic-region-filter",
            "name": "Region restriction",
            "target": "Region",
            "operator": "selection",
            "selection_reference": "synthetic://filters/region",
            "status": "observed",
            "evidence_reference": "synthetic://evidence/filter",
        }]

        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("filters=1", result.stderr)
            evidence = json.loads(
                (output_dir / "bex_linkage_assessment.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                evidence["bex_semantics_not_converted"]["counts"]["filters"],
                1,
            )

    def test_unconverted_filter_and_hierarchy_declarations_are_id_status_only(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        semantics["coverage"]["filters"] = "complete"
        semantics["coverage"]["hierarchies"] = "complete"
        semantics["filters"] = [
            {
                "id": "fílter-東京-01",
                "name": "FILTER_NAME_CANARY Ω",
                "target": "FILTER_SELECTOR_CANARY [0REGION]",
                "operator": "selection",
                "selection_reference": "FILTER_LITERAL_CANARY 秘密値-01",
                "status": "observed",
                "evidence_reference": "FILTER_EVIDENCE_CANARY",
            },
            {
                "id": "fílter-東京-02",
                "name": "FILTER_NAME_CANARY 第二",
                "target": "FILTER_SELECTOR_CANARY [0COUNTRY]",
                "operator": "exclude",
                "selection_reference": "FILTER_LITERAL_CANARY 秘密値-02",
                "status": "inferred",
                "evidence_reference": "FILTER_EVIDENCE_CANARY_SECOND",
            },
        ]
        semantics["hierarchies"] = [
            {
                "id": "階層-東京-01",
                "characteristic": "HIERARCHY_NAME_CANARY Ω",
                "hierarchy_reference": "HIERARCHY_SELECTOR_CANARY [0REGION]",
                "versioning": "static",
                "selection_behavior_reference": "HIERARCHY_LITERAL_CANARY 選択値-01",
                "status": "observed",
                "evidence_reference": "HIERARCHY_EVIDENCE_CANARY",
            },
            {
                "id": "階層-東京-02",
                "characteristic": "HIERARCHY_NAME_CANARY 第二",
                "hierarchy_reference": "HIERARCHY_SELECTOR_CANARY [0COUNTRY]",
                "versioning": "time_dependent",
                "selection_behavior_reference": "HIERARCHY_LITERAL_CANARY 選択値-02",
                "status": "inferred",
                "evidence_reference": "HIERARCHY_EVIDENCE_CANARY_SECOND",
            },
        ]
        expected_coverage = copy.deepcopy(semantics["coverage"])
        private_declaration_values = (
            "FILTER_NAME_CANARY",
            "FILTER_SELECTOR_CANARY",
            "FILTER_LITERAL_CANARY",
            "FILTER_EVIDENCE_CANARY",
            "HIERARCHY_NAME_CANARY",
            "HIERARCHY_SELECTOR_CANARY",
            "HIERARCHY_LITERAL_CANARY",
            "HIERARCHY_EVIDENCE_CANARY",
        )

        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("candidate_for_owner_review", result.stdout)
            self.assertIn(
                "declared BEx semantics are not reproduced in this PBIP draft "
                "(filters=2, hierarchies=2, key_figure_semantics=1)",
                result.stderr,
            )
            evidence = json.loads(
                (output_dir / "bex_linkage_assessment.json").read_text(
                    encoding="utf-8"
                )
            )
            summary = evidence["bex_semantics_not_converted"]
            self.assertEqual(summary["counts"], {
                "variables": 0,
                "filters": 2,
                "hierarchies": 2,
                "master_data": 0,
                "key_figure_semantics": 1,
                "authorization_contexts": 0,
            })
            self.assertEqual(summary["declared_coverage"], expected_coverage)
            self.assertEqual(summary["unconverted_filter_declarations"], [
                {"id": "fílter-東京-01", "status": "observed"},
                {"id": "fílter-東京-02", "status": "inferred"},
            ])
            self.assertEqual(summary["unconverted_hierarchy_declarations"], [
                {"id": "階層-東京-01", "status": "observed"},
                {"id": "階層-東京-02", "status": "inferred"},
            ])
            for declarations in (
                summary["unconverted_filter_declarations"],
                summary["unconverted_hierarchy_declarations"],
            ):
                for declaration in declarations:
                    self.assertEqual(set(declaration), {"id", "status"})
            evidence_text = json.dumps(evidence, ensure_ascii=False)
            for value in private_declaration_values:
                self.assertNotIn(value, evidence_text)
            self.assertEqual(evidence["native_infocube_identity_verification"], "not_verified")
            self.assertEqual(evidence["schema_version"], "1.0")
            self.assertEqual(plan["schema_version"], "1.2")

    def test_partial_key_figure_selection_is_reported_without_blocking_pbip(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        extra_figure = copy.deepcopy(semantics["key_figures"][0])
        extra_figure.update({"id": "synthetic-discount", "name": "Discount"})
        semantics["key_figures"].append(extra_figure)
        provider = next(
            item for item in inventory["objects"]
            if item["id"] == plan["bex_linkage"]["provider_id"]
        )
        extra_measure = copy.deepcopy(provider["semantics"]["measures"][0])
        extra_measure["name"] = "Discount"
        provider["semantics"]["measures"].append(extra_measure)
        extra_binding = copy.deepcopy(semantics["provider_key_figure_bindings"][0])
        extra_binding.update({
            "key_figure_id": "synthetic-discount",
            "provider_measure_name": "Discount",
        })
        semantics["provider_key_figure_bindings"].append(extra_binding)

        for select_no_figures in (False, True):
            with self.subTest(select_no_figures=select_no_figures):
                selected_plan = copy.deepcopy(plan)
                selected = ["synthetic-net-sales"]
                unselected = ["synthetic-discount"]
                if select_no_figures:
                    table = selected_plan["datasource"]["tables"][0]
                    table["columns"] = [
                        column for column in table["columns"]
                        if column["name"] != "Quantity"
                    ]
                    table["sap_bw_navigation"]["measures"] = []
                    selected_plan["bex_linkage"]["key_figure_bindings"] = []
                    selected = []
                    unselected.insert(0, "synthetic-net-sales")

                with tempfile.TemporaryDirectory() as temporary:
                    output_dir = Path(temporary) / "generated"
                    result = self._run_cli(
                        selected_plan, output_dir, temporary,
                        inventory=inventory, semantics=semantics,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(
                        f"{len(unselected)} declared BEx key figure(s) are not selected",
                        result.stderr,
                    )
                    evidence = json.loads(
                        (output_dir / "bex_linkage_assessment.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(
                        evidence["key_figure_selection"],
                        {
                            "status": "some_declared_unselected",
                            "selected": selected,
                            "unselected": unselected,
                            "selected_semantics_scope": (
                                "local_bex_manifest_declarations_only"
                            ),
                            "selected_semantics": (
                                [{
                                    "key_figure_id": "synthetic-net-sales",
                                    "selector": "[Measures].[Net sales amount]",
                                    "column": "Quantity",
                                    "manifest_status": "observed",
                                    "declared_aggregation": "sum",
                                    "declared_exception_aggregation": {
                                        "status": "not_applicable",
                                        "method": None,
                                        "reference_characteristic": None,
                                    },
                                    "declared_unit_currency": {
                                        "status": "observed",
                                        "unit": None,
                                        "currency": "EUR",
                                        "conversion_reference": (
                                            "synthetic://currency/eur"
                                        ),
                                    },
                                }]
                                if selected else []
                            ),
                        },
                    )
                    self.assertTrue(
                        (output_dir / selected_plan["project_name"]
                         / f'{selected_plan["project_name"]}.pbip').is_file()
                    )

    def test_no_declared_key_figures_does_not_claim_selection_coverage(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        table = plan["datasource"]["tables"][0]
        table["columns"] = [
            column for column in table["columns"] if column["name"] != "Quantity"
        ]
        table["sap_bw_navigation"]["measures"] = []
        plan["bex_linkage"]["key_figure_bindings"] = []
        semantics["key_figures"] = []
        semantics["provider_key_figure_bindings"] = []
        semantics["coverage"]["key_figures"] = "not_applicable"
        semantics["coverage"]["exception_aggregation"] = "not_applicable"
        semantics["coverage"]["units_currencies"] = "not_applicable"

        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("declared BEx key figure(s) are not selected", result.stderr)
            evidence = json.loads(
                (output_dir / "bex_linkage_assessment.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                evidence["key_figure_selection"],
                {
                    "status": "none_declared",
                    "selected": [],
                    "unselected": [],
                    "selected_semantics_scope": (
                        "local_bex_manifest_declarations_only"
                    ),
                    "selected_semantics": [],
                },
            )
            self.assertEqual(
                evidence["bex_semantics_not_converted"]["evidence_scope"],
                "declared_local_manifest_counts_only",
            )
            self.assertNotIn(
                "declared BEx semantics are not reproduced",
                result.stderr,
            )

    def test_ambiguous_info_cube_dimension_is_rejected_before_output(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        provider = next(
            item for item in inventory["objects"]
            if item["id"] == plan["bex_linkage"]["provider_id"]
        )
        duplicate = copy.deepcopy(provider["semantics"]["dimensions"][0])
        duplicate["data_type"] = "STRING"
        provider["semantics"]["dimensions"].append(duplicate)

        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                plan, output_dir, temporary, inventory=inventory, semantics=semantics,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("matches multiple InfoCube dimensions", result.stderr)
            self.assertFalse(output_dir.exists())

    def test_bex_linkage_requires_both_evidence_inputs_and_link_declaration(self):
        plan, inventory, semantics = self._linked_plan_and_evidence()
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(plan, output_dir, temporary)
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires --inventory and --semantics", result.stderr)
            self.assertFalse(output_dir.exists())

            unlinked_plan = copy.deepcopy(self.fixture)
            result = self._run_cli(
                unlinked_plan,
                output_dir,
                temporary,
                inventory=inventory,
                semantics=semantics,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("BEx linkage is required", result.stderr)
            self.assertFalse(output_dir.exists())

        legacy_plan, inventory, semantics = self._linked_plan_and_evidence()
        legacy_plan["schema_version"] = "1.1"
        legacy_plan["bex_linkage"].pop("dimension_bindings")
        provider = next(
            item for item in inventory["objects"]
            if item["id"] == legacy_plan["bex_linkage"]["provider_id"]
        )
        provider["semantics"]["dimensions"].append(
            copy.deepcopy(provider["semantics"]["dimensions"][0])
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "generated"
            result = self._run_cli(
                legacy_plan,
                output_dir,
                temporary,
                inventory=inventory,
                semantics=semantics,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
