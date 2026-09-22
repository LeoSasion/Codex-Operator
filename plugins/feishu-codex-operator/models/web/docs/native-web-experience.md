# Native experience and project memory

The product is **Codex-Operator**, with Channels and Models; Models contains API, Local and Web Providers, including ChatGPT Web. The Windows preview prioritizes complete setup and real task execution; stability work is a later phase. Preserve native task ownership, saved configuration, minimal interruptions, permissions and no replay.

The owner's current direction (2026-09-20) makes **totec448-spec/chat-on-steroids** the primary research reference for smoother native Codex conversations with fewer UI clicks, configuration steps and interruptions. **yyjeqhc/webcodex**, **daodao97/localmcp / MCPX** and **miuuyy/codex-chatgpt-web** are dormant references, consulted only for a concrete necessary gap. MCPX's screenshot identity remains unconfirmed; `opentokenz/mcpx` is only a candidate. Existing provenance and licenses remain in [implementation sources](web-background-sources.md).

The scope is native Codex conversation, not a separate workspace UI, companion-extension product, Goal/Loop or another multi-agent orchestrator. Substantial internal redesign is welcome; report major direction changes, migration effects and validation plans before implementation. The [native conversation plan](native-conversation-plan.md) distinguishes the completed management-entry improvements from later work and Desktop acceptance.

The first approved improvements let repeated Web configuration reuse the exact saved settings and interpreter without repeated parameters or writes. Fixed diagnostics distinguish access limitations, changed registration or programs, and failed checks. The focused 39 checks passed; full validation passed 778 Python checks with 10 existing skips and all 82 page checks. Two real saved-entry reuse checks left protected files and Web processes unchanged. Tool declaration refresh, hidden-page preparation and native model selection remain later work; no first-turn speed improvement is claimed.

Native models use the official direct route by default. Web can register an independent provider without changing the native default. Provider registration, task binding, menu visibility and actual execution are separate checks. Global routing remains disabled in the current preview after native request-size regressions.

Read [the setup guide](../../../QUICKSTART.md) and [module responsibilities](../../../MODULES.md). Use the existing `models web configure/start/status/assist/inspect/stop` commands; keep login and fixed connection state. Independent Desktop preparation uses `desktop-prepare/connect/status/check/disconnect`. New task integration still requires assisted setup.

Historical checks demonstrated file/tool roundtrips, search citations and ordinary same-task continuation in specific cases. Failures also included page-loading timeouts, incomplete context consumption and incorrect selection of an older task. Neither reading all context pages nor a successful transport proves task correctness. Current version and verification scope are summarized in [release audit](../../../development/docs/release-audit.md).

Developer audit receipts, private task identifiers, local paths, browser profiles and original failed requests remain local; they are deliberately excluded from the public release. A public summary does not reclassify those failed checks.
