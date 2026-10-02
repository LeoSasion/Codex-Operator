"""Explicitly supersede one untouched, prepared unified cold-launch plan.

This is not recovery for an armed or attempted launch. It preserves the whole
old directory and never changes routing, Desktop, the entry or the model cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys

import operator_unified_retire as records


ROOT = "operator-unified-prepared-archive"
SOURCE = "operator-unified-activation"
GENERATION = re.compile(r"generation-[a-f0-9]{32}\Z")
MAX_GENERATIONS = 32
FILES = frozenset({"plan.json", "journal.json", "before.toml", "candidate.toml"})
MARKER = b"operator-native-route-only-v1\n"
CUA_PIPE_LINE = re.compile(rb"""SKY_CUA_NATIVE_PIPE_DIRECTORY = (?:'[^'\r\n]{1,4096}'|"[^"\r\n]{1,4096}")\r?\n?\Z""")


class SupersedeError(ValueError):
    """Fixed public failure code without private paths or configuration text."""


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: object) -> bytes:
    return records._json(value)


def _identity(snapshot) -> dict:
    return records._identity(snapshot)


def _config_delta(saved: bytes, current: bytes) -> str:
    """Admit only one native Desktop-managed CUA pipe value change."""
    if saved == current:
        return "unchanged"
    old_lines = saved.splitlines(keepends=True)
    new_lines = current.splitlines(keepends=True)
    if len(old_lines) != len(new_lines):
        raise SupersedeError("unified_supersede_native_state_changed")
    changed = [index for index, pair in enumerate(zip(old_lines, new_lines))
               if pair[0] != pair[1]]
    if (len(changed) != 1 or
            sum(bool(CUA_PIPE_LINE.fullmatch(line)) for line in old_lines) != 1 or
            sum(bool(CUA_PIPE_LINE.fullmatch(line)) for line in new_lines) != 1 or
            not CUA_PIPE_LINE.fullmatch(old_lines[changed[0]]) or
            not CUA_PIPE_LINE.fullmatch(new_lines[changed[0]]) or
            old_lines[changed[0]].split(b" = ", 1)[1][:1] !=
            new_lines[changed[0]].split(b" = ", 1)[1][:1]):
        raise SupersedeError("unified_supersede_native_state_changed")
    return "cua_pipe_only"


def _router_mode(plan: dict) -> str:
    """Witness either the exact idle service or its absence and a free port."""
    import operator_model_router as router
    import operator_unified_cold_start as cold
    import operator_web_service as web_service

    binding = plan["router"]
    try:
        cold._idle_router(plan)
        return "bound_idle"
    except (OSError, ValueError, cold.ColdStartError):
        pass
    pid = binding["process"]["pid"]
    if web_service.process_identity(pid) is not None:
        raise SupersedeError("unified_supersede_router_changed")
    try:
        with router.reserve_inactive_port(binding["port"]):
            if web_service.route_preview(Path(binding["web_profile"])) != binding["web_route"]:
                raise SupersedeError("unified_supersede_web_route_changed")
    except (OSError, router.RouterError) as exc:
        raise SupersedeError("unified_supersede_router_changed") from exc
    return "stopped_exact_process_absent"


def _source_drift(plan: dict, current: dict[str, str], router_mode: str) -> list[str]:
    saved = plan["source_sha256"]
    if set(current) != set(saved):
        raise SupersedeError("unified_supersede_source_scope_changed")
    changed = sorted(name for name in saved if current[name] != saved[name])
    allowed = {"preparer"}
    if router_mode == "stopped_exact_process_absent":
        allowed.update(("router", "renderer"))
    if set(changed) - allowed:
        raise SupersedeError("unified_supersede_source_changed")
    return changed


