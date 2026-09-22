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


ROOT = _OPERATOR_PLUGIN_ROOT
sys.path.insert(0, str(ROOT / "scripts"))

from operator_core.responder_observer import (  # noqa: E402
    RUNNING_STATE,
    TERMINAL_STATE,
    UNKNOWN_STATE,
    ResponderLifecycleObserver,
    classify_turn_lifecycle,
)


THREAD_ID = "11111111-1111-1111-1111-111111111111"
BASE_TURN_ID = "22222222-2222-2222-2222-222222222222"
TARGET_TURN_ID = "33333333-3333-3333-3333-333333333333"


def turn(
    turn_id: str,
    status: str,
    *,
    completed_at: int | None = None,
    items: list[object] | None = None,
) -> dict[str, object]:
    return {
        "id": turn_id,
        "status": status,
        "startedAt": 100,
        "completedAt": completed_at,
        "items": [] if items is None else items,
        "itemsView": "notLoaded",
    }


class FakeSession:
    def __init__(self, snapshots: list[tuple[bool, list[dict[str, object]]]]) -> None:
        self.snapshots = snapshots
        self.snapshot_index = 0
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.initialized = False
        self.closed = False

    def initialize(self) -> None:
        self.initialized = True

    def request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self.requests.append((method, params))
        active, turns = self.snapshots[self.snapshot_index]
        if method == "thread/read":
            return {
                "thread": {
                    "id": THREAD_ID,
                    "status": {"type": "active" if active else "idle"},
                    "turns": [],
                }
            }
        if method == "thread/turns/list":
            self.snapshot_index = min(
                self.snapshot_index + 1,
                len(self.snapshots) - 1,
            )
            return {"data": turns, "nextCursor": None}
        raise AssertionError(method)

    def close(self) -> None:
        self.closed = True


class ResponderLifecycleObserverTests(unittest.TestCase):
    def test_transient_interrupted_without_completion_is_unknown(self) -> None:
        observation = classify_turn_lifecycle(
            turn(TARGET_TURN_ID, "interrupted"),
            thread_active=False,
        )
        self.assertEqual(UNKNOWN_STATE, observation.state)

    def test_explicit_thread_activity_is_running(self) -> None:
        observation = classify_turn_lifecycle(
            turn(TARGET_TURN_ID, "interrupted"),
            thread_active=True,
        )
        self.assertEqual(RUNNING_STATE, observation.state)

    def test_only_stable_completed_metadata_is_terminal(self) -> None:
        unstable = classify_turn_lifecycle(
            turn(TARGET_TURN_ID, "completed"),
            thread_active=False,
        )
        stable = classify_turn_lifecycle(
            turn(TARGET_TURN_ID, "completed", completed_at=120),
            thread_active=False,
        )
        self.assertEqual(UNKNOWN_STATE, unstable.state)
        self.assertEqual(TERMINAL_STATE, stable.state)

    def test_observer_reads_only_metadata_and_tracks_one_new_turn(self) -> None:
        session = FakeSession(
            [
                (False, [turn(BASE_TURN_ID, "completed", completed_at=90)]),
                (
                    True,
                    [
                        turn(TARGET_TURN_ID, "interrupted"),
                        turn(BASE_TURN_ID, "completed", completed_at=90),
                    ],
                ),
                (
                    False,
                    [
                        turn(TARGET_TURN_ID, "completed", completed_at=120),
                        turn(BASE_TURN_ID, "completed", completed_at=90),
                    ],
                ),
            ]
        )
        config = SimpleNamespace(
            codex_executable="",
            app_server_timeout_seconds=20,
        )
        observer = ResponderLifecycleObserver(
            config,
            executable=Path("codex.exe"),
            session_factory=lambda _path, _timeout: session,
        )

        watch = observer.begin(THREAD_ID)
        self.assertEqual(RUNNING_STATE, observer.poll(watch).state)
        self.assertEqual(TERMINAL_STATE, observer.poll(watch).state)
        observer.close(watch)

        self.assertTrue(session.initialized)
        self.assertTrue(session.closed)
        self.assertEqual(
            [
                "thread/read",
                "thread/turns/list",
                "thread/read",
                "thread/turns/list",
                "thread/read",
                "thread/turns/list",
            ],
            [method for method, _params in session.requests],
        )
        turn_requests = [
            params
            for method, params in session.requests
            if method == "thread/turns/list"
        ]
        self.assertTrue(turn_requests)
        for params in turn_requests:
            self.assertEqual("notLoaded", params["itemsView"])
            self.assertEqual(20, params["limit"])

    def test_content_bearing_response_disables_observer(self) -> None:
        session = FakeSession(
            [(False, [turn(BASE_TURN_ID, "completed", items=[{"type": "text"}])])]
        )
        config = SimpleNamespace(
            codex_executable="",
            app_server_timeout_seconds=20,
        )
        observer = ResponderLifecycleObserver(
            config,
            executable=Path("codex.exe"),
            session_factory=lambda _path, _timeout: session,
        )

        watch = observer.begin(THREAD_ID)

        self.assertIsNone(watch.session)
        self.assertTrue(session.closed)
        self.assertEqual(UNKNOWN_STATE, observer.poll(watch).state)


if __name__ == "__main__":
    unittest.main()
