"""Reviewed, one-shot release of the native-route-only protection marker.

This transaction only retires the exact recovery marker for a prepared unified
picker plan. It never changes Codex configuration, starts services or Desktop,
or sends a model request. An interrupted attempt is retained for manual review.
"""
from __future__ import annotations

from contextlib import ExitStack
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets

import operator_unified_entry_preview as entry_preview
import operator_unified_prepare as preparation
import operator_web_service as web_service
from operator_core import windows_config_transaction as transaction
from operator_core.web_browser_driver import private_directory


MARKER = "operator-native-route-only"
MARKER_BYTES = b"operator-native-route-only-v1\n"
STATE = "marker-release"
BACKUP = re.compile(r"retired-marker-[a-f0-9]{32}\.bin\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")


class MarkerReleaseError(ValueError):
    """Fixed public failure code with no configuration or credential data."""


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: object) -> bytes:
    return preparation._json(value)


def _read(path: Path, *, limit: int = 16384) -> bytes:
    raw = entry_preview._read(path, limit=limit)
    assert raw is not None
    return raw


def _identity(value: transaction.FileIdentity) -> dict:
    return preparation._identity(value)


def _load_plan(plan_path: Path, *, require_lock: bool = False) -> tuple[dict, bytes, Path]:
    try:
        if not plan_path.is_absolute() or plan_path.name != "plan.json":
            raise ValueError("plan path")
        directory = entry_preview._directory(plan_path.parent)
        if directory.name != preparation.STATE:
            raise ValueError("plan location")
        plan_raw = _read(directory / "plan.json")
        plan = json.loads(plan_raw)
        expected = {"schema_version", "project", "home", "review_sha256",
                    "config_sha256", "config_identity", "candidate_sha256", "cache",
                    "recovery_sha256", "retirement", "startup_bundle", "router",
                    "source_sha256", "future_arm_blockers"}
        if (not isinstance(plan, dict) or set(plan) != expected
                or plan["schema_version"] != 1 or plan["home"] != str(directory.parent)
                or not isinstance(plan["future_arm_blockers"], list)
                or (require_lock and "unified_native_route_lock_active"
                    not in plan["future_arm_blockers"])
                or not isinstance(plan["router"], dict)):
            raise ValueError("plan schema")
        launcher_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
        if entry_preview._directory(launcher_home) != directory.parent:
            raise ValueError("launcher home mismatch")
        journal = json.loads(_read(directory / "journal.json"))
        if journal != {"schema_version": 1, "phase": "prepared_not_armed",
                       "plan_sha256": _hash(plan_raw)}:
            raise ValueError("preparation journal")
        return plan, plan_raw, directory
    except Exception as exc:
        raise MarkerReleaseError("unified_marker_plan_unavailable") from exc


def _selected_entry(plan: dict) -> dict:
    """Check the exact installed entry before removing its native fallback."""
    try:
        project = entry_preview._directory(Path(plan["project"]))
        if project / ".codex/operator-unified-startup" != Path(plan["startup_bundle"]["path"]):
            raise ValueError("bundle path")
        bundle = entry_preview._directory(project / ".codex/operator-desktop-entry")
        config_raw = _read(bundle / "desktop-entry.json")
        build_raw = _read(bundle / "launcher-manifest.json")
        config, build = json.loads(config_raw), json.loads(build_raw)
        script = bundle / "operator_desktop_entry.ps1"
        binary = bundle / "Codex拓展入口.exe"
        source = Path(__file__).resolve().with_name("operator_desktop_entry.ps1")
        script_sha, binary_sha = _hash(_read(script, limit=1024 * 1024)), _hash(_read(binary, limit=1024 * 1024))
        if (config.get("schema_version") != 1 or config.get("mode") != "reviewed_startup"
                or build.get("schema_version") != 1
                or build.get("native_fallback") != "native-only-v1"
                or not isinstance(config.get("startup_bundle"), str)
                or Path(config["startup_bundle"]).is_absolute()
                or (project / config["startup_bundle"]).resolve(strict=True)
                    != Path(plan["startup_bundle"]["path"])
                or script_sha != _hash(_read(source, limit=1024 * 1024))
                or config.get("entry_script_sha256") != script_sha
                or build.get("entry_script_sha256") != script_sha
                or build.get("binary_sha256") != binary_sha):
            raise ValueError("entry changed")
        ownership_hash = entry_preview.verify_owned_entry(project, bundle)
        return {"configuration_sha256": _hash(config_raw),
                "build_sha256": _hash(build_raw), "script_sha256": script_sha,
                "binary_sha256": binary_sha, "ownership_sha256": ownership_hash}
    except Exception as exc:
        raise MarkerReleaseError("unified_marker_entry_unverified") from exc


