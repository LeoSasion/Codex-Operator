"""One-shot Desktop-exit handoff for a reviewed unified cold launch.

Preparation saves only local evidence. The runner waits for a normal Desktop
exit, then uses each existing preview/commit pair once. A verified stopped
router may be started fresh after the old plan is archived. It never sends a
model request, closes Desktop, or retries a failed transaction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from operator_handoff_feedback import Feedback, FeedbackError, read_state


SOURCES = (
    "operator_handoff_feedback.py",
    "operator_handoff_status.ps1",
    "operator_unified_handoff.py",
    "operator_unified_supersede.py",
    "operator_unified_withdraw.py",
    "operator_unified_prepare.py",
    "operator_unified_marker_release.py",
    "operator_unified_cold_start.py",
    "operator_unified_retire.py",
    "operator_unified_failed_archive.py",
    "operator_unified_workflow_renew.py",
    "operator_web_startup.py",
    "operator_model_router.py",
    "operator_web_service.py",
    "operator_web_activation_retire.py",
    "operator_unified_upgrade.py",
    "operator_unified_entry_preview.py",
    "operator_unified_desktop.py",
    "restore-codex-official-route.ps1",
    "operator_desktop_setup.ps1",
    "operator_desktop_pair.psm1",
    "operator_desktop_pair_upgrade.psm1",
    "operator_desktop_pair_legacy.psm1",
    "operator_native_entry.ps1",
    "operator_core/model_router_config.py",
    "operator_core/responses_labels.py",
    "install-native-recovery-shortcut.ps1",
    "恢复官方默认路由.cmd",
    "operator_installation.psm1",
    "operator_entry_migration.ps1",
    "operator_entry_shortcut_adoption.ps1",
    "operator_entry_upgrade.ps1",
    "operator_desktop_entry.ps1",
    "operator_desktop_entry.cs",
)
RUN_NAME = re.compile(r"run-[a-f0-9]{32}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
MARKER = b"operator-native-route-only-v1\n"


class HandoffError(ValueError):
    """A fixed, content-free handoff failure."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _local_failure_reason(error: Exception) -> str | None:
    """Project only dated, typed local codes; never arbitrary exception text."""
    from operator_unified_supersede import SupersedeError
    from operator_unified_prepare import PrepareError
    from operator_unified_retire import RetireError
    from operator_core.windows_config_transaction import TransactionFailure

    supersede_codes = frozenset("""
        unified_prepared_archive_requires_review unified_prepared_plan_already_archived
        unified_prepared_plan_digest_invalid unified_supersede_archive_capacity
        unified_supersede_archive_requires_review unified_supersede_cache_appeared
        unified_supersede_cache_changed unified_supersede_cache_identity_changed
        unified_supersede_changed_after_intent unified_supersede_entry_changed
        unified_supersede_move_uncertain unified_supersede_native_lock_not_planned
        unified_supersede_native_state_changed unified_supersede_not_prepared
        unified_supersede_plan_scope unified_supersede_preflight_changed
        unified_supersede_prepared_copy_changed unified_supersede_python_mismatch
        unified_supersede_receipt_uncertain unified_supersede_review_changed
        unified_supersede_review_required unified_supersede_router_changed
        unified_supersede_source_changed unified_supersede_source_scope_changed
        unified_supersede_unexpected_plan_artifact unified_supersede_volume_changed
        unified_supersede_web_route_changed
    """.split())
    prepare_codes = frozenset("""
        unified_config_snapshot_changed unified_existing_preparation_requires_review
        unified_preparation_blocked unified_preparation_volume_changed
        unified_prepare_port_invalid unified_review_changed
        unified_review_changed_after_directory_creation unified_review_changed_after_snapshot_write
        unified_review_digest_required unified_router_identity_changed unified_router_token_invalid
    """.split())
    retire_codes = frozenset("""
        unified_retire_file_unavailable unified_retire_linked_path unified_retire_record_invalid
        unified_retired_archive_too_large unified_retired_archive_invalid
        unified_retired_archive_incomplete unified_retired_archive_changed
        unified_retired_archive_requires_review unified_retired_archive_scope
    """.split())
    transaction_codes = frozenset("""
        absolute_path_required backup_not_expected candidate_size_or_type candidate_unchanged
        config_name_required config_size_bound different_volume expected_file_changed
        file_changed_during_read intent_backup_invalid intent_invalid intent_target_invalid
        linked_file not_plain_directory not_plain_file reparse_path replacement_backup_mismatch
        replacement_target_changed snapshot_target_mismatch stage_changed_or_moved stage_still_present
        state_parent_not_directory stored_bytes_changed stored_size_bound target_not_candidate
        target_or_backup_changed transaction_directory_missing transaction_name_collision windows_only
    """.split())
    reason = str(error)
    for kind, codes in ((SupersedeError, supersede_codes), (PrepareError, prepare_codes),
                        (RetireError, retire_codes), (TransactionFailure, transaction_codes)):
        if type(error) is kind and reason in codes:
            return reason
    if type(error) in (TransactionFailure, PrepareError):
        match = re.fullmatch(r"(?:file_id|file_info|open|read|replacefile)_([0-9]{1,10})", reason)
        if match is not None and int(match[1]) <= 0xFFFFFFFF:
            return reason
    # Preparation may forward one of the retained prepared-archive codes.
    if type(error) is PrepareError and reason in supersede_codes:
        return reason
    return None


