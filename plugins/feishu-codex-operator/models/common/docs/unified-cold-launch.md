# One-shot unified picker cold launch

`scripts/operator_unified_cold_start.py` consumes a reviewed
`operator_unified_prepare.py` plan once. It does not start or restart the Web
service, router, or Desktop; it sends no model request. Its successful result is
`config_switch_witnessed`, with Desktop acceptance still unverified. The
existing `Codex拓展入口` launcher opens the official Desktop application only
after the workflow exits successfully.

## Entry and preparation order

An automatically reopened native application after a failed handoff is recovery,
not update completion. The saved result must report `config_switch_witnessed`
and witnessed package activation before reporting the unified switch. New local
preflight failures preserve only explicitly allowed typed preparation,
supersession, file and bounded Windows error codes; unrecognized exception text
remains redacted. This does not retry a transaction or change older results.

The current launcher accepts schema 2 only with the exact name
`start-codex-with-web.ps1`. The unified workflow uses that name in its own
`.codex/operator-unified-startup` bundle. This is a reviewed Web-plus-router
startup contract, not the older `.codex/operator-web-startup` plan. The
launcher source and its saved Web startup source identity remain unchanged.

1. Prepare the Web service and an API/Local registry router through their
   existing explicit lifecycle, then bind the exact ready, idle Web generation.
   The router must run the source that reports the bound Web profile and session
   SHA-256 values in read-only `/lifecycle` diagnostics. An older running router
   lacks those fields and blocks arming; replacing its code needs its own
   explicit request-free restart, never an automatic action here.
2. Run `operator_unified_cold_start.py workflow` with the exact project, Codex
   home and reviewed Python interpreter. It creates only the private schema-2
   bundle and pins the consumer source, interpreter and future plan path in a
   hashed PowerShell script. Any later source or interpreter change invalidates
   that bundle. Do not edit the script or manifest to bypass the check.
3. For a fully owned installation, use `operator_desktop_setup.ps1 -Action install
   -StartupBundle <project>/.codex/operator-unified-startup` transaction to
   select that bundle for the current user's `Codex拓展入口` shortcuts. This
   updates the owned `desktop-entry.json` after checking the previous launcher
   and shortcut fingerprints. The existing native-route recovery entry can put
   the checked launcher back in native mode. A launcher still in native mode
   cannot arm this trial. An entry-only legacy migration must use its separate
   reviewed config attachment; never invoke first-install setup to invent missing
   runtime ownership. Reselecting a recovered existing workflow uses the exact
   original and receipt described in the upgrade section below.
4. Use `operator_unified_prepare.py preview` and then its explicit `prepare`
   with the reported review digest. Preparation binds exact config and model
   cache bytes plus Windows file identities, recovery source, workflow, source
   hashes, registry bytes, router PID/birth, and idle Web session digests.
   Preparation holds short Windows read handles on the exact existing config and
   cache before creating its directory, rechecks all readiness inputs, and keeps
   the handles until its journal is written. Missing cache files remain subject
   to absence checks. No cache timestamps or other source bytes are filtered.
   If the native-route-only marker was present at preparation, use the separate
   reviewed `operator_unified_marker_release.py preview` then `release` with
   its exact review digest. It retains and witnesses the marker's bytes and
   Windows identity. Removing the marker by hand cannot substitute for this
   receipt. `operator_unified_cold_start.py arm --plan <plan> --python <same
   interpreter>` rechecks those identities, verifies the selected installed
   entry and full release receipt, and binds
   either the direct interpreter or the Windows venv launcher parent and base
   interpreter child. Run `arm` under the same Python executable named by
   `--python`. The native-route-only marker must be absent and Desktop must be
   fully closed before arming. This module has no marker-release action.
5. On a later click of the selected shortcut while Desktop remains closed, its
   exact script invokes `consume`. The old router PID/birth, registry digest,
   Web route digests, parent/child interpreter lineage, marker-release receipt,
   source, recovery,
   configuration and cache must still match. If Desktop is already running,
   the launcher simply opens that instance and does not consume the plan.

