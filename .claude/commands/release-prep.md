---
name: release-prep
description: "Read-only release readiness report. Reconciles the current GitHub release and tag against what has actually merged since it, checks the CHANGELOG's [Unreleased] section against those commits, resolves which issues the merged PRs close, and flags documentation and version drift. Reports to the user and changes nothing — no tag, no release, no file edit, no push."
risk: safe
source: local
date_added: "2026-09-13"
---

# Release Prep

Answer one question for the user: **is this repository ready to cut a release, and what would
they want to know before deciding?**

This command is **read-only**. It does not edit `CHANGELOG.md`, bump a version, create a tag,
publish a release, push, or comment on anything. Its only output is a report in the reply.

`$ARGUMENTS` (optional) names the version being considered, e.g. `release-prep v1.1.0`. Given
one, also check that the number is defensible against what changed. Given nothing, infer the
likely bump and say why — without asserting it as decided.

## Ground truth

`docs/PRD.md` §6 is the only place milestone progress is recorded. `CHANGELOG.md`'s format and
promises are set by its own header block. `.claude/rules/documentation.md` lists every doc that
must move when something changes — that table is the drift checklist in §5 below.

## Gather first, in parallel

These are independent; run them together rather than one at a time.

```bash
# Releases and tags — local tags are often stale or absent, so fetch before believing them
git fetch --tags --quiet
gh release list --limit 10
gh release view --json tagName,publishedAt,isDraft,isPrerelease,targetCommitish
git tag --sort=-creatordate | head
git ls-remote --tags origin | tail

# What has merged since that release
git log --oneline <last-tag>..HEAD          # or --since=<release publishedAt> when no local tag
git diff --stat <last-tag>..HEAD
gh pr list --state merged --limit 40 --json number,title,mergedAt,author,body,closingIssuesReferences

# Issues
gh issue list --state all --limit 100 --json number,state,title,labels,closedAt

# The documents
git diff --stat <last-tag>..HEAD -- docs/ '*.md'
```

**Do not trust `git tag` alone.** This repository has had a published GitHub release whose tag
was not present locally — `git tag` returned nothing while `gh release list` showed `v1.0.0`. If
the two disagree after a fetch, that disagreement is itself the first thing to report: a release
without a reachable tag means `git log <tag>..HEAD` silently compares nothing, and every
downstream count in this report would be wrong. Fall back to the release's `publishedAt` with
`git log --since=`, and **say in the report that you did**.

## What to report

### 1. Where the release line currently sits

The latest release: its tag, publish date, whether it is a draft or prerelease, and the commit
it points at. Then the gap: how many commits and how many merged PRs have landed since, the
date range they span, and a one-line characterisation — mostly features, mostly fixes, mostly
docs. That characterisation is what the bump argument rests on.

Flag any of these plainly:

- A release whose tag does not exist locally or on the remote after a fetch.
- A draft or prerelease sitting at the top of the list, which `gh release view` will return as
  "latest" and quietly skew every comparison below it.
- Commits on `main` that no merged PR accounts for — a direct push. Not wrong, but the user
  should know the PR list is not the whole story.

### 2. The `[Unreleased]` section, reconciled against what actually merged

This is the heart of the report and the part most likely to be wrong.

Walk **both directions** — one alone is half an audit:

- **Merged, but not in the changelog.** For each merged PR and each commit since the release,
  find its entry under `## [Unreleased]`. Anything user-visible with no entry is a gap. Per
  `.claude/rules/documentation.md`, user-visible means: a route, a JSON field, an `ErrorCode`
  value, a configuration default, or a fixed defect. A pure refactor or a test-only change
  legitimately has no entry — **say so explicitly** rather than leaving it unmentioned, so the
  user can see it was considered rather than missed.
- **In the changelog, but not merged.** An entry describing something no commit since the last
  release implements. This happens when work is written up before it lands, or when a branch
  was abandoned after its entry went in. Shipping that entry is worse than omitting it — it is
  a release note for a feature that does not exist.

Then check the section's mechanics:

- Entries sit under the Keep a Changelog headings (`Added` / `Changed` / `Deprecated` /
  `Removed` / `Fixed` / `Security`), and each is in the right one. A behaviour change filed
  under `Added` is how a breaking change gets missed.
- **Nothing was added to a released section.** `## [1.0.0] — 2026-09-06` and every section below
  it are a historical record and are never edited. Diff the released sections against the last
  tag; any change there is a finding.
- The link definitions at the bottom of the file still resolve. `[Unreleased]` compares
  `<last-tag>...HEAD`, and each released version points at its release. A release will need a
  new line added and `[Unreleased]`'s compare base moved — **name that as a step the user will
  take**, and do not take it.

### 3. What the merged PRs close

For every PR merged since the release, report: number, title, merge date, and the issues it
closes.

**`closingIssuesReferences` under-reports here, and relying on it alone will produce a wrong
list.** It is populated only when a PR body uses a linking keyword (`closes #N`, `fixes #N`) in
the right form. In this repository, PRs have shipped work for an issue while recording no
closing reference — the issue number appeared only in the PR title, a commit subject, or the
changelog entry. So cross-check three more places and merge the results:

```bash
gh pr view <n> --json body,title            # keyword links and bare "#N" mentions
git log --format='%s%n%b' <last-tag>..HEAD  # "(#N)" in subjects and trailers
grep -n "#[0-9]\+" CHANGELOG.md             # issue references inside entries
gh issue view <n> --json state,closedAt,stateReason
```

Then report three groups, because each one asks the user for a different decision:

| Group | What it means | What the user does |
| --- | --- | --- |
| **Closed by a merged PR** | Shipped and closed. | Nothing — this is the release's content. |
| **Closed, but by no PR here** | Closed by hand, or by work in an earlier release. | Confirm it belongs in these notes at all. |
| **Shipped but still open** | The work merged; the issue was never closed. | Close it, or explain why it stays open. |

