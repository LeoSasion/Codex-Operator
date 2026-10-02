# 原生 / 拓展启动选择窗

更新：2026-10-02。所有者要求入口小窗左“原生”、右“拓展”，具体型号仍在 Codex 原生对话框内选择；随后明确开始实施，并要求处理新实例的首次个性设置引导。同一聊天跨 provider 的重绑定与跨模式历史迁移已从本轮目标移除。

## 当前实现

`operator_mode_picker.cs` 是两按钮 WinForms 窗口。无参数或 `--preview` 仅预览；`--select` 返回取消 0、原生 10、拓展 20，错误参数返回 2。实际入口使用 `--launch`，绑定准确目录与入口摘要；选择不保存成下次自动启用。

点击拓展后，选择窗保留并显示启动状态，等待控制器返回已核对的进程出生身份、程序和可见窗口，再由这个接收点击的窗口执行普通前台激活。准备过程中不可重复派发。若用户已转到其他窗口而 Windows 拒绝置前，按钮改为“打开窗口”；再次点击只打开已核对的窗口，不重复启动或发送请求。入口仅等待选择器本身退出，不等待它启动的后台服务进程树，避免入口锁持续占用。

`operator_mode_entry.ps1`/`.py` 负责实际启动与精确实例复用：

- 原生通过 Windows 注册应用激活接口打开官方包，不写默认 home 配置、不依赖路由服务。
- 拓展使用独立 `CODEX_HOME`、Electron userData 和窗口 AppUserModelID，只列显式注册的自定义型号，不发现或转发官方模型，不复制登录、原生聊天或其他原生设置。
- 自定义推理由本机路由分发，型号由原生聊天菜单选择。Desktop 继续负责上下文、权限、工具和答案。两种模式分别保留窗口与聊天列表。
- 重开优先唤回精确出生身份的原进程；后台窗口复用只接受同包、同配置的转交，不接受替代进程。失败与不确定记录保留且不重试。

旧共享配置激活不能满足“官方入口始终原生”，没有接回本次模式入口。本机官方主窗口始终保持运行，默认配置哈希在实机检查中未变。官方菜单、原生语音与业务聊天不继承拓展模型能力声明。

## 首次启动引导

`operator_mode_onboarding.py` 仅识别 **26.928.3736.0** 的精确资产 SHA-256。首次创建空白拓展 home 时，只初始化本地 `electron:onboarding-projectless-completed` 偏好，避免重复的职业/项目个性设置。实际空白实例已直接进入正常聊天界面。

不选职业、不勾选个性化同意、不填身份、不跳登录/安全/权限步骤；已打开状态不改写。未知版本或资产变化保留官方正常引导，不猜新字段。

## 搜索与凭据

新准备必须显式选择 `--search official-current-user` 或 `--search unavailable`。前者采用 `official_current_user_search_v1`：CLI 的 `standalone_web_search` feature 与 provider `supports_standalone_web_search` 共同声明普通 `web.run`。仅固定官方 `https://chatgpt.com/backend-api/codex/alpha/search` 使用默认当前用户 home 内的现有 ChatGPT access token/account id。读取不复制、不保存、不刷新；登录仍由官方应用管理。

原生模型、图片和未知端点仍拒绝。外部模型只使用各自注册的凭据，不带官方搜索凭据、cookie 或账号头。搜索失败不重试、不换来源。`unavailable` 明确将该独立 home 的托管搜索设为不可用，不改原生或项目配置，也不声称有搜索能力；其他注册执行工具仍由 Desktop 管理。

首条真实 GLM 文本请求曾被适配器以 `unsupported_tool_type` 拒绝，失败保留。全本地当前 CLI 夹具已复现旧配置发出的 hosted `web_search`，并验证新普通搜索调用、完整结果往返与凭据分离。不同的新实机 GLM 输入已返回正确答案；不因此将任意模型、全部工具或长历史标为通过。

官方依据：[Codex 0.159.2 工具选择](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/core/src/tools/spec_plan.rs)、[配置 schema](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/core/config.schema.json)。

## 停机更新与入口绑定

私有目录为 `.codex/operator-mode-entry/<32位随机标识>`。准备绑定官方包、源码、Python、目录、注册表与凭据文件指纹；不修改原生 home。正常退出拓展窗口后，显式 `service-stop` 须得到服务空闲确认、精确进程退出与独占端口可用，才保存停止记录。Windows 后台路由使用 `CREATE_NO_WINDOW`，实机未出现额外 Python 控制台。

`refresh-preview`/`refresh --expected-preview-sha256 …` 只在窗口与服务已确认停止时更新拥有的启动文件，保留原件与缺失状态、完整聊天和其他设置。旧搜索配置可显式加入 `--enable-native-search`；预览绑定完整替换配置，事务只新增两项搜索声明并保留原字节。失败、部分更新、原生并发编辑或未知服务记录停止，不自动重跑。

