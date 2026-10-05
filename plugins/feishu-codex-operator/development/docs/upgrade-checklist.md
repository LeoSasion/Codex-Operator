# Codex 升级后固定检查流程

更新：2026-10-05。本页用于官方 Desktop/CLI 升级、Operator 源码更新或明确端点合同变化后的人工维护，复用已有检查命令，不新增后台监视、自动升级、自动重试或产品界面。先读[项目记忆](../../models/web/docs/native-web-experience.md)、[原生对话计划](../../models/web/docs/native-conversation-plan.md)及[安装与恢复](../../shared/docs/installation-and-removal.md)。旧版本的通过、失败和未确认记录均保留。

## 1. 开始前建立本轮身份与保护范围

从仓库根目录运行。解释器、CLI、隔离目录和端口必须来自当前已核验记录；示例占位符须人工替换，不能从 PATH、目录名或旧报告推断当前身份。

```powershell
$operatorRepo = (Resolve-Path -LiteralPath '.').Path
$operatorPlugin = Join-Path $operatorRepo 'plugins/feishu-codex-operator'
$operatorPython = '<已有记录绑定的 Python 绝对路径>'
$operatorCli = '<本轮核验的 codex.exe 绝对路径>'
$operatorModeRoot = '<已有隔离模式目录绝对路径>'
$operatorRouterState = Join-Path $operatorModeRoot 'router'
$operatorPort = <已有记录绑定的端口>
```

本轮私有回执至少绑定以下内容，保留完整摘要和 `existed` 状态；公开文档只写结果、固定原因和验证范围。

| 身份/保护对象 | 必须保留的绑定 | 现有核对入口 |
| --- | --- | --- |
| 官方 Desktop | 唯一 Appx 包 full name/family/package_version、manifest 摘要、官方程序摘要；executable_product_version 与独立核验的 desktop_product_version 分开 | `Get-AppxPackage`、`Get-FileHash`；模式入口的 `inspect_package` 另核对 manifest 的 App/executable/entry point |
| CLI 与测试环境 | 准确 CLI 路径、文件摘要、`--version` 原输出及退出码；Python/Node/pwsh/Bash 的版本与摘要 | 准确可执行文件的只读版本命令；不用旧成功替代当前版本 |
| canonical 源码 | Git HEAD、完整未提交差异的范围、发布清单中的逐文件摘要 | release audit 与 `build_codex_operator_release.collect`；已装 runtime/cache 单独比较 |
| 已装隔离入口 | `entry.json`、entry.ps1、三份编译入口、Python、source bindings、当前包与配对归属链 | `operator_mode_entry.py status`；已装配对入口只沿配对维护流程 |
| 目录与端点合同 | 实际 `registry.json`、隔离 `home/models.json` 摘要；每个明确 Responses 合同及其 adapter/evaluator 摘要 | `readiness`、`preflight`、`verification-status`；目录可见不等于能力通过 |
| 保护与恢复 | 本轮列明的原生 config/cache/入口、原恢复 helper/launcher、快捷方式和归属记录的摘要、原件位置、缺失状态 | 既有安装/恢复记录与只读预览；仅算摘要，不将凭据或历史正文复制到回执 |
| 服务与执行状态 | 准确进程出生身份、固定端口、已保存终态；Operator 待办与活动回调数 | 各自已有状态出口。运行中、读取受限、未知或不完整状态不能变成“已停机” |

以下命令只读观察当前包和 CLI，不启动 Desktop、App Server 或模型回合：

```powershell
$operatorPackages = @(Get-AppxPackage -Name OpenAI.Codex)
if ($operatorPackages.Count -ne 1) { throw 'official_package_ambiguous' }
$operatorPackage = $operatorPackages[0]
$operatorExe = Join-Path $operatorPackage.InstallLocation 'app/ChatGPT.exe'
[ordered]@{
    full_name = $operatorPackage.PackageFullName
    family = $operatorPackage.PackageFamilyName
    version = $operatorPackage.Version.ToString()
    executable_product_version = (Get-Item -LiteralPath $operatorExe).VersionInfo.ProductVersion
    manifest_sha256 = (Get-FileHash -LiteralPath (Join-Path $operatorPackage.InstallLocation 'AppxManifest.xml') -Algorithm SHA256).Hash
    executable_sha256 = (Get-FileHash -LiteralPath $operatorExe -Algorithm SHA256).Hash
} | ConvertTo-Json -Compress
Get-FileHash -LiteralPath $operatorCli -Algorithm SHA256
& $operatorCli --version
if ($LASTEXITCODE -ne 0) { throw 'current_cli_version_unavailable' }
```

