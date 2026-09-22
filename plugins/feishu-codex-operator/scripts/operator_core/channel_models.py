"""Task-scoped, explicit model selection; Desktop still owns dispatch/execution."""
from __future__ import annotations

import os
import re
import time
import uuid

from .app_server import AppServerSession

MODEL = re.compile(r"gpt-[a-z0-9][a-z0-9.-]{0,78}\Z")
THREAD = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z")
EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
FIELD = "model_selection"
HELP = "发送 /model list 查看模型；/model <模型> [思考强度] 为下一条新消息选择；/model cancel 取消待应用选择。"


class ModelSelectionError(ValueError):
    pass


def model_arguments(value):
    if (not isinstance(value, dict) or set(value) != {"model", "thinking"}
            or not isinstance(value["model"], str) or not MODEL.fullmatch(value["model"])
            or "spark" in value["model"] or not isinstance(value["thinking"], str)
            or value["thinking"] not in EFFORTS):
        raise ModelSelectionError("invalid_model_selection")
    return dict(value)


def pending_arguments(session):
    selection = session.get(FIELD)
    if selection is None:
        return None
    if (not isinstance(selection, dict)
            or selection.get("thread_id") != session.get("thread_id")
            or selection.get("host_id") != (session.get("host_id") or "local")
            or selection.get("state") not in {"pending", "requested"}
            or not isinstance(selection.get("id"), str)
            or not re.fullmatch(r"[a-f0-9]{32}", selection["id"])):
        raise ModelSelectionError("model_selection_binding_changed")
    arguments = model_arguments({"model": selection.get("model"), "thinking": selection.get("thinking")})
    return arguments if selection["state"] == "pending" else None


class NativeModelCatalog:
    def __init__(self, config):
        self.config = config

    def read(self, session):
        from .beeper_relay import discover_codex_executable
        thread_id = session.get("thread_id", "")
        if (not isinstance(thread_id, str) or not THREAD.fullmatch(thread_id)
                or thread_id == self.config.beeper_thread_id
                or (session.get("host_id") or "local") != "local"):
            raise ModelSelectionError("model_task_unavailable")
        # The native provider can be redirected without changing its name.
        # Never treat a catalog obtained through that override as direct-native.
        if os.environ.get("OPENAI_BASE_URL"):
            raise ModelSelectionError("model_native_route_unverified")
        with AppServerSession(discover_codex_executable(self.config.codex_executable),
                              self.config.app_server_timeout_seconds) as api:
            api.deadline = time.monotonic() + self.config.app_server_timeout_seconds
            config = api.request("config/read", {"includeLayers": False})
            config = config.get("config") if isinstance(config, dict) else None
            if (not isinstance(config, dict) or (config.get("model_provider") or "openai") != "openai"
                    or config.get("openai_base_url") is not None
                    or config.get("model_catalog_json")
                    or not isinstance(config.get("model_providers", {}), dict)
                    or config.get("model_providers", {}).get("openai")):
                raise ModelSelectionError("model_native_route_unverified")
            raw = api.request("thread/read", {"threadId": thread_id, "includeTurns": False})
            task = raw.get("thread") if isinstance(raw, dict) else None
            if (not isinstance(task, dict) or task.get("id") != thread_id
                    or task.get("ephemeral") is not False or task.get("modelProvider") != "openai"):
                raise ModelSelectionError("model_task_provider_unverified")
            page = api.request("model/list", {"includeHidden": False, "limit": 100})
        if (not isinstance(page, dict) or not isinstance(page.get("data"), list)
                or len(page["data"]) > 100 or page.get("nextCursor") is not None):
            raise ModelSelectionError("model_catalog_incomplete")
        rows, seen = [], set()
        for row in page["data"]:
            if not isinstance(row, dict):
                raise ModelSelectionError("model_catalog_invalid")
            name = row.get("model")
            if not isinstance(name, str) or name in seen:
                raise ModelSelectionError("model_catalog_invalid")
            seen.add(name)
            if row.get("hidden") is not False or not MODEL.fullmatch(name) or "spark" in name:
                continue
            choices = row.get("supportedReasoningEfforts")
            if not isinstance(choices, list) or len(choices) > len(EFFORTS):
                raise ModelSelectionError("model_catalog_invalid")
            efforts = [r.get("reasoningEffort") if isinstance(r, dict) else None for r in choices]
            default = row.get("defaultReasoningEffort")
            if any(not isinstance(e, str) or e not in EFFORTS for e in efforts) or default not in efforts:
                raise ModelSelectionError("model_catalog_invalid")
            rows.append({"model": name, "efforts": efforts, "default": default})
        # Never retain native preview, path, turns or user content.
        current = {"model": task.get("model"), "thinking": task.get("reasoningEffort")}
        return rows, current


class ChannelModels:
    def __init__(self, config, sessions, catalog=None):
        self.config, self.sessions = config, sessions
        self.catalog = catalog or NativeModelCatalog(config)

    def command(self, scope, session, argument):
        if not session.get("thread_id"):
            return "请先用 /init 连接一个业务任务，再选择模型。"
        if session.get("thread_id") == self.config.beeper_thread_id:
            return "Beeper 不能用作业务任务；请先用 /init 连接业务任务。"
        parts = argument.split()
        if len(parts) > 2:
            return HELP
        if parts == ["cancel"]:
            self.sessions.update_model_selection(scope, session, None)
            return "已取消待应用的模型选择。后续消息沿用 Desktop 任务设置；已发出的消息不受影响。"
        rows, current = self.catalog.read(session)
        if not parts:
            model = current.get("model")
            effort = current.get("thinking")
            name = model if isinstance(model, str) and MODEL.fullmatch(model) else "暂未读到"
            label = effort if isinstance(effort, str) and effort in EFFORTS else "原生默认"
            answer = f"当前原生任务设置：{name} / {label}。"
            pending = pending_arguments(session)
            if pending:
                answer += f"\n下一条新消息：{pending['model']} / {pending['thinking']}（待应用）。"
            elif session.get(FIELD):
                answer += "\n上次选择已交给单次发送流程；上方为当前读回设置，不代表那条消息执行成功。"
            return answer + "\n" + HELP
        if parts == ["list"]:
            return ("当前任务可选的官方模型：\n" + "\n".join(
                r["model"] + " · " + "/".join(r["efforts"]) for r in rows)
                + "\n例：/model luna low。API、本地和 Web 模型待原生路由接入后开放。")
        name = parts[0].casefold()
        candidates = [r for r in rows if name in {r["model"], r["model"].rsplit("-", 1)[-1]}]
        if len(candidates) != 1:
            return "没有找到唯一可用的官方模型。请用 /model list 查看准确名称。"
        chosen = candidates[0]
        effort = parts[1].casefold() if len(parts) == 2 else chosen["default"]
        if effort not in chosen["efforts"]:
            return "这个模型不支持该思考强度。可选：" + "/".join(chosen["efforts"]) + "。"
        selection = {"id": uuid.uuid4().hex, "thread_id": session["thread_id"],
                     "host_id": session.get("host_id") or "local", "state": "pending",
                     "model": chosen["model"], "thinking": effort}
        self.sessions.update_model_selection(scope, session, selection)
        return f"已保存：{chosen['model']} / {effort}，将在当前任务的下一条新消息上应用。发送后可用 /model 读回原生设置。"

    def prepare(self, session):
        arguments = pending_arguments(session)
        if arguments:
            rows, _ = self.catalog.read(session)
            if not any(r["model"] == arguments["model"] and arguments["thinking"] in r["efforts"] for r in rows):
                raise ModelSelectionError("model_selection_no_longer_available")
        return arguments
