"""Contract and generated-notebook tests for bounded BW transformation conversion."""

import ast
import contextlib
import copy
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import types
import unittest
from decimal import Decimal, localcontext
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from powerbi_import.bw_bronze_generator import build_bw_bronze_notebook
from powerbi_import.bw_inventory import BWInventoryError
from powerbi_import.bw_transform_generator import (
    BWTransformConversionError,
    build_bw_conversion_notebook,
)
from powerbi_import.bw_transform_validation import compare_transform_vectors

ROOT = Path(__file__).resolve().parents[1]


class _BWConversionExpression:
    def __init__(self, spark, evaluate, spark_type, name=None):
        self.spark = spark
        self.evaluate = evaluate
        self.spark_type = spark_type
        self.name = name

    def alias(self, name):
        return _BWConversionExpression(self.spark, self.evaluate, self.spark_type, name)

    def cast(self, spark_type):
        decimal_type = re.fullmatch(r"decimal\(\d+,(\d+)\)", spark_type)

        def cast_value(row):
            value = self.evaluate(row)
            if value is None or decimal_type is None:
                return value
            scale = int(decimal_type.group(1))
            return Decimal(value).quantize(Decimal(1).scaleb(-scale))

        return _BWConversionExpression(self.spark, cast_value, spark_type)

    def eqNullSafe(self, other):
        return _BWConversionExpression(
            self.spark, lambda row: self.evaluate(row) == other.evaluate(row), "boolean"
        )

    def __invert__(self):
        return _BWConversionExpression(self.spark, lambda row: not self.evaluate(row), "boolean")

    def __or__(self, other):
        return _BWConversionExpression(
            self.spark, lambda row: self.evaluate(row) or other.evaluate(row), "boolean"
        )

    def _arithmetic(self, other, subtract):
        left_type = re.fullmatch(r"decimal\((\d+),(\d+)\)", self.spark_type)
        right_type = re.fullmatch(r"decimal\((\d+),(\d+)\)", other.spark_type)
        if left_type is None or right_type is None:
            raise AssertionError("Unexpected decimal operand type")
        left_precision, left_scale = map(int, left_type.groups())
        right_precision, right_scale = map(int, right_type.groups())
        if left_scale != right_scale:
            raise AssertionError("Unexpected decimal scale")
        result_type = f"decimal({max(left_precision, right_precision) + 1},{left_scale})"
        if self.spark.corrupt_output_type:
            result_type = "double"

        def evaluate(row):
            left, right = self.evaluate(row), other.evaluate(row)
            if left is None or right is None:
                return None
            return left - right if subtract else left + right

        return _BWConversionExpression(self.spark, evaluate, result_type)

    def __add__(self, other):
        return self._arithmetic(other, False)

    def __sub__(self, other):
        return self._arithmetic(other, True)


class _BWConversionFrame:
    def __init__(self, spark, fields, rows):
        self.spark = spark
        self.fields = list(fields)
        self.rows = [dict(row) for row in rows]
        self.released = False
        self.count_offset = 0
        self.schema = types.SimpleNamespace(fields=[
            types.SimpleNamespace(
                name=name,
                dataType=types.SimpleNamespace(simpleString=lambda kind=kind: kind),
            )
            for name, kind in self.fields
        ])

    def persist(self, level):
        if level != "disk":
            raise AssertionError("Unexpected cache level")
        self.spark.persisted.append(self)
        return self

    def unpersist(self):
        self.released = True

    def count(self):
        return len(self.rows) + self.count_offset

    def filter(self, expression):
        return _BWConversionFrame(
            self.spark, self.fields, [row for row in self.rows if expression.evaluate(row)]
        )

    def limit(self, number):
        return _BWConversionFrame(self.spark, self.fields, self.rows[:number])

    def select(self, *expressions):
        return _BWConversionFrame(
            self.spark,
            [(expression.name, expression.spark_type) for expression in expressions],
            [
                {expression.name: expression.evaluate(row) for expression in expressions}
                for row in self.rows
            ],
        )

    @property
    def write(self):
        return _BWConversionWriter(self.spark, self)


class _BWConversionWriter:
    def __init__(self, spark, frame):
        self.spark = spark
        self.frame = frame
        self.format_name = None
        self.mode_name = None

    def format(self, value):
        self.format_name = value
        return self

    def mode(self, value):
        self.mode_name = value
        return self

    def saveAsTable(self, target):
        if self.format_name != "delta" or self.mode_name != "errorifexists":
            raise AssertionError("Unexpected writer settings")
        if self.spark.fail_write:
            raise RuntimeError("Synthetic write failure")
        if target in self.spark.tables:
            raise RuntimeError("Target already exists")
        result = _BWConversionFrame(self.spark, self.frame.fields, self.frame.rows)
        if self.spark.corrupt_target_count:
            result.count_offset = 1
        self.spark.tables[target] = result


class _BWConversionSpark:
    def __init__(self, table_name, fields, rows):
        self.persisted = []
        self.corrupt_output_type = False
        self.corrupt_target_count = False
        self.fail_write = False
        self.tables = {table_name: _BWConversionFrame(self, fields, rows)}
        self.source_types = dict(fields)
        self.catalog = types.SimpleNamespace(tableExists=lambda name: name in self.tables)

    def table(self, name):
        return self.tables[name]

    def column(self, quoted):
        if not (quoted.startswith("`") and quoted.endswith("`")):
            raise AssertionError("Source identifier was not quoted")
        inner = quoted[1:-1]
        index = 0
        parts = []
        while index < len(inner):
            if inner[index] == "`":
                if index + 1 >= len(inner) or inner[index + 1] != "`":
                    raise AssertionError("Source identifier has an unescaped backtick")
                index += 1
            parts.append(inner[index])
            index += 1
        name = "".join(parts)
        return _BWConversionExpression(self, lambda row: row[name], self.source_types[name])

    def literal(self, value):
        if value is None:
            spark_type = "void"
        elif type(value) is bool:
            spark_type = "boolean"
        elif type(value) is int:
            spark_type = "int" if -(2**31) <= value < 2**31 else "bigint"
        elif isinstance(value, str):
            spark_type = "string"
        else:
            raise AssertionError("Unexpected literal")
        return _BWConversionExpression(self, lambda row: value, spark_type)


