"""Tests for the experimental, read-only Desktop Intelligence inventory."""

import ctypes
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import migrate_deski_inspect as deski_cli
from bo_export import desktop_intelligence_extractor as deski
from migrate import main as migration_main
from migrate_deski_inspect import main
from migrate_paginated import _mapping_with_extracted_sql, _sql_from_bo_file
from powerbi_import.deski_migration_report import build_deski_migration_report


def _lp(value):
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return len(raw).to_bytes(2, "little") + raw


def _provider(provider_id, name, sql):
    return (_lp(provider_id) + _lp("DPQTC") + _lp(name) + b"\x00" * 8
            + _lp(sql) + b"\x00\x00")


def _sheets(records):
    data = (_lp("V1.1.0") + _lp("BusinessObjects 5.0 Report Sheet List")
            + struct.pack("<d", 1.1) + struct.pack("<I", 0xffffffff)
            + _lp("BOReportSheetsList") + struct.pack("<II", len(records), len(records)))
    if records:
        data += struct.pack("<I", 0xffffffff) + _lp("_BOReportSheet")
    for index, (name, storage) in enumerate(records):
        if index:
            data += struct.pack("<I", 0x80000003)
        data += _lp(name) + _lp(storage) + b"\x00" * 36
    return data


def _object(provider_id, object_id, name, alias):
    accessor = f"{provider_id}DAC1#1"
    return (_lp(provider_id) + b"\x00" * 4 + _lp(f"{accessor}.{object_id}")
            + _lp(name) + _lp(alias) + _lp(accessor))


def _query_metadata(label, name, source):
    return (struct.pack("<I", 6) + b"\x00\x00" + _lp(label)
            + b"\x03\x00\x00\x00\x00\x00\x01\x00" + _lp(name)
            + _lp(source) + b"\x00\x00\x01\x00")


def _streams():
    sql_one = "\r\nSELECT [R\u00e9gion] FROM [Sales] WHERE [State] = @variable('Choose ''state''')\r\n"
    sql_two = "SELECT [Name] FROM [Other]"
    providers = (_lp("V4.1") + _lp("Tosca_Unicode_64K") + struct.pack("<dI", 4.1, 2)
                 + _provider("#DP#1", "Ventes / 100%", sql_one)
                 + _provider("#DP#2", "Second", sql_two)
                 + _lp("select a state") + _lp("DBPASSWORD-DO-NOT-EXPORT"))
    dictionary = (
        _object("#DP#1", "42", "R\u00e9gion / O'Brien", "R\u00e9gion")
        + _object("#DP#2", "7", "Name", "Name")
        + _lp("={F97}({V1})")
    )
    return {
        "GDM|/DM|/DPList;": providers,
        "GDM|/DM|/DMDict;": dictionary,
        "GDM|/#DP#1|/Query;": _query_metadata("Query", "Query 1", "Univers Ventes / 100%"),
        "GDM|/#DP#2|/Query;": _query_metadata("Query", "Query 2", "Second"),
        "ReportSheets|/ReportSheetList;": _sheets([
            ("R\u00e9sum\u00e9 / 100% (O'Brien)", "ReportSheet0"),
            ("Second", "ReportSheet1"),
        ]),
        "ReportSheets|/ReportSheet0|/Data ReportFmt;": b"BOWOBTableBlockFmt",
        "ReportSheets|/ReportSheet1|/Data ReportFmt;": b"BOGraphBlockFmt",
        "AlerterManager;": _lp("=(If (<Measure> >= 30) Then (0) Else(99))"),
        "FormatVersion": b"12.5.0.1190\x00",
        "EarliestCompatibleFormatVersion": b"11.0.0.0\x00",
        "GDM|/LDB|/Data;": b"SAVED-DATA-DO-NOT-EXPORT",
        "apc/The VBA Project/macro": b"MACRO-DO-NOT-EXPORT",
    }, [sql_one, sql_two]


def _zip_rep(path, streams):
    with path.open("wb") as handle:
        handle.write(b"\x00" * 14)
        with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in streams.items():
                archive.writestr(name, value)


def _ole_rep(path, streams):
    ole = ctypes.WinDLL("ole32")
    ole.StgCreateDocfile.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole.StgCreateDocfile.restype = ctypes.c_int32
    root = ctypes.c_void_p()
    deski._deski_com_error(ole.StgCreateDocfile(str(path), 0x1012, 0,
                                                ctypes.byref(root)), "Create test OLE")
    storages = {(): root}
    try:
        for path_name, value in streams.items():
            parts = path_name.split("/")
            for index in range(1, len(parts)):
                key = tuple(parts[:index])
                if key in storages:
                    continue
                child = ctypes.c_void_p()
                result = deski._deski_com_call(
                    storages[key[:-1]], 5, ctypes.c_int32,
                    [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                     ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)],
                    key[-1], 0x1012, 0, 0, ctypes.byref(child),
                )
                deski._deski_com_error(result, "Create test substorage")
                storages[key] = child
            stream = ctypes.c_void_p()
            result = deski._deski_com_call(
                storages[tuple(parts[:-1])], 3, ctypes.c_int32,
                [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                 ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)],
                parts[-1], 0x1012, 0, 0, ctypes.byref(stream),
            )
            deski._deski_com_error(result, "Create test stream")
            try:
                data = ctypes.create_string_buffer(value, max(1, len(value)))
                written = ctypes.c_uint32()
                result = deski._deski_com_call(
                    stream, 4, ctypes.c_int32,
                    [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)],
                    data, len(value), ctypes.byref(written),
                )
                deski._deski_com_error(result, "Write test stream")
                if written.value != len(value):
                    raise OSError("incomplete test stream")
            finally:
                deski._deski_com_release(stream)
    finally:
        for storage in reversed(list(storages.values())):
            deski._deski_com_release(storage)


