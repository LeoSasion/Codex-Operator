# Initialization and safe removal

## Desktop entry pair

Installations offer the two names requested on 2026-09-30. Legacy shared-home
generations share the official application, login and task history. Disposable installation/recovery
tests and one reviewed legacy migration have passed. The migrated Desktop and
retained Start menu file identities, current native configuration and original
receipts were checked. Real Desktop exit/start acceptance remains separate.

| Desktop name | Behavior |
| --- | --- |
| `ChatGPT 原生入口` | Open the official application on its native route, with a recovery path that does not depend on the extension router or Web service being available. |
| `ChatGPT 拓展模型 MM-DD 入口` | Open the same application with the explicitly configured extension models. The month and day identify the successfully installed extension build, not the latest launch, attempted upgrade or official app update. Retain its full date, including year, in the ownership record. |

The install record binds the full build date, version, source digest, launcher
and helper bytes. Reinstalling the same build is a no-op. A changed build uses a
private compiled candidate and a digest-bound preview before replacement; a
failed or uncertain transaction retains its originals and stops further writes.
The upgrade replaces the one owned extension link without accumulating dated
links. Unknown same-name
shortcuts and later edits stop installation/restoration without overwriting them.
The internal launcher retains the stable `Codex拓展入口.exe` path. No new Start
menu shortcut is created by the pair; old journaled entries retain their names.

In those legacy generations both entries share the native configuration. The native helper first checks that
configuration, then uses the exact [native recovery](../../models/common/docs/native-route-recovery.md)
transaction when necessary, preserving its original bytes. It does not need
Python or running extension services. Both launch paths activate the registered
Windows package; they never execute the packaged `ChatGPT.exe` directly. A running
instance with an active or uncertain cached route requires normal exit first.
The helper never kills Desktop. The extension link uses the reviewed startup
configuration and does not remove native-only protection or rearm a failed plan.
Returning from recovery to extended routing still requires explicit reviewed
activation; these are not a one-click live mode switch or simultaneous modes.

The pair supports only the normal current-user `%USERPROFILE%/.codex` home;
`CODEX_HOME` must be absent or point to that same directory. A brokered Windows
package activation cannot establish that a custom parent environment reaches the
application. Custom-home installations stop before pair writes.

The separately reviewed and installed 2026-10-02 `isolated_mode` generation is described in
[mode entry](../../models/common/docs/mode-entry-window.md). The native side still requires that
default home; the extension side has its own bound home, userData and chat list. It copies no
login/history and does not mutate the native route. The extension shortcut first shows native/extension
buttons, while models remain in the actual native conversation menu. Its native helper uses ordinary
registered-application activation without legacy recovery or a running-native-Desktop exit requirement.
Only a bound `-IsolatedModePath <entry.json>` build enables this policy; older records retain their
original behavior. Known-version initialization skips only the local welcome preference, never consent,
login or permissions. Search credentials are separately restricted to the fixed official search endpoint.
Actual shortcut checks passed extension cold start, both buttons, existing extension process reuse and
native-shortcut double-click, with the original native process/configuration unchanged. Installed
isolated entries require `models mode-maintenance pair-prepare|pair-preview|pair-apply` for a stopped,
digest-bound refresh of both the private entry and pair ownership chain. It preserves original native
shortcut bytes and pinned helpers; standalone refresh is rejected while a pair binds the entry.
Before runtime removal, every saved isolated instance and router must be known stopped; uncertain
preparation or process records block teardown. Isolated homes/history are retained outside runtime data.

`operator init` uses this pair for a fresh installation. The public commands are
`operator models desktop-pair preview|install|status|restore -ProjectRoot <project>`.
Preview/status are read-only; install uses the actual saved build metadata. Restore
requires routing/lifecycle checks, removes only the exact two owned links and keeps
native helpers for taskbar pins. Normal `operator uninstall -Apply` includes this
restoration after its routing checks. A partial transaction remains retained for
review, never automatically retried. An internal prepared pair build is marked
as such so a failed pair install cannot silently fall back to old shortcut names.

For an existing pair or a reviewed entry-only legacy installation, use
`models desktop-pair prepare-build`, then `preview-upgrade -CandidateDirectory
<returned directory>`, then `upgrade -CandidateDirectory <same directory>
-ExpectedPlanSha256 <preview digest>`. Preparation compiles only a private
candidate. The preview checks the existing native route, exact configuration,
source and helper bytes, build metadata and current shortcuts. An activation
record still requires its separate reviewed retirement before an upgrade.
Neither step starts services, closes Desktop, changes model routing or replays a
request. The installed date changes only after the whole transaction succeeds.
New preview digests sort dictionary keys consistently across independent
PowerShell processes while preserving arrays and values. Historical journals,
receipts and their original serialization rules remain unchanged.

