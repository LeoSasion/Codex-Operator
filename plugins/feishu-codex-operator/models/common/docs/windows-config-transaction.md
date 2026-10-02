# Windows config replacement witness

`operator_core.windows_config_transaction` is an independent, one-shot primitive
for an existing `config.toml`. The reviewed
[unified cold-launch consumer](unified-cold-launch.md) now calls it, while the
disposable tests still use temporary directories only. No real Desktop
activation has been verified from that integration.

The caller first takes `observe_config`'s exact bytes and Windows volume/file
identity, then supplies a reviewed candidate and a controlled state directory
on the **same volume**. The primitive holds the old file open for reading with
`FILE_SHARE_READ | FILE_SHARE_DELETE`. This excludes ordinary writers; an
already-open writer prevents the guard from being acquired. It also holds the
target and state directories against rename. It writes and flushes an original
copy, candidate copy, staged replacement, and intent before the native call.
The intent contains hashes and identities, not configuration text.

`ReplaceFileW` receives an unpredictable backup path inside the newly created
private transaction directory. On this Windows/NTFS host, the successful target
has the staged file's identity and the backup has the file replaced at the call
boundary. The primitive compares **both exact bytes and both file identities**,
then records a verified receipt while the resulting target and backup are held
against further ordinary writes or renames. `inspect_transaction` can make the
same read-only comparison after a process crash. It never repairs or retries.

The old guard must allow delete for `ReplaceFileW`, so an external actor can
rename the old path and put a different file there between the last check and
the call. In 20 deterministic test races, `ReplaceFileW` succeeded, but its
backup contained the external file and the identity/byte check returned
`uncertain`. That backup and the prior original copy were retained. A separate
post-replacement edit is likewise `uncertain`. Every native error, including
documented partial-error outcomes, leaves the transaction files for review.
The caller must not start Desktop or claim activation from an `uncertain` result.
An `applied` result witnesses the state while locked; a later edit requires a
fresh inspection before using that result.

`ReplaceFileW` overwrites an **already existing backup path** on this host.
The primitive therefore uses a unique empty path in an owner-only transaction
directory; callers cannot supply a backup filename. This is a concurrency
protocol for ordinary external editors, not protection against a malicious
same-user process manipulating the private directory. It covers file bytes and
identity; it does not attest to all ACL, alternate-stream, or metadata changes.
The `REPLACEFILE_WRITE_THROUGH` flag is unsupported, so a sudden power failure
is not claimed to be a fully durable, atomic multi-file transaction. Missing
or inconsistent artifacts after any crash classify as `uncertain`.

References: [Microsoft `ReplaceFileW`](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew),
[Microsoft `CreateFileW` sharing modes](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).