程序的 `VersionInfo.ProductVersion` 是 executable_product_version，Appx 是 package_version；两者均不能代替界面或本机受支持只读工具观察到的 desktop_product_version。`verification-status --desktop-version` 只使用独立核验的 Desktop 产品版本。若该版本当前未能确认，标记此项未验，不从可执行文件推导。

包身份与当前入口绑定不一致时，标记入口需受审更新；此时不尝试普通 launch。文件摘要检查不能证明准确进程已退出。Windows 的访问拒绝、枚举缺席或窗口关闭都不是准确进程对象不存在的替代证据。

## 2. 先检查源码和已装状态，保留每条命令的退出码

只读源码检查可以先进行。Python `--list` 不导入或运行测试；PowerShell release audit 只做清单、规则镜像、内容筛查、Python 与 PowerShell 语法检查，不构建发布包、不写入 runtime。

```powershell
& $operatorPython -X utf8 -E -s -B (Join-Path $operatorPlugin 'development/run_tests.py') --list --node
pwsh -NoProfile -File (Join-Path $operatorPlugin 'scripts/audit-feishu-codex-release.ps1')
& $operatorPython -X utf8 -E -s -B (Join-Path $operatorPlugin 'scripts/operator_mode_entry.py') status --root $operatorModeRoot
& $operatorPython -X utf8 -E -s -B (Join-Path $operatorPlugin 'scripts/operator_model_router.py') readiness --state-dir $operatorRouterState --port $operatorPort
```

release audit 内部通过 `Get-OperatorPython` 从 PATH 独立发现解释器，不使用上文 `$operatorPython` 变量；须另行记录其实际路径、版本和摘要，不能假定与模式入口绑定的解释器相同。

需要本轮完整源码指纹时，复用发布收集函数，只输出摘要到私有回执，不创建 zip：

```powershell
$operatorSourceFingerprint = @'
import hashlib
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'plugins/feishu-codex-operator/scripts'))
from build_codex_operator_release import collect
data, _, package_version = collect(root)
files = {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(data.items())}
print(json.dumps({'package_version': package_version, 'files': files}, sort_keys=True))
'@
& $operatorPython -X utf8 -E -s -B -c $operatorSourceFingerprint $operatorRepo
```

`collect` 返回插件 manifest 的包版本，摘要标签使用 `package_version`；release audit 的 `source_version` 是 Operator 代码版本，两者分列。官方 Appx 的 `package_version` 另属于官方包身份，不混为同一对象。

`status` 核对当前源码、编译文件、解释器、目录、登记、配置合同及包身份，不启动服务或刷新入口；失败 JSON 和非零退出都须保留。源码更新后出现 `source_changed` 是已装版本不同的观察，不能修改 journal 使它通过。`readiness` 只核对本地登记和已有服务状态，其 `ready_for_global_activation` 仍为 false；`configured_keys_available` 只描述检查进程当前环境，不解密或重写保存凭据，也不证明实际后端连通。

已有单模型注册文件或能力 profile 时，另运行其明确合同检查：

```powershell
& $operatorPython -X utf8 -E -s -B (Join-Path $operatorPlugin 'scripts/operator_model_router.py') preflight --registration '<私有单模型完整注册文件>'
& $operatorPython -X utf8 -E -s -B (Join-Path $operatorPlugin 'scripts/operator_model_router.py') preflight --profile '<私有能力 profile>' --cli-version '<本轮 CLI 版本号，保留预发布后缀>'
& $operatorPython -X utf8 -E -s -B (Join-Path $operatorPlugin 'scripts/operator_model_router.py') verification-status --registration '<同一私有单模型注册文件>' --desktop-evidence '<原有私有 Desktop 证据账本>' --cli-version '<同一 CLI 版本号>' --desktop-version '<本轮已准确核验的 Desktop 产品版本>' --model-sha256 '<已明确绑定的型号身份摘要>'
```

