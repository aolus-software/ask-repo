---
name: rag-check
description: "Run the model-backed prompt-honesty test suite after touching app/rag/prompts.py or the retrieval graph, since ordinary tests can't catch a prompt that routes or cites wrongly."
risk: safe
source: local
date_added: "2026-09-05"
---

# RAG Check

`.claude/rules/rag.md` and `CLAUDE.md` both flag `tests/test_rag_model_integration.py` as the
**only** suite that runs against a real served chat model instead of `ScriptedChatModel` — it is
what keeps `app/rag/prompts.py` honest. It sits behind the opt-in `model` pytest marker, which
makes it easy to forget precisely when it matters most: right after editing a prompt or the
retrieval graph.

`$ARGUMENTS` (optional) narrows the run to one test, e.g. `rag-check grading`.

## When to reach for this

- After any change to `app/rag/prompts.py`.
- After any change to `app/rag/graph/nodes.py`, `build.py`, or `state.py` — this is the suite
  positioned to catch a regression in a node's fallback behaviour (`classify` falling back to
  `codebase_question`, `grade` falling back to `sufficient`) or in the grader's deliberate
  asymmetry (`rag.md`: "a grader that can refuse an answer is a regression").
- After any change to `app/rag/answerer.py` or `app/rag/grounding.py`.

## How to run it

1. Confirm a chat model is actually reachable first. `make dev`/`make worker` only *warn* when
   nothing answers on `:11434` — they don't fail — so a silent connection problem here would
   just look like every test failing for the same unrelated reason. Ask the user to confirm
   `ollama serve` (or their configured `CHAT_BASE_URL`) is up before running, rather than
   guessing from the error output.
2. From `backend/`: `uv run pytest -m model`, or `uv run pytest -m model -k "<narrowing term>"`
   if `$ARGUMENTS` named one.
3. Report the real output — pass/fail counts and any failing test names — never an assumed
   "should be fine." This suite exists specifically because prompt regressions are silent
   everywhere else in the test suite; treating its own output loosely defeats the point of
   running it.
4. A failure here is a signal to look again at the prompt or graph change just made — not a
   reason to loosen the test. This is the one place in the codebase that can tell a routing or
   citation regression apart from a fluent-looking wrong answer.

## Rules

- This command only runs a test suite. It does not edit `app/rag/prompts.py` or any graph node
  to make a failure go away — report the failure and let the user decide the fix.
- Do not skip this after a prompts/graph change just because other tests passed —
  `ScriptedChatModel`-backed tests cannot catch this class of regression by design.
