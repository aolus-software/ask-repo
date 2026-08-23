# Audit Findings Writing Rules

How to write a finding in `docs/audit-findings.md` or any other audit report produced by
`/audit-flow`. This rule governs **how findings are written**, not what is audited — the
categories to sweep live in `.claude/commands/audit-flow.md`.

## Principle: write for the human who has to decide, not for the auditor who found it

A finding is read by someone who was **not** in the audit: the owner deciding whether to spend
a day on it, a developer picking it up three weeks later, a reviewer asking "is this real?".
They do not have the audit's context loaded. They should be able to read one finding, in
isolation, and come away knowing **what the thing is, how it goes wrong, what it costs, and
what to do about it** — without opening the code first.

A finding written as a note-to-self fails this. This is a real shape to avoid:

> ❌ "`resolve_project_ids` is bypassed in `list_projects` — filters on `created_by` inline."

That is true, cited, and useless to anyone who does not already know what the resolver is, why
phase 2 depends on it, or what actually breaks for a user. **Rewrite until a competent
developer who has never opened that file understands the problem.**

## Every finding has these blocks, in this order

Use these exact inline bold labels, not `###` headings, so findings scan uniformly:

```markdown
### §2.1 Any user can delete a colleague's project — 🔴 bug

**Where:** `backend/app/api/routes/projects.py:88-96`,
`backend/app/services/project_service.py:141`

**What this is.** Projects are shared: anyone on the instance can list and query any project
someone else added. That is intended. What is *not* intended is deleting one — the PRD limits
delete and reindex to the person who created the project, or an admin, because deleting drops
the project's vectors and everyone loses the index.

**Why this can happen.** The delete route resolves the project by id and calls
`service.delete()` directly. The `created_by`/`is_admin` comparison that the PRD describes was
never written — there is no check between the route and the delete. Any authenticated user who
can see a project id in the list response can delete it, and the list response returns every
project on the instance.

**What it costs.** One mistaken click destroys a shared index. Re-creating it means a full
re-clone and re-embed of the repository, because the working copy is deleted after indexing —
so there is no cheap recovery. There is also no attribution: nothing records who deleted it.

**What we should do.** Add the ownership check in the service, not the route, so reindex picks
it up too — both operations are gated identically per PRD §4.1. Return `403`, not `404`:
project existence is deliberately public here. Roughly two hours including the access test the
PRD §7 success criteria already call for. See `.claude/rules/router.md` → "Destructive
operations are gated".
```

### Block-by-block requirements

| Block | Must contain | Must not contain |
| --- | --- | --- |
| **Where** | Every relevant `file:line`. A finding with no location is not a finding | Vague "in the project routes" |
| **What this is** | The mechanism in plain language — what the feature does, who calls it, what the normal path looks like. Assume the reader has never seen this subsystem | Jargon used before it is explained; a restatement of the code |
| **Why this can happen** | The concrete trigger: who does what, in which order, under what conditions (an admin vs a regular user, an empty field, a restart mid-index) | "Could potentially", "may cause issues", "is not ideal". If you cannot name the trigger it is a SUSPECT — say so |
| **What it costs** | The observable damage — what a *user* or *operator* sees. Data exposed to whom, work destroyed, wrong number displayed where, request that 500s | Severity restated as a feeling ("this is bad") |
| **What we should do** | A specific, implementable fix; rough effort; the rule or doc it should follow; other sites with the same shape | An actual code change — audits are read-only |

Short findings may compress **What it costs** into **Why this can happen**, but never drop
**What this is** or **What we should do** — those two are what make the report usable by
someone other than the author.

## Plain language rules

- **Expand every abbreviation and pattern name on first use in the document.** "server-side
  request forgery (making the server fetch a URL an attacker chose)", "SSRF" thereafter. Same
  for RAG, chunking, embedding, top-k, soft delete, TOCTOU, N+1. The reader may be an owner,
  not a backend engineer.
- **Prefer the domain word over the code word.** "a user can read a project they were never
  given" beats "`resolve_project_ids` returns unfiltered". Give the code word right after, in
  the same sentence, so it stays greppable.