Before moving the cache, `consume` writes one exclusive `attempt.json` with
phase `may_have_activated`. A crash, denial or changed observation after that
point is terminal and requires review; another click never retries it. An
existing cache is held under a Windows handle that denies in-place writes from
the full preflight through retirement and completion witnessing. Delete sharing
allows the one-shot move; this is not an atomic compare-and-swap. A path swap
still has to pass the exact before/after identity and byte checks, and a missing
cache retains its explicit absence checks. A held writer blocks before the
attempt. No timestamp or catalog field is ignored to admit a changed cache. An
existing cache is moved to a unique private backup and compared by exact bytes
and Windows file identity. The configuration switch uses
`windows_config_transaction.replace_config_once` and its read-only witness.
Only after both witnesses and a final router/Desktop check does it write
`completion.json`. The native marker and full release receipt are also
rechecked after cache retirement, before the config replacement, and before
completion. A marker that reappears leaves the attempt terminal without
opening Desktop. The original configuration, boundary backup, cache bytes,
and uncertain evidence remain private. No file or turn is replayed or silently
restored.

The prepared plan binds one live router process. A reboot, router restart, Web
session change, source edit, cache rewrite, or uncertain launch invalidates
that attempt; this is not persistent restart recovery. A native-route-only
marker prevents arming until its separate reviewed release transaction has
completed and its receipt verifies.

### Replacing an untouched prepared plan

`operator_unified_supersede.py` has a narrower, explicit path when a prepared
plan's cache snapshot or one Desktop-owned Computer Use pipe setting has gone
stale **before** marker release, arming or any
launch attempt. Close Desktop first and keep the exact native-route-only marker
and reviewed startup entry. The plan-bound router may still be idle, or its
exact saved process may be absent with its port exclusively reservable and the
saved Web route still ready. Run the
script under the exact Python executable saved in
`start-codex-with-web.ps1`. Use `preview --plan <plan.json> --python <saved
python>`, then `supersede` with the same arguments plus
`--expected-review-sha256 <digest>`. This does not recover a switched route,
stop or start the router, change the entry, or restore/overwrite the current
cache. A stopped router needs a separate, freshly witnessed start before new
preparation.

Supersession retains every original plan file in a private generation archive.
Its exclusive intent is written before the same-volume directory move; the
receipt follows a fresh check of native config, marker, cache, entry, workflow
and router. `operator_unified_prepare.py` blocks new preparation while an
archive intent lacks a valid receipt, an archive changes, or an old plan
reappears. On a complete receipt, the fixed plan path is empty and a new
`prepare` may snapshot the current cache while Desktop stays closed. The
existing reviewed entry/workflow still points to that fixed path, so no
second entry upgrade is needed. An incomplete supersession is terminal and
requires separate review; never delete its directory or retry it implicitly.
This path rejects any marker-release, arm, attempt, completion or unknown
artifact and cannot retire a witnessed or uncertain activation.

### Explicit archive of the dated cache-prewrite failure

`models unified-failed preview` and `archive` provide a separate maintenance
scope for the retained September 30 consumer contract. Select the exact saved
interpreter with `--python <saved-python.exe>`; the public command selects it
and the Python helper verifies its own identity. Supply the exact
`--plan`, `--handoff-result`, `--consumer-source` and `--recovery-intent` paths;
archive additionally requires `--expected-review-sha256` from the fresh preview.
The historical consumer must match the reviewed
`af99c0e24316641e30ab2919e9bf3730cbf10fe4d16e140ad0784fcea5dba8bf`
source. Its unchanged test fixture records provenance, not development authority.
Only the exact consume-stage `unified_cache_changed` outcome with zero model
requests and no reopen is admitted. A cache backup, configuration transaction,
completion, unknown artifact or other error remains blocked. This is explicit
reviewed maintenance; ordinary retirement and the unused-plan paths still reject
the failed attempt.

The preview binds all original files and directory identities, the completed
native-entry recovery, current native config/cache/entry snapshots, exact old
workflow and interpreter, failure context and maintenance source. The router's
saved PID must be absent and its port exclusively reservable; the Operator and
saved Web service must be stopped with no pending callback or actionable inbox.
Desktop may remain open on its unchanged native route. A later native model,
detail-mode, Computer Use pipe or observed native reasoning-effort preference
may be retained only as complete, digest-reviewed current bytes. Other config
changes remain conflicts. No settings are rewritten or copied from history.

