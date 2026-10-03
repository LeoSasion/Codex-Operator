"""Opt-in native task registration, separate from business relay/callback state.

The owner grants creation once. Desktop's create_thread tool creates the task;
the Operator records identities. No App Server creation, turns or history reads.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing, contextmanager
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable

from .app_server import AppServerSession

PROFILE_NAME = "user-task-project.json"
DATABASE_NAME = "user-tasks.sqlite3"
RECEIPT_DIR = ".operator/task-receipts"
TASK_ID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
REQUEST_ID = re.compile(r"[a-f0-9]{32}")
SETUP_TIMEOUT = 180


class UserTaskError(RuntimeError):
    """Fixed, non-retrying management failure; never a business result."""


def configure(runtime: Path, grant: dict, *, executable: Path, verifier: Callable | None = None) -> dict:
    """Owner-invoked, stopped configuration; never infer a grant from a message."""
    if ((runtime / "operator.pid").exists() or grant.get("status") != "granted"
            or grant.get("project_registered") is not True
            or grant.get("allow_fixed_relay_task") is not True
            or grant.get("scope") != "authorized_private_users"):
        raise UserTaskError("user_task_configuration_not_authorized_or_stopped")
    for filename, query in (
        ("callbacks.sqlite3", "SELECT COUNT(*) FROM final_callback_requests WHERE state!='closed'"),
        ("state.sqlite3", "SELECT COUNT(*) FROM inbox_events WHERE status NOT IN ('completed','terminal_failed') AND NOT (status='retryable_failed' AND last_error='producer_unavailable_no_retry')"),
    ):
        database = checked_path(runtime / filename)
        if database.exists():
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                if db.execute(query).fetchone()[0]:
                    raise UserTaskError("user_task_configuration_requests_pending")
    keys = ("channel", "app_id", "bot_open_id", "project_id", "project_path",
            "allow_create_project", "allow_create_user_tasks", "allow_reuse_user_tasks")
    profile = {key: grant.get(key) for key in keys}
    relay_record = grant.get("fixed_relay_creation")
    if not isinstance(relay_record, dict) or relay_record.get("status") != "created":
        raise UserTaskError("user_task_fixed_relay_unverified")
    profile["beeper_thread_id"] = relay_record.get("thread_id")
    profile.update(schema_version=1, status="enabled", host_id="local",
                   grant_source_thread_id=grant.get("grant_source_thread_id"), granted_at=grant.get("granted_at"))
    encoded = json.dumps(profile, ensure_ascii=True, separators=(",", ":")).encode()
    if len(encoded) > 16_384:
        raise UserTaskError("user_task_record_too_large")
    path = checked_path(runtime / PROFILE_NAME)
    if path.exists():
        if path.read_bytes() != encoded:
            raise UserTaskError("user_task_existing_grant_requires_review")
        read_profile(runtime)
        return {"enabled": True, "reused": True}
    # Validate before creating anything in the granted project.
    if (any(profile[key] is not True for key in ("allow_create_project", "allow_create_user_tasks", "allow_reuse_user_tasks"))
            or profile["channel"] != "Feishu" or not TASK_ID.fullmatch(str(profile["project_id"]))
            or not TASK_ID.fullmatch(str(profile["beeper_thread_id"]))
            or not re.fullmatch(r"cli_[a-zA-Z0-9]+", str(profile["app_id"]))
            or not re.fullmatch(r"ou_[a-zA-Z0-9]+", str(profile["bot_open_id"]))):
        raise UserTaskError("user_task_grant_invalid")
    project = Path(str(profile["project_path"]))
    if not project.is_absolute() or not project.is_dir():
        raise UserTaskError("user_task_project_unavailable")
    checked_path(project)
    receipts = checked_path(project / RECEIPT_DIR)
    if receipts.exists() and any(receipts.iterdir()):
        raise UserTaskError("user_task_receipts_already_exist")
    existing = grant.get("initial_user_creation")
    binding_digest = None
    if existing is not None:
        if not isinstance(existing, dict) or existing.get("status") != "bound":
            raise UserTaskError("user_task_initial_registration_unverified")
        saved, binding_digest = read_object(runtime / "sessions.json", 1_048_576)
        binding = saved.get("sessions", {}).get(existing.get("scope"))
        if (not isinstance(binding, dict) or binding.get("thread_id") != existing.get("thread_id")
                or binding.get("user_open_id") != existing.get("user_open_id")
                or binding.get("chat_type") != "p2p" or binding.get("host_id", "local") != "local"):
            raise UserTaskError("user_task_initial_binding_changed")
        from types import SimpleNamespace
        config = SimpleNamespace(beeper_thread_id=grant.get("fixed_relay_creation", {}).get("thread_id", ""), app_server_timeout_seconds=20)
        # This only records an existing exact binding; it never selects or
        # rebinds a task. Native list misses must not invalidate owner-reviewed
        # bindings. Later automatic reuse still requires active native metadata.
        (verifier or verify_bound_task)(config, executable, existing["thread_id"], str(project))
        if read_object(runtime / "sessions.json", 1_048_576)[1] != binding_digest:
            raise UserTaskError("user_task_initial_binding_changed")
    receipts.mkdir(parents=True, exist_ok=True)
    store = UserTaskStore(runtime)
    digest = hashlib.sha256(encoded).hexdigest()
    if existing is not None:
        store.seed(profile, digest, existing["user_open_id"], existing["display_name"], existing["scope"], existing["thread_id"])
    # Exclusive creation fails rather than overwriting a concurrent grant. An
    # interrupted initial configuration is retained for reviewed repair.
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    read_profile(runtime)
    return {"enabled": True, "reused": False}


def revoke(runtime: Path) -> dict:
    path = runtime / PROFILE_NAME
    if not path.exists():
        return {"enabled": False, "state": "not_configured"}
    profile, digest = read_object(path, 16_384)
    if profile.get("status") == "revoked":
        return {"enabled": False, "state": "revoked"}
    profile["status"] = "revoked"
    encoded = json.dumps(profile, ensure_ascii=True, separators=(",", ":")).encode()
    if len(encoded) > 16_384:
        raise UserTaskError("user_task_record_too_large")
    original = path.read_bytes()
    if hashlib.sha256(original).hexdigest() != digest:
        raise UserTaskError("user_task_grant_changed")
    backup = path.with_name(path.name + ".before-revocation-" + uuid.uuid4().hex)
    with backup.open("xb") as stream:
        stream.write(original)
    temporary = path.with_name(path.name + ".revoke-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != original:
            raise UserTaskError("user_task_grant_changed")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"enabled": False, "state": "revoked"}


def checked_path(path: Path) -> Path:
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise UserTaskError("user_task_linked_path")
    return path.resolve()


def read_object(path: Path, limit: int) -> tuple[dict, str]:
    checked_path(path)
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise UserTaskError("user_task_record_too_large")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise UserTaskError("user_task_record_invalid") from exc
    if not isinstance(value, dict):
        raise UserTaskError("user_task_record_invalid")
    return value, hashlib.sha256(raw).hexdigest()


def read_profile(runtime: Path) -> tuple[dict, str] | None:
    path = runtime / PROFILE_NAME
    if not path.exists():
        return None
    profile, digest = read_object(path, 16_384)
    if profile.get("status") == "revoked":
        return None
    if (profile.get("schema_version") != 1 or profile.get("status") != "enabled"
            or profile.get("allow_create_project") is not True
            or profile.get("allow_create_user_tasks") is not True
            or profile.get("allow_reuse_user_tasks") is not True
            or profile.get("channel") != "Feishu"
            or profile.get("host_id") != "local"
            or not TASK_ID.fullmatch(str(profile.get("project_id", "")))
            or not TASK_ID.fullmatch(str(profile.get("beeper_thread_id", "")))
            or not re.fullmatch(r"cli_[a-zA-Z0-9]+", str(profile.get("app_id", "")))
            or not re.fullmatch(r"ou_[a-zA-Z0-9]+", str(profile.get("bot_open_id", "")))):
        raise UserTaskError("user_task_grant_invalid")
    root = Path(str(profile.get("project_path", "")))
    if not root.is_absolute() or not root.is_dir():
        raise UserTaskError("user_task_project_unavailable")
    checked_path(root)
    receipts = root / RECEIPT_DIR
    if not receipts.is_dir():
        raise UserTaskError("user_task_receipt_directory_unavailable")
    checked_path(receipts)
    return profile, digest


def user_key(profile: dict, user_id: str) -> str:
    if not re.fullmatch(r"ou_[a-zA-Z0-9]+", user_id):
        raise UserTaskError("user_task_identity_invalid")
    return hashlib.sha256(("feishu\n" + profile["app_id"] + "\n" + user_id).encode()).hexdigest()


def display_title(name: str) -> str:
    name = re.sub(r"[\x00-\x1f\x7f]", " ", str(name)).strip()
    return ("飞书用户" if name.startswith("ou_") else name[:160]) or "飞书用户"


class UserTaskStore:
    def __init__(self, runtime: Path):
        self.runtime = runtime
        self.path = checked_path(runtime / DATABASE_NAME)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS user_tasks (
                user_key TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                grant_digest TEXT NOT NULL, display_name TEXT NOT NULL,
                scope TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL,
                consumed_at REAL, thread_id TEXT, failure_code TEXT)""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=0.1)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, profile: dict, digest: str, user_id: str, name: str, scope: str) -> tuple[dict, bool]:
        key = user_key(profile, user_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM user_tasks WHERE user_key=?", (key,)).fetchone()
            if old is not None:
                return dict(old), False
            if db.execute("SELECT COUNT(*) FROM user_tasks").fetchone()[0] >= 500:
                raise UserTaskError("user_task_registration_capacity")
            request_id = uuid.uuid4().hex
            db.execute("INSERT INTO user_tasks (user_key,request_id,grant_digest,display_name,scope,state,created_at) VALUES (?,?,?,?,?,'queued',?)",
                       (key, request_id, digest, display_title(name), scope, time.time()))
            row = db.execute("SELECT * FROM user_tasks WHERE user_key=?", (key,)).fetchone()
        return dict(row), True

    def get(self, request_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM user_tasks WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def take(self, request_id: str) -> tuple[dict, dict] | None:
        current = read_profile(self.runtime)
        if current is None:
            return None
        profile, digest = current
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM user_tasks WHERE request_id=?", (request_id,)).fetchone()
            if row is None or row["state"] != "queued":
                return None
            if row["grant_digest"] != digest or time.time() - row["created_at"] > SETUP_TIMEOUT:
                db.execute("UPDATE user_tasks SET state='uncertain',failure_code='user_task_grant_or_deadline_changed' WHERE request_id=?", (request_id,))
                return None
            # Commit before returning executable control code. An uncertain
            # creation is never re-reserved or retrieved after process loss.
            db.execute("UPDATE user_tasks SET state='consumed',consumed_at=? WHERE request_id=?", (time.time(), request_id))
        return dict(row), profile

    def ready(self, request_id: str, thread_id: str) -> None:
        if not TASK_ID.fullmatch(thread_id):
            raise UserTaskError("user_task_result_invalid")
        with self.connect() as db:
            changed = db.execute("UPDATE user_tasks SET state='ready',thread_id=? WHERE request_id=? AND state='consumed'", (thread_id, request_id)).rowcount
            if changed != 1:
                raise UserTaskError("user_task_operation_changed")

    def fail(self, request_id: str, reason: str = "user_task_creation_uncertain") -> None:
        with self.connect() as db:
            db.execute("UPDATE user_tasks SET state='uncertain',failure_code=? WHERE request_id=? AND state IN ('queued','consumed')", (reason, request_id))

    def seed(self, profile: dict, digest: str, user_id: str, name: str, scope: str, thread_id: str) -> None:
        """Owner-reviewed registration of an already-created exact native task."""
        if not TASK_ID.fullmatch(thread_id):
            raise UserTaskError("user_task_result_invalid")
        with self.connect() as db:
            db.execute("INSERT INTO user_tasks (user_key,request_id,grant_digest,display_name,scope,state,created_at,thread_id) VALUES (?,?,?,?,?,'ready',?,?)",
                       (user_key(profile, user_id), uuid.uuid4().hex, digest, display_title(name), scope, time.time(), thread_id))


def setup_program(prepared: tuple[dict, dict] | None) -> str:
    if prepared is None:
        return '(async()=>{text({state:"setup_already_consumed_or_closed"});})'
    job, profile = prepared
    request_id = job["request_id"]
    if not REQUEST_ID.fullmatch(request_id):
        raise UserTaskError("user_task_request_invalid")
    arguments = {
        "title": job["display_name"],
        "target": {"type": "project", "projectId": profile["project_id"], "environment": {"type": "local"}},
        "prompt": "The project owner has authorized creating and reusing this native task for one Feishu user. Operator records the exact user/task identity; the title is only a display label. For future relayed user requests with request_id, this native task owns all business work and submits its unchanged final answer with submit_final_callback. This message only initializes the task. Reply 已就绪 and wait; do not send a Feishu message, call Final Callback or do other work now.",
    }
    # Only validated native UUIDs enter the receipt command. User titles and
    # paths stay structured tool arguments, never interpolated shell source.
    command_prefix = (
        "$ErrorActionPreference='Stop'\n"
        "$receiptPath=Join-Path (Get-Location).Path '.operator/task-receipts/" + request_id + ".json'\n"
        "$receiptBytes=[Text.Encoding]::UTF8.GetBytes('"
    )
    command_suffix = (
        "')\n$receiptStream=[IO.File]::Open($receiptPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)\n"
        "try{$receiptStream.Write($receiptBytes,0,$receiptBytes.Length);$receiptStream.Flush($true)}finally{$receiptStream.Dispose()}\n"
        "Write-Output 'Native task receipt saved.'"
    )
    encode = lambda value: json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return (
        "(async()=>{\n"
        'if(!Number.isFinite(Date.now()-started)||Date.now()-started<0||Date.now()-started>2000)throw Error("Setup preparation expired; do not retry");\n'
        'const creators=ALL_TOOLS.filter(t=>t.name.endsWith("__create_thread"));\n'
        'const catalogs=ALL_TOOLS.filter(t=>t.name.endsWith("__list_projects"));\n'
        'const watchers=ALL_TOOLS.filter(t=>t.name.endsWith("__wait_threads"));\n'
        'const writers=ALL_TOOLS.filter(t=>t.name==="exec_command"||t.name.endsWith("__exec_command"));\n'
        'if(creators.length!==1||catalogs.length!==1||watchers.length!==1||writers.length!==1||typeof tools[creators[0].name]!=="function"||typeof tools[catalogs[0].name]!=="function"||typeof tools[watchers[0].name]!=="function"||typeof tools[writers[0].name]!=="function")throw Error("Native setup tools unavailable; do not retry");\n'
        'const catalog=await tools[catalogs[0].name]({});\n'
        'if(catalog.isError)throw Error("Native project unavailable; do not retry");\n'
        'const payloads=[];if(Array.isArray(catalog.structuredContent?.projects))payloads.push(catalog.structuredContent);\n'
        'for(const block of catalog.content||[]){if(block.type==="text"){try{const obj=JSON.parse(block.text);if(Array.isArray(obj?.projects))payloads.push(obj);}catch{}}}\n'
        'if(payloads.length===0)throw Error("Native project result uncertain; do not retry");\n'
        'for(const payload of payloads){const projects=payload.projects.filter(p=>p.projectId===' + encode(profile["project_id"]) + ');\n'
        'if(projects.length!==1||projects[0].hostId!=="local"||projects[0].projectKind!=="local"||projects[0].isGitRepository!==false||projects[0].path!==' + encode(profile["project_path"]) + ')throw Error("Native project changed; do not retry");}\n'
        'const created=await tools[creators[0].name](' + encode(arguments) + ');\n'
        'if(created.isError)throw Error("Native creation failed; do not retry");\n'
        'let candidates=[];if(created.structuredContent?.threadId)candidates.push(created.structuredContent);\n'
        'for(const block of created.content||[]){if(block.type==="text"){try{const obj=JSON.parse(block.text);if(obj?.threadId)candidates.push(obj);}catch{}}}\n'
        'const ids=[...new Set(candidates.map(x=>JSON.stringify([x.threadId,x.hostId])))];\n'
        'if(ids.length!==1)throw Error("Native creation result uncertain; do not retry");\n'
        'const [threadId,hostId]=JSON.parse(ids[0]);\n'
        'if(typeof threadId!=="string"||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(threadId)||hostId!=="local")throw Error("Native creation identity invalid; do not retry");\n'
        'const progress=await tools[watchers[0].name]({targets:[{threadId,hostId}],timeoutMs:0});\n'
        'if(progress.isError)throw Error("Native setup progress unavailable; do not retry");\n'
        'const receipt=JSON.stringify({request_id:' + encode(request_id) + ',thread_id:threadId,host_id:hostId});\n'
        'const saved=await tools[writers[0].name]({cmd:' + encode(command_prefix) + '+receipt+' + encode(command_suffix)
        + ',workdir:' + encode(profile["project_path"]) + ',shell:"pwsh",login:false,max_output_tokens:128});\n'
        'if(saved.exit_code!==0||saved.session_id)throw Error("Native receipt uncertain; do not retry");\n'
        'text({state:"native_task_created_and_recorded",created_thread_directive:"::created-thread{threadId=\\\""+threadId+"\\\"}"});\n'
        '})'
    )


def validate_native_identity(config: Any, result: Any, thread_id: str, project_path: str, *, since: float | None = None) -> None:
    if not TASK_ID.fullmatch(thread_id) or thread_id == config.beeper_thread_id:
        raise UserTaskError("user_task_result_invalid")
    thread = result.get("thread") if isinstance(result, dict) else None
    if (not isinstance(thread, dict) or thread.get("id") != thread_id
            or thread.get("ephemeral") is True or thread.get("turns") not in (None, [])
            or not isinstance(thread.get("cwd"), str)):
        raise UserTaskError("user_task_native_identity_mismatch")
    try:
        same_project = os.path.samefile(thread["cwd"], project_path)
    except OSError as exc:
        raise UserTaskError("user_task_native_identity_mismatch") from exc
    if not same_project:
        raise UserTaskError("user_task_native_identity_mismatch")
    if since is not None:
        created = thread.get("createdAt")
        if type(created) not in (int, float) or not (since - 2 <= created <= time.time() + 2):
            raise UserTaskError("user_task_native_creation_time_mismatch")


def verify_bound_task(config: Any, executable: Path, thread_id: str, project_path: str) -> None:
    """Identity check for owner-reviewed bookkeeping of an unchanged binding."""
    with AppServerSession(executable, config.app_server_timeout_seconds) as api:
        result = api.request("thread/read", {"threadId": thread_id, "includeTurns": False})
    validate_native_identity(config, result, thread_id, project_path)


def native_metadata_path(value: str) -> Path:
    # Native Windows metadata may use a verbatim local drive path. Keep UNC and
    # device namespaces untouched; only this equivalent drive spelling is mapped.
    if os.name == "nt" and re.match(r"^\\\\\?\\[A-Za-z]:\\", value):
        value = value[4:]
    return checked_path(Path(value))


def verify_empty_preview_task(api: AppServerSession, thread: dict) -> None:
    """Confirm one known paginated task omitted by the native preview filter.

    This v5 metadata compatibility check is not a task catalog or history reader.
    The server supplies its home and exact identity; unknown storage layouts fail.
    """
    failure = "user_task_not_confirmed_active"
    if (thread.get("preview") != "" or thread.get("historyMode") != "paginated"
            or thread.get("ephemeral") is not False
            or thread.get("parentThreadId") not in (None, "")
            or thread.get("source") not in ("cli", "vscode", "appServer")
            or type(thread.get("createdAt")) is not int
            or type(thread.get("updatedAt")) is not int):
        raise UserTaskError(failure)
    info = getattr(api, "server_info", None)
    home = info.get("codexHome") if isinstance(info, dict) else None
    if (not isinstance(home, str) or not home or len(home) > 4096
            or not Path(home).is_absolute()
            or os.environ.get("CODEX_SQLITE_HOME", "").strip()):
        raise UserTaskError(failure)
    settings = api.request("config/read", {"includeLayers": False})
    config = settings.get("config") if isinstance(settings, dict) else None
    requirements = api.request("configRequirements/read", {})
    if (not isinstance(config, dict) or "sqlite_home" not in config
            or config["sqlite_home"] is not None
            or not isinstance(requirements, dict) or "requirements" not in requirements):
        raise UserTaskError(failure)
    required = requirements["requirements"]
    if required is not None and (not isinstance(required, dict) or required.get("sqlite_home") is not None):
        raise UserTaskError(failure)
    try:
        root = native_metadata_path(home)
        # A retained older database must never stand in for a newer native store.
        stores = list(islice(root.glob("state_*.sqlite"), 9))
        if len(stores) > 8 or any(not re.fullmatch(r"state_[0-5]\.sqlite", p.name) for p in stores):
            raise UserTaskError(failure)
        database = checked_path(root / "state_5.sqlite")
        if not database.is_file():
            raise UserTaskError(failure)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.2)) as db:
            db.execute("PRAGMA query_only=ON")
            deadline = time.monotonic() + 1
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            db.execute("BEGIN")
            if db.execute("SELECT type FROM sqlite_master WHERE name='threads'").fetchall() != [("table",)]:
                raise UserTaskError(failure)
            columns = {row[1]: row for row in db.execute("PRAGMA table_info(threads)")}
            expected = {"id": "TEXT", "rollout_path": "TEXT", "cwd": "TEXT", "source": "TEXT",
                        "model_provider": "TEXT", "history_mode": "TEXT", "preview": "TEXT",
                        "archived": "INTEGER", "archived_at": "INTEGER", "created_at": "INTEGER",
                        "updated_at": "INTEGER"}
            if (any(name not in columns or columns[name][2].upper() != kind for name, kind in expected.items())
                    or columns["id"][5] != 1 or sum(bool(row[5]) for row in columns.values()) != 1):
                raise UserTaskError(failure)
            row = db.execute("SELECT rollout_path,cwd,source,model_provider,history_mode,"
                             "preview='',archived,archived_at,created_at,updated_at "
                             "FROM threads WHERE id=? LIMIT 1", (thread["id"],)).fetchone()
            if (row is None or row[2:5] != (thread["source"], thread.get("modelProvider"), "paginated")
                    or row[5:8] != (1, 0, None)
                    or row[8:] != (thread["createdAt"], thread["updatedAt"])):
                raise UserTaskError(failure)
            paths = [row[0], row[1], thread.get("path"), thread["cwd"]]
            if any(not isinstance(p, str) or not p or len(p) > 4096 or not Path(p).is_absolute() for p in paths):
                raise UserTaskError(failure)
            rollout, cwd, native_rollout, native_cwd = [native_metadata_path(p) for p in paths]
            if (not rollout.is_relative_to(root / "sessions") or not rollout.is_file()
                    or not os.path.samefile(rollout, native_rollout) or not os.path.samefile(cwd, native_cwd)):
                raise UserTaskError(failure)
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise UserTaskError(failure) from exc


def verify_native_task(config: Any, executable: Path, thread_id: str, project_path: str, *, since: float | None = None) -> None:
    if not TASK_ID.fullmatch(thread_id) or thread_id == config.beeper_thread_id:
        raise UserTaskError("user_task_result_invalid")
    with AppServerSession(executable, config.app_server_timeout_seconds) as api:
        cursor = None
        seen = set()
        active = False
        # A bounded catalog miss is never evidence for creating a replacement.
        for _ in range(10):
            args = {"archived": False, "limit": 100, "useStateDbOnly": True,
                    "modelProviders": [],
                    "sourceKinds": ["cli", "vscode", "appServer"]}
            if cursor:
                args["cursor"] = cursor
            page = api.request("thread/list", args)
            rows = page.get("data") if isinstance(page, dict) else None
            if not isinstance(rows, list):
                raise UserTaskError("user_task_native_read_uncertain")
            if any(isinstance(row, dict) and row.get("id") == thread_id for row in rows):
                active = True
                break
            cursor = page.get("nextCursor")
            if cursor is not None and not isinstance(cursor, str):
                raise UserTaskError("user_task_native_read_uncertain")
            if not cursor:
                break
            if cursor in seen:
                raise UserTaskError("user_task_native_read_uncertain")
            seen.add(cursor)
        else:
            raise UserTaskError("user_task_native_read_uncertain")
        result = api.request("thread/read", {"threadId": thread_id, "includeTurns": False})
        validate_native_identity(config, result, thread_id, project_path, since=since)
        if not active:
            verify_empty_preview_task(api, result["thread"])


class UserTaskManager:
    """One bounded management worker; no business prompt or result is retained."""
    def __init__(self, config: Any, sessions: Any, relay: Any, *, verifier: Callable = verify_native_task):
        self.config, self.sessions, self.relay = config, sessions, relay
        self.verifier = verifier
        self.stop = threading.Event()
        self._lock = threading.Lock()
        self._pending: dict[str, Future] = {}
        self._pool: ThreadPoolExecutor | None = None

    def begin(self, scope: str, session: dict, bot_id: str) -> Future | None:
        if session.get("thread_id") or session.get("chat_type") != "p2p":
            return None
        try:
            current = read_profile(self.config.runtime_dir)
        except OSError as exc:
            raise UserTaskError("user_task_grant_unavailable") from exc
        if current is None:
            return None
        profile, digest = current
        if bot_id != profile["bot_open_id"] or self.config.beeper_thread_id != profile["beeper_thread_id"]:
            raise UserTaskError("user_task_channel_identity_changed")
        key = user_key(profile, str(session.get("user_open_id") or ""))
        with self._lock:
            if self.stop.is_set():
                raise UserTaskError("user_task_manager_stopped")
            existing = self._pending.get(key)
            if existing is not None and not existing.done():
                return existing
            self._pending = {key: future for key, future in self._pending.items() if not future.done()}
            if len(self._pending) >= 32:
                raise UserTaskError("user_task_setup_capacity")
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="native-task-registration")
            future = self._pool.submit(self._ensure, scope, dict(session), profile, digest)
            self._pending[key] = future
            return future

    def _ensure(self, scope: str, session: dict, profile: dict, digest: str) -> dict:
        store, job = None, None
        try:
            store = UserTaskStore(self.config.runtime_dir)
            job, fresh = store.reserve(profile, digest, session["user_open_id"], session.get("name", ""), scope)
            if job["grant_digest"] != digest or job["scope"] != scope:
                raise UserTaskError("user_task_registration_scope_changed")
            current = read_profile(self.config.runtime_dir)
            if self.stop.is_set() or current is None or current[1] != digest:
                raise UserTaskError("user_task_grant_changed")
            if fresh:
                # Persisted before queueing; acceptance, rejection and uncertainty
                # all prohibit another creation attempt for this registration.
                wake = self.relay.queue_user_task_setup(job["request_id"])
                deadline = time.monotonic() + SETUP_TIMEOUT
                receipt_path = Path(profile["project_path"]) / RECEIPT_DIR / (job["request_id"] + ".json")
                while not receipt_path.exists():
                    if callable(wake):
                        wake()
                    if self.stop.wait(0.25) or time.monotonic() >= deadline:
                        raise UserTaskError("user_task_creation_uncertain")
                receipt, _ = read_object(receipt_path, 2048)
                if (set(receipt) != {"request_id", "thread_id", "host_id"}
                        or receipt["request_id"] != job["request_id"] or receipt["host_id"] != "local"
                        or not isinstance(receipt["thread_id"], str)):
                    raise UserTaskError("user_task_receipt_invalid")
                self.verifier(self.config, self.relay.codex_executable, receipt["thread_id"], profile["project_path"], since=job["created_at"])
                store.ready(job["request_id"], receipt["thread_id"])
                job = store.get(job["request_id"])
            elif job["state"] != "ready":
                raise UserTaskError("user_task_previous_creation_uncertain")
            else:
                self.verifier(self.config, self.relay.codex_executable, job["thread_id"], profile["project_path"])
            current = read_profile(self.config.runtime_dir)
            if self.stop.is_set() or current is None or current[1] != digest:
                raise UserTaskError("user_task_grant_changed")
            latest = self.sessions.get(scope)
            if latest.get("user_open_id") != session["user_open_id"] or latest.get("chat_type") != "p2p":
                raise UserTaskError("user_task_session_identity_changed")
            if latest.get("thread_id"):
                return latest  # An explicit concurrent binding for this user wins.
            try:
                return self.sessions.bind_thread_if_current(scope, job["thread_id"], expected_thread_id="",
                    host_id="local", project_id=profile["project_id"], operation_receipt=job["request_id"],
                    expected_user_open_id=session["user_open_id"], expected_chat_type="p2p")
            except ValueError as exc:
                latest = self.sessions.get(scope)
                if latest.get("user_open_id") != session["user_open_id"] or latest.get("chat_type") != "p2p":
                    raise UserTaskError("user_task_session_identity_changed") from exc
                if latest.get("thread_id"):
                    return latest
                raise UserTaskError("user_task_binding_changed") from exc
        except Exception as exc:
            if store is not None and job is not None:
                try:
                    store.fail(job["request_id"])
                except (OSError, sqlite3.Error):
                    # The durable reservation already prevents any fresh queue.
                    pass
            if isinstance(exc, UserTaskError):
                raise
            raise UserTaskError("user_task_creation_uncertain") from exc

    def pending_count(self) -> int:
        with self._lock:
            return sum(not future.done() for future in self._pending.values())

    def close(self) -> None:
        self.stop.set()
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
