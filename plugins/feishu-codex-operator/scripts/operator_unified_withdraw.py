"""Withdraw one never-armed plan while retaining current native settings.

This explicitly abandons preparation; it does not prepare or authorize a new
activation. Config, cache, entry, services and Desktop remain untouched.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import argparse
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tomllib

import operator_unified_cold_start as cold
import operator_unified_prepare as preparation
import operator_unified_retire as records
import operator_unified_supersede as supersede
from operator_core import windows_config_transaction as transaction
from operator_core.web_browser_driver import private_directory


SOURCE_FILES = frozenset({"operator_unified_withdraw.py", "operator_unified_supersede.py",
    "operator_unified_cold_start.py", "operator_unified_prepare.py", "operator_unified_retire.py",
    "restore-codex-official-route.ps1", "operator_core/windows_config_transaction.py"})
ENTRY_REQUIRED = frozenset({"desktop-entry.json", "launcher-manifest.json",
    "operator_desktop_entry.ps1", "Codex拓展入口.exe"})
ENTRY_OPTIONAL = frozenset({"Codex拓展入口.ico", "native-only"})
REVIEW_KEYS = frozenset({"schema_version", "scope", "project", "home", "plan_sha256",
    "manifest_sha256", "directory_identity", "source_sha256", "config", "marker", "cache", "entry"})
EMPTY_REVIEW_KEYS = (REVIEW_KEYS - {"plan_sha256", "manifest_sha256"}) | {"failure_evidence"}
EMPTY_SCOPE = "reviewed_empty_preallocation_withdrawal"
EMPTY_FAILURE = {"status": "unavailable", "reason": "unified_review_changed_after_directory_creation",
                 "activation_available": False, "configuration_changed": False, "model_requests": 0}


class WithdrawError(ValueError):
    """Fixed public diagnostics without paths, configuration or credentials."""


def _source_sha256() -> dict:
    source = Path(__file__).resolve().parent
    return {name: records._hash(records._read(source / name)) for name in sorted(SOURCE_FILES)}


def _snapshot(path: Path, *, optional: bool = False) -> dict | None:
    if optional and not records._present(path):
        records._plain(path.parent)
        return None
    item = transaction._snapshot(path)
    return {"sha256": records._hash(item.data), "identity": records._identity(item)}


def _directory_identity(path: Path) -> dict:
    records._plain(path)
    with transaction._open(path, directory=True) as handle:
        value, _ = transaction._identity(handle)
        return {"volume": value.volume, "file_id": value.file_id}


class _DirectoryRow(ctypes.Structure):
    _fields_ = [("next", wintypes.DWORD), ("index", wintypes.DWORD),
        ("created", ctypes.c_int64), ("accessed", ctypes.c_int64),
        ("written", ctypes.c_int64), ("changed", ctypes.c_int64),
        ("size", ctypes.c_int64), ("allocated", ctypes.c_int64),
        ("attributes", wintypes.DWORD), ("name_length", wintypes.DWORD),
        ("ea_size", wintypes.DWORD), ("short_length", ctypes.c_byte),
        ("short_name", wintypes.WCHAR * 12), ("file_id", ctypes.c_int64),
        ("name", wintypes.WCHAR * 1)]


class _RenameInfo(ctypes.Structure):
    _fields_ = [("flags", wintypes.DWORD), ("root", wintypes.HANDLE),
               ("name_length", wintypes.DWORD), ("name", wintypes.WCHAR * 1)]


@contextmanager
def _allocation_directory_handle(path: Path, *, moving: bool = False, parent: bool = False):
    """The moving handle forbids replacement without relinquishing its identity."""
    if os.name != "nt":
        raise WithdrawError("unified_withdraw_windows_required")
    records._plain(path)
    access = 0x80 | (0x20 if parent else 1) | (0x10000 if moving else 0)
    share = 3 if moving or parent else 7
    kernel = transaction._kernel
    handle = kernel.CreateFileW(str(path), access, share, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise WithdrawError("unified_withdraw_directory_unavailable")
    try:
        _, info = transaction._identity(handle)
        if not info.attributes & 0x10 or info.attributes & 0x400:
            raise WithdrawError("unified_withdraw_directory_unavailable")
        yield handle
    finally:
        kernel.CloseHandle(handle)


def _empty_handle_identity(handle) -> dict:
    """Enumerate the actual handle, never a possibly replaced path spelling."""
    before, info = transaction._identity(handle)
    if not info.attributes & 0x10 or info.attributes & 0x400:
        raise WithdrawError("unified_withdraw_directory_unavailable")
    # Empty directories contain at most the two dot entries. Any malformed,
    # unexpectedly repeated or overlong enumeration is an uncertainty, not empty.
    seen = set()
    for page in range(4):
        buffer = ctypes.create_string_buffer(4096)
        if not transaction._kernel.GetFileInformationByHandleEx(handle, 11 if page == 0 else 10,
                buffer, len(buffer)):
            if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                raise WithdrawError("unified_withdraw_directory_unavailable")
            after, _ = transaction._identity(handle)
            if before != after:
                raise WithdrawError("unified_withdraw_directory_changed")
            return {"volume": before.volume, "file_id": before.file_id}
        offset = 0
        for _ in range(3):
            if offset + ctypes.sizeof(_DirectoryRow) > len(buffer):
                raise WithdrawError("unified_withdraw_directory_unavailable")
            row = _DirectoryRow.from_buffer(buffer, offset)
            start, length = offset + _DirectoryRow.name.offset, row.name_length
            if not length or length % 2 or start + length > len(buffer):
                raise WithdrawError("unified_withdraw_directory_unavailable")
            name = buffer.raw[start:start + length].decode("utf-16-le", errors="strict")
            if name not in {".", ".."}:
                raise WithdrawError("unified_withdraw_allocation_not_empty")
            if name in seen:
                raise WithdrawError("unified_withdraw_directory_unavailable")
            seen.add(name)
            if not row.next:
                break
            if row.next < _DirectoryRow.name.offset + length or row.next % 8:
                raise WithdrawError("unified_withdraw_directory_unavailable")
            offset += row.next
        else:
            raise WithdrawError("unified_withdraw_directory_unavailable")
    raise WithdrawError("unified_withdraw_directory_unavailable")


def empty_allocation_directory_identity(path: Path) -> dict:
    """Read-only schema-v3 archive witness, compatible with a held moving handle."""
    with _allocation_directory_handle(path) as handle:
        return _empty_handle_identity(handle)


def _rename_empty_allocation_handle(source_handle, target_handle, target: Path, expected: dict) -> None:
    if _empty_handle_identity(source_handle) != expected:
        raise WithdrawError("unified_withdraw_directory_changed")
    parent_identity = transaction._identity(target_handle)[0]
    if parent_identity.volume != expected["volume"]:
        raise WithdrawError("unified_withdraw_volume_changed")
    if (not target.is_absolute() or target.name != "activation"
            or _directory_identity(target.parent) != {"volume": parent_identity.volume,
                                                       "file_id": parent_identity.file_id}):
        raise WithdrawError("unified_withdraw_directory_changed")
    # All target ancestors remain open without delete sharing. SetFileInformationByHandle
    # receives one absolute destination and the already-bound source handle.
    name = str(target).encode("utf-16-le")
    buffer = ctypes.create_string_buffer(_RenameInfo.name.offset + len(name) + 2)
    value = _RenameInfo.from_buffer(buffer)
    value.flags = 0  # FileRenameInfo: ReplaceIfExists=False, no overwrite/fallback.
    value.root = None
    value.name_length = len(name)
    ctypes.memmove(ctypes.addressof(buffer) + _RenameInfo.name.offset, name, len(name))
    kernel = transaction._kernel
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                 ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    if not kernel.SetFileInformationByHandle(source_handle, 3, buffer, len(buffer)):
        raise WithdrawError("unified_withdraw_move_failed")


@contextmanager
def _completion_fence_handle(path: Path, expected: bytes):
    """A new transaction-only fence remains present unless its own handle commits."""
    records._plain(path)
    kernel = transaction._kernel
    handle = kernel.CreateFileW(str(path), 0x80010000, 1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise WithdrawError("unified_withdraw_completion_fence_unavailable")
    try:
        raw, _ = transaction._read_handle(handle)
        if raw != expected:
            raise WithdrawError("unified_withdraw_completion_fence_changed")
        yield handle
    finally:
        kernel.CloseHandle(handle)


def _commit_completion_fence(handle) -> None:
    # FileDispositionInfo marks only this verified newly-created file for
    # deletion on close. It cannot select or replace a path that changed later.
    delete = ctypes.c_ubyte(1)
    kernel = transaction._kernel
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                 ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)):
        raise WithdrawError("unified_withdraw_completion_fence_unavailable")


def _native_config(raw: bytes) -> None:
    """Use the existing conservative recovery parser, without applying it."""
    try:
        parsed = tomllib.loads(raw.decode("utf-8-sig"))
        for key in ("experimental_realtime_webrtc_call_base_url", "experimental_realtime_ws_base_url"):
            if key in parsed and parsed[key] != "https://chatgpt.com/backend-api/codex":
                raise ValueError("native realtime route unverified")
        shell = shutil.which("pwsh")
        if not shell or os.name != "nt":
            raise ValueError("native inspection unavailable")
        script = r'''
$ErrorActionPreference='Stop'
try {
    $request=[Console]::In.ReadToEnd() | ConvertFrom-Json -AsHashtable
    . $request.helper -Library
    foreach ($scope in @('Process','User','Machine')) {
        if ([Environment]::GetEnvironmentVariable('OPENAI_BASE_URL',$scope)) {exit 3}
    }
    $result=Get-RecoveryConfigPlan ([Convert]::FromBase64String($request.bytes))
    if ($result.state -cne 'native' -or $result.changed) {exit 4}
    [Console]::WriteLine('{"native":true}')
} catch {exit 5}
'''
        result = subprocess.run([shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            input=json.dumps({"helper": str(Path(__file__).with_name("restore-codex-official-route.ps1")),
                              "bytes": base64.b64encode(raw).decode("ascii")}),
            capture_output=True, text=True, encoding="utf-8", timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or json.loads(result.stdout) != {"native": True}:
            raise ValueError("native route unverified")
    except Exception as exc:
        raise WithdrawError("unified_withdraw_native_route_unverified") from exc


def _entry(project: Path) -> dict:
    """Capture the current installed entry, without approving or updating it."""
    bundle = project / ".codex/operator-desktop-entry"
    records._plain(bundle)
    if not bundle.is_dir():
        raise WithdrawError("unified_withdraw_entry_unavailable")
    result = {name: _snapshot(bundle / name) for name in sorted(ENTRY_REQUIRED)}
    for name in sorted(ENTRY_OPTIONAL):
        result[name] = _snapshot(bundle / name, optional=True)
    config = json.loads(records._read(bundle / "desktop-entry.json", 16384))
    build = json.loads(records._read(bundle / "launcher-manifest.json", 16384))
    if (not isinstance(config, dict) or not isinstance(build, dict)
            or config.get("schema_version") != 1
            or config.get("mode") not in {"native", "reviewed_startup"}
            or build.get("schema_version") != 1 or build.get("native_fallback") != "native-only-v1"
            or build.get("entry_script_sha256") != result["operator_desktop_entry.ps1"]["sha256"]
            or config.get("entry_script_sha256") != result["operator_desktop_entry.ps1"]["sha256"]
            or build.get("binary_sha256") != result["Codex拓展入口.exe"]["sha256"]):
        raise WithdrawError("unified_withdraw_entry_unavailable")
    return result


def _current(plan: dict) -> dict:
    home, project = Path(plan["home"]), Path(plan["project"])
    records._plain(project)
    if not project.is_dir():
        raise WithdrawError("unified_withdraw_project_unavailable")
    config = transaction.observe_config(home / "config.toml")
    marker = transaction._snapshot(home / "operator-native-route-only")
    if marker.data != supersede.MARKER:
        raise WithdrawError("unified_withdraw_native_marker_changed")
    _native_config(config.data)
    return {"config": {"sha256": records._hash(config.data), "identity": records._identity(config)},
            "marker": {"sha256": records._hash(marker.data), "identity": records._identity(marker)},
            "cache": _snapshot(home / "models_cache.json", optional=True), "entry": _entry(project)}


def _inspect(plan_path: Path, *, pending: Path | None = None) -> dict:
    plan, raw, directory = cold._plan(plan_path)
    home = Path(plan["home"])
    if directory != home / supersede.SOURCE:
        raise WithdrawError("unified_withdraw_plan_scope")
    blockers = plan.get("future_arm_blockers")
    if (not isinstance(blockers, list) or any(not isinstance(value, str) for value in blockers)
            or len(blockers) != len(set(blockers))
            or "unified_native_route_lock_active" not in blockers
            or not set(blockers) <= preparation.REVIEW_BLOCKERS):
        raise WithdrawError("unified_withdraw_original_native_lock_required")
    if records.archive_status(home)["status"] == "uncertain":
        raise WithdrawError("unified_withdraw_retired_archive_requires_review")
    archive = supersede.archive_status(home, pending=pending)
    if archive["status"] == "uncertain" or (pending is not None and archive["status"] != "pending_internal"):
        raise WithdrawError("unified_withdraw_archive_requires_review")
    if pending is None and archive["generations"] >= 32:
        raise WithdrawError("unified_withdraw_archive_capacity")
    journal = json.loads(records._read(directory / "journal.json", 16384))
    if journal != {"schema_version": 1, "phase": "prepared_not_armed", "plan_sha256": records._hash(raw)}:
        raise WithdrawError("unified_withdraw_not_unused_preparation")
    try:
        manifest = supersede._manifest(directory)
    except supersede.SupersedeError as exc:
        raise WithdrawError("unified_withdraw_not_unused_preparation") from exc
    cache = plan["cache"]
    if (not isinstance(cache, dict) or set(cache) != {"existed", "sha256", "identity"}
            or type(cache["existed"]) is not bool
            or manifest["plan.json"]["sha256"] != records._hash(raw)
            or manifest["before.toml"]["sha256"] != plan["config_sha256"]
            or manifest["candidate.toml"]["sha256"] != plan["candidate_sha256"]
            or cache["existed"] != ("cache-before.bin" in manifest)
            or (cache["existed"] and manifest["cache-before.bin"]["sha256"] != cache["sha256"])
            or (cache["existed"] and not _valid_snapshot({"sha256": cache["sha256"], "identity": cache["identity"]}))
            or (not cache["existed"] and (cache["sha256"] is not None or cache["identity"] is not None))):
        raise WithdrawError("unified_withdraw_prepared_copy_changed")
    return {"schema_version": 1, "scope": "unused_prepared_plan_withdrawal",
            "project": plan["project"], "home": plan["home"], "plan_sha256": records._hash(raw),
            "manifest_sha256": records._hash(records._json(manifest)),
            "directory_identity": _directory_identity(directory),
            "source_sha256": _source_sha256(), **_current(plan)}


def preview(plan_path: Path) -> dict:
    review = _inspect(plan_path)
    return {"status": "withdrawal_preview", "review_sha256": records._hash(records._json(review)),
            "phase": "prepared_not_armed", "configuration_changed": False,
            "cache_changed": False, "entry_changed": False, "model_requests": 0}


@contextmanager
def _entry_mutex(project: Path):
    if os.name != "nt":
        raise WithdrawError("unified_withdraw_windows_required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    key = records._hash(str(project).rstrip("\\").lower().encode("utf-8")).upper()
    handle = kernel.CreateMutexW(None, False, "Local\\CodexOperatorDesktopEntry-" + key)
    if not handle:
        raise WithdrawError("unified_withdraw_entry_mutex_unavailable")
    owns = False
    try:
        owns = kernel.WaitForSingleObject(handle, 0) in (0, 0x80)
        if not owns:
            raise WithdrawError("unified_withdraw_entry_busy")
        yield
    finally:
        if owns:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def _valid_snapshot(value, *, optional: bool = False) -> bool:
    if value is None:
        return optional
    if not isinstance(value, dict) or set(value) != {"sha256", "identity"}:
        return False
    identity = value["identity"]
    return (isinstance(value["sha256"], str) and records.HEX64.fullmatch(value["sha256"]) is not None
            and isinstance(identity, dict) and set(identity) == {"volume", "file_id"}
            and type(identity["volume"]) is int and 0 <= identity["volume"] < 2 ** 64
            and isinstance(identity["file_id"], str) and re.fullmatch(r"[a-f0-9]{32}", identity["file_id"]) is not None)


def _freeze_current(review: dict, stack: ExitStack) -> None:
    home, project = Path(review["home"]), Path(review["project"])
    files = [(home / "config.toml", review["config"]),
             (home / "operator-native-route-only", review["marker"]),
             (home / "models_cache.json", review["cache"])]
    files.extend((project / ".codex/operator-desktop-entry" / name, value)
                 for name, value in review["entry"].items())
    for path, expected in files:
        if expected is None:
            records._plain(path.parent)
            if records._present(path):
                raise WithdrawError("unified_withdraw_review_changed")
            continue
        current = transaction._snapshot_while_frozen(path, stack)
        if {"sha256": records._hash(current.data), "identity": records._identity(current)} != expected:
            raise WithdrawError("unified_withdraw_review_changed")


def validate_archive_intent(intent: dict, receipt: dict, intent_raw: bytes) -> None:
    """Strict schema-v2 supplement; shared archive path/manifest checks stay on."""
    review = intent.get("review")
    if (set(intent) != {"schema_version", "phase", "home", "source", "target",
                       "plan_sha256", "review", "review_sha256", "manifest"}
            or intent["schema_version"] != 2 or intent["phase"] != "may_have_withdrawn"
            or not isinstance(review, dict) or set(review) != REVIEW_KEYS
            or review["schema_version"] != 1 or review["scope"] != "unused_prepared_plan_withdrawal"
            or not isinstance(review["project"], str) or not Path(review["project"]).is_absolute()
            or review["home"] != intent["home"] or not isinstance(review["home"], str)
            or not Path(review["home"]).is_absolute()
            or not isinstance(review["plan_sha256"], str) or records.HEX64.fullmatch(review["plan_sha256"]) is None
            or intent["plan_sha256"] != review["plan_sha256"]
            or intent["review_sha256"] != records._hash(records._json(review))
            or not isinstance(intent["manifest"], dict)
            or review["manifest_sha256"] != records._hash(records._json(intent["manifest"]))
            or not _valid_snapshot({"sha256": review["plan_sha256"], "identity": review["directory_identity"]})
            or not isinstance(review["source_sha256"], dict) or set(review["source_sha256"]) != SOURCE_FILES
            or any(not isinstance(v, str) or records.HEX64.fullmatch(v) is None for v in review["source_sha256"].values())
            or not _valid_snapshot(review["config"]) or not _valid_snapshot(review["marker"])
            or review["marker"]["sha256"] != records._hash(supersede.MARKER)
            or not _valid_snapshot(review["cache"], optional=True)
            or not isinstance(review["entry"], dict) or set(review["entry"]) != ENTRY_REQUIRED | ENTRY_OPTIONAL
            or any(not _valid_snapshot(review["entry"][name], optional=name in ENTRY_OPTIONAL)
                   for name in review["entry"])
            or receipt != {"schema_version": 2, "phase": "withdrawn_witnessed",
                           "intent_sha256": records._hash(intent_raw), "plan_sha256": intent["plan_sha256"]}):
        raise WithdrawError("unified_withdraw_archive_invalid")


def _failure_bytes(raw: bytes) -> None:
    try:
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate key")
                value[key] = item
            return value
        value = json.loads(raw, object_pairs_hook=unique)
        if (len(raw) > 16384 or value != EMPTY_FAILURE
                or type(value.get("model_requests")) is not int
                or value.get("configuration_changed") is not False
                or value.get("activation_available") is not False):
            raise ValueError("failure shape")
    except Exception as exc:
        raise WithdrawError("unified_withdraw_failure_evidence_invalid") from exc


def _empty_paths(project: Path, home: Path, failure_evidence: Path) -> tuple[Path, Path, Path]:
    paths = [Path(project), Path(home), Path(failure_evidence)]
    if any(not path.is_absolute() for path in paths):
        raise WithdrawError("unified_withdraw_scope_invalid")
    for path in paths:
        records._plain(path)
    project, home, failure_evidence = (path.resolve(strict=True) for path in paths)
    if (not project.is_dir() or not home.is_dir()
            or failure_evidence.is_relative_to(home / supersede.SOURCE)
            or failure_evidence.is_relative_to(home / supersede.ROOT)):
        raise WithdrawError("unified_withdraw_scope_invalid")
    return project, home, failure_evidence


def _inspect_empty(project: Path, home: Path, failure_evidence: Path,
                   expected_failure_sha256: str, *, pending: Path | None = None) -> dict:
    if not isinstance(expected_failure_sha256, str) or records.HEX64.fullmatch(expected_failure_sha256) is None:
        raise WithdrawError("unified_withdraw_failure_digest_required")
    project, home, failure_evidence = _empty_paths(project, home, failure_evidence)
    snapshot = transaction._snapshot(failure_evidence)
    _failure_bytes(snapshot.data)
    if records._hash(snapshot.data) != expected_failure_sha256:
        raise WithdrawError("unified_withdraw_failure_evidence_changed")
    if records.archive_status(home)["status"] == "uncertain":
        raise WithdrawError("unified_withdraw_retired_archive_requires_review")
    archive = supersede.archive_status(home, pending=pending)
    if archive["status"] == "uncertain" or (pending is not None and archive["status"] != "pending_internal"):
        raise WithdrawError("unified_withdraw_archive_requires_review")
    if pending is None and archive["generations"] >= supersede.MAX_GENERATIONS:
        raise WithdrawError("unified_withdraw_archive_capacity")
    return {"schema_version": 1, "scope": EMPTY_SCOPE, "project": str(project), "home": str(home),
            "directory_identity": empty_allocation_directory_identity(home / supersede.SOURCE),
            "source_sha256": _source_sha256(),
            "failure_evidence": {"path": str(failure_evidence), "sha256": expected_failure_sha256},
            **_current({"project": str(project), "home": str(home)})}


def preview_empty_allocation(project: Path, home: Path, failure_evidence: Path,
                             expected_failure_sha256: str) -> dict:
    review = _inspect_empty(project, home, failure_evidence, expected_failure_sha256)
    return {"status": "empty_allocation_withdrawal_preview", "scope": EMPTY_SCOPE,
            "review_sha256": records._hash(records._json(review)),
            "configuration_changed": False, "cache_changed": False,
            "entry_changed": False, "model_requests": 0}


def validate_empty_allocation_intent(intent: dict) -> None:
    """Strict independent schema: no plan, journal or installation ownership is inferred."""
    try:
        review = intent["review"]
        failure = review["failure_evidence"]
        home, project = Path(review["home"]), Path(review["project"])
        target = Path(intent["target"])
        if (set(intent) != {"schema_version", "phase", "home", "source", "target", "review",
                            "review_sha256", "manifest"}
                or type(intent["schema_version"]) is not int or intent["schema_version"] != 3
                or intent["phase"] != "may_have_withdrawn_empty_allocation"
                or not isinstance(review, dict) or set(review) != EMPTY_REVIEW_KEYS
                or type(review["schema_version"]) is not int or review["schema_version"] != 1
                or review["scope"] != EMPTY_SCOPE or not home.is_absolute() or not project.is_absolute()
                or intent["home"] != str(home) or intent["source"] != str(home / supersede.SOURCE)
                or target.parent.parent != home / supersede.ROOT or target.name != "activation"
                or supersede.GENERATION.fullmatch(target.parent.name) is None
                or intent["review_sha256"] != records._hash(records._json(review))
                or intent["manifest"] != {} or not isinstance(intent["manifest"], dict)
                or not isinstance(failure, dict) or set(failure) != {"path", "sha256"}
                or not isinstance(failure["path"], str) or not Path(failure["path"]).is_absolute()
                or Path(failure["path"]).is_relative_to(home / supersede.SOURCE)
                or Path(failure["path"]).is_relative_to(home / supersede.ROOT)
                or not _valid_snapshot({"sha256": failure["sha256"], "identity": review["directory_identity"]})
                or not isinstance(review["source_sha256"], dict) or set(review["source_sha256"]) != SOURCE_FILES
                or any(not isinstance(v, str) or records.HEX64.fullmatch(v) is None
                       for v in review["source_sha256"].values())
                or not _valid_snapshot(review["config"]) or not _valid_snapshot(review["marker"])
                or review["marker"]["sha256"] != records._hash(supersede.MARKER)
                or not _valid_snapshot(review["cache"], optional=True)
                or not isinstance(review["entry"], dict) or set(review["entry"]) != ENTRY_REQUIRED | ENTRY_OPTIONAL
                or any(not _valid_snapshot(review["entry"][name], optional=name in ENTRY_OPTIONAL)
                       for name in review["entry"])):
            raise ValueError("archive shape")
    except Exception as exc:
        raise WithdrawError("unified_withdraw_empty_archive_invalid") from exc


def validate_empty_allocation_archive(intent: dict, receipt: dict, intent_raw: bytes) -> None:
    validate_empty_allocation_intent(intent)
    if (not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int
            or receipt != {"schema_version": 3, "phase": "empty_allocation_withdrawn_witnessed",
                           "intent_sha256": records._hash(intent_raw)}):
        raise WithdrawError("unified_withdraw_empty_archive_invalid")


def withdraw_empty_allocation(project: Path, home: Path, failure_evidence: Path,
                              expected_failure_sha256: str, expected_review_sha256: str) -> dict:
    if not isinstance(expected_review_sha256, str) or records.HEX64.fullmatch(expected_review_sha256) is None:
        raise WithdrawError("unified_withdraw_review_required")
    review = _inspect_empty(project, home, failure_evidence, expected_failure_sha256)
    if records._hash(records._json(review)) != expected_review_sha256:
        raise WithdrawError("unified_withdraw_review_changed")
    home, project = Path(review["home"]), Path(review["project"])
    failure_evidence = Path(review["failure_evidence"]["path"])
    source = home / supersede.SOURCE
    with ExitStack() as stack:
        stack.enter_context(_entry_mutex(project))
        stack.enter_context(transaction._open(home, directory=True))
        _freeze_current(review, stack)
        failure = transaction._snapshot_while_frozen(failure_evidence, stack)
        if records._hash(failure.data) != expected_failure_sha256:
            raise WithdrawError("unified_withdraw_failure_evidence_changed")
        source_handle = stack.enter_context(_allocation_directory_handle(source, moving=True))
        if (_empty_handle_identity(source_handle) != review["directory_identity"]
                or _inspect_empty(project, home, failure_evidence, expected_failure_sha256) != review):
            raise WithdrawError("unified_withdraw_review_changed")
        root = supersede._archive_root(home)
        if not records._present(root):
            private_directory(root)
        stack.enter_context(transaction._open(root, directory=True))
        generation = root / ("generation-" + secrets.token_hex(16))
        if records._present(generation):
            raise WithdrawError("unified_withdraw_generation_exists")
        private_directory(generation)
        target_handle = stack.enter_context(_allocation_directory_handle(generation, parent=True))
        intent = {"schema_version": 3, "phase": "may_have_withdrawn_empty_allocation", "home": str(home),
                  "source": str(source), "target": str(generation / "activation"), "review": review,
                  "review_sha256": expected_review_sha256, "manifest": {}}
        records._record(generation / "intent.json", intent)
        intent_snapshot = transaction._snapshot_while_frozen(generation / "intent.json", stack)
        if intent_snapshot.data != records._json(intent):
            raise WithdrawError("unified_withdraw_intent_changed")
        preparation._write_new(generation / "failure-evidence.json", failure.data)
        retained = transaction._snapshot_while_frozen(generation / "failure-evidence.json", stack)
        if retained.data != failure.data:
            raise WithdrawError("unified_withdraw_failure_evidence_changed")
        if _inspect_empty(project, home, failure_evidence, expected_failure_sha256, pending=generation) != review:
            raise WithdrawError("unified_withdraw_changed_after_intent")
        _rename_empty_allocation_handle(source_handle, target_handle, generation / "activation",
                                        review["directory_identity"])
        if (_empty_handle_identity(source_handle) != review["directory_identity"]
                or empty_allocation_directory_identity(generation / "activation") != review["directory_identity"]
                or records._present(source)):
            raise WithdrawError("unified_withdraw_move_uncertain")
        if (_source_sha256() != review["source_sha256"]
                or _current(review) != {key: review[key] for key in ("config", "marker", "cache", "entry")}
                or records._present(source)):
            raise WithdrawError("unified_withdraw_current_state_changed")
        # Sharing prevents path replacement, not child creation. Repeat the
        # enumeration at the final boundary and leave any new child intact.
        if (_empty_handle_identity(source_handle) != review["directory_identity"]
                or records._present(source)):
            raise WithdrawError("unified_withdraw_move_uncertain")
        receipt = {"schema_version": 3, "phase": "empty_allocation_withdrawn_witnessed",
                   "intent_sha256": records._hash(intent_snapshot.data)}
        validate_empty_allocation_archive(intent, receipt, intent_snapshot.data)
        # Four entities become a completed archive only after the post-receipt
        # witness. Any failed write, new optional file, child or source path
        # leaves this fifth entity intact, so a saved receipt cannot mask failure.
        fence = generation / "completion-pending.json"
        fence_value = {"schema_version": 3, "intent_sha256": records._hash(intent_snapshot.data)}
        records._record(fence, fence_value)
        with _completion_fence_handle(fence, records._json(fence_value)) as fence_handle:
            records._record(generation / "receipt.json", receipt)
            receipt_snapshot = transaction._snapshot_while_frozen(generation / "receipt.json", stack)
            if (receipt_snapshot.data != records._json(receipt)
                    or _source_sha256() != review["source_sha256"]
                    or _current(review) != {key: review[key] for key in ("config", "marker", "cache", "entry")}
                    or _empty_handle_identity(source_handle) != review["directory_identity"]
                    or records._present(source)):
                raise WithdrawError("unified_withdraw_final_witness_changed")
            _commit_completion_fence(fence_handle)
        if supersede.archive_status(home)["status"] != "superseded_witnessed":
            raise WithdrawError("unified_withdraw_receipt_uncertain")
    return {"status": "empty_allocation_withdrawn_witnessed", "scope": EMPTY_SCOPE,
            "configuration_changed": False, "cache_changed": False, "entry_changed": False, "model_requests": 0}


def withdraw(plan_path: Path, expected_review_sha256: str) -> dict:
    if not isinstance(expected_review_sha256, str) or records.HEX64.fullmatch(expected_review_sha256) is None:
        raise WithdrawError("unified_withdraw_review_required")
    review = _inspect(plan_path)
    if records._hash(records._json(review)) != expected_review_sha256:
        raise WithdrawError("unified_withdraw_review_changed")
    home, project = Path(review["home"]), Path(review["project"])
    with ExitStack() as stack:
        stack.enter_context(_entry_mutex(project))
        # Short read handles deny writes and replacement through the final
        # witness. The marker also prevents concurrent marker-release/arming.
        _freeze_current(review, stack)
        if _inspect(plan_path) != review:
            raise WithdrawError("unified_withdraw_review_changed")
        root = supersede._archive_root(home)
        if not records._present(root):
            private_directory(root)
        generation = root / ("generation-" + secrets.token_hex(16))
        private_directory(generation)
        target_handle = stack.enter_context(transaction._open(generation, directory=True))
        with transaction._open(plan_path.parent, directory=True) as source_handle:
            if transaction._identity(source_handle)[0].volume != transaction._identity(target_handle)[0].volume:
                raise WithdrawError("unified_withdraw_volume_changed")
        manifest = supersede._manifest(plan_path.parent)
        if records._hash(records._json(manifest)) != review["manifest_sha256"]:
            raise WithdrawError("unified_withdraw_review_changed")
        intent = {"schema_version": 2, "phase": "may_have_withdrawn", "home": str(home),
                  "source": str(plan_path.parent), "target": str(generation / "activation"),
                  "plan_sha256": review["plan_sha256"], "review": review,
                  "review_sha256": expected_review_sha256, "manifest": manifest}
        records._record(generation / "intent.json", intent)
        intent_snapshot = transaction._snapshot_while_frozen(generation / "intent.json", stack)
        if intent_snapshot.data != records._json(intent):
            raise WithdrawError("unified_withdraw_intent_changed")
        if _inspect(plan_path, pending=generation) != review or supersede._manifest(plan_path.parent) != manifest:
            raise WithdrawError("unified_withdraw_changed_after_intent")
        os.rename(plan_path.parent, generation / "activation")
        if (supersede._manifest(generation / "activation") != manifest or records._present(plan_path.parent)
                or _directory_identity(generation / "activation") != review["directory_identity"]):
            raise WithdrawError("unified_withdraw_move_uncertain")
        # The original plan's digest and every file ID survive the rename. New
        # arm/attempt artifacts or a concurrent live setting change remain a
        # retained incomplete archive, never an automatically retried action.
        plan = json.loads(records._read(generation / "activation/plan.json", 16384))
        if (_source_sha256() != review["source_sha256"]
                or _current(plan) != {key: review[key] for key in ("config", "marker", "cache", "entry")}
                or records._present(plan_path.parent)):
            raise WithdrawError("unified_withdraw_current_state_changed")
        receipt = {"schema_version": 2, "phase": "withdrawn_witnessed",
                   "intent_sha256": records._hash(records._json(intent)), "plan_sha256": review["plan_sha256"]}
        validate_archive_intent(intent, receipt, records._json(intent))
        records._record(generation / "receipt.json", receipt)
        if supersede.archive_status(home)["status"] != "superseded_witnessed":
            raise WithdrawError("unified_withdraw_receipt_uncertain")
    return {"status": "withdrawn_witnessed", "configuration_changed": False, "cache_changed": False,
            "entry_changed": False, "model_requests": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "withdraw", "status", "preview-empty", "withdraw-empty"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--failure-evidence", type=Path)
    parser.add_argument("--expected-failure-sha256")
    parser.add_argument("--expected-review-sha256")
    args = parser.parse_args()
    try:
        if args.action not in {"withdraw", "withdraw-empty"} and args.expected_review_sha256:
            parser.error("only withdrawal accepts the review digest")
        empty = (args.project_root, args.codex_home, args.failure_evidence, args.expected_failure_sha256)
        if args.action in {"preview-empty", "withdraw-empty"}:
            if args.plan or not all(empty):
                parser.error("empty allocation requires project, home and exact failure evidence; no plan")
            result = (preview_empty_allocation(*empty) if args.action == "preview-empty" else
                      withdraw_empty_allocation(*empty, args.expected_review_sha256))
        else:
            if not args.plan or any(empty):
                parser.error("prepared-plan actions require only --plan")
            result = (preview(args.plan) if args.action == "preview" else
                      withdraw(args.plan, args.expected_review_sha256) if args.action == "withdraw" else
                      supersede.archive_status(args.plan.parent.parent))
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] != "uncertain" else 1
    except Exception as exc:
        code = str(exc) if isinstance(exc, WithdrawError) else "unified_withdraw_unavailable"
        print(json.dumps({"status": "unavailable", "reason": code, "configuration_changed": False,
                          "cache_changed": False, "entry_changed": False, "model_requests": 0}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
