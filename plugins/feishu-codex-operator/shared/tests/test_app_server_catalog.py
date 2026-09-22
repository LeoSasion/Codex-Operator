from __future__ import annotations

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)


from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = _OPERATOR_PLUGIN_ROOT
sys.path.insert(0, str(ROOT / "scripts"))

import operator_core.app_server_catalog as catalog_module  # noqa: E402


THREAD = "11111111-1111-1111-1111-111111111111"
BEEPER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class FakeSession:
    requests = []

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def request(self, method, params):
        self.requests.append((method, params))
        thread = {
            "id": THREAD,
            "name": "Desktop 任务",
            "cwd": "C:\\project",
            "projectId": "project-1",
            "status": {"type": "idle"},
            "ephemeral": False,
            "parentThreadId": None,
            "updatedAt": 42,
            "turns": [],
        }
        if method == "thread/list":
            return {
                "data": [thread, {**thread, "id": BEEPER, "name": "Minimal Beeper"}],
                "nextCursor": None,
            }
        if method == "thread/read":
            return {"thread": thread}
        raise AssertionError(method)


class AppServerCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeSession.requests = []
        self.catalog = catalog_module.AppServerCatalog(
            SimpleNamespace(
                app_server_timeout_seconds=10,
                codex_executable="",
                beeper_thread_id=BEEPER,
            ),
            executable=Path("C:/fake/codex.exe"),
        )

    def test_init_catalog_uses_native_read_only_methods_only(self) -> None:
        with patch.object(catalog_module, "AppServerSession", FakeSession):
            snapshot = self.catalog.list_task_catalog(
                visible_thread_ids=None,
                include_archived=False,
            )
            task = snapshot.tasks[0]
            inspection = self.catalog.inspect_thread(
                task.thread_id,
                expected_project_id=task.project_id,
                expected_host_id=task.host_id,
                catalog_snapshot_id=snapshot.snapshot_id,
                snapshot_fingerprint=task.snapshot_fingerprint,
            )

        self.assertEqual(THREAD, inspection.responder_thread_id)
        methods = [method for method, _ in FakeSession.requests]
        self.assertEqual(["thread/list", "thread/read"], methods)
        self.assertNotIn("thread/start", methods)
        self.assertNotIn("turn/start", methods)
        self.assertEqual(False, FakeSession.requests[1][1]["includeTurns"])

    def test_init_catalog_never_lists_or_inspects_the_minimal_beeper(self) -> None:
        with patch.object(catalog_module, "AppServerSession", FakeSession):
            snapshot = self.catalog.list_task_catalog(
                visible_thread_ids=None,
                include_archived=False,
            )
            self.assertEqual([THREAD], [task.thread_id for task in snapshot.tasks])
            with self.assertRaises(catalog_module.CatalogError):
                self.catalog.inspect_thread(
                    BEEPER,
                    expected_project_id="project-1",
                    expected_host_id="local",
                    catalog_snapshot_id=snapshot.snapshot_id,
                    snapshot_fingerprint="irrelevant",
                )

    def test_catalog_includes_other_providers_without_widening_task_visibility(self) -> None:
        external = "22222222-2222-4222-8222-222222222222"
        child = "33333333-3333-4333-8333-333333333333"
        class ProviderSession(FakeSession):
            def request(self, method, params):
                value = super().request(method, params)
                if method == "thread/list":
                    row = {**value['data'][0], 'id': external, 'modelProvider': 'registered_web'}
                    if params.get('modelProviders') == []:
                        value['data'].extend([row, {**row, 'id': child, 'parentThreadId': THREAD}])
                return value
        with patch.object(catalog_module, "AppServerSession", ProviderSession):
            snapshot = self.catalog.list_task_catalog(visible_thread_ids=[external, BEEPER, child], include_archived=False)
        self.assertEqual([external], [task.thread_id for task in snapshot.tasks])
        self.assertEqual(len(FakeSession.requests), 1)
        params = FakeSession.requests[0][1]
        self.assertIs(params['archived'], False)
        self.assertIs(params['useStateDbOnly'], True)
        self.assertEqual(params['sourceKinds'], ['cli', 'vscode', 'appServer'])

    def test_changed_snapshot_is_rejected_without_activating_a_task(self) -> None:
        with patch.object(catalog_module, "AppServerSession", FakeSession):
            snapshot = self.catalog.list_task_catalog(
                visible_thread_ids=None, include_archived=False,
            )
            task = snapshot.tasks[0]
            with self.assertRaises(catalog_module.CatalogError):
                self.catalog.inspect_thread(
                    task.thread_id,
                    expected_project_id=task.project_id,
                    expected_host_id=task.host_id,
                    catalog_snapshot_id="changed-snapshot",
                    snapshot_fingerprint=task.snapshot_fingerprint,
                )
        self.assertEqual(["thread/list", "thread/read"], [method for method, _ in FakeSession.requests])


if __name__ == "__main__":
    unittest.main()