已安装入口绑定此目录时，禁止独立刷新。`models mode-maintenance pair-prepare`、`pair-preview`、`pair-apply` 通过准确 `--root`、返回的 `--stage` 和 `--expected-preview-sha256` 完成绑定升级。窗口和服务须先正常停止；准备保留启动原件，应用同时更新独立入口与配对归属链，保留原生快捷方式字节、固定原生 helper 和完整 home。它不创建旧安装 runtime 的首次归属，也不启动 Desktop 或服务。

显式后端更新可在 `pair-prepare` 同时选择私有 `--registry-file` 与 `--web-profile` 目录。
注册更新保留现有每一型号、端点、凭据来源和顺序，只允许明确的 Responses 合同更新或降低
现有容量。Web 必须是已登记且准确 ready/idle 的保存服务，取消观察的 home 须绑定本拓展
目录。准备、预览与应用重复核对同一代次和源文件；事务只增添注册表与模型目录两个受管
文件。Web 密钥只在服务绑定的内存中，不写入注册表。已接纳请求与旧 WebSocket 保留原
快照，菜单出版、服务绑定和实际对话仍分别验收。失败或不确定更新保留，不自动重跑。

本轮已安装此后端更新，真实菜单显示原 6 项和 3 项 Web 型号。Huihui 的隔离 CLI 已完成
三次真实窄范围工具调用与五项文件测试；早期 Desktop 的两次新文本请求仍保留为 HTTP 500。
LM Studio 的日志与无推理模板渲染确认其后置系统消息拒绝，准确模板兼容已单独准备并在
实际加载实例完成只读渲染复核。修复与恢复范围见[Huihui 模板说明](../../local/docs/huihui-template.md)。
第一条 GPT-5.6 Sol/high 的 Desktop 新请求保留为 300 秒路由读取超时，未回放。
绑定 Web 的新读取期限为 900 秒，普通 API/Local/原生仍保留 300 秒；浏览器配置期限、
MCP 截止、容量、单次读取与零重试均未变。两个传输的真实延迟夹具已通过，后续主窗口
文字、接续、工具和压缩结果按日期独立记录。所有者报告的 GPT-6 Pro 额度耗尽，因此当前验收
选择其他已观察位置；目录项存在不构成剩余额度或可用性证据。

旧版单纯置前失败可独立使用 `focus-preview` / `focus-review` 复核：仅接受固定 `mode_foreground_not_granted`、无转交进程、原 Desktop 正常退出且原生配置不变，并绑定完整原记录。追加复核回执，不改变原失败或自动重放。`retire-pair-preview` / `retire-pair` 也仅接受入口锁拒绝且所有安装文件仍为原字节、从未开始发布、服务与窗口已确认停止的更新；原失败、原件与候选均保留，未来更新使用全新事务。部分写入和其他未知失败不能走此退役路径。

10 月 2 日另一条实机启动已打开拓展窗口，但保存子进程身份前发生 `mode_host_failed`，
HRESULT 为 -2147467261，没有生成 `desktop-started` 或窗口见证。这个数值也属于 .NET
空引用异常，不能单凭数值称为 COM 故障；源码立即解引用可能为空的 `Process.MainModule`
与现场阶段一致，但旧记录没有堆栈，因此具体语句仍是推断。新宿主使用 Windows 内核
`QueryFullProcessImageName` 核对准确映像，并记录固定故障阶段；实际暂停在模块加载前的
私有子进程已验证映像可读、主模块未就绪，测试只终止它自己创建的夹具。

独立 `startup-preview` / `startup-review --attempt …` 仅复核这种准确的早期空引用记录，
须保留六个完整原件、准确计划和未变的原生配置，并确认该目录的 Desktop、宿主和选择器
均已退出。预览还绑定当前拓展配置，保留 Desktop 已保存的选模；应用仅追加复核回执，
不制造正常退出或成功启动，不恢复配置、不启动或重放。其他错误、部分身份记录、仍运行
或未知进程、预览后文件变化都拒绝。复核后可独立停止原空闲路由，再进行新的配对升级。
这次原失败保持失败；新宿主的实机启动须另外验收。

官方自动更新不自动重绑旧入口。所有者要求恢复时，`pair-prepare --package-update` 仅在
拓展进程已退出、路由有正常停机或独立缺席复核时，准备同一官方包家族的更高版本。
候选只更新包身份与本地引导合同，再沿用原摘要预览/应用；当前包 manifest、程序摘要、
源码、原生配置与原件在每个写入边界复核。已有 home/userData 不重建，不改欢迎状态，
未知引导资产按官方行为处理。普通启动与普通刷新继续拒绝包变化，不隐式降级或恢复。

完整 `intent/running` 对应的路由进程消失且没有 stop/失败/部分维护记录时，可以显式
`router-absence-preview` / `router-absence-review --expected-preview-sha256 …`。须正常退出
拓展、核对所有包代次的该目录进程都不存在，并独占路由端口；复核保存原入口及原运行
记录摘要，不生成 `stopped.json`，不声称服务曾空闲或正常停止。部分、变化、仍运行或
无法观察的记录继续拒绝。未来由新显式启动创建新代次，旧输入不恢复或回放。

