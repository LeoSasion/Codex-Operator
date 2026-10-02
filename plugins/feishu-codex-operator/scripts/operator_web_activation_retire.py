"""One-shot maintenance for a stopped legacy Web activation record.

This never loads the current Web startup plan, starts a service, changes the
Desktop entry, or repairs a failed transaction. Preview is read-only. Retire
requires the exact preview digests and retains the original activation bytes.
"""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tomllib

import operator_model_router as router
import operator_web_service as manager


PLAN = "web-startup.json"
ACTIVATION = "activation.json"
JOURNAL = "legacy-activation-retirement.json"
BACKUP = "legacy-activation-original.json"
ARCHIVE = "legacy-activation-retired.json"
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
HEX32 = re.compile(r"[a-f0-9]{32}\Z")
ERRORS = frozenset({
    "retire_plan_scope", "retire_plan_invalid", "retire_activation_invalid",
    "retire_plan_digest_changed", "retire_original_config_changed",
    "retire_entry_active_or_unknown",
    "retire_desktop_entry_changed", "retire_router_record_invalid",
    "retire_router_process_live_or_unknown", "retire_snapshot_changed",
    "retire_expected_digest_required", "retire_transaction_already_recorded",
    "retire_backup_changed", "retire_config_invalid", "retire_source_unknown",
    "retire_port_not_exclusive", "retire_file_unavailable", "retire_file_too_large",
})


def require(condition, code):
    if not condition:
        raise ValueError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def bounded(path, limit):
    try:
        return manager.read_bytes(path, limit)
    except (OSError, ValueError) as exc:
        code = "retire_file_too_large" if str(exc) == "web_manager_file_bound" else "retire_file_unavailable"
        raise ValueError(code) from exc


def record(raw, code):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, code)
            value[key] = item
        return value

    def invalid_constant(_):
        raise ValueError(code)

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=invalid_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(code) from exc
    require(type(value) is dict, code)
    return value


def exact_identity(value):
    return (type(value) is dict and set(value) == {"pid", "birth", "executable"}
        and type(value["pid"]) is int and value["pid"] > 0
        and type(value["birth"]) is str and value["birth"].isdigit()
        and type(value["executable"]) is str and Path(value["executable"]).is_absolute())


def native_config(raw):
    try:
        config_text = raw.decode("utf-8")
        parsed = tomllib.loads(config_text)
        inactive = re.match(
            r'\A# BEGIN FEISHU OPERATOR MODEL ROUTER\r?\n'
            r'# [ \t]*openai_base_url[ \t]*=[ \t]*'
            r'"http://127\.0\.0\.1:([0-9]{1,5})/[a-f0-9]{64}/v1"[ \t]*\r?\n'
            r'# END FEISHU OPERATOR MODEL ROUTER\r?\n', config_text)
        remaining = (config_text[inactive.end():] if inactive and 1024 <= int(inactive[1]) <= 65535
            else config_text)
        require("# BEGIN FEISHU OPERATOR MODEL ROUTER" not in remaining
            and "# END FEISHU OPERATOR MODEL ROUTER" not in remaining
            and parsed.get("model_provider", "openai") == "openai"
            and "openai_base_url" not in parsed and "model_catalog_json" not in parsed
            and not parsed.get("profile"), "retire_entry_active_or_unknown")
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("retire_config_invalid") from exc


def native_desktop(project, bundle, raw_entry, raw_manifest, raw_script, raw_launcher):
    entry = record(raw_entry, "retire_desktop_entry_changed")
    manifest = record(raw_manifest, "retire_desktop_entry_changed")
    relative = Path(entry.get("startup_bundle", "")) if type(entry.get("startup_bundle")) is str else Path("..")
    source = Path(__file__).resolve().parent
    require(set(entry) == {"schema_version", "mode", "startup_bundle", "entry_script_sha256"}
        and type(entry["schema_version"]) is int and entry["schema_version"] == 1
        and entry["mode"] == "native"
        and not relative.is_absolute() and ".." not in relative.parts
        and project / relative == bundle
        and set(manifest) == {"schema_version", "native_fallback", "entry_script_sha256", "binary_sha256"}
        and type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
        and manifest["native_fallback"] == "native-only-v1"
        and entry["entry_script_sha256"] == manifest["entry_script_sha256"] == digest(raw_script)
        and manifest["binary_sha256"] == digest(raw_launcher)
        and raw_script == bounded(source / "operator_desktop_entry.ps1", 65536),
        "retire_desktop_entry_changed")


