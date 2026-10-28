"""Exact synthetic event fragmentation and text fixtures; no transport or execution."""
from operator_core.responses_tool_adapter import dumps
from .responses import response


def events_for(*items):
    events = [{"type": "response.created", "response": response(status="in_progress")}]
    for index, item in enumerate(items):
        argument_key = "input" if item["type"] == "custom_tool_call" else "arguments"
        added = {**item, "status": "in_progress", argument_key: ""}
        events.append({"type": "response.output_item.added", "output_index": index, "item": added})
    # Interleave chunks from every call to exercise independent output indices.
    for part in range(3):
        for index, item in enumerate(items):
            key = "input" if item["type"] == "custom_tool_call" else "arguments"
            value = item[key]
            start, end = len(value) * part // 3, len(value) * (part + 1) // 3
            prefix = ("response.custom_tool_call_input." if key == "input"
                      else "response.function_call_arguments.")
            events.append({"type": prefix + "delta", "item_id": item["id"],
                           "output_index": index, "delta": value[start:end]})
    for index, item in enumerate(items):
        key = "input" if item["type"] == "custom_tool_call" else "arguments"
        prefix = ("response.custom_tool_call_input." if key == "input"
                  else "response.function_call_arguments.")
        events.append({"type": prefix + "done", "item_id": item["id"],
                       "output_index": index, key: item[key]})
        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    events.append({"type": "response.completed", "response": response(*items)})
    return events



def sparse_events_for(*items):
    # Arguments may appear first in output_item.done, without delta/done events.
    return [event for event in events_for(*items)
            if not event["type"].startswith(("response.function_call_arguments.",
                                              "response.custom_tool_call_input."))]



def wire(events, newline=b"\n"):
    return b"".join(b"event: " + e["type"].encode() + newline +
                    b"data: " + dumps(e).encode() + newline + newline for e in events)



def text_events(text, *, part_type="output_text"):
    reasoning = part_type in {"summary_text", "reasoning_text"}
    collection = "summary" if part_type == "summary_text" else "content"
    index_key = "summary_index" if collection == "summary" else "content_index"
    value_key = "refusal" if part_type == "refusal" else "text"
    part = {"type": part_type, value_key: text}
    item = {"id": "text_1", "type": "reasoning" if reasoning else "message",
            "status": "completed", collection: [part]}
    if not reasoning:
        item["role"] = "assistant"
    prefix = {"output_text": "response.output_text", "refusal": "response.refusal",
              "summary_text": "response.reasoning_summary_text",
              "reasoning_text": "response.reasoning_text"}[part_type]
    common = {"item_id": item["id"], "output_index": 0, index_key: 0}
    events = [{"type": "response.created", "response": response(status="in_progress")},
              {"type": "response.output_item.added", "output_index": 0,
               "item": {**item, "status": "in_progress", collection: []}}]
    part_prefix = ("response.reasoning_summary_part" if collection == "summary"
                   else "response.content_part")
    if part_prefix:
        events.append({"type": part_prefix + ".added", **common, "part": {**part, value_key: ""}})
    for char in text:
        events.append({"type": prefix + ".delta", **common, "delta": char})
    events.append({"type": prefix + ".done", **common, value_key: text})
    if part_prefix:
        events.append({"type": part_prefix + ".done", **common, "part": part})
    events.extend([{"type": "response.output_item.done", "output_index": 0, "item": item},
                   {"type": "response.completed", "response": response(item)}])
    return events
