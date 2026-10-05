"""Explicit bounded live CLI evaluation in disposable state. Never an answer transport."""

import argparse
import asyncio
from copy import deepcopy
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time

from operator_core.app_server import AppServerSession
from operator_core.model_registry import ModelRegistry, RouterError
from operator_core.model_router_config import atomic_write, read_registration
from operator_core.responses_profiles import adapter_digest, contract_digest, evaluator_digest, preflight
from operator_core.responses_profiles import FINAL_TEXT_POLICIES, valid_cli_version
from operator_core.responses_tool_adapter import dumps
from operator_responses_probe import reserve_receipt
from operator_terminal_fixture import (TERMINAL_CASES, TerminalFixture, executable_digest,
                                       terminal_sandbox_settings)

STOP_CASES = frozenset({"cli_error_stop", "cli_exit_stop"})
CASES = ("cli_nested", "cli_multiround", "cli_tool_error", "cli_error_stop", "cli_exit_stop",
         "cli_patchplan", "cli_workspace", "cli_cancel", *TERMINAL_CASES)
SOURCE = '# Synthetic currency helper — preserve this comment.\r\ndef cents(amount):\r\n    return round(amount * 10)\r\n'
EXPECTED = SOURCE.replace('amount * 10)', 'amount * 100)')

# Separate opt-in acceptance transport. The existing never/read-only evaluator
# and CASES above do not enter this lane. These bounds include owner wait time.
NATIVE_RPC_BYTES = 16 * 1024 * 1024
NATIVE_RPC_TIMEOUT_SECONDS = 120
NATIVE_APPROVAL_METHODS = frozenset({"item/commandExecution/requestApproval",
                                     "item/fileChange/requestApproval"})
NATIVE_APPROVAL_CONTRACT_0160 = "native_0160_single_action_v1"


def _native_rpc_id(value):
    try:
        return ((isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 512)
                or (type(value) is int and -(2 ** 63) <= value < 2 ** 63))
    except UnicodeError:
        return False


def _native_rpc_object(raw):
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > NATIVE_RPC_BYTES:
        raise RouterError("native_fixture_invalid_rpc")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RouterError("native_fixture_duplicate_json_key")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise RouterError("native_fixture_invalid_rpc") from exc
    if not isinstance(value, dict) or value.get("jsonrpc", "2.0") != "2.0":
        raise RouterError("native_fixture_invalid_rpc")
    return value


class NativeApprovalGate:
    """One observed single-action RPC; an explicit owner reply is still required.

    A fresh random ticket binds the complete received bytes, exact ID type and
    action identity. It is not approval evidence until the transport writes the
    corresponding reply. Session grants/amendments and subcommand callbacks are
    outside this acceptance contract. Timeout never supplies a denial decision.
    """
    def __init__(self, raw, *, thread_id, turn_id, command=None, cwd=None,
                 approval_contract=None, command_argv=None):
        if approval_contract not in (None, NATIVE_APPROVAL_CONTRACT_0160):
            raise RouterError("native_fixture_approval_contract_rejected")
        request = _native_rpc_object(raw)
        params = request.get("params")
        if (not isinstance(request.get("method"), str) or request["method"] not in NATIVE_APPROVAL_METHODS
                or not _native_rpc_id(request.get("id")) or not isinstance(params, dict)
                or params.get("threadId") != thread_id or params.get("turnId") != turn_id
                or not all(isinstance(params.get(key), str) and params[key]
                           for key in ("threadId", "turnId", "itemId"))
                or type(params.get("startedAtMs")) is not int
                or not 0 <= params["startedAtMs"] < 2 ** 63):
            raise RouterError("native_fixture_approval_identity_rejected")
        if request["method"] == "item/commandExecution/requestApproval":
            if (params.get("approvalId") is not None or params.get("kind", "command") != "command"
                    or any(params.get(key) is not None for key in ("additionalPermissions", "networkApprovalContext",
                        "proposedNetworkPolicyAmendments"))
                    or not isinstance(command, str) or not command or not isinstance(cwd, str) or not cwd
                    or params.get("command") != command or params.get("cwd") != cwd):
                raise RouterError("native_fixture_approval_scope_rejected")
            if approval_contract == NATIVE_APPROVAL_CONTRACT_0160:
                # CLI 0.160.0 / a956835d: a proposal is inert request metadata.
                # Its argv comes from the separately constrained source call,
                # never by parsing/reconstructing the native display command.
                known = {"kind", "threadId", "turnId", "itemId", "startedAtMs", "approvalId",
                         "environmentId", "reason", "networkApprovalContext", "command", "cwd",
                         "commandActions", "additionalPermissions", "proposedExecpolicyAmendment",
                         "proposedNetworkPolicyAmendments", "availableDecisions"}
                proposal, offered = params.get("proposedExecpolicyAmendment"), params.get("availableDecisions")
                if set(params) - known or params.get("environmentId") != "local":
                    raise RouterError("native_fixture_approval_scope_rejected")
                if proposal is not None:
                    if (not isinstance(command_argv, list) or not command_argv
                            or not all(isinstance(part, str) and part and "\x00" not in part for part in command_argv)
                            or proposal != command_argv):
                        raise RouterError("native_fixture_approval_scope_rejected")
                    try:
                        for part in command_argv:
                            part.encode("utf-8", errors="strict")
                    except UnicodeError as exc:
                        raise RouterError("native_fixture_approval_scope_rejected") from exc
                    expected_offered = ["accept", {"acceptWithExecpolicyAmendment": {
                        "execpolicy_amendment": command_argv}}, "cancel"]
                else:
                    expected_offered = ["accept", "cancel"]
                if offered is None and proposal is None:
                    decisions = frozenset({"accept", "decline"})  # Unadvertised legacy request.
                elif offered == expected_offered:
                    decisions = frozenset({"accept", "cancel"})
                else:
                    raise RouterError("native_fixture_approval_scope_rejected")
            elif params.get("proposedExecpolicyAmendment") is not None or command_argv is not None:
                raise RouterError("native_fixture_approval_scope_rejected")
            else:
                decisions = frozenset({"accept", "decline"})
        elif params.get("grantRoot") is not None:
            raise RouterError("native_fixture_approval_scope_rejected")
        else:
            decisions = frozenset({"accept", "decline"})
        self.approval_contract = approval_contract
        self._decisions = decisions
        self.request = deepcopy(request)
        self.raw = bytes(raw)
        self.nonce = secrets.token_hex(16)
        self.used = False

    def ticket(self):
        params = self.request["params"]
        return {"nonce": self.nonce, "request_sha256": hashlib.sha256(self.raw).hexdigest(),
                "id": self.request["id"], **{key: params[key] for key in ("threadId", "turnId", "itemId")}}

    def response(self, owner_decision):
        ticket = self.ticket()
        if (self.used or not isinstance(owner_decision, dict)
                or set(owner_decision) != set(ticket) | {"decision"}
                or type(owner_decision.get("id")) is not type(ticket["id"])
                or any(owner_decision.get(key) != value for key, value in ticket.items())
                or not isinstance(owner_decision.get("decision"), str)
                or owner_decision["decision"] not in self._decisions):
            raise RouterError("native_fixture_owner_decision_rejected")
        self.used = True
        return {"jsonrpc": "2.0", "id": self.request["id"],
                "result": {"decision": owner_decision["decision"]}}


