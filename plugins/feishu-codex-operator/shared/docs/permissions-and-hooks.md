# Permissions and Hooks

The plugin contributes two separate one-tool MCP servers: Final Callback
submits the final answer; the Beeper-only relay server consumes prepared input
and returns a fixed, data-escaped program without sending to Desktop itself.
Beeper executes that program in its existing exec context; only Desktop's native
send tool dispatches the request. This is not permission to evaluate arbitrary
tool text. It also contributes two project lifecycle
Hooks, and no UserPromptSubmit or Stop Hook.

Review Hooks in Codex Desktop under “设置 → 钩子”. Enable and trust only the
project SessionStart and SessionEnd rows after checking that their command paths
resolve below the current project's `.codex\hooks` directory. Do not use
“信任全部”.

SessionStart acquires an Operator lease and may start the installed Operator only
after source/runtime and manifest checks. SessionEnd releases that lease. Hooks
never route a business message, query a task, call Final Callback, or contact
Feishu directly.

Codex Desktop has no `/hooks` chat command. If CLI inspection is needed, first follow
the [upgrade identity checklist](../../development/docs/upgrade-checklist.md#1-开始前建立本轮身份与保护范围)
to resolve and verify the exact CLI from the current official installation or an explicitly
configured executable. Then use that CLI's Hook inspection only if the selected version exposes it.
Do not select a cached executable merely by modification time, use a PATH-selected CLI,
or copy a username/version hash. A missing CLI inspection capability does not justify
changing Hooks or restarting Desktop; its settings remain the first choice.
