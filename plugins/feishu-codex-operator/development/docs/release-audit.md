# Preview verification scope

This is a Windows preview, not a claim of production stability or support for every IM/model.

The entries below are dated observations, not a live status dashboard. Test
counts refer to their individual runs; the current source must be checked with
the [test instructions](testing.md). A later source-only pass never changes an
earlier live-task result or proves that installed services were updated.

2026-10-04 bounded evaluator-cleanup delta:

- The second frozen regression completed 1,766 Python tests without assertion failures,
  test errors or reader-thread errors, with six conditional skips; all 157 Node tests
  passed. Its original protection gate remains failed: the native root reasoning-effort
  value changed during that run, while all other native bytes stayed identical. The
  actor and cause remain unknown; the current setting is preserved. One ancillary
  Proactor callback exception is retained separately, with no inferred failure cause.
- Evaluator cleanup now shares a five-second asynchronous budget across process exit,
  stream collectors and the local runner. Kill/wait errors and child-task cancellation
  retain a failed report with the actual observed exit or an explicit unknown value.
  Caller cancellation still propagates. Cleanup closes fixture admission before late
  requests can reach its handler, and returned diagnostics are independent snapshots.
  Unknown exit or incomplete cleanup retains the private home and any separately owned
  work directory. A failed directory creation never grants ownership of an existing path.
  Seventeen new in-memory regressions cover these boundaries. They do not attest to
  complete asyncio shutdown, filesystem timing, real Windows worker cleanup or native
  freeform-patch execution, and do not change requests, token limits or retry settings.
- The separately reviewed source-test gate allowed seven exact stopped-runtime code
  updates. Web startup then stopped at a read-only process-identity preflight; no start
  intent or service launch was created. Entry refresh and current-window acceptance
  remain pending. Prior failed model, approval and legacy-ownership gates remain visible.

2026-10-04 follow-up candidate:

- The first hidden frozen regression ran 1759 Python tests with no assertion failures,
  two test-harness errors and six conditional skips; all 157 Node tests passed. Strict
  UTF-8 readers rejected CP936 PowerShell error formatting in two legacy-pair cases.
  A third launch-rejection case appeared successful without checking its failed stderr
  reader. Independent byte captures preserved the original nonzero exits, fixed
  rejection reasons and unchanged protected files. The test bootstraps now explicitly
  select UTF-8, and launch rejection requires an actual captured nonempty stderr string.
  This failed full run remains retained; the corrected source requires a new full run.
- CLI timeout diagnostics now retain bounded consumed-stream prefix counts, SHA-256,
  EOF and overflow observations, plus the actual process exit and harness kill request.
  They do not reconstruct lost output, reread a stream, enlarge the 16 MiB bound,
  change request budgets or turn a timeout into success. Synthetic cleanup observations
  do not establish real Windows child cleanup or explain an earlier wait.
- New independent model cases retain separate stages: the custom-source case failed;
  a four-part synthetic-result case returned the exact marker without execution; two
  freeform-patch cases returned exact original patch bytes, but native writing failed
  in one and completion timed out with missing exit/output evidence in the other.
  The first fixture's work directory was beneath a private TemporaryDirectory; its
  original ACL was not observed. The second used normal work inheritance and a private
  home. Native capability setup changed ACL entries, but no actual worker token or
  denial established the wait's cause. No failed request was replayed or reclassified.

2026-10-03 remaining-work candidate:

- Six remaining workstreams are being completed after the owner requested all of them.
  Sixteen old isolated acceptance chats were archived once through the native API, six
  key chats remain active, and every history file stayed byte-identical. The extension
  exited normally; its request-free router and Web service stopped once each, while
  the original native Desktop and native configuration were preserved.
- Task registration now validates sender/private-chat identity after task creation and
  inside the final binding CAS, including a concurrent explicit binding. Oversized
  project grants are rejected before profile/database/directory writes. An existing
  legacy entry migration directory without its journal blocks uninstall. The complete
  four affected modules initially passed 119 tests with no skips; eleven separate restoration,
  interrupted-transaction and later-user-edit controls also passed.
  Independent review found that revocation's default JSON spaces expanded a valid 16 KiB
  grant beyond the read bound. Revocation now encodes and checks compact JSON before
  backup/temporary writes, preserving originals and later edits. The next complete
  four-module run passed 122 tests without skips, including exact-bound idempotent revoke.
- Explicit Web start observes and binds only its exact late-ready generation under
  one lock, with no second spawn. Dependency I/O is followed by fresh source/settings,
  profile/current-record and fixed-connection checks before any launch journal. The
  direct hidden PowerShell entry explicitly decodes UTF-8 helper JSON. Its complete
  eight-module regression passed 172 tests with one unavailable-symlink skip, and a
  separate hidden-entry run passed all 18 tests. Prior CP936 failures remain retained.
- Read-only approval verification supports the current CLI 0.160 granular policy and
  native item types. A real allow/deny gate needs identity-paired original native RPC
  evidence and execution/denial terminal evidence. Non-null subcommand approval IDs
  and session-root grants do not establish single-action approval. Twenty-four verifier
  tests passed; the private summary observer's CRLF mismatch remains a separate failure,
  independently reviewed against its complete original test log without rerunning.
- A new Huihui custom-source probe failed once with
  `completed_response_without_message_or_tool`; no source execution or second-step result
  delivery occurred. The current native standalone apply_patch grammar was observed in
  a zero-model CLI fixture and rejected by the older adapter. Its explicit registered
  codec now admits only an explicitly registered bare apply_patch with the complete
  observed Windows CLI 0.160 grammar. Actual nonempty input stays verbatim under the
  existing 2 MiB bound; unknown/changed grammar and other names/namespaces remain rejected.
  All 51 tool-adapter tests passed. No history codec or active registry was broadened.
  A new live case remains separate; ordinary command-based file edits do not establish
  either freeform-patch or custom-exec fidelity.
- Complete frozen regression, runtime deployment, the next service generation, paired
  entry refresh and restored current-window acceptance remain separate pending gates
  at this candidate stage. A second real Channels account is still required; the supplied
  name resolves to the existing owner, whose exact binding is preserved. No new-user,
  untested-model/token-capacity or missing legacy first-install gate is inferred.

2026-10-03 second official-update repair candidate:

- Current Desktop product 26.930.31730 / Windows package 26.930.3930.0 uses CLI 0.160.0.
  Thirteen new local compatibility cases passed; no business turn was sent. The native
  route remains official direct. Before the maintenance below, the saved isolated entry
  still bound package 26.930.2377.0.
- The owner requested all known issues repaired. The exact vanished isolated router gained
  a separate absence review retaining its original running record; no stopped record or
  request-free server claim was created. The idle saved Web service was then normally stopped,
  preserving login and native configuration. Package deployment and fresh live acceptance
  remain separate from these maintenance records.
- Status now checks the isolated entry after the manager observation, with its checked saved
  interpreter and current binding, rather than projecting a retained legacy provider. Installed
  runtime status uses only a byte-identical canonical helper's fixed read-only action; missing
  canonical maintenance modules do not justify silently installing their authority into runtime.
- The status review also identified imports occurring before controller path validation. The
  candidate must reject missing or linked canonical dependencies before their code executes;
  a same-named system module is not a substitute. The incomplete superseded regression remains
  retained and does not count as a full pass.
- Router startup requires native_search.py, but both installer inventories and the startup
  guard omitted it. The candidate adds that one dependency and its narrowly reviewed schema-v2
  missing-file migration. Original absent state and Hook bytes are retained; historical pair-only
  receipts keep their scope. Legacy first-install ownership remains unresolved.
- Candidate full regression, runtime deployment, package entry update and different new
  Desktop execution cases must be recorded separately. Approval/denial, native freeform patch
  and untested models retain their original verification status. Native generic 413 retries
  remain an official-client limitation and do not authorize global routing.
- The completed v3 regression ran 1,709 Python tests with 12 failures and six conditional
  skips; all 157 Node tests passed. Source, CLI and native configuration stayed unchanged,
  with the exact Operator stopped and callbacks/inbox empty. This is a failed full run,
  retained separately from the two earlier incomplete runs, and does not authorize deployment.
  Two fresh private diagnostics reproduced all 12 CLI failures. Complete parsed requests
  passed request adaptation unchanged; they contained no AdditionalTools envelope. The
  evaluator's proxy override omitted the newer `web_binding` keyword accepted by the base
  router, so Python rejected dispatch before entering that override. A separate signature
  binding check confirmed the mismatch; it is not a reconstructed original traceback.
  The narrow candidate repair adds and forwards that keyword in the evaluator only.
  Endpoint codecs, capabilities, permissions, request limits, retries and original test
  assertions remain unchanged. The complete affected evaluator module passed 12 tests with
  no skips in 9.409 seconds, including both actual CLI 0.160 methods and all original
  acceptance/rejection assertions. Its implementation, CLI, interpreter and native bytes
  stayed unchanged. Earlier failures remain failures.
- The subsequent complete frozen v4 run passed 1,709 Python tests, with zero failures/errors
  and six conditional skips, plus all 157 Node tests with no failures/cancellations/skips.
  Total elapsed time was 2,285.007 seconds. The frozen 285-file source identity was
  `f0f7b595504e077ebd7ecafff4ae3104b8e9acc8a1a96cc6d45d2310a6ef84da`;
  source, CLI and native configuration stayed unchanged. The exact Operator remained stopped,
  callbacks/inbox were empty, and the owned test processes exited. The six skips retain their
  distinct unmet conditions: three real Windows symlink cases, one explicit catalog path and
  two selected-shell fixtures; no live Desktop gate is inferred from them.
- A fresh reviewed schema-v2 same-version runtime transaction updated 16 code files, retaining
  originals and the native_search absent state, without native configuration changes. A separate
  read-only check confirms all 63 installed code files match manifest and canonical source at
  4.2.0-alpha.138. Legacy first-install ownership remains unresolved. This deployment does not
  establish package-entry or fresh Desktop acceptance.
- Local loopback service startup was confirmed once against the exact application and CLI.
  One model load completed, but the original restoration assertion failed: the SDK load object
  adds an own `gpu.mainGpu=undefined` key absent from saved JSON. All three readback JSON values
  match the originals. A separate read-only SDK review retained the assertion traceback and
  confirmed complete load/prediction equality in JSON, stable model identity, 32768 context,
  parallel capacity four and unchanged defaults. No load was retried and no inference was sent;
  the original failed receipt remains failed.
- The new Web service preflight recorded `web_desktop_locked_before_dispatch`, with zero model
  requests and zero browser launches. Current Windows flags independently reported locked;
  the exact native window showed a black capture and disabled accessibility controls. The cause
  remains unconfirmed. The exact idle service was normally stopped with saved login intact.
  At that locked-desktop observation, the current-package paired entry update, restored side window
  and two prepared different new execution cases remained pending. No challenge requirement is inferred,
  and no native restart, lock bypass or old-request replay occurred. The v4 frozen source artifact
  and receipts remain intact; this later documentation records deployment and the remaining gate.

2026-10-03 unlocked-window follow-up:

- Explicit package-pair maintenance refreshed the isolated entry to official Windows package
  26.930.3930.0, preserving its exact existing home, user-data and legacy originals. A new extension
  process opened with the existing chats; the running native Desktop was retained and native config
  stayed byte-identical. The saved Web page was already signed in; no verification or model probe
  was needed to check that page.
- One different ordinary Local input, RL0310, completed in 53.582 seconds with same-turn natural
  native compaction, one exact CSV read, exit zero, all three data rows, unchanged fixture bytes
  and final `398 RL0310`. The original observer remains failed: its planned-body comparison
  rejects the actual complete request plus one final LF, and its final filter requires a phase field
  absent from this native message. A separate read-only review preserves the complete actual bytes
  and binds the same-turn completed AgentMessage and task_complete. No trim, replay or original
  result reclassification occurred.
- A different new Web input, RW0310, failed after 598.807 seconds with
  `web_browser_final_timeout_no_retry`. Its request stayed consumed. Local transport recorded zero
  context-page reads, calls and results; both fixtures stayed unchanged. The exact cause remains
  unknown; neither zero calls nor an earlier ready state establishes a cloud or login failure.
- One explicit closed-browser replacement retained the same service, endpoint, connection and
  consumed-request ledger. Its empty auxiliary page initially stayed white, then displayed the
  signed-in temporary chat. No reload, GPU change or security bypass occurred; observation timing
  does not establish the cause of that painting delay. The checked empty page was hidden normally.
- A separately prepared, different ordinary Web input, RW0416, completed in 84.787 seconds with
  two paired native commands. They read both new fixtures, changed only the faulty arithmetic
  expression, and ran the specified Python with `-B`. Both native executions exited zero; all three
  tests passed, test bytes stayed unchanged and no cache file appeared. The exact final was
  `34 RW0416`. Early saved browser evidence separately verified GPT-5.6 Sol, generation 5.6 and
  Medium before dispatch. Complete context reads and HTTP 200 are not substituted for these
  actual command/result/file checks. The earlier timeout remains failed, with no retry.
- The final was visibly present after bringing the same extension window forward, without chat
  re-selection or reload. A concurrent computer-use capture showed another task's surface, and
  the accessibility tree still lagged the actual final; those observations do not establish general
  UI stability or exact paint timing. The final saved service state was ready and idle, with current
  source/session binding and the native configuration unchanged.
- These live records do not change the frozen v4 artifact, its six conditional skips or any tested
  implementation bytes. Real approval/denial, native freeform patch, custom exec fidelity, other
  untested models and legacy first-install ownership remain separate gates.

2026-10-03 installed public-status follow-up after the unlocked-window cases:

- A final real comparison found canonical status checked the current bound Web service, while
  the byte-identical installed product helper returned partial with `check_result_invalid`.
  Its inspection invoked the old management filename, which is absent from the runtime inventory.
  The repair keeps the same three internal read-only operations and maps them through the existing
  public `codex-operator.ps1` facade. The installed facade still checks its saved canonical path,
  digest and unlinked parent chain. No legacy alias, control action, fallback or retry was added.
- Three new regressions first reproduced four deterministic failures against the old helper;
  those original logs remain unchanged. The fixed new cases passed, then the complete affected
  product, legacy runtime maintenance and Python runtime modules passed 157 tests with no skips,
  failures or errors in 388.354 seconds. Independent review matched every ordered test identity
  (65 + 80 + 12), the exact 285-file source, saved Python, CLI 0.160.0 and native configuration.
  This later one-file implementation patch and its test change are separate from the full v4 run.
- The extension was normally quit through its own File menu. Closing its window alone had left
  the exact process alive; the guard rejected service stop before any stop action. The original
  process was reopened normally and then quit, without killing or restarting the native Desktop.
  The router confirmed request-free normal stop; a subsequent manager observation confirmed the
  saved Web service stopped. The reviewed schema-v1 maintenance updated only the product helper
  and its manifest, retaining all 2,604 original runtime files and protected integrations. All 63
  installed files match manifest and canonical source; legacy first-install ownership stays unresolved.
- Explicit Web startup returned starting before its ownership binding was saved. A read-only ready
  observation remained unbound, and the first pair preparation rejected that state before creating
  a stage. After checking the same live process, worker and session, explicit start reuse saved only
  their exact binding, with no additional service/browser launch or model request. The original
  rejection remains retained. A new same-package pair transaction then bound this ready service,
  preserving the native config, existing isolated home, chats, registry rows and catalog selections.
- The private entry-open observer failed to decode the launcher's empty output as JSON and stays
  uncertain; it was not repeated. Separate
  retained launch/process records and the current visible window confirmed the extension opened
  on the current official package. Opening its saved chat displayed the earlier `34 RW0416` final;
  no new business turn was sent. Canonical and installed status then both returned checked with
  identical complete reports, current ready/idle Web binding and unchanged native config. The
  later isolated home/config fingerprint changed from its prepared baseline; original baseline
  bytes are unavailable for exact comparison, so the change remains observed and unattributed.
  Route/provider invariants were checked separately; no rollback or CUA-only claim is made.
- The final source package binds the full v4 receipt plus this separate affected-suite receipt.
  Only the product helper and corresponding test differ in implementation/verification from v4;
  later reviewed documentation is recorded separately. Historical packages, failures and login
  remain intact. Approval/denial, native freeform patch, custom exec fidelity, untested models,
  unknown painting/timeout causes and unresolved legacy ownership retain their distinct limits.

2026-10-03 status and public-page integrity follow-up:

- Five completed/terminal Web attempts produced a 67,951-byte observation file, then a
  68,011-byte stopped observation. The ordinary 64 KiB reader rejected both. The exact
  idle service was checked through its authenticated health endpoint before normal
  extension/router shutdown and one explicit Web stop; original bytes are retained.
  New status publication budgets the complete serialized snapshot and omits only the
  oldest whole browser diagnostic events, with an omission count. Other counters,
  request records, context and capacity bounds are unchanged. A dedicated legacy reader
  accepts only the prior writer's exact representation whose complete compact JSON still
  fits 64 KiB; recovery hashes and copies the original bytes without normalization.
- A non-null modern request binding now requires modern completion and fresh-chat checks.
  Mixed or legacy-only page rows cannot downgrade an existing modern binding. A separate
  local fixture reproduced a cancellation race: a page changing after host verification
  could receive the old Stop click. Exact source/user/binding verification and the unique
  Stop click now share one synchronous page operation; post-cancellation idle checks remain.
  Focused page/surface regression passed 157 Node cases. Full and live results are recorded
  separately below when available; these fixtures alone do not prove Desktop acceptance.
- Fresh read-only schema export from CLI 0.159.0-alpha.12.1 confirms supported granular
  approval and distinct permission-request response shapes; the selected granular policy
  is recorded separately in the exact native rollout's `turn_context`. No real approval/denial
  was observed. This Web catalog does not enable native freeform patch; ordinary native
  file reading/editing/testing is a separate acceptance case, not evidence of patch or approval.