def _read(path: Path, limit: int = 65536) -> bytes:
    from operator_unified_retire import _read as checked_read

    return checked_read(path, limit)


def _write_new(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _sources() -> dict[str, str]:
    parent = Path(__file__).resolve().parent
    return {name: _sha(_read(parent / name, 1024 * 1024)) for name in SOURCES}


def _fixed_paths() -> tuple[Path, Path]:
    scripts = Path(__file__).resolve().parent
    return scripts.parent.parent.parent, scripts


def _manifest_path(project: Path, run: Path) -> Path:
    project_root, _ = _fixed_paths()
    if project != project_root or not run.is_absolute():
        raise HandoffError("handoff_project_scope_changed")
    if (run.name != "manifest.json" or RUN_NAME.fullmatch(run.parent.name) is None
            or run.parent.parent != project / ".codex/operator-unified-handoff"):
        raise HandoffError("handoff_manifest_scope_changed")
    return run


def _no_prior_upgrade(project: Path, plan_sha: str, *, current: Path | None = None) -> None:
    root = project / ".codex/operator-unified-handoff"
    if not root.exists():
        return
    import operator_unified_retire as records
    records._plain(root)
    if (root / ("upgrade-" + plan_sha + ".claim")).exists():
        raise HandoffError("handoff_prior_upgrade_requires_review")
    for index, run in enumerate(root.iterdir()):
        if index >= 256:
            raise HandoffError("handoff_history_bound")
        path = run / "manifest.json"
        if path == current:
            continue
        if not path.is_file():
            if run.is_dir() and any((run / name).exists() for name in ("launch-intent.json", "started.json")):
                raise HandoffError("handoff_prior_upgrade_requires_review")
            continue
        previous = json.loads(_read(path, 16384))
        if (previous.get("plan_sha256") == plan_sha and previous.get("plan_action") == "upgrade_witnessed"
                and any((run / name).exists() for name in ("launch-intent.json", "started.json"))):
            raise HandoffError("handoff_prior_upgrade_requires_review")


def _verify_activation_entry(plan: dict, python: Path) -> None:
    """Read-only cold-launch checks, before any native-lock release."""
    import operator_unified_cold_start as cold

    try:
        cold._verify_workflow(plan, python)
        cold._selected_entry(plan)
    except cold.ColdStartError as exc:
        # ColdStartError carries fixed public codes. Preserve the failure in
        # prepare's CLI result as well as the runner's terminal report.
        raise HandoffError(str(exc)) from exc


def prepare(project: Path, home: Path, python: Path, official: Path,
            *, wait_seconds: int = 120, complete_prepared: bool = False,
            upgrade_witnessed: bool = False, contract_updates: Path | None = None) -> dict:
    """Prepare a bounded, reviewable local handoff without changing routing."""
    from operator_core.web_browser_driver import private_directory
    import operator_unified_cold_start as cold
    import operator_unified_retire as records
    import operator_unified_supersede as supersede

    project = project.resolve(strict=True)
    home = home.resolve(strict=True)
    python = python.resolve(strict=True)
    official = official.resolve(strict=True)
    if project != _fixed_paths()[0] or python != Path(sys.executable).resolve(strict=True):
        raise HandoffError("handoff_source_or_python_changed")
    if not isinstance(wait_seconds, int) or not 30 <= wait_seconds <= 600:
        raise HandoffError("handoff_wait_bound")
    entry = project / ".codex/operator-desktop-entry/Codex拓展入口.exe"
    records._plain(entry)
    records._plain(official)
    if not entry.is_file() or not official.is_file() or official.name != "ChatGPT.exe":
        raise HandoffError("handoff_entry_unavailable")
    plan_path = home / "operator-unified-activation/plan.json"
    plan, plan_raw, _ = cold._plan(plan_path)
    if plan["project"] != str(project) or plan["home"] != str(home):
        raise HandoffError("handoff_native_preflight_changed")
    upgrade = None
    if upgrade_witnessed:
        from operator_unified_upgrade import inspect
        if complete_prepared:
            raise HandoffError("handoff_action_conflict")
        upgrade = inspect(plan_path, python, contract_updates)
        _no_prior_upgrade(project, _sha(plan_raw))
    elif (contract_updates is not None or cold.status(plan_path)["status"] != "prepared_not_armed"
            or _read(home / "operator-native-route-only", 4096) != MARKER):
        raise HandoffError("handoff_native_preflight_changed")
    current_config_sha = (_sha(_read(home / "config.toml", 1024 * 1024))
                          if complete_prepared or upgrade_witnessed else _current_native_config_sha(home, plan))
    if complete_prepared and current_config_sha != plan["config_sha256"]:
        raise HandoffError("handoff_saved_state_changed")
    try:
        router_mode = "bound_idle" if upgrade_witnessed else supersede._router_mode(plan)
    except Exception as exc:
        raise HandoffError("handoff_router_unverified") from exc
    if complete_prepared and router_mode != "bound_idle":
        raise HandoffError("handoff_router_unverified")
    if complete_prepared:
        _verify_activation_entry(plan, python)
    manifest = {"schema_version": 1, "project": str(project), "home": str(home),
                "python": str(python), "official": str(official),
                "official_sha256": _sha(_read(official, 64 * 1024 * 1024)),
                "entry": str(entry), "entry_sha256": _sha(_read(entry, 16 * 1024 * 1024)),
                "plan": str(plan_path), "plan_sha256": _sha(plan_raw),
                "config_sha256": current_config_sha,
                "router_mode": router_mode,
                "router_state": plan["router"]["state"],
                "web_profile": plan["router"]["web_profile"],
                "port": plan["router"]["port"], "wait_seconds": wait_seconds,
                "source_sha256": _sources()}
    if complete_prepared:
        manifest.update(schema_version=2, plan_action="complete_prepared")
    if upgrade_witnessed:
        manifest.update(schema_version=3, plan_action="upgrade_witnessed", upgrade=upgrade)
    root = project / ".codex/operator-unified-handoff"
    records._plain(root.parent)
    if not records._present(root):
        private_directory(root)
    run = root / ("run-" + uuid.uuid4().hex)
    private_directory(run)
    _write_new(run / "manifest.json", (json.dumps(manifest, sort_keys=True) + "\n").encode())
    return {"status": "handoff_prepared", "manifest": str(run / "manifest.json"),
            "router_mode": router_mode,
            "configuration_changed": False, "model_requests": 0}


def _load_manifest(path: Path) -> dict:
    import operator_unified_retire as records

    raw = _read(path, 16384)
    value = json.loads(raw)
    standard_keys = {
            "schema_version", "project", "home", "python", "official",
            "official_sha256", "entry", "entry_sha256", "plan", "plan_sha256",
            "config_sha256", "router_mode", "router_state", "web_profile", "port",
            "wait_seconds", "source_sha256"}
    if (not isinstance(value, dict) or not (
            (set(value) == standard_keys and value.get("schema_version") == 1)
            or (set(value) == standard_keys | {"plan_action"}
                and value.get("schema_version") == 2
                and value.get("plan_action") == "complete_prepared")
            or (set(value) == standard_keys | {"plan_action", "upgrade"}
                and value.get("schema_version") == 3 and value.get("plan_action") == "upgrade_witnessed"
                and isinstance(value.get("upgrade"), dict)))):
        raise HandoffError("handoff_manifest_invalid")
    project = Path(value["project"])
    _manifest_path(project, path)
    home = Path(value["home"])
    if (not home.is_absolute() or Path(value["plan"]) != home / "operator-unified-activation/plan.json"
            or Path(value["entry"]) != project / ".codex/operator-desktop-entry/Codex拓展入口.exe"
            or Path(value["python"]).resolve(strict=True) != Path(sys.executable).resolve(strict=True)
            or type(value["port"]) is not int or not 1024 <= value["port"] <= 65535
            or value["router_mode"] not in ("bound_idle", "stopped_exact_process_absent")
            or (value.get("plan_action") == "complete_prepared"
                and value["router_mode"] != "bound_idle")
            or type(value["wait_seconds"]) is not int or not 30 <= value["wait_seconds"] <= 600
            or any(not isinstance(value[key], str) or HEX64.fullmatch(value[key]) is None
                   for key in ("official_sha256", "entry_sha256", "plan_sha256", "config_sha256"))
            or not isinstance(value["source_sha256"], dict)
            or set(value["source_sha256"]) != set(SOURCES)):
        raise HandoffError("handoff_manifest_invalid")
    records._plain(path.parent)
    if (_sources() != value["source_sha256"]
            or _sha(_read(Path(value["entry"]), 16 * 1024 * 1024)) != value["entry_sha256"]
            or _sha(_read(Path(value["official"]), 64 * 1024 * 1024)) != value["official_sha256"]):
        raise HandoffError("handoff_source_changed")
    return value


def _current_native_config_sha(home: Path, plan: dict) -> str:
    import operator_unified_supersede as supersede

    saved = _read(home / "operator-unified-activation/before.toml", 1024 * 1024)
    if _sha(saved) != plan["config_sha256"]:
        raise HandoffError("handoff_saved_config_copy_changed")
    current = _read(home / "config.toml", 1024 * 1024)
    try:
        supersede._config_delta(saved, current)
    except supersede.SupersedeError as exc:
        raise HandoffError("handoff_native_config_changed") from exc
    return _sha(current)


def wait_for_normal_exit(check, *, seconds: int, clock=time.monotonic,
                         sleep=time.sleep, heartbeat=lambda: None,
                         guard=lambda: None) -> None:
    from operator_core.model_registry import RouterError
    deadline = clock() + seconds
    while clock() < deadline:
        heartbeat()
        guard()
        try:
            check()
            sleep(3)
            guard()
            check()
            return
        except RouterError as exc:
            if str(exc) != "web_startup_close_desktop_before_activation":
                raise HandoffError("handoff_exit_observation_unavailable") from exc
            sleep(2)
    raise HandoffError("handoff_wait_expired")


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _wmi_spawn(python: Path, manifest: Path, project: Path) -> int:
    """Start a hidden interactive-session worker through WMI, outside Desktop's job."""
    import base64

    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    worker = ("& " + _powershell_literal(str(python)) + " "
              + _powershell_literal(str(Path(__file__).resolve())) + " run --manifest "
              + _powershell_literal(str(manifest)) + "; exit $LASTEXITCODE")
    encoded_worker = base64.b64encode(worker.encode("utf-16le")).decode("ascii")
    command_line = subprocess.list2cmdline([str(shell), "-NoProfile", "-NonInteractive",
        "-WindowStyle", "Hidden", "-EncodedCommand", encoded_worker])
    controller = ("$ErrorActionPreference='Stop';"
        "$r=Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
        "@{CommandLine=" + _powershell_literal(command_line) + ";CurrentDirectory="
        + _powershell_literal(str(project)) + "};"
        "[pscustomobject]@{code=$r.ReturnValue;pid=$r.ProcessId}|ConvertTo-Json -Compress")
    encoded_controller = base64.b64encode(controller.encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run([str(shell), "-NoProfile", "-NonInteractive",
            "-WindowStyle", "Hidden", "-EncodedCommand", encoded_controller],
            cwd=project, capture_output=True, timeout=20, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW)
        value = json.loads(result.stdout)
        if (result.returncode != 0 or not isinstance(value, dict)
                or set(value) != {"code", "pid"} or value["code"] != 0
                or type(value["pid"]) is not int or value["pid"] <= 0):
            raise ValueError("create failed")
        return value["pid"]
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError) as exc:
        raise HandoffError("handoff_independent_launch_failed") from exc


def launch(path: Path) -> dict:
    """Start the one-shot runner outside the Desktop process tree."""
    if os.name != "nt":
        raise HandoffError("handoff_windows_required")
    import operator_web_service as web_service

    manifest = _load_manifest(path)
    run_dir = path.parent
    if manifest.get("plan_action") == "upgrade_witnessed":
        _no_prior_upgrade(Path(manifest["project"]), manifest["plan_sha256"], current=path)
        # The plan-scoped exclusive claim also fences two different prepared
        # manifests launched concurrently. It remains terminal after a crash.
        _write_new(run_dir.parent / ("upgrade-" + manifest["plan_sha256"] + ".claim"),
                   (json.dumps({"manifest_sha256": _sha(_read(path, 16384))}) + "\n").encode())
    if any((run_dir / name).exists() for name in
           ("launch-intent.json", "started.json", "result.json", "events.jsonl")):
        raise HandoffError("handoff_already_started_or_uncertain")
    _write_new(run_dir / "launch-intent.json", (json.dumps({
        "schema_version": 1, "manifest_sha256": _sha(_read(path, 16384)),
        "at": int(time.time())}) + "\n").encode())
    root_pid = _wmi_spawn(Path(manifest["python"]), path, Path(manifest["project"]))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if (run_dir / "result.json").exists():
            result = json.loads(_read(run_dir / "result.json", 4096))
            if result.get("status") == "config_switch_witnessed":
                return result
            raise HandoffError("handoff_stopped_before_exit_request")
        started = run_dir / "started.json"
        if started.exists():
            value = json.loads(_read(started, 4096))
            if not isinstance(value, dict):
                raise HandoffError("handoff_start_unwitnessed")
            worker_pid = value.get("pid")
            if (value.get("schema_version") != 1 or value.get("phase") != "may_have_handed_off"
                    or value.get("manifest_sha256") != _sha(_read(path, 16384))
                    or type(worker_pid) is not int or worker_pid <= 0):
                raise HandoffError("handoff_start_unwitnessed")
            current = worker_pid
            independent = False
            for _ in range(4):
                if current == root_pid and web_service.process_identity(root_pid) is not None:
                    independent = True
                    ready = run_dir / "feedback-ready.json"
                    if ready.exists():
                        shown = json.loads(_read(ready, 4096))
                        if (shown.get("schema_version") != 1 or
                                shown.get("session") != value["manifest_sha256"] or
                                type(shown.get("pid")) is not int or
                                web_service.process_identity(shown["pid"]) is None or
                                web_service.parent_pid(shown["pid"]) != worker_pid):
                            raise HandoffError("handoff_feedback_unavailable")
                        return {"status": "handoff_running", "manifest": str(path),
                                "feedback_window": "shown", "wait_seconds": manifest["wait_seconds"],
                                "configuration_changed": False, "model_requests": 0}
                    break
                current = web_service.parent_pid(current)
                if not isinstance(current, int) or current <= 0:
                    break
            if not independent:
                raise HandoffError("handoff_independent_process_unverified")
        if web_service.process_identity(root_pid) is None:
            raise HandoffError("handoff_independent_process_exited")
        time.sleep(0.2)
    raise HandoffError("handoff_launch_unwitnessed")


def _result(stage: str, status: str, *, native_reopen_attempted: bool = False) -> dict:
    return {"schema_version": 1, "stage": stage, "status": status,
            "native_reopen_attempted": native_reopen_attempted, "model_requests": 0}


def _package_launch_target(official: Path) -> tuple[str, str]:
    """Derive the exact installed Codex AUMID; never execute WindowsApps directly."""
    import xml.etree.ElementTree as ET

    package = official.parents[1]
    match = re.fullmatch(r"OpenAI\.Codex_[0-9]+(?:\.[0-9]+){3}_[A-Za-z0-9]+__([a-z0-9]+)",
                         package.name)
    if (official.name != "ChatGPT.exe" or official.parent.name != "app"
            or match is None):
        raise HandoffError("handoff_package_identity_changed")
    try:
        root = ET.fromstring(_read(package / "AppxManifest.xml", 1024 * 1024))
        namespace = "{http://schemas.microsoft.com/appx/manifest/foundation/windows10}"
        identity = root.find(namespace + "Identity")
        apps = root.find(namespace + "Applications")
        app = None if apps is None else next((item for item in apps
            if item.tag == namespace + "Application" and item.get("Id") == "App"), None)
        if (identity is None or identity.get("Name") != "OpenAI.Codex"
                or app is None or app.get("Executable") != "app/ChatGPT.exe"
                or app.get("EntryPoint") != "Windows.FullTrustApplication"):
            raise ValueError("package contract")
    except (OSError, ValueError, ET.ParseError) as exc:
        raise HandoffError("handoff_package_identity_changed") from exc
    return "OpenAI.Codex_" + match.group(1) + "!App", package.name


def _process_package_full_name(pid: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetPackageFullName.argtypes = [wintypes.HANDLE,
        ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR]
    kernel.GetPackageFullName.restype = wintypes.LONG
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        length = wintypes.UINT(0)
        code = kernel.GetPackageFullName(handle, ctypes.byref(length), None)
        if code == 15700:  # APPMODEL_ERROR_NO_PACKAGE
            return None
        if code != 122 or not 0 < length.value <= 512:
            raise HandoffError("handoff_package_identity_unavailable")
        buffer = ctypes.create_unicode_buffer(length.value)
        if kernel.GetPackageFullName(handle, ctypes.byref(length), buffer) != 0:
            raise HandoffError("handoff_package_identity_unavailable")
        return buffer.value
    finally:
        kernel.CloseHandle(handle)


def activate_official(official: Path) -> None:
    """Use the Windows packaged-app shell contract and witness its identity."""
    import operator_web_service as web_service
    import operator_web_startup as web_startup

    web_startup.assert_desktop_closed()
    aumid, package = _package_launch_target(official)
    explorer = Path(os.environ["SystemRoot"]) / "explorer.exe"
    if not explorer.is_file():
        raise HandoffError("handoff_package_activation_unavailable")
    subprocess.Popen([str(explorer), "shell:AppsFolder\\" + aumid],
        cwd=explorer.parent, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)
    # Explorer delegates to the shell broker. Its exit code or continued
    # lifetime does not prove whether the packaged application was activated.
    # Issue one activation only and judge the exact application below.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        for entry in web_service.windows_process_entries():
            if entry["name"].lower() != "chatgpt.exe":
                continue
            identity = web_service.process_identity(entry["pid"])
            if (identity is not None and Path(identity["executable"]) == official
                    and _process_package_full_name(entry["pid"]) == package):
                time.sleep(2)
                if web_service.process_identity(entry["pid"]) == identity:
                    return
        time.sleep(1)
    raise HandoffError("handoff_package_activation_unwitnessed")


def execute(manifest: dict, progress, run_directory: Path | None = None) -> None:
    """Run one strict sequence; each preview digest authorizes its next write."""
    import operator_unified_supersede as supersede
    import operator_unified_prepare as preparation
    import operator_unified_marker_release as marker
    import operator_unified_cold_start as cold
    import operator_model_router as router

    plan = Path(manifest["plan"])
    python = Path(manifest["python"])
    project = Path(manifest["project"])
    home = Path(manifest["home"])
    state = Path(manifest["router_state"])
    profile = Path(manifest["web_profile"])
    port = manifest["port"]

    def checked_progress(stage: str) -> None:
        if _sources() != manifest["source_sha256"]:
            raise HandoffError("handoff_source_changed")
        progress(stage)

    if (_sha(_read(plan, 16384)) != manifest["plan_sha256"]
            or _sha(_read(home / "config.toml", 1024 * 1024)) != manifest["config_sha256"]):
        raise HandoffError("handoff_saved_state_changed")
    saved_plan, _, _ = cold._plan(plan)
    if (manifest.get("plan_action") != "upgrade_witnessed"
            and supersede._router_mode(saved_plan) != manifest["router_mode"]):
        raise HandoffError("handoff_router_changed")
    if manifest.get("plan_action") == "upgrade_witnessed":
        from operator_unified_upgrade import execute as upgrade
        if run_directory is None:
            raise HandoffError("handoff_upgrade_evidence_directory_required")
        upgrade(manifest, checked_progress, run_directory)
    elif manifest.get("plan_action") == "complete_prepared":
        checked_progress("prepared_current")
        if (manifest["router_mode"] != "bound_idle"
                or cold.status(plan)["status"] != "prepared_not_armed"
                or supersede._router_mode(saved_plan) != "bound_idle"):
            raise HandoffError("handoff_prepared_plan_changed")
    else:
        checked_progress("supersede")
        review = supersede.preview(plan, python)
        if review.get("status") != "reviewed_preview":
            raise HandoffError("handoff_supersede_blocked")
        if supersede.supersede(plan, python, review["review_sha256"]).get("status") != "superseded_witnessed":
            raise HandoffError("handoff_supersede_unwitnessed")
        if manifest["router_mode"] == "stopped_exact_process_absent":
            checked_progress("start_router")
            if supersede._router_mode(saved_plan) != "stopped_exact_process_absent":
                raise HandoffError("handoff_router_changed")
            ready = router.start(state, port, web_profile=profile, require_fresh=True)
            if ready.get("status") != "ready":
                raise HandoffError("handoff_router_start_unwitnessed")
            checked_progress("bind_web")
            bound = router.bind_web(state, port, profile)
            if (bound.get("pid") != ready.get("pid")
                    or bound.get("service") != ready.get("service")):
                raise HandoffError("handoff_web_binding_unwitnessed")
        checked_progress("prepare")
        review = preparation.preview(project, home, state, profile, port)
        if (review.get("status") != "reviewed_preview" or not review.get("prepare_available")
                or review.get("blockers") != ["unified_native_route_lock_active"]):
            raise HandoffError("handoff_preparation_blocked")
        if preparation.prepare(project, home, state, profile, port,
                               review["review_sha256"]).get("status") != "prepared_not_armed":
            raise HandoffError("handoff_preparation_unwitnessed")
    checked_progress("marker_release")
    review = marker.preview(plan)
    if review.get("status") != "reviewed_preview":
        raise HandoffError("handoff_marker_blocked")
    # Supersede/upgrade may have created a new plan. Re-read that exact current
    # plan and validate its workflow and selected entry after the last preview,
    # while the native-only marker still protects the configuration.
    current_plan, _, _ = cold._plan(plan)
    _verify_activation_entry(current_plan, python)
    if marker.release(plan, review["review_sha256"]).get("status") != "released_witnessed":
        raise HandoffError("handoff_marker_unwitnessed")
    checked_progress("arm")
    if cold.arm(plan, python).get("status") != "armed_for_one_cold_launch":
        raise HandoffError("handoff_arm_unwitnessed")
    checked_progress("consume")


def run(path: Path) -> dict:
    import operator_web_startup as web_startup
    import operator_unified_cold_start as cold

    manifest = _load_manifest(path)
    run_dir = path.parent
    _write_new(run_dir / "started.json", (json.dumps({"schema_version": 1,
        "phase": "may_have_handed_off", "manifest_sha256": _sha(_read(path, 16384)),
        "pid": os.getpid()}) + "\n").encode())
    stage = "waiting_for_exit"
    last_heartbeat = [0.0]
    feedback = Feedback(run_dir, _sha(_read(path, 16384)), manifest["wait_seconds"])

    def heartbeat() -> None:
        now = time.monotonic()
        feedback.waiting()
        if now - last_heartbeat[0] < 10:
            return
        last_heartbeat[0] = now
        try:
            desktop_count = min(100, sum(
                row.get("name", "").lower() == "chatgpt.exe"
                for row in web_startup.manager.windows_process_entries()))
        except Exception:
            desktop_count = None
        with (run_dir / "heartbeat.json").open("wb") as stream:
            stream.write((json.dumps({"schema_version": 1,
                "stage": stage, "at": int(time.time()),
                "desktop_process_count": desktop_count}) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())

    def progress(value: str) -> None:
        nonlocal stage
        stage = value
        feedback.phase(value)
        with (run_dir / "events.jsonl").open("ab") as stream:
            stream.write((json.dumps({"stage": value, "at": int(time.time())}) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())

    try:
        feedback.start()
        wait_for_normal_exit(web_startup.assert_desktop_closed,
                             seconds=manifest["wait_seconds"], heartbeat=heartbeat,
                             guard=feedback.check_wait)
        _load_manifest(path)
        feedback.applying()
        execute(manifest, progress, run_dir)
        if cold.consume(Path(manifest["plan"]))["status"] != "config_switch_witnessed":
            raise HandoffError("handoff_witness_missing")
        progress("activate_official")
        activate_official(Path(manifest["official"]))
        result = _result("config_switch", "config_switch_witnessed")
        result["package_activation"] = "witnessed"
        result["desktop_acceptance"] = "unverified"
        _write_new(run_dir / "result.json", (json.dumps(result) + "\n").encode())
        try:
            feedback.finish(result)
        except Exception:
            pass  # A display error cannot reverse the witnessed activation.
        return result
    except Exception as exc:
        reopened = False
        reopen_witnessed = False
        try:
            if stage == "waiting_for_exit":
                raise HandoffError("handoff_no_maintenance_started")
            web_startup.assert_desktop_closed()
            from operator_unified_upgrade import native_reopen_safe
            recovered_native = (manifest.get("plan_action") == "upgrade_witnessed"
                                and native_reopen_safe(manifest, run_dir))
            if (recovered_native or (_sha(_read(Path(manifest["home"]) / "config.toml", 1024 * 1024))
                    == manifest["config_sha256"]
                    and not (Path(manifest["plan"]).parent / "attempt.json").exists())):
                official = Path(manifest["official"])
                if _sha(_read(official, 64 * 1024 * 1024)) == manifest["official_sha256"]:
                    reopened = True
                    activate_official(official)
                    reopen_witnessed = True
        except Exception:
            pass
        result = _result(stage, "stopped_for_review", native_reopen_attempted=reopened)
        result["native_reopen_witnessed"] = reopen_witnessed
        if stage == "waiting_for_exit":
            result["configuration_changed"] = False
        try:
            result["activation_status"] = cold.status(Path(manifest["plan"]))["status"]
        except Exception:
            result["activation_status"] = "unverified"
        from operator_core.model_registry import RouterError
        from operator_unified_cold_start import ColdStartError
        router_codes = {"router_existing_service_requires_review", "router_not_ready",
                        "router_fresh_service_identity_mismatch", "router_start_failed",
                        "web_route_selected_profile_mismatch", "web_route_identity_changed_no_retry",
                        "web_route_service_unavailable_no_retry", "web_route_binding_busy_no_retry",
                        "web_route_binding_throttled_no_retry", "web_route_catalog_collision"}
        result["reason"] = (str(exc) if isinstance(exc, (HandoffError, ColdStartError, FeedbackError))
                            or isinstance(exc, RouterError) and str(exc) in router_codes
                            else _local_failure_reason(exc) or "handoff_unexpected_error")
        _write_new(run_dir / "result.json", (json.dumps(result) + "\n").encode())
        try:
            feedback.finish(result)
        except Exception:
            pass  # The original terminal outcome is already retained, never replay.
        return result


def status(path: Path, *, clock=time.time) -> dict:
    """Classify a missing result as uncertain after its bounded witness window."""
    _manifest_path(_fixed_paths()[0], path)
    run_dir = path.parent
    result_path = run_dir / "result.json"
    if result_path.exists():
        return json.loads(_read(result_path, 4096))
    feedback_path = run_dir / "feedback.jsonl"
    if feedback_path.exists():
        try:
            view = read_state(run_dir)
            if (view.get("schema_version") != 1 or
                    view.get("session") != _sha(_read(path, 16384)) or
                    type(view.get("updated_at")) is not int or
                    not 0 <= clock() - view["updated_at"] <= 20):
                raise ValueError("stale or unrelated view")
            phase = view.get("phase")
            if phase == "waiting" and type(view.get("remaining_seconds")) is int:
                return {"status": "waiting_for_exit", "remaining_seconds":
                    max(0, min(600, view["remaining_seconds"])),
                    "configuration_changed": False, "model_requests": 0}
            if phase in {"applying", "opening"}:
                return {"status": phase, "model_requests": 0}
        except (OSError, ValueError, TypeError):
            pass  # A view never authorizes an operation or replaces its receipt.
    started = run_dir / "started.json"
    intent = run_dir / "launch-intent.json"
    if started.exists():
        age = clock() - started.stat().st_mtime
        state = "handoff_result_missing_review" if age > 900 else "waiting_or_unknown"
    elif intent.exists():
        age = clock() - intent.stat().st_mtime
        state = "handoff_start_unwitnessed_review" if age > 15 else "waiting_or_unknown"
    else:
        state = "handoff_prepared"
    result = {"status": state, "model_requests": 0}
    if state == "handoff_prepared":
        result["configuration_changed"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "prepare-current", "prepare-upgrade", "launch", "run", "status"))
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--official-exe", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--contract-updates", type=Path)
    args = parser.parse_args()
    try:
        if args.contract_updates and args.action != "prepare-upgrade":
            parser.error("contract updates require prepare-upgrade")
        if args.action in ("prepare", "prepare-current", "prepare-upgrade"):
            if (not all((args.project_root, args.codex_home, args.python, args.official_exe))
                    or args.manifest):
                parser.error("prepare requires project, home, Python and official exe")
            result = prepare(args.project_root, args.codex_home, args.python,
                             args.official_exe,
                             complete_prepared=args.action == "prepare-current",
                             upgrade_witnessed=args.action == "prepare-upgrade", contract_updates=args.contract_updates)
        elif args.action in ("launch", "run"):
            if not args.manifest or any((args.project_root, args.codex_home,
                                         args.python, args.official_exe)):
                parser.error("run requires one manifest")
            result = launch(args.manifest) if args.action == "launch" else run(args.manifest)
        else:
            if not args.manifest or any((args.project_root, args.codex_home,
                                         args.python, args.official_exe)):
                parser.error("status requires one manifest")
            result = status(args.manifest)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("status") in ("handoff_prepared", "handoff_running", "config_switch_witnessed") else 1
    except Exception as exc:
        reason = str(exc) if isinstance(exc, HandoffError) else "handoff_unavailable"
        print(json.dumps({"status": "handoff_unavailable", "reason": reason,
                          "configuration_changed": False,
                          "model_requests": 0}, sort_keys=True))
        return 1


if __name__ == "__main__":
    # Helpers import this module for its fixed-code exception. Execute through
    # the same module identity so those errors survive the public redaction gate.
    from operator_unified_handoff import main as canonical_main
    raise SystemExit(canonical_main())
