# 两个职能板块

总名与插件名：**Codex-Operator** / `codex-operator`。一个插件，按需配置 Channels 和 Models。

| 模块 | 负责 | 实现范围（验收另列） |
| --- | --- | --- |
| Channels | IM 登录、消息与附件接收、准确任务映射、结果回传 | 飞书已实现；其他 IM 待扩展 |
| Models / API | 原生 profile 添加与撤回、Responses 调度、工具协议适配 | 独立 profile 与拓展模式；同一 provider 内已有实测，跨 provider 不作首发保证 |
| Models / Local | 本地服务发现、原生 profile 添加与撤回 | LM Studio 发现；不自动下载或加载模型 |
| Models / Web | 固定连接、保存网页登录、后台页面与原生工具往返 | ChatGPT Web 独立 provider 预览；新任务接入需助手协助 |

实现不等于稳定发布验收；准确型号、日期和未完成门槛见[支持矩阵](development/docs/first-release-readiness.md)。

两个板块共享 Codex Desktop 的任务归属。Channels 不复制业务上下文，Models 不接管工具执行，Web Providers 不改变原生审批与权限。

公开使用入口是 `scripts/codex-operator.ps1`：`status` 汇总两个板块，Web 位于 `models.providers.web`；通道操作用 `channels <操作>`，网页提供方操作用 `models web <操作>`，API/Local 原生配置用 [`models native <操作>`](models/common/docs/native-models.md)，可选调度沿用 `models <路由操作>`。整体移除使用根命令 `uninstall`；`channels stop` 只停止通道，`channels uninstall` 会拒绝，避免误卸整个产品。

```text
Codex-Operator
├── channels/feishu/         飞书接入与远程操作
├── models/
│   ├── api/                API Providers
│   ├── local/              Local Providers
│   ├── web/                Web Providers，包括 ChatGPT Web
│   └── common/             三类提供方共用的协议与调度
├── shared/                 Codex 接口、安装、桌面入口与恢复
├── development/            发布与跨板块验证
└── scripts/                当前安装及运行入口，保留已绑定的路径
```

common、shared 和 development 是内部组织，不是额外插件。文档、测试、示例与第三方许可已放入对应功能目录。当前运行脚本保留已有位置，因为保存的 Web 连接和启动计划绑定准确路径与摘要；源码搬迁必须与安装映射、已停止服务的重新绑定一起实施，不能用重复源码或符号链接假装完成。现有旧飞书目录名属于内部安装兼容，源码权威仍只有本插件目录。

## 状态与安装入口

统一入口只读检查时，会区分未安装、未配置、正在启动或连接、需要人工协助，以及暂时无法检查。检查不可用不会被当作配置丢失，也不会要求重新登录。`status` 的 JSON 使用 `checked` / `partial` 区分完整和部分结果，部分结果退出码为 2；不代表执行失败的业务请求需要重发。

安装目录中的统一入口引用安装时记录的插件源码入口，并核对路径与文件摘要。插件入口丢失或变更时会停止转交，保留已有数据；由助手从当前插件源码核对并升级。运行目录不再被当成另一套完整插件源码。

## Channels 中的模型选择

Channels 也是无法方便使用 Desktop 时的远程操作入口，因此需要模型选择能力。已实现 `/model` 读回当前原生任务模型设置、`/model list` 列出官方模型、`/model <名称> [思考强度]` 保存下一条新消息的选择，以及 `/model cancel` 取消待应用选择。源码验证、安装更新与实机收发分别记录。首版只开放经当前原生目录与官方直连校验的模型；API、Local、Web 的任务级选择仍待原生路由接入。

2026-09-22 的真实飞书验收完成同一任务切换至 Luna/low、再恢复 Astra/high。两条新业务消息均核对了原生实际回合模型、一次转交、准确回调与对应飞书回复；固定 Beeper 保持 Luna/low。模型列表、保存选择与设置读回属于控制指令，未额外调用模型。该结果不覆盖外部提供方或新用户自动建任务。

Channels 解析指令、定位准确绑定任务并展示结果；Models 与原生任务设置层负责校验和应用选择。默认只作用于该任务，不改变全局默认、不改变固定 Beeper，不在执行中替换模型或重放请求。选择保存在准确绑定上，改绑清除；单次发送边界消费后不再次覆盖 Desktop 设置。未选择时仍省略模型参数，失败或不确定不重放。保存、已交给发送流程和原生设置读回分别展示；设置读回不等于消息执行成功。

## 保留与隔离

每个功能目录内可有 `_quarantine/`，存放该功能的待确认旧内容；不能明确归属的才放 `shared/_quarantine/`。未审核材料保留完整字节，成功、失败及不确定的记录继续保留；隔离区不加入 Git、发布清单、安装源或测试发现。原位置记录仅供溯源，不是目录组织方式。

浏览器登录资料、任务数据库、恢复事务与在用解释器继续放在现有私有运行目录。它们有明确用途，不归为垃圾。旧版本代码或参考项目也不能仅凭日期判为废弃。