class NativeApprovalCapture(AppServerSession):
    """Fixture-only binary App Server transport with complete bounded raw logs.

    Launch and thread parameters enforce a private read-only/untrusted lane.
    The caller must separately constrain the model's exact tool source and
    inspect actual terminal/file evidence; this transport never attests to it.
    Raw artifacts are private, not public diagnostics. No server request is
    answered automatically. Reaching the fixed deadline only fails the lane;
    the controller must interrupt its exact turn and retain failure evidence.
    """
    def __init__(self, executable, home, work, capture_root, *, model, provider,
                 timeout_seconds=NATIVE_RPC_TIMEOUT_SECONDS, approval_contract=None):
        self._error_type = RouterError
        self.home, self.work, self.capture_root = map(Path, (home, work, capture_root))
        if (approval_contract not in (None, NATIVE_APPROVAL_CONTRACT_0160)
                or type(timeout_seconds) is not int or not 0 < timeout_seconds <= NATIVE_RPC_TIMEOUT_SECONDS
                or not all(path.is_absolute() and path.is_dir() and not path.is_symlink()
                           for path in (self.home, self.work, self.capture_root))
                or len({path.resolve() for path in (self.home, self.work, self.capture_root)}) != 3
                or not all(isinstance(value, str) and value for value in (model, provider))):
            raise RouterError("native_fixture_configuration_rejected")
        self.model, self.provider = model, provider
        self.approval_contract = approval_contract
        self.timeout_seconds = timeout_seconds
        self.deadline = time.monotonic() + timeout_seconds
        self._next_id = 1
        self._messages = queue.Queue()
        self._deferred = []
        self._observed = {}
        self._lock = threading.Lock()
        self._total_bytes = 0
        self._capture_failed = False
        self._write_pending = False
        self._cleanup_deadline = None
        self._interrupt_attempted = False
        self._admission_closed = False
        self._cleanup_write_active = False
        self._thread_id = self._turn_id = None
        self._start_attempted = {"thread/start": False, "turn/start": False}
        self._streams = {}
        self._handles = {}
        try:
            for name in ("server", "client", "stderr"):
                self._handles[name] = (self.capture_root / (name + ".raw")).open("xb")
                self._streams[name] = {"bytes": 0, "sha256_state": hashlib.sha256(), "complete": False}
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            # App Server 0.160 rejects untrusted in public startup config.
            # Bootstrap without a turn under never/read-only; thread/start must
            # explicitly select internal untrusted and pass the actual echo gate
            # before this fixture can send any turn. This is not a policy fallback.
            settings = {"approval_policy": "never", "approvals_reviewer": "user",
                        "sandbox_mode": "read-only", "analytics.enabled": False,
                        "skills.include_instructions": False, "project_doc_max_bytes": 0,
                        "features.plugins": False, "features.remote_plugin": False,
                        "features.view_image": False, "features.image_generation": False,
                        "features.goals": False, "features.multi_agent": False,
                        "features.multi_agent_v2": False, "web_search": "disabled"}
            command = [str(executable), "app-server", "--listen", "stdio://"]
            for key, value in settings.items():
                command += ["-c", key + "=" + dumps(value)]
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                env=isolated_environment(self.home), cwd=str(self.work), creationflags=flags)
        except Exception as exc:
            for handle in self._handles.values():
                try:
                    handle.close()
                except OSError:
                    pass
            raise RouterError("native_fixture_launch_failed") from exc
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        try:
            self._reader.start()
            self._stderr_reader.start()
        except Exception as exc:
            self._capture_failed = True
            report = self.close()
            try:
                with (self.capture_root / "reader-start-failure.json").open("xb") as handle:
                    handle.write((dumps({"state": "failed", "reason": "native_fixture_reader_start_failed",
                                         "cleanup": report}) + "\n").encode("utf-8"))
            except OSError:
                pass
            raise RouterError("native_fixture_reader_start_failed") from exc

    def _retain(self, stream, raw):
        with self._lock:
            if self._capture_failed or self._total_bytes + len(raw) > NATIVE_RPC_BYTES:
                self._capture_failed = True
                raise RouterError("native_fixture_capture_too_large")
            self._handles[stream].write(raw)
            self._handles[stream].flush()
            self._total_bytes += len(raw)
            self._streams[stream]["bytes"] += len(raw)
            self._streams[stream]["sha256_state"].update(raw)

    def _read(self):
        try:
            while raw := self.process.stdout.readline(NATIVE_RPC_BYTES + 1):
                self._retain("server", raw)
                if not raw.endswith(b"\n"):
                    raise RouterError("native_fixture_incomplete_rpc")
                message = _native_rpc_object(raw)
                if "method" in message and "id" in message:
                    if not _native_rpc_id(message["id"]):
                        raise RouterError("native_fixture_invalid_rpc_id")
                    key = (type(message["id"]), message["id"])
                    if key in self._observed:
                        raise RouterError("native_fixture_duplicate_server_request")
                    self._observed[key] = raw
                self._messages.put(message)
            self._streams["server"]["complete"] = True
        except Exception:
            self._capture_failed = True
            self._messages.put(RouterError("native_fixture_server_capture_failed"))
        finally:
            self._messages.put(None)

    def _read_stderr(self):
        try:
            while raw := self.process.stderr.read(65536):
                self._retain("stderr", raw)
            self._streams["stderr"]["complete"] = True
        except Exception:
            self._capture_failed = True
            self._messages.put(RouterError("native_fixture_stderr_capture_failed"))

    def _write(self, message):
        if ((self._admission_closed and not self._cleanup_write_active)
                or time.monotonic() >= self.deadline or self.process.poll() is not None
                or self._write_pending or self._capture_failed):
            raise RouterError("native_fixture_transport_unavailable")
        raw = (dumps(message) + "\n").encode("utf-8")
        self._retain("client", raw)  # Attempted source bytes; completion is separate.
        result, completed = [], threading.Event()
        self._write_pending = True
        def write():
            try:
                if self.process.stdin.write(raw) != len(raw):
                    raise OSError()
                self.process.stdin.flush()
            except Exception:
                result.append(False)
            else:
                result.append(True)
            finally:
                self._write_pending = False
                completed.set()
        threading.Thread(target=write, daemon=True).start()
        if not completed.wait(max(0, self.deadline - time.monotonic())) or not result or not result[0]:
            self._capture_failed = True
            raise RouterError("native_fixture_rpc_write_incomplete")

    def notify(self, method, params=None):
        if method != "initialized" or params is not None:
            raise RouterError("native_fixture_method_rejected")
        super().notify(method, params)

    def _validate_request(self, method, params):
        if self._admission_closed and not (self._cleanup_write_active and method == "turn/interrupt"):
            raise RouterError("native_fixture_admission_closed")
        if method == "initialize" and self._thread_id is None:
            return
        if method == "thread/start" and self._thread_id is None and not self._start_attempted[method]:
            required = {"model": self.model, "modelProvider": self.provider, "cwd": str(self.work),
                        "approvalPolicy": "untrusted", "approvalsReviewer": "user",
                        "sandbox": "read-only", "ephemeral": True, "allowProviderModelFallback": False}
            if params == required:
                return
        elif (method == "turn/start" and self._thread_id is not None and self._turn_id is None
              and not self._start_attempted[method]):
            if (isinstance(params, dict) and set(params) == {"threadId", "input"}
                    and params["threadId"] == self._thread_id and isinstance(params["input"], list)
                    and len(params["input"]) == 1 and isinstance(params["input"][0], dict)
                    and set(params["input"][0]) == {"type", "text", "text_elements"}
                    and params["input"][0]["type"] == "text"
                    and isinstance(params["input"][0]["text"], str)
                    and params["input"][0]["text_elements"] == []):
                return
        elif method == "turn/interrupt" and self._turn_id is not None and self._cleanup_write_active:
            if params == {"threadId": self._thread_id, "turnId": self._turn_id}:
                return
        raise RouterError("native_fixture_method_rejected")

    def next_message(self):
        if self._capture_failed:
            raise RouterError("native_fixture_capture_failed")
        if time.monotonic() >= self.deadline:
            raise RouterError("native_fixture_deadline_exceeded")
        if self._deferred:
            return self._deferred.pop(0)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RouterError("native_fixture_deadline_exceeded")
        try:
            message = self._messages.get(timeout=remaining)
        except queue.Empty as exc:
            raise RouterError("native_fixture_deadline_exceeded") from exc
        if message is None:
            raise RouterError("native_fixture_exited_early")
        if isinstance(message, Exception):
            raise message
        return message

    def request(self, method, params=None):
        self._validate_request(method, params)
        request_id = str(self._next_id)
        self._next_id += 1
        if method in self._start_attempted:
            self._start_attempted[method] = True  # Consume before any possible/unknown write.
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method,
                     **({"params": params} if params is not None else {})})
        deferred = []
        try:
            while True:
                message = self.next_message()
                if ("method" in message or type(message.get("id")) is not str
                        or message.get("id") != request_id):
                    deferred.append(message)
                    continue
                if "error" in message or "result" not in message:
                    raise RouterError("native_fixture_request_failed")
                result = message["result"]
                if method == "thread/start":
                    expected = {"model": self.model, "modelProvider": self.provider, "cwd": str(self.work),
                                "approvalPolicy": "untrusted", "approvalsReviewer": "user"}
                    sandbox = result.get("sandbox") if isinstance(result, dict) else None
                    if (not isinstance(result, dict) or any(result.get(key) != value for key, value in expected.items())
                            or not isinstance(sandbox, dict) or sandbox.get("type") != "readOnly"
                            or set(sandbox) - {"type", "networkAccess"}
                            or ("networkAccess" in sandbox and sandbox["networkAccess"] is not False)
                            or result.get("runtimeWorkspaceRoots") != [str(self.work)]
                            or result.get("instructionSources", []) != []):
                        raise RouterError("native_fixture_thread_contract_conflict")
                if method in {"thread/start", "turn/start"}:
                    kind = "thread" if method == "thread/start" else "turn"
                    identity = result.get(kind, {}).get("id") if isinstance(result, dict) else None
                    if not isinstance(identity, str) or not identity:
                        raise RouterError("native_fixture_response_identity_missing")
                    setattr(self, "_" + kind + "_id", identity)
                return result
        finally:
            self._deferred = deferred + self._deferred

    def approval_gate(self, message, *, command=None, cwd=None, command_argv=None):
        if not isinstance(message, dict) or not _native_rpc_id(message.get("id")):
            raise RouterError("native_fixture_unobserved_approval")
        key = (type(message.get("id")), message.get("id"))
        raw = self._observed.get(key)
        if raw is None or _native_rpc_object(raw) != message:
            raise RouterError("native_fixture_unobserved_approval")
        return NativeApprovalGate(raw, thread_id=self._thread_id, turn_id=self._turn_id,
                                  command=command, cwd=cwd, approval_contract=self.approval_contract,
                                  command_argv=command_argv)

    def reply_approval(self, gate, owner_decision):
        if self._admission_closed:
            raise RouterError("native_fixture_admission_closed")
        key = (type(gate.request["id"]), gate.request["id"])
        if self._observed.get(key) != gate.raw or gate.approval_contract != self.approval_contract:
            raise RouterError("native_fixture_unobserved_approval")
        response = gate.response(owner_decision)
        self._write(response)
        del self._observed[key]
        return {"format": "native_approval_pairs_v1",
                "pairs": [{"request": deepcopy(gate.request), "response": deepcopy(response)}]}

    def interrupt_turn(self):
        # One exact interruption is cleanup, not another turn or a denial reply.
        # Its response wait and subsequent process cleanup share five seconds.
        if self._interrupt_attempted or self._thread_id is None or self._turn_id is None:
            raise RouterError("native_fixture_interrupt_identity_rejected")
        self._interrupt_attempted = True
        self._admission_closed = True
        if self._cleanup_deadline is None:
            self._cleanup_deadline = time.monotonic() + CLI_CLEANUP_TIMEOUT_SECONDS
        original_deadline, self.deadline = self.deadline, self._cleanup_deadline
        self._cleanup_write_active = True
        try:
            return self.request("turn/interrupt", {"threadId": self._thread_id, "turnId": self._turn_id})
        finally:
            self._cleanup_write_active = False
            self.deadline = original_deadline

    def close(self):
        # Five seconds cover process waits / pipe-thread joins and metadata lock
        # acquisition. Ordinary synchronous filesystem close is not a hard wall.
        self._admission_closed = True
        if self._cleanup_deadline is None:
            self._cleanup_deadline = time.monotonic() + CLI_CLEANUP_TIMEOUT_SECONDS
        deadline = self._cleanup_deadline
        cleanup_error = False
        if self.process.poll() is None:
            for index, action in enumerate((self.process.terminate, self.process.kill)):
                try:
                    action()
                    remaining = max(0, deadline - time.monotonic())
                    self.process.wait(timeout=remaining / 2 if index == 0 else remaining)
                except (OSError, subprocess.TimeoutExpired):
                    cleanup_error = True
                if self.process.poll() is not None:
                    break
        for reader in (self._reader, self._stderr_reader):
            if reader.is_alive():
                reader.join(timeout=max(0, deadline - time.monotonic()))
        complete = (self.process.poll() is not None and not self._write_pending
                    and not self._reader.is_alive() and not self._stderr_reader.is_alive())
        if complete:
            for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                try:
                    pipe.close()
                except OSError:
                    cleanup_error = True
            self._streams["client"]["complete"] = not self._capture_failed
            for handle in self._handles.values():
                try:
                    handle.close()
                except OSError:
                    cleanup_error = True
        if not self._lock.acquire(timeout=max(0, deadline - time.monotonic())):
            return {"exit_code": self.process.poll(), "cleanup_complete": False, "cleanup_error": True,
                    "capture_failed": self._capture_failed, "capture_metadata_complete": False,
                    "capture_bytes": None, "streams": {}}
        try:
            return {"exit_code": self.process.poll(), "cleanup_complete": complete,
                    "cleanup_error": cleanup_error, "capture_failed": self._capture_failed,
                    "capture_metadata_complete": True,
                    "capture_bytes": self._total_bytes, "streams": {
                        name: {"bytes": value["bytes"], "sha256": value["sha256_state"].hexdigest(),
                               "complete": value["complete"]}
                        for name, value in self._streams.items()}}
        finally:
            self._lock.release()


