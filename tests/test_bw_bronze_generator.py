"""Local contract and notebook-behavior tests for BW historical landing."""

import ast
import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from powerbi_import.bw_bronze_generator import BWBronzeError, build_bw_bronze_notebook


ROOT = Path(__file__).resolve().parents[1]


class _FakeType:
    def __init__(self, value):
        self.value = value

    def simpleString(self):
        return self.value


class _FakeFrame:
    def __init__(self, spark, fields, rows, resolved_files=None):
        self.spark = spark
        self.fields = list(fields)
        self.rows = [dict(row) for row in rows]
        self.resolved_files = resolved_files or []
        self.schema = types.SimpleNamespace(fields=[
            types.SimpleNamespace(name=name, dataType=_FakeType(data_type))
            for name, data_type in self.fields
        ])
        self.released = False

    def withColumn(self, name, value):
        fields = self.fields
        rows = self.rows
        if self.spark.replace_unicode_collision and name == "_bw_object_id":
            fields = [(key, kind) for key, kind in fields if key != "_bw_object_İd"]
            rows = [{key: value for key, value in row.items() if key != "_bw_object_İd"} for row in rows]
        result = _FakeFrame(
            self.spark, fields + [(name, "timestamp" if name == "_bw_ingested_at" else "string")],
            [{**row, name: value} for row in rows],
        )
        return result

    def unionByName(self, other):
        return _FakeFrame(self.spark, self.fields, self.rows + other.rows)

    def persist(self, level):
        self.spark.persisted.append(self)
        return self

    def unpersist(self):
        self.released = True

    def count(self):
        if self is self.spark.count_override_frame:
            return len(self.rows) + 1
        return len(self.rows)

    def inputFiles(self):
        return list(self.resolved_files)

    @property
    def write(self):
        return _FakeWriter(self.spark, self)


class _FakeWriter:
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
            raise AssertionError("Unexpected writer mode")
        if self.spark.fail_write:
            raise RuntimeError("Synthetic write failure")
        if target in self.spark.tables:
            raise RuntimeError("Target already exists")
        self.spark.tables[target] = _FakeFrame(
            self.spark, self.frame.fields, self.frame.rows
        )
        if self.spark.corrupt_target_count:
            self.spark.count_override_frame = self.spark.tables[target]


class _FakeReader:
    def __init__(self, spark):
        self.spark = spark

    def format(self, value):
        if value != "parquet":
            raise AssertionError("Unexpected source format")
        return self

    def load(self, source):
        fields, rows = self.spark.sources[source]
        return _FakeFrame(self.spark, fields, rows, self.spark.resolved_files.get(source, [source]))


class _FakeSpark:
    def __init__(self, sources):
        self.sources = sources
        self.resolved_files = {}
        self.tables = {}
        self.persisted = []
        self.fail_write = False
        self.corrupt_target_count = False
        self.replace_unicode_collision = False
        self.count_override_frame = None
        self.catalog = types.SimpleNamespace(tableExists=lambda name: name in self.tables)
        self.read = _FakeReader(self)

    def table(self, name):
        return self.tables[name]


def _execute_notebook(notebook, spark):
    fake_pyspark = types.ModuleType("pyspark")
    fake_pyspark.StorageLevel = types.SimpleNamespace(DISK_ONLY="disk")
    fake_sql = types.ModuleType("pyspark.sql")
    fake_sql.functions = types.SimpleNamespace(
        lit=lambda value: value,
        current_timestamp=lambda: "synthetic-ingestion-time",
    )
    fake_pyspark.sql = fake_sql
    code = "".join(notebook["cells"][1]["source"])
    with patch.dict(sys.modules, {"pyspark": fake_pyspark, "pyspark.sql": fake_sql}):
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(code, "<bw-notebook>", "exec"), {"spark": spark})


class TestBWBronzeGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads(
            (ROOT / "docs" / "fixtures" / "sap_bw_inventory.partial.example.json")
            .read_text(encoding="utf-8")
        )
        cls.plan = json.loads(
            (ROOT / "docs" / "fixtures" / "sap_bw_bronze_plan.example.json")
            .read_text(encoding="utf-8")
        )
        cls.fields = [
            ("VenteID", "string"), ("Montant", "decimal(15,2)"), ("Région", "string")
        ]

    def _notebook(self, plan=None, inventory=None):
        return build_bw_bronze_notebook(
            copy.deepcopy(self.inventory if inventory is None else inventory),
            copy.deepcopy(self.plan if plan is None else plan),
        )

    def test_notebook_is_unbound_valid_python_and_preserves_input(self):
        inventory = copy.deepcopy(self.inventory)
        plan = copy.deepcopy(self.plan)
        original_inventory, original_plan = copy.deepcopy(inventory), copy.deepcopy(plan)
        notebook = build_bw_bronze_notebook(inventory, plan)

        self.assertEqual(inventory, original_inventory)
        self.assertEqual(plan, original_plan)
        self.assertEqual(notebook["nbformat"], 4)
        metadata = notebook["metadata"]["bw_migration"]
        self.assertEqual(metadata["lakehouse_binding"], "unbound")
        self.assertEqual(metadata["execution_status"], "not_run")
        self.assertEqual(metadata["bw_reconciliation_status"], "not_run")
        self.assertGreater(metadata["inventory_unknowns"], 0)
        self.assertGreater(metadata["unresolved_features"], 0)
        self.assertNotIn("dependencies", notebook["metadata"])
        for cell in notebook["cells"]:
            self.assertTrue(cell["id"])
            self.assertTrue(all(line.endswith("\n") for line in cell["source"]))
            if cell["cell_type"] == "code":
                self.assertIsNone(cell["execution_count"])
                self.assertEqual(cell["outputs"], [])
                ast.parse("".join(cell["source"]))

    def test_fake_run_preserves_duplicates_nulls_lineage_and_refuses_replay(self):
        plan = copy.deepcopy(self.plan)
        plan["source_files"].append("Files/bw_history/synthetic_sales/part-00001.parquet")
        plan["snapshot_id"] = "run'); raise RuntimeError('not executed') #"
        rows = [
            {"VenteID": "1", "Montant": "12.00", "Région": "Été"},
            {"VenteID": "1", "Montant": "12.00", "Région": "Été"},
            {"VenteID": "2", "Montant": None, "Région": None},
        ]
        spark = _FakeSpark({
            plan["source_files"][0]: (self.fields, rows[:2]),
            plan["source_files"][1]: (list(reversed(self.fields)), rows[2:]),
        })
        resolved_file = "abfss://synthetic-lakehouse/Files/part-00001.parquet"
        spark.resolved_files[plan["source_files"][1]] = [resolved_file]
        notebook = self._notebook(plan)
        _execute_notebook(notebook, spark)
        landed = spark.tables[plan["target_table"]].rows
        self.assertEqual(len(landed), 3)
        self.assertEqual(landed[0], landed[1])
        self.assertIsNone(landed[2]["Montant"])
        self.assertEqual(landed[0]["_bw_snapshot_id"], plan["snapshot_id"])
        self.assertEqual(landed[0]["_bw_object_id"], plan["source_object_id"])
        self.assertEqual(landed[2]["_bw_source_file"], resolved_file)
        self.assertTrue(spark.persisted[0].released)

        before = copy.deepcopy(landed)
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            _execute_notebook(notebook, spark)
        self.assertEqual(spark.tables[plan["target_table"]].rows, before)

    def test_fake_run_rejects_mismatches_before_writing_and_releases_cache(self):
        notebook = self._notebook()
        file_path = self.plan["source_files"][0]
        spark = _FakeSpark({file_path: (self.fields, [{"VenteID": "1"}])})
        with self.assertRaisesRegex(RuntimeError, "row count"):
            _execute_notebook(notebook, spark)
        self.assertEqual(spark.tables, {})
        self.assertTrue(spark.persisted[0].released)

        bad_fields = [("VenteID", "string"), ("Montant", "double"), ("Région", "string")]
        spark = _FakeSpark({file_path: (bad_fields, [])})
        with self.assertRaisesRegex(ValueError, "schema"):
            _execute_notebook(notebook, spark)
        self.assertEqual(spark.tables, {})

    def test_fake_run_handles_empty_snapshot_and_explicit_write_failures(self):
        plan = copy.deepcopy(self.plan)
        plan["expected_rows"] = 0
        spark = _FakeSpark({plan["source_files"][0]: (self.fields, [])})
        _execute_notebook(self._notebook(plan), spark)
        self.assertEqual(spark.tables[plan["target_table"]].rows, [])
        self.assertTrue(spark.persisted[0].released)

        spark = _FakeSpark({plan["source_files"][0]: (self.fields, [])})
        spark.fail_write = True
        with self.assertRaisesRegex(RuntimeError, "Synthetic write failure"):
            _execute_notebook(self._notebook(plan), spark)
        self.assertEqual(spark.tables, {})
        self.assertTrue(spark.persisted[0].released)

        spark = _FakeSpark({plan["source_files"][0]: (self.fields, [])})
        spark.corrupt_target_count = True
        with self.assertRaisesRegex(RuntimeError, "investigate"):
            _execute_notebook(self._notebook(plan), spark)
        self.assertIn(plan["target_table"], spark.tables)
        self.assertTrue(spark.persisted[0].released)

    def test_detects_runtime_unicode_identifier_collision_before_writing(self):
        plan = copy.deepcopy(self.plan)
        plan["expected_rows"] = 1
        plan["expected_columns"].append({"name": "_bw_object_İd", "spark_type": "string"})
        fields = self.fields + [("_bw_object_İd", "string")]
        spark = _FakeSpark({
            plan["source_files"][0]: (fields, [{"_bw_object_İd": "source-value"}]),
        })
        spark.replace_unicode_collision = True
        with self.assertRaisesRegex(ValueError, "collide"):
            _execute_notebook(self._notebook(plan), spark)
        self.assertEqual(spark.tables, {})

    def test_rejects_invalid_plan_fields_types_paths_and_schema(self):
        invalid = []
        for field, value in (
            ("schema_version", "9.0"), ("expected_rows", True),
            ("expected_rows", -1), ("snapshot_cutoff_utc", "2026-10-31"),
            ("snapshot_cutoff_utc", "2026-10-31T23:59:59+01:00"),
            ("target_table", "bronze.target; DROP TABLE bronze.other"),
            ("target_table", "a.b.c"),
            ("source_files", []), ("source_files", ["Files/../secret.parquet"]),
            ("source_files", ["Files/x%2fother.parquet"]),
            ("source_files", ["Files/*.parquet"]),
            ("source_files", ["Files/{a,b}.parquet"]),
            ("source_files", ["Files/{single}.parquet"]),
            ("source_files", ["https://example.test/part.parquet"]),
            ("source_files", ["Files\\part.parquet"]),
            ("source_files", ["Files/folder"]),
            ("expected_columns", []),
        ):
            plan = copy.deepcopy(self.plan)
            plan[field] = value
            invalid.append(plan)
        plan = copy.deepcopy(self.plan)
        plan["source_files"].append(plan["source_files"][0])
        invalid.append(plan)
        plan = copy.deepcopy(self.plan)
        plan["expected_columns"].append({"name": "venteid", "spark_type": "string"})
        invalid.append(plan)
        plan = copy.deepcopy(self.plan)
        plan["expected_columns"].append({"name": "_BW_OBJECT_ID", "spark_type": "string"})
        invalid.append(plan)
        for spark_type in ("decimal(39,2)", "decimal(4,5)", "decimal(4,02)", "array<string>"):
            plan = copy.deepcopy(self.plan)
            plan["expected_columns"][0]["spark_type"] = spark_type
            invalid.append(plan)
        plan = copy.deepcopy(self.plan)
        plan["unexpected"] = True
        invalid.append(plan)
        plan = copy.deepcopy(self.plan)
        plan["snapshot_id"] = "password=not-for-output"
        invalid.append(plan)

        for index, plan in enumerate(invalid):
            with self.subTest(case=index):
                with self.assertRaises(BWBronzeError):
                    self._notebook(plan)

    def test_fake_run_rejects_multiple_resolved_files_and_source_aliases(self):
        plan = copy.deepcopy(self.plan)
        plan["source_files"].append("Files/bw_history/synthetic_sales/part-00001.parquet")
        spark = _FakeSpark({source: (self.fields, []) for source in plan["source_files"]})
        spark.resolved_files[plan["source_files"][0]] = ["physical-a", "physical-b"]
        with self.assertRaisesRegex(ValueError, "one distinct Parquet"):
            _execute_notebook(self._notebook(plan), spark)
        self.assertEqual(spark.tables, {})

        spark.resolved_files = {source: ["same-physical-file"] for source in plan["source_files"]}
        with self.assertRaisesRegex(ValueError, "one distinct Parquet"):
            _execute_notebook(self._notebook(plan), spark)
        self.assertEqual(spark.tables, {})

    def test_requires_an_observed_in_scope_unblocked_provider(self):
        for field, value in (
            ("type", "datasource"), ("disposition", "out_of_scope"),
            ("discovery_status", "inferred"),
        ):
            inventory = copy.deepcopy(self.inventory)
            provider = next(obj for obj in inventory["objects"] if obj["id"] == self.plan["source_object_id"])
            provider[field] = value
            with self.subTest(field=field):
                with self.assertRaises(BWBronzeError):
                    self._notebook(inventory=inventory)
        inventory = copy.deepcopy(self.inventory)
        provider = next(obj for obj in inventory["objects"] if obj["id"] == self.plan["source_object_id"])
        provider["migration_decision"]["classification"] = "blocked"
        with self.assertRaises(BWBronzeError):
            self._notebook(inventory=inventory)
        inventory = copy.deepcopy(self.inventory)
        inventory["unsupported_features"][0]["object_id"] = self.plan["source_object_id"]
        with self.assertRaises(BWBronzeError):
            self._notebook(inventory=inventory)
        plan = copy.deepcopy(self.plan)
        plan["source_object_id"] = "unknown-provider"
        with self.assertRaises(BWBronzeError):
            self._notebook(plan)

    def test_cli_writes_new_notebook_and_never_overwrites_or_accepts_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            inventory = folder / "inventory.json"
            plan = folder / "plan.json"
            output = folder / "landing.ipynb"
            inventory.write_text(json.dumps(self.inventory, ensure_ascii=False), encoding="utf-8")
            plan.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")
            command = [
                sys.executable, str(ROOT / "migrate_bw.py"), "--inventory", str(inventory),
                "--plan", str(plan), "--output", str(output),
            ]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            emitted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(emitted["metadata"]["bw_migration"]["execution_status"], "not_run")
            original = output.read_bytes()
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), original)

            other_output = folder / "invalid.ipynb"
            command[-1] = str(other_output)
            plan.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unable to load", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(other_output.exists())


if __name__ == "__main__":
    unittest.main()
