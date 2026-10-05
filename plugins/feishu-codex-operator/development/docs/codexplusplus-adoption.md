# Codex++ 方案吸纳记录

更新：2026-10-05。首轮研究只针对 Codex-Operator 现有功能的必要缺口，保留官方直连与拓展实例隔离、Desktop 任务所有权、完整历史、准确工具身份、零回放和恢复原件。新增功能或界面先与所有者商量；研究不扩大安装、发布或实机操作授权。

## 来源与采用方式

准确项目为 [BigPizzaV3/CodexPlusPlus](https://github.com/BigPizzaV3/CodexPlusPlus/tree/f55bb64663ba5024ab434017bb6212a0fd9f4bb3)，本轮固定提交 `f55bb64663ba5024ab434017bb6212a0fd9f4bb3`，提交日期 2026-10-03；不能用变化中的 main 替代这些依据。

该提交的 [LICENSE](https://github.com/BigPizzaV3/CodexPlusPlus/blob/f55bb64663ba5024ab434017bb6212a0fd9f4bb3/LICENSE) 为 AGPLv3。本轮采用设计和验证方法，修改由本项目独立编写，没有复制上游代码、测试代码或引入其运行依赖。未来代码复用须另行记录实际片段及适用许可；本次记录不是代码移植许可。

## 首轮采用：三个必要落点

### 1. 将失败原因传到已有状态出口

上游 [launcher.rs 的启动状态保存](https://github.com/BigPizzaV3/CodexPlusPlus/blob/f55bb64663ba5024ab434017bb6212a0fd9f4bb3/crates/codex-plus-core/src/launcher.rs#L648)区分运行、功能尚未就绪和失败；[502 原因日志](https://github.com/BigPizzaV3/CodexPlusPlus/blob/f55bb64663ba5024ab434017bb6212a0fd9f4bb3/crates/codex-plus-core/src/launcher.rs#L2257)避免把不同原因都显示成一个状态码。采用的是“原因和阶段必须到达最终诊断出口”的方法。

本地发现两个具体断点：

- [模式选择窗](../../scripts/operator_mode_picker.cs)在子进程非零退出时先抛通用错误，未解析已经输出的固定失败 JSON；早期 PowerShell 固定错误也被丢弃，原有状态标签无法区分版本变化、进程检查受限和派发未确认。
- [JSON 响应容量边界](../../scripts/operator_core/model_router.py)已有 `external_json_response_too_large` 拒绝，但 [protocol_reason](../../scripts/operator_core/responses_capabilities.py) 白名单漏列该固定码，状态记录丢失容量归因。

修复范围是既有标签的有界固定原因投影和已有诊断白名单。只接纳经过核验的固定原因，未知或异常形状保持通用失败；不显示 stderr/异常原文、端点、正文或凭据。保留非零退出和不确定终态，不通过提示文案触发重试或恢复。容量拒绝继续发生在任何工具交付前，不提高限制。

上游的原始 `error.to_string()`、端点日志、自动结束进程及失败转移不采用。JSON 错误包装已有原因链遍历和测试，未将其误列为缺陷。此修复也不能解决旧进程对象无法检查的事实；准确身份不确定时继续停止。

### 2. 在端点登记阶段拒绝非法端口

上游 [validate_upstream](https://github.com/BigPizzaV3/CodexPlusPlus/blob/f55bb64663ba5024ab434017bb6212a0fd9f4bb3/crates/codex-plus-core/src/protocol_proxy.rs#L1823)展示派发前检查上游配置的分层方式，但只检查空地址和缺少 key，没有提供本次端口校验算法。

本地 [ModelRegistry](../../scripts/operator_core/model_registry.py)检查 URL 的 scheme、hostname、用户信息等，却未读取解析结果的 `.port`；非法非数字、超范围或零端口可进入登记和只读检查，直到实际发送才失败。端口细则沿用本项目 [原生 provider 校验](../../scripts/operator_native_models.py)，将错误提前为固定 `RouterError`。合法省略端口、IPv4/IPv6 及原有 HTTPS/loopback 策略保持。

这是本地已确认缺陷的独立修复，不宣传为 Codex++ 的现成端口算法。共同登记层也会拒绝旧 v1/null 登记中的非法端口；合法 v1/null 及原生透传的协议行为不变。校验不做联网探测、重试、模型加载或配置迁移；测试只能证明非法配置被提前拒绝，不能证明合法地址当前连通或模型能力。

### 3. 把分片异常放进一个完整工具回归

上游 [混合 custom/namespace 测试](https://github.com/BigPizzaV3/CodexPlusPlus/blob/f55bb64663ba5024ab434017bb6212a0fd9f4bb3/crates/codex-plus-core/tests/protocol_proxy.rs#L2751)、[延后工具名](https://github.com/BigPizzaV3/CodexPlusPlus/blob/f55bb64663ba5024ab434017bb6212a0fd9f4bb3/crates/codex-plus-core/tests/protocol_proxy.rs#L3066)和 [UTF-8 分片](https://github.com/BigPizzaV3/CodexPlusPlus/blob/f55bb64663ba5024ab434017bb6212a0fd9f4bb3/crates/codex-plus-core/tests/protocol_proxy.rs#L3089)适合用于审查工具流的组合边界。

本地 [ResponsesEventAdapter](../../scripts/operator_core/responses_events.py)已经在完整成功终态前缓冲可执行调用；没有发现需要重写转换器的缺陷。补入 [test_responses_events.py](../../models/common/tests/test_responses_events.py) 的组合回归：两个 `output_index` 的参数交错，真实 `id/call_id` 从开始保持，完整名称延后到达，CRLF SSE 按 UTF-8 字节切分，最终 snapshot 和原始 custom source/函数参数逐字一致。

验收同时检查终态前零可执行调用、终态后每个调用和输入准确还原。缺失身份、名称矛盾、失败或截断继续按原合同拒绝；测试不补造 ID、不修补参数，不放宽实现。这是验证方法吸纳，不是新增协议、执行能力或真实模型通过结论。

## 已有覆盖：保留实现，借鉴检查顺序

| 可复用的检查方法 | 本项目现状与保留点 | 再次验证的触发条件 |
| --- | --- | --- |
| 工具声明 → 请求上下文 → 历史配对 → 终态还原 | [responses_tool_adapter.py](../../scripts/operator_core/responses_tool_adapter.py)已有 namespace/custom/deferred loading、具名结果和 tool choice 合同；不再增加转换器 | 原生工具声明版本、明确端点合同或实际失败形状变化 |
| 目录 → 声明能力 → 实际往返 → Desktop 分别验证 | 上游 [/models 不证明 Responses 能力测试](https://github.com/BigPizzaV3/CodexPlusPlus/blob/f55bb64663ba5024ab434017bb6212a0fd9f4bb3/crates/codex-plus-core/tests/model_catalog.rs#L423)值得保留为检查方法；本地目录从自有基线及显式能力生成，未验证 Web 窗口不刊登 | 新模型/合同/原生版本；旧成功只对原身份和版本有效 |
| 当前官方包身份 → 私有启动环境 → 准确进程/窗口 → 复用 | 本地 [模式入口](../../models/common/docs/mode-entry-window.md)已检查当前包和显式升级快照；不能用枚举缺席替代准确进程对象的检查 | 官方包、入口来源或进程出生身份变化 |

不复制上游模板推断的 multi-agent、Lite、窗口容量或隐藏模型能力。目录可见、配置保存、请求路由、工具执行和主窗口体验继续各自留证；本轮研究没有补成任何缺失的实机通过。

## 后续工作怎样使用本记录

开始现有模型、工具、启动或配置引导修复时，先读[当前项目记忆](../../models/web/docs/native-web-experience.md)和[原生对话计划](../../models/web/docs/native-conversation-plan.md)，再按上表找到本项目现有合同。先用当前失败形状核对已覆盖项；没有明确缺陷时记录证据缺口，不为上游功能创造需求。

每次新增采用记录至少包含：既有缺口、准确仓库/提交/文件或符号、采用方法、本地落点、不适用行为、合成验证和实机验证范围。端点合同、历史或调用身份不得因参考实现而被省略。重大内部方向调整先讨论用户收益、迁移/恢复和验证计划。

本轮不采用 CDP/React 菜单注入、历史 provider 重写、聚合重试/轮换、Chat Completions 通路或独立管理界面。当前官方直连和拓展实例隔离继续保留；这些上游能力不是本项目已获准的新开发工作。

## 本轮验证与部署边界

三个必要修复及组合回归已写入 canonical 源码；运行前只读核对 Operator 已退出、无活动回调，测试只用纯内存或临时 loopback、私有合成编译，不发送真实模型请求。

| 检查范围 | 实际结果 | 证据限制 |
| --- | --- | --- |
| `test_responses_events` 完整模块 | 31 项通过，零失败/错误/跳过 | 新组合用例为 `test_interleaved_calls_with_delayed_names_and_utf8_wire_preserve_exact_input`，没有真实工具执行 |
| `test_model_router`、`test_responses_profiles`、`test_responses_router` 完整模块 | 101 项通过，零失败/错误/跳过 | 原始工具输出保留；没有另存原始日志文件或回执，不伪称已有 |
| `test_mode_host`、`test_mode_picker_lifetime`、`test_mode_entry` 完整模块 | 24 项运行，23 项通过，零失败/错误，1 项既有 symlink 条件跳过；unittest exit 0 | 新固定诊断解析包含 28 个子案例，实际编译并调用静态方法；未构造真实窗口。私有包装回执要求零跳过，因此仍为 failed，原件保留 |

两源登记/容量诊断修复、选择窗诊断修复和事件组合回归均经交叉只读审查；发布清单纳入本文件，链接、已审文档摘要和内容检查另行复核。未执行全量回归或重新打包，也未更新已安装入口、runtime/cache、活动登记或路由。

源码、合成测试和编译结果不能替代当前服务、真实模型或 Desktop 主窗口验收；旧进程身份受限、真实审批配对和不同新用户首次接入等原有未确认项不因本轮研究而消失。已有失败记录、历史和恢复原件继续保留。
