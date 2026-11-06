# Easel conversation account scope

This optional OpenClaw plugin uses the official `resolve_exec_env` hook to set
`EASEL_ACCOUNT_PERSONA` for each exec from the Web conversation's persisted binding.
It never changes the gateway's process environment and never rewrites shell commands.
Unknown or invalid bindings receive an invalid scope, so account scripts fail closed.

Enable `easel-account-scope` and add this directory's absolute path to
`plugins.load.paths` in the Easel profile. If a plugin allow list exists, add this ID.
Keep all other plugin settings intact. Start the gateway with `EASEL_ROOT` pointing
to the running Easel checkout, and restart after active conversations finish.
Verify the plugin is loaded and registers `resolve_exec_env` before using scoped
accounts through OpenClaw. No tool budget configuration is required.

See [persona account behavior and deployment](../../docs/persona-accounts.md).
