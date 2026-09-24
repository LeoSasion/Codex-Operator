# Web model catalog

The public ChatGPT picker observed on 2026-09-23 offers GPT-5.6 Sol and Latest,
each with five slider positions: Instant, Medium, High, Extra high and Pro.
The response-level "Switch model" menu identified a reply sent with Latest/High
as **GPT-5.6 Sol**. It identified Latest/Pro as **6 Pro**. The Pro header alone
therefore cannot establish that ordinary Latest positions use GPT-6. GPT-5.5
is marked for retirement on October 14 and is not added to this catalog.

| Codex Web entry | Native reasoning choices | Public Web selection |
| --- | --- | --- |
| Web GPT-5.6 Sol | none, medium, high, xhigh | GPT-5.6 Sol, positions 0–3 |
| Web GPT-5.6 Pro | max (fixed) | GPT-5.6 Sol, position 4, 5.6 Pro |
| Web GPT-6 Pro | max (fixed) | Latest, position 4, 6 Pro |

The earlier unverified `Web GPT-6 Sol` preview entry has been removed: it
would label a GPT-5.6 Sol reply as GPT-6. Native official GPT-6 models are
unchanged. A Web GPT-6 ordinary entry requires its own observed selection
and response-level model identity before it can be published.

Pro is a separate model entry. Its sole native `max` value is a local selector
representation for the Web Pro position; it does not assert equivalence with
API `reasoning.effort=max`. Web Instant maps to `none`. No low, minimal or ultra
option has been observed in this Web picker, so those settings are rejected.
The existing GPT-5.6 Sol slug retains its high default.

The Python service and browser host share `operator_core/web_model_catalog.json`.
Every request carries its exact model and effort. The host checks the selected
radio option, slider range, visible effort label and explicit Pro generation
header before dispatch. The in-app browser displayed `5.6 Pro`, while the
managed Electron page displayed `5.6 Sol Pro`; both exact 5.6 forms are
accepted only after the GPT-5.6 Sol radio option is checked. The header may
update after the slider value, so the browser waits for a named Pro header
before comparing generations. The slider's public description may prefix the
effort with `5.6` or `6`; the host reads the effort and announced generation
separately and rejects disagreement with the selected model. Latest alone is insufficient evidence for GPT-6. A
changed generation, ambiguous option or unavailable control stops that request.
All entries share one browser, admission gate, MCP endpoint and consumed-turn
ledger. Changing the selected model cannot enable parallel dispatch or replay.

The catalog is published only for a checked service that advertises its complete
model list. Native catalog rows and existing WebSocket/request snapshots retain
their identities. Independent Desktop preparation includes all advertised Web
entries, but preparation is distinct from the running Desktop's picker and its
provider routing. Do not reactivate global routing after native recovery merely
to display additional names.

