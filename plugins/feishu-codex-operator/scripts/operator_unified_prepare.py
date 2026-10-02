"""Reviewed unified-picker preparation; no activation or Desktop entry writes.

The saved plan is deliberately `prepared_not_armed`; a separate one-shot
cold-launch consumer must arm and recheck it. Public results contain only
fixed codes and digests.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re

import operator_model_router as router
import operator_unified_desktop as candidate
import operator_unified_entry_preview as entry_preview
import operator_web_service as web_service
import operator_web_startup as web_startup
from operator_core import windows_config_transaction as transaction
from operator_core.web_browser_driver import private_directory


STATE = "operator-unified-activation"
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
REVIEW_BLOCKERS = frozenset({
    "unified_native_route_lock_active", "unified_desktop_open_or_unknown",
})


class PrepareError(ValueError):
    """Fixed content-free reason code."""


@dataclass(frozen=True)
class Evidence:
    report: dict
    before: transaction.ConfigSnapshot | None
    candidate: bytes | None
    cache: transaction.ConfigSnapshot | None
    router_binding: dict | None
    recovery_sha256: str | None
    retirement: str
    source_sha256: dict[str, str]
    startup_bundle: dict | None


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(raw: object) -> bytes:
    return (json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _identity(value: transaction.FileIdentity | None) -> dict | None:
    return None if value is None else {"volume": value.volume, "file_id": value.file_id}


def _startup_bundle(project: Path) -> dict | None:
    """Bind an existing schema-2 entry workflow without executing it."""
    bundle = project / ".codex/operator-unified-startup"
    if bundle.is_symlink() or not bundle.is_dir():
        return None
    try:
        candidate._plain(bundle)
        manifest_raw = entry_preview._read(bundle / "startup-sync-plan.json", limit=16384)
        script_raw = entry_preview._read(bundle / "start-codex-with-web.ps1", limit=16384)
        manifest = json.loads(manifest_raw)
        if manifest != {"schema_version": 2, "startup_script": "start-codex-with-web.ps1",
                        "entry_files": {"start-codex-with-web.ps1": _hash(script_raw)}}:
            return None
        return {"path": str(bundle), "sync_plan_sha256": _hash(manifest_raw),
                "startup_script_sha256": _hash(script_raw)}
    except (candidate.CandidateError, entry_preview.PreviewError, OSError,
            ValueError, TypeError, KeyError):
        return None


def _readiness(project: Path, home: Path, state: Path, profile: Path, port: int,
               *, ignore_preparation: bool = False,
               ignore_archive_gate: bool = False) -> Evidence:
    project = entry_preview._directory(project)
    home = entry_preview._directory(home)
    state = entry_preview._directory(state)
    profile = entry_preview._directory(profile)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise PrepareError("unified_prepare_port_invalid")
    original, base_report = entry_preview._inventory(project, home)
    blockers = list(base_report["blockers"])
    plan_dir = home / STATE
    if not ignore_preparation and entry_preview._present(plan_dir):
        blockers.append("unified_existing_preparation_requires_review")
    if not ignore_archive_gate:
        from operator_unified_supersede import archive_status
        if archive_status(home)["status"] == "uncertain":
            blockers.append("unified_prepared_archive_requires_review")
        from operator_unified_retire import archive_status as retired_archive_status
        if retired_archive_status(home)["status"] == "uncertain":
            blockers.append("unified_retired_archive_requires_review")
        from operator_unified_failed_archive import archive_status as failed_archive_status
        if failed_archive_status(home)["status"] == "uncertain":
            blockers.append("unified_failed_archive_requires_review")
        from operator_unified_workflow_renew import status as workflow_renewal_status
        if workflow_renewal_status(home)["status"] == "uncertain":
            blockers.append("unified_workflow_renewal_requires_review")
    try:
        web_startup.assert_desktop_closed()
    except Exception:
        blockers.append("unified_desktop_open_or_unknown")

    before = None
    target = home / "config.toml"
    if not target.exists() or target.is_symlink():
        blockers.append("unified_existing_config_required")
    else:
        try:
            before = transaction.observe_config(target)
            if before.data != original:
                raise PrepareError("unified_config_snapshot_changed")
        except Exception:
            blockers.append("unified_config_snapshot_unavailable")

    candidate_bytes = None
    token = None
    try:
        token = entry_preview._read(state / "token", limit=128).decode("ascii").strip()
        if HEX64.fullmatch(token) is None:
            raise PrepareError("unified_router_token_invalid")
        base = f"http://127.0.0.1:{port}/{token}/backend-api/codex"
        candidate_bytes = candidate.render(original, base)[2]
    except Exception:
        blockers.append("unified_candidate_unavailable")

    cache = None
    cache_path = home / "models_cache.json"
    if entry_preview._present(cache_path):
        try:
            cache = transaction._snapshot(cache_path)
        except Exception:
            blockers.append("unified_cache_snapshot_unavailable")

    recovery = project / ".codex/operator-native-recovery/ownership.json"
    try:
        recovery_raw = entry_preview._read(recovery, limit=16384)
        recovery_sha256 = _hash(recovery_raw)
    except Exception:
        recovery_sha256 = None

    old = project / ".codex/operator-web-startup"
    old_artifacts = ("activation.json", "legacy-activation-retirement.json",
                     "legacy-activation-original.json", "legacy-activation-retired.json")
    if any(entry_preview._present(old / name) for name in old_artifacts):
        from operator_web_activation_retire import retirement_status
        retirement = retirement_status(old / "web-startup.json", replacement_home=home)
    else:
        retirement = "absent"
    if retirement == "retired":
        blockers = [value for value in blockers
                    if value != "unified_old_activation_record_requires_review"]
    elif retirement != "absent" and "unified_old_activation_record_requires_review" not in blockers:
        blockers.append("unified_old_activation_record_requires_review")

    startup_bundle = _startup_bundle(project)
    if startup_bundle is None:
        blockers.append("unified_startup_bundle_unverified")

    binding = None
    try:
        current = router.control(state, port)
        diagnostics = current["diagnostics"]
        registry_raw = entry_preview._read(state / "registry.json", limit=1024 * 1024)
        route = web_service.route_preview(profile)
        pid = current["pid"]
        process = web_service.process_identity(pid)
        if (current.get("status") != "ready"
                or current.get("service") != router.service_identity(state)
                or type(pid) is not int or pid <= 0
                or not isinstance(process, dict) or process.get("pid") != pid
                or not isinstance(process.get("birth"), str) or not process["birth"].isdigit()
                or not isinstance(process.get("executable"), str)
                or diagnostics.get("registry_sha256") != _hash(registry_raw)
                or diagnostics.get("web_profile_identity") != router.web_profile_identity(profile)
                or diagnostics.get("web_route_bound") is not True
                or diagnostics.get("web_route_profile_sha256") != route["profile_sha256"]
                or diagnostics.get("web_route_session_sha256") != route["session_sha256"]
                or not isinstance(route, dict)
                or set(route) != {"profile_sha256", "session_sha256"}
                or any(not isinstance(value, str) or HEX64.fullmatch(value) is None
                       for value in route.values())):
            raise PrepareError("unified_router_identity_changed")
        binding = {"state": str(state), "port": port,
                   "token_sha256": _hash(token.encode("ascii")),
                   "service": current["service"], "process": process,
                   "registry_sha256": diagnostics["registry_sha256"],
                   "web_profile": str(profile), "web_profile_identity": diagnostics["web_profile_identity"],
                   "web_route": route}
    except Exception:
        blockers.append("unified_router_service_unverified")

    sources = {name: _hash(path.read_bytes()) for name, path in {
        "renderer": Path(candidate.__file__),
        "preparer": Path(__file__),
        "transaction": Path(transaction.__file__),
        "preview": Path(entry_preview.__file__),
        "router": Path(router.__file__),
        "legacy_retirement": Path(__file__).with_name("operator_web_activation_retire.py"),
        "failed_archive": Path(__file__).with_name("operator_unified_failed_archive.py"),
        "workflow_renewal": Path(__file__).with_name("operator_unified_workflow_renew.py"),
    }.items()}
    current_sha = None if before is None else _hash(before.data)
    candidate_sha = None if candidate_bytes is None else _hash(candidate_bytes)
    review = {"schema_version": 1, "project": str(project), "home": str(home),
              "config_sha256": current_sha,
              "config_identity": None if before is None else _identity(before.identity),
              "candidate_sha256": candidate_sha,
              "cache": {"existed": cache is not None,
                        "sha256": None if cache is None else _hash(cache.data),
                        "identity": None if cache is None else _identity(cache.identity)},
              "recovery_sha256": recovery_sha256, "retirement": retirement,
              "startup_bundle": startup_bundle,
              "router": binding, "source_sha256": sources,
              "blockers": sorted(set(blockers))}
    digest = _hash(_json(review))
    can_prepare = (before is not None and candidate_bytes is not None and binding is not None
                   and not any(value not in REVIEW_BLOCKERS for value in blockers))
    report = {"status": "reviewed_preview" if can_prepare else "blocked",
              "review_sha256": digest, "current_sha256": current_sha,
              "candidate_sha256": candidate_sha, "blockers": review["blockers"],
              "prepare_available": can_prepare, "activation_available": False,
              "configuration_changed": False, "model_requests": 0}
    return Evidence(report, before, candidate_bytes, cache, binding, recovery_sha256,
                    retirement, sources, startup_bundle)


def preview(project: Path, home: Path, router_state: Path, profile: Path, port: int) -> dict:
    """Read current evidence, including future activation blockers, without writes."""
    return _readiness(project, home, router_state, profile, port).report


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _build_plan(project: Path, home: Path, evidence: Evidence, review_sha256: str) -> dict:
    """Use the same exact plan for preflight replay checking and persistence."""
    assert evidence.before is not None and evidence.candidate is not None
    return {"schema_version": 1, "project": str(entry_preview._directory(project)),
            "home": str(entry_preview._directory(home)), "review_sha256": review_sha256,
            "config_sha256": _hash(evidence.before.data),
            "config_identity": _identity(evidence.before.identity),
            "candidate_sha256": _hash(evidence.candidate),
            "cache": {"existed": evidence.cache is not None,
                      "sha256": None if evidence.cache is None else _hash(evidence.cache.data),
                      "identity": None if evidence.cache is None else _identity(evidence.cache.identity)},
            "recovery_sha256": evidence.recovery_sha256,
            "retirement": evidence.retirement, "startup_bundle": evidence.startup_bundle,
            "router": evidence.router_binding,
            "source_sha256": evidence.source_sha256,
            "future_arm_blockers": [value for value in evidence.report["blockers"]
                                    if value in REVIEW_BLOCKERS]}


def prepare(project: Path, home: Path, router_state: Path, profile: Path, port: int,
            expected_review_sha256: str) -> dict:
    """Persist a reviewed plan. Never arm, alter config/cache, or touch Desktop."""
    if not isinstance(expected_review_sha256, str) or HEX64.fullmatch(expected_review_sha256) is None:
        raise PrepareError("unified_review_digest_required")
    first = _readiness(project, home, router_state, profile, port)
    if first.report["review_sha256"] != expected_review_sha256:
        raise PrepareError("unified_review_changed")
    if not first.report["prepare_available"]:
        raise PrepareError("unified_preparation_blocked")
    home = entry_preview._directory(home)
    directory = home / STATE
    if entry_preview._present(directory):
        raise PrepareError("unified_existing_preparation_requires_review")
    planned = _build_plan(project, home, first, expected_review_sha256)
    try:
        from operator_unified_supersede import _assert_unarchived_plan, SupersedeError
        _assert_unarchived_plan(home, _hash(_json(planned)))
    except SupersedeError as exc:
        raise PrepareError(str(exc)) from exc
    with ExitStack() as stack:
        # Bind the reviewed bytes and identities before allocating anything.
        # The transaction helper is already included in source_sha256. Its
        # short Windows read handles deny concurrent writes and replacement;
        # missing cache files remain missing only by explicit rechecks.
        for path, expected in ((home / "config.toml", first.before),
                               (home / "models_cache.json", first.cache)):
            if expected is None:
                candidate._plain(path.parent)
                if entry_preview._present(path):
                    raise PrepareError("unified_review_changed")
                continue
            observed = transaction._snapshot_while_frozen(path, stack)
            if observed.identity != expected.identity or observed.data != expected.data:
                raise PrepareError("unified_review_changed")
        frozen = _readiness(project, home, router_state, profile, port)
        if (frozen.report["review_sha256"] != expected_review_sha256
                or not frozen.report["prepare_available"]
                or _build_plan(project, home, frozen, expected_review_sha256) != planned):
            raise PrepareError("unified_review_changed")
        # This directory is on config's volume, so a future reviewed replacement
        # can use it as the private same-volume transaction parent.
        private_directory(directory)
        with transaction._open(directory, directory=True) as directory_handle:
            if transaction._identity(directory_handle)[0].volume != first.before.identity.volume:
                raise PrepareError("unified_preparation_volume_changed")
        second = _readiness(project, home, router_state, profile, port,
                            ignore_preparation=True)
        if (second.report["review_sha256"] != expected_review_sha256
                or not second.report["prepare_available"]):
            raise PrepareError("unified_review_changed_after_directory_creation")
        assert second.before is not None and second.candidate is not None
        _write_new(directory / "before.toml", second.before.data)
        _write_new(directory / "candidate.toml", second.candidate)
        if second.cache is not None:
            _write_new(directory / "cache-before.bin", second.cache.data)
        plan = _build_plan(project, home, second, expected_review_sha256)
        if plan != planned:
            raise PrepareError("unified_review_changed_after_directory_creation")
        plan_raw = _json(plan)
        _write_new(directory / "plan.json", plan_raw)
        third = _readiness(project, home, router_state, profile, port,
                           ignore_preparation=True)
        if (third.report["review_sha256"] != expected_review_sha256
                or not third.report["prepare_available"]):
            raise PrepareError("unified_review_changed_after_snapshot_write")
        _write_new(directory / "journal.json", _json({"schema_version": 1,
            "phase": "prepared_not_armed", "plan_sha256": _hash(plan_raw)}))
    return {"status": "prepared_not_armed", "plan_sha256": _hash(plan_raw),
            "future_arm_blockers": plan["future_arm_blockers"],
            "configuration_changed": False, "activation_available": False,
            "model_requests": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "prepare"))
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--codex-home", required=True, type=Path)
    parser.add_argument("--router-state", required=True, type=Path)
    parser.add_argument("--web-profile", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--expected-review-sha256")
    args = parser.parse_args()
    try:
        if args.action == "preview":
            if args.expected_review_sha256 is not None:
                parser.error("preview does not take an expected digest")
            result = preview(args.project_root, args.codex_home, args.router_state,
                             args.web_profile, args.port)
        else:
            result = prepare(args.project_root, args.codex_home, args.router_state,
                             args.web_profile, args.port, args.expected_review_sha256)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, PrepareError) else "unified_prepare_unavailable"
        print(json.dumps({"status": "unavailable", "reason": code,
                          "configuration_changed": False,
                          "activation_available": False, "model_requests": 0}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
