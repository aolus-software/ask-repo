# Plain-language QA Checklist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every generated QA Checklist `feature`, `test_name` and `expected_result` describe what a person does and sees, never the code, with the file reference kept only in `citation_paths`.

**Architecture:** Prompt and schema text only. A new `TESTER_LANGUAGE` constant in `app/rag/prompts.py` is appended to the system message by `build_reduce_prompt` and `build_propose_prompt`. `REDUCE_SYSTEM` loses its status-code example and its "cite the file" sentence. `ProposedOperation`'s field descriptions stop teaching status codes. Model-backed tests check the behaviour.

**Tech Stack:** Python 3.13, LangChain messages, Pydantic `Field` descriptions, pytest (`-m model` marker for real-model checks).

**Spec:** `docs/superpowers/specs/2026-10-03-plain-language-checklist-design.md`

## Global Constraints

- No table, route, setting, migration or UI change.
- `MAP_FILE_SYSTEM`, `ANSWER_SYSTEM` and the mock-data prompts are unchanged.
- Banned from generated `feature` / `test_name` / `expected_result`: file names, paths, line numbers; function / method / class / variable / table names; HTTP methods, URL paths, status codes, payloads; exception names, error-code constants, translation keys; code.
- Translate, never drop: an observation the code describes as "silently returns" still produces a test.
- `TESTER_LANGUAGE` is an upper-case `str` constant in `app/rag/prompts.py`, so it is under `PROMPT_VERSION`.
- Existing checklist rows are not rewritten.
- Never start a local Ollama for the `-m model` tests; run them against a configured hosted provider, or leave them skipped and say so.
- Backend commands run from `backend/`. Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

---

### Task 1: The shared tester-language block, in both prompts and the schema

**Files:**
- Modify: `backend/app/rag/prompts.py` (new constant above `REDUCE_SYSTEM`; two lines inside `REDUCE_SYSTEM`; `build_reduce_prompt` at :380–381; `build_propose_prompt` at :396–397)
- Modify: `backend/app/checklist/model_output.py` (`ProposedOperation.expected_result` and `citation_paths`)
- Test: `backend/tests/test_checklist_prompts.py`

**Interfaces:**
- Produces: `TESTER_LANGUAGE: str` in `app.rag.prompts`. `build_reduce_prompt(...)[0].content` and `build_propose_prompt(...)[0].content` both end with `"\n\n" + TESTER_LANGUAGE`.

- [ ] **Step 1: Write the failing tests**

Add `from app.checklist.model_output import ProposedOperation` above the existing `from app.checklist.source import ModuleFile`. Add `TESTER_LANGUAGE,` as the first name in the `from app.rag.prompts import (...)` block. Append:

```python
def test_reduce_prompt_writes_for_a_tester_who_has_never_seen_the_code() -> None:
    """A checklist is read by testers who may be new to testing and have never opened
    the repository. The model must be told to describe what a person does and sees,
    and told where the file reference goes instead -- "cite the file" is what put
    `(src/...:139-147)` at the end of every generated row."""
    system = str(build_reduce_prompt(module_name="Auth", observations=[], existing=[])[0].content)

    assert system.endswith(TESTER_LANGUAGE)
    assert "citation_paths" in system
    assert "INVALID_CREDENTIALS" not in system
    assert "cite the file" not in system


def test_propose_prompt_holds_chat_proposals_to_the_same_language() -> None:
    """The refinement chat writes into the same checklist. Its answer is technical by
    design; the rows it proposes must not be."""
    system = str(
        build_propose_prompt(module_name="Auth", answer="See users.service.ts.", existing=[])[
            0
        ].content
    )

    assert system.endswith(TESTER_LANGUAGE)


def test_tester_language_names_every_banned_category() -> None:
    lowered = TESTER_LANGUAGE.lower()
    for phrase in (
        "file name",
        "line number",
        "function",
        "class",
        "http method",
        "status code",
        "exception",
        "error-code",
        "translation key",
    ):
        assert phrase in lowered, phrase


def test_the_schema_does_not_teach_status_codes() -> None:
    """Field descriptions reach the model inside the structured-output schema, so a
    technical example there undoes the prompt."""
    expected = ProposedOperation.model_fields["expected_result"].description or ""

    assert "INVALID_CREDENTIALS" not in expected
    assert "status code" not in expected.lower()
    assert ProposedOperation.model_fields["citation_paths"].description
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_checklist_prompts.py -v`
Expected: collection ERROR, `ImportError: cannot import name 'TESTER_LANGUAGE'`

