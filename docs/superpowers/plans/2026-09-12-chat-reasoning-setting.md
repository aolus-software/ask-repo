# Configurable Chat Reasoning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator turn off hidden reasoning/"thinking" tokens on the chat model, via two new `Settings` fields that reach all three providers `build_chat_model` already branches on.

**Architecture:** `Settings.chat_reasoning` (`Literal["default", "off"]`) is mapped per-provider inside `build_chat_model` (`backend/app/rag/chat.py`) using each provider's own vocabulary — `reasoning: bool` on Ollama, `thinking: dict` on Anthropic, `reasoning_effort: str` on OpenAI/OpenAI-compatible. `Settings.chat_extra_model_kwargs` (`dict[str, Any]`) forwards verbatim as `extra_body`, scoped to the OpenAI branch only, as an escape hatch for self-hosted OpenAI-compatible servers whose thinking toggle isn't `reasoning_effort`. Both default to today's behavior — nothing changes for an instance that sets neither.

**Tech Stack:** Python 3.13, pydantic-settings, LangChain (`langchain-ollama`, `langchain-anthropic`, `langchain-openai`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-chat-reasoning-setting-design.md`

## Global Constraints

- Both new settings default to values that reproduce **today's** behavior exactly — this is a pure opt-in (spec §1).
- `chat_reasoning` must reach **all three** provider branches in `build_chat_model`, never just one (spec §1, citing #28's timeout gap as the failure shape to avoid).
- `chat_extra_model_kwargs` is scoped to the `openai` branch **only** — do not wire it into Ollama or Anthropic (spec §1, §2).
- Neither setting gets new validation beyond the `Literal` on `chat_reasoning` — `chat_extra_model_kwargs` stays a plain unvalidated `dict[str, Any]` (spec §3).
- No new `ErrorCode`, no new exception class — a bad `chat_extra_model_kwargs` key surfaces as an ordinary provider error through the existing `classify_chat_error` path (spec §3).
- This plan covers plumbing only. Do not add anything measuring answer/checklist quality with reasoning off — that is explicitly out of scope (spec §6).

---

### Task 1: `Settings` fields

**Files:**
- Modify: `backend/app/config.py:5` (import), `backend/app/config.py:172` (after `chat_max_concurrency`)
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces: `Settings.chat_reasoning: Literal["default", "off"]` (default `"default"`), `Settings.chat_extra_model_kwargs: dict[str, Any]` (default `{}`). Task 2 reads both off a `Settings` instance.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_config.py`:

```python
def test_chat_reasoning_defaults_to_unconfigured() -> None:
    """Off by default in the sense of "unset" -- an instance that configures
    nothing must answer exactly as it did before this setting existed (#26)."""
    settings = Settings()
    assert settings.chat_reasoning == "default"
    assert settings.chat_extra_model_kwargs == {}


def test_chat_reasoning_rejects_an_unknown_value() -> None:
    with pytest.raises(ValidationError, match="chat_reasoning"):
        Settings(chat_reasoning="thinking-hard")  # type: ignore[arg-type]  # test builder
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_config.py -k chat_reasoning -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'chat_reasoning'`

- [ ] **Step 3: Add the fields**

In `backend/app/config.py`, change the `typing` import on line 5:

```python
from typing import Any, Literal, Self
```

Then insert immediately after `chat_max_concurrency: int = Field(default=2, ge=1)` (currently `backend/app/config.py:172`):

```python
    # Off ("default") is the safe direction: an instance that sets nothing answers
    # exactly as it does today. Reasoning models spend most of their output on hidden
    # chain-of-thought nobody reads (issue #26) -- "off" tells build_chat_model to
    # explicitly disable it on all three providers, in whatever vocabulary each one uses.
    chat_reasoning: Literal["default", "off"] = "default"
    # Forwarded verbatim as `extra_body` on the `openai` branch only. That branch is a
    # catch-all for any OpenAI-*compatible* endpoint (docs/llm.md), and self-hosted
    # servers behind it often need a provider-specific key `reasoning_effort` does not
    # cover -- e.g. `{"chat_template_kwargs": {"enable_thinking": false}}`. Ollama and
    # Anthropic already have unambiguous typed reasoning knobs, so there is nothing for a
    # generic pass-through to paper over there. Unvalidated on purpose: a bad key is a
    # provider error like any other, not a new failure mode.
    chat_extra_model_kwargs: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_config.py -k chat_reasoning -v`
Expected: PASS, 2 passed

- [ ] **Step 5: Run the full config test file and the linter**

Run: `cd backend && uv run pytest tests/test_config.py -v && uv run ruff check app/config.py`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat: add chat_reasoning and chat_extra_model_kwargs settings"
```

---

### Task 2: Per-provider mapping in `build_chat_model`

**Files:**
- Modify: `backend/app/rag/chat.py:31-94`
- Test: `backend/tests/test_chat_model.py`

**Interfaces:**
- Consumes: `Settings.chat_reasoning`, `Settings.chat_extra_model_kwargs` (Task 1).
- Produces: no new public names — `build_chat_model`'s existing signature is unchanged, it now additionally reads the two fields above.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chat_model.py`:

```python
def test_reasoning_off_reaches_every_provider() -> None:
    """#26: a reasoning model spends most of its output on hidden chain-of-thought
    nobody reads. `chat_reasoning="off"` has to reach every provider the same
    complete way `chat_timeout_seconds` does after #28, or the gap that fixed
    reopens here for reasoning instead of timeouts."""

    def built(provider: str) -> BaseChatModel:
        settings = settings_for(provider).model_copy(update={"chat_reasoning": "off"})
        return build_chat_model(settings)

    ollama_model = built("ollama")
    assert isinstance(ollama_model, ChatOllama)
    assert ollama_model.reasoning is False

    anthropic_model = built("anthropic")
    assert isinstance(anthropic_model, ChatAnthropic)
    assert anthropic_model.thinking == {"type": "disabled"}

    openai_model = built("openai")
    assert isinstance(openai_model, ChatOpenAI)
    assert openai_model.reasoning_effort == "none"


def test_reasoning_default_leaves_every_provider_unset() -> None:
    """The regression guard: an instance that sets nothing must answer exactly as
    it did before this setting existed."""
    ollama_model = build_chat_model(settings_for("ollama"))
    assert isinstance(ollama_model, ChatOllama)
    assert ollama_model.reasoning is None

    anthropic_model = build_chat_model(settings_for("anthropic"))
    assert isinstance(anthropic_model, ChatAnthropic)
    assert anthropic_model.thinking is None

    openai_model = build_chat_model(settings_for("openai"))
    assert isinstance(openai_model, ChatOpenAI)
    assert openai_model.reasoning_effort is None


def test_extra_model_kwargs_reach_only_the_openai_client() -> None:
    """The escape hatch for self-hosted OpenAI-compatible servers whose thinking
    toggle is not `reasoning_effort` -- e.g. a vLLM endpoint expecting
    `chat_template_kwargs`. Scoped to the `openai` branch: Ollama and Anthropic
    already have unambiguous typed knobs, so there is nothing for a generic
    escape hatch to paper over there."""
    settings = settings_for("openai").model_copy(
        update={
            "chat_extra_model_kwargs": {"chat_template_kwargs": {"enable_thinking": False}}
        }
    )

    model = build_chat_model(settings)

    assert isinstance(model, ChatOpenAI)
    assert model.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_extra_model_kwargs_default_to_no_extra_body() -> None:
    model = build_chat_model(settings_for("openai"))
    assert isinstance(model, ChatOpenAI)
    assert model.extra_body is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_chat_model.py -v`
Expected: the four new tests FAIL — `ollama_model.reasoning` is `None` when the test expects `False` (and similarly for the other two providers); `AttributeError` is not raised since the fields already exist on the LangChain classes, only the wiring from `Settings` is missing.

- [ ] **Step 3: Implement the mapping**

In `backend/app/rag/chat.py`, replace the body of `build_chat_model` (currently `backend/app/rag/chat.py:31-94`) with:

```python
def build_chat_model(settings: Settings, *, timeout_seconds: int | None = None) -> BaseChatModel:
    """The chat model this instance is configured to use.

    **Every provider gets `chat_timeout_seconds`, and that is not decoration.** The
    setting used to be applied in exactly one place -- the graph's answer nodes
    (`app/rag/graph/build.py`) -- so a question was bounded while checklist generation,
    mock-data generation, and the classify and grade nodes were not. They fell back to
    the provider client's own default, which for the OpenAI client is ten minutes per
    request and three attempts.

    The symptom was not an error. A checklist generation whose reduce step stalled sat
    there for half an hour per attempt, and the run looked slow rather than broken.

    `timeout_seconds` overrides `chat_timeout_seconds` for callers whose calls are not
    interactive. The worker passes `generation_timeout_seconds`, because one number
    cannot serve both: a checklist reduce folds every file's findings into a single
    structured call and legitimately runs for minutes, while a question that has not
    started answering in that long has failed. Bounding both at the interactive figure
    cuts the reduce off mid-call -- which surfaces as `RetryableChatError` with no HTTP
    response logged, since the request never completed -- and the retry ladder then
    spends the whole budget re-running a call that was always going to take longer than
    it was given.

    `chat_reasoning` gets the same complete treatment (issue #26): "default" omits the
    parameter on every provider, leaving its own default behavior untouched; "off"
    explicitly disables reasoning on all three, in whatever vocabulary each one uses.
    `chat_extra_model_kwargs` is a separate, narrower escape hatch -- forwarded as
    `extra_body` on the `openai` branch only, for self-hosted OpenAI-compatible servers
    whose thinking toggle isn't `reasoning_effort`.
    """
    timeout = timeout_seconds if timeout_seconds is not None else settings.chat_timeout_seconds
    reasoning_off = settings.chat_reasoning == "off"

    if settings.chat_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.chat_model,
            base_url=settings.chat_base_url,
            temperature=settings.chat_temperature,
            # No first-class timeout field on this class; the underlying Ollama client
            # takes one and passes it to httpx.
            client_kwargs={"timeout": timeout},
            reasoning=False if reasoning_off else None,
        )

    if settings.chat_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            # `model_name` here, not `model`: the field's alias is what mypy's
            # pydantic plugin synthesizes into the constructor signature, and
            # `populate_by_name` isn't enough to make it accept the bare field name too.
            model_name=settings.chat_model,
            base_url=settings.chat_base_url,
            api_key=settings.chat_api_key or "",  # type: ignore[arg-type]  # SecretStr coerces
            temperature=settings.chat_temperature,
            timeout=timeout,
            max_retries=PROVIDER_RETRIES,
            stop=None,
            thinking={"type": "disabled"} if reasoning_off else None,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.chat_model,
        base_url=settings.chat_base_url,
        api_key=settings.chat_api_key or "",  # type: ignore[arg-type]  # SecretStr coerces
        temperature=settings.chat_temperature,
        timeout=timeout,
        max_retries=PROVIDER_RETRIES,
        reasoning_effort="none" if reasoning_off else None,
        extra_body=dict(settings.chat_extra_model_kwargs) or None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_chat_model.py -v`
Expected: PASS, all tests in the file green

- [ ] **Step 5: Run the full backend test suite and the linter**

Run: `cd backend && uv run pytest && uv run ruff check app/rag/chat.py && uv run ruff format --check app/rag/chat.py`
Expected: all pass, no lint or format diffs

- [ ] **Step 6: Commit**

```bash
git add backend/app/rag/chat.py backend/tests/test_chat_model.py
git commit -m "feat: map chat_reasoning and chat_extra_model_kwargs into build_chat_model"
```

---

### Task 3: Docs and changelog

**Files:**
- Modify: `backend/.env.example:91-98`
- Modify: `docs/configuration.md:237-246`
- Modify: `docs/llm.md:58-66`
- Modify: `CHANGELOG.md:11-33`

**Interfaces:**
- Consumes: nothing from earlier tasks — this is documentation only, but it documents the fields Task 1 defined and the mapping Task 2 implemented, so it must be written and merged after both.
- Produces: nothing consumed by another task. This is the last task in the plan.

- [ ] **Step 1: Add the two variables to `backend/.env.example`**

In `backend/.env.example`, the chat model group currently reads (lines 91-98):

```
CHAT_PROVIDER=ollama
CHAT_MODEL=qwen2.5-coder:14b
CHAT_BASE_URL=http://localhost:11434
CHAT_API_KEY=
CHAT_TEMPERATURE=0.1
CHAT_TIMEOUT_SECONDS=180
GENERATION_TIMEOUT_SECONDS=600
CHAT_MAX_CONCURRENCY=2
```

Add two lines after `CHAT_MAX_CONCURRENCY=2`:

```
CHAT_REASONING=default
CHAT_EXTRA_MODEL_KWARGS={}
```

- [ ] **Step 2: Add two rows to the chat model table in `docs/configuration.md`**

The table currently ends with the `CHAT_MAX_CONCURRENCY` row (`docs/configuration.md:246`, reading `| `CHAT_MAX_CONCURRENCY` | `2` | Answers generated at once, instance-wide |`). Insert two new rows immediately after it, before the blank line that follows:

```markdown
| `CHAT_REASONING` | `default` | `default` leaves each provider's own reasoning behavior untouched; `off` explicitly disables it -- `reasoning=False` on Ollama, `thinking={"type": "disabled"}` on Anthropic, `reasoning_effort="none"` on the `openai` branch. Reaches all three providers the same way `CHAT_TIMEOUT_SECONDS` does after 2026-09-12, so it cannot silently miss one (issue #26) |
| `CHAT_EXTRA_MODEL_KWARGS` | `{}` | A JSON object forwarded verbatim as `extra_body`, on the `openai` branch only. The escape hatch for a self-hosted OpenAI-compatible server (vLLM, SGLang, ...) whose thinking toggle isn't `reasoning_effort` -- e.g. `{"chat_template_kwargs": {"enable_thinking": false}}`. Unvalidated: a key the endpoint rejects is a provider error like any other |
```

- [ ] **Step 3: Add a "Reasoning control" section to `docs/llm.md`**

`docs/llm.md` currently has this `---` separator between "Choosing a provider" and "How LangChain is actually used" (`docs/llm.md:58-66`):

```
- **It returns `BaseChatModel`, not a hand-rolled protocol.** `astream` and `ainvoke` are the
  entire interface used, and LangChain ships streaming-capable test doubles; a protocol wrapping
  two methods would buy indirection and cost those fakes.

Switching providers is configuration, not a migration — no re-index, no change to stored
citations.

---

## How LangChain is actually used
```

Insert a new section between the two `---`-delimited blocks, so the file reads:

```markdown
- **It returns `BaseChatModel`, not a hand-rolled protocol.** `astream` and `ainvoke` are the
  entire interface used, and LangChain ships streaming-capable test doubles; a protocol wrapping
  two methods would buy indirection and cost those fakes.

Switching providers is configuration, not a migration — no re-index, no change to stored
citations.

---

## Reasoning control

Some chat models spend most of their output on hidden chain-of-thought before the answer they
return — reasoning models, including plenty served through the `openai` catch-all branch above.
Left unconfigured, none of that is visible: the answer looks normal, while the bill and the
latency do not (issue #26). `CHAT_REASONING=off` tells `build_chat_model` to explicitly disable
it, in whatever vocabulary each provider actually uses:

| Provider | `CHAT_REASONING=off` sets | `CHAT_REASONING=default` (unset) |
| --- | --- | --- |
| Ollama | `reasoning=False` | nothing — the model's own default stands |
| Anthropic | `thinking={"type": "disabled"}` | nothing |
| OpenAI-compatible | `reasoning_effort="none"` | nothing |

`CHAT_EXTRA_MODEL_KWARGS` is the escape hatch for the `openai` branch specifically, because that
branch is a catch-all for *any* OpenAI-compatible endpoint (see above), and self-hosted servers
behind it — vLLM, SGLang, and similar — often expect a server-specific key instead of
`reasoning_effort`:

```bash
CHAT_EXTRA_MODEL_KWARGS={"chat_template_kwargs": {"enable_thinking": false}}
```

It is forwarded verbatim as `extra_body` and deliberately unvalidated: a key the endpoint does
not recognize is a provider error like any other, not a new failure mode. Ollama and Anthropic
have no equivalent field — their reasoning knobs above are already unambiguous, so there is
nothing for a generic pass-through to paper over.

Neither setting changes what the graph asks a model to produce — the content contract is
unaffected either way. Whether disabled reasoning costs answer or checklist quality is
unmeasured; `uv run pytest -m model` is the suite that would have an opinion.

---

## How LangChain is actually used
```

- [ ] **Step 4: Add a changelog entry**

In `CHANGELOG.md`, the `### Added` section under `## [Unreleased]` currently ends with the
`INDEXED_PATH_*` bullet (`CHANGELOG.md:32-34`). Append a new bullet immediately after it, before
the `### Fixed` heading:

```markdown
- **`CHAT_REASONING` and `CHAT_EXTRA_MODEL_KWARGS`**, so an operator can turn off a reasoning
  model's hidden chain-of-thought (issue #26). `CHAT_REASONING=off` reaches all three providers
  `build_chat_model` supports, in each one's own vocabulary; `CHAT_EXTRA_MODEL_KWARGS` is a
  narrower escape hatch, forwarded as `extra_body` on the `openai` branch only, for self-hosted
  OpenAI-compatible servers whose thinking toggle isn't `reasoning_effort`. Both default to
  today's behavior — this is a pure opt-in.
```

- [ ] **Step 5: Verify the docs changes render sanely**

Run: `cd /Users/zulfikar/dev/opensources/ask-repo && grep -n "CHAT_REASONING\|CHAT_EXTRA_MODEL_KWARGS" backend/.env.example docs/configuration.md docs/llm.md CHANGELOG.md`
Expected: each file lists both variable names at least once, confirming no insertion was dropped.

- [ ] **Step 6: Run the backend checks one more time**

Run: `cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all pass — this task touches no `.py` files, so this is a no-op sanity check that the tree is still clean.

- [ ] **Step 7: Commit**

```bash
git add backend/.env.example docs/configuration.md docs/llm.md CHANGELOG.md
git commit -m "docs: document CHAT_REASONING and CHAT_EXTRA_MODEL_KWARGS"
```

- [ ] **Step 8: Comment on issue #26**

Run:

```bash
gh issue comment 26 --body "$(cat <<'EOF'
The plumbing half of this is done on `feat-configurable-chat-reasoning` (stacked on #28):
`CHAT_REASONING=off` disables reasoning on all three providers, and `CHAT_EXTRA_MODEL_KWARGS`
is an escape hatch for self-hosted OpenAI-compatible servers that don't honor
`reasoning_effort`. See `docs/superpowers/specs/2026-09-12-chat-reasoning-setting-design.md`.

Still open: the quality-comparison question below — nobody has compared checklist or answer
output with and without reasoning. Leaving that unchecked.
EOF
)"
```

Expected: the comment posts successfully; issue #26 stays open with its quality-comparison
checkbox unchecked.

---

## Self-Review

**Spec coverage:**
- §1 (two settings, both opt-in) → Task 1.
- §2 (per-provider mapping table) → Task 2, Step 3.
- §3 (validation, no new error class) → Task 1 Step 1 (`Literal` rejection test); Task 2 has no new exception handling, matching the spec's "no new failure mode" call.
- §4 (testing) → Task 1 Step 1, Task 2 Step 1.
- §5 (docs, same change) → Task 3 covers `.env.example`, `docs/configuration.md`, `docs/llm.md`, `CHANGELOG.md`, and the #26 comment.
- §6 (out of scope) → nothing in this plan touches quality comparison, a generation/interactive split, a typed `chat_extra_model_kwargs`, or Anthropic's `reasoning_effort` tri-state field.
- §7 (build order) → Tasks 1, 2, 3 follow it exactly.

**Placeholder scan:** no "TBD"/"handle it"/"similar to Task N" language; every step has complete code or an exact doc excerpt.

**Type consistency:** `chat_reasoning: Literal["default", "off"]` and `chat_extra_model_kwargs: dict[str, Any]` are named identically across Task 1's implementation, Task 2's usage, and Task 3's docs. `reasoning_off = settings.chat_reasoning == "off"` is a local variable, not a public interface, and is used consistently within `build_chat_model`.