The third group is the one worth surfacing loudly: an open issue describing shipped work makes
the issue tracker lie, and this is the moment someone notices.

Finally, check the **phase labels**. Issues labelled `phase-2` are deferred by design
(`docs/PRD.md` §2.1) and must **not** appear in release notes as outstanding work — they are
scope, not a backlog gap. Report them as a count and a reminder, never as a blocker.

### 4. Version numbers, and whether they agree with each other

Report every place a version is written and whether they agree:

- the latest release tag,
- `backend/pyproject.toml` → `version`,
- `frontend/package.json` → `version`,
- the top released section in `CHANGELOG.md`.

**These have drifted before**: both package files have sat at `0.1.0` through a `v1.0.0`
release. Whether the package versions are meant to track the release tag is the user's call —
report the mismatch, name it as a decision rather than a defect, and do not change either file.

Then the bump argument, stated as a recommendation and not a conclusion. `CHANGELOG.md`'s own
header defines what versioning covers here: **the wire contract — route paths, JSON field
names, and `ErrorCode` values.** A `MAJOR` means one of those changed incompatibly;
configuration defaults and internal module layout may move in a `MINOR`. So the question is not
"how big was this work" — it is: did any route path, JSON field name, or `ErrorCode` change
incompatibly since the last release? Answer that with evidence:

```bash
git diff <last-tag>..HEAD -- backend/app/api/routes/ backend/app/schemas/ backend/app/core/errors.py
```

A removed or renamed `ErrorCode` member is the sharpest signal — `CLAUDE.md` states those are a
wire contract where members are added and never renamed.

### 5. Documentation drift

Walk `.claude/rules/documentation.md`'s table and check each row against what changed. Report
only rows where something actually moved; a clean row gets a single summary line, not an entry
each.

The checks that catch the most per unit of effort:

- **`docs/PRD.md` §6 milestone status.** It is the single record of progress, and it is wrong
  last rather than first. Does it match what merged?
- **No other doc carries a status banner or a roadmap claim.** `CLAUDE.md` and
  `.claude/rules/documentation.md` both forbid one. A "shipped" claim that crept into a README
  is a finding.
- **New `Settings` fields land in three places** — `backend/app/config.py`,
  `backend/.env.example`, and `docs/configuration.md`. Diff the field list in `config.py`
  against the other two; a setting missing from `.env.example` is undiscoverable.
- **`backend/README.md`'s route table is exhaustive.** Diff the routers against it.
- **Counts are exact.** `CLAUDE.md` states the number of rule files and commands, and lists the
  frontend routes. Verify each against the tree — a count is the fact that goes stale most
  quietly. *(This command and `audit-ui` both landed in `.claude/commands/`; confirm the stated
  count moved with them.)*
- **`infra/docker-compose.prod.yml`** received every non-development-specific change made to
  `infra/docker-compose.yml`. Nothing in `make check` builds or starts the production stack, so
  this pair drifts silently and a release is when that bites.
- **Examples still work.** A `curl` or a response example in a README must match the code as
  committed.

### 6. Does the tree actually build

Report the state of `make check` — lint, format-check, typecheck, and both test suites — and of
`docker compose config --quiet` for both compose files if either changed.

Run them if they are cheap and nothing is already running; otherwise say plainly that you did
not run them and that the user should before tagging. **Never report a check as passing that you
did not run.** Do not start infrastructure, do not start a model server, and do not run the
`integration` or `model` markers — both need services this command has no business starting.

## Output shape

A terse report in the reply — not a file. This is a briefing the user reads once and acts on,
and writing it to `docs/` would leave a stale artifact behind after the release it describes.

Order it so the first thing read is the thing that matters:

1. **Verdict** — one line. Ready to tag; ready once N things are settled; or not ready, and why.
2. **Blockers** — things that should be fixed before a tag exists. Each with its evidence.
3. **Decisions for the user** — the version number, any version-file mismatch, an entry that
   might be over- or under-claimed, an issue that should probably close. Each stated as a
   question with a recommendation, never as an action taken.
4. **Changelog reconciliation** — the two-direction walk from §2, as a short table.
5. **PRs and the issues they close** — the three groups from §3.
6. **Doc drift** — only the rows that moved.
7. **Checks** — what was run and what was not, stated honestly.
8. **The steps the user would take to release** — listed as a sequence for them to execute, not
   performed. Typically: settle the version, move `[Unreleased]` into a dated section, add the
   compare link, bump the package versions if they are meant to track, commit, tag, push the
   tag, and publish the release from `CHANGELOG.md`'s section as the body.

## Rules for this command

- **Nothing is modified. Nothing is created. Nothing is pushed.** No file edit, no
  `git tag`, no `git push`, no `gh release create`, no `gh issue close`, no PR comment. If the
  report concludes a file should change, it says so and stops — `.claude/rules/contradiction-halt.md`
  applies here with no exceptions.
- **Only `git fetch --tags` is permitted to touch the repository**, because a report built on
  stale tags is worse than no report. It changes no working-tree state.
- **Every claim carries its evidence** — a PR number, a commit SHA, a `file:line`, or the command
  that produced it. A release decision made on an unsourced assertion is the failure this
  command exists to prevent.
- **Say what you did not check.** An unrun test suite, a compose file you did not validate, a
  PR body you could not fetch. Silence reads as "clean", and on a release report that is the
  most expensive kind of wrong.
- **Deferred scope is not a gap.** `phase-2` and `phase-3` items in `docs/PRD.md` §2.1 and their
  tracking issues are deliberate. Never report them as unfinished work blocking a release.