def reviewed_replacement_desktop(project, home, desktop, raw_entry, raw_manifest,
                                 raw_script, raw_launcher):
    """Accept only the completed, owned entry-only upgrade in a read-only status check."""
    import operator_unified_entry_preview as entry_preview

    pair_root = project / ".codex/operator-desktop-pair"
    if pair_root.exists() or pair_root.is_symlink():
        return reviewed_legacy_pair_desktop(project, home, desktop, raw_entry,
            raw_manifest, raw_script, raw_launcher)

    code = "retire_desktop_entry_changed"
    entry = record(raw_entry, code)
    manifest = record(raw_manifest, code)
    workflow = project / ".codex/operator-unified-startup"
    source = Path(__file__).resolve().parent
    require(set(entry) == {"schema_version", "mode", "startup_bundle", "entry_script_sha256"}
        and type(entry["schema_version"]) is int and entry["schema_version"] == 1
        and entry["mode"] == "reviewed_startup"
        and entry["startup_bundle"] == ".codex/operator-unified-startup"
        and set(manifest) == {"schema_version", "native_fallback", "entry_script_sha256", "binary_sha256"}
        and type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
        and manifest["native_fallback"] == "native-only-v1"
        and entry["entry_script_sha256"] == manifest["entry_script_sha256"] == digest(raw_script)
        and manifest["binary_sha256"] == digest(raw_launcher)
        and raw_script == bounded(source / "operator_desktop_entry.ps1", 65536), code)
    startup_script = bounded(workflow / "start-codex-with-web.ps1", 16384)
    startup_metadata = bounded(workflow / "startup-sync-plan.json", 16384)
    require(record(startup_metadata, code) == {
        "schema_version": 2, "startup_script": "start-codex-with-web.ps1",
        "entry_files": {"start-codex-with-web.ps1": digest(startup_script)}}, code)
    migration_raw = bounded(project / ".codex/operator-entry-migration/journal.json", 1048576)
    upgrade = project / ".codex/operator-entry-upgrade"
    intent_raw = bounded(upgrade / "intent.json", 65536)
    receipt = record(bounded(upgrade / "receipt.json", 65536), code)
    intent = record(intent_raw, code)
    plan = intent.get("plan")
    before_sha = digest(bounded(upgrade / "before.json", 65536))
    require(type(plan) is dict and set(intent) == {"schema_version", "phase", "plan", "plan_sha256"}
        and intent["schema_version"] == 1 and intent["phase"] == "may_have_updated"
        and plan.get("schema_version") == 1 and plan.get("scope") == "entry_only_config_upgrade"
        and plan.get("project") == str(project) and plan.get("runtime_ownership") == "unresolved"
        and plan.get("migration_sha256") == digest(migration_raw)
        and plan.get("codex_home") == str(home)
        and plan.get("startup_bundle") == str(workflow)
        and plan.get("startup_metadata_sha256") == digest(startup_metadata)
        and plan.get("startup_script_sha256") == digest(startup_script)
        and plan.get("entry_script_sha256") == digest(raw_script)
        and plan.get("binary_sha256") == digest(raw_launcher)
        and plan.get("after_sha256") == digest(raw_entry)
        and plan.get("before_sha256") == before_sha
        and set(receipt) == {"schema_version", "phase", "plan_sha256", "intent_sha256",
                             "before_sha256", "after_sha256"}
        and receipt["schema_version"] == 1 and receipt["phase"] == "applied"
        and receipt["plan_sha256"] == intent["plan_sha256"]
        and receipt["intent_sha256"] == digest(intent_raw)
        and receipt["before_sha256"] == before_sha
        and receipt["after_sha256"] == digest(raw_entry)
        and digest(bounded(upgrade / "after.json", 65536)) == digest(raw_entry), code)
    # This independently checks the completed upgrade receipt, migration build,
    # shortcut bytes/targets, adoption receipt and migration-time originals.
    entry_preview.verify_owned_entry(project, desktop)


