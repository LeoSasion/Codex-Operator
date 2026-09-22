"""Fixed metric labels, snapshots and disconnect accounting, never content."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import asyncio
import unittest

from operator_core.responses_metrics import CURRENT_METRICS, ResponsesMetrics, measure_current


class MetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_byte_is_measured_once_and_body_does_not_retain_content(self):
        import time
        metrics = ResponsesMetrics()
        async def chunks():
            yield b"synthetic private text"
            yield b"another private chunk"
        data = [chunk async for chunk in metrics.chunks(chunks(), time.perf_counter())]
        self.assertEqual(len(data), 2)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["stages"]["upstream_first_byte"]["count"], 1)
        self.assertNotIn("private", str(snapshot))
        snapshot["outcomes"]["failed"] = 999
        self.assertEqual(metrics.snapshot()["outcomes"]["failed"], 0)

    async def test_adaptation_cpu_context_is_reset_and_fixed_labels_only(self):
        metrics = ResponsesMetrics()
        token = CURRENT_METRICS.set(metrics)
        try:
            with self.assertRaises(RuntimeError), measure_current("response_adaptation"):
                raise RuntimeError("synthetic private diagnostic")
        finally:
            CURRENT_METRICS.reset(token)
        with self.assertRaises(ValueError):
            metrics.observe("synthetic prompt", 1)
        self.assertEqual(metrics.snapshot()["stages"]["response_adaptation"]["count"], 1)
        self.assertIsNone(CURRENT_METRICS.get())


if __name__ == "__main__":
    unittest.main()
