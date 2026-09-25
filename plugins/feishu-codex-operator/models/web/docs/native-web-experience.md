# Native experience and project memory

Current guidance as of 2026-09-24. Codex-Operator has two areas: Channels and Models; Models contains API, Local and Web Providers. The Windows preview prioritizes setup and actual task execution. Native Codex owns the conversation, context, permissions, tools and final answer; Operator supplies the transport and its local lifecycle.

## Read first

The owner's 2026-09-20 direction makes Chat On Steroids the primary research reference for smoother native conversation with fewer clicks, configuration steps and interruptions. The four separate dormant references, MCPX identity uncertainty, adopted ideas and applicable copied-code licenses are recorded in one place: [implementation sources](web-background-sources.md).

The scope remains native Codex tasks. Do not introduce a separate workspace UI, companion-extension product, Goal/Loop or another multi-agent orchestrator. For a major internal redesign, explain user benefit, migration and verification before implementation. The [current plan](native-conversation-plan.md) lists remaining work; the [dated history](native-web-history-20260924.md) records superseded approaches and failures.

## Operational rules

1. Reuse saved settings, login and fixed connection state. `models web configure` may omit settings and interpreter for an unchanged saved registration; it checks them without writes. Distinguish access restrictions, changed programs/registration and failed checks from missing setup.
2. Use `models web start/status/assist/inspect/stop` for the saved service. Startup prepares one hidden empty temporary chat without sending a prompt or MCP call, then rechecks it when consumed. Low-level `serve` retains its explicitly selected behavior. Read-only status never prepares a page or makes a model request.
   Read-only status and uninstall preflight import without `aiohttp`; serving still requires it. The isolated `python -S` test covers this boundary.
3. Before requesting human login or verification, observe the exact current page. A historical challenge, `needs_assistance`, window title or open acknowledgement is insufficient. Allow transient loading to settle with bounded observation; reuse a ready page. If observation fails, report that uncertainty. Locate a missing assistance window before asking the user to find it. `assist` prepares an empty chat; `inspect` preserves an ended page as a read-only text snapshot.
4. Native models remain on their official direct route. Web registers an independent provider through `desktop-prepare/connect/status/check/disconnect`. After a verified service change, `desktop-rebind` updates only the owned provider block and retains its original configuration. Registration, task binding, menu visibility, request routing and live Desktop behavior require separate evidence. Global routing stays disabled after the native capacity/retry regressions.
5. Send each authorized test once with a new input and exact task/provider identity. Preserve old failed turns. Assistant task-tool delivery is not manual composer input. A completed HTTP response or fully read context does not prove that the model handled the current task; compare actual arguments, results and files with the request.
6. Keep transport and context limits distinct: native HTTP wire/decompressed input is bounded to 64 MiB; indexed Web context retains 48 KiB replies, 24 pages and 40 single-use reads. A rejected long task is not repaired by truncation, a larger native HTTP bound or replay. New-task creation needs authorization.

## Search and model selection

Do not disable `web_search` in global or project `.codex/config.toml` to accommodate Web: project settings also affect other models in that directory. The earlier dedicated-project override was removed after a private backup; it survives only as [dated evidence](native-web-history-20260924.md#2026-09-24-search-routing-and-citations).

The Web provider accepts one optional live hosted `web_search` declaration with the checked shape, no filters/location/indexed/cached constraints and automatic tool choice. It projects that declaration to the webpage's own optional search path, keeps the caller input intact and advertises supported native tools through MCP. Unsupported constraints fail before submission. The bounded `web_page_auto_v1` status means route selection, not proof of search or accuracy. Do not execute Codex search as an implicit second backend or invent a `web_search_call`; return only the observed answer and validated public sources. Other providers retain their own search contracts.

Search capability belongs to the exact model and endpoint. GLM-5.3's official direct case returned a provider-hosted search event; GLM-5.3 Flash's separately validated search used Codex. DeepSeek's official Responses endpoint ignores hosted search declarations; a Codex-executed adapted route needs its own verification. See [online model evidence](../../api/docs/official-online-models.md).

The observed Web catalog contains **GPT-5.6 Sol** (`none/medium/high/xhigh`), **GPT-5.6 Pro** (`max`) and **GPT-6 Pro** (`max`). Pro's native `max` selects the Web Pro position, not an asserted API effort equivalence. Latest/High was observed as GPT-5.6 Sol, so the unverified Web GPT-6 Sol entry was removed. Check exact selection, visible effort and generation before each dispatch; preserve one serial browser and consumed-turn ledger across models. [Catalog and dated evidence](web-model-catalog.md) are authoritative for this surface; native GPT-6 is separate.

## What the evidence establishes

| Area | Recorded result | Remaining boundary |
| --- | --- | --- |
| Saved setup and hidden readiness | Unchanged setup reuses protected files/processes; saved startup prepares an empty page with zero model requests | No first-token speed or long-run reliability claim |
| Managed Web text | Fresh serial samples returned exact text across the published Web choices | Selected UI identity is not backend attestation; prior 403s remain failures |
| Web to native coding | A fresh GPT-6 Pro/max isolated CLI case completed three paired calls, the exact edit and five executed tests | Not current Desktop picker, manual composer or all-tool acceptance |
| Web-page sources | Two distinct fresh native tasks without the search override completed with source links and zero local tool calls | One explanation relied on a mirror; citation validity does not establish factual/source fidelity |
| Dedicated native task continuation | Assistant-relayed fresh text in the same Desktop task completed under the then-current test setup | That setup temporarily disabled search; later Web-only search has separate evidence |
| Provider binding and switching | Synthetic fresh-process resume preserved/changed explicit provider binding; same-process switching still reached the first provider | No supported seamless live Desktop switch is established |
| Capacity and old-port recovery | Rebind fixed the stale local address; the next long task reached the current provider and failed indexed-context preflight | 502 and 413 remain distinct failures; neither proves a completed reply |
| Current native read-only audit | Complete context and a selected schema were read, but no tool call reached Codex; the page returned a refusal | Task acceptance failed despite a completed native turn; the refusal cause is unverified |

Historical checks also covered follow-up context and cancellation reuse; missing context, wrong historical-task selection, page timeouts, citation failures and 403s remain retained. Current implementation and test results are recorded in the [release audit](../../../development/docs/release-audit.md); raw receipts, task identities, local paths and original failed inputs remain private. Passing a later new case never changes an earlier result.

Use the [setup guide](../../../QUICKSTART.md), [module responsibilities](../../../MODULES.md) and [current plan](native-conversation-plan.md) for the next action. Channels evidence belongs in its [core recovery record](../../../development/docs/core-recovery-20260921.md); an existing user's success does not prove a second user's first-contact setup.