class TestDesktopIntelligenceInventory(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_main_cli_routes_real_rep_candidate_with_explicit_acknowledgement(self):
        source = self.root / "Ventes.REP"
        streams, sql = _streams()
        _zip_rep(source, streams)
        candidates = deski.inspect_desktop_intelligence(source)["sql_candidates"]
        selected = next(item for item in candidates if item["sql"] == sql[1])
        selector = deski.desktop_intelligence_sql_selector(selected)
        mapping = self.root / "mapping.json"
        mapping.write_text(json.dumps({
            "title": "Synthetic", "source_kind": "desktop_intelligence",
            "server": "sql.example.test", "database": "Demo",
            "columns": ["Name"],
        }), encoding="utf-8")
        report = self.root / "report.rdl"
        query = self.root / "query.m"
        base = ["--output-format", "rdl", "--rdl-mapping", str(mapping),
                "--rdl-output", str(report), "--rdl-power-query-output", str(query),
                "--rdl-bo-source", str(source), "--rdl-sql-name", selector]

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(migration_main(base), 2)
            self.assertFalse(report.exists())
            self.assertFalse(query.exists())
            self.assertEqual(migration_main(base + ["--rdl-accept-unverified-rep-sql"]), 0)
        namespace = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
        self.assertEqual(ET.parse(report).findtext(".//r:CommandText", namespaces=namespace), sql[1])
        self.assertIn(sql[1], query.read_text(encoding="utf-8"))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(migration_main(base + ["--rdl-accept-unverified-rep-sql"]), 2)

    def test_main_cli_rejects_rep_acknowledgement_outside_single_rep_rdl(self):
        cases = [
            ["--rdl-accept-unverified-rep-sql"],
            ["--output-format", "rdl", "--rdl-mapping", "map.json", "--rdl-output", "out.rdl",
             "--rdl-bo-source", "source.wid", "--rdl-sql-name", "DP",
             "--rdl-accept-unverified-rep-sql"],
            ["--output-format", "rdl", "--batch", str(self.root),
             "--rdl-batch-config", "batch.json", "--rdl-accept-unverified-rep-sql"],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments), redirect_stdout(io.StringIO()), \
                    redirect_stderr(io.StringIO()):
                self.assertIn(migration_main(arguments), (2, 3))

    def test_rdl_batch_selects_rep_sql_only_after_per_source_acknowledgement(self):
        source_dir = self.root / "sources"
        source_dir.mkdir()
        source = source_dir / "Ventes.rep"
        streams, sql = _streams()
        _zip_rep(source, streams)
        candidate = next(
            item for item in deski.inspect_desktop_intelligence(source)["sql_candidates"]
            if item["sql"] == sql[1]
        )
        selector = deski.desktop_intelligence_sql_selector(candidate)
        mapping = self.root / "mapping.json"
        mapping.write_text(json.dumps({
            "title": "Synthetic", "source_kind": "desktop_intelligence",
            "server": "sql.example.test", "database": "Demo",
            "columns": ["Name"],
        }), encoding="utf-8")
        config = self.root / "batch.json"
        entry = {
            "mapping": mapping.name,
            "sql_name": selector,
            "power_query": True,
            "accept_unverified_rep_sql": False,
        }
        config.write_text(json.dumps({"sources": {source.name: entry}}), encoding="utf-8")

        rejected_output = self.root / "rejected"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertNotEqual(migration_main([
                str(source_dir), "--output-format", "rdl",
                "--rdl-batch-config", str(config), "--output-dir", str(rejected_output),
            ]), 0)
        rejected = json.loads((rejected_output / "batch_manifest.json").read_text(encoding="utf-8"))
        self.assertIn("requires accept_unverified_rep_sql: true",
                      rejected["artifacts"][0]["targets"]["paginated"]["error"])
        self.assertFalse((rejected_output / source.name / "report.rdl").exists())

        entry["accept_unverified_rep_sql"] = True
        config.write_text(json.dumps({"sources": {source.name: entry}}), encoding="utf-8")
        dry_output = self.root / "dry"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(migration_main([
                str(source_dir), "--output-format", "rdl",
                "--rdl-batch-config", str(config), "--output-dir", str(dry_output),
                "--dry-run",
            ]), 0)
        self.assertFalse(dry_output.exists())

        output = self.root / "output"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(migration_main([
                str(source_dir), "--output-format", "rdl",
                "--rdl-batch-config", str(config), "--output-dir", str(output),
            ]), 0)
        namespace = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
        target = output / source.name
        self.assertEqual(
            ET.parse(target / "report.rdl").findtext(".//r:CommandText", namespaces=namespace),
            sql[1],
        )
        self.assertIn(sql[1], (target / "query.m").read_text(encoding="utf-8"))
        manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
        report_result = manifest["artifacts"][0]
        self.assertEqual(report_result["source_kind"], "desktop_intelligence")
        self.assertIn("REP SQL remains an unverified candidate", report_result["warnings"][0])

    def test_dual_target_batch_reports_unsupported_rep_pbip_and_generates_rdl(self):
        source_dir = self.root / "sources"
        source_dir.mkdir()
        source = source_dir / "Ventes.rep"
        streams, sql = _streams()
        _zip_rep(source, streams)
        candidate = next(item for item in deski.inspect_desktop_intelligence(source)["sql_candidates"]
                         if item["sql"] == sql[1])
        mapping = self.root / "mapping.json"
        mapping.write_text(json.dumps({
            "title": "Synthetic", "source_kind": "desktop_intelligence",
            "server": "sql.example.test", "database": "Demo", "columns": ["Name"],
        }), encoding="utf-8")
        entry = {
            "mapping": mapping.name,
            "sql_name": deski.desktop_intelligence_sql_selector(candidate),
            "power_query": True,
            "accept_unverified_rep_sql": True,
        }
        config = self.root / "batch.json"
        config.write_text(json.dumps({"sources": {source.name: entry}}), encoding="utf-8")

        for acknowledged in (False, True):
            entry["accept_unverified_rep_sql"] = acknowledged
            config.write_text(json.dumps({"sources": {source.name: entry}}), encoding="utf-8")
            output = self.root / f"output-{acknowledged}"
            with self.subTest(acknowledged=acknowledged), redirect_stdout(io.StringIO()), \
                    redirect_stderr(io.StringIO()):
                self.assertNotEqual(migration_main([
                    str(source_dir), "--rdl-batch-config", str(config), "--output-dir", str(output),
                ]), 0)
            manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
            artifact = manifest["artifacts"][0]
            self.assertEqual(artifact["source_kind"], "desktop_intelligence")
            self.assertEqual(artifact["status"], "failed")
            self.assertEqual(artifact["targets"]["powerbi"]["status"], "failed")
            self.assertIn("not supported", artifact["targets"]["powerbi"]["error"])
            self.assertIn("PBIP", artifact["targets"]["powerbi"]["error"])
            self.assertFalse(list((output / source.name).rglob("*.pbip")))
            paginated = artifact["targets"]["paginated"]
            report = output / source.name / "PaginatedReport" / "report.rdl"
            if acknowledged:
                self.assertEqual(paginated["status"], "success")
                self.assertIn("REP SQL remains an unverified candidate", artifact["warnings"][0])
                namespace = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
                self.assertEqual(
                    ET.parse(report).findtext(".//r:CommandText", namespaces=namespace), sql[1],
                )
                self.assertIn(sql[1], report.with_name("query.m").read_text(encoding="utf-8"))
            else:
                self.assertEqual(paginated["status"], "failed")
                self.assertIn("requires accept_unverified_rep_sql: true", paginated["error"])
                self.assertFalse(report.exists())

    def test_dual_target_batch_generates_pbip_from_selected_rep_sql_and_manual_columns(self):
        source_dir = self.root / "sources"
        source_dir.mkdir()
        source = source_dir / "Ventes.rep"
        streams, sql = _streams()
        _zip_rep(source, streams)
        candidate = next(item for item in deski.inspect_desktop_intelligence(source)["sql_candidates"]
                         if item["sql"] == sql[1])
        mapping = self.root / "mapping.json"
        mapping.write_text(json.dumps({
            "title": "Synthetic", "source_kind": "desktop_intelligence",
            "server": "sql.example.test", "database": "Demo",
            "columns": ["Name", "Amount"],
        }), encoding="utf-8")
        entry = {
            "mapping": mapping.name,
            "sql_name": deski.desktop_intelligence_sql_selector(candidate),
            "power_query": True,
            "accept_unverified_rep_sql": True,
            "pbip": {
                "connection_name": "DemoSql",
                "query_name": "ReviewedQuery",
                "schema": "dbo",
                "columns": [
                    {"name": "Name", "data_type": "string", "role": "dimension"},
                    {"name": "Amount", "data_type": "decimal", "role": "measure"},
                ],
            },
        }
        config = self.root / "batch.json"
        config.write_text(json.dumps({"sources": {source.name: entry}}), encoding="utf-8")
        output = self.root / "output"

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = migration_main([
                str(source_dir), "--rdl-batch-config", str(config), "--output-dir", str(output),
            ])

        manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
        artifact = manifest["artifacts"][0]
        self.assertEqual(result, 0)
        self.assertEqual(artifact["status"], "success")
        self.assertEqual(artifact["targets"]["powerbi"]["status"], "success")
        self.assertEqual(artifact["targets"]["paginated"]["status"], "success")

        namespace = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
        paginated = output / source.name / "PaginatedReport"
        self.assertEqual(
            ET.parse(paginated / "report.rdl").findtext(
                ".//r:CommandText", namespaces=namespace,
            ),
            sql[1],
        )
        self.assertIn(sql[1], (paginated / "query.m").read_text(encoding="utf-8"))

        pbip_files = list((output / source.name).rglob("*.pbip"))
        self.assertEqual(len(pbip_files), 1)
        project = pbip_files[0].parent
        model = project / f"{pbip_files[0].stem}.SemanticModel" / "definition" / "model.tmdl"
        self.assertTrue(model.is_file())
        model_text = model.read_text(encoding="utf-8")
        self.assertIn("ReviewedQuery", model_text)
        table = model.parent / "tables" / "ReviewedQuery.tmdl"
        self.assertTrue(table.is_file())
        table_text = table.read_text(encoding="utf-8")
        self.assertIn("Name", table_text)
        self.assertIn("Amount", table_text)
        exported_query = (project / "PowerQuery" / "ReviewedQuery.pq").read_text(encoding="utf-8")
        self.assertIn(sql[1], exported_query)
        self.assertTrue((project / "expression_export.json").is_file())
        visuals = list(project.rglob("visual.json"))
        self.assertEqual(len(visuals), 1)

        warnings = " ".join(artifact["warnings"]).lower()
        self.assertIn("manual", warnings)
        self.assertIn("unverified", warnings)
        self.assertTrue(any("REP SQL remains an unverified candidate" in warning
                            for warning in artifact["warnings"]))

    def test_dual_target_batch_fails_only_pbip_on_static_artifact_validation_error(self):
        source_dir = self.root / "sources"
        source_dir.mkdir()
        source = source_dir / "Ventes.rep"
        streams, sql = _streams()
        _zip_rep(source, streams)
        candidate = next(item for item in deski.inspect_desktop_intelligence(source)["sql_candidates"]
                         if item["sql"] == sql[1])
        mapping = self.root / "mapping.json"
        mapping.write_text(json.dumps({
            "title": "Synthetic", "source_kind": "desktop_intelligence",
            "server": "sql.example.test", "database": "Demo",
            "columns": ["Name"],
        }), encoding="utf-8")
        entry = {
            "mapping": mapping.name,
            "sql_name": deski.desktop_intelligence_sql_selector(candidate),
            "power_query": True,
            "accept_unverified_rep_sql": True,
            "pbip": {
                "connection_name": "DemoSql",
                "query_name": "ReviewedQuery",
                "schema": "dbo",
                "columns": [
                    {"name": "Name", "data_type": "string", "role": "dimension"},
                ],
            },
        }
        config = self.root / "batch.json"
        config.write_text(json.dumps({"sources": {source.name: entry}}), encoding="utf-8")
        output = self.root / "output"
        finding = "Synthetic PBIP validation finding"
        validation = {
            "valid": False,
            "errors": [finding],
            "warnings": [],
            "files_checked": 1,
        }

        with patch(
                "powerbi_import.validator.ArtifactValidator.validate_project",
                return_value=validation,
        ) as validate_project, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = migration_main([
                str(source_dir), "--output-format", "pbip",
                "--rdl-batch-config", str(config), "--output-dir", str(output),
            ])

        manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
        artifact = manifest["artifacts"][0]
        self.assertNotEqual(result, 0)
        self.assertEqual(artifact["status"], "failed")
        self.assertEqual(artifact["targets"]["powerbi"]["status"], "failed")
        self.assertIn(finding, artifact["targets"]["powerbi"]["error"])
        self.assertIn(finding, artifact["error"])

        pbip_files = list((output / source.name / "PowerBI").rglob("*.pbip"))
        self.assertEqual(len(pbip_files), 1)
        project = pbip_files[0].parent
        validate_project.assert_called_once()
        self.assertEqual(Path(validate_project.call_args.args[0]), project)

        paginated = artifact["targets"]["paginated"]
        report = output / source.name / "PaginatedReport" / "report.rdl"
        self.assertEqual(paginated["status"], "success")
        self.assertTrue(report.is_file())
        namespace = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
        self.assertEqual(
            ET.parse(report).findtext(".//r:CommandText", namespaces=namespace), sql[1],
        )

    def test_dual_target_batch_rejects_rep_sql_with_bo_function_markers_for_pbip(self):
        source_dir = self.root / "sources"
        source_dir.mkdir()
        source = source_dir / "Ventes.rep"
        streams, sql = _streams()
        selected_sql = sql[0].replace("@variable", "@dpvalues")
        streams["GDM|/DM|/DPList;"] = streams["GDM|/DM|/DPList;"].replace(
            sql[0].encode("utf-8"), selected_sql.encode("utf-8"),
        )
        _zip_rep(source, streams)
        candidate = next(item for item in deski.inspect_desktop_intelligence(source)["sql_candidates"]
                         if item["sql"] == selected_sql)
        mapping = self.root / "mapping.json"
        mapping.write_text(json.dumps({
            "title": "Synthetic", "source_kind": "desktop_intelligence",
            "server": "sql.example.test", "database": "Demo",
            "columns": ["Région"],
        }), encoding="utf-8")
        entry = {
            "mapping": mapping.name,
            "sql_name": deski.desktop_intelligence_sql_selector(candidate),
            "power_query": True,
            "accept_unverified_rep_sql": True,
            "pbip": {
                "connection_name": "DemoSql",
                "query_name": "ReviewedQuery",
                "schema": "dbo",
                "columns": [
                    {"name": "Région", "data_type": "string", "role": "dimension"},
                ],
            },
        }
        config = self.root / "batch.json"
        config.write_text(json.dumps({"sources": {source.name: entry}}), encoding="utf-8")
        output = self.root / "output"

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = migration_main([
                str(source_dir), "--rdl-batch-config", str(config), "--output-dir", str(output),
            ])

        artifact = json.loads(
            (output / "batch_manifest.json").read_text(encoding="utf-8")
        )["artifacts"][0]
        self.assertNotEqual(result, 0)
        self.assertEqual(artifact["targets"]["powerbi"]["status"], "failed")
        self.assertRegex(
            artifact["targets"]["powerbi"]["error"].lower(),
            r"bo function markers?",
        )
        paginated = artifact["targets"]["paginated"]
        report = output / source.name / "PaginatedReport" / "report.rdl"
        if paginated["status"] == "success":
            namespace = {
                "r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition",
            }
            self.assertEqual(
                ET.parse(report).findtext(".//r:CommandText", namespaces=namespace),
                selected_sql,
            )
        self.assertFalse(list((output / source.name).rglob("*.pbip")))

    def test_mcp_lists_and_assesses_rep_without_returning_raw_inventory(self):
        source = self.root / "Ventes.REP"
        streams, sql = _streams()
        _zip_rep(source, streams)
        requests = [
            {"name": "inventory", "arguments": {"directory": "."}},
            {"name": "assess", "arguments": {"file": source.name}},
            {"name": "assess", "arguments": {"file": "../outside.rep"}},
        ]
        process = subprocess.run(
            [sys.executable, "-m", "powerbi_import.mcp_server", "--root", str(self.root)],
            input="\n".join(json.dumps({"jsonrpc": "2.0", "id": index,
                                       "method": "tools/call", "params": params})
                            for index, params in enumerate(requests)) + "\n",
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            encoding="utf-8", timeout=30, check=True,
        )
        inventory, assessment, outside = [
            json.loads(line)["result"] for line in process.stdout.splitlines()
        ]
        self.assertFalse(inventory["isError"])
        self.assertEqual(inventory["structuredContent"]["files"], [
            {"path": source.name, "format": "desktop_intelligence"},
        ])
        self.assertFalse(assessment["isError"], assessment)
        summary = assessment["structuredContent"]["assessment"]
        expected = build_deski_migration_report(deski.inspect_desktop_intelligence(source))
        self.assertEqual(summary, expected)
        self.assertEqual(summary["status"], "review_required")
        self.assertEqual(summary["counts"]["sql_candidates"], 2)
        self.assertEqual(summary["checks"]["rdl_generation"], "not_run")
        for value in (sql[0].strip(), sql[1], "Choose", "={F97}({V1})", "DBPASSWORD-DO-NOT-EXPORT"):
            self.assertNotIn(value, assessment["content"][0]["text"])
        self.assertTrue(outside["isError"])
        self.assertIn("outside the configured MCP root", outside["structuredContent"]["error"])
        self.assertEqual(list(self.root.iterdir()), [source])

    def _assert_inventory(self, inventory, sql, container):
        self.assertEqual(inventory["status"], "partial")
        self.assertEqual(inventory["source"]["container"], container)
        self.assertEqual(inventory["format_version"], "12.5.0.1190")
        self.assertEqual(inventory["sheets"]["declared_count"], 2)
        self.assertEqual([item["name"] for item in inventory["sheets"]["candidates"]],
                         ["R\u00e9sum\u00e9 / 100% (O'Brien)", "Second"])
        self.assertEqual([item["structure_markers"] for item in inventory["sheets"]["candidates"]],
                         [["BOWOBTableBlockFmt"], ["BOGraphBlockFmt"]])
        self.assertEqual([item["id"] for item in inventory["providers"]["candidates"]],
                         ["#DP#1", "#DP#2"])
        self.assertEqual(
            inventory["providers"]["candidates"][0]["query_metadata_candidate"]["source_name_candidate"],
            "Univers Ventes / 100%",
        )
        self.assertEqual(
            inventory["providers"]["candidates"][0]["query_metadata_candidate"]["source_interpretation"],
            "possible_universe_not_verified",
        )
        self.assertEqual([item["name"] for item in inventory["object_candidates"]],
                         ["R\u00e9gion / O'Brien", "Name"])
        self.assertEqual([item["sql"] for item in inventory["sql_candidates"]], sql)
        self.assertEqual([item["possible_provider_id"] for item in inventory["sql_candidates"]],
                         ["#DP#1", "#DP#2"])
        self.assertEqual(inventory["sql_candidates"][0]["literal_arguments"],
                         [{"function": "variable", "literal": "Choose 'state'"}])
        self.assertEqual(inventory["sql_candidates"][0]["bo_function_markers"], ["variable"])
        self.assertTrue(all(item["sql_status"] == "unverified"
                            for item in inventory["sql_candidates"]))
        self.assertEqual([item["expression"] for item in inventory["formula_candidates"]],
                         ["={F97}({V1})", "=(If (<Measure> >= 30) Then (0) Else(99))"])
        serialized = json.dumps(inventory)
        for secret in ("DBPASSWORD-DO-NOT-EXPORT", "SAVED-DATA-DO-NOT-EXPORT",
                       "MACRO-DO-NOT-EXPORT"):
            self.assertNotIn(secret, serialized)

    def test_prefixed_zip_preserves_framed_candidates_without_reading_data_or_macros(self):
        path = self.root / "sample.rep"
        streams, sql = _streams()
        _zip_rep(path, streams)
        inventory = deski.inspect_desktop_intelligence(path)
        self._assert_inventory(inventory, sql, "zip")

        mapping = {"title": "T", "source_kind": "desktop_intelligence", "server": "s",
                   "database": "d", "columns": ["Name"]}
        with self.assertRaisesRegex(ValueError, "captured status"):
            _mapping_with_extracted_sql(
                mapping, [{"name": "unreviewed", **inventory["sql_candidates"][1]}],
                "unreviewed",
            )

    @unittest.skipUnless(sys.platform == "win32", "OLE reading uses Windows Structured Storage")
    def test_ole_streams_are_read_without_running_the_document(self):
        path = self.root / "sample.rep"
        streams, sql = _streams()
        _ole_rep(path, streams)
        self._assert_inventory(deski.inspect_desktop_intelligence(path), sql, "ole")

    def test_mismatched_provider_count_does_not_assign_a_sql_candidate(self):
        path = self.root / "sample.rep"
        streams, _ = _streams()
        header = _lp("V4.1") + _lp("Tosca_Unicode_64K") + struct.pack("<dI", 4.1, 3)
        old_header = _lp("V4.1") + _lp("Tosca_Unicode_64K") + struct.pack("<dI", 4.1, 2)
        streams["GDM|/DM|/DPList;"] = header + streams["GDM|/DM|/DPList;"][len(old_header):]
        _zip_rep(path, streams)
        inventory = deski.inspect_desktop_intelligence(path)
        self.assertTrue(all(item["possible_provider_id"] is None
                            for item in inventory["sql_candidates"]))
        self.assertTrue(any("declared provider count" in item for item in inventory["warnings"]))

    def test_non_utf8_names_are_reported_without_corrupting_them(self):
        path = self.root / "sample.rep"
        streams, _ = _streams()
        streams["GDM|/DM|/DPList;"] = (
            _lp("V4.0") + _lp("Tosca_Unicode") + struct.pack("<dI", 4.0, 1)
            + _provider("#DP#1", b"caf\xe9", "SELECT [Name] FROM [Sales]")
        )
        _zip_rep(path, streams)
        inventory = deski.inspect_desktop_intelligence(path)
        self.assertEqual(inventory["providers"]["candidates"], [])
        self.assertIsNone(inventory["sql_candidates"][0]["possible_provider_id"])
        self.assertTrue(any("not UTF-8" in item for item in inventory["warnings"]))

    def test_unknown_query_metadata_is_not_interpreted_as_a_universe(self):
        path = self.root / "sample.rep"
        streams, _ = _streams()
        streams["GDM|/#DP#1|/Query;"] = b"\x06\x00\x00\x00\x00\x00" + _lp("Query")
        _zip_rep(path, streams)
        inventory = deski.inspect_desktop_intelligence(path)
        self.assertNotIn("query_metadata_candidate", inventory["providers"]["candidates"][0])
        self.assertTrue(any("Query metadata could not be decoded" in item
                            for item in inventory["warnings"]))

    def test_malformed_and_ambiguous_selected_streams_fail_explicitly(self):
        path = self.root / "sample.rep"
        streams, _ = _streams()
        _zip_rep(path, streams)
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("gdm|/dm|/dplist;", b"other")
        with self.assertRaisesRegex(ValueError, "duplicate REP stream"):
            deski.inspect_desktop_intelligence(path)

        _zip_rep(path, streams)
        with patch.object(deski, "_DESKI_STREAM_LIMIT", 64):
            with self.assertRaisesRegex(ValueError, "read limits"):
                deski.inspect_desktop_intelligence(path)

        path.write_bytes(b"not a REP")
        with self.assertRaisesRegex(ValueError, "unsupported REP container"):
            deski.inspect_desktop_intelligence(path)

    def test_encrypted_selected_stream_is_rejected(self):
        path = self.root / "sample.rep"
        streams, _ = _streams()
        _zip_rep(path, streams)
        original = zipfile.ZipFile.infolist

        def encrypted_list(archive):
            entries = original(archive)
            for entry in entries:
                if entry.filename == "GDM|/DM|/DPList;":
                    entry.flag_bits |= 1
            return entries

        with patch.object(zipfile.ZipFile, "infolist", encrypted_list):
            with self.assertRaisesRegex(ValueError, "encrypted"):
                deski.inspect_desktop_intelligence(path)

    def test_cli_writes_new_json_and_does_not_overwrite(self):
        path = self.root / "sample.rep"
        output = self.root / "inventory.json"
        streams, _ = _streams()
        _zip_rep(path, streams)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--source", str(path), "--output", str(output)]), 0)
        before = output.read_bytes()
        self.assertEqual(json.loads(before)["status"], "partial")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--source", str(path), "--output", str(output)]), 2)
        self.assertEqual(output.read_bytes(), before)

    def test_sdk_registry_check_distinguishes_registration_and_partial_entries(self):
        clsid = "{52AA10AA-2E74-4930-BC39-000000000001}"
        server = f"CLSID\\{clsid}\\LocalServer32"
        values = {
            (32, r"BusinessObjects.Application"): "",
            (32, r"BusinessObjects.Application\CLSID"): clsid,
            (32, server): r"C:\Private\DeskI.exe",
            (64, r"BusinessObjects.Application"): "",
        }

        class FakeKey:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def open_key(_root, path, _reserved, access):
            try:
                return FakeKey(values[(access, path)])
            except KeyError:
                raise FileNotFoundError(path) from None

        registry = types.SimpleNamespace(
            KEY_READ=0, KEY_WOW64_32KEY=32, KEY_WOW64_64KEY=64,
            HKEY_CLASSES_ROOT=object(), OpenKey=open_key,
            QueryValueEx=lambda key, _name: (key.value, 1),
        )
        output = io.StringIO()
        with patch.object(deski_cli.sys, "platform", "win32"), \
                patch.dict(sys.modules, {"winreg": registry}), redirect_stdout(output):
            self.assertEqual(main(["--check-sdk"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["registration"], {"32_bit": "registered", "64_bit": "incomplete"})
        self.assertIn("provider_sql_capture", result["checks_not_run"])
        self.assertNotIn("Private", output.getvalue())

        values[(32, server)] = ""
        self.assertEqual(deski_cli._deski_registration_status(registry, 32), "incomplete")
        values[(32, r"BusinessObjects.Application\CLSID")] = "not-a-clsid"
        self.assertEqual(deski_cli._deski_registration_status(registry, 32), "incomplete")
        values[(32, r"BusinessObjects.Application\CLSID")] = clsid
        values[(32, f"CLSID\\{clsid}\\InprocServer32")] = "DeskI.dll"
        self.assertEqual(deski_cli._deski_registration_status(registry, 32), "registered")

        values.clear()
        absent = io.StringIO()
        with patch.object(deski_cli.sys, "platform", "win32"), \
                patch.dict(sys.modules, {"winreg": registry}), redirect_stdout(absent):
            self.assertEqual(main(["--check-sdk"]), 1)
        self.assertEqual(json.loads(absent.getvalue())["registration"],
                         {"32_bit": "absent", "64_bit": "absent"})

        def denied(*_args):
            raise PermissionError("registry access denied")

        registry.OpenKey = denied
        error = io.StringIO()
        with patch.object(deski_cli.sys, "platform", "win32"), \
                patch.dict(sys.modules, {"winreg": registry}), redirect_stderr(error):
            self.assertEqual(main(["--check-sdk"]), 2)
        self.assertIn("registry access denied", error.getvalue())

    def test_sdk_check_rejects_output_and_non_windows(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["--check-sdk", "--output", str(self.root / "ignored.json")])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse((self.root / "ignored.json").exists())
        with patch.object(deski_cli.sys, "platform", "linux"), \
                redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(main(["--check-sdk"]), 2)
        self.assertIn("requires Windows", stderr.getvalue())

    def test_cli_reports_partial_evidence_without_copying_sql_or_formulas(self):
        source = self.root / "sample.rep"
        inventory_path = self.root / "inventory.json"
        report_path = self.root / "report.json"
        html_path = self.root / "report.html"
        streams, sql = _streams()
        streams["ReportSheets|/ReportSheetList;"] = _sheets([
            ('<script>alert("sheet")</script>', "ReportSheet0"),
        ])
        _zip_rep(source, streams)
        args = [
            "--source", str(source), "--output", str(inventory_path),
            "--migration-report", str(report_path), "--html-report", str(html_path),
        ]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        report_text = report_path.read_text(encoding="utf-8")
        report = json.loads(report_text)
        html = html_path.read_text(encoding="utf-8")

        self.assertEqual(report["scope"], "current_inspection_only")
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["source"]["sha256"], inventory["source"]["sha256"])
        self.assertEqual(report["counts"]["sql_candidates"], 2)
        self.assertEqual(report["counts"]["formula_candidates"], 2)
        self.assertEqual(
            report["formula_candidates"],
            [
                {
                    "selector": f"{item['stream']}@{item['stream_offset']}",
                    "formula_status": "unverified",
                }
                for item in inventory["formula_candidates"]
            ],
        )
        self.assertEqual(report["sql_candidates"][0]["bo_function_markers"], ["variable"])
        self.assertEqual(report["sql_candidates"][0]["literal_argument_count"], 1)
        self.assertEqual(report["sql_candidates"][0]["sql_status"], "unverified")
        self.assertTrue(all(value == "not_run" for value in report["checks"].values()))
        self.assertIn("Stream-local selector", html)
        self.assertEqual(
            [item["selector"] for item in report["sql_candidates"]],
            [item["name"] for item in _sql_from_bo_file(
                source, {"source_kind": "desktop_intelligence"}
            )],
        )
        self.assertIn("&lt;script&gt;alert(&quot;sheet&quot;)&lt;/script&gt;", html)
        self.assertNotIn("<script>", html)
        for sensitive in [*sql, "Choose 'state'", "={F97}({V1})",
                          "DBPASSWORD-DO-NOT-EXPORT", "SAVED-DATA-DO-NOT-EXPORT"]:
            self.assertNotIn(sensitive, report_text)
            self.assertNotIn(sensitive, html)

        second_report = self.root / "report-again.json"
        second_html = self.root / "report-again.html"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--source", str(source), "--output", str(self.root / "inventory-again.json"),
                "--migration-report", str(second_report), "--html-report", str(second_html),
            ]), 0)
        self.assertEqual(report_path.read_bytes(), second_report.read_bytes())
        self.assertEqual(html_path.read_bytes(), second_html.read_bytes())

    def test_report_without_sql_or_visual_markers_does_not_claim_absence(self):
        source = self.root / "sample.rep"
        streams, _ = _streams()
        streams["GDM|/DM|/DPList;"] = (
            _lp("V4.1") + _lp("Tosca_Unicode_64K") + struct.pack("<dI", 4.1, 1)
            + _provider("#DP#1", "Query", "not a SQL statement")
        )
        streams["ReportSheets|/ReportSheet0|/Data ReportFmt;"] = b"unrecognized format"
        _zip_rep(source, streams)
        report_path = self.root / "report.json"
        html_path = self.root / "report.html"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--source", str(source), "--output", str(self.root / "inventory.json"),
                "--migration-report", str(report_path), "--html-report", str(html_path),
            ]), 0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["counts"]["sql_candidates"], 0)
        self.assertEqual(report["sheet_candidates"][0]["structure_markers"], [])
        self.assertIn("No SQL candidate was recovered", report["findings"][1]["observation"])
        self.assertIn("do not establish", report["findings"][0]["observation"])
        self.assertIn("absence is not established", html_path.read_text(encoding="utf-8"))

    def test_unresolved_report_selectors_match_paginated_cli(self):
        source = self.root / "sample.rep"
        streams, _ = _streams()
        old_header = _lp("V4.1") + _lp("Tosca_Unicode_64K") + struct.pack("<dI", 4.1, 2)
        new_header = _lp("V4.1") + _lp("Tosca_Unicode_64K") + struct.pack("<dI", 4.1, 3)
        streams["GDM|/DM|/DPList;"] = new_header + streams["GDM|/DM|/DPList;"][len(old_header):]
        _zip_rep(source, streams)
        report_path = self.root / "report.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--source", str(source), "--output", str(self.root / "inventory.json"),
                "--migration-report", str(report_path),
            ]), 0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        selected = _sql_from_bo_file(source, {"source_kind": "desktop_intelligence"})
        self.assertEqual(
            [item["selector"] for item in report["sql_candidates"]],
            [item["name"] for item in selected],
        )
        self.assertTrue(all(item["selector"].startswith("unresolved@")
                            for item in report["sql_candidates"]))

    def test_report_does_not_copy_extra_source_fields_or_warning_text(self):
        source = self.root / "sample.rep"
        streams, _ = _streams()
        _zip_rep(source, streams)
        inventory = deski.inspect_desktop_intelligence(source)
        inventory["source"]["unrecognized_metadata"] = "SENSITIVE-SOURCE-MARKER"
        inventory["warnings"].append("SENSITIVE-WARNING-MARKER")
        report = json.dumps(build_deski_migration_report(inventory))
        self.assertNotIn("SENSITIVE-SOURCE-MARKER", report)
        self.assertNotIn("SENSITIVE-WARNING-MARKER", report)

    def test_cli_rolls_back_new_outputs_when_a_report_cannot_be_created(self):
        source = self.root / "sample.rep"
        streams, _ = _streams()
        _zip_rep(source, streams)
        inventory_path = self.root / "inventory.json"
        report_path = self.root / "report.json"
        html_path = self.root / "report.html"
        html_path.write_text("existing", encoding="utf-8")
        args = [
            "--source", str(source), "--output", str(inventory_path),
            "--migration-report", str(report_path), "--html-report", str(html_path),
        ]
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 2)
        self.assertFalse(inventory_path.exists())
        self.assertFalse(report_path.exists())
        self.assertEqual(html_path.read_text(encoding="utf-8"), "existing")

        with redirect_stderr(io.StringIO()):
            self.assertEqual(main([
                "--source", str(source), "--output", str(inventory_path),
                "--migration-report", str(inventory_path),
            ]), 2)
        self.assertFalse(inventory_path.exists())

    def test_cli_rejects_empty_optional_report_paths(self):
        source = self.root / "sample.rep"
        streams, _ = _streams()
        _zip_rep(source, streams)
        inventory_path = self.root / "inventory.json"
        for flag in ("--migration-report", "--html-report"):
            with self.subTest(flag=flag), redirect_stderr(io.StringIO()):
                self.assertEqual(main([
                    "--source", str(source), "--output", str(inventory_path), flag, "",
                ]), 2)
            self.assertFalse(inventory_path.exists())

    def test_cli_removes_all_new_outputs_after_partial_write_failure(self):
        source = self.root / "sample.rep"
        streams, _ = _streams()
        _zip_rep(source, streams)
        inventory_path = self.root / "inventory.json"
        report_path = self.root / "report.json"
        original_open = deski_cli.open_new_text

        class FailingWriter:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.handle.close()

            def write(self, content):
                self.handle.write(content[:20])
                raise OSError("simulated write failure")

        def open_with_failure(path):
            handle = original_open(path)
            if path == report_path:
                return FailingWriter(handle)
            return handle

        errors = io.StringIO()
        with patch.object(deski_cli, "open_new_text", side_effect=open_with_failure), \
                redirect_stderr(errors):
            self.assertEqual(main([
                "--source", str(source), "--output", str(inventory_path),
                "--migration-report", str(report_path),
            ]), 2)
        self.assertIn("simulated write failure", errors.getvalue())
        self.assertFalse(inventory_path.exists())
        self.assertFalse(report_path.exists())

    def test_cli_reports_failed_cleanup_of_partial_outputs(self):
        source = self.root / "sample.rep"
        streams, _ = _streams()
        _zip_rep(source, streams)
        html_path = self.root / "report.html"
        html_path.write_text("existing", encoding="utf-8")
        errors = io.StringIO()
        with patch.object(Path, "unlink", side_effect=PermissionError("cleanup denied")):
            with redirect_stderr(errors):
                self.assertEqual(main([
                    "--source", str(source), "--output", str(self.root / "inventory.json"),
                    "--html-report", str(html_path),
                ]), 2)
        self.assertIn("could not remove partial outputs", errors.getvalue())
        self.assertEqual(html_path.read_text(encoding="utf-8"), "existing")

    @unittest.skipIf(sys.platform == "win32", "Non-Windows limitation")
    def test_ole_without_windows_is_an_explicit_failure(self):
        path = self.root / "sample.rep"
        path.write_bytes(deski._DESKI_OLE_SIGNATURE + b"not a compound document")
        with self.assertRaisesRegex(ValueError, "requires Windows"):
            deski.inspect_desktop_intelligence(path)


