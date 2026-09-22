"""Local one-shot input retrieval; never invokes Desktop or transports answers."""
from pathlib import Path
from contextlib import closing
import json
import sqlite3
import sys

# The plugin launches with -I -S. Admit only its own adjacent source modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from final_callback_mcp_server import FinalCallbackError, _verified_runtime, main
from operator_core.final_callback import FinalCallbackStore, FinalCallbackStoreError
from operator_core.user_tasks import DATABASE_NAME, REQUEST_ID, UserTaskError, UserTaskStore, setup_program
from operator_core.channel_models import model_arguments, ModelSelectionError

TOOLS = [{
    "name": "take_relay",
    "description": "Fixed Operator task only: consume one locally prepared business relay or owner-granted user-task registration. In the SAME exec, execute the Operator-generated structuredContent.code with eval(code)(), keeping the retrieval start time in const started. Never print or rewrite the program, inspect its payload, send separately, or retry. Registration uses the native project and create tools, then saves only returned task identity; it does not execute user work. If a created_thread_directive is returned, include that exact directive in the final. This is bookkeeping, not authentication or exactly-once execution.",
    "inputSchema": {
        "type": "object", "properties": {"request_id": {
            "type": "string", "pattern": "^[a-f0-9]{32}$", "minLength": 32, "maxLength": 32,
        }}, "required": ["request_id"], "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": False, "destructiveHint": False,
                    "idempotentHint": False, "openWorldHint": False},
}]


def relay_program(dispatch: dict | None) -> str:
    """Build trusted control code; request text is only an escaped JSON value."""
    if dispatch is not None and (
        not isinstance(dispatch, dict)
        or set(dispatch) not in ({"threadId", "hostId", "prompt"}, {"threadId", "hostId", "prompt", "model", "thinking"})
        or any(not isinstance(value, str) or not value for value in dispatch.values())
    ):
        raise FinalCallbackError("invalid prepared relay; do not retry")
    if dispatch is not None and "model" in dispatch:
        try:
            model_arguments({"model": dispatch["model"], "thinking": dispatch["thinking"]})
        except ModelSelectionError as exc:
            raise FinalCallbackError("invalid prepared model choice; do not retry") from exc
    payload = json.dumps(dispatch, ensure_ascii=True, separators=(",", ":"))
    return (
        "(async()=>{\n"
        "const preparation_ms=Date.now()-started;\n"
        "if(!Number.isFinite(preparation_ms)||preparation_ms<0||preparation_ms>2000)"
        'throw Error("Relay preparation expired; stop without retry");\n'
        "const dispatch=" + payload + ";\n"
        'if(dispatch===null){text({state:"already_consumed_or_closed",model_selection_contract:"native_next_turn_v1",preparation_ms});return;}\n'
        'const matches=ALL_TOOLS.filter(t=>t.name.endsWith("__send_message_to_thread"));\n'
        'if(matches.length!==1||typeof tools[matches[0].name]!=="function")'
        'throw Error("Desktop send unavailable; stop without retry");\n'
        "const sent=await tools[matches[0].name](dispatch);\n"
        'text({state:sent.isError?"send_error":"send_returned",preparation_ms});\n'
        "})"
    )


def call_tool(name, arguments):
    if name != "take_relay" or not isinstance(arguments, dict) or set(arguments) != {"request_id"}:
        raise FinalCallbackError("invalid relay tool or arguments")
    if not isinstance(arguments["request_id"], str) or not REQUEST_ID.fullmatch(arguments["request_id"]):
        raise FinalCallbackError("invalid request id")
    try:
        runtime, _ = _verified_runtime()
        # Management uses a distinct table and no business content or Final
        # Callback. The same one-shot retrieval surface preserves existing MCP
        # permissions; a request can never select its own program or project.
        if (runtime / DATABASE_NAME).exists():
            setup_store = UserTaskStore(runtime)
            if setup_store.get(arguments["request_id"]) is not None:
                callback_db = runtime / "callbacks.sqlite3"
                if callback_db.exists():
                    with closing(sqlite3.connect(callback_db.as_uri() + "?mode=ro", uri=True, timeout=0.1)) as db:
                        collision = db.execute("SELECT 1 FROM final_callback_requests WHERE request_id=?", (arguments["request_id"],)).fetchone()
                    if collision:
                        raise UserTaskError("user_task_request_collision")
                return {"code": setup_program(setup_store.take(arguments["request_id"]))}
        dispatch = FinalCallbackStore(runtime / "callbacks.sqlite3", busy_timeout_seconds=0.1).take_relay(
            arguments["request_id"])
    except (OSError, sqlite3.Error, FinalCallbackStoreError, UserTaskError) as exc:
        raise FinalCallbackError("relay preparation unavailable; do not retry") from exc
    return {"code": relay_program(dispatch)}


if __name__ == "__main__":
    raise SystemExit(main(tool_handler=call_tool, tools=TOOLS, server_name="feishu-operator-relay"))
