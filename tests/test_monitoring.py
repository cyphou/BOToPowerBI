import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from powerbi_import.monitoring import (
    MigrationMonitor,
    _AzureMonitorBackend,
    _JsonBackend,
    _PrometheusBackend,
)


class MonitoringTests(unittest.TestCase):
    def test_json_metric_event_record_and_flush(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "nested", "monitor.jsonl")
            monitor = MigrationMonitor("json", log_path=path)

            monitor.record_metric("migration.duration_seconds", 12.5, workbook="Ventés")
            monitor.record_event("migration_complete", workbook="Ventés", fidelity=98.2)

            backend = monitor._backend
            self.assertEqual(len(backend._buffer), 2)
            self.assertEqual(backend._buffer[0]["type"], "metric")
            self.assertEqual(backend._buffer[0]["name"], "migration.duration_seconds")
            self.assertEqual(backend._buffer[0]["value"], 12.5)
            self.assertEqual(backend._buffer[0]["dimensions"], {"workbook": "Ventés"})
            self.assertIn("timestamp", backend._buffer[0])
            self.assertEqual(backend._buffer[1]["properties"], {"workbook": "Ventés", "fidelity": 98.2})

            self.assertEqual(monitor.flush(), 2)
            self.assertEqual(backend._buffer, [])
            self.assertEqual(monitor.flush(), None)

            with open(path, "r", encoding="utf-8") as handle:
                records = [json.loads(line) for line in handle if line.strip()]
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["dimensions"]["workbook"], "Ventés")

    def test_empty_json_buffer_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "missing", "monitor.jsonl")
            monitor = MigrationMonitor("json", log_path=path)
            self.assertIsNone(monitor.flush())
            self.assertFalse(os.path.exists(path))

    def test_standard_migration_metrics_and_event(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor = MigrationMonitor("json", log_path=os.path.join(directory, "metrics.jsonl"))
            monitor.record_migration("Synthetic Sales", 7.25, 96.5, tables=3, measures=14, visuals=5, pages=2)

            entries = monitor._backend._buffer
            self.assertEqual(len(entries), 7)
            metrics = {entry["name"]: entry["value"] for entry in entries if entry["type"] == "metric"}
            self.assertEqual(metrics, {
                "migration.duration_seconds": 7.25,
                "migration.fidelity_percent": 96.5,
                "migration.tables": 3,
                "migration.measures": 14,
                "migration.visuals": 5,
                "migration.pages": 2,
            })
            event = entries[-1]
            self.assertEqual(event["type"], "event")
            self.assertEqual(event["name"], "migration.complete")
            self.assertEqual(event["properties"]["workbook"], "Synthetic Sales")

    def test_none_backend_and_unknown_backend_fallback(self):
        none = MigrationMonitor("none")
        none.record_metric("ignored", 1, workbook="none")
        none.record_event("ignored", workbook="none")
        self.assertIsNone(none.flush())

        with tempfile.TemporaryDirectory() as directory:
            unknown = MigrationMonitor("not-a-backend", log_path=os.path.join(directory, "unknown.jsonl"))
            self.assertIsInstance(unknown._backend, _JsonBackend)
            unknown.record_metric("fallback", 9)
            self.assertEqual(unknown._backend._buffer[0]["value"], 9)

    def test_azure_offline_import_fallback_is_json_only(self):
        with tempfile.TemporaryDirectory() as directory:
            fallback_path = os.path.join(directory, "azure.jsonl")
            real_json_backend = _JsonBackend

            class LocalJsonBackend(real_json_backend):
                def __init__(self, log_path=None):
                    super().__init__(fallback_path)

            with patch("powerbi_import.monitoring._JsonBackend", LocalJsonBackend):
                with patch.dict(sys.modules, {"opencensus": None, "opencensus.ext": None, "opencensus.ext.azure": None, "opencensus.ext.azure.metrics_exporter": None}):
                    backend = _AzureMonitorBackend(connection_string="synthetic=value")
                    backend.record_metric("azure.metric", 3.0, {"region": "local"})
                    backend.record_event("azure.event", {"status": "test"})
                    self.assertEqual(backend.flush(), 2)

            with open(fallback_path, "r", encoding="utf-8") as handle:
                records = [json.loads(line) for line in handle]
            self.assertEqual([record["type"] for record in records], ["metric", "event"])

    def test_azure_optional_sdk_success_with_patched_module_and_no_network(self):
        modules = {}
        azure = types.ModuleType("opencensus.ext.azure")
        exporter = types.ModuleType("opencensus.ext.azure.metrics_exporter")
        azure.metrics_exporter = exporter
        opencensus = types.ModuleType("opencensus")
        ext = types.ModuleType("opencensus.ext")
        modules.update({
            "opencensus": opencensus,
            "opencensus.ext": ext,
            "opencensus.ext.azure": azure,
            "opencensus.ext.azure.metrics_exporter": exporter,
        })

        with tempfile.TemporaryDirectory() as directory:
            fallback_path = os.path.join(directory, "azure-success.jsonl")
            real_json_backend = _JsonBackend

            class LocalJsonBackend(real_json_backend):
                def __init__(self, log_path=None):
                    super().__init__(fallback_path)

            with patch("powerbi_import.monitoring._JsonBackend", LocalJsonBackend):
                with patch.dict(sys.modules, modules, clear=False):
                    backend = _AzureMonitorBackend(connection_string="synthetic=1")
                    self.assertIs(backend._client, exporter)
                    backend.record_metric("azure.metric", 2.5, {"sample": "yes"})
                    backend.record_event("azure.event", {"sample": "yes"})
                    self.assertGreaterEqual(len(backend._fallback._buffer), 2)
                    self.assertEqual(backend.flush(), 2)

    def test_prometheus_offline_fallback_and_empty_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            fallback_path = os.path.join(directory, "prometheus-offline.jsonl")
            real_json_backend = _JsonBackend

            class LocalJsonBackend(real_json_backend):
                def __init__(self, log_path=None):
                    super().__init__(fallback_path)

            with patch("powerbi_import.monitoring._JsonBackend", LocalJsonBackend):
                with patch.dict(sys.modules, {"prometheus_client": None}):
                    backend = _PrometheusBackend(gateway_url="http://127.0.0.1:9")
                    backend.record_metric("prom.metric", 4, {"label": "synthetic"})
                    backend.record_event("prom.event", {"status": "test"})
                    self.assertIsNone(backend._registry)
                    self.assertEqual(backend.flush(), 2)

    def test_prometheus_optional_sdk_success_uses_patched_push_no_network(self):
        collector_registry = type("CollectorRegistry", (), {})()
        gauges = []

        class FakeGauge:
            def __init__(self, name, description, labelnames=None, registry=None):
                self.name = name
                self.values = {}
                gauges.append(self)

            def labels(self, **labels):
                key = tuple(sorted(labels.items()))
                gauge = self

                class Bound:
                    def set(self, value):
                        gauge.values[key] = value
                return Bound()

            def set(self, value):
                self.values[()] = value

        prometheus = types.ModuleType("prometheus_client")
        prometheus.CollectorRegistry = lambda: collector_registry
        prometheus.Gauge = FakeGauge
        pushed = []
        prometheus.push_to_gateway = lambda gateway, job, registry: pushed.append((gateway, job, registry))

        with tempfile.TemporaryDirectory() as directory:
            fallback_path = os.path.join(directory, "prometheus-success.jsonl")
            real_json_backend = _JsonBackend

            class LocalJsonBackend(real_json_backend):
                def __init__(self, log_path=None):
                    super().__init__(fallback_path)

            with patch("powerbi_import.monitoring._JsonBackend", LocalJsonBackend):
                with patch.dict(sys.modules, {"prometheus_client": prometheus}):
                    backend = _PrometheusBackend(gateway_url="http://synthetic.invalid")
                    backend.record_metric("requests.count", 12, {"method": "GET"})
                    backend.record_metric("unlabeled.count", 5)
                    backend.record_event("migration.complete", {"workbook": "Synthetic"})
                    count = backend.flush()

        self.assertEqual(count, 3)
        self.assertEqual(pushed, [("http://synthetic.invalid", "bo_to_pbi", collector_registry)])
        self.assertEqual(gauges[0].values[(("method", "GET"),)], 12)
        self.assertEqual(gauges[1].values[()], 5)


if __name__ == "__main__":
    unittest.main()