Reference: [Chat On Steroids, commit 750fad9](https://github.com/totec448-spec/chat-on-steroids/blob/750fad9378a0cf9e37791916b11f7ed9add645dd/src/shared/chat-models.ts).
Adopted ideas are exact model aliases, preservation of the selected generation
and separate Pro identity. The implementation is independent; it imports no
upstream runtime, orchestration, retry or permission behavior. API documentation
is a separate source and cannot establish an account's Web picker options.

Validation records must separate public menu observation, isolated protocol
tests, actual Web generation, native CLI calls and live Desktop acceptance.
Model self-reports and menu presence alone do not establish backend identity or
successful tool execution. A stopped launch that was never bound may be explicitly
retired only with a request-free stopped snapshot, absent exact processes,
dependencies and tunnel marker, and an exclusively reservable listener port.
Retain originals without fabricating worker ownership, replaying or launching.

## Verification on 2026-09-23

- Corrected three-entry catalog: 866 Python cases (856 passed, 10 existing
  skips), 88 Node checks at that stage, five focused Python catalog checks and
  the 183-file inventory/syntax audit passed. The later plain-composer check
  brought the passing Node count to 89.
- Fresh isolated native App Server after correction: three visible entries
  and six choices appeared, with no model request or main configuration change.
- In-app browser: four serial exact-text replies passed. Their response menus
  identified GPT-5.6 Sol for both explicit GPT-5.6 High and Latest/High,
  GPT-5.6 Pro for explicit 5.6 Pro, and 6 Pro for Latest/Pro. This corrects
  the earlier inference that Latest/High was GPT-6 Sol. The other live
  effort combinations were not generation-tested.
- Managed provider: the saved-profile inspection failed before dispatch; an
  explicit assistance window later remained blank. A local page rendered in
  the same surface implementation. The exact service was stopped without a
  model request, login reset or replay. The initial blank page supplied no
  actionable verification evidence. Later foreground inspection did show the
  actual Cloudflare human-verification checkbox. A prior foreground probe reached the
  composer without finding the expected model control before its deadline;
  its cause is unconfirmed and that failure is retained.
- A later request-free foreground review reached the authenticated page and
  passed the existing model-control check after loading. The earlier missing
  control does not establish a selector defect.
- The first managed-provider sample for GPT-5.6 High ended at a real
  background Cloudflare challenge before browser model dispatch. After the
  same worker reached a normal page, two distinct new samples stopped before
  dispatch at the Pro-header check: the first rejected the observed
  `5.6 Sol Pro` label, and the second timed out while waiting for a label
  format it could not accept. The exact observed format is now handled by
  the checked selector. A further new sample encountered another Cloudflare
  challenge on a new hidden-page navigation. The assistance window visibly
  contained the verification checkbox, then closed without passing its ready
  check. That old service was explicitly stopped before the catalog change.
  Every
  failed request remains terminal, no MCP tool call was accepted, and none
  was replayed. At that stage managed generation still needed fresh acceptance.
- After the catalog correction, two distinct serial requests reached the
  effort selector and stopped before dispatch. Bounded diagnostics showed the
  slider moving from position 3 to 4 and the exact `5.6 SolPro` header, while
  its effort label remained unrecognized. The current page announces a
  generation-prefixed label such as `5.6 Pro`; the parser previously expected
  `Pro` alone. The parser now supports the observed prefix and verifies its
  generation separately. A subsequent request-free assistance page showed an
  actionable Cloudflare checkbox after a new service start. It later reached a
  normal composer in both the screenshot and accessibility view; this did not
  require resending any failed request.
- A distinct new GPT-5.6 High managed sample then passed the checked model and
  effort selector and dispatched exactly once. The page's generation POST
  returned HTTP 403. The provider surfaced the fixed, non-retrying
  `web_model_http_rejected_no_retry` failure in a local HTTP 400 envelope and
  closed the failed browser worker. There was no completed Web answer or
  accepted MCP tool call. The 403 establishes an upstream HTTP rejection of
  this dispatched request; it does not identify the upstream reason or prove
  that another human verification is needed. The failed input was not replayed.
- After an explicit stopped/reconfigured service start and a request-free
  ready-page check, five distinct, serial managed text samples passed: all
  four published GPT-5.6 Sol efforts and GPT-5.6 Pro. Each verified its chosen
  public model and effort, received HTTP 200, and returned its exact marker.
  These samples requested no native tool execution; they do not reclassify the
  earlier 403 or prove server-side model identity.
- The first managed GPT-6 Pro sample stopped before dispatch because its
  visible heading was only `Pro` although the slider announced `6 Pro`. The
  selector now accepts that exact pair only after checking the Latest radio
  option. A different new GPT-6 Pro sample passed that selector, then stopped
  at `web_prompt_text_mismatch` before browser dispatch. The editor check now
  briefly reobserves already inserted text without typing or sending again.
  A further distinct GPT-6 Pro sample passed selection and exact composer
  verification, dispatched once, and received HTTP 403 from the ChatGPT
  generation POST. No answer or tool result was accepted and it was not
  replayed. All 88 Node checks pass.
- A separate new in-app-browser Latest/Pro text sample returned its exact
  marker, and that reply's model menu identified `6 Pro`. The page also showed
  app choices, but no app action was requested. This confirms a direct-browser
  text reply for the account, not managed Electron access, MCP execution, or
  the cause of either managed 403. The previous Latest/Extra high selection
  was restored.
- After request-free hidden-page preparation was installed and the saved
  service explicitly restarted, one further fresh **managed GPT-6 Pro** text
  request completed over the checked local provider: HTTP 200, `completed`,
  one exact random-marker output, and ready/idle status afterward with no
  assistance window. The request selected `Latest`/Pro through the managed
  page and asked for no tools. The provider-projected model slug is not
  independent backend attestation; this pass does not change either earlier
  HTTP 403 outcome or establish native Desktop/tool acceptance.
- At that stage, Main Desktop retained the native direct route. Global catalog
  activation, native tool roundtrips with these entries and the live picker
  were pending.

The in-app browser's login and successful replies cannot establish readiness
of the separate saved browser profile used by the provider.
After the later managed 403, an explicit stopped/restarted saved service was
observed request-free. Its new assistance page briefly showed a verification
checkbox and later showed a normal composer; no human click was confirmed.
The checked assistance window was closed and the service returned to ready
without another model request. A fresh-start challenge should be allowed to
settle and rechecked before asking the owner to act.

Two new, separate native CLI coding fixtures then exercised the managed
GPT-5.6 Sol/High path. The first stopped before browser dispatch at
`web_prompt_text_mismatch`; its multi-line editor representation exposed a
plain-composer comparison that relied only on `innerText`. The composer now
also accepts the exact ordered paragraph structure already required for
connector prompts, without changing or resending the input. All 89 Node
checks pass, including changed/extra paragraph and unexpected-pill rejection.
The second fixture passed model, effort and composer checks and dispatched one
generation POST, which returned HTTP 403. Neither fixture delivered an
`operator_call`, modified its synthetic file or ran its tests. Both failures
remain terminal and distinct; the later 403 has no confirmed cause and does
not prove a current human-verification requirement. Those two cases did not
establish native CLI tool execution or live Desktop acceptance.

On 2026-09-24, a separate new isolated native CLI coding case explicitly
selected the published GPT-6 Pro/max route. It completed three paired MCP
operations against disposable files and five real passing tests, with zero
retries or rejected tool calls; the saved service returned to ready/idle.
This verifies one managed Web tool path, not the running Desktop picker or
independent server-side model identity. Earlier 403 cases remain failed.
The follow-up full suite passed 871 Python cases with 10 existing skips,
93 Node checks and the 183-file release inventory/syntax audit.