def _source_sha256() -> dict[str, str]:
    source = Path(__file__).resolve().parent
    return {name: _hash(records._read(source / name, 1024 * 1024)) for name in (
        "operator_unified_supersede.py", "operator_unified_prepare.py",
        "operator_unified_cold_start.py", "operator_unified_retire.py",
        "operator_unified_withdraw.py")}


def _manifest(directory: Path) -> dict:
    from operator_core import windows_config_transaction as transaction
    children = {path.name for path in directory.iterdir()}
    if children not in (FILES, FILES | {"cache-before.bin"}):
        raise SupersedeError("unified_supersede_unexpected_plan_artifact")
    manifest = {}
    for name in sorted(children):
        snapshot = transaction._snapshot(directory / name)
        manifest[name] = {"sha256": _hash(snapshot.data),
                          "identity": _identity(snapshot)}
    return manifest


def _archive_root(home: Path) -> Path:
    return home / ROOT


def _archive_state(home: Path, *, pending: Path | None = None) -> tuple[dict, frozenset[str]]:
    """Validate every archive before returning its retained plan identities."""
    from operator_core import windows_config_transaction as transaction
    home = Path(home)
    root = _archive_root(home)
    if not records._present(root):
        return {"status": "absent", "generations": 0}, frozenset()
    try:
        records._plain(root)
        if not root.is_dir():
            raise ValueError("archive root")
        generations = list(root.iterdir())
        if not generations or len(generations) > MAX_GENERATIONS:
            raise ValueError("empty archive root")
        old_digests = set()
        found_pending = False
        for generation in generations:
            records._plain(generation)
            if not generation.is_dir() or GENERATION.fullmatch(generation.name) is None:
                raise ValueError("unknown generation")
            if pending is not None and generation == pending:
                pending_children = {path.name for path in generation.iterdir()}
                if pending_children == {"intent.json", "failure-evidence.json"}:
                    from operator_unified_withdraw import validate_empty_allocation_intent
                    allocation, _ = records._load(generation / "intent.json", 65536)
                    validate_empty_allocation_intent(allocation)
                    allocation_review = allocation.get("review")
                    if (set(allocation) != {"schema_version", "phase", "home", "source", "target",
                            "review", "review_sha256", "manifest"}
                            or allocation.get("schema_version") != 3
                            or allocation.get("phase") != "may_have_withdrawn_empty_allocation"
                            or allocation.get("home") != str(home)
                            or allocation.get("source") != str(home / SOURCE)
                            or allocation.get("target") != str(generation / "activation")
                            or allocation.get("manifest") != {}
                            or not isinstance(allocation_review, dict)
                            or allocation_review.get("scope") != "reviewed_empty_preallocation_withdrawal"
                            or allocation.get("review_sha256") != _hash(_json(allocation_review))
                            or _hash(records._read(generation / "failure-evidence.json", 65536))
                                != allocation_review.get("failure_evidence", {}).get("sha256")):
                        raise ValueError("pending allocation changed")
                elif pending_children != {"intent.json"}:
                    raise ValueError("pending generation changed")
                else:
                    legacy_pending, _ = records._load(generation / "intent.json", 65536)
                    if (type(legacy_pending.get("schema_version")) is not int
                            or legacy_pending["schema_version"] not in (1, 2)):
                        raise ValueError("pending failure evidence missing")
                found_pending = True
                continue
            children = {path.name for path in generation.iterdir()}
            if not {"intent.json", "receipt.json"}.issubset(children):
                raise ValueError("incomplete generation")
            intent, intent_raw = records._load(generation / "intent.json", 65536)
            receipt, _ = records._load(generation / "receipt.json", 16384)
            review = intent.get("review")
            saved = intent.get("manifest")
            if intent.get("schema_version") == 3:
                from operator_unified_withdraw import (
                    validate_empty_allocation_archive, empty_allocation_directory_identity)
                if (children != {"intent.json", "receipt.json", "failure-evidence.json", "activation"}
                        or intent.get("home") != str(home)
                        or intent.get("source") != str(home / SOURCE)
                        or intent.get("target") != str(generation / "activation")):
                    raise ValueError("allocation archive scope")
                validate_empty_allocation_archive(intent, receipt, intent_raw)
                archived = generation / "activation"
                records._plain(archived)
                if (not archived.is_dir() or any(archived.iterdir())
                        or empty_allocation_directory_identity(archived) != review["directory_identity"]
                        or _hash(records._read(generation / "failure-evidence.json", 65536))
                            != review["failure_evidence"]["sha256"]):
                    raise ValueError("allocation archive changed")
                continue
            if children != {"intent.json", "receipt.json", "activation"}:
                raise ValueError("incomplete generation")
            if (set(intent) != {"schema_version", "phase", "home", "source", "target",
                                "plan_sha256", "review", "review_sha256", "manifest"}
                    or intent["home"] != str(home)
                    or intent["source"] != str(home / SOURCE)
                    or intent["target"] != str(generation / "activation")
                    or not isinstance(review, dict) or not isinstance(saved, dict)
                    or intent["review_sha256"] != _hash(_json(review))
                    or intent["plan_sha256"] != review.get("plan_sha256")):
                raise ValueError("archive receipt")
            if intent["schema_version"] == 1:
                if (intent["phase"] != "may_have_superseded"
                        or review.get("schema_version") != 1
                        or review.get("scope") != "prepared_plan_supersede" or
                        receipt != {"schema_version": 1, "phase": "superseded_witnessed",
                                    "intent_sha256": _hash(intent_raw),
                                    "plan_sha256": intent["plan_sha256"]}):
                    raise ValueError("archive receipt")
            elif intent["schema_version"] == 2:
                # Explicit unused-plan withdrawal has its own strict schema.
                # The existing path, manifest, journal and replay checks below
                # apply to both kinds of retained original directories.
                from operator_unified_withdraw import validate_archive_intent
                validate_archive_intent(intent, receipt, intent_raw)
            else:
                raise ValueError("archive receipt version")
            archived = generation / "activation"
            records._plain(archived)
            if not archived.is_dir() or _manifest(archived) != saved:
                raise ValueError("archive manifest")
            if intent["schema_version"] == 2:
                from operator_unified_withdraw import _directory_identity
                if _directory_identity(archived) != review["directory_identity"]:
                    raise ValueError("archive directory identity")
            if saved["plan.json"]["sha256"] != intent["plan_sha256"]:
                raise ValueError("archive plan digest")
            journal = json.loads(records._read(archived / "journal.json", 16384))
            if journal != {"schema_version": 1, "phase": "prepared_not_armed",
                           "plan_sha256": intent["plan_sha256"]}:
                raise ValueError("archive journal")
            old_digests.add(intent["plan_sha256"])
        current = home / SOURCE / "plan.json"
        if records._present(current) and _hash(records._read(current, 16384)) in old_digests:
            raise ValueError("old plan reappeared")
        if pending is not None and not found_pending:
            raise ValueError("pending generation missing")
        return ({"status": "pending_internal" if pending is not None else "superseded_witnessed",
                 "generations": len(generations)}, frozenset(old_digests))
    except Exception:
        return {"status": "uncertain", "generations": 0}, frozenset()


