"""One visible maintenance window for an explicit, bounded Desktop handoff.

Only status and a request to defer are exchanged. The window has no service,
configuration, model, process-termination or retry capability.
"""
from pathlib import Path
import json
import os
import subprocess
import time


class FeedbackError(ValueError):
    """Fixed, content-free reason for stopping before maintenance."""


def write_state(directory: Path, value: dict) -> None:
    from operator_unified_retire import _plain
    _plain(directory)
    path = directory / "feedback.jsonl"
    raw = (json.dumps(value, ensure_ascii=True) + "\n").encode("ascii")
    if len(raw) > 4096:
        raise FeedbackError("handoff_feedback_state_bound")
    if path.exists():
        _plain(path)
    # A bounded single-writer journal avoids Windows rename/open-handle races.
    # Readers use only complete newline-terminated snapshots, never a torn tail.
    with path.open("ab") as stream:
        if stream.tell() + len(raw) > 512 * 1024:
            raise FeedbackError("handoff_feedback_state_bound")
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def read_state(directory: Path) -> dict:
    from operator_unified_retire import _read
    raw = _read(directory / "feedback.jsonl", 512 * 1024)
    end = raw.rfind(b"\n")
    if end < 0:
        raise FeedbackError("handoff_feedback_incomplete")
    return json.loads(raw[:end].rsplit(b"\n", 1)[-1])


class Feedback:
    def __init__(self, directory: Path, session: str, seconds: int):
        self.directory, self.session, self.seconds = directory, session, seconds
        self.process = None
        self.deadline = 0

    def publish(self, phase: str, *, remaining: int = 0, outcome: str = "", counts=None):
        write_state(self.directory, {"schema_version": 1, "session": self.session,
            "phase": phase, "remaining_seconds": remaining, "outcome": outcome,
            "counts": counts, "updated_at": int(time.time())})

    def start(self):
        self.publish("preparing")
        shell = Path(os.environ.get("ProgramFiles", "")) / "PowerShell/7/pwsh.exe"
        script = Path(__file__).with_name("operator_handoff_status.ps1")
        self.process = subprocess.Popen([str(shell), "-NoLogo", "-NoProfile", "-NonInteractive",
            "-STA", "-WindowStyle", "Hidden", "-File", str(script),
            "-RunDirectory", str(self.directory), "-Session", self.session],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.check_open()
            ready = self.directory / "feedback-ready.json"
            if ready.exists():
                from operator_unified_retire import _read
                value = json.loads(_read(ready, 4096))
                if value != {"schema_version": 1, "session": self.session, "pid": self.process.pid}:
                    raise FeedbackError("handoff_feedback_ready_changed")
                self.deadline = time.monotonic() + self.seconds
                self.waiting()
                return
            time.sleep(0.1)
        raise FeedbackError("handoff_feedback_unavailable")

    def check_open(self):
        if self.process is None or self.process.poll() is not None:
            raise FeedbackError("handoff_feedback_closed")

    def check_wait(self):
        self.check_open()
        cancel = self.directory / "defer.json"
        if cancel.exists():
            from operator_unified_retire import _read
            if json.loads(_read(cancel, 4096)) != {"schema_version": 1, "session": self.session}:
                raise FeedbackError("handoff_defer_record_invalid")
            raise FeedbackError("handoff_deferred")

    def waiting(self, counts=None):
        self.check_wait()
        self.publish("waiting", remaining=max(0, int(self.deadline - time.monotonic())), counts=counts)

    def applying(self):
        # A request arriving after this boundary cannot undo an in-progress
        # transaction. The UI waits for the actual result before claiming defer.
        self.check_wait()
        self.publish("applying")

    def phase(self, stage: str):
        self.publish("opening" if stage == "activate_official" else "applying")

    def finish(self, result: dict):
        if result.get("status") == "config_switch_witnessed":
            outcome = "complete"
        elif result.get("reason") == "handoff_deferred":
            outcome = "deferred"
        elif result.get("stage") == "waiting_for_exit":
            outcome = "wait_expired" if result.get("reason") == "handoff_wait_expired" else "preflight_failed"
        elif result.get("native_reopen_witnessed") is True:
            outcome = "native_recovered"
        else:
            outcome = "review_required"
        self.publish("finished", outcome=outcome)