- [ ] **Step 3: Add `TESTER_LANGUAGE`**

In `backend/app/rag/prompts.py`, directly above `REDUCE_SYSTEM = """\`:

```python
# Appended to the reduce and propose system messages, because both write rows into the
# same checklist. The reader is any manual tester, including one new to testing who has
# never opened the repository: a row describes what a person does and sees. The file it
# came from travels in `citation_paths` -- shown as sources -- and never in the text.
# Translate, never drop: a behaviour the code calls "silently returns" is still a test.
TESTER_LANGUAGE = """\
Write every `feature`, `test_name` and `expected_result` for a manual tester who has \
never seen the source code and may be new to testing. They work through the \
application's screens, so describe what a person does and what they see.

Never write any of these into those three fields:
  - a file name, a path or a line number;
  - a function, method, class, variable or database table name;
  - an HTTP method, a URL path, a status code or a request payload;
  - an exception name, an error-code constant or a translation key;
  - code, or any term only a developer would know.

Translate each observation into what the person experiences -- never leave one out \
because it is described in code terms. "Raises NotFoundException" becomes "the page \
says the user could not be found". "422 with validation.IS_EMAIL" becomes "the form \
refuses the email address and says it is not valid". When the code quietly does \
nothing, say what the person notices: "the same confirmation message is shown, and no \
email arrives".

The files an expectation came from go in `citation_paths`, and only there. The \
tester's sources panel shows them; the expectation itself never mentions a file.\
"""
```

- [ ] **Step 4: Fix the two technical lines in `REDUCE_SYSTEM`**

Replace:

```
  - `expected_result`: what a correct implementation should do, specifically. "401 \
with code INVALID_CREDENTIALS".
```

with:

```
  - `expected_result`: what the tester should see when the application behaves \
correctly, specifically. "The sign-in is refused and the page says the email or \
password is wrong".
```

Replace:

```
Base every expectation on an observation you were given, and cite the file it came \
from.
```

with:

```
Base every expectation on an observation you were given, and list the file it came \
from in `citation_paths`.
```

Everything else in `REDUCE_SYSTEM` stays, including the positive/negative coverage rules.

- [ ] **Step 5: Append the block in the two builders**

In `build_reduce_prompt`, change `SystemMessage(content=REDUCE_SYSTEM),` to:

```python
        SystemMessage(content=f"{REDUCE_SYSTEM}\n\n{TESTER_LANGUAGE}"),
```

In `build_propose_prompt`, change `SystemMessage(content=PROPOSE_SYSTEM),` to:

```python
        SystemMessage(content=f"{PROPOSE_SYSTEM}\n\n{TESTER_LANGUAGE}"),
```

The append happens at the builder rather than by redefining the constants, so `REDUCE_SYSTEM` and `PROPOSE_SYSTEM` stay single definitions. `PROMPT_VERSION` still covers all three, because each is an upper-case `str` constant. Update both builders' docstrings with one clause: "…with `TESTER_LANGUAGE` appended, so rows are written for a tester, not a developer."

- [ ] **Step 6: Fix the schema descriptions**

In `backend/app/checklist/model_output.py`, replace `expected_result`'s `description` with:

```python
        description=(
            "what the tester should SEE when the application behaves correctly, in "
            "plain words with no code, file names or status codes, e.g. 'The sign-in "
            "is refused and the page says the email or password is wrong'"
        ),
```

Replace `citation_paths: list[str] = Field(default_factory=list)` with:

```python
    citation_paths: list[str] = Field(
        default_factory=list,
        description="the files this expectation came from -- the only place a file is ever named",
    )
```

Keep the comment above it. Add one line to it: these descriptions are outside `prompts.py`, so editing them does not move `PROMPT_VERSION`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_checklist_prompts.py tests/test_prompt_version.py tests/test_checklist_generator.py tests/test_graph.py -v`
Expected: PASS. `test_prompt_version.py` computes the hash rather than pinning it, so it needs no edit.

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean. If `citation_paths`'s description line exceeds the line length, split the string in parentheses.

