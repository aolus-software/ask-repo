---
name: audit-ui
description: "Read-only audit of the frontend for visual and interaction inconsistency across every flow — login, forced password change, dashboard, projects, Ask, QA Checklist, Mock Data, and admin user management. Measures the code against docs/design.md and the design-system/forms/navigation rules. Writes findings to docs/ui-audit-findings.md. Never modifies a component."
risk: safe
source: local
date_added: "2026-09-13"
---

# UI Audit

Sweep `frontend/` for **inconsistency** — the same idea rendered two different ways on two
different screens — and record the results in `docs/ui-audit-findings.md`. This command
**never changes a component, a token, or a stylesheet**. Its only output is the findings
document.

`$ARGUMENTS` (optional) narrows the scope to flows or categories, e.g. `audit-ui checklist ask`
or `audit-ui forms tokens`. With no arguments, sweep every flow and every category.

## What this audit is looking for

Not "is this screen pretty". A pass here answers one question: **could a user tell which
screen they were on from the chrome alone, and would they be wrong about what it means?**

Three failure shapes, in descending order of cost:

1. **The same state rendered two ways.** A module that is `review` on the list and `ready` on
   the detail. A timestamp that is relative here and ISO there. These teach a user a rule the
   next screen breaks.
2. **A shared shell bypassed.** A screen that hand-rolls a page header, an empty state, or a
   submit row instead of using the one component that exists for it. Correct today; drifts the
   moment the shared one changes and this copy does not.
3. **A missing state.** An async surface with a loading path and a data path and no empty path,
   or no error path. Invisible until the day the list is empty.

## Ground truth — read these first, in this order

1. `docs/design.md` — the token table, typography scale, layout geometry, spacing intervals,
   component inventory, the list skeleton, the form contract, and the feedback table. **This is
   what findings are measured against.**
2. `.claude/rules/design-system.md` — the ten enforced rules.
3. `.claude/rules/forms.md` — dialog vs page, validation ownership, field composition.
4. `.claude/rules/navigation.md` — the single nav source, breadcrumbs, route gating.
5. `.claude/rules/frontend-bff.md` — only when a finding touches session, refresh, or the
   answer stream.
6. `frontend/app/globals.css` — the tokens as implemented. When it and `docs/design.md`
   disagree, that is itself a 📄 finding, not a doc to quietly prefer.

`docs/PRD.md` outranks all of the above. A screen that looks inconsistent because the PRD says
it should behave differently is **not** a finding — say so in the verified-correct notes.

## The calibration that decides whether this report is usable

**`frontend/components/ui/` is out of scope for every token, `dark:`, arbitrary-value, and
spacing check.** That directory is shadcn-CLI-managed (`design-system.md` §1), and its
generated source legitimately contains `dark:` variants, `rounded-[calc(...)]`, `bg-black/10`
overlays, and off-scale paddings. Auditing it produces dozens of hits that are all correct,
which buries the handful in app code that are not — and a report a reader learns to skim is
worth less than no report.

So every grep in this command excludes it:

```bash
grep -rn "<pattern>" --include='*.tsx' frontend/app frontend/components frontend/hooks \
  | grep -v 'components/ui/'
```

The one thing worth checking **inside** `components/ui/` is whether a file was hand-written
rather than CLI-generated — a component there with no `data-slot` attribute and no `useRender`
import is a rule violation regardless of how it looks.

## Flows to walk

Walk each one screen by screen, in the order a person actually hits them. For each, read the
route's `page.tsx`, its `*-screen.tsx`, and every component under `frontend/components/<area>/`
it renders.

| Flow | Route(s) | Screen file |
| --- | --- | --- |
| Login | `/login` | `app/(auth)/login/login-screen.tsx` |
| Forced password change | `/change-password` | `app/(auth)/change-password/change-password-screen.tsx` |
| Dashboard | `/` | `app/(app)/dashboard-screen.tsx` |
| Projects list + create | `/projects` | `app/(app)/projects/projects-screen.tsx` |
| Project detail, reindex, delete | `/projects/[id]` | `app/(app)/projects/[id]/project-detail-screen.tsx` |
| Ask — new conversation | `/ask` | `app/(app)/ask/new-conversation-screen.tsx` |
| Ask — streaming answer | `/ask/[conversationId]` | `app/(app)/ask/[conversationId]/conversation-screen.tsx` |
| QA Checklist modules | `/checklist` | `app/(app)/checklist/checklist-screen.tsx` |
| Module grid, generation, refinement chat, Mock Data tab | `/checklist/[moduleId]` | `app/(app)/checklist/[moduleId]/module-screen.tsx` |
| Admin — user management | `/settings/users` | `app/(app)/settings/users/users-screen.tsx` |

