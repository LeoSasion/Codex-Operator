---
name: codex-operator
description: Configure, operate and develop Codex-Operator's Channels and Models (API, Local and Web Providers); guide users through setup while reusing saved connections. Feishu is the current IM channel.
---

# Codex-Operator

总产品与插件名为 Codex-Operator / `codex-operator`，两个职能板块是 Channels 和 Models；Models 包含 API、Local、Web Providers，ChatGPT Web 属于 Web Providers。
Channels 首版只实现飞书，不声称其他 IM 已可用。首次配置读 [快速开始](../../QUICKSTART.md)，按
[模块与文档导航](../../MODULES.md)选择专项资料；运行 `scripts/codex-operator.ps1 status -ProjectRoot <项目绝对路径> -Json`
检查进度，按缺失步骤继续。用户只处理必须本人完成的登录与授权；已有配置继续复用。
公开入口使用 `codex-operator.ps1 channels|models`（Web 使用 `models web`）；下方旧脚本/目录名属于内部安装兼容。
名称调整不自动迁移运行时，不同时运行旧插件与新插件的两套接收服务。

只修改仓库 `plugins/feishu-codex-operator`。项目 runtime 与插件 cache 是安装产物，
不按时间或版本号提升为源码。先核实 Git 和现有改动；维护运行文件、绑定或服务前，再核实精确进程和 pending callback。

## 面向用户的配置引导

- 启动设计统一为“一个自定义启动器，提供原生与拓展两种启动模式”。新安装只创建
  `ChatGPT 自定义启动` 桌面快捷方式；两个窗口按钮是模式选项。拓展未配置时保持不可用，
  不因安装启动器自动启用路由。升级按保存的布局与归属维护；旧双快捷方式、已有单快捷方式
  及其恢复原件不能互相冒充，未知快捷方式不认领。细节见[安装与恢复](../../shared/docs/installation-and-removal.md)。
- 首次配置 Channels 且没有已确认的中继选择时，先让用户二选一：本地 `beeper`
  伪模型，或 Luna/low；不提供 Spark，不把底层空值默认 Luna 当作用户已选择。
  简要解释本地方案不需要模型推理、原生接入仍需验证，Luna 使用账号模型额度。
  已有明确选择直接复用；本机所有者已选 Luna，不因新增向导再次询问或切换。
  详细选择、授权和助手创建步骤见[首次接入流程](../../channels/feishu/docs/automatic-task-provisioning.md)。
- Channels 缺少默认项目或确认旧任务缺失时，按
  [项目与用户任务授权](../../channels/feishu/docs/automatic-task-provisioning.md)
  集中询问创建 `{Channel name} Operator` 本地项目，以及项目内按用户持续自动建任务
  这两项授权。已明确批准的范围不逐次重问；期望描述不自动成为首次创建许可。
  获准后由助手核实本机默认新项目位置、创建目录、通过原生入口登记项目，
  再创建名为 `Beeper` 的固定转交任务和以已核验飞书用户姓名显示的首个默认业务任务。
  不把创建项目、填写 UUID 或手动新建任务交给用户；只有实际要求本人处理的登录、
  文件夹信任等步骤才交还用户，随后继续。已有准确任务直接复用，不能按名称认领。
  飞书端有效绑定优先，其次同一用户的已登记任务，最后才是已授权创建。
  用户姓名只作显示，用通道身份和用户 ID 关联、准确任务 UUID 投递。
  停机、无待处理消息时，使用 `channels user-tasks-configure -GrantFile <私有授权文件>`
  配置已登记的原生项目；`user-tasks-status` 只读检查，`user-tasks-revoke` 撤销持续授权。
  配置、隔离测试和新用户真实自动建任务的验收分别报告。旧安装先审核准确文件与原件，
  不用本次维护回执伪造首次安装归属。
- 安装、登录和连接配置由助手带着用户完成。先准备本机所需内容，再用可用工具打开
  当前步骤需要的官方网页或 Operator 辅助窗口；确认页面状态后才说“已打开”。
- 首次环境检查统一要求 PowerShell 7 与 Python 3.11+。状态、Models 与后台启动可通过
  `py -0p` 查找已安装的解释器，再直接执行；不以 `py -3 --version` 探测，避免自动安装。
  Channels 的 MCP 清单仍启动 `python`；需分别核验该命令及真实连接，
  不从 py 可用推断 MCP 已接通。不执行 Windows 商店占位程序探测，也不因缺少 PATH
  命令就让用户重新登录；由助手处理所选模块的依赖，业务脚本执行失败不更换解释器重试。