- Frozen complete regression ran 1,648 Python cases (30 conditional skips) and 157 Node cases,
  with no failures and unchanged implementation throughout, in 2,277.808 seconds. One earlier
  focused run retained its document-inventory mismatch; that case passed after the inventory
  was synchronized. The final diagnostic-only change preserves `web_service_status_invalid`
  through the manager's exact fixed-code whitelist while still redacting unknown text. Its full
  manager module passed 44 cases on a separately frozen final tree. Only that manager file and
  its test differ from the whole-suite tree; both original receipts and the complete file map remain.
- Before deployment, the native configuration differed from the whole-suite starting digest.
  Two later snapshots matched each other and still selected the built-in OpenAI configuration;
  a dated selection also shows a reasoning preference change. The exact earlier bytes were
  unavailable, so a complete difference and its cause are unconfirmed. Current bytes were retained,
  with no rollback; a new paired-entry preview protects that current configuration. The original
  native process remained alive. This observation does not claim the entire config was unchanged.
- The current saved Web service was explicitly configured, started and bound using the final
  implementation. A fresh digest-bound paired entry refresh completed without native configuration
  writes; the owned extension shortcut opened a new isolated Desktop process with the existing chats.
  A different new file case completed in 70.055 seconds: two actual paired native `exec_command`
  calls read both fixtures, changed only the faulty fee expression and ran the specified Python with
  `-B`. Both executions exited zero, all three tests passed, source bytes exactly matched the expected
  result and test bytes were unchanged. The exact final was visible in the restored extension window;
  accessibility briefly lagged the screenshot. This is ordinary file read/edit/test acceptance only.
- A different new Stop case ended as native `turn_aborted` after 84.425 seconds, with no tools
  or accepted final. Two native UI click attempts were needed: the first coordinate action did not
  visibly stop it; a fresh accessibility-button action did. Saved browser evidence records one
  request-bound `cancel_click_attempted` followed by `cancel_idle_verified`. A different new
  continuation completed in 34.437 seconds with the correct integer and original marker, visible
  in the same window. The same browser birth survived; this instance had three dispatches, two
  completions, one cancellation and zero failures. Its retained cancellation snapshot was collected
  after the continuation, and is labelled accordingly. Native config changed again during this
  period; configuration invariance is not claimed. No cancelled input was replayed.
- The unchanged Huihui 32768 load/prediction configuration was checked independently before
  three different ordinary-composer CSV cases in its existing Desktop chat. The first completed
  in 19.697 seconds, read all 24 rows once and correctly continued the prior successful result;
  native last usage reached 30,455 with an effective window of 31,129. The next ordinary input
  produced one new same-turn native `ContextCompaction` event and a retained `compacted` record
  with complete replacement-history evidence. No manual compact action or threshold override was
  used. That case completed in 76.046 seconds with the correct result; its first tool arguments
  were rejected before execution for an invalid `justification` combination, and a subsequent
  corrected call performed the sole complete CSV read. The rejection remains separately recorded,
  not an approval success or transport retry. A different post-compaction case completed in
  14.162 seconds with one exact paired read and the correct historical integer/marker. All three
  CSVs remained byte-identical, and the final result was visible in the extension window.
  The initial private observer only recognized an older terminal-output envelope, yielding a
  retained false file-read classification for the first case. The observed current `Output:`
  envelope and exact native command/result evidence were reviewed separately; original evidence
  is not rewritten. These cases establish this model/configuration's observed natural compaction
  and continuation, not every model, context or tool. Approval/denial and native freeform patch
  remain unverified.

2026-10-02 later current-window visual review:

- After a prior retry displayed the Windows lock screen, a different current capture showed the
  exact recovered extension window. Its saved search answer, both official links and expanded
  native search execution row were visible. The black/lock-screen capture cause remains unconfirmed;
  no privacy settings, login, routing or service lifecycle was changed by this review.
- One different new ordinary-composer continuation completed in 28.853 seconds and returned the
  correct integer and original marker. The final was visible without re-selecting or reloading the
  chat. The accessibility snapshot temporarily lagged the visible result; closing the model menu
  with Escape showed the exact final, empty composer and Send control with no Stop. Native completion
  duration is not a first-token or exact visual-paint latency measurement.
- The same source-bound browser remained alive with one launch, five dispatches, four completions,
  one retained cancellation and no failures in this instance. At that checkpoint, implementation matched
  the frozen 417 Python / 152 Node run. The nine prior acceptance receipts and their native history
  byte prefixes remained unchanged, as did native configuration and both existing Desktop process births.
  This dated visual case does not establish general UI stability, approval, freeform patch,
  automatic full-capacity compaction, other models or legacy runtime ownership.

2026-10-02 follow-up after the update closed the extension window:

- Current public rendering unmounts the user unit and bubble while showing the assistant. Its user
  and assistant identity lists are separate role turns; neither user membership nor the user's entire
  ID prefix binds the assistant. The current ancestor render list also contains only the mounted role.
  Five different diagnostic cases remain cancelled with closed workers; none was replayed.
- The fresh-document candidate admits an empty page, binds the original full source and public user
  identity, and monitors public user/document changes. Its first live case terminated in 13.955 seconds
  at capture with `web_page_state_timeout`, with one dispatch, no tool and no final. The next candidate
  treats the renderer's conversation key as an exact bounded opaque key, arms after model selection,
  and exposes only fixed binding booleans. These changes require new independent live evidence.
- Before that later key/diagnostic change, frozen complete Web regression passed 417 Python cases and
  all 145 Node cases in 380.981 seconds, with unchanged source. It does not reclassify the live failure.
  The next complete run passed 417 Python and 146 Node cases in 374.100 seconds, with unchanged source;
  its different live case still failed capture in 14.263 seconds. Diagnostics established exact source,
  user and document/root with a conversation field outside the assumed UUID/simple-key format.
- The final temporary-document path preserves an exact opaque string up to 128 characters, rejects
  control characters/accessors/nontext fields, and permits an explicit empty field only on the checked
  temporary route. It retains the original user UUID/source, one-request nonce, document/root and
  mutation fences; the field alone never supplies identity or authentication. Its complete frozen run
  passed 417 Python and 147 Node cases in 369.753 seconds, with unchanged implementation throughout.
  New ordinary Desktop text returned the correct integer in 11.749 seconds; a different same-chat
  continuation returned the correct new integer and original marker in 15.924 seconds. One browser
  worker remained alive, with two dispatches, two completions and no failed/cancelled turns in that instance.
- A new file case completed in 33.624 seconds with one exact native `exec_command`/result pair,
  a zero exit status, the expected fixture contents and correct arithmetic/history/fixture markers.
  The fixture stayed byte-identical. A different native Stop case was interrupted after 136.328 seconds,
  but the thinking unit had no final selection marker; page binding rejected and its worker closed.
  That cancelled request remains terminal. The next repair separates public assistant-unit identity
  from readable final-message content for cancellation only; it cannot return a pending answer.
  Its affected suites passed 48 Python and 148 Node cases. Its complete frozen run then passed
  417 Python and 148 Node cases in 386.432 seconds. A different fast live continuation left the
  document armed but unbound: the user vanished between source reads and a later controls snapshot.
  It was cancelled from the native window after 446.866 seconds, without a final or worker retention.
- Atomic dispatch capture now compares the complete source, checks the selected app projection,
  obtains the user identity and binds the document in one synchronous page evaluation. It rejects a
  managed modern dispatch without that binding before waiting for a final. Affected checks passed
  87 Python and all 152 Node cases. A different native continuation completed in 19.412 seconds with
  the correct integer and original marker while its user row was absent; the current binding stayed
  exact and its worker remained alive. Complete frozen Web regression passed 417 Python and 152 Node
  cases in 369.416 seconds, with unchanged source. A different thinking-stage native Stop interrupted
  its exact turn in 66.827 seconds; the Web side clicked Stop once and confirmed stable idle without
  closing the worker. A different new continuation then completed in 22.962 seconds with the correct
  integer and original marker. The same browser process birth predates all three cases; its saved
  lifecycle records show one launch and no replacement. Cancelled inputs remain terminal.
- A different new native search completed in 52.263 seconds. Its one actual search call contains the
  current request's two `pathlib` methods and official-domain restriction; the identity-paired result
  includes the supporting Python documentation. The final answer and two official links match those
  results. Re-selecting the current chat as a read-only view showed the answer and links in native
  accessibility state, with an empty input and no Stop. Screenshot capture was black for that running
  window; immediate visual painting is not attested by the persisted result or this accessibility review.
- A failed paired refresh retained a may-have-written pending transaction and all originals, while
  every current installed byte matched the validated old baseline. Explicit digest-bound rollback
  review preserved the failed stage and pending transaction and wrote only cross-bound review receipts.
  The old transaction was never reapplied. Different new paired refreshes completed normally, with
  the same home, old receipt chain and unresolved legacy runtime ownership. No original history,
  native configuration or native shortcut bytes were rewritten.
- The complete frozen maintenance run passed 54 cases in 641.709 seconds. It covers original-file
  retention, changed/missing rollback material, later edits, live-process rejection, actual PowerShell
  receipt reading and unchanged locked files. Identical installed files keep their entity while still
  receiving complete transaction backups. Running-native process identity remains a separate check.

2026-10-02 backend acceptance and official-update recovery:

- On Desktop 26.928.3736.0 / CLI 0.159.2, Huihui passed fresh text and same-chat continuation,
  three paired terminal calls and five file tests. A different manual-compaction case retained complete
  replacement history, then read only a new fixture and correctly continued its prior number/marker.
  One native argument rejection before the corrected execution remains in that case. A separate
  intervening Local HTTP 500 remains failed and unattributed; approval and freeform patch are unverified.
- Web GPT-5.6 Sol/high returned the correct 43-line final answer in 12.140 seconds. Its later
  continuation was cancelled by an actual native Stop click. The bridge recorded cancellation,
  but could not bind its page Stop and closed the worker; stable retained-browser reuse did not pass.
  The earlier 598.579-second browser-final timeout remains failed with no business calls or final.
  New inputs and explicit closed-browser recovery never replayed those originals. GPT-6 Pro is excluded
  following the owner's quota report. Search, full-context understanding and other model entries remain
  separate live gates, not inferred from HTTP 200 or a context-read count.
- The owner's official update installed package 26.930.2377.0. The actual native and recovered
  extension App Servers use CLI 0.159.0-alpha.12.1. The old extension has a genuine normal exit;
  the vanished router has a separate digest-bound absence review, with no fabricated clean-stop record.
  The explicit paired package update retained original entry bytes, historical receipts, native
  shortcuts and the same chat home. The actual new extension window restored its chat list and selected
  Web model while the owner's running native window and configuration stayed unchanged by this work.
- On the updated package, the same Huihui weight and complete load/prediction settings were restored;
  context remains 32768 and parallel remains four. The `lms ps` observation woke the service and is
  recorded as a side effect. One pre-restoration transport failure and one post-restoration reasoning-only
  capacity failure remain failed. A new actual manual compaction completed in 25.557 seconds, then a
  different new file case completed in 32.006 seconds with one successful native read and the correct
  continuation of the last successful number/marker. Failed-turn additions were not incorporated.
- Updated-package Web search completed two exact paired native tool calls but returned no final answer;
  the 598.759-second browser-final timeout remains failed. A different Sol/medium turn was cancelled by
  one actual native Stop click. Initial public-text binding was exact, but Stop revalidation returned
  `web_cancel_user_binding_required`; its worker closed and stable retained-browser reuse did not pass.
  The page's precise identity failure cause is not established, and no check was relaxed. Explicit
  empty-browser recovery and current-page review reached ready/idle after the owner completed verification.
  No cancelled or failed input was replayed. Readiness never reclassifies the original cases.
- The package/recovery checks passed 17 Python maintenance cases, 21 existing entry cases (one symlink
  skip), and six real PowerShell pair cases in disposable folders. Package changes after preview,
  unlabelled rebinding, altered native settings, live old processes and modified retained records reject.
  Nine separately enabled current-CLI fixtures passed in 5.723 seconds, including paired historical
  functions with an empty current tool catalog, standalone search and manual/automatic compaction.
- Before this update repair, one complete frozen-source run passed 1,624 Python cases (30 skips) and
  all 134 Node cases, with unchanged source throughout. The new package/absence implementation passed
  its separate complete frozen-source run: 1,632 Python cases (30 skips), all 134 Node cases, zero failures,
  unchanged implementation throughout 2,072.182 seconds. The earlier result retains its original binding.
  Native process birth, both actual windows and unchanged native configuration were separately rechecked.
  Approval, freeform patch, automatic full-capacity Desktop compaction and all models/tools remain unverified.
  Packaging is local preview only, with no external publication or claim that every live gate passed.

2026-10-02 isolated native/extension entry implementation:

- Current Windows package 26.928.3736.0 and CLI 0.159.2 have separate native and extension homes,
  userData and windows. The original native process remained running; its configuration stayed
  byte-identical. Exact local onboarding initialization reached the ordinary empty chat UI without
  role selection, consent, login copying or permission changes. Unknown builds retain official onboarding.
- Six custom entries appeared in the actual conversation menu. Four new turns in one extension
  chat passed: GLM text, DeepSeek history continuation, a real standalone `web.run` with paired official
  documentation results, and return to GLM after that tool history. Native turn metadata confirms the
  actual model IDs. GLM used low; DeepSeek metadata used none despite a medium-looking UI label.
- The earlier hosted-tool rejection is retained. Local current-CLI fixtures reproduce that declaration
  and verify standalone search plus credential isolation. Official search credentials stay restricted
  to the fixed official endpoint and are never copied to the extension or sent to model providers.
- A separate service `http_connect` transport failure remains unattributed by the bounded diagnostic
  counts. Do not label it a title failure, replay it, or erase it because the four selected turns passed.
  Local model/Web backend operation, all tools, long contexts and universal Windows/package-version
  support are not established. The package helper's documented debugging/token limitations remain.
- The reviewed paired shortcut is installed. Actual extension-link launches passed cold extension
  startup, the native button, and same-process extension foreground reuse. Both the picker and outer
  launcher exited while the service remained alive. Actual native-shortcut double-click returned to
  the unchanged original native process. A background shell launch that did not foreground native is
  retained separately; it is not treated as the user-click case.
- A prior foreground denial and an unwritten entry-lock denial remain failed. Narrow stopped reviews
  retained their exact originals; bound pair refresh updated both the isolated entry and legacy
  ownership chain without changing native link bytes, configuration, login or chat history. No failed
  model request was replayed. Disposable pair refresh also passed restoration of the legacy pair.
- The earlier full run finished with 1,588 Python cases: four failures, one error and 29 skips;
  all 134 Node cases passed. The five Python failures were stale fixtures (four still expected Explorer
  activation, one omitted explicit router diagnostic fields). After correcting those fixtures, the
  final six-module run completed 50 cases in 107.456 seconds, with 49 passes and one environment-dependent
  symlink skip. This includes actual Windows pair refresh and a background-child lifetime test. It is
  a targeted final regression, not a claimed fresh full-suite pass. Source packaging checks remain a
  separate gate.

2026-09-29 follow-up to the Web-service incident and unified-picker candidate:

- A one-shot, pre-initialization recovery retained the failed Web launch record
  after verifying its process had exited, its state/session had never been
  created, and its dependencies were absent. The saved service was configured
  with the project interpreter, explicitly started, then observed ready and idle.
  The independent Desktop Web provider was rebound to that generation, and the
  running API/Local router reported the matching bound Web generation. No model
  request was sent by this maintenance. See the
  [recovery contract](../../models/web/docs/web-preinit-recovery.md).
- After that maintenance, one new synthetic short-text request to the bound
  `api/chatgpt-web/gpt-5.6-sol` route completed over local HTTP in about nine
  seconds and returned the exact requested marker. The router then reported
  ready, idle and Web-bound. This verifies one live basic text path through the
  current service; it does not verify Desktop menu selection or task switching.
- The reviewed [unified cold-launch consumer](../../models/common/docs/unified-cold-launch.md)
  now calls the Windows config replacement witness in disposable tests. The
  real home remains on the official native route with its recovery marker; no
  real cold launch, main-window picker selection or same-task mixed-provider
  turn has been accepted. The explicit unified retirement path has since
  passed disposable recovery tests for prepared, armed and witnessed plans;
  an uncertain attempt still blocks uninstall. No real retirement or Desktop
  acceptance is inferred from those tests.
- The owner approved a one-time adoption of the previously edited Desktop
  `Codex拓展入口` shortcut. Its current bytes matched the retained September 19
  review copy; the adoption saved a private backup and receipt without changing
  either shortcut. The entry-only config upgrade then selected the reviewed
  unified startup workflow. Read-only checks confirmed exact shortcut ownership
  and that the running Desktop would open its existing window. A new real
  unified activation plan is `prepared_not_armed`; the native-route-only marker
  and official direct configuration remain intact. Desktop subsequently wrote
  new bytes to its model cache, so the original prepared plan is stale and
  cannot be released or armed. A new explicit prepared-only supersede path now
  retains that plan and its exact files in a witnessed archive before a fresh
  preparation; incomplete archive attempts block reuse. Its ten disposable
  tests pass, but no real supersede has run. The recovery/retirement/entry
  integration passed disposable tests and the 226-file release audit; no live
  cold launch, picker click, same-task switch or voice call has passed yet.
