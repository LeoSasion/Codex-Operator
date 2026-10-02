---
name: codex-operator
description: Configure, operate and develop Codex-Operator's Channels and Models (API, Local and Web Providers); guide users through setup while reusing saved connections. Feishu is the current IM channel.
---

# Codex-Operator

总产品与插件名为 Codex-Operator / `codex-operator`，两个职能板块是 Channels 和 Models；Models 包含 API、Local、Web Providers，ChatGPT Web 属于 Web Providers。
Channels 首版只实现飞书，不声称其他 IM 已可用。先读 [快速开始](../../QUICKSTART.md) 与
[模块职责](../../MODULES.md)，运行 `scripts/codex-operator.ps1 status -ProjectRoot <项目绝对路径> -Json`
检查进度，按缺失步骤继续。用户只处理必须本人完成的登录与授权；已有配置继续复用。
公开入口使用 `codex-operator.ps1 channels|models`（Web 使用 `models web`）；下方旧脚本/目录名属于内部安装兼容。
名称调整不自动迁移运行时，不同时运行旧插件与新插件的两套接收服务。

只修改仓库 `plugins/feishu-codex-operator`。项目 runtime 与插件 cache 是安装产物，
不按时间或版本号提升为源码。开始变更前核实 Git、现有改动、精确进程和 pending callback。

## 面向用户的配置引导

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

## 工作边界

- Operator 管接收、持久路由和回传；固定 Beeper 的业务转交只发送一次；Responder 独占业务执行与 final。
  已授权私聊的任务登记可在同一固定任务运行独立管理程序：原生项目查询、一次原生创建、
  保存准确返回身份。程序由私有授权生成，不含用户业务正文，不提交业务回调或决定绑定。
- 原生列表漏项不能作为重新创建任务的理由。自动登记可按已知准确 UUID 对空摘要的
  paginated 任务执行受限的 v5 索引只读核验；只接受同一原生 home 的未归档匹配记录。
  未知存储、身份变化或读取不确定保持待审核，不改原生索引、摘要或历史；详见
  `channels/feishu/docs/automatic-task-provisioning.md`。这不扩大 `/init` 的原生可见目录。
- Final Callback 的 `request_id` 仅关联请求，不是身份认证。不要恢复 Page/capability/claim。
- queue 接受或结果不确定后不重放。2026-09-21 所有者要求固定转交任务保持
  `Beeper` 命名；首次选择为本地伪模型或 Luna/low，在线方案只提供 Luna，
  不再选 Spark 或做其实机诊断。Spark 兼容代码及旧验收保留为历史。
  本地方案只能在用户明确选择后配置，不能从目录可见或文件已安装推断原生可用。
- 未配置或留空时底层兼容默认仍为 Luna/low，首次向导必须先取得明确选择。
  排队参数不等于原生任务的实际模型：首次配置通过原生任务工具设置固定 Beeper，
  再核对新回合模型元数据；不能自行覆盖用户业务任务的模型。用户通过 /model 显式选择
  时，仅下一条新业务消息携带经过校验的 model/thinking；不改变 Beeper 或全局设置，
  不为切换额外发送确认轮次。保存选择不等于已生效，/model 读回设置不等于执行成功。
  本地 provider 随运行时安装，协议外输入只返回已确认的固定身份声明。
  目录使用 `visibility: list`，但 Desktop 下拉框及固定任务默认 provider 的接入仍待验证；
  不得以目录可见性代替路由证据，也不能替换原生 provider/catalog 条目而影响 Spark/Luna。
  可选 Python Responses 路由器仅追加目录项，原生请求仍送原生后端；不依赖
  LiteLLM，不转换 Chat Completions。涉及此功能先读 `../../models/common/docs/model-router.md`。
  registry v2 按明确能力适配外部工具，v1/null 保留透传；代码与调用 ID 不改写，
  工具调用仅在成功终态完整校验后交付。探测、隔离 CLI 执行和真实 Desktop 验收分别记录。
  现有登记与已验证源码合同不一致时，先用 `update-contracts` 只读预览；仅在既有停用、
  空回调和端口检查通过后，绑定原登记与候选摘要显式更新。它只改 `responses`，保留原件；
  不改型号、容量或档位，不重试旧请求。参数与恢复边界见上述路由文档。
  能力复用、注册前检查和多轮评测再读 `../../models/common/docs/responses-acceptance.md`；
  私有 profile/receipt 不随发布复制。只读补丁计划与实际文件写入审批分开验收。
  全局入口启用与安装分开；常驻生命周期、原生辅助工具及真实 Desktop 下拉/默认值
  尚未验收，不能根据隔离测试自动启用。
  此处“全局入口”指模型请求路由；可恢复的桌面/开始菜单快捷方式初始化不代表启用模型路由。
  本地 provider 失败或不确定时不兜底。
  所有 Operator 添加给 Spark 的外层指令、内层回调/附件说明
  均用简洁结构化英文，飞书原句不翻译。附件元数据用无损 JSON 转义，不改真实路径。
  旧 Spark 到 Luna 的额度备选和 Spark 推理强度诊断仅作历史兼容记录，当前不选择 Spark。
  中文控制模板仍可供 Luna 显式诊断；不覆盖 Responder 设置，也不构成重试理由。
