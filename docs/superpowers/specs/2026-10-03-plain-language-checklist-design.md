# Plain-language QA Checklist: Design

**Date:** 2026-10-03
**Intent:** `docs/PRD.md` §4.3 (QA Checklist): an amendment to who a test case is written for
**Depends on:** M4's generator (map → reduce → change set) and the module refinement chat
**Scope:** prompt and schema text only — no table, route, setting or UI change

---

## 0. What this document covers

The QA Checklist is meant for **general QA**: any manual tester, including one new to testing
who has never opened the repository. Generated test cases currently read like a code review.
A real generation against a NestJS `users` module (`qwen-3.8-max`) produced, for example:

| Test case | Expected result (as generated) |
| --- | --- |
| Rejects missing user fetch | `usersService.findOne raises NotFoundException when user is missing (src/settings/users/users.service.ts:139-147).` |
| Rejects invalid email | `POST /users with malformed email fails validation with i18n message keyed validation.IS_EMAIL (src/settings/users/dto/create-user.dto.ts:…)` |
| Ignores missing forgot-password user | `usersService.sendForgotPasswordEmail silently returns if user is missing (src/settings/users/users.service.ts:265-269).` |

A tester working through the product's screens can observe none of `usersService.findOne`,
`NotFoundException`, `validation.IS_EMAIL` or a line range. The rows are unreadable to the
audience they were generated for, and the row cannot be executed as written.

This spec makes every generated `feature`, `test_name` and `expected_result` describe **what a
person does and what they see**, and nothing about the code.

What is **not** in scope: a per-module "technical / API tester" audience setting (considered,
§0.1 decision 2); rewriting rows that already exist; the mock-data generator, whose records
are data rather than prose; the module chat's *answers*, which stay technical because they are
a conversation about the code.

### 0.1 The decisions, made

1. **Plain language for everyone.** No file name, path or line number; no function, method,
   class, variable or table name; no HTTP method, URL path, status code or payload; no
   exception name, error-code constant or translation key; no code. Each observation is
   translated into the experience it produces.
2. **One audience, not a per-module setting.** A "technical (API tester)" mode was considered
   and deferred: it is a column, a form field and a second prompt variant, and nothing yet
   says a team needs it. Should one ask, it is an additive change on top of this one.
3. **The file reference moves, it is not lost.** Every item already stores its sources in
   `checklist_items.citations` (`app/models/checklist.py:177`), resolved by the generator from
   the model's `citation_paths` (`app/checklist/model_output.py:86`), and the grid shows them in
   the sources panel. The inline `(src/…:139-147)` suffix is a duplicate the prompt asked for
   by accident (§1.1). A developer who needs the code still has it one click away.
4. **Both writers follow the rule.** The reduce step and the refinement chat's propose step
   write into the same checklist, so they share one instruction block. The chat's own answer
   is not affected.

---

## 1. Why the rows are technical today

### 1.1 Three places teach it

1. **`REDUCE_SYSTEM`** (`backend/app/rag/prompts.py`) gives `"401 with code
   INVALID_CREDENTIALS"` as its example of an `expected_result`, and ends with *"Base every
   expectation on an observation you were given, and cite the file it came from."* A model
   reads "cite the file" as "write the file into the text", which is exactly the suffix in §0.
2. **`ProposedOperation.expected_result`'s field description**
   (`backend/app/checklist/model_output.py`) says *"the status code, message or state, e.g.
   '401 with code INVALID_CREDENTIALS'"*. Structured output sends field descriptions to the
   model as part of the schema, so this teaches status codes even where the prompt does not.
3. **`MAP_FILE_SYSTEM`** asks for observations about exposures, validations, raises and
   returns, with line ranges. That is **correct and stays**: the map output is internal input
   to the reduce step, never shown to a tester, and its precision is what lets the reduce step
   cover refusals. The translation into plain language belongs in the reduce step, which is
   the one that writes rows.

### 1.2 `PROPOSE_SYSTEM` says nothing either way

The refinement chat proposes operations from its own answer, which is technical and cited by
design (`ANSWER_SYSTEM`). With no instruction, a chat-proposed row inherits the answer's
vocabulary.

---

## 2. The change

### 2.1 One shared block: `TESTER_LANGUAGE`

A new upper-case constant in `backend/app/rag/prompts.py`, so it is under `PROMPT_VERSION` and
feedback's before/after comparison sees the change:

```
Write every `feature`, `test_name` and `expected_result` for a manual tester who has never
seen the source code and may be new to testing. They work through the application's screens,
so describe what a person does and what they see.

Never write any of these into those three fields:
  - a file name, a path or a line number;
  - a function, method, class, variable or database table name;
  - an HTTP method, a URL path, a status code or a request payload;
  - an exception name, an error-code constant or a translation key;
  - code, or any term only a developer would know.

Translate each observation into what the person experiences. "Raises NotFoundException"
becomes "the page says the user could not be found". "422 with validation.IS_EMAIL" becomes
"the form refuses the email address and says it is not valid". When the code quietly does
nothing, say what the person notices: "the same confirmation message is shown, and no email
arrives".

The files an expectation came from go in `citation_paths`, and only there. The tester's
sources panel shows them; the expectation itself never mentions a file.
```