def _execute_conversion_notebook(notebook, spark):
    fake_pyspark = types.ModuleType("pyspark")
    setattr(fake_pyspark, "StorageLevel", types.SimpleNamespace(DISK_ONLY="disk"))
    fake_sql = types.ModuleType("pyspark.sql")
    setattr(fake_sql, "functions", types.SimpleNamespace(col=spark.column, lit=spark.literal))
    setattr(fake_pyspark, "sql", fake_sql)
    source = "".join(notebook["cells"][1]["source"])
    with patch.dict(sys.modules, {"pyspark": fake_pyspark, "pyspark.sql": fake_sql}):
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(source, "<bw-conversion-notebook>", "exec"), {"spark": spark})


class TestBWTransformConversion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures = ROOT / "docs" / "fixtures"
        cls.inventory = json.loads(
            (fixtures / "sap_bw_conversion_inventory.example.json").read_text(encoding="utf-8")
        )
        cls.bronze = json.loads(
            (fixtures / "sap_bw_conversion_bronze_plan.example.json").read_text(encoding="utf-8")
        )
        cls.plan = json.loads(
            (fixtures / "sap_bw_conversion_plan.example.json").read_text(encoding="utf-8")
        )
        cls.definition_file = fixtures / "sap_bw_conversion_definition.example.txt"
        cls.rule_ledger_file = fixtures / "sap_bw_source_rules.example.json"
        cls.rule_ledger = json.loads(cls.rule_ledger_file.read_text(encoding="utf-8"))
        cls.lineage_fields = [
            ("_bw_source_system_id", "string"), ("_bw_object_id", "string"),
            ("_bw_snapshot_id", "string"), ("_bw_snapshot_cutoff_utc", "string"),
            ("_bw_source_file", "string"), ("_bw_ingested_at", "timestamp"),
        ]

    def _notebook(self, plan=None, inventory=None, *, definition_file=None, rule_ledger=None):
        return build_bw_conversion_notebook(
            copy.deepcopy(self.inventory if inventory is None else inventory),
            copy.deepcopy(self.plan if plan is None else plan),
            definition_file=definition_file,
            rule_ledger=rule_ledger,
        )

    def _notebook_with_source_ledger(self, ledger):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
            return self._notebook(definition_file=self.definition_file, rule_ledger=path)

    def _spark(self, plan=None, rows=None):
        plan = self.plan if plan is None else plan
        fields = [(column["name"], column["spark_type"]) for column in plan["input_columns"]]
        if rows is None:
            lineage = {
                "_bw_source_system_id": self.inventory["source_system"]["id"],
                "_bw_object_id": plan["source_object_id"],
                "_bw_snapshot_id": plan["source_snapshot_id"],
                "_bw_snapshot_cutoff_utc": plan["source_snapshot_cutoff_utc"],
                "_bw_source_file": "synthetic-staged-file",
                "_bw_ingested_at": "synthetic-timestamp",
            }
            first = {
                "VenteID": "1", "Montant": Decimal("12.34"),
                "Ajustement": Decimal("-1.20"), "Région": "Île / région", **lineage,
            }
            rows = [
                first, copy.deepcopy(first),
                {
                    "VenteID": "2", "Montant": None, "Ajustement": Decimal("2.00"),
                    "Région": None, **lineage,
                },
            ]
        return _BWConversionSpark(plan["source_table"], fields + self.lineage_fields, rows)

    def test_synthetic_chain_contract_and_unbound_notebook(self):
        inventory = copy.deepcopy(self.inventory)
        plan = copy.deepcopy(self.plan)
        original_inventory, original_plan = copy.deepcopy(inventory), copy.deepcopy(plan)
        bronze = build_bw_bronze_notebook(inventory, self.bronze)
        notebook = build_bw_conversion_notebook(inventory, plan)
        self.assertEqual(inventory, original_inventory)
        self.assertEqual(plan, original_plan)
        self.assertEqual(self.bronze["target_table"], plan["source_table"])
        self.assertEqual(self.bronze["expected_columns"], plan["input_columns"])
        self.assertEqual(self.bronze["snapshot_id"], plan["source_snapshot_id"])
        self.assertEqual(self.bronze["snapshot_cutoff_utc"], plan["source_snapshot_cutoff_utc"])
        self.assertEqual(self.bronze["expected_rows"], plan["expected_rows"])
        self.assertEqual(bronze["metadata"]["bw_migration"]["source_object_id"], plan["source_object_id"])
        metadata = notebook["metadata"]["bw_migration"]
        self.assertEqual(metadata["lakehouse_binding"], "unbound")
        self.assertEqual(metadata["rule_coverage"], "declared_complete")
        self.assertEqual(metadata["source_evidence"]["definition_sha256_check"], "not_run")
        self.assertEqual(metadata["source_evidence"]["plan_vs_declared_ledger"], "not_run")
        self.assertIsNone(metadata["source_evidence"]["ledger_canonical_sha256"])
        self.assertEqual(metadata["rule_counts"], {
            "transfer": 3, "constant": 1, "decimal_add": 1, "decimal_subtract": 1,
        })
        for field in (
            "execution_status", "source_golden_case_execution", "target_golden_case_execution",
            "semantic_equivalence", "business_approval",
        ):
            self.assertEqual(metadata[field], "not_run")
        self.assertNotIn("dependencies", notebook["metadata"])
        for cell in notebook["cells"]:
            self.assertTrue(cell["id"])
            self.assertTrue(all(line.endswith("\n") for line in cell["source"]))
            if cell["cell_type"] == "code":
                self.assertIsNone(cell["execution_count"])
                self.assertEqual(cell["outputs"], [])
                ast.parse("".join(cell["source"]))

        schema = json.loads(
            (ROOT / "docs" / "schemas" / "sap_bw_conversion_plan.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["$id"], "urn:bo-to-powerbi:schema:sap-bw-conversion-plan:1.0")
        self.assertEqual(set(schema["required"]), set(plan))
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0")

    def test_source_definition_and_declared_ledger_are_checked_before_generation(self):
        notebook = self._notebook(
            definition_file=self.definition_file, rule_ledger=self.rule_ledger_file
        )
        evidence = notebook["metadata"]["bw_migration"]["source_evidence"]
        canonical = json.dumps(
            self.rule_ledger, ensure_ascii=True, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("ascii")
        self.assertEqual(hashlib.sha256(self.definition_file.read_bytes()).hexdigest(), self.plan["definition_sha256"])
        self.assertEqual(evidence["definition_sha256_check"], "pass")
        self.assertEqual(evidence["plan_vs_declared_ledger"], "pass")
        self.assertEqual(evidence["ledger_canonical_sha256"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(evidence["ledger_rule_count"], len(self.plan["rules"]))
        self.assertEqual(evidence["source_definition_authenticity"], "not_verified")
        self.assertEqual(evidence["ledger_source_correspondence"], "not_verified")
        self.assertEqual(evidence["source_owner_approval"], "not_run")
        self.assertEqual(notebook["metadata"]["bw_migration"]["rule_coverage"], "declared_complete")
        self.assertEqual(notebook["cells"], self._notebook()["cells"])
        rendered = json.dumps(notebook, ensure_ascii=True)
        self.assertNotIn(str(self.definition_file), rendered)
        self.assertNotIn(str(self.rule_ledger_file), rendered)
        self.assertNotIn("NOT A SAP EXPORT", rendered)
        spark = self._spark()
        _execute_conversion_notebook(notebook, spark)
        self.assertEqual(spark.tables[self.plan["target_table"]].rows[0]["net_amount"], Decimal("11.14"))

        schema = json.loads(
            (ROOT / "docs" / "schemas" / "sap_bw_source_rules.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["$id"], "urn:bo-to-powerbi:schema:sap-bw-source-rules:1.0")
        self.assertEqual(set(schema["required"]), set(self.rule_ledger))

    def test_ledger_and_input_order_do_not_change_matching_semantics(self):
        ledger = copy.deepcopy(self.rule_ledger)
        ledger["input_columns"].reverse()
        ledger["rules"].reverse()
        notebook = self._notebook_with_source_ledger(ledger)
        self.assertEqual(
            notebook["metadata"]["bw_migration"]["source_evidence"]["plan_vs_declared_ledger"],
            "pass",
        )
        self.assertEqual(notebook["cells"], self._notebook()["cells"])

    def test_legacy_plan_without_source_rule_ids_remains_declaration_only(self):
        plan = copy.deepcopy(self.plan)
        for rule in plan["rules"]:
            rule.pop("source_rule_id")
        notebook = self._notebook(plan)
        self.assertEqual(notebook["metadata"]["bw_migration"]["source_evidence"]["definition_sha256_check"], "not_run")
        with self.assertRaisesRegex(BWTransformConversionError, "source_rule_id"):
            self._notebook(plan, definition_file=self.definition_file, rule_ledger=self.rule_ledger_file)

    def test_rule_identity_must_match_its_declared_semantics(self):
        ledger = copy.deepcopy(self.rule_ledger)
        first_id = ledger["rules"][0]["source_rule_id"]
        second_id = ledger["rules"][1]["source_rule_id"]
        ledger["rules"][0]["source_rule_id"] = second_id
        ledger["rules"][1]["source_rule_id"] = first_id
        with self.assertRaisesRegex(BWTransformConversionError, "mappings differ"):
            self._notebook_with_source_ledger(ledger)

        plan = copy.deepcopy(self.plan)
        plan["rules"][0]["source_rule_id"] = "RULE-OTHER"
        with self.assertRaisesRegex(BWTransformConversionError, "source rules are missing"):
            self._notebook(plan, definition_file=self.definition_file, rule_ledger=self.rule_ledger_file)

        plan["rules"][0]["source_rule_id"] = "rule-002"
        with self.assertRaisesRegex(BWTransformConversionError, "unique ignoring case"):
            self._notebook(plan)

    def test_source_rule_ledger_rejects_mismatches_and_unsupported_rules(self):
        def append_extra_rule(ledger):
            entry = copy.deepcopy(ledger["rules"][5])
            entry["source_rule_id"] = "RULE-EXTRA"
            entry["mapping"]["target"] = "extra_target"
            ledger["rules"].append(entry)

        mutations = (
            lambda x: x.update({"schema_version": "2.0"}),
            lambda x: x.update({"inventory_run_id": "different-run"}),
            lambda x: x.update({"transformation_object_id": "different-transformation"}),
            lambda x: x.update({"definition_reference": "different-reference"}),
            lambda x: x.update({"definition_sha256": "f" * 64}),
            lambda x: x.update({"rule_coverage": "partial"}),
            lambda x: x.update({"unexpected": "field"}),
            lambda x: x.pop("input_columns"),
            lambda x: x["input_columns"].append({"name": "another", "spark_type": "string"}),
            lambda x: x["rules"].pop(0),
            append_extra_rule,
            lambda x: x["rules"][0]["mapping"].update({"source": "Région"}),
            lambda x: x["rules"][0]["mapping"].update({"kind": "abap_routine"}),
            lambda x: x["rules"][0]["mapping"].update({"unknown": "field"}),
            lambda x: x["rules"][0].update({"source_rule_id": ""}),
            lambda x: x["rules"][0].update({"source_rule_id": "RULE-OTHER"}),
            lambda x: x["rules"][1].update({"source_rule_id": "rule-001"}),
            lambda x: x["rules"][1]["mapping"].update({"target": "SALE_ID"}),
            lambda x: x["rules"][0]["mapping"].update({"source_rule_id": "RULE-001"}),
            lambda x: x["rules"][0].update({"mapping": None}),
            lambda x: x["rules"][0].update({"source_rule_id": "password=synthetic-secret"}),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                ledger = copy.deepcopy(self.rule_ledger)
                mutate(ledger)
                with self.assertRaises(BWTransformConversionError) as error:
                    self._notebook_with_source_ledger(ledger)
                self.assertNotIn("synthetic-secret", str(error.exception))

    def test_definition_bytes_and_ledger_are_required_together(self):
        for definition_file, rule_ledger in (
            (self.definition_file, None), (None, self.rule_ledger_file),
        ):
            with self.subTest(definition_file=definition_file, rule_ledger=rule_ledger):
                with self.assertRaisesRegex(BWTransformConversionError, "requires both"):
                    self._notebook(definition_file=definition_file, rule_ledger=rule_ledger)

        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / "definition.bin"
            wrong.write_bytes(self.definition_file.read_bytes() + b"x")
            with self.assertRaisesRegex(BWTransformConversionError, "SHA-256"):
                self._notebook(definition_file=wrong, rule_ledger=self.rule_ledger_file)
            with self.assertRaisesRegex(BWTransformConversionError, "cannot read"):
                self._notebook(definition_file=Path(directory) / "missing", rule_ledger=self.rule_ledger_file)
            with self.assertRaisesRegex(BWTransformConversionError, "cannot load"):
                self._notebook(definition_file=self.definition_file, rule_ledger=Path(directory) / "missing")

    def test_definition_hash_handles_large_binary_input_without_embedding_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "definition.bin"
            payload = bytes(range(256)) * 8193
            path.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            inventory = copy.deepcopy(self.inventory)
            plan = copy.deepcopy(self.plan)
            ledger = copy.deepcopy(self.rule_ledger)
            inventory["objects"][1]["definition"]["hash"] = digest
            plan["definition_sha256"] = digest
            ledger["definition_sha256"] = digest.upper()
            ledger_path = Path(directory) / "ledger.json"
            ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
            notebook = self._notebook(plan, inventory, definition_file=path, rule_ledger=ledger_path)
            self.assertEqual(notebook["metadata"]["bw_migration"]["source_evidence"]["definition_sha256_check"], "pass")
            self.assertNotIn(str(path), json.dumps(notebook))
            self.assertLess(len(json.dumps(notebook)), len(payload))

    def test_source_rule_ledger_requires_strict_json(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "ledger.json"
            for content in (
                b'{"schema_version":"1.0","schema_version":"1.0"}',
                b'{"bad":NaN}',
                b"\xff",
            ):
                with self.subTest(content=content):
                    ledger_path.write_bytes(content)
                    with self.assertRaisesRegex(BWTransformConversionError, "strict local JSON"):
                        self._notebook(definition_file=self.definition_file, rule_ledger=ledger_path)

    def test_cli_source_evidence_gates_output_and_preserves_existing_files(self):
        fixtures = ROOT / "docs" / "fixtures"
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            output = folder / "conversion.ipynb"
            command = [
                sys.executable, str(ROOT / "migrate_bw_convert.py"),
                "--inventory", str(fixtures / "sap_bw_conversion_inventory.example.json"),
                "--transformation", str(fixtures / "sap_bw_conversion_plan.example.json"),
                "--definition-file", str(self.definition_file),
                "--rule-ledger", str(self.rule_ledger_file),
                "--output", str(output),
            ]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("plan-to-declared-ledger checks passed", result.stdout)
            self.assertIn("source-rule completeness remain unverified", result.stdout)
            emitted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(emitted["metadata"]["bw_migration"]["source_evidence"]["definition_sha256_check"], "pass")
            original = output.read_bytes()
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(output.read_bytes(), original)

            bad_definition = folder / "bad.bin"
            bad_definition.write_bytes(b"synthetic mismatching definition")
            invalid_output = folder / "invalid.ipynb"
            command[command.index("--definition-file") + 1] = str(bad_definition)
            command[command.index("--output") + 1] = str(invalid_output)
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 2)
            self.assertIn("SHA-256", result.stderr)
            self.assertFalse(invalid_output.exists())

            mismatched_ledger = copy.deepcopy(self.rule_ledger)
            mismatched_ledger["rules"].pop()
            bad_ledger_path = folder / "mismatched-ledger.json"
            bad_ledger_path.write_text(json.dumps(mismatched_ledger, ensure_ascii=False), encoding="utf-8")
            command[command.index("--definition-file") + 1] = str(self.definition_file)
            command[command.index("--rule-ledger") + 1] = str(bad_ledger_path)
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 2)
            self.assertIn("missing from the source-rule ledger", result.stderr)
            self.assertFalse(invalid_output.exists())

            del command[command.index("--rule-ledger"):command.index("--rule-ledger") + 2]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires both", result.stderr)
            self.assertFalse(invalid_output.exists())

    def test_fake_run_preserves_rows_nulls_decimals_and_lineage(self):
        spark = self._spark()
        source_before = copy.deepcopy(spark.tables[self.plan["source_table"]].rows)
        notebook = self._notebook()
        _execute_conversion_notebook(notebook, spark)
        rows = spark.tables[self.plan["target_table"]].rows
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[0]["sale_id"], "1")
        self.assertEqual(rows[0]["region"], "Île / région")
        self.assertEqual(rows[0]["gross_amount"], Decimal("12.34"))
        self.assertEqual(rows[0]["net_amount"], Decimal("11.14"))
        self.assertEqual(rows[0]["difference_amount"], Decimal("13.54"))
        self.assertEqual(rows[0]["source_label"], "BW")
        self.assertIsNone(rows[2]["net_amount"])
        self.assertIsNone(rows[2]["difference_amount"])
        self.assertIsNone(rows[2]["region"])
        self.assertEqual(rows[0]["_bw_object_id"], self.plan["source_object_id"])
        self.assertEqual(rows[0]["_bw_transformation_id"], self.plan["transformation_object_id"])
        self.assertEqual(rows[0]["_bw_target_object_id"], self.plan["target_object_id"])
        self.assertEqual(rows[0]["_bw_transformation_definition_sha256"], self.plan["definition_sha256"])
        self.assertEqual(spark.tables[self.plan["source_table"]].rows, source_before)
        self.assertTrue(spark.persisted[0].released)

        target_before = copy.deepcopy(rows)
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            _execute_conversion_notebook(notebook, spark)
        self.assertEqual(spark.tables[self.plan["target_table"]].rows, target_before)

    def test_quoted_input_identifiers_and_typed_constants(self):
        plan = copy.deepcopy(self.plan)
        unusual = "Région.part/é`x"
        plan["input_columns"][3]["name"] = unusual
        plan["rules"][1]["source"] = unusual
        plan["rules"][1]["target"] = "région"
        plan["rules"][5]["value"] = "BW'); raise RuntimeError('not executed') #"
        plan["rules"].extend([
            {"kind": "constant", "target": "nullable", "spark_type": "string", "value": None},
            {"kind": "constant", "target": "enabled", "spark_type": "boolean", "value": True},
            {"kind": "constant", "target": "number", "spark_type": "int", "value": -(2**31)},
            {"kind": "constant", "target": "large_number", "spark_type": "bigint", "value": 2**63 - 1},
        ])
        spark = self._spark()
        source = spark.tables.pop(self.plan["source_table"])
        fields = [(unusual if name == "Région" else name, kind) for name, kind in source.fields]
        rows = [{(unusual if name == "Région" else name): value for name, value in row.items()} for row in source.rows]
        spark = _BWConversionSpark(plan["source_table"], fields, rows)
        _execute_conversion_notebook(self._notebook(plan), spark)
        row = spark.tables[plan["target_table"]].rows[0]
        self.assertEqual(row["région"], "Île / région")
        self.assertEqual(row["source_label"], plan["rules"][5]["value"])
        self.assertIsNone(row["nullable"])
        self.assertIs(row["enabled"], True)
        self.assertEqual(row["number"], -(2**31))
        self.assertEqual(row["large_number"], 2**63 - 1)

    def test_exact_decimal_constants_and_ledger_mapping(self):
        plan = copy.deepcopy(self.plan)
        mapping = {
            "kind": "constant",
            "target": "tax_amount",
            "spark_type": "decimal(8,2)",
            "value": "12.3400",
        }
        plan["rules"].append({"source_rule_id": "RULE-007", **mapping})
        ledger = copy.deepcopy(self.rule_ledger)
        ledger["rules"].append({"source_rule_id": "RULE-007", "mapping": mapping})

        with tempfile.TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "ledger.json"
            ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
            notebook = self._notebook(
                plan,
                definition_file=self.definition_file,
                rule_ledger=ledger_path,
            )

        evidence = notebook["metadata"]["bw_migration"]["source_evidence"]
        self.assertEqual(evidence["plan_vs_declared_ledger"], "pass")
        spark = self._spark(plan)
        _execute_conversion_notebook(notebook, spark)
        self.assertEqual(
            spark.tables[plan["target_table"]].rows[0]["tax_amount"],
            Decimal("12.34"),
        )

        null_plan = copy.deepcopy(self.plan)
        null_plan["rules"].append({
            "kind": "constant",
            "target": "optional_tax",
            "spark_type": "decimal(8,2)",
            "value": None,
        })
        null_spark = self._spark(null_plan)
        _execute_conversion_notebook(self._notebook(null_plan), null_spark)
        self.assertIsNone(null_spark.tables[null_plan["target_table"]].rows[0]["optional_tax"])

    def test_zero_decimal_constants_fit_when_precision_equals_scale(self):
        for value in ("0", "0.0", "0.0000", "-0.00", "0.01", "-0.99"):
            with self.subTest(value=value):
                plan = copy.deepcopy(self.plan)
                plan["rules"].append({
                    "kind": "constant",
                    "target": "fractional_constant",
                    "spark_type": "decimal(2,2)",
                    "value": value,
                })
                spark = self._spark(plan)
                _execute_conversion_notebook(self._notebook(plan), spark)
                actual = spark.tables[plan["target_table"]].rows[0]["fractional_constant"]
                self.assertEqual(actual, Decimal(value))

        for value in ("1", "0.001"):
            with self.subTest(value=value):
                plan = copy.deepcopy(self.plan)
                plan["rules"].append({
                    "kind": "constant",
                    "target": "fractional_constant",
                    "spark_type": "decimal(2,2)",
                    "value": value,
                })
                with self.assertRaises(BWTransformConversionError):
                    self._notebook(plan)

    def test_decimal_precision_boundary_does_not_round_or_lose_sign(self):
        plan = copy.deepcopy(self.plan)
        plan["input_columns"][1]["spark_type"] = "decimal(37,2)"
        plan["input_columns"][2]["spark_type"] = "decimal(37,2)"
        plan["rules"][2]["spark_type"] = "decimal(37,2)"
        plan["rules"][3]["spark_type"] = "decimal(38,2)"
        plan["rules"][4]["spark_type"] = "decimal(38,2)"
        spark = self._spark(plan)
        source = spark.tables[plan["source_table"]]
        maximum = Decimal("9" * 35 + ".99")
        source.rows[0]["Montant"] = maximum
        source.rows[0]["Ajustement"] = maximum
        source.rows[1]["Montant"] = maximum
        source.rows[1]["Ajustement"] = maximum.copy_negate()
        with localcontext() as context:
            context.prec = 50
            _execute_conversion_notebook(self._notebook(plan), spark)
            rows = spark.tables[plan["target_table"]].rows
            self.assertEqual(rows[0]["net_amount"], maximum + maximum)
            self.assertEqual(rows[0]["difference_amount"], Decimal("0.00"))
            self.assertEqual(rows[1]["net_amount"], Decimal("0.00"))
            self.assertEqual(rows[1]["difference_amount"], maximum + maximum)
            self.assertIsNone(rows[2]["net_amount"])
        self.assertIn(
            ("net_amount", "decimal(38,2)"),
            spark.tables[plan["target_table"]].fields,
        )

    def test_synthetic_converted_values_can_be_submitted_to_vector_comparator(self):
        vectors = json.loads(
            (
                ROOT / "docs" / "fixtures"
                / "sap_bw_conversion_vectors.example.json"
            ).read_text(encoding="utf-8")
        )
        cases = vectors["cases"]
        lineage = {
            "_bw_source_system_id": self.inventory["source_system"]["id"],
            "_bw_object_id": self.plan["source_object_id"],
            "_bw_snapshot_id": self.plan["source_snapshot_id"],
            "_bw_snapshot_cutoff_utc": self.plan["source_snapshot_cutoff_utc"],
            "_bw_source_file": "synthetic-staged-file",
            "_bw_ingested_at": "synthetic-timestamp",
        }
        input_types = {
            column["name"]: column["spark_type"]
            for column in self.plan["input_columns"]
        }
        source_rows = []
        for case in cases:
            row = dict(case["input"])
            for name, value in row.items():
                if input_types[name].startswith("decimal("):
                    row[name] = Decimal(value)
            source_rows.append({**row, **lineage})
        # The conversion plan declares three source rows; the comparator fixture
        # intentionally covers two, so include one non-vector filler row.
        source_rows.append(copy.deepcopy(source_rows[0]))

        spark = self._spark(rows=source_rows)
        _execute_conversion_notebook(self._notebook(), spark)
        generated_rows = spark.tables[self.plan["target_table"]].rows
        output_targets = [rule["target"] for rule in self.plan["rules"]]
        self.assertEqual(len(generated_rows), self.plan["expected_rows"])
        for case, generated in zip(cases, generated_rows):
            # Poison the declarations in our manifest copy: the comparator inputs
            # below must come from executing the generated notebook, not these values.
            case["target_output"] = {
                target: "fixture declaration must not be reused"
                for target in output_targets
            }
            generated_output = {
                target: (
                    str(generated[target])
                    if isinstance(generated[target], Decimal)
                    else generated[target]
                )
                for target in output_targets
            }
            self.assertNotEqual(generated_output, case["target_output"])
            case["target_output"] = generated_output
            self.assertEqual(
                case["target_output"],
                {
                    target: (
                        str(generated[target])
                        if isinstance(generated[target], Decimal)
                        else generated[target]
                    )
                    for target in output_targets
                },
            )

        report = compare_transform_vectors(vectors, conversion_plan=self.plan)
        self.assertEqual(report["comparison_status"], "pass")
        self.assertEqual(report["conversion_plan_linkage"], "pass")
        self.assertEqual(
            report["runtime_evidence"]["target_transformation_execution"],
            "not_run",
        )

    def test_fake_run_fails_closed_and_releases_cache(self):
        notebook = self._notebook()
        for kind in ("row_count", "null_lineage", "wrong_lineage", "output_type", "write"):
            with self.subTest(kind=kind):
                spark = self._spark()
                source = spark.tables[self.plan["source_table"]]
                if kind == "row_count":
                    source.rows.pop()
                elif kind == "null_lineage":
                    source.rows[0]["_bw_snapshot_id"] = None
                elif kind == "wrong_lineage":
                    source.rows[1]["_bw_source_system_id"] = "another-system"
                elif kind == "output_type":
                    spark.corrupt_output_type = True
                else:
                    spark.fail_write = True
                with self.assertRaises((ValueError, RuntimeError)):
                    _execute_conversion_notebook(notebook, spark)
                self.assertNotIn(self.plan["target_table"], spark.tables)
                self.assertTrue(spark.persisted[0].released)

        spark = self._spark()
        source = spark.tables[self.plan["source_table"]]
        source.fields[1] = ("Montant", "double")
        spark.tables[self.plan["source_table"]] = _BWConversionFrame(spark, source.fields, source.rows)
        with self.assertRaisesRegex(ValueError, "schema"):
            _execute_conversion_notebook(notebook, spark)
        self.assertNotIn(self.plan["target_table"], spark.tables)
        self.assertEqual(spark.persisted, [])

        spark = self._spark()
        spark.corrupt_target_count = True
        with self.assertRaisesRegex(RuntimeError, "investigate"):
            _execute_conversion_notebook(notebook, spark)
        self.assertIn(self.plan["target_table"], spark.tables)
        self.assertTrue(spark.persisted[0].released)

    def test_empty_snapshot_is_allowed_but_contains_no_row_level_lineage(self):
        plan = copy.deepcopy(self.plan)
        plan["expected_rows"] = 0
        spark = self._spark(plan, rows=[])
        _execute_conversion_notebook(self._notebook(plan), spark)
        self.assertEqual(spark.tables[plan["target_table"]].rows, [])
        self.assertTrue(spark.persisted[0].released)

    def test_rejects_unsupported_or_ambiguous_plan_rules(self):
        invalid = []
        for field, value in (
            ("schema_version", "2.0"), ("inventory_run_id", "another-run"),
            ("rule_coverage", "partial"), ("expected_rows", True), ("expected_rows", -1),
            ("source_snapshot_cutoff_utc", "2026-10-31"),
            ("source_snapshot_cutoff_utc", "2026-10-31T23:59:59+01:00"),
            ("source_table", "bronze.x;DROP TABLE x"), ("target_table", "bronze.synthetic_sales_history"),
            ("definition_sha256", "bad-hash"), ("dtp_object_id", []),
            ("input_columns", []), ("rules", []),
        ):
            plan = copy.deepcopy(self.plan)
            plan[field] = value
            invalid.append(plan)
        for mutate in (
            lambda p: p.update({"unexpected": "field"}),
            lambda p: p["input_columns"].append({"name": "venteid", "spark_type": "string"}),
            lambda p: p["input_columns"].append({"name": "_BW_OBJECT_ID", "spark_type": "string"}),
            lambda p: p["input_columns"][1].update({"spark_type": "decimal(39,2)"}),
            lambda p: p["rules"][0].update({"kind": "abap"}),
            lambda p: p["rules"][0].update({"kind": []}),
            lambda p: p["rules"][0].update({"source": "not_declared"}),
            lambda p: p["rules"][0].update({"spark_type": "int"}),
            lambda p: p["rules"][1].update({"target": "SALE_ID"}),
            lambda p: p["rules"][1].update({"target": "_bw_object_id"}),
            lambda p: p["rules"][1].update({"target": "target with spaces"}),
            lambda p: p["rules"][3].update({"spark_type": "decimal(15,2)"}),
            lambda p: p["rules"][3].update({"null_policy": "zero"}),
            lambda p: p["input_columns"][2].update({"spark_type": "decimal(15,3)"}),
            lambda p: p["input_columns"][1].update({"spark_type": "decimal(38,2)"}),
            lambda p: p["rules"][5].update({"spark_type": "int", "value": 2**31}),
            lambda p: p["rules"][5].update({"spark_type": "bigint", "value": 2**63}),
            lambda p: p["rules"][5].update({"spark_type": "int", "value": True}),
            lambda p: p["rules"][5].update({"spark_type": "double", "value": 1.5}),
            lambda p: p["rules"][5].update({"spark_type": "decimal(6,2)", "value": "1.234"}),
            lambda p: p["rules"][5].update({"spark_type": "decimal(5,2)", "value": "1000"}),
            lambda p: p["rules"][5].update({"spark_type": "decimal(6,2)", "value": 1}),
            lambda p: p["rules"][5].update({"value": "password=synthetic-secret"}),
        ):
            plan = copy.deepcopy(self.plan)
            mutate(plan)
            invalid.append(plan)
        for index, plan in enumerate(invalid):
            with self.subTest(index=index):
                with self.assertRaises(BWTransformConversionError):
                    self._notebook(plan)

    def test_rejects_unobserved_lineage_unsupported_features_and_routines(self):
        for mutate in (
            lambda i: i["objects"][1]["migration_decision"].update({"classification": "blocked"}),
            lambda i: i["objects"][1]["migration_decision"].update({"classification": "unknown"}),
            lambda i: i["objects"][1].update({"metadata_status": "unknown"}),
            lambda i: i["objects"][1]["semantics"].update({"status": "unknown"}),
            lambda i: i["objects"][1]["semantics"]["measures"].append(
                {"name": "unknown measure", "data_type": "decimal", "status": "unknown", "details": None}
            ),
            lambda i: i["objects"][1]["semantics"]["functions"].append(
                {"name": "synthetic routine", "data_type": "ABAP", "status": "unknown", "details": None}
            ),
            lambda i: i["objects"][1]["definition"].update({"status": "unknown"}),
            lambda i: i["objects"][1]["definition"].update({"hash": "f" * 64}),
            lambda i: i["objects"][0].update({"discovery_status": "inferred"}),
            lambda i: i["objects"][2].update({"type": "process_chain"}),
            lambda i: i["objects"][3].update({"disposition": "out_of_scope"}),
            lambda i: i["dependencies"].pop(0),
            lambda i: i["dependencies"][0].update({"evidence_status": "inferred"}),
            lambda i: i["dependencies"][1].update({"resolution_status": "unresolved"}),
            lambda i: i["dependencies"].append({
                "source_id": "unresolved-other-input",
                "target_id": self.plan["transformation_object_id"],
                "kind": "transforms", "evidence_status": "unknown",
                "resolution_status": "unresolved", "evidence_reference": None,
            }),
            lambda i: i["unknowns"].append({
                "id": "selected-unknown", "path": f"objects[{self.plan['transformation_object_id']}].semantics",
                "reason": "Synthetic unknown routine", "status": "unknown", "owner": "synthetic-owner",
            }),
            lambda i: i["unknowns"].append({
                "id": "selected-index", "path": "$.objects[1].semantics",
                "reason": "Synthetic unknown routine", "status": "unknown", "owner": "synthetic-owner",
            }),
            lambda i: i["unknowns"].append({
                "id": "global-unknown", "path": "$.objects[*].semantics",
                "reason": "Unscoped unknown", "status": "unknown", "owner": "synthetic-owner",
            }),
            lambda i: i["unknowns"].append({
                "id": "oversized-index", "path": "objects[" + "9" * 5000 + "].semantics",
                "reason": "Invalid object scope", "status": "unknown", "owner": "synthetic-owner",
            }),
            lambda i: i["errors"].append({
                "code": "synthetic-discovery-error", "category": "discovery", "status": "unknown",
                "message": "Synthetic inventory discovery error", "evidence_reference": None,
            }),
            lambda i: i["unsupported_features"].append({
                "id": "unknown-routine", "object_id": self.plan["transformation_object_id"],
                "category": "abap_routine", "name": "synthetic routine",
                "support_status": "unknown", "impact": "unknown", "description": None,
                "conversion_status": "not_run", "evidence_reference": None,
            }),
            lambda i: i["unsupported_features"].append({
                "id": "claimed-supported-routine", "object_id": self.plan["transformation_object_id"],
                "category": "abap_routine", "name": "synthetic routine",
                "support_status": "supported", "impact": "high", "description": None,
                "conversion_status": "not_run", "evidence_reference": None,
            }),
            lambda i: (
                i["objects"][1]["migration_decision"].update({"classification": "manual_redesign"}),
                i["unsupported_features"].append({
                    "id": "unsupported-lookup", "object_id": self.plan["transformation_object_id"],
                    "category": "other", "name": "synthetic lookup", "support_status": "unsupported",
                    "impact": "high", "description": None, "conversion_status": "not_run",
                    "evidence_reference": None,
                }),
            ),
        ):
            inventory = copy.deepcopy(self.inventory)
            mutate(inventory)
            with self.subTest(inventory=inventory):
                with self.assertRaises((BWTransformConversionError, BWInventoryError)):
                    self._notebook(inventory=inventory)

    def test_unrelated_object_unknown_is_reported_without_blocking_the_selected_chain(self):
        inventory = copy.deepcopy(self.inventory)
        unrelated = copy.deepcopy(inventory["objects"][0])
        unrelated["id"] = "SYNTHETIC-BW-01:ADSO:OTHER"
        inventory["objects"].append(unrelated)
        inventory["unknowns"].append({
            "id": "unrelated-unknown", "path": f"objects[{unrelated['id']}].semantics",
            "reason": "Unrelated synthetic unknown", "status": "unknown", "owner": "synthetic-owner",
        })
        notebook = self._notebook(inventory=inventory)
        self.assertEqual(notebook["metadata"]["bw_migration"]["inventory_unknowns"], 1)

    def test_selected_objects_with_declared_functions_are_rejected(self):
        for index in range(4):
            for status in ("observed", "unknown"):
                with self.subTest(object_index=index, status=status):
                    inventory = copy.deepcopy(self.inventory)
                    inventory["objects"][index]["semantics"]["functions"].append({
                        "name": "synthetic routine", "data_type": "ABAP",
                        "status": status, "details": None,
                    })
                    with self.assertRaisesRegex(BWTransformConversionError, "declared functions"):
                        self._notebook(inventory=inventory)

    def test_additional_incoming_transformation_dependencies_are_rejected(self):
        kinds = (
            "feeds", "transforms", "scheduled_by", "queries",
            "consumes", "secured_by", "plans", "other",
        )
        for kind in kinds:
            for resolution in ("resolved", "unresolved"):
                with self.subTest(kind=kind, resolution=resolution):
                    inventory = copy.deepcopy(self.inventory)
                    other = copy.deepcopy(inventory["objects"][0])
                    other["id"] = "SYNTHETIC-BW-01:ADSO:OTHER"
                    inventory["objects"].append(other)
                    inventory["dependencies"].append({
                        "source_id": other["id"],
                        "target_id": self.plan["transformation_object_id"],
                        "kind": kind, "evidence_status": "observed",
                        "resolution_status": resolution, "evidence_reference": "synthetic edge",
                    })
                    with self.assertRaisesRegex(BWTransformConversionError, "additional incoming"):
                        self._notebook(inventory=inventory)

        inventory = copy.deepcopy(self.inventory)
        inventory["dependencies"].append({
            "source_id": self.plan["source_object_id"],
            "target_id": self.plan["transformation_object_id"],
            "kind": "feeds", "evidence_status": "observed",
            "resolution_status": "resolved", "evidence_reference": "synthetic edge",
        })
        with self.assertRaisesRegex(BWTransformConversionError, "additional incoming"):
            self._notebook(inventory=inventory)

    def test_numeric_unknown_path_must_not_ambiguously_name_two_unrelated_objects(self):
        inventory = copy.deepcopy(self.inventory)
        first = copy.deepcopy(inventory["objects"][0])
        first["id"] = "5"
        second = copy.deepcopy(first)
        second["id"] = "SYNTHETIC-BW-01:ADSO:OTHER"
        inventory["objects"].extend([first, second])
        inventory["unknowns"].append({
            "id": "ambiguous-unknown", "path": "objects[5].semantics",
            "reason": "Ambiguous synthetic object scope", "status": "unknown", "owner": "synthetic-owner",
        })
        with self.assertRaisesRegex(BWTransformConversionError, "ambiguous"):
            self._notebook(inventory=inventory)

    def test_direct_lineage_without_a_dtp_is_supported_when_observed(self):
        plan = copy.deepcopy(self.plan)
        plan["dtp_object_id"] = None
        inventory = copy.deepcopy(self.inventory)
        inventory["dependencies"].append({
            "source_id": plan["transformation_object_id"], "target_id": plan["target_object_id"],
            "kind": "transforms", "evidence_status": "observed",
            "resolution_status": "resolved", "evidence_reference": "synthetic edge",
        })
        notebook = self._notebook(plan, inventory)
        self.assertIsNone(notebook["metadata"]["bw_migration"]["dtp_object_id"])

    def test_cli_writes_new_notebook_and_refuses_partial_or_duplicate_input(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            inventory = folder / "inventory.json"
            plan = folder / "plan.json"
            output = folder / "conversion.ipynb"
            inventory.write_text(json.dumps(self.inventory, ensure_ascii=False), encoding="utf-8")
            plan.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")
            command = [
                sys.executable, str(ROOT / "migrate_bw_convert.py"), "--inventory", str(inventory),
                "--transformation", str(plan), "--output", str(output),
            ]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            emitted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(emitted["metadata"]["bw_migration"]["semantic_equivalence"], "not_run")
            original = output.read_bytes()
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(output.read_bytes(), original)

            other_output = folder / "invalid.ipynb"
            command[-1] = str(other_output)
            invalid = copy.deepcopy(self.plan)
            invalid["rules"][0]["kind"] = "abap"
            plan.write_text(json.dumps(invalid), encoding="utf-8")
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 2)
            self.assertIn("unsupported", result.stderr)
            self.assertFalse(other_output.exists())

            plan.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 2)
            self.assertIn("Unable to load", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(other_output.exists())


if __name__ == "__main__":
    unittest.main()
