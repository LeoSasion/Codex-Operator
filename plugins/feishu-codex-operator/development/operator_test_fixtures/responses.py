"""Original synthetic protocol inputs and constructors, without TestCase imports."""
from copy import deepcopy
import json
from operator_core.responses_capabilities import ResponsesCapabilities
from operator_core.responses_tool_adapter import (
    APPLY_PATCH_GRAMMAR_0160, EXEC_GRAMMAR, dumps, prepare_request,
)
from . import PLUGIN_ROOT


CAPABILITIES = {
    "protocol": "responses-tools-v1", "function_tools": True,
    "custom_tools": {"exec": "wrap"}, "tool_choice": ["auto", "none", "required"],
    "named_tool_choice": "native", "parallel_tool_calls": True, "tool_search": True,
    "input_modalities": ["text"], "structured_tool_outputs": False,
    "developer_role": "native", "reasoning_input": True, "reasoning_summary": False,
    "previous_response_id": False, "text_verbosity": False, "codex_tool_mode": "code_mode_only",
}
EXEC = {"type": "custom", "name": "exec", "description": "Run JavaScript using tools.",
        "format": {"type": "grammar", "syntax": "lark", "definition": EXEC_GRAMMAR}}
PATCH = {"type": "custom", "name": "apply_patch", "description": "Native freeform patch.",
         "format": {"type": "grammar", "syntax": "lark", "definition": APPLY_PATCH_GRAMMAR_0160}}
PATCH_SOURCE = ('*** Begin Patch\r\n*** Update File: synthetic-中文😀.py\r\n@@\r\n'
                '-    return "C:\\new\\file\\n"  \r\n+    return "C:\\new\\file\\n改"  \r\n'
                '*** End Patch\r\n')
FUNCTION = {"type": "function", "name": "add", "description": "Add numbers.",
            "parameters": {"type": "object", "properties": {"a": {"type": "number"}}}}
CODE = '// @exec: {"max_output_tokens": 23}\r\ntext("中文😀\\n\\"");\ntext("\\\\");\u2028\u2029'
ROUTE = {"slug": "local/protocol", "display_name": "Protocol fixture", "model": "fixture",
         "api_base": "http://127.0.0.1:1/v1", "api_key_env": "", "context_window": 32768,
         "reasoning_efforts": ["low", "max"], "responses": CAPABILITIES}
BEEPER = json.loads((PLUGIN_ROOT /
                    "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))


def prepare(payload=None, **changes):
    caps = ResponsesCapabilities.parse({**deepcopy(CAPABILITIES), **changes})
    return prepare_request(payload or {"tools": [EXEC], "input": "Synthetic input."}, caps, ("low", "max"))


def call(context, code=CODE, *, name="exec", namespace=None, call_id="call_1", item_id="fc_1"):
    spec = context.specs[("custom", namespace, name)]
    return {"type": "function_call", "id": item_id, "call_id": call_id,
            "name": spec.upstream_name, "arguments": dumps({"input": code}), "status": "completed"}


def response(*items, status="completed"):
    return {"id": "resp_1", "object": "response", "status": status, "output": list(items),
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, "model": "fixture"}