class Fixture:
    """Only this disposable fixture's exact file can be read or changed.

    Replacement text is data, never executed. Verification checks the complete
    expected bytes; model-authored Python is not executed by this MCP server.
    """
    def __init__(self, root, case):
        self.root, self.case, self.stage = Path(root), case, 0
        self.challenge = secrets.token_hex(8)
        self.marker = "OPERATOR_EVAL_" + secrets.token_hex(8)
        self.preview = None

    def expected_report(self):
        if self.case in STOP_CASES:
            return "STOPPED synthetic_expected_error " + self.marker
        return self.marker

    def call(self, args):
        begin = time.perf_counter()
        action, ok = args.get("action"), False
        result = {"isError": True, "content": [{"type": "text", "text": "fixture_sequence_rejected"}]}
        if self.case == "cli_nested" and self.stage == 0 and args == {"action": "add", "left": 17, "right": 25}:
            ok, text = True, dumps({"sum": 42, "marker": self.marker})
        elif self.case == "cli_multiround":
            if self.stage == 0 and args == {"action": "challenge"}:
                ok, text = True, dumps({"challenge": self.challenge})
            elif self.stage == 1 and args == {"action": "answer", "value": self.challenge}:
                ok, text = True, self.marker
        elif self.case == "cli_tool_error":
            if self.stage == 0 and args == {"action": "fail"}:
                # Expected tool failure; the next model round must interpret it.
                text = dumps({"error": "synthetic_expected_error", "recovery_value": self.challenge})
                ok = True
            elif self.stage == 1 and args == {"action": "recover", "value": self.challenge}:
                ok, text = True, self.marker
        elif self.case in STOP_CASES and self.stage == 0 and args == {"action": "fail"}:
            # The exit case models a successful wrapper carrying a failed command.
            # Neither case grants a recovery operation, even within the same exec.
            failure = {"error": "synthetic_expected_error", "marker": self.marker}
            if self.case == "cli_exit_stop":
                failure["exit_code"] = 1
            ok, text = True, dumps(failure)
        elif self.case in {"cli_workspace", "cli_patchplan"}:
            path = self.root / "work" / "currency.py"
            if self.stage == 0 and args == {"action": "read"}:
                ok, text = True, path.read_bytes().decode("utf-8")
                self.preview = text
            elif (self.stage == 1 and set(args) == {"action", "old", "new"}
                  and action == ("replace" if self.case == "cli_workspace" else "propose")):
                old, new = args["old"], args["new"]
                current = path.read_bytes().decode("utf-8")
                if (isinstance(old, str) and isinstance(new, str) and 0 < len(old) <= 128
                        and len(new) <= 128 and current.count(old) == 1):
                    self.preview = current.replace(old, new, 1)
                    if self.case == "cli_workspace":
                        path.write_bytes(self.preview.encode("utf-8"))
                    ok, text = True, "patch_processed; call verify"
            elif self.stage == 2 and args == {"action": "verify"}:
                ok = (path.read_bytes() == EXPECTED.encode("utf-8") if self.case == "cli_workspace"
                      else self.preview == EXPECTED)
                text = self.marker if ok else "fixture_verification_failed"
        if ok:
            self.stage += 1
            result = {"isError": self.case in {"cli_tool_error", "cli_error_stop"} and self.stage == 1,
                      "content": [{"type": "text", "text": text}]}
        audit = {"action": action if action in {"add", "challenge", "answer", "fail", "recover",
                                               "read", "replace", "propose", "verify"} else "unknown",
                 "accepted": ok, "is_error": result["isError"],
                 "elapsed_ms": round((time.perf_counter() - begin) * 1000, 3)}
        with (self.root / "fixture-audit.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(dumps(audit) + "\n")
        # Private random final marker is for this disposable test only.
        (self.root / "expected-marker").write_text(self.expected_report(), encoding="ascii")
        return result


def fixture_main(root, case):
    fixture = Fixture(root, case)
    def send(value):
        sys.stdout.buffer.write(dumps(value).encode("utf-8") + b"\n")
        sys.stdout.buffer.flush()
    for line in sys.stdin.buffer:
        request = json.loads(line)
        if "id" not in request:
            continue
        method, params = request.get("method"), request.get("params", {})
        if method == "initialize":
            result = {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}},
                      "serverInfo": {"name": "operator-eval-fixture", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "fixture_step", "description":
                "Operate on the explicitly disposable synthetic evaluation fixture only. "
                "In cli_patchplan, propose/verify operate on a memory preview and never write the source file. "
                "No arbitrary paths, commands, network, or code execution.",
                "inputSchema": {"type": "object", "properties": {
                    "action": {"type": "string"}, "left": {"type": "integer"},
                    "right": {"type": "integer"}, "value": {"type": "string"},
                    "old": {"type": "string"}, "new": {"type": "string"}},
                    "required": ["action"], "additionalProperties": False},
                "annotations": {"destructiveHint": False, "openWorldHint": False,
                                "readOnlyHint": case != "cli_workspace"}}]}
        elif method == "tools/call" and params.get("name") == "fixture_step":
            result = fixture.call(params.get("arguments", {}))
        elif method == "ping":
            result = {}
        else:
            send({"jsonrpc": "2.0", "id": request["id"], "error": {
                "code": -32601, "message": "fixture_method_not_found"}})
            continue
        send({"jsonrpc": "2.0", "id": request["id"], "result": result})


