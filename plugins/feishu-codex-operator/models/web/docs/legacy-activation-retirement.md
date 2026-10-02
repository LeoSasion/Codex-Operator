# 旧 Web 激活记录的显式退休

旧 `web-startup.json` 的源码摘要过期时，常规 `status` 固定返回
`web_startup_runtime_changed`。这不证明旧 `activation.json` 可以删除，也不授权
重新启动后台。`operator_web_activation_retire.py` 是独立的一次性维护入口，仅处理
`phase=activated`、已停止且入口确实为原生模式的旧记录。

先用 `preview --plan <绝对 web-startup.json 路径>` 只读检查。它把旧激活记录的
`plan_sha256` 与旧计划原始字节比对，把 `config_sha256` 与激活前配置原件比对；
核对旧启动回执的完整来源和父、子进程出生身份，要求进程已不在、路由端口可
独占保留、路由入口 journal 缺失。它还检查当前全局配置没有活动路由、原生恢复锁
在位、Desktop 入口模式和已安装启动程序与其清单相符，并为相关文件生成快照摘要。
预览不启动服务、不发送模型请求，也不改配置、入口或任何记录。

只有独立复核预览结果后，才可显式使用 `retire --plan ...`
并同时提供预览返回的三个 `--expected-plan-sha256`、
`--expected-activation-sha256`、`--expected-snapshot-sha256` 参数。退休时再次
检查文件、进程和端口，先写一次性维护 journal 与完整原件备份，再将活动
`activation.json` 原子移到 `legacy-activation-retired.json`，最后写终态回执。
它不更改旧计划、保存的配置、Desktop 入口、后台服务或路由。现有启动流程不会
从缺失的激活记录自动重新启动或重放请求。

`legacy-activation-retirement.json` 只要存在，就禁止该维护工具再次执行。
统一入口预览和卸载预检仅在回执为 `retired`、备份与归档字节完整匹配、旧进程
出生身份已不在且端口空闲时认可退休完成。回执为 `may_have_retired`、文件缺失、
记录变更、进程或端口不确定时均继续阻断，留待独立人工审查；不得自动补写终态、
重试退休或通过启动新服务来“验证”。恢复锁是另一项独立阻断，本工具不解除。

退休回执中的 `files_sha256.profile` 保留退休当时 Web profile 的历史摘要，并受
`snapshot_sha256` 约束。退休完成后，正常显式 `configure` 可更新当前
`operator-web-service/profile.json`；只读退休状态不再要求它与历史摘要保持同字节。
旧启动脚本、同步计划、registry、token、激活原件及归档仍按原有摘要和路由守卫核验；
当前 Web profile 的有效性由后续服务与统一预备各自检查。

2026-09-29 的临时目录测试覆盖了旧源码摘要变化、原件备份、原子归档、运行中
旧进程、占用端口、入口/配置冲突、快照变化，以及归档完成但终态回执写入失败的
窗口。此后的真实旧记录已单次显式退休，原件与回执保留；本次 profile 状态修复只在
临时目录验证，未改真实服务状态，也未验证新的 Desktop 主窗口接入。