只运行实际存在且属于准确对象的检查。缺少 profile、Desktop 账本或型号摘要就记录未验，不新建成功记录；已有失败不改判。`verification-status` 是原有证据复核，不重新执行模型。版本、合同、adapter/evaluator 或原证据改变时按原检查结果记录陈旧/不匹配，不把旧 profile 转移给新型号。

## 3. 按变更范围运行现有快速回归

实际测试前，确认准确 Operator 实例退出、待办和活动回调为零；保护范围在前后保持同一份清单。使用已有隔离测试环境和临时夹具，不指定真实聊天、凭据或任务历史。测试前后源码摘要必须一致；另一任务正在改同一源码或受保护配置时，先完成协调再冻结新一轮输入。

### 本轮测试输入

完整回归和含 CLI 的模块必须显式绑定 `CODEX_OPERATOR_TEST_CLI`；目录用例另绑定 `CODEX_OPERATOR_TEST_CATALOG`。不能用 `CODEX_CLI_PATH` 代替。PowerShell 与 Bash 是原有合同中的附加终端诊断：执行前记录本轮选定的用例，分别绑定 `CODEX_OPERATOR_TEST_POWERSHELL` 或 `CODEX_OPERATOR_TEST_BASH`，不把两种 shell 变成产品运行依赖。选定的 CLI/shell 都使用本机已经存在且核验过的准确可执行文件；先记录其绝对路径、文件摘要、版本与退出码，不从 PATH 名称或旧成功推定。选定输入缺失导致的 opt-in skip 是配置缺项；明确未选定的诊断另列为未验，均不能算通过。真实平台条件跳过另列。详见[附加终端合同](../../models/common/docs/responses-acceptance.md#bounded-cli-evaluation)。

`CATALOG` 指向本轮新私有目录中的原生 `models_cache.json` 精确字节副本。复制前后核对当前原件和副本 SHA256，保留缺失、改变或失败的记录；不下载目录、不调用真实模型，也不修改或合成原生 cache 来满足测试。另在私有回执保留本轮原生 config/cache 前后原字节和摘要；即使测试完成，保护字节变化仍须单列失败或待审，不自动豁免、不推断原因、不回滚当前内容。

选定终端诊断时，在执行前明确记录 Windows backend 与期望结果。2026-10-05 原完整运行选择了两项夹具、`CODEX_OPERATOR_TEST_WINDOWS_SANDBOX='unelevated'` 和 `CODEX_OPERATOR_TEST_TERMINAL_OUTCOME='passed'`，其 Bash 进程失败仍保留；不能事后取消选定用例或改期望来重判该运行。后续新的范围可明确选择其中一项，并清除未选定夹具的继承变量。全部选择仅用于 disposable CLI 子进程；保留 read-only/never、准确 shell 身份、参数与原文件字节核验。不进行自动 fallback、UAC 设置或 host 配置变更，也不证明用户 Desktop 的终端选择。策略拒绝仍保留实际失败；不能事后把期望改为 `policy_rejected` 来配合本轮结果。

下面示例明确选择两项终端诊断，只改变当前测试进程的四个路径输入与两项终端夹具选择，并在 `finally` 恢复原值和原先缺失状态；也可由受审包装器仅向测试子进程传入同一组变量。只选择 PowerShell 时，须在新运行前保存范围，并将示例中的 `CODEX_OPERATOR_TEST_BASH` 值设为 `$null`，保留其原值恢复步骤；Bash 不获得通过记录。不得写入用户/系统环境或改变用户/全局 `CODEX_HOME`，隔离 home 由已有夹具创建。选定完整或受影响模块的一次执行；需要模块运行时，仅替换 `try` 内现有 `run_tests.py` 的参数。

```powershell
$operatorPwsh = '<本轮已核验的 PowerShell 可执行文件绝对路径>'
$operatorBash = '<本轮已核验的 Bash 可执行文件绝对路径>'
$operatorCatalogSource = '<当前原生 models_cache.json 绝对路径>'
$operatorCatalogCopy = '<本轮新私有目录中的 catalog-source.original 绝对路径>'
foreach ($operatorExecutable in @($operatorPython, $operatorCli, $operatorPwsh, $operatorBash)) {
    Get-FileHash -LiteralPath $operatorExecutable -Algorithm SHA256
}
$operatorCatalogBeforeHash = (Get-FileHash -LiteralPath $operatorCatalogSource -Algorithm SHA256).Hash
if (Test-Path -LiteralPath $operatorCatalogCopy) { throw 'test_catalog_copy_already_exists' }
[System.IO.File]::Copy($operatorCatalogSource, $operatorCatalogCopy, $false)
$operatorCatalogCopyHash = (Get-FileHash -LiteralPath $operatorCatalogCopy -Algorithm SHA256).Hash
$operatorCatalogAfterHash = (Get-FileHash -LiteralPath $operatorCatalogSource -Algorithm SHA256).Hash
if ($operatorCatalogCopyHash -cne $operatorCatalogBeforeHash -or $operatorCatalogAfterHash -cne $operatorCatalogBeforeHash) {
    throw 'test_catalog_source_or_copy_changed'
}
$operatorTestInputs = [ordered]@{
    CODEX_OPERATOR_TEST_CLI = $operatorCli
    CODEX_OPERATOR_TEST_CATALOG = $operatorCatalogCopy
    CODEX_OPERATOR_TEST_POWERSHELL = $operatorPwsh
    CODEX_OPERATOR_TEST_BASH = $operatorBash
    CODEX_OPERATOR_TEST_WINDOWS_SANDBOX = 'unelevated'
    CODEX_OPERATOR_TEST_TERMINAL_OUTCOME = 'passed'
}
$operatorOriginalInputs = @{}
foreach ($operatorInputName in $operatorTestInputs.Keys) {
    $operatorOriginalInputs[$operatorInputName] = [Environment]::GetEnvironmentVariable($operatorInputName, 'Process')
}
$operatorTestExitCode = $null
try {
    foreach ($operatorInputName in $operatorTestInputs.Keys) {
        [Environment]::SetEnvironmentVariable($operatorInputName, $operatorTestInputs[$operatorInputName], 'Process')
    }
    & $operatorPython -X utf8 -E -s -B (Join-Path $operatorPlugin 'development/run_tests.py') --node
    $operatorTestExitCode = $LASTEXITCODE
} finally {
    foreach ($operatorInputName in $operatorTestInputs.Keys) {
        [Environment]::SetEnvironmentVariable($operatorInputName, $operatorOriginalInputs[$operatorInputName], 'Process')
    }
}
if ($null -eq $operatorTestExitCode -or $operatorTestExitCode -ne 0) { throw 'test_run_not_passed' }
```

完整回归的父包装器等待上限设为 3600 秒：历史一次完整运行耗时 2166.633 秒，1800 秒不足。3600 秒仅用于整套测试的行政等待，不改变产品模型、请求、工具或审批 deadline，也不增加重试。超时、缺少 Python/Node 完整终态、读取线程异常或保护失败均保持未完成/失败；不得把旧模块结果、后续成功或跳过拼接成新的完整通过。

每次官方 Desktop/CLI 更新先运行入口、目录与版本基线；再加本次变化涉及的行。下面模块名均由已有 `run_tests.py` 解析，保留每行的原始结果，不合并成含糊的“基本通过”。

| 本次变化 | 必选模块 |
| --- | --- |
| 官方 Desktop/CLI 更新基线 | `test_mode_entry_cli test_native_models test_mode_entry test_mode_host test_mode_picker_lifetime test_mixed_model_catalog test_responses_profiles` |
| 2026-10-05 首轮吸纳修复 | `test_model_router test_responses_profiles test_responses_router test_responses_events test_mode_host test_mode_picker_lifetime test_mode_entry` |
| Responses 工具、历史、分片或明确端点合同 | `test_responses_tools test_responses_events test_responses_router test_responses_cli test_responses_profiles test_model_router` |
| 取消、执行夹具或路由生命周期 | `test_responses_eval test_model_router_lifecycle`；Web 相关另加 `test_web_service_manager test_web_startup test_web_responses_provider` |
| 配对升级、入口归属或恢复 | `test_mode_maintenance test_mode_pair_refresh test_mode_backends test_native_route_recovery test_recovery_shortcut test_direct_recovery` |

例如，本次吸纳修复的完整受影响模块命令：

```powershell
& $operatorPython -X utf8 -E -s -B (Join-Path $operatorPlugin 'development/run_tests.py') test_model_router test_responses_profiles test_responses_router test_responses_events test_mode_host test_mode_picker_lifetime test_mode_entry
```

有共享层变化、受影响范围不明或准备整体发布时，在同一冻结树和已核验保护范围下运行已有完整 Python/Node 回归，而非把多个旧版本模块结果拼成整仓通过：

```powershell
& $operatorPython -X utf8 -E -s -B (Join-Path $operatorPlugin 'development/run_tests.py') --node
```

快速回归仅证明所列当前模块和合成夹具；完整回归也不能证明实机工具、审批或 Desktop 窗口。测试可能调用本地临时 loopback、合成编译及隔离 CLI 夹具，与真实模型请求不同。

## 4. 固定记录结果，再决定下一步

每一项独立保留 `观察时间 + 精确版本/摘要 + 命令/用例 + 退出码 + 原始输出或原回执位置 + 范围 + 后续动作`。以新私有文件追加本轮记录，不覆盖旧日志、失败事务或原件。测试结果与保护门槛分列；unittest exit 0、零断言失败或后来独立成功不能抹去原保护门槛失败。

| 结果 | 判定 | 后续动作 |
| --- | --- | --- |
| 通过 | 当前绑定范围内全部所需断言成立、退出码正确，且相应保护门槛成立 | 仅进入该范围的下一门；不扩展到未测型号、权限或部署 |
| 失败 | 测试/协议断言失败、非零退出、受保护字节变化、身份不符或原门槛不成立 | 保留原件及固定原因；先定位具体缺口，不回滚用户后来设置、不重放输入 |
| 配置缺项 | 已选定的 CLI/catalog/终端输入缺失或未绑定，所需用例因此跳过 | 不算所需 CLI 检查通过；补齐本轮已有输入后使用新冻结树和新回执，旧跳过与失败保持原结论 |
| 环境跳过 | 框架明确给出 Windows/依赖/symlink 等条件跳过 | 单列用例和原因；不算通过。若现有严格回执要求零跳过，它仍为 failed；需要条件就补环境后开新回执，不能改旧回执 |
| 未验 | 没有运行、缺少原证据或无法提供当前准确观察 | 明确缺项；需要真实账号、审批配对或当前窗口时先满足原条件，不用助手声称或目录替代 |
| 陈旧 | 有原证据，但它绑定的版本、源码、合同或身份与当前不同 | 保留其历史结论；在新绑定上安排不同新案例，不修改旧摘要或自动再派发 |
| 阻断/不确定 | 准确进程、所有权、服务终态、原件或事务状态无法核验 | 停止依赖它的写入/启动；沿已有只读预览和显式受审维护处理，不能自动重试或制造 stopped 记录 |

本次首轮吸纳的入口回归已有一个 symlink 条件跳过，虽然 unittest exit 0，私有零跳过包装回执仍为 failed；详见[吸纳记录](codexplusplus-adoption.md)。这展示两层结果，不能以本页新命名改判旧记录。

## 5. 部署和当前窗口验收另立记录

满足准确停机、空闲、原件、保护和源码门槛后，既有安装配对沿 `pair-prepare → pair-preview → pair-apply`，绑定同一 stage 和当前预览摘要；官方包升级只有明确核验更高同家族版本时使用 `--package-update`。完整命令与异常维护边界见[升级操作](upgrade-20261002.md)和[模式入口](../../models/common/docs/mode-entry-window.md)。已绑定配对入口不使用独立 refresh；失败/不确定事务不重跑。本页不自动调用服务 start/stop、入口 launch、注册写入或全局激活。

受审写入后核对已装源码、编译入口、当前包、登记/目录和恢复材料的新摘要，保留迁移前原件，再分别记录：准确入口打开、模型菜单身份、不同新输入的回复、真实工具参数/结果/文件、审批允许/拒绝和停止。官方主窗口与配置保持保护；完整历史和已消费失败输入保持不变。

原生 model/list 诊断只能说明目录，HTTP 完成只能说明传输；合成协议测试、隔离 CLI、当前 Desktop 实机结果不得互相代替。关键门尚未确认时如实列出，保留原生直连与独立拓展隔离，不能据此启用全局路由。
