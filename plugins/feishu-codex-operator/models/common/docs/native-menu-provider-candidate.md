# 原生模型菜单提供方候选

2026-10-02 状态补充：所有者要求先记录教训，再共同讨论需求调整。
阅读[模型切换复盘](native-model-switching-lessons-20261002.md)后再决定后续路线；
本候选继续保留为未部署研究，不代表已经选定的下一实施方案。

2026-10-02，所有者明确纠正验收要求：自定义模型必须能在 Codex 原生对话框模型列表选择。
应用启动前的外部选择器不满足该要求，不继续作为交付方向。保留原生官方直连优先级；
先前所有安装、恢复、失败和未测证据不改判。

## 当前实现与证据

`models/common/native-menu/provider-policy.cjs` 是独立、无 I/O 的候选策略，不是已安装的
Desktop 扩展。保留完整原生模型响应字段及原模型行；在原列表最后一页追加准确注册的条目。
新任务只有精确匹配的自定义型号才传入其 `modelProvider` 和线程范围的 Responses 配置；
官方型号、辅助型号、其他主机保持原参数对象，不设置全局提供方或 HTTP 代理。
未知鉴权字段、冲突登记、显式提供方冲突均拒绝。凭据不在模型登记中。

旧会话拒绝候选按现有提供方检查明确的型号选择，不宣称支持跨提供方切换。
已有会话的提供方未知或不匹配时，自定义选择拒绝，不能把菜单可见当成路由成功。
原生本体全部分派路径是否经过该拒绝检查仍需单独核对；没有上线许可或成功证明。

Windows Desktop 26.928.2636.0 的私有副本预览匹配到 `listModels`、`startThread` 和
conversation manager 的 `sendRequest` 接入点。原包保持不变。候选副本通过 Node 语法检查；
七项策略边界测试及七个已保存 API/Local 型号的纯参数核对通过，无模型请求或真实配置写入。
私有候选、旧候选和准确原字节摘要位于 `.codex/audit/native-picker-research-20261002`。

主窗口模型显示、实际新任务路由、原生辅助任务、已加载聊天的拒绝覆盖、本地服务就绪、
缺失提供方会话恢复，以及 Windows 包完整性/可恢复部署均未验证。不得安装当前候选，
更不得为通过这些门槛强退应用、绕过包校验、改写历史、重放失败或重启未知服务。
普通插件配置没有被证明能直接改动原生菜单；当前预览涉及应用 JavaScript 接入点，
不能把它包装成受支持的官方插件 API。

## 必要参考与许可

2026-10-02 的研究当时以 Chat On Steroids 为首要参考；2026-10-05 起按[当前参考策略](../../web/docs/web-background-sources.md)重点参考 Codex++，新增功能或界面先与所有者商量。本候选状态不因此改变。这个菜单接入缺口当时额外核对了
[Keksuccino/Better-Codex-App-Custom-Provider-Support](https://github.com/Keksuccino/Better-Codex-App-Custom-Provider-Support/tree/4e19e474330dc5266eb814e425410127aa7c1a4e)，
固定提交 `4e19e474330dc5266eb814e425410127aa7c1a4e`，Unlicense。
参考 `patch_chatgpt_providers.py` 的 `CENTRAL_DIFF`、`PICKER_DIFF` 及版本变体，
采用的是菜单展示与新任务显式提供方绑定分开的接入思路。策略代码独立实现，未执行上游
安装器、复制其自动退进程/签名/回退行为，未添加其默认 OpenRouter 模型或凭据。
完整源码和 LICENSE 私有只读保存，来源与摘要保留。
上游当前只支持 macOS，也明确不支持运行中的同聊天提供方切换；不是本机 Windows 验收。