def archive_status(home: Path, *, pending: Path | None = None) -> dict:
    """Read-only gate for every later preparation and uninstall."""
    return _archive_state(home, pending=pending)[0]


def _assert_unarchived_plan(home: Path, plan_sha256: str) -> None:
    """Reject a deterministic replay before preparation creates any files."""
    if not isinstance(plan_sha256, str) or records.HEX64.fullmatch(plan_sha256) is None:
        raise SupersedeError("unified_prepared_plan_digest_invalid")
    status, old_digests = _archive_state(home)
    if status["status"] == "uncertain":
        raise SupersedeError("unified_prepared_archive_requires_review")
    if plan_sha256 in old_digests:
        raise SupersedeError("unified_prepared_plan_already_archived")


def _inspect(plan_path: Path, python: Path, *, pending: Path | None = None) -> dict:
    import operator_unified_cold_start as cold
    import operator_unified_prepare as preparation
    import operator_web_startup as web_startup
    from operator_core import windows_config_transaction as transaction

    plan, raw, directory = cold._plan(plan_path)
    home = Path(plan["home"])
    archive = archive_status(home, pending=pending)
    if archive["status"] == "uncertain" or (pending is not None and archive["status"] != "pending_internal"):
        raise SupersedeError("unified_supersede_archive_requires_review")
    if pending is None and archive["generations"] >= MAX_GENERATIONS:
        raise SupersedeError("unified_supersede_archive_capacity")
    if directory != home / SOURCE:
        raise SupersedeError("unified_supersede_plan_scope")
    journal = json.loads(records._read(directory / "journal.json", 16384))
    if journal != {"schema_version": 1, "phase": "prepared_not_armed",
                   "plan_sha256": _hash(raw)}:
        raise SupersedeError("unified_supersede_not_prepared")
    manifest = _manifest(directory)
    if (manifest["plan.json"]["sha256"] != _hash(raw)
            or manifest["before.toml"]["sha256"] != plan["config_sha256"]
            or manifest["candidate.toml"]["sha256"] != plan["candidate_sha256"]
            or (plan["cache"]["existed"] != ("cache-before.bin" in manifest))
            or (plan["cache"]["existed"] and
                manifest["cache-before.bin"]["sha256"] != plan["cache"]["sha256"])):
        raise SupersedeError("unified_supersede_prepared_copy_changed")
    if (set(plan["future_arm_blockers"]) - preparation.REVIEW_BLOCKERS
            or "unified_native_route_lock_active" not in plan["future_arm_blockers"]):
        raise SupersedeError("unified_supersede_native_lock_not_planned")
    config = transaction.observe_config(home / "config.toml")
    marker = transaction._snapshot(home / "operator-native-route-only")
    delta = _config_delta(records._read(directory / "before.toml"), config.data)
    if (marker.data != MARKER or
            (delta == "unchanged" and _identity(config) != plan["config_identity"])):
        raise SupersedeError("unified_supersede_native_state_changed")
    cache_path = home / "models_cache.json"
    if plan["cache"]["existed"]:
        cache = transaction._snapshot(cache_path)
        if _identity(cache) != plan["cache"]["identity"]:
            raise SupersedeError("unified_supersede_cache_identity_changed")
        cache_state = {"sha256": _hash(cache.data), "identity": _identity(cache)}
    else:
        if records._present(cache_path):
            raise SupersedeError("unified_supersede_cache_appeared")
        cache_state = {"sha256": None, "identity": None}
    web_startup.assert_desktop_closed()
    selected = cold._selected_entry(plan)
    python = Path(python).resolve(strict=True)
    if Path(sys.executable).resolve(strict=True) != python:
        raise SupersedeError("unified_supersede_python_mismatch")
    cold._verify_workflow(plan, python)
    binding = plan["router"]
    current = preparation._readiness(Path(plan["project"]), home,
        Path(binding["state"]), Path(binding["web_profile"]), binding["port"],
        ignore_preparation=True, ignore_archive_gate=True)
    router_mode = _router_mode(plan)
    source_drift = _source_drift(plan, current.source_sha256, router_mode)
    expected_blockers = (["unified_native_route_lock_active"] if router_mode == "bound_idle"
                         else ["unified_native_route_lock_active", "unified_router_service_unverified"])
    if (current.report["blockers"] != expected_blockers
            or (router_mode == "bound_idle" and current.router_binding != binding)
            or (router_mode != "bound_idle" and current.router_binding is not None)
            or current.before is None or current.candidate is None
            or _hash(current.before.data) != _hash(config.data)
            or _identity(current.before) != _identity(config)
            or (delta == "unchanged" and router_mode == "bound_idle" and
                _hash(current.candidate) != plan["candidate_sha256"])
            or current.recovery_sha256 != plan["recovery_sha256"]
            or current.retirement != plan["retirement"]
            or current.startup_bundle != plan["startup_bundle"]):
        raise SupersedeError("unified_supersede_preflight_changed")
    return {"schema_version": 1, "scope": "prepared_plan_supersede",
            "plan_sha256": _hash(raw), "manifest_sha256": _hash(_json(manifest)),
            "source_sha256": _source_sha256(),
            "config_sha256": _hash(config.data), "config_identity": _identity(config),
            "config_delta": delta, "candidate_sha256": _hash(current.candidate),
            "marker_sha256": _hash(marker.data), "marker_identity": _identity(marker),
            "cache": cache_state, "entry": selected,
            "router_process": binding["process"], "router_mode": router_mode,
            "replacement_source_sha256": current.source_sha256,
            "source_drift": source_drift,
            "preparer_source_changed": current.source_sha256.get("preparer")
                != plan["source_sha256"].get("preparer")}


