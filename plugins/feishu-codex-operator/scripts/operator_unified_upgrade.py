"""Reviewed replacement of a witnessed unified activation; no implicit replay.

Used only by the explicit Desktop-exit handoff. Inspection has no side effects;
execution preserves recovery, retirement and archive witnesses at every step.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
import tomllib

import operator_unified_retire as records


def bound_runtime(plan: dict) -> dict:
    """Validate the exact saved running generation, even if its source needs upgrade."""
    import operator_model_router as router
    import operator_web_service as service
    from operator_unified_handoff import HandoffError
    binding = plan["router"]
    profile, config = service.load_profile(Path(binding["web_profile"]), validate_current=False)
    record = service.current_record(profile)
    state, live = service.observe(profile, config, record)
    if (state.get("status") != "ready" or state.get("active") is not False or live is None
            or config["settings"] != service.settings_identity(config["settings"]["path"])):
        raise HandoffError("handoff_upgrade_saved_web_not_idle")
    saved_route = {"profile_sha256": service.digest(service.read_bytes(profile / "profile.json")),
                   "session_sha256": live[1]}
    current = router.control(Path(binding["state"]), binding["port"])
    diagnostics = current.get("diagnostics", {})
    if (current.get("status") != "ready" or current.get("service") != binding["service"]
            or service.process_identity(current.get("pid")) != binding["process"]
            or diagnostics.get("timing", {}).get("active") != 0
            or diagnostics.get("registry_sha256") != binding["registry_sha256"]
            or records._hash(records._read(Path(binding["state"]) / "registry.json")) != binding["registry_sha256"]
            or diagnostics.get("web_profile_identity") != binding["web_profile_identity"]
            or diagnostics.get("web_route_bound") is not True
            or diagnostics.get("web_route_profile_sha256") != saved_route["profile_sha256"]
            or diagnostics.get("web_route_session_sha256") != saved_route["session_sha256"]
            or saved_route != binding["web_route"]):
        raise HandoffError("handoff_upgrade_router_not_idle")
    runtime = service.runtime_identity()
    return {"runtime_sha256": records._hash(records._json(runtime)),
            "web_runtime_changed": config["runtime"] != runtime}


def inspect(plan_path: Path, python: Path, updates: Path | None) -> dict:
    import operator_unified_cold_start as cold
    from operator_core import model_router_config as settings
    from operator_unified_handoff import HandoffError

    plan, raw, directory = cold._plan(plan_path)
    home = Path(plan["home"])
    if records._present(home / "operator-native-route-only") or records._present(directory / "retirement"):
        raise HandoffError("handoff_upgrade_requires_witnessed_active_route")
    completion_sha, _ = records._active(plan, directory, records._hash(raw))
    arm, _ = records._load(directory / "arm.json")
    if (arm.get("phase") != "armed" or arm.get("plan_sha256") != records._hash(raw)
            or cold._selected_entry(plan) != arm.get("entry")):
        raise HandoffError("handoff_upgrade_entry_changed")
    release_sha, release_entry = records._historical_release(plan, directory, records._hash(raw), arm)
    if (arm.get("marker_release_sha256") != release_sha
            or release_entry is not None and release_entry != arm["entry"]):
        raise HandoffError("handoff_upgrade_release_changed")
    cold._verify_workflow(plan, python)
    current = records._read(home / "config.toml")
    saved = records._read(directory / "candidate.toml")
    original = records._read(directory / "before.toml")
    delta = records._config_delta(saved, current)
    if not original or saved.count(original) != 1:
        raise HandoffError("handoff_upgrade_original_scope_ambiguous")
    prefix, _, suffix = saved.partition(original)
    if not suffix or not current.startswith(prefix) or not current.endswith(suffix):
        raise HandoffError("handoff_upgrade_owned_route_changed")
    native = current[len(prefix):-len(suffix)]
    records._config_delta(original, native)
    import operator_unified_desktop as candidate
    base = tomllib.loads(saved.decode())["model_providers"][candidate.PROVIDER]["base_url"]
    proposed = candidate.render(native, base)[2]
    runtime = bound_runtime(plan)
    result = {"completion_sha256": completion_sha, "config_delta": delta,
              "config_sha256": records._hash(current), "contracts": None,
              "native_sha256": records._hash(native), "candidate_sha256": records._hash(proposed), **runtime}
    if updates is not None:
        if not updates.is_absolute():
            raise HandoffError("handoff_upgrade_absolute_updates_required")
        update_raw = records._read(updates)
        preview = settings.update_contracts(Path(plan["router"]["state"]), json.loads(update_raw))
        result["contracts"] = {"path": str(updates), "sha256": records._hash(update_raw),
                               "registry_sha256": preview["registry_sha256"],
                               "candidate_sha256": preview["candidate_sha256"]}
    return result


def _powershell(script: str, args: list[str], *, parse_json=False):
    from operator_unified_handoff import HandoffError
    shell = Path(os.environ.get("ProgramFiles", "")) / "PowerShell/7/pwsh.exe"
    source = Path(__file__).resolve().parent / script
    result = subprocess.run([str(shell), "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                             str(source), *args], stdin=subprocess.DEVNULL, capture_output=True,
                            timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode or len(result.stdout) > 65536:
        raise HandoffError("handoff_upgrade_maintenance_command_failed")
    return json.loads(result.stdout.decode("utf-8-sig")) if parse_json else None


def reselect_entry(plan: dict, saved_entry: dict, recovery_path: Path,
                   run_directory: Path) -> None:
    """Restore only the witnessed entry bytes, without reinstalling integrations."""
    import operator_unified_cold_start as cold
    import operator_unified_entry_preview as entry
    from operator_core import windows_config_transaction as transaction
    from operator_unified_handoff import HandoffError

    project, home = Path(plan["project"]), Path(plan["home"])
    bundle = project / ".codex/operator-desktop-entry"
    target = bundle / "desktop-entry.json"
    if (recovery_path.name != "intent.json" or
            recovery_path.parent.parent != home / "operator-route-recovery" or
            records._read(home / "operator-native-route-only") != records.MARKER):
        raise HandoffError("handoff_entry_recovery_scope")
    intent, _ = records._load(recovery_path, 65536)
    completed, _ = records._load(recovery_path.parent / "completed.json", 65536)
    rows = [row for row in intent.get("files", []) if row.get("name") == "desktop-entry.json"]
    if (intent.get("purpose") != "operator_official_route_recovery" or
            completed.get("warnings") != [] or len(rows) != 1 or
            completed.get("completed", []).count("desktop-entry.json") != 1 or
            Path(rows[0]["target"]) != target):
        raise HandoffError("handoff_entry_recovery_unwitnessed")
    original = records._read(recovery_path.parent / "desktop-entry.json.before", 16384)
    snapshot = transaction._snapshot(target)
    restored = json.loads(original)
    expected_native = {**restored, "mode": "native"}
    if (restored.get("mode") != "reviewed_startup" or
            restored.get("startup_bundle") != ".codex/operator-unified-startup" or
            json.loads(snapshot.data) != expected_native or
            records._hash(original) != rows[0]["before_sha256"] or
            records._hash(original) != saved_entry["configuration_sha256"] or
            records._hash(snapshot.data) != rows[0]["after_sha256"]):
        raise HandoffError("handoff_entry_recovered_bytes_changed")

    def check():
        if (records._read(home / "operator-native-route-only") != records.MARKER or
                records._present(home / "operator-unified-activation")):
            raise HandoffError("handoff_entry_activation_requires_review")
        cold._verify_workflow(plan, Path(sys.executable))
        files = {"build_sha256": "launcher-manifest.json", "script_sha256": "operator_desktop_entry.ps1",
                 "binary_sha256": "Codex拓展入口.exe"}
        if (any(cold._hash_file(bundle / name) != saved_entry[key] for key, name in files.items()) or
                cold._hash_file(bundle / "operator_desktop_entry.ps1") != cold._hash_file(
                    Path(__file__).with_name("operator_desktop_entry.ps1")) or
                entry.verify_owned_entry(project, bundle, recovered_config=rows[0]) != saved_entry["ownership_sha256"] or
                transaction._snapshot(target) != snapshot):
            raise HandoffError("handoff_entry_ownership_changed")

    check()
    folder = run_directory / "entry-reselection"
    records._plain(run_directory)
    folder.mkdir()  # Existing or uncertain attempts are never repeated.
    records._plain(folder)
    transaction._write_new(folder / "before.json", snapshot.data)
    transaction._write_new(folder / "after.json", original)
    stage, backup = folder / "pending.json", folder / "boundary.bak"
    transaction._write_new(stage, original)
    staged = transaction._snapshot(stage)
    records._record(folder / "intent.json", {"target": str(target), "before_sha256": records._hash(snapshot.data),
                    "after_sha256": records._hash(original), "saved_entry": saved_entry})
    check()
    transaction._replace_file(target, stage, backup)
    if (transaction._snapshot(target) != transaction.ConfigSnapshot(target, original, staged.identity) or
            transaction._snapshot(backup) != transaction.ConfigSnapshot(backup, snapshot.data, snapshot.identity) or
            cold._selected_entry(plan) != saved_entry):
        raise HandoffError("handoff_entry_reselection_unwitnessed")
    records._record(folder / "completed.json", {"status": "entry_reselected", "routing_changed": False})


def execute(manifest: dict, progress, run_directory: Path) -> None:
    import operator_model_router as router
    import operator_unified_cold_start as cold
    import operator_unified_prepare as preparation
    import operator_web_service as web_service
    from operator_core import model_router_config as settings
    from operator_core.responses_labels import assert_registry_edit_stopped
    from operator_unified_handoff import HandoffError

    plan_path, python = Path(manifest["plan"]), Path(manifest["python"])
    project, home = Path(manifest["project"]), Path(manifest["home"])
    state, profile = Path(manifest["router_state"]), Path(manifest["web_profile"])
    port = manifest["port"]
    contract = manifest["upgrade"]["contracts"]
    if inspect(plan_path, python, Path(contract["path"]) if contract else None) != manifest["upgrade"]:
        raise HandoffError("handoff_upgrade_review_changed")
    old_plan, _, _ = cold._plan(plan_path)
    old_arm, _ = records._load(plan_path.parent / "arm.json")

    progress("recovery_entry")
    settings.ensure_recovery_shortcut(home / "config.toml")
    progress("native_recovery")
    recovery = _powershell("restore-codex-official-route.ps1",
        ["-ProjectRoot", str(project), "-CodexHome", str(home), "-Apply", "-Json"], parse_json=True)
    if recovery.get("status") != "completed" or recovery.get("warnings") != [] or not recovery.get("backup"):
        raise HandoffError("handoff_upgrade_recovery_unwitnessed")
    recovery_path = Path(recovery["backup"]) / "intent.json"
    records._recovery(old_plan, plan_path.parent, recovery_path, True,
                      records._present(plan_path.parent / "marker-release"))
    records._record(run_directory / "recovery.json", {"intent": str(recovery_path)})
    if records._hash(records._read(home / "config.toml")) != manifest["upgrade"]["native_sha256"]:
        raise HandoffError("handoff_upgrade_recovered_config_changed")

    progress("stop_router")
    if bound_runtime(old_plan) != {key: manifest["upgrade"][key] for key in ("runtime_sha256", "web_runtime_changed")}:
        raise HandoffError("handoff_upgrade_runtime_changed")
    stopped = router.control(state, port, stop=True)
    if stopped.get("pid") != old_plan["router"]["process"]["pid"] or stopped.get("status") != "stopping":
        raise HandoffError("handoff_upgrade_router_stop_unwitnessed")
    deadline = time.monotonic() + 10
    while web_service.process_identity(stopped["pid"]) is not None:
        if time.monotonic() >= deadline:
            raise HandoffError("handoff_upgrade_router_exit_unwitnessed")
        time.sleep(0.1)
    progress("retire_activation")
    review = records.preview(plan_path, recovery_path)
    records.retire(plan_path, recovery_path, review["review_sha256"])
    progress("archive_retired_activation")
    review = records.archive_preview(plan_path)
    records.archive_retired(plan_path, review["review_sha256"])
    with router.reserve_inactive_port(port):
        if contract:
            progress("update_contracts")
            raw = records._read(Path(contract["path"]))
            if records._hash(raw) != contract["sha256"]:
                raise HandoffError("handoff_upgrade_contracts_changed")
            settings.update_contracts(state, json.loads(raw), apply=True,
                expected_sha256=contract["registry_sha256"],
                expected_candidate_sha256=contract["candidate_sha256"], guard=assert_registry_edit_stopped)

    if manifest["upgrade"]["web_runtime_changed"]:
        progress("stop_saved_web")
        _, saved = web_service.load_profile(profile, validate_current=False)
        web_service.control(profile, "stop")
        deadline = time.monotonic() + 30
        while web_service.status(profile).get("status") != "stopped":
            if time.monotonic() >= deadline:
                raise HandoffError("handoff_upgrade_web_stop_unwitnessed")
            time.sleep(0.5)
        progress("refresh_saved_web")
        web_service.configure(profile, Path(saved["settings"]["path"]))
        progress("start_saved_web")
        ready_web = web_service.start(profile)
        deadline = time.monotonic() + 90
        while ready_web.get("status") in ("starting", "preparing", "connection", "reconnecting"):
            if time.monotonic() >= deadline:
                raise HandoffError("handoff_upgrade_web_start_unwitnessed")
            time.sleep(0.5)
            ready_web = web_service.status(profile)
        if ready_web.get("status") != "ready" or ready_web.get("active") is not False:
            raise HandoffError("handoff_upgrade_web_start_unwitnessed")
        # Finish registration of this exact ready generation; never launch a
        # replacement for a failed or uncertain start.
        registered = web_service.start(profile)
        if registered.get("status") != "ready" or registered.get("reused") is not True:
            raise HandoffError("handoff_upgrade_web_registration_unwitnessed")

    progress("start_router")
    ready = router.start(state, port, web_profile=profile, require_fresh=True)
    progress("bind_web")
    bound = router.bind_web(state, port, profile)
    if bound.get("pid") != ready.get("pid") or bound.get("service") != ready.get("service"):
        raise HandoffError("handoff_upgrade_web_binding_unwitnessed")
    progress("select_entry")
    cold.create_workflow(project, home, python)
    reselect_entry(old_plan, old_arm["entry"], recovery_path, run_directory)
    progress("prepare")
    review = preparation.preview(project, home, state, profile, port)
    if not review.get("prepare_available") or review.get("blockers") != ["unified_native_route_lock_active"]:
        raise HandoffError("handoff_upgrade_preparation_blocked")
    preparation.prepare(project, home, state, profile, port, review["review_sha256"])
    if cold._plan(plan_path)[0]["candidate_sha256"] != manifest["upgrade"]["candidate_sha256"]:
        raise HandoffError("handoff_upgrade_candidate_changed")


def native_reopen_safe(manifest: dict, run_directory: Path) -> bool:
    """Only a witnessed recovered native config and no new activation attempt."""
    try:
        home = Path(manifest["home"])
        recorded, _ = records._load(run_directory / "recovery.json")
        intent_path = Path(recorded["intent"])
        if intent_path.parent.parent != home / "operator-route-recovery":
            return False
        intent, _ = records._load(intent_path)
        completed, _ = records._load(intent_path.parent / "completed.json")
        row = next(row for row in intent["files"] if row["name"] == "config.toml")
        if (intent.get("purpose") != "operator_official_route_recovery"
                or completed.get("warnings") != [] or "config.toml" not in completed.get("completed", [])
                or Path(row["target"]) != home / "config.toml"
                or row["before_sha256"] != manifest["config_sha256"]
                or records._hash(records._read(home / "config.toml")) != row["after_sha256"]
                or records._read(home / "operator-native-route-only") != records.MARKER):
            return False
        plan = Path(manifest["plan"])
        # An original completed attempt may remain before archival. A new or
        # changed attempt is never repaired/reopened by this fallback.
        return (not records._present(plan.parent / "attempt.json") or
                records._hash(records._read(plan)) == manifest["plan_sha256"])
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        return False
