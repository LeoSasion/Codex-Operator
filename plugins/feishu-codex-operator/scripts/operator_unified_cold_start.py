"""One-shot, reviewed cold launch for the unified native model picker.

This module never starts a service or Desktop. The selected Desktop entry runs
the reviewed workflow and opens Desktop only after ``consume`` succeeds. A
created attempt is terminal even when the process dies before its receipt.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys

import operator_unified_entry_preview as entry_preview
import operator_unified_prepare as preparation
import operator_web_service as web_service
import operator_web_startup as web_startup
from operator_core import windows_config_transaction as transaction
from operator_core.web_browser_driver import private_directory


SCRIPT = "start-codex-with-web.ps1"  # Existing schema-2 entry contract.
BUNDLE = "operator-unified-startup"
HEX64 = re.compile(r"[a-f0-9]{64}\Z")


class ColdStartError(ValueError):
    """A fixed public reason without paths, configuration or credentials."""


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash_file(path: Path) -> str:
    preparation.candidate._plain(path)
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ColdStartError("unified_workflow_file_unavailable")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(value: object) -> bytes:
    return preparation._json(value)


def _read(path: Path, *, limit: int = 1024 * 1024) -> bytes:
    raw = entry_preview._read(path, limit=limit)
    assert raw is not None
    return raw


def _record(path: Path, value: dict) -> None:
    preparation._write_new(path, _json(value))


def _load_record(path: Path, *, limit: int = 16384) -> tuple[dict, bytes]:
    try:
        raw = _read(path, limit=limit)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("record object required")
    except (OSError, ValueError, TypeError, entry_preview.PreviewError) as exc:
        raise ColdStartError("unified_record_unavailable") from exc
    return value, raw


def _identity(value: transaction.ConfigSnapshot | None) -> dict | None:
    return None if value is None else preparation._identity(value.identity)


def _plan(plan_path: Path) -> tuple[dict, bytes, Path]:
    if not plan_path.is_absolute() or plan_path.name != "plan.json":
        raise ColdStartError("unified_plan_path_invalid")
    try:
        directory = entry_preview._directory(plan_path.parent)
        if directory.name != preparation.STATE or directory.parent / preparation.STATE != directory:
            raise ValueError("plan location")
        value, raw = _load_record(directory / "plan.json")
        expected = {"schema_version", "project", "home", "review_sha256",
                    "config_sha256", "config_identity", "candidate_sha256", "cache",
                    "recovery_sha256", "retirement", "startup_bundle", "router",
                    "source_sha256", "future_arm_blockers"}
        if (set(value) != expected or value["schema_version"] != 1
                or value["home"] != str(directory.parent)
                or not isinstance(value["project"], str)
                or not Path(value["project"]).is_absolute()
                or not isinstance(value["router"], dict)
                or not isinstance(value["cache"], dict)
                or not isinstance(value["startup_bundle"], dict)
                or not isinstance(value["source_sha256"], dict)
                or not isinstance(value["future_arm_blockers"], list)):
            raise ValueError("plan schema")
        selected_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
        if entry_preview._directory(selected_home) != directory.parent:
            raise ColdStartError("unified_launcher_home_mismatch")
        return value, raw, directory
    except ColdStartError:
        raise
    except (OSError, ValueError, TypeError, KeyError, entry_preview.PreviewError) as exc:
        raise ColdStartError("unified_plan_invalid") from exc


def render_workflow(python: Path, plan_path: Path) -> bytes:
    """An exact schema-2 Web-named wrapper for the existing Desktop entry."""
    python = python.resolve(strict=True)
    source = Path(__file__).resolve()
    python_hash = _hash_file(python)
    source_hash = _hash_file(source)
    quote = web_startup.powershell_quote
    return ("#requires -Version 7.0\n$ErrorActionPreference = 'Stop'\n"
            "$python = " + quote(str(python)) + "\n"
            "if ((Get-FileHash -LiteralPath $python -Algorithm SHA256).Hash.ToLowerInvariant() -cne "
            + quote(python_hash) + ") { throw 'Saved Python changed.' }\n"
            "if ((Get-FileHash -LiteralPath " + quote(str(source))
            + " -Algorithm SHA256).Hash.ToLowerInvariant() -cne "
            + quote(source_hash) + ") { throw 'Reviewed cold launch source changed.' }\n"
            "& $python -X utf8 -E -s -B " + quote(str(source))
            + " consume --plan " + quote(str(plan_path)) + "\n"
            "if ($LASTEXITCODE -ne 0) { exit 1 }\nexit 0\n").encode("utf-8")


def create_workflow(project: Path, home: Path, python: Path) -> dict:
    """Prepare a private reviewed wrapper; no settings or services are changed."""
    project = entry_preview._directory(project)
    home = entry_preview._directory(home)
    bundle = project / ".codex" / BUNDLE
    entry_preview._directory(project / ".codex")
    python = python.resolve(strict=True)
    script = render_workflow(python, home / preparation.STATE / "plan.json")
    manifest = {"schema_version": 2, "startup_script": SCRIPT,
                "entry_files": {SCRIPT: _hash(script)}}
    if entry_preview._present(bundle):
        if (entry_preview._directory(bundle) != bundle
                or _read(bundle / SCRIPT, limit=16384) != script
                or _read(bundle / "startup-sync-plan.json", limit=16384) != _json(manifest)):
            raise ColdStartError("unified_workflow_requires_review")
        return {"status": "workflow_prepared", "reused": True,
                "configuration_changed": False, "model_requests": 0}
    private_directory(bundle)
    _record(bundle / "startup-sync-plan.json", manifest)
    preparation._write_new(bundle / SCRIPT, script)
    return {"status": "workflow_prepared", "reused": False,
            "configuration_changed": False, "model_requests": 0}


def _selected_entry(plan: dict) -> dict:
    """Bind the installed, owned launcher to this exact reviewed bundle."""
    try:
        project = entry_preview._directory(Path(plan["project"]))
        bundle = entry_preview._directory(project / ".codex/operator-desktop-entry")
        config, config_raw = _load_record(bundle / "desktop-entry.json")
        build, build_raw = _load_record(bundle / "launcher-manifest.json")
        script = bundle / "operator_desktop_entry.ps1"
        binary = bundle / "Codex拓展入口.exe"
        source = Path(__file__).resolve().with_name("operator_desktop_entry.ps1")
        script_hash, binary_hash = _hash_file(script), _hash_file(binary)
        if (config.get("schema_version") != 1 or config.get("mode") != "reviewed_startup"
                or build.get("schema_version") != 1
                or build.get("native_fallback") != "native-only-v1"
                or not isinstance(config.get("startup_bundle"), str)
                or Path(config["startup_bundle"]).is_absolute()
                or (project / config["startup_bundle"]).resolve(strict=True)
                    != Path(plan["startup_bundle"]["path"])
                or script_hash != _hash_file(source)
                or config.get("entry_script_sha256") != script_hash
                or build.get("entry_script_sha256") != script_hash
                or build.get("binary_sha256") != binary_hash):
            raise ValueError("entry mismatch")
        ownership_hash = entry_preview.verify_owned_entry(project, bundle)
        return {"configuration_sha256": _hash(config_raw), "build_sha256": _hash(build_raw),
                "script_sha256": script_hash, "binary_sha256": binary_hash,
                "ownership_sha256": ownership_hash}
    except (OSError, ValueError, KeyError, TypeError, entry_preview.PreviewError) as exc:
        raise ColdStartError("unified_entry_not_selected_or_changed") from exc


def _verify_workflow(plan: dict, python: Path) -> None:
    bundle = entry_preview._directory(Path(plan["startup_bundle"]["path"]))
    if bundle != Path(plan["project"]) / ".codex" / BUNDLE:
        raise ColdStartError("unified_workflow_scope_changed")
    script = _read(bundle / SCRIPT, limit=16384)
    if (script != render_workflow(python, Path(plan["home"]) / preparation.STATE / "plan.json")
            or _hash(script) != plan["startup_bundle"]["startup_script_sha256"]
            or _hash(_read(bundle / "startup-sync-plan.json", limit=16384))
                != plan["startup_bundle"]["sync_plan_sha256"]):
        raise ColdStartError("unified_workflow_changed")


def _launcher_identity(plan: dict, python: Path) -> dict:
    """Bind a direct Python worker or the Windows venv launcher and its child."""
    try:
        python = python.resolve(strict=True)
        if Path(sys.executable).resolve(strict=True) != python:
            raise ValueError("arm must run under workflow Python")
        worker = plan["router"]["process"]
        if web_service.process_identity(worker["pid"]) != worker:
            raise ValueError("worker birth changed")
        if Path(worker["executable"]) == python:
            return {"mode": "direct", "worker": worker,
                    "python_sha256": _hash_file(python)}
        base = Path(getattr(sys, "_base_executable", sys.executable)).resolve(strict=True)
        if Path(worker["executable"]) != base or base == python:
            raise ValueError("unexpected worker interpreter")
        parent_pid = web_service.parent_pid(worker["pid"])
        parent = web_service.process_identity(parent_pid)
        if (parent is None or parent.get("pid") != parent_pid
                or Path(parent["executable"]) != python
                or int(parent["birth"]) > int(worker["birth"])):
            raise ValueError("venv parent unverified")
        return {"mode": "venv_launcher_child", "launcher": parent,
                "worker": worker, "python_sha256": _hash_file(python),
                "base_python_sha256": _hash_file(base)}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ColdStartError("unified_python_process_lineage_changed") from exc


def _marker_release(plan: dict, directory: Path) -> str | None:
    """Require the separately witnessed release of a prepared native lock."""
    try:
        from operator_unified_marker_release import verify_release
        return verify_release(directory / "plan.json", require_released=
            "unified_native_route_lock_active" in plan["future_arm_blockers"])
    except Exception as exc:
        raise ColdStartError("unified_marker_release_unverified") from exc


def _checked_prepared(plan: dict, directory: Path) -> transaction.ConfigSnapshot:
    """Recheck every prepared input, including live service and source identity."""
    router = plan["router"]
    evidence = preparation._readiness(Path(plan["project"]), Path(plan["home"]),
        Path(router["state"]), Path(router["web_profile"]), router["port"],
        ignore_preparation=True)
    if evidence.report["blockers"] or not evidence.report["prepare_available"]:
        raise ColdStartError("unified_cold_launch_blocked")
    before = evidence.before
    if before is None or evidence.candidate is None:
        raise ColdStartError("unified_snapshot_unavailable")
    compared = {
        "config_sha256": _hash(before.data),
        "config_identity": _identity(before),
        "candidate_sha256": _hash(evidence.candidate),
        "cache": {"existed": evidence.cache is not None,
                  "sha256": None if evidence.cache is None else _hash(evidence.cache.data),
                  "identity": _identity(evidence.cache)},
        "recovery_sha256": evidence.recovery_sha256,
        "retirement": evidence.retirement,
        "startup_bundle": evidence.startup_bundle,
        "router": evidence.router_binding,
        "source_sha256": evidence.source_sha256,
    }
    if any(plan[key] != value for key, value in compared.items()):
        raise ColdStartError("unified_prepared_evidence_changed")
    if (_read(directory / "before.toml") != before.data
            or _read(directory / "candidate.toml") != evidence.candidate):
        raise ColdStartError("unified_prepared_copy_changed")
    cache_copy = directory / "cache-before.bin"
    if evidence.cache is None:
        if entry_preview._present(cache_copy):
            raise ColdStartError("unified_prepared_copy_changed")
    elif _read(cache_copy) != evidence.cache.data:
        raise ColdStartError("unified_prepared_copy_changed")
    _idle_router(plan)
    return before


def _idle_router(plan: dict) -> None:
    import operator_model_router as router
    binding = plan["router"]
    state, port = Path(binding["state"]), binding["port"]
    current = router.control(state, port)
    process = web_service.process_identity(current.get("pid"))
    registry = _read(state / "registry.json")
    route = web_service.route_preview(Path(binding["web_profile"]))
    diagnostics = current.get("diagnostics")
    active = diagnostics.get("timing", {}).get("active") if isinstance(diagnostics, dict) else None
    if (current.get("status") != "ready" or current.get("service") != binding["service"]
            or process != binding["process"] or active != 0
            or _hash(registry) != binding["registry_sha256"]
            or diagnostics.get("registry_sha256") != binding["registry_sha256"]
            or diagnostics.get("web_profile_identity") != binding["web_profile_identity"]
            or diagnostics.get("web_route_bound") is not True
            or diagnostics.get("web_route_profile_sha256") != binding["web_route"]["profile_sha256"]
            or diagnostics.get("web_route_session_sha256") != binding["web_route"]["session_sha256"]
            or route != binding["web_route"]):
        raise ColdStartError("unified_router_not_idle_or_changed")


def arm(plan_path: Path, python: Path) -> dict:
    """Explicitly bind a reviewed prepared plan for one later cold launch."""
    plan, plan_raw, directory = _plan(plan_path)
    journal, _ = _load_record(directory / "journal.json")
    if journal != {"schema_version": 1, "phase": "prepared_not_armed",
                   "plan_sha256": _hash(plan_raw)}:
        raise ColdStartError("unified_preparation_journal_changed")
    if entry_preview._present(directory / "arm.json") or entry_preview._present(directory / "attempt.json"):
        raise ColdStartError("unified_arming_already_recorded")
    python = python.resolve(strict=True)
    _checked_prepared(plan, directory)
    release = _marker_release(plan, directory)
    _verify_workflow(plan, python)
    selected_entry = _selected_entry(plan)
    launcher = _launcher_identity(plan, python)
    _record(directory / "arm.json", {"schema_version": 1, "phase": "armed",
        "plan_sha256": _hash(plan_raw), "consumer_sha256": _hash_file(Path(__file__).resolve()),
        "python_sha256": _hash_file(python), "entry": selected_entry,
        "launcher": launcher, "marker_release_sha256": release})
    return {"status": "armed_for_one_cold_launch", "configuration_changed": False,
            "model_requests": 0}


def _retire_cache(plan: dict, directory: Path, backup_name: str) -> None:
    cache = Path(plan["home"]) / "models_cache.json"
    expected = plan["cache"]
    backup = directory / backup_name
    if entry_preview._present(backup):
        raise ColdStartError("unified_cache_backup_conflict")
    if expected["existed"]:
        snapshot = transaction._snapshot(cache)
        if (_hash(snapshot.data) != expected["sha256"]
                or _identity(snapshot) != expected["identity"]
                or snapshot.data != _read(directory / "cache-before.bin")):
            raise ColdStartError("unified_cache_changed")
        # Windows rename refuses a destination that appeared after our check.
        os.rename(cache, backup)
        moved = transaction._snapshot(backup)
        if (moved.data != snapshot.data or moved.identity != snapshot.identity):
            raise ColdStartError("unified_cache_move_uncertain")
    elif entry_preview._present(cache):
        raise ColdStartError("unified_cache_changed")
    if entry_preview._present(cache):
        raise ColdStartError("unified_cache_reappeared")


@contextmanager
def _guard_cache(plan: dict, directory: Path):
    """Deny in-place cache writes through preflight, retirement and witnessing.

    Delete sharing permits the existing one-shot rename. A path replacement
    remains possible and must pass the exact identity/bytes retirement checks;
    this handle does not turn those checks into an atomic compare-and-swap.
    """
    cache = Path(plan["home"]) / "models_cache.json"
    with ExitStack() as stack:
        transaction._plain_existing(cache.parent)
        stack.enter_context(transaction._open(cache.parent, directory=True))
        if plan["cache"]["existed"]:
            transaction._plain_existing(cache)
            handle = stack.enter_context(transaction._open(cache))
            data, identity = transaction._read_handle(handle)
            snapshot = transaction.ConfigSnapshot(cache, data, identity)
            if (_hash(data) != plan["cache"]["sha256"]
                    or _identity(snapshot) != plan["cache"]["identity"]
                    or data != _read(directory / "cache-before.bin")):
                raise ColdStartError("unified_prepared_evidence_changed")
        elif entry_preview._present(cache):
            raise ColdStartError("unified_prepared_evidence_changed")
        yield


def consume(plan_path: Path) -> dict:
    """One attempt only; a crash or uncertain witness never triggers retry."""
    plan, plan_raw, directory = _plan(plan_path)
    journal, _ = _load_record(directory / "journal.json")
    if journal != {"schema_version": 1, "phase": "prepared_not_armed",
                   "plan_sha256": _hash(plan_raw)}:
        raise ColdStartError("unified_preparation_journal_changed")
    armed, _ = _load_record(directory / "arm.json")
    if entry_preview._present(directory / "attempt.json"):
        raise ColdStartError("unified_attempt_requires_review")
    python = Path(sys.executable).resolve(strict=True)
    if (armed != {"schema_version": 1, "phase": "armed", "plan_sha256": _hash(plan_raw),
                  "consumer_sha256": _hash_file(Path(__file__).resolve()),
                  "python_sha256": _hash_file(python), "entry": _selected_entry(plan),
                  "launcher": _launcher_identity(plan, python),
                  "marker_release_sha256": _marker_release(plan, directory)}):
        raise ColdStartError("unified_arm_changed")
    # Keep the exact existing cache unwritable across the former gap between
    # readiness and retirement. Missing/replaced paths retain their explicit
    # checks and every created attempt remains terminal on any failure.
    with _guard_cache(plan, directory):
        return _consume_guarded(plan, plan_raw, directory, armed, python)


def _consume_guarded(plan: dict, plan_raw: bytes, directory: Path,
                     armed: dict, python: Path) -> dict:
    before = _checked_prepared(plan, directory)
    _verify_workflow(plan, python)
    # The exclusive attempt is the terminal journal. It precedes every cache
    # and configuration write; a crash leaves it for read-only review.
    backup_name = "cache-retired-" + secrets.token_hex(16) + ".bin"
    try:
        _record(directory / "attempt.json", {"schema_version": 1,
            "phase": "may_have_activated", "plan_sha256": _hash(plan_raw),
            "cache_backup": backup_name})
    except FileExistsError as exc:
        raise ColdStartError("unified_attempt_requires_review") from exc
    _retire_cache(plan, directory, backup_name)
    _idle_router(plan)
    web_startup.assert_desktop_closed()
    if _marker_release(plan, directory) != armed["marker_release_sha256"]:
        raise ColdStartError("unified_marker_release_changed")
    expected = transaction.ConfigSnapshot(Path(plan["home"]) / "config.toml",
        before.data, before.identity)
    result = transaction.replace_config_once(expected.path, expected,
        _read(directory / "candidate.toml"), directory)
    if result.status != "applied" or result.directory is None:
        raise ColdStartError("unified_config_replacement_uncertain")
    if transaction.inspect_transaction(result.directory).status != "applied_witnessed":
        raise ColdStartError("unified_config_witness_uncertain")
    if entry_preview._present(Path(plan["home"]) / "models_cache.json"):
        raise ColdStartError("unified_cache_reappeared")
    _idle_router(plan)
    web_startup.assert_desktop_closed()
    if _marker_release(plan, directory) != armed["marker_release_sha256"]:
        raise ColdStartError("unified_marker_release_changed")
    _record(directory / "completion.json", {"schema_version": 1,
        "phase": "config_switch_witnessed", "plan_sha256": _hash(plan_raw),
        "cache_backup": backup_name, "transaction": str(result.directory),
        "candidate_sha256": plan["candidate_sha256"]})
    return {"status": "config_switch_witnessed", "desktop_acceptance": "unverified",
            "configuration_changed": True, "model_requests": 0}


def status(plan_path: Path) -> dict:
    """Read only. An attempt without completion is terminal, never resumable."""
    plan, plan_raw, directory = _plan(plan_path)
    if entry_preview._present(directory / "attempt.json"):
        attempt, _ = _load_record(directory / "attempt.json")
        if (set(attempt) != {"schema_version", "phase", "plan_sha256", "cache_backup"}
                or attempt.get("schema_version") != 1
                or attempt.get("phase") != "may_have_activated"
                or attempt.get("plan_sha256") != _hash(plan_raw)):
            raise ColdStartError("unified_attempt_requires_review")
        if entry_preview._present(directory / "completion.json"):
            completion, _ = _load_record(directory / "completion.json")
            transaction_dir = Path(completion.get("transaction", ""))
            if (completion.get("plan_sha256") == _hash(plan_raw)
                    and completion.get("phase") == "config_switch_witnessed"
                    and completion.get("candidate_sha256") == plan["candidate_sha256"]
                    and transaction_dir.parent == directory
                    and re.fullmatch(r"\.operator-config-transaction-[a-f0-9]{32}",
                                     transaction_dir.name) is not None
                    and transaction.inspect_transaction(transaction_dir).status == "applied_witnessed"):
                return {"status": "config_switch_witnessed",
                        "desktop_acceptance": "unverified", "configuration_changed": False}
        return {"status": "attempt_requires_review", "configuration_changed": False}
    return {"status": "armed" if entry_preview._present(directory / "arm.json")
            else "prepared_not_armed", "configuration_changed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("workflow", "arm", "consume", "status"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--python", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "workflow":
            if args.plan or not all((args.project_root, args.codex_home, args.python)):
                parser.error("workflow requires project root, Codex home and Python")
            result = create_workflow(args.project_root, args.codex_home, args.python)
        else:
            if not args.plan or any((args.project_root, args.codex_home)):
                parser.error("action requires one plan")
            if args.action == "arm":
                if not args.python:
                    parser.error("arm requires Python")
                result = arm(args.plan, args.python)
            elif args.action == "consume":
                if args.python:
                    parser.error("consume uses its actual Python")
                result = consume(args.plan)
            else:
                if args.python:
                    parser.error("status does not select Python")
                result = status(args.plan)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, ColdStartError) else "unified_cold_start_unavailable"
        attempted = False
        if args.plan is not None and args.plan.is_absolute() and args.plan.name == "plan.json":
            try:
                attempted = entry_preview._present(args.plan.parent / "attempt.json")
            except OSError:
                attempted = True
        print(json.dumps({"status": "unavailable", "reason": code,
            "configuration_changed": None if attempted else False,
            "change_state": "uncertain" if attempted else "unchanged",
            "next_action": "inspect_status" if attempted else None,
            "model_requests": 0}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
