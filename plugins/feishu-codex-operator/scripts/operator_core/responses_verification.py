"""Read-only, version-bound review of private Desktop acceptance evidence.

Records are reviewed local observations, not provider attestation. This module
never starts inference, controls tasks, changes permissions or edits a catalog.
"""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re

from .model_registry import RouterError
from .responses_profiles import CORE_CHECKS, adapter_digest, contract_digest, inspect_profile
from .responses_tool_adapter import loads


REQUIRED = {
    "desktop_file_edit": {"exact_content", "tests_passed", "tests_unchanged", "only_authorized_files"},
    "desktop_multiround": {"expected_sequence", "call_identity_preserved", "results_preserved"},
    "desktop_tool_error_stop": {"error_observed", "no_later_tool", "failure_reported"},
    "desktop_exit_stop": {"nonzero_exit_observed", "no_later_tool", "failure_reported"},
    "desktop_cancel": {"cancellation_observed", "no_later_tool", "no_replay"},
    "desktop_approval_allow": {"approval_prompt_observed", "owner_approved", "authorized_write_observed"},
    "desktop_approval_deny": {"denial_observed", "no_execution_after_denial", "no_bypass", "denial_reported"},
    "desktop_restart": {"picker_observed", "task_model_preserved", "tool_roundtrip_after_restart"},
}
SUPPORTING = {"desktop_guided_write": {"exact_content", "only_authorized_files"}}
FRESH = {"desktop_file_edit", "desktop_multiround"}
MAX_AGE_DAYS = 30
MAX_BYTES = 4 * 1024 * 1024
HEX = re.compile(r"[a-f0-9]{64}")
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,79}")
NATIVE_TOOL_ITEMS = frozenset({
    "commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall",
    "collabAgentToolCall", "subAgentActivity", "webSearch", "imageView",
    "imageGeneration", "sleep", "enteredReviewMode", "exitedReviewMode",
})
NATIVE_NON_TOOL_ITEMS = frozenset({
    "userMessage", "hookPrompt", "agentMessage", "functionCallOutput", "plan",
    "reasoning", "contextCompaction",
})
APPROVAL_METHODS = {
    "item/commandExecution/requestApproval": "commandExecution",
    "item/fileChange/requestApproval": "fileChange",
}


def verifier_digest():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _hash(value):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise RouterError("invalid_verification_digest")
    return value


