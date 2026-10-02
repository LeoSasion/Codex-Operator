# Unified native picker candidate

`scripts/operator_unified_desktop.py` is a test-only configuration transaction.
It creates a fresh marked Codex home below the OS temporary directory, previews
the proposed change, and can explicitly apply and revert it **only there**. It
does not copy login state, alter the real Codex home, start a service, create a
task, or send a model request. The real home is always rejected. An active
`operator-native-route-only` marker blocks preparation and activation; if it
appears after an isolated activation, explicit rollback remains available.

The candidate selects one stable `operator_unified_candidate` provider named
`Codex Operator`, using the router's exact `/backend-api/codex` alias and dynamic
`model_catalog_url`. Both native retry settings are zero. It pins missing
realtime call and WebSocket voice URLs to the official ChatGPT endpoint and
leaves an existing identical voice setting byte-for-byte intact. A separate
provider table is appended; parsed TOML comparison rejects changes to any
unowned setting. Config and cache originals are retained privately, the
journal is written before a switch, and an uncertain transaction is never
retried automatically. Explicit rollback removes only the exact owned bytes
and preserves unrelated later tables. One exact leading, wholly commented
legacy router block is retained byte-for-byte; other marker shapes conflict.
The name is functional: in the installed 0.158 client, `OpenAI` selects remote
compaction v2 for every model under that provider. The generic name selects
Codex's own text-summary compaction instead, including for native rows. The
router neither creates summaries nor invents encrypted compaction items.
See the version-bound evidence and limitations in the
[router contract](model-router.md#client-owned-compaction-2026-09-30).
Older exact `OpenAI`-named transactions remain recoverable; they are never
renamed in place or reactivated automatically.
Apply and revert require the disposable home to be idle. A cache that appears
before the terminal journal is rejected as uncertain, rather than reported as
a clean switch. An exclusive transaction claim prevents parallel apply/revert;
a claim left by a crash requires review and is not auto-retried. This does not
coordinate with an unrelated live App Server. The candidate's final snapshot
check and file replacement are not one atomic operation: an unrelated editor
can still change `config.toml` between them. This disposable writer must not
be promoted to a real Codex home. The separate reviewed
[cold-launch workflow](unified-cold-launch.md) now uses the tested Windows
[replacement witness](windows-config-transaction.md) to preserve both the
reviewed original and the exact file replaced at the native boundary.

This tests the configuration and recovery mechanism, **not** signed-in custom
provider authentication, current Desktop picker visibility, same-task
switching, voice, search, WebSocket behavior, or persistent startup. Existing
native tasks remain bound to their original provider. The separate real-home
path now has a one-shot cold-launch consumer and emergency native-only recovery;
uninstall still blocks on its retained activation directory until a reviewed
retirement exists. The standalone recovery source recognizes these exact
candidate blocks in disposable tests. On
2026-09-29 the existing owned recovery shortcut and its installed source were
updated through the project's retained-original transaction; read-only
inspection verified their target and current-source match. This does not
establish activation or uninstall ownership. The real recovery marker remains
in force. The stopped old Web activation record was retired once after exact
read-only preview and is retained in its private backup and archive; this did
not activate a replacement route.
Current transport and CLI evidence is in
[model-router.md](model-router.md#native-picker-candidate-2026-09-29).

`scripts/operator_unified_entry_preview.py` provides a separate read-only
`inventory` for the selected project and Codex home, plus `preview` when an
exact router state and port are supplied. It hashes the current and hypothetical
candidate config without writing either. Fixed blockers include the native-only
marker, any active or uncertain old Web activation record, stale recovery shortcut source,
and conflicting route settings. The output contains only digests and fixed
codes, not config text, paths or router tokens. A candidate digest is not an
activation plan or proof of Desktop readiness; the disposable apply/revert
contract above remains unchanged.

Focused local check (uses only temporary homes; no external network or model
request). With `CODEX_OPERATOR_TEST_CLI` set to an installed current Codex
executable, one additional case logs in with a synthetic key, loads the
**applied** candidate through a fresh App Server and confirms both synthetic
official and Web rows in `model/list` from a loopback catalog. This still does
not test the signed-in Desktop account or a model turn.

```powershell
python -B -m unittest discover -s plugins/feishu-codex-operator/models/common/tests -p 'test_unified_desktop_entry.py'
```