- [ ] **Step 8: Commit**

```bash
git add app/rag/prompts.py app/checklist/model_output.py tests/test_checklist_prompts.py
git commit -m "feat(checklist): write generated test cases in plain language for any tester"
```

---

### Task 2: Model-backed checks that the rows really are plain

**Files:**
- Modify: `backend/tests/test_rag_model_integration.py`

**Interfaces:**
- Consumes: `build_reduce_prompt`, `build_propose_prompt`, `ProposedChangeSet` (existing); the module's `settings` fixture and `build_chat_model`.

- [ ] **Step 1: Write the tests**

Add `build_propose_prompt` to the existing `from app.rag.prompts import (...)` block if it isn't there. Append:

```python
# What a tester who has never opened the repository cannot read. Each is something the
# old prompt produced in a real generation (spec §0).
TECHNICAL = {
    "source file": re.compile(r"\b[\w./-]+\.(py|ts|tsx|js|java|go|rb)\b"),
    "line range": re.compile(r":\d+-\d+"),
    "HTTP route": re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+/"),
    "status code": re.compile(r"\b[1-5]\d\d\b"),
    "camelCase identifier": re.compile(r"\b[a-z]+[A-Z][A-Za-z]*\b"),
    "snake_case identifier": re.compile(r"\b[a-z]+_[a-z_]+\b"),
    "UPPER_SNAKE constant": re.compile(r"\b[A-Z]{2,}_[A-Z_]+\b"),
    "exception name": re.compile(r"Exception\b"),
}


def _technical_terms(text: str) -> list[str]:
    return [name for name, pattern in TECHNICAL.items() if pattern.search(text)]


def _assert_plain(result: ProposedChangeSet) -> None:
    for operation in result.operations:
        for field in (operation.feature, operation.test_name, operation.expected_result):
            found = _technical_terms(field)
            assert not found, f"{found} in {field!r}"


async def test_reduce_writes_for_a_tester_who_has_never_seen_the_code(
    settings: Settings,
) -> None:
    """The rows a newcomer to testing has to execute. A model reading code-shaped
    observations must translate them into what a person does and sees -- and must
    still produce the test for a behaviour the code calls "silently returns", rather
    than dropping it as unobservable."""
    model = build_chat_model(settings).with_structured_output(ProposedChangeSet)
    result = await model.ainvoke(
        build_reduce_prompt(
            module_name="Users",
            observations=[
                (
                    "src/users/users.service.ts",
                    "findOne raises NotFoundException when the user id does not exist",
                    139,
                    147,
                ),
                (
                    "src/users/dto/create-user.dto.ts",
                    "POST /users with a malformed email fails with 422 and i18n key "
                    "validation.IS_EMAIL",
                    20,
                    24,
                ),
                (
                    "src/users/users.service.ts",
                    "sendForgotPasswordEmail silently returns when no user has the email",
                    265,
                    269,
                ),
                (
                    "src/users/users.controller.ts",
                    "POST /users with a valid name, email and strong password returns 201",
                    40,
                    61,
                ),
            ],
            existing=[],
        )
    )

    assert isinstance(result, ProposedChangeSet)
    assert result.operations
    _assert_plain(result)
    assert any(operation.citation_paths for operation in result.operations), (
        "no operation kept its source in citation_paths"
    )
    mentions_reset = [
        operation
        for operation in result.operations
        if "password" in f"{operation.test_name} {operation.expected_result}".lower()
    ]
    assert mentions_reset, "the 'silently returns' behaviour was dropped, not translated"


async def test_a_chat_proposal_from_a_technical_answer_is_plain(settings: Settings) -> None:
    """The chat's answer is technical and cited by design; the row it proposes must
    not inherit that vocabulary."""
    model = build_chat_model(settings).with_structured_output(ProposedChangeSet)
    result = await model.ainvoke(
        build_propose_prompt(
            module_name="Users",
            answer=(
                "There is no test for a missing user. `usersService.findOne` raises "
                "`NotFoundException` when the id does not exist [1], which the "
                "controller maps to a 404 (src/users/users.service.ts:139-147). You "
                "should add a negative test for it."
            ),
            existing=[],
        )
    )

    assert isinstance(result, ProposedChangeSet)
    assert result.operations, "the answer asked for a test and none was proposed"
    _assert_plain(result)
```

