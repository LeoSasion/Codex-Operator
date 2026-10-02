# Reviewed native-route marker release

`operator_unified_marker_release.py` releases the exact
`operator-native-route-only-v1\n` marker for one already prepared unified picker
plan. It changes only that marker. It does not edit `config.toml` or the model
cache, start a service or Desktop, or make a model request. The existing
emergency **恢复官方默认路由** entry can recreate the marker while removing a
recognized owned global route.

`preview --plan <absolute plan.json>` is read-only and returns a digest. An
explicit `release --plan ... --expected-review-sha256 ...` accepts that exact
digest once. Before writing, it checks the prepared plan and copies, the
current recovery shortcut and owned entry, closed Desktop, matching config and
cache file identities, same router process birth and registry, an idle request
count, and the exact bound Web route. Only the known recovery marker may be a
blocker. Unknown marker bytes, links, a changed entry, stale plan evidence, or
an existing attempt stop the operation.

The transaction creates a private directory on the marker's volume under
`operator-unified-activation/marker-release`. It saves the exact marker bytes,
Windows file identity and an intent before moving the original marker to a
unique backup path. A completion receipt is saved only after the moved file's
bytes and identity match the original and the marker path is absent. A crash or
uncertain result remains terminal for review; repeating the release never
repairs or replays it. The read-only `verify_release` checks the receipt,
retained original, current entry and marker absence. The cold-launch arm and
consume stages must bind this receipt digest whenever the prepared plan was
made while the native-route lock existed. Deleting the marker by hand yields no
valid receipt.

This release alone does not activate routing or prove Desktop picker behavior.
The cold-launch config switch and its emergency recovery are separate stages.
Windows tests use disposable homes and mocked router/Web status, including a
real marker rename with its Windows file identity held for comparison.