Archive copies the bounded context and all original file bytes, then moves the
same failed directory by one Windows handle rename into the independent private
`operator-unified-failed-archive`. Windows requires descendant handles to close
at the move boundary; the directory itself stays bound, then every moved file
is frozen and compared with its original bytes and identity. A changed child
leaves both the captured original bytes and changed directory for review. The
completion fence remains until all final witnesses pass. Partial archives block
new preparation and uninstall and are never retried. Read-only `status --plan`
checks archived evidence, without observing current chats or refreshing caches.

The original attempt remains failed and terminal in the archive. This operation
only frees the fixed preparation allocation after independent review. It never
creates activation success, restores a model cache, starts a service or Desktop,
changes routing/entry/workflow, or replays a request. A replacement workflow and
new preparation still require their own explicit checked transactions.

For ordinary supersession, a config change is admitted only when the sole changed line is the value of
`SKY_CUA_NATIVE_PIPE_DIRECTORY`. The preview and post-move witness bind the
current config identity and newly rendered candidate; fresh preparation uses
that current config without rewriting the Desktop-owned value. Any other
config change remains a conflict, and the original plan/config copy stays in
the archive. Only when the exact old router process is absent may the router
and candidate renderer source fingerprints differ from that untouched plan;
the archive review binds the replacement source fingerprints. Other source
changes still block supersession.

### Source-pinned workflow renewal

Legacy pair retirement recognizes a completed renewal through its independent
receipt. It compares the historical upgrade and every pair step with the exact
retained workflow, while checking the current replacement's complete file and
directory identities. Unknown, partial, ambiguous or changed renewal records
still block preparation. This read-only recognition changes no historical
receipt, ownership, native configuration, service or activation.

`operator_unified_workflow_renew.py` provides a separate digest-reviewed
`preview`/`renew` maintenance API after the exact failed archive is complete.
It requires the original two workflow files and their Windows identities to
match retained context, native protection, no allocated activation, exact entry
recovery and ownership, the saved interpreter, stopped services, an exclusively
reservable router port and empty inbox/callbacks. It does not admit an unknown
workflow or broaden failed-plan retirement.

The independent `operator-unified-workflow-renewal` journal copies original
bytes before one directory-handle move. The required Windows closed-child
boundary preserves directory identity; changed children keep their captured
originals, moved state and an incomplete fence. A new workflow is generated by
the existing creator and bound to current source. Entry reselection uses the
original recovery path and exact retained entry bytes, with a before/after,
replacement backup and completion receipt. Its input is a new workflow scope,
never a rewritten historical activation. Native config, cache and protection
stay guarded. Unknown, partial or changed records block preparation and uninstall.

No activation is prepared or armed by renewal, no service or Desktop starts,
and no request is replayed. Subsequent existing preparation may save a reviewed
plan while Desktop is open. The existing independent handoff then observes a
normal exit, supersedes only that untouched unarmed plan, and prepares from a
fresh complete snapshot before marker release, arming and one consumption.

### One-shot Desktop-exit handoff

`operator_unified_handoff.py prepare` saves a private, source-bound handoff
manifest while the existing Desktop remains open. The explicit `launch` action
uses the local Windows process service to start a hidden worker in the same
user session, outside the Desktop process tree; it witnesses the worker's
process ancestry and start record. A hidden window alone was insufficient:
two earlier September 29 attempts left start records but no terminal receipt
after the owner closed Desktop. Their exact termination cause was not observed.
The heartbeat reports only a bounded `ChatGPT.exe` process count; a closed
window with a remaining background process still blocks the cold launch. `run` waits
by default up to two minutes for a normal, stable Desktop exit; it never closes the app. It
then invokes the supersede, new preparation, marker release and arm preview/
commit pairs once. When the old
plan-bound router has exited, the runner starts a new router only after the
old plan is archived, verifies that the ready listener is the process it
started, explicitly binds the saved Web generation, and binds that new process
in the new plan. A separate `prepare-current` handoff may finish an already
prepared plan with an unchanged, bound idle router; it does not archive or
restart that plan. After arming, the independent worker invokes the same
one-shot `consume` directly, then activates the official packaged app through
its validated Windows application ID. A raw launch of the WindowsApps
`ChatGPT.exe` does not supply package identity and is not a fallback. Every stage
checks its exact witness and stops without retrying on a changed or uncertain
state. After maintenance has begun, if the original native configuration remains exact and no cold-launch
attempt exists, a failed handoff may activate the official packaged app so the
owner can inspect the retained private result. An uncertain attempt never
triggers that fallback. A launch intent or start record without a terminal
result is uncertain and must not be retried automatically; the bounded waiting
heartbeat helps locate the last witnessed stage but does not prove its cause.
Read-only `status` reports an overdue missing result as review-only; it never
resumes the runner. This is only exit coordination, not a model request,
automatic recovery or Desktop picker acceptance; `status` reads its bounded
result after the app reopens. Never relaunch an existing handoff. A later new
handoff for the same still-unarmed plan requires a terminal prior result and
fresh review of its exact plan, router, native config and protection marker;
an uncertain or active predecessor blocks it.