`re` is already imported at the top of this module (`CITATION_LABEL` uses it). `ProposedChangeSet` is imported. Check `Settings` and `build_chat_model` are imported too; they are used by the existing tests.

The `snake_case` pattern also matches ordinary words joined by an underscore, and the `camelCase` pattern also matches brand-style words such as "iPhone". If a real run fails only on such a false positive, tighten that one pattern and say why in a comment. Never loosen the prompt to fit the test.

- [ ] **Step 2: Check collection without a model**

Run: `uv run pytest tests/test_rag_model_integration.py -v`
Expected: the new tests are deselected or skipped (they carry the module's `pytestmark = pytest.mark.model`). No failure, no import error.

- [ ] **Step 3: Run against a real model, if one is configured**

Run: `uv run pytest tests/test_rag_model_integration.py -m model -k "plain or never_seen or reduce" -v`
Expected: PASS against a hosted provider, including the three existing reduce cases (both kinds, named tests, update-not-duplicate). If no provider is configured, it reports SKIPPED "no chat model at …". **Do not start Ollama.** Record "model suite not run: no provider" in the PR test plan instead.

If a run fails on content (a status code slipped through), adjust `TESTER_LANGUAGE`'s wording in Task 1's constant, re-run, and keep the five banned categories and the translate-never-drop sentence intact.

- [ ] **Step 4: Commit**

```bash
git add tests/test_rag_model_integration.py
git commit -m "test(checklist): check generated and chat-proposed rows carry no code terms"
```

---

### Task 3: Documentation moved in the same change

**Files:**
- Modify: `docs/PRD.md` (§4.3 decisions list, and the schema comment at :811)
- Modify: `docs/llm.md` (around :109, where the generation prompts are listed)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: PRD §4.3**

In the **Decisions** list of §4.3, after the bullet beginning "**`current_result` is only ever a human's observation.**", add:

```markdown
- **Written for any tester.** Generated test names and expected results describe what a person does in the application and what they see — never the code: no file paths or line numbers, no function or class names, no HTTP methods, routes or status codes, no exception names, error-code constants or translation keys. The checklist is for general QA, including someone new to testing who has never opened the repository. The files an expectation came from are its `citations`, shown as sources, never repeated in the text. Both the generator and the module chat's proposals follow this; the chat's own answers stay technical, since they are a conversation about the code. See `docs/superpowers/specs/2026-10-03-plain-language-checklist-design.md`.
```

In the item schema block, change:

```
    expected_result: str                # "401 with code INVALID_CREDENTIALS"
```

to:

```
    expected_result: str                # "The sign-in is refused and the page says the email or password is wrong"
```

Run `grep -n "INVALID_CREDENTIALS" docs/PRD.md` and fix any other place §4.3 uses it as an *example of an expected result*. Leave places that name the real error code.

- [ ] **Step 2: `docs/llm.md`**

Next to the sentence at :109 listing `MAP_FILE_SYSTEM`, `REDUCE_SYSTEM` and `PROPOSE_SYSTEM`, add:

```markdown
The reduce and propose system messages both end with `TESTER_LANGUAGE`, which holds every
generated row to plain language for a manual tester — no paths, code names, HTTP details or
error codes — and sends the file reference to `citation_paths` instead. The map step stays
technical on purpose: its observations are input to the reduce step, never shown to a tester.
```

- [ ] **Step 3: `CHANGELOG.md`**

Under `## [Unreleased]`, in its `### Changed` subsection (create it if absent, following the file's existing order of subsections):

```markdown
- Generated QA Checklist test cases — from generation and from the module chat — are written in plain language for any tester: no file paths, code names, HTTP details or error codes. Sources stay in the sources panel. Existing rows are not rewritten.
```

- [ ] **Step 4: Full check**

Run (repo root): `make check`
Expected: lint, format-check, typecheck and tests all pass.

- [ ] **Step 5: Commit**

```bash
git add docs/PRD.md docs/llm.md CHANGELOG.md
git commit -m "docs: record that generated checklist rows are written for any tester"
```