所有者授权清理后，可按逐文件核对结果删除无运行引用的缓存、可重建依赖和重复解压副本；留下来源、摘要、实际删除回执与必要的精确副本。经验与操作步骤见[项目文件复盘与清理](development/docs/workspace-maintenance.md)。清理不等于升级、卸载或功能验收。

新增 IM 通道应实现账号与权限配置、事件规范化、稳定会话范围、附件传输、出站投递，并复用现有准确任务映射和回传边界。当前没有为未实现的 IM 创建占位登录按钮或虚构支持状态。

预览版以打通安装与实际使用为优先，连续运行稳定性后续完善。容量、原生直连、防重复执行和凭据边界继续保留。

## 文档导航与阅读顺序

先按任务选择一份指南；需要改协议或查证历史时再深入。日期记录中的“当前”“未部署”仅指
当时检查点，不覆盖后来的交付；个人选择、研究结论和历史批准不自动授予其他安装操作权限。

| 用途 | 入口与专题 |
| --- | --- |
| 安装与使用 | [插件说明](README.md)、[快速开始](QUICKSTART.md)、[现有 skill](skills/feishu-codex-operator/SKILL.md)、[旧文档入口](feishu-codex-operator-skill.md)、[升级](upgrade-operator.md) |
| 当前支持与待验收 | [发布准备](development/docs/first-release-readiness.md)。发布、本机安装和运行状态各有证据，日期记录不是实时状态。 |
| Channels | [首次接入](channels/feishu/docs/automatic-task-provisioning.md)、[命令](channels/feishu/docs/feishu-command-ux.md)、[认证](channels/feishu/docs/feishu-auth.md)、[客户端](channels/feishu/docs/feishu-desktop-client.md)、[E2E 经验](channels/feishu/docs/beeper-e2e-lessons.md) |
| 共享边界 | [架构](shared/docs/architecture.md)、[术语](shared/docs/terminology.md)、[权限与 Hooks](shared/docs/permissions-and-hooks.md)、[安装与恢复](shared/docs/installation-and-removal.md)、[公开规则镜像](assets/AGENTS.feishu-codex-operator.md) |
| API / Local | [原生登记](models/common/docs/native-models.md)、[路由合同](models/common/docs/model-router.md)、[Responses 验收](models/common/docs/responses-acceptance.md)、[API 日期证据](models/api/docs/official-online-models.md)、[Huihui 模板](models/local/docs/huihui-template.md) |
| Web | [运行指南](models/web/docs/native-web-experience.md)、[连接引导](models/web/docs/web-fixed-tunnel.md)、[目录合同](models/web/docs/web-model-catalog.md)、[集成概览](models/web/docs/chatgpt-web-integration.md)、[当前计划与历史阶段](models/web/docs/native-conversation-plan.md) |
| 入口与事务 | [模式选择窗](models/common/docs/mode-entry-window.md)、[原生路由恢复](models/common/docs/native-route-recovery.md)、[Windows 替换见证](models/common/docs/windows-config-transaction.md)。按保存的实现代次维护，不能混用恢复链。 |
| 历史统一入口的维护合同 | [隔离候选](models/common/docs/unified-picker-candidate.md)、[只读准备](models/common/docs/unified-picker-preparation.md)、[标记释放](models/common/docs/unified-marker-release.md)、[一次性冷启动](models/common/docs/unified-cold-launch.md)、[旧激活退役](models/web/docs/legacy-activation-retirement.md)、[初始化前恢复](models/web/docs/web-preinit-recovery.md) |
| 研究与前阶段方案 | [工具兼容计划](models/common/docs/responses-tool-compatibility-plan.md)、[直连入口记录](models/common/docs/direct-profile-entry.md)、[未部署菜单候选](models/common/docs/native-menu-provider-candidate.md)、[模型切换复盘](models/common/docs/native-model-switching-lessons-20261002.md)、[保留搜索思路](shared/docs/retained-desktop-search-idea.md) |
| 开发与验证 | [工作区维护](development/docs/workspace-maintenance.md)、[升级检查](development/docs/upgrade-checklist.md)、[测试](development/docs/testing.md)、[发布日期记录](development/docs/release-audit.md) |
| 历史与来源 | [Web 历史](models/web/docs/native-web-history-20260924.md)、[10 月 2 日升级](development/docs/upgrade-20261002.md)、[9 月 21 日恢复](development/docs/core-recovery-20260921.md)、[Codex++ 采用](development/docs/codexplusplus-adoption.md)、[实现来源](models/web/docs/web-background-sources.md)、[致谢与许可](NOTICE.md) |

操作以当前源码命令合同和保存的准确登记为准；文档出现分歧时先核对源码和日期，不直接执行旧命令。
维护分工和校验要求见[文档维护约定](development/docs/workspace-maintenance.md#文档维护约定)。