If an unused prepared launch plan predates later native model, effort, hook or
other legitimate configuration changes, `models unified-withdraw preview --plan
<exact saved plan>` and `withdraw --plan <same plan> --expected-review-sha256
<digest>` retain that old plan in a separate witnessed archive. This accepts only
an exact `prepared_not_armed` journal, its complete original files and an intact
native-route protection marker. Armed, attempted, failed and uncertain plans
cannot use this path. The current configuration, model cache, entry files and
services remain untouched. Desktop may remain open for this archival operation;
its cached route is not attested. The earlier strict supersede operation keeps
its original native-configuration restrictions.

A preparation failure can leave an empty allocation before any plan or journal
was written. The separate `models unified-withdraw preview-empty|withdraw-empty`
path requires the exact failed preparation JSON and its SHA-256, a reviewed digest,
an ordinary empty directory with its original Windows identity, and intact native
protection. It retains the failure and moves that same directory by its bound
Windows handle into a witnessed archive. It never invents a plan or installation
ownership. Any child file, changed state or partial archive stops the operation
for review. Normal preparation briefly holds the exact config and cache snapshots
through its writes so Desktop background refreshes cannot invalidate them midway.

Legacy migration preserves the migration, adoption and configuration-upgrade
receipts. It renames the current Desktop link within its directory, retaining
its Windows file identity; the Start menu link remains the same entity. A
separate pair origin and build chain bind the old restoration materials and each
new build. No project/runtime first-install ownership is invented. Restoring the
pair first returns the old Desktop name and removes its added native link while
retaining the repaired build and native helpers for pins. Only then can
`restore-migration` restore the older shortcut originals. Runtime ownership still
requires its separate review. Pair restoration uses the route/process/request
checks independently of that later full-uninstall ownership gate.

Real acceptance still needs normal exit, native start with unavailable extension
services, extension startup and duplicate clicks. Keep the existing recovery
shortcut and legacy journals throughout the reviewed migration and acceptance.

## Current installation and migration behavior

The explicit native-first `direct_profile` candidate is documented in
[direct provider entry](../../models/common/docs/direct-profile-entry.md).
It keeps native protection and uses the same official package/default home.
Its private chooser index binds each installed API/Local profile plan, current
source, interpreter and independent native helper; it is not global routing.
`prepare-pair-build -DirectPickerPath <index>` prepares a separate compiled
candidate without changing real shortcuts or application configuration.
The normal reviewed pair upgrade retains current originals and all older
ownership generations. Legacy entry-only installations use their separate chain
and do not acquire runtime first-install ownership. Pending or uncertain direct
cycles block upgrade; new direct candidates use the read-only maintenance gate
to verify retained explicit recovery records before replacing a helper.

An archived old unified plan is recognized only through its exact retained
retirement and archive witnesses. A later native recovery transition is bound
as a new step without altering earlier build hashes or original receipts.
The direct workflow is a distinct index contract, never a fabricated Web startup
receipt. New generations retain the exact index for historical build-chain
validation, while current boundaries recheck live dependencies. This source
candidate still requires full regression and separate real installation and
Desktop acceptance; preparing a build does not refresh a running application.

For a reviewed legacy `Codex拓展入口` rename with no project ownership journal,
`operator_desktop_setup.ps1 -Action preview-migration` accepts its retained
`-LegacyReceipt` and the exact saved Web `-StartupBundle`. Explicit `migrate`
requires the returned `-ExpectedPlanSha256`, validates the old launcher and both
current-user shortcut paths again, and creates a **separate entry-only journal**.
It retains the current original bytes and absence state, not invented first-install
originals. Rules, Hooks and runtime ownership remain unresolved and unchanged.
An existing or uncertain transaction stops rather than replaying setup.

`restore-migration` restores only those original shortcuts after checking the
complete build, current files and backups. It preserves later user changes and
retains a native-only launcher for taskbar pins. This does not detach a model
route, stop a service, restore unknown legacy integrations or uninstall the
runtime. Full uninstall checks that this separate entry has already been restored
as well as the existing routing/lifecycle requirements. A migrated entry is not
evidence of cold-launch activation or live main-window model acceptance.