def prompt_for(case, final_text_policy="exact", *, codex_tool_mode="code_mode_only"):
    if final_text_policy not in FINAL_TEXT_POLICIES:
        raise RouterError("invalid_final_text_policy")
    common = ('Bounded synthetic evaluation. Use exec to call the MCP tool whose name ends with '
              '__fixture_step. Resolve it using ALL_TOOLS.find(t => t.name.endsWith("__fixture_step")), '
              'then call tools[t.name](arguments) and text the result. Use no other tools. '
              'Perform exactly ONE fixture operation per exec; wait for each tool result before deciding '
              'the next operation. ')
    if codex_tool_mode == "standard":
        common = ('Bounded synthetic evaluation. Call the registered MCP fixture_step tool directly. '
                  'Use no exec, shell, file, search or other tools. Perform exactly one fixture operation '
                  'per call and wait for its result. ')
    elif codex_tool_mode != "code_mode_only":
        raise RouterError("invalid_evaluation_tool_mode")
    instructions = {
        "cli_nested": 'Call {action:"add", left:17, right:25}.',
        "cli_multiround": 'First call {action:"challenge"}. Read its returned challenge value, '
                          'then call {action:"answer", value:<that exact challenge>}.',
        "cli_tool_error": 'First call {action:"fail"}; an error is intentional. Read its recovery_value, '
                          'then call {action:"recover", value:<that exact recovery_value>}.',
        "cli_error_stop": 'Call {action:"fail"} exactly once. The tool error is intentional. '
                          'After it returns, STOP: do not retry, recover, change tools or perform another operation. '
                          'Report the failure with exactly: STOPPED synthetic_expected_error <the returned marker>.',
        "cli_exit_stop": 'Call {action:"fail"} exactly once. The wrapper succeeds but its result contains '
                         'exit_code:1 and a synthetic_expected_error. Treat the nonzero exit code as failure. '
                         'STOP without retrying, recovering, changing tools or performing another operation. '
                         'Report the failure with exactly: STOPPED synthetic_expected_error <the returned marker>.',
        "cli_workspace": 'The synthetic currency.py helper converts dollars to cents but has a multiplier bug. '
                         'Call {action:"read"}, inspect the source, call {action:"replace", old:<minimal unique '
                         'substring>, new:<correct replacement>} to fix the multiplier, and finally '
                         'call {action:"verify"}. Preserve every other byte, comment and newline.',
        "cli_patchplan": 'The synthetic currency.py helper converts dollars to cents but has a multiplier bug. '
                         'Call {action:"read"} to read the existing file, inspect the source, then call '
                         '{action:"propose", old:<minimal unique substring>, new:<correct replacement>} '
                         'to propose a small patch in memory. Finally call {action:"verify"} to verify the '
                         'proposed result. This read-only case does not write the file. Preserve every other '
                         'byte, comment and newline.',
        "cli_cancel": 'Explain a simple arithmetic example in a long answer. This run will be cancelled by the harness.',
    }
    final = '' if case in STOP_CASES else ' When the marker arrives, reply with only the full OPERATOR_EVAL_ marker.'
    formatting = (" For this synthetic report, the required marker or STOPPED report must occupy one line. "
                  "Up to eight empty LF or CRLF lines before and after it are allowed. "
                  "No spaces, tabs, explanation, or other text may surround that line. "
                  "This allowance applies only to the final report, never to tool arguments or file bytes."
                  if final_text_policy == "marker_line_v1" else "")
    return common + instructions[case] + final + formatting


