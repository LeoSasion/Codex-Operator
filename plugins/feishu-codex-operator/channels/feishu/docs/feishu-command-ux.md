# Feishu command UX

`/init` and `/model` are reserved commands.

`/init` lists at most 50 active stored Codex tasks across model providers, shows eight per page, binds the
wizard to its initiating Feishu user, expires after ten minutes, and requires a
confirmation before changing the local mapping. Selection is by exact UUID,
never by title. The configured minimal Beeper is filtered out and cannot be
selected.

All other slash commands receive a generic unsupported-command reply. An
authorized unbound private user may first enter the separately configured
automatic task-registration flow. Once an exact binding exists, ordinary
messages are relayed once through the fixed Beeper to that task. Existing valid
bindings skip registration; groups and topics retain their original scope rules.
Successful binding displays one risk notice: delivery can rarely be missed or
duplicated, so the Operator should not be used for irreversible actions.

The owner-requested [project and user-task onboarding](automatic-task-provisioning.md)
offers a first-run local Beeper/Luna-low choice and separate project/default-task
and continuing user-task grants. The assistant creates the initial project and
tasks after approval; runtime user-task registration is implemented, with live
new-user acceptance recorded separately. The current `/init` remains a read-only
catalog plus an explicit binding operation, available for manual selection or
rebinding rather than an obligatory step after authorized automatic setup.

## Task model selection

`/model` reads the exact bound native task settings without turns; `/model list`
lists the bounded current official catalog. `/model <exact model ID> [effort]`
saves a choice for the next new business message. The list includes a copyable
example using one current model's exact ID and supported default effort; an empty
catalog offers no selection example. Short names such as `luna` work only when
they identify exactly one catalog entry. Multiple generations sharing a name
require the full ID; the Operator never silently chooses a generation.
`/model cancel` removes only the pending/local selection, leaving native settings
and already dispatched messages alone. These commands do not send model turns.

The new message revalidates the task provider and catalog, then the existing
one-shot Desktop send carries the explicit model and effort. Selection is
consumed before queueing; accepted, rejected or uncertain sends never restore it
or replay input. Subsequent ordinary messages omit overrides again. Rebinding
clears the choice; a concurrent binding/selection change stops dispatch.
Only official direct routing is admitted in this preview; custom catalogs,
external providers and Spark are not selectable. Beeper's own Luna/low stays
independent. Saved selection, dispatch bookkeeping, native settings readback and
actual execution are distinct evidence.

The direct-route check rejects root `openai_base_url` and inherited
`OPENAI_BASE_URL` overrides as well as a custom native provider. A task appearing
in `/init` does not make its provider selectable through `/model`. Neither
directory lookup nor route validation changes configuration or sends a model turn.
