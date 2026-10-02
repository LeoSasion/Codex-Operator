"""Disposable-home candidate for one native Codex provider and mixed model picker.

This is deliberately not an installer or a real-home activation path. It changes
only a freshly marked home below the OS temporary directory; the official
route recovery and persistent startup workflows do not yet own this entry.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import tomllib

from operator_core import model_router_config
from operator_core.web_browser_driver import private_directory


LIMIT = 1024 * 1024
PROVIDER = "operator_unified_candidate"
MARKER = "operator-unified-disposable.json"
STATE = "operator-unified-candidate"
TOP_BEGIN = b"# BEGIN OPERATOR UNIFIED CANDIDATE\n"
TOP_END = b"# END OPERATOR UNIFIED CANDIDATE\n"
PROVIDER_BEGIN = b"# BEGIN OPERATOR UNIFIED PROVIDER CANDIDATE\n"
PROVIDER_END = b"# END OPERATOR UNIFIED PROVIDER CANDIDATE\n"
VOICE_KEYS = (model_router_config.VOICE_ROUTE_KEY, model_router_config.VOICE_WS_ROUTE_KEY)
OFFICIAL_VOICE = model_router_config.OFFICIAL_VOICE_BASE_URL
ROUTE = re.compile(r"http://127\.0\.0\.1:(?:[1-9][0-9]{3,4})/[a-f0-9]{64}/backend-api/codex\Z")
INERT_LEGACY = re.compile(
    rb"\A# BEGIN FEISHU OPERATOR MODEL ROUTER\r?\n"
    rb"# [ \t]*openai_base_url[ \t]*=[ \t]*"
    rb'"http://127\.0\.0\.1:([0-9]{1,5})/[a-f0-9]{64}/v1"[ \t]*\r?\n'
    rb"# END FEISHU OPERATOR MODEL ROUTER\r?\n"
)


class CandidateError(ValueError):
    """Fixed public reason; never include configuration or router tokens."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _plain(path: Path) -> None:
    cursor = path.absolute()
    while True:
        if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
            raise CandidateError("candidate_linked_path")
        if cursor == cursor.parent:
            return
        cursor = cursor.parent


def _within(path: Path, root: Path) -> bool:
    try:
        return os.path.normcase(os.path.commonpath((str(path), str(root)))) == os.path.normcase(str(root))
    except ValueError:
        return False


def _reject_protected_home(path: Path) -> None:
    protected = [Path.home() / ".codex"]
    if os.environ.get("CODEX_HOME"):
        protected.append(Path(os.environ["CODEX_HOME"]))
    for value in protected:
        root = value.resolve()
        if path == root or _within(path, root):
            raise CandidateError("candidate_real_home_refused")


def _actual_home(home: Path, *, allow_locked: bool = False) -> Path:
    if not home.is_absolute():
        raise CandidateError("candidate_absolute_home_required")
    _plain(home)
    if not home.is_dir():
        raise CandidateError("candidate_home_missing")
    actual = home.resolve(strict=True)
    temp = Path(tempfile.gettempdir()).resolve(strict=True)
    if actual == temp or not _within(actual, temp) or not actual.name.startswith("operator-unified-candidate-"):
        raise CandidateError("candidate_temp_home_required")
    _reject_protected_home(actual)
    marker = actual / MARKER
    data = _read(marker)
    try:
        identity = json.loads(data)
    except (ValueError, TypeError) as exc:
        raise CandidateError("candidate_marker_invalid") from exc
    if (not isinstance(identity, dict) or set(identity) != {"schema_version", "home", "nonce"}
            or identity["schema_version"] != 1 or identity["home"] != str(actual)
            or not isinstance(identity["nonce"], str)
            or re.fullmatch(r"[a-f0-9]{32}", identity["nonce"]) is None):
        raise CandidateError("candidate_marker_invalid")
    if (not allow_locked and ((actual / "operator-native-route-only").exists()
                              or (actual / "operator-native-route-only").is_symlink())):
        raise CandidateError("candidate_native_route_lock_active")
    return actual