For that entry-only migration, `operator_desktop_setup.ps1 -Action
preview-entry-upgrade -ProjectRoot <project> -StartupBundle
<project>/.codex/operator-unified-startup -CodexHome <home>` reviews a separate,
one-time configuration upgrade. If emergency native recovery changed
`desktop-entry.json`, also supply its exact `intent.json` with
`-RecoveryReceipt`; the completed receipt and retained original must match the
migration baseline and current native configuration. `-Action upgrade-entry`
requires the preview's `-ExpectedPlanSha256`. It changes only
`desktop-entry.json` to select the reviewed unified workflow, retaining private
before/after bytes and an intent before the atomic write. Existing, incomplete,
or changed upgrade evidence stops further writes. It requires the native-route
marker and no unified activation plan, leaves the original migration journal
and unresolved runtime ownership intact, and never starts a service or activates
global routing. `restore-migration` recognizes only the exact completed upgrade
receipt and current configuration; it still checks the migration-time shortcut
originals and refuses later edits. Before marker release or cold-launch arming,
the current Desktop and Start menu shortcuts are checked against their ownership
journal and actual launcher target.

A later-edited Desktop shortcut is a separate stop, even when its visible launch
fields still match. `-Action preview-shortcut-adoption -ProjectRoot <project>
-CodexHome <home>` can read the one archived September 19 Desktop link and its
review files, compare their exact bytes with the current link, verify the
unchanged Start menu link and complete COM fields, and report a digest and a
bounded difference summary. Preview makes no changes. Only an owner-approved
`-Action adopt-shortcut -ExpectedPlanSha256 <digest>
-OwnerApprovedShortcutAdoption` may create a one-shot, separate receipt and
private copy of the changed bytes. It never writes either shortcut or changes
the migration journal's original `after` hash or rollback baseline. Incomplete
or altered adoption evidence blocks entry upgrade and restoration; those paths
recognize only the exact completed receipt and current Windows file identity.
Both shortcut adoption and entry upgrade require the supplied Codex home to
equal the home the launcher actually selects from `CODEX_HOME` or the current
user default. Adoption also checks the migration journal's old rollback
launcher and the installed entry script against current source. If restoration
was interrupted after the Start menu link returned to its exact retained
original, an explicit continuation may finish restoring the Desktop link;
other Start menu edits remain conflicts.

An independent Web Desktop trial may own an additional provider block.
Before uninstall, use `web desktop-disconnect` to remove only its exact recorded
bytes, preserving later unrelated settings. The uninstall preflight refuses an
attached, changed or incomplete trial. Its private originals and task history
remain; this does not stop the Web service or prove live Desktop refresh.

