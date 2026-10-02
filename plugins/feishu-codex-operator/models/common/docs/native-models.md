# 原生 API 与本地模型接入

本页是 API、Local 的原生登记与撤回指南。由助手完成检查、生成配置和验证，用户只需提供服务商、准确型号以及必要的本机授权。Web 沿用自己的[独立提供方入口](../../web/docs/native-web-experience.md)。工具适配和全局路由仍见 [model-router.md](model-router.md)，不与原生直连混用。

## 能力与限制

`models native` 为一个准确模型生成一个 Codex 文件式 profile、专属模型目录和 provider。只在显式安装时写入指定 Codex home 的 `operator-*.config.toml` 与对应 `.catalog.json`；不修改基础 `config.toml`、原生默认、权限、任务历史或正在运行的服务。模型请求直接到声明的 Responses 端点，不经过 Operator 路由。

上下文窗口必须绑定**实际选中的模型 ID**及其对应端点的可核对依据。清单中的 `model.context_window` 会写进该模型的目录项；切换型号时重新核对并使用新型号的值，不沿用上一型号或统一常数。API 模型卡的窗口不能直接当作 ChatGPT 网页版的窗口，本地服务列出的最大值也不能代替实际加载模型的验收。来源不足时记录为未验证，不为了让目录可见而猜测数值。