def reviewed_legacy_pair_desktop(project, home, desktop, raw_entry, raw_manifest,
                                 raw_script, raw_launcher):
    """Bind the retained config upgrade to the first build of an owned legacy pair.

    The old upgrade describes historical bytes, while the pair's complete build
    chain owns the current bytes. Neither record is rewritten or promoted to
    first-install runtime ownership by this read-only recognition.
    """
    import operator_unified_entry_preview as entry_preview

    code = "retire_desktop_entry_changed"
    pair_root = project / ".codex/operator-desktop-pair"
    workflow = project / ".codex/operator-unified-startup"
    upgrade = project / ".codex/operator-entry-upgrade"
    source = Path(__file__).resolve().parent
    snapshots = {}

    def capture(path, limit):
        raw = bounded(path, limit)
        snapshots[path] = (limit, raw)
        return raw

    current = {"desktop-entry.json": raw_entry, "launcher-manifest.json": raw_manifest,
        "operator_desktop_entry.ps1": raw_script, "Codex拓展入口.exe": raw_launcher}
    for name, raw in current.items():
        limit = 1048576 if name.endswith(".exe") else 65536
        require(capture(desktop / name, limit) == raw, code)
    current["Codex拓展入口.ico"] = capture(desktop / "Codex拓展入口.ico", 1048576)
    pair = record(capture(pair_root / "ownership.json", 1048576), code)
    origin_raw = capture(pair_root / "legacy-origin.json", 1048576)
    origin = record(origin_raw, code)
    migration_raw = capture(project / ".codex/operator-entry-migration/journal.json", 1048576)
    intent_raw = capture(upgrade / "intent.json", 65536)
    intent = record(intent_raw, code)
    receipt_raw = capture(upgrade / "receipt.json", 65536)
    receipt = record(receipt_raw, code)
    before_sha = digest(capture(upgrade / "before.json", 65536))
    after_sha = digest(capture(upgrade / "after.json", 65536))
    # An explicitly renewed workflow retains the historical upgrade's bytes
    # and identities independently. Never rewrite that upgrade or the pair.
    import operator_unified_workflow_renew as renewal
    historical_workflow = renewal.retained_workflow(project, home)
    if historical_workflow is not None:
        capture(workflow / "start-codex-with-web.ps1", 16384)
        capture(workflow / "startup-sync-plan.json", 16384)
    selected_workflow = historical_workflow or workflow
    startup_script = capture(selected_workflow / "start-codex-with-web.ps1", 16384)
    startup_metadata = capture(selected_workflow / "startup-sync-plan.json", 16384)
    require(record(startup_metadata, code) == {
        "schema_version": 2, "startup_script": "start-codex-with-web.ps1",
        "entry_files": {"start-codex-with-web.ps1": digest(startup_script)}}, code)
    expected_workflow = {"path": str(workflow), "startup_script_sha256": digest(startup_script),
        "startup_metadata_sha256": digest(startup_metadata)}
    steps = pair.get("steps")
    require(type(pair.get("schema_version")) is int and pair["schema_version"] == 1
        and pair.get("scope") == "legacy_entry_only" and pair.get("phase") == "installed"
        and pair.get("runtime_ownership") == "unresolved"
        and pair.get("project") == str(project) and pair.get("home") == str(home)
        and pair.get("build") == {name: digest(raw) for name, raw in current.items()}
        and pair.get("origin_sha256") == digest(origin_raw)
        and type(origin.get("schema_version")) is int and origin["schema_version"] == 1
        and origin.get("scope") == "legacy_pair_origin"
        and origin.get("project") == str(project) and origin.get("home") == str(home)
        and origin.get("runtime_ownership") == "unresolved"
        and origin.get("migration_sha256") == digest(migration_raw)
        and type(steps) is list and 1 <= len(steps) <= 128
        and all(type(step) is dict and step.get("workflow") == expected_workflow for step in steps), code)
    first = steps[0].get("before")
    require(type(first) is dict and set(first) == set(current)
        and all(type(value) is str and HEX64.fullmatch(value) for value in first.values())
        and first == origin.get("before_build"), code)
    adoption_path = project / ".codex/operator-entry-shortcut-adoption/receipt.json"
    adoption_sha = (digest(capture(adoption_path, 65536))
        if adoption_path.exists() or adoption_path.is_symlink() else "absent")
    require(pair.get("origin") == {"migration_sha256": digest(migration_raw),
        "upgrade_receipt_sha256": digest(receipt_raw), "adoption_receipt_sha256": adoption_sha}, code)
    entry = record(raw_entry, code)
    manifest = record(raw_manifest, code)
    require(set(entry) == {"schema_version", "mode", "startup_bundle", "entry_script_sha256"}
        and type(entry["schema_version"]) is int and entry["schema_version"] == 1
        and entry["mode"] == "reviewed_startup"
        and entry["startup_bundle"] == ".codex/operator-unified-startup"
        and set(manifest) == {"schema_version", "native_fallback", "entry_script_sha256",
            "binary_sha256", "build_date", "product_version", "source_sha256", "shortcut_layout"}
        and type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
        and manifest["native_fallback"] == "native-only-v1"
        and manifest["shortcut_layout"] == "paired"
        and manifest["build_date"] == pair.get("build_date")
        and manifest["product_version"] == pair.get("version")
        and manifest["source_sha256"] == pair.get("source_sha256")
        and entry["entry_script_sha256"] == manifest["entry_script_sha256"] == digest(raw_script)
        and manifest["binary_sha256"] == digest(raw_launcher)
        and raw_script == capture(source / "operator_desktop_entry.ps1", 65536), code)
    plan = intent.get("plan")
    require(type(plan) is dict and set(intent) == {"schema_version", "phase", "plan", "plan_sha256"}
        and type(intent["schema_version"]) is int and intent["schema_version"] == 1
        and intent["phase"] == "may_have_updated"
        and plan.get("schema_version") == 1 and plan.get("scope") == "entry_only_config_upgrade"
        and plan.get("project") == str(project) and plan.get("runtime_ownership") == "unresolved"
        and plan.get("migration_sha256") == digest(migration_raw)
        and plan.get("codex_home") == str(home) and plan.get("startup_bundle") == str(workflow)
        and plan.get("startup_metadata_sha256") == digest(startup_metadata)
        and plan.get("startup_script_sha256") == digest(startup_script)
        and plan.get("entry_script_sha256") == first["operator_desktop_entry.ps1"]
        and plan.get("binary_sha256") == first["Codex拓展入口.exe"]
        and plan.get("after_sha256") == first["desktop-entry.json"] == after_sha
        and plan.get("before_sha256") == before_sha
        and set(receipt) == {"schema_version", "phase", "plan_sha256", "intent_sha256",
            "before_sha256", "after_sha256"}
        and type(receipt["schema_version"]) is int and receipt["schema_version"] == 1
        and receipt["phase"] == "applied" and receipt["plan_sha256"] == intent["plan_sha256"]
        and receipt["intent_sha256"] == digest(intent_raw)
        and receipt["before_sha256"] == before_sha and receipt["after_sha256"] == after_sha, code)
    # This checks every transaction, original, migration/adoption receipt, build
    # step, real shortcut target and retained shortcut identity independently.
    fingerprint = entry_preview.verify_owned_entry(project, desktop)
    require(entry_preview.verify_owned_entry(project, desktop) == fingerprint, code)
    require(all(bounded(path, limit) == raw for path, (limit, raw) in snapshots.items())
        and (adoption_sha != "absent" or
            (not adoption_path.exists() and not adoption_path.is_symlink())), code)
    require(renewal.retained_workflow(project, home) == historical_workflow, code)


