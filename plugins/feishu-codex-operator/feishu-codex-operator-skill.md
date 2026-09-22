# Codex-Operator 使用说明

这是保留的中文导航页，不另维护一份运行策略。

- [安装与日常操作](README.md)：Windows 命令、飞书 `/init` 与只读诊断。
- [操作与开发 skill](skills/feishu-codex-operator/SKILL.md)：对话中的逐步配置引导、源码权威与按任务加载的参考资料。
- [Channels 首次接入](channels/feishu/docs/automatic-task-provisioning.md)：选择本地 Beeper 或 Luna/low，授权后由助手创建通道项目、Beeper 与默认用户任务，按需持续创建/续用。
- [ChatGPT Web 固定连接](models/web/docs/web-fixed-tunnel.md)：助手打开网页，逐步引导保存连接编号与运行密钥。
- [原生 Web 体验方案](models/web/docs/native-web-experience.md)：最新参考优先级、一次配置与统一后台管理。
- [原生对话改进计划](models/web/docs/native-conversation-plan.md)：重点研究 Chat On Steroids，减少 Codex 原生对话中的点击、配置和中断；大方向改动先汇报。
- [架构](shared/docs/architecture.md)：投递、回调、额度缓存与等待策略。
- [命名](shared/docs/terminology.md)：Operator、Beeper、Responder、wake-up signal 与 wake lease。
- [升级](upgrade-operator.md)：新命名切换与数据保留。
- [初始化和安全卸载](shared/docs/installation-and-removal.md)：首次说明、入口备份、恢复冲突和卸载顺序。

Beeper 只中继，Responder 执行业务，Operator 负责接收、路由和回传。