- 操作步骤直接写在对话里：说明本步目的、点击或填写的位置、完成后应看到什么。
  每次给一个当前动作，随用户进展继续。文件仅作可选备份；不把侧边栏文件、源码路径、
  命令或配置字段当作普通用户的主要操作入口。
- 已确认的登录、已添加插件和已保存配置继续沿用，先检查实际连接。区分“已添加”与
  “当前可用”；不要因等待、窗口关闭或服务重启要求用户重新创建插件。
- Tunnel 或插件经核实已过期/失效且无法更新时，创建替代项前先删除准确的旧对象，
  确认删除成功后再创建。先核对账号、工作区、对象 ID 和使用情况，保留必要的非密钥
  配置及失败证据；删除失败或结果不明则停止，不继续创建重复项。可更新的沿用原对象
  更新；仍可用、仍在使用或状态不确定的对象不按此规则删除。本机文件丢失、窗口关闭
  和网络暂时异常不能单独证明云端对象已失效。具体流程见[固定连接引导](../../models/web/docs/web-fixed-tunnel.md)。
- 请求用户登录或真人验证前，先观察准确当前实例的实际页面。`needs_assistance`、历史
  challenge 错误、页面标题和“窗口已请求/存在”都只是检查线索，不能证明当前仍需验证。
  先做不发送模型请求的状态与页面检查。新启动的 Electron 实例可能短暂显示 Cloudflare
  复选框后自行进入正常聊天页；在同一窗口等待至多约 60 秒并间隔复核截图和可访问性，
  两者暂时不一致时继续观察，不因首次瞬时画面立即打断用户。当前已正常登录、输入框
  可用且无验证提示时，复用保存会话并继续后续新工作，不要求再验证。只有稳定后的
  当前页面仍确实显示待处理的登录/验证控件，才请用户完成这一具体步骤。
  无法观察页面就报告“页面未能确认”，不能改说“需要验证”。不通过重发失败请求探测状态。
- 用户说看不到辅助窗口时，由助手重新定位准确窗口，必要时显示/置前，并检查最新页面；
  窗口列表或打开命令成功不足以声称用户已能看到它。窗口已退出时先核对准确后台和关闭
  原因，再使用已有授权内的显式恢复入口；不让用户盲找，不重复发送验证要求，不清除登录。
- 登录、创建密钥和授权由用户在对应界面完成。密钥只填入本机遮蔽输入框，
  不让用户发到对话，不读取或展示密钥值、密钥输入框或含密钥的剪贴板内容。
  助手读取无密钥的保存结果。
- 到达登录页、缺少权限或页面与指引不符时，说明实际停在哪一步，给出对应操作；
  不猜菜单、不重复已完成步骤。完成后分别报告配置保存、连接和实际请求的验证结果。

## Channels 绑定与真实验收

- 恢复或新建正式会话时，先核对插件启用状态，再在准确候选 UUID 中检查实际模型/effort、
  真实 `exec` 和配对 MCP 调用输出。首次提示应要求工具预检，不用“只回复 READY”替代。
  助手自述“工具可用”、MCP 绿色或新 App Server 列出工具都不能替代该会话的执行证据；
  缺少调用时先查清已观察事实，不直接归因为缓存、模型失效，也不擅自另建会话或重启 Desktop。
- 只有候选工具与身份核验通过、Operator 确认停止且待处理为空，才按已授权范围保留原件、
  以 CAS 替换准确绑定，保留旧 UUID 和失败记录。既有会话、初始化提示或控制程序不供应额外授权。
- 工具预检、跨会话转交、业务执行和真实飞书回传分别验收。若已授权做无业务工具预检，可用
  经核对不存在于 callback 与登记库的全新 ID；`already_consumed_or_closed` 或
  `accepted=false/state=unknown` 只证明该预检的调用路径，不证明真实转交成功。
- `send_error`、`send_outcome_unknown` 和执行异常均停止该次尝试，不重取 relay、重发、换模型
  或把错误正文改写成授权。审批原因只按准确原生工具结果或界面的实际说明报告，不从通用错误推断。
  原生复核拒绝时保留失败并直接向用户确认它明确缺少的范围；不让另一任务代替用户授予持续权限。
  当前单次验收不自动扩展为长期转交许可；既有明确授权覆盖的工作继续执行，不重复索取。