def create_disposable_home(parent: Path | None = None) -> Path:
    """Create an empty test home; no Codex configuration, login or task is copied."""
    temp = Path(tempfile.gettempdir()).resolve(strict=True)
    parent = temp if parent is None else parent
    if not parent.is_absolute():
        raise CandidateError("candidate_absolute_parent_required")
    _plain(parent)
    if not parent.is_dir():
        raise CandidateError("candidate_parent_missing")
    parent = parent.resolve(strict=True)
    if not _within(parent, temp):
        raise CandidateError("candidate_temp_parent_required")
    # Fail before creating anything under the active Codex home.
    _reject_protected_home(parent)
    home = parent / ("operator-unified-candidate-" + secrets.token_hex(16))
    private_directory(home)
    identity = {"schema_version": 1, "home": str(home.resolve(strict=True)),
                "nonce": secrets.token_hex(16)}
    with (home / MARKER).open("xb") as stream:
        stream.write(json.dumps(identity, sort_keys=True).encode())
        stream.flush()
        os.fsync(stream.fileno())
    return _actual_home(home)


def _read(path: Path, *, allow_missing: bool = False) -> bytes | None:
    _plain(path)
    if not path.exists():
        if allow_missing:
            return None
        raise CandidateError("candidate_file_missing")
    if not path.is_file() or path.stat().st_nlink != 1:
        raise CandidateError("candidate_regular_file_required")
    with path.open("rb") as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise CandidateError("candidate_file_too_large")
    return data


def _parse(raw: bytes) -> dict:
    try:
        value = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise CandidateError("candidate_invalid_toml") from exc
    if not isinstance(value, dict):
        raise CandidateError("candidate_invalid_toml")
    return value


def _base(base: str) -> str:
    if (not isinstance(base, str) or ROUTE.fullmatch(base) is None
            or not 1024 <= int(base.split(":", 2)[2].split("/", 1)[0]) <= 65535):
        raise CandidateError("candidate_exact_loopback_route_required")
    return base


def _provider(base: str) -> dict:
    # In Codex 0.158, the OpenAI name enables remote compaction v2 for the
    # entire provider, including external rows. Use the official client's text
    # compaction path; never synthesize encrypted compaction in the router.
    return {"name": "Codex Operator", "base_url": base, "model_catalog_url": base + "/models",
            "wire_api": "responses", "requires_openai_auth": True,
            "request_max_retries": 0, "stream_max_retries": 0,
            "supports_websockets": False, "supports_standalone_web_search": True}


def _scope(before: bytes, candidate: bytes, provider: dict, voice_added: tuple[str, ...]) -> None:
    original = _parse(before)
    parsed = _parse(candidate)
    expected = deepcopy(original)
    expected["model_provider"] = PROVIDER
    for key in voice_added:
        expected[key] = OFFICIAL_VOICE
    expected.setdefault("model_providers", {})[PROVIDER] = provider
    if parsed != expected:
        raise CandidateError("candidate_scope_changed")


def render(before: bytes, base: str) -> tuple[bytes, bytes, bytes]:
    """Pure, exact TOML candidate; never reads or writes a real Codex home."""
    base = _base(base)
    if before.startswith(b"\xef\xbb\xbf") or len(before) > LIMIT:
        raise CandidateError("candidate_original_format_conflict")
    # The one exact leading, wholly commented legacy loopback block is inert
    # user history. Keep its bytes in place; all other markers remain conflicts.
    inert = INERT_LEGACY.match(before)
    inspected = (before[inert.end():] if inert and 1024 <= int(inert[1]) <= 65535
                 else before)
    if any(marker.strip() in inspected for marker in (
            TOP_BEGIN, TOP_END, PROVIDER_BEGIN, PROVIDER_END,
            model_router_config.BEGIN.encode(), model_router_config.END.encode())):
        raise CandidateError("candidate_existing_managed_block")
    original = _parse(before)
    if (any(key in original for key in ("model_provider", "openai_base_url", "profile", "model_catalog_json"))
            or os.environ.get("OPENAI_BASE_URL")):
        raise CandidateError("candidate_existing_route_conflict")
    providers = original.get("model_providers", {})
    if not isinstance(providers, dict) or PROVIDER in providers:
        raise CandidateError("candidate_provider_collision")
    voice_added = []
    for key in VOICE_KEYS:
        if key in original and original[key] != OFFICIAL_VOICE:
            raise CandidateError("candidate_voice_route_conflict")
        if key not in original:
            voice_added.append(key)
    prefix = TOP_BEGIN + b'model_provider = "' + PROVIDER.encode() + b'"\n'
    for key in voice_added:
        prefix += (key + " = " + json.dumps(OFFICIAL_VOICE) + "\n").encode()
    prefix += TOP_END
    provider = _provider(base)
    suffix = b"\n" + PROVIDER_BEGIN + ("[model_providers." + PROVIDER + "]\n").encode()
    for key, value in provider.items():
        suffix += (key + " = " + json.dumps(value) + "\n").encode()
    suffix += PROVIDER_END
    candidate = prefix + before + suffix
    if len(candidate) > LIMIT:
        raise CandidateError("candidate_config_too_large")
    _scope(before, candidate, provider, tuple(voice_added))
    return prefix, suffix, candidate


