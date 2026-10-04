# Feedback Rules

Everything under `app/core/feedback.py`, `app/models/feedback.py`,
`app/repositories/feedback.py`, `app/services/feedback.py`, `app/api/routes/feedback.py`,
`app/rag/prompt_version.py`, the `myFeedback` fields on message and change-set reads, and
`frontend/components/output-feedback/`.

Design: `docs/superpowers/specs/2026-09-27-phase-2.5-measurement-design.md`.
Intent: `docs/PRD.md` §2.1, Phase 2.5.

Every invariant here fails silently when broken — no failing request, just a vote that reached
somewhere it should not have.

## 1. Nothing feedback-authored ever reaches a model

Feedback is user-authored text about a private repository. Concatenated into a prompt it becomes
an instruction, which breaks the property `.claude/rules/rag.md` rests on: the model's
instructions come from the system message and nowhere else. The loop is manual on purpose — an
administrator reads, spots a pattern, and edits `app/rag/prompts.py`.
`tests/test_feedback_never_reaches_a_model.py` fails if `app/rag/`, `app/checklist/`,
`app/eval/` or `app/mockdata/` imports any feedback module. `app/rag/prompt_version.py` may be imported *by*
feedback; the reverse is the defect.

## 2. Administrators see the aggregate and the notes — never the turn, never the voter

`FeedbackAdminRead` carries no user field, and a test pins that. A note with a name attached is
most of the way to reading a private conversation. Nothing on `/feedback` joins to `messages`,
`conversations`, or a change set's body. The popover tells the user, in fixed text, who can read
their note.

**Admin reads carry the vote's day, never its time, and are ordered within a day by id, not
timestamp.** `conversation.created` in the audit trail (`.claude/rules/audit-trail.md`) already
gives an administrator a second-precision timestamp for the same actor and the same project —
the conversation a user opened seconds before casting an `answer` vote. A second-precision
`created_at`/`updated_at` on `FeedbackAdminRead` would let that timestamp be matched against the
vote and name the voter, so `FeedbackAdminRead.created_on` is a bare UTC date and
`updated_at` is dropped entirely — a revision time leaks the same way a creation time does.
`FeedbackRepository.page` orders by the UTC day and then by `id` (a random UUID), never by the
full `created_at`, because ordering within a day by timestamp would leak the same sequence back
out as page position instead of a printed clock time. This is a mitigation, not a guarantee: on
a project with exactly one member, that member is the voter regardless of how coarse the
timestamp is — day-only narrows the set of suspects, it does not always widen it past one.

## 3. Every write-side miss is one `404`

`FEEDBACK_TARGET_NOT_FOUND` for a missing id, a user-role message, someone else's conversation,
and a module outside scope alike. Visibility is the exact read check each subject already has —
`get_for_owner` for Ask, `ChecklistModuleRepository.get_in_scope` for the rest — never a new
permission and never an admin bypass for conversations.

## 4. A row points at what it judges and never copies it

No answer text, no change-set body, no prompt. Deleting a conversation nulls its notes (the
counts survive); deleting a project soft-deletes its feedback. `feature` and `project_id` are
derived server-side from the target, never accepted from a request.

## 5. `traceUrl` links a vote to its Langfuse trace, except for Ask answers

`FeedbackAdminRead.trace_url` is built from the target's own id with
`app/observability/trace_ids.py`, the same seed function the call log uses, so nothing stores a
trace id. It is `null` when `LANGFUSE_ENABLED` is off, and **always `null` for a `message` vote on
the Ask screen**: a trace carries second-precision start and end times, which would let an
administrator match a vote to its voter through `conversation.created` — the exact leak rule 2's
day-only `created_on` closes. Checklist and mock-data chat replies and both kinds of change set
are shared documents, so they link: a chat reply seeds on its change set's `message_id`, a
generation change set on its own id. A change set `get_many` cannot load (soft-deleted) gets
`null` rather than a guessed seed. Seeds are fetched one query per change-set table, never one per
row. See `.claude/rules/call-log.md` rule 6.

## 6. Recording a vote is not audited

Exemption 7 in `.claude/rules/audit-trail.md`. Do not add an `AuditEventType` for it.