def preview(plan_path: Path, python: Path) -> dict:
    review = _inspect(plan_path, python)
    return {"status": "reviewed_preview", "review_sha256": _hash(_json(review)),
            "phase": "prepared_not_armed", "configuration_changed": False,
            "cache_changed": False, "model_requests": 0}


def _post_move_state(archived: Path, review: dict, python: Path) -> None:
    """Witness unchanged live inputs once more before the terminal receipt."""
    import operator_unified_cold_start as cold
    import operator_unified_prepare as preparation
    import operator_web_startup as web_startup
    from operator_core import windows_config_transaction as transaction

    raw = records._read(archived / "plan.json", 16384)
    plan = json.loads(raw)
    if _hash(raw) != review["plan_sha256"]:
        raise SupersedeError("unified_supersede_move_uncertain")
    if _source_sha256() != review["source_sha256"]:
        raise SupersedeError("unified_supersede_source_changed")
    home = Path(plan["home"])
    config = transaction.observe_config(home / "config.toml")
    marker = transaction._snapshot(home / "operator-native-route-only")
    delta = _config_delta(records._read(archived / "before.toml"), config.data)
    if (_hash(config.data) != review["config_sha256"]
            or _identity(config) != review["config_identity"]
            or delta != review["config_delta"]
            or _hash(marker.data) != review["marker_sha256"]
            or _identity(marker) != review["marker_identity"]):
        raise SupersedeError("unified_supersede_native_state_changed")
    cache_path = home / "models_cache.json"
    if review["cache"]["identity"] is None:
        if records._present(cache_path):
            raise SupersedeError("unified_supersede_cache_changed")
    else:
        cache = transaction._snapshot(cache_path)
        if ({"sha256": _hash(cache.data), "identity": _identity(cache)} != review["cache"]):
            raise SupersedeError("unified_supersede_cache_changed")
    web_startup.assert_desktop_closed()
    if cold._selected_entry(plan) != review["entry"]:
        raise SupersedeError("unified_supersede_entry_changed")
    cold._verify_workflow(plan, python)
    binding = plan["router"]
    current = preparation._readiness(Path(plan["project"]), home,
        Path(binding["state"]), Path(binding["web_profile"]), binding["port"],
        ignore_preparation=True, ignore_archive_gate=True)
    router_mode = _router_mode(plan)
    source_drift = _source_drift(plan, current.source_sha256, router_mode)
    expected_blockers = (["unified_native_route_lock_active"] if router_mode == "bound_idle"
                         else ["unified_native_route_lock_active", "unified_router_service_unverified"])
    if (router_mode != review["router_mode"]
            or current.report["blockers"] != expected_blockers
            or (router_mode == "bound_idle" and current.router_binding != binding)
            or (router_mode != "bound_idle" and current.router_binding is not None)
            or current.before is None or current.candidate is None
            or _hash(current.before.data) != review["config_sha256"]
            or _identity(current.before) != review["config_identity"]
            or _hash(current.candidate) != review["candidate_sha256"]
            or current.recovery_sha256 != plan["recovery_sha256"]
            or current.retirement != plan["retirement"]
            or current.startup_bundle != plan["startup_bundle"]
            or current.source_sha256 != review["replacement_source_sha256"]
            or source_drift != review["source_drift"]):
        raise SupersedeError("unified_supersede_preflight_changed")


