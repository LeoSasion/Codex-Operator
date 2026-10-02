# Codex-Operator

Connect IM channels, online/local models, and ChatGPT Web to Codex Desktop.

**Windows preview · MIT · 1.2.0-preview.1**

Two functional areas share the native Codex task:

- **Channels** receives messages and attachments and delivers results. Feishu is implemented; other IM channels are planned.
- **Models** contains API, Local and Web Providers. ChatGPT Web is a Web Provider that reuses a saved login and fixed connection through a managed background service.

Codex Desktop owns task history, files, approvals and actual tool execution.

[开始使用](QUICKSTART.md) · [模块结构](MODULES.md) · [许可证与来源](NOTICE.md) · [安装与卸载](shared/docs/installation-and-removal.md)

Install the local Marketplace from the extracted release, select **Codex-Operator**, and ask:

> 使用 $codex-operator 帮我配置所需模块，复用已有登录，只让我处理必须本人完成的操作。

The unified entry is `scripts/codex-operator.ps1`. Run `status` to inspect both areas without model requests or configuration writes. Use `channels` and `models`; the Web Provider entry is `models web`. API and local [native profiles](models/common/docs/native-models.md) use `models native` for preparation, installation, status and restoration, keeping the official default unchanged.

The reviewed Windows [mode entry](models/common/docs/mode-entry-window.md) opens a native/extension choice. Extension mode has its own home and chat list, with custom models in the Codex conversation menu; native mode retains the official configuration. The current package passed GLM/DeepSeek continuation, standalone search and actual shortcut switching. Local and Web backends require their own acceptance. Known-version initialization avoids repeated welcome preferences without copying login or bypassing permissions.

In Feishu, `/model` reads the bound task's settings. `/model list` lists validated official models and provides an exact command for selecting a model for the next new business message. Use the full model ID when multiple generations share a name. `/model cancel` removes a pending choice. Beeper keeps its own model. API, Local and Web switching through this command remains pending.

This preview does not enable global model routing. Independent Web provider registration does not by itself integrate the main-window picker; a new Web task still needs assisted setup. Cold page loading can time out, and long-history/complex-tool reliability remains limited. Failed requests are retained and are not replayed automatically.

Source tests and historical live checks establish only their documented scope. An installed plugin, configured connection, visible model, and successful business task are separate results. See [verification scope](development/docs/release-audit.md).

The legacy `feishu-codex-operator` source/runtime paths remain internal installation details for existing projects. The public product and plugin name are Codex-Operator. Existing installations require a reviewed stopped migration; installing a renamed plugin alone does not migrate their data.