class TestDesktopIntelligenceMainCLI(unittest.TestCase):
    """Test REP shortcuts using the real inventory and pre-migration report."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source_dir = self.root / "sources XI résumé"
        source_dir.mkdir()
        self.source = source_dir / "Bilan régional.v1.REP"
        streams, self.sql = _streams()
        _zip_rep(self.source, streams)
        self.inventory = deski.inspect_desktop_intelligence(self.source)
        self.script = Path(__file__).resolve().parents[1] / "migrate.py"

    def _run_cli(self, *arguments, timeout=30):
        return subprocess.run(
            [sys.executable, str(self.script), *arguments],
            cwd=self.root, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=timeout,
        )

    def _snapshot(self):
        return {
            path.relative_to(self.root): path.read_bytes() if path.is_file() else None
            for path in self.root.rglob("*")
        }

    @staticmethod
    def _json_strings(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from TestDesktopIntelligenceMainCLI._json_strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from TestDesktopIntelligenceMainCLI._json_strings(item)
        elif isinstance(value, str):
            yield value

    @staticmethod
    def _sensitive_values(inventory):
        values = [
            item["sql"].strip() for item in inventory["sql_candidates"]
        ] + [
            item["expression"] for item in inventory["formula_candidates"]
        ] + [
            argument["literal"]
            for item in inventory["sql_candidates"]
            for argument in item["literal_arguments"]
        ]
        return values + [
            "DBPASSWORD-DO-NOT-EXPORT", "SAVED-DATA-DO-NOT-EXPORT",
            "MACRO-DO-NOT-EXPORT",
        ]

    def _assert_report(self, text, source=None, inventory=None):
        source = source or self.source
        inventory = inventory or self.inventory
        report = json.loads(text)
        self.assertEqual(report, build_deski_migration_report(inventory))
        self.assertEqual(report["report_type"], "desktop_intelligence_pre_migration")
        self.assertEqual(report["scope"], "current_inspection_only")
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["source"]["file_name"], source.name)
        self.assertEqual(report["counts"]["sql_candidates"], 2)
        self.assertEqual(report["counts"]["formula_candidates"], 2)
        self.assertEqual(report["sql_candidates"][0]["literal_argument_count"], 1)
        self.assertTrue(all(value == "not_run" for value in report["checks"].values()))
        # Names are retained as evidence and may themselves be sensitive.
        self.assertEqual(
            report["provider_candidates"][0]["source_name_candidate"],
            "Univers Ventes / 100%",
        )
        self.assertEqual(report["sheet_candidates"][0]["name"], "Résumé / 100% (O'Brien)")
        strings = list(self._json_strings(report))
        for sensitive in self._sensitive_values(inventory):
            self.assertNotIn(sensitive, text)
            self.assertTrue(all(sensitive not in value for value in strings), sensitive)
        return report

    def _assert_successful_report(self, result, source=None, inventory=None):
        self.assertEqual(result.returncode, 0, result.stderr)
        report = self._assert_report(result.stdout, source, inventory)
        for sensitive in self._sensitive_values(inventory or self.inventory):
            self.assertNotIn(sensitive, result.stderr)
        return report

    def test_assess_and_dry_run_print_report_without_default_outputs(self):
        before = self._snapshot()
        for flags in (("--assess",), ("--dry-run",), ("--assess", "--dry-run")):
            with self.subTest(flags=flags):
                result = self._run_cli(str(self.source), *flags)
                self._assert_successful_report(result)
                self.assertEqual(self._snapshot(), before)

    def test_assessment_emits_unicode_json_without_encoding_overrides(self):
        environment = os.environ.copy()
        environment.pop("PYTHONIOENCODING", None)
        environment.pop("PYTHONUTF8", None)
        before = self._snapshot()

        result = subprocess.run(
            [sys.executable, str(self.script), str(self.source), "--assess"],
            cwd=self.root, env=environment, capture_output=True, timeout=30,
        )

        stdout = result.stdout.decode("utf-8", errors="strict")
        stderr = result.stderr.decode("utf-8", errors="strict")
        self.assertEqual(result.returncode, 0, stderr)
        self._assert_report(stdout)
        for sensitive in self._sensitive_values(self.inventory):
            self.assertNotIn(sensitive, stderr)
        self.assertEqual(self._snapshot(), before)

    def test_assessment_does_not_invoke_target_generators(self):
        before = self._snapshot()
        for flags in (("--assess",), ("--dry-run",), ("--assess", "--dry-run")):
            with self.subTest(flags=flags), \
                 patch("powerbi_import.import_to_powerbi.PowerBIImporter") as importer, \
                 patch("migrate_paginated.main") as paginated, \
                 patch("powerbi_import.paginated_generator.generate_semantic_model_rdl") as rdl:
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    result = migration_main([str(self.source), *flags])
                self.assertEqual(result, 0)
                self._assert_report(stdout.getvalue())
                importer.assert_not_called()
                paginated.assert_not_called()
                rdl.assert_not_called()
                self.assertEqual(self._snapshot(), before)

    @unittest.skipUnless(sys.platform == "win32", "OLE reading uses Windows Structured Storage")
    def test_assess_ole_rep_uses_existing_static_inventory(self):
        source = self.root / "Ancien modèle OLE.rep"
        streams, _ = _streams()
        _ole_rep(source, streams)
        inventory = deski.inspect_desktop_intelligence(source)
        before = self._snapshot()

        result = self._run_cli(str(source), "--assess")

        report = self._assert_successful_report(result, source, inventory)
        self.assertEqual(report["source"]["container"], "ole")
        self.assertEqual(self._snapshot(), before)

    def test_assess_saves_only_the_named_report_and_refuses_a_second_write(self):
        output = self.root / "résultats partiels" / "2026"
        saved = output / f"{self.source.stem}_deski_assessment.json"

        result = self._run_cli(str(self.source), "--assess", "--output-dir", str(output))

        printed = self._assert_successful_report(result)
        self.assertTrue(saved.is_file())
        self.assertEqual(self._assert_report(saved.read_text(encoding="utf-8")), printed)
        self.assertEqual(set(output.iterdir()), {saved})
        self.assertEqual(
            {path for path in self.root.rglob("*") if path.is_file()},
            {self.source, saved},
        )
        before = self._snapshot()
        retry = self._run_cli(str(self.source), "--assess", "--output-dir", str(output))
        self.assertNotEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertEqual(self._snapshot(), before)

    def test_assess_never_overwrites_an_existing_report(self):
        output = self.root / "existing assessments"
        output.mkdir()
        saved = output / f"{self.source.stem}_deski_assessment.json"
        sentinel = b"existing assessment must remain unchanged\n"
        saved.write_bytes(sentinel)
        before = self._snapshot()

        result = self._run_cli(str(self.source), "--assess", "--output-dir", str(output))

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(saved.read_bytes(), sentinel)
        self.assertEqual(self._snapshot(), before)

    def test_only_one_concurrent_assessment_writer_succeeds(self):
        output = self.root / "concurrent assessments"
        output.mkdir()
        saved = output / f"{self.source.stem}_deski_assessment.json"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda _: self._run_cli(
                    str(self.source), "--assess", "--output-dir", str(output), timeout=120,
                ),
                range(2),
            ))

        winners = [result for result in results if result.returncode == 0]
        self.assertEqual(len(winners), 1)
        printed = self._assert_successful_report(winners[0])
        self.assertEqual(self._assert_report(saved.read_text(encoding="utf-8")), printed)
        self.assertEqual(set(output.iterdir()), {saved})
        self.assertEqual(
            {path for path in self.root.rglob("*") if path.is_file()},
            {self.source, saved},
        )

    def test_assess_does_not_follow_a_dangling_report_symlink(self):
        output = self.root / "symlink assessments"
        output.mkdir()
        saved = output / f"{self.source.stem}_deski_assessment.json"
        victim = output / "not-yet-created.json"
        try:
            saved.symlink_to(victim.name)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Creating a file symlink is unavailable: {error}")
        self.assertTrue(saved.is_symlink())
        self.assertFalse(saved.exists())

        result = self._run_cli(str(self.source), "--assess", "--output-dir", str(output))

        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertTrue(saved.is_symlink())
        self.assertFalse(victim.exists())

    def test_dry_run_neither_creates_nor_overwrites_requested_outputs(self):
        missing = self.root / "not created"
        existing = self.root / "existing output"
        existing.mkdir()
        saved = existing / f"{self.source.stem}_deski_assessment.json"
        saved.write_bytes(b"existing private report\n")
        (existing / "unrelated.txt").write_bytes(b"do not touch\n")
        before = self._snapshot()

        for flags in (("--dry-run",), ("--assess", "--dry-run")):
            for option, output in (("--output-dir", missing), ("-o", existing)):
                with self.subTest(flags=flags, output=output):
                    result = self._run_cli(str(self.source), *flags, option, str(output))
                    self._assert_successful_report(result)
                    self.assertEqual(self._snapshot(), before)

    def test_rep_assessment_rejects_unsupported_and_extra_arguments(self):
        mapping = self.root / "valid mapping.json"
        mapping.write_text(json.dumps({
            "title": "Sales", "source_kind": "webi", "workspace": "Workspace",
            "semantic_model": "Model", "dax": "EVALUATE Sales",
            "columns": ["Sales[Amount]"],
        }), encoding="utf-8")
        output = self.root / "must not be created"
        before = self._snapshot()
        cases = (
            ["--global-assess"],
            ["--output-format", "fabric"],
            ["--output-format=pbip"],
            ["--no-compare"],
            ["--calendar-start", "2015"],
            ["--universe", str(self.root / "other.unx")],
            ["--rdl-mapping", str(mapping)],
            ["--rdl-output", str(self.root / "other.rdl")],
            ["--deploy", "workspace"],
            ["--batch", str(self.root)],
            ["--biar", str(self.root / "archive.biar")],
            ["--unknown-rep-option"],
            ["extra.rep"],
        )
        for extra in cases:
            with self.subTest(extra=extra):
                result = self._run_cli(
                    str(self.source), "--assess", "--output-dir", str(output), *extra,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self._snapshot(), before)

    def test_rep_assessment_cannot_start_a_server_migration(self):
        before = self._snapshot()
        with patch("migrate._run_server_migration") as server, \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = migration_main([
                str(self.source), "--dry-run", "--server", "https://127.0.0.1:1",
                "--folder", "/Public",
            ])
        self.assertNotEqual(result, 0)
        server.assert_not_called()
        self.assertEqual(self._snapshot(), before)

    def test_assess_rejects_an_empty_output_directory(self):
        before = self._snapshot()

        result = self._run_cli(str(self.source), "--assess", "--output-dir", "")

        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._snapshot(), before)

    def test_invalid_or_unassessed_rep_sources_do_not_generate(self):
        malformed = self.root / "malformed.rep"
        malformed.write_bytes(b"not a REP container")
        missing = self.root / "missing.rep"
        output = self.root / "must not be created"
        before = self._snapshot()
        cases = (
            [str(self.source), "--output-dir", str(output)],
            [str(malformed), "--assess", "--output-dir", str(output)],
            [str(missing), "--dry-run", "--output-dir", str(output)],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self._run_cli(*arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self._snapshot(), before)

    def test_inferred_rdl_requires_acknowledgement_for_real_rep_sql(self):
        candidate = next(item for item in self.inventory["sql_candidates"]
                         if item["sql"] == self.sql[1])
        selector = deski.desktop_intelligence_sql_selector(candidate)
        mapping = self.root / "Mappage régional.v1.json"
        mapping.write_text(json.dumps({
            "title": "Synthetic", "source_kind": "desktop_intelligence",
            "server": "sql.example.test", "database": "Demo", "columns": ["Name"],
        }), encoding="utf-8")
        report = mapping.with_suffix(".rdl")
        query = self.root / "Requête sélectionnée.m"
        base = [
            "--rdl-mapping", str(mapping), "--rdl-bo-source", str(self.source),
            "--rdl-sql-name", selector, "--rdl-power-query-output", str(query),
        ]
        ack = "--rdl-accept-unverified-rep-sql"
        bad_selector = base.copy()
        bad_selector[bad_selector.index("--rdl-sql-name") + 1] = "not-a-candidate"
        before = self._snapshot()
        cases = (
            base,
            [*bad_selector, ack],
            ["--rdl-mapping", str(mapping), "--rdl-bo-source", str(self.source), ack],
            ["--rdl-mapping", str(mapping), ack],
            [*base, ack, "--output-format=pbip"],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self._run_cli(*arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self._snapshot(), before)
                self.assertFalse(report.exists())
                self.assertFalse(query.exists())

        result = self._run_cli(*base, ack)
        self.assertEqual(result.returncode, 0, result.stderr)
        namespace = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
        self.assertEqual(
            ET.parse(report).findtext(".//r:CommandText", namespaces=namespace),
            self.sql[1],
        )
        self.assertIn(self.sql[1], query.read_text(encoding="utf-8"))
        self.assertIn("unverified", result.stdout.lower())
        self.assertIn("not_run", result.stdout.lower())

    def test_inferred_rdl_rejects_rep_acknowledgement_for_a_webi_source(self):
        source = self.root / "Synthetic WebI.wid"
        source.write_text(
            '<document><dataProvider name="Sales">'
            '<sql>SELECT Name FROM Sales</sql></dataProvider></document>',
            encoding="utf-8",
        )
        mapping = self.root / "WebI mapping.json"
        mapping.write_text(json.dumps({
            "title": "Synthetic", "source_kind": "webi",
            "server": "sql.example.test", "database": "Demo", "columns": ["Name"],
        }), encoding="utf-8")
        report = mapping.with_suffix(".rdl")
        arguments = [
            "--rdl-mapping", str(mapping), "--rdl-bo-source", str(source),
            "--rdl-sql-name", "Sales",
        ]
        before = self._snapshot()

        rejected = self._run_cli(*arguments, "--rdl-accept-unverified-rep-sql")
        self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
        self.assertEqual(self._snapshot(), before)
        self.assertFalse(report.exists())

        accepted = self._run_cli(*arguments)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        namespace = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}
        self.assertEqual(
            ET.parse(report).findtext(".//r:CommandText", namespaces=namespace),
            "SELECT Name FROM Sales",
        )