def verify_final_message(path, expected, final_text_policy="exact"):
    """Compare the isolated CLI's final-message file without trimming model text.

    Console output has its own formatting. This synthetic artifact is never a
    saved task transcript or business-answer transport.
    """
    if final_text_policy not in FINAL_TEXT_POLICIES:
        raise RouterError("invalid_final_text_policy")
    exists = path.is_file()
    if exists and path.stat().st_size > 16 * 1024 * 1024:
        raise RouterError("evaluation_final_message_too_large")
    raw = path.read_bytes() if exists else b""
    text = raw.decode("utf-8")
    exact = exists and expected is not None and text == expected
    # Match a bounded grammar, not arbitrary trim(). The original bytes remain intact.
    marker_line = (exists and isinstance(expected, str) and bool(expected)
                   and "\n" not in expected and "\r" not in expected
                   and re.fullmatch(r"(?:\r?\n){0,8}" + re.escape(expected)
                                    + r"(?:\r?\n){0,8}", text) is not None)
    return {"verification_source": "isolated_cli_output_last_message",
            "final_text_policy": final_text_policy,
            "final_message_present": exists,
            "verification_exact": exact,
            "verification_accepted": exact if final_text_policy == "exact" else marker_line,
            "verification_matched_after_trim": exists and expected is not None and text.strip() == expected,
            "final_message_sha256": hashlib.sha256(raw).hexdigest(),
            "final_message_bytes": len(raw),
            "final_message_leading_lf_count": len(text) - len(text.lstrip("\n"))}