def plan_paths(plan_path):
    plan_path = manager.checked_path(plan_path)
    require(plan_path.name == PLAN, "retire_plan_scope")
    bundle = plan_path.parent
    require(bundle.name == "operator-web-startup" and bundle.parent.name == ".codex",
        "retire_plan_scope")
    project = bundle.parent.parent
    return project, bundle


def inspect_files(plan_path):
    """Capture complete bounded file snapshots without requiring current runtime hashes."""
    project, bundle = plan_paths(plan_path)
    raw_plan = bounded(plan_path, 65536)
    plan = record(raw_plan, "retire_plan_invalid")
    require(set(plan) == {"version", "project", "profile", "home", "port", "runtime",
        "profile_sha256", "router_state", "startup_script"}
        and type(plan["version"]) is int and plan["version"] == 1,
        "retire_plan_invalid")
    require(plan["project"] == str(project) and plan["profile"] == str(project / ".codex/operator-web-service")
        and plan["router_state"] == str(bundle / "router") and plan["startup_script"] == "start-codex-with-web.ps1"
        and type(plan["port"]) is int and 1024 <= plan["port"] <= 65535,
        "retire_plan_scope")
    home = manager.checked_path(plan["home"], directory=True)
    state = manager.checked_path(plan["router_state"], directory=True)
    runtime = plan["runtime"]
    source = Path(__file__).resolve().parent
    require(type(runtime) is dict and runtime.get("source_root") == str(source)
        and runtime.get("backend") == str(source / "operator_web_model.py")
        and type(runtime.get("startup_sources")) is dict
        and set(runtime["startup_sources"]) == {"operator_web_startup.py", "operator_model_router.py",
            "operator_desktop_entry.ps1"}
        and all(type(value) is str and HEX64.fullmatch(value) for value in runtime["startup_sources"].values())
        and type(runtime.get("python")) is str and Path(runtime["python"]).is_absolute()
        and type(runtime.get("worker_python")) is str and Path(runtime["worker_python"]).is_absolute(),
        "retire_source_unknown")

    files = {
        "plan": (plan_path, 65536),
        "activation": (bundle / ACTIVATION, 65536),
        "original_config": (bundle / "config-before-activation.toml", 1048576),
        "router_launch": (bundle / "router-launch.json", 65536),
        "startup_workflow": (bundle / "start-codex-with-web.ps1", 65536),
        "startup_sync": (bundle / "startup-sync-plan.json", 65536),
        "registry": (state / "registry.json", 1048576),
        "token": (state / "token", 128),
        "profile": (Path(plan["profile"]) / "profile.json", 65536),
        "config": (home / "config.toml", 1048576),
        "native_lock": (home / "operator-native-route-only", 4096),
        "desktop_entry": (project / ".codex/operator-desktop-entry/desktop-entry.json", 16384),
        "desktop_manifest": (project / ".codex/operator-desktop-entry/launcher-manifest.json", 16384),
        "desktop_script": (project / ".codex/operator-desktop-entry/operator_desktop_entry.ps1", 65536),
        "desktop_launcher": (project / ".codex/operator-desktop-entry/Codex拓展入口.exe", 1048576),
    }
    contents = {name: bounded(path, limit) for name, (path, limit) in files.items()}
    activation = record(contents["activation"], "retire_activation_invalid")
    require(set(activation) == {"version", "phase", "plan_sha256", "config_sha256"}
        and type(activation["version"]) is int and activation["version"] == 1
        and activation["phase"] == "activated"
        and type(activation["plan_sha256"]) is str and HEX64.fullmatch(activation["plan_sha256"])
        and type(activation["config_sha256"]) is str and HEX64.fullmatch(activation["config_sha256"]),
        "retire_activation_invalid")
    require(digest(raw_plan) == activation["plan_sha256"], "retire_plan_digest_changed")
    require(digest(contents["original_config"]) == activation["config_sha256"],
        "retire_original_config_changed")

    launch = record(contents["router_launch"], "retire_router_record_invalid")
    require(set(launch) == {"version", "phase", "attempt", "runtime", "pid", "process", "worker", "service_pid"}
        and type(launch["version"]) is int and launch["version"] == 1
        and launch["phase"] == "stopped"
        and type(launch["attempt"]) is str and HEX32.fullmatch(launch["attempt"])
        and launch["runtime"] == runtime
        and exact_identity(launch["process"]) and exact_identity(launch["worker"])
        and launch["pid"] == launch["process"]["pid"]
        and launch["service_pid"] == launch["worker"]["pid"]
        and launch["process"]["executable"] == runtime["python"]
        and launch["worker"]["executable"] in (runtime["python"], runtime["worker_python"]),
        "retire_router_record_invalid")

    native_desktop(project, bundle, contents["desktop_entry"], contents["desktop_manifest"],
        contents["desktop_script"], contents["desktop_launcher"])

    require(not (state / "codex-entry.json").exists() and not (state / "codex-entry.json").is_symlink(),
        "retire_entry_active_or_unknown")
    native_config(contents["config"])

    hashes = {name: digest(value) for name, value in contents.items()}
    snapshot = digest(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("ascii"))
    return plan, launch, files, contents, hashes, snapshot


