# Codex-Operator

Connect IM channels, online/local models, and ChatGPT Web to Codex Desktop.

**Windows preview · MIT · [1.2.0-preview.8](https://github.com/LeoSasion/Codex-Operator/releases/tag/v1.2.0-preview.8) · Operator 4.2.0-alpha.146**

本版补记 preview.7/alpha146 的一次真实飞书私聊文本验收：用户直接明确固定转交范围后，实际 GPT-6 Luna/low 完成原生转交，GPT-6.1 Terra/low 提交精确 Final Callback，同一私聊的机器人原文回复已核验。旧失败保留且未重放。第二用户、附件、群聊与话题仍待独立验收，不能将这一条通过扩大为所有通道能力通过。

本版仅更新现有 skill、文档与包元数据，运行代码与 preview.7 相同，Operator runtime 保持 alpha.146。此前的原生发送固定失败诊断、一次发送与零重放边界继续保留。

运行发行包继续排除开发测试、公共夹具和 runner；完整 Git 源码的互斥清单与两组内容仍须审计。解压运行包使用 `audit-feishu-codex-release.ps1 -Scope release`，旧版本兼容、权限、取消和恢复测试保留。

此前已修复拓展启动子进程的回环代理排除，避免本机模型请求误入系统代理而返回 502。当前 Windows 包已完成真实快捷方式冷启动、GPT-6 Medium 文件读取、正常退出重开与同聊接续验收。此前的 Web 分层诊断、等待期限及原生停止结果继续保留；完整回归、真实工具执行和 Desktop 界面的证据范围独立记录，未覆盖场景不由一次通过推定可用。

The first-release scope is Windows and Feishu, with two API registrations selected
for release qualification: `api/glm-5.3-flash` / `low` and
`api/deepseek-v4-flash` / `none`. Their dated live checks cover specific cases;
current-version release qualification is still pending. Local and Web Providers
remain experimental. See the [support matrix and release checklist](development/docs/first-release-readiness.md).

Two functional areas share the native Codex task:

- **Channels** receives messages and attachments and delivers results. Feishu is implemented; other IM channels are planned.
- **Models** contains API, Local and Web Providers. ChatGPT Web is a Web Provider that reuses a saved login and fixed connection through a managed background service.

Codex Desktop owns task history, files, approvals and actual tool execution.

[开始使用](QUICKSTART.md) · [模块结构](MODULES.md) · [参考与致谢](NOTICE.md) · [安装与卸载](shared/docs/installation-and-removal.md)

Install the local Marketplace from the extracted release, select **Codex-Operator**, and ask:

> 使用 $codex-operator 帮我配置所需模块，复用已有登录，只让我处理必须本人完成的操作。

The unified entry is `scripts/codex-operator.ps1`. Run `status` to inspect both areas without model requests or configuration writes. Use `channels` and `models`; the Web Provider entry is `models web`. API and local [native profiles](models/common/docs/native-models.md) use `models native` for preparation, installation, status and restoration, keeping the official default unchanged.

The reviewed Windows [mode entry](models/common/docs/mode-entry-window.md) opens a native/extension choice. Extension mode has its own home and chat list, with custom models in the Codex conversation menu; native mode retains the official configuration. Dated live checks passed GLM/DeepSeek continuation, standalone search and actual shortcut switching; they do not qualify every later package or model. Local and Web backends require their own acceptance. Known-version initialization avoids repeated welcome preferences without copying login or bypassing permissions.

In Feishu, `/model` reads the bound task's settings. `/model list` lists validated official models and provides an exact command for selecting a model for the next new business message. Use the full model ID when multiple generations share a name. `/model cancel` removes a pending choice. Beeper keeps its own model. API, Local and Web switching through this command remains pending.

This preview does not enable global model routing. Independent Web provider registration does not by itself integrate the main-window picker; a new Web task still needs assisted setup. Cold page loading can time out, and long-history/complex-tool reliability remains limited. Failed requests are retained and are not replayed automatically.

Source tests and historical live checks establish only their documented scope. An installed plugin, configured connection, visible model, and successful business task are separate results. See [verification scope](development/docs/release-audit.md).

The legacy `feishu-codex-operator` source/runtime paths remain internal installation details for existing projects. The public product and plugin name are Codex-Operator. Existing installations require a reviewed stopped migration; installing a renamed plugin alone does not migrate their data.