Before asking the owner to quit, `launch` also requires a shown-window receipt
from the exact status-window child. If that window cannot start, maintenance
does not begin. This single window is limited to explicit maintenance; normal
startup and conversations do not open it. It displays preparation, a countdown
while waiting for exit, update progress, application opening and a retained final
outcome. Closing it while waiting requests defer and waits for acknowledgement.
Defer is accepted only before the maintenance boundary; once updating begins,
the window waits for the actual result. It has no retry, service or process-kill
button. Cancelled, timed-out or failed preflight waits never change settings or
start the application. Observation errors stop distinctly from a process that
is still running; the same-name process safety gate is not relaxed.

The bounded status journal contains fixed phases and counts, with no task,
request or credential contents. Readers accept only its latest complete record,
never a torn tail; terminal transaction receipts remain authoritative. This
avoids the observed Windows rename/read-handle conflict. A stale or unavailable
status ends the UI's waiting indication with an explicit unconfirmed-result
message. Successful activation, witnessed native recovery and merely attempted
application startup have different outcomes. The full exit/update/reopen path
with this window remains a release acceptance gate, separate from control,
concurrent-file and simulated lifecycle tests.

Explorer delegates activation to Windows; its exit code and lifetime are not
the packaged app's outcome. After one activation, the runner requires the exact
executable and package identity with stable process birth within the bounded
observation period. It never launches a second instance to repair a missing
witness. A later Desktop config rewrite can make the strict transaction status
review-only even when `completion.json` records the earlier switch. Preserve
both observations and compare changed fields read-only; do not relax the byte
identity gate or consume the plan again.

## Explicit retirement after native recovery

### Replacing a witnessed activation during an explicit upgrade

`operator_unified_handoff.py prepare-upgrade` is distinct from replaying a cold
launch or superseding an untouched plan. It requires the original completed
Windows config witness, exact owned entry, current idle router process and
bound idle Web generation. A source-stale Web service may be inspected through
its saved process/session identities; changed settings, uncertain ownership or
active requests still block. An optional `--contract-updates <absolute JSON>`
binds both current and candidate registry digests using `update-contracts`.
Preparation writes only its private manifest. `launch` starts one independent
hidden worker and one visible maintenance status window before asking the owner
to quit Desktop normally. The default wait is two minutes.

After exit, the worker rechecks the entire manifest, updates the owned recovery
entry, recovers native routing, stops the exact idle router once, retires and
archives the witnessed activation, and applies the optional stopped registry
transaction. It explicitly refreshes a source-stale Web service only after its
normal stop is witnessed, retaining login, connection, prior profiles and turns.
It then starts a new router, binds the ready Web generation, selects the owned
entry, and prepares/releases/arms/consumes a new cold-launch plan. Opening the
official packaged app requires its existing process witness. There is no model
request, automatic retry, old-turn replay or termination of Desktop.

Explicit retirement can preserve changed **values only** for the existing
top-level `model`, `desktop.conversationDetailMode` and
`mcp_servers.node_repl.env.SKY_CUA_NATIVE_PIPE_DIRECTORY` string fields.
Their TOML paths, line count, quote/newline form and all other bytes remain
checked. The recovered config must retain the same current values, and its
full digest and file identity enter the new review. This never weakens the old
activation's exact-byte witness or retroactively changes its status. Other
changes require separate review.

`operator_unified_retire.py archive-preview|archive` moves only an already
retired activation into `operator-unified-retired-archive`, retaining a bounded
file/identity manifest, intent and completion receipt. It does not change config,
cache, services or models. Incomplete or changed archives block new preparation
and uninstall. The old directory is never deleted, emptied or reset.

