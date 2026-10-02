"""Explicit, one-shot retirement of a recovered unified cold-launch plan.

The activation directory remains as private evidence. Retirement never repairs
an uncertain launch, restores a cache, starts a service, or sends a model turn.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import secrets
import tomllib
from copy import deepcopy


HEX64 = re.compile(r"[a-f0-9]{64}\Z")
TRANSACTION = re.compile(r"\.operator-config-transaction-[a-f0-9]{32}\Z")
RETIRED_CACHE = re.compile(r"cache-retired-[a-f0-9]{32}\.bin\Z")
RETIRED_MARKER = re.compile(r"retired-marker-[a-f0-9]{32}\.bin\Z")
MARKER = b"operator-native-route-only-v1\n"
ARCHIVE = "operator-unified-retired-archive"


def _tree(directory: Path) -> dict:
    """Bounded file/identity manifest; preserve all evidence without following links."""
    from operator_core import windows_config_transaction as transaction
    result, pending, entries = {}, [directory], 0
    while pending:
        current = pending.pop()
        _plain(current)
        for path in sorted(current.iterdir()):
            entries += 1
            if entries > 128:
                raise RetireError("unified_retired_archive_too_large")
            _plain(path)
            relative = path.relative_to(directory).as_posix()
            if path.is_dir():
                result[relative] = {"directory": True}
                pending.append(path)
            else:
                snapshot = transaction._snapshot(path)
                result[relative] = {"sha256": _hash(snapshot.data), "identity": _identity(snapshot)}
    return result


def archive_status(home: Path) -> dict:
    """Read-only integrity gate, including interrupted moves. Never resumes work."""
    root = home / ARCHIVE
    if not _present(root):
        return {"status": "absent"}
    try:
        _plain(root)
        rows = list(root.iterdir())
        if len(rows) > 64:
            raise RetireError("unified_retired_archive_too_large")
        for run in rows:
            _plain(run)
            if re.fullmatch(r"generation-[a-f0-9]{32}", run.name) is None:
                raise RetireError("unified_retired_archive_invalid")
            if {p.name for p in run.iterdir()} != {"intent.json", "receipt.json", "evidence"}:
                raise RetireError("unified_retired_archive_incomplete")
            intent, raw = _load(run / "intent.json", 65536)
            receipt, _ = _load(run / "receipt.json")
            if (intent.get("schema_version") != 1 or intent.get("home") != str(home)
                    or intent.get("purpose") != "archive_reviewed_retired_activation"
                    or receipt != {"schema_version": 1, "phase": "archived_witnessed",
                                   "intent_sha256": _hash(raw)}
                    or _tree(run / "evidence") != intent.get("files")):
                raise RetireError("unified_retired_archive_changed")
        return {"status": "retained", "generations": len(rows)}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "uncertain"}


def _archive_review(plan_path: Path) -> dict:
    from operator_unified_cold_start import _plan
    plan, _, directory = _plan(plan_path)
    home = directory.parent
    if archive_status(home)["status"] == "uncertain":
        raise RetireError("unified_retired_archive_requires_review")
    verify_retired(plan_path)
    _stopped(plan, require_desktop_closed=True)
    receipt, _ = _load(directory / "retirement/intent.json", 65536)
    review = {"schema_version": 1, "purpose": "archive_reviewed_retired_activation",
            "home": str(home), "files": _tree(directory),
            "retirement_review": receipt["review"]}
    if len(_json(review)) > 65536:
        raise RetireError("unified_retired_archive_too_large")
    return review


def archive_preview(plan_path: Path) -> dict:
    review = _archive_review(plan_path)
    return {"status": "reviewed_archive_preview", "review_sha256": _hash(_json(review)),
            "configuration_changed": False, "model_requests": 0}


def archive_retired(plan_path: Path, expected_review_sha256: str) -> dict:
    from operator_unified_cold_start import _plan
    from operator_core import windows_config_transaction as transaction
    review = _archive_review(plan_path)
    if expected_review_sha256 != _hash(_json(review)):
        raise RetireError("unified_retired_archive_review_changed")
    plan, _, source = _plan(plan_path)
    home = source.parent
    root = home / ARCHIVE
    if not _present(root):
        os.mkdir(root, 0o700)
    _plain(root)
    run = root / ("generation-" + secrets.token_hex(16))
    os.mkdir(run, 0o700)
    # From here an interrupted operation is terminal. No caller may repeat it.
    _record(run / "intent.json", review)
    verify_retired(plan_path)
    _stopped(plan, require_desktop_closed=True)
    if _tree(source) != review["files"]:
        raise RetireError("unified_retired_archive_changed")
    destination = run / "evidence"
    if source != home / "operator-unified-activation" or destination.parent.parent != root:
        raise RetireError("unified_retired_archive_scope")
    os.rename(source, destination)
    if _present(source) or _tree(destination) != review["files"]:
        raise RetireError("unified_retired_archive_changed")
    state = review["retirement_review"]
    current = transaction.observe_config(home / "config.toml")
    marker = transaction._snapshot(home / "operator-native-route-only")
    if (_hash(current.data) != state["config_sha256"] or _identity(current) != state["config_identity"]
            or marker.data != MARKER or _identity(marker) != state["marker_identity"]):
        raise RetireError("unified_retired_archive_native_state_changed")
    _stopped(plan, require_desktop_closed=True)
    _record(run / "receipt.json", {"schema_version": 1, "phase": "archived_witnessed",
                                   "intent_sha256": _hash(_json(review))})
    if archive_status(home)["status"] != "retained":
        raise RetireError("unified_retired_archive_changed")
    return {"status": "archived_witnessed", "configuration_changed": False, "model_requests": 0}


class RetireError(ValueError):
    """Fixed public failure code without local paths or configuration text."""


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _plain(path: Path) -> None:
    cursor = path
    while True:
        info = os.lstat(cursor)
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise RetireError("unified_retire_linked_path")
        if cursor.parent == cursor:
            return
        cursor = cursor.parent


def _read(path: Path, limit: int = 1024 * 1024) -> bytes:
    _plain(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
        raise RetireError("unified_retire_file_unavailable")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise RetireError("unified_retire_file_unavailable")
    return raw


def _present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _record(path: Path, value: dict) -> None:
    from operator_unified_prepare import _write_new
    _write_new(path, _json(value))


def _load(path: Path, limit: int = 16384) -> tuple[dict, bytes]:
    raw = _read(path, limit)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RetireError("unified_retire_record_invalid")
    return value, raw


def _identity(snapshot) -> dict:
    return {"volume": snapshot.identity.volume, "file_id": snapshot.identity.file_id}


def _config_delta(saved: bytes, current: bytes) -> str:
    # This is explicit, digest-reviewed retirement after native recovery, not
    # permission to reuse or relax an old cold-launch activation witness.
    if saved == current:
        return "unchanged"
    paths = {"model": ("model",), "conversationDetailMode": ("desktop", "conversationDetailMode"),
             "SKY_CUA_NATIVE_PIPE_DIRECTORY": ("mcp_servers", "node_repl", "env", "SKY_CUA_NATIVE_PIPE_DIRECTORY")}
    pattern = re.compile(rb'''(?P<key>model|conversationDetailMode|SKY_CUA_NATIVE_PIPE_DIRECTORY) = (?P<quote>["'])(?P<value>[^\r\n]{1,4096})(?P=quote)(?P<ending>\r?\n?)\Z''')
    try:
        old_lines, new_lines = saved.splitlines(keepends=True), current.splitlines(keepends=True)
        if len(old_lines) != len(new_lines):
            raise ValueError()
        changed = set()
        for old, new in zip(old_lines, new_lines):
            if old == new:
                continue
            a, b = pattern.fullmatch(old), pattern.fullmatch(new)
            if (a is None or b is None or a['key'] != b['key'] or a['quote'] != b['quote']
                    or a['ending'] != b['ending'] or a['key'] in changed):
                raise ValueError()
            changed.add(a['key'])
        before, after = tomllib.loads(saved.decode()), tomllib.loads(current.decode())
        expected = deepcopy(before)
        for key in changed:
            path = paths[key.decode()]
            left, right = expected, after
            for name in path[:-1]:
                left, right = left[name], right[name]
            if not isinstance(left[path[-1]], str) or not isinstance(right[path[-1]], str):
                raise ValueError()
            left[path[-1]] = right[path[-1]]
        if expected != after:
            raise ValueError()
        return "cua_pipe_only" if changed == {b"SKY_CUA_NATIVE_PIPE_DIRECTORY"} else "desktop_preferences_only"
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise RetireError("unified_retire_config_changed") from exc


def _stopped(plan: dict, *, require_desktop_closed: bool) -> None:
    from operator_web_service import process_identity
    if require_desktop_closed:
        from operator_web_startup import assert_desktop_closed
        from operator_core.responses_capabilities import RouterError
        try:
            assert_desktop_closed()
        except RouterError as exc:
            if str(exc) == "web_startup_close_desktop_before_activation":
                raise RetireError("unified_retire_desktop_not_closed") from exc
            raise
    binding = plan["router"]
    if process_identity(binding["process"]["pid"]) is not None:
        raise RetireError("unified_retire_router_not_stopped")
    with socket.socket() as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", binding["port"]))


def _historical_release(plan: dict, directory: Path, plan_sha: str,
                        arm: dict | None) -> tuple[str | None, dict | None]:
    from operator_core import windows_config_transaction as transaction
    release = directory / "marker-release"
    exists = _present(release)
    required = "unified_native_route_lock_active" in plan["future_arm_blockers"]
    if not exists:
        if required and arm is not None:
            raise RetireError("unified_retire_marker_evidence_missing")
        return None, None
    _plain(release)
    intent, intent_raw = _load(release / "intent.json")
    receipt, receipt_raw = _load(release / "receipt.json")
    backup_name = intent.get("backup")
    if (not required or not isinstance(backup_name, str)
            or RETIRED_MARKER.fullmatch(backup_name) is None
            or set(intent) != {"schema_version", "phase", "plan_sha256", "review_sha256",
                               "marker_sha256", "marker_identity", "backup", "entry",
                               "release_source_sha256"}
            or set(receipt) != {"schema_version", "phase", "plan_sha256",
                                "intent_sha256", "backup_sha256", "backup_identity"}
            or intent["schema_version"] != 1 or intent["phase"] != "may_have_released"
            or receipt["schema_version"] != 1 or receipt["phase"] != "released_witnessed"
            or intent["plan_sha256"] != plan_sha or receipt["plan_sha256"] != plan_sha
            or receipt["intent_sha256"] != _hash(intent_raw)
            or intent["marker_sha256"] != _hash(MARKER)
            or receipt["backup_sha256"] != _hash(MARKER)
            or intent["marker_identity"] != receipt["backup_identity"]
            or (arm is not None and arm.get("entry") != intent["entry"])):
        raise RetireError("unified_retire_marker_evidence_invalid")
    original = _read(release / "before.bin", 4096)
    retired = transaction._snapshot(release / backup_name)
    if original != MARKER or retired.data != MARKER or _identity(retired) != intent["marker_identity"]:
        raise RetireError("unified_retire_marker_evidence_invalid")
    return _hash(receipt_raw), intent["entry"]


def _recovery(plan: dict, directory: Path, receipt_path: Path, active: bool,
              released: bool, *, current_config: bytes | None = None) -> dict:
    home = Path(plan["home"])
    project = Path(plan["project"])
    if (not receipt_path.is_absolute() or receipt_path.name != "intent.json"
            or receipt_path.parent.parent != home / "operator-route-recovery"):
        raise RetireError("unified_retire_recovery_scope")
    intent, intent_raw = _load(receipt_path, 65536)
    completed, completed_raw = _load(receipt_path.parent / "completed.json", 65536)
    rows = intent.get("files")
    if (intent.get("schema_version") != 1
            or intent.get("purpose") != "operator_official_route_recovery"
            or not isinstance(rows, list) or not isinstance(completed.get("completed"), list)
            or completed.get("schema_version") != 1 or completed.get("warnings") != []):
        raise RetireError("unified_retire_recovery_invalid")
    files = {}
    allowed = {"config.toml", "desktop-entry.json", "operator-native-route-only"}
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"name", "target", "before_sha256", "after_sha256"}
                or row["name"] not in allowed or row["name"] in files):
            raise RetireError("unified_retire_recovery_invalid")
        files[row["name"]] = row
    if set(completed["completed"]) != set(files) or len(completed["completed"]) != len(files):
        raise RetireError("unified_retire_recovery_invalid")
    entry_path = project / ".codex/operator-desktop-entry/desktop-entry.json"
    entry_row = files.get("desktop-entry.json")
    if entry_row is None or Path(entry_row["target"]) != entry_path:
        raise RetireError("unified_retire_entry_not_recovered")
    entry_before = _read(receipt_path.parent / "desktop-entry.json.before", 16384)
    entry_after = _read(entry_path, 16384)
    old_entry = json.loads(entry_before)
    expected_entry = dict(old_entry)
    expected_entry["mode"] = "native"
    if (old_entry.get("mode") != "reviewed_startup"
            or old_entry.get("startup_bundle") != ".codex/operator-unified-startup"
            or _hash(entry_before) != entry_row["before_sha256"]
            or not HEX64.fullmatch(entry_row["after_sha256"])
            or _hash(entry_after) != entry_row["after_sha256"]
            or json.loads(entry_after) != expected_entry):
        raise RetireError("unified_retire_entry_not_recovered")
    config_row = files.get("config.toml")
    post_recovery = {}
    if active:
        recovery_before = _read(receipt_path.parent / "config.toml.before")
        original = _read(directory / "before.toml")
        candidate = _read(directory / "candidate.toml")
        active_delta = _config_delta(candidate, recovery_before)
        # Recover the completed transaction's exact after bytes from its retained
        # before bytes and the plan-bound owned prefix/suffix. This is a read-only
        # integrity check; never replay recovery or rewrite its historical receipt.
        if not original or candidate.count(original) != 1:
            raise RetireError("unified_retire_config_recovery_invalid")
        prefix, _, suffix = candidate.partition(original)
        if (not prefix or not suffix or not recovery_before.startswith(prefix)
                or not recovery_before.endswith(suffix)):
            raise RetireError("unified_retire_config_recovery_invalid")
        recovered_config = recovery_before[len(prefix):-len(suffix)]
        native_delta = _config_delta(original, recovered_config)
        if (config_row is None or Path(config_row["target"]) != home / "config.toml"
                or native_delta != active_delta
                or config_row["before_sha256"] != _hash(recovery_before)
                or config_row["after_sha256"] != _hash(recovered_config)):
            raise RetireError("unified_retire_config_recovery_invalid")
        # Every current preference must survive recovery byte-for-byte; merely
        # accepting two independent allowed deltas would permit a rollback.
        if native_delta != "unchanged":
            def preferences(raw):
                return [line for line in raw.splitlines(keepends=True)
                        if line.startswith((b"model = ", b"conversationDetailMode = ",
                                            b"SKY_CUA_NATIVE_PIPE_DIRECTORY = "))]
            if preferences(recovered_config) != preferences(recovery_before):
                raise RetireError("unified_retire_config_recovery_invalid")
        observed = _read(home / "config.toml") if current_config is None else current_config
        if observed != recovered_config:
            # A later Desktop launch changes only this exact native CUA pipe.
            # Bind its current digest/identity in _inspect's new reviewed snapshot.
            # Other later preferences remain a conflict, including otherwise
            # admissible model/display changes. A changed preview never commits.
            if _config_delta(recovered_config, observed) != "cua_pipe_only":
                raise RetireError("unified_retire_post_recovery_config_changed")
            post_recovery = {"config_recovered_sha256": config_row["after_sha256"],
                             "post_recovery_config_delta": "cua_pipe_only"}
    elif config_row is not None:
        raise RetireError("unified_retire_unexpected_config_recovery")
    marker_row = files.get("operator-native-route-only")
    if marker_row is not None:
        if (Path(marker_row["target"]) != home / "operator-native-route-only"
                or marker_row["before_sha256"] != "absent"
                or marker_row["after_sha256"] != _hash(MARKER)):
            raise RetireError("unified_retire_recovery_invalid")
    elif released or "unified_native_route_lock_active" not in plan["future_arm_blockers"]:
        raise RetireError("unified_retire_marker_recovery_missing")
    return {"intent_sha256": _hash(intent_raw), "completed_sha256": _hash(completed_raw),
            "entry_before_sha256": _hash(entry_before),
            "entry_recovered_sha256": entry_row["after_sha256"], **post_recovery}


def _active(plan: dict, directory: Path, plan_sha: str) -> tuple[str, str | None]:
    from operator_core import windows_config_transaction as transaction
    attempt, _ = _load(directory / "attempt.json")
    completion, completion_raw = _load(directory / "completion.json")
    backup_name = attempt.get("cache_backup")
    tx_path = Path(completion.get("transaction", ""))
    if (not isinstance(backup_name, str) or RETIRED_CACHE.fullmatch(backup_name) is None
            or attempt != {"schema_version": 1, "phase": "may_have_activated",
                           "plan_sha256": plan_sha, "cache_backup": backup_name}
            or set(completion) != {"schema_version", "phase", "plan_sha256", "cache_backup",
                                   "transaction", "candidate_sha256"}
            or completion["schema_version"] != 1 or completion["phase"] != "config_switch_witnessed"
            or completion["plan_sha256"] != plan_sha or completion["cache_backup"] != backup_name
            or completion["candidate_sha256"] != plan["candidate_sha256"]
            or tx_path.parent != directory or TRANSACTION.fullmatch(tx_path.name) is None):
        raise RetireError("unified_retire_attempt_unwitnessed")
    transactions = list(directory.glob(".operator-config-transaction-*"))
    if transactions != [tx_path]:
        raise RetireError("unified_retire_transaction_ambiguous")
    tx, _ = _load(tx_path / "intent.json")
    before = _read(tx_path / "before.bin")
    candidate = _read(tx_path / "candidate.bin")
    backup_name_tx = tx.get("backup")
    if (tx.get("schema_version") != 1 or tx.get("target") != str(Path(plan["home"]) / "config.toml")
            or not isinstance(backup_name_tx, str)
            or re.fullmatch(r"boundary-[a-f0-9]{32}\.bak", backup_name_tx) is None
            or tx.get("expected_sha256") != plan["config_sha256"]
            or tx.get("candidate_sha256") != plan["candidate_sha256"]
            or tx.get("expected_identity") != plan["config_identity"]
            or before != _read(directory / "before.toml")
            or candidate != _read(directory / "candidate.toml")
            or _read(tx_path / "verified.json", 4096) != b'{"status":"applied_witnessed"}\n'
            or _present(tx_path / "pending.toml")):
        raise RetireError("unified_retire_transaction_invalid")
    backup = transaction._snapshot(tx_path / backup_name_tx)
    if backup.data != before or _identity(backup) != plan["config_identity"]:
        raise RetireError("unified_retire_transaction_invalid")
    if plan["cache"]["existed"]:
        retired = transaction._snapshot(directory / backup_name)
        if (retired.data != _read(directory / "cache-before.bin")
                or _hash(retired.data) != plan["cache"]["sha256"]
                or _identity(retired) != plan["cache"]["identity"]):
            raise RetireError("unified_retire_cache_backup_changed")
        cache_hash = _hash(retired.data)
    else:
        if _present(directory / backup_name):
            raise RetireError("unified_retire_cache_backup_changed")
        cache_hash = None
    return _hash(completion_raw), cache_hash


def _inspect(plan_path: Path, recovery_path: Path, *, allow_retirement: bool,
             require_desktop_closed: bool = True) -> dict:
    import operator_unified_cold_start as cold
    from operator_core import windows_config_transaction as transaction
    plan, plan_raw, directory = cold._plan(plan_path)
    plan_sha = _hash(plan_raw)
    journal, _ = _load(directory / "journal.json")
    if journal != {"schema_version": 1, "phase": "prepared_not_armed", "plan_sha256": plan_sha}:
        raise RetireError("unified_retire_plan_invalid")
    retirement = directory / "retirement"
    if not allow_retirement and _present(retirement):
        raise RetireError("unified_retire_already_recorded")
    config = transaction.observe_config(Path(plan["home"]) / "config.toml")
    config_delta = _config_delta(_read(directory / "before.toml"), config.data)
    marker = transaction._snapshot(Path(plan["home"]) / "operator-native-route-only")
    if (_hash(_read(directory / "before.toml")) != plan["config_sha256"] or marker.data != MARKER
            or _hash(_read(directory / "candidate.toml")) != plan["candidate_sha256"]):
        raise RetireError("unified_retire_native_route_unverified")
    if plan["cache"]["existed"]:
        if _hash(_read(directory / "cache-before.bin")) != plan["cache"]["sha256"]:
            raise RetireError("unified_retire_cache_copy_changed")
    elif _present(directory / "cache-before.bin"):
        raise RetireError("unified_retire_cache_copy_changed")
    arm_path = directory / "arm.json"
    attempt_path = directory / "attempt.json"
    completion_path = directory / "completion.json"
    arm = _load(arm_path)[0] if _present(arm_path) else None
    if arm is not None and (set(arm) != {"schema_version", "phase", "plan_sha256",
                                "consumer_sha256", "python_sha256", "entry", "launcher",
                                "marker_release_sha256"}
                            or arm.get("phase") != "armed" or arm.get("schema_version") != 1
                            or arm.get("plan_sha256") != plan_sha
                            or not isinstance(arm.get("entry"), dict)
                            or not isinstance(arm.get("launcher"), dict)
                            or not isinstance(arm.get("consumer_sha256"), str)
                            or HEX64.fullmatch(arm["consumer_sha256"]) is None
                            or not isinstance(arm.get("python_sha256"), str)
                            or HEX64.fullmatch(arm["python_sha256"]) is None):
        raise RetireError("unified_retire_arm_invalid")
    if _present(attempt_path) or _present(completion_path):
        if arm is None or not _present(attempt_path) or not _present(completion_path):
            raise RetireError("unified_retire_attempt_unwitnessed")
        completion_sha, cache_backup_sha = _active(plan, directory, plan_sha)
        phase = "active_witnessed_recovered"
    else:
        if list(directory.glob(".operator-config-transaction-*")) or list(directory.glob("cache-retired-*")):
            raise RetireError("unified_retire_unexpected_attempt_artifact")
        completion_sha, cache_backup_sha = None, None
        phase = "armed_recovered" if arm is not None else "prepared_recovered"
    release_sha, release_entry = _historical_release(plan, directory, plan_sha, arm)
    if arm is not None and arm["marker_release_sha256"] != release_sha:
        raise RetireError("unified_retire_arm_invalid")
    recovery = _recovery(plan, directory, recovery_path, completion_sha is not None,
                         release_sha is not None, current_config=config.data)
    if (arm is not None and arm["entry"].get("configuration_sha256")
            != recovery["entry_before_sha256"]):
        raise RetireError("unified_retire_arm_invalid")
    if (release_entry is not None and release_entry.get("configuration_sha256")
            != recovery["entry_before_sha256"]):
        raise RetireError("unified_retire_marker_evidence_invalid")
    _stopped(plan, require_desktop_closed=require_desktop_closed)
    return {"schema_version": 1, "scope": "unified_activation_retirement",
            "phase": phase, "plan_sha256": plan_sha,
            **({"config_delta": config_delta} if config_delta != "unchanged" else {}),
            "recovery_path": str(recovery_path), "recovery": recovery,
            "config_sha256": _hash(config.data), "config_identity": _identity(config),
            "marker_sha256": _hash(marker.data), "marker_identity": _identity(marker),
            "marker_release_receipt_sha256": release_sha,
            "completion_sha256": completion_sha, "cache_backup_sha256": cache_backup_sha,
            "cache_original_sha256": plan["cache"]["sha256"]}


def preview(plan_path: Path, recovery_path: Path) -> dict:
    review = _inspect(plan_path, recovery_path, allow_retirement=False)
    return {"status": "reviewed_preview", "review_sha256": _hash(_json(review)),
            "phase": review["phase"], "cache_original_retained": True,
            "configuration_changed": False, "model_requests": 0}


def retire(plan_path: Path, recovery_path: Path, expected_review_sha256: str) -> dict:
    if not isinstance(expected_review_sha256, str) or HEX64.fullmatch(expected_review_sha256) is None:
        raise RetireError("unified_retire_review_required")
    review = _inspect(plan_path, recovery_path, allow_retirement=False)
    if _hash(_json(review)) != expected_review_sha256:
        raise RetireError("unified_retire_review_changed")
    directory = plan_path.parent / "retirement"
    os.mkdir(directory, 0o700)
    again = _inspect(plan_path, recovery_path, allow_retirement=True)
    if again != review or any(directory.iterdir()):
        raise RetireError("unified_retire_changed_after_intent")
    intent = {"schema_version": 1, "phase": "may_have_retired",
              "review": review, "review_sha256": expected_review_sha256}
    _record(directory / "intent.json", intent)
    if _inspect(plan_path, recovery_path, allow_retirement=True) != review:
        raise RetireError("unified_retire_changed_after_intent")
    _record(directory / "receipt.json", {"schema_version": 1,
        "phase": "retired_witnessed", "intent_sha256": _hash(_json(intent)),
        "review_sha256": expected_review_sha256})
    verify_retired(plan_path)
    return {"status": "retired_witnessed", "phase": review["phase"],
            "cache_original_retained": True, "configuration_changed": False,
            "model_requests": 0}


def verify_retired(plan_path: Path) -> dict:
    directory = plan_path.parent / "retirement"
    intent, intent_raw = _load(directory / "intent.json")
    receipt, _ = _load(directory / "receipt.json")
    review = intent.get("review")
    if (set(intent) != {"schema_version", "phase", "review", "review_sha256"}
            or intent["schema_version"] != 1 or intent["phase"] != "may_have_retired"
            or not isinstance(review, dict) or intent["review_sha256"] != _hash(_json(review))
            or receipt != {"schema_version": 1, "phase": "retired_witnessed",
                           "intent_sha256": _hash(intent_raw),
                           "review_sha256": intent["review_sha256"]}):
        raise RetireError("unified_retire_receipt_invalid")
    current = _inspect(plan_path, Path(review["recovery_path"]),
                       allow_retirement=True, require_desktop_closed=False)
    if current != review:
        raise RetireError("unified_retire_state_changed")
    return {"status": "retired_witnessed", "phase": review["phase"],
            "recovery": review["recovery"], "configuration_changed": False}


def archived_entry_status(plan_path: Path, project: Path, before_sha256: str,
                          after_sha256: str, *, historical: bool = False) -> dict:
    """Read one exact archived retirement's entry witness; never revive its plan.

    A historical lookup validates a retained build transition, not the current
    entry. The caller must separately check its current build and native route.
    """
    if (not plan_path.is_absolute() or plan_path.name != "plan.json"
            or plan_path.parent.name != "operator-unified-activation"
            or not project.is_absolute() or HEX64.fullmatch(before_sha256) is None
            or HEX64.fullmatch(after_sha256) is None):
        raise RetireError("unified_retired_entry_scope_invalid")
    home = plan_path.parent.parent
    if home != Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")):
        raise RetireError("unified_retired_entry_home_mismatch")
    _plain(home)
    _plain(project)
    if _present(plan_path.parent):
        raise RetireError("unified_retired_entry_active_plan_conflict")
    if archive_status(home)["status"] != "retained":
        raise RetireError("unified_retired_entry_archive_requires_review")
    matches = []
    for run in sorted((home / ARCHIVE).iterdir()):
        archive, archive_raw = _load(run / "intent.json", 65536)
        evidence = run / "evidence"
        intent, intent_raw = _load(evidence / "retirement/intent.json")
        receipt, _ = _load(evidence / "retirement/receipt.json")
        review = intent.get("review")
        if (set(intent) != {"schema_version", "phase", "review", "review_sha256"}
                or intent["schema_version"] != 1 or intent["phase"] != "may_have_retired"
                or not isinstance(review, dict) or intent["review_sha256"] != _hash(_json(review))
                or receipt != {"schema_version": 1, "phase": "retired_witnessed",
                               "intent_sha256": _hash(intent_raw),
                               "review_sha256": intent["review_sha256"]}
                or archive.get("retirement_review") != review
                or review.get("scope") != "unified_activation_retirement"
                or review.get("phase") not in {"prepared_recovered", "armed_recovered",
                                                "active_witnessed_recovered"}):
            raise RetireError("unified_retired_entry_receipt_invalid")
        plan, plan_raw = _load(evidence / "plan.json")
        if plan.get("project") != str(project) or plan.get("home") != str(home):
            continue
        binding = review.get("recovery", {})
        if (binding.get("entry_before_sha256") != before_sha256
                or binding.get("entry_recovered_sha256") != after_sha256):
            continue
        recovery_path = Path(review.get("recovery_path", ""))
        if (review.get("plan_sha256") != _hash(plan_raw)
                or not recovery_path.is_absolute() or recovery_path.name != "intent.json"
                or recovery_path.parent.parent != home / "operator-route-recovery"):
            raise RetireError("unified_retired_entry_recovery_invalid")
        recovery, recovery_raw = _load(recovery_path, 65536)
        completed, completed_raw = _load(recovery_path.parent / "completed.json", 65536)
        rows = recovery.get("files", [])
        entry = project / ".codex/operator-desktop-entry/desktop-entry.json"
        selected = [row for row in rows if isinstance(row, dict)
                    and row.get("name") == "desktop-entry.json"]
        before = _read(recovery_path.parent / "desktop-entry.json.before", 16384)
        if (binding.get("intent_sha256") != _hash(recovery_raw)
                or binding.get("completed_sha256") != _hash(completed_raw)
                or recovery.get("schema_version") != 1
                or recovery.get("purpose") != "operator_official_route_recovery"
                or completed.get("schema_version") != 1 or completed.get("warnings") != []
                or len(selected) != 1 or completed.get("completed", []).count("desktop-entry.json") != 1
                or selected[0] != {"name": "desktop-entry.json", "target": str(entry),
                                   "before_sha256": before_sha256, "after_sha256": after_sha256}
                or _hash(before) != before_sha256):
            raise RetireError("unified_retired_entry_recovery_invalid")
        previous = json.loads(before)
        if (previous.get("mode") != "reviewed_startup"
                or previous.get("startup_bundle") != ".codex/operator-unified-startup"):
            raise RetireError("unified_retired_entry_recovery_invalid")
        if not historical:
            current = _read(entry, 16384)
            if (_hash(current) != after_sha256
                    or json.loads(current) != {**previous, "mode": "native"}):
                raise RetireError("unified_retired_entry_current_changed")
        matches.append({"status": "archived_retired_entry_witnessed", "recovery": binding,
                        "archive_witness_sha256": _hash(archive_raw),
                        "retirement_intent_sha256": _hash(intent_raw),
                        "startup_bundle": plan.get("startup_bundle"),
                        "configuration_changed": False, "model_requests": 0,
                        "historical_entry_only": historical})
    if len(matches) != 1:
        raise RetireError("unified_retired_entry_witness_ambiguous")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "retire", "status", "archive-preview", "archive",
                                           "archived-entry-status"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--recovery-intent", type=Path)
    parser.add_argument("--expected-review-sha256")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--entry-before-sha256")
    parser.add_argument("--entry-after-sha256")
    parser.add_argument("--historical-entry", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "archived-entry-status":
            if (args.recovery_intent or args.expected_review_sha256 or args.project_root is None
                    or args.entry_before_sha256 is None or args.entry_after_sha256 is None):
                parser.error("archived entry status requires exact project and entry hashes")
            result = archived_entry_status(args.plan, args.project_root, args.entry_before_sha256,
                                           args.entry_after_sha256, historical=args.historical_entry)
        elif (args.project_root is not None or args.entry_before_sha256 is not None
              or args.entry_after_sha256 is not None or args.historical_entry):
            parser.error("entry witness arguments apply only to archived-entry-status")
        elif args.action in ("archive-preview", "archive"):
            if args.recovery_intent:
                parser.error("archive reads the saved retirement receipt")
            result = (archive_preview(args.plan) if args.action == "archive-preview" else
                      archive_retired(args.plan, args.expected_review_sha256))
        elif args.action == "status":
            if args.recovery_intent or args.expected_review_sha256:
                parser.error("status reads the saved receipt")
            result = verify_retired(args.plan)
        else:
            if args.recovery_intent is None:
                parser.error("preview and retire require exact recovery intent")
            if args.action == "preview":
                if args.expected_review_sha256:
                    parser.error("preview does not take a review digest")
                result = preview(args.plan, args.recovery_intent)
            else:
                result = retire(args.plan, args.recovery_intent, args.expected_review_sha256)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, RetireError) else "unified_retire_unavailable"
        print(json.dumps({"status": "unavailable", "reason": code,
                          "configuration_changed": False, "model_requests": 0}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
