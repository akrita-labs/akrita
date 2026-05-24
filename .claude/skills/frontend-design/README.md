# frontend-design (vendored)

Vendored **verbatim, unmodified** from Anthropic's official Claude Code plugin
`frontend-design` (marketplace `claude-plugins-official`).

- **License:** Apache-2.0 — see [LICENSE.txt](LICENSE.txt).
- **Why it's here:** the skill is already available at user level via the
  `claude-plugins-official` plugin, but committing it to `.claude/skills/` ships it
  with the repo so teammates and Agent SDK / CI runs
  (`setting_sources=["user","project"]`) get it without installing the plugin.
- **AKRITA fit:** guides building distinctive, production-grade frontend UIs — used
  when extending the Byzantine illuminated-manuscript frontend (dashboard, personalize,
  /akritai profile, etc.).

To update, re-copy from the upstream plugin rather than editing in place (keeps it
verbatim and license-clean).