def supersede(plan_path: Path, python: Path, expected_review_sha256: str) -> dict:
    from operator_core.web_browser_driver import private_directory
    from operator_core import windows_config_transaction as transaction
    if not isinstance(expected_review_sha256, str) or records.HEX64.fullmatch(expected_review_sha256) is None:
        raise SupersedeError("unified_supersede_review_required")
    review = _inspect(plan_path, python)
    if _hash(_json(review)) != expected_review_sha256:
        raise SupersedeError("unified_supersede_review_changed")
    home = plan_path.parent.parent
    root = _archive_root(home)
    if not records._present(root):
        private_directory(root)
    generation = root / ("generation-" + secrets.token_hex(16))
    private_directory(generation)
    with transaction._open(plan_path.parent, directory=True) as source_handle:
        with transaction._open(generation, directory=True) as target_handle:
            if transaction._identity(source_handle)[0].volume != transaction._identity(target_handle)[0].volume:
                raise SupersedeError("unified_supersede_volume_changed")
    # From this point, an interruption is terminal: the preparation gate sees
    # this generation even if the source directory has already moved.
    manifest = _manifest(plan_path.parent)
    intent = {"schema_version": 1, "phase": "may_have_superseded",
              "home": str(home), "source": str(plan_path.parent),
              "target": str(generation / "activation"),
              "plan_sha256": review["plan_sha256"], "review": review,
              "review_sha256": expected_review_sha256, "manifest": manifest}
    records._record(generation / "intent.json", intent)
    if (_inspect(plan_path, python, pending=generation) != review
            or _manifest(plan_path.parent) != manifest):
        raise SupersedeError("unified_supersede_changed_after_intent")
    os.rename(plan_path.parent, generation / "activation")
    if _manifest(generation / "activation") != manifest or records._present(plan_path.parent):
        raise SupersedeError("unified_supersede_move_uncertain")
    _post_move_state(generation / "activation", review, python)
    records._record(generation / "receipt.json", {"schema_version": 1,
        "phase": "superseded_witnessed", "intent_sha256": _hash(_json(intent)),
        "plan_sha256": review["plan_sha256"]})
    if archive_status(home)["status"] != "superseded_witnessed":
        raise SupersedeError("unified_supersede_receipt_uncertain")
    return {"status": "superseded_witnessed", "configuration_changed": False,
            "cache_changed": False, "model_requests": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "supersede", "status"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--expected-review-sha256")
    args = parser.parse_args()
    try:
        if args.action == "status":
            if args.python or args.expected_review_sha256:
                parser.error("status reads the saved generations")
            result = archive_status(args.plan.parent.parent)
        elif args.action == "preview":
            if not args.python or args.expected_review_sha256:
                parser.error("preview requires Python and no review digest")
            result = preview(args.plan, args.python)
        else:
            if not args.python:
                parser.error("supersede requires the saved workflow Python")
            result = supersede(args.plan, args.python, args.expected_review_sha256)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] != "uncertain" else 1
    except Exception as exc:
        code = str(exc) if isinstance(exc, SupersedeError) else "unified_supersede_unavailable"
        print(json.dumps({"status": "unavailable", "reason": code,
                          "configuration_changed": False, "cache_changed": False,
                          "model_requests": 0}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
