# Codex-Operator

**Channels · Models（API / Local / Web）**

面向 Codex Desktop 的两个职能板块：Channels 连接 IM 会话，Models 接入 API、本地和 Web 模型。Codex 原生任务继续负责上下文、工具、审批和执行。

Windows 预览版 **[1.2.0-preview.1](https://github.com/LeoSasion/Codex-Operator/releases/tag/v1.2.0-preview.1)**，项目自有代码采用 [MIT](LICENSE)。此版本为 Pre-release，实机验收尚未全部完成，支持范围与待验项见[发布验收清单](plugins/feishu-codex-operator/development/docs/first-release-readiness.md)。

- **Channels**：首版实现飞书，其他 IM 作为后续通道扩展。
- **Models**：分为 API Providers、Local Providers、Web Providers。ChatGPT Web 属于 Web Providers，复用登录与固定连接。

[开始使用](plugins/feishu-codex-operator/QUICKSTART.md) · [模块说明](plugins/feishu-codex-operator/MODULES.md) · [参考与致谢](plugins/feishu-codex-operator/NOTICE.md)

在 Codex 中添加本目录的本地 Marketplace（`.agents/plugins/marketplace.json`），安装 **Codex-Operator**，再输入：

> 使用 $codex-operator 帮我配置所需模块，先检查现有进度，复用已有登录和设置。

统一命令入口为 `plugins/feishu-codex-operator/scripts/codex-operator.ps1`，支持 `status`、`channels`、`models`；Web 使用 `models web`。目录中的旧飞书名称属于现有安装兼容细节，不是新的产品或插件名。已有安装需停止准确服务后单独迁移，不因插件改名移动账号或任务数据。

预览版保留原生官方直连。全局同菜单路由未默认开放，新 Web 任务仍需助手协助接入；网页冷启动、长历史和复杂工具仍有已知限制。接通某个模块不代表全部模块已验收。

文档、测试和示例配置按功能放入 `channels/`、`models/`、`shared/`、`development/`。待确认旧内容放在所属功能目录的 `_quarantine/` 子目录，完整保留并排除发布。

发布包按明确清单生成，包含经审查的公开源码与文档，不包括账号、密钥、浏览器资料、任务历史或运行数据库。构建器位于 `plugins/feishu-codex-operator/scripts/build_codex_operator_release.py`，只生成本地包，不上传或发布。