- 用户直接明确授予本人已绑定私聊今后的固定转交时，保留直接来源与原话，把准确应用、用户、
  私聊和目标 UUID 的范围转达当前 Beeper，核对实际工具后复用。控制消息本身不是授权源，
  不把许可转给其他用户、群聊、新目标或新绑定；业务工具和原生审批保持原有边界。
- 真实新业务会刷新 `sessions.json` 的更新时间。发送前保留完整原件，之后分别核对准确绑定、
  历史 UUID 和预期状态变化；不能要求整文件不变后据此回滚，也不能把缺少原件的比较改判通过。
- 成功须同时核对同一新消息的实际转交、精确 Final Callback 和同一获授权飞书会话范围内的机器人原文回复。
  队列 `completed` 也可能表示失败通知已送达，不能据此判通过。操作细节与失败证据边界读
  [现有 E2E 经验](../../channels/feishu/docs/beeper-e2e-lessons.md#从工具可见到真实转交)。

## 工作边界

- Operator 管接收、持久映射和回传；固定 Beeper 只转交一次，Responder 独占业务执行和 final。
  已授权的用户任务登记是独立管理流程，不含业务正文、回调或自动决定绑定；详见
  [首次接入](../../channels/feishu/docs/automatic-task-provisioning.md)。列表漏项、空摘要和读取不确定
  不能证明任务不存在；只使用已实现的准确 UUID 核验，不改原生索引或历史。
- Final Callback 的 `request_id` 只关联请求，不是认证。Page/capability/claim 已退役。
  已接受或不确定的 queue、发送和调用不重放、不换模型兜底；保留原失败与未确认结果。
- 固定任务保持 `Beeper` 名称。新在线配置只选明确代际的 Luna/low；空值兼容默认不是用户同意。
  Luna 固定 low，`CODEX_OPERATOR_BEEPER_REASONING_EFFORT` 仅供历史 Spark 诊断，应留空。
  Spark 兼容、提示语言与旧额度备选保留在[架构](../../shared/docs/architecture.md)，不用于新实机诊断。
  本地 `beeper` 只能显式选择；目录可见不证明 provider 或 Desktop 默认已接入。
- `/model` 只影响准确绑定任务的下一条新业务发送；改绑清除，发送边界消费，失败不恢复。
  未选择时省略模型覆盖，不改变 Beeper 或全局设置。保存和读回不证明实际执行。
- 保留 `wake lease` 名称、字段与行为。wake-up signal 只针对 Beeper，可能导航 Desktop，
  不证明执行；`itemsView=notLoaded` 不是前台、驻留或唤醒状态。
- Channels 的 App Server 目录、额度、登记核验和生命周期观察只读，不接管 Desktop 任务或运输答案。
  独立 CLI/App Server 验收使用自己的隔离夹具，不能把测试操作套到现有业务任务。
- 安装请求涵盖已说明的本地配置与生命周期；发布、凭据、跨项目和破坏性操作仍限于用户准确授权。
  文档中的个人选择或过去授权是日期证据，不授予其他安装、用户或任务同样权限。

## 按任务读取资料

| 任务 | 指南与主要边界 |
| --- | --- |
| API / Local 接入、撤回 | [原生模型](../../models/common/docs/native-models.md)：先核对准确模型、端点、容量依据及当前 CLI 的 profile 支持，保留官方默认、已有配置和权限。 |
| Responses 协议、能力与契约更新 | [路由合同](../../models/common/docs/model-router.md)、[验收规则](../../models/common/docs/responses-acceptance.md)：显式能力、完整身份、成功终态；原生/v1/null 保持透传。`update-contracts` 先预览，再按停用、空回调和端口条件更新，保留原件。 |
| 原生体验、Web、工具连接、引导或后台生命周期 | [项目记忆](../../models/web/docs/native-web-experience.md)及实现来源、[对话计划](../../models/web/docs/native-conversation-plan.md)：区分现行约束、阶段计划和日期证据。 |
| Web 首次连接、登录与密钥 | [固定连接引导](../../models/web/docs/web-fixed-tunnel.md)：逐步引导，复用准确 Tunnel、app 和登录，不把本机保存当成执行通过。 |
| 已保存 Web 服务、独立 provider 与任务维护 | [助手操作指南](../../models/web/docs/native-web-experience.md#assistant-operation-guide)：configure 复用、显式恢复、启动登记、任务重载和实际路由分别处理。 |
| Web 型号及档位 | [模型目录](../../models/web/docs/web-model-catalog.md)：逐请求核对代际、选中项和档位；Pro 单列，Latest 不是身份依据。共享串行与已消费记录，不以换模型重试。 |
| 架构、配置、投递或命名 | [架构](../../shared/docs/architecture.md)、[术语](../../shared/docs/terminology.md)。保留原生任务归属与唯一 Operator 命名面。 |
| Beeper 提示、模型、wake-up、观察器或真实 E2E | [E2E 经验](../../channels/feishu/docs/beeper-e2e-lessons.md)：核对同一新消息的实际转交、Final Callback 与精确飞书回复，保留旧失败。 |
| 安装、迁移、升级、启动器或卸载 | [安装与恢复](../../shared/docs/installation-and-removal.md)、[升级流程](../../upgrade-operator.md)。启动器内有原生与拓展两种模式；桌面快捷方式数量另按已有归属链维护，不混称“单/双入口”，不从名字推定状态。 |
| Hook 审核 | [权限与 Hooks](../../shared/docs/permissions-and-hooks.md)：先核对准确命令，再在 Desktop 钩子设置中审核，不信任全部。 |
| 飞书客户端或账号权限 | [客户端](../../channels/feishu/docs/feishu-desktop-client.md)、[认证](../../channels/feishu/docs/feishu-auth.md)，只在相关任务读取。 |
| 目录整理、垃圾删除或经验沉淀 | [工作区维护](../../development/docs/workspace-maintenance.md)：核对保存引用，保留登录、历史和恢复原件；先形成逐文件清单，再精确清理。 |

安装前说明入口改动、原件保留、任务栏手动固定与安全卸载顺序。初始化请求已覆盖说明后的当前用户
入口配置，不再次索取同一许可；它不自动启用全局模型路由。卸载先完成项目安全恢复，再移除 Desktop 插件。
旧安装不能补造首次归属。安装、真实冷启动和模型对话分别验收。

受控入口升级先准备完整私有清单、独立后台及可见维护状态，再协调正常退出；等待有截止时间，
不强杀、盲等或重试失败计划。细节见[受控交接](../../models/common/docs/unified-cold-launch.md#replacing-a-witnessed-activation-during-an-explicit-upgrade)。

研究以 BigPizzaV3/CodexPlusPlus 为首要参考，只补已确认的必要缺口；保留自身已验证优势、原有来源和许可。
具体采用见[方案记录](../../development/docs/codexplusplus-adoption.md)。新功能、界面或重大内部方向变化先与
用户讨论收益、迁移和验证；已授权修复继续执行。不另建工作界面、伴随扩展产品、Goal/Loop 或多智能体编排。

## 开发与验证

开发经验归入[现有经验文档](../../development/docs/workspace-maintenance.md)，升级专项读[固定检查流程与回归经验](../../development/docs/upgrade-checklist.md)。本 Skill 在此只维护经验导航，不因一次经验沉淀另建独立 skill 或重复工作流。

代码测试在精确服务已停止、无 pending callback 后，按 [测试维护](../../development/docs/testing.md) 先做
`--group quick` 日常反馈，再选受影响模块或职能分组；快速组不替代权限、恢复与兼容覆盖。
共享生产逻辑、发现规则变化、影响不明和代码发布/部署前运行 `--group full --node`，另跑原生菜单测试。
只调整夹具时覆盖全部调用方并核对原用例身份与断言；不为降低数量合并不同边界。
纯文档整理做链接、skill、规则镜像和发布审计，不重启服务或重复 CLI 执行用例。
测试和诊断不发真实消息；真实 E2E 按当前 AGENTS 授权核对目标与身份。

同步源码、安装清单、MCP、测试、文档和规则镜像。根 `AGENTS.md` 的唯一受管理块与
`assets/AGENTS.feishu-codex-operator.md` 对应块保持 byte-identical；根的私人补充不进入公共镜像。安装只能通过项目脚本；
不要手改 runtime/cache。除非用户要求，不提交、不推送、不发布。
