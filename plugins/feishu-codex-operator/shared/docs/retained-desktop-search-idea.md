# 保留思路：统一工具映射与 Desktop 搜索桥接

当前跨模型搜索结果与适配经验已提炼到独立 `codex-model-adaptation` skill。本文的历史搜索设计、原始范围及致谢继续保留；知识迁移不恢复或启用旧搜索桥。

2026-09-14 跟进：容量修复已加载。Huihui 的 exec 调用层级混淆由 LM Studio 日志
确认；单模型 standard 配置已热加载，配置前后两次隔离 CLI 搜索通过，Desktop
刷新及新任务验收仍待完成。旧任务压缩错误未消除。见[具体诊断](../../models/common/docs/model-router.md#local-exec-call-level-diagnosis-20260914)。

状态：**2026-09-12 已按所有者要求恢复统一搜索，采用 Codex 官方独立搜索入口；原替换草案及致谢继续保留。**

最新实现依据：Codex 0.153.4 的独立搜索扩展提供真实 `web.run`，普通函数模式直接调用，
code-mode 通过 `exec` 调用。选择条件为 `features.standalone_web_search=true` 或原生
Responses Lite 模式，并且当前 provider 提供所需命名空间与搜索能力。扩展还要求 provider
为原生 OpenAI、使用 OpenAI actor 授权，或显式支持独立搜索。当前项目入口保持原生
OpenAI provider，Router 已独立透传 `/alpha/search`；无需把 hosted 声明改成虚构函数。

两项隔离 CLI 场景已验证：标准函数和 code-mode 均经 Codex 自身扩展发起一次专用搜索，
缓存/实时模式、查询域名与时间条件、Unicode 和结果保真。全部使用模拟服务及假凭据；
不能据此宣称实际外部模型或真实搜索后端已验收。旧普通 CLI 探测未选用独立搜索功能，
其空工具列表不能证明 Desktop 缺少搜索扩展。`supports_search_tool` 控制的是工具发现，
不是独立网页搜索的选择开关。

另有独立的真实原生搜索接口检查：当前六个外部注册标识各发出一次新的合成文本查询，
均获得 HTTP 200 和非空 SearchResponse.output，零重试。这只验证原生搜索接口接受
这些模型标识，不是模型推理、真实 Desktop 任务或搜索内容正确性的验收。开启的用户
设置仅增加 standalone_web_search，原生 provider、路由入口和原搜索模式均保留。

随后六个模型各执行一次新的、有明确调用指引的隔离 CLI 搜索用例，共十次模型请求、
四次原生搜索，零重试。DeepSeek V4 Flash、GLM 5.3 Flash、Qwen 3.6 27B 和
Huihui Qwen 3.8 27B 均完成真实工具调用、搜索结果回传和最终回答。前三者原用例通过；
Huihui 的官网首页链接被私有脚本错误地要求必须带非空路径，原失败状态保留，另行
只读复核记录其成功搜索往返和链接校验误判，不重新请求模型。Qwen 0.6B 返回文字而
未产生工具调用；Gemma E2B 的响应传输中断，两者均未执行搜索。共享 Router 当时
可见 arguments_done_mismatch 诊断，但它不是逐请求归属证据，不能据此确定 Gemma 根因。
这些用例使用现有 alpha.131 运行配置、普通工具和 code-mode 两种模式；私有临时网关
只放行指定的一次搜索，并在下发前完整检查响应。它们不证明 Desktop 验收、自由选择
工具的能力、首 token 延迟或答案内容正确性；未修改活动注册表或重启服务。

所有者随后明确授权创建四个可见 Desktop 搜索任务。DeepSeek 与 GLM 的官方
App Server 只读快照确认了实际模型、原生 provider 和完成的任务轮次；两者各有一次
原生 webSearch 与十二项结构化结果。MCP 任务读取投影省略了 results 字段，不能
用这一投影中的缺失断言实际搜索未返回结果。GLM 的答案链接与结果 URL 完全一致；
DeepSeek 省略了结果 URL 的查询参数，搜索执行已观察到，但精确链接保真未通过。
两个 Qwen 27B 任务则在最初的 codex_app.create_thread 内容处被拒绝，错误为
named_function_output_not_registered；它们没有执行搜索。冻结运行代码的纯本地
合成检查复现了该错误；只在内存中显式增加既有 create-task codec 后可完成请求
准备，不构成部署或真实模型验收。该首次检查保留四个任务，没有重试或修改运行配置。
这些记录仍不证明 Desktop 精确版本、权限、传输重试计数、完整结果回传的字节
一致性或全部答案语义，也不替代文件操作、审批或全局就绪门槛。

所有者随后要求修复剩余失败。四个现有本地模型仅增加显式
`codex_app.create_thread: user_message_json_v1` 配置；候选、活动注册表和准备摘要
同步留存原件后写入，运行中的 alpha.131 路由单次热加载成功，没有重启或改权限。
旧 alpha.123 启动发现流程不接受这个新来源，原 policy 保持不变；兼容新运行版的
发现 policy 仅另存为待接入内容，尚未配置后续自动发现。

两个已有 Qwen 任务各接收一个新的独立查询，旧失败轮次保留。Qwen 3.6 实际完成
一次 `webSearch`，返回十二项结构化结果；最终官网首页 URL 与结果精确一致。
模型改写了结果标题，未核验全文语义或完整结果回传字节。Huihui 新轮次在接入阶段
收到 `router_busy_no_retry`，零搜索、零结果，尚不能证明它已通过 codec 检查。
当时路由 active 为十六；源码确认 WebSocket 整个连接周期与 HTTP 推理、搜索共用
十六个名额，具备长连接耗尽请求额度的触发路径，但没有逐连接证据证明当时全部空闲。
容量修复需独立部署后另行验收，不能将这次 busy 或原始失败改判成功。

官方版本依据：
- [扩展注册及 provider 条件](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/ext/web-search/src/extension.rs)
- [独立搜索选择与 hosted 声明互斥](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/core/src/tools/spec_plan.rs)
- [Codex 执行器与结果回传](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/ext/web-search/src/tool.rs)

下文为保留的历史设计，不作为当前部署方案。

2026-09-09，项目所有者明确要求暂停这一开发方向，将方案记录为 Markdown，
并在没有明确删除要求时保留。常规整理、升级、重构、合并或清理未完成工作，
均不得自动删除本文或使其内容丢失；也不得据此自动恢复开发、启用配置或部署。
只有所有者明确要求删除时，才可以删除这一保留思路。

同日后续，所有者明确要求参考 CC Switch 开始研发。普通 function/custom、namespace、
客户端工具发现的可逆协议转换据此继续开发；这不撤销本文的保留要求。
新增 `additional_tools` 输入声明适配复用原 Router，不启用下文的托管搜索替换或
通用 `codex_tool_call` MCP 执行桥。当前进度见[工具兼容架构](../../models/common/docs/responses-tool-compatibility-plan.md)。

2026-09-09，所有者进一步明确授权清理 ChatGPT Web 相关废弃代码，并要求保留
致谢和简洁的架构流程。原私有草稿代码、补丁及其归档清单已清理；本文的设计记录、
下方架构流程和 README 致谢继续保留。清理不改变当前 Router 实现或搜索方案的暂停状态。

## 来源与致谢

工具声明转换、保存工具原始身份，以及把调用交回当前 Codex 任务执行的设计，
参考了 [miuuyy/codex-chatgpt-web](https://github.com/miuuyy/codex-chatgpt-web)。
感谢 miuuyy 分享这一实现思路，帮助我们解决工具调用方案设计中的难题。
核对源码时参考的版本为 `e85e3693fdb4e3e033348c08df0298c20fcdb612`。

本项目使用 LM Studio 的 Responses API；参考项目为 ChatGPT 网页提供的
`codex_tool_call` MCP 入口不必整体移植。搜索 MCP 若用于本方案，应由 Desktop
配置和执行。LM Studio 服务端 MCP 是另一条执行通道，未在本方案中启用。

## 拟采用的流程

```text
Codex 原始 tools
      ↓
Router：转换声明，保存原始类型、名称、namespace 与映射
      ↓
LM Studio / Qwen：接收工具定义和用法说明，产生工具调用
      ↓
Router：校验完整响应，在执行前恢复真实 Desktop 调用
function_call / custom_tool_call / tool_search_call
      ↓
当前 Codex 任务：权限审批、工具执行
      ↓
真实工具结果：function_call_output / custom_tool_call_output / …
      ↓
Router：按同一映射转换结果
      ↓
模型继续推理或回答
```

Prompt 说明工具用法；真实身份映射和校验由代码负责。
恢复调用类型发生在执行之前；执行后回传的是结果，而不是新的调用。

## 2026-09-09 补充：API 代理与 MCP 执行桥的区别

所有者补充了 CC Switch 的实现对比。本补充完善保留记录，不恢复开发。

CC Switch 的 API 代理在请求侧转换工具声明并保存工具上下文，在响应侧恢复
custom、namespace 和客户端工具发现的 Responses 语义，再交给 Codex 执行。
该流程不需要另建 `codex_tool_call` MCP 执行入口；参考其
[本地路由说明](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/2-providers/2.1-add.md#codex-local-routing-and-model-mapping)、
[转换源码](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/proxy/providers/transform_codex_chat.rs)
及 [v3.16.1 工具恢复说明](https://github.com/farion1231/cc-switch/blob/main/docs/release-notes/v3.16.1-zh.md)。

本项目现有 Router 已处于同样的 Codex API 请求/响应位置。普通工具继续采用
“代码转换声明 → 保存原始身份 → 校验并恢复调用 → Desktop 执行”的路径，
无需再经通用 MCP 桥接。MCP 可以提供搜索、GitHub、数据库等具体能力；这些
工具若已作为当前任务的函数声明暴露，仍走普通映射。模型需要工具定义和用法说明，
但 Prompt 不能替代协议转换、身份校验或执行权限。

这里的“有状态”指本次请求的工具映射和流式校验状态。当前实现由 Desktop 提交的
tools/input 重建对应关系，不代表 Router 需要持久化业务对话或另建任务执行循环。
“可逆”限于明确支持的工具契约；已经支持的原生类型不必强制改成 function。

托管 `web_search` 仍需独立的搜索执行能力。CC Switch 的
[Claude→Responses 搜索说明](https://github.com/farion1231/cc-switch/blob/main/docs/guides/claude-codex-routing-guide-en.md)
同样要求上游实现托管搜索。另须注意，其 Chat 转换器对未知类型存在直接忽略分支，
不能据此概括为所有路径都明确拒绝；本项目保留 `unsupported_tool_type` 的显式拒绝。
普通工具协议转换和待研究的搜索能力替换必须分别评估，不能把后者当作无损类型还原。

## 已有基础与暂停范围

已有适配器保存 `ToolSpec` 与 `RequestContext`，支持显式配置的 function/custom、
namespace、客户端工具发现及 JSON/SSE 调用还原。相关源码和既有诊断修复保留。
`tool_search` 是发现工具；它不是联网搜索。

暂停的是新增的“托管 `web_search` → 实际 Desktop 搜索工具”能力绑定。
暂停时曾编写未验证的实现和测试草稿，尚未执行该草稿测试、部署或启用。
草稿曾保存为私有补丁及源文件快照，并从当前可执行源码改动中撤出，未进入安装和
发布内容。该归档现已按所有者明确要求清理；已有适配器和错误分类修复继续保留。

当前显式适配路由仍对托管 `web_search` / `web_search_preview` 返回
`unsupported_tool_type`。这条错误分类修复不代表搜索兼容已经完成。

## 留待重新评估的两种绑定

| 方案 | 前提 | 需要保持的边界 |
|---|---|---|
| 绑定当前任务的搜索 function/MCP 函数 | 当前请求真实声明且已加载该工具；准确 name/namespace 和参数 schema 已核对 | 模型调用还原到原工具，由 Desktop 执行；不凭名称猜测 |
| 通过当前任务的 `exec` 访问内部搜索工具 | 当前请求声明并允许该 exec；端点策略明确指定内部工具及参数格式 | 固定桥接程序在 Desktop 运行时核对真实工具列表；查询仅作为 JSON 数据；一次调用，不自动重试 |

曾考虑先支持单一文本查询，并对暂时不能保留的域名限制、位置、缓存模式、
搜索上下文大小及图片结果明确拒绝。具体配置字段和协议版本仍是草案，
不能视为已支持的公开接口。

已安装搜索 MCP 或某个工具名称含有 `search`，不等于该工具可供当前任务调用。
只看见 `exec` 声明也不等于 Router 知道其内部工具列表。原始托管工具与替代
执行工具的身份、参数约束和结果语义均需要明确记录，不能宣称是无损改名。

## 将来恢复开发前的检查点

- 重新检查当前 Desktop、LM Studio、模型和工具接口，确认是否仍需这一方案。
- 明确目标工具、允许范围、参数和结果契约；保持 `none`、指定工具、并行和取消约束。
- 验证未知/歧义目标、schema 变化、未加载、权限拒绝、错误及取消均不会产生重试。
- 验证文本、Unicode、来源 URL、内容边界、call_id 和历史关联；不伪造搜索结果或引用。
- 验证 JSON/SSE 在一致成功终态前不交付可执行调用；保留原生模型和原生搜索通路。
- 分别记录隔离测试与真实 Desktop 搜索及审批证据；检查通过不自动启用服务或部署。

更完整的既有映射边界见 [工具兼容架构](../../models/common/docs/responses-tool-compatibility-plan.md)。
本文保留的是可重新评估的设计，不是继续开发的排期或自动执行指令。