def _idle_router(plan: dict) -> None:
    """Require the exact prepared process, registry and idle Web route."""
    try:
        binding = plan["router"]
        state = entry_preview._directory(Path(binding["state"]))
        profile = entry_preview._directory(Path(binding["web_profile"]))
        current = preparation.router.control(state, binding["port"])
        diagnostics = current["diagnostics"]
        process = web_service.process_identity(current["pid"])
        registry = _read(state / "registry.json", limit=1024 * 1024)
        route = web_service.route_preview(profile)
        if (current.get("status") != "ready" or current.get("service") != binding["service"]
                or process != binding["process"]
                or diagnostics.get("timing", {}).get("active") != 0
                or _hash(registry) != binding["registry_sha256"]
                or diagnostics.get("registry_sha256") != binding["registry_sha256"]
                or diagnostics.get("web_profile_identity") != binding["web_profile_identity"]
                or diagnostics.get("web_route_bound") is not True
                or diagnostics.get("web_route_profile_sha256") != binding["web_route"]["profile_sha256"]
                or diagnostics.get("web_route_session_sha256") != binding["web_route"]["session_sha256"]
                or route != binding["web_route"]):
            raise ValueError("router changed")
    except Exception as exc:
        raise MarkerReleaseError("unified_marker_router_not_idle_or_changed") from exc


def _preflight(plan: dict, plan_raw: bytes, directory: Path, *, empty_release_dir: bool = False
               ) -> tuple[transaction.ConfigSnapshot, dict, str]:
    """Match the saved prepared evidence while the sole permitted blocker exists."""
    try:
        if any(entry_preview._present(directory / name) for name in
               ("arm.json", "attempt.json", "completion.json")):
            raise ValueError("already attempted")
        release_dir = directory / STATE
        if empty_release_dir:
            if not release_dir.is_dir() or any(release_dir.iterdir()):
                raise ValueError("release directory changed")
        elif entry_preview._present(release_dir):
            raise ValueError("release already attempted")
        router = plan["router"]
        evidence = preparation._readiness(Path(plan["project"]), Path(plan["home"]),
            Path(router["state"]), Path(router["web_profile"]), router["port"],
            ignore_preparation=True)
        if evidence.report["blockers"] != ["unified_native_route_lock_active"]:
            raise ValueError("blockers")
        before = evidence.before
        marker = transaction._snapshot(Path(plan["home"]) / MARKER)
        if marker.data != MARKER_BYTES:
            raise ValueError("marker bytes")
        if before is None or evidence.candidate is None:
            raise ValueError("prepared snapshot")
        expected = {
            "config_sha256": _hash(before.data),
            "config_identity": _identity(before.identity),
            "candidate_sha256": _hash(evidence.candidate),
            "cache": {"existed": evidence.cache is not None,
                      "sha256": None if evidence.cache is None else _hash(evidence.cache.data),
                      "identity": None if evidence.cache is None else _identity(evidence.cache.identity)},
            "recovery_sha256": evidence.recovery_sha256,
            "retirement": evidence.retirement,
            "startup_bundle": evidence.startup_bundle,
            "router": evidence.router_binding,
            "source_sha256": evidence.source_sha256,
        }
        if any(plan[key] != value for key, value in expected.items()):
            raise ValueError("evidence changed")
        if (_read(directory / "before.toml", limit=1024 * 1024) != before.data
                or _read(directory / "candidate.toml", limit=1024 * 1024) != evidence.candidate):
            raise ValueError("prepared copies")
        cache_copy = directory / "cache-before.bin"
        if ((evidence.cache is None and entry_preview._present(cache_copy))
                or (evidence.cache is not None and
                    _read(cache_copy, limit=1024 * 1024) != evidence.cache.data)):
            raise ValueError("cache copy")
        selected = _selected_entry(plan)
        _idle_router(plan)
        review = _hash(_json({"plan_sha256": _hash(plan_raw),
                              "marker_sha256": _hash(marker.data),
                              "marker_identity": _identity(marker.identity),
                              "entry": selected,
                              "release_source_sha256": _hash(Path(__file__).read_bytes())}))
        return marker, selected, review
    except MarkerReleaseError:
        raise
    except Exception as exc:
        raise MarkerReleaseError("unified_marker_preflight_blocked") from exc