- 保留 `wake lease` 名称和行为。wake-up signal 是动作，deep link 是当前实现，可能导航
  Desktop；只针对 Beeper，不能据此认定执行成功。`itemsView=notLoaded` 不是驻留状态。
- App Server 只用于目录、额度、无正文生命周期观察，不能接管 Desktop 任务或运输最终答案。
- 用户授权只覆盖其请求；本地安装和生命周期可自动执行，发布、凭据、跨项目变更不自动扩大。

## 按任务读取资料

- 添加或撤回 API、本地模型：先读[原生模型接入](../../models/common/docs/native-models.md)，
  使用 `models native prepare|install|status|restore` 为准确模型配置独立原生 profile 和目录。
  先核对当前 CLI 对文件式 profile 的支持、端点与密钥引用；保留官方默认、已有 profile 与权限。
  旧 `[profiles.name]` 表不能作为当前接入方式。不要仅追加混合目录后声称 Desktop 能切换 provider；
  配置加载、列表可见、真实路由、工具执行与主窗口验收分别记录。API 密钥不发到对话中。
- 原生体验、Web 模型、工具连接、配置引导或后台生命周期：先读
  [长期项目记忆](../../models/web/docs/native-web-experience.md) 与
  [原生对话改进计划](../../models/web/docs/native-conversation-plan.md)。2026-09-20 最新方向以
  Chat On Steroids 为首要研究参考，目标仅为原生 Codex 对话更流畅、减少 UI 点击与配置。
  其余四个参考冷置，仅遇到具体必要缺口才查阅，已有来源与许可记录保留。
  不扩展独立工作界面、浏览器伴随扩展产品、Goal/Loop 或另一套多智能体编排。
  允许大幅内部架构调整；大方向变动须先汇报用户收益、迁移影响与验证计划，再实施。
  记录实际借鉴与验证范围，不将研究结论或上游宣传当作本机验收。
- 改架构、配置或投递逻辑：先读 [Architecture](../../shared/docs/architecture.md)。
- 复盘目录、删除垃圾或整理隔离区：先读
  [文件维护与已验证经验](../../development/docs/workspace-maintenance.md)。核对当前进程和保存引用，
  不按临时目录名或日期判废；保留登录、任务、失败证据及恢复原件。删除前形成逐文件清单，
  核对精确副本或可重建来源，执行后复核配置和服务。公开摘要与私有同名文档分别审阅，
  不用 `git add -A` 把本地复盘记录带入发布。
- 改 Beeper 提示、模型、推理强度、wake-up、观察器或真实 E2E：必须再读
  [Beeper E2E lessons](../../channels/feishu/docs/beeper-e2e-lessons.md)。保留失败样本，不重放；
  成功必须是同一飞书消息经 Final Callback 收到精确关联回复，不能用 Desktop 输出替代。
