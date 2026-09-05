---
name: commit
description: "Stage relevant changes and create a git commit with a message describing the why, following repo conventions. Never pushes, never amends, never force-anything."
risk: caution
source: local
date_added: "2026-09-05"
---

# Commit

Create a git commit for the current changes in this repository. `$ARGUMENTS` (optional) is
extra guidance on scope or message content — e.g. `commit only the backend changes` or
`commit "fix: ..."` to suggest a message. With no arguments, commit everything relevant that is
currently staged or unstaged (never untracked files outside the user's intent).

## How to run it

1. Run in parallel: `git status` (never `-uall`), `git diff` (staged and unstaged), and
   `git log --oneline -10` to learn this repo's commit message style.
2. Analyze **all** changes that will be included — previously staged and newly added alike —
   and decide what belongs in this commit. If the diff clearly contains unrelated changes (e.g.
   a scratch file, an unrelated feature), ask before bundling them in.
3. Do not stage or commit anything that looks like a secret (`.env`, `credentials.json`, API
   keys). Warn the user if they explicitly ask to commit one of these anyway.
4. Draft a concise commit message (1-2 sentences) that explains **why**, not just what changed.
   Match the repository's existing style from the `git log` output.
5. Stage the relevant files by name (never `git add -A` / `git add .`), then commit with the
   message via a HEREDOC, ending with:
   ```
   Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
   ```
6. Run `git status` after the commit to confirm success.
7. If a pre-commit hook fails: fix the underlying issue, re-stage, and create a **new** commit —
   never `--amend` after a hook failure, since the commit did not happen and amend would target
   the previous one.

## Rules

- Only create a commit when this command is invoked — do not commit proactively for unrelated
  work.
- Never run destructive git commands (`reset --hard`, `checkout --`, `clean -f`) to "clean up"
  before committing. If uncommitted work looks unfamiliar, ask before touching it.
- Never skip hooks (`--no-verify`) or bypass signing (`--no-gpg-sign`) unless the user explicitly
  asks.
- Never amend an existing commit unless the user explicitly requests `--amend`.
- Never push. This command only creates a local commit — pushing is a separate, explicit step
  (see `/open-pr` for the flow that pushes and opens a PR).
- If there are no changes to commit, say so and stop — do not create an empty commit.
- This is a repository using git worktrees in places — never run `git stash` bare; if setting
  work aside is needed, prefer a WIP commit or `git stash push -u -m "<unique-tag>"` per the
  environment's git-safety rules.
