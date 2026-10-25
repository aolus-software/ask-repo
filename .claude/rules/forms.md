---
paths:
  - "frontend/**/*.tsx"
---

# Form Rules

One shape for every form in this app. If a new form does not fit these, change the rule
deliberately — do not fork a second style.

## 1. Dialog or page: count the inputs

| Form | Surface |
| --- | --- |
| **2–4 inputs**, all simple (text, select, single password) | `FormDialog` |
| **5+ inputs**, OR any checkbox picker, OR a repeatable/unbounded list | `FormPage` on its own route |
| A single destructive confirmation, no inputs | `ConfirmDialog` |
| **One control and a Save button** in a settings card (an inline-save section) | neither — a card on the screen that owns the setting |

A checkbox picker counts as "many" on its own, whatever the field count, because it has no fixed
height. A repeatable list counts too.

An inline-save settings section is a legitimate fourth surface: one control and its own Save button
inside a card, as in `components/profile/language-section.tsx` and
`components/projects/content-language-section.tsx`. It saves one preference in place, so a dialog
or a page would only add a hop. It still follows §4 and §8 (backend-owned validation, toast on
success, stay put on error); it is not a shell, so a second control means moving it to a
`FormDialog`.

Applied to the screens the PRD describes:

| Surface | Fields | Verdict |
| --- | --- | --- |
| Create user (admin) | name, email, password, isAdmin | dialog |
| Reset a user's password | new password | dialog |
| Change own password (forced first login, and the profile's Password section) | current, new | `FormPage` |
| Create project | repoUrl, branch, pat, contentLanguage | dialog |
| Confirm project delete | none | `ConfirmDialog` |
| Confirm project reindex | none | `ConfirmDialog` |
| Generate mock data | count | inline control beside the module's Generate button — one field, no dialog or page |
| Edit QA pair | module, question, tags | dialog |
| Export checklist and mock data | project, parts, modules (a checkbox picker), four checklist filters | page, `/checklist/export` |

## 2. Both shells take the same props

`FormDialog` and `FormPage` share `title`, `description`, `submitLabel`, `isPending`, `error`,
`onSubmit`. Moving a form between them is a swap, not a rewrite. `FormDialog` adds
`open` / `onOpenChange`; `FormPage` adds `backHref`.

Never hand-roll a `<form>`, a submit row, or an error banner at a call site.

## 3. Dialog width is a size, never a class

`FormDialog` takes `size`: `sm` (28rem), `md` (36rem, the default), `lg` (48rem). The generated
`DialogContent` defaults to `sm:max-w-sm`, which is too cramped for a labelled form — inputs
wrap and the footer crowds. Pick a size; do not pass a `max-w-*` class.

## 4. The backend owns validation

The API returns `422` with a field map for schema violations (`response-api.md`). Parse it once
in the API client into `ApiError.fieldErrors` and `ApiError.fieldTypes`, read one field with the
function `useFieldErrorText()` returns (`lib/i18n/error-text.ts`), and render it in a
`FieldError`. It translates by Pydantic's error type through `forms.validation.<type>`, and falls
back to the backend's text for a type the catalogue does not know — which is how a service-level
rule such as the password policy still reaches the user verbatim. A form-level error renders
through `useErrorText()`, which translates by `ErrorCode`. **A form never renders `error.message`
or a `fieldErrors` entry directly**: that is English on a translated screen.

Client-side checks are limited to **required** and **shape** (an `@` in an email), purely so the
form answers instantly. Their messages come from the catalogue, in the namespace of the screen
that owns the form (`auth.login.emailRequired`), like every other string on it. **Never restate a backend rule** — a copy cannot be kept honest, and the
password policy in particular (12 chars, common-password list) lives in one place. **No `zod`,
no `react-hook-form`.**

A form-level `Alert` shows **only** when the backend named no fields. When it did, those messages
render against their own inputs and a banner repeating them is noise. Both shells implement this;
do not add a second banner.

## 5. Field composition

`Field` > `FieldLabel` + control + `FieldError`, inside the shell's `FieldGroup`. Every control
gets an `id` and its label an `htmlFor` — the tests query by label, and so do screen readers.

## 6. Seed edit forms during render, never from an effect

Compare the fetched record's id against a stored `seededId` and set state during render.
`react-hooks/set-state-in-effect` rejects the effect form and is right to: it cascades an extra
render pass on every settle. Keying on the id also means reopening on a different row re-seeds,
while the operator's own edits survive a refetch.

## 7. A form that reads before it writes handles its own error

An edit form fetches `GET /{id}` to seed itself. The client-side gate mirrors the backend but is
not it, so render the failure — `<Forbidden />` on `403`, `<NotFound />` on `404` — never an
empty form. Note which one applies: per `response-api.md`, a project you may not delete answers
`403`, while another user's conversation answers `404`.

## 8. Submitting

On success: a dialog closes, a page `router.push()`es back to `backHref`. Both invalidate the
resource's query prefix and toast. On error: stay put, keep the operator's input, surface the
message.

Replacement collections submit **every** selected id. An omitted id is a revocation, not an
untouched value.

## 9. Never put a secret in form state longer than the submit

A PAT typed into the create-project form is write-only: the API never returns it
(`docs/PRD.md` §4.1), so an edit form cannot seed the field and must not pretend to. Show an
empty control with helper text saying a stored token is left unchanged when blank. Never render a
masked placeholder that looks like a value — an operator will submit it thinking it is the real
one.

## 10. Long-running submits are not modal

Creating a project starts a clone-and-index that takes minutes. The form closes as soon as the
API accepts the job (`202`/`201`), and progress is shown on the project row. Never hold a dialog
open on a job, and never block the page — the operator will navigate away, and the flow must
survive it.
