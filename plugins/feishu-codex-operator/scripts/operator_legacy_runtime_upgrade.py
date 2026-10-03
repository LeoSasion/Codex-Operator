"""One-shot, reviewed runtime cutover for a pre-journal Operator install.

This intentionally does not establish first-install ownership of Hooks, rules,
shortcuts, configuration, or business data. A failed transaction is never
resumed automatically; its exact original bytes remain in a private backup.
Schema v2 may add exact reviewed model/search dependencies and update only the
startup Hook's literal inventory; this is maintenance, not first-install ownership.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
from functools import wraps
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import time
from typing import Any, Callable


RUNTIME_RELATIVE = Path(".codex/feishu-codex-operator-runtime")
MAINTENANCE_RELATIVE = Path(".codex/operator-channel-maintenance/legacy-runtime-upgrade")
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_BACKUP_BYTES = 256 * 1024 * 1024
MAX_BACKUP_FILES = 4096
HASH_RE = re.compile(r"[a-f0-9]{64}\Z")
VERSION_RE = re.compile(r"\bOPERATOR_VERSION\s*=\s*['\"]([^'\"]+)['\"]")
HOLD_ERROR = "producer_unavailable_no_retry"
EXPECTED_FILES_RE = re.compile(r"\$expectedFiles\s*=\s*@\((.*?)\)", re.S)
QUOTED_FILE_RE = re.compile(r"'([^'\r\n]+)'\s*,?\s*", re.S)
EXPECTED_FILES_BYTES_RE = re.compile(rb"\$expectedFiles\s*=\s*@\((.*?)\)", re.S)
REVIEWED_ADDITIONS = frozenset({"operator_core/web_native_interruption.py",
                              "operator_native_models.py"})
REVIEWED_SEARCH_ADDITIONS = frozenset({"operator_core/native_search.py"})
REVIEWED_ADDITION_SETS = (REVIEWED_ADDITIONS, REVIEWED_SEARCH_ADDITIONS,
                         REVIEWED_ADDITIONS | REVIEWED_SEARCH_ADDITIONS)
START_HOOK = ".codex/hooks/start-feishu-codex-operator.ps1"
ABSENT = {"sha256": "absent", "size": 0}
WEB_RECOVERY_ERRORS = frozenset({
    "cutover_web_recovery_receipt_invalid", "cutover_web_recovery_changed",
    "cutover_web_recovery_history_bound", "cutover_web_recovery_current_instance",
    "cutover_web_recovery_process_not_dead", "cutover_web_recovery_port_not_free",
    "cutover_web_recovery_unavailable",
})


class CutoverError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require(condition: bool, code: str) -> None:
    if not condition:
        raise CutoverError(code)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def plain_path(path: Path) -> None:
    """Reject links and Windows reparse points before resolving any path."""
    require(path.is_absolute(), "cutover_absolute_path_required")
    cursor = path
    while True:
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            pass
        else:
            require(not stat.S_ISLNK(info.st_mode)
                    and not (getattr(info, "st_file_attributes", 0) & 0x400),
                    "cutover_linked_path")
        if cursor.parent == cursor:
            return
        cursor = cursor.parent


def regular_bytes(path: Path, limit: int = MAX_MANIFEST_BYTES) -> bytes:
    plain_path(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= limit,
            "cutover_invalid_file")
    raw = path.read_bytes()
    require(len(raw) == info.st_size, "cutover_file_changed")
    return raw


def recovery_original_bytes(path: Path, *, status_snapshot: bool = False) -> bytes:
    if not status_snapshot:
        return regular_bytes(path, 65536)
    import operator_web_model as service

    plain_path(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= service.LEGACY_STATUS_SNAPSHOT_BYTES,
            'cutover_invalid_file')
    try:
        raw = service.read_status_bytes(path)
    except ValueError as exc:
        raise CutoverError('cutover_invalid_file') from exc
    require(len(raw) == info.st_size, 'cutover_file_changed')
    return raw


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(regular_bytes(path).decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise CutoverError("cutover_invalid_json") from exc
    require(isinstance(value, dict), "cutover_invalid_json")
    return value


def file_fingerprint(path: Path) -> dict[str, Any]:
    plain_path(path)
    if not path.exists():
        return {"sha256": "absent", "size": 0}
    info = path.stat()
    require(stat.S_ISREG(info.st_mode), "cutover_invalid_file")
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    require(path.stat().st_size == info.st_size, "cutover_file_changed")
    return {"sha256": hasher.hexdigest(), "size": info.st_size}


def checked_bytes(path: Path, fingerprint: dict[str, Any], code: str) -> bytes:
    raw = regular_bytes(path, max(fingerprint["size"], 1))
    require({"sha256": digest(raw), "size": len(raw)} == fingerprint, code)
    return raw


def expected_source(plugin: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    require(not candidate.is_absolute() and len(candidate.parts) >= 1
            and all(part not in ("", ".", "..") for part in candidate.parts),
            "cutover_runtime_file_name_invalid")
    if candidate.parts[0] == "licenses":
        require(len(candidate.parts) == 2 and candidate.suffix == ".txt",
                "cutover_runtime_file_name_invalid")
        source = plugin / "models/web/licenses" / candidate.name
    else:
        require(candidate.parts[0] != "operator.env", "cutover_runtime_file_name_invalid")
        source = plugin / "scripts" / Path(*candidate.parts)
    plain_path(source)
    return source


def runtime_snapshot(runtime: Path) -> dict[str, dict[str, Any]]:
    plain_path(runtime)
    require(runtime.is_dir(), "cutover_runtime_missing")
    result: dict[str, dict[str, Any]] = {}
    total = 0
    for directory, dirs, files in os.walk(runtime, followlinks=False):
        base = Path(directory)
        plain_path(base)
        for name in dirs:
            child = base / name
            plain_path(child)
            require(child.is_dir(), "cutover_invalid_runtime_tree")
        for name in files:
            child = base / name
            key = child.relative_to(runtime).as_posix()
            value = file_fingerprint(child)
            result[key] = value
            total += value["size"]
            require(len(result) <= MAX_BACKUP_FILES and total <= MAX_BACKUP_BYTES,
                    "cutover_backup_capacity_exceeded")
    return dict(sorted(result.items()))


def protected_snapshot(project: Path) -> dict[str, dict[str, Any]]:
    paths = ("AGENTS.md", ".codex/hooks.json",
             ".codex/hooks/start-feishu-codex-operator.ps1",
             ".codex/hooks/stop-feishu-codex-operator.ps1",
             ".codex/operator-desktop-entry/desktop-entry.json",
             ".codex/operator-desktop-entry/launcher-manifest.json")
    return {name: file_fingerprint(project / name) for name in paths}


def startup_inventory(path: Path) -> set[str]:
    """Accept only the literal startup guard inventory this cutover can review."""
    raw = regular_bytes(path, 2 * 1024 * 1024).decode("utf-8-sig")
    match = EXPECTED_FILES_RE.search(raw)
    require(match is not None, "cutover_startup_inventory_unreadable")
    entries = QUOTED_FILE_RE.findall(match.group(1))
    remaining = QUOTED_FILE_RE.sub("", match.group(1))
    require(not remaining.strip() and len(entries) == len(set(entries))
            and 40 <= len(entries) <= 100,
            "cutover_startup_inventory_unreadable")
    return set(entries)


def revised_start_hook(project: Path, plugin: Path) -> tuple[bytes, bytes]:
    """Replace only one literal inventory, with byte-identical surrounding code."""
    old = regular_bytes(project / START_HOOK, 2 * 1024 * 1024)
    source = regular_bytes(plugin / "scripts/start-feishu-codex-operator.ps1",
                           2 * 1024 * 1024)
    old_matches = list(EXPECTED_FILES_BYTES_RE.finditer(old))
    new_matches = list(EXPECTED_FILES_BYTES_RE.finditer(source))
    require(len(old_matches) == len(new_matches) == 1,
            "cutover_hook_inventory_ambiguous")
    before, after = old_matches[0], new_matches[0]
    require(old[:before.start(1)] == source[:after.start(1)]
            and old[before.end(1):] == source[after.end(1):],
            "cutover_hook_logic_requires_review")
    return old, old[:before.start(1)] + after.group(1) + old[before.end(1):]


def protected_after(plan: dict[str, Any]) -> dict[str, Any]:
    result = dict(plan["protected"])
    if plan.get("schema_version") == 2:
        result[START_HOOK] = plan["startup_hook"]["after"]
    return result


def check_restore_integrations(project: Path, plan: dict[str, Any]) -> None:
    current = protected_snapshot(project)
    if plan.get("schema_version") == 2:
        row = plan["startup_hook"]
        require(current[START_HOOK] in (row["before"], row["after"]),
                "cutover_restore_integration_changed")
        current[START_HOOK] = row["before"]
    require(current == plan["protected"], "cutover_restore_integration_changed")


def process_alive(pid: int) -> bool:
    if pid <= 0 or pid > 0xFFFFFFFF:
        raise CutoverError("cutover_pid_invalid")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


def process_gate(project: Path, plugin: Path) -> None:
    runtime = project / RUNTIME_RELATIVE
    for name in ("operator.pid", "operator.lock"):
        path = runtime / name
        if path.exists():
            raw = regular_bytes(path, 32).decode("ascii", errors="strict").strip()
            require(raw.isdecimal() and not process_alive(int(raw)),
                    "cutover_operator_running_or_uncertain")
    if os.name != "nt":
        return  # Disposable cross-platform tests inject their own service gate.
    # A missing/stale PID file is not proof that the exact script is absent.
    targets = [runtime / "operator_main.py", runtime / "operator_model_router.py",
               plugin / "scripts/operator_model_router.py",
               runtime / "operator_web_service.py",
               plugin / "scripts/operator_web_service.py"]
    env = dict(os.environ, CODEX_OPERATOR_CUTOVER_TARGETS=json.dumps(
        [str(path).replace("/", "\\").lower() for path in targets]))
    command = ("$ErrorActionPreference='Stop';"
               "$targets=ConvertFrom-Json $env:CODEX_OPERATOR_CUTOVER_TARGETS;"
               "$state='idle';"
               "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | ForEach-Object {"
               "if(-not $_.CommandLine){$state='uncertain'}else{"
               "$line=$_.CommandLine.Replace('/','\\').ToLowerInvariant();"
               "foreach($target in $targets){if($line.Contains($target) -and $state -ne 'uncertain'){$state='busy'}}}};"
               "$state")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                                 "-Command", command], env=env, capture_output=True,
                                timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CutoverError("cutover_process_identity_unavailable") from exc
    require(result.returncode == 0 and result.stdout.strip() in (b"idle", b"busy"),
            "cutover_process_identity_unavailable")
    require(result.stdout.strip() == b"idle", "cutover_processes_running")


def queue_gate(runtime: Path) -> dict[str, int]:
    for name in ("state.sqlite3", "callbacks.sqlite3"):
        require((runtime / name).is_file(), "cutover_state_missing")
        plain_path(runtime / name)
    try:
        inbox = sqlite3.connect((runtime / "state.sqlite3").as_uri() + "?mode=ro", uri=True)
        callback = sqlite3.connect((runtime / "callbacks.sqlite3").as_uri() + "?mode=ro", uri=True)
        try:
            inbox.execute("PRAGMA query_only=ON")
            callback.execute("PRAGMA query_only=ON")
            actionable = inbox.execute(
                "SELECT COUNT(*) FROM inbox_events WHERE status IS NULL OR "
                "(status NOT IN ('completed','terminal_failed') AND NOT "
                "(status='retryable_failed' AND COALESCE(last_error,'')=?))",
                (HOLD_ERROR,)).fetchone()[0]
            callbacks = callback.execute(
                "SELECT COUNT(*) FROM final_callback_requests "
                "WHERE state IS NULL OR state!='closed'").fetchone()[0]
        finally:
            inbox.close()
            callback.close()
    except sqlite3.Error as exc:
        raise CutoverError("cutover_state_unavailable") from exc
    require(actionable == 0 and callbacks == 0, "cutover_pending_work")
    return {"actionable_inbox": actionable, "open_callbacks": callbacks}


def _recovery_journal(profile: Path, receipt: Path) -> tuple[dict[str, Any], bytes, list[bytes]]:
    """Validate retained recovery bytes without treating retirement as a stop."""
    require(receipt.is_absolute() and ".." not in receipt.parts
            and receipt.name == "receipt.json"
            and receipt.parent.parent == profile / "history"
            and re.fullmatch(r"recovery-[a-f0-9]{32}", receipt.parent.name),
            "cutover_web_recovery_receipt_invalid")
    raw = regular_bytes(receipt, 65536)
    value = read_json(receipt)
    marker = value.get("marker")
    keys = {"version", "attempt", "instance", "session_sha256", "files", "marker",
            "preview_sha256", "phase", "outcome", "replayed", "launched"}
    if marker is not None:
        keys.add("archived_marker")
    require(set(value) == keys and type(value.get("version")) is int
            and value["version"] == 1 and value.get("phase") == "retired"
            and value.get("outcome") in ("uncontrolled_exit_retired",
                "unbound_request_free_stopped_snapshot_retired")
            and value.get("replayed") is False and value.get("launched") is False
            and all(isinstance(value.get(key), str)
                    and re.fullmatch(r"[a-f0-9]{32}", value[key])
                    for key in ("attempt", "instance"))
            and all(isinstance(value.get(key), str) and HASH_RE.fullmatch(value[key])
                    for key in ("session_sha256", "preview_sha256"))
            and (marker is None or isinstance(marker, str)),
            "cutover_web_recovery_receipt_invalid")
    state = profile / "instances" / value["attempt"]
    expected = [profile / "profile.json", profile / "current.json",
                profile / "instances" / (value["attempt"] + ".json"),
                state / "session.json", state / "status.json"]
    if marker is not None:
        original_marker = Path(marker)
        require(original_marker.is_absolute() and ".." not in original_marker.parts,
                "cutover_web_recovery_receipt_invalid")
        expected += [state / "connection.json", original_marker]
    else:
        original_marker = None
    require(value["outcome"] != "unbound_request_free_stopped_snapshot_retired"
            or marker is None, "cutover_web_recovery_receipt_invalid")
    files = value.get("files")
    require(isinstance(files, dict) and list(files) == [str(path) for path in expected]
            and all(isinstance(item, str) and HASH_RE.fullmatch(item) for item in files.values()),
            "cutover_web_recovery_receipt_invalid")
    preview = {key: value[key] for key in
               ("version", "attempt", "instance", "session_sha256", "files", "marker")}
    if value["outcome"] == "unbound_request_free_stopped_snapshot_retired":
        preview["outcome"] = value["outcome"]
    require(digest(json.dumps(preview, sort_keys=True).encode("utf-8"))
            == value["preview_sha256"], "cutover_web_recovery_receipt_invalid")
    expected_names = {"receipt.json", "current.json"} | {
        str(number) + ".original" for number in range(len(expected))}
    plain_path(receipt.parent)
    require({path.name for path in receipt.parent.iterdir()} == expected_names,
            "cutover_web_recovery_receipt_invalid")
    originals = []
    for number, expected_hash in enumerate(files.values()):
        original = recovery_original_bytes(receipt.parent / (str(number) + ".original"),
                                          status_snapshot=number == 4)
        require(digest(original) == expected_hash, "cutover_web_recovery_changed")
        originals.append(original)
        if number >= 2 and expected[number] != original_marker:
            require(recovery_original_bytes(expected[number], status_snapshot=number == 4) == original,
                    "cutover_web_recovery_changed")
    pointer = regular_bytes(receipt.parent / "current.json", 65536)
    pointer_value = json.loads(pointer.decode("utf-8-sig"))
    require(pointer == originals[1] and isinstance(pointer_value, dict)
            and type(pointer_value.get("version")) is int
            and pointer_value == {"version": 1, "attempt": value["attempt"]},
            "cutover_web_recovery_changed")
    if original_marker is not None:
        archived = original_marker.with_name("retired-" + receipt.parent.name + "-" + original_marker.name)
        require(value["archived_marker"] == str(archived)
                and regular_bytes(archived, 65536) == originals[-1]
                and archived.stat().st_nlink == 1,
                "cutover_web_recovery_changed")
    require(regular_bytes(receipt, 65536) == raw, "cutover_web_recovery_changed")
    return value, raw, originals


def _recovery_history(profile: Path) -> dict[str, str]:
    """An older completed receipt cannot hide another incomplete retirement."""
    history = profile / "history"
    plain_path(history)
    result = {}
    for index, path in enumerate(history.iterdir()):
        require(index < 4096, "cutover_web_recovery_history_bound")
        if not path.name.casefold().startswith("recovery-"):
            continue
        plain_path(path)
        require(path.is_dir(), "cutover_web_recovery_receipt_invalid")
        _, raw, _ = _recovery_journal(profile, path / "receipt.json")
        result[path.name] = digest(raw)
    return result


def retired_web_evidence(profile: Path, receipt: Path) -> dict[str, str]:
    """Read one explicitly selected completed dead-instance recovery under its Python."""
    import operator_web_service as manager

    profile, config = manager.load_profile(profile)
    require(manager.current_record(profile) is None,
            "cutover_web_recovery_current_instance")
    manager.require_complete_preinit_recoveries(profile)
    history = _recovery_history(profile)
    value, receipt_raw, originals = _recovery_journal(profile, receipt)
    require(value["outcome"] == "uncontrolled_exit_retired"
            and history.get(receipt.parent.name) == digest(receipt_raw),
            "cutover_web_recovery_receipt_invalid")
    require(regular_bytes(profile / "profile.json", 65536) == originals[0],
            "cutover_web_recovery_changed")
    for number, name in enumerate(value["files"]):
        if number == 1 or name == value["marker"]:
            continue
        require(recovery_original_bytes(Path(name), status_snapshot=number == 4) == originals[number],
                "cutover_web_recovery_changed")
    record = manager.read_json(profile / "instances" / (value["attempt"] + ".json"))
    require(type(record.get("version")) is int and record["version"] == 1
            and record.get("attempt") == value["attempt"]
            and record.get("phase") in ("starting", "running", "uncertain")
            and record.get("runtime") == config["runtime"]
            and {"worker", "instance", "session_sha256"} <= set(record),
            "cutover_web_recovery_receipt_invalid")
    state = manager.state_path(profile, record)
    session, session_hash = manager.session_snapshot(state, record)
    details = manager.read_status_json(state / "status.json")
    require(session["instance"] == value["instance"]
            and session_hash == value["session_sha256"]
            and details.get("instance") == session["instance"]
            and details.get("state") in ("ready", "preparing", "connection", "reconnecting",
                                        "assistance", "unavailable", "draining"),
            "cutover_web_recovery_receipt_invalid")
    require(not manager.owned_process(record, config)
            and manager.process_identity(session["pid"]) is None,
            "cutover_web_recovery_process_not_dead")
    manager.recovery_dependencies_absent(config)
    settings = manager.service.loads(manager.read_bytes(config["settings"]["path"]))
    if settings.get("transport", "text_only") == "mcp_v1":
        mcp = settings["mcp"]
        marker = Path(mcp["binding_file"]).parent / ("active-" + mcp["tunnel_id"] + ".json")
        plain_path(marker)
        require(value["marker"] == str(marker) and not marker.exists(),
                "cutover_web_recovery_changed")
        connection = manager.read_json(state / "connection.json")
        require(connection.get("instance") == session["instance"]
                and connection.get("tunnel_id") == mcp["tunnel_id"]
                and connection.get("kind") == "fixed_openai_tunnel"
                and isinstance(connection.get("connection_id"), str)
                and manager.ID.fullmatch(connection["connection_id"])
                and json.loads(originals[-1].decode("utf-8-sig")) == {
                    "version": 1, "instance": connection["connection_id"],
                    "pid": record["worker"]["pid"], "state": str(state)},
                "cutover_web_recovery_receipt_invalid")
    else:
        require(value["marker"] is None and len(value["files"]) == 5,
                "cutover_web_recovery_receipt_invalid")
    require(manager.fixed_connection_available(config), "cutover_web_recovery_changed")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        if os.name == "nt":
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            reservation.bind(("127.0.0.1", int(session["base_url"].split(":")[2][:-3])))
        except OSError as exc:
            raise CutoverError("cutover_web_recovery_port_not_free") from exc
        require(manager.load_profile(profile)[1] == config
                and manager.current_record(profile) is None
                and manager.fixed_connection_available(config)
                and _recovery_history(profile) == history
                and _recovery_journal(profile, receipt)[1] == receipt_raw,
                "cutover_web_recovery_changed")
        manager.require_complete_preinit_recoveries(profile)
        for number, name in enumerate(value["files"]):
            if number == 1 or name == value["marker"]:
                continue
            require(recovery_original_bytes(Path(name), status_snapshot=number == 4) == originals[number],
                    "cutover_web_recovery_changed")
        require(not manager.owned_process(record, config)
                and manager.process_identity(session["pid"]) is None,
                "cutover_web_recovery_process_not_dead")
        manager.recovery_dependencies_absent(config)
    return {"kind": "explicit_dead_web_recovery_v1", "receipt": str(receipt),
            "receipt_sha256": digest(receipt_raw), "profile_sha256": digest(originals[0]),
            "history_sha256": digest(canonical_json(history))}


def _retired_web_child(profile: Path, receipt: Path) -> dict[str, Any]:
    try:
        return {"status": "verified", "evidence": retired_web_evidence(profile, receipt)}
    except Exception as exc:
        return {"status": "blocked", "code": exc.code if isinstance(exc, CutoverError)
                else "cutover_web_recovery_unavailable"}


def _retired_web_probe(python: str, plugin: Path, profile: Path, receipt: Path) -> dict[str, str]:
    command = [python, "-I", "-B", "-c",
        "import json,sys;from pathlib import Path;sys.path[:0]=sys.argv[1:3];"
        "import operator_legacy_runtime_upgrade as c;"
        "print(json.dumps(c._retired_web_child(Path(sys.argv[3]),Path(sys.argv[4]))))",
        str(Path(__file__).resolve().parent), str(plugin / "scripts"), str(profile), str(receipt)]
    try:
        child = subprocess.run(command, capture_output=True, timeout=10, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        require(child.returncode == 0 and len(child.stdout) <= 65536,
                "cutover_web_recovery_unavailable")
        result = json.loads(child.stdout.decode("utf-8-sig"))
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError) as exc:
        raise CutoverError("cutover_web_recovery_unavailable") from exc
    if isinstance(result, dict) and result.get("status") == "blocked":
        code = result.get("code")
        raise CutoverError(code if isinstance(code, str) and code in WEB_RECOVERY_ERRORS
                           else "cutover_web_recovery_not_verified")
    require(isinstance(result, dict) and result.get("status") == "verified",
            "cutover_web_recovery_not_verified")
    evidence = result.get("evidence")
    require(isinstance(evidence, dict) and set(evidence) == {
                "kind", "receipt", "receipt_sha256", "profile_sha256", "history_sha256"}
            and evidence.get("kind") == "explicit_dead_web_recovery_v1"
            and evidence.get("receipt") == str(receipt)
            and all(isinstance(evidence.get(key), str) and HASH_RE.fullmatch(evidence[key])
                    for key in ("receipt_sha256", "profile_sha256", "history_sha256")),
            "cutover_web_recovery_not_verified")
    return evidence


def service_gate(project: Path, plugin: Path, *,
                 web_recovery_receipt: Path | None = None) -> dict[str, str] | None:
    # A stale or uncertain service identity blocks migration until separately
    # reviewed recovery; HTTP timeout or zero requests is never a stopped proof.
    profile = project / ".codex/operator-web-service"
    evidence = None
    require(web_recovery_receipt is None or profile.exists(),
            "cutover_web_recovery_receipt_invalid")
    if profile.exists():
        plain_path(profile)
        settings = read_json(profile / "profile.json")
        runtime_settings = settings.get("runtime")
        require(isinstance(runtime_settings, dict), "cutover_web_state_unavailable")
        python = runtime_settings.get("python")
        python_hash = runtime_settings.get("python_sha256")
        require(isinstance(python, str) and isinstance(python_hash, str)
                and HASH_RE.fullmatch(python_hash)
                and file_fingerprint(Path(python))["sha256"] == python_hash,
                "cutover_web_python_changed")
        command = [python, str(plugin / "scripts/operator_web_service.py"),
                   "status", "--profile", str(profile)]
        try:
            # The manager emits a localized JSON summary. With redirected pipes
            # Windows Python otherwise uses the current ANSI code page, which
            # cannot be decoded as UTF-8 even when the service is stopped.
            result = subprocess.run(command, capture_output=True, timeout=10,
                                    check=False,
                                    env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            status = json.loads(result.stdout.decode("utf-8-sig"))
        except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError) as exc:
            raise CutoverError("cutover_web_state_unavailable") from exc
        require(result.returncode == 0 and isinstance(status, dict)
                and status.get("configuration_current") is True,
                "cutover_web_not_confirmed_stopped")
        if web_recovery_receipt is None:
            require(status.get("status") == "stopped", "cutover_web_not_confirmed_stopped")
        else:
            require(status.get("status") == "configured",
                    "cutover_web_recovery_requires_configured")
            evidence = _retired_web_probe(python, plugin, profile, web_recovery_receipt)
    router = project / RUNTIME_RELATIVE / "model-router"
    if router.exists():
        plain_path(router)
        require(not (router / "codex-entry.json").exists(),
                "cutover_router_entry_active")
    # Even when there is no state directory, an unknown listener cannot be
    # mistaken for a stopped dedicated router.
    with socket.socket() as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", 4317))
        except OSError as exc:
            raise CutoverError("cutover_router_port_not_free") from exc
    return evidence


def _service_evidence(project: Path, plugin: Path, check: Callable[..., Any],
                      receipt: Path | None) -> dict[str, str] | None:
    return check(project, plugin) if receipt is None else check(
        project, plugin, web_recovery_receipt=receipt)


def source_version(plugin: Path) -> str:
    raw = regular_bytes(plugin / "scripts/operator_core/config.py", 2 * 1024 * 1024)
    match = VERSION_RE.search(raw.decode("utf-8"))
    require(match is not None, "cutover_source_version_missing")
    inventory = read_json(plugin / "assets/release-inventory.json")
    require(inventory.get("source_version") == match.group(1),
            "cutover_source_version_mismatch")
    return match.group(1)


def preview(project: Path, plugin: Path, *,
            process_check: Callable[[Path, Path], None] = process_gate,
            services_check: Callable[..., Any] = service_gate,
            web_recovery_receipt: Path | None = None) -> dict[str, Any]:
    require(project.is_absolute() and plugin.is_absolute(), "cutover_absolute_path_required")
    plain_path(project)
    plain_path(plugin)
    runtime = project / RUNTIME_RELATIVE
    require(runtime.is_dir(), "cutover_runtime_missing")
    require(not (project / ".codex/operator-installation/ownership.json").exists(),
            "cutover_not_legacy_install")
    old_raw = regular_bytes(runtime / "runtime-manifest.json")
    old = json.loads(old_raw.decode("utf-8-sig"))
    require(isinstance(old, dict) and old.get("schema_version") == 1
            and isinstance(old.get("code_files"), dict)
            and 40 <= len(old["code_files"]) <= 100,
            "cutover_manifest_invalid")
    installed_config = regular_bytes(runtime / "operator_core/config.py", 2 * 1024 * 1024)
    match = VERSION_RE.search(installed_config.decode("utf-8"))
    require(match is not None and old.get("operator_version") == match.group(1),
            "cutover_manifest_version_mismatch")
    old_entry = old.get("public_entry")
    require(isinstance(old_entry, dict)
            and old_entry.get("path") == str(plugin / "scripts/codex-operator.ps1")
            and isinstance(old_entry.get("sha256"), str)
            and HASH_RE.fullmatch(old_entry["sha256"]),
            "cutover_entry_identity_mismatch")
    installed_names = set(old["code_files"])
    source_names = startup_inventory(plugin / "scripts/start-feishu-codex-operator.ps1")
    require(installed_names == startup_inventory(project / START_HOOK),
            "cutover_runtime_inventory_mismatch")
    additions = source_names - installed_names
    require(not installed_names - source_names
            and (not additions or frozenset(additions) in REVIEWED_ADDITION_SETS),
            "cutover_runtime_inventory_mismatch")
    hook_update = None
    if additions:
        hook_before, hook_after = revised_start_hook(project, plugin)
        hook_update = {"before": {"sha256": digest(hook_before), "size": len(hook_before)},
                       "after": {"sha256": digest(hook_after), "size": len(hook_after)}}
    code: dict[str, dict[str, Any]] = {}
    for relative, old_hash in old["code_files"].items():
        require(isinstance(relative, str) and isinstance(old_hash, str)
                and HASH_RE.fullmatch(old_hash), "cutover_manifest_invalid")
        source = expected_source(plugin, relative)
        destination = runtime / Path(*PurePosixPath(relative).parts)
        before = file_fingerprint(destination)
        after = file_fingerprint(source)
        require(before["sha256"] == old_hash and after["sha256"] != "absent",
                "cutover_installed_or_source_changed")
        code[relative] = {"before": before, "after": after}
    for relative in sorted(additions):
        destination = runtime / Path(*PurePosixPath(relative).parts)
        before, after = file_fingerprint(destination), file_fingerprint(expected_source(plugin, relative))
        require(before == ABSENT and after["sha256"] != "absent"
                and destination.parent.is_dir(), "cutover_unowned_addition_exists")
        code[relative] = {"before": before, "after": after}
    hooks = protected_snapshot(project)
    require(hooks[".codex/hooks/start-feishu-codex-operator.ps1"]["sha256"]
            == old.get("start_hook_sha256")
            and hooks[".codex/hooks/stop-feishu-codex-operator.ps1"]["sha256"]
            == old.get("stop_hook_sha256"), "cutover_hook_identity_mismatch")
    process_check(project, plugin)
    queue = queue_gate(runtime)
    web_recovery = _service_evidence(project, plugin, services_check, web_recovery_receipt)
    snapshot = runtime_snapshot(runtime)
    new = {"schema_version": 1, "operator_version": source_version(plugin),
           "public_entry": {"path": str(plugin / "scripts/codex-operator.ps1"),
                            "sha256": file_fingerprint(
                                plugin / "scripts/codex-operator.ps1")["sha256"]},
           "code_files": {name: row["after"]["sha256"] for name, row in code.items()},
           "start_hook_sha256": hook_update["after"]["sha256"] if hook_update else old["start_hook_sha256"],
           "stop_hook_sha256": old["stop_hook_sha256"]}
    require(new["operator_version"] == old["operator_version"],
            "cutover_cross_version_requires_review")
    plan = {"schema_version": 2 if hook_update else 1, "project": str(project), "plugin": str(plugin),
            "old_manifest_sha256": digest(old_raw), "new_manifest": new,
            "code": code, "runtime_snapshot": snapshot, "protected": hooks,
            "queue": queue, "legacy_ownership_unresolved": True}
    if hook_update:
        plan["startup_hook"] = hook_update
    if web_recovery_receipt is not None:
        require(isinstance(web_recovery, dict)
                and web_recovery.get("receipt") == str(web_recovery_receipt),
                "cutover_web_recovery_not_verified")
        plan["web_recovery"] = web_recovery
    plan["preview_sha256"] = digest(canonical_json(plan))
    return plan


def atomic_bytes(path: Path, raw: bytes) -> None:
    plain_path(path)
    temporary = path.with_name(path.name + ".cutover-" + os.urandom(8).hex() + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def save_json(path: Path, value: dict[str, Any]) -> None:
    atomic_bytes(path, canonical_json(value))


@contextmanager
def operation_lock(maintenance: Path):
    """Serialize explicit apply/restore; the lock is released by the OS on crash."""
    path = maintenance / "operation.lock"
    plain_path(path)
    with path.open("a+b") as stream:
        if not path.stat().st_size:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise CutoverError("cutover_operation_busy_no_retry") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def locked_action(action):
    @wraps(action)
    def wrapped(project: Path, *args, **kwargs):
        maintenance = project / MAINTENANCE_RELATIVE
        plain_path(maintenance)
        maintenance.mkdir(parents=True, exist_ok=True)
        with operation_lock(maintenance):
            return action(project, *args, **kwargs)
    return wrapped


def backup_runtime(runtime: Path, destination: Path,
                   expected: dict[str, dict[str, Any]]) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for relative, fingerprint in expected.items():
        source = runtime / Path(*PurePosixPath(relative).parts)
        require(file_fingerprint(source) == fingerprint, "cutover_runtime_changed")
        target = destination / Path(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        plain_path(target)
        shutil.copyfile(source, target, follow_symlinks=False)
        require(file_fingerprint(target) == fingerprint, "cutover_backup_changed")


@locked_action
def apply(project: Path, plugin: Path, expected_digest: str, *,
          process_check: Callable[[Path, Path], None] = process_gate,
          services_check: Callable[..., Any] = service_gate,
          web_recovery_receipt: Path | None = None,
          writer: Callable[[Path, bytes], None] = atomic_bytes) -> dict[str, Any]:
    require(bool(HASH_RE.fullmatch(expected_digest)), "cutover_preview_required")
    maintenance = project / MAINTENANCE_RELATIVE
    transaction = maintenance / expected_digest
    require(not transaction.exists(), "cutover_transaction_exists_no_retry")
    plan = preview(project, plugin, process_check=process_check,
                   services_check=services_check, web_recovery_receipt=web_recovery_receipt)
    require(plan["preview_sha256"] == expected_digest,
            "cutover_preview_changed")
    runtime = project / RUNTIME_RELATIVE
    require(not transaction.exists(), "cutover_transaction_exists_no_retry")
    # An unresolved older cutover may have changed files before crashing.
    for child in maintenance.iterdir():
        if child.is_dir() and (child / "intent.json").exists():
            state = read_json(child / "intent.json").get("state")
            require(state in ("applied", "restored"),
                    "cutover_previous_transaction_uncertain")
    transaction.mkdir()
    manifest = {**plan["new_manifest"], "generated_at": int(time.time())}
    manifest_raw = canonical_json(manifest)
    intent = {"schema_version": plan["schema_version"], "state": "backing_up",
              "preview_sha256": expected_digest,
              "target_manifest_sha256": digest(manifest_raw),
              "legacy_ownership_unresolved": True}
    save_json(transaction / "intent.json", intent)
    save_json(transaction / "preview.json", plan)
    try:
        backup_runtime(runtime, transaction / "originals", plan["runtime_snapshot"])
        if plan["schema_version"] == 2:
            before, after = revised_start_hook(project, plugin)
            for label, raw in (("original", before), ("prepared", after)):
                path = transaction / ("startup-hook." + label + ".ps1")
                atomic_bytes(path, raw)
                require(file_fingerprint(path) == plan["startup_hook"][
                    "before" if label == "original" else "after"], "cutover_backup_changed")
        # The backup and original manifest are rechecked before the first write.
        require(preview(project, plugin, process_check=process_check,
                        services_check=services_check,
                        web_recovery_receipt=web_recovery_receipt)["preview_sha256"] == expected_digest,
                "cutover_preview_changed")
        intent["state"] = "prepared"
        save_json(transaction / "intent.json", intent)
        intent["state"] = "writing"
        save_json(transaction / "intent.json", intent)
        for relative, row in plan["code"].items():
            if row["before"] == row["after"]:
                continue
            process_check(project, plugin)
            queue_gate(runtime)
            require(_service_evidence(project, plugin, services_check, web_recovery_receipt)
                    == plan.get("web_recovery"), "cutover_web_recovery_changed")
            require(protected_snapshot(project) == plan["protected"],
                    "cutover_integration_changed")
            destination = runtime / Path(*PurePosixPath(relative).parts)
            source = expected_source(plugin, relative)
            require(file_fingerprint(destination) == row["before"]
                    and file_fingerprint(source) == row["after"],
                    "cutover_file_changed_before_write")
            writer(destination, checked_bytes(source, row["after"], "cutover_file_changed_before_write"))
            require(file_fingerprint(destination) == row["after"],
                    "cutover_file_changed_after_write")
        process_check(project, plugin)
        queue_gate(runtime)
        require(_service_evidence(project, plugin, services_check, web_recovery_receipt)
                == plan.get("web_recovery"), "cutover_web_recovery_changed")
        require(protected_snapshot(project) == plan["protected"],
                "cutover_integration_changed")
        if plan["schema_version"] == 2:
            hook = plan["startup_hook"]
            prepared_hook = transaction / "startup-hook.prepared.ps1"
            require(file_fingerprint(prepared_hook) == hook["after"]
                    and file_fingerprint(transaction / "startup-hook.original.ps1") == hook["before"]
                    and file_fingerprint(plugin / "scripts/start-feishu-codex-operator.ps1") == hook["after"],
                    "cutover_backup_changed")
            writer(project / START_HOOK, checked_bytes(prepared_hook, hook["after"], "cutover_backup_changed"))
        require(protected_snapshot(project) == protected_after(plan),
                "cutover_integration_changed")
        require(file_fingerprint(runtime / "runtime-manifest.json")["sha256"]
                == plan["old_manifest_sha256"], "cutover_manifest_changed")
        process_check(project, plugin)
        queue_gate(runtime)
        require(_service_evidence(project, plugin, services_check, web_recovery_receipt)
                == plan.get("web_recovery"), "cutover_web_recovery_changed")
        writer(runtime / "runtime-manifest.json", manifest_raw)
        require(file_fingerprint(runtime / "runtime-manifest.json")["sha256"]
                == intent["target_manifest_sha256"],
                "cutover_manifest_write_failed")
        for relative, row in plan["code"].items():
            require(file_fingerprint(runtime / Path(*PurePosixPath(relative).parts))
                    == row["after"], "cutover_file_changed_after_write")
        expected_runtime = dict(plan["runtime_snapshot"])
        expected_runtime.update({name: row["after"] for name, row in plan["code"].items()})
        expected_runtime["runtime-manifest.json"] = file_fingerprint(
            runtime / "runtime-manifest.json")
        observed = runtime_snapshot(runtime)
        require(observed == expected_runtime
                and protected_snapshot(project) == protected_after(plan),
                "cutover_protected_data_changed")
        process_check(project, plugin)
        queue_gate(runtime)
        require(_service_evidence(project, plugin, services_check, web_recovery_receipt)
                == plan.get("web_recovery"), "cutover_web_recovery_changed")
        intent["state"] = "applied"
        save_json(transaction / "intent.json", intent)
        return {"status": "applied", "transaction": str(transaction),
                "changed_code_files": sum(row["before"] != row["after"]
                                          for row in plan["code"].values()),
                "legacy_ownership_unresolved": True}
    except Exception as exc:
        intent["state"] = "failed"
        intent["failure_code"] = (exc.code if isinstance(exc, CutoverError)
                                  else "cutover_write_uncertain")
        save_json(transaction / "intent.json", intent)
        raise


@locked_action
def restore(project: Path, plugin: Path, preview_digest: str, *,
            process_check: Callable[[Path, Path], None] = process_gate,
            services_check: Callable[..., Any] = service_gate,
            web_recovery_receipt: Path | None = None,
            writer: Callable[[Path, bytes], None] = atomic_bytes) -> dict[str, Any]:
    require(bool(HASH_RE.fullmatch(preview_digest)), "cutover_preview_required")
    transaction = project / MAINTENANCE_RELATIVE / preview_digest
    plain_path(transaction)
    intent = read_json(transaction / "intent.json")
    plan = read_json(transaction / "preview.json")
    require(intent.get("preview_sha256") == preview_digest
            and plan.get("schema_version") in (1, 2)
            and intent.get("schema_version") == plan.get("schema_version")
            and plan.get("preview_sha256") == preview_digest
            and digest(canonical_json({k: v for k, v in plan.items()
                                      if k != "preview_sha256"})) == preview_digest
            and intent.get("state") in ("prepared", "writing", "failed", "applied")
            and isinstance(intent.get("target_manifest_sha256"), str)
            and HASH_RE.fullmatch(intent["target_manifest_sha256"]),
            "cutover_restore_identity_invalid")
    require(plan.get("project") == str(project) and plan.get("plugin") == str(plugin),
            "cutover_restore_identity_invalid")
    if plan["schema_version"] == 2:
        require(not intent.get("restore_attempted"), "cutover_restore_terminal_no_retry")
        added = {name for name, row in plan["code"].items() if row["before"] == ABSENT}
        require(frozenset(added) in REVIEWED_ADDITION_SETS
                and plan["startup_hook"]["before"] == plan["protected"][START_HOOK]
                and plan["startup_hook"]["after"]["sha256"] == plan["new_manifest"]["start_hook_sha256"],
                "cutover_restore_identity_invalid")
    else:
        added = set()
    recovery = plan.get("web_recovery")
    if recovery is not None:
        require(isinstance(recovery, dict) and isinstance(recovery.get("receipt"), str)
                and (web_recovery_receipt is None
                     or str(web_recovery_receipt) == recovery["receipt"]),
                "cutover_restore_identity_invalid")
        web_recovery_receipt = Path(recovery["receipt"])
    else:
        require(web_recovery_receipt is None, "cutover_restore_identity_invalid")
    process_check(project, plugin)
    queue_gate(project / RUNTIME_RELATIVE)
    require(_service_evidence(project, plugin, services_check, web_recovery_receipt) == recovery,
            "cutover_web_recovery_changed")
    runtime = project / RUNTIME_RELATIVE
    originals = transaction / "originals"
    require(runtime_snapshot(originals) == plan["runtime_snapshot"],
            "cutover_backup_changed")
    if plan["schema_version"] == 2:
        require(file_fingerprint(transaction / "startup-hook.original.ps1") == plan["startup_hook"]["before"]
                and file_fingerprint(transaction / "startup-hook.prepared.ps1") == plan["startup_hook"]["after"],
                "cutover_backup_changed")
    current = runtime_snapshot(runtime)
    require(set(plan["runtime_snapshot"]) <= set(current)
            <= set(plan["runtime_snapshot"]) | added,
            "cutover_restore_target_changed")
    for relative, row in plan["code"].items():
        require(current.get(relative, ABSENT) in (row["before"], row["after"]),
                "cutover_restore_target_changed")
    manifest_hash = current.get("runtime-manifest.json", {}).get("sha256")
    require(manifest_hash == plan["old_manifest_sha256"]
            or manifest_hash == intent["target_manifest_sha256"],
            "cutover_restore_manifest_changed")
    for relative, value in plan["runtime_snapshot"].items():
        if relative not in plan["code"] and relative != "runtime-manifest.json":
            require(current.get(relative) == value, "cutover_restore_data_changed")
    check_restore_integrations(project, plan)
    intent["state"] = "restoring"
    if plan["schema_version"] == 2:
        intent["restore_attempted"] = True
    save_json(transaction / "intent.json", intent)
    try:
        for relative, row in plan["code"].items():
            if row["before"] == row["after"]:
                continue
            process_check(project, plugin)
            queue_gate(runtime)
            require(_service_evidence(project, plugin, services_check, web_recovery_receipt) == recovery,
                    "cutover_web_recovery_changed")
            check_restore_integrations(project, plan)
            path = runtime / Path(*PurePosixPath(relative).parts)
            require(file_fingerprint(path) in (row["before"], row["after"]),
                    "cutover_restore_target_changed")
            if relative in added:
                current_file = file_fingerprint(path)
                require(current_file in (ABSENT, row["after"]),
                        "cutover_restore_target_changed")
                if current_file != ABSENT:
                    path.unlink()
            else:
                writer(path, checked_bytes(originals / Path(*PurePosixPath(relative).parts),
                                           row["before"], "cutover_backup_changed"))
            require(file_fingerprint(path) == row["before"],
                    "cutover_restore_write_failed")
        process_check(project, plugin)
        queue_gate(runtime)
        require(_service_evidence(project, plugin, services_check, web_recovery_receipt) == recovery,
                "cutover_web_recovery_changed")
        check_restore_integrations(project, plan)
        if plan["schema_version"] == 2:
            original_hook = transaction / "startup-hook.original.ps1"
            require(file_fingerprint(original_hook) == plan["startup_hook"]["before"],
                    "cutover_backup_changed")
            writer(project / START_HOOK, checked_bytes(original_hook,
                plan["startup_hook"]["before"], "cutover_backup_changed"))
        require(protected_snapshot(project) == plan["protected"],
                "cutover_restore_integration_changed")
        manifest_path = runtime / "runtime-manifest.json"
        require(file_fingerprint(manifest_path)["sha256"] in (
                    plan["old_manifest_sha256"], intent["target_manifest_sha256"]),
                "cutover_restore_manifest_changed")
        process_check(project, plugin)
        queue_gate(runtime)
        require(_service_evidence(project, plugin, services_check, web_recovery_receipt) == recovery,
                "cutover_web_recovery_changed")
        writer(manifest_path, checked_bytes(originals / "runtime-manifest.json",
            plan["runtime_snapshot"]["runtime-manifest.json"], "cutover_backup_changed"))
        require(runtime_snapshot(runtime) == plan["runtime_snapshot"]
                and protected_snapshot(project) == plan["protected"],
                "cutover_restore_write_failed")
        process_check(project, plugin)
        queue_gate(runtime)
        require(_service_evidence(project, plugin, services_check, web_recovery_receipt) == recovery,
                "cutover_web_recovery_changed")
        intent["state"] = "restored"
        save_json(transaction / "intent.json", intent)
        return {"status": "restored", "transaction": str(transaction),
                "legacy_ownership_unresolved": True}
    except Exception as exc:
        intent["state"] = "failed"
        intent["failure_code"] = (exc.code if isinstance(exc, CutoverError)
                                  else "cutover_restore_uncertain")
        save_json(transaction / "intent.json", intent)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "apply", "restore"))
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--expected-preview-sha256", default="")
    parser.add_argument("--web-recovery-receipt", type=Path,
                        help="Exact completed dead-Web recovery receipt; no clean-stop claim.")
    args = parser.parse_args()
    project = args.project_root
    plugin = Path(__file__).absolute().parent.parent
    try:
        require(os.name == "nt", "cutover_windows_only")
        require(project.is_absolute(), "cutover_absolute_path_required")
        if args.action == "preview":
            value = preview(project, plugin, web_recovery_receipt=args.web_recovery_receipt)
            result = {"status": "preview", "preview_sha256": value["preview_sha256"],
                      "code_files": len(value["code"]),
                      "changed_code_files": sum(row["before"] != row["after"]
                                                for row in value["code"].values()),
                      "runtime_backup_files": len(value["runtime_snapshot"]),
                      "runtime_backup_bytes": sum(row["size"] for row in value["runtime_snapshot"].values()),
                      "queue": value["queue"], "legacy_ownership_unresolved": True}
        elif args.action == "apply":
            result = apply(project, plugin, args.expected_preview_sha256,
                           web_recovery_receipt=args.web_recovery_receipt)
        else:
            result = restore(project, plugin, args.expected_preview_sha256,
                             web_recovery_receipt=args.web_recovery_receipt)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (CutoverError, OSError, UnicodeError, ValueError) as exc:
        code = exc.code if isinstance(exc, CutoverError) else "cutover_unavailable_no_retry"
        print(json.dumps({"status": "blocked", "code": code,
                          "legacy_ownership_unresolved": True}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
