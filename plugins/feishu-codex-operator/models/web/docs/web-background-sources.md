# 后台浏览器实现来源

## 2026-09-20 当前参考策略与研究范围

所有者将 [Chat On Steroids](https://github.com/totec448-spec/chat-on-steroids) 设为首要参考，
其他参考冷置，仅在必要时查阅；下方带日期的旧优先级保留为历史来源。
本轮阅读其 `src/main/connection.ts`、`src/main/plugin-refresh.ts`、
`src/main/browser-startup.ts`、`src/main/browser-wake.ts` 与
`docs/chatgpt-turn-signals.md`，对照本项目已有后台、保存连接、页面与提供方入口。
采用的是研究方向：保存连接复用、按真实工具声明判断是否需要刷新、准确回合归属、
将后台准备与模型发送分开。具体研究链接、差异和计划见 [原生对话改进计划](native-conversation-plan.md)。
这些是 2026-09-20 阅读的公开 main 页面，不是已固定提交的代码移植；本轮没有复制代码，
没有安装上游产品或验证其本机效果。后续如采用代码，先固定提交并登记对应文件和许可。

所有者随后同意优化代码，本项目按保存连接复用及明确状态的思路独立改进
`operator_web_entry.ps1` 与 `operator_product.py`：省略重复配置参数时只读核验原登记，
不自动采用变化；固定诊断区别检查受限与保存入口变化。未复制上游代码、引入依赖或
采用其重试策略。39 项专项及全量回归通过，真实保存入口重复复用且文件与进程保持；
这是 2026-09-20 的验收范围；隐藏页面准备已在 2026-09-23 落地，工具声明刷新与
主窗口模型选择仍需各自验收，详见上述改进计划。

2026-09-23 后续研究固定到
[`750fad9378a0cf9e37791916b11f7ed9add645dd`](https://github.com/totec448-spec/chat-on-steroids/tree/750fad9378a0cf9e37791916b11f7ed9add645dd)：

| 来源 | 本项目独立采用的机制与边界 |
| --- | --- |
| [browser-startup.ts](https://github.com/totec448-spec/chat-on-steroids/blob/750fad9378a0cf9e37791916b11f7ed9add645dd/src/main/browser-startup.ts)、[browser-wake.ts](https://github.com/totec448-spec/chat-on-steroids/blob/750fad9378a0cf9e37791916b11f7ed9add645dd/src/main/browser-wake.ts) | 保存服务的后台准备与发送分开；不复制自动重试或引入伴随扩展 |
| [chat-models.ts](https://github.com/totec448-spec/chat-on-steroids/blob/750fad9378a0cf9e37791916b11f7ed9add645dd/src/shared/chat-models.ts) | 精确别名、保留代际和独立 Pro 身份；不从 Latest 或 API 型号推定网页身份 |

初始未固定的研究入口仍保留用于溯源：
[connection.ts](https://github.com/totec448-spec/chat-on-steroids/blob/main/src/main/connection.ts)、
[plugin-refresh.ts](https://github.com/totec448-spec/chat-on-steroids/blob/main/src/main/plugin-refresh.ts)、
[chatgpt-turn-signals.md](https://github.com/totec448-spec/chat-on-steroids/blob/main/docs/chatgpt-turn-signals.md)、
[codex-desktop-bridge.md](https://github.com/totec448-spec/chat-on-steroids/blob/main/docs/codex-desktop-bridge.md)。
这些 main 链接不是固定版本证据；刷新摘要不能忽略输出 schema、风险标记等声明语义，
Desktop bridge 草案也不是已完成的 Windows 模型菜单方案。没有复制其运行代码。

2026-09-24 对照同一固定提交的
[`extension/chatgpt-dom.js` 可见性判断](https://github.com/totec448-spec/chat-on-steroids/blob/750fad9378a0cf9e37791916b11f7ed9add645dd/extension/chatgpt-dom.js#L139)
与 [`chatgpt-turn-signals.md` 屏幕阅读播报误判记录](https://github.com/totec448-spec/chat-on-steroids/blob/750fad9378a0cf9e37791916b11f7ed9add645dd/docs/chatgpt-turn-signals.md#L132)，
本项目在 [web_browser_page.cjs](../../../scripts/web_browser_page.cjs) 独立排除明确视觉隐藏的
告警节点，包括上游所列 `sr-only`、`visually-hidden` 与明确隐藏测试标记，防止把无障碍播报
误作当前可见的人机验证或错误界面。保留真实可见的小尺寸告警，不引入任意像素阈值、
观察失败即放行、reload 或 retry；没有复制上游代码。验证结果单列在
[发布验收](../../../development/docs/release-audit.md)，此项不能推导当前页面已登录或服务已部署。

下方历史中的“当前”“优先级不变”均指对应记录日期。2026-09-20 后统一以本节的
Chat On Steroids 首要策略为准。2026-09-24 已移除仅用于旧验收的项目搜索禁用配置；
当前 Web-only 搜索方案和通过/失败边界见[项目记忆](native-web-experience.md)，
合并的逐次验收见[历史索引](native-web-history-20260924.md)。来源登记不是功能验收。

## 历史实现来源与验证

2026-09-20 终止错误兼容：本轮依据本机原生 CLI 和实际本地 Web/router 验证独立实现。Web 自有终止错误以 HTTP 400 保留原 cause_http_status、固定原因和已转交/已返回工具计数；受管 Web 长连接返回失败事件，原生与其他上游不改写。容量仍返回 413，单独记录范围与上限，独立 provider 保持原有两项零重试配置。统一原生 provider 的 413 仍可触发客户端重试，因此 native-only 保护保持。沿用 WebCodex 原生任务/后台生命周期分工，没有复制参考项目的重试、截断或恢复逻辑；四项参考优先级不变。

2026-09-19 冷启动修复独立实现于本项目配置/启动层：区分已知完全注释的旧路由与活动路由，原字节保存，提前预检并在 I/O 后复核。延续 WebCodex 的保存配置与后台生命周期方向，未复制上游重试、恢复或配置清理代码；四项参考及优先级不变。真实主窗口冷启动仍须单独验收。

2026-09-19 labelled URL 兼容依据本项目新的独立 AV 公共消息形状检查，独立实现 `url/title/item` 与零宽末尾来源注脚转换。没有复制参考产品的 HTML 抽取、宽松链接猜测或重试。延续 WebCodex 的原生任务/后台服务分工；四项参考顺序不变。浏览器结构检查不推导原生窗口搜索通过。

2026-09-19 原生同任务切换验收沿用已记录的 WebCodex 原生任务/后台服务分工和本项目统一路由；此次没有复制新增上游代码。独立官方 Desktop 使用已有 provider、启动目录与私有运行目录完成 AS1 Web→AS2 官方 Sol→AS3 Web 普通文本历史往返。实际请求去向独立核对，不能由目录显示推断。官方配置字段参考 https://learn.chatgpt.com/docs/config-file/config-reference；目录与 env_key/env_http_headers 是配置机制，不赋予全局部署或辅助能力通过。四项参考与 WebCodex 优先、codex-chatgpt-web 最低保持，MCPX 身份仍待确认。


2026-09-19 消息 ID 兼容修复依据本机隔离统一路由的官方 400 字段错误独立实现：网页公共消息 UUID 与 Responses 输出项命名域分开，在新输出投影生成稳定 msg_ow_ 身份。没有复制四个参考项目的实现，也不重写既有历史、工具或调用身份。WebCodex 的资料/执行分工与固定优先级保持；接口分流、消息历史和真实 Desktop 仍分别验收。


2026-09-19 模型入口沿用 WebCodex 的配置/生命周期分工；本次只读审阅当前官方 Desktop 已安装代码中的目录筛选和模型设置路径，独立实现诊断，没有复制官方或四个参考项目的代码。官方 [配置说明](https://learn.chatgpt.com/docs/config-file/config-reference) 与 [App Server 模型列表说明](https://learn.chatgpt.com/docs/app-server#list-models-modellist) 分别限定启动目录与元数据语义。隔离 UI 菜单显示通过不推导服务路由切换；私有证据另见项目记忆。


2026-09-19 会话生命周期修复依据 MCP 2025-11-25 的服务端终止/404 规则独立实现，保持固定容量和正在等待的准确调用。没有复制四个参考项目的会话代码、权限或重试策略；固定优先级不变。详见 [固定连接会话回收](web-fixed-tunnel.md#mcp-会话回收2026-09-19)。

2026-09-19 v3 大记录的剩余页容量计算为本项目独立修复；没有引入参考项目的历史裁剪、重试或权限策略。全量往返及实际终端输出另行核验。

2026-09-19 延续固定 WebCodex context_projection.rs 的资料/执行分工，将已有显式最后用户副本也放入结构化上下文头部；完整原始来源与索引核对，位于 request value 之外。独立 Python 实现，无 Rust 源码复制、历史裁剪、权限改动或重试。真实 AI1 通过、AI2 部分通过及新合成历史检索分别记录，不从副本位置推断语义可靠性。

2026-09-19 再次阅读固定 WebCodex 提交 context_projection.rs 的结构化 materials 及序列化预算分工。本项目独立实现完整上下文记录分页：整条请求字段/消息直接保留为 JSON 对象，只有超大记录分片，逐项可无损重建；没有复制 Rust 代码、上游材料筛选、裁剪、权限或重试策略。参考关系不证明模型正确遵循当前任务。AB1 误执行历史任务为新失败，保留具体调用而不按协议完成宣称成功。四项参考及优先级保持。


以下固定提交是代码审阅与改编来源，不是当前插件在真实账户中的验收证明。
主体为 Python；必须接触网页渲染的部分使用 Electron，不运行参考项目的产品。

2026-09-18 当时的参考顺序为 WebCodex → localmcp / MCPX → codex-chatgpt-web；
已被上方 2026-09-20 策略取代。下列改编记录用于来源归属，不是当前优先顺序。

## codex-chatgpt-web

- 源提交：[`e85e3693fdb4e3e033348c08df0298c20fcdb612`](https://github.com/miuuyy/codex-chatgpt-web/tree/e85e3693fdb4e3e033348c08df0298c20fcdb612)。
- 原文件：[`launcher/electron/browser-host.cjs`](https://github.com/miuuyy/codex-chatgpt-web/blob/e85e3693fdb4e3e033348c08df0298c20fcdb612/launcher/electron/browser-host.cjs#L1413)。
- 原符号：`hiddenTurnBounds`、`enableHiddenTurnViewport`、`presentTurnView`。
- 改编文件：[web_browser_surface.cjs](../../../scripts/web_browser_surface.cjs)。
- 具体移植：运行页移出窗口内容区域但保持 view 可见；最小可用视口；显式设备仿真；
  主框架导航后的重新应用；显示辅助页面时清除隐藏仿真；保留后台渲染。
- 本项目差异：一个明确归属的 Python 服务与浏览器进程，不开放调试端口、不使用
  Playwright/CDP，也不复制上游自动授权、账户设置修改、响应重建或重试。
- [完整 MIT 许可证](../licenses/codex-chatgpt-web-MIT.txt)；源文件同时保留版权及许可。

## WebCodex

- 源提交：[`01dc7d31d567aa0300bc246ac7f4a2db590bdbe2`](https://github.com/yyjeqhc/webcodex/tree/01dc7d31d567aa0300bc246ac7f4a2db590bdbe2)。
- [`desktop_shell.rs`](https://github.com/yyjeqhc/webcodex/blob/01dc7d31d567aa0300bc246ac7f4a2db590bdbe2/apps/desktop/src-tauri/src/desktop_shell.rs#L61)：后台启动与显式前台操作分别处理。
- [`lib.rs`](https://github.com/yyjeqhc/webcodex/blob/01dc7d31d567aa0300bc246ac7f4a2db590bdbe2/apps/desktop/src-tauri/src/lib.rs#L28)：关闭窗口与退出服务分别处理。
- [`supervisor.rs`](https://github.com/yyjeqhc/webcodex/blob/01dc7d31d567aa0300bc246ac7f4a2db590bdbe2/apps/desktop/src-tauri/src/process/supervisor.rs#L392)：所属进程的有界关闭。
- 对应 Python：[web_browser_session.py](../../../scripts/operator_core/web_browser_session.py)、
  [operator_web_model.py](../../../scripts/operator_web_model.py)。这些文件独立实现相应状态机；
  未复制 Rust 源码、Runner、本地执行权限、连接自动重试或任务恢复机制。
- [完整 Apache-2.0 许可证](../licenses/webcodex-Apache-2.0.txt)。所查提交根目录没有独立 NOTICE 文件。

2026-09-18 按所有者调整后的首要参考顺序，继续阅读同一固定提交的
[`context_projection.rs`](https://github.com/yyjeqhc/webcodex/blob/01dc7d31d567aa0300bc246ac7f4a2db590bdbe2/src/tool_runtime/context_projection.rs)、
[`tool_catalog.rs`](https://github.com/yyjeqhc/webcodex/blob/01dc7d31d567aa0300bc246ac7f4a2db590bdbe2/crates/webcodex-tool-contracts/src/tool_catalog.rs)
及 `src/tool_runtime/tests/targeted_inventory.rs`。采用其有界资料获取和工具发现分工；
本项目独立实现完整上下文分页、完整工具目录和按需准确 schema。没有复制 Rust 代码、
上游上下文截断、权限、Runner 或工具执行器。所有历史仍完整提供，工具身份和原生
执行边界不变。具体采用与实测边界见[项目记忆](native-web-experience.md)。

同日继续阅读该固定提交 `context_projection.rs` 的序列化预算校验；本项目独立改进
已有分页装填，在既有字符及嵌套 JSON 字节界限内寻找最长前缀。没有复制其上下文
裁剪、材料授权策略或 Rust 算法。纯本地中文与转义夹具的页数减少，不代表真实
网页时延、工具执行或原生验收通过，运行中旧实例暂未升级。

2026-09-19 再次核对同一提交的工具发现分组和 targeted_inventory 中按需获取资料
的分工。本项目独立增加 `mcp_catalog_pages_v2` 的完整条目分页：工具目录不裁剪、
不筛选、不改顺序，已发现条目可以直接读取其完整 schema，其他页继续保留。
没有复制 Rust 实现、summary_only 字段删减、搜索匹配或上游执行策略。该改变
减少读取无关目录的前置往返；338 工具夹具验证只读一页即可走完选中定义与调用，
但不能据本地结果认定真实网页时延已改善或 S2 的远端超时已修复。

## 验证边界

2026-09-19 固定插件页提示 operator_call 缺少输出架构；源码核对为旧 JSON 文本
返回。本项目按 [OpenAI 工具结果契约](https://developers.openai.com/plugins/build/mcp-server)
独立补齐显式 structured_call_v1 和匹配输出架构，完整保留原生配对结果；继续采用
WebCodex 的资料/执行分工。对照最低优先级固定提交的 codex_tool_call 仅确认其
原生执行与风险注解边界，没有移植权限、重试或结果改写。此格式改进与零调用
原因分开，既有所有失败继续保留。

2026-09-19 重新核对同一 WebCodex 提交 context_projection.rs 的带标记资料投影
与独立权限检查。本项目独立增加 composer 中有界、完整的最后原始 user 消息副本；
没有复制 Rust 代码、资料裁剪、授权范围或执行器。副本只改善当前需求在传输中的
可见位置；它不替代完整上下文、不提升工具结果角色，也不构成权限或拒绝根因证据。
四项参考次序保持，V1 等旧失败不重放；以新的独立案例验证当前表示的实际效果。

2026-09-19 取消后的同进程保留继续采用上述 WebCodex 的窗口与进程生命周期分工，
由本项目独立实现准确请求取消、一次公开停止操作、稳定空闲观察与 Python/worker
接纳条件。未复制上游任务恢复、重试或权限逻辑。取消只允许后续新输入；原轮次的
MCP key 已关闭，旧轮次仍禁止重放。本地 HTTP 与宿主夹具不是实机停止按钮或上游
终止证明，多文件 V1 的零调用失败也没有据此改判或重新发送。

2026-09-18 begin 结构化交付依据
[OpenAI 工具结果契约](https://developers.openai.com/plugins/reference#tool-results) 与
[输出 schema](https://developers.openai.com/plugins/reference#tool-descriptor-parameters)。
模型可见数据放入 structuredContent，声明相应输出 schema；不用仅组件可见的
元数据承载上下文，也不附加同一大文本副本。代码独立实现，底层旧文本模式保留。
这延续 WebCodex 的资料传递与工具执行分工，没有引入上游执行器、裁剪历史或重试。
OpenAI_Support 在[相关社区回复](https://community.openai.com/t/tool-response-truncation-on-mcp-connector-responses-that-previously-worked/1383071/4)
提到了 structuredContent-only 的反馈排查，但没有公布统一截断阈值；此处不把该
回复或本地模型自述当成本案例远端截断的定论，也未向外部发送私有会话或请求数据。

2026-09-18 完成人工协助后继续核对同一固定提交的 `mcp-server.ts` 中 `result`、
`asMcpResult` 和工具目录读取：上游将内容与结构化结果分别保留。本轮仅作比较，未采用
其结果改写、工具筛选、权限合同或重试。A5 的本地 begin 回复已准备但指定答案未到达，
后续小请求又在 begin 前超时；两项均不能单独证明网页大小限制或授权问题。
沿用 WebCodex 的生命周期分工，本项目独立补充当前轮次的最终回复等待超时分类，
保留明确登录协助与停止后的配置复用。没有为减少提示而自动批准网页操作。

2026-09-18 继续采用 codex-chatgpt-web 的“原生任务提供实际工具、MCP 读取请求”分工。
真实 Desktop 带入完整工具与历史后超过原输入框通道界限，因此本项目独立将 MCP
composer 改为当前 turn key 的简短读取说明；完整请求由既有 `operator_begin` 交付。
这是传输位置调整，不是删减上下文、移植上游权限策略或自动重试。原生搜索声明的
适配缺口保留明确拒绝；仅隔离验收目录通过原生配置关闭该未实现能力，未复制 hosted
搜索执行器，也不把这一受限目录的成功当成日常全部功能验收。该项目级禁用办法
在 2026-09-24 已撤回；它会影响同目录其他模型，不能继续作为配置指引。

2026-09-17 的独立 Desktop 准备继续采用 codex-chatgpt-web 的原生任务入口方向，
并沿用 WebCodex 的“保存配置”和“启动实例”分工。新增准备器由本项目独立实现，
只登记供显式选择的提供方，保留官方默认、审批和任务；没有复制上游启动器或命名
配置写法。当前原生 CLI 的只读配置实测发现旧式 profile 选择已停用，准备器因此
只追加提供方，验收参数单独传入。此项不证明真实 Desktop 已加载或可在同任务切换。

2026-09-16 的统一工具连接继续使用本项目既有 `WebMcpTurn`/`WebResponsesBridge`，
由 `operator_web_model.py` 与 `web_connection.py` 管理单个开发连接。参考上游
`src/adapters/chatgpt-web/mcp-server.ts` 的实际工具清单、请求绑定与结果接续分工，
没有复制其 Zero Risk 合同、工具筛选、参数改写或后台权限策略。本项目保留明确的
工具风险标记、原始 Codex 声明和审批返回，不由连接是否成功推断执行权限。

同一固定提交的 `src/adapters/chatgpt-web/browser-worker.ts` 分开实现插件目录刷新、
临时聊天个性化检查、插件选择和消息提交。2026-09-16 实际新增插件后遇到选择超时，
显式更换已关闭浏览器后 UI 可见新条目，印证应把注册后的就绪检查放在发送之前。
本项目目前只复用已有显式恢复路径；未复制其个性化设置切换、自动目录重试或授权。

继续核对该 `browser-worker.ts` 的 `enqueueMaintenance`、`close` 和 `runStage`：
工作请求的阶段期限与浏览器持有、关闭分别处理。本项目在 2026-09-17 去掉了宿主
另行两小时自动退出的早期限制，由 Python 所属服务控制整体关闭。单次请求期限、
失败停止、128 轮容量和防重放记录不变，不引入自动重启或延长已执行请求。

`selectConnector` 和 `ensureChatGptPersonalizedConnectorAccess` 还将临时聊天插件访问
与菜单选择分别处理。本项目只采用只读就绪等待，不复制其个性化切换或再次触发菜单。
2026-09-17 核实的公开菜单带 `data-composer-plugin-impression-id`；点击前新增准确 ID
和完整名称双重核对，限制在 composer 插件行中，点击后继续检查原有选中标签的 ID。

同一提交的 `src/adapters/chatgpt-web/prompt.ts` 在完整上下文后再次明确要求原样传递
当前 turn token。本项目保留完整、无损的请求 JSON，并采用对应的明确复制提示；
本机生成的临时 key 使用 32 字节随机值的十六进制表示，避免其本身需要 JSON 转义。
准确核对、失配拒绝和不重放边界不变；没有采用上游 Zero Risk 权限合同，也不推断
此前真实失配一定由转义导致。

2026-09-17 继续核对 `browser-worker.ts` 的 `resolveChatGptToolConfirmation`、
`throwIfChatGptSessionFailureAlert` 和 `throwIfChatGptTerminalErrorAlert`。页面层采用
其公开确认卡片、准确插件标题和错误控件的识别依据，独立实现只读、有界状态投影。
持续两秒的单次确认、会话过期、订阅加载失败或回复错误会结束当前等待，并经 Python
传回中文说明；短暂提示可自行消失。没有移植其自动允许、自动拒绝或重试行为。
普通助手正文中的“安全检查拦截”不供这些状态取证，也不能用来推断拒绝组件。

同一 `mcp-server.ts` 的 `codex_tool_call` 正确声明 `openWorldHint: true`。本项目的
通用代理也可能转交联网工具，因此修正此前不准确的封闭环境标记；读写、破坏性和
非幂等标记仍保守保留。声明修正不增加实际工具、执行权限或重试路径，也不能证明
此前未到达本机的测试调用因此失败。

隐藏视图夹具验证窗口、导航和渲染；私有进程及 loopback 测试验证 IPC、接纳、取消、
协助和停止。真实 ChatGPT 登录、真人验证、工具审批、长时间稳定性与 Desktop 交互
必须另留相应版本的实际证据。普通请求不会触发自动弹窗或重新发送失败请求。
当前辅助窗口仅允许 ChatGPT 与 `auth.openai.com` 的明确导航；Google、Microsoft、
Apple 等第三方身份提供方的跳转尚未接入，不能据此声称所有登录方式都可用。

2026-09-18 的 `inspect` 继续沿用 WebCodex 显式前台操作与后台进程持有的分工，
由本项目独立实现公开回复/提示的只读文字快照。现有 `assist` 负责登录与空白聊天
恢复；新入口保留已结束页面，绑定准确消息与实例，并暂停新请求接纳。没有复制
上游重试或权限逻辑，也不读取隐藏推理。预览壳使用独立内存 session、转义文本、
禁用脚本与外部内容；关闭后清空壳的导航历史。截图方案的本地空图失败已保留，
最终没有依赖隐藏页面截图或新增截图降级重试。真实 Desktop 编码仍需独立验收。

## 固定隧道

2026-09-19 S2 缺会话标识及非 POST 拒绝的复核依据
[MCP 2025-11-25 Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)：
已返回会话标识时客户端须在后续请求携带；要求会话的服务可对缺失标识返回 400，
不提供 GET SSE 可返回 405。S2 的这两次拒绝之后已有成功页面回复，不能仅据代码
判为后续目录读取失败的原因。未采用无会话降级、自动初始化重试或旧请求重放。
S1 的专用历史错误提示由本项目独立实现，无新增上游代码改编。

2026-09-18 首次真实原生编码 G1 通过后，现场预览发现隐藏网页的 DOM 回复仍只
绘制首字。沿用上述当前公开终态的校验来源，本项目独立修正预览：使用已验证
`content.parts`，逐段展示原字符串和边界；DOM 只读取固定公开提示并核对回复行。
不是补写或重建模型回答，也不读取隐藏推理。没有复制新增上游代码；完整回复、
空提示、超限拒绝及原页面保留由独立回归与后续实机检查分别验证。

继续审阅同一 codex-chatgpt-web 提交的 `src/tunnel.ts`，包括发布包校验、私有 key
引用、Tunnel ID/插件绑定和真实 readiness 判定。Python `web_openai_tunnel.py`
独立实现所属前台子进程、固定配置、原子独占绑定和接纳控制；直接使用官方客户端
的 HTTP MCP 通道，不导入上游 TypeScript、stdio 执行器、自动审批或全局安装流程。

## Windows 独立后台生命周期（2026-09-18）

沿用 WebCodex 的后台连接与原生任务分工，本次 Windows 启动独立实现复用本项目
`start-feishu-codex-operator.ps1` 的 CIM 启动方向。依据微软
[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) 与
[Win32_ProcessStartup](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-processstartup)，
通过固定系统 PowerShell 调用 Win32_Process.Create，传递经过编码的参数数据、
显式环境与隐藏启动标志。没有复制新上游代码或引入服务安装/定时自动重启。
原父进程所在的 Job 与新进程可能所在的其他 Job 必须区分；任意 Job 成员检查为真
并不能说明仍属于 Desktop。回归明确测试准确启动 Job 关闭后子进程存活。

## 其他开源桥接项目（2026-09-17）

本轮对以下三个固定提交阅读源码，没有安装依赖或运行它们的服务。

- [codex-chatgpt-bridge / `call_tool`](https://github.com/Dalomeve/codex-chatgpt-bridge/blob/c022afddcc3dea588a14136df571263a2d36000f/src/codex_chatgpt_bridge/mcp.py#L59)：
  核对 JSON 对象参数、真实 handler 结果和通用执行工具的风险声明。
  同提交 [Host Limits](https://github.com/Dalomeve/codex-chatgpt-bridge/blob/c022afddcc3dea588a14136df571263a2d36000f/README.md#L214)
  记录了网页称安全检查拦截、调用未到达本地的现象。这只是该项目的报告；不能凭本项目
  模型回复的相似措辞独立确定拒绝组件。其 Full Delegate、本地执行和授权模式未采用。
- [codexbridge / `task_verify`](https://github.com/naplesblue/codexbridge/blob/fbe4fc72c172155ad70757fd8826bd1501649ad9/src/server.ts#L1669)：
  核对先执行真实命令、再记录实际退出状态的顺序，及网络执行工具保守的风险标记。
  本项目仍由 Codex 执行工具，不复制其命令策略、任务计划注入或本地执行器。
- [chatgpt-sol-local-bridge / `instrumentServer`](https://github.com/mingrath/chatgpt-sol-local-bridge/blob/3c7b0c0fffa0e04f4533f871ece3da0064cf6620/src/lib/audit.js#L11)：
  参考调用开始、实际结果和异常分别观察的分工。Python `WebMcpTurn` 独立增加接纳、
  向本机接口交付和配对结果计数；`WebResponsesBridge` 保留当前及最近一次终态，
  状态命令给出中文进度。没有复制 JavaScript 源码、参数日志、错误正文或哈希日志链。

三个项目均为 MIT；此处仅作源码比较与设计参考，没有复制代码文件。新增观察只保存
固定计数、布尔值和阶段，不保存工具名、参数、结果、key、任务编号或网页正文。
收到配对结果可能表示成功、拒绝或失败；网页回复返回也不构成任务完成证明。
本地交付观察不能证明另一端收到 HTTP 响应，旧失败记录不会被新诊断改判。

2026-09-17 继续采用上述调用阶段分别观察的思路，将既有 `WebMcpEndpoint` 的有界
接收/拒绝记录接到私有服务状态和认证健康接口。独立验收器新增前后区间校验，
只在相同端点代次、一个新增轮次和准确客户端请求数下归属计数；缺页或混入其他
轮次则保留不确定。没有复制上游代码或增加网页调用、权限变更、重试及正文日志。

独立的真实只读空参数案例在同一固定连接、同一隐藏进程上完成一次 `inspect_fixture({})`：
内容、UTF-8 字节数和 SHA-256 精确一致，20.241 秒，显示/焦点计数均为零。
范围仅为空对象传递与只读结果，不运行程序、不提供 `run_tests`，不替代此前失败的编码
案例。该证据排除这个版本的一般性空参数传递问题，不能证明此前缺少测试调用的原因。

协议与生命周期核对了 [OpenAI tunnel-client v0.0.12](https://github.com/openai/tunnel-client/tree/v0.0.12)
的 `docs/configuration.md`、`docs/protocol.md`、`pkg/runtimehealth/health.go`、
`pkg/controlplane/internal/poller.go`、`metrics.go` 与 `pkg/oauth/discovery_failure.go`。
本项目没有复制这些 Go 源码，也不把本地 readiness 当成远端认证；用成功轮询指标
补充判断。发布客户端为独立、校验过的用户本地依赖，不复制进插件发布包。

2026-09-19 延续首要参考 WebCodex 的完整资料分页与工具发现分工，本项目修正页容量计算与实际 structuredContent 表示不一致的保守开销；未复制其上下文裁剪、资料权限或执行器。完整 48 KiB 边界和原始资料保持，缩页只来自已选传输格式的真实编码差异。

2026-09-19 持久入口延续 WebCodex 的后台服务/前台窗口分工。本项目独立实现保存身份、Windows CIM 脱离父进程生命周期、单次冷启动激活及明确停止边界；复用项目自己的安装与恢复实现，无新增上游源码复制或重试策略。