- The first live Desktop-exit handoff timed out with a retained review result.
  The second started but disappeared without a result or stage event when the
  Desktop was closed; the owner had to reopen it manually, and the first manual
  login failed before a later launch succeeded. The native-route-only marker
  remained, but Desktop rewrote its Computer Use pipe-location value; the old
  plan is still prepared and its whole-config digest is now stale. The missing
  result does not prove exactly why the runner exited, and the login failure has
  no demonstrated relation to routing. The launcher now requests a detached
  Windows process group, witnesses startup, refuses duplicate or uncertain
  launches and writes a bounded waiting heartbeat. Prepared-plan supersession
  accepts only that exact scoped value-line change, retaining the old copy and
  binding the refreshed config through preview and post-move checks. Other
  changes remain blocked. Independent process survival was probed without
  closing the live app; the repair has not yet run a real cold launch.
  The old plan's exact router process is also absent and port 4317 is free.
  Read-only preparation reports `unified_router_service_unverified`; the
  handoff preflight now refuses this state without creating another run.
  Router `start` now uses the same detached Windows process boundary. An
  isolated empty router survived its launching command, reported the same PID,
  then accepted authenticated stop and released its port. The real router was
  not restarted, and the prepared plan remains blocked pending a separately
  reviewed recovery of its stale service binding.
  A successful real cold launch, picker click, same-task switch and voice call
  remain unverified.

2026-09-29 native-picker implementation candidate, still inactive:

- The mixed registry now publishes one checked Web service generation alongside
  untouched native and registered API/Local rows. It rejects duplicate or
  mixed-generation Web rows. Its provisional per-route 16k admission budget is
  not advertised as any Web model's verified context window. Current CLI
  `model/list` accepted native, API and three Web rows in an isolated home.
- The router accepts an exact token-bound `/backend-api/codex` alias. Loopback
  tests preserved native Responses, search, image-generation/edit payloads
  and native WebSocket traffic through it, rejecting other endpoints. A
  current-CLI synthetic task listed native-shaped and Web model rows in one catalog,
  switched its next input to the Web slug in the same task, and reached the
  corresponding local fixture. That fixture did not run ChatGPT Web.
- With a synthetic API key, a separate custom `OpenAI`-named provider used the
  alias for the native search tool, fetched the model catalog through
  `model_catalog_url`, and sent exactly one upstream 413 request with both
  retry settings at zero. The built-in `openai` provider sent six HTTP POSTs
  on a comparable isolated 413. A synthetic ChatGPT login failed in workspace
  discovery with 401 before reaching the local router. A separate fresh CLI
  App Server using the current signed-in home and process-local provider
  overrides completed only `initialize` and `model/list`: the loopback catalog
  saw Authorization present and the synthetic row appeared. It sent no model
  turn. This also unexpectedly replaced the real model cache with the probe
  catalog; a later read found nine ordinary models and no probe row, but no
  original digest was saved to prove byte identity. No manual cache restore was
  attempted. Desktop authentication and picker behavior remain untested.
- New managed global-entry preparation pins both WebRTC call creation and
  realtime WebSocket voice to the official address, preserving an existing
  identical user setting and rejecting a conflicting setting before writes.
  Existing three/four-line entry journals remain removable, but cannot be
  reaccepted as fully voice-protected when either pin is missing. Cross-review
  caught and fixed the emergency-recovery case of a new active block followed
  by the one permitted inert commented legacy block; the original comments
  remain byte-for-byte after recovery. No real voice request or global
  activation was performed; both Codex override fields are experimental.
- The standalone recovery source now recognizes the exact unified candidate
  prefix and provider table, removing only those owned bytes while retaining
  an inert legacy comment and later independent tables. Its 15 disposable
  Windows PowerShell tests passed. The owned installed recovery shortcut and
  script copy were updated through the retained-original installer; read-only
  inspection confirmed the current Desktop location, target, working directory,
  empty arguments and source match. This changed no route configuration. The
  real native-only marker remains in place.
- A disposable-home unified provider candidate now has a journaled,
  reversible configuration transaction. Its generated config was parsed by
  the current CLI and listed both synthetic native and Web rows through a
  local catalog with no model turn. It cannot apply to the real Codex home;
  startup and uninstall do not yet own it. The updated recovery shortcut can
  remove only its exact block and is not activation ownership.
  Existing native tasks remain bound to their prior provider. Focused review
  found protected-home, cache and concurrent-journal races; all were fixed,
  and the candidate's 18 focused cases passed. See the
  [candidate contract](../../models/common/docs/unified-picker-candidate.md).
- Read-only unified-entry inventory checked the real home without starting a
  model or changing configuration. After the recovery shortcut update, the
  retained native-only marker and old Web activation record blocked the
  candidate. The old record was version 1/activated with no active entry journal;
  the old Desktop entry was native and its router receipt said stopped. Current
  Web-startup status instead returned `web_startup_runtime_changed`, so those
  observations alone did not authorize deleting the old record. A forged
  recovery receipt plus an arbitrary same-named file was found and fixed in
  the preview: Windows now verifies the current Desktop shortcut target,
  working directory and empty arguments. Its ten focused tests passed.
- An independent one-shot retirement compared the old plan and original config
  hashes, installed native entry, old process birth identities, exclusive old
  router port and complete file snapshot. Its ten disposable tests passed;
  the terminal status also rejects later changes to every journaled historical
  workflow, registry, token and profile file.
  A fresh real preview returned `ready_to_retire`; the exact three digests were
  supplied to `retire`, which preserved the original activation bytes in a
  private backup, archived the active record and wrote a terminal receipt.
  Read-only follow-up reported `retired`, the real config digest was unchanged,
  and unified-entry inventory now reports only the native-route-only lock.
  No service was restarted, no route was enabled and no model request was sent.
- At this checkpoint, the separate Windows config replacement primitive was
  still unconnected to activation. Its eight temporary-directory tests passed,
  including 20 deterministic rename races and a process exit after the native
  replace.
  It retains both the reviewed original and the file replaced at the native
  boundary, checks their bytes and file identities, and reports uncertainty
  without retrying. It has not modified the real Codex config. See
  [transaction limits](../../models/common/docs/windows-config-transaction.md).
- During explicit idle Web-service maintenance, I ran `configure` with the
  system Python rather than the saved project interpreter. The new source
  profile was accepted, but its first `start` child exited before creating a
  state/session directory because that interpreter lacks `aiohttp`. The
  resulting launch record is `uncertain`; no second start was attempted.
  Read-only inspection found the saved process dead, the new state absent,
  the fixed connection available and saved dependency processes absent.
  The previously saved project interpreter imports `aiohttp`. At that point,
  this was a Web-service availability regression until an explicit reviewed
  recovery retired the failed pointer and restored the correct interpreter;
  it is not a model-turn or login failure.
- Uninstall preflight originally scanned raw configuration bytes for the
  candidate marker. A valid TOML Unicode escape could hide the parsed provider
  identity and bypass the stop. It now checks both raw managed markers and the
  parsed provider selector/table; 20 uninstall and 13 installation tests passed.
  The isolated candidate writer still has a race between its last snapshot
  read and file replacement when an unrelated editor writes concurrently.
  That writer remains disposable-home-only and must not be promoted to real
  activation. No live Desktop picker or voice test was performed.
- The opt-in common suite passed 319 cases with 3 skips using current CLI
  0.158.0-alpha.2.1 and the project interpreter. The affected configuration,
  emergency recovery, uninstall and cold-start tests passed 77 cases. All
  134 browser Node checks passed. These isolated results do not establish
  the actual Desktop menu, ChatGPT login reuse, or normal voice. Official
  native traffic remains direct and its recovery lock remains in place.

2026-09-29 basic Web text path after explicit service maintenance:

- The saved Web service was initially ready and idle, with a bound session and
  unchanged settings, but its source registration differed from three current
  model-catalog files. One fresh direct-provider GPT-5.6 Sol/Instant request
  asked for a short text answer without tools or search. It returned the fixed
  local HTTP 400 `web_browser_driver_failed_no_retry` envelope (cause 502).
  The browser recorded one attempt, zero generation dispatches, zero tool calls,
  no public final answer and a closed worker. Its only failure event was the
  generic `driver_failed/rejected`; neither a login challenge nor the specific
  rejection stage was observed. This failed input was not replayed.
- The old instance was then explicitly stopped. Its saved settings and process
  ownership were checked, the source registration was updated while stopped,
  and a new service was started, bound through explicit reuse and reconnected
  to the existing independent Desktop provider. A **different** fresh direct-
  provider GPT-5.6 Sol/High text request returned HTTP 200, the exact requested
  marker and the selected model slug. The new service's request count increased
  once, no tool call was released, a public final answer was recorded, and the
  same instance returned ready and idle. This verifies the managed provider's
  basic text path only; it does not establish an existing Desktop task's route,
  same-task model switching, voice, or complex tools. The before/after result
  does not isolate source drift as the first failure's cause because the effort
  and browser instance also changed. Official native routing remained direct.
- A fresh App Server task then sent one short text request with an explicit
  no-tools/no-search instruction. It failed with local 502
  `web_mcp_context_not_read`: none of its three context pages was read and no
  native tool call was released. A different, app-native follow-up failed before
  browser dispatch with 503 `assistance_pending` after the inspection preview
  was explicitly opened; no current login requirement was established. These
  failed turns were retained and not replayed. The idle service was explicitly
  stopped, configured from the same saved settings, restarted and rebound.
- The Web composer guidance now identifies `operator_begin` as a required
  read-only transport step even for a request that forbids task tools or search.
  It does not grant a business tool call or relax complete-context checks;
  [44 focused driver tests](../../models/web/tests/test_web_browser_driver.py)
  passed. A **new** App Server task on the recovered service answered `17 + 25`
  with the exact `42`, using the intended Web provider and no business tool
  call. An app-native message to that same task returned `50` for the next
  arithmetic prompt, but also issued one unwanted
  `codex_app.send_message_to_thread` call to the originating task. That second
  result is therefore not clean no-tool acceptance, and neither task-tool
  delivery proves ordinary Desktop composer entry. The service returned ready
  and idle; existing failed turns were not retried.
- A separate fresh task bound to the exact independent Web provider and
  GPT-5.6 Sol/High completed two App Server `userMessage` turns: the first
  answered `19`, and the second referred to it and answered `25`. Native task
  history showed only paired user/agent messages and no `mcpToolCall` in either
  turn; the service ended ready/idle with zero accepted, released or returned
  business calls and a final answer. This verifies two-turn Web provider
  protocol continuation, not ordinary Desktop composer input.
- The owner then authorized Computer Use for a fresh ordinary Desktop composer
  check in that exact task. The
  visible window showed the prior `19` and `25` turns. One new composer message
  asked to add 11 to the preceding final answer; the same window displayed the
  submitted message and `36`. Native history recorded one new completed
  `userMessage`/`agentMessage` turn
  with no tool call. Its turn context selected
  `api/chatgpt-web/gpt-5.6-sol`/High, and the session remained bound to
  its independent Web provider. Local Web status returned ready/idle,
  `session_bound=true`, `configuration_current=true` and zero accepted,
  released or returned business calls for the last turn. This verifies the
  basic same-task text path through the visible Desktop composer; it does not
  establish fresh-task model selection from the main picker, native voice,
  file tools or long-running requests.
- A subsequent read-only native catalog check showed the Web provider registered
  while its model was absent from `model/list`; the official native provider
  remained the default. In that task, the visible `自定义 高` control opened a
  reasoning-strength slider, not a provider picker. No model selection or
  configuration change was made. Fresh-task model choice remains a separate
  usability gap despite the working bound-task text path.

2026-09-28 native model onboarding and remaining fixes:

- Follow-up review found the native `prepare` summary lacked the model ID,
  bound Codex home and original-file presence required by its own guide.
  `prepare`, repeated preparation, `status`, `install` and `restore` now give
  those validated, non-secret identity fields without exposing the endpoint or
  key reference. API and Local preview tests check the fields and no target
  writes. This changes no saved plan format or installed profile bytes.
- The correction passed 86 focused cases and a full regression of 1025 Python
  cases (1015 passed, 10 existing skips) plus all 134 Node cases. An initial
  focused run used system Python without the project's Web dependency and ran
  before reviewed-document hashes were synchronized; both harness conditions
  were corrected before the passing runs. A second reviewed legacy maintenance
  transaction changed only `operator_native_models.py` in the stopped real
  runtime. All sixty-two installed code hashes and the startup Hook matched;
  Channels returned to full readiness. The saved Web service was explicitly
  started, reused once to register its ready worker, and rebound to the same
  independent provider without sending a model request. Desktop adoption of
  that new Web service generation remains unverified.
- Read-only native protocol schema at CLI 0.158.0-alpha.2.1 confirmed that
  `model/list` has no per-model provider and `turn/start` has no provider
  parameter. `thread/start.modelProvider` starts a separate task. These gates
  prevent claiming a mixed-provider main-window picker from the seven installed
  file profiles or from a combined catalog alone.
- A suspected Web v3 scalar-input schema mismatch was disproven by an offline
  emitted-page check. The complete page entry's outer `value` is always a record
  object, as the output schema requires; a scalar `request.input` stays unchanged
  inside that record's `input_value.value`. The observed 1/14 failure also used
  array input. No tool declaration or installed app snapshot was changed.
- An opt-in isolated App Server test on CLI 0.158.0-alpha.2.1 sent two models
  through one fake loopback Responses provider in the same task and observed
  the exact selected slug at each new user request. Codex sent a checkpoint to
  the old model before the switch; a synthetic 413 made one upstream dispatch
  with both custom-provider retry settings at zero and kept its failed turn.
  This proves neither real mixed-provider Desktop switching nor global routing.
- A second opt-in test used the current `ModelRouter` between that disposable
  App Server and separate fake native/external endpoints. The same task completed
  both model turns, retained history and a distinct failed 413 turn, and routed
  each new input to the selected endpoint with its own synthetic credential.
  Native token-usage events reported effective windows of 32000 and 15200 for
  catalog rows set to 32000 and 16000 respectively. The targeted suite passed
  two cases with one optional catalog case skipped; all 53 router tests passed.
  This does not establish actual Web model limits, official-provider 413 retry
  behavior or live Desktop rendering. The owner rejected a separate same-UUID
  App Server wrapper because Desktop cannot display its execution process;
  that route was stopped and no wrapper was added.
