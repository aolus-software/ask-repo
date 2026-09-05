---
name: open-pr
description: "Push the current branch and open a GitHub pull request with a summary and test plan, using gh. Never merges, never force-pushes."
risk: caution
source: local
date_added: "2026-09-05"
---

# Open PR

Push the current branch (if needed) and open a pull request via `gh`. `$ARGUMENTS` (optional)
gives extra guidance — e.g. a target base branch, a draft flag, or PR title wording.

## How to run it

1. Run in parallel:
   - `git status` (never `-uall`)
   - `git diff` (staged and unstaged)
   - Check whether the current branch tracks a remote and is up to date
   - `git log` and `git diff [base-branch]...HEAD` to see the **full** commit history for this
     branch since it diverged from the base branch — not just the latest commit
2. If there are uncommitted changes, stop and ask whether to commit them first (see `/commit`) —
   this command does not silently commit on the user's behalf.
3. Read `.github/PULL_REQUEST_TEMPLATE.md` and fill it in — do not draft a freeform Summary/Test
   plan body instead. In particular:
   - `# Summary` — one or two sentences, why not just what. Fill in `Closes #` if an issue number
     is known, otherwise delete that line rather than leaving a dangling `#`.
   - `## Type of change` — check the box(es) that actually apply.
   - `## Milestone` — name the PRD milestone (M0–M6) this serves, or `none`, per `docs/PRD.md`
     §6. Don't guess if it isn't clear from the diff — ask.
   - `## What changed` — walk a reviewer through it; call out any non-obvious decision or
     tradeoff.
   - `## How this was verified` — real commands and their actual output, from this session
     (e.g. `uv run pytest`, `bun lint`, `docker compose config`). Never write "it should work".
     If a check wasn't run, leave its checkbox unchecked rather than checking it speculatively.
   - `## Checklist` — check only items genuinely satisfied by the diff (docs updated,
     `.env.example` updated, migration included, no secrets, new config documented).
   - `## Security and access` — delete this section only if the diff touches none of it;
     otherwise check each item honestly per `docs/PRD.md` §4.1/§5.1/§9.
4. Run in parallel:
   - Create a new branch if the current one is `main`/`master` or otherwise unsuitable to push
     directly (ask first if unclear)
   - Push to remote with `-u` if the branch has no upstream yet
   - `gh pr create --title "..." --body "$(cat <<'EOF' ... EOF)"` using the drafted title and the
     filled-in template as the body
5. Return the PR URL to the user.

## Rules

- Never push to `main`/`master` directly, and never force-push. Warn the user if they explicitly
  ask for a force push and let them confirm.
- Never merge, close, or approve a PR as part of this command — opening it is the whole job.
- Do not push or open a PR without the user having asked for this command — confirm scope first
  if it's ambiguous which branch or commits are meant.
- This is a git worktree: do not run installs, dependency setup, or build commands as part of
  this flow, and do not `cd` out of the current worktree directory. Only run the git/`gh`
  commands needed to inspect state and open the PR.
- If `gh` reports the repo has no remote configured, or auth is missing, report that back rather
  than trying to configure git/gh settings yourself.
