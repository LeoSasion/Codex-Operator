# Beeper E2E lessons

Read the success criteria for live work, then the relevant dated case. The latest owner-private
text case is [recorded below](#直接授权后的同范围新请求); simulation, legacy model choices and failed
production attempts remain separate. A previous approval in this document is not a grant for another user.

## What success means

Do not treat queue exit zero, a visible Desktop answer, a completed Responder
turn, or a message merely seen inside Codex as E2E success. Success requires the
exact marker to return to the same Feishu chat from the bot, tied to the exact
sent message, after the Final Callback and Operator delivery path.

For each live sample:

1. Confirm one exact owner P2P binding, verify the current `lark-cli` user
   identity matches it, and confirm the Operator is ready with zero active turns
   and zero pending callbacks.
2. Send one harmless plain-text request with a unique marker and a deterministic
   idempotency key. Never retry a send whose outcome is uncertain.
3. Run samples sequentially. Wait for the prior request to settle before sending
   the next one, and observe only a bounded recent window without downloading
   resources.
4. Match the bot reply to the sent message and require byte-exact marker text.
   Record elapsed time and the terminal path, including exact failure text.
5. Restore empty diagnostic overrides, restart, and verify the normal selected
   policy before declaring the experiment complete.

## Failure and debugging lessons

- Preserve one Beeper wake-up signal after a successful queue when the wake
  lease is inactive. In observed inactive states, queueing without the signal
  did not reliably begin until the Beeper task was made active in Desktop. A
  process-local 30-minute wake lease suppresses frequent signals, but only
  attributed Responder activity or a Final Callback refreshes it. If a request
  with an active lease has no downstream evidence for 30 seconds, invalidate
  the assumption and send the signal once. It must never carry request data,
  requeue the request, or target the Responder.
- `itemsView=notLoaded` is the observer's requested content-free projection,
  not a returned foreground, residency, wake-state, or task-load signal. Do not
  use it as the wake-lease source of truth.
- Separate execution time from callback time. Explicit running evidence has no
  deadline; a stable terminal turn gets only the short callback grace; unknown
  state uses the longer unknown window. A single 3600-second timeout concealed
  failures and made iteration needlessly slow.
- High reasoning is not a delivery guarantee: one Spark/high sample completed
  without a callback. Conversely, five Spark/low English successes do not prove
  that low is safe as the normal default.
- The lifecycle observer is metadata-only. It can distinguish running,
  terminal, and unknown states but cannot replace Final Callback or use Desktop
  output as answer transport.
- Immediately after restart, readiness can remain false while the initial quota
  read and event consumer start. Wait for a fresh health snapshot; do not label
  this short startup interval as a relay failure.
- A new diagnostic value must be admitted consistently by Python config,
  PowerShell validation, health parsing, tests, docs, and the release audit.
  Otherwise the Operator may run correctly while status reports an invalid health
  snapshot.
- Before running isolated tests, verify the exact Operator is stopped rather than
  trusting that a stop command addressed the intended project. When invoking
  the controller outside the repository root, pass the exact `-ProjectRoot`.
- Prompt-localization tests should prove the envelope and payload invariants.
  If a wording-only change trips a banned-word assertion, distinguish actual
  injected history from harmless control vocabulary; never relax the no-history
  transport contract merely to make the test pass.

## Comparison discipline

Use the same Responder, Feishu scope, request text, prompt language, model,
reasoning effort, timeout policy, and success definition for paired comparisons.
Verify effective Beeper model and reasoning effort from bounded, explicit
diagnostic metadata for each sample; report unknown if unavailable. Do not
add transcript inspection to the ordinary runtime or use it as answer transport.
Report the numerator and denominator plus individual durations. Treat fewer than
roughly 20 samples per variant as directional evidence. Preserve failures in the
result rather than rerunning them, because replay would bias the success rate and
can duplicate user work.


## 2026-10-29：正式绑定恢复与发布边界

- 新版本代码部署必须逐项比较运行时、启动 Hook 和插件缓存；包版本相同或运行时文件清单相同，不代表 Hook 逻辑已经同步。alpha.145 对一个经过审查的完整旧、新 Hook 摘要对提供独立备份与恢复；其他逻辑漂移仍停止升级。
- 原生会话 UUID 缺失时，不按标题找替代。由所有者明确选择新建正式 Beeper 与业务会话，先核对原生项目、实际模型和 effort，再以 CAS 替换绑定并保留旧 UUID。仿真聊天不自动转为正式聊天。
- 异常退出的 Web 实例与正常停止是不同凭据。先检查确切进程、依赖、端口和保留原件，显式归档后才能使用恢复凭据升级；不得伪造 stopped、重启或重放历史请求。
- 旧目录清理可能同时删除退休隧道标记。所有者明确选择新归档目录后，只从完整恢复原件逐字保留退休标记，并保存独立迁移凭据。核验绑定原回执摘要、原路径缺失、新文件内容和完整恢复历史；不改旧回执、不建立活动标记，不恢复隧道或密钥。旧路径出现新文件或新副本被修改均停止维护。
- 原生解释器身份也是恢复凭据的一部分。刷新源码登记应沿用原解释器；系统 Python 缺少运行依赖的测试失败不能视为功能通过。保留失败记录，在已安装的完整依赖解释器下验证修正后的用例。

- 升级最终写入与隔离测试应顺序进行；测试子进程退出期间，Windows 进程命令行可能暂时无法观察，维护必须保持拒绝。失败事务保留并独立审查恢复，不能重试原事务。后续真实绑定变化需要新的预览与原件快照。

- 同步完成后还要分别核对启动与停止 Hook。alpha.146 将一个经过审查的停止 Hook 完整摘要对纳入独立保留和恢复；只更新停止 Hook 时，启动 Hook 保持原字节。清单最后写入失败也必须能恢复两者原件。

- 根 AGENTS.md 可同时包含其他项目指令。启动前只按严格 UTF-8、唯一独占行标记、完整顺序和受管块正文验证 Operator 镜像，允许 LF/CRLF 与文件开头 BOM，不要求整文件哈希一致；块外内容不改写。BOM 必须按首字符精确判断，不能使用可能忽略零宽字符的文化相关前缀比较。

### 从工具可见到真实转交

本机恢复出现了两个不同失败样本，均保留且没有重放。第一组正式会话只完成文字初始化，
之后 Beeper 自述工具不可见，却没有真实 exec 证据。插件页和新原生进程能列出工具，
仍不能据此判定那个会话可以执行，也不能单独证明缓存或模型是根因。

所有者明确批准新候选后，两者首轮实际调用了 MCP：Beeper 为 GPT-6 Luna/low，业务候选为
GPT-6.1 Terra/low。预检 ID 先在 callback 与用户登记库核对不存在；relay 返回无转交程序，
callback 返回 `accepted=false/state=unknown`。配对 exec 输出、准确调用参数及预检前后旧行
不变均已核对。这只完成工具预检，没有给真实消息添加回调记录、授权或成功结果。

随后一条全新飞书消息确实进入 Operator。Beeper 逐字执行四行 bootstrap、取得 relay 并
调用原生发送工具；跨会话发送失败，界面显示“需要明确授权”。`relay_started=1` 仅表示
输入已被消费，不能说明业务已经开始。失败回调关闭，队列进入 `completed` 是失败通知
已送达的记录，不能改判为业务收发通过。

| 证据 | 能证明的范围 | 下一道独立检查 |
|---|---|---|
| 插件已启用、MCP 服务可见 | 当前登记或服务加载 | 准确候选中的真实 exec/MCP 配对输出 |
| 无业务 ID 的 MCP 预检返回 | 该候选调用了实际工具 | 原生跨会话发送是否被接受 |
| 原生发送正常返回 | 一次调用返回，不是业务完成 | 新业务回合及精确 Final Callback |
| 回调与同一飞书私聊的精确机器人回复 | 该条新请求的实际业务往返 | 保留其版本、身份及失败样本边界 |

用户在主对话授权配置和单次验收，不自动成为 Beeper 可见的持续跨会话权限。一次把持续
授权确认委托给 Beeper 的控制消息也被复核拒绝；处理方式是保留拒绝，直接向用户确认
明确缺少的范围。不能由程序生成授权声明、关闭审批、改发其他会话或用新提示绕过拒绝。
用户确已授予的范围继续复用，不把所有初始化都变成重复确认。后续许可只用于不同的新请求。

生成程序现在对原生发送失败输出固定诊断并抛出固定错误，让失败保持可观察：

| reason | 含义 |
|---|---|
| `native_send_tool_error` | 原生工具明确返回 `isError=true`，不推断审批、网络或接收方原因 |
| `native_send_exception` | 原生调用抛异常，结果不明 |
| `invalid_native_send_result` | 返回形状或 `isError` 类型不合法，结果不明 |

错误正文可能包含请求、凭据或路径，不复制到生成程序的诊断中。具体审批原因仍查原生
工具原件或准确界面。`send_returned` 只表示发送调用返回，不是成功业务回复；以上所有
失败或不明结果都没有重试，也不改变回调关联、模型、权限、正文或 2000 ms 准备期限。

停止命令在退出竞争时若报告 Python 身份不可确认，先复核准确 PID、健康快照和待处理数。
本轮随后观察到原进程已退出、健康为 stopped、回调为零；保留最初异常，不强制结束不明进程，
不把命令异常本身当作仍在运行或正常停止的证明。

### 直接授权后的同范围新请求

后续所有者在主对话直接明确授予本人已绑定私聊今后的固定转交。保留原话与来源后，
仅把准确应用、用户、私聊和现有目标的范围转达固定 Beeper；控制消息不自成授权，
没有代替用户批准，也没有更改原生审批或业务工具权限。Beeper 在同一 UUID 完成一次
全新无业务 ID 的实际 MCP 预检，旧数据库行与绑定字节在该预检前后相同。

preview.7 / alpha146 随后仅发送一条新的真实飞书私聊验收请求。核验实际
GPT-6 Luna/low 的四行 bootstrap、一次原生转交的完整参数与 `send_returned`；
准备阶段为 43 ms，不等于整轮延迟。准确业务 UUID 的实际 GPT-6.1 Terra/low
回合仅提交本次精确 Final Callback，配对输出为 `accepted=true/state=captured`，
最终文本相同。飞书接口读回同一私聊的原用户请求和唯一机器人回复，核对 sender、
app、bot、reply_to 和完整原文。入队尝试为一，回调关闭后待处理与活动数均为零。
旧失败行逐字段保持原样，旧 UUID 保留，没有重放；Channels 留在已核验的在线状态。

真实业务期间，`on_dispatching` 和完成路径会调用 `SessionStore.bind_thread`，
该方法刷新 `updated_at` 并保存。因此“业务前后整个 sessions 文件哈希相同”不是正确的
成功标准。本轮首次整文件哈希比较确实失败，原失败保留；业务前仅保存了摘要，缺少该时点
完整文件，不能反推“仅时间戳字节变化”或宣布整文件保护通过。后续分别核对准确绑定身份、
历史 UUID、其他配置原字节、原数据库行以及独立的业务配对证据，不恢复或修改运行中的会话
文件来满足比较。下一次应在新请求前保留完整原件，再逐字段核对预期变化。

生命周期命令的参数也要按实际支持范围使用：`channels start|stop` 不带 `-Json`，
机器读取状态使用 `channels status -Json`。本轮初次启动被参数校验拒绝，尚未发生生命周期
动作；保留该失败后才执行参数正确的新启动，不把它描述为重复业务执行或产品修复。

这只证明当前所有者、这一准确私聊、这一对正式 UUID 和普通文本单次回传。
第二用户、附件、群聊/话题、续聊、其他工具审批与异常恢复仍须各自验收；不能把持续转交
许可当作这些能力的成功证据，也不能把后续通过改写到前两条失败请求中。

## Current explicit selection and simulation (2026-10-29)

The owner explicitly selected `gpt-6-luna` / `low` for Beeper and the current
Terra 6-series entry `gpt-6.1-terra` / `low` for the business task. Admit the
new Luna ID explicitly in Python configuration, relay policy, both PowerShell
environment validators and health parsing. Retain the old default and legacy
cases for compatibility; this explicit selection does not migrate another
installation, change a Responder model, or permit model fallback or replay.

Two owner-approved disposable Desktop tasks completed two different simulated
Feishu requests through the real queue, Beeper input MCP, native task send and
Final Callback MCP. The first preserved Chinese, Emoji, a Windows path and
quotes; the second continued the same business task. The local Feishu sink
received one exact reply for each request, at 15.027 s and 15.028 s. Repeating
each admitted event caused no additional queue or reply. Native turn metadata
confirmed the exact models and low effort; both callback rows closed after one
relay consumption, with prior rows and the callback registration unchanged.
This is a two-sample simulated-transport observation, not real Feishu delivery,
statistical reliability or acceptance of the old production bindings.

The saved old Beeper and Responder UUIDs were not found by the native reader and
exact same-home index. Retain those UUIDs; do not adopt another task by title or
create replacements automatically. Here the owner separately approved two new
test tasks, which were archived after verification. Plugin skills/tool presence
must be checked from actual tool calls and model metadata, not an assistant
claim or an enabled flag alone. The temporary plugin enablement was restored.

A new invalid-effort fixture exposed a prior health-reporting defect: parsing
could raise `invalid_health_snapshot` after setting `valid=true`. Clear that
flag on every parsing failure. Preserve the original failed run and exercise
both old and new Luna invalid efforts. Account quota rejection fixtures need
the existing explicit reached signal; a percentage alone is not that signal.

## Previous owner selection (2026-09-21)

The fixed relay task is named **Beeper**. At that checkpoint, the owner selected **Luna/low only**
for online relay work and reports Spark retired; do not run new Spark probes.
The historical measurements below remain unchanged. The deterministic local
`beeper` is a different implementation for the same relay role, not a separate
business task, and remains dormant pending native integration.

This installation again demonstrated why requested and effective models differ:
the channel health and queue selected Luna/low, while the recent fixed-task turn
metadata still reported Astra/high inherited from task creation. A native
`send_message_to_thread` call with explicit Luna/low, containing only a no-tool
configuration acknowledgement, completed; its actual turn metadata confirmed
Luna/low. No business event was replayed and no Responder setting was changed.
This confirms the new native selection; future ordinary queue execution and
new-user creation remain separate acceptance observations.

Read this reference when changing the Beeper control prompt, model, reasoning
effort, wake-up behavior, lifecycle observation, or live E2E procedure. The
numbers below are bounded observations from one Windows host on 2026-09-04, not
general model guarantees.

## Observed outcomes

The configuration labels in the historical table below are requested settings,
not verified Desktop execution settings. Do not use these rows to compare
reasoning efforts until the matching turn metadata has been checked. Queue
arguments, Operator health, and model policy logs are not execution evidence.

| Beeper configuration | Exact Feishu replies | Observation |
|---|---:|---|
| Spark/low, Chinese control prompt | 1/2 | Small sample with a high failure rate. |
| Spark/medium, Chinese control prompt | 2/3 | One request reached the uncertainty path. |
| Spark/high, Chinese control prompt | 4/5 | One stable terminal turn produced no Final Callback. |
| Luna/low, Chinese control prompt | 3/3 | Clean small sample, not evidence of universal superiority. |
| Spark/medium, English control prompt | 4/4 | All four produced exact replies before the batch was intentionally stopped. |
| Spark/low, English control prompt | 5/5 | Times were 31.846, 26.487, 27.576, 31.903, and 29.459 seconds; mean 29.454 seconds, median 29.459 seconds. |

### Effective settings and code-relay feasibility (2026-09-05)

The alpha.83 five-message batch returned five related Feishu replies, four
exact. Durations were 23.969, 21.714, 15.558, 18.130, and 24.208 seconds.
Operator requested Spark/medium, but all five Desktop `turn_context` records
reported Spark/low, including `collaboration_mode.settings.reasoning_effort`.
These are NOT five medium samples. The fifth Beeper first sent a corrupted
marker, then sent a corrected second message. The first callback captured the
corrupted marker; the corrected Desktop final did not replace it. Operator
queued once, but Beeper sent twice. Count both exactness and duplicate-send
failures rather than treating a related bot reply as success.

Three bounded, non-business probes tested same-cell JavaScript orchestration:
the normal queue, a queue with `--enable code_mode --enable code_mode_only`,
and a Desktop task-tool send explicitly selecting Spark/medium. The first two
executed at low; the third executed at medium. All three returned an unavailable
marker and made no JavaScript orchestration call. This establishes failure of
these probes on this installation, not universal model incompatibility.

Two further owner-authorized project-only probes enabled
`[features.code_mode] enabled=true`, then also `features.code_mode_only=true`.
The Desktop-bundled CLI reported these features enabled, but the existing
Desktop Beeper again returned unavailable markers without an orchestration
call. Both turns actually ran Spark/medium. The second was an ordinary CLI
queue after the earlier Desktop task-tool calibration, establishing that the
saved medium setting survived this queue on this host. It does not establish
that arbitrary queue config overrides are applied. The only JavaScript tool
named by the final probe was the browser CUA tool, not a Desktop-task-tool
executor. Temporary project configuration was removed after the probes.
After a Desktop restart, enabling project code mode before the not-yet-loaded
Beeper was first loaded exposed exec. The first probe dropped the tools prefix;
the corrected probe actually confirmed both nested shell and Desktop send
functions at Spark/medium. A shell-based retrieval probe then took 4.5 seconds
and stopped without sending, failing the 2-second budget. Alpha.84 instead uses
a separate input-only relay MCP in the same exec. Its offline protocol tests
pass, but the live Beeper must reload the newly installed MCP before timing and
Feishu E2E can establish acceptance. Do not call this a measured performance gain.
CLI feature output alone does not prove a live Desktop task's tool inventory.

After the next reload, the input MCP was available in Beeper: an unknown-route
probe took 258 ms. The first alpha.84 real sample used verified Spark/medium,
retrieved input in 80 ms and returned the exact Feishu marker in 31.335 s.
The second sample failed before retrieval: Spark replaced the supplied MCP
namespace with a nonexistent placeholder. No Desktop send occurred; the
batch stopped without replay. Fast successful retrieval alone is therefore
insufficient acceptance evidence. Alpha.85 resolves both functions from the
live ALL_TOOLS inventory by unique suffix before retrieval, instead of asking
the model to preserve long MCP namespaces. Missing or ambiguous inventory
matches stop before consumption. This remains model-executed code, not a
guarantee that the model follows the program. New live samples are required.

Alpha.85 subsequently returned three exact replies in four new real samples
at verified Spark/medium (21.282, 16.730, and 26.348 s). The fourth took 307.600 s
to return an uncertainty notice, not the requested marker. Its 955 ms retrieval
had consumed the correct route, but Spark changed `data.dispatch` to `data.status`
in the branch and skipped sending. The generated diagnostic label incorrectly
said already_consumed_or_closed; durable state proved input had been consumed.
The fifth sample was not sent. Do not infer store state from a model-rewritten
diagnostic label, or hide this failure behind three fast successes.

Alpha.86 moves dispatch validation and fixed control-program generation to the
input MCP. Its code owns timing, null handling, Desktop resolution, and one send;
the model sees only a four-line bootstrap and no control branches. Execute the
returned program directly in the same exec without printing it or resampling.
Quoted text, Unicode separators, and code-like user input must round-trip as
JSON data only. Older MCP payloads must stop rather than fall back to model
copying. A bootstrap can still be rewritten: verify the loaded MCP contract,
same-exec program invocation, timing, and actual Feishu replies before activation.

Alpha.87 adds a deterministic loopback Responses API model named `beeper` and a
private hidden catalog installed with Operator. Offline engine, HTTP/SSE,
catalog-shape, queue-argument, and install-integrity tests cover the fixed
custom-tool call and terminal response. An isolated ephemeral invocation with
the current Desktop-bundled CLI also completed the real Responses/custom-tool
protocol and returned the terminal `DONT_NOTIFY`; this caught that the wire name
is model-facing `exec`, not the application-qualified tool name. It used no live
Desktop task or Feishu event, so it is not evidence that the current Desktop
Beeper loaded the provider or completed a Feishu E2E. Keep local-provider
failures terminal with no Spark/Luna fallback.

Alpha.88 fixes an important gap in the alpha.87 probe: a synthetic
`request_id="..."` input was not the actual relay envelope, which embeds a JSON
colon instead. The provider now matches the shared exact relay template from
the latest user message only. Unit tests exercise the real producer template,
old-history isolation, known-call continuation, and the approved identity text
over JSON and SSE. The catalog uses `visibility: list`, not `hide`.

The current CLI's generated `thread/settings/update` schema permits `model`
and `effort`, but contains no provider/config override. `model/list` has no
provider selector. Official config documentation exposes a startup catalog and
one selected provider, not per-entry provider routing. Neither changing the
catalog nor changing the model string establishes Desktop provider selection.
Dropdown/default integration therefore remains unverified. Preserve normal
Spark/Luna routing and do not modify the running task or global provider to
simulate successful integration.

Do not activate an opaque-payload code relay until a live Beeper invocation
demonstrates both local payload retrieval and Desktop sending in one code
execution, without model resampling between them. A standalone plugin MCP
does not automatically gain access to Desktop's task tools. Fetching payload
in a separate Responder model round trip is not an equivalent implementation:
local I/O timing cannot establish a two-second incremental latency bound.
Keep the existing route until this execution prerequisite and the full-path
latency gate pass. Never replay accepted probe or business messages.

### Wake-up signal observations

The following 2026-09-05 probes bypassed the Feishu entry and delivery edges so
the only changed variable was whether Operator sent the Beeper wake-up signal.
They still used the real
`codex queue -> Beeper -> Responder -> Final Callback` path, one new request per
sample, with no replay:

| Desktop/Beeper condition | Wake-up signal | Exact callbacks | Duration |
|---|---:|---:|---:|
| Reported idle for more than 30 minutes | suppressed | 0/1 | unknown after 98.179 s |
| Same inactive sequence, new request | sent | 1/1 | 66.843 s; likely included earlier accepted backlog |
| Beeper visible and freshly active | suppressed | 1/1 | 17.463 s |
| Beeper active but another task visible | suppressed | 2/2 | 27.094 s, 22.497 s |
| Codex Desktop restarted, new request | suppressed | 0/1 | unknown after 96.703 s |
| Same restart sequence, new request | sent | 1/1 | 41.343 s; likely included earlier accepted backlog |
| Alpha.78 fresh relay client, inactive wake lease | sent immediately | 1/1 | 21.868 s |
| Same alpha.78 client, immediately following active lease | suppressed; no fallback needed | 1/1 | 19.194 s |

These small samples support an active/inactive wake-lease distinction but do
not prove that 30 minutes is the product's exact eviction threshold. They do
show that foreground visibility is unnecessary after a task becomes active,
and that Codex Desktop
can restart while the separate Operator process survives. Therefore a wake lease
alone is insufficient: retain a short no-downstream-evidence fallback that
sends one wake-up signal for the already-accepted Beeper request without
requeueing it.

The alpha.78 smoke pair used the real queue, Beeper, Responder, and Final
Callback path with one accepted request per sample. The inactive-lease sample
attempted exactly one Beeper wake-up signal; the following active-lease sample
attempted none. This
confirms the implemented state transition on this host, but it is still a
two-sample smoke check rather than a statistical reliability claim.

The English prompt correlated with better results in these samples, including
Spark/low, but language, model effort, host load, Desktop state, and time were
not independently controlled. The retained Spark compatibility path used English
for all Operator-authored input, not only the outer Beeper instructions. Preserve
the original user text and losslessly encode attachment metadata. Keep the
Chinese control template for explicit Luna diagnostics, not Spark. Earlier
Chinese Spark samples above remain historical evidence, not a current option.
Do not turn a language choice into an automatic retry. The former recommendation
to keep Spark/medium as the normal policy was superseded by the owner's
2026-09-21 Luna/low choice; these Spark samples are retained as historical evidence,
not a current selection or a reason to run new diagnostics.