Before its first write, `operator init` explains the [desktop pair](#desktop-entry-pair)
for a fresh installation, or the retained Desktop/Start menu `Codex拓展入口`
ownership for a legacy installation, and project rules. Runtime installation explains the same scope before
installing Hooks and code. This notice is part of initialization, not an extra
permission prompt after an owner has already requested that scope.

The launcher is built locally under `.codex/operator-desktop-entry`; no binary
is published. Its executable and Windows product/title metadata use `Codex拓展入口`;
official `Codex` shortcuts remain separate. It resolves the installed Codex application dynamically. An
ordinary new installation opens native Codex. It does not activate the optional
Responses router or infer an LM Studio endpoint/capability policy. A separately
reviewed local-model startup bundle can be attached through `operator desktop-entry
-StartupBundle <bundle>`. An existing running Desktop is only opened. A cold
launch performs the already-configured startup workflow once, with its original
service, digest and no-replay checks. No background polling is introduced.

Windows-generated MSIX shortcuts and taskbar pins are not rewritten. Users may
need to pin the new launcher once. Shortcut name collisions or ownership by
another project stop setup; an installer never takes ownership merely because
a file has the expected name. Old `Codex.exe` installations require a reviewed
rename; restoration still recognizes their journaled shortcut paths and retained
launcher. Upgrading a runtime does not replace shortcut settings.

Repeated entry setup checks the existing executable and entry script against
their build record before replacing either file or starting a new ownership
generation. Missing files, invalid records or changed fingerprints stop setup.
The configuration must still reference the recorded entry script. A changed
managed shortcut also stops before the launcher is rebuilt, even if its new
target happens to be native Codex. Unchanged upgrades and completed-uninstall
reactivation retain their original recovery behavior. These checks do not attest
to historical configuration fields that were never recorded as fingerprints.

## Original files and recovery

The private `.codex/operator-installation/ownership.json` journal records exact
target paths, original fingerprints and installed fingerprints. Original bytes
are retained separately before an intent is published or a target is modified.
Upgrades retain the first original. Writes are atomic per file, not a claim of
an atomic transaction across every file. An interrupted operation remains
recoverable from the journal, without automatically replaying a startup or task.
Before rewriting an already managed file, the upgrade also verifies that its
first-original backup still matches the journal; a missing or changed backup
stops the write. This is covered by `test_install_upgrade.py`.
The installer checks the runtime destination and each copied file's parent
chain for links, so a linked runtime or nested directory cannot redirect an
upgrade outside the selected project. The same isolated test module covers
both boundaries. Runtime destinations are checked as a batch before runtime
copying begins; Hook writes earlier in installation remain separately journaled.
This is not an all-or-nothing installation transaction.

The journal covers the managed project rules file, Hook configuration, two Hook
scripts and selected current-user shortcuts. It does not own arbitrary files,
the native application, taskbar registry data, user task history or model weights.
Restore previews are read-only. Restore validates the complete file set first;
changed target files, altered backups, linked paths or unknown targets block the
operation. It never overwrites a later user edit to force a successful uninstall.
An existing installation with a missing ownership journal stops both recovery
and installation. A missing journal is never treated as an empty file set.

### Reviewed legacy runtime cutover

For an older installation that has a valid runtime manifest but no ownership
journal, `scripts/operator_legacy_runtime_upgrade.py` is a separate, explicit
runtime-code cutover. Run `preview --project-root <absolute project directory>`
from the canonical plugin source. Review its digest, changed-file count and
backup size; only then run `apply` with the same project root and
`--expected-preview-sha256 <reviewed digest>`. It requires the exact old code
hashes and the installed startup inventory to match its original manifest. The Operator,
saved Web service and model router must be stopped, the router entry deactivated,
and inbox/Final Callback work empty apart from the documented held failed row.

Schema 1 requires the same source file set. Schema 2 permits only the reviewed
pair `operator_core/web_native_interruption.py` and `operator_native_models.py`,
the required `operator_core/native_search.py` dependency, or both complete groups
to be newly added in the same version. Every added destination must be absent. It
retains that absence state and the current startup Hook bytes, replaces only
the literal file inventory, and requires all surrounding Hook bytes to match
the canonical source. Unknown additions, removals or other Hook differences
stop for review. The new manifest binds the resulting startup Hook hash.

The transaction keeps a complete private runtime backup in
`.codex/operator-channel-maintenance/legacy-runtime-upgrade`, checks the source
and protected integrations again, and replaces changed runtime code atomically
per file with the manifest last. A failed or interrupted apply is terminal: do
not retry it. After reviewing the retained transaction and stopping services,
`restore --expected-preview-sha256 <same digest>` can restore its exact old
runtime when no later file edits conflict. The separate journal **does not**
create first-install ownership for Hooks, rules, shortcuts or runtime data;
ordinary uninstall remains blocked until its legacy ownership is separately
resolved. Neither preview nor apply starts services or replays a message.

Schema 2 recovery removes only its exact unchanged added files, restores its
retained startup inventory and runtime originals, and preserves later edits.
An incomplete restore write is terminal and is not retried; read-only preflight
rejection does not rewrite the transaction. Schema 1 receipts remain restorable
under their original file-set and ownership checks.

After an explicitly reviewed dead Web instance has been archived, the Web manager
correctly reports `configured`, rather than a clean stop. A runtime cutover may
use `--web-recovery-receipt <exact completed receipt>` for that separate state.
The preview binds the selected receipt and its retained originals, confirms the
current profile and absence of the old processes, listener and active marker,
and rejects incomplete recovery history. Apply uses the same receipt and preview
digest. Without that explicit evidence, the existing stopped-service check stays
in force. This does not rewrite the old abnormal exit, start services or replay
requests, and it does not establish first-install ownership.

After a completed uninstall, ordinary `operator init` / `operator install`
can start another installation. The previous journal and uninstall receipt are
retained under private `operator-installation/history`; original-file backups
and archived runtime data remain intact. A partially completed uninstall, an
unavailable completion receipt or changed restored files stops reinstallation.
The retained taskbar launcher is checked before reactivation. Reinstallation
starts in native mode unless a reviewed startup bundle is explicitly supplied;
it does not reuse an old workflow that may refer to archived runtime state.
`operator init -StartupBundle <bundle>` preserves that explicit selection.

## Safe uninstall command

First restore any API/Local native profiles selected for removal using their
retained transactions in [native model onboarding](../../models/common/docs/native-models.md).
Generic uninstall does not discover private profile transactions or remove
arbitrary Codex profiles; retain each transaction until its restoration completes.

Run `operator uninstall` to review the exact recovery plan. Finish pending
callbacks and requests and stop the exact Operator first. If the optional global
router entry is active, close Desktop before restoring its configuration.

The unified entry accepts `uninstall -ProjectRoot <project>` and forwards
`-CodexConfig <config.toml>` and `-RouterPort <port>` when explicitly supplied.
These two options apply only to uninstall; otherwise the existing current-user
config and port 4317 defaults remain. Use the installation's actual identities,
not an arbitrary unused port to evade a running-service check. Add `-Apply`
only after reviewing the same plan.

A saved Web service must also be cleanly stopped, even when no Web cold-launch
plan was ever created. Preflight checks it before restoring files or archiving
the interpreter. Missing, malformed or uncertain service records block teardown.
Channels-only installations with no Web state need no optional Web dependencies
for this check. The official-route recovery lock still prohibits global
activation, while allowing Web status, disarming a deactivated entry and stopping
its exact idle router for cleanup.

The disposable unified picker trial has no real-home uninstall owner. If its
configuration markers, the parsed candidate provider identity (including TOML
escapes), home marker or transaction directory appear at the selected Codex
config path, uninstall stops before routing detachment or runtime archival.
Even a `reverted` journal needs separate review; uninstall never
interprets it as permission to discard the retained transaction.

A real unified picker preparation has separate ownership under the selected
Codex home's `operator-unified-activation` directory. Emergency native-route
recovery can remove a recognized active candidate route and put the checked
entry back in native mode; it does not retire the activation plan or restore
its model-cache backup. With the plan-bound router explicitly stopped and
Desktop closed, use `codex-operator.ps1 models unified-retire preview --plan
<plan.json> --recovery-intent <recovery-run>/intent.json`, then `retire` with
the same paths and `--expected-review-sha256 <digest>`. `status --plan
<plan.json>` rechecks the terminal receipt. The command retains all original
evidence and any later cache edits. It accepts prepared or armed plans and
fully witnessed switches only after exact native recovery; partial or
uncertain attempts still block uninstall. See the [cold-launch retirement
procedure](../../models/common/docs/unified-cold-launch.md).

Uninstall requires that terminal retirement receipt and rechecks the native
entry, original config, native-route marker and stopped router. Restore the
separately owned entry shortcuts first; their original ownership journal is
not created by unified retirement. A running saved Web service, pending
callbacks, changed launcher, or other ordinary uninstall blocker still stops
teardown before writes. Removing the plugin alone does not perform these
recovery steps.

`operator uninstall -Apply` rechecks the current state, detaches only the exact
owned router entry, stops its request-free router once, and unregisters only
this runtime's Final Callback mapping. It then restores original files and
removes files created by this installation. Unrelated callback registrations,
settings, tasks and other applications remain untouched.

The router check recognizes the exact canonical-source and installed-copy
script identities for this state directory. It retains the observed service and
process identity and checks them again before issuing one stop; an unrelated
router or changed process is rejected.

The detached runtime, including local state and retained data, is moved to a
unique `.codex/operator-uninstalled` archive, never recursively deleted. A small
launcher remains in native-only mode so existing taskbar pins still open Codex.
That mode uses the Windows app installation directly and survives plugin-source
removal; it does not start the router or depend on plugin code or PowerShell 7.
The retained archive and recovery journal remain private.

Only after the command reports success should the user remove the plugin in
Codex Desktop. The plugin declares no supported pre-uninstall handler; clicking
Remove in Desktop alone is not claimed to run project recovery. The setup notice
states this order before installation. Do not invent a removal Hook or modify
the app's uninstall implementation.

Older installations without an original ownership record require a separately
reviewed migration. Do not treat the latest runtime backup as the original, and
do not make old data appear to be a fresh-install receipt. A stopped recovery
plan can preserve original shortcut receipts and identify exact owned Hook/rule
fragments for removal, with its provenance stated separately.