- 安装、迁移或升级：读 [README](../../README.md) 和 [Upgrade](../../upgrade-operator.md)。
  桌面双入口的命名、日期含义、原生恢复与发布验收只维护在
  [安装与恢复指南](../../shared/docs/installation-and-removal.md#desktop-entry-pair)。
  桌面双入口已实现，支持经审查的旧入口迁移；保留原归属记录，实机冷启动、退出后重开
  和模型连续对话仍需分别验收。
- ChatGPT Web 后台连接、Tunnel ID 或运行密钥配置：先读
  [固定连接与对话引导](../../models/web/docs/web-fixed-tunnel.md)，按其中用户步骤逐步带操作。
  管理已配置的后台服务时读[原生 Web 体验方案](../../models/web/docs/native-web-experience.md)，
  由助手使用持久配置入口，复用准确实例，不让用户重复填写配置或寻找运行目录。
  优先使用统一入口 `models web status|start|assist|inspect|stop`；首次 `models web configure` 由助手登记
  已有设置与准确 Python 路径。已有保存入口的 configure 可省略 Settings/Python，核验原设置摘要、
  程序与完整登记后只确认复用，不更新登记或启动服务。设置/程序变化时先核对，再明确提供设置
  进入既有升级流程；不因省略参数而自动采用变化。入口固定 reason/stage 区分访问受限、登记、
  程序及检查失败；这些情况不能当作丢失配置并要求重新登录。占用记录未经独立进程核对不能当成可自动清除的旧锁。
  已确认异常退出时可显式使用 `models web recover` 预览；按准确摘要应用归档，保留原异常
  和请求记录。它不启动后台，不重放请求；不能从普通 start/status 隐式触发。
  查看已结束对话用 `models web inspect` 的只读文字快照；`assist` 会准备空白聊天，不能
  用来保留旧现场。只读预览不重发请求、不展开卡片，也不能替代工具执行/拒绝证据。
  将该后台接入模型路由时，按原生 Web 体验方案使用显式 `--web-profile` 与
  `bind-web` 内存绑定。摘要回执不含密钥；不要手填端口、复制 session 凭据、
  自动重启现有路由，或把目录追加当作 Desktop 列表/工具任务验收。
  升级已经成功启用的统一入口，先按[受控升级交接](../../models/common/docs/unified-cold-launch.md#replacing-a-witnessed-activation-during-an-explicit-upgrade)
  准备并核验 `prepare-upgrade` 的完整私有清单，再协调用户退出。旧成功记录、用户后来选定的
  模型和显示偏好须保留；失败或不确定的启动不能重置重试。不要让用户先退出，再临时准备恢复。
  2026-09-30 所有者要求避免升级时无反馈地等待：交接必须先确认独立后台和可见维护状态窗口，
  再请用户退出；明确窗口关闭不一定代表应用退出，等待可延期且有截止时间。超时、检查失败、
  官方恢复与升级完成分开报告，不让用户猜状态、反复退出或自行结束进程。具体行为与发布验收
  统一见上述受控交接文档；未完成真实退出闭环前不声称发布就绪。
  用户要求验证编码能力时，可使用 `models web verify`：只在新合成项目中做一次有界真实
  CLI 读取、精确修正与实际测试。失败保留，不重放；回执须区分工具执行与 Desktop
  体验。它会调用网页模型；普通 `status` 等只读检查不能暗中调用它。
  独立 Desktop 验收先用 `models web desktop-prepare` 准备，再用 `desktop-connect` 追加
  供显式选择的 provider；`desktop-status` 查看登记，`desktop-check` 用新原生进程
  只读核对模型目录与提供方（不等于运行中菜单或路由验收），`desktop-disconnect`
  撤回准确片段。服务换代时先以 `desktop-status` 确认 `stale`，核对当前服务
  ready/idle 后显式 `desktop-rebind`，保留原 provider 名称与任务，保存原配置。
  用户明确要求以所选 Web 型号新建任务时，助手先核对保存后台 ready/idle、独立
  provider 已连接、项目位置和准确型号/强度，再通过原生 App Server 的
  `thread/start.modelProvider` 创建专用任务，以新输入调用一次 `turn/start`，
  核对落盘的提供方、实际模型和回合结果后打开该任务的准确 UUID。空任务在首轮落盘前
  不能视为可续用；普通 `create_thread` 不提供 provider 选择，不能替代这一步。
  这仍是助手引导的专用任务入口，不宣称主窗口新任务模型菜单已经支持 Web。
  rebind 只更新保存配置，已加载任务可能仍缓存旧地址。对已授权维护的准确空闲任务，按
  [原生任务重载](../../models/web/docs/native-web-experience.md#reload-an-idle-web-task)
  由助手使用原生归档/恢复工具处理同一 UUID，并读回实际状态；不重建任务、不重启 Desktop。
  操作报错不能当作一定未生效，不盲目重复；确认恢复后才用全新输入验证实际去向，不重发旧失败请求。
  所有者已授权助手代发验收测试消息；先核对准确任务与提供方，发送每次全新的测试输入，
  核对原生任务最终内容和服务证据。任务工具转交与用户亲自在输入框发送属于不同验收范围，
  不能混称。旧长任务若在 Web 索引上下文容量处返回 413，保留历史与失败回合；
  旧版 64 MiB 原生 HTTP 正文修复不适用于 48 KiB/24 页/40 读取的 Web 容量限制。
  如环境提供 Windows Computer Use 且用户已授权操作，可在准确任务的普通 Desktop
  输入框代发一次全新测试消息：先观察任务标题、历史及输入框，确认草稿后只发送一次，
  再分别核对窗口可见结果、原生回合的模型/提供方/工具记录及后台状态。操作结果不明时
  先检查实际回合，不能再次点击发送或重放原请求；桌面输入框实测也不等于用户亲自输入。
  `desktop-status` 的保守验收字段不是已发生的主窗口输入回执。
  不要为 Web 任务在项目或全局 `.codex/config.toml` 关闭 `web_search`：项目设置也会影响
  同目录的 GLM、DeepSeek 和原生任务。Web provider 仅将准确的可选 live hosted
  `web_search` 声明绑定到 ChatGPT 网页自己的搜索路径，不生成 Codex
  `web_search_call`；有缓存、索引、域名/位置限制或强制工具选择时，在网页提交前拒绝。
  该绑定只适用于 Web provider，状态中的 `web_page_auto_v1` 表示路由选择，
  不能单独证明网页实际搜索或结果正确。GLM-5.3 官方直连曾返回服务商托管搜索事件；
  GLM-5.3 Flash 的已验收搜索是 Codex 执行，型号和端点不能混称。
  DeepSeek 官方 Responses 文档说明忽略 hosted `web_search`，适配型号如需搜索须
  单独验证 Codex 搜索工具。保留原生搜索设置、默认路由和旧失败任务。
  官方默认、权限和现有任务保持；新任务必须有明确创建指令。
  登记不是活跃 Desktop 的加载或切换证据，不能据此启用全局路由。卸载前先撤回。
  改浏览器、MCP 或模型执行逻辑时再读
  [ChatGPT Web integration](../../models/web/docs/chatgpt-web-integration.md)。
- 初始化入口或卸载：读 [Installation and removal](../../shared/docs/installation-and-removal.md)。
  首次写入前说明入口改动、原件备份、任务栏手动固定和安全卸载顺序。初始化请求已覆盖
  说明后的当前用户入口配置，不重复索要许可；不自动启用未经配置的模型路由。
  用户要求移除插件时，先预览并执行项目安全卸载，成功后才移除 Desktop 插件。
  不把 Desktop 直接删除插件说成自动恢复，不覆盖后续用户修改，也不伪造旧安装原件记录。
- Hook 审核：读 [Permissions and Hooks](../../shared/docs/permissions-and-hooks.md)。
  首选 Desktop“设置 → 钩子”；Desktop 没有 `/hooks`，Windows CMD 启动 CLI 的动态路径命令仅作备选。
- 命名变更：读 [Terminology](../../shared/docs/terminology.md)。新执行面只用 Operator，
  旧名称仅出现在一次性迁移识别、退役状态和未更名的 GitHub 地址中。
- 飞书客户端安装或权限问题：分别读 [Desktop client](../../channels/feishu/docs/feishu-desktop-client.md)
  或 [Authentication and permissions](../../channels/feishu/docs/feishu-auth.md)，不要默认加载。

## 开发与验证

精确服务已停止、无 pending callback 后，按 [测试维护](../../development/docs/testing.md) 选择受影响模块。
跨层改动和发布/部署前运行全量；纯文档措辞改动执行发布审计，不重复启动 CLI 执行用例。
测试和诊断不发真实消息；真实 E2E 按当前 AGENTS 授权核对目标与身份。

同步源码、安装清单、MCP、测试、文档和规则镜像。根 `AGENTS.md` 与
`assets/AGENTS.feishu-codex-operator.md` 保持 byte-identical。安装只能通过项目脚本；
不要手改 runtime/cache。除非用户要求，不提交、不推送、不发布。

Web 模型目录维护先读 [版本与推理档位契约](../../models/web/docs/web-model-catalog.md)。网页档位以当前可见菜单为准；Pro 单列，“最新”须核对明确代际标签。普通与 Pro 请求共享串行执行和已消费任务记录，不能通过换模型重试。目录准备、CLI 执行、Desktop 菜单与路由分别验收，不为增加菜单项自动恢复全局路由。