def preview(plan_path: Path) -> dict:
    """Read-only digest for the exact prepared, locked, idle environment."""
    plan, plan_raw, directory = _load_plan(plan_path, require_lock=True)
    marker, _, review = _preflight(plan, plan_raw, directory)
    return {"status": "reviewed_preview", "review_sha256": review,
            "marker_sha256": _hash(marker.data), "configuration_changed": False,
            "model_requests": 0}


def release(plan_path: Path, expected_review_sha256: str) -> dict:
    """Retire the exact marker once, retaining its bytes and Windows identity."""
    if not isinstance(expected_review_sha256, str) or HEX64.fullmatch(expected_review_sha256) is None:
        raise MarkerReleaseError("unified_marker_review_required")
    plan, plan_raw, directory = _load_plan(plan_path, require_lock=True)
    release_dir = directory / STATE
    if entry_preview._present(release_dir):
        raise MarkerReleaseError("unified_marker_attempt_requires_review")
    _, _, review = _preflight(plan, plan_raw, directory)
    if review != expected_review_sha256:
        raise MarkerReleaseError("unified_marker_review_changed")
    try:
        private_directory(release_dir)
        marker_path = Path(plan["home"]) / MARKER
        backup_name = "retired-marker-" + secrets.token_hex(16) + ".bin"
        backup = release_dir / backup_name
        with ExitStack() as stack:
            home_handle = stack.enter_context(transaction._open(marker_path.parent, directory=True))
            release_handle = stack.enter_context(transaction._open(release_dir, directory=True))
            marker_handle = stack.enter_context(transaction._open(marker_path))
            original, identity = transaction._read_handle(marker_handle)
            if (original != MARKER_BYTES
                    or transaction._identity(home_handle)[0].volume != identity.volume
                    or transaction._identity(release_handle)[0].volume != identity.volume):
                raise ValueError("marker identity")
            # The repeat review covers config, entry, Desktop and service changes
            # after the private directory was made. Its extra directory is ignored.
            marker, selected, second_review = _preflight(
                plan, plan_raw, directory, empty_release_dir=True)
            if second_review != review or marker.identity != identity or marker.data != original:
                raise ValueError("review changed")
            preparation._write_new(release_dir / "before.bin", original)
            intent = {"schema_version": 1, "phase": "may_have_released",
                      "plan_sha256": _hash(plan_raw), "review_sha256": review,
                      "marker_sha256": _hash(original), "marker_identity": _identity(identity),
                      "backup": backup_name, "entry": selected,
                      "release_source_sha256": _hash(Path(__file__).read_bytes())}
            intent_raw = _json(intent)
            preparation._write_new(release_dir / "intent.json", intent_raw)
            if entry_preview._present(backup):
                raise ValueError("backup appeared")
            # A competing rename can still win the narrow path race. The moved
            # backup identity below then differs and the attempt stays uncertain.
            os.replace(marker_path, backup)
            with ExitStack() as final_stack:
                retired = transaction._snapshot_while_frozen(backup, final_stack)
                if (retired.data != original or retired.identity != identity
                        or entry_preview._present(marker_path)):
                    raise ValueError("rename not witnessed")
                preparation._write_new(release_dir / "receipt.json", _json({
                    "schema_version": 1, "phase": "released_witnessed",
                    "plan_sha256": _hash(plan_raw), "intent_sha256": _hash(intent_raw),
                    "backup_sha256": _hash(original), "backup_identity": _identity(identity)}))
        receipt_sha = verify_release(plan_path, require_released=True)
        return {"status": "released_witnessed", "receipt_sha256": receipt_sha,
                "configuration_changed": False, "model_requests": 0}
    except MarkerReleaseError:
        raise
    except Exception as exc:
        raise MarkerReleaseError("unified_marker_attempt_requires_review") from exc