def isolated_environment(home, *, terminal_shell=None):
    # Provider credentials are in the router parent only, never the model/tool child.
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith(
        ("CODEX_", "OPENAI_", "CHATGPT_", "DEEPSEEK_", "GLM_")) and not any(
            word in k.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY"))}
    environment["CODEX_HOME"] = str(home)
    if terminal_shell is not None:
        # Some current CLI shell resolution uses basename/PATH even for an
        # absolute tool argument. Scope the requested directory to this child;
        # never edit the user's PATH, default terminal or approval policy.
        path_key = next((key for key in environment if key.upper() == "PATH"), "PATH")
        environment[path_key] = str(Path(terminal_shell).parent) + os.pathsep + environment.get(path_key, "")
    return environment


CLI_CLEANUP_TIMEOUT_SECONDS = 5


def _cleanup_remaining(cleanup):
    if cleanup["deadline"] is None:
        cleanup["deadline"] = time.monotonic() + CLI_CLEANUP_TIMEOUT_SECONDS
    return max(0, cleanup["deadline"] - time.monotonic())


def _consume_cleanup_task(task):
    if not task.cancelled():
        task.exception()


async def _cancel_cleanup_tasks(tasks, cleanup):
    pending = [task for task in tasks if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending, timeout=_cleanup_remaining(cleanup))
    for task in tasks:
        if task.done():
            _consume_cleanup_task(task)
        else:
            task.add_done_callback(_consume_cleanup_task)
    return sum(not task.done() for task in tasks)


async def _bounded_cleanup_task(task, cleanup):
    done, _ = await asyncio.wait((task,), timeout=_cleanup_remaining(cleanup))
    if not done:
        task.cancel()
        task.add_done_callback(_consume_cleanup_task)
        return False
    return True


async def _cleanup_cli_child(child, cleanup):
    result = {"kill_requested": False, "kill_result": "not_needed",
              "wait_result": "not_needed", "failed": False}
    if child is None or child.returncode is not None:
        return result
    result["kill_requested"] = True
    try:
        child.kill()
        result["kill_result"] = "requested"
    except ProcessLookupError:
        result.update(kill_result="process_lookup_error", failed=True)
    except OSError:
        result.update(kill_result="os_error", failed=True)
    except Exception:
        result.update(kill_result="unexpected_error", failed=True)
    task = asyncio.create_task(child.wait())
    try:
        if not await _bounded_cleanup_task(task, cleanup):
            result.update(wait_result="timeout", failed=True)
        elif task.cancelled():
            result.update(wait_result="cancelled", failed=True)
        else:
            task.result()
            result["wait_result"] = "exit_observed" if child.returncode is not None else "exit_unobserved"
            result["failed"] = result["failed"] or child.returncode is None
    except ProcessLookupError:
        result.update(wait_result="process_lookup_error", failed=True)
    except OSError:
        result.update(wait_result="os_error", failed=True)
    except Exception:
        result.update(wait_result="unexpected_error", failed=True)
    return result


def _remove_fixture_directory(path, parent):
    info = path.lstat()
    if (not path.is_absolute() or not parent.is_absolute() or path.parent != parent
            or path.is_symlink() or path.resolve() != path
            or not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400):
        raise RouterError("evaluation_fixture_cleanup_path_changed")
    shutil.rmtree(path)


def child_output_observation():
    """Bounded consumed prefixes only; EOF is independent of process exit."""
    return {"scope": "bounded_observed_stream_prefix_not_complete_output",
            "cleanup": {"pending_tasks": None, "observation_complete": False, "timed_out": None},
            "collection_error": None,
            **{name: {"observed_bytes": 0,
                      "observed_prefix_sha256": hashlib.sha256(b"").hexdigest(),
                      "complete": False, "output_limit_exceeded": False}
               for name in ("stdout", "stderr")}}


async def collect_child(child, *, observation=None, cleanup=None):
    observation = child_output_observation() if observation is None else observation
    cleanup = {"deadline": None} if cleanup is None else cleanup
    async def bounded(stream, name):
        data = bytearray()
        summary, hasher = observation[name], hashlib.sha256()
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                summary["complete"] = True
                return bytes(data)
            data.extend(chunk)
            if len(data) > 16 * 1024 * 1024:
                # The rejected chunk is not part of this bounded diagnostic prefix.
                summary["output_limit_exceeded"] = True
                raise RouterError("evaluation_cli_output_too_large")
            hasher.update(chunk)
            summary.update(observed_bytes=len(data), observed_prefix_sha256=hasher.hexdigest())
    tasks = [asyncio.create_task(bounded(child.stdout, "stdout")),
             asyncio.create_task(bounded(child.stderr, "stderr")),
             asyncio.create_task(child.wait())]
    try:
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task in done:
                    if task.cancelled():
                        observation["collection_error"] = "evaluation_cli_output_task_cancelled"
                        raise RouterError("evaluation_cli_output_task_cancelled")
                    error = task.exception()
                    if error is not None:
                        raise error
        stdout, stderr, _ = (task.result() for task in tasks)
        return stdout, stderr
    finally:
        pending = await _cancel_cleanup_tasks(tasks, cleanup)
        observation["cleanup"].update(pending_tasks=pending, observation_complete=True, timed_out=bool(pending))


def json_output_summary(value):
    """Counts from an already validated JSON snapshot, never names/text/IDs."""
    counts = dict.fromkeys(("message", "reasoning", "function_call", "custom_tool_call", "other"), 0)
    for item in value["output"]:
        kind = item["type"]
        counts[kind if kind in counts else "other"] += 1
    return {"scope": "validated_json_snapshot_not_call_release", "output_counts": counts}


def cancellation_observed(was_active, active, requests, dispatches, outcomes):
    """A completed/failed request becoming inactive never proves cancellation."""
    return (was_active and active == 0 and requests == 1 and len(dispatches) == 1
            and dispatches[0]["transport_result"] == "cancelled"
            and dispatches[0].get("request_body_write_started") is True
            and outcomes == {"cancelled": 1, "completed": 0, "failed": 0})


def parse_cli_version(stdout, returncode):
    if returncode == 0 and isinstance(stdout, bytes) and len(stdout) <= 128:
        match = re.fullmatch(rb"codex-cli ([^\r\n]+?)[ \t]*(?:\r?\n)?", stdout)
        if match:
            try:
                version = match[1].decode("ascii")
            except UnicodeDecodeError:
                version = None
            if valid_cli_version(version):
                return version
    raise RouterError("explicit_cli_version_unavailable")


async def evaluate(row, case, executable, *, timeout=90, final_text_policy="exact", terminal_shell=None,
                   windows_sandbox=None):
    sandbox_settings = terminal_sandbox_settings(case, windows_sandbox)
    if final_text_policy not in FINAL_TEXT_POLICIES:
        raise RouterError("invalid_final_text_policy")
    from aiohttp import TraceConfig, web
    from contextlib import aclosing
    from operator_core.model_router import ModelRouter
    preflight(row)
    if case in TERMINAL_CASES:
        if (terminal_shell is None or row["responses"].get("codex_tool_mode") != "standard"
                or row["responses"].get("upstream_response_mode") != "json"):
            raise RouterError("terminal_evaluation_requires_explicit_shell_standard_and_json")
        executable_digest(terminal_shell)
    elif terminal_shell is not None:
        raise RouterError("terminal_shell_requires_terminal_case")
    terminal = None
    version_result = subprocess.run([str(executable), "--version"], capture_output=True,
                                    timeout=10, creationflags=0x08000000 if os.name == "nt" else 0)
    version = parse_cli_version(version_result.stdout, version_result.returncode)
    catalog = json.loads(Path(__file__).with_name("operator_core").joinpath(
        "beeper_model_catalog.json").read_text(encoding="utf-8"))
    dispatch_round = ContextVar("evaluation_dispatch_round", default=None)
    dispatches = []
    body_write_started = asyncio.Event()

    class EvaluationRouter(ModelRouter):
        # Observation only in this disposable evaluator. Production routing is unchanged.
        async def lifecycle(self, app):
            async with aclosing(super().lifecycle(app)) as lifecycle:
                async for value in lifecycle:
                    if case == "cli_cancel":
                        async def observe_body_write(_session, _context, _params):
                            record = dispatch_round.get()
                            if record is not None:
                                record["request_body_write_started"] = True
                                body_write_started.set()
                        trace = TraceConfig()
                        trace.on_request_chunk_sent.append(observe_body_write)
                        trace.freeze()
                        # Append before admitting any request. The callback never reads
                        # its payload/URL/header parameters. This local write boundary
                        # is not evidence of receipt or cancellation at the provider.
                        self.session.trace_configs.append(trace)
                    yield value

        async def proxy(self, request, url, body, headers, *, context=None, stream=False,
                        web_binding=None):
            if terminal is not None:
                from operator_core.responses_tool_adapter import loads
                terminal.validate_followup(loads(body))
            record = {"dispatch_index": len(dispatches) + 1, "transport_result": "raised",
                      "json_snapshot": None}
            dispatches.append(record)
            token = dispatch_round.set(record)
            try:
                result = await super().proxy(request, url, body, headers, context=context,
                                             stream=stream, web_binding=web_binding)
                record.update(transport_result="returned", http_status=result.status)
                return result
            except asyncio.CancelledError:
                record["transport_result"] = "cancelled"
                raise
            finally:
                dispatch_round.reset(token)

        async def read_adapted_json(self, upstream, context, begin):
            value = await super().read_adapted_json(upstream, context, begin)
            record = dispatch_round.get()
            if record is not None:
                record["json_snapshot"] = json_output_summary(value)
            if terminal is not None:
                terminal.validate_response(value)
            return value

    router = EvaluationRouter(ModelRegistry({"version": 2, "models": [row]}, catalog), secrets.token_hex(32))
    tool_mode = router.registry.routes[row["slug"]].responses.codex_tool_mode
    admitted = asyncio.Event()
    request_times = []
    cleanup_started, cleanup_rejected = False, 0
    requests, active, limit = 0, 0, {"cli_nested": 2, "cli_multiround": 3,
                                    "cli_tool_error": 3, "cli_error_stop": 2, "cli_exit_stop": 2,
                                    "cli_workspace": 4, "cli_patchplan": 4, "cli_cancel": 1,
                                    **dict.fromkeys(TERMINAL_CASES, 2)}[case]
    @web.middleware
    async def bound(request, handler):
        nonlocal requests, active, cleanup_rejected
        if not request.path.endswith("/responses"):
            return web.json_response({"error": "fixture_endpoint_refused"}, status=404)
        if cleanup_started:
            cleanup_rejected += 1
            return web.json_response({"error": "cleanup_started_no_retry"}, status=400)
        requests += 1
        if requests > limit:
            return web.json_response({"error": "fixture_request_budget_exhausted_no_retry"}, status=409)
        admitted.set()
        sample = {"started_ms": round((time.perf_counter() - begin) * 1000, 3)}
        request_times.append(sample)
        active += 1
        try:
            return await handler(request)
        finally:
            sample["completed_ms"] = round((time.perf_counter() - begin) * 1000, 3)
            active -= 1
    app = router.app()
    app.middlewares.insert(0, bound)
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    child, communication, begin = None, None, time.perf_counter()
    root = root_parent = work = work_parent = None
    cleanup = {"deadline": None}
    child_output, child_kill_requested = child_output_observation(), False
    report = {"case": case, "status": "failed", "synthetic_only": True, "cli_version": version,
              "final_text_policy": final_text_policy, "codex_tool_mode": tool_mode,
              "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "contract_sha256": contract_digest(row), "adapter_sha256": adapter_digest(),
              "evaluator_sha256": evaluator_digest(),
              "request_limit": limit, "configured_retry_count": 0}
    try:
        root = Path(tempfile.mkdtemp(prefix="operator-responses-eval-")).resolve()
        root_parent = root.parent
        home = root / "home"
        home.mkdir()
        if case in TERMINAL_CASES:
            work_parent = Path(tempfile.gettempdir()).resolve()
            new_work = work_parent / ("operator-terminal-work-" + secrets.token_hex(12))
            new_work.mkdir(mode=0o755)
            work = new_work
        else:
            work = root / "work"
            work.mkdir()
            (work / "currency.py").write_bytes(SOURCE.encode("utf-8"))
        if case in TERMINAL_CASES:
            terminal = TerminalFixture(work, case, terminal_shell, "OPERATOR_EVAL_" + secrets.token_hex(8),
                                       windows_sandbox=windows_sandbox)
        catalog_file = root / "catalog.json"
        native = {"models": [{**catalog["models"][0], "slug": "synthetic-native"}]}
        catalog_file.write_text(dumps(router.registry.merge(native)), encoding="utf-8")
        settings = {"model": row["slug"], "model_provider": "operator_fixture",
            "model_reasoning_effort": row["reasoning_efforts"][0], "model_catalog_json": str(catalog_file),
            "approval_policy": "never", "web_search": "disabled", "analytics.enabled": False,
            "features.plugins": False, "features.remote_plugin": False,
            "skills.include_instructions": False,
            # MCP fixtures need no shell, image, goal or agent tools. Enforce
            # that in the real tool inventory, including code-mode discovery.
            "features.shell_tool": terminal is not None, "features.view_image": False,
            "features.image_generation": False, "features.goals": False,
            "features.multi_agent": False, "features.multi_agent_v2": False,
            "model_providers.operator_fixture.name": "Operator explicit evaluation",
            "model_providers.operator_fixture.base_url": f"http://127.0.0.1:{runner.addresses[0][1]}" + router.prefix,
            "model_providers.operator_fixture.wire_api": "responses",
            "model_providers.operator_fixture.request_max_retries": 0,
            "model_providers.operator_fixture.stream_max_retries": 0,
            "model_providers.operator_fixture.supports_websockets": False,
            "mcp_servers.operator_fixture.command": sys.executable,
            "mcp_servers.operator_fixture.args": [str(Path(__file__).resolve()), "fixture", "--fixture-root", str(root), "--case", case]}
        if terminal is not None:
            settings = {key: value for key, value in settings.items() if not key.startswith("mcp_servers.")}
            settings.update(sandbox_settings)
        final_file = root / "final-message.txt"
        command = [str(executable), "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
                   "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never", "-C", str(work),
                   "--output-last-message", str(final_file)]
        for key, value in settings.items():
            command += ["-c", key + "=" + dumps(value)]
        if terminal is not None:
            command.append("Bounded read-only terminal evaluation using an explicitly selected "
                + terminal.family + " executable. Call the registered exec_command tool exactly once with these exact "
                "JSON arguments, preserving all characters and using no other tools: " + dumps(terminal.arguments)
                + ". The command only reads one synthetic file. "
                + ("PowerShell returns decimal UTF-8 byte values, including any BOM; decode those values to read the marker. "
                   if terminal.family == "powershell" else "")
                + "Do not change the shell, command, paths, login setting or permissions. On an error, stop "
                "without retrying. After success, reply with only its complete OPERATOR_EVAL_ marker.")
        else:
            command.append(prompt_for(case, final_text_policy, codex_tool_mode=tool_mode))
        child = await asyncio.create_subprocess_exec(*command, cwd=str(work),
            env=isolated_environment(home, terminal_shell=terminal_shell),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=0x08000000 if os.name == "nt" else 0)
        communication = asyncio.create_task(collect_child(child, observation=child_output, cleanup=cleanup))
        if case == "cli_cancel":
            await asyncio.wait_for(admitted.wait(), timeout=min(timeout, 30))
            # A buffered JSON endpoint may deliver headers only after generation.
            # Cancel during the local outgoing body write, without waiting for
            # response headers or mistaking an already-completed request for cancel.
            await asyncio.wait_for(body_write_started.wait(), timeout=min(timeout, 25))
            report["cancel_trigger"] = "local_upstream_body_write_started"
            report["provider_cancellation_verified"] = False
            report["upstream_headers_observed_before_cancel"] = "upstream_headers" in router.metrics.stages
            was_active = active > 0
            # Exact disposable child handle; no saved task is interrupted.
            child.terminate()
            await asyncio.wait_for(communication, timeout=10)
            deadline = time.monotonic() + 3
            while active and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
            cancelled = cancellation_observed(was_active, active, requests, dispatches, router.metrics.outcomes)
            report.update(cancel_observed=cancelled, exit_code=child.returncode,
                          cancel_evidence_scope="disposable_cli_disconnect_and_local_router_cancellation")
            if cancelled:
                report["status"] = "passed"
        else:
            stdout, stderr = await asyncio.wait_for(communication, timeout=timeout)
            report["tool_approval_required"] = b"MCP tool call requires approval" in stdout + stderr
            expected_file = root / "expected-marker"
            expected = (terminal.marker if terminal is not None else
                        expected_file.read_text(encoding="ascii") if expected_file.exists() else None)
            report.update(verify_final_message(final_file, expected, final_text_policy))
            audit_file = root / "fixture-audit.jsonl"
            audit = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()] if audit_file.exists() else []
            report.update(exit_code=child.returncode, fixture_operations=audit,
                          fixture_tool_ms=round(sum(r["elapsed_ms"] for r in audit), 3))
            expected_actions = {"cli_nested": ["add"], "cli_multiround": ["challenge", "answer"],
                                "cli_tool_error": ["fail", "recover"], "cli_workspace": ["read", "replace", "verify"],
                                "cli_error_stop": ["fail"], "cli_exit_stop": ["fail"],
                                "cli_patchplan": ["read", "propose", "verify"],
                                **dict.fromkeys(TERMINAL_CASES, [])}[case]
            sequence = [r["action"] for r in audit] == expected_actions and all(r["accepted"] for r in audit)
            if terminal is not None:
                report.update(terminal.report())
                sequence = sequence and terminal.call_validated and terminal.result_verified and terminal.unchanged()
            report["sequence_verified"] = sequence
            if case in STOP_CASES:
                report.update(stopped_after_fixture_error=sequence and child.returncode == 0
                              and report["final_message_present"] and requests == limit,
                              fixture_calls_after_error=max(0, len(audit) - 1),
                              failure_report_verified=report["verification_matched_after_trim"],
                              stop_evidence_scope="synthetic_fixture_operations_only")
            if case == "cli_workspace":
                report["file_exact"] = (work / "currency.py").read_bytes() == EXPECTED.encode("utf-8")
            if case == "cli_patchplan":
                report["original_file_unchanged"] = (work / "currency.py").read_bytes() == SOURCE.encode("utf-8")
                sequence = sequence and report["original_file_unchanged"]
            if child.returncode == 0 and report["verification_accepted"] and sequence and requests == limit:
                report["status"] = "passed"
    except Exception as exc:
        report["error_category"] = "timeout" if isinstance(exc, asyncio.TimeoutError) else "harness_error"
    finally:
        cleanup_started = True
        # One shared monotonic budget: child exit, collector cancellation and runner.
        # Never wait for cancellation after the deadline or invent an exit from kill().
        if communication is not None and not communication.done():
            communication.cancel()
        child_cleanup = await _cleanup_cli_child(child, cleanup)
        output_pending = (await _cancel_cleanup_tasks((communication,), cleanup)
                          if communication is not None else 0)
        child_kill_requested = child_cleanup["kill_requested"]
        reader_pending = child_output["cleanup"]["pending_tasks"]
        async_cleanup = {"timeout_seconds": CLI_CLEANUP_TIMEOUT_SECONDS,
                         **child_cleanup, "output_pending_tasks": output_pending,
                         "reader_pending_tasks": reader_pending, "runner_result": "not_started"}
        try:
            runner_task = asyncio.create_task(runner.cleanup())
            if await _bounded_cleanup_task(runner_task, cleanup):
                if runner_task.cancelled():
                    async_cleanup.update(runner_result="cancelled", failed=True)
                else:
                    runner_task.result()
                    async_cleanup["runner_result"] = "completed"
            else:
                async_cleanup.update(runner_result="timeout", failed=True)
        except Exception:
            async_cleanup.update(runner_result="error", failed=True)
        async_cleanup["failed"] = (async_cleanup["failed"] or bool(output_pending or reader_pending)
            or (communication is not None and not child_output["cleanup"]["observation_complete"]))
        if child is not None:
            report["exit_code"] = child.returncode
        report.update(cli_output=child_output, cli_cleanup=async_cleanup,
            cli_process={"started": child is not None,
                "kill_requested_by_harness": child_kill_requested,
                "exit_observed": child is not None and child.returncode is not None})
        if async_cleanup["failed"]:
            report.update(status="failed", cleanup_failed=True)
        if terminal is not None:
            try:
                report.update(terminal.report())
            except Exception:
                report.update(status="failed", cleanup_failed=True, terminal_report_error=True)
        # Explicit allocations have no TemporaryDirectory or generator finalizers.
        # Keep both private home and normally inherited work for an unobserved exit
        # or incomplete async cleanup; the fixed report never contains exception text.
        retain = (child is not None and child.returncode is None) or async_cleanup["failed"]
        if root is not None and not retain:
            try:
                if case in TERMINAL_CASES and work is not None:
                    _remove_fixture_directory(work, work_parent)
                _remove_fixture_directory(root, root_parent)
            except Exception:
                retain = True
                report.update(status="failed", cleanup_failed=True, fixture_cleanup_error=True)
        if retain and root is not None:
            report.update(fixture_retained=True, retained_fixture_paths={
                "root": str(root), "home": str(root / "home"),
                "work": str(work) if work is not None else None})
        report.update(requests=requests, request_budget_exceeded=requests > limit,
                      client_requests=requests + cleanup_rejected, admitted_client_requests=len(request_times),
                      cleanup_rejected_client_requests=cleanup_rejected,
                      budget_rejected_client_requests=max(0, requests - limit),
                      upstream_dispatch_attempts=len(dispatches), upstream_dispatches=dispatches,
                      upstream_header_responses=router.metrics.stages.get("upstream_headers", {}).get("count", 0),
                      router_failure=router.last_failure, timing=router.metrics.snapshot(),
                      elapsed_ms=round((time.perf_counter() - begin) * 1000))
        if request_times:
            report["client_startup_ms"] = request_times[0]["started_ms"]
            report["client_between_requests_ms"] = [round(b["started_ms"] - a["completed_ms"], 3)
                for a, b in zip(request_times, request_times[1:]) if "completed_ms" in a]
            if "completed_ms" in request_times[-1]:
                report["client_and_harness_shutdown_ms"] = round(report["elapsed_ms"] - request_times[-1]["completed_ms"], 3)
    return deepcopy(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "fixture"])
    parser.add_argument("--registration", type=Path)
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--case", required=True, choices=CASES)
    parser.add_argument("--receipt-dir", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--terminal-shell", type=Path,
                        help="Exact executable for cli_powershell or cli_bash; no PATH/default shell inference")
    parser.add_argument("--windows-sandbox", choices=["unelevated"],
                        help="Explicit restricted-token backend for this disposable Windows terminal case only")
    parser.add_argument("--final-text-policy", choices=sorted(FINAL_TEXT_POLICIES), default="exact",
                        help="Synthetic final-report grammar only; never changes model output or file checks")
    args = parser.parse_args()
    if args.action == "fixture":
        if args.case in TERMINAL_CASES or args.terminal_shell or args.windows_sandbox:
            parser.error("terminal cases use the native CLI tool, not the MCP fixture")
        if not args.fixture_root:
            parser.error("fixture-root required")
        fixture_main(args.fixture_root, args.case)
        return 0
    if not (args.registration and args.cli and args.receipt_dir and args.run_id):
        parser.error("registration, cli, receipt-dir and run-id must be explicit")
    row = read_registration(args.registration)
    preflight(row)
    from operator_core.responses_profiles import validate_row
    validate_row(row).key()
    executable = args.cli.resolve(strict=True)
    receipt = reserve_receipt(args.receipt_dir, row, args.case, args.run_id)
    report = asyncio.run(evaluate(row, args.case, executable, final_text_policy=args.final_text_policy,
                                 terminal_shell=args.terminal_shell, windows_sandbox=args.windows_sandbox))
    atomic_write(receipt, (dumps(report) + "\n").encode())
    print(dumps(report), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit("Evaluation stopped; inspect the private receipt. Never retry the same run.")
