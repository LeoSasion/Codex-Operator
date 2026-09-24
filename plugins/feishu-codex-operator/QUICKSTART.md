# 开始使用 Codex-Operator

Windows 预览版包含 Channels 与 Models 两个板块；Models 下分 API、Local、Web Providers，ChatGPT Web 属于 Web Providers。可以按需配置。正常对话、文件、工具执行和审批仍由 Codex Desktop 负责。

## 安装插件

先准备 Windows、官方 Codex Desktop、PowerShell 7 和 Python 3.11 或更新版本。Channels 使用飞书官方 CLI；Models/Web 的 Python 依赖列在 `scripts/model-router-requirements.txt`。Web 还需要 Electron 和官方 Secure MCP Tunnel 客户端，首次接入由助手检查并准备。

把发布包解压到一个长期保留的位置。在 Codex 的插件管理中添加该目录内的本地 Marketplace，安装 **Codex-Operator**。本仓库中的 Marketplace 清单位于 `.agents/plugins/marketplace.json`。不要把解压目录放在用完就清理的临时文件夹中。

安装后，在需要接入的 Codex 项目中输入：

> 使用 $codex-operator 帮我配置 Codex-Operator。先检查已有配置，分别告诉我 Channels 与 Models 下一步需要做什么；模型区包括 API、本地和 Web。只让我操作必须本人完成的登录与授权。

助手应先运行 `scripts/codex-operator.ps1 status -ProjectRoot <项目绝对路径> -Json`，按当前状态继续。这个命令不启动服务、不修改配置、不发送模型请求。不要将源码目录或安装缓存的更新时间当成版本依据。

状态、Models 和后台启动会检查 Python 版本；如需使用 `py`，先列出已安装的解释器，
再直接使用其程序，不触发启动器自动安装或运行 Windows 商店占位程序。
Channels 的插件工具仍要求可用的 `python` 命令，
首次检查会单独核对这一点，由助手处理环境配置，避免把“检测到启动器”误当成工具已接通。

如果显示“暂时无法确认”，现有配置会继续保留，由助手核对无法检查的部分；这不等于需要重新安装、登录或创建连接。启动中、连接中和已打开辅助窗口也会分别显示。

## Channels：从聊天软件发起任务

首版实现飞书私聊、群聊和话题，其他 IM 尚未实现。

告诉助手“配置飞书通道”。首次接入先选择固定转交方式：**Luna/low**（使用账号模型额度），或 **本地 Beeper 伪模型**（不需要模型推理，目前仍需验证原生接入）。Spark 不再列入选项；已有选择、登录与任务映射直接复用。

助手会集中询问是否允许创建 **Feishu Operator** 项目、固定 **Beeper** 和以你飞书姓名显示的默认业务任务，以及是否允许今后为获准用户自动创建/续用任务。获准后由助手核实本机默认位置并完成创建和配置；你只处理必须本人完成的登录或文件夹信任，不用自己建项目、任务或填写编号。详见[首次接入流程](channels/feishu/docs/automatic-task-provisioning.md)。

绑定完成后直接在飞书发消息；需要另选任务时才使用 `/init`。未授权自动登记的用户仍可用 `/init` 选择已有任务。只有实际收到同一请求的对应回复才算收发通过。自动新用户创建、本地伪模型接入与已有任务收发分别验证，不把“安装成功”当成全部就绪。

在飞书发送 `/model` 查看当前绑定任务的原生模型设置，`/model list` 查看可选官方模型。例如 `/model luna low` 为下一条新消息选择 Luna/low；之后按正常方式发送需求即可，不需要返回 Desktop 点击切换。`/model cancel` 可取消尚未应用的选择。此操作不改变固定 Beeper；API、Local、Web 的任务级切换仍待接入。

安装会设置当前用户的 **Codex拓展入口** 快捷方式与项目 Hooks，保留原件；任务栏固定项可能需要你手动重新固定一次。

