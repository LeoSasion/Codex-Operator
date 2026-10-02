"""One-shot, witnessed Windows replacement of an existing config.toml.

This is an independent primitive. It does not select a model, start Desktop,
recover a transaction, or touch any configuration without an explicit call.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat


MAX_CONFIG_BYTES = 1024 * 1024
_REPARSE_POINT = 0x400
_DIRECTORY = 0x10
_GENERIC_READ = 0x80000000
_FILE_READ_ATTRIBUTES = 0x80
_SHARE_READ = 1
_SHARE_WRITE = 2
_SHARE_DELETE = 4
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_BACKUP_NAME = re.compile(r"boundary-[0-9a-f]{32}\.bak\Z")


class TransactionFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FileIdentity:
    volume: int
    file_id: str


@dataclass(frozen=True)
class ConfigSnapshot:
    path: Path
    data: bytes
    identity: FileIdentity


@dataclass(frozen=True)
class TransactionResult:
    status: str
    reason: str
    directory: Path | None


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("created", wintypes.FILETIME),
        ("accessed", wintypes.FILETIME),
        ("written", wintypes.FILETIME),
        ("volume", wintypes.DWORD),
        ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD),
        ("index_low", wintypes.DWORD),
    ]


class _FileIdInfo(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_uint64), ("file_id", ctypes.c_ubyte * 16)]


if os.name == "nt":
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    _kernel.ReadFile.restype = wintypes.BOOL
    _kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation)]
    _kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    _kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
        ctypes.c_void_p, wintypes.DWORD]
    _kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _kernel.ReplaceFileW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    _kernel.ReplaceFileW.restype = wintypes.BOOL


def _native_error(prefix: str) -> TransactionFailure:
    return TransactionFailure(f"{prefix}_{ctypes.get_last_error()}")


def _absolute(path: Path | str) -> Path:
    value = Path(path)
    if not value.is_absolute():
        raise TransactionFailure("absolute_path_required")
    return value


def _plain_existing(path: Path) -> None:
    current = path
    while True:
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
            raise TransactionFailure("reparse_path")
        if current.parent == current:
            break
        current = current.parent


@contextmanager
def _open(path: Path, *, directory: bool = False, freeze: bool = False):
    if os.name != "nt":
        raise TransactionFailure("windows_only")
    access = _FILE_READ_ATTRIBUTES if directory else _GENERIC_READ
    # A directory cannot be renamed while held; child replacement remains valid.
    # A file allows delete/rename so ReplaceFileW can operate, but denies writes.
    share = (_SHARE_READ | _SHARE_WRITE) if directory else (_SHARE_READ if freeze
        else _SHARE_READ | _SHARE_DELETE)
    flags = _FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
    handle = _kernel.CreateFileW(str(path), access, share, None, _OPEN_EXISTING, flags, None)
    if handle == _INVALID_HANDLE:
        raise _native_error("open")
    try:
        if directory:
            _, info = _identity(handle)
            if not info.attributes & _DIRECTORY or info.attributes & _REPARSE_POINT:
                raise TransactionFailure("not_plain_directory")
        yield handle
    finally:
        _kernel.CloseHandle(handle)


def _identity(handle) -> tuple[FileIdentity, _ByHandleFileInformation]:
    info = _ByHandleFileInformation()
    if not _kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise _native_error("file_info")
    file_id = _FileIdInfo()
    # FileIdInfo (18) includes the 128-bit ID required on ReFS as well as NTFS.
    if not _kernel.GetFileInformationByHandleEx(handle, 18, ctypes.byref(file_id), ctypes.sizeof(file_id)):
        raise _native_error("file_id")
    return FileIdentity(file_id.volume, bytes(file_id.file_id).hex()), info


def _read_handle(handle, *, ordinary_file: bool = True) -> tuple[bytes, FileIdentity]:
    identity, info = _identity(handle)
    if info.attributes & _REPARSE_POINT or bool(info.attributes & _DIRECTORY) == ordinary_file:
        raise TransactionFailure("not_plain_file")
    if ordinary_file and info.links != 1:
        raise TransactionFailure("linked_file")
    size = (info.size_high << 32) | info.size_low
    if size > MAX_CONFIG_BYTES:
        raise TransactionFailure("config_size_bound")
    if not ordinary_file:
        return b"", identity
    pieces = []
    total = 0
    buffer = ctypes.create_string_buffer(64 * 1024)
    while True:
        count = wintypes.DWORD()
        if not _kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None):
            raise _native_error("read")
        if count.value == 0:
            break
        total += count.value
        if total > MAX_CONFIG_BYTES:
            raise TransactionFailure("config_size_bound")
        pieces.append(buffer.raw[:count.value])
    after, after_info = _identity(handle)
    if after != identity or after_info.links != 1:
        raise TransactionFailure("file_changed_during_read")
    return b"".join(pieces), identity


def _snapshot(path: Path) -> ConfigSnapshot:
    _plain_existing(path)
    with _open(path) as handle:
        data, identity = _read_handle(handle)
    return ConfigSnapshot(path, data, identity)


def _snapshot_while_frozen(path: Path, stack: ExitStack) -> ConfigSnapshot:
    _plain_existing(path)
    handle = stack.enter_context(_open(path, freeze=True))
    data, identity = _read_handle(handle)
    return ConfigSnapshot(path, data, identity)


def observe_config(path: Path | str) -> ConfigSnapshot:
    """Capture exact bytes and file identity under a no-writer Windows handle."""
    target = _absolute(path)
    if target.name != "config.toml":
        raise TransactionFailure("config_name_required")
    return _snapshot(target)


def _write_new(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _replace_file(target: Path, stage: Path, backup: Path) -> None:
    # REPLACEFILE_WRITE_THROUGH is unsupported. No retry follows any error.
    if not _kernel.ReplaceFileW(str(target), str(stage), str(backup), 0, None, None):
        raise _native_error("replacefile")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _failure(exc: Exception) -> str:
    if isinstance(exc, TransactionFailure):
        return exc.code
    if isinstance(exc, OSError):
        return f"os_error_{exc.winerror or exc.errno or 0}"
    return "unexpected_error"


def _new_private_directory(parent: Path) -> Path:
    for _ in range(3):
        directory = parent / (".operator-config-transaction-" + secrets.token_hex(16))
        try:
            # Python 3.13+ applies the owner-only mode to Windows directory ACLs.
            os.mkdir(directory, 0o700)
            return directory
        except FileExistsError:
            continue
    raise TransactionFailure("transaction_name_collision")


def _same_volume(target_handle, state_parent_handle) -> None:
    target_id, _ = _identity(target_handle)
    state_id, _ = _identity(state_parent_handle)
    if target_id.volume != state_id.volume:
        raise TransactionFailure("different_volume")


def replace_config_once(target: Path | str, expected: ConfigSnapshot,
                        candidate: bytes, state_parent: Path | str) -> TransactionResult:
    """Replace once. Leave all transaction evidence on every outcome.

    `state_parent` must be a controlled directory on the target's volume.
    A successful return proves the backup at the replace boundary and current
    target matched the reviewed files; later edits require a fresh inspection.
    """
    directory = None
    try:
        target = _absolute(target)
        state_parent = _absolute(state_parent)
        if target.name != "config.toml" or expected.path != target:
            raise TransactionFailure("snapshot_target_mismatch")
        if not isinstance(candidate, bytes) or len(candidate) > MAX_CONFIG_BYTES:
            raise TransactionFailure("candidate_size_or_type")
        if candidate == expected.data:
            raise TransactionFailure("candidate_unchanged")
        _plain_existing(target)
        _plain_existing(state_parent)
        if not state_parent.is_dir():
            raise TransactionFailure("state_parent_not_directory")
        with ExitStack() as stack:
            parent_handle = stack.enter_context(_open(target.parent, directory=True))
            state_handle = stack.enter_context(_open(state_parent, directory=True))
            target_handle = stack.enter_context(_open(target))
            _same_volume(target_handle, state_handle)
            _same_volume(target_handle, parent_handle)
            current, current_id = _read_handle(target_handle)
            if current != expected.data or current_id != expected.identity:
                raise TransactionFailure("expected_file_changed")
            directory = _new_private_directory(state_parent)
            stack.enter_context(_open(directory, directory=True))
            before = directory / "before.bin"
            candidate_copy = directory / "candidate.bin"
            stage = directory / "pending.toml"
            backup_name = "boundary-" + secrets.token_hex(16) + ".bak"
            backup = directory / backup_name
            _write_new(before, current)
            _write_new(candidate_copy, candidate)
            _write_new(stage, candidate)
            # ReplaceFileW refuses even a fully shared open source handle on
            # current Windows. The private stage is closed before the call;
            # its identity and bytes are witnessed at the new target afterward.
            staged_snapshot = _snapshot(stage)
            staged, staged_id = staged_snapshot.data, staged_snapshot.identity
            if staged != candidate or staged_id.volume != current_id.volume:
                raise TransactionFailure("stage_changed_or_moved")
            intent = {
                "schema_version": 1,
                "target": str(target),
                "backup": backup_name,
                "expected_sha256": _hash(current),
                "candidate_sha256": _hash(candidate),
                "expected_identity": current_id.__dict__,
                "candidate_identity": staged_id.__dict__,
            }
            _write_new(directory / "intent.json", (json.dumps(intent, sort_keys=True) + "\n").encode())
            # This check narrows the race. The backup identity check below closes
            # the remaining rename/swap gap without claiming atomic CAS.
            if (_snapshot(target) != expected or _snapshot(stage) != staged_snapshot
                    or backup.exists()):
                raise TransactionFailure("target_or_backup_changed")
            _replace_file(target, stage, backup)
            with ExitStack() as final_stack:
                final_target = _snapshot_while_frozen(target, final_stack)
                final_backup = _snapshot_while_frozen(backup, final_stack)
                if final_target != ConfigSnapshot(target, candidate, staged_id):
                    raise TransactionFailure("replacement_target_changed")
                if final_backup != ConfigSnapshot(backup, current, current_id):
                    raise TransactionFailure("replacement_backup_mismatch")
                if stage.exists():
                    raise TransactionFailure("stage_still_present")
                _write_new(directory / "verified.json", b'{"status":"applied_witnessed"}\n')
            return TransactionResult("applied", "applied_witnessed", directory)
    except Exception as exc:
        return TransactionResult("uncertain", _failure(exc), directory)


def inspect_transaction(directory: Path | str) -> TransactionResult:
    """Read only: classify an interrupted attempt from its retained evidence."""
    directory = None if directory is None else Path(directory)
    try:
        if directory is None:
            raise TransactionFailure("transaction_directory_missing")
        directory = _absolute(directory)
        _plain_existing(directory)
        intent = json.loads((directory / "intent.json").read_bytes())
        if intent.get("schema_version") != 1 or not isinstance(intent.get("target"), str):
            raise TransactionFailure("intent_invalid")
        backup_name = intent.get("backup")
        if not isinstance(backup_name, str) or not _BACKUP_NAME.fullmatch(backup_name):
            raise TransactionFailure("intent_backup_invalid")
        target = _absolute(intent["target"])
        if target.name != "config.toml":
            raise TransactionFailure("intent_target_invalid")
        before = (directory / "before.bin").read_bytes()
        candidate = (directory / "candidate.bin").read_bytes()
        if len(before) > MAX_CONFIG_BYTES or len(candidate) > MAX_CONFIG_BYTES:
            raise TransactionFailure("stored_size_bound")
        if _hash(before) != intent.get("expected_sha256") or _hash(candidate) != intent.get("candidate_sha256"):
            raise TransactionFailure("stored_bytes_changed")
        expected_id = FileIdentity(**intent["expected_identity"])
        candidate_id = FileIdentity(**intent["candidate_identity"])
        backup = directory / backup_name
        with ExitStack() as stack:
            stack.enter_context(_open(target.parent, directory=True))
            stack.enter_context(_open(directory, directory=True))
            if _snapshot_while_frozen(target, stack) != ConfigSnapshot(target, candidate, candidate_id):
                raise TransactionFailure("target_not_candidate")
            if _snapshot_while_frozen(backup, stack) != ConfigSnapshot(backup, before, expected_id):
                raise TransactionFailure("backup_not_expected")
            if (directory / "pending.toml").exists():
                raise TransactionFailure("stage_still_present")
        return TransactionResult("applied_witnessed", "exact_current_artifacts", directory)
    except Exception as exc:
        return TransactionResult("uncertain", _failure(exc), directory)