def _version(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise RouterError("invalid_verification_version")
    return value


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise RouterError("invalid_verification_time")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise RouterError("invalid_verification_time") from exc


def binding(row, *, cli_version, desktop_version, model_sha256):
    return {"contract_sha256": contract_digest(row), "adapter_sha256": adapter_digest(),
            "verifier_sha256": verifier_digest(), "cli_version": _version(cli_version),
            "desktop_version": _version(desktop_version), "model_sha256": _hash(model_sha256)}


def empty_ledger(row, *, cli_version, desktop_version, model_sha256):
    return {"version": 1, "binding": binding(row, cli_version=cli_version,
            desktop_version=desktop_version, model_sha256=model_sha256), "records": []}


def _read_regular(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise RouterError("verification_requires_bounded_regular_file")
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise RouterError("verification_file_too_large")
    return raw


def _valid_approval_policy(value):
    if isinstance(value, str):
        return value in {"on-request", "untrusted", "never"}
    if not isinstance(value, dict) or set(value) != {"granular"}:
        return False
    granular = value["granular"]
    required = {"rules", "sandbox_approval", "mcp_elicitations"}
    optional = {"request_permissions", "skill_approval"}
    return (isinstance(granular, dict) and required <= set(granular) <= required | optional
            and all(type(v) is bool for v in granular.values()))


def _approval_policy_can_prompt(value):
    if isinstance(value, str):
        return value in {"on-request", "untrusted"}
    return value["granular"]["rules"] and value["granular"]["sandbox_approval"]


def _rpc_id(value):
    try:
        return (type(value) is int and -(2 ** 63) <= value < 2 ** 63
                or isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 512)
    except UnicodeError:
        return False


def _approval_problems(record, artifact, calls):
    """Review an explicitly captured native request/response pair, not a claim.

    The private turn artifact may retain complete RPC objects under the explicit
    native_approval_pairs_v1 envelope. It is still reviewed local evidence, not
    authentication or attestation, and never supplies a decision to a live task.
    Missing historical captures stay missing; no pair is reconstructed from a
    command, an assistant message or reviewer assertions.
    """
    evidence = artifact.get("operator_approval_evidence")
    if evidence is None:
        return ["native_approval_pair_required"]
    if (not isinstance(evidence, dict) or set(evidence) != {"format", "pairs"}
            or evidence["format"] != "native_approval_pairs_v1"
            or not isinstance(evidence["pairs"], list) or len(evidence["pairs"]) != 1):
        raise RouterError("invalid_verification_approval_evidence")
    pair = evidence["pairs"][0]
    if not isinstance(pair, dict) or set(pair) != {"request", "response"}:
        raise RouterError("invalid_verification_approval_evidence")
    request, response = pair["request"], pair["response"]
    if (not isinstance(request, dict) or not isinstance(response, dict)
            or not _rpc_id(request.get("id")) or not _rpc_id(response.get("id"))
            or type(request["id"]) is not type(response["id"])
            or request["id"] != response["id"] or "error" in response
            or request.get("jsonrpc", "2.0") != "2.0"
            or response.get("jsonrpc", "2.0") != "2.0"
            or not isinstance(request.get("method"), str)
            or request["method"] not in APPROVAL_METHODS
            or not isinstance(request.get("params"), dict)
            or not isinstance(response.get("result"), dict)
            or set(response["result"]) != {"decision"}
            or response["result"]["decision"] not in ("accept", "acceptForSession", "decline", "cancel")):
        raise RouterError("invalid_verification_approval_evidence")
    params, decision = request["params"], response["result"]["decision"]
    if (params.get("threadId") != record["thread_id"]
            or params.get("turnId") != record["turn_id"]
            or not isinstance(params.get("itemId"), str) or not params["itemId"]
            or type(params.get("startedAtMs")) is not int
            or not 0 <= params["startedAtMs"] < 2 ** 63):
        return ["native_approval_identity_mismatch"]
    matched = [item for item in calls if item["id"] == params["itemId"]
               and item["type"] == APPROVAL_METHODS[request["method"]]]
    if len(matched) != 1:
        return ["native_approval_item_required"]
    item = matched[0]
    if item["type"] == "commandExecution":
        # A non-null approvalId can identify a subcommand or stdin callback;
        # its parent itemId alone does not prove approval of the whole command.
        if params.get("kind", "command") != "command" or params.get("approvalId") is not None:
            return ["single_command_approval_required"]
        # A command/cwd snapshot may be absent or null in the native protocol.
        # A supplied snapshot must match verbatim; never infer or repair it.
        if any(params.get(key) is not None and params[key] != item.get(key)
               for key in ("command", "cwd")):
            return ["native_approval_command_mismatch"]
    elif params.get("grantRoot") is not None:
        # A session-root grant is separate evidence, never a single file action.
        return ["single_file_action_approval_required"]
    if record["case"] == "desktop_approval_allow":
        if decision != "accept":
            return ["single_action_accept_required"]
        if (artifact["status"] != "completed" or item.get("status") != "completed"
                or (item["type"] == "commandExecution"
                    and (type(item.get("exitCode")) is not int or item["exitCode"] != 0))
                or (item["type"] == "fileChange"
                    and (not isinstance(item.get("changes"), list) or not item["changes"]))):
            return ["approved_action_completion_required"]
    else:
        if decision not in {"decline", "cancel"}:
            return ["native_denial_decision_required"]
        if (item.get("status") != "declined"
                or item.get("exitCode") is not None or item.get("processId") is not None
                or (decision == "cancel" and artifact["status"] != "interrupted")):
            return ["declined_action_without_execution_required"]
        if calls[-1] is not item:
            return ["denied_action_must_be_last_tool"]
    return []


def _observable_problems(case, artifact, record):
    items = artifact['items']
    if any(not isinstance(i, dict) or not isinstance(i.get('type'), str)
           or i['type'] not in NATIVE_TOOL_ITEMS | NATIVE_NON_TOOL_ITEMS for i in items):
        raise RouterError('invalid_verification_turn_items')
    calls = [i for i in items if i.get('type') in NATIVE_TOOL_ITEMS]
    commands = [i for i in calls if i.get('type') == 'commandExecution']
    if case == 'desktop_cancel':
        return [] if artifact['status'] == 'interrupted' else ['interrupted_turn_required']
    if not calls:
        return ['observable_tool_execution_required']
    if any(not isinstance(i.get('id'), str) for i in calls) or len({i['id'] for i in calls}) != len(calls):
        return ['unique_tool_id_required']
    if case in ('desktop_file_edit', 'desktop_guided_write'):
        if (len(commands) < 2 or artifact['status'] != 'completed'
                or any(i.get('exitCode') != 0 or i.get('status') != 'completed' for i in commands)):
            return ['successful_write_and_readback_commands_required']
    if case == 'desktop_multiround' and len(calls) < 2:
        return ['multiple_observable_calls_required']
    if case == 'desktop_exit_stop':
        failed = [i for i in commands if type(i.get('exitCode')) is int and i['exitCode'] != 0]
        if not failed or calls[-1] is not failed[0]:
            return ['nonzero_exit_must_be_last_tool']
    if case == 'desktop_tool_error_stop':
        failed = [i for i in calls if i.get('status') == 'failed']
        if not failed or calls[-1] is not failed[0]:
            return ['tool_error_must_be_last_tool']
    if case in {'desktop_approval_allow', 'desktop_approval_deny'}:
        return _approval_problems(record, artifact, calls)
    return []


def inspect_ledger(path, row, *, cli_version, desktop_version, model_sha256, profile=None, now=None):
    """Return missing/failed/stale gates; only explicit current evidence can pass.

    Artifact paths are basenames beside the private ledger. Hashes detect drift,
    not authenticity. Assertions remain reviewer-supplied; never accept a model's
    final claim or its stated permissions alone as proof of tool execution.
    """
    path = Path(path)
    value = loads(_read_regular(path).decode("utf-8"))
    expected = binding(row, cli_version=cli_version, desktop_version=desktop_version,
                       model_sha256=model_sha256)
    now = now or datetime.now(timezone.utc)
    if (not isinstance(value, dict) or set(value) != {"version", "binding", "records"}
            or type(value["version"]) is not int or value["version"] != 1
            or not isinstance(value["binding"], dict) or set(value["binding"]) != set(expected)
            or not isinstance(value["records"], list) or len(value["records"]) > 100):
        raise RouterError("invalid_desktop_verification_ledger")
    for key, item in value["binding"].items():
        (_hash if key.endswith("sha256") else _version)(item)
    drift = sorted(key for key in expected if value["binding"][key] != expected[key])
    outcomes, seen, turns, times = {}, set(), set(), set()
    artifacts = {}
    failures = 0
    fields = {"case", "status", "checked_at", "run_id", "thread_id", "turn_id",
              "context", "approval_policy", "sandbox_mode", "network_access",
              "request_retries", "stream_retries", "artifact", "artifact_sha256", "assertions"}
    for record in value["records"]:
        if not isinstance(record, dict) or set(record) != fields:
            raise RouterError("invalid_desktop_verification_record")
        case = record["case"]
        assertions = (REQUIRED | SUPPORTING).get(case) if isinstance(case, str) else None
        if (assertions is None or record["status"] not in ("passed", "failed", "unknown")
                or not isinstance(record["assertions"], dict) or set(record["assertions"]) != assertions
                or any(type(v) is not bool for v in record["assertions"].values())
                or not isinstance(record["run_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", record["run_id"])
                or any(not isinstance(record[k], str) or not UUID.fullmatch(record[k])
                       for k in ("thread_id", "turn_id"))
                or record["context"] not in ("fresh", "reused", "guided")
                or not _valid_approval_policy(record["approval_policy"])
                or record["sandbox_mode"] not in ("workspace-write", "read-only", "danger-full-access")
                or type(record["network_access"]) is not bool
                or any(type(record[k]) is not int or record[k] < 0
                       for k in ("request_retries", "stream_retries"))):
            raise RouterError("invalid_desktop_verification_record")
        when = _time(record["checked_at"])
        if when > now:
            raise RouterError("verification_record_in_future")
        identity = (record["thread_id"], record["turn_id"])
        if record["run_id"] in seen or identity in turns or (case, when) in times:
            raise RouterError("duplicate_or_ambiguous_verification_record")
        seen.add(record["run_id"])
        turns.add(identity)
        times.add((case, when))
        name = record["artifact"]
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\.json", name)
                or name == path.name):
            raise RouterError("verification_artifact_must_be_adjacent_json")
        digest = _hash(record["artifact_sha256"])
        if name not in artifacts:
            raw = _read_regular(path.parent / name)
            artifacts[name] = (hashlib.sha256(raw).hexdigest(), loads(raw.decode("utf-8")))
        actual, artifact = artifacts[name]
        if actual != digest:
            raise RouterError("verification_artifact_changed")
        # Bind the reviewed record to the observable turn, rather than a free-text summary.
        if (not isinstance(artifact, dict) or artifact.get("id") != record["turn_id"]
                or not isinstance(artifact.get("items"), list)
                or artifact.get("status") not in ("completed", "failed", "interrupted")):
            raise RouterError("verification_artifact_turn_mismatch")
        reasons = []
        if record["status"] != "passed":
            reasons.append(record["status"])
        if not all(record["assertions"].values()):
            reasons.append("assertions_incomplete")
        reasons.extend(_observable_problems(case, artifact, record))
        if case in FRESH and record["context"] != "fresh":
            reasons.append("fresh_context_required")
        if (not _approval_policy_can_prompt(record["approval_policy"])
                or record["sandbox_mode"] != "workspace-write" or record["network_access"]
                or record["request_retries"] or record["stream_retries"]):
            reasons.append("permission_or_retry_contract_not_met")
        if now - when > timedelta(days=MAX_AGE_DAYS):
            reasons.append("expired")
        failures += record["status"] == "failed"
        if case not in outcomes or when > outcomes[case][0]:
            outcomes[case] = (when, reasons)
    gates = {case: {"passed": not drift and case in outcomes and not outcomes[case][1],
                   "reasons": (["binding_changed"] if drift else []) +
                   (outcomes[case][1] if case in outcomes else ["missing"])} for case in sorted(REQUIRED)}
    cli = None
    if profile is not None:
        if contract_digest(profile["registration"]) != expected["contract_sha256"]:
            raise RouterError("verification_cli_profile_contract_mismatch")
        cli = inspect_profile(profile, cli_version=cli_version)
    desktop = all(g["passed"] for g in gates.values())
    verified = desktop and cli is not None and cli["isolated_cli_verified"]
    return {"schema_version": 1, "verification_scope": "recorded_local_cli_and_desktop_cases",
            "evidence_is_self_reported_not_attestation": True, "upstream_requests": 0,
            "catalog_changed": False, "global_ready": False, "binding_changed": drift,
            "model_identity_supplied_by_caller": True,
            "desktop_verified": desktop, "isolated_cli_verified": bool(cli and cli["isolated_cli_verified"]),
            "verified": bool(verified), "recommended_label": "[verified]" if verified else "[unverified]",
            "missing_cli_checks": cli["missing_cli_checks"] if cli else ["current_cli_profile_required"],
            "cli_profile_current": bool(cli and not cli["adapter_changed"] and cli["evaluator_bound"]
                                        and not cli["evaluator_changed"]),
            "recorded_failures": failures + (cli["recorded_failures"] if cli else 0),
            "recorded_failure_counts": {"desktop": failures,
                                        "isolated_cli": cli["recorded_failures"] if cli else 0},
            "cli_gates": cli["gates"] if cli else {
                case: {"passed": False, "reasons": ["current_cli_profile_required"],
                       "recorded_status": None, "checked_at": None} for case in sorted(CORE_CHECKS)},
            "gates": gates,
            "supporting_cases": sorted(set(outcomes) & set(SUPPORTING)), "max_age_days": MAX_AGE_DAYS}


def format_verification_report(result):
    """Render only the reviewed status fields, never task text or artifact bodies."""
    counts = result["recorded_failure_counts"]
    lines = ["Local model verification: " + result["recommended_label"],
             "Reviewed local evidence only; not attestation or global readiness.",
             f"Recorded failures retained: {result['recorded_failures']} "
             f"(CLI: {counts['isolated_cli']}; Desktop: {counts['desktop']})"]
    if result["binding_changed"]:
        lines.append("Desktop evidence binding changed: " + ", ".join(result["binding_changed"]))
    for title, gates in (("Isolated CLI", result["cli_gates"]), ("Desktop", result["gates"])):
        lines.extend(["", title + ":"])
        for case, gate in sorted(gates.items()):
            reasons = ", ".join(reason.replace("_", " ") for reason in gate["reasons"])
            lines.append(f"  {'PASS' if gate['passed'] else 'NOT PASSED'} {case}" +
                         (": " + reasons if reasons else "") +
                         (" [final report: " + gate["final_text_policy"] + "]"
                          if gate.get("final_text_policy") else ""))
    lines.extend(["", "No inference, catalog, permission or service changes performed."])
    return "\n".join(lines)
