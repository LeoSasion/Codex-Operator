# Tests

Run from the extracted repository root with Python 3.11+ and the dependencies in `../../scripts/model-router-requirements.txt` installed in your test environment:

```powershell
python -B plugins/feishu-codex-operator/development/run_tests.py
python -B plugins/feishu-codex-operator/development/run_tests.py --node
pwsh -NoProfile -File plugins/feishu-codex-operator/scripts/audit-feishu-codex-release.ps1
```

Stop the exact Operator instance and finish pending callbacks before tests. Use temporary projects and isolated homes; never aim fixtures at real chats, credentials or task histories. Tests must not send real business messages. Synthetic protocol checks, real model execution and Desktop UI acceptance are distinct.

The suite includes Windows-specific and environment-dependent skips. Retain failures and report the tested versions. Full results belong in a private receipt, not a copied personal diagnostic history in the public package.