- A later [isolated CLI 413 probe](../../models/common/tests/test_native_official_413_cli.py)
  used one new failed turn per condition, a disposable home with a fake API key,
  and only loopback Router/upstream fixtures. CLI 0.158.0-alpha.2.1's built-in
  `openai` provider sent **six HTTP POST attempts** for an upstream 413 plus
  seven separate WebSocket handshake attempts; the handshakes are not model
  executions. A local Router capacity 413 likewise caused six HTTP attempts
  but zero upstream POSTs. Both failed turns remained in native history; no
  request content was retained by the probe. Under the same fixtures, an
  explicitly configured custom provider with `requires_openai_auth=true`,
  `request_max_retries=0`, `stream_max_retries=0` and HTTP-only transport sent
  one POST per 413 condition, zero upstream POSTs for the local rejection, and
  retained both failures. That result covers only fake API-key authentication,
  not the owner's Desktop ChatGPT login or plugin connection. [Official config
  guidance](https://learn.chatgpt.com/docs/config-file/config-advanced#azure-provider-and-per-provider-tuning)
  says the built-in `openai` ID cannot be overridden with a provider table;
  its supported `openai_base_url` override does not expose those retry knobs.
  Native global routing remains disabled; changing 413 to a 400 is not an
  authorized repair for native or other upstream errors.
- Explicit API/Local file profiles now have preparation, installation, read-only
  status and exact restoration. They preserve base configuration and reject
  unknown existing target files and base-provider name collisions. Independent
  native checks reproduced both old-header inheritance and permission loss when
  those conflicts were not rejected. The new workflow is documented only in
  [native model onboarding](../../models/common/docs/native-models.md).
- Independent fixtures reproduced two ownership faults: concurrent transactions
  could both claim one profile, and restoring a failed first install could remove
  a later transaction's identical files. Installation/restoration now serialize
  the exact home/profile and retain a state-bound claim after uncertain writes.
  Only its original interrupted transaction can use that claim for explicit
  recovery. Complete old installation receipts remain compatible; old interrupted
  receipts without ownership evidence stop for review. Twenty-two focused cases
  cover those races, later lock edits and partial restoration.
- Seven profiles were installed in the real Codex home: five local models plus
  DeepSeek Flash and GLM-5.3. Each generated catalog passed an isolated native
  `config/read` and `model/list` check. A separate temporary profile completed
  the public prepare/install/status/restore workflow in that same home, removing
  only its two files. Base configuration was byte-identical; the official default
  stayed OpenAI with nine catalog entries, seven visible. This is independent
  profile support, not the Desktop main-window mixed-provider picker.
- New isolated native CLI read-only cases passed for `deepseek-flash`, `glm-5.3`,
  `gemma-4-e2b-it@q4_k_m`, `zai-org/glm-4.7-flash`,
  `qwen3.6-27b-neo-code-here-2t-ot` and `huihui-qwen3.8-27b-abliterated`.
  Each executed one exact displayed read command, returned the complete file
  marker and preserved the fixture hash. `qwen3-0.6b` made no tool call and
  returned only the marker prefix: that case failed despite CLI exit zero.
  All cases were sequential, with no automatic request retries. API credentials
  stayed in the scoped CLI environment; model-launched shells did not inherit
  them. These guided single-read cases prove neither write/search/multiround
  capabilities nor Desktop acceptance; model labels remain unverified overall.
- Two earlier acceptance-harness stops remain failed: a native development
  warning was misclassified as a tool, and Windows parsing was incorrectly used
  on Codex's POSIX command-display encoding. Offline checks corrected the harness
  before new fixtures were used. Earlier completion and dispatch uncertainty
  are retained; the native request and command text were not rewritten. See the
  [command evidence boundary](../../models/common/docs/responses-acceptance.md#native-cli-command-display-2026-09-28).
- Native metadata cancellation can bind an explicit non-default Codex home;
  the read-only child alone receives it. Desktop writes reject a mismatched home.
  Source and isolated tests cover the binding; the live service keeps its
  already configured default home.
- Fresh installation omitted the metadata observer despite the release package
  containing it. An isolated installed-directory import reproduced the failure;
  copy and hash inventories now include both the observer and native-model entry.
- The actual old runtime and startup Hook still listed sixty files, so adding
  the two dependencies also exposed a legacy upgrade rejection. A separately
  reviewed schema 2 supports exactly that pair with absent-before records and
  changes only the startup Hook's literal inventory. Original bytes and all
  other integrations remain protected; this does not establish first-install
  ownership. Normal upgrade/restore and independent failure injection passed;
  the maintenance contract is in [installation and removal](../../shared/docs/installation-and-removal.md#reviewed-legacy-runtime-cutover).
- The reviewed cutover was then applied once to the actual stopped installation:
  seventeen code files changed, all sixty-two installed hashes and the startup
  Hook hash matched, and the complete original runtime was retained. Channels
  restarted with every readiness gate passing. This maintenance still does not
  resolve historical first-install ownership for general uninstall.
- One authorized user CLI `/model list` then received the exact bot's unique
  reply in 3.68 seconds. Its seven official models and full-ID/default-effort
  example matched the current catalog. The control event completed with no
  model turn, relay or business callback; the existing binding and selection
  were unchanged. API/Local profiles are not exposed through this official-only
  Channels selector until native provider switching is verified.
- The earlier 12-page read failure below was subsequently confirmed by retained
  MCP endpoint events as a local `web_mcp_read_key_unavailable` rejection. Its
  exact key category remains unknown. New fixed-category counters distinguish
  invalid, consumed and unknown keys without retaining request data in diagnostics.
- After explicit idle deployment, a new native task-tool message completed two
  sequential file reads and returned both markers in 59.2 seconds. Both commands
  exited zero; the two source files remained unchanged. The bridge observed
  13/13 context pages, one relevant catalog page, one schema and two paired
  calls/results, with one hidden browser dispatch and no replay. This is a new
  success, not a reclassification of the earlier failed input or a full manual
  composer/Stop verification.
- A subsequent service-maintenance check failed: for a new native task-tool
  request, the local endpoint consumed page 1/14 and prepared its reply, then
  received no second read or native tool call before the webpage finished.
  `web_mcp_context_not_read` correctly rejected the incomplete result; the new
  fixture remained unchanged. The request was not replayed. Saved login and the
  provider registration remain intact, but this prevents claiming a reliable
  long-context Web workflow from the earlier two-read success alone. Complete
  endpoint events contain no read rejection; the initial RPC body and public
  final text were not retained, so neither remote delivery nor the stopping
  cause can be established. No local defect, network cause or login requirement
  was confirmed; the complete-context gate remains unchanged.
- A later distinct native request on that same task failed at 4/14 pages in
  21.5 seconds, with zero native tool calls and no file write. Each of its four
  indexed replies reached local socket `write_eof`; no fifth read or local
  read-key rejection occurred. The selected Web model/effort matched the prior
  13/13 success (`gpt-6-pro/max`). Its browser recorded one dispatch, a model
  response starting with HTTP 200, and a completed public page, without a
  recorded network or page error. The successful 13/13 case and this failure
  both initialized an MCP session for each tool call, so session churn did not
  distinguish them. Local writes and HTTP 200 do not establish cloud receipt,
  model comprehension or a reason for stopping. The complete-context rejection
  and both original failed turns remain unchanged. A separate 14-page synthetic
  request failed before any page read with a generic browser-driver error, so it
  did not test long-page comprehension; an explicit stopped restart and rebind
  restored the saved service to ready/idle with its connection intact, without
  replaying any request.
- The real Web task's `task_started.model_context_window` was 258400 in the
  13/13 success and both later failures. No global model catalog or window
  override was configured, and the task's project had no config. Current Codex
  [fallback metadata](https://github.com/openai/codex/blob/rust-v0.158.0-alpha.2.1/codex-rs/models-manager/src/model_info.rs)
  gives unknown slugs 272000 tokens with 95% usable, explaining 258400. A
  local-only temporary-home/App Server probe with the same Web slug reproduced
  258400 without a catalog; a global 16000 Web catalog row produced 15200.
  When the App Server started outside a trusted project's directory, its
  project-level catalog left the task at 258400 and absent from `model/list`.
  A trusted project's `model_context_window = 16000` or a new task's equivalent
  start override instead yielded 15200 effective; setting that override on
  `thread/resume` for an already loaded UUID left its next turn at 258400.
  Codex's [same-version model metadata](https://github.com/openai/codex/blob/rust-v0.158.0-alpha.2.1/codex-rs/protocol/src/openai_models.rs)
  computes a default auto-compaction limit from 90% of the declared window,
  but no compaction event occurred in these short synthetic probes or the
  retained real task. Neither task-scoped setting proves live Desktop adoption
  or compaction. The long history may contribute to page growth; it does not
  prove the 4/14 stop cause. A Web-only global catalog would omit official
  models and was not installed.
- The current source checkpoint passed 1030 Python cases (1019 passed, 11
  skipped) and all 134 Node checks. The opt-in same-task native fixture passed
  separately. These are source and isolated protocol results, not renewed live
  long-context acceptance.

Final source regression passed 1023 Python cases (1013 passed, 10 existing skips)
and all 134 Node cases. The first expanded run retained eleven failures from an
obsolete runtime-file-count assertion; its fixture now checks both new required
files and exact migration sets. Ownership and interrupted-recovery guards remain.
Windows junction rejection also covers Python versions without `is_junction`;
an actual reparse-point fixture failed before the fix and passed afterward.

2026-09-28 global product follow-up:

- `/model list` now derives its example from an exact currently selectable model
  ID and supported default effort. Two Luna generations reproduced the previous
  ambiguous example; the new example can actually save a valid choice. Ambiguous
  aliases still fail, and an empty catalog offers no unavailable command.
- Read-only saved Web status distinguishes an observed ready process from its
  persisted session receipt. A missing receipt directs explicit `start` reuse
  before Desktop publication; status does not save ownership or launch a child.
  An active request still takes precedence over this setup guidance.
- Product route diagnostics check endpoint environment and same-name provider
  overrides instead of treating the name `openai` as official-direct proof.
  This describes the inspecting process's environment and saved configuration,
  not the route already cached by a running Desktop task. No routing is changed.
- A failed tool continuation followed by repeated caller cancellation reproduced
  an orphaned browser driver and prematurely reopened admission. One shared
  cleanup now retains the observer and driver until both finish; concurrent stop
  joins it, and cancellation still reaches the caller afterward. Regressions
  verify the admission fence, cleanup completion, consumed old turn and new input.
  This race was reproduced with isolated asynchronous fixtures, not a live replay.
- A result arriving during metadata observation also reproduced a lost watcher
  for the same turn's second tool call. Identity changes still end observation;
  a concurrent continuation instead waits for the next owned call gap and reads
  fresh metadata before cancellation. Unknown observations remain terminal.
  The two-call regression verifies two observations, two released calls and one
  returned result before cancellation, without reusing the old observation.

At this checkpoint native-metadata cancellation only targeted the default Codex
home. The later explicit binding fix is recorded above; the verified live
default-home Stop case below still does not establish live non-default-home use.

Final regression for these follow-ups passed 978 Python cases (968 passed,
10 existing skips) and all 134 Node cases on Python 3.14.3, Node 24.14.0 and
PowerShell 7.6.6. The earlier 977-case full pass preceded the two-call watcher
regression and remains separate evidence. Private receipts retain both runs.

After explicit idle deployment, the real overview reported `needs_registration`
and explicit start reused the same ready process before Desktop rebind. A new
native two-file read then failed its business acceptance in 39.1 seconds: no
native call was released, all 12 context pages were read, and zero catalog/schema
pages were read. The assistant reported `web_mcp_read_key_unavailable`; subsequent
endpoint-event inspection confirmed that local rejection, while its exact key
category remains unknown. The final text was delivered; the requested files were
not read by the task and their hashes remained unchanged. Keep this as a failed
case, without replay or inferred attribution to the new cancellation code.
The service remained ready with one process launch and the preview was closed.
Channels changes have source/isolated validation, not a new installed-chat test.

2026-09-28 Stop/lifecycle verification:

- Shared Stop recognition now covers the current composer controls. Cancelled
  worker reuse binds the exact public user-message ID and full dispatched text,
  with one Stop click and stable idle. Exact URL and literal-title checks were
  rejected by live cases because the page changes both during generation.
  Origin, login/plugin routes, challenge/approval, draft, identity and hidden
  worker checks remain. Fixed diagnostic codes contain no page text or IDs.
- A native interruption after a released tool call initially left the browser
  waiting for its result: that interval has no pending HTTP exchange to close.
  Explicit `app_server_metadata_v1` cancellation now reads only bounded native
  metadata and requires the exact completed interrupted turn. Unknown evidence
  stops that turn's watcher; ownership and concurrent result changes are checked
  again before cancellation. The default remains disabled.
- With that option enabled, a new native case was interrupted through the
  Desktop Stop button at 61.1 seconds, with one released call and no returned
  result. Metadata confirmed that exact interruption, the Web Stop was clicked
  once, and the same browser became ready. A new request in the same native task
  then actually read its new fixture, exited zero and returned the exact marker
  in 41.0 seconds; its SHA-256 was unchanged. Browser totals were two dispatches,
  one cancellation, one completion and one process launch. Messages were sent
  through the native task tool, so this does not claim ordinary-composer delivery
  for the whole Stop/next-message case, all approval paths or billing cessation.
- Separate new HTTP cancellations also retained the browser and accepted native
  task-tool reads in 47.3 and 41.3 seconds. These remain separate from the native
  Stop case above. One 2,931-character direct story completed in 21.8 seconds;
  the following native file read completed in 35.4 seconds in the same process.
  A complete answer snapshot must now remain identical for 500 ms before release;
  the existing next-turn mismatch check still rejects later changes. One passing
  long-answer continuation does not prove all late renderer updates are gone.
- Desktop connect/rebind now rejects a live service whose starting record lacks
  the exact worker/session receipt, before writes. Explicit start reuse records
  the same ready child without a second launch; read-only status stays read-only.
  The owner approved one earlier stopped-unbound-instance recovery despite its
  one failed request. Original hashes, process/dependency absence and an exclusive
  port check were verified; only the pointer was retired. Original evidence stays
  retained and this exception does not relax ordinary zero-request recovery.
- Failed cases remain failed: missing Stop recognition, title/URL rejection,
  cancellation after the public Stop had already disappeared, late answer change,
  a story returning only a process claim, and another story wrongly forwarded
  back to its originating task. The latter was not task success. UI navigation
  to unrelated tasks blocked several clicks; a finish/click race opened the voice
  error page, which was closed without retrying voice. No failed input was replayed.

Final full regression passed 971 Python cases (961 passed, 10 existing skips)
and all 134 Node checks. The native cancellation, transport, lifecycle and
manager checks also passed 165 focused Python cases. They cover unknown/duplicate native
metadata, bounded content-free reads, child cleanup, racing continuation and
service stop, consumed turns, changed public identities, legacy one-shot Stop,
and complete/citation snapshot stability. Reference provenance remains in the
implementation sources document; raw receipts and synthetic fixtures stay private.

Earlier 2026-09-28 stop acceptance: one new ordinary-composer input
ended in 20.4 seconds before the attempted Stop could cancel it. The local
terminal gate rejected its public citation sources, with no native tool calls
and no returned final. Read-only inspection showed ten lines of plain test
text; the browser recorded one public reference, but its type was not retained.
An empty-source footer is a hypothesis, not an established cause. The original
failed turn remains retained and was not replayed; the distinct follow-up input
was not sent.

Source diagnostics now retain bounded reference kinds and source-list shapes
only after an actual local citation validation failure. They appear in the
private transport snapshot, contain no answer, title, URL or identity, and are
absent after a successful new turn or a browser exception claiming the same
error. After explicit idle service maintenance, three distinct task-tool inputs
returned the exact short text, all 20 requested lines, and a source-bound answer
consistent with the [Python documentation](https://docs.python.org/3/library/stdtypes.html#str.casefold).
No citation error recurred. These were forwarded inputs, not composer or Stop
acceptance, and do not identify the original failure's reference type.

A separate synthetic regression demonstrated that the browser projection
preserves an empty `sources_footnote`, while the modern renderer rejected it
even for plain text. Modern empty footers now cite nothing and preserve the
answer bytes; present/absent state is separate so duplicates remain rejected.
Empty inline groups, unmatched links/markers, missing/null sources and malformed
footers still fail. Legacy handling is unchanged. This compatibility is verified
synthetically, not evidence that the earlier live failure had an empty footer.
The 125 focused checks and full regression passed: 957 Python cases (947 passed,
10 existing environment skips), all 123 Node checks and the 181-file release
audit. The initial two failing regression cases remain in private evidence.

After deploying the compatibility into the saved idle service and explicitly
reloading the same idle native task, a distinct read-only fixture completed in
29.8 seconds: one paired native command, exit zero, unchanged file hash and the
exact final marker. The saved browser selected GPT-6 Pro/max and stayed hidden.
All 28 product/package checks also passed. This is task-tool delivery, not a new
ordinary-composer Stop test; the empty-footer shape was not observed in this
live result. Saved login, fixed connection and official native defaults remain.

2026-09-28 review follow-up: a new regression first reproduced rejection of a
source-bound Markdown URL containing balanced parentheses. The modern citation
reader now scans nested parentheses within the existing URL bound and preserves
the original link bytes. Paired cases cover plain/angle destinations, optional
display markers, the 8192-byte boundary, unbalanced and mismatched sources, and
oversized input. The 121 focused protocol, MCP and Desktop-configuration checks
passed. Final full regression passed 952 Python cases (942 passed, 10 existing
environment skips) and all 123 Node checks. The initial run caught a document
digest mismatch, corrected using the builder's existing LF normalization before
the complete rerun; both logs remain private. The 181-file release audit passed.
This parser repair makes no model request or installed-service change.

2026-09-28 preview acceptance: three successive new inputs through the ordinary
Desktop composer completed in the same existing GPT-6 Pro/max Web task. Each
executed its exact new read-only command with exit zero; the second and third
answers preserved the prior markers without rereading their files. Native
turn durations were 23.6, 24.9 and 26.7 seconds. Saved login, fixed connection
and citation settings were reused without assistance windows. These were
assistant-operated composer inputs, not task-tool forwarding or owner typing.
The earlier single-character public app-separator mismatch remains failed;
no input was replayed. Main-window stop/reuse remains a separate acceptance
gate, as do cross-provider switching and new-user Channels onboarding.

The bounded public projection accepts only the exact selected app link,
one ASCII-space/NBSP separator and the complete unchanged body, with a second
exact check before proceeding. Cancellation retains that dispatched projection
and verifies the current renderer's idle state. Read-only inspection accepts
only the exact unique mounted modern result, without reading its reply text.
Fixtures reject body, link, identity, mixed-renderer and ambiguous-row changes.
Normal `preparing` status now remains distinct from unavailable setup.

An extracted-package lifecycle check exposed missing `CodexConfig` and
`RouterPort` forwarding in the unified uninstall entry. The entry now forwards
these explicit uninstall-only options; lifecycle and ownership checks are
unchanged. The fresh-install/restoration regression now exercises that public
entry and verifies preserved unrelated settings and retained private runtime
data. Legacy installations without original ownership remain blocked; a
runtime-upgrade backup cannot supply first-install ownership.

The complete source regression passed 950 Python cases (940 passed, 10
existing environment skips) and all 123 Node checks. The 181-file inventory,
reviewed-document/content screen, syntax audit and whitespace check passed.
An earlier extracted snapshot passed 69 installation, upgrade, product and
Desktop-binding cases. Package hashes and fresh-project lifecycle receipts
remain private; none of these local checks publishes or pushes a release.

2026-09-27 native-result regression repair: a new failing native read isolated
24 changed nested descriptions, with identities, parameters, strict flags,
formats and loading unchanged. Indexed continuation now stages complete new
pages only for visible leaf descriptions with zero schema reads. Published
first keys remain valid, partial/full reads stay immutable, and native
history/call/result checks precede publication. Non-indexed requests and all
other contract changes still fail closed; no read budget is reset. A separate
configuration repair recognizes exact owned provider bytes when native Codex
has appended an independent Hooks table before the closing comment. Rebind
and disconnect preserve those independent bytes; provider edits and ambiguous
markers still fail. Real rebind preserved every unrelated configuration byte.

After an explicit saved-service refresh, a new GPT-6 Pro/max native task
completed one actual read and its exact final marker while 250 unread
descriptions refreshed. A distinct geometry input then returned a real failed
command: the model combined inspection with a guessed regex that matched no
source. Both files stayed unchanged, no test ran, and the final answer reported
the failure. Another distinct temperature input explicitly required awaiting
inspection before editing. In the same native task, its two commands and two
paired results completed; only the wrong constant changed, the original test
bytes remained exact, all five tests ran with exit zero, and the final reply
matched. These latter inputs used assistant task-tool delivery, not the manual
composer. They establish this read/edit/test transport, not general model
coding reliability, all-tool acceptance or seamless provider switching.

A separate new input sent to an already loaded older task reached its cached
previous service port and failed 502 before the current service received any
request. It was retained, not resent. Native defaults, saved login and fixed
tunnel settings remained unchanged. Description generation provenance remains
unconfirmed; it is not a reason to relax the binding guard or ask for login
without a current visible requirement.

The later 2026-09-27 maintenance check recovered that exact old task through
native archive/restore, preserving its UUID, provider, directory and failed
turn. Restore reported a load error; metadata and archived-list readback proved
that it had already unarchived and unloaded. The operation was not repeated.
One different file-read input then completed on the current saved service:
one actual command, one paired result and the exact final marker in 25.8 seconds.
The synthetic file and all global configuration bytes remained unchanged;
Desktop was not restarted. This establishes the assistant-guided maintenance
flow in native-web-experience, not automatic hot reload or a provider switch.
The installed CLI was 0.158.0-alpha.2.1; its generated schema still exposes no
immediate unload field on thread/unsubscribe. No source transport change or
new model request was needed to inspect that schema.

The focused 185-case protocol, transport, provider, browser and Desktop suite
passed. The final full Python run completed 950 cases (940 passed, 10 existing
skips); all 119 Node page/surface checks, the 181-file release inventory/syntax
audit and the whitespace diff check passed. New regression cases cover all three indexed representations, complete
new description bytes, retained schema keys, unchanged failed results, read
and page limits, partial reads and altered history/controls. Historical G1
success and pre-reorganization source comparison are recorded in the native
conversation plan; no deleted-code restoration or upstream code copy was needed.

2026-09-26 Web login and continuation repair: the owner's Apple sign-in had
previously closed the auxiliary window at `web_assistance_navigation_not_allowed`.
Visible human assistance now permits standard HTTPS identity-provider redirects
and shows the destination host; hidden execution keeps its narrow navigation
gate. The owner completed Apple sign-in and closed the window. The saved
service reached `ready` without a model request and reused that login after
subsequent explicit restarts. A fresh GPT-6 Pro/max native CLI task completed
two different inputs: the second exact answer included the first answer's
marker. The prior-page failure was traced to a visible assistant row whose old
React child had been detached while its alternate remained mounted. The branch
resolver now accepts that one-sided case only after proving the remaining
parent is current; disconnected fixtures still fail closed. This two-turn
sample used an isolated text-only setting, not a change to the owner's saved
citation profile. The original `markdown_links_v1` profile was restored.

The current Web renderer exposed two public references during a separate
search sample, but its prompt also instructed the page not to use Operator.
That turn was withheld as `web_mcp_context_not_read`; it was not a fair test
of normal context reading. Later distinct CLI samples read all 2/2 context
pages and exposed a newer citation representation: public content already
contains Markdown links and numbered `chatgpt-content-reference` markers,
while `contentReferences` offsets refer to the earlier raw-marker text. The
old positional renderer correctly withheld those results. A temporary
text-only diagnostic profile showed the original public content; it was
removed, and the owner's `markdown_links_v1` profile was restored. The
modern projection now identifies that renderer explicitly, checks source
URLs and numbered public markers, and removes only presentation markers
adjacent to validated links. A bare numbered marker cannot safely identify
its source and fails closed; a two-group regression showed that treating its
display number as a reference-array index could attach the wrong source.
The older offset-based
renderer remains separate. One fresh GPT-6 Pro/max CLI search task then
completed: 2/2 context pages read, zero local tool calls, source-bound final
returned, and its official Help Center article was independently checked
against the answer. Other citation layouts and live Desktop UI are not
proven. All failed inputs and their evidence remain retained; none was
replayed. A different synthetic question unexpectedly released one native
tool call and then failed `web_mcp_request_binding_changed` when the tool
declarations changed; no paired result arrived. That is an unresolved
continuation case, not a successful tool execution. The retained observation
does not establish whether tools were added, removed or redefined. Future
rejections now record only bounded before/after/add/remove declaration counts;
the guard and no-retry behavior remain unchanged. After an explicit
source-bound service refresh, a distinct GPT-6 Pro/max isolated CLI coding
check passed three paired tool steps, the exact synthetic edit and five tests;
the service returned to ready/idle with no assistance needed. That new success
does not reclassify the earlier binding failure. The current source passed
934 Python tests (10 existing skips), 114 page/surface Node tests, the
181-file release audit and `git diff --check`. Live main-window and
three-turn acceptance remain open.

Later on 2026-09-26, a distinct native request exposed a moved public New chat
button under the chat-history navigation. A request-free page inspection
identified the visible, exact-text button; the selector was extended without
relaxing the completed-page, empty-composer or unique-control gates. A new
GPT-6 Pro/max isolated CLI coding check again passed three paired tool calls,
the exact edit and five real tests. A fresh native task then traversed New
chat, read all context pages and executed its one read-only command with the
correct file result, but the next native request changed six of 27 source tool
declarations. No paired result reached Web; the failed turn remains terminal.
A separate GPT-5.6 Sol task called `operator_begin` with a nonmatching first
key and read no context; the source prompt had been submitted intact. A
GPT-6 Sol probe was rejected before Web dispatch because that route is not in
the bound catalog. These observations are not login or verification failures.
Fixed-category diagnostics on further new GPT-6 Pro/max tasks showed unchanged
tool identities, order, descriptions, parameters and strict flags, excluded
`defer_loading` flips, and located all six differences in namespace `tools`
lists. The nested entries were not retained, so their exact change and whether
any safe subset can be carried across a continuation remained unresolved.
A final distinct native sample classified the nested difference: 250 same-
identity tool definitions changed, with zero nested additions, removals or
order-only changes. Their contents were not retained. This is not evidence for
a monotonic-addition exception, so online probes stopped and the strict guard
remains. None of these failed requests was replayed or treated as success.
One private, local-only CLI/MCP fixture produced
two Responses requests and one successful synthetic read-only tool result,
but had 3 top-level tools and no namespaces. It cannot explain the live
27-item/6-namespace drift; no second local attempt or Web replay was made.
The earlier full source run passed 941 Python cases (10 existing skips),
117 Node page/surface checks, the 181-file release audit and `git diff
--check`. After refreshing the two edited reviewed-document hashes, the
post-diagnostic full Python regression passed 943 cases (10 existing skips).

2026-09-27 modern page binding follow-up: an independent review found that the
new public renderer's message units were absent from the older empty-page
counters. A retained conversation could therefore look blank after a temporary
chat URL transition. The page now counts both row formats, and preparation,
assistance closure, request readiness and the final send click all reject a
retained unit. A separate synthetic mixed-turn fixture first reproduced an
old completed assistant row being accepted for a new user row. The modern
projection now requires both rows to share the exact observed turn object;
otherwise it waits without releasing an answer. The page/surface tests pass
119/119. After a request-free stop, source-bound configuration update, hidden
restart and explicit provider rebind, one new synthetic native CLI check passed
three paired calls, the exact edit and five executed tests. The saved service
returned ready/idle without assistance; native defaults stayed unchanged.
This is not live Desktop main-window or earlier declaration-drift acceptance.
No failed request was replayed.

2026-09-25 navigation bound: an Electron page load previously awaited its
navigation promise with no deadline, so a network stall could leave the saved
service indefinitely preparing. The browser surface now ends an uncompleted
navigation after 60 seconds with a non-retrying fixed error; the worker is
closed by its existing failure path and no input is replayed. A hanging-load
fixture and the complete page/host Node suite passed 111/111 checks. This
does not resolve the separately observed old-conversation startup route.

2026-09-25 continuation follow-up: a fresh user-home native CLI task completed
one GPT-6 Pro/max text turn with the exact marker. That isolated invocation
selected live search only for Web; the user's global search setting stayed
unchanged. The second distinct input in the same task failed before browser
dispatch at the prior-page identity check, with zero new model requests or
tool calls. The current ChatGPT page uses different public message rows and a
sidebar New chat button, so the page adapter now checks the exact completed
turn and waits for a confirmed empty destination before admitting another
turn. The resulting 63 page and 47 host checks passed; the 929-case Python
suite passed before the final bounded page-read wait, which changed no Python
source. Live two-turn acceptance of this final source remains unverified. A
later explicit service start failed page preparation on an unrelated old
conversation view, and another stopped request-free instance exposed no
visible login or human-verification control. Those observations are startup
failures, not a reason to ask the owner to verify again. Both stopped
instances and the earlier failed native input remain in their original
records. No Web Desktop picker or same-task provider switch was accepted.

2026-09-25 current Web repair: the saved, exact-source Web service reached a
logged-in hidden empty page without a new assistance request. The current
ChatGPT editor's app menu exposes a unique name before selection and an exact
app ID in the inserted pill; it consumes the placeholder separator and encodes
the inserted replacement as NBSP. The driver now binds that one editor form
and the exact resulting public app-link prefix while preserving every byte of
the native request body. A new GPT-6 Pro/max isolated CLI case passed: three
paired `operator_call` results, the requested exact source edit, five executed
tests with exit code 0, and the exact final reply. The preceding new cases
remain failed at their original gates; none was replayed. Concurrent React
assistant rows without a final selection marker are now waited out rather than
accepted as completed. The Python suite passed 929 tests (919 passed, 10
existing skips), and the then-current page/host suite passed 107 Node tests.
This verifies a real Web
to native CLI coding loop, not the main Desktop composer, live model picker,
same-task provider switching, every model or a published release. The exact
installed ChatGPT app was visible with its existing all-tools permission, but
its frozen tool snapshot was not exposed for comparison and no refresh was
performed. API credentials were unavailable in the test process and the local
LM Studio endpoint was not running, so those live generations were not tested.

2026-09-25 final source gate: the complete suite passed 925 Python cases
(915 passed, 10 existing skips) and all 103 Node checks. After an explicit,
backed-up legacy runtime migration of 20 code files, the current Channels
source completed one exact Feishu user-to-bot reply: one inbox attempt and
the expected bound task's final callback closed. This verifies that existing
user's route, not first contact from another account. That run's Web source
remained fail-closed before browser dispatch because the managed effort slider
is under `aria-hidden`; that attempt made zero browser dispatches and zero MCP
calls. Web coding and live main-window acceptance were unverified at that run;
the earlier successful cases below are historical evidence, not a pass for
this source.

2026-09-25 source verification: the complete suite passed 910 Python cases
(900 passed, 10 skips) with Python 3.14.3 and aiohttp 3.14.3, and all 94 Node
checks with Node 24.14.0. Eight skips require an explicitly enabled current
Desktop CLI fixture; two Windows reparse-point subcases could not create a
symbolic link without the required host privilege. A first attempt with a
system interpreter missing aiohttp failed import and isolated-install checks;
the dependency-equipped interpreter produced the passing complete run. The
179-file inventory, five reviewed-document digests, source syntax and content
screen passed. This is source-only evidence: the saved Web service still needs
a reviewed update to the current source, and fresh Desktop and Feishu turns
must be checked separately.

2026-09-24 source follow-up: fixed a private-chat sender-ID mismatch in the
secondary name lookup, the public Web `tools/list` check against its actual
structured declaration, and direct model-registry CLI writes that could miss
the installed Operator's running processes or pending callbacks. Disposable
first-contact and failure-path cases cover the affected boundaries. The complete
run passed 906 Python cases (896 passed, 10 existing skips), all 94 Node checks,
the 179-file inventory/syntax audit and whitespace checks. Read-only live status
still found the saved Web service ready/idle but bound to an older source digest;
the native default remains official direct. A fresh native App Server confirmed
the Web provider registration with zero model requests, but its model is not in
the picker list and running Desktop acceptance remains unverified. No installed
service, real Feishu task, or model request was changed for this source follow-up.

2026-09-24 bounded Web cleanup: tool-result continuations now bind the complete original hosted-search declaration and its source position, including absent versus explicit fields. Citation attribution compatibility is limited to an actual final query parameter; path, fragment and query-value lookalikes are rejected. Public interruption checks exclude explicitly hidden accessibility announcements and CSS-hidden surfaces while retaining real visible alerts. A final CSS-inheritance review preserves an explicitly visible descendant of a visibility-hidden ancestor; all 94 Node checks passed again, and the final service refresh made no model request. The browser preparation race keeps its fixed readiness code, and both assistance paths first require current-page inspection. Shared user-binding diagnostics now use one bounded whitelist; lifecycle ownership remains separate.

The complete regression passed 883 Python cases (873 passed, 10 existing skips), all 94 Node checks, the 184-file inventory/syntax audit and a 189-file content-screened source collection. One initial focused fixture failed because its synthetic session lacked background mode; it was corrected before the complete run. Current guidance and plans were reduced from 38,325 to 14,360 bytes; exact original documents and hashes are retained privately under the Web module, with unique dated events consolidated into the history index. No private transcript, credential or recovery original was deleted. Similar acceptance programs had distinct inputs/receipts and were retained. The older 2026-09-20 test-count discrepancy is documented, not silently resolved without its raw output.

The source-bound saved service was explicitly stopped, updated, started and rebound after regression. One fresh native read-only case then consumed all three context pages, one catalog page and one complete schema, but produced no operator_call or native file read. Its public final reported that a safety check blocked the tool. That wording is not independent evidence of the refusal source. The native turn status was completed, but task acceptance failed; there was no retry and the original case remains intact. The service is ready/idle with saved login, while global search and native direct routing remain unchanged. This audit does not establish current main-window tool or seamless-switch acceptance.

2026-09-24 search-route follow-up: the project-local `web_search="disabled"` test workaround below was privately backed up and removed because it also changes other models in the same directory. The independent Web provider now accepts only the observed optional live hosted declaration and binds it to ChatGPT Web's own search/citation path; other routes and the user's global search configuration are unchanged. Two separate fresh native tasks without the override completed with public source links and zero local tool calls, including one after the final source-bound restart. Earlier citation failures and an unread-context failure remain failed; a source URL marker carrying the bare URL while its validated link appended `utm_source=chatgpt.com` led to a narrowly bounded citation fix. The final answer's body used a mirror as evidence, so factual source fidelity is a separate gate. The 311-case Web regression and 26-case preview check passed; live Desktop manual-composer and all-query accuracy remain separate gates. The saved service is ready/idle.

On 2026-09-24, a new message typed directly into the dedicated Desktop Web task failed with local HTTP 502 at the old independent-provider port. The old port had no listener; the saved Web service was ready/idle at a different port and its last-turn browser/tool counters did not advance. The failed input was not replayed. Read-only Desktop status now identifies a stale service-generation binding. An explicit, journaled `desktop-rebind` kept the provider and task identity, saved the prior complete config, changed only the owned local address/token block, and left native default routing and zero retries unchanged. The actual configuration now matches the checked saved service; a fresh native App Server read the provider with zero model requests. Running Desktop adoption and a new direct message remain unverified.

After this repair, the full regression passed 874 Python cases (864 passed, 10 existing skips), all 93 Node checks, the 183-file inventory/syntax audit and whitespace checks. A separate simultaneous focused run hit a transient Windows socket-capacity error in an unrelated service-manager fixture; that exact fixture passed alone before the serial full run passed. The current saved Web service remained ready/idle and required no assistance.

After Desktop reopened, an assistant-relayed new marker in the existing long Web task reached the current provider port and returned a typed local HTTP 413 before browser submission. The local transport recorded zero tool calls and no final; the original 502 and this 413 remain distinct failed turns, neither replayed. This establishes that the rebind removed the old-port failure for this path, but not a completed Desktop Web answer or manual input-box acceptance. A fresh short task is needed to test the remaining gate without altering or truncating the long task; the older S1 task has its own opaque cross-provider history failure.

The owner authorized that short task and asked the assistant to send future test messages. The pre-reorganization 413 repair was for a different native HTTP body bound (16 MiB to 64 MiB after a roughly 17 MiB request); this long task hit the Web indexed-context preflight (24 pages of 48 KiB, 40 single-use reads), so the old transport fix does not apply. The first clean Web task failed before browser dispatch on `unsupported_tool_type`. A local synthetic request captured one native `web_search` declaration without storing content. A task-start-only search override produced one exact Web answer, but Desktop reopening lost it and the next distinct follow-up failed on the same tool type. A third clean task in an already trusted dedicated directory used project-local `.codex/config.toml` with `web_search = "disabled"` and `features.standalone_web_search = false`; `config/read` confirmed both. Its first Web answer matched a new marker. After the creation process exited, an assistant-relayed follow-up in the same Desktop task produced another exact final marker in the native rollout. Saved service diagnostics showed browser HTTP 200, public final returned, zero local tool calls and ready/idle state. The official native default and user-level search were unchanged. This is a completed tool-relayed Desktop task text continuation, not manual composer input, native hosted search, file/tool execution or universal provider switching. All prior failed turns remain failed and unreplayed.

On 2026-09-24, one new Feishu user-identity CLI message to “Codex 接线员” completed the existing user's full path: one inbox attempt, fixed Beeper on Luna/low, bound business task on Astra/high, accepted final callback and one exact bot reply. The prior producer-held failed row remained untouched. This is current-user continuation, not first contact by a second account. The legacy installed Channels runtime was upgraded only after its stopped manifest bytes were verified and originals retained; startup hooks were corrected in a separate exact-byte transaction. All readiness gates passed, but the original installation ownership journal remains absent, so full uninstall and normal upgrade still require separate review.

The isolated Web coding verifier now accepts an explicit published model and supported reasoning effort without changing its default or the user's configuration. One fresh GPT-6 Pro/max case completed three paired MCP calls, an exact disposable source edit and five actual passing tests. Its private receipt records zero retries, no tool rejections, a ready/idle saved service and no Desktop acceptance claim. This proves one managed Web-to-native-tool execution path, not live main-window selection, same-task provider switching or independent backend model attestation. Earlier HTTP 403 failures remain failed.

Two disposable local Responses listeners then tested same-task provider changes on the installed App Server version. A fresh process resumed the exact completed task with a second explicit provider/model and sent its next request only to the second listener. In the original loaded process, resume retained the first provider/model and the second request stayed on the first listener. An experimental in-process settings update accepted a model change, but a new turn explicitly naming that second model still reached the first listener in this probe. This is a failed in-process switching acceptance, not a reason to restart the live Desktop, mutate user tasks or enable global routing.

After those changes, the complete suite passed 871 Python cases (861 passed, 10 existing skips) and all 93 Node checks. The 183-file inventory/syntax audit and whitespace check passed. Read-only product status still showed Channels and the saved Web service ready, with the official native route direct.

On 2026-09-23 the saved Web service gained a request-free hidden-page readiness gate. Its cold launch reached an authenticated empty temporary chat with one hidden browser process, zero model requests, no assistance window and no login prompt. A later independent native CLI coding fixture passed: three MCP calls were received and paired, the source edit matched the requested bytes, and all five tests exited successfully. The cached page is rechecked on consumption. Persistent login or challenge status requires exact page observation before asking the owner to act. One broad test run overlapped a source edit and correctly failed its runtime-fingerprint check; the source was then fixed and focused checks passed. This does not reclassify earlier HTTP 403 requests or establish live main-window Desktop acceptance. Official native traffic remained on its direct route.

With runtime source fixed, the complete plugin suite passed 869 Python cases (859 passed, 10 existing skips) and all 93 Node checks; the 183-file release inventory/syntax audit and whitespace check passed. A fresh native App Server check on CLI 0.155.0-alpha.16.3 still found the independent Web provider registered but no Web model in the main model list. Its new `thread/start` schema includes a `modelProvider` field, while `thread/settings/update` does not. Provider registration, isolated CLI execution and live Desktop model selection remain distinct acceptance gates.

A separate disposable App Server probe on the same CLI confirmed the narrower per-task path. Without a custom model catalog, `model/list` excluded the Web slug but `thread/start` returned the requested model and independent provider. An empty task could not resume because no rollout existed. One new text-only turn against a local synthetic Responses listener then completed with exactly one model request; a new App Server process resumed that task with the same model and provider. No real Web request, existing task, main Codex configuration or global route was touched. This does not establish live Desktop visibility, task opening, same-task provider switching or real Web execution.

After hidden-page preparation, one fresh managed GPT-6 Pro text request to the saved checked provider returned HTTP 200 and a completed response with the exact random marker; the service remained ready and idle with no assistance prompt. It requested no tools. This is a real managed Web text pass, separate from the synthetic per-thread probe and earlier failed 403 turns; the provider's returned model slug is not independent backend attestation. Desktop picker, tool execution and same-task continuation remain separate.

The next two isolated native CLI coding fixtures did not pass. The first
stopped before Web dispatch when the plain multi-line editor failed an
`innerText`-only exact-input check. The editor now also verifies its exact
ordered paragraphs; 89 Node checks pass. A different new fixture passed that
check and dispatched one GPT-5.6 Sol/High generation POST, but the page
returned HTTP 403. Local MCP evidence recorded zero `operator_call` deliveries,
zero file edits and no tests run in both fixtures. Neither failed request was
replayed. The upstream reason for 403 and live Desktop tool acceptance remain
unconfirmed; the native direct route is unchanged.

On 2026-09-23, source runtime 4.2.0-alpha.138 passed 866 Python cases
(856 passed, 10 existing skips) after the Web catalog correction. After the
earlier browser-host changes, all 88 then-current Node checks, 62 focused Python browser
checks, and the 183-file inventory/syntax audit passed. A response-level model check corrected the Web
catalog to GPT-5.6 Sol, GPT-5.6 Pro and GPT-6 Pro: three entries with six
choices. Latest/High produced a reply whose own model menu says GPT-5.6 Sol,
so the earlier Web GPT-6 Sol preview entry was removed. Every remaining
selection verifies the exact public model option, effort label and explicit
generation before dispatch. The three entries share one browser and consumed-turn ledger. The ideas of exact aliases,
generation preservation and separate Pro identity came from the pinned
Chat On Steroids reference; no upstream runtime or retry behavior was copied.

A fresh isolated native App Server returned the corrected three visible catalog
rows and six choices without a model request or a change to the main
configuration. The earlier four-row/ten-choice probe belongs to the superseded
catalog. These are catalog checks, not live main-window selection or routing.
An earlier independent saved-profile browser inspection failed before model dispatch.
The managed Web service was then upgraded with the saved settings and reached
request-free readiness. Its explicit assistance window displayed a blank page, without an
actionable login or verification control. A local page rendered correctly in
the same window implementation. The exact service was stopped with zero model
requests; saved login and fixed connection data remain retained. No request
was replayed, no verification was requested from that evidence, and the native
direct route remains unchanged. At that stage managed Web generation and live
Desktop acceptance were pending. See the [Web model catalog](../../models/web/docs/web-model-catalog.md).

The in-app browser separately completed four serial, exact-text samples with
the public selection set to GPT-5.6 High, Latest/Pro, GPT-5.6 Pro and
Latest/High. There was one request at a time and no retry. Response-level
"Switch model" menus showed GPT-5.6 Sol, 6 Pro, 5.6 Pro and GPT-5.6 Sol,
respectively. The previous Latest/Extra high selection was restored afterward.
These observations cover public UI selection and replies, not the managed
provider, all six current combinations, native tools, server-side attestation
or the main Desktop picker.

A separate, explicit recovery now retires a stopped launch that never acquired
a verified worker binding only after checking its unchanged settings, original
process and dependency absence, request-free stopped snapshot, absent tunnel
marker and exclusively reservable listener port. The real old record was
retired with its original bytes retained; no worker ownership was invented.
Later foreground inspection did reveal the actual human-verification checkbox.
Assistance was requested only after that current screenshot/accessibility
evidence. An earlier probe temporarily missed the model control, but a fresh
request-free review reached the authenticated page and verified its button and
Latest/GPT-5.6 picker after loading. The first managed GPT-5.6 High sample
stopped at a genuine background challenge before model dispatch (HTTP 400,
zero tool calls). After the same worker was ready, two distinct new samples
stopped before dispatch on the Pro-header check. The managed Electron page
showed `5.6 Sol Pro` where the in-app browser showed `5.6 Pro`; the selector
now waits for the heading update and accepts these two observed forms only
after checking the GPT-5.6 radio option. All 87 current Node checks pass.
A further new sample encountered another real challenge after a fresh hidden
page navigation. Its assistance window visibly showed the checkbox but closed
without passing the ready check; that old service was explicitly stopped
before catalog correction. All failed
inputs remain terminal, with zero browser model dispatch and zero accepted MCP
tool calls; none was replayed. Managed generation and live Desktop acceptance
are still pending. Earlier failed
fixtures and the full run that detected a source change remain separate from
the successful baseline regression run.

Further bounded diagnostics on fresh, serial requests exposed the current
slider-description format: after reaching position 4 and the `5.6 SolPro`
header, the effort label was unrecognized because the page announced a
generation-prefixed label such as `5.6 Pro`. The parser now separates that
observed prefix from the effort and verifies both against the selected model.
At that stage, all 87 Node checks and 62 focused Python browser lifecycle checks passed; the
final full Python regression is recorded above. A later request-free assistance
page did show a Cloudflare checkbox, then both screenshot and accessibility
view showed the normal composer. A distinct new managed GPT-5.6 High sample
passed the checked model and effort selector and dispatched once. Its exact
ChatGPT generation POST returned HTTP 403, which the provider reported as a
non-retrying local HTTP 400 `web_model_http_rejected_no_retry` envelope. The
failed worker closed; no answer or MCP tool call was accepted, and that input
was not replayed. The upstream reason for 403 remains unconfirmed. The current
saved service was unavailable after the terminal failure, with no actionable
verification window. Managed generation and live Desktop acceptance remained
pending at that stage; native direct routing remained unchanged.

After an explicit stopped/reconfigured service start, a checked assistance
page became ready without resending the failed 403 input. Five distinct,
serial managed text samples passed: GPT-5.6 Sol at none, medium, high and
xhigh, plus GPT-5.6 Pro at max. Each selected its checked public option and
effort, received HTTP 200 and returned its exact marker. No native tool
execution was requested or accepted. The first GPT-6 Pro sample stopped
before dispatch because this managed page displayed a bare `Pro` heading while
its slider announced `6 Pro`. The selector now accepts that exact combination
only with a checked Latest option and matching slider generation. A different
new GPT-6 Pro sample passed selection, then stopped before dispatch at the
exact composer-text check. The host now briefly reobserves the text already
inserted without typing or sending it again. A further distinct GPT-6 Pro
sample passed selection and exact composer verification, dispatched once, and
received HTTP 403 from the page's generation POST. No answer or tool result
was accepted. All 88 Node checks pass. No failed input was replayed. A separate
new in-app-browser Latest/Pro text sample succeeded with an exact reply whose
response menu identified 6 Pro; the user's previous Latest/Extra high choice
was restored. That direct browser success does not establish managed Electron
access, native tools or the cause of either 403. At that stage, the five GPT-5.6
managed text choices were the only live managed generation passes. Global native
routing remains direct.

After the final browser-host edit, all 88 Node checks and 62 focused Python
browser driver/lifecycle checks passed. The release inventory and source syntax
audit passed for 183 files. An explicit stop/start restored the saved Web
service; its new assistance page briefly showed a verification checkbox, then
returned to a normal composer without a confirmed human click. The assistance
window was closed and read-only service status is ready. No model request was
sent on this final service instance. The canonical skill now waits and
rechecks a transient new-instance challenge before asking the user to act.

Source runtime 4.2.0-alpha.137 passed 859 Python cases (849 passed, 10 existing skips), all 82 Node checks, and the 178-file inventory/syntax audit. This fixes five review findings: independent saved Web services are checked before uninstall even without a cold-launch plan; fresh exhausted quota blocks first-contact task registration before a creation job or Beeper queue is consumed; the official-route recovery lock allows status and owned cleanup while continuing to block activation; uninstall recognizes the exact source and installed router identities and rechecks the observed process before stopping; and all four installation inventories include the Web tunnel module. Isolated Python imports verify the installed Web service without access to the source tree.

The first focused run exposed a missing synthetic contact lookup. The first full run caught an unnecessary optional-dependency requirement for Channels-only uninstall and an outdated Desktop fixture; these were corrected, with the failed evidence retained. A subprocess without third-party packages now checks the no-Web preflight. The current installation received only the reviewed quota-guard file and manifest maintenance, preserving its existing ownership status. Channels and Web returned online/ready with saved login and official native direct routing unchanged. No live model request or new-user task was sent for this repair; first contact by a second real authorized account remains unverified.

Source runtime 4.2.0-alpha.136 passed 849 Python cases (839 passed, 10 existing skips), all 82 Node checks, and the 178-file inventory/syntax audit. First-install checks now require Python 3.11+ consistently. Status, Models and new background installations discover existing runtimes through an installed-only launcher listing, then execute the selected interpreter directly. They skip Windows Store placeholders and keep the project virtual environment's startup priority. MCP readiness checks the first `python` command separately, so another working interpreter cannot hide a broken MCP entry.

Eleven interpreter-discovery checks cover old versions, launcher-only environments, command precedence, bounded discovery, path handling and the preferred project interpreter. The real source status command also completed without creating files in an empty project or sending a model request. Initial focused runs caught two missing inventory entries, which were fixed before the full runs. A successful earlier 844-case run preceded the launcher auto-install correction and is retained separately. This batch updates source and the preview package; the existing installation retains its reviewed channel maintenance. It does not establish real first-contact task creation, MCP connectivity on a launcher-only computer or fresh-install Desktop acceptance.

Source runtime 4.2.0-alpha.135 passed 838 Python cases (828 passed, 10 existing skips), all 82 Node checks, and the 176-file inventory/syntax audit. Automatic registration can now verify one known empty-preview paginated task against matching unarchived native v5 metadata when the complete native catalog omits it. The compatibility check is read-only and rejects unknown storage layouts, incomplete catalogs and identity differences. It does not change the native index or expand `/init` visibility.

The deployed check verified the previously omitted existing task without changing its binding or native configuration. A new, single Feishu `/model` control message received the expected reply without a model request. Channels returned online and Web reused the saved login. Synthetic creation/reuse tests cover one creation and no duplicate creation; first contact by a different real authorized user remains a separate acceptance gate. The initial test fixtures leaked SQLite handles during cleanup and the initial live metadata check rejected equivalent Windows path spellings; those failures were retained and corrected before deployment.

Source runtime 4.2.0-alpha.134 passed 833 Python cases (823 passed, 10 existing skips), all 82 Node checks, and 176-file inventory/syntax checks. It fixes provider-filtered task lookup and rejects legacy root/environment endpoint overrides during official `/model` selection. The initial full run caught an installer version mismatch introduced by this version bump; the installer was corrected and the full suite rerun. Earlier failed evidence is retained.

Installed alpha.134 read-only checks confirmed that two existing external-provider tasks appear in the directory while Beeper remains excluded. The current bound task's native settings and five official model choices remained readable without configuration or model requests. At that stage, a separate native directory omission for that bound task was unresolved; the alpha.135 compatibility check above addresses registration verification. Saved Web service configuration was updated with the same connection settings and returned ready without a new login.

On 2026-09-22, source runtime 4.2.0-alpha.133 passed 830 Python cases (820 passed, 10 existing skips) and all 82 Node checks. The product-status subset passed 24 checks. The suite ran with the exact Channels service stopped and no pending callbacks. Inventory and source syntax checks covered 176 files.

Seven new Feishu messages were tested serially: five control commands and two business messages. `/model` selected Luna/low and then restored Astra/high in the same bound native task. Both business turns were checked against actual native model metadata, one relay, an accepted callback and the exact Feishu reply. Beeper remained Luna/low. Control commands did not invoke a model. These checks do not establish API/Local/Web switching, new-user automatic task creation or global menu integration.

Read-only status now distinguishes an installation-manifest review from missing setup. A saved Web assistance flag requires observation of the exact current page before asking a user to log in or verify. Existing channel bindings no longer receive an unconditional `/init` instruction. This does not relax readiness gates or change service execution.

Before product packaging changes, the regression suite contained 759 cases: 749 passed and 10 existing skips. Version compatibility was checked with Desktop 26.915.4065.0 and CLI 0.155.0-alpha.9.2. Four serial isolated CLI rejection fixtures each produced exactly one Web POST and no browser/model dispatch. They covered direct HTTP, router HTTP, router WebSocket and independent-provider capacity errors. These tests do not establish a live main-window Web workflow.

New product/release checks are recorded in the generated local release receipt. Source syntax, exact inventory, archive hashes and content screening are separate from real account, tool and Desktop acceptance. A release build does not start services or publish to a remote repository.

The 2026-09-20 saved-entry reuse and diagnostic improvements passed 39 focused checks, 778 Python regression checks with 10 existing skips, and all 82 page checks. Two consecutive checks of the real saved entry confirmed reuse without changes to protected configuration files or Web process identities. They sent no model requests and do not establish page-preparation speed or native model-menu improvements. That work used source version 4.2.0-alpha.132 and did not build or publish a new release package.

Known failures remain: occasional Web cold-page timeout, long-context/task-selection failures, and global-routing request-size/retry concerns. Official native direct routing is retained. Preview scope explicitly defers stability work without removing permissions, capacity limits or no-replay boundaries.

2026-09-29 stopped-router handoff repair: the never-armed prepared plan now has
a reviewed archive path when its exact saved router process is absent, its
port is exclusively free, and the saved Web route remains idle and ready.
The handoff starts a fresh detached router only after that archive has a
witnessed receipt; a concurrent listener or wrong process identity stops the
sequence before new preparation. It still preserves the original plan,
native-route-only marker, config and failed runs, and does not retry a turn.
The focused handoff, supersede and router-config tests cover order, changed
state, and process mismatch. These are isolated checks; the earlier live
Desktop-exit attempt still has a missing terminal result and no confirmed
cause. No new Desktop exit, global activation or model request occurred during
this repair. Synthetic scratch from the independent router survival check was
moved to `.codex/recycle-bin/operator-router-lifecycle-probe/` at the owner's
request for later manual disposal.

A subsequent owner-performed Desktop exit left the detached handoff at
`waiting_for_exit`, with a launch intent and a last heartbeat but no terminal
result. The owner then ended residual GPT/Codex processes and reopened manually.
The saved plan and native-route-only marker remained in place; there was no
activation attempt or model request. Current config differed only in the
Desktop-owned Computer Use pipe value. The helper's exact termination cause
remains unobserved. Local Scheduled Task registration was denied for the
current unelevated user, so no scheduled task was retained. A disposable WMI
process-create probe ran under the same user and interactive session with a
`WmiPrvSE.exe` ancestor, and the actual handoff launcher function witnessed
its start after the controlling Python command exited. The launcher now uses
that independent hidden process path and verifies the started worker's
ancestry. The bounded heartbeat reports the number of remaining Desktop
processes, without exposing process arguments. These isolated results do not
yet establish successful live Desktop exit or automatic reopen. The probe
files were moved to the same project recycle-bin area.

2026-09-30 live handoff findings: the independent WMI worker did survive a
normal Desktop exit and witnessed the old plan's archive, but the router's
Windows virtual-environment launcher handed the listener to its one-hop base
Python child. The former exact-PID test rejected that actual child. An explicit
new request-free start reproduced `router_fresh_service_identity_mismatch`;
the bounded one-hop, birth and executable check then started an exact ready
listener. Explicit Web binding was also required before a new plan could pass
preparation. A later plan prepared while Desktop was open bound a router
started from the Desktop's process tree; that router disappeared on exit, so
the handoff stopped before any config or model request. Its native fallback
launched the WindowsApps executable without package identity, matching the
owner's visible ChatGPT error. The official packaged application ID and the
current Desktop process's package identity were checked read-only. The handoff
now uses Windows packaged-app activation for fallback and directly runs the
existing one-shot consumer after arming; the installed entry is unchanged.
The subsequent independent-worker run witnessed the configuration switch,
retained the router across exit, and reopened the official app; the owner
confirmed automatic reopening and process inspection verified package identity.
The handoff nevertheless recorded a terminal failure because Explorer returned
a nonzero exit code after dispatch. That record is retained. A regression first
reproduced this false failure; activation now judges only the stable exact app
identity, without waiting for Explorer or relaunching. Negative tests reject an
unrelated package, executable or changed process birth. The focused
router/unified tests pass 92 cases. The strict transaction status became
review-only after Desktop changed its auxiliary connection pipe directory;
read-only TOML comparison found no other changed field, including model routing.
The earlier completion and later changed configuration remain distinct evidence,
not permission to replay activation. At that checkpoint, main-window model
selection and new-turn acceptance were unverified; UI inspection stopped when the owner switched to
another task. The installed entry and its normal-launch path remain unchanged.

2026-09-30 ordinary Desktop picker/composer acceptance: the unified menu showed
native, Local, API and three Web choices. A new Desktop-owned unified-provider
task first failed a native setup turn with a transport 502 before upstream
headers; its cause remains unconfirmed. A subsequent unauthenticated, read-only
network check received 401 and did not replay that turn. Three distinct composer
turns then passed: GPT-6 Luna/low arithmetic (2.746 seconds), Web GPT-5.6 Sol/high
using the previous answer (14.796 seconds), and native Luna/low using the Web
answer after switching back (3.488 seconds). Turn metadata and exact final
answers matched; no service restart, login prompt or separate App Server task
takeover was used. This proves this short text sequence, not every history shape,
tool, model, stop state or voice path.

An intervening GLM 5.3 Flash/low composer turn failed locally with
`reasoning_summary_not_supported`; metadata confirmed Desktop's detailed
summary setting. The active API registry predates the source candidates' summary
passthrough, named create-task result and standard-tool contracts. Offline
fixtures reproduced rejection by both old API registrations and acceptance of
the unchanged detailed-summary parameter by both source candidates. A private
replacement preview retains endpoint/model/credential-variable/context identities;
it was not applied to the running registry and requires reviewed stopped
maintenance. Updated contracts alone do not prove live API acceptance.

LM Studio was initially stopped. Its existing server was explicitly started on
loopback, and a single subsequent Qwen3 0.6B composer turn was rejected with
`opaque_cross_provider_context_not_supported` in this same native-history task.
The synthetic opaque-input guard preserved its input while reproducing the
rejection. No historical content was deleted, no failed turn was repeated, and
no local-model answer is claimed. The task was left selecting native Luna and
the UI returned to the owner's development chat. The first native 502, GLM
contract failure and local-history failure remain separate retained outcomes.

The subsequent read-only review found an actual `compacted` record during the
Qwen3 0.6B turn, with one encrypted `compaction` item in its replacement history.
The selected model's registered context is 40,960 and Desktop reported 38,912
effective tokens, whereas the preceding native turns reported 258,400. No earlier
standalone encrypted response item was found in this exact fixture. The evidence
therefore identifies native compaction during the switch, rather than a failed
local inference. It does not establish compatibility for other histories/models;
no ciphertext was printed or discarded and no capacity was enlarged.

Existing API contracts can now be maintained by explicit `update-contracts`
preview/apply. The transaction binds old and candidate registry digests, permits
only `responses` changes, preserves an original backup and unrelated rows, and
uses the stopped lifecycle/port and callback checks. Twelve new tests cover the
summary regression, preview/apply, identity protection, digest drift, lifecycle,
concurrent edits, backup conflicts, locks/write failures, no-op, verification-label protection,
restoration retaining later registrations and CLI wiring.
The related registry, adapter, label, discovery and product-preview suites passed 137 tests.
The real two-API preview succeeded without network requests or live registry
changes; deployment and new Desktop API acceptance remain outstanding.

A later ordinary Desktop composer test selected LM Studio Gemma 4 E2B Instruct
in a new projectless conversation. Its first input (23 + 34) returned exactly
57 in 23.261 seconds without a tool call. The endpoint reported 129,460 input
tokens against Desktop's effective 124,518-token window (registered 131,072).
A distinct follow-up asking to subtract nine failed during remote compaction
with `unsupported_history_item` after 71 ms. The exact rejected input shape was
not captured, so this is not attributed to encrypted history, a particular
codec or LM Studio inference. The first success and failed continuation remain
separate evidence; no request was retried, no history/config was changed, and
the development chat was visually restored. Basic local first-turn text is
verified for this exact model; local multi-turn and cross-model acceptance are
still incomplete. Private turn metadata is retained alongside the picker audit.

The subsequent source repair selects the official client's text-compaction
path in newly generated unified configurations and preserves recovery of both
old and new provider names. The version-bound cause, native-model behavior
change, migration requirements and unsupported existing encrypted histories
are documented once in the [router compaction contract](../../models/common/docs/model-router.md#client-owned-compaction-2026-09-30).
The focused candidate/preparation/cold-start/recovery/router/adapter suites
passed 193 tests, including eight opt-in installed-client cases with synthetic
credentials. Those cases include both automatic and manual compaction followed
by continuation, native passthrough compaction, search and single-attempt 413.
No real-home configuration or running service was changed by this repair.
Live Gemma follow-up, Web continuation and signed-in native behavior with the
new provider name remain unverified; the earlier failure remains terminal.

Closure work added an explicit witnessed-activation upgrade handoff. It retains
reviewed Desktop preference changes, archives the complete recovered activation,
binds optional API contract updates, and refreshes a source-stale Web service only
after normal stop. The focused lifecycle/registry/installed-client suites passed
175 tests; subsequent handoff/retirement/product checks passed 70, and the latest
six upgrade cases passed. These overlapping counts are not a full-suite total.
Synthetic process observations were used for upgrade lifecycle tests; Windows
config replacement, recovery, retirement and archive witnesses used real
disposable files. The later 50 installation/recovery checks passed. The live
Desktop-exit handoff recovered native routing, retired and archived the previous
activation, applied the two API contracts, refreshed the saved Web service and
bound its new idle router. It then stopped at entry selection: first-install
setup cannot claim ownership of this machine's entry-only migration. The worker
reopened the official packaged app in native mode; this was recovery, not a
successful activation of the new provider. The original failed handoff is retained.

The repair restores only the exact recovered entry bytes against their old
witness, keeping launcher/shortcut ownership and all recovery originals. It also
uses one canonical Python module identity for handoff errors, so imported fixed
failure codes are not mislabeled as unknown. The upgrade/handoff/migration checks
passed 39 tests, including real disposable migration ownership checks; the final
upgrade/handoff rerun passed 26 after adding the pending-activation guard. The
live recovered entry was then restored from its exact original with a witnessed
replacement backup. Native protection remains active and the official app stays
on its native route. No service start, contract update or model turn was repeated.
Post-upgrade
local/API/Web acceptance remains outstanding. The maintenance
contract is maintained in [cold-launch guidance](../../models/common/docs/unified-cold-launch.md#replacing-a-witnessed-activation-during-an-explicit-upgrade).

The next live handoff ended in the exit-wait stage after its original ten-minute
budget. Its final observation counted remaining same-name processes; it created
no activation attempt and changed no configuration. This does not establish why
those processes remained, or whether the owner's close action completed.
The owner subsequently opened the official app manually. This failure is retained.

The maintenance experience now requires one shown status-window child before
asking the owner to exit. New plans wait two minutes by default, allow defer
before maintenance and retain a visible terminal outcome. Waiting failures do
not launch the app; process-observation failures are distinct from normal waiting.
The window has no process-kill, service-control or retry capability. A real Windows
concurrent-reader test reproduced status-file replacement denial; the bounded
append-only status journal fixes it without retrying maintenance. Control tests
exercise the actual Windows Forms defer button and terminal labels, and rendered
waiting/timeout layouts were inspected. Computer Use did not enumerate the
PowerShell-hosted window, so those controls were exercised by the isolated UI
test harness, not claimed as user-driven Desktop acceptance. The full real
exit/update/reopen flow with this UI remains a release gate; this work did not
start a new live handoff, change native routing or replay any failed turn.
The focused feedback/handoff/upgrade/preparation/cold-launch/product regression
passed 89 tests. A final feedback/handoff rerun passed 32, including a display
failure after successful activation that must not overwrite the witnessed
result or reopen the app again. These counts overlap.

2026-09-30 final entry closure, source and disposable integration evidence:

The shared startup helper and retained native-only executable now activate the
checked Windows package through AppsFolder. A direct `WindowsApps/app/ChatGPT.exe`
launch can omit the package identity; compilation and isolated activation tests
exercise the actual C# fallback and PowerShell helper without opening the real
app. This repairs a launch path, not every earlier exit-wait failure.

Fresh-install desktop pairs bind the default native home, successful build
metadata and exact shortcut/helper
bytes. Disposable real Windows shortcuts passed install, unchanged reuse,
uninstall and reinstall. Regression tests cover partial-link rollback, edited
files, pending activation, mismatched uninstall home and preservation of the
native helper's read-only flag across imports. A prepared pair build cannot fall
back to legacy shortcut creation after failure. Pair ownership is checked by
unified-entry preparation and its helper sources are bound into new handoff
manifests. Existing entry-only journals are not adopted as first installations.

The final default suite ran 1,290 Python tests in 532.867 seconds with 26 skips
and no failures; Node passed 134 tests. The default skips remain optional
environment/CLI cases and unavailable Windows symlink privileges. The separate
eight current-CLI synthetic search/413/compaction/catalog cases passed earlier
in this closure run; they do not establish Desktop acceptance. The first full
baseline's two release-inventory failures and intermediate integration failures
remain in private evidence; the final inventory includes all four new files.
All 197 public-document local links and 37 anchors resolve. Root and packaged
project rules are byte-identical.

No real shortcuts, login, task history, routing or installed services were changed
by this closure. Legacy-to-pair migration, in-place pair build upgrades, the real
status-window exit/update/reopen flow and post-upgrade Local/API/Web basic turns
remain unaccepted. Current legacy entry and failed handoff records are retained.

The public package includes five reviewed documents at their original source
paths, including this audit and the plugin README. The release inventory binds
their reviewed SHA-256 digests, and the builder screens the complete allowlisted
source before packaging without substituting document copies. Personal accounts,
credentials, browser profiles, runtime databases, private evidence and task
histories are not included. Raw private evidence remains local.

2026-09-30 entry upgrade continuation, source verification:

A private compiled candidate now supports digest-bound replacement of an owned
pair build. A separate legacy pair record preserves the original migration,
adoption and config-only upgrade chain. Its Desktop link is renamed in place,
retaining the Windows file identity, while the Start menu entity remains intact.
The current native settings are not replaced by these operations. Recovery
returns the old Desktop name before the earlier migration can restore its
original shortcuts; the repaired build and native pin helpers remain available.

The legacy COM integration passed five tests, including build-chain upgrades,
restoration, changed historical recovery material and corrupted new-backup
rejection before public writes. Unified entry preview passed 23 tests, including
seven new real-shortcut legacy cases and a complete older adoption/config-upgrade
chain. The focused pair, build upgrade, desktop experience, uninstall and handoff
suite passed 73 tests. These counts overlap earlier component checks. Failed
intermediate implementation checks were corrected without operating on live
shortcuts or replaying model requests.

A read-only inspection of the saved unused launch plan found later legitimate
native settings changes, so the original strict supersede preview refused it.
The separate unused-plan withdrawal path preserves that original plan and current
native state; it does not relax the original supersede contract or permit failed
activation reuse. Real installation and normal-exit/reopen acceptance remain
separate from these source and disposable tests.

2026-09-30 reviewed entry/runtime deployment:

The second full regression passed 1,360 Python tests in 929.498 seconds with 26
skips and 134 Node tests. The initial full run's ten hidden-PowerShell encoding
errors remain recorded; explicit UTF-8 fixed that process boundary. A subsequent
completion-boundary change passed all 47 runtime-cutover tests: changed process,
queue or Web recovery evidence prevents a completed receipt even after the last
file write. These component counts overlap the full run.

The first real pair upgrade stopped before creating a transaction because two
independent PowerShell processes serialized identical nested dictionaries in
different orders. New preview hashing now sorts keys without changing historical
journal serialization. Both legacy and ordinary pair public CLI tests perform
preview and upgrade in separate processes; the complete pair upgrade suites
passed 20 tests. The rejected preview, unused candidate and original output are
retained rather than relabelled as a successful installation.

A new compiled candidate then completed the reviewed legacy pair installation.
The dated Desktop link retains its prior Windows file identity, the Start menu
link remains the same entity, and the added native helper and repaired launcher
match their recorded bytes. Current native settings and the original migration,
adoption and configuration-upgrade receipts remained intact. The unused old
prepared launch plan was separately withdrawn with its complete original files.

After explicit retirement of a proven-dead Web instance, a receipt-bound runtime
cutover updated 15 code files. All 62 installed code files and the public entry
matched current source, and the installed command facade passed its read-only
check. Old runtime bytes and abnormal Web records remain retained; unresolved
legacy first-install ownership is not converted into a new ownership claim.

The new request-free Web startup encountered a disconnected Windows desktop
before launching its browser. Its zero-request service was explicitly stopped;
saved login and connection settings remain. This is not evidence of a ChatGPT
login requirement. Real exit/update/reopen, post-upgrade ordinary Local/API/Web
continuation and actual voice remain unaccepted pending their own observations.

The startup preflight exception is now inside the owned session's failure
boundary. A locked/disconnected desktop or changed source closes that session
before browser launch and records only a fixed failure code. The service leaves
`preparing`, publishes `unavailable`, and fences new requests while retaining an
explicit stop path. All 37 lifecycle tests passed, including zero-launch,
zero-request cases and refusal to restart the closed session after conditions
improve. The first new integration assertion expected the wrong existing health
state; it was corrected to distinguish stopped admission from service availability,
and its original failure remains recorded. These are disposable fixture checks,
not a successful live browser startup or model conversation.

After independent review, the saved stopped profile was explicitly rebound to
the same settings and updated source. A separate digest-bound cutover deployed
this one runtime file and retained its complete predecessor backup. Final
read-only verification matched all 62 installed files to source, preserved the
pair fingerprint and current native configuration, and confirmed stopped
Operator/router/Web services with empty actionable inbox and callback queues.
The Windows desktop was still disconnected, so no new browser or model request
was launched and the remaining live acceptance gates were not marked complete.

### 2026-09-30 native client update: read-only and synthetic evidence

The installed official Desktop package was separately observed as 26.928.2636.0,
with its exact executable path and digest retained privately. A fresh native
App Server using CLI 0.159.2 returned GPT-6.1 Sol as a visible default model,
with low configured and low/medium/high/xhigh/max/ultra advertised. The probe
preserved the current configuration and model-cache bytes, timestamps and file
identities. It started or resumed no task and sent no model request. This is
native metadata evidence, not live Desktop picker or model-execution acceptance.

Seven private synthetic checks passed. The dynamic native catalog preserves
GPT-6.1 entries and unknown fields; Channels accepts the complete model identifier
and advertised ultra effort while rejecting the ambiguous sol alias. Business
delivery retains the selected arguments, and Beeper remains Luna/low. An existing
router cache rejects an unlisted native slug without dispatch or automatic
refresh. After an explicit catalog refresh, a different new request passes through
unchanged; the rejected input is not replayed. One initial harness assertion
expected the wrong error field; its failure remains retained, and only the
harness was corrected. No production compatibility change was needed.

The dated Web catalog remains separate and gains no GPT-6.1 entry from this
native update. These checks do not establish Web readiness, cold-launch/reopen
acceptance, voice or broad Desktop compatibility. Any new handoff must bind the
current official executable separately from the CLI and retain older manifests.

The unlocked desktop allowed a later zero-request Web startup to reach an empty,
logged-in temporary chat. Closing its assistance window then made the worker
unavailable. That failure and its explicit normal stop remain retained. Source
inspection found that the Host's existing `modernRows` diagnostic field was
missing from both strict Python field tables; the deployed bytes matched source.
No evidence tied this defect to the native model update.

The fix adds only those two field declarations. Exact shapes, enums, assistance
identity, phase order and the requirement for zero modern message rows remain
unchanged. All 39 Python lifecycle tests and 59 Node browser tests passed,
including actual Host diagnostic functions and emission expressions delivered to
the Python receiver. Independent review confirmed the two-line production diff.
The saved stopped profile was explicitly updated with the same settings, and a
separate digest-bound cutover deployed one runtime file. Read-only checks matched
all 62 files, the public entry and existing pair fingerprint, preserved the
current GPT-6.1 native configuration, and found no actionable inbox or callbacks.
These deployment and fixture results alone do not establish cold-launch or live
conversation acceptance.

The next source-bound Web instance became ready while hidden, without assistance
or a model request. Explicit reuse saved its exact session receipt; a fresh
request-free router was started and bound to that generation. Native routing
remained protected. The initial unified preview rejected the older legacy
activation recognizer, which required the pre-pair manifest and build bytes.
Its original retirement evidence was intact; this was another entry integration
defect, not evidence that GPT-6.1 routing failed.

The read-only recognizer now accepts only a completed legacy entry pair whose
first historical build matches the original config-upgrade receipt. It validates
the current build through the complete pair ownership chain, rechecks bounded
files, and preserves all original retirement, process and exclusive-port gates.
Fifteen tests passed, including an actual temporary Windows migration/adoption/
config-upgrade/pair chain and 19 mutation categories with unchanged file-byte
snapshots. Independent review passed. Forty-seven preparation/cold-start/handoff
tests also passed; the verifier source is now bound into fresh review digests
and handoff manifests. A new live preview accepted the complete old-to-current
chain, leaving only Desktop-open and native-protection conditions. No old
receipt was rewritten or retirement repeated, and no model request was sent.

Later preparation failed before writing a plan; a second attempt retained an
ordinary empty allocation after its exact readiness digest changed. Bounded
subsequent observations found Desktop refreshing the cache timestamp with an
unchanged catalog. Those observations do not retroactively establish either
failure's complete cause. The current GPT-6.1/xhigh native settings remain
preserved rather than restored to an earlier snapshot.

Preparation now freezes the exact existing config/cache bytes and Windows
identities before directory allocation, rechecks full readiness and retains the
short read handles through journal completion. Sixteen preparation tests passed.
A separate explicit empty-allocation archival operation binds the original
failure JSON, source identity and current protected snapshots. It moves the same
empty directory by one Windows handle rename, retains the failure, and keeps a
completion fence until its post-receipt witness. It creates no plan, journal or
installation ownership. Thirty-seven withdrawal tests passed, covering old and
new archive coexistence, actual Windows sharing and rename behavior, partial
archives and final-boundary mutations. Independent review found two boundary
gaps during development; both were fixed and their failure evidence retained.
Seventy-four combined preparation/cold-start/handoff/supersede tests passed with
unchanged source hashes. These scoped counts overlap earlier runs.

The idle router and Web service were explicitly stopped and witnessed before a
separate runtime transaction deployed the new public entry commands. A fresh
Web instance then became hidden-ready; its exact session was explicitly bound
to a fresh router with zero inference requests. The real empty allocation was
witnessed into its independent archive with its original directory identity and
failure copy. Read-only verification matched all 62 runtime files, the public
entry and unchanged pair fingerprint, retained the current GPT-6.1/xhigh config
and native protection, and accepted all four retained archive generations.
These source, deployment and preparation checks do not yet establish normal
Desktop exit/reopen, ordinary same-task model continuation or voice acceptance.

The owner later performed a normal Desktop exit during a new handoff. That
handoff reached `consume`, reported `unified_cache_changed`, retained its
exclusive attempt and stopped for review without trying to reopen Desktop or
sending a model request. The owner manually reopened the official application.
Read-only inspection found no cache-retirement backup, config transaction or
completion receipt. Current config differed from the retained native original
only in Desktop's Computer Use pipe; GPT-6.1 Sol/xhigh and the official native
provider remained selected. The current cache retained its original Windows
identity and catalog, with only `fetched_at` changed. This later observation does
not identify the original writer or prove the complete failure cause.

Source inspection found an unprotected in-place-write gap between the
consumer's full preflight and cache retirement. The consumer now holds a Windows
read handle denying writes through preflight, retirement and completion. Delete
sharing retains the existing one-shot rename; exact byte and identity checks
still reject path replacement before or during that move. Missing-cache and
reappearance checks are unchanged. The config parent is held against directory
rename, and every created attempt remains terminal. No timestamp is filtered,
no failed plan reset, and no business request replayed.

One initial test expected a native Win32 error from Python's ordinary file API;
its original failure log is retained. The assertion was corrected to check the
observed permission-denied errno and rejected child-process write. Seventeen
cold-start tests passed, including real Windows writer contention, an already
open writer, equal-byte identity replacement, a rename-boundary swap, missing
cache creation and interruption. A combined 138 preparation, cold-start,
handoff, marker-release, supersession, retirement and withdrawal tests passed;
these counts overlap. The exact idle router and Web service were normally
stopped, with process absence, exclusive router-port reservation and empty
actionable inbox/callbacks checked before source changes.

This consumer fix is source evidence, not a repaired real activation or a new
Desktop acceptance. The original failed attempt and released-marker evidence
remain in place. Ordinary retirement deliberately rejects attempts without a
completion witness; the failure therefore needs separate explicit reviewed
maintenance before a new plan can be prepared. The old source-pinned workflow
must not be edited or rerun to bypass that boundary. Same-task model and voice
acceptance remain pending.

A separate native-entry recovery preview selected only the absent protection
marker and the verified entry configuration. The existing recovery command
retained the original entry and completed both changes with no warnings. Exact
post-checks matched the entire failed activation tree and current config bytes
and Windows identity. The entry is now native, the protection marker is restored,
and the owner's running Desktop was neither closed nor restarted. This recovery
does not retire or repair the failed attempt, deploy the consumer fix, or finish
the pending unified model acceptance.

Separate reviewed archival now has a narrow source implementation for the exact
September 30 cache-prewrite consumer and saved failure result. It checks the
retained marker release, native-entry recovery, stopped services, empty inbox
and callbacks, workflow and ownership evidence before allocating an independent
archive. The original failed attempt keeps its verdict; no completion is
manufactured and no config, cache or entry bytes are restored by archival.
Current root native effort may be reviewed within the observed native values,
while all other config changes retain the existing conservative checks. This
does not widen ordinary retirement or any cold-launch equality check.

Disposable tests cover the actual Windows directory move and its required
closed-child-handle boundary. Original bytes are copied before that boundary;
changed children, directory replacement, destination collision and final source
changes retain a completion fence and remain uncertain. Current native files
stay guarded through the move. Static archive integrity gates also block new
preparation and uninstall when any independent archive is incomplete. The
dated historical consumer fixture is provenance only. A combined 158 tests and
a final 66 failed-archive/handoff tests passed; these scoped counts overlap.
Full regression, real archival, workflow renewal and Desktop acceptance remain
separate pending steps. The owner's current GPT-6.1 Sol/high preference remains
preserved. Existing failed records have not been reset or replayed.

The first full traversal used a base interpreter without the optional aiohttp
dependency. It ran 1,236 Python cases in 1,241.321 seconds, with one failure and
nine errors, all reporting that missing dependency, and 115 skips. All 134 Node
cases passed. That unsuccessful log remains retained. The existing saved venv
then ran all affected modules, including the optional aiohttp cases previously
skipped: 351 cases passed in 87.197 seconds. These runs overlap; they are not a
claim that the first traversal passed or that every opt-in CLI gate ran. No
dependency was installed and no real model request was sent.

A fresh real review then archived the exact failed allocation in its independent
namespace. Post-checks matched the complete original tree and Windows identities,
retained the failed attempt without a completion, and matched current config,
cache, marker and entry snapshots. The current native effort is high, as selected
after the owner's manual reopen. A separate stopped runtime transaction updated
one public entry file and its source binding, retaining all originals. Read-only
verification matched all 62 runtime files and protected integrations, empty
inbox/callbacks, stopped Web state and an exclusively reservable router port.
No Desktop restart or routing activation occurred. The old source-pinned startup
workflow remains retained; its renewal, fresh handoff and live model/voice
acceptance are still pending.

The replacement workflow now has a separate source implementation bound to the
completed failed archive, original workflow identities, exact recovery path,
entry ownership and current protected native state. It retains the old directory,
creates a current source-pinned workflow and reselects the original entry bytes
with the existing replacement witness. It does not mutate the historical plan
or prepare/arm an activation. Partial renewal gates preparation and uninstall.
The first disposable run exposed a wrong use of the archived recovery copy;
that failed log remains retained. The implementation now checks the original
recovery path and its retained identity. Six cases passed after that correction,
then 83 combined renewal, preparation, handoff, upgrade and uninstall cases
passed, including four additional sharing, source and backup-identity boundaries.
Those counts overlap. Full regression and the real renewal remain separate.

The saved dependency-complete environment then ran the full suite: 1,454 Python
cases passed in 1,360.091 seconds, with 26 explicit opt-in CLI cases skipped;
all 134 Node cases passed. During that run a final optional-entry-file presence
check was tightened. A separate fresh 11-case renewal run passed, including
the added later-owner-file boundary; it is supplemental, not an additional
11 distinct full-suite cases. Source syntax, inventory and content audit passed.

A fresh real preview then completed the independent workflow renewal. Checks
matched the old workflow bytes and Windows identities, retained the failed
activation archive, verified the new source-pinned workflow and reselected
the exact recovery-bound entry bytes with unchanged ownership. Native config,
cache and protection snapshots matched, all 62 runtime files and the public
entry matched their sources, and no Desktop restart, routing activation or
model request occurred. The saved Web configuration was current and normally
stopped before one explicit new service start. Fresh cold-launch and ordinary
same-task model/voice acceptance remain separate pending gates.
A live preparation preview then exposed one remaining compatibility gate:
legacy pair retirement compared its historical workflow against the explicitly
renewed current files. Read-only recognition now binds the complete renewal,
old workflow identities, current replacement identities and retained failed
archive, while all original upgrade/pair/retirement checks remain active.
Thirteen real Windows renewal cases and sixteen retirement cases passed.

A fresh full run partitioned all 81 canonical Python modules exactly once among
four independent disposable test processes, with Node tests in one partition.
Raw summaries report 1,458 Python cases OK and 134 Node cases passed, zero Node
failures. Python sources remained byte-identical through the run. The collector
exited 1 after children completed because a retained Windows console log was not
UTF-8; no child exit-code receipts were retained. Independent read-only review
verified every complete unittest OK summary and the Node result without rewriting
raw logs or reclassifying the collector failure. Source/PowerShell syntax and
inventory audit passed. These tests and the real no-write preview do not establish
cold-launch, model switching, conversation continuity or voice acceptance.
2026-10-01 follow-up: the owner's normal exit was observed, but the bound
router process was absent at the handoff check. A separate reviewed stopped
router handoff then failed before plan supersession and safely reopened native
Codex. Its terminal result remains `stopped_for_review` with
`handoff_unexpected_error`, not successful activation. Current direct and
independent read-only diagnostic previews passed; they cannot reconstruct the
old missing cause. The untouched, unarmed plan was independently withdrawn
with complete originals and current snapshots retained; native config, cache
and entry were unchanged. An explicit idle Web stop reached saved `stopped`
status. The first immediate status observation raced worker shutdown and was
retained separately; no duplicate stop or request replay occurred.

The handoff now preserves allowlisted typed supersession/preparation/file codes
and bounded Windows error numbers in its new terminal results. Unknown text and
untyped lookalikes remain redacted. It does not change admission, activation,
retry, recovery, permissions or old outcomes. Fifty-seven affected cases passed.
Fresh full coverage of all 81 canonical modules in four disposable processes
passed 1,460 Python tests; Node passed 134, failed zero. Every child exit code
was zero and Python source hashes were unchanged throughout. Raw console bytes,
child exits and prior collector failure remain separately retained. Source and
syntax audits passed. A fresh independent background preparation and live
cold-launch acceptance remain distinct from these diagnostic checks.

The next independently prepared background router survived the owner's normal
Desktop exit. A fresh handoff completed supersession, preparation, marker release,
arming, config/cache consumption and witnessed official-package reopen. Retained
before/candidate copies, boundary backup, retired cache and their original Windows
identities matched the plan and completion. The old failed attempts were retained.
After reopen, only Desktop's managed CUA pipe value differed from the candidate;
the strict transaction inspection remains `uncertain`/`target_not_candidate`.
The independent read-only review reports this explicitly and matches the current
native default/high setting, registry and exact idle Web/router bindings. It does
not reclassify the strict current-target check or retry an activation.

Ordinary Desktop selection then displayed native, Local, API and Web model rows
in the exact existing local acceptance task. One new input selected GPT-6.1 Sol
with low effort through its ordinary picker and composer. The saved new turn's
model/effort metadata agrees, but the turn failed after 2,840 ms with
`array_above_max_length` on `input[4].content` (maximum zero, observed one), with
no assistant answer or tool call. Its remaining four continuity inputs were not
submitted. The old successful Local turn, old compaction failure and this new
native failure remain preserved. A plaintext, unencrypted Local reasoning item
exists in history; because the complete upstream packet was not captured, its
exact correspondence to the reported input index is an inference. Native wire
passthrough and reasoning representation remain unchanged. The current receipt
does not establish same-task conversation or voice acceptance, nor publication.

## 2026-10-01: native-first direct entry research and pure candidate

The owner chose provider/model switching through the extension entry, accepted
limited custom-model capabilities and prioritized keeping official native traffic
direct. This new candidate does not deploy a model menu, mutate the real config,
change shortcuts, start/stop services, rewrite history or revive an old plan.

Fresh CLI 0.159.2 standard and experimental schema exports still lack provider
identity in model entries and per-turn/settings updates; start/resume/fork retain
it. The exact installed Desktop 26.928.2636.0 ASAR was read without execution or
modification. CODEX_CLI_PATH is present, but no production wrapper was adopted.
The Windows package diagnostic did not inherit its process marker. The legacy
base-config `profile` selector was rejected with a specific error; the first
generic-error and temporary-directory-cleanup failure remain retained separately.

Two independent synthetic direct-provider cases used the installed CLI and a
private, account-free home. One resumed the same UUID across native, external and
native providers, retained text history and completed three distinct new inputs
at the expected direct endpoints, exactly once each. The other retained foreign
reasoning content; its native return turn was rejected and remained failed. That
case passed its negative-boundary assertions, not native conversation acceptance.
Neither used the Operator router, contacted a real model or touched real history.

The new `operator_direct_profile.py` pure projection/recovery and read-only
preview reuse the installed native profile contract. Seventeen meaningful checks
passed. The preceding combined run passed 56 checks: the then-16 candidate checks
and 40 existing native-profile/recovery checks. The final 17-check run follows
recovery-description validation changes; overlapping totals are not added.
Seven actually installed API/Local profiles passed source-bound previews against
a private proposed-native snapshot, with `baseline_is_live_config=false`.
That does not prove current native configuration, endpoint connectivity or tools.

A third, fresh installed-CLI case used the actual new renderer and recovery
output. Its same UUID completed three native/external/native turns at three
expected direct requests, with text history and byte-identical restored config.
It remains a synthetic CLI check. Live Desktop, entry transactions, independent
native recovery, current cache and each real model require their own acceptance.
The already installed native entry's read-only check currently reports
`normal_exit_required`; no real configuration or launch occurred.

Current Chat On Steroids research is pinned to `2524773c8b4389c27f6c420c6a27f5a14bacbe4d`;
its Desktop bridge is still a design draft. For entry isolation alone, the MIT
Codex Desktop Custom Models architecture was read at
`10a8954ea2d8fd57d6b8943dc3c035df2e18e1ab`. Its app clone, separate home,
Chat Completions proxy and automations were not adopted. No upstream code was
copied or installed. The new direct candidate and its limitations are documented
in `models/common/docs/direct-profile-entry.md`; older evidence stays unchanged.

## 2026-10-01: actual native recovery after reported reopen

The owner reported reopening in native mode. Exact packaged Desktop processes
had new birth times, but the observed disk still selected the unified provider,
with no native protection. The exact shortcut fields and frozen native helper
were checked; its read-only status required normal exit. No cause is inferred
from the owner's report alone. The old bound router PID was absent; a lifecycle
GET at its saved port timed out and no listener was observed. This is not a clean
service-stop receipt or permission to restart/replay an old plan.

The existing standalone official-route recovery preview passed without warnings.
Its explicit application completed only its managed config/entry/protection
changes and retained private originals. A subsequent preview showed native mode
with no remaining changes. No Desktop process was killed, model request sent,
history rewritten or custom entry deployed.

One fresh native App Server ran initialization, `config/read`, and a single
bounded `model/list`. It loaded the official default provider and eight native
model identities. Its config and model-cache snapshots remained byte-identical.
All seven saved native API/Local profiles then passed source-bound previews
against the current real native config, with `baseline_is_live_config=true`.
These are configuration/catalog/preparation evidence, not real endpoint or main
window acceptance. The existing running Desktop predates the recovery and its
native entry check still returns `normal_exit_required`. Cold main-window
acceptance and direct entry deployment remain pending. Old failures and uncertain
lifecycle evidence stay retained.

## 2026-10-01: native cold-start review and durable direct-entry source

After the owner's next normal restart, every observed process belonged to the
exact official package and was born after the actual native configuration
recovery. The current config still selected the official default provider, with
native protection and no custom root catalog or active unified/direct projection.
The only parsed difference from the retained recovered native bytes was the
native tool's CUA pipe leaf. Config stayed unchanged during this read-only
review; actionable inbox and pending callbacks were zero. No diagnostic model
request or task operation was sent. This establishes configuration and startup
order, not a selected task's observed upstream packet or voice acceptance.

New canonical source adds immutable profile plans, one-shot direct cycles and
witnessed Windows config replacement. The independent PowerShell helper restores
only validated owned bytes and retains later settings without Python or model
services. v1 remains strict; explicit v2 permits only the same manifest model and
listed effort values. A new recovery epoch retains exact native-after bytes and
completion time; the running-native guard accepts only an exact later CUA pipe
change. Legacy recovery dates do not acquire this authority. Per-cycle Shell
launch intent/result records retain failed or uncertain attempts without replay.

The chooser and pair build bind a separate direct workflow and retain the legacy
origin, original files and every prior ownership step. Retirement preview now
binds the current CUA-only delta after validated historical recovery. Archived
entry witnesses distinguish current and historical checks; no previous build or
failed result is rewritten. Actual retirement, archive, direct entry installation
and real model/Desktop acceptance remain unperformed at this source stage.

Targeted tests cover real disposable Windows replacement, independent recovery,
later CUA/effort changes, poisoned records, stale sources, pending cycles,
credential scope, picker cancellation/process identity and failed Shell attempts.
Earlier source-digest races, a test-placement error and diagnostic stderr decoder
errors remain retained as development failures. The native-epoch test exposed
PowerShell ISO-date coercion; its repair reads the original JSON string and the
five revised epoch checks pass. The initial private restart-observation script
had a syntax error before any record/write, then the repaired bounded review
completed. Full regression and candidate readiness are recorded separately.

The frozen implementation's full run completed 1,544 Python tests in 1,414.159
seconds, with 26 skips and three failures limited to the already loaded legacy
pair fixture missing the new immutable profile-plan binding. The failure log
remains unchanged. Only that test fixture was corrected; its fresh nine-test
suite passed in 146.824 seconds. All 134 Node tests passed. This is a full run
plus an affected-suite correction, not a rewritten successful full-run receipt.
No implementation source changed between the compiled candidate, the full run
and the corrected affected suite.

The actual private candidate and seven direct plans passed a separate read-only
review of all 76 script-source bindings, exact Python/helper/entry identities,
candidate files and seven live-config previews. Config, cache, protection and
the owned live entry stayed byte-identical. The current release source collector
accepted 254 files and five reviewed documents; 162 Python source files compiled
without imports. The candidate remains uninstalled and the old unified plan has
not been retired or archived.

Cold entry selection changes the application default provider, not a per-task
provider boundary. Existing task model caches, automatic Desktop tasks and
foreign reasoning history remain separate live acceptance risks. An entry
upgrade followed by native opening does not establish custom-model routing or
same-chat acceptance. No custom turn is dispatched by the planned maintenance
handoff.

After that frozen candidate review, the canonical maintenance renderer gained
one additive `native_entry_updated` outcome for this private entry-maintenance
handoff. Existing `complete` behavior is unchanged. It explicitly labels entry
upgrade plus native opening rather than implying custom-model activation. Its
PowerShell parse check and eight existing feedback tests passed in 7.321 seconds.
This later renderer change is separate from the retained full run and does not
change any candidate or direct-plan source binding.