def preview(home: Path, base: str) -> dict:
    home = _actual_home(home)
    before = _read(home / "config.toml", allow_missing=True)
    raw = b"" if before is None else before
    _, _, candidate = render(raw, base)
    return {"status": "preview", "configuration_changed": False,
            "original_sha256": digest(raw), "candidate_sha256": digest(candidate),
            "provider": PROVIDER, "real_home_supported": False}


def _write_exclusive(path: Path, data: bytes) -> None:
    _plain(path)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _journal(state: Path, phase: str, **extra) -> None:
    _atomic_write(state / "journal.json", json.dumps({"phase": phase, **extra}, sort_keys=True).encode(),
                  expected=_read(state / "journal.json", allow_missing=True))


def _atomic_write(path: Path, replacement: bytes, *, expected: bytes | None) -> None:
    _plain(path)
    if _read(path, allow_missing=True) != expected:
        raise CandidateError("candidate_snapshot_changed")
    fd, name = tempfile.mkstemp(prefix=".operator-unified-", dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        if _read(path, allow_missing=True) != expected:
            raise CandidateError("candidate_snapshot_changed")
        os.replace(pending, path)
    finally:
        if pending.exists():
            pending.unlink()


def prepare(home: Path, base: str) -> dict:
    """Save a reviewable plan inside a disposable home, without changing config."""
    home = _actual_home(home)
    state = home / STATE
    if state.exists() or state.is_symlink():
        raise CandidateError("candidate_existing_plan_requires_review")
    before = _read(home / "config.toml", allow_missing=True)
    raw = b"" if before is None else before
    prefix, suffix, candidate = render(raw, base)
    private_directory(state)
    files = {"before.toml": raw, "prefix.bin": prefix, "suffix.bin": suffix,
             "candidate.toml": candidate}
    for name, value in files.items():
        _write_exclusive(state / name, value)
    plan = {"schema_version": 1, "home": str(home), "config_existed": before is not None,
            "source_sha256": digest(Path(__file__).read_bytes()),
            "files": {name: digest(value) for name, value in files.items()}}
    _write_exclusive(state / "plan.json", json.dumps(plan, sort_keys=True).encode())
    _journal(state, "prepared")
    return {"status": "prepared", "configuration_changed": False,
            "provider": PROVIDER, "candidate_sha256": digest(candidate), "real_home_supported": False}


def _load(home: Path, *, allow_locked: bool = False) -> tuple[Path, dict, dict[str, bytes], dict]:
    home = _actual_home(home, allow_locked=allow_locked)
    state = home / STATE
    _plain(state)
    if not state.is_dir():
        raise CandidateError("candidate_plan_missing")
    try:
        plan = json.loads(_read(state / "plan.json"))
        journal = json.loads(_read(state / "journal.json"))
    except (ValueError, TypeError) as exc:
        raise CandidateError("candidate_plan_invalid") from exc
    names = {"before.toml", "prefix.bin", "suffix.bin", "candidate.toml"}
    if (not isinstance(plan, dict)
            or set(plan) != {"schema_version", "home", "config_existed", "source_sha256", "files"}
            or plan["schema_version"] != 1 or plan["home"] != str(home)
            or type(plan["config_existed"]) is not bool
            or not isinstance(plan["files"], dict) or set(plan["files"]) != names
            or not isinstance(journal, dict) or journal.get("phase") not in
               {"prepared", "applying", "active", "reverting", "reverted"}):
        raise CandidateError("candidate_plan_invalid")
    files = {name: _read(state / name) for name in names}
    if (any(digest(value) != plan["files"][name] for name, value in files.items())
            or files["candidate.toml"] != files["prefix.bin"] + files["before.toml"] + files["suffix.bin"]
            or not files["prefix.bin"].startswith(TOP_BEGIN)
            or not files["prefix.bin"].endswith(TOP_END)
            or not files["suffix.bin"].startswith(b"\n" + PROVIDER_BEGIN)
            or not files["suffix.bin"].endswith(PROVIDER_END)
            or not isinstance(plan["source_sha256"], str)
            or re.fullmatch(r"[a-f0-9]{64}", plan["source_sha256"]) is None):
        raise CandidateError("candidate_plan_invalid")
    try:
        original = _parse(files["before.toml"])
        installed = _parse(files["candidate.toml"])
        provider = installed["model_providers"][PROVIDER]
        expected = _provider(_base(provider["base_url"]))
        # Retained older transactions must still be inspectable/recoverable.
        # This does not permit modifying their saved or installed bytes.
        if provider not in (expected, {**expected, "name": "OpenAI"}):
            raise CandidateError("candidate_plan_invalid")
        _scope(files["before.toml"], files["candidate.toml"], provider,
               tuple(key for key in VOICE_KEYS if key not in original))
    except (KeyError, TypeError, CandidateError) as exc:
        raise CandidateError("candidate_plan_invalid") from exc
    return state, plan, files, journal


def _config_matches(home: Path, expected: bytes, existed: bool) -> None:
    current = _read(home / "config.toml", allow_missing=True)
    if (current is not None) != existed or (b"" if current is None else current) != expected:
        raise CandidateError("candidate_config_changed")


@contextmanager
def _exclusive_transaction(state: Path):
    _plain(state)
    if not state.is_dir():
        raise CandidateError("candidate_plan_missing")
    lock = state / "transaction.lock"
    _plain(lock)
    try:
        with lock.open("xb") as stream:
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise CandidateError("candidate_transaction_locked") from exc
    try:
        yield
    finally:
        lock.unlink()


def apply(home: Path) -> dict:
    """Switch only a disposable home; uncertain phases are never retried."""
    home = _actual_home(home)
    with _exclusive_transaction(home / STATE):
        return _apply_locked(home)


def _apply_locked(home: Path) -> dict:
    state, plan, files, journal = _load(home)
    if journal != {"phase": "prepared"}:
        raise CandidateError("candidate_transaction_requires_review")
    if digest(Path(__file__).read_bytes()) != plan["source_sha256"]:
        raise CandidateError("candidate_source_changed")
    _config_matches(home, files["before.toml"], plan["config_existed"])
    cache = home / "models_cache.json"
    cache_raw = _read(cache, allow_missing=True)
    _journal(state, "applying", cache_existed=cache_raw is not None,
             cache_sha256=digest(cache_raw) if cache_raw is not None else None)
    if cache_raw is not None:
        _write_exclusive(state / "cache-before.bin", cache_raw)
    if cache_raw is not None:
        if _read(cache) != cache_raw:
            raise CandidateError("candidate_cache_changed")
        os.replace(cache, state / "cache-retired.bin")
    _atomic_write(home / "config.toml", files["candidate.toml"],
                  expected=files["before.toml"] if plan["config_existed"] else None)
    _config_matches(home, files["candidate.toml"], True)
    if _read(cache, allow_missing=True) is not None:
        raise CandidateError("candidate_cache_changed")
    _journal(state, "active", cache_existed=cache_raw is not None,
             cache_sha256=digest(cache_raw) if cache_raw is not None else None)
    return {"status": "active", "configuration_changed": True, "provider": PROVIDER,
            "real_home_supported": False}


def _remove_owned(current: bytes, files: dict[str, bytes]) -> bytes:
    prefix, suffix = files["prefix.bin"], files["suffix.bin"]
    if (not current.startswith(prefix) or current.count(TOP_BEGIN) != 1
            or current.count(TOP_END) != 1 or current.count(PROVIDER_BEGIN) != 1
            or current.count(PROVIDER_END) != 1 or current.count(suffix) != 1):
        raise CandidateError("candidate_owned_bytes_changed")
    body = current[len(prefix):]
    position = body.find(suffix)
    if position < 0:
        raise CandidateError("candidate_owned_bytes_changed")
    remaining = body[:position] + body[position + len(suffix):]
    original = _parse(files["before.toml"])
    installed = _parse(files["candidate.toml"])
    expected = deepcopy(_parse(remaining))
    for key in ("model_provider", *VOICE_KEYS):
        if key not in original:
            if key in expected:
                raise CandidateError("candidate_owned_scope_changed")
            expected[key] = installed[key]
    providers = expected.setdefault("model_providers", {})
    if not isinstance(providers, dict) or PROVIDER in providers:
        raise CandidateError("candidate_owned_scope_changed")
    providers[PROVIDER] = installed["model_providers"][PROVIDER]
    if _parse(current) != expected:
        raise CandidateError("candidate_owned_scope_changed")
    return remaining


def revert(home: Path) -> dict:
    """Explicit exact rollback, retaining unrelated later TOML edits."""
    home = _actual_home(home, allow_locked=True)
    with _exclusive_transaction(home / STATE):
        return _revert_locked(home)


def _revert_locked(home: Path) -> dict:
    state, plan, files, journal = _load(home, allow_locked=True)
    if journal.get("phase") != "active":
        raise CandidateError("candidate_transaction_requires_review")
    current = _read(home / "config.toml")
    remaining = _remove_owned(current, files)
    cache = home / "models_cache.json"
    cache_raw = _read(cache, allow_missing=True)
    _journal(state, "reverting", remaining_sha256=digest(remaining),
             cache_existed=cache_raw is not None)
    _write_exclusive(state / "before-revert.toml", current)
    if cache_raw is not None:
        _write_exclusive(state / "cache-after.bin", cache_raw)
    if cache_raw is not None:
        if _read(cache) != cache_raw:
            raise CandidateError("candidate_cache_changed")
        os.replace(cache, state / "cache-after-retired.bin")
    _atomic_write(home / "config.toml", remaining, expected=current)
    _config_matches(home, remaining, True)
    if not plan["config_existed"] and remaining == b"":
        _config_matches(home, b"", True)
        (home / "config.toml").unlink()
    if _read(cache, allow_missing=True) is not None:
        raise CandidateError("candidate_cache_changed")
    _journal(state, "reverted", remaining_sha256=digest(remaining))
    return {"status": "reverted", "configuration_changed": True,
            "original_absence_restored": not plan["config_existed"] and remaining == b"",
            "real_home_supported": False}


def status(home: Path) -> dict:
    home = _actual_home(home, allow_locked=True)
    _, _, files, journal = _load(home, allow_locked=True)
    raw = _read(home / "config.toml", allow_missing=True)
    current = b"" if raw is None else raw
    exact = current == files["candidate.toml"] if journal["phase"] == "active" else None
    return {"status": journal["phase"], "configuration_matches_original_candidate": exact,
            "real_home_supported": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create-home", "preview", "prepare", "apply", "revert", "status"))
    parser.add_argument("--home", type=Path)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--router-state", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    try:
        if args.action == "create-home":
            result = {"status": "created", "home": str(create_disposable_home(args.parent))}
        else:
            if args.home is None:
                parser.error("--home is required")
            if args.action in {"preview", "prepare"}:
                if args.router_state is None or args.port is None:
                    parser.error("--router-state and --port are required")
                _actual_home(args.home)
                upstream = model_router_config.url(args.router_state, args.port)
                base = upstream.removesuffix("/v1") + "/backend-api/codex"
                result = preview(args.home, base) if args.action == "preview" else prepare(args.home, base)
            else:
                result = {"apply": apply, "revert": revert, "status": status}[args.action](args.home)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (CandidateError, OSError, ValueError) as exc:
        code = str(exc) if isinstance(exc, CandidateError) else "candidate_unavailable"
        # A failed write may have passed its replacement boundary. The journal
        # retains that uncertainty; the CLI must not promise unchanged config.
        changed = None if args.action in {"apply", "revert"} else False
        print(json.dumps({"status": "unavailable", "reason": code,
                          "configuration_changed": changed}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