The wording is a starting point, tuned against the `-m model` case in §3. What the design
fixes is the five banned categories, the translate-don't-omit instruction, and the redirect
to `citation_paths`.

**Translate, never drop.** A negative case the code describes as "silently returns" is still
a test — "requesting a reset for an unknown email shows the same confirmation and sends no
email" is exactly the check a security-minded tester should run. The block must not read as
"skip what a user cannot see"; the existing positive/negative coverage rules in
`REDUCE_SYSTEM` are unchanged and still apply.

### 2.2 `REDUCE_SYSTEM`

- The `expected_result` bullet's definition and example become: *what the tester should see
  when the application behaves correctly, specifically. "The sign-in is refused and the page
  says the email or password is wrong".* `test_name`'s example ("Rejects a wrong password") is
  already plain and stays.
- *"…and cite the file it came from."* becomes *"…and list the file it came from in
  `citation_paths`."*
- `TESTER_LANGUAGE` is appended, after the operations instructions, so it is the last thing
  the model reads before writing.

### 2.3 `PROPOSE_SYSTEM`

`TESTER_LANGUAGE` is appended. Nothing else changes: an empty operation list is still the
right answer to a question that changes nothing.

### 2.4 `ProposedOperation`'s field descriptions

- `expected_result`: *"what the tester should SEE when the application behaves correctly, in
  plain words with no code, file names or status codes, e.g. 'The sign-in is refused and the
  page says the email or password is wrong'"*.
- `citation_paths` gains a description: *"the files this expectation came from — the only
  place a file is ever named"*. Today it has none, and a model is more likely to fill a field
  it has been told the purpose of.

These descriptions live outside `prompts.py`, so they are **not** under `PROMPT_VERSION`. That
is an existing property of every structured schema in the app and is not changed here; it is
named so a reviewer is not surprised that editing them leaves the version alone.

---

## 3. Testing

| Test | Asserts |
| --- | --- |
| `test_checklist_prompts.py` | `TESTER_LANGUAGE` is in the reduce and propose system messages; the reduce prompt names `citation_paths`; it no longer contains `INVALID_CREDENTIALS` or "cite the file"; `ProposedOperation.expected_result`'s description contains neither `INVALID_CREDENTIALS` nor "status code"; `citation_paths` has a description |
| `test_prompt_version.py` | Updated only if it pins a literal hash |
| `test_rag_model_integration.py` (`-m model`) | **New:** a reduce run over technical observations (an exception, a 422 with a translation key, a "silently returns", an HTTP route) produces rows whose `feature`, `test_name` and `expected_result` match none of: a source-file path (`\b[\w./-]+\.(py|ts|tsx|js|java|go|rb)\b`), a line range (`:\d+-\d+`), an HTTP verb followed by `/`, a three-digit status code (`\b[1-5]\d\d\b`), a `camelCase` or `snake_case` identifier, an `UPPER_SNAKE` constant, or the word `Exception`; at least one operation carries a non-empty `citation_paths`; the "silently returns" observation still yields a row (translate, not drop). **Existing** reduce cases keep passing — both kinds, named tests, update-not-duplicate |
| `test_rag_model_integration.py` (`-m model`) | **New:** a propose run from a technical chat answer ("`usersService.findOne` raises `NotFoundException` [1]") that calls for one `add` produces a row passing the same pattern check |

The model-backed cases are the only real check: `ScriptedChatModel` returns whatever a test
scripts, so the unit suite passes against a prompt that asks for anything. Run
`uv run pytest -m model` against a hosted provider; do not start a local Ollama for it.

---

## 4. Rows that already exist

Nothing is rewritten. `REDUCE_SYSTEM` tells the model that an item which is still *correct*
must not appear in its operations, because a tester may have recorded results against it — and
a technical row is still correct. Regenerating a module therefore leaves its technical rows in
place and adds plain ones only for what is missing.

Rewording existing rows is a separate decision with a real cost (a reworded expectation looks,
to a reviewer, like a changed one), and is out of scope. An editor can reword a row by hand
today (`item.edit`), and the refinement chat can propose an `update` when asked ("rewrite
these in plain language"), which this change makes produce plain text.

---

## 5. Documentation moved in the same change

- `docs/PRD.md` §4.3: a decision bullet — "**Written for any tester.** Test names and expected
  results describe what a person does and sees, never the code: no paths, identifiers, HTTP
  details, status or error codes. The files an expectation came from are its `citations`,
  shown as sources, never repeated in the text." The schema comment at `docs/PRD.md:811`
  changes from `# "401 with code INVALID_CREDENTIALS"` to `# "The sign-in is refused and the
  page says the email or password is wrong"`.
- `docs/llm.md` or `docs/rag.md`, wherever the reduce and propose prompts are described: one
  sentence on `TESTER_LANGUAGE`.
- `CHANGELOG.md` under `## [Unreleased]` → Changed: "Generated QA Checklist test cases are
  written in plain language for any tester — no file paths, code names, HTTP details or error
  codes; sources stay in the sources panel."
- `.claude/rules/rag.md` needs no change: it governs the answer path, and this rule lives in
  the prompt's own comment and `docs/PRD.md` §4.3.
