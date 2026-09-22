# Feishu authentication and chat permissions

Use this reference only for setup/authentication diagnosis. Operator runs as the
Bot; user OAuth, Bot credentials, and Bot tenant permissions are separate checks.

## Initial setup

When setup is requested, the existing CLI workflow is:

1. `lark-cli config init --new` for official Feishu PersonalAgent QR registration.
2. `lark-cli auth login --recommend --no-wait --json` for user OAuth.
3. After the user completes the official page,
   `lark-cli auth login --device-code <device_code>`.

`--recommend` can include broad write scopes and changes with the CLI. Explain
its breadth; the authorization page is the list the user reviews. Forward the
returned verification URL unchanged and keep each QR in a dedicated temporary
directory. Do not print or persist codes/tokens in project files, restart a flow
to repair an audit failure, or reuse expired URLs.

## Verify independently

```powershell
lark-cli auth status --json --verify
lark-cli api GET /open-apis/application/v6/scopes --as bot
```

Report user validity, Bot validity, and tenant-scope audit separately.
`auth scopes` may show the user's scopes and is not the Bot audit.
Check tenant `grant_status`. User OAuth does not grant missing Bot tenant scopes;
follow the returned `console_url` and wait for the user/admin when required.

Locked identities and group @ gating remain the defaults. Receiving arbitrary
non-mention group messages requires the appropriate Bot tenant permission; a
successful QR login does not establish it. Permission grants do not authorize
unrelated future message or administration operations.

## Windows failures worth distinguishing

- Metadata/App ID in a copied `.lark-cli` directory is not proof of credentials:
  the secret/token may still live in the old machine's OS keychain.
- The filesystem sandbox can also hide valid credentials from a child CLI.
  Before reinitializing, use the supported credential-visible process for one
  read-only `auth status --json --verify` check. Do not print credential contents.
  If valid, reuse the existing setup; if still missing, report missing local
  credentials rather than a tenant-permission failure.
- Create the per-run QR directory and confirm the working directory before QR
  generation. An inaccessible temp path is not an OAuth failure. Correct only
  that directory's access and retry QR rendering with the same URL; never
  restart authorization merely to get a writable location.
- Local token metadata, live identity verification, and client UI login are
  distinct evidence. A timeout is unknown, not denial. For a read-only transient
  audit error, retry at most once (2 seconds for EOF/timeout, bounded Retry-After
  up to 30 seconds for 429); otherwise report the failure.
- Clean up the exact temporary QR directory after success, failure, denial, or
  expiry. Do not copy keychain entries, switch profiles, or recreate the app as
  a generic repair.

### Background credential context (2026-09-20)

The Windows WMI launcher reproduced a narrower failure: the interactive CLI
verified both identities, while its WMI child reported `not_configured`/`missing`
for the same application, user account, configuration paths and CLI executable.
Do not treat the shared account name as proof of an equivalent credential context,
or repair this by copying/exporting OS-protected secrets.

The Channels helper now uses `CreateProcessW` with the caller's token, no inherited
handles, hidden window and explicit job breakaway. It uses the caller's PowerShell
edition from `PSHOME`; directly launching Windows PowerShell 5 from a PowerShell 7
environment reproduced missing `Get-FileHash` because of the inherited module
path. A failed process creation remains terminal, with no WMI fallback. Existing
lease, process-identity, manifest, environment and lifecycle checks still apply.

Real isolated process tests check user-scoped DPAPI with synthetic data, module
loading, lease arguments and child survival after the parent exits. Live Channels
then reached `online` with its Feishu event consumer ready. This establishes
startup/ingress readiness only, not a user-message/Final Callback round trip.

## CLI compatibility and identity drift (reviewed 2026-09-20)

Lark CLI 1.0.96 was the latest version returned by the official update check on
this date. Use `lark-cli update --check --json` to inspect availability and Skills
synchronization without requesting an installation. Do not upgrade merely because
an older project-local skill copy disagrees with the installed command's help.

Before an owner-authorized user-identity channel test, resolve the current CLI
profile and compare its verified user `openId` with the exact durable P2P binding
and configured owner. Local configuration metadata uses `userOpenId`; those two
field names are not interchangeable. Compare values in memory, never print or
store raw user/chat identifiers in diagnostics. A different open ID establishes
a mismatch, not its cause: application scope changes and different users must be
distinguished before logging in or updating a binding. Do not switch to bot
identity, change the saved owner, or search unrelated chat history to make a test
proceed. A bot being ready does not prove the user's authorization is valid.

The [v1.0.90 release](https://github.com/larksuite/cli/releases/tag/v1.0.90)
excluded `im:message.send_as_user` from batch authorization sets. When that
explicitly requested capability is needed, inspect the actual granted scopes and
request the exact missing scope; `--recommend` alone is not proof of send-as-user
permission. A CLI user refresh token can expire independently of bot credentials.

The [v1.0.95 release](https://github.com/larksuite/cli/releases/tag/v1.0.95)
added optional concise IM output and improved credential/configuration error
handling. Exact reply verification continues to use JSON without `--concise`,
with a bounded recent time range and `--no-reactions`; never enable resource
downloads for a plain-text test. The
[v1.0.96 release](https://github.com/larksuite/cli/releases/tag/v1.0.96)
restricts chat creation to bot identity; it does not remove user-identity plain-text
sending. Test an already-confirmed P2P chat rather than creating another chat.

For bot ingress preflight, the current CLI supports
`lark-cli event consume im.message.receive_v1 --as bot --dry-run`. A ready result
checks preconditions only: it neither starts the Operator nor proves a received
event, Desktop relay, Final Callback or returned Feishu message.
