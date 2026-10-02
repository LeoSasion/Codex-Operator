# Saved Web service: pre-initialization recovery

`scripts/operator_web_preinit_recover.py` is a separate, explicit maintenance
path for one failed saved-service launch. It accepts only an unchanged
`uncertain` launch record with the exact fields `version`, `attempt`, `phase`,
`pid`, `process`, and `runtime`. It does not change the ordinary
`models web recover` path, which requires a session and a stopped or dead
service snapshot.

This path is for the observed failure where the saved Python interpreter lacks
`aiohttp`. The saved `operator_web_model.py` imports `web_openai_tunnel.py`
inside `serve()` before it creates the attempt's state directory. That module
imports `aiohttp` before it can create a listener, browser or request ledger.
The command binds the saved process birth, interpreter binaries, saved settings,
and those two exact source digests. It runs one isolated import check in the
saved interpreter with the same `-E -s` import settings and source directory as
the failed child. The check makes no model request.

Before preview or apply, the command requires the recorded process birth to be
gone; the attempt state path and fixed tunnel marker to be absent; and the
saved browser and tunnel dependency binaries to have no running process. It
also requires the saved profile and settings to match. If any observation is
unavailable or changed, it rejects the retirement. The absence of a state
directory is a distinct pre-initialization inference: the command never
fabricates a `stopped` status or a zero-request snapshot.

Run `preview --profile <saved-profile>` first. It returns a digest and changes
no saved service record. Only a later explicit `apply --profile
<saved-profile> --expected-preview <digest>` can retire the pointer. Apply
saves original profile, pointer, launch record and settings bytes in a private
transaction, rechecks the whole snapshot, then moves only `current.json` into
that transaction. It never deletes the failed record, login partition, history,
or credentials; it never launches or replays. A prepared or malformed
transaction is terminal for automatic start. A receipt-writing crash after the
pointer move also blocks start until separately reviewed. After a successful
retirement, update the registered interpreter through the normal explicit
configure path before a separate service start.

The project rule for *unbound starting* records requires an original stopped
snapshot with zero requests and a known listener port. Those artifacts do not
exist in this pre-initialization failure. Treat this command as a distinct
reviewed exception; do not use it to relax the existing recovery path or to
retire an unknown `uncertain` launch.