10 月 2 日实际官方更新至 26.930.2377.0 后，这两项独立维护已完成。新拓展窗口恢复
原聊天列表与 Web 选择，原生当前进程与配置保持不变。当前实际 App Server/CLI 为
0.159.0-alpha.12.1；九项独立 CLI 搜索、工具历史及手动/自动压缩夹具通过。新包的
实际 Huihui 手动压缩与不同新文件接续已通过，两个更新后失败回合完整保留。
Web 搜索实际收到两次配对工具结果，但最终超时；另一条原生 Stop 已取消准确回合，
浏览器身份复核未通过并关闭，稳定保留/复用失败。显式空白浏览器恢复后已核对 ready/idle，
不回放旧输入、不将准备状态当作实机通过。最新冻结源码完整回归为 1,632 Python
（30 跳过）及 134 Node 全部通过；审批、自由格式 patch 和全容量自动压缩仍未确认。
详情见[发布审计](../../../development/docs/release-audit.md)，不继承前一包或其他模型结论。

依据：[MainModule 的可空返回](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.process.mainmodule)、
[内核映像路径查询](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew)。

卸载先检查全部隔离目录，运行、失败或不确定记录须先处理，不能只检查旧端口就归档 Python。聊天目录不属于因此新造的旧安装 runtime 所有权。

`models desktop-pair prepare-build -IsolatedModePath <entry.json>` 准备模式入口候选，再沿用精确预览、备份、配对更新与恢复链。新原生快捷方式使用 `registered_application_v1`，不恢复旧共享路由，不要求关闭正常运行的原生窗口。原迁移历史与恢复限制保留。

## 验证范围与平台限制

已观察两窗口分离、首次引导省略、6 个自定义菜单项和显式停机更新。同一真实聊天中，GLM 新文本回答 77，切换 DeepSeek 后根据历史回答 82；随后 DeepSeek 实际发起一次 `web.run`，准确配对结果含微软官方文档，最终答案返回相同链接。原生逐轮元数据确认 provider 始终为 `operator_extension`，模型分别为 `api/glm-5.3-flash` 与 `api/deepseek-v4-flash`。GLM 实际 effort 为 low，DeepSeek 为 none；UI 的“中”标签不证明有效 medium 设置。

实际配对入口已安装为 **ChatGPT 原生入口** 和 **ChatGPT 拓展模型 10-02 入口**。从真实拓展快捷方式打开选择窗后，冷启动拓展、左侧回到原生、再次右侧回到同一个拓展进程均已通过；选择器和外层启动器随之退出，后台服务继续运行。真实双击原生快捷方式也回到原来的原生进程。整个验收中原生主进程持续运行，默认配置哈希不变。

本地/Web 后端继续单独验收；可见性不等于可用性，原未验证标签保留。本轮未继承旧 Web 服务或启动/加载本地模型，复杂工具、全部后端与长上下文仍非这次基本入口验收结论。

搜索后切回 GLM 的新请求也已完成，原生记录保留原始答案 `77, 82`，未重写或截断工具历史。
这四个明确验收回合均有成功终态；同一服务另外保留一项 `http_connect` 传输失败，普通
计数未提供其请求身份，不将其归到某个已完成回合，也不擅自解释为自动标题失败或重试。

拓展启动通过 `Invoke-CommandInDesktopPackage` 传递私有环境。微软将其定位为调试工具，token 不保证与正常 AppId 进程完全相同；当前实机通过不等于所有 Windows/官方升级版本的生产保证。未改官方 exe、签名、manifest 或系统权限。

原生激活使用 `IApplicationActivationManager.ActivateApplication`，已观察回到原生主进程。此前 `explorer shell:AppsFolder` 未完成切换的失败保留。来源：[包进程入口](https://learn.microsoft.com/en-us/powershell/module/appx/invoke-commandindesktoppackage?view=windowsserver2025-ps)、[注册应用激活](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-iapplicationactivationmanager-activateapplication)。

前台置换遵循 [SetForegroundWindow 的系统规则](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow)，没有更改系统权限或使用全局前台授权。后台命令打开原生快捷方式时曾未置前；真实文件夹双击随后通过，两项证据分别保留，不把后台启动当作用户点击验收。早先拓展置前失败与入口等待整棵进程树的缺陷也保留；修复后的相关回归共 50 项，49 通过、1 项符号链接环境检查跳过。完整测试运行曾有 4 个失败和 1 个错误，均为旧夹具；修正后的对应模块及入口回归通过，不能表述为重新跑过的全量全绿。

原始提交、未提交源码与[模型切换复盘](native-model-switching-lessons-20261002.md)保留。不继续跨模式历史改写，不将隐藏思考或转发降低质量写成已证实根因。
