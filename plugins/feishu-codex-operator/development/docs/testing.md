# Tests

For official Desktop/CLI upgrades, source updates or endpoint-contract changes, use the [fixed upgrade checklist](upgrade-checklist.md) to bind versions, fingerprints, affected modules and separate evidence gates before maintenance.

Run from the extracted repository root with Python 3.11+ and the dependencies in `../../scripts/model-router-requirements.txt` installed in your test environment:

Before a full regression or a CLI-containing module run, bind the current CLI and the exact private catalog copy needed by catalog cases in [本轮测试输入](upgrade-checklist.md#本轮测试输入). Predeclare any additional PowerShell/Bash terminal cases, bind each selected executable and disposable-CLI backend/outcome, and clear inherited inputs for unselected cases. Missing selected inputs are setup omissions; unselected cases remain unverified. Neither kind of skip counts as a passed CLI check. Preserve failed runs when choosing a different scope for later work.

```powershell
python -B plugins/feishu-codex-operator/development/run_tests.py
python -B plugins/feishu-codex-operator/development/run_tests.py --node
pwsh -NoProfile -File plugins/feishu-codex-operator/scripts/audit-feishu-codex-release.ps1
```

Stop the exact Operator instance and finish pending callbacks before tests. Use temporary projects and isolated homes; never aim fixtures at real chats, credentials or task histories. Tests must not send real business messages. Synthetic protocol checks, real model execution and Desktop UI acceptance are distinct.

The suite includes Windows-specific and environment-dependent skips. Retain failures and report the tested versions. Full results belong in a private receipt, not a copied personal diagnostic history in the public package.

Upgrade repairs add isolated argv/PID ownership fixtures for both PowerShell 5 and 7, complete-terminal opaque argument rejection, managed-rule byte comparisons, and public single-entry maintenance cases. Tests must exercise the public dispatch as well as private receipt validators. A run edited midway is diagnostic evidence; repeat the affected scope after freezing. Preserve raw log bytes and parse both Node spec and TAP summaries, including indented unittest subtest skips. Native cache timestamp drift remains a separate failed protection gate even when model records are unchanged.

Temporary directories do not isolate shared fixed ports; related port-reservation fixtures run serially across processes. Keep the product's exclusive reservation gate unchanged. Pin UTF-8 on both sides of captured PowerShell JSON, retain strict decoding and Unicode assertions, and use a private child console. Negative source-read injection must prove it hit the exact module and changed its digest. New contracts also require valid baseline fixtures; retain the original secret/allowlist and archive byte assertions when updating them.

Transaction concurrency checks use independent interpreters and explicit checkpoints around the real write path, including abrupt exit and outside edits after preflight/fsync. On Windows a venv executable can redirect to a different process: bind the current environment's base interpreter for these standard-library-only fixtures and compare the child's reported PID with the controlled process. Retain uncertainty and original bytes; never turn a fixture crash into automatic lock takeover. Asynchronous health checks need both stale-success and stale-validation-error interleavings; invalid current-generation observations must still fail. A protocol test that releases one valid call before a later invalid item is a failure even if the final response is rejected.

Web layered diagnostics test endpoint readiness and poll freshness independently, retaining only fixed labels/counts and rejecting stale generations. Bound stopped snapshots and labelled unbound terminal snapshots remain read-only; the latter keeps its original uncertain-launch error and grants no worker ownership. Check malformed values, unknown text, no extra HTTP/RPC probes and unchanged saved files. Model-catalog state stays unobserved unless separate evidence exists.

Check diagnostic failure codes against both actual connection implementations. Preserve their known fixed codes, while approximate invented names and arbitrary text remain scrubbed. A stopped snapshot never becomes a clean-stop or current-connectivity assertion.

MCP waiting tests keep the 900-second whole-turn deadline while expiring one real loopback HTTP exchange early. Verify one exact released call, unchanged arguments/deadline, cancelled pending result, rejection of late results and no second dispatch. The pinned tunnel client's per-command server deadline is distinct from its empty-poll timeout; no fixed 60-second production cap is inferred.

CurrentCliCancellationTests in test_responses_cli exercises the actual selected CLI with disposable App Server homes, never/read-only, synthetic Responses and one stdio MCP child. It verifies both native tool-timeout cancellation and turn/interrupt, exact RPC identity types and write ordering, one interrupted turn and a different completed continuation without restarting MCP. Set CODEX_OPERATOR_TEST_NATIVE_CANCELLATION_CAPTURE to a fresh private parent to retain bounded raw evidence and short case-name mappings. Loopback NO_PROXY applies only to these children. Record native EOF/startup failures immediately; do not mistake a Windows SQLite path failure for a cancellation timeout. These cases make no real inference or business request and do not establish live Desktop/Web acceptance.

For a separately authorized live Desktop Stop check, bind the exact test chat,
model, turn and actual tool input before clicking once. A default exec yield may
return a running cell and let the turn finish before Stop; retain that fixture
as unaccepted and use a different bounded pending-call fixture, never an old
request replay. Verify the paired aborted tool result, interrupted turn and a
different completed continuation. Read-thread summaries may omit custom calls;
review the exact rollout's call/result records without reading reasoning text.
Recheck the actual selected task after user input can switch the foreground
chat. Gray composer suggestions with an empty edit value are placeholders,
not user drafts; preserve a real nonempty draft. A Stop click or assistant claim
alone does not attest to upstream inference or billing cessation.

The existing isolated evaluator also adds exact loopback exclusions to its child's NO_PROXY, retaining inherited exclusions and proxy values. Verify that the parent environment is unchanged. A native 502 with zero admitted local requests needs private bounded stderr evidence before attribution; do not rewrite it into a tool, provider or permission failure. Repeat the original cancellation, multiround and selected terminal cases after repair. Keep the initial full-run failures and native config/cache protection drift separate from later affected-module results and a newly retained comparison snapshot.

The isolated Desktop host must retain this same loopback property. The Windows
compiled-host probe inspects its actual ProcessStartInfo for absent and existing
bypass values, proxy preservation, private home selection and unchanged parent
environment, without launching Desktop. A real CLI comparison using two disposable
local capture endpoints can distinguish a system-proxy 502 from a router or Web
failure: bind the CLI, count actual arrivals and retain the synthetic terminal,
with zero account or model access. Do not disable the system proxy or broaden
network permissions to make a local route work.

For live cold-start acceptance, normally exit the exact extension instance and
obtain a request-free router stop before editing bound source. Apply its checked
pair upgrade, use the real shortcut and picker, then compare exact process births,
model/effort, tool arguments/results and visible final output. Retain a failed turn
and use a different new fixture after a fix. Verify exit/reopen and same-chat
continuation separately. Newer Desktop versions can compress rollouts to
`.jsonl.zst`; compare the fully decompressed bytes and retained prefixes rather
than assuming a missing original path means history was lost. Never rewrite the
history to satisfy a byte check.

Explicit legacy alpha-version maintenance also tests the public version flags, default refusal, exact from/to mismatch, downgrade and release-line rejection, complete original-manifest restoration, late source changes and preservation of later edits. The version selection is part of the preview identity; source-test success does not itself authorize deployment or erase an earlier incomplete wrapper run. Keep the documented 3600-second whole-run allowance when invoking the complete legacy module.

The fixture-only NativeApprovalCapture in [the evaluator](../../scripts/operator_responses_eval.py) is a separate opt-in App Server transport; the existing evaluate() and CLI cases keep their never/read-only policy. Use newly created private homes and raw-log folders, new synthetic work directories with normal permission inheritance, a pinned CLI, and an explicitly checked model/endpoint contract. The controller must constrain and inspect the actual command or file change. Capture the complete original request and response, exact RPC ID type, thread/turn/item identities, terminal outcome and before/after file bytes; a model claim is insufficient.

This lane uses untrusted/read-only settings, one combined 16 MiB raw-capture bound and a 120-second deadline that includes waiting for the owner. Only a decision on the exact pending single action may become a reply. The default contract permits accept or decline; the explicit CLI 0.160 single-action contract uses accept or cancel for its advertised command decisions. An exec-policy proposal remains inert request metadata, never an amendment response. Session grants, root grants and policy amendments are rejected. No default approval, manufactured timeout denial, repeated start or request replay is allowed. Preserve failed and incomplete captures. CLI/App Server evidence remains separate from live Desktop approval and native freeform-patch acceptance; an unregistered tool contract cannot be expanded to fill those gates.
