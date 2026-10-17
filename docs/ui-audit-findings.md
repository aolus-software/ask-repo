# UI audit findings

The standing record of **open** frontend findings, written by `/audit-ui`, plus each sweep's
verified-correct notes so the next sweep can tell "clean" from "not audited". A finding that has
been fixed moves, verbatim, to [`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).
A number cited below that is not in this file (§U7.1, §U11.3 and so on) is there.

**Sweeps:** 2026-09-13, 2026-09-19, 2026-09-27 and 2026-10-04. All four were read-only. The first
three were each followed by a separate, explicitly requested fix pass; the fourth has had none.

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

Every finding from the first three sweeps has been fixed and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md). Everything below was raised on
2026-10-04 and is open.

| # | Finding | Severity | Raised |
| --- | --- | --- | --- |
| §U6.12 | Excluding an eval pair fails silently | 🔴 | 2026-10-04 |
| §U7.7 | An eval set's runs read "No runs yet" while loading, and forever if the request fails | 🔴 | 2026-10-04 |
| §U7.8 | The eval set screen reports any project-load failure as "not found" | 🔴 | 2026-10-04 |
| §U6.13 | Starting an eval run discards the server's error and has no success toast | 🟠 | 2026-10-04 |
| §U6.14 | Eval sets cannot be deleted from the UI | 🟠 | 2026-10-04 |
| §U7.9 | The eval run sheet has no error state and can say "Loading the run…" forever | 🟠 | 2026-10-04 |
| §U7.10 | A generating or failed eval set shows empty tables and an invitation the page refuses | 🟠 | 2026-10-04 |
| §U7.11 | The eval compare section is silent while loading or on error | 🟠 | 2026-10-04 |
| §U7.12 | The Answer style tab shows "Default" for every dial while loading | 🟠 | 2026-10-04 |
| §U7.13 | The test plan and mock data tabs invite generation while generation is running | 🟠 | 2026-10-04 |
| §U7.14 | A failed change-set request hides a pending change set the tooltip points to | 🟠 | 2026-10-04 |
| §U8.9 | Mock-data change-set rows do not say which record they change | 🟠 | 2026-10-04 |
| §U9.6 | Breadcrumbs show raw ids instead of names | 🟠 | 2026-10-04 |
| §U10.11 | Lists, headings and tables in answers render as plain paragraphs | 🟠 | 2026-10-04 |
| §U10.12 | The feedback summary hand-rolls a third stat tile | 🟠 | 2026-10-04 |
| §U1.4 | White text on three status colours, and three status text colours, fall below contrast guidance | 🟡 | 2026-10-04 |
| §U3.5 | `/settings/feedback` says "No feedback yet" when filters exclude everything | 🟡 | 2026-10-04 |
| §U3.6 | `/settings/feedback` applies URL-only filters the screen cannot show or clear | 🟡 | 2026-10-04 |
| §U3.7 | Eval tables have no pagination and stop at 100 rows | 🟡 | 2026-10-04 |
| §U4.7 | The "Negative" test-case badge is coloured at two call sites | 🟡 | 2026-10-04 |
| §U5.9 | The generate-eval-set dialog: two unassociated labels and a silent blank name | 🟡 | 2026-10-04 |
| §U5.10 | The eval sizes 10/25/50 restate a backend rule without saying so | 🟡 | 2026-10-04 |
| §U5.11 | The thumbs-down popover keeps stale reasons and sits outside the form contract | 🟡 | 2026-10-04 |
| §U7.15 | The eval sets empty state has no action, and `ListError` sits flush in two cards | 🟡 | 2026-10-04 |
| §U7.16 | A thumbs vote briefly reverts after a remount | 🟡 | 2026-10-04 |
| §U8.10 | A stray separator in the mock-data change-set card | 🟡 | 2026-10-04 |
| §U8.11 | A stored interrupted answer is worded differently from the live one | 🟡 | 2026-10-04 |
| §U8.12 | The sources panel moves from above the answer to below it on reconcile | 🟡 | 2026-10-04 |
| §U8.13 | "Try again" after a timeout exists on Ask only | 🟡 | 2026-10-04 |
| §U8.14 | The chat composers say "no permission" while the project is still loading | 🟡 | 2026-10-04 |
| §U9.5 | The eval set route answers a missing permission with `NotFound`, not `Forbidden` | 🟡 | 2026-10-04 |
| §U9.7 | Admin screens request data before their admin gate | 🟡 | 2026-10-04 |
| §U10.13 | Identifiers on the eval screens are in the body face | 🟡 | 2026-10-04 |
| §U10.14 | Off-scale spacing and a `text-[10px]` badge | 🟡 | 2026-10-04 |
| §U11.6 | Excluded pairs and pressed thumbs are signalled by colour alone | 🟡 | 2026-10-04 |
| §U11.7 | Eval run rows are clickable without a visible or accessible control | 🟡 | 2026-10-04 |
| §U11.8 | The compare selects and the date filters lose their visible labels | 🟡 | 2026-10-04 |
| §U12.6 | `navigation.md` §4 and §6 are stale | 📄 | 2026-10-04 |
| §U12.7 | `frontend/README.md`'s layout is stale | 📄 | 2026-10-04 |
| §U12.8 | `design.md` lacks the feedback control, the drawer width, and two column rules (column rules SUSPECT) | 📄 | 2026-10-04 |

## Top priorities (2026-10-04)

1. **The eval set screen tells people false things when a request fails** — that a set has no runs
   (§U7.7), that the whole set may have been deleted (§U7.8), or that a run is still loading
   (§U7.9). Each needs its loading and error states wired the way the rest of the app already does.
2. **Excluding an eval pair can fail with no message** (§U6.12): the switch snaps back and nobody is
   told why. Add an error toast.
3. **Answers lose their formatting** (§U10.11): bullet lists, numbered steps, headings and tables
   in answers render as run-on paragraphs — more visible now that the Answer style tab offers
   "bullets".
4. **Some screens show placeholder values as if they were real**: "Default" on every answer-style
   dial while loading (§U7.12), and "generate" invitations while generation is running (§U7.10,
   §U7.13).
5. **Reviewers cannot tell which record a mock-data change touches** (§U8.9), and breadcrumbs show
   ids instead of names (§U9.6).
6. **Eval sets cannot be deleted from the UI** (§U6.14) — the API supports it and the owner wants it.
7. Then the hygiene items and the documentation (§U12.6–§U12.8).

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

### §U1.4 White text on three status colours, and three status text colours, fall below contrast guidance — 🟡 hygiene

**Where:** `app/globals.css:36-43` (light-mode `--success`, `--danger`, `--info` and their
`-foreground`); `components/feedback/status-badge.tsx:11`, `:13`, `:15`;
`components/users/user-role-badge.tsx:11`; `text-warning`/`text-success`/`text-danger` at
`components/eval/eval-run-sheet.tsx:68`, `components/checklist/item-grid.tsx:204`,
`components/checklist/change-set-panel.tsx:186`, `components/form/password-field.tsx:88`, `:111`

**What this is.** Status badges (Ready, Failed, Indexing…) are small coloured pills, and a few
places colour a line of text to signal a state. Web Content Accessibility Guidelines (WCAG)
contrast asks for at least 4.5:1 between small text and its background, so that people with
reduced vision can read it.

**Why this can happen.** In light mode, the status colours are bright mid-tones with white text on
top. Measured ratios: success badge 2.22, info badge 2.37, danger badge 3.81. The warning badge
uses dark text and passes, at 8.31. Used as text colour on a card, warning is 2.15, success 2.22
and danger 3.81, and each is lower again on the page background. All of these are `text-xs` or
`text-sm`, so 4.5:1 applies.

**What it costs.** Status pills, the single most-read signal on the list screens, are hard to read
in light mode for anyone with reduced contrast sensitivity, and in bright light for everyone.
`docs/design.md:41` claims AA (the 4.5:1 level) only for `muted-foreground`, so nothing promised
otherwise. But nothing warns against it either.

**What we should do.** Darken the light-mode `--success`, `--info` and `--danger` until white
reaches 4.5:1, or switch their `-foreground` to the dark ink the warning badge already uses. Add
separate darker `*-text` tokens for coloured text. Record the ratios in `docs/design.md`. Roughly
half a day, most of it checking the results look right.

## U3 The list skeleton

### §U3.5 `/settings/feedback` says "No feedback yet" when filters exclude everything — 🟡 hygiene

**Where:** `app/(app)/settings/feedback/feedback-screen.tsx:89-94`

**What this is.** The admin feedback screen lists votes and can be filtered by feature, vote,
reason and date.

**Why this can happen.** Whenever the result is empty, the screen renders the same "No feedback yet"
empty state, whether or not a filter is active.

**What it costs.** An administrator who filters to a narrow window is told nobody has ever voted,
which is false.

**What we should do.** Branch on whether any filter is set, the way the audit screen does: "No
feedback matches these filters", with a clear-filters action. Half an hour.

### §U3.6 `/settings/feedback` applies URL-only filters the screen cannot show or clear — 🟡 hygiene

**Where:** `app/(app)/settings/feedback/feedback-screen.tsx:23-31`, `:33-38` (`changedKey`);
`hooks/use-feedback.ts:32`, `:36`; `components/output-feedback/feedback-filters.tsx:34-150`

**What this is.** Filters on this screen live in the URL so a filtered view can be shared.

**Why this can happen.** The screen reads `projectId` and `promptVersion` from the URL and sends
them to the API, but the filter row has controls only for feature, vote, reason, from and to. A
link that carries `?projectId=…` filters the list with nothing on screen saying so, and no control
can remove it.

**What it costs.** An administrator opens a shared link, sees a fraction of the feedback, and has
no visible reason or way back except editing the URL by hand.

**What we should do.** Either render a control (or at least a removable chip) for each filter the
URL can carry, or stop reading the two the screen cannot show. One to two hours.

### §U3.7 Eval tables have no pagination and stop at 100 rows — 🟡 hygiene

**Where:** `hooks/use-eval.ts:29-32` (sets), `:62-65` (runs); `backend/app/schemas/pagination.py:13`
(`MAX_PAGE_SIZE = 100`)

**What this is.** Every other list in the app has a pagination footer (`docs/design.md` → Lists).

**Why this can happen.** The eval set list and the run list each fetch one page with `?limit=100`,
which is the backend's maximum. No eval component reads `totalCount` or renders a pager. Pair
lists are not affected, since a set has at most 50 pairs.

**What it costs.** The 101st eval set on a project, or the 101st run of a set, silently never
appears. That is unlikely soon, but invisible when it happens.

**What we should do.** Use `PaginationFooter` on both tables, as the project and checklist lists do.
One to two hours.

## U4 Status and semantic colour

### §U4.7 The "Negative" test-case badge is coloured at two call sites — 🟡 hygiene

**Where:** `components/checklist/item-grid.tsx:201-207`, `components/checklist/change-set-panel.tsx:183-189`

**What this is.** `.claude/rules/design-system.md` §5 says a status maps to its colour in one
module and renders through `StatusBadge`. A checklist test case can be marked "Negative" (a test
that expects a failure).

**Why this can happen.** Both places build the badge by hand with the same `text-warning
border-warning/60` classes, instead of using one shared mapping.

**What it costs.** Nothing yet, as the two copies match. The next change to one will not reach the
other. Both also inherit §U1.4's low contrast.

**What we should do.** Give the test-case kind a tone in one module and render both through
`StatusBadge`. Half an hour.

## U5 Forms

### §U5.9 The generate-eval-set dialog has two unassociated labels and a silent blank name — 🟡 hygiene

**Where:** `components/eval/generate-eval-set-dialog.tsx:139`, `:146`, `:160`, `:165`, `:72`

**What this is.** `.claude/rules/forms.md` requires every control to have an `id` and its label an
`htmlFor`, so that clicking the label focuses the control and screen readers announce it. Required
fields show an error when empty.

**Why this can happen.** The "Questions" and "Mix" labels have no `htmlFor`, and their selects have
no `id`. Submitting with a blank name hits `if (!values.name.trim()) return;`, which simply does
nothing: no error, no required marker.

**What it costs.** A user presses Generate and nothing happens, with no explanation. Screen-reader
users hear two unlabelled dropdowns.

**What we should do.** Add `id`/`htmlFor` to both selects, mark Name required, and show a field
error on a blank name. Half an hour.

### §U5.10 The eval sizes 10/25/50 restate a backend rule without saying so — 🟡 hygiene

**Where:** `components/eval/generate-eval-set-dialog.tsx:24`, `lib/api/types.ts:673`;
`backend/app/schemas/eval.py:24`; `docs/PRD.md` §2.1 Phase 2.6

**What this is.** `forms.md` says the client must not restate a backend rule. The backend accepts
only 10, 25 or 50 questions.

**Why this can happen.** The dialog hard-codes `[10, 25, 50]` and the type mirrors it, with no
comment linking either to the backend.

**What it costs.** Nothing while the numbers agree. If the backend's options change, the dialog
offers a choice that fails with a `422`.

**What we should do.** At minimum, comment both sites as mirroring `schemas/eval.py`. Better, serve
the options from the API. Minutes for the comment.

### §U5.11 The thumbs-down popover keeps stale reasons and sits outside the form contract — 🟡 hygiene

**Where:** `components/output-feedback/feedback-control.tsx:61-64`, `:84-88`, `:98`, `:78-81`, `:154-183`

**What this is.** Thumbs-down opens a small popover where a user picks reasons and may add a note.

**Why this can happen.** The reasons and note are seeded once, and later re-seeding only updates
the vote. So closing without sending, removing a vote, or a failed save all leave the old ticks and
text in place the next time it opens. The popover also uses a raw `Label`/`Textarea` rather than
`Field`/`FieldLabel`/`FieldError`. Its textarea has an `aria-label` but no `id`. A failed save only
toasts. The character limit and counter restate a backend limit.

**What it costs.** A user who changed their mind sees reasons they did not mean to send pre-ticked,
and can send them by accident.

**What we should do.** Reset reasons and note whenever the popover opens on a fresh vote, and
compose it from the form shells. One to two hours.

## U6 Feedback and copy

### §U6.12 Excluding an eval pair fails silently — 🔴 bug

**Where:** `components/eval/eval-pair-table.tsx:81-84`; `hooks/use-eval.ts:114-124` (`useSetPairExcluded`)

**What this is.** Each generated question in an eval set has a switch that excludes it from future
runs. `docs/design.md` → Feedback requires every mutation to end in a toast, a field error or an
alert.

**Why this can happen.** The switch calls the mutation with no `onError`, and the hook has none
either. The switch is controlled by the server's value, so when the request fails it snaps back.

**What it costs.** A user excludes a bad question, the switch flicks back, and nothing says why. If
they don't notice, the next run includes a question they removed, and its score is not the one
they thought they asked for.

**What we should do.** Add an `onError` toast that carries the server's message. Minutes.

### §U6.13 Starting an eval run discards the server's error and has no success toast — 🟠 inconsistency

**Where:** `components/eval/eval-set-screen.tsx:107-109`; `hooks/use-eval.ts:101-112`

**What this is.** Starting a run is a long job, and the backend refuses it with a specific message
in some cases, for example `409` while a reindex is running.

**Why this can happen.** The failure path shows a fixed "The run could not be started.", which
throws away the server's explanation, and the success path shows nothing.

**What it costs.** A user refused because of a reindex is not told that waiting will fix it. A user
who succeeds gets no confirmation until the row appears.

**What we should do.** Toast the server's message on error (the shared error helper already
extracts it) and add a success toast such as "Run started". Half an hour.

### §U6.14 Eval sets cannot be deleted from the UI — 🟠 inconsistency

**Where:** `hooks/use-eval.ts:126` (`useDeleteEvalSet`, unused); `components/eval/eval-set-table.tsx:63-89`;
`components/eval/eval-set-screen.tsx:98-117`; `backend/app/api/routes/eval.py` (the delete route)

**What this is.** The API can delete an eval set, and a hook for it already exists.

**Why this can happen.** No screen calls the hook. The set table has no actions column, and the set
screen's header holds only Run.

**What it costs.** Old or broken eval sets pile up on the Eval tab with no way to remove them except
the API directly. Owner decision (2026-10-04): it should be deletable.

**What we should do.** Add a row action and a header action that open a `ConfirmDialog`. The dialog
should name the set and say that its runs and results go with it, and the action should be gated on
the eval permission the backend checks. Two hours.

## U7 Loading, empty and error

### §U7.7 An eval set's runs read "No runs yet" while loading, and forever if the request fails — 🔴 bug

**Where:** `components/eval/eval-set-screen.tsx:75`, `:140`; `components/eval/eval-run-table.tsx:26-33`

**What this is.** Every surface that reads data must show a distinct loading, empty and error state
(`docs/design.md`).

**Why this can happen.** The screen takes `runsQuery.data?.items ?? []` and ignores loading and
error, so the table always receives a list. An empty one renders the "No runs yet" empty state.

**What it costs.** A user is told a set has never been run while the runs are loading, and
indefinitely when the request fails. That is a false statement about their data, so it is red.

**What we should do.** Render `TableSkeleton` while loading and `ListError` on error, as every
other list does. Half an hour.

### §U7.8 The eval set screen reports any project-load failure as "not found" — 🔴 bug

**Where:** `components/eval/eval-set-screen.tsx:70-72`; compare `:61-69` and
`components/feedback/detail-error.tsx:25-31`

**What this is.** The set screen loads the project and the set. The set's failure path is correct:
`DetailError` turns `404` into Not found, `403` into Forbidden, and anything else into a retry
alert.

**Why this can happen.** The project query's error is never read. If the project fails to load,
for any reason including a network blip, the set query stays disabled, and the screen falls through
to `if (!set || !project) return <NotFound />`.

**What it costs.** A transient error tells the user the eval set, and with it their work, does not
exist.

**What we should do.** Route the project query's error through `DetailError` before the set
checks. Half an hour.

### §U7.9 The eval run sheet has no error state and can say "Loading the run…" forever — 🟠 inconsistency

**Where:** `components/eval/eval-run-sheet.tsx:29-30`, `:41-43`, `:46`

**What this is.** Clicking a run opens a side sheet with its answers and verdicts.

**Why this can happen.** The sheet reads `query.data` and never `query.error`. Its title reads
"Loading the run…" whenever there is no data, so a failed fetch leaves that text up for good. The
skeleton below disappears once the request ends.

**What it costs.** A failed run load looks like a slow one, indefinitely.

**What we should do.** Show `DetailError` (or an alert with retry) when the query fails. Half an
hour.

### §U7.10 A generating or failed eval set shows empty tables and an invitation the page refuses — 🟠 inconsistency

**Where:** `components/eval/eval-set-screen.tsx:105`, `:126-128`, `:133`, `:140`;
`components/eval/eval-pair-table.tsx:45-109`; `components/eval/eval-run-table.tsx:26-33`

**What this is.** An eval set is `generating`, `ready` or `failed`, and only a ready set can be
run.

**Why this can happen.** The pair table has no empty state, so while generating it is a bare
header row. The runs card shows "Run the set to ask each question…" while the Run button is
disabled for any status other than `ready`.

**What it costs.** The page invites an action it refuses, and shows an empty table where it should
say questions are being generated.

**What we should do.** Branch both cards on the set's status: "Generating questions…" while
generating, nothing to invite while failed (the alert already explains). One hour.

### §U7.11 The eval compare section is silent while loading or on error — 🟠 inconsistency

**Where:** `components/eval/eval-set-screen.tsx:181-185`

**What this is.** Choosing two runs shows a side-by-side comparison of their scores.

**Why this can happen.** The compare card renders only when both runs' data has arrived, and
`null` otherwise. Nothing checks loading or error.

**What it costs.** After choosing two runs the user sees nothing at all, with no way to tell "still
loading" from "failed".

**What we should do.** A skeleton while either run loads, and an alert if either fails. Half an
hour.

### §U7.12 The Answer style tab shows "Default" for every dial while loading — 🟠 inconsistency

**Where:** `components/profile/answer-style-section.tsx:57-60`, `:77-80`, `:106`

**What this is.** The profile's Answer style tab has radio groups for how answers are shaped
(length, format and so on), each with a "Default" option.

**Why this can happen.** Until the saved style arrives, the section falls back to "all unset", so
every group shows Default as selected. The controls are disabled until load, which prevents
overwriting, but nothing says the values are not real yet.

**What it costs.** A user with saved preferences briefly sees them all reset to Default. On a slow
connection that is long enough to believe it.

**What we should do.** Show `Skeleton` rows until loaded, as the other profile sections do.
Half an hour.

### §U7.13 The test plan and mock data tabs invite generation while generation is running — 🟠 inconsistency

**Where:** `components/checklist/item-grid.tsx:146-153`; `components/mock-data/records-table.tsx:91-98`;
`app/(app)/checklist/[moduleId]/module-screen.tsx:240-244`, `:295`;
`components/checklist/chat-panel.tsx:243-250`; compare `components/mock-data/chat-panel.tsx:201-209`

**What this is.** A module's checklist and mock data are produced by a background generation, and
while it runs, another cannot be started.

**Why this can happen.** Both empty states ("Generate the checklist, or add one by hand." and
"Generate a batch, or ask for one by chat.") render whatever the job status is, because neither
component is given it. The checklist chat panel is not told about generation either, so it invites
refinement mid-run. The mock-data chat panel does guard this.

**What it costs.** A user is invited to start work that is already running, and on the checklist
side can type a refinement that will land against rows about to change.

**What we should do.** Pass the module's generation status to both empty states and the checklist
chat panel, and show "Generating…" instead. One hour.

### §U7.14 A failed change-set request hides a pending change set the tooltip points to — 🟠 inconsistency

**Where:** `app/(app)/checklist/[moduleId]/module-screen.tsx:69-74`, `:138-141`, `:212` (checklist);
`:96-111`, `:345` (mock data)

**What this is.** While a change set awaits review, Generate is disabled, with a tooltip saying to
apply or discard it first. A "Review N changes" button opens it.

**Why this can happen.** The tooltip depends only on the module's pending change-set id, but the
review button needs the change-set list to have loaded. If that list is loading or has failed,
there is no button and no error, and the tooltip points at something that is not on screen.

**What it costs.** A user is told to deal with pending changes they cannot reach, with no
indication that a request failed.

**What we should do.** Show a skeleton for the button while the list loads, and an inline error
with retry if it fails. One hour.

### §U7.15 The eval sets empty state has no action, and `ListError` sits flush in two cards — 🟡 hygiene

**Where:** `components/eval/eval-set-table.tsx:33-43`; `app/(app)/projects/[id]/project-detail-screen.tsx:162-164`,
`:183`, `:188-190`; `components/members/member-table.tsx:166`; `components/feedback/list-error.tsx:18`

**What this is.** `docs/design.md` says an empty state carries the primary action. List errors sit
inside the list's card.

**Why this can happen.** The eval empty state has no `action`; the only Generate control is in the
tab header. On both the Eval and Members tabs, `ListError` renders inside a `Card className="p-0"`,
and `ListError` has no padding of its own, so the alert touches the card's edges.

**What it costs.** Cosmetic, plus a small extra step for a first-time user.

**What we should do.** Pass the generate dialog trigger as the empty state's action, and give
`ListError` padding when it is inside a zero-padding card. Half an hour.

### §U7.16 A thumbs vote briefly reverts after a remount — 🟡 hygiene

**Where:** `components/output-feedback/feedback-control.tsx:68-82`, `:84-88`; `lib/query/client.ts:18`

> **Narrowed 2026-10-17.** First filed as "saved choices briefly revert after a save or a vote".
> The save half does not reproduce: `answer-style-section.tsx:108-113` clears its draft only after
> the refetch lands, because TanStack awaits the hook's `invalidateQueries` first. Only the vote
> half is confirmed.

**What this is.** A vote's state comes from `myFeedback` on the message or change-set read, which
is cached.

**Why this can happen.** Casting a vote never writes back to that cache. When the control remounts
(navigating back to a conversation, or a chat list re-rendering from cache within its 30-second
stale time), it re-seeds from the stale cached value. The vote shows as un-cast until the refetch
lands.

**What it costs.** A user who just voted sees their vote disappear and may vote again.

**What we should do.** On success, update `myFeedback` in the cached message or change set with
`setQueryData`, or invalidate it. Half an hour.

## U8 The streaming surfaces

### §U8.9 Mock-data change-set rows do not say which record they change — 🟠 inconsistency

**Where:** `components/mock-data/change-set-panel.tsx:145-154`, `:47-53`

**What this is.** A mock-data change set is a list of proposed operations (add, update, delete a
record) that a reviewer ticks and applies.

**Why this can happen.** Each row shows only the operation word and the field values. An update
shows only the changed fields, and a delete shows nothing at all. `operation.recordId` is used
only for an internal orphan check and is never displayed.

**What it costs.** A reviewer approving "delete" cannot tell which record will be deleted. That is
the decision the panel exists for, made blind.

**What we should do.** Show the target record's identity on update and delete rows: its id in
`font-mono`, or a few identifying fields. The checklist panel's handling of its target row is the
model. One to two hours.

### §U8.10 A stray separator in the mock-data change-set card — 🟡 hygiene

**Where:** `components/mock-data/change-set-panel.tsx:181-182`; `components/form/form-error.tsx:10`;
compare `components/checklist/change-set-panel.tsx:247`

**Why this can happen.** A `<Separator />` renders unconditionally above `FormError`, which renders
nothing when there is no error. The result is a dangling rule at the bottom of the card. The
checklist twin has no such separator.

**What we should do.** Remove it, or render it only with the error. Minutes.

### §U8.11 A stored interrupted answer is worded differently from the live one — 🟡 hygiene

**Where:** `components/ask/message-list.tsx:72-78`; `components/ask/interrupted-note.ts:9-10`;
`components/ask/interrupted-note.tsx:4-8`

**What this is.** When a stream drops mid-answer, the partial answer is kept and a note says so.

**Why this can happen.** The live note reads "The connection dropped. What arrived above is kept."
After reload, the stored message reads "This answer was interrupted. What arrived is kept." The
`interrupted-note` comment claims one shared sentence across surfaces, which is untrue for the
stored copy.

**What it costs.** The same event is described two ways on either side of a reload.

**What we should do.** Use `INTERRUPTED_MESSAGE` in `message-list.tsx` too. Minutes.

### §U8.12 The sources panel moves from above the answer to below it on reconcile — 🟡 hygiene

**Where:** `app/(app)/ask/[conversationId]/conversation-screen.tsx:134-141`;
`components/checklist/chat-panel.tsx` (the live turn, around `:270`); `components/ask/message-list.tsx:70-71`

**What this is.** Citations arrive before the first token (`.claude/rules/rag.md`), so the live
turn renders Sources above the Answer. Once the turn is stored, the live copy is replaced by the
stored message.

**Why this can happen.** The stored message renders Answer, then Sources. So the instant a turn
reconciles, its sources jump from above the answer to below it.

**What it costs.** A visible jump at the end of every answer, contradicting the "one visual
language" comment at `conversation-screen.tsx:134-137`.

**What we should do.** Pick one order and use it in both. Minutes, plus a decision on which order.

### §U8.13 "Try again" after a timeout exists on Ask only — 🟡 hygiene

**Where:** `app/(app)/ask/[conversationId]/conversation-screen.tsx:163-172`;
`components/checklist/chat-panel.tsx`, `components/mock-data/chat-panel.tsx` (no `finishReason` in
their turn state); `lib/checklist/stream.ts:32`

**What this is.** All three streaming surfaces share one backend and one terminator contract, and
every terminator carries a `finishReason`.

**Why this can happen.** Ask keeps `finishReason` and offers "Try again" on `timeout`. The two
refinement chats drop it, though their streams carry it, so a timeout there offers nothing.

**What it costs.** The same failure gives a one-click recovery on one screen, and on the other two
the user has to retype.

**What we should do.** Keep `finishReason` in both chats' turn state and render the same retry.
One hour.

### §U8.14 The chat composers say "no permission" while the project is still loading — 🟡 hygiene

**Where:** `app/(app)/checklist/[moduleId]/module-screen.tsx:59-65`, `:112-113`, `:142-143`, `:243`,
`:379`; `components/checklist/chat-panel.tsx:244-245`; `components/mock-data/chat-panel.tsx:207-208`

**What this is.** The module screen decides who may generate or refine from the project's
permissions.

**Why this can happen.** Before the project loads (or if it fails), the permission flags are
`false`. Both composers' placeholders then read "You do not have permission to refine…", and the
Generate tooltips say the same.

**What it costs.** Every user is briefly told they lack a permission they have. If the project
request fails, they are told it permanently, which hides the real error.

**What we should do.** Treat "not yet known" as disabled with no reason given, and show the
project error where there is one. Half an hour.

## U9 Navigation and route gating

### §U9.5 The eval set route answers a missing permission with `NotFound`, not `Forbidden` — 🟡 hygiene

**Where:** `components/eval/eval-set-screen.tsx:60`; `backend/app/core/access.py:99-100`; compare
`app/(app)/settings/feedback/feedback-screen.tsx:53`, `app/(app)/settings/roles/[id]/role-matrix-screen.tsx:64`

**What this is.** `CLAUDE.md` ("`403` vs `404` is a security decision"): a member who can see a
project but lacks a permission gets *forbidden*, because *not found* would contradict the screen
they just came from.

**Why this can happen.** The project has loaded, which proves the user is a member, but the screen
answers a missing `eval.read` with `NotFound`.

**What it costs.** A viewer following a link is told an eval set does not exist when it does.

**What we should do.** Render `Forbidden` there. Minutes.

### §U9.6 Breadcrumbs show raw ids instead of names — 🟠 inconsistency

**Where:** `lib/nav.ts:100-143` (raw ids at `:130`, `:133`, `:139`; the comment at `:95-99`);
`components/layout/app-breadcrumbs.tsx:37-41`

**What this is.** Breadcrumbs are built from the URL in `lib/nav.ts`.

**Why this can happen.** For a detail route, the crumb label is the path segment, which is a UUID.
The comment says "the page overrides once it knows the resource's name", but no override mechanism
exists anywhere.

**What it costs.** Every project, module, conversation and eval set page shows a 36-character UUID
in its breadcrumb.

**What we should do.** Add the override the comment promises, for example a small context a
detail page fills with its resource name, and have the breadcrumb prefer it. Two to three hours.

### §U9.7 Admin screens request data before their admin gate — 🟡 hygiene

**Where:** `app/(app)/settings/users/users-screen.tsx:30` then `:37`; `settings/audit/audit-screen.tsx:42`
then `:48`; `settings/audit/[eventId]/audit-event-screen.tsx:26` then `:31`;
`settings/roles/roles-screen.tsx:21-22` then `:35`; `settings/roles/[id]/role-matrix-screen.tsx:29-31`
then `:50`; `settings/feedback/feedback-screen.tsx:47-48` then `:51`; `hooks/use-roles.ts:17`

**What this is.** Admin screens render `Forbidden` for a non-admin. The backend is the real
control, and it answers `403`.

**Why this can happen.** React hooks must run before any early return, so each screen fires its
data request before checking `isAdmin`. Only `useRoles` takes an `enabled` option, and no screen
passes it.

**What it costs.** A non-admin who types an admin URL sends a request that is refused. No data
leaks, because the backend gates it. It is wasted traffic and a `403` in the console.

**What we should do.** Give each admin hook an `enabled` option and pass `user.isAdmin`. One hour.

## U10 Layout, spacing, typography

### §U10.11 Lists, headings and tables in answers render as plain paragraphs — 🟠 inconsistency

**Where:** `components/ask/answer.tsx:49-79`

**What this is.** Answers are Markdown, rendered with `remark-gfm`, on Ask and in both refinement
chats.

**Why this can happen.** The renderer styles only `pre`, `code` and `a`. With no typography plugin
and no styles for `ul`, `ol`, `li`, headings, tables, blockquotes or rules, Tailwind's reset
strips list markers, heading sizes and table borders. The markup is there but unstyled.

**What it costs.** Numbered steps and bullet lists read as run-on paragraphs, and tables as
jumbled text. This matters more now that the Answer style tab offers a "bullets" format.

**What we should do.** Add component overrides (or scoped styles) for lists, headings, tables and
blockquotes using the existing type scale, and record them in `docs/design.md`. Two hours.

### §U10.12 The feedback summary hand-rolls a third stat tile — 🟠 inconsistency

**Where:** `components/output-feedback/feedback-summary.tsx:37-48`, `:65-79`; `app/(app)/dashboard-screen.tsx:49-76`

**What this is.** A stat tile is a card holding one label and one big number.

**Why this can happen.** There is no shared tile. The dashboard builds two, with `CardContent p-6`,
a `text-sm` label and a `text-3xl` number. The feedback summary builds a third differently, with
`CardHeader`/`CardTitle` and a `text-2xl` number.

**What it costs.** The same idea looks different on two screens, and the next tile will be a fourth
version.

**What we should do.** Extract a `StatTile` into `components/feedback/` or `layout/` and use it in
both places. One hour.

### §U10.13 Identifiers on the eval screens are in the body face — 🟡 hygiene

**Where:** `components/eval/eval-set-screen.tsx:79` (`sourcePath` in the header description);
`components/eval/eval-run-table.tsx:69` (`chatModel`); `components/eval/eval-run-sheet.tsx:59`,
`components/eval/eval-compare.tsx:53` (raw `pairId` fallback)

**What this is.** `docs/design.md:80`, `:90`: paths and identifiers use `font-mono text-sm`. The
eval Path and Source columns already do.

**Why this can happen.** These four places render a path, a model id and a pair id in the body
font.

**What we should do.** Wrap each in `font-mono`. Minutes.

### §U10.14 Off-scale spacing and a `text-[10px]` badge — 🟡 hygiene

**Where:** `components/notifications/notification-bell.tsx:35` (`text-[10px]`, `-top-0.5 -right-0.5`);
`gap-1.5` at `components/form/password-field.tsx:87`, `components/roles/role-badge.tsx:10`,
`components/audit/audit-event-detail.tsx:25`, `components/audit/audit-change-list.tsx:92`; `py-2.5` at
`audit-change-list.tsx:92`; `mb-1.5` at `components/eval/eval-pair-table.tsx:98`; `mt-0.5` at
`eval-pair-table.tsx:64`, `:66`; `py-0.5` at `components/ask/answer.tsx:60`

**What this is.** `docs/design.md:121`: spacing uses steps 1, 2, 3, 4, 6, 8 and 12 only. Type comes
from the seven-row scale.

**What we should do.** Snap each to the nearest step, or document an exception for the bell's
count badge. Half an hour.

## U11 Icons and accessibility

### §U11.6 Excluded pairs and pressed thumbs are signalled by colour alone — 🟡 hygiene

**Where:** `components/eval/eval-pair-table.tsx:52`; `components/output-feedback/feedback-control.tsx:124-125`, `:138-139`

**What this is.** A state shown only by colour cannot be seen by colour-blind users, or in a
greyscale screenshot.

**Why this can happen.** An excluded pair is shown only by dimming its row's text. A pressed thumb
differs from an unpressed one only by colour, with the same icon. Screen readers are covered,
because the thumbs carry `aria-pressed` and the exclude switch is a labelled control. The gap is
for sighted users.

**What we should do.** Fill the pressed thumb icon, and add an "Excluded" badge on the row.
Half an hour.

### §U11.7 Eval run rows are clickable without a visible or accessible control — 🟡 hygiene

**Where:** `components/eval/eval-run-table.tsx:48-56`; compare `components/eval/eval-pair-table.tsx:57-61`

**Why this can happen.** The whole run row has `onClick`, `tabIndex={0}` and an Enter handler, with
no button, link, role or accessible name, and Space does nothing. The only cue is the pointer
cursor. The pair table beside it uses a real `<button aria-expanded>`.

**What it costs.** Screen-reader users hear a row of cells with no hint it opens anything.
Keyboard users get half the expected keys.

**What we should do.** Put a real button (for example on the run's name or an "Open" control) in
the row, as the pair table does. Half an hour.

### §U11.8 The compare selects and the date filters lose their visible labels — 🟡 hygiene

**Where:** `components/eval/eval-set-screen.tsx:151-176`; `components/output-feedback/feedback-filters.tsx:127-152`;
`components/audit/audit-filters.tsx:138-161`; `.claude/rules/forms.md:66-67`

**Why this can happen.** These controls carry only an `aria-label`. The compare selects show "Base
run" or "Head run" as a placeholder, and once a run is chosen that text is replaced by the run's
name, so nothing on screen says which side is which. The date inputs have no visible label at all.
The feedback screen's feature, vote and reason selects are in the same state.

**What we should do.** Give each a visible `FieldLabel` with `htmlFor`, which `forms.md` requires.
One hour.

## U12 Documentation drift

### §U12.6 `navigation.md` §4 and §6 are stale — 📄 doc

**Where:** `.claude/rules/navigation.md:48-57`, `:83-99`; `lib/nav-child.ts:14`; `docs/PRD.md:34`

§4 still says "Phase 1 has exactly one axis of authority — `is_admin`… Do not invent a permission
system" and that "Phase 2 will add per-project access". Phase 2.1's per-project roles shipped long
ago, along with `lib/can.ts`. `lib/nav-child.ts:14` repeats the sentence. §6's "shape AskRepo is
heading for" route list omits `/projects/[id]/eval/[setId]`, `/settings/feedback`, `/notifications`,
`/profile` and the `/settings/notifications` redirect, all of which exist. **Fix:** rewrite §4
around `lib/can.ts`, list the real routes in §6 in the present tense, and fix the comment.

### §U12.7 `frontend/README.md`'s layout is stale — 📄 doc

**Where:** `frontend/README.md:6-26`, `:98-137`

The `(auth)/` line lists only `/login` and `/change-password` (the tree also has
`forgot-password` and `reset-password`). Settings omits `/settings/feedback`. `components/` omits
`audit/`, `change-sets/`, `live/` and `output-feedback/`. `lib/` omits `checklist/`, `live/`,
`mock-data/` and eight files. `app/api/` omits `auth/password-policy` and `auth/password-reset`.
The prose never mentions the feedback screen or the vote control. **Fix:** regenerate the layout
block from the tree.

### §U12.8 `design.md` lacks the feedback control, the drawer widths, and two column rules — 📄 doc

**Where:** `docs/design.md:148-152` (inventory: `sheet` with no widths), `:178-179` (column rules),
`:208` (the Feedback section, which covers loading and mutations only);
`components/output-feedback/feedback-control.tsx`; sheet widths at
`components/eval/eval-run-sheet.tsx:35`, `components/checklist/refinement-drawer.tsx:180-190`,
`components/ask/conversation-rail.tsx:425`; `components/output-feedback/feedback-table.tsx:73`, `:76`

`design.md` never describes the thumbs control, and three sheets use three different widths with
no rule. The two column rules are SUSPECT: the original row did not name them. The likely
candidates are a `font-mono` identifier column (`feedback-table.tsx:76`,
`feedback-summary.tsx:117`) and a wrapped free-text column (`max-w-xs whitespace-pre-wrap`,
`feedback-table.tsx:73`). **Fix:** add the control, a drawer-width rule, and those column rules.

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

## See also

- [`audit-finding-solved-logs.md`](audit-finding-solved-logs.md) — the findings that have been fixed, verbatim
- [`audit-findings.md`](audit-findings.md) — the backend/architecture sweep (`§1`–`§9`)
- [`design.md`](design.md) — the design reference these findings are measured against
- [`../.claude/rules/design-system.md`](../.claude/rules/design-system.md),
  [`../.claude/rules/forms.md`](../.claude/rules/forms.md),
  [`../.claude/rules/navigation.md`](../.claude/rules/navigation.md) — the enforceable rules
- [`../.claude/commands/audit-ui.md`](../.claude/commands/audit-ui.md) — how this sweep is run
- [`../.claude/rules/audit-findings.md`](../.claude/rules/audit-findings.md) — how a finding is written