Cross-cutting chrome, audited once rather than per flow: `components/layout/` (app shell,
navbar, sidebar, breadcrumbs, account menu, theme toggle, list toolbar, page header,
pagination footer) and `components/feedback/` (empty state, not-found, forbidden, status badge,
table skeleton).

## Categories to cover

### 1. Token and theme discipline

App code only (see the calibration above). A raw hex, `rgb()`, `oklch()`, a literal
`rounded-[10px]`, a palette utility (`bg-zinc-50`, `text-slate-600`), `text-white` on a coloured
surface, or **any `dark:` colour utility** is a finding. `globals.css` is the only file allowed a
raw hex. `dark:` on a non-colour property (`dark:invert`) is fine.

Also check: every `bg-*` paired with its `-foreground`; a token referenced by a component that
`globals.css` does not define; and a token defined in `:root` but not redefined under `.dark`.

### 2. Shared shells, adopted or bypassed

For each shell, list which screens use it and which hand-roll the same thing:

| Shell | Hand-rolled equivalent to look for |
| --- | --- |
| `PageHeader` | a bare `<h1 className="text-3xl …">` plus a sibling action button |
| `EmptyState` | a bare "No results" / "Nothing here yet" paragraph |
| `TableSkeleton` | a spinner, or `Skeleton` rows whose count does not match the real columns |
| `ListToolbar` | a hand-built search + filter row |
| `PaginationFooter` | page buttons assembled at a call site |
| `FormDialog` / `FormPage` / `ConfirmDialog` | a raw `<form>`, a hand-built submit row, a bespoke error banner |
| `StatusBadge` | a `Badge` given a colour class at the call site |
| `Forbidden` / `NotFound` | an inline "you can't see this" message, or a redirect |

A screen legitimately outside a shell exists — a streaming conversation is not a list. Record
it under verified-correct with the reason, rather than as a finding or as silence.

### 3. The list skeleton

`docs/design.md` → Lists. For every list screen (`/projects`, `/checklist`, `/settings/users`)
check all six: page header with primary action right; toolbar above; a `Card` with no padding
wrapping the `Table`; pagination footer inside that same card; column order
**identity → status → timestamps → right-aligned actions**; and relative timestamps carrying an
absolute `title` via `formatRelative`/`formatAbsolute`.

A list that formats a date inline instead of through `lib/dates.ts` is a finding even when the
output happens to match.

### 4. Status and semantic colour — one mapping per state domain

`design-system.md` §5. Every status maps to a `StatusTone` in exactly one module, and every
badge renders through `StatusBadge`.

The live example to measure new code against: `lib/status.ts` owns the project mapping and
`components/checklist/module-status-badge.tsx` owns the module mapping. **Check whether a third
domain has appeared** — mock-data record state, change-set operation kind, staleness, a
checklist item's `current_result` — and whether it picked colours at its call site instead. Also
check whether two domains disagree about what one word means: `ready` is `success` for a
project and `success` for a module, and if some third surface renders `ready` as `info` that is
a finding.

Note for the report, not as a defect unless it has caused drift: the two mappings live in
different layers (one in `lib/`, one in a component). Say whether that has cost anything yet.

### 5. Forms

Against `.claude/rules/forms.md`, for every form in the app:

- **Dialog vs page by input count** — 2–4 simple inputs is a dialog; 5+, or any checkbox picker,
  or any repeatable list, is a `FormPage`. Check the count as built, not as the rule's table
  predicted.
- **Size, never a class** — `size="sm|md|lg"`, never a `max-w-*` at the call site.
- **No `zod`, no `react-hook-form`** — grep `package.json` and every import. Client-side checks
  limited to required-ness and shape.
- **No restated backend rule** — the password policy in particular. A hardcoded "12 characters"
  in a component is a finding even if it is currently the right number.
