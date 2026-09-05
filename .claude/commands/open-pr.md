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
   - `git remote -v` — this repo is set up per `CONTRIBUTING.md` ("`git clone <your-fork>`"),
     so a contributor's checkout typically has `origin` pointing at their own fork and a
     second remote (conventionally named `upstream`) pointing at the real project repo. If a
     remote other than `origin` exists, `git fetch <that-remote> <its-default-branch>
     --quiet` and compare it against `HEAD`/`origin/<branch>` — do not assume `origin` is the
     PR target just because it is the default push remote. If unsure which remote is the
     real base, `gh repo view --json parent,nameWithOwner` on the `origin` repo tells you
     directly whether it is a fork and what its parent is.
   - Check whether the current branch tracks a remote and is up to date
   - `git log` and `git diff [base-branch]...HEAD` to see the **full** commit history for this
     branch since it diverged from the base branch — not just the latest commit. **The base
     branch for this diff is the upstream/parent repo's default branch when one exists**, not
     `origin/main` — a fork's `main` can already be ahead of `origin/main` (e.g. from an
     editor's auto-sync push, or a prior local merge) while still being exactly what needs a
     PR into the real project. Compare against the correct base before concluding "nothing to
     PR here."
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
     directly (ask first if unclear). **In a fork setup, pushing to your own fork's `main`
     is not the same risk as pushing to the real project's `main`** — the destructive case
     this rule guards against is bypassing review on the repo other people rely on. If
     `origin`'s `main` is already at the commit you'd push (nothing left to push, as after an
     editor's auto-sync), there is nothing to push here at all; the PR itself is what still
     needs opening, against the upstream/parent repo.
   - Push to remote with `-u` if the branch has no upstream yet
   - `gh pr create --title "..." --body "$(cat <<'EOF' ... EOF)"` using the drafted title and
     the filled-in template as the body. **When a second remote exists** (step 1), pass
     `--repo <owner>/<name>` naming that remote's repo, and `--base <its-default-branch>` —
     `gh` does not infer a fork's parent as the target on its own. `--head
     <your-username>:<branch>` disambiguates the source when opening cross-repository.
5. Return the PR URL to the user.

## Rules

- Never push to `main`/`master` **of the upstream/parent repo** directly, and never
  force-push. Pushing to your own fork's `main` is not gated the same way — it doesn't touch
  the repo a PR review protects — but still warn the user if a push there wasn't clearly what
  they asked for.
- Never merge, close, or approve a PR as part of this command — opening it is the whole job.
- Do not push or open a PR without the user having asked for this command — confirm scope first
  if it's ambiguous which branch or commits are meant.
- This is a git worktree: do not run installs, dependency setup, or build commands as part of
  this flow, and do not `cd` out of the current worktree directory. Only run the git/`gh`
  commands needed to inspect state and open the PR.
- If `gh` reports the repo has no remote configured, or auth is missing, report that back rather
  than trying to configure git/gh settings yourself.
- If a second remote exists but you can't tell which one is the real base (neither is
  obviously a fork of the other, or `gh repo view --json parent` returns null on both), ask
  the user rather than guessing — opening a PR against the wrong repo is not something `gh`
  lets you quietly undo.
