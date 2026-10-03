# Call Log Rules

Everything under `app/observability/` (`features.py`, `record.py`, `recorder.py`,
`trace_ids.py`, `langfuse_sink.py`), the `callbacks=` wiring in `app/rag/chat.py`, the
`build_call_log` calls in `app/main.py` and `app/worker.py`, every `config=call_config(...)` at a
model call site, and the `langfuse` profile in `infra/docker-compose*.yml`. Read `rag.md` and
`feedback.md` alongside this — the call log joins to feedback on a feature and a trace id, and
shares its premise with both: a private repository's content never gets a second copy.

Design: `docs/superpowers/specs/2026-09-27-phase-2.5-measurement-design.md` §4.
Intent: `docs/PRD.md` §2.1, Phase 2.5.

Every invariant here fails **silently** when broken — no exception, no failing request, just a
prompt, a completion or a user's question sitting in ClickHouse and in blob storage, outside the
lifecycle `docs/PRD.md` §5.1's delete rule governs. That is what makes these rules rather than
preferences.

## 1. A call record carries no content, and its field set is the enforcement

`CallRecord` and `CallStart` (`app/observability/record.py`) are the only things the sink ever
sees. Neither has a field that could hold a prompt, a completion, a question, a message, retrieved
code or a user id: `feature`, `provider`, `model`, timing, `outcome`, `error_class`, token
counts, `trace_seed`, `project_id`, `attempt` and `prompt_version`. `CallStart` is the content-free
announcement of a call beginning and its fields are a subset of `CallRecord`'s.

The rule is not "mask the content" — it is "never accept it". The recorder ignores the `messages`
argument of `on_chat_model_start` and the generations of `on_llm_end` except for the usage
numbers, so there is nothing to mask and no hook that must see every path. Langfuse's own
`CallbackHandler` was not used for exactly that reason: it writes span attributes directly, and
the mask that covers them cannot touch the span *events* an exception is recorded as.

**A new field is a change to this file first.** `tests/test_call_recorder.py` pins both field
sets, so adding one means editing that test, which is what makes a silent addition impossible.
Adding a field to the sink's `metadata` dict is the same change by another route.

## 2. The error's class, never its message

`CallRecord.error_class` is `type(error).__name__`. Provider error text can echo the request, and
`scrub` removes known secrets, not content — so it is the wrong tool here and its absence is
deliberate. `outcome` and `error_class` say that a call failed and how; the message stays in the
application log, where every other exception message already goes.

## 3. The recorder is attached in the factory, and every call passes a feature config

`build_chat_model` (`app/rag/chat.py`) takes `callbacks=` and hands it to whichever provider class
it builds, so the API process and the worker record every call through one door and
`isinstance` checks on the returned class still hold. A call site never constructs a handler.

Every `.ainvoke(` and `.astream(` on a chat model passes `config=call_config(CallFeature.X, ...)`.
A call with no tag is recorded as `untagged`, which is a number nobody can act on — the cost
shows up and the feature does not. `tests/test_call_sites_tagged.py` fails if a listed call site
omits it. A new model call is not finished until it is tagged and, if it is a new kind of call,
has a `CallFeature` value.

## 4. Scope travels as inherited metadata — never `TurnState`, never a context variable

The trace seed, project id and delivery attempt are set **once** with `scope_config(...)` on the
graph run or the generation job, and LangChain's inherited metadata carries them to every call
beneath. Two places they must not go:

- **Not `TurnState`.** The state is what the nodes reason about; scope is bookkeeping about the
  run, and a node that read it would be coupled to the call log.
- **Not a `contextvars` variable.** A chat turn's events are pulled through an async generator,
  and each `anext` may run in a **fresh task**. A context variable set in one task cannot be
  reset in another (`ValueError: ... was created in a different Context`), and nothing in the
  happy path would show it — the failure arrives on a disconnect, in the shielded cleanup.

`attempt` is the 0-based Kafka delivery attempt on a worker job and **absent** on the API path
(`None`, not `1`). Absent keys are omitted rather than written as `null`.

## 5. Tracing never fails a call

`CallRecorder.raise_error` is `False`, and every sink call goes through one `try`/`except` that
logs at `WARNING` and returns. A Langfuse outage, a bad key or an SDK bug costs a missing row, not
a failed answer — the same fail-open stance as `AuditRecorder`, for the same reason.

The consequence is accepted and not to be reframed as a guarantee: the call log is a strong
record, not a complete one. Both processes flush on shutdown (`CallLog.shutdown`), and that flush
never raises either. The recorder and the sink each cap their open-run map at 1024 so a call whose
end never arrives cannot grow either forever.

## 6. Ask answers get no trace link

A trace id is derived from the subject's own id (`app/observability/trace_ids.py`), never stored:
a chat turn from its assistant message id, a generation run from its change set id. The admin
feedback screen computes `traceUrl` from the same seed, so feedback and cost join without either
table knowing about the other.

`FeedbackAdminRead.trace_url` is `null` for `target_type == "message"` on the Ask screen, and that
is **a decision, not a gap.** Admins see only the *day* of a vote (`.claude/rules/feedback.md`
rule 2), because a second-precision time beside the audit trail's `conversation.created` row names
the voter. A Langfuse trace carries second-precision start and end times, so linking an Ask vote
to its trace would undo that. Change-set targets and the checklist and mock-data chat replies are
shared documents, so they link. A change set that can no longer be loaded (soft-deleted) is
`null` too — the seed is never guessed.

## 7. Langfuse is off by default, imports nothing when off, and phones nowhere

`LANGFUSE_ENABLED` defaults to `false`. When it is, `build_call_log` returns an empty `CallLog`
before the `langfuse` import is reached, so an instance without it never loads the package, makes
no connection and attaches no callback. The import stays inside the function for the same reason
the provider imports in `app/rag/chat.py` do.

Self-hosted Langfuse reaches out by default, and the Compose profile shuts what an environment
variable can shut: `TELEMETRY_ENABLED=false` on web and worker, `CHECKPOINT_DISABLE=1` on web. The
third path, image pulls from `docker.langfuse.com`, is not a setting — it is the operator's to
mirror (`docs/deployment.md`). Managed Langfuse Cloud is out of scope whatever it costs
(`docs/PRD.md` §2.1): it would make every traced call an egress of the code the prompt carried.

## 8. Retention is a ClickHouse TTL the operator sets

Langfuse's automated retention is Enterprise-only, and there is no AskRepo setting for it: the
data lives in Langfuse's store, not ours. `docs/deployment.md` documents the lever, a ClickHouse
`MODIFY TTL` on the traces, observations and scores tables. An instance that never sets one keeps
every call forever, and `SECURITY.md` says so under the operator's responsibilities.