def verify_release(plan_path: Path, *, require_released: bool) -> str | None:
    """Read-only receipt check for both arming and the one cold-launch consume."""
    try:
        plan, plan_raw, directory = _load_plan(plan_path)
        marker = Path(plan["home"]) / MARKER
        if entry_preview._present(marker):
            raise ValueError("marker exists")
        release_dir = directory / STATE
        if not entry_preview._present(release_dir):
            if require_released:
                raise ValueError("receipt required")
            return None
        if "unified_native_route_lock_active" not in plan["future_arm_blockers"]:
            raise ValueError("release not planned")
        entry_preview._directory(release_dir)
        intent_raw = _read(release_dir / "intent.json")
        receipt_raw = _read(release_dir / "receipt.json")
        intent, receipt = json.loads(intent_raw), json.loads(receipt_raw)
        backup_name = intent["backup"]
        if not isinstance(backup_name, str) or BACKUP.fullmatch(backup_name) is None:
            raise ValueError("backup name")
        if (set(intent) != {"schema_version", "phase", "plan_sha256", "review_sha256",
                            "marker_sha256", "marker_identity", "backup", "entry",
                            "release_source_sha256"}
                or set(receipt) != {"schema_version", "phase", "plan_sha256",
                                    "intent_sha256", "backup_sha256", "backup_identity"}
                or intent["schema_version"] != 1 or intent["phase"] != "may_have_released"
                or receipt["schema_version"] != 1 or receipt["phase"] != "released_witnessed"
                or intent["plan_sha256"] != _hash(plan_raw)
                or receipt["plan_sha256"] != _hash(plan_raw)
                or receipt["intent_sha256"] != _hash(intent_raw)
                or intent["marker_sha256"] != _hash(MARKER_BYTES)
                or receipt["backup_sha256"] != _hash(MARKER_BYTES)
                or intent["marker_identity"] != receipt["backup_identity"]
                or intent["entry"] != _selected_entry(plan)
                or intent["release_source_sha256"] != _hash(Path(__file__).read_bytes())
                or not isinstance(intent["review_sha256"], str)
                or HEX64.fullmatch(intent["review_sha256"]) is None):
            raise ValueError("receipt mismatch")
        original = _read(release_dir / "before.bin")
        retired = transaction._snapshot(release_dir / backup_name)
        if (original != MARKER_BYTES or retired.data != MARKER_BYTES
                or _identity(retired.identity) != intent["marker_identity"]):
            raise ValueError("backup changed")
        return _hash(receipt_raw)
    except Exception as exc:
        raise MarkerReleaseError("unified_marker_release_unverified") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "release", "status"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--expected-review-sha256")
    args = parser.parse_args()
    try:
        if args.action == "preview":
            if args.expected_review_sha256 is not None:
                parser.error("preview does not accept a review digest")
            result = preview(args.plan)
        elif args.action == "release":
            result = release(args.plan, args.expected_review_sha256)
        else:
            if args.expected_review_sha256 is not None:
                parser.error("status does not accept a review digest")
            result = {"status": "released_witnessed" if verify_release(
                args.plan, require_released=True) else "unavailable",
                "configuration_changed": False, "model_requests": 0}
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, MarkerReleaseError) else "unified_marker_release_unavailable"
        print(json.dumps({"status": "unavailable", "reason": code,
                          "configuration_changed": False, "model_requests": 0}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