- **One error surface** — field errors inline via `fieldError`/`FieldError`; the form-level
  `Alert` only when the backend named no fields. Never both.
- **`Field` > `FieldLabel` + control + `FieldError`**, every control with an `id` and its label
  an `htmlFor`.
- **Required marked** with a trailing asterisk in `text-danger`.
- **Seeding during render**, never from an effect.
- **Secrets** — the PAT field never seeded, never a masked placeholder that looks like a value.
- **Long submits are not modal** — create-project closes on `201`/`202` and shows progress on
  the row.

### 6. Feedback, and the copy that carries it

`docs/design.md` → Feedback. Every mutation ends in exactly one of: a `sonner` toast on success,
inline `FieldError`s, or a form-level `Alert`. A mutation with a success toast and **no** error
path is a finding — the user is told when it worked and nothing when it did not.

Then audit the **copy** across all of them together, because this is where an app most visibly
looks assembled by different people:

- Sentence case, no trailing period, no title (`docs/design.md` → Feedback).
- One voice for one kind of event. The tree today mixes bare object phrases ("Changes applied",
  "Result recorded", "Password changed") with name-interpolated ones (`${project.name} deleted`,
  `Password reset for ${user.email}`). Decide which is the house style, report the minority, and
  **ask the user which they want** rather than picking for them.
- Destructive confirmations name the thing being destroyed and what is lost with it — deleting a
  project drops its vectors and there is no cheap recovery.
- Error copy says what to do next, not just that something failed.

### 7. The loading / empty / error triad

For every surface that reads data, confirm all three exist and are distinguishable:

| State | Expected |
| --- | --- |
| Loading | `Skeleton` matching the settled layout, never a spinner, never a layout that jumps |
| Empty | `EmptyState` with the primary action, never a bare "No results" |
| Error | `Forbidden` on `403`, `NotFound` on `404`, an `Alert` otherwise — never an empty shell |

A missing empty state is the one most often absent, because it is the one hardest to reach by
hand during development. Check the Ask conversation rail, the module grid, the mock-data records
table, the sources panel, and both change-set panels specifically.

### 8. The three streaming surfaces must behave identically

AskRepo streams in three places — `/ask/[conversationId]`, the checklist refinement chat, and
the mock-data refinement chat — and `.claude/rules/rag.md` says all three are served by the same
`Answerer`. **The UI must not make them look like three different features.** Compare, side by
side:

- The composer: same disabled-while-streaming behaviour, same submit affordance, same
  placeholder voice, same keyboard handling.
- The in-flight indicator: same treatment for "thinking" versus "typing".
- Citations and the sources panel: rendered the same way, appearing at the same moment
  (`citations` is emitted before the first token on every route).
- Grounding warnings: the same component and the same tone in all three. Note that
  `conversational` and `out_of_scope` turns carry **no** warnings by design — a surface showing
  "nothing matched" there is a 🔴 finding, not a cosmetic one.
- The change-set panel: `components/checklist/change-set-panel.tsx` and
  `components/mock-data/change-set-panel.tsx` are near-twins by construction. Diff them. Where
  they differ, decide whether the difference is meaningful or drift, and say which.
- Disconnect and reload: a partial answer is persisted server-side under the shield. Does the UI
  show the same thing on reload in all three?

### 9. Navigation and route gating

`.claude/rules/navigation.md`. No nav label or href hardcoded in a component; the sidebar a thin
renderer over `visibleNavTree(user)`; `BreadcrumbSeparator` a **sibling** of `BreadcrumbItem`,
never a child; placeholder rows while the profile is pending, never a filtered list; a group
with no reachable children hidden entirely.

And the one that is a security finding rather than a UI one: **every route body wrapped in its
gate.** Hiding a sidebar item is not gating a route — an operator can type the URL. Check
`/settings/users` in particular.

### 10. Layout geometry, spacing, typography

Navbar `h-16`, sidebar `w-64` / `top-16` / `h-[calc(100vh-4rem)]`, content `mt-16 p-4 md:p-8`,
`max-w-7xl` for lists and `max-w-3xl` for forms and prose. The `4rem` is load-bearing in three
places — flag any one of them changed alone.

