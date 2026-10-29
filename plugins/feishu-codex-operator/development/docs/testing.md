# Tests

For official Desktop/CLI upgrades, source updates or endpoint-contract changes, use the [fixed upgrade checklist](upgrade-checklist.md) to bind versions, fingerprints, affected modules and separate evidence gates before maintenance.

Run from a full Git source checkout with Python 3.11+ and the dependencies in `../../scripts/model-router-requirements.txt` installed in your test environment. The runtime ZIP retains the application and maintenance code but omits development tests, fixtures and this runner. `assets/release-inventory.json` keeps separate runtime component paths and `development_paths`; source audit requires their complete, disjoint union and screens both groups before building only the runtime files.

Before a full regression or a CLI-containing module run, bind the current CLI and the exact private catalog copy needed by catalog cases in [本轮测试输入](upgrade-checklist.md#本轮测试输入). Predeclare any additional PowerShell/Bash terminal cases, bind each selected executable and disposable-CLI backend/outcome, and clear inherited inputs for unselected cases. Missing selected inputs are setup omissions; unselected cases remain unverified. Neither kind of skip counts as a passed CLI check. Preserve failed runs when choosing a different scope for later work.

```powershell
python -B plugins/feishu-codex-operator/development/run_tests.py --group full --node
node --test plugins/feishu-codex-operator/models/common/native-menu/provider-policy.test.cjs
pwsh -NoProfile -File plugins/feishu-codex-operator/scripts/audit-feishu-codex-release.ps1
```

The runner collects Node files only under the owning `tests` directories. The native-menu policy test sits beside its implementation and uses the separate Node command above. Verify the actual `--list --node` file list before recording coverage; a wider filename pattern does not expand directory discovery.

For an extracted runtime ZIP, explicitly select `audit-feishu-codex-release.ps1 -Scope release`. This checks the complete runtime file set, reviewed documents and syntax; it does not claim development coverage. The default source scope rejects missing development files rather than inferring that an incomplete checkout is a release. Source fingerprints use `build_codex_operator_release.collect(root, include_development=True)` so changes to excluded tests remain visible during frozen regression.

For documentation-only work, use the source audit above, local-link/rule-mirror checks and
the existing skill validator; these checks do not require a service restart or a business test.

Stop the exact Operator instance and finish pending callbacks before executing tests. Use temporary projects and isolated homes; never aim fixtures at real chats, credentials or task histories. Tests must not send real business messages. Synthetic protocol checks, real model execution and Desktop UI acceptance are distinct.

The suite includes Windows-specific and environment-dependent skips. Retain failures and report the tested versions. Full results belong in a private receipt, not a copied personal diagnostic history in the public package.

## Discovery and shared fixtures

### Select the required scope

Use `--group quick` for everyday initial feedback, then run the affected owning
group or exact modules. It selects a small set of configuration, rate-limit,
protocol, release-rule and runner checks. It does not exercise every permission,
recovery, compatibility or CLI boundary. No-argument invocation remains full
Python for existing callers; Node remains explicitly selected with `--node`.

| Selection | Scope and use |
| --- | --- |
| `--group quick` | Small initial feedback set; never a release gate |
| `--group channels` | All Channels tests, including state, routing and callbacks |
| `--group models` | All Models tests, including API/Local/Web and isolated CLI cases |
| `--group web --node` | Web Python and browser Node tests |
| `--group shared` | Shared application, launcher, installation, legacy compatibility and recovery tests |
| `--group development` | Product packaging/preview and test-runner checks |
| `--group full --node` | Complete discovered Python/Node suite; native-menu policy still runs separately |
| `test_module[.Class[.method]]` | Exact affected scope; cannot be combined with groups |

Repeat `--group` to union scopes; files in overlapping groups run once. Owning
groups discover new modules under their directories automatically. The quick
set is explicit and fails when a listed module is missing. `--pattern` narrows
group discovery, so a filtered full group is not full coverage. Named tests keep
their existing independent selection; their names, rather than `--pattern`,
determine the Python scope. `--node` with named Python tests retains the complete
matching Node file selection.

```powershell
python -B plugins/feishu-codex-operator/development/run_tests.py --group quick --list
python -B plugins/feishu-codex-operator/development/run_tests.py --group quick --durations 10
python -B plugins/feishu-codex-operator/development/run_tests.py --group channels --group shared --list
python -B plugins/feishu-codex-operator/development/run_tests.py test_responses_tools test_responses_events --durations 10
python -B plugins/feishu-codex-operator/development/run_tests.py --group full --collect-only
```

`--list` is import-free and lists only selected files. `--collect-only` imports
Python modules and lists exact case IDs without executing cases; it does not
collect Node case IDs. Collection errors, zero Python cases and duplicate IDs
fail before execution, including overlapping explicit module/class/method names.
Neither listing command is behavioral evidence. `--durations N` observes Python
case setup, execution, teardown and cleanup without changing results or order;
class/module fixtures and Node time remain outside those individual timings.
Use the complete run's wall time when comparing before and after, and retain the
same selection, environment and original logs. A shorter preparation path does
not itself prove a measured speedup.

When an isolated CLI case passes alone but fails in full collection, reproduce
with the complete module imports and only that case's execution before repeating
the full suite. Record process exit, each pipe's EOF and bounded output collection
separately. The search fixture reuses the evaluator's bounded concurrent collector
instead of another `communicate()` wrapper; both actual EOFs and the original exit,
request-count and output assertions remain required. Keep its 35-second failure
deadline and one shared five-second cleanup budget. A timeout stays failed even
when the process has exited or cleanup later succeeds. This does not establish a
general Python/Windows defect or a cause for other CLI failures.
A later passing probe does not establish a repair while the original observation
still reproduces. Keep that issue unresolved, retain both outcomes, and distinguish
improved diagnostics or shared fixture code from a verified behavioral fix.

Selection follows the changed behavior, not just the edited filename. For a
contained repair, run quick feedback plus its affected modules and relevant
permission/recovery cases from the [upgrade matrix](upgrade-checklist.md#3-按变更范围运行现有快速回归).
Shared production changes, unclear impact, discovery changes and code releases
or deployment require one frozen full Python/Node run. A shared fixture-only
change requires every caller and unchanged original case identities/assertions;
do not infer production-wide change solely from its directory. Documentation-only
work keeps the audit checks described above. Preserve older failures and report
skips separately; partial results never combine into a full pass.

Import shared TestCase fixtures through their module rather than exposing the class as another test module's global. unittest also discovers directly imported TestCase classes, so fixture reuse can silently run an existing test ID twice. Check the collected ID multiset before and after a discovery repair: preserve every unique ID, test method's source and required inheritance. Inherited methods with different fixture inputs remain distinct coverage; do not remove them merely because they share a function. Discovery checks do not execute cases or replace behavioral regression results, and prior run counts remain historical evidence.

Shared Responses, event-fragmentation and Web protocol inputs live in `development/operator_test_fixtures`. These modules contain the original synthetic constructors and constants, without importing TestCase modules. Callers retain their local fixture names and direct-file bootstrap. A fixture move must preserve its function AST, exact source values and the collected case identities; import-path-only edits are reviewed separately from assertion or input changes. Existing migration, cancellation, permissions and recovery cases stay in the source suite.

Reuse only immutable fixture inputs. The Desktop installation fixture compiles
its inert fake application once per class/run and copies immutable bytes into
each case's new directory. Actual launcher compilation, mutable manifests,
shortcuts, journals, migration chains and configuration remain per case. Do not
reuse committed transactions or add a persistent binary cache that could hide
source/compiler changes. Combine PowerShell setup stages only when their
intermediate process boundaries are not themselves under test.

Retire coverage only after mapping the old case to a retained case with the same
fixture preconditions, production path, injected failure and observable outcome.
Identical assertions or inherited method bodies do not establish redundancy.
Keep independently named cases when they cover different inputs; collapsing them
into a loop merely to lower the displayed count is not an optimization.

## Windows CLI descendants and pipe EOF

The 2026-10-29 investigation of CLI 0.165.0-alpha.1.2 observed an exited root
with a suspended `git config --null --get core.fsmonitor` descendant retaining
its output pipes. Ending that exact synthetic descendant released both EOFs;
the prior collector refactor alone had not fixed the failure. This establishes
the fixture's missing process-tree cleanup, not the internal cause of Codex's
suspended spawn or a general Python pipe defect. Retain the earlier failures.

The search fixture now uses
[isolated_cli_process](../operator_test_fixtures/processes.py). On Windows it
creates the root suspended, assigns its retained process handle to a private
[Job Object](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
and resumes only its verified initial thread. The job permits no breakaway;
assignment or resume failure aborts that one launch without an uncontained retry.
After the root actually exits, closing the job ends only its temporary descendants.
The original bounded collector still reads both real EOFs and preserves the root
exit, exact request counts, authentication separation and output assertions.
Never use `child.wait()` as the prerequisite for this cleanup: inherited output
handles can make that wait depend on the very descendants that need cleanup.

The normal collection retains its 35-second deadline and five-second reader
cleanup budget. Failure/cancellation also closes the fixture transports and uses
a separate bounded process reap; it never changes a failed result into success.
This test-only helper is excluded from runtime packages and is not a service
cleanup policy. Verify it with an actually suspended descendant retaining both
pipes, full byte-for-byte output, an unaffected unrelated process, cancellation,
and failed assignment/resume. Then run the original CLI cases with all modules
imported and no diagnostic termination intervention. This is isolated CLI/test
ownership evidence, not a fix to the official binary or live Desktop acceptance.

## Process, transaction and output boundaries

Upgrade repairs add isolated argv/PID ownership fixtures for both PowerShell 5 and 7, complete-terminal opaque argument rejection, managed-rule byte comparisons, and public single-entry maintenance cases. Tests must exercise the public dispatch as well as private receipt validators. A run edited midway is diagnostic evidence; repeat the affected scope after freezing. Preserve raw log bytes and parse both Node spec and TAP summaries, including indented unittest subtest skips. Native cache timestamp drift remains a separate failed protection gate even when model records are unchanged.

Temporary directories do not isolate shared fixed ports; related port-reservation fixtures run serially across processes. Keep the product's exclusive reservation gate unchanged. Pin UTF-8 on both sides of captured PowerShell JSON, retain strict decoding and Unicode assertions, and use a private child console. Negative source-read injection must prove it hit the exact module and changed its digest. New contracts also require valid baseline fixtures; retain the original secret/allowlist and archive byte assertions when updating them.

A direct asynchronous test can stall in standard-library socketpair initialization before its setup runs in a restricted execution environment. Retain that stack and failed observation, then use the same declared local test boundary as the main suite for a separate check. Do not change event-loop policies, suppress callbacks or relax product deadlines to hide the difference. Concurrent native configuration changes remain a separate failed protection gate: preserve current settings and originals, and do not attribute a writer without evidence.

Transaction concurrency checks use independent interpreters and explicit checkpoints around the real write path, including abrupt exit and outside edits after preflight/fsync. On Windows a venv executable can redirect to a different process: bind the current environment's base interpreter for these standard-library-only fixtures and compare the child's reported PID with the controlled process. Retain uncertainty and original bytes; never turn a fixture crash into automatic lock takeover. Asynchronous health checks need both stale-success and stale-validation-error interleavings; invalid current-generation observations must still fail. A protocol test that releases one valid call before a later invalid item is a failure even if the final response is rejected.

## Web diagnostics and native cancellation

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

## Loopback transport and real cold launch

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

## Legacy maintenance and native approval evidence

Explicit legacy alpha-version maintenance also tests the public version flags, default refusal, exact from/to mismatch, downgrade and release-line rejection, complete original-manifest restoration, late source changes and preservation of later edits. The version selection is part of the preview identity; source-test success does not itself authorize deployment or erase an earlier incomplete wrapper run. Keep the documented 3600-second whole-run allowance when invoking the complete legacy module.

The fixture-only NativeApprovalCapture in [the evaluator](../../scripts/operator_responses_eval.py) is a separate opt-in App Server transport; the existing evaluate() and CLI cases keep their never/read-only policy. Use newly created private homes and raw-log folders, new synthetic work directories with normal permission inheritance, a pinned CLI, and an explicitly checked model/endpoint contract. The controller must constrain and inspect the actual command or file change. Capture the complete original request and response, exact RPC ID type, thread/turn/item identities, terminal outcome and before/after file bytes; a model claim is insufficient.

This lane uses untrusted/read-only settings, one combined 16 MiB raw-capture bound and a 120-second deadline that includes waiting for the owner. Only a decision on the exact pending single action may become a reply. The default contract permits accept or decline; the explicit CLI 0.160 single-action contract uses accept or cancel for its advertised command decisions. An exec-policy proposal remains inert request metadata, never an amendment response. Session grants, root grants and policy amendments are rejected. No default approval, manufactured timeout denial, repeated start or request replay is allowed. Preserve failed and incomplete captures. CLI/App Server evidence remains separate from live Desktop approval and native freeform-patch acceptance; an unregistered tool contract cannot be expanded to fill those gates.