- **Say who.** Access findings must name the role and the direction: *which* user gets to see
  or change *whose* data. "Missing check" is not a finding; "any regular user can delete any
  project on the instance" is.
- **Tell it as a sequence when it is a race or a flow.** "Worker A selects → worker B selects →
  both index" reads instantly; prose describing the same thing does not.
- **One finding, one problem.** If a paragraph contains two independent defects, split it into
  two numbered findings so each can be fixed, argued, or dismissed on its own.
- **No unexplained numbers.** `limit=25` means nothing alone — say what it bounds and why it is
  wrong here.

## Severity — pick the tag from consequence, not from effort

| Tag | Meaning | Test |
| --- | --- | --- |
| 🔴 **bug** | Wrong behaviour reachable today: data exposed to someone who should not see it, wrong data written, work destroyed, a request that fails | "Could I write a failing test for this against `main`?" |
| 🟠 **inconsistency / latent risk** | Correct today but fragile — depends on a condition that could change, or diverges from a rule so the next change lands wrong | "Does this break the moment someone adds the obvious next feature?" |
| 🟡 **hygiene** | Duplication, dead code, magic values. No behavioural consequence | "Is the only cost developer time?" |
| 📄 **doc** | A doc, rule, or PRD claim contradicts the code | See `documentation.md` |

Security findings are always 🔴 and always sort to the top of "Top priorities", ahead of
data-integrity, then hygiene/doc.

**Phase-1 scope matters when judging severity.** "Any user can query any project" is
**intended behaviour** in phase 1, not a finding (`docs/PRD.md` §4.1, and `SECURITY.md`
lists malicious authenticated users as out of the threat model). Reporting intended sharing as
a leak wastes the reader's attention and trains them to distrust the report. What *is* a
finding: read scoping that bypasses the access resolver, because that breaks phase 2 — file it
as 🟠, not 🔴.

## Evidence: CONFIRMED vs SUSPECT

Every finding carries one, and the difference is honest:

- **CONFIRMED** — the path was traced end to end and the trigger can be named. All blocks are
  fillable.
- **SUSPECT** — the shape looks wrong but something is unverified. Say **what specifically is
  unverified** and **what would settle it**: "unverified: whether `require_admin` is applied as
  a router-level dependency; reading the `APIRouter(...)` call in `users.py` settles it."

Never promote a SUSPECT to CONFIRMED to make the report look stronger, and never bury one in a
CONFIRMED list. A SUSPECT later disproved is marked refuted, not deleted.

## Document layout

1. **Header block** — sweep date, what was swept, ground-truth docs used, severity legend, and
   an explicit read-only statement ("nothing below has been fixed").
2. **Top priorities** — a numbered list ordered security → data integrity → correctness →
   hygiene/doc, each one line pointing at its section. This is the part the owner actually
   reads; write it last, and in the plainest language in the document.
3. **Sections** — one per audit category, numbered stably (`§1`–`§9`). A scoped sweep uses its
   own prefix (`A1`–`A9`) so numbers never collide across reports.
4. **Verified-correct notes** — where a category came back clean, say so and name what was
   checked. "Clean" with no evidence is indistinguishable from "not audited".

Finding numbers are permanent identifiers — commits, branches, and follow-up conversations cite
them. **Never renumber** an existing finding; new ones append.

## Resolved findings stay, marked

When a finding is fixed, do **not** delete it in the change that fixes it:

- Append `— ✅ RESOLVED <YYYY-MM-DD>` to its heading.
- Add a short quote block at the top saying what changed and in which branch, and **keep the
  original text below** under "Original finding follows." The next auditor needs to see the
  pattern that was wrong, not just that it went away.
- Add a one-line entry to the header block's resolved note so the summary stays readable.
- Say plainly when a fix is *partial*, or when a related finding survives it.

Pruning long-resolved items into a single "prior sweeps (see git history)" line is fine on a
later sweep, once the document gets unwieldy.

## Audits do not fix things

`/audit-flow` and every audit report are **read-only**. Findings are reported and the user
decides what gets fixed — that is `contradiction-halt.md`, and it applies with no exceptions
here. "What we should do" describes a fix; it does not perform one. The one file an audit
writes is its findings document.
