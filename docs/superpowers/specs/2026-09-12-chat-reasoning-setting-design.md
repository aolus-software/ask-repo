# Configurable chat reasoning: Design

**Status:** Approved design.
**Date:** 2026-09-12

## 0. What this document covers

`docs/superpowers/specs/2026-09-04-m4.5-model-provider-design.md` established `build_chat_model`
(`backend/app/rag/chat.py`) as the one factory every model call goes through. #28 fixed the fact
that `CHAT_TIMEOUT_SECONDS` reached only the answer nodes — checklist generation, mock-data
generation, and the classify/grade nodes fell through to the provider client's own ten-minute,
three-retry default. Issue #26 names the mechanism behind why that timeout was being hit at all:
**a reasoning model spends most of its output on hidden chain-of-thought, and nothing in this
codebase can turn it down.** Measured against a live instance running a reasoning model through
an OpenAI-compatible endpoint, 86% of output tokens on a one-word reply, and 2.8× the wall clock
on a checklist-reduce-shaped call versus the same call with thinking off.

This document covers the **plumbing** half of #26 only, per the scope decision made when this
was brainstormed: a setting that lets an operator turn reasoning off, threaded through all three
providers the same way `CHAT_TIMEOUT_SECONDS` now is. It does **not** cover #26's last open
question — whether disabling reasoning costs checklist or answer quality. That stays open; `uv
run pytest -m model` is the suite that would have an opinion, and it is a follow-up, not part of
this change.