当前已在 CLI **0.158.0-alpha.2.1** 验证文件式 profile 加载，以及隔离配置中的 `config/read`、`model/list`。官方配置说明：`codex --profile <name>` 使用 `$CODEX_HOME/<name>.config.toml`；这是新文件层，不能再生成旧的 `[profiles.name]` 表。项目配置和命令参数仍可覆盖 profile，实际使用前须核对有效配置。参考：[官方高级配置](https://learn.chatgpt.com/docs/config-file/config-advanced)。

当前 Desktop **26.924.2738.0** 的菜单条目没有独立 provider 字段。只追加混合目录不会随模型切换端点，因此此入口提供的是**独立原生 profile 的模型列表**，尚未实现主窗口官方、API、本地模型同菜单切换。`app-server` 也拒绝 `--profile`；不要通过它假装验证 profile。保持官方直连及已有保护，不能为显示几个名称重新启用全局路由。

同版原生 App Server schema 的只读核对进一步确认：`model/list` 请求和返回的模型项均无 provider 字段，`turn/start` 也不能逐回合切换 provider；`thread/start` 虽可指定 `modelProvider`，但会创建独立任务。它不满足“同一主窗口现有任务里选任意提供方”的体验要求。目录、独立任务与 Desktop 主菜单分别验收；在上游支持前不把目录可见性写成菜单可用性。

2026-09-28 的 opt-in 隔离实验 `test_one_provider_routes_two_models_in_same_task` 使用当前 CLI、临时 Codex home 和无真实账号的 loopback Responses 端点，证明同一任务在**同一个 provider** 内连续选择两个模型 slug 时，新用户输入到达各自的模型；固定 413 加上该自定义 provider 的双重零重试配置只发送一次，失败回合仍保留。切到第二个模型前还观察到 Codex 把一次自动上下文检查点发给旧模型，因此模型切换不能简单等同于“只有新模型会收到流量”。实验中 `model/list` 的两个合成条目依赖替换式静态 `model_catalog_json`；只实现 `/v1/models` 不会将它们列出。真实混合目录必须另外保留完整官方条目。这只证明单一合成 provider 的 App Server 行为，不证明官方、API、本地和 Web 在真实 Desktop 主菜单中可无缝切换，也不解除当前官方直连保护。完整隔离用例见 [`test_model_catalog_cli.py`](../tests/test_model_catalog_cli.py)。

## 助手引导流程

1. 读取现有配置与历史证据，核对当前 Codex 版本。API 使用厂商明确支持的 Responses 地址和准确 ID；本地先读取现有服务的模型元数据，不自动下载、载入或猜测工具能力。现有有效的同绑定失败可用于选择后续适配，不能重放旧请求。
2. 在项目私有 `.codex/operator-native-models/` 中为每个选择准备唯一事务目录。使用尚未占用的 profile 名字；未知历史文件及基础配置中的同名 provider 会阻止创建，避免继承旧认证头或丢失原有权限设定。密钥只保存环境变量名称，不能写进清单、catalog、对话或公开仓库；缺少引用值时先核对已有安全保存来源，仍不可用再报告未具备实际调用条件。
3. 从确认的信息生成下述清单，执行 `prepare`。公开预览和后续 `status` 显示准确模型 ID、API/Local 类型、绑定的 Codex home，以及两个目标文件原先是否存在；不会输出端点或密钥环境变量名。核对后再执行 `install`。首次提出“添加模型”已经涵盖已说明范围内的安装，无需重复索要相同许可。
4. 检查保存状态和 Codex 的实际配置加载。`debug prompt-input` 可以确认 profile 文件可加载，但输出没有 model/provider 字段；不能用它单独证明目录、实际路由或工具成功。隔离副本的 `model/list` 只证明该产物可被当前原生版本解析。
5. 使用 `codex --profile <准确名称>` 进入对应原生 CLI 模型列表。需要真实能力验收时，使用新的有限样例，分别核对实际端点、工具声明、调用、执行、结果及产物。登记不等于已加载模型、连接成功或 Desktop 已生效。
6. 撤回前先结束使用该 profile 的会话；执行 `restore`，仅恢复本事务的两个文件。之后不选择该 profile 即继续使用原有默认。已运行会话不由撤回操作强制结束。

统一入口示例（路径由助手填入，不要求用户手工编辑 JSON）：

```powershell
pwsh -NoProfile -File plugins/feishu-codex-operator/scripts/codex-operator.ps1 models native prepare --state <绝对私有事务目录> --home <绝对Codex目录> --manifest <绝对清单路径>
pwsh -NoProfile -File plugins/feishu-codex-operator/scripts/codex-operator.ps1 models native install --state <同一事务目录> --home <同一Codex目录>
pwsh -NoProfile -File plugins/feishu-codex-operator/scripts/codex-operator.ps1 models native status --state <同一事务目录> --home <同一Codex目录>
pwsh -NoProfile -File plugins/feishu-codex-operator/scripts/codex-operator.ps1 models native restore --state <同一事务目录> --home <同一Codex目录>
```

`prepare` 保存原件、缺失状态、待安装内容及摘要，不写 Codex 配置。`install` 先发布完整 catalog，再发布引用它的 profile。`status` 只读，不启动服务或调用模型。`restore` 先撤回 profile，再恢复或移除 catalog，原件和事务保留。文件链接、原件损坏、准备后来源变化、后来修改的文件与不确定事务均停止写入；不自动重试安装。未完成安装可经显式核对后执行恢复，不修改旧失败回执。

安装和撤回还按 home/profile 使用短暂的独占锁，防止两个事务认领同一配置。已开始的写入失败会保留绑定原事务的锁，禁止另一事务接管；显式恢复须匹配它。旧的完整安装记录仍可精确撤回，缺少归属锁的旧中断记录须人工核查，不能凭相同文件内容推断归属或直接删除锁。

产品总览的 `registered_count` 统计可选适配路由，不包含这些独立 profile；原生登记应按保存事务运行 `models native status`。环境变量引用也不等于凭据已经进入当前 Codex 进程，实际调用前由助手核对安全保存来源与所选进程，不能将密钥值填进命令参数或 profile。当前真实登记、恢复和有限工具验收统一记录在[发布审计](../../../development/docs/release-audit.md)。

整体卸载前先撤回仍需移除的原生 profile；通用插件卸载不会扫描任意私有事务目录或代删用户的 profile。恢复完成前不能把事务目录当垃圾删除。

## 清单合同

只接受 `version: 1`、`contract: "native_responses_v1"`，不接受旧路由器注册项，避免绕过已有适配合同。必填字段：

| 字段 | 含义 |
| --- | --- |
| `kind` | `local` 或 `api`；本地只接受字面量 loopback，API 要求 HTTPS |
| `profile` | 唯一的 `operator-` 前缀名称，仅小写字母、数字和连字符 |
| `provider` | `name`、`base_url`、`env_key`；本地无认证时 `env_key` 为 `""` |
| `model` | `id`、`display_name`、`context_window`、`reasoning_efforts`、`default_reasoning_effort`、`input_modalities`、`tool_mode`、`supports_search_tool` |
| `web_search` | 此 profile 独有的 `disabled`、`cached` 或 `live`，不影响其他模型 |

生成的 provider 固定使用 Responses、关闭请求/流重试、不使用官方 ChatGPT 凭据。能力字段必须有显式依据；只是声明，不能从模型名称、参数量或列表可见推断实际支持。原生托管搜索和 Codex 执行的独立搜索也须分别验证，详见[在线模型记录](../../api/docs/official-online-models.md)。

验证入口：`test_native_models` 覆盖精确安装/恢复、后续编辑、链接、摘要变化与中断事务；`test_install_upgrade` 验证实际安装目录可独立加载入口；`test_product_preview` 验证公开命令只读状态。私有实际调用回执不随发布包复制。