日常启动、状态与停止统一使用 `codex-operator.ps1 channels start|status|stop`。账号安装与登录入口是 `channels cli-install|configure|login`；更详细的设置由助手调用现有模块命令完成。

## Models：API 与 Local Providers

告诉助手准确的服务、模型名称和用途，例如“接入我的 LM Studio 模型”。凭据填写在本机相应配置界面，不发送到对话中。

助手先验证官方 provider 直连，再按实际缺口选择 Responses 适配。登记、工具往返、Desktop 显示分别检查。当前统一全局路由不是默认安装步骤；保留官方原生模型直连。模型模块的命令入口为 `codex-operator.ps1 models <操作> --state-dir <私有目录>`；参数由助手填写。

支持范围取决于具体端点与工具模式，不能从模型名称推断。详见 [模型接入](models/common/docs/model-router.md) 和 [实际验收规则](models/common/docs/responses-acceptance.md)。

## Models / Web：在原生任务中使用 ChatGPT Web

告诉助手“配置 ChatGPT Web”。首次接入需要你的 ChatGPT 登录、固定 Tunnel、运行密钥及准确的 app 绑定。助手按 [首次连接流程](models/web/docs/web-fixed-tunnel.md) 准备本机表单并逐步引导。密钥直接填到本机遮蔽输入框，后续复用保存配置。

配置完成后，用 `models web start` 启动保存的后台，`models web status` 检查状态。只有状态要求协助时才用 `models web assist` 打开辅助窗口；处理完关闭窗口即可。失败的请求不会自动重发。

已有保存入口时，再次要求助手配置会直接复用原设置和运行程序，无需重填位置、连接编号或密钥。不带新设置的 `models web configure` 只核验并确认复用，不更新登记或启动后台；首次配置和明确升级仍由助手提供必要参数。访问受限、登记不符、运行程序变化和检查结果不可用会分别说明，由助手按具体原因继续处理。

首版保留独立 Web provider：助手使用 `models web desktop-prepare`、`models web desktop-connect` 登记，再完成你明确选择的任务接入。**仅登记 provider 不会自动把主窗口模型菜单全部打通，也不会创建或切换你的任务。** 当前已接入 Web 的任务可继续使用；新任务接入仍需助手协助，不应宣称已具备一键全局切换。无需在项目或全局配置中关闭 Codex 搜索；Web provider 对已核对的可选实时搜索声明使用 ChatGPT 网页自己的搜索与来源引用。带域名、位置、缓存、索引等无法对应的要求会在网页提交前明确拒绝。GLM、DeepSeek 等模型的搜索方式按各自型号及接入端点单独验证；网页有来源引用不等于 Codex 执行了原生搜索工具。

如果已登记的 Web provider 因后台显式重启而指向旧实例，`models web desktop-status` 会显示 `stale`；后台就绪且空闲后，由助手执行一次 `models web desktop-rebind`，保留原 provider 名称和任务绑定，并备份原配置。运行中的 Desktop 是否采用新地址须另行验收；失败请求不能重发。

日常入口：`codex-operator.ps1 models web start|status|assist|inspect|stop`。验证编码闭环可明确要求助手执行 `models web verify`；这会用新样例调用一次真实网页模型。它不属于普通状态检查。

## 升级与卸载

升级前检查已有实例和待完成请求，按模块升级；保留固定连接、登录、任务与失败记录。预览版不自动恢复未知占用或重新执行失败操作。

卸载时先停止准确的后台并解除独立 Web 登记，再由助手使用根命令 `uninstall` 运行项目安全卸载预览和应用操作，最后从 Codex 移除插件。直接在插件列表点“移除”不会替你恢复快捷方式或 Hooks。详细顺序见 [安装与移除](shared/docs/installation-and-removal.md)。

已有旧版飞书 Operator 的项目继续保留原运行目录。插件改名不自动搬迁旧运行时、账号或任务；迁移需先停止准确服务并核对原有记录。