It also does not reopen the "one setting or two?" question #26 raised. Timeout forked into
`CHAT_TIMEOUT_SECONDS` / `GENERATION_TIMEOUT_SECONDS` because a reduce call and an interactive
answer have genuinely different *durations*. Reasoning is a binary preference, not a duration,
and classify/grade are cheap enough either way (#26 says so directly) that a single instance-wide
value is enough. If that stops being true, splitting it is the same shape of change the timeout
already went through.

## 1. Two new settings, both opt-in

```python
# app/config.py, beside the other chat_* fields
chat_reasoning: Literal["default", "off"] = "default"
chat_extra_model_kwargs: dict[str, Any] = Field(default_factory=dict)
```

Both defaults are the current, unconfigured behavior. An instance that sets neither answers
exactly as it does today — this is a pure opt-in, not a behavior change.

**`chat_reasoning` reaches all three providers, not one.** #28 exists because a setting applied
in only one place produces a silent gap everywhere else. `chat_reasoning="off"` would be that
same defect if it only reached, say, the OpenAI branch.

**`chat_extra_model_kwargs` is scoped to the OpenAI branch only, and that is not the same gap.**
`chat_provider="openai"` (`app/config.py:156`) is not "OpenAI the company" — it is any
OpenAI-compatible chat completions endpoint, `chat_base_url` pointed wherever the operator likes.
Self-hosted servers behind that setting (vLLM, SGLang, and similar) frequently do not honor
`reasoning_effort` and instead expect something server-specific — `chat_template_kwargs:
{"enable_thinking": false}` is one real example. LangChain's own `BaseChatOpenAI.extra_body`
field is documented, in the library itself, as the mechanism for exactly this: "additional JSON
properties... to OpenAI compatible APIs, such as vLLM, LM Studio, or other providers." Ollama and
Anthropic have no equivalent gap — their reasoning knobs (`reasoning: bool`, `thinking: dict`)
are unambiguous — so there is nothing for a generic escape hatch to paper over there. Scoping it
to one provider here is the correct shape, not an oversight, and the field's docstring says so.

## 2. Per-provider mapping

`build_chat_model` (`app/rag/chat.py:31-94`) gains one more per-branch mapping, alongside the
existing `timeout` line. `"default"` means the parameter is omitted entirely — each provider's
own default behavior stands, unchanged from today. Only `"off"` sets anything:

| Provider | `chat_reasoning="off"` sets | `chat_reasoning="default"` sets |
| --- | --- | --- |
| Ollama (`app/rag/chat.py:57-67`) | `reasoning=False` | nothing (`reasoning=None`, today's behavior) |
| Anthropic (`app/rag/chat.py:69-83`) | `thinking={"type": "disabled"}` | nothing (`thinking=None`) |
| OpenAI / OpenAI-compatible (`app/rag/chat.py:85-94`) | `reasoning_effort="none"` | nothing |

`chat_extra_model_kwargs` forwards as `extra_body=dict(settings.chat_extra_model_kwargs) or
None` on the OpenAI branch, unconditionally — independent of `chat_reasoning`, because it is a
general escape hatch and reasoning happens to be its motivating case, not its only one.

Each provider's own vocabulary differs (`bool` / `dict` / string) on purpose. This mirrors how
`timeout` already reaches all three under three different field names
(`client_kwargs["timeout"]` / `timeout` / `timeout`) — the factory's job is exactly this kind of
per-provider translation, and `test_every_provider_gets_the_configured_timeout` is the existing
precedent for asserting it per provider rather than trusting a shared code path.

## 3. Validation and failure modes

`chat_reasoning` is a `Literal`, validated by pydantic at Settings load, same as `chat_provider`.
A misspelled value fails at startup, not at the first model call.

`chat_extra_model_kwargs` is deliberately unvalidated beyond being a JSON object — the tradeoff
#26 already names: an operator's typo in a provider-specific key surfaces as a normal provider
error on the first call, through the same `classify_chat_error` path every other provider failure
already goes through. No new error class, no new `ErrorCode`.

Neither setting introduces a new failure mode the retry ladder does not already handle: a
misconfigured `extra_body` key that the endpoint rejects is a chat error like any other, and
`classify_chat_error` decides retryable vs. terminal exactly as it does today.

## 4. Testing

`backend/tests/test_chat_model.py`, extending the existing suite in the same style as
`test_every_provider_gets_the_configured_timeout`:

- `chat_reasoning="off"` reaches all three providers with the shape in §2 —
  `ChatOllama.reasoning is False`, `ChatAnthropic.thinking == {"type": "disabled"}`,
  `ChatOpenAI.reasoning_effort == "none"`.
- `chat_reasoning="default"` (today's implicit behavior) leaves all three at `None` — the
  regression guard that the default stays behavior-preserving.
- `chat_extra_model_kwargs` reaches `ChatOpenAI.extra_body` and only that provider.

`backend/tests/test_config.py`: defaults are `"default"` and `{}`.

## 5. Docs, same change

Per `.claude/rules/documentation.md`, all in this change:

- `docs/configuration.md` — two new rows in the same format as `CHAT_TIMEOUT_SECONDS` /
  `GENERATION_TIMEOUT_SECONDS` (`docs/configuration.md:244-245`).
- `docs/llm.md` — the provider-variance note: what each provider's reasoning knob actually is,
  and the `extra_body` escape hatch for self-hosted OpenAI-compatible servers.
- `backend/.env.example` — `CHAT_REASONING=default` and `CHAT_EXTRA_MODEL_KWARGS={}`, in the chat
  group, names and defaults only.
- `CHANGELOG.md` — one line under `## [Unreleased]`.
- Issue #26 gets a comment noting this closes the plumbing half only; the quality-comparison
  question in its checklist stays open and unchecked.

## 6. Out of scope

- **The quality-comparison question.** Whether disabled reasoning degrades checklist or answer
  quality is unmeasured and stays that way here — flagged in #26 as a follow-up.
- **Splitting into a generation-side and interactive-side setting.** Reasoning is a preference,
  not a duration; see §0.
- **A typed field for `chat_extra_model_kwargs`'s contents.** It is deliberately opaque — see §1.
- **Anthropic's `reasoning_effort` (`effort`) tri-state field.** That is a shortcut for shaping
  `thinking` adaptively (`high`/`medium`/`low`/etc.), not an off switch, and is not part of a
  binary "off" design. A future `chat_reasoning` value between `"default"` and `"off"` could use
  it, but nothing here proposes one.

## 7. Build order

1. `Settings.chat_reasoning` / `Settings.chat_extra_model_kwargs` in `app/config.py`.
2. The per-provider mapping in `build_chat_model`.
3. `backend/.env.example`, `docs/configuration.md`, `docs/llm.md`.
4. Tests: `test_chat_model.py`, `test_config.py`.
5. `CHANGELOG.md`, the comment on #26.
