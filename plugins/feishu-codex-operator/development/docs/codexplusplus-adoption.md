# Codex++ 方案吸纳记录

更新：2026-10-28。研究只针对 Codex-Operator 现有功能的必要缺口，保留官方直连与拓展实例隔离、Desktop 任务所有权、完整历史、准确工具身份、零回放和恢复原件。新增功能或界面先与所有者商量；研究不扩大安装、发布或实机操作授权。2026-10-05 首轮及 2026-10-17 的固定来源与验收记录继续保留。

## 来源与采用方式

准确项目为 [BigPizzaV3/CodexPlusPlus](https://github.com/BigPizzaV3/CodexPlusPlus/tree/f55bb64663ba5024ab434017bb6212a0fd9f4bb3)，首轮固定提交 `f55bb64663ba5024ab434017bb6212a0fd9f4bb3`，提交日期 2026-10-03；不能用变化中的 main 替代这些依据。

该提交的 [LICENSE](https://github.com/BigPizzaV3/CodexPlusPlus/blob/f55bb64663ba5024ab434017bb6212a0fd9f4bb3/LICENSE) 为 AGPLv3。本轮采用设计和验证方法，修改由本项目独立编写，没有复制上游代码、测试代码或引入其运行依赖。未来代码复用须另行记录实际片段及适用许可；本次记录不是代码移植许可。

## 2026-10-28 授权后的分层诊断与取消验收

所有者要求先补 Web 分层诊断和等待期限验证，再验收新版 Codex 取消，发现问题即修复并写回现有开发文档。本次 alpha144 修复已复现的诊断与隔离评估缺口；工具等待和原生取消实现经验证后保持，没有新增界面、依赖、固定生产等待上限或自动恢复。

- 借鉴 [codex-chatgpt-web `a738f04`](https://github.com/miuuyy/codex-chatgpt-web/commit/a738f0485c6a8dcfd948d57ba94830d1540fe4e6) 分开本地代理与目录健康的检查方法，独立实现固定隧道 readyz/poll 保存观察和 manager 分层输出。初轮三项回归先复现缺少分层健康字段及 bound stopped 丢失诊断；旧实机失败回执和原 error_result 另确认未绑定终态也不保留失败阶段，随后补其边界回归。现在只保留固定枚举、布尔和有界计数，陈旧代次不能影响接纳，目录仍明确未观察。未绑定终态仍抛出原 uncertain-launch 错误；快照不建立当前 worker、登录或连接事实。仅从既有观察投影，没有新增探测或模型请求。
- [codex-chatgpt-web `53b6050`](https://github.com/miuuyy/codex-chatgpt-web/commit/53b60503b4324e2b3f0a3cbf5445af2014afc290) 的 60 秒 command-poll 限制提供验证方向，不作为本机合同。本机准确保存的 tunnel-client v0.0.12 逐命令响应期限由[服务端字段转换](https://github.com/openai/tunnel-client/blob/v0.0.12/pkg/controlplane/internal/command_parser.go)并由 [processor](https://github.com/openai/tunnel-client/blob/v0.0.12/pkg/dispatcher/internal/processor.go)执行；空 poll 的 10 秒加 5 秒余量不是工具执行期限。本地以真实 TCP 提前断连验证 900 秒回合中的一个已交付调用，保留参数和回合 deadline，取消 pending future、拒绝晚结果与重复派发。该边界通过，没有据此改短原生参数或写入未经证实的 60 秒上限。
- 对照官方 [Codex PR #56132](https://github.com/openai/codex/pull/56132) 的取消传播及写入顺序，在实际 CLI 0.165.0-alpha.1.2 上分别验证原生 MCP tool timeout 和 turn/interrupt。私有 App Server 用 never/read-only、新 home、合成模型及只读 stdio MCP；核对准确 RPC ID 类型、请求先于取消、原生 interrupted 终态和同一 MCP 进程上的不同新回合完成。真实模型请求为零。公开 tag `rust-v0.165.0-alpha.1.2` 的提交为 `720fec862a608ae1e5878d1eecb04fb93192e93c`，包含该 PR 的 merge commit；源码祖先关系只是辅助证据，实际二进制行为另有原始配对记录。

来源方法由本项目独立实现，没有复制外部代码或测试。codex-chatgpt-web 为已记录 MIT 来源，官方 tunnel-client/Codex 为 Apache-2.0 来源；先前 Codex++ AGPLv3 及采用记录保留。定向四模块 168 项通过，随后完整当前 CLI 模块 5 项通过；全量冻结结果另记发布审计，不把模块相加当作整仓回归。

首轮冻结全量完成 1914 项 Python（13 个失败断言、4 项跳过）和 157 项 Node（通过）。失败均发生在旧评估器接纳本地请求之前，另以私有有界 stderr 确认回环 502。补充子进程专用 NO_PROXY 并保留继承的代理/排除项后，原取消、多轮及选定 PowerShell 失败用例通过；诊断固定码同时补齐实际 quick-tunnel 退出原因，未知或杜撰名称仍脱敏。首轮原生 desktop 字段及缓存抓取时间的字节漂移不归因于已知主体，原件与失败保护门保留，路由和模型记录相同也不改判通过。这些局部跟进结果不替代最终整仓或实机验收。

最后七个受影响模块通过 244 项（未选 Bash 一项跳过）；CLI/Node/选定 PowerShell 指纹不变。后续缓存新增一条目录记录并保留原十条，再次观察到抓取时间变化，没有合成夹具标识，仍不推断归因或回滚。最初全量、后续模块、原生配置保护及 Desktop/Web 各自保留结果，两个保护门均未通过。

原沙箱包装器未启动测试子进程的未完成记录、旧代码的三项诊断失败、loopback 未到达的两次 502、观察器路径拼接错误及一次启动前语法错误均保留。原生取消的新长路径夹具又在 Windows SQLite 初始化阶段失败，未进入取消；缩短 home 并保留用例映射后通过。EOF 立即关闭未回复 RPC 的等待，不把启动失败记录成取消超时。这些夹具修复不改变产品代理、权限、历史或安装。真实 Desktop Stop 按钮和 ChatGPT Web 仍为独立验收，alpha143 本机安装及 preview.2 附件未更新。

## 2026-10-23 授权后的实际采用

所有者随后要求将有价值的逻辑用于优化项目。本次只修复已复现的隧道观察竞态，并将配置事务及工具历史的验证缺口补成隔离回归；下方同日研究阶段的候选和旧结论仍保留。沿用固定来源，只学习方法，由本项目独立编写，没有复制上游代码或新增运行依赖。

### 隧道观察先核对生命周期，再影响接纳

参考 [tunnel-client 的观察代次边界](https://github.com/openai/tunnel-client/blob/0e4201e5e17dac104a091a16afc5609f6ef68420/pkg/mcpclient/protocol_observation.go)，在 [WebOpenAITunnel.monitor](../../scripts/operator_core/web_openai_tunnel.py) 复现了具体缺陷：健康读取等待期间发生空闲断线，晚到的旧样本仍能重新开放接纳、增加恢复计数并取消原计时器；关闭或观察过期后，状态出口也可能保留旧的 `local_ready=true`。

现在每次空闲中断都使在途健康观察失效。读取后先核对中断代次、准确 child 和终态，再处理成功或验证异常；旧观察既不能恢复连接，也不能用超界响应或异常指标终止新代次。当前代次的非法样本仍固定失败；下一个完整有效观察才可沿原合同恢复。`local_ready` 与同次状态中的当前 `connected` 一致，`poll_observed` 继续表示历史成功轮询事实。原恢复 deadline、一次启动、主动请求断线终态及无重放边界不变，没有新增探测或自动重启。

[隧道回归](../../models/web/tests/test_web_openai_tunnel.py)控制真实异步交错，检查重复中断、关闭/失败/子进程退出、旧异常与当前异常的区别，以及只读状态不触发探测。独立审查另发现 `local_get` 的超界异常也必须经过同一代次检查，已纳入修复，不能仅把指标解析移到检查之后。

### 两个已成立的保护，补成完整行为证据

- [配置事务回归](../../models/common/tests/test_native_models.py)吸纳 [Codex++ `23596ed`](https://github.com/BigPizzaV3/CodexPlusPlus/commit/23596ed9151a0a37ee258a90e24309c10128eca4) 的独立进程竞争验证方法。两个实际解释器竞争同一目标，仅一个可发布；在 catalog 或 profile 发布后直接退出，仍保留原件、两层 claim 与不确定 journal，不能自动接管。恢复预检后出现的新编辑，以及临时文件 fsync 后新建的目标，均不能被覆盖。未发现需要修改现有 `target_lock` / `replace_file` 的缺陷。进程退出夹具不是断电耐久性证明。
- [工具路由回归](../../models/common/tests/test_responses_router.py)吸纳 [CC Switch `91fc2fc`](https://github.com/farion1231/cc-switch/commit/91fc2fcbf7debb7227222b9b18fb41e4745c690a) 与 [Codex++ `845a288`](https://github.com/BigPizzaV3/CodexPlusPlus/commit/845a2882252ad36facb09f4aa6449e56fa440b14) 的跨模式、晚失败组合验证。先通过实际 loopback 获得准确旧调用，再跨 JSON/SSE/WebSocket 验证：切到仅声明 `exec_command` 的 standard 模式后，旧 `exec` 历史不能把 `exec` 重新登记为当前工具；错误结果身份在派发前拒绝；合法首调用之后出现错类型、namespace、旧 call_id 或失败终态时无工具交付且仅一次派发。完整历史、文本分段及元数据保留；无需修改现有转换器，也不引入压缩、角色提升或历史改写。

新事务夹具最初误把 Windows venv 重定向启动器的 PID 当成实际解释器 PID；失败记录保留。夹具改用当前已绑定环境的 base interpreter，并检查实际 `os.getpid()`，确保退出与清理控制准确进程。原失败不是生产事务失败，后续通过也不改判原测试运行。

源码版本为 `4.2.0-alpha.143`，插件包版本未变。定向复现、冻结回归、保护文件观察分别留私有回执，范围见[发布验收记录](release-audit.md)。这些是源码与隔离测试证据，没有部署已装 runtime、升级 tunnel-client、发送真实模型请求或补成 Desktop 实机验收。

完整冻结回归覆盖 101 个 Python 模块，共 1,897 项、零失败/错误、4 项条件跳过（含子场景）；157 项 Node 全部通过。三个跳过来自符号链接权限，一个是本轮未选定的 Bash 夹具。源码和绑定解释器/CLI 摘要未变。55 个保护对象仅原生模型缓存 `fetched_at` 变化，模型数据及其余 54 个对象未变；保护门仍记失败，写入者未确认且未回滚。运行后只补充本段验证结果和表述，另行通过发布审计，不把文档补充说成重新跑了一次完整回归。

## 2026-10-23 再次研究：候选与已有覆盖

本轮从 52 份已跟踪 Markdown 梳理出 17 项外部仓库/问题来源，核对默认分支、正式发布、固定源码与既有本地实现。完整状态、许可和不可访问项见[来源复核表](../../models/web/docs/web-background-sources.md)。下述判断来自实际阅读的补丁和本地代码，不是上游功能或本机实测通过声明。本轮只更新研究记录，没有新增实现、测试、skill、运行依赖或界面，也没有运行上游产品、升级服务或发送模型请求。

主参考 Codex++ 固定到 [`35c682058ba82083c75aecd04529d08780e33918`](https://github.com/BigPizzaV3/CodexPlusPlus/tree/35c682058ba82083c75aecd04529d08780e33918)，提交于 2026-10-23 08:12:15 UTC；相对上次 `6105d570` 的[完整比较](https://github.com/BigPizzaV3/CodexPlusPlus/compare/6105d57019083f8bbb2483399fa4bcdaadc92497...35c682058ba82083c75aecd04529d08780e33918)为新增 193 个提交。查询时最新正式版 [v1.11.2](https://github.com/BigPizzaV3/CodexPlusPlus/releases/tag/v1.11.2) 发布于同日 08:12:29 UTC，解引用后的 tag commit 与本次 main 相同；这次不能沿用 10/17 的“main 在正式发布之后”判断。[固定点许可](https://github.com/BigPizzaV3/CodexPlusPlus/blob/35c682058ba82083c75aecd04529d08780e33918/LICENSE)仍为 AGPLv3，本轮没有复制代码。

| 优先级与准确来源 | 值得学习的方法 | 本地对照与下一步证据范围 |
| --- | --- | --- |
| 优先补验证：[Codex++ `23596ed`](https://github.com/BigPizzaV3/CodexPlusPlus/commit/23596ed9151a0a37ee258a90e24309c10128eca4) | 稳定锁、revision、不可变 catalog 与最后发布指针；真正启动两个进程验证一胜一冲突，并在发布失败后保留外部新修改 | [replace_file / target_lock](../../scripts/operator_native_models.py)已有原字节复核、flush/fsync、目标 claim 与失败终态；[并发测试](../../models/common/tests/test_native_models.py)目前主要以线程和注入构造交错。值得在一次性 home 补独立进程竞争、发布阶段退出及恢复保留后续编辑的组合验证。尚未确认锁或发布实现存在缺陷；不引入读/保存入口自动接管 pending。 |
| 优先补组合用例：[CC Switch `91fc2fc`](https://github.com/farion1231/cc-switch/commit/91fc2fcbf7debb7227222b9b18fb41e4745c690a)与 [Codex++ `845a288`](https://github.com/BigPizzaV3/CodexPlusPlus/commit/845a2882252ad36facb09f4aa6449e56fa440b14) | 工具模式切换后，旧 exec 历史不能使当前模型调用未声明工具；把 namespace、声明变化、截断和晚到失败放入完整往返验证 | [历史适配](../../scripts/operator_core/responses_tool_adapter.py)已有严格配对、opaque/未知调用拒绝及终态工具门；[现有负例](../../models/common/tests/test_responses_tools.py)继续保留。候选是 code-mode exec → standard exec_command、准确旧结果与当前声明的组合拒绝，不是重写历史或触发上一个模型压缩；合成拒绝不证明 Desktop 同聊切换。 |
| 补强目录/分页验证：[Chat On Steroids `772f670`](https://github.com/totec448-spec/chat-on-steroids/commit/772f670cbb672b15cde9375bbb291c0ca93c561c)、[WebCodex `f8ddfe8`](https://github.com/yyjeqhc/webcodex/commit/f8ddfe84f8a23c905937964b08661116d847d8a4)与 [a0cb170](https://github.com/yyjeqhc/webcodex/commit/a0cb170ea6ab48651e8a752938aa77e4d921c740) | 完整目录约束在各层一致，续页绑定同一资源/版本，准备 I/O 后再检查来源 | 本地 [IndexedWebRequest](../../scripts/operator_core/web_mcp_transport.py)从完整请求生成分页，使用固定请求快照及单次 key；[Web 启动](../../scripts/operator_web_startup.py)已有依赖 I/O 后复核。可补大目录与中途变化的组合场景；不照搬上游 64 工具上限、自动刷新或新 Skill store。 |
| 待证实需求的诊断建议：[tunnel-client 固定源码](https://github.com/openai/tunnel-client/blob/0e4201e5e17dac104a091a16afc5609f6ef68420/pkg/mcpclient/protocol_observation.go) | 进程存活、启动就绪、同代次工具发现、完整连续分页与请求交付分别留证；只读 health 不发协议探测，旧 child/epoch 的观察必须失效 | 本地 [status / monitor](../../scripts/operator_core/web_openai_tunnel.py)已有 local_ready、poll_observed、准确子进程及固定诊断分类；不能把它们写成工具授权或执行成功。额外目录观察属于候选诊断需求，尚未获实施或升级授权；先验证代次过期、分页不完整和 status 零协议探测。v0.0.17 的发布不等于这些源码都在本周新增。 |
| 官方兼容测试参考：[Codex `60adfa8`](https://github.com/openai/codex/commit/60adfa8513f77c27826f0c5b770e7a7d4eca538e) | 精确 `model_not_found` 终态在 HTTP、SSE 和 WebSocket 的分类及零重试测试 | 本地已有单次派发、错误/失败终态拒绝和原生透传，可把新原生错误形状加入下一次明确版本的兼容矩阵，不自行重分类原生失败。该提交在 10/23 的 main，晚于 0.164.0 正式发布；本机只读版本仍为 0.163.0-alpha.11.2，未据此认定已支持。 |

另外两项可作为后续夹具来源：[Chat On Steroids `c31e892`](https://github.com/totec448-spec/chat-on-steroids/commit/c31e8923696c86ffb7b66316ea8cad2914f678c1)提示编辑器 style 展示节点可能污染原文判断；[CC Switch `2dfc848`](https://github.com/farion1231/cc-switch/commit/2dfc848f4d67cf6e2e8e0bad8b270f2a2531cf83)验证 Windows 监听 socket 不被子进程继承。前者不能授权清洗/重绑定用户原文，后者是 Rust/mio 的具体问题，不能推断 Python/aiohttp 有相同缺陷；本轮均没有确认对应本地故障。

### 已有覆盖与不适用的更新

- Codex++ [同名模型精确分组](https://github.com/BigPizzaV3/CodexPlusPlus/commit/83527acc6f6377f5a3c28c64c125ff68a7c3fa19)和 [rename 前 flush](https://github.com/BigPizzaV3/CodexPlusPlus/commit/a9e87e30e6795db5bf1e21893f962b9442f823af)的原则已覆盖；本地按准确注册/端点身份选路，同步写入已有 flush/fsync，不重复实现菜单注入或异步下载器。
- codex-chatgpt-web 的[跨聊委托来源](https://github.com/miuuyy/codex-chatgpt-web/commit/c3f707179bdbcfb9987b9677d1eb8eeced3306d4)及[纯 agent 输入压缩](https://github.com/miuuyy/codex-chatgpt-web/commit/4ad190fefbe0dc3991d64d6dd76fefd703d33da6)可用于审查来源边界。本地显式 named-result codec 完整保留原对象、metadata 和 absent/null，不提取 XML 或推断真人意图；不移植角色提升、重建压缩或编排。这两项是 v6.1.13 之后的 main 源码。
- Codex++ [缓冲输出后的自动重试](https://github.com/BigPizzaV3/CodexPlusPlus/commit/a966eff1c20896bd7c9bcd0df1f292cef862800b)、[按 Payload 启发式转换 encrypted_content](https://github.com/BigPizzaV3/CodexPlusPlus/commit/dbd6b30cf1174cd154ee47055ca738be9b6bd114)、[退出等待后强退并返回 0](https://github.com/BigPizzaV3/CodexPlusPlus/commit/64da04d60c3dc763bb576dea07a2a210e4b05e22)不适合本地零回放、准确身份和保留不确定失败的合同。缓冲不证明安全重试，强制退出不证明清理成功。
- `ademisler/codex-desktop-custom-models` 的旧固定 SHA 当前不可读取，新仓库历史无法连续比较；其“恢复”是上游自述，不是本项目独立安全认证。`mingrath/chatgpt-sol-local-bridge` 当前公开入口不可访问，不能写成已删除或停更；旧来源、许可和已记录机制均保留，详见来源表。

建议下一项先限定为真实跨进程发布竞争/中断验收，再做跨工具模式历史的组合负例。这些是待开展的验证范围，本次没有把任何候选写成已采用、已部署或当前 Desktop 验收通过。

## 2026-10-17 增量研究与采用范围

本次查询 main 固定到 [`6105d57019083f8bbb2483399fa4bcdaadc92497`](https://github.com/BigPizzaV3/CodexPlusPlus/tree/6105d57019083f8bbb2483399fa4bcdaadc92497)，提交时间为 2026-10-16 15:22:02 UTC；相对首轮固定点的[比较结果](https://github.com/BigPizzaV3/CodexPlusPlus/compare/f55bb64663ba5024ab434017bb6212a0fd9f4bb3...6105d57019083f8bbb2483399fa4bcdaadc92497)为新增 273 个提交。查询时最新正式 [Release v1.9.0](https://github.com/BigPizzaV3/CodexPlusPlus/releases/tag/v1.9.0) 发布于 2026-10-14 17:39:36 UTC；Release 与此后 main 的源码证据分别保留。[当前固定点许可](https://github.com/BigPizzaV3/CodexPlusPlus/blob/6105d57019083f8bbb2483399fa4bcdaadc92497/LICENSE)仍为 AGPLv3；本次继续只吸纳机制和验证方法，独立编写修复，没有复制代码或引入依赖。

| 上游机制及准确来源 | 本地必要缺口与实际采用 | 保留边界 |
| --- | --- | --- |
| [`2a9bb2d` 的 launcher.rs 与 `completed_exec_stream_does_not_wait_for_upstream_eof`](https://github.com/BigPizzaV3/CodexPlusPlus/blob/2a9bb2d22c3466a85848d58006d958c2440a0749/crates/codex-plus-core/src/launcher.rs)：上游发送完成后仍持有连接的回归 | [restore_events](../../scripts/operator_core/responses_events.py)在完整成功终态及显式 `[DONE]` 到达后结束迭代，避免继续等待上游 EOF；返回前校验已收到的整个 chunk 及未完成尾部，尾随事件或垃圾仍拒绝 | 未收到 `[DONE]` 继续保留 EOF 校验；不把参数完成当作响应完成，不采用上游协商重试、失败转移或历史重写 |
| [`38efe6c` 的 connect/app_server.rs](https://github.com/BigPizzaV3/CodexPlusPlus/blob/38efe6c57cb7c6a9f03938b5893ec0d4bb9769a5/crates/codex-plus-core/src/connect/app_server.rs)：桌面升级会使旧 CLI 路径失效 | 以此检查方法复核 [discover_codex_executable](../../scripts/operator_core/beeper_relay.py)，补齐候选已解析后、排序读取 stat 时消失或访问失败的竞态，转换为固定 `codex_cli_unavailable` | 显式路径仍按原选择核验；不自动重新发现、换路径、重启或发送唤醒；失败不扩大为身份可信 |

本地另有独立的 HTTP 头修复：[clean_headers / opaque_response_headers](../../scripts/operator_core/model_router.py)按 [RFC 9110 §7.6.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-7.6.1)汇总每一条 `Connection` 的字段名，包括大小写变体，再过滤逐跳字段；禁止把其中声明的 `Content-Length` 重新加入。不将此项记为 Codex++ 移植；不改变正文、身份、工具执行、容量或重试合同。

### 已有覆盖与未采用建议

- [`d3e7f8e` 的目录 `base_instructions`](https://github.com/BigPizzaV3/CodexPlusPlus/commit/d3e7f8eea11ecfd55544eeaa6963b43bfb9b3c2f)和 [`bf2fbea` 的旧身份不静默改派](https://github.com/BigPizzaV3/CodexPlusPlus/commit/bf2fbea092b938ffa0761c5fabb6a3cf9525c3a4)在本地已有覆盖，本次未重复实现，也不引入聚合路由。
- [`029c6a4` 的 update.rs](https://github.com/BigPizzaV3/CodexPlusPlus/blob/029c6a45263530b3628cdcb10d6265bec158eee8/crates/codex-plus-core/src/update.rs)区分下载、写入与启动，只在已知总字节时计算下载百分比。这是未来可讨论的状态表达方法；本次没有新增更新器、界面、日志内容或自动安装。
- 次参考 Chat On Steroids 固定到 [`666a51858df614105507e13a4995424a95eed4ee`](https://github.com/totec448-spec/chat-on-steroids/tree/666a51858df614105507e13a4995424a95eed4ee)（[MIT](https://github.com/totec448-spec/chat-on-steroids/blob/666a51858df614105507e13a4995424a95eed4ee/LICENSE)）。[`b1a7719` 的空资源/提示目录](https://github.com/totec448-spec/chat-on-steroids/commit/b1a7719086696229a75ae0bcfe7793e46af5364a)针对其新连接握手失败；本机没有对应失败证据，故仅登记兼容候选，不新增协议版本、能力声明或目录处理。
- codex-chatgpt-web 固定到 [`f137c2f84da5df214c1e228d74f5ff43e7641c48`](https://github.com/miuuyy/codex-chatgpt-web/commit/f137c2f84da5df214c1e228d74f5ff43e7641c48)（[MIT](https://github.com/miuuyy/codex-chatgpt-web/blob/f137c2f84da5df214c1e228d74f5ff43e7641c48/LICENSE)）。其回复归属和展开长消息后的再次核验适合作比较；本地已有完整原文、准确用户/回复及文档归属核验，不采用以 broker token 替代完整原文的路径，也不新增页面操作。

定向复现、统一冻结回归、保护观察与实机验收分别保留，本节不推断已部署或实机通过。终态持有连接、同 chunk 尾随拒绝、无 sentinel 的原 EOF 合同、CLI stat 失败及多条 `Connection` 字段分别检查；候选范围见[发布验收记录](release-audit.md)，完整原始结果在私有回执保留。既有失败、完整历史与恢复原件不被研究或新成功改判。

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

## 首轮（2026-10-05）验证与部署边界

三个必要修复及组合回归已写入 canonical 源码；运行前只读核对 Operator 已退出、无活动回调，测试只用纯内存或临时 loopback、私有合成编译，不发送真实模型请求。

| 检查范围 | 实际结果 | 证据限制 |
| --- | --- | --- |
| `test_responses_events` 完整模块 | 31 项通过，零失败/错误/跳过 | 新组合用例为 `test_interleaved_calls_with_delayed_names_and_utf8_wire_preserve_exact_input`，没有真实工具执行 |
| `test_model_router`、`test_responses_profiles`、`test_responses_router` 完整模块 | 101 项通过，零失败/错误/跳过 | 原始工具输出保留；没有另存原始日志文件或回执，不伪称已有 |
| `test_mode_host`、`test_mode_picker_lifetime`、`test_mode_entry` 完整模块 | 24 项运行，23 项通过，零失败/错误，1 项既有 symlink 条件跳过；unittest exit 0 | 新固定诊断解析包含 28 个子案例，实际编译并调用静态方法；未构造真实窗口。私有包装回执要求零跳过，因此仍为 failed，原件保留 |

两源登记/容量诊断修复、选择窗诊断修复和事件组合回归均经交叉只读审查；发布清单纳入本文件，链接、已审文档摘要和内容检查另行复核。未执行全量回归或重新打包，也未更新已安装入口、runtime/cache、活动登记或路由。

源码、合成测试和编译结果不能替代当前服务、真实模型或 Desktop 主窗口验收；旧进程身份受限、真实审批配对和不同新用户首次接入等原有未确认项不因本轮研究而消失。已有失败记录、历史和恢复原件继续保留。
