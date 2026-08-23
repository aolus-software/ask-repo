---
name: audit-flow
description: "Read-only audit of the codebase for access-control gaps, ingestion/SSRF validation, soft-delete vs Qdrant divergence, response-contract completeness, dead code, and doc drift. Writes findings to docs/audit-findings.md. Never modifies application code."
risk: safe
source: local
date_added: "2026-08-23"
---

# Audit Flow

Run a structured, **read-only** audit of AskRepo and record the results in
`docs/audit-findings.md`. This command **never changes application code, schemas, services, or
migrations** — its only output is the findings document.

`$ARGUMENTS` (optional) narrows the scope to specific categories or paths, e.g.
`audit-flow access ingestion` or `audit-flow backend/app/api`. With no arguments, run all
categories across the whole repository.

## How to run it

1. **Read the ground truth first:** `docs/PRD.md`, `CLAUDE.md`, all `.claude/rules/*.md`, and
   `SECURITY.md`. These define the intended behaviour that findings are measured against. The
   PRD outranks the rules; the rules outrank the code.
2. Dispatch parallel read-only `Explore` subagents — one per category below — so each returns a
   concise, `file:line`-referenced list. Do not do the reading serially in the main thread.
3. Each subagent must distinguish **CONFIRMED** from **SUSPECT**, and for each finding give:
   (a) the intended behaviour per the PRD/rules, (b) what the code actually does, (c) the
   contradiction and its runtime risk.
4. Merge the results into `docs/audit-findings.md`, grouped by category, each item tagged
   🔴 bug · 🟠 inconsistency · 🟡 hygiene · 📄 doc, with a "Top priorities" section ordered
   security-first, then data integrity, then hygiene/doc. **Write every finding in the
   five-block plain-language format** — a subagent's terse notes are raw material, not the
   finished finding. Expand them.
5. Report a short summary to the user. **Do not fix anything** — fixes are a separate,
   explicitly requested step.

## Categories to cover

1. **Access control.** Destructive operations (`DELETE`, `reindex`) gated on `created_by` or
   `is_admin` per PRD §4.1; `403` vs `404` used correctly per §5.1; auth dependencies actually
   applied to every route that needs them; admin-only routes (`POST /users`,
   `POST /users/{id}/reset-password`) genuinely admin-only; `must_change_password` enforced on
   every route except the change-password one.
2. **Read scoping and phase-2 readiness.** Every retrieval path goes through the single access
   resolver (PRD §2, §4.1, §5.1). Any route, service, or query filtering projects on its own is
   a finding even when its current output is correct — that is the whole point of the rule.
   Grep for project filtering outside the resolver.
3. **Conversation privacy.** Conversations are scoped by `user_id` and return `404` — not `403`
   — for another user's. Check every conversation and message read path (PRD §4.2).
4. **Ingestion safety / SSRF.** `repo_url` validation: `https://` only, host allowlist,
   rejection of private/loopback/link-local addresses **resolved at connect time** not just
   parse time, clone timeout, repo size cap (PRD §4.1, §9). This is the sharpest risk in the
   app — an internal instance where `10.0.x.x` resolves.
5. **Soft delete vs Qdrant.** Every Postgres soft delete of a project has a matching **hard**
   delete of its Qdrant points, in the same operation (PRD §5.1). A soft-deleted project whose
   vectors survive is retrievable content that should be gone. Also check `deleted_at IS NULL`
   filters on every query.
6. **Secret handling.** PATs and tokens never serialized (not even masked), never logged, never
   in a traceback or error response. Check response models, log statements, and exception
   handlers (PRD §4.1, §9).
7. **Response-contract completeness.** Every route declares `response_model`, `status_code`,
   `summary`, and a `responses` block matching what its service and dependencies actually raise.
   Every schema inherits `ApiModel` — a plain `BaseModel` ships `snake_case` and breaks the
   contract. Examples match the real payload shape. See `.claude/rules/response-api.md`.
8. **Job and status handling.** Ingestion jobs that can leave a project stuck in `cloning` or
   `indexing` forever — a restart mid-job, an unhandled exception that never writes `failed`, a
   missing timeout. Check that every terminal path sets a terminal status and populates `error`.
9. **Dead code and unused validation.** Schema fields never read, dead `Literal` members,
   missing validators, config settings declared in `Settings` but never used, and settings used
   but absent from `.env.example`.
10. **Shared-code placement and duplication.** Logic copy-pasted across services that belongs in
    one place; magic values; three ways to do one thing.
11. **Documentation drift.** `CLAUDE.md`, `README.md`, `backend/README.md`, `SECURITY.md`,
    `CONTRIBUTING.md`, and `.claude/rules/*` claims versus the code: route lists, counts, env
    var names, commands, roadmap checkboxes, the README status banner, and rules with no
    coverage for shipped patterns. See `.claude/rules/documentation.md`.

## Rules for this command

- **Read-only.** If the audit surfaces something that looks like a bug or a rule contradiction,
  **report it — do not act on it** (`.claude/rules/contradiction-halt.md`).
- **Phase 1 sharing is intended, not a leak.** Any user querying any project is designed
  behaviour (PRD §4.1); `SECURITY.md` puts malicious authenticated users out of scope. Do not
  file intended sharing as a security finding. Read scoping that bypasses the resolver *is* a
  finding — as 🟠, because it breaks phase 2 rather than leaking today.
- Prefer updating the existing `docs/audit-findings.md` over creating a new file, so the report
  stays a single living record.
- Cite `file:line` for every finding. No finding without a location.
- Writing format, severity choice, CONFIRMED-vs-SUSPECT honesty, document layout, and how to
  mark a finding resolved are all governed by `.claude/rules/audit-findings.md`. **Read it
  before writing the report.**
