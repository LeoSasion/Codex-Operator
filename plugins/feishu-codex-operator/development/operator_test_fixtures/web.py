"""Original synthetic protocol inputs and constructors, without TestCase imports."""
from copy import deepcopy
import json
from operator_core.model_registry import ModelRegistry
from operator_core.responses_tool_adapter import EXEC_GRAMMAR
from operator_core.web_model_protocol import WebModelProtocol
from . import PLUGIN_ROOT


CAPS = {"protocol": "responses-tools-v1", "function_tools": True,
    "custom_tools": {"exec": "wrap"}, "tool_choice": ["auto", "none", "required"],
    "named_tool_choice": "native", "parallel_tool_calls": False, "tool_search": True,
    "input_modalities": ["text"], "structured_tool_outputs": False,
    "developer_role": "native", "reasoning_input": True, "reasoning_summary": False,
    "previous_response_id": False, "text_verbosity": False, "codex_tool_mode": "code_mode_only",
    "completed_output_policy": "require_message_or_tool"}
SLUG = "api/chatgpt-web/gpt-5.6-sol"
ROW = {"slug": SLUG, "display_name": "Web GPT-5.6 Sol contract fixture", "model": "gpt-5.6-sol",
    "api_base": "http://127.0.0.1:1/v1", "api_key_env": "", "context_window": 32000,
    "reasoning_efforts": ["high"], "responses": CAPS}
BEEPER = json.loads((PLUGIN_ROOT /
    "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))
EXEC = {"type": "custom", "name": "exec", "description": "Native Codex exec",
    "format": {"type": "grammar", "syntax": "lark", "definition": EXEC_GRAMMAR}}
FUNCTION = {"type": "function", "name": "inspect", "description": "Synthetic read",
    "parameters": {"type": "object", "properties": {"value": {"type": "string"}},
                   "required": ["value"], "additionalProperties": False}}
SOURCE = '// @exec: {"max_output_tokens": 23}\r\ntext("中文😀 C:\\\\tmp\\\\a_b");\n'


def make(payload=None, **caps):
    row = deepcopy(ROW)
    row["responses"].update(caps)
    route = ModelRegistry({"version": 2, "models": [row]}, BEEPER).routes[SLUG]
    body = {"model": SLUG, "input": "Synthetic request", "tools": [],
            "reasoning": {"effort": "high"}, "stream": True}
    if payload:
        body.update(payload)
    return WebModelProtocol(route, body)


def message(parts=None, **changes):
    return {"id": "web_message_1", "author": {"role": "assistant"}, "recipient": "all",
            "status": "finished_successfully", "channel": "final", "end_turn": True,
            "content": {"content_type": "text", "parts": parts or ["Synthetic answer"]}, **changes}


def response(protocol, *items, **changes):
    return {"id": "response_web_1", "object": "response", "model": protocol.route.model,
            "status": "completed", "output": list(items), "usage": None, **changes}
