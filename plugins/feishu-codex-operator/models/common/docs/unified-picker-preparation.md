# Unified picker reviewed preparation

`operator_unified_prepare.py` provides a read-only `preview` and an explicit
`prepare` for a selected Codex home. Preparation saves evidence only. It never
changes `config.toml`, `models_cache.json`, a Desktop entry, the native-only
marker, router state, or a Web service. It sends no model request. There is no
arm or activation command in this module.

The caller supplies absolute project, Codex home, existing router-state, Web
profile, and router-port paths. `preview` returns a review digest and fixed
blocker codes without file bytes, token, or private paths. A matching digest
may be passed once to `prepare`. Before persistence, preparation checks exact
config bytes and Windows file identity, the current model cache snapshot, the
recovery-shortcut receipt, old Web activation retirement, router service and
process identity, registry digest, and idle bound Web route. It renders the
candidate with the existing pure renderer. It also examines the separate
`<project>/.codex/operator-unified-startup` schema-2 startup workflow; the
router state may be the existing API/Local router elsewhere. A missing or
changed workflow blocks persistence so a saved plan never lacks the exact
startup workflow it would need to bind later. The native-only marker and an
already-open Desktop remain visible future activation blockers; they do not
prevent a read-only preview or an otherwise complete snapshot.

`prepare` exclusively creates `<home>/operator-unified-activation` and retains
`before.toml`, `candidate.toml`, optional `cache-before.bin`, `plan.json`, and
`journal.json` with `phase=prepared_not_armed`. The directory is private and
on the config volume. The plan records digests, exact config/cache identities,
router process birth and service identity, Web route digests, source digests,
recovery receipt digest, old retirement status, and workflow bundle identity.
The candidate contains the local router token, so the directory must remain
private. A changed review, incomplete write, or existing preparation stops;
all saved files remain for explicit review. No automatic retry or recovery is
provided. Clearing a native-route-only marker is never part of preparation.

This snapshot alone cannot activate a mixed picker. The separate
[one-shot cold-launch consumer](unified-cold-launch.md) now rechecks the exact
prepared evidence, binds a reviewed native-marker release receipt when needed,
and witnesses cache retirement and the Windows config replacement. Explicit
deactivation/uninstall ownership and live Desktop picker, voice and task
acceptance remain separate checks. Existing Web startup code assumes its own
empty dedicated router and cannot claim ownership of the API/Local router.

All tests use disposable homes and mocked services. They do not modify a real
Codex home, install a shortcut, start a router, or make a model request.