Spacing from `1, 2, 3, 4, 6, 8, 12` only. Typography from the seven-row scale; **`font-bold`
never appears** (`font-semibold` is the heaviest weight); no font family set in a component;
`font-mono` on every file path, SHA, and identifier — check that citations, `source_path`, and
project repo URLs all use it, since a path rendered in the body face on one screen and mono on
another is exactly this audit's subject.

### 11. Icons and accessibility

`lucide-react` only; `size-4` inline with text, `size-5` standalone. **Every icon-only control
needs an `aria-label`** — the row-action menus, the theme toggle, the sidebar collapse, the
composer send button, the delete buttons. No icon carries meaning that no label or text also
carries (a red trash icon with no accessible name is unusable by a screen reader and ambiguous
in a screenshot).

Also: label/control association everywhere (the tests query by label, and so do screen readers),
a visible focus ring on every interactive element, and no colour-only status signal.

### 12. Documentation drift

`docs/design.md` is a claim about `frontend/app/globals.css` and about what is installed. Check:
the token table against the file; the component inventory against `frontend/components/ui/`;
the route list in `.claude/rules/navigation.md` §6 against `frontend/app/`; and `CLAUDE.md`'s
frontend section against the tree. Tag these 📄 and cite both sides.

## Asking the user

This audit will surface differences that are **decisions, not defects** — and you cannot tell
which from the code. Use `AskUserQuestion` rather than guessing, and ask in **one batch** once
the sweep is done, not one at a time as you go.

Legitimate questions look like:

- "The Ask and module-detail screens do not use `PageHeader`. Deliberate — because they are
  workspaces rather than lists — or drift?"
- "Toast copy is split between `Changes applied` and `${project.name} deleted`. Which is the
  house style?"
- "`/projects` polls while indexing; `/checklist` does not poll while generating. Intended?"
- "The checklist and mock-data change-set panels differ in `<specific way>`. Meaningful, or
  should they converge?"

Do **not** ask questions the documents already answer. `docs/design.md`, the rules, and the PRD
are the ground truth — read them before asking, and a question they settle is a question that
wastes the user's turn.

## Writing the report

Output is `docs/ui-audit-findings.md`, and **`.claude/rules/audit-findings.md` governs every
aspect of how it is written** — the five blocks in order (**Where** / **What this is** / **Why
this can happen** / **What it costs** / **What we should do**), plain language over jargon,
CONFIRMED vs SUSPECT honesty, the severity legend, the header block, "Top priorities" written
last and in the plainest language, stable numbering that is never reused, and how a resolved
finding is marked rather than deleted. **Read it before writing.**

Two adaptations for this report specifically:

- **Number sections `U1`–`U12`**, matching the categories above, so UI findings never collide
  with `/audit-flow`'s `§1`–`§9` in a commit message or a follow-up conversation.
- **Severity here is about the user, not the runtime.** Most UI inconsistency is 🟠 or 🟡. Reserve
  🔴 for something that shows a user the wrong thing or blocks them: a status badge that says
  `ready` when a module needs review, an ungated route, a mutation whose failure is silent, a
  grounding warning shown on a turn that never searched. "Two screens use different padding" is
  🟡 however much it grates.

Prefer updating an existing `docs/ui-audit-findings.md` over creating a second file, so the
report stays a single living record. If you create it for the first time, add its one-line entry
to `docs/README.md` in the same change — `.claude/rules/documentation.md` requires it.

## Rules for this command

- **Read-only.** Not one component, token, or stylesheet changes. If the sweep finds something
  that looks like a bug or a rule contradiction, **report it and stop there** —
  `.claude/rules/contradiction-halt.md` applies here with no exceptions. "What we should do"
  describes a fix; it never performs one.
- **Cite `file:line` for every finding.** A finding with no location is not a finding.
- **Exclude `frontend/components/ui/`** from the token, `dark:`, arbitrary-value and spacing
  checks, for the reason given above.
- **A difference the PRD or `docs/design.md` justifies is not a finding.** Record it under
  verified-correct with the justification, so the next sweep does not re-raise it.
- **Name what came back clean.** A category checked with nothing found gets a verified-correct
  note saying what was checked. "Clean" with no evidence is indistinguishable from "not
  audited".
- Dispatch parallel read-only `Explore` subagents — roughly one per flow, one per cross-cutting
  category — rather than reading serially in the main thread. Their terse notes are raw
  material; expand every one into the five-block format before it reaches the document.