def assert_router_absent(launch):
    for saved in (launch["process"], launch["worker"]):
        observed = manager.process_identity(saved["pid"])
        require(observed is None or (observed.get("birth") != saved["birth"]),
            "retire_router_process_live_or_unknown")


def retirement_status(plan_path, *, replacement_home=None):
    """Read-only classification for other preflights; uncertainty always blocks."""
    try:
        project, bundle = plan_paths(plan_path)
        artifacts = (bundle / JOURNAL, bundle / BACKUP, bundle / ARCHIVE)
        if not any(path.exists() or path.is_symlink() for path in artifacts):
            return "absent"
        with manager.operation_lock(bundle):
            require(all(path.is_file() and not path.is_symlink() for path in artifacts)
                and not (bundle / ACTIVATION).exists() and not (bundle / ACTIVATION).is_symlink(),
                "retire_transaction_already_recorded")
            journal_raw = bounded(bundle / JOURNAL, 65536)
            journal = record(journal_raw, "retire_transaction_already_recorded")
            require(set(journal) == {"version", "phase", "plan_sha256", "activation_sha256",
                "snapshot_sha256", "files_sha256"}
                and type(journal["version"]) is int and journal["version"] == 1
                and journal["phase"] == "retired"
                and all(type(journal[key]) is str and HEX64.fullmatch(journal[key]) for key in
                    ("plan_sha256", "activation_sha256", "snapshot_sha256"))
                and type(journal["files_sha256"]) is dict
                and set(journal["files_sha256"]) == {"plan", "activation", "original_config",
                    "router_launch", "startup_workflow", "startup_sync", "registry", "token",
                    "profile", "config", "native_lock", "desktop_entry", "desktop_manifest",
                    "desktop_script", "desktop_launcher"}
                and all(type(value) is str and HEX64.fullmatch(value)
                    for value in journal["files_sha256"].values()),
                "retire_transaction_already_recorded")
            hashes = journal["files_sha256"]
            require(hashes["plan"] == journal["plan_sha256"]
                and hashes["activation"] == journal["activation_sha256"]
                and digest(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("ascii"))
                    == journal["snapshot_sha256"], "retire_transaction_already_recorded")
            original = bounded(bundle / BACKUP, 65536)
            archived = bounded(bundle / ARCHIVE, 65536)
            activation = record(original, "retire_activation_invalid")
            require(original == archived and digest(original) == journal["activation_sha256"]
                and set(activation) == {"version", "phase", "plan_sha256", "config_sha256"}
                and type(activation["version"]) is int and activation["version"] == 1
                and activation["phase"] == "activated"
                and activation["plan_sha256"] == journal["plan_sha256"],
                "retire_backup_changed")
            raw_plan = bounded(plan_path, 65536)
            plan = record(raw_plan, "retire_plan_invalid")
            require(digest(raw_plan) == journal["plan_sha256"]
                and plan.get("project") == str(project)
                and plan.get("router_state") == str(bundle / "router")
                and type(plan.get("port")) is int and 1024 <= plan["port"] <= 65535,
                "retire_plan_digest_changed")
            original_config = bounded(bundle / "config-before-activation.toml", 1048576)
            require(digest(original_config) == activation["config_sha256"]
                == hashes["original_config"], "retire_original_config_changed")
            # The saved Web profile can be explicitly reconfigured after this
            # activation is retired. Its retirement-time digest remains bound
            # in the journal snapshot, but its current bytes are not an old
            # activation credential. The old startup/router artifacts are.
            historical_files = {
                "startup_workflow": (bundle / "start-codex-with-web.ps1", 65536),
                "startup_sync": (bundle / "startup-sync-plan.json", 65536),
                "registry": (bundle / "router/registry.json", 1048576),
                "token": (bundle / "router/token", 128),
            }
            require(all(digest(bounded(path, limit)) == hashes[name]
                for name, (path, limit) in historical_files.items()),
                "retire_snapshot_changed")
            raw_launch = bounded(bundle / "router-launch.json", 65536)
            launch = record(raw_launch, "retire_router_record_invalid")
            require(digest(raw_launch) == hashes["router_launch"]
                and type(launch.get("version")) is int and launch["version"] == 1
                and launch.get("phase") == "stopped"
                and launch.get("runtime") == plan.get("runtime")
                and exact_identity(launch.get("process")) and exact_identity(launch.get("worker"))
                and launch.get("pid") == launch["process"]["pid"]
                and launch.get("service_pid") == launch["worker"]["pid"],
                "retire_router_record_invalid")
            state = manager.checked_path(plan["router_state"], directory=True)
            entry_journal = state / "codex-entry.json"
            require(not entry_journal.exists() and not entry_journal.is_symlink(),
                "retire_entry_active_or_unknown")
            home = manager.checked_path(plan["home"], directory=True)
            native_config(bounded(home / "config.toml", 1048576))
            desktop = project / ".codex/operator-desktop-entry"
            entry_bytes = bounded(desktop / "desktop-entry.json", 16384)
            manifest_bytes = bounded(desktop / "launcher-manifest.json", 16384)
            script_bytes = bounded(desktop / "operator_desktop_entry.ps1", 65536)
            launcher_bytes = bounded(desktop / "Codex拓展入口.exe", 1048576)
            if (replacement_home is not None
                    and record(entry_bytes, "retire_desktop_entry_changed").get("mode")
                        == "reviewed_startup"):
                require(manager.checked_path(replacement_home, directory=True) == home,
                    "retire_desktop_entry_changed")
                reviewed_replacement_desktop(project, home, desktop, entry_bytes,
                    manifest_bytes, script_bytes, launcher_bytes)
            else:
                native_desktop(project, bundle, entry_bytes, manifest_bytes,
                    script_bytes, launcher_bytes)
            assert_router_absent(launch)
            with router.reserve_inactive_port(plan["port"]):
                require(bounded(bundle / JOURNAL, 65536) == journal_raw
                    and bounded(bundle / BACKUP, 65536) == original
                    and bounded(bundle / ARCHIVE, 65536) == archived
                    and not (bundle / ACTIVATION).exists() and not (bundle / ACTIVATION).is_symlink()
                    and not entry_journal.exists() and not entry_journal.is_symlink(),
                    "retire_snapshot_changed")
                assert_router_absent(launch)
            return "retired"
    except Exception:
        return "uncertain"


