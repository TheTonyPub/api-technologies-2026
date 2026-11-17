import unittest

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY
from prometheus_client.parser import text_string_to_metric_families

from _stubs import install_env

install_env()

from app.main import metrics
from app.metrics import observe_run


class MetricsTests(unittest.TestCase):
    def test_exposition_records_success_and_error_without_sensitive_labels(self):
        def count(outcome):
            return REGISTRY.get_sample_value(
                "loader_runs_total", {"phase": "incremental", "outcome": outcome}
            ) or 0

        successes, failures = count("success"), count("error")
        with observe_run("incremental"):
            pass
        with self.assertRaisesRegex(RuntimeError, "private-detail"):
            with observe_run("incremental"):
                raise RuntimeError("private-detail")
        self.assertEqual(count("success"), successes + 1)
        self.assertEqual(count("error"), failures + 1)

        response = metrics()
        self.assertEqual(response.headers["content-type"], CONTENT_TYPE_LATEST)
        text = response.body.decode("utf-8")
        self.assertNotIn("private-detail", text)
        metrics_by_name = {metric.name for metric in text_string_to_metric_families(text)}
        self.assertIn("loader_run_duration_seconds", metrics_by_name)
        self.assertIn("loader_last_success_timestamp_seconds", metrics_by_name)