If preparation failed after allocating a directory but before writing any files,
`operator_unified_withdraw.py preview-empty|withdraw-empty` accepts only the
observed ordinary empty directory, its Windows identity, and the exact bounded
failure JSON bound by SHA-256. Its independent schema retains that failure and
the original directory in `operator-unified-prepared-archive` using one bound
Windows handle rename. It freezes the reviewed config, native protection, cache
and entry snapshots through the witnessed move. No plan, journal, installation
ownership or successful activation is inferred. New children, changed identities
and incomplete archives remain terminal for review, with no retry or reset.

An upgrade failure stops at its recorded stage. The worker may reopen the
official app only if exact recovery evidence confirms native config and its
protection marker, with no new uncertain activation. A launched upgrade is not
automatically repeated against the same original plan. Inspect its saved result
before further maintenance; Desktop acceptance remains separate from deployment.

Entry reselection restores the exact `desktop-entry.json.before` retained by
native recovery and bound to the old activation's entry witness. It does not
invoke first-install setup: an entry-only migration deliberately has no runtime
installation journal. Check the recovered native bytes, original entry digest,
unchanged launcher/build/workflow and owned shortcuts before replacing only this
configuration. Retain before/after bytes, replacement-boundary backup and a
completion receipt in a fresh maintenance directory; later edits or an existing
attempt stop the operation. Native protection remains in force until a separately
prepared and reviewed activation is consumed. Failed handoffs remain terminal.

The saved plan is not retired by native-route recovery alone. First use the
official-route recovery command with the same project and Codex home, and
retain its exact `intent.json` path from the completed recovery run. The
recovery must put the owned entry in native mode, restore the original config
if the unified switch was witnessed, and leave the exact native-route-only
marker. Stop the plan-bound router through its explicit request-free stop and
close Desktop before reviewing retirement. A running saved Web service remains
a separate uninstall blocker.

`codex-operator.ps1 models unified-retire preview --plan <home>/operator-unified-activation/plan.json
--recovery-intent <home>/operator-route-recovery/<run>/intent.json` returns a
review digest without writing. Pass that digest to `models unified-retire retire`
with the same plan and recovery paths plus `--expected-review-sha256 <digest>`.
`models unified-retire status --plan <plan>` rechecks the terminal receipt and
current native state. Use the Codex home selected by the launcher; for a
nondefault home, set `CODEX_HOME` for this command as well. The command sends
no model request and does not stop services, restore cache bytes, or edit the
configuration. It retains the preparation, activation and recovery evidence
with an exclusive `retirement/intent.json` and `retirement/receipt.json`.

Prepared plans, armed plans that never attempted a launch, and fully witnessed
switches are eligible only after exact recovery. An attempt without its
completion witness, a partial marker release, changed native entry/config,
or uncertain router state remains blocked for separate review. A cache created
or edited after the switch stays untouched; the original cache backup remains
private. After retirement, restore the separately owned entry shortcuts before
uninstall. Uninstall rechecks the retirement receipt, native entry/config and
marker, stopped route, and its other service and ownership gates.

Neither a config witness nor a cached catalog proves that the Desktop picker
offers the model, that a click selects the intended endpoint, or that native
voice, tools, approval and Stop work. Those require distinct live Desktop
acceptance with new requests and preserved failed turns.

2026-10-01 live review witnessed a new config/cache switch and official package
reopen after the owner's normal exit, with the exact bound router surviving.
Retained original bytes and Windows identities matched. Desktop subsequently
replaced its own CUA pipe value, so the strict old transaction's current-target
check returned `target_not_candidate`. A separate full-byte read-only comparison
found only that one managed value change and matching service bindings; it did
not rewrite the historical transaction, reset the attempt or authorize replay.
The ordinary menu displayed the four model areas, but the first new same-task
native turn failed a historical-content format check. Cold-launch completion
and conversation acceptance therefore remain separate results.

The disposable Windows tests exercise the cache/config witness, one-shot
rejection after a simulated crash, changed source and cache, native mode,
missing or changed router binding digests, the venv launcher/child identity,
and exact native recovery and retirement for prepared, armed and witnessed
switches. Retirement tests simulate the stopped router and preserve edited
cache bytes; they do not establish live Desktop acceptance.
The router diagnostic tests use no secrets or request content; the optional
full HTTP lifecycle case runs only where `aiohttp` is installed.
