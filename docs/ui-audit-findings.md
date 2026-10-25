# UI audit findings

The standing record of **open** frontend findings, written by `/audit-ui`, plus each sweep's
verified-correct notes so the next sweep can tell "clean" from "not audited". A finding that has
been fixed moves, verbatim, to [`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).
A number cited below that is not in this file (§U7.1, §U11.3 and so on) is there.

**Sweeps:** 2026-09-13, 2026-09-19, 2026-09-27, 2026-10-04 and 2026-10-24. All five were
read-only. The first three were each followed by a separate, explicitly requested fix pass; the last
two have had none. The 2026-10-24 sweep re-checked every open finding: none was fixed outright, two
are partly fixed, and current locations are listed under [Sweep 2026-10-24](#sweep-2026-10-24).

**Re-verified 2026-10-17**, still at `df7594e` (no frontend change). The 2026-10-04 sweep had
recorded its findings only as table rows; their bodies are now written out under
[Sweep 2026-10-04](#sweep-2026-10-04). Every row was re-checked against the code. None was
refuted. Ten SUSPECTs were settled as CONFIRMED, and §U1.4 and §U7.16 were narrowed to what
reproduces. The one part still unverified is which two column rules §U12.8 meant.

**Ground truth:** [`design.md`](design.md), `.claude/rules/design-system.md`,
`.claude/rules/forms.md`, `.claude/rules/navigation.md`, `frontend/app/globals.css`, and
[`PRD.md`](PRD.md), which outranks them all.

**Severity:** 🔴 bug (shows a user something false, or blocks them) · 🟠 inconsistency / latent
risk · 🟡 hygiene · 📄 doc.

**Numbering:** `U1`–`U12`, matching the audit categories. These never collide with
[`audit-findings.md`](audit-findings.md)'s `§1`–`§9`, and are permanent identifiers — new
findings append, existing ones are never renumbered or reused, including once they move to the
log.

**Scope note on `components/ui/`.** That directory is shadcn-CLI-managed
(`design-system.md` §1). Its generated source legitimately contains `dark:` variants,
`rounded-[calc(…)]` arbitrary values, `bg-black/10` overlays and off-scale paddings, so it is
excluded from every token, `dark:`, arbitrary-value and spacing check below.

## Open findings

No finding is open. Every finding from every sweep has been fixed and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md), under the sweep that raised it; the
last open ones were fixed on 2026-10-25. A new sweep adds its rows to this table.

| # | Finding | Severity | Raised |
| --- | --- | --- | --- |

---

# Sweep 2026-09-13

Every finding this sweep raised has been resolved and is in the log. What stays here is what
it verified correct.

### §U1.1 Application code is clean — 🟢 verified correct

**Where:** `frontend/app/`, `frontend/components/` excluding `components/ui/`,
`frontend/hooks/`

Greps for raw hex, `rgb()`, `oklch()`, literal `rounded-[Npx]`, palette utilities
(`bg-zinc-*`, `text-slate-*`, `border-gray-*`), `text-white` / `bg-black`, `asChild`, and
`font-bold` return **zero hits outside `components/ui/`**. Every colour in application code
flows through a semantic token, and `frontend/app/globals.css` is the only file carrying a raw
hex, exactly as `design-system.md` §2 requires.

Every token defined in `:root` (globals.css:18-75) is redefined under `.dark` (:77-121) and
exposed through `@theme inline` (:123-177). No component references a token `globals.css` does
not define. `components/layout/theme-toggle.tsx:31-32` is the only `dark:` usage in application
code and it drives `display`, not colour — legal under `design-system.md` §3 and documented in
place.

### §U8.5 The two refinement chat panels are consistent with each other — 🟢 verified correct

**Where:** `components/checklist/chat-panel.tsx` and `components/mock-data/chat-panel.tsx`

A line-by-line diff shows the same `TurnState` shape, the same `reconciled` reconciliation, the
same per-animation-frame token batching, the same pre-flight/mid-stream error split, the same
`refetchOnMount: "always"` with the same explanatory comment, the same shared-chat `Alert`, and
the same composer disable ladder. The mock-data panel adds one state the checklist has no
equivalent for — `isGenerating`, with a comment at lines 170-174 explaining the server-side `409`
it mirrors.

The duplication is deliberate and documented at `mock-data/chat-panel.tsx:40-47`: "Kept as a
separate component rather than a parameterised shared one so this feature and the checklist's own
chat can diverge without a shared file changing under both." Recorded here so a future sweep does
not file it as copy-paste. Note that §U8.1 and §U8.2 are gaps in **both** panels, so the
consistency being preserved here is consistency in omission.

### §U9.1 Navigation is clean — 🟢 verified correct

**Where:** `lib/nav.ts`, `lib/settings-nav.ts`, `lib/nav-child.ts`,
`components/layout/app-sidebar.tsx`, `components/layout/app-breadcrumbs.tsx`,
`app/(app)/settings/users/users-screen.tsx:36-37`

Checked against all seven of `.claude/rules/navigation.md`'s rules:

- No nav label or href is hardcoded in a component; the sidebar is a thin renderer over
  `visibleNavTree(user)` (app-sidebar.tsx:85).
- `BreadcrumbSeparator` is emitted as a **sibling** of `BreadcrumbItem` inside a `Fragment`
  (app-breadcrumbs.tsx:34-45), with the hydration reason recorded in place.
- The permission flash is eliminated structurally rather than papered over: `app/(app)/layout.tsx`
  resolves the user server-side before first byte, so there is no pending state for the sidebar to
  render a filtered list during. The docstring at layout.tsx:8-13 explicitly warns against
  re-adding a placeholder.
- `/settings/users` wraps its body in its own gate (users-screen.tsx:36-37) with the comment
  "Hiding the nav item is not gating the route — an operator can type the URL", and renders
  `<Forbidden />` rather than redirecting.
- `NavGroup` holds its open state controlled and syncs on the transition during render rather than
  from an effect (app-sidebar.tsx:40-48), with the `defaultOpen` trap documented.

### §U10.1 Geometry and type scale hold — 🟢 verified correct

**Where:** `components/layout/app-navbar.tsx:13`, `components/layout/app-sidebar.tsx:88`,
`components/layout/app-shell.tsx:22`

The navbar is `fixed … h-16`, the sidebar is `top-16 h-[calc(100vh-4rem)]`, and main content is
`mt-16 p-4 md:p-8` — all three derivations of the load-bearing `4rem` agree, and both files carry
a comment saying so. Every app screen wraps in `max-w-7xl` and both form shells in `max-w-3xl`,
matching [`docs/design.md`](design.md) → Layout. `font-bold` appears nowhere. No component sets a
font family. `font-mono` is applied consistently to file paths, repo URLs, commit SHAs, citations
and the module `source_path`.

### §U11.1 Icon-only controls are labelled — 🟢 verified correct

**Where:** 27 `aria-label` usages across application code

Every icon-only control carries an accessible name: the row-action menus interpolate the subject
(`project-row-actions.tsx:59` — `Actions for ${project.name}`; `user-row-actions.tsx:34`), the
theme toggle (`theme-toggle.tsx:28`), the sidebar trigger (`app-navbar.tsx:14`), the account menu
(`account-menu.tsx:50`), the composer's inputs (`composer.tsx:39`), the copy-code button
(`answer.tsx:18`), the delete buttons (`conversation-rail.tsx:44`, `records-table.tsx:67`), and
both search inputs. `password-input.tsx:39-41` is the best of them: the label states what the
action *does* and `aria-pressed` carries the state separately, with a comment explaining the
distinction. The drawer's resize handle implements the full ARIA window-splitter pattern
(`refinement-drawer.tsx:216-231`). Every form control has an `id` and its label an `htmlFor`.

## Verified correct

Categories checked with nothing found, and what was checked:

- **§U1 Token discipline.** No raw hex, `rgb()`, `oklch()`, arbitrary radius, palette utility,
  `text-white`/`bg-black`, `asChild` or `font-bold` anywhere in application code. All 38 tokens
  defined in `:root` are redefined under `.dark` and exported through `@theme inline`. See §U1.1.
- **§U5 Form architecture.** No `zod` and no `react-hook-form` in `package.json` or any import.
  Every form uses `FormDialog`, `FormPage` or `ConfirmDialog` — no hand-rolled `<form>` with its
  own submit row outside `login-screen.tsx`, which is a full-page auth card no shell covers. The
  dialog-versus-page split matches `forms.md` §1's table exactly, including create-user as a
  dialog with four inputs. `edit-user-dialog.tsx:26-32` seeds during render keyed on the row id,
  never from an effect. `create-project-dialog.tsx:102-123` treats the PAT as write-only with
  helper text and no masked placeholder, per `forms.md` §9. `create-project-dialog.tsx:45-51`
  closes on `201` rather than holding the dialog on the clone job, per `forms.md` §10.
- **Backend rules are not restated client-side.** `password-field.tsx` reads the policy from
  `GET /auth/password-policy` rather than hardcoding "12 characters", and its docstring explains
  the two honesty constraints that follow — the checklist stays hidden until the policy loads, and
  a satisfied field reads "Looks good so far" because the server also screens a wordlist the
  browser never sees. `login-screen.tsx:38-44` limits itself to required-ness and an `@`.
- **The single error-banner rule holds.** `FormError` (`form-error.tsx:10-11`) returns null when
  the error carries field errors, so a banner never duplicates inline messages. No second banner
  exists at any call site. (Its *styling* is §U6.1; its logic is correct.)
- **§U9 Navigation.** All seven rules pass — see §U9.1.
- **§U10 Geometry.** The `4rem` navbar derivation is consistent across all three dependants; every
  screen uses the documented max-widths; the type scale holds. See §U10.1.
- **§U11 Accessibility.** Every icon-only control is labelled; every control has an `id`/`htmlFor`
  pair. See §U11.1.
- **`components/ui/` is genuinely CLI-managed.** Spot-checked for hand-editing: every file carries
  `data-slot` attributes and the generated `cva` structure. `hooks/use-mobile.ts:5` is the one
  deliberate divergence from generated output and says so in a comment.
- **Streaming security.** `components/ask/answer.tsx:36-48` uses no `rehype-raw` and no
  `dangerouslySetInnerHTML`, with a docstring explaining that rendering raw HTML would convert a
  prompt-injection attempt from something the model can *say* into something it can *do* —
  the architectural bound `docs/PRD.md` §9 depends on.
- **Conversation privacy in the UI.** There is no "all conversations" destination anywhere; the
  rail fetches only the caller's own and `conversation-rail.tsx:75-84` records why an affordance
  implying otherwise would be the first step toward someone adding the route.
- **Deliberate duplication, documented.** The two refinement chat panels (§U8.5) and the two
  status-tone mappings (§U4.1 item 2) are intentional and carry their reasoning in place. The
  indeterminate progress bar at `project-detail-screen.tsx:77-82` is likewise deliberate: the API
  reports a phase, never a percentage, and the comment explains why inventing one would be worse.

---

# Sweep 2026-09-19

**Scope:** every flow again, plus the two areas that did not exist on 2026-09-13 — the roles
screens and the whole audit-trail area, including the filter row and detail dialog that landed
hours before this sweep.

**Read-only; a fix pass followed it.** Every finding it raised is resolved and in the log. Six
were left open by that fix pass and fixed on 2026-09-27.

**No finding resolved on 2026-09-13 had regressed** when this sweep ran. §U7.1's fix held on all
five screens it was applied to, and §U8.1–§U8.4 held in all three streaming surfaces.

## Verified correct in this sweep

Recorded so the next sweep can tell "clean" from "not audited".

- **Every token-discipline grep came back empty** across `frontend/app`, `frontend/components` and
  `frontend/hooks` with `components/ui/` excluded: no raw hex or `rgb()`/`oklch()` outside
  `globals.css` and the documented `manifest.ts`; no arbitrary `rounded-[…]`; no palette utility
  (`zinc`/`slate`/`gray`/`neutral`/`stone`); no `bg-white` or `text-black`; no `text-white`; no
  `font-bold`; no `asChild`; and no `dark:` colour utility — the only `dark:` uses are the theme
  toggle's documented non-colour `dark:block`/`dark:hidden`.
- **Layout geometry is intact as a set.** Navbar `h-16`, sidebar `top-16` and
  `h-[calc(100vh-4rem)]`, content `mt-16 p-4 md:p-8`, `max-w-7xl` on the three list screens and
  `max-w-3xl` on detail and form screens. All three `4rem` dependencies still agree.
- **Navigation holds.** `lib/nav.ts` is the sole source of labels and hrefs; the sidebar is a thin
  renderer over `visibleNavTree(user)`; `BreadcrumbSeparator` is a sibling of `BreadcrumbItem`
  inside a `Fragment`; and there is no permission flash, because the layout resolves the user
  server-side before any render.
- **Route gating** is synchronous and commented on `/settings/users`, `/settings/roles`,
  `/settings/audit` and `/settings/audit/[eventId]` — the one exception is §U9.4.
- **The streaming surfaces are one feature, not three.** `components/ask/composer.tsx` is imported
  unchanged by all four call sites; `PHASE_LABELS` lives in `lib/ask/phase-labels.ts` and is shared;
  `components/ask/sources.tsx` self-hides on empty citations so no route needs special-casing; and
  the server-computed `groundingWarnings` is passed straight through everywhere with no client-side
  re-derivation — so a `conversational` or `out_of_scope` turn cannot acquire a false "nothing
  matched" warning. All three render persisted history through one `MessageList`, so a reload after
  a disconnect looks the same on every route.
- **`components/ui/` is CLI-generated throughout.** Every file carries `data-slot` markup or a
  `useRender` import except `sonner.tsx`, which wraps a third-party toaster rather than a Base UI
  primitive and correctly has neither.
- **The new audit work is otherwise sound.** The filter row's `ANY` sentinel never leaves its
  module; the four filter controls carry `aria-label`s and are direct grid siblings; the detail
  dialog guards its fetch through the hook's existing `enabled` check; and it reuses the extracted
  detail body rather than re-implementing it — the two findings against it (§U2.4, §U10.5) are
  about the wrapper and the doc, not the structure.
- **Forms hold.** No `zod` or `react-hook-form` anywhere; no `max-w-*` at a call site; the password
  policy is fetched from `GET /auth/password-policy` and never restated; the PAT field is never
  seeded and never masked; the permission picker is correctly a `FormPage` and submits every
  selected id rather than a diff; and edit forms seed during render.
- **Destructive confirmations name what is lost** — project deletion says re-creating means a full
  re-clone and re-embed, module deletion names the test cases, proposed changes and chat that go
  with it, and clearing results names the exact count and that it resets rather than deletes.
- **The `info` token is now in use**, at the audit screens' "As of now" block. §U1.2 reported it
  unused; that is resolved by adoption rather than removal.

---

# Sweep 2026-09-27

**Scope:** the surfaces that landed after 2026-09-19: the notification bell and `/notifications`,
`/profile` (account, password, sessions, activity, notification preferences), `/forgot-password`
and `/reset-password`, the `/settings` and `/settings/notifications` redirects, and the
live-events provider with the hooks it quiets down. Every earlier open finding was re-checked,
and the token, geometry and streaming-surface checks were re-run app-wide.

**Read-only.** Every finding it raised (§U4.6, §U6.8–§U6.11, §U10.9, §U10.10, §U11.4,
§U11.5, §U12.5) was fixed the same day and is in the log. What stays here is what it verified.

**Ground truth unchanged:** [`design.md`](design.md), `.claude/rules/design-system.md`,
`.claude/rules/forms.md`, `.claude/rules/navigation.md`, `.claude/rules/live-events.md` (rule 5,
polling stays the fallback), `frontend/app/globals.css`, and [`PRD.md`](PRD.md).

**It re-checked the six findings left open on 2026-09-19** (§U4.4, §U5.7, §U8.6, §U8.7,
§U9.4, §U10.8) and found them unchanged. All six were fixed in the same pass.

**Three decisions were put to the owner during this sweep, and the answers are recorded in the
findings they settled, now in the log.** `/profile`'s wider page is drift, not a new layout width (§U10.9). A
two-value success/failure outcome counts as a status domain and should map in one place (§U4.6).
An IP address counts as an identifier and takes `font-mono` (§U10.10).

## Verified correct in this sweep (2026-09-27)

- **Tokens hold app-wide**, with `components/ui/` excluded. There is no raw hex or `rgb()`/`oklch()`
  outside `globals.css` and `manifest.ts`, no `rounded-[`, no palette utility, no
  `bg-white`/`text-black`/`text-white`, no `font-bold`, no `asChild`, no `text-destructive`, and no
  `dark:` colour utility. The only off-scale spacing is §U10.8's `pl-9`. Every token in
  `globals.css` is in `design.md`'s table and the reverse. The only `:root` entries not redefined
  under `.dark` are `--destructive`/`--destructive-foreground` (an alias of `danger`) and
  `--radius`, and both are documented.
- **`components/ui/switch.tsx` is CLI-generated.** It imports `@base-ui/react/switch` and carries
  `data-slot="switch"`. The inventory lists all 30 installed components.
- **Geometry holds.** `app-navbar.tsx:14` `h-16`, `app-sidebar.tsx:88` `top-16
  h-[calc(100vh-4rem)]`, `app-shell.tsx:24` `mt-16 p-4 md:p-8`. All three `4rem` sites still agree.
- **The new screens adopt every shell.** `/notifications` and `/profile` use `PageHeader`,
  `ListToolbar`, `Card className="p-0"`, `PaginationFooter`, `EmptyState`, `ListError`,
  `TableSkeleton`, `StatusBadge` and `ConfirmDialog`. None hand-rolls list chrome.
  `/notifications` follows the list skeleton in full, and every new timestamp goes through
  `formatRelative`/`formatAbsolute`.
- **The loading/empty/error triad holds on every new surface.** `notifications-screen`,
  `preferences-screen`, and the account, activity and sessions sections each branch
  `isError → ListError`. No failed read renders as "nothing here", so §U7.1's bug has not
  recurred. What §U6.8 and §U6.9 found is the mutation half, not the read half.
- **Forms hold.** `ChangePasswordFields` is reused unchanged by the forced-change, profile and
  reset screens. The password policy comes from `GET /auth/password-policy` and no length is
  restated. There is no `zod`/`react-hook-form` and no `max-w-*` at a dialog call site.
- **Navigation holds.** `/settings` redirects to its first reachable admin child,
  `/settings/notifications` is a bare redirect to `/profile#notifications`, and `/notifications`
  and `/profile` are breadcrumb-only entries in `lib/nav.ts`, never in `visibleNavTree`.
  `navigation.md`'s route list and `CLAUDE.md`'s both match the `page.tsx` tree.
- **Live events never replace polling** (`live-events.md` rule 5). The bell and list poll every
  60 seconds when unconnected and every 5 minutes when connected. Job hooks in `use-projects.ts`,
  `use-checklist.ts` and `use-mock-data.ts` poll every 3 seconds unconnected and every 60 seconds
  connected. None stops.
- **The three streaming surfaces are unchanged.** One `Composer`, one `PHASE_LABELS`, and
  server `groundingWarnings` passed straight through with no client re-derivation. The two
  change-set panels differ only by what §U8.7 already names.
- **Icon-only controls are labelled.** The bell, the account menu trigger and the sidebar
  trigger all carry `aria-label`. The bell's `size-4` matches every other icon-only menu
  trigger in the app (only `theme-toggle.tsx` uses `size-5`). That split predates this sweep and
  is not filed.
- **Not filed, by the docs:** "Mark all read" has no confirmation. No rule asks for one, and it
  destroys no content: it changes a flag the user can still see on every row.

---

# Sweep 2026-10-04

**Scope:** the surfaces that landed after 2026-09-27, weighted toward Phase 2.5 and Phase 2.6. That
means the feedback control on answers and change sets (`components/output-feedback/`), the admin
`/settings/feedback` screen, the project Eval tab, the eval set screen
(`/projects/[id]/eval/[setId]`) with its run sheet and compare section, and the profile's Answer
style tab. Every streaming surface and both change-set panels were re-read.

**Read-only.** Nothing below has been fixed. All paths are under `frontend/` unless they start with
`docs/` or `.claude/`.

**How this section came to exist.** The 2026-10-04 sweep put its 40 findings into the "Open
findings" table and the "Top priorities" list, but never wrote their bodies. That breaks
`.claude/rules/audit-findings.md`, which requires every finding to be readable on its own. On
2026-10-17, still at `df7594e` with no frontend change, every row was re-verified against the code
and written out below. Numbers are unchanged. None was refuted. Ten SUSPECT tags were settled as
CONFIRMED. §U1.4 and §U7.16 were narrowed to what actually reproduces. One owner decision from
2026-10-04 survives in the Top priorities: eval sets should be deletable from the UI (§U6.14). A
second frontend decision mentioned in the backend report was never written down, and is not
reconstructed here.

**Evidence:** every finding below is CONFIRMED by reading the code on 2026-10-17. None was executed
in a browser.

## U1 Tokens and theme

Every finding this sweep raised here (§U1.4) was resolved on 2026-10-25 and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U3 The list skeleton

Every finding still open here (§U3.6–§U3.7) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U4 Status and semantic colour

Every finding still open here (§U4.7) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U5 Forms

Every finding still open here (§U5.10–§U5.11) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U6 Feedback and copy

Every finding this sweep raised here (§U6.12–§U6.14) was resolved on 2026-10-17 and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).

## U7 Loading, empty and error

Every finding still open here (§U7.15) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U8 The streaming surfaces

Every finding still open here (§U8.10–§U8.11) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U9 Navigation and route gating

Every finding still open here (§U9.5–§U9.7) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U10 Layout, spacing, typography

Every finding still open here (§U10.13–§U10.14) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U11 Icons and accessibility

Every finding this sweep raised here (§U11.6–§U11.8) was resolved on 2026-10-25 and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U12 Documentation drift

Every finding this sweep raised here (§U12.6–§U12.8) was resolved on 2026-10-25 and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## Verified correct in this sweep (2026-10-04, re-checked 2026-10-17)

- **The read half of the older screens still holds.** None of the 2026-09-13 to 2026-09-27
  resolutions has regressed. The new loading, empty and error gaps (§U7.7–§U7.16) are all on
  surfaces added in Phases 2.5 and 2.6.
- **The eval Path and pair Source columns use `font-mono`** (`eval-set-table.tsx:73`,
  `eval-pair-table.tsx:74`). §U10.13 covers only the four places that do not.
- **The eval set's own failure path is right.** `eval-set-screen.tsx:61-69` routes through
  `DetailError`. Only the project half (§U7.8) and the permission branch (§U9.5) are wrong.
- **The pair table's expand control is a real `<button aria-expanded>`** (`eval-pair-table.tsx:57-61`),
  which is the model §U11.7 asks the run table to follow.
- **The mock-data chat already refuses refinement during generation** (`mock-data/chat-panel.tsx:201-209`).
  §U7.13 asks the checklist chat to match it.
- **The answer-style save does not flash old values.** Its draft clears only after the refetch
  lands, which is why §U7.16 was narrowed to votes.

---

# Sweep 2026-10-24

**Scope:** every flow and every category, at `ac3a52c`, weighted toward what landed since
`df7594e`. That means Phase 2.7: every string moved into `messages/<locale>/` and seven languages
(#68), eval set languages and translation (#69), and a project's content language (#70). It also
covers the new `/checklist/export` screen (#67) and eval notifications (#66).

**Read-only.** Nothing below has been fixed. All paths are under `frontend/` unless they start with
`docs/`, `backend/` or `.claude/`.

**Evidence:** every finding was traced in the code. Nothing was run in a browser, so anything that
depends on rendering (truncation, wrapping) says SUSPECT.

**Four decisions were put to the owner during this sweep.**
1. Copy of two or more sentences (most of `errors.json`, "X. Try again.") keeps its full stops.
   Only a single-sentence toast or alert drops its trailing period.
2. A `size-4` icon inside an icon-only button is intended, so design.md is what needs to change.
3. The profile Language section and the project Content language section are a legitimate fourth
   form surface, an inline-save settings section. forms.md should say so.
4. The notification bell's popover may use a plain sentence for its empty case instead of
   `EmptyState`.

§U12.13 and §U12.14 record the two documents those decisions leave out of date.

## Open findings re-checked

All twenty-four findings open before this sweep are **still open**, and none was refuted. Two are
now **partly fixed** and stay open for what remains:

- **§U7.15:** the run table now pads its error (`components/eval/eval-run-table.tsx:~43-46`). The set
  table still returns a bare `ListError` (`components/eval/eval-set-table.tsx:~48-50`), and its empty
  state still has no action.
- **§U11.6:** editors now get a labelled `Switch` for exclusion (`components/eval/eval-pair-table.tsx:108`).
  Read-only viewers still see a greyed row only. The pressed thumbs are still colour-only for sighted
  users (`components/output-feedback/feedback-control.tsx:124-125`, `:138-141`).

These have moved:

| # | Now at |
| --- | --- |
| §U3.5 | `app/(app)/settings/feedback/feedback-screen.tsx:~83-89` |
| §U3.7 | `hooks/use-eval.ts:32`, `:65` |
| §U4.7 | `components/checklist/item-grid.tsx:212-218`, `components/checklist/change-set-panel.tsx:187-193` |
| §U5.9 | `components/eval/generate-eval-set-dialog.tsx:72`, `:138`, `:142`, `:159`, `:163` |
| §U5.10 | `components/eval/generate-eval-set-dialog.tsx:24` |
| §U7.16 | `components/output-feedback/feedback-control.tsx:~70-96` |
| §U8.10 | `components/mock-data/change-set-panel.tsx:207` |
| §U8.11 | `components/ask/message-list.tsx:72-78` uses `messages.interrupted`. The live note uses `interruptedNote` (`messages/en/ask.json:43` vs `:47`). The old `interrupted-note.ts` path no longer exists |
| §U8.14 | `app/(app)/checklist/[moduleId]/module-screen.tsx:65`, `:69` |
| §U9.5 | `components/eval/eval-set-screen.tsx:100` |
| §U9.7 | Gates at `users-screen.tsx:39`, `audit-screen.tsx:50`, `feedback-screen.tsx:53`, `roles-screen.tsx:37`, `role-matrix-screen.tsx:54` |
| §U10.13 | `components/eval/eval-run-table.tsx:122`, `eval-run-sheet.tsx:74`, `eval-compare.tsx:75`, `eval-set-screen.tsx:123` (two of the original sites are now mono) |
| §U10.14 | `password-field.tsx:100`, `role-badge.tsx:14`, `audit-change-list.tsx:91`, `audit-event-detail.tsx:28`, `eval-pair-table.tsx:86`, `:88`, `:137`, `answer.tsx:62`, `notification-bell.tsx:37` |
| §U11.7 | `components/eval/eval-run-table.tsx:96-104` |
| §U11.8 | `eval-set-screen.tsx:301`, `:352`; `feedback-filters.tsx:50`, `:80`, `:110`, `:141`, `:156`; `audit-filters.tsx:96`, `:127`, `:153`, `:168` |
| §U12.6 | `/checklist/export` is now in `.claude/rules/navigation.md` §6. Still missing: `/projects/[id]/eval/[setId]`, `/settings/feedback`, `/notifications`, `/profile`, `/settings/notifications`. Also still stale: the "Phase 1" text in §4 and in `lib/nav-child.ts:14` |
| §U12.7 | The README now covers i18n, eval and export. Still stale: the `(auth)/` line omits `forgot-password`/`reset-password`, the layout omits `/settings/feedback`, the `components/` listing omits `audit/`, `change-sets/`, `live/`, `output-feedback/`, and the `lib/` listing omits `checklist/`, `live/`, `mock-data/` |
| §U12.8 | Unchanged. The column candidates are now `components/output-feedback/feedback-table.tsx:76`, `:79` |

## U1 Tokens and theme

Every finding still open here (§U1.5) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U3 The list skeleton

Every finding still open here (§U3.8–§U3.9) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U4 Status and semantic colour

Every finding still open here (§U4.8) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U5 Forms

Every finding still open here (§U5.14) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U6 Feedback and copy

Every finding still open here (§U6.17–§U6.19) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U7 Loading, empty and error

Every finding still open here (§U7.19) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U8 The streaming surfaces

Every finding still open here (§U8.17–§U8.18) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U10 Layout, spacing, typography

Every finding still open here (§U10.15–§U10.18) was resolved on 2026-10-25; all of them are in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U11 Icons and accessibility

Every finding this sweep raised here (§U11.9–§U11.10) was resolved on 2026-10-25 and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## U12 Documentation drift

Every finding this sweep raised here (§U12.9–§U12.14) was resolved on 2026-10-25 and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).


## Verified correct in this sweep (2026-10-24)

- **Tokens.** Searching app code (not `components/ui/`) found no raw hex, rgb or oklch except
  `app/manifest.ts` (§U1.5). It also found no `rounded-[…]`, no palette utility, and no `dark:` colour
  utility (`theme-toggle.tsx`'s `dark:block`/`dark:hidden` is visibility). Every solid `bg-<role>` is
  paired with its foreground. Every colour utility used is defined in `globals.css`, and every
  `:root` token is redefined under `.dark` except the deliberate aliases. `docs/design.md`'s token
  table matches `globals.css` in both themes.
- **Typography and geometry.** No `font-bold`, no font family set in a component, and no 4rem
  changed alone. The navbar is `h-16`, content is `mt-16 p-4 md:p-8`, and the sidebar and rail use
  `top-16 h-[calc(100vh-4rem)]`. Lists are `max-w-7xl`. Forms, including the new export
  `FormPage`, are `max-w-3xl`. Repository URLs and eval paths are `font-mono`.
- **Icons and names.** `lucide-react` only. All 21 icon-only buttons have an `aria-label`, and every
  one comes from the message catalogue. There is no literal `aria-label`, `title` or `placeholder`,
  and no `eslint-disable` sits around a literal string. `<html lang>` follows the active locale
  (`app/layout.tsx:33`). Every `FieldLabel htmlFor` has its `id`, apart from §U5.9 and §U5.12.
- **Dates follow the language.** `formatRelative` takes the locale, and `useFormatRelative` binds it.
  Every table timestamp has an absolute `title`, apart from §U3.8, and nothing formats a date inline
  except §U3.9's deliberate day-only column.
- **Shared shells.** These screens use `PageHeader`: dashboard, projects, project detail, checklist,
  module, both Ask screens, users, roles, audit list and detail, feedback, notifications, profile and
  eval set. The export screen and the role matrix use `FormPage`'s own card title, and the auth
  pages use `FormPage` or a card. Both are legitimate. `ConfirmDialog` guards every destructive
  action. `user-role-badge.tsx` building its own `info` badge is the role-only exception that
  `lib/status.ts` documents. The login card's raw `<form>` is the exception already accepted. The
  bell popover's plain empty sentence is acceptable, per the owner's 2026-10-24 decision.
- **Status mapping.** No word means two things. `generating`, `running` and `pending` are warning;
  `ready` and `done` are success; `failed` is danger, in one record per domain in `lib/status.ts`.
  The module mapping moved into `lib/status.ts`, ending the lib-versus-component split. Its only
  drift is §U4.7 and §U4.8.
- **Forms.** No `zod` and no `react-hook-form`. No `max-w-*` at a `FormDialog` call site. No form
  seeds from an effect. The personal access token is never seeded, and create-project closes on
  `201`. Required asterisks are `text-danger`. The password rules come from
  `GET /auth/password-policy`. The language list is held to the backend's by a test.
- **Toast voice.** All 40 success toasts are bare object phrases ("Module created", "Changes
  applied"), and none interpolates a name, so the §U6.7 decision holds. None of §U6.5–§U6.14 has
  regressed. Every other mutation has an error path besides §U6.15 and §U6.16.
- **Translations.** `lib/i18n/messages.test.ts` holds every locale to English's key set, placeholders
  and tags, and its namespace imports. A recount by hand found no missing key, extra key or
  placeholder mismatch in any of the six translations. Every one of the backend's 56 error codes has
  an entry.
  - Observation, not filed: `ACTIONABLE_MESSAGE_CODES` (`lib/i18n/error-text.ts:5-20`) deliberately
    shows the backend's English message for ten codes whose text names what to fix, such as the
    failing password rule. A Japanese user sees English for those until the backend sends a
    translatable reason. The comment states this.
- **Streaming parity.** The three surfaces share one composer, one SSE parser (`lib/ask/sse.ts`), one
  `GroundingNotice` and one `InterruptedNote`, and set citations on the same event before the first
  token. The UI never invents a "nothing matched" warning: it renders only what `done` carries, so
  conversational and out-of-scope turns show none. The two change-set panels differ meaningfully in
  row shape, permission and query keys. Their drift is only §U8.10, and mock-data's raw field keys,
  which are user-defined.
- **Navigation and gating.** Every `/settings/*` body is gated on `isAdmin` and returns `Forbidden`.
  `/settings` redirects to its first reachable child. `/checklist/export` is correctly not
  admin-gated, and filters projects by permission. The nav source holds every label key and href.
  The sidebar is a thin renderer over `visibleNavTree`. `BreadcrumbSeparator` is a sibling, and the
  export crumb comes from `FIXED_CRUMBS`. `proxy.ts`'s public pages are still exactly `/login`,
  `/forgot-password` and `/reset-password`.
- **Docs that hold.** All 33 `components/ui/` files are in `docs/design.md`'s inventory. All 23
  `page.tsx` routes are in `CLAUDE.md`, the `/settings` index being the stated non-screen. The
  `CLAUDE.md` backend-for-frontend bullets match `app/api/auth/` route for route, including
  `locale`. Only `components/ui/sonner.tsx` lacks `data-slot` and `useRender`, and it is the
  standard generated wrapper.

---

## See also

- [`audit-finding-solved-logs.md`](audit-finding-solved-logs.md) — the findings that have been fixed, verbatim
- [`audit-findings.md`](audit-findings.md) — the backend/architecture sweep (`§1`–`§9`)
- [`design.md`](design.md) — the design reference these findings are measured against
- [`../.claude/rules/design-system.md`](../.claude/rules/design-system.md),
  [`../.claude/rules/forms.md`](../.claude/rules/forms.md),
  [`../.claude/rules/navigation.md`](../.claude/rules/navigation.md) — the enforceable rules
- [`../.claude/commands/audit-ui.md`](../.claude/commands/audit-ui.md) — how this sweep is run
- [`../.claude/rules/audit-findings.md`](../.claude/rules/audit-findings.md) — how a finding is written