@contextmanager
def guarded(plan_path):
    _, bundle = plan_paths(plan_path)
    with manager.operation_lock(bundle):
        require(not (bundle / JOURNAL).exists() and not (bundle / JOURNAL).is_symlink()
            and not (bundle / BACKUP).exists() and not (bundle / BACKUP).is_symlink()
            and not (bundle / ARCHIVE).exists() and not (bundle / ARCHIVE).is_symlink(),
            "retire_transaction_already_recorded")
        plan, launch, files, contents, hashes, snapshot = inspect_files(plan_path)
        assert_router_absent(launch)
        try:
            with router.reserve_inactive_port(plan["port"]):
                yield plan, launch, files, contents, hashes, snapshot
        except router.settings.RouterError as exc:
            if str(exc) == "router_port_in_use_stop_before_registration":
                raise ValueError("retire_port_not_exclusive") from exc
            raise


def preview(plan_path):
    with guarded(plan_path) as (plan, _, _, contents, _, snapshot):
        return {"status": "ready_to_retire", "plan_sha256": digest(contents["plan"]),
            "activation_sha256": digest(contents["activation"]), "snapshot_sha256": snapshot,
            "router_port": plan["port"], "configuration_changed": False,
            "model_requests": 0, "replayed": False}


def write_exclusive(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def assert_unchanged(files, contents, launch):
    for name, (path, limit) in files.items():
        require(bounded(path, limit) == contents[name], "retire_snapshot_changed")
    assert_router_absent(launch)
    entry_journal = Path(files["registry"][0]).parent / "codex-entry.json"
    require(not entry_journal.exists() and not entry_journal.is_symlink(),
        "retire_entry_active_or_unknown")


def retire(plan_path, expected_plan, expected_activation, expected_snapshot):
    require(all(type(value) is str and HEX64.fullmatch(value) for value in
        (expected_plan, expected_activation, expected_snapshot)), "retire_expected_digest_required")
    _, bundle = plan_paths(plan_path)
    with guarded(plan_path) as (plan, launch, files, contents, hashes, snapshot):
        require(expected_plan == hashes["plan"] and expected_activation == hashes["activation"]
            and expected_snapshot == snapshot, "retire_snapshot_changed")
        journal_path, backup_path, archive_path = bundle / JOURNAL, bundle / BACKUP, bundle / ARCHIVE
        journal = {"version": 1, "phase": "may_have_retired", "plan_sha256": hashes["plan"],
            "activation_sha256": hashes["activation"], "snapshot_sha256": snapshot,
            "files_sha256": hashes}
        write_exclusive(journal_path, json.dumps(journal, sort_keys=True).encode("ascii"))
        write_exclusive(backup_path, contents["activation"])
        require(bounded(backup_path, 65536) == contents["activation"], "retire_backup_changed")
        assert_unchanged(files, contents, launch)
        require(not archive_path.exists() and not archive_path.is_symlink(),
            "retire_transaction_already_recorded")
        os.rename(bundle / ACTIVATION, archive_path)
        for name, (path, limit) in files.items():
            if name != "activation":
                require(bounded(path, limit) == contents[name], "retire_snapshot_changed")
        assert_router_absent(launch)
        entry_journal = Path(plan["router_state"]) / "codex-entry.json"
        require(not entry_journal.exists() and not entry_journal.is_symlink(),
            "retire_entry_active_or_unknown")
        require(not (bundle / ACTIVATION).exists() and not (bundle / ACTIVATION).is_symlink()
            and bounded(archive_path, 65536) == contents["activation"]
            and bounded(backup_path, 65536) == contents["activation"], "retire_backup_changed")
        manager.service.write_json(journal_path, {**journal, "phase": "retired"})
        return {"status": "retired", "plan_sha256": hashes["plan"],
            "original_activation_sha256": hashes["activation"],
            "configuration_changed": False, "model_requests": 0, "replayed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "retire"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--expected-activation-sha256")
    parser.add_argument("--expected-snapshot-sha256")
    args = parser.parse_args()
    expectations = (args.expected_plan_sha256, args.expected_activation_sha256,
        args.expected_snapshot_sha256)
    if args.action == "preview":
        require(all(value is None for value in expectations), "retire_expected_digest_required")
        result = preview(args.plan)
    else:
        result = retire(args.plan, *expectations)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = str(exc) if type(exc) is ValueError and str(exc) in ERRORS else "retire_unavailable"
        print(json.dumps({"status": "unavailable", "code": code,
            "configuration_changed": False, "model_requests": 0, "replayed": False}))
        raise SystemExit(1)
